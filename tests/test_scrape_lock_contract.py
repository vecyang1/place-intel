"""Contract: concurrent scrapes of one place are serialised, and a timed-out
scraper takes its whole browser tree with it.

Both guard a defect measured in production on 2026-08-31, not a hypothetical:

  * Sessions 128 and 129 scraped place `0x314a443465a12319:0` with a 2m20s
    overlap. Run B's refresh wipe deleted the `places` row run A's in-flight
    review INSERTs referenced, the vendor logged
    `Error during review processing: FOREIGN KEY constraint failed`, and the
    run reported `new: 300` into a table holding 91 rows.
  * Four abandoned Chrome trees (PPid 1, 48 processes, 4718 MB RSS) survived
    on a 12 GB box because `subprocess.run(timeout=)` SIGKILLs only the direct
    child, and the browser is two levels below it.

The tests use real processes and real flock rather than mocks: the property
under test is cross-PROCESS, and the production collision was between a root
CLI run and the web service. An in-process mock cannot observe either.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401  — pins DATA_DIR before placeintel imports

from placeintel import reviews, scrape_lock  # noqa: E402


def _hold_place_lock(key: str, hold_s: float, started, ready) -> None:
    """Child process: take the lock, signal, hold it, release."""
    with scrape_lock.place_scrape_lock(key):
        started.value = time.monotonic()
        ready.set()
        time.sleep(hold_s)


class PlaceScrapeLockTest(unittest.TestCase):
    def test_second_process_waits_for_the_first(self):
        """Two processes cannot hold one place's lock at the same time."""
        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        started = ctx.Value("d", 0.0)
        hold_s = 2.0
        child = ctx.Process(
            target=_hold_place_lock, args=("place-A", hold_s, started, ready)
        )
        child.start()
        try:
            self.assertTrue(ready.wait(timeout=30), "child never acquired the lock")
            t0 = time.monotonic()
            with scrape_lock.place_scrape_lock("place-A", timeout_s=30):
                waited = time.monotonic() - t0
            # Must have blocked for most of the hold, not sailed through.
            self.assertGreater(
                waited, hold_s * 0.5,
                f"parent acquired the same place lock after only {waited:.2f}s — "
                "two scrapes of one place would run concurrently",
            )
        finally:
            child.join(timeout=30)

    def test_different_places_do_not_block_each_other(self):
        """The lock must not serialise unrelated places — that would be a
        throughput bug wearing a correctness bug's clothes."""
        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        started = ctx.Value("d", 0.0)
        child = ctx.Process(target=_hold_place_lock, args=("place-B", 3.0, started, ready))
        child.start()
        try:
            self.assertTrue(ready.wait(timeout=30))
            t0 = time.monotonic()
            with scrape_lock.place_scrape_lock("place-C", timeout_s=30):
                waited = time.monotonic() - t0
            self.assertLess(waited, 1.0, f"unrelated place blocked for {waited:.2f}s")
        finally:
            child.join(timeout=30)

    def test_timeout_raises_rather_than_proceeding_unlocked(self):
        """A waiter that gives up must raise. Proceeding without the lock is
        exactly the double-scrape the lock exists to prevent."""
        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        started = ctx.Value("d", 0.0)
        child = ctx.Process(target=_hold_place_lock, args=("place-D", 5.0, started, ready))
        child.start()
        try:
            self.assertTrue(ready.wait(timeout=30))
            with self.assertRaises(scrape_lock.ScrapeLockTimeout):
                with scrape_lock.place_scrape_lock("place-D", timeout_s=1):
                    self.fail("acquired a lock that was held")
        finally:
            child.join(timeout=30)


class ScrapeSlotTest(unittest.TestCase):
    def test_slot_count_is_bounded_and_configurable(self):
        self.assertEqual(
            scrape_lock.max_concurrent_scrapes(),
            scrape_lock.DEFAULT_MAX_CONCURRENT_SCRAPES,
        )
        with unittest.mock.patch.dict(
            os.environ, {"PLACEINTEL_MAX_CONCURRENT_SCRAPES": "5"}
        ):
            self.assertEqual(scrape_lock.max_concurrent_scrapes(), 5)
        # A garbage value must fall back, not crash the scrape path.
        with unittest.mock.patch.dict(
            os.environ, {"PLACEINTEL_MAX_CONCURRENT_SCRAPES": "not-a-number"}
        ):
            self.assertEqual(
                scrape_lock.max_concurrent_scrapes(),
                scrape_lock.DEFAULT_MAX_CONCURRENT_SCRAPES,
            )
        # Zero would mean "no scrapes ever" — clamp rather than deadlock.
        with unittest.mock.patch.dict(
            os.environ, {"PLACEINTEL_MAX_CONCURRENT_SCRAPES": "0"}
        ):
            self.assertEqual(scrape_lock.max_concurrent_scrapes(), 1)

    def test_slots_are_exhaustible(self):
        """With N slots, the N+1th caller must block rather than launch a browser."""
        with unittest.mock.patch.dict(
            os.environ, {"PLACEINTEL_MAX_CONCURRENT_SCRAPES": "1"}
        ):
            with scrape_lock.scrape_slot(timeout_s=5):
                # Same process, but flock is per-fd: a second acquisition opens
                # its own descriptor and must fail to lock.
                with self.assertRaises(scrape_lock.ScrapeLockTimeout):
                    with scrape_lock.scrape_slot(timeout_s=1):
                        self.fail("took a second slot when only one exists")


class ProcessGroupKillTest(unittest.TestCase):
    """The browser is a GRANDchild. Killing the child is not enough."""

    def _spawn_with_grandchild(self, timeout_s: float):
        script = (
            "import subprocess,sys,time;"
            "g=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
            "print(g.pid, flush=True);"
            "time.sleep(120)"
        )
        original = reviews.SCRAPER_TIMEOUT_S
        reviews.SCRAPER_TIMEOUT_S = timeout_s
        try:
            return reviews._run_in_own_process_group(
                [sys.executable, "-c", script], cwd=Path("."), env=dict(os.environ)
            )
        finally:
            reviews.SCRAPER_TIMEOUT_S = original

    @staticmethod
    def _alive(pid: int) -> bool:
        return subprocess.run(
            ["ps", "-p", str(pid)], capture_output=True
        ).returncode == 0

    def test_timeout_reaps_the_grandchild(self):
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            self._spawn_with_grandchild(timeout_s=2)
        grandchild = int((caught.exception.output or "").strip().split()[0])
        # Give the SIGTERM/SIGKILL sequence a moment to land.
        deadline = time.monotonic() + 20
        while self._alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(
            self._alive(grandchild),
            f"grandchild {grandchild} survived the timeout — this is how 4.7 GB "
            "of orphaned Chrome accumulated on prod",
        )

    def test_successful_run_returns_completed_process(self):
        """The happy path must still behave like subprocess.run."""
        proc = reviews._run_in_own_process_group(
            [sys.executable, "-c", "print('hello')"],
            cwd=Path("."), env=dict(os.environ),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "hello")

    def test_nonzero_exit_is_reported_not_raised(self):
        proc = reviews._run_in_own_process_group(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            cwd=Path("."), env=dict(os.environ),
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn("boom", proc.stderr)


if __name__ == "__main__":
    unittest.main()
