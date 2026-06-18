import tempfile
import unittest
from pathlib import Path

from placeintel import cache, photos


class PhotoContractTest(unittest.TestCase):
    def test_photo_resolver_returns_safe_bounded_url_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            cache.upsert_place(
                conn,
                cache.Place(
                    place_id="place-1",
                    name="Photo Test Cafe",
                    maps_url="https://maps.google.com/?cid=123",
                    raw={
                        "thumbnail": "https://maps.example/place-thumb.jpg",
                        "photos": [
                            {"url": "https://maps.example/place-photo.jpg"},
                            {"link": "https://www.google.com/maps/place/Photo+Test+Cafe"},
                        ],
                    },
                ),
            )
            cache.upsert_place(
                conn,
                cache.Place(
                    place_id="place-2",
                    name="Only Maps Link",
                    maps_url="https://www.google.com/maps/place/Only+Maps+Link",
                    raw={"url": "https://www.google.com/maps/place/Only+Maps+Link"},
                ),
            )
            cache.upsert_reviews(
                conn,
                [
                    cache.Review(
                        review_id="review-1",
                        place_id="place-1",
                        author="Grace",
                        rating=5,
                        review_date="2026-06-01",
                        images=[
                            "javascript:alert(1)",
                            "https://lh3.googleusercontent.com/review-photo=w400",
                            "https://lh3.googleusercontent.com/review-photo=w400",
                        ],
                        source="scraper-pro",
                    ),
                    cache.Review(
                        review_id="review-2",
                        place_id="place-1",
                        author="Minh",
                        rating=4,
                        review_date="2026-06-02",
                        images=[{"thumbnail": "https://serp.example/thumb.jpg", "image": "https://serp.example/full.jpg"}],
                        source="serpapi",
                    ),
                ],
            )

            detail = photos.resolve_place_photos(conn, "place-1")
            thumbnail = photos.resolve_place_photos(conn, "place-1", list_mode=True)
            maps_only = photos.resolve_place_photos(conn, "place-2", list_mode=True)
            conn.close()

        self.assertLessEqual(len(detail), photos.PHOTO_DETAIL_LIMIT)
        self.assertIsInstance(thumbnail, dict)
        self.assertEqual(thumbnail["url"], "https://lh3.googleusercontent.com/review-photo=w400")
        self.assertEqual(thumbnail["kind"], "review")
        self.assertEqual(thumbnail["source"], "scraper-pro")
        self.assertEqual(thumbnail["review_id"], "review-1")
        self.assertEqual(thumbnail["author"], "Grace")
        self.assertEqual(thumbnail["rating"], 5)
        self.assertEqual(thumbnail["date"], "2026-06-01")
        urls = [item["url"] for item in detail]
        self.assertEqual(urls.count("https://lh3.googleusercontent.com/review-photo=w400"), 1)
        self.assertIn("https://serp.example/full.jpg", urls)
        self.assertIn("https://maps.example/place-thumb.jpg", urls)
        self.assertNotIn("https://www.google.com/maps/place/Photo+Test+Cafe", urls)
        self.assertIsNone(maps_only)
        self.assertTrue(all(url.startswith("https://") for url in urls))
        for item in detail:
            self.assertIn("thumb_url", item)
            self.assertIn("place_id", item)
            self.assertNotIn("raw_json", item)


if __name__ == "__main__":
    unittest.main()
