import os
import unittest
from unittest.mock import patch, MagicMock

from placeintel import proxy, reviews
from placeintel.cache import Place, Review
from placeintel.reviews import ScraperProError


class ProxyTest(unittest.TestCase):
    def test_mask_proxy(self):
        self.assertEqual(proxy.mask_proxy(None), "None")
        masked = proxy.mask_proxy("http://user12345:secret_pwd@proxy.example.com:823")
        self.assertIn("user***", masked)
        self.assertNotIn("secret_pwd", masked)
        self.assertIn("proxy.example.com:823", masked)

    def test_resolve_residential_proxy_from_env(self):
        with patch.dict(os.environ, {"DATAIMPULSE_PROXY_URL": "http://user:pwd@proxy.example.com:823"}):
            url = proxy.resolve_residential_proxy(geo="vn")
            self.assertIn("__cr-vn", url)
            self.assertIn("proxy.example.com:823", url)

    def test_reviews_fallback_to_residential_proxy_on_direct_failure(self):
        place = Place(
            place_id="ChIJtest_proxy",
            name="Test Cafe",
            maps_url="https://www.google.com/maps/place/Test+Cafe/?q=place_id:ChIJtest_proxy",
            review_count=50,
        )

        mock_reviews = [
            Review(
                review_id="gsp:rev1",
                place_id="ChIJtest_proxy",
                author="Alice",
                rating=5.0,
                text="Great coffee!",
                lang="en",
                review_date="2026-08-30",
                owner_response=None,
                images=[],
                source="scraper-pro",
                raw={},
            )
        ]

        calls = []

        def mock_fetch(p, max_revs, proxy_url=None, refresh=False):
            calls.append(proxy_url)
            if proxy_url is None:
                raise ScraperProError("direct scrape blocked")
            return mock_reviews

        with patch("placeintel.reviews._primary_blockers", return_value=[]), \
             patch("placeintel.reviews._fetch_via_scraper_pro", side_effect=mock_fetch), \
             patch("placeintel.proxy.resolve_residential_proxy", return_value="http://user:pass@proxy.example.com:823"):
            res = reviews.fetch_reviews(place, max_reviews=10)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0].author, "Alice")
            self.assertEqual(calls, [None, "http://user:pass@proxy.example.com:823"])


if __name__ == "__main__":
    unittest.main()
