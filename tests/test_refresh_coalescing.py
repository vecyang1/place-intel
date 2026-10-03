"""Contract: a refresh that queued behind another refresh reuses its result.

Measured on prod 2026-08-31: two `refresh=True` calls for one place, three
seconds apart. The place lock correctly stopped them overlapping — session 130
ran alone and completed with 300 reviews — and then caller B took the lock,
wiped those 300 rows, and started a second 15-minute scrape for the same data.

Correct, and wasteful. B asked for fresh data *while* A was fetching it, so A's
result already answers B. The boundary matters and is asserted below: a scrape
that finished BEFORE B asked does not count, or `refresh=True` quietly decays
into "recent enough is fine".

The fixture is a real SQLite file on the vendor's actual schema, including the
`FOREIGN KEY (place_id) REFERENCES places(place_id)` that produced the original
incident — a fake that dropped it could not express the failure.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401

from placeintel import config, reviews  # noqa: E402
from placeintel.cache import Place  # noqa: E402

VENDOR_SCHEMA = """
CREATE TABLE places (
    place_id TEXT PRIMARY KEY, place_name TEXT,
    original_url TEXT, resolved_url TEXT, lat REAL, lng REAL
);
CREATE TABLE place_aliases (original_url TEXT, canonical_id TEXT);
CREATE TABLE reviews (
    review_id TEXT PRIMARY KEY, place_id TEXT NOT NULL, review_text TEXT,
    rating REAL, author TEXT, review_date TEXT, is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
);
CREATE TABLE scrape_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'scrape', started_at TEXT NOT NULL,
    completed_at TEXT, status TEXT NOT NULL DEFAULT 'running',
    reviews_found INTEGER DEFAULT 0, reviews_new INTEGER DEFAULT 0,
    reviews_updated INTEGER DEFAULT 0, sort_by TEXT, error_message TEXT,
    FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
);
"""

INTERNAL_ID = "0x314a443465a12319:0"
MAPS_URL = "https://www.google.com/maps/place/Dung+Yen/@20.7,107.0,17z/data=x"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class RefreshCoalescingTest(unittest.TestCase):
    def setUp(self):
        self.db = config.DATA_DIR / "scraper_pro_reviews.db"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        if self.db.exists():
            self.db.unlink()
        conn = sqlite3.connect(self.db)
        conn.executescript(VENDOR_SCHEMA)
        conn.execute(
            "INSERT INTO places VALUES (?,?,?,?,?,?)",
            (INTERNAL_ID, "Dung Yen", MAPS_URL, MAPS_URL, 20.7, 107.0),
        )
        for i in range(5):
            conn.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,0)",
                (f"rev{i}", INTERNAL_ID, f"text {i}", 5.0, f"author {i}", "2026-08-01"),
            )
        conn.commit()
        self.conn = conn
        self.addCleanup(conn.close)

    def _place(self) -> Place:
        return Place(place_id="ChIJtest", name="Dung Yen", maps_url=MAPS_URL,
                     review_count=1395)

    def _add_session(self, completed_at: datetime | None, status: str = "completed"):
        self.conn.execute(
            "INSERT INTO scrape_sessions (place_id, started_at, completed_at, status) "
            "VALUES (?,?,?,?)",
            (INTERNAL_ID, _iso(datetime.now(timezone.utc) - timedelta(minutes=20)),
             _iso(completed_at) if completed_at else None, status),
        )
        self.conn.commit()

    # -- _scrape_completed_since ------------------------------------------

    def test_scrape_finished_after_we_asked_counts(self):
        asked = time.time()
        self._add_session(datetime.now(timezone.utc) + timedelta(seconds=5))
        self.assertTrue(
            reviews._scrape_completed_since(self._place(), MAPS_URL, asked)
        )

    def test_scrape_finished_before_we_asked_does_not_count(self):
        self._add_session(datetime.now(timezone.utc) - timedelta(minutes=5))
        asked = time.time()
        self.assertFalse(
            reviews._scrape_completed_since(self._place(), MAPS_URL, asked),
            "an older scrape satisfied a refresh — refresh would mean "
            "'recent enough', which is not what the caller asked for",
        )

    def test_still_running_session_does_not_count(self):
        asked = time.time()
        self._add_session(None, status="running")
        self.assertFalse(
            reviews._scrape_completed_since(self._place(), MAPS_URL, asked),
            "a killed/in-flight session was treated as a finished one",
        )

    def test_empty_session_does_not_count(self):
        asked = time.time()
        self._add_session(datetime.now(timezone.utc) + timedelta(seconds=5), status="empty")
        self.assertFalse(
            reviews._scrape_completed_since(self._place(), MAPS_URL, asked)
        )

    def test_no_sessions_at_all_does_not_count(self):
        self.assertFalse(
            reviews._scrape_completed_since(self._place(), MAPS_URL, time.time())
        )

    # -- the wiring -------------------------------------------------------

    def test_refresh_reuses_a_scrape_that_landed_while_we_queued(self):
        """The whole point: no second Chrome, and the rows survive."""
        self._add_session(datetime.now(timezone.utc) + timedelta(seconds=5))

        launched = []

        def trap(*a, **kw):
            launched.append(a)
            raise AssertionError("launched Chrome for data another run just fetched")

        with mock.patch.object(reviews, "_run_scraper_pro", trap):
            got = reviews._fetch_via_scraper_pro(self._place(), 300, refresh=True)

        self.assertEqual(launched, [])
        self.assertEqual(len(got), 5)
        surviving = self.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        self.assertEqual(surviving, 5, "the reused rows were wiped anyway")

    def test_refresh_with_no_recent_scrape_still_wipes_and_scrapes(self):
        """Coalescing must not turn a genuine refresh into a cache read."""
        self._add_session(datetime.now(timezone.utc) - timedelta(minutes=5))
        calls = []

        def fake_run(place, max_reviews, target_url=None, proxy_url=None):
            calls.append(place.place_id)
            # Model what the real scraper does after a wipe: `upsert_place`
            # re-registers the place row BEFORE inserting reviews. A fake that
            # only inserts reviews leaves them unmappable and fails for a reason
            # the production path never hits.
            c = sqlite3.connect(self.db)
            c.execute(
                "INSERT OR REPLACE INTO places VALUES (?,?,?,?,?,?)",
                (INTERNAL_ID, "Dung Yen", MAPS_URL, MAPS_URL, 20.7, 107.0),
            )
            c.execute(
                "INSERT INTO reviews VALUES ('new1',?, 'fresh', 5.0, 'a', '2026-08-31', 0)",
                (INTERNAL_ID,),
            )
            c.commit(); c.close()

        with mock.patch.object(reviews, "_run_scraper_pro", fake_run):
            got = reviews._fetch_via_scraper_pro(self._place(), 300, refresh=True)

        self.assertEqual(calls, ["ChIJtest"], "a real refresh skipped the scrape")
        self.assertEqual(len(got), 1, "the pre-existing rows were not wiped")


if __name__ == "__main__":
    unittest.main()
