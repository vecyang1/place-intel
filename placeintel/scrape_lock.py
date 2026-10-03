"""Cross-process locks that serialise Google Maps scrapes.

Two distinct problems, two locks. Both are `fcntl.flock` on files under DATA_DIR
rather than in-process primitives, because the collision we actually measured
crossed process boundaries: on 2026-08-31 a root CLI scrape and the
`placeintel.service` web worker scraped the same place at the same time. A
`threading.Lock` would not have seen either one.

PLACE LOCK — one scrape per place at a time.
  Two concurrent scrapes of one place share the vendor's SQLite file. The second
  one re-registers the place (`upsert_place`) and `_clear_scraper_db_entry`
  hard-deletes the `places` row the first one's in-flight review INSERTs still
  reference. Measured result: the vendor logged `new: 300` and the table held
  91 rows, because `batch_stats` counts *attempted* upserts and the
  `FOREIGN KEY constraint failed` was swallowed by a bare `except Exception`.

SLOT LOCK — a ceiling on concurrent browsers.
  One scraper subprocess is ~13 OS processes and ~0.8-1.2 GB RSS (measured:
  11 chrome + uc_driver + python). `ThreadPoolExecutor(max_workers=4)` bounds one
  job's fan-out, but nothing bounded the number of jobs, so four abandoned
  browser trees reached 4.7 GB on a 12 GB box with swap at 74%.

Both are advisory: every scraper path in this codebase goes through
:func:`place_scrape_lock`, so the lock is honoured by construction. A caller that
skips it is not blocked, it is a bug.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

logger = logging.getLogger(__name__)

# A scrape can legitimately run for SCRAPER_TIMEOUT_S (30 min). A waiter must
# outlast a full run in front of it, or it gives up on a lock that was about to
# be released and starts the very double-scrape the lock exists to prevent.
PLACE_LOCK_TIMEOUT_S = 35 * 60

# Concurrent browser trees, across every process on the machine.
#
# This is a ceiling, not a throttle: `pipeline._deep_dive` already fans out to
# `ThreadPoolExecutor(max_workers=min(len(places), 4))`, and the bug was that
# nothing bounded the number of JOBS doing that at once — `server.py` spawns an
# unbounded thread per HTTP request. Two simultaneous scouts meant 8 browser
# trees. So the intent here is to keep the existing per-job parallelism while
# making the total finite.
#
# The arithmetic, from measurements on the prod box (6 vCPU, 12 GB, ~5.2-6.5 GB
# available): one tree is ~13 processes at 806 MB-1.2 GB RSS.
#   3 trees -> 2.4-3.6 GB, comfortably under the unit's MemoryHigh=5G
#   4 trees -> 3.2-4.8 GB, which reaches MemoryHigh with the app and page cache
# 3 keeps nearly all the throughput with headroom that is actually there.
#
# Raise it with PLACEINTEL_MAX_CONCURRENT_SCRAPES on a bigger box. Note that for
# a SINGLE place this changes nothing: one review pane scrolls sequentially, so
# a 1,395-review shop is bounded by per-scrape speed, not by this number.
DEFAULT_MAX_CONCURRENT_SCRAPES = 3
SLOT_LOCK_TIMEOUT_S = 35 * 60

_POLL_INTERVAL_S = 0.5


class ScrapeLockTimeout(RuntimeError):
    """Waited past the timeout for a scrape lock; the holder is still running."""


def max_concurrent_scrapes() -> int:
    """Browser-tree ceiling, overridable for boxes with a different budget."""
    raw = os.getenv("PLACEINTEL_MAX_CONCURRENT_SCRAPES")
    if raw is None:
        return DEFAULT_MAX_CONCURRENT_SCRAPES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "PLACEINTEL_MAX_CONCURRENT_SCRAPES=%r is not an integer — using %d",
            raw, DEFAULT_MAX_CONCURRENT_SCRAPES,
        )
        return DEFAULT_MAX_CONCURRENT_SCRAPES
    if value < 1:
        logger.warning(
            "PLACEINTEL_MAX_CONCURRENT_SCRAPES=%d is below 1 — using 1", value
        )
        return 1
    return value


def _lock_dir() -> Path:
    path = config.DATA_DIR / "locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _place_lock_path(place_key: str) -> Path:
    # place_id can contain characters that are not filename-safe, and the
    # vendor's own ids carry ':'. Hash rather than sanitise: a sanitiser that
    # maps two distinct ids to one filename would silently serialise unrelated
    # places, which looks like a performance bug and never like a lock bug.
    digest = hashlib.sha256(place_key.encode("utf-8")).hexdigest()[:32]
    return _lock_dir() / f"place-{digest}.lock"


@contextmanager
def _flock(path: Path, timeout_s: float, what: str) -> Iterator[None]:
    """Hold an exclusive flock on *path*, or raise ScrapeLockTimeout."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    waited_from = time.monotonic()
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise ScrapeLockTimeout(
                        f"waited {timeout_s:.0f}s for {what} ({path.name}); "
                        "another scrape still holds it"
                    ) from exc
                time.sleep(_POLL_INTERVAL_S)
        waited = time.monotonic() - waited_from
        if waited > _POLL_INTERVAL_S:
            logger.info("waited %.1fs for %s", waited, what)
        # Recorded for humans reading a wedged box; never read back by code.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()} at={time.time():.0f} {what}\n".encode())
        except OSError:
            pass
        yield
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


@contextmanager
def place_scrape_lock(place_key: str, timeout_s: float = PLACE_LOCK_TIMEOUT_S) -> Iterator[None]:
    """Serialise scrapes of one place across every process on this machine."""
    with _flock(_place_lock_path(place_key), timeout_s, f"place scrape lock {place_key!r}"):
        yield


@contextmanager
def scrape_slot(timeout_s: float = SLOT_LOCK_TIMEOUT_S) -> Iterator[int]:
    """Hold one of N browser slots; yields the slot index actually taken.

    Polls the slots rather than blocking on one, so a caller is not stuck behind
    a specific long-running scrape when another slot frees first.
    """
    slots = max_concurrent_scrapes()
    paths = [_lock_dir() / f"slot-{i}.lock" for i in range(slots)]
    deadline = time.monotonic() + timeout_s
    while True:
        for index, path in enumerate(paths):
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(fd)
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                continue
            try:
                try:
                    os.ftruncate(fd, 0)
                    os.write(fd, f"pid={os.getpid()} at={time.time():.0f}\n".encode())
                except OSError:
                    pass
                logger.debug("took scrape slot %d/%d", index + 1, slots)
                yield index
                return
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(fd)
        if time.monotonic() >= deadline:
            raise ScrapeLockTimeout(
                f"waited {timeout_s:.0f}s for one of {slots} scrape slots"
            )
        time.sleep(_POLL_INTERVAL_S)
