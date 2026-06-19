"""SerpAPI partial-scrape salvage: a later page timing out must not discard the
reviews already collected (the v0.4.49 'report jumps back to nothing' fix). Only a
first-page failure — where nothing was collected — should propagate."""
import unittest
from unittest import mock

from placeintel import reviews
from placeintel.cache import Place


def _place() -> Place:
    return Place(place_id="ChIJtest", name="Test Place",
                 maps_url="https://maps.google.com/?cid=1", raw={"data_id": "0x:0x"})


def _page1_payload(n: int = 20) -> dict:
    return {"reviews": [{"review_id": f"r{i}"} for i in range(n)],
            "serpapi_pagination": {"next_page_token": "tok2"}}


class SerpApiSalvageTest(unittest.TestCase):
    def setUp(self) -> None:
        # Pass items straight through so the test exercises pagination control flow,
        # not _serp_item_to_review's field mapping (covered elsewhere).
        self._patches = [
            mock.patch.object(reviews.config, "serpapi_api_key", return_value="k"),
            mock.patch.object(reviews, "_serp_item_to_review", side_effect=lambda item, pid: item),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def test_later_page_timeout_salvages_earlier_reviews(self):
        def fake_get(params, page):
            if page == 1:
                return _page1_payload(20)
            raise RuntimeError("SerpAPI request failed on page 2: Read timed out")

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            got = reviews._fetch_via_serpapi(_place(), max_reviews=300)

        self.assertEqual(len(got), 20)  # page-1 reviews kept, not lost to the page-2 raise

    def test_first_page_failure_still_raises(self):
        def fake_get(params, page):
            raise RuntimeError("SerpAPI request failed on page 1: Read timed out")

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            with self.assertRaises(RuntimeError):
                reviews._fetch_via_serpapi(_place(), max_reviews=300)


if __name__ == "__main__":
    unittest.main()
