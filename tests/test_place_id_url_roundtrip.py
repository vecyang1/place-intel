"""Contract: a `?q=place_id:X` Maps URL carries an identity, and the URLs this
codebase generates can be parsed back by the codebase that generated them.

Measured 2026-08-31: `placeintel shop 'https://www.google.com/maps/place/?q=place_id:ChIJ…'`
for a place already holding 314 cached reviews logged

    gosom returned 0 entries → 0 places
    [done] 没找到匹配「place_id:ChIJGSOhZTRESjERzhfaGlo7ql0」的店铺

because `parse_maps_url` skipped `q=place_id:` entirely, leaving the URL with no
identity, so the pipeline ran a Maps *text search* for the literal string
"place_id:ChIJ…" — which matches nothing, ever.

The round-trip test is the one that would have caught it early: two functions in
this package build exactly this URL shape, so an identity the app writes must be
an identity the app can read.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401

from placeintel import discover, planner, reviews  # noqa: E402
from placeintel.cache import Place  # noqa: E402

PID = "ChIJGSOhZTRESjERzhfaGlo7ql0"


class PlaceIdQueryParsingTest(unittest.TestCase):
    def test_bare_place_id_url_yields_an_identity(self):
        info = planner.parse_maps_url(
            f"https://www.google.com/maps/place/?q=place_id:{PID}"
        )
        self.assertIsNotNone(info)
        self.assertEqual(info.get("place_id"), PID)

    def test_named_place_id_url_yields_both_name_and_identity(self):
        info = planner.parse_maps_url(
            f"https://www.google.com/maps/place/Dung+Yen/?q=place_id:{PID}"
        )
        self.assertEqual(info.get("name"), "Dung Yen")
        self.assertEqual(info.get("place_id"), PID)

    def test_place_id_is_not_mistaken_for_a_name(self):
        """The old behaviour skipped the value for naming — that part was right
        and must stay right, or the shop is searched for by a literal id."""
        info = planner.parse_maps_url(
            f"https://www.google.com/maps/place/?q=place_id:{PID}"
        )
        self.assertNotIn("name", info)

    def test_ordinary_query_url_is_unaffected(self):
        info = planner.parse_maps_url(
            "https://www.google.com/maps?q=Lazy+Gecko+Cafe,+Hoi+An"
        )
        self.assertEqual(info.get("name"), "Lazy Gecko Cafe")
        self.assertIsNone(info.get("place_id"))

    def test_malformed_place_id_query_yields_no_identity(self):
        # "place_id:" with nothing after it is not an identity; returning "" here
        # would look like a hit and dead-end the lookup on an empty key.
        info = planner.parse_maps_url("https://www.google.com/maps/place/?q=place_id:")
        self.assertIsNone(info.get("place_id"))


class GeneratedUrlsRoundTripTest(unittest.TestCase):
    """Whatever this package emits, this package must be able to read back."""

    def test_discover_serpapi_maps_url_round_trips(self):
        url = discover._serpapi_maps_url("Dũng Yến Motorbike shop", PID)
        info = planner.parse_maps_url(url)
        self.assertIsNotNone(info, f"could not parse a URL we generated: {url}")
        self.assertEqual(
            info.get("place_id"), PID,
            f"generated URL lost its identity on the way back in: {url}",
        )

    def test_reviews_scraper_target_url_round_trips(self):
        place = Place(
            place_id=PID,
            name="Dũng Yến Motorbike shop",
            maps_url="https://maps.app.goo.gl/shortlink",  # no name, no hex pair
            review_count=1395,
        )
        url = reviews._scraper_target_url(place)
        info = planner.parse_maps_url(url)
        self.assertIsNotNone(info, f"could not parse a URL we generated: {url}")
        self.assertEqual(
            info.get("place_id"), PID,
            f"generated URL lost its identity on the way back in: {url}",
        )


if __name__ == "__main__":
    unittest.main()
