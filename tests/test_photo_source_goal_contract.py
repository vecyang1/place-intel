import re
import tempfile
import unittest
from pathlib import Path

from placeintel import cache, photos


ROOT = Path(__file__).resolve().parents[1]


class PhotoSourceGoalContractTest(unittest.TestCase):
    def test_detail_photos_return_more_url_only_items_without_binary_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            raw_photos = [{"image": f"https://maps.example/place-{i}.jpg"} for i in range(5)]
            cache.upsert_place(
                conn,
                cache.Place(place_id="many-photos", name="Many Photos", raw={"photos": raw_photos}),
            )
            cache.upsert_reviews(
                conn,
                [cache.Review(
                    review_id="review-many",
                    place_id="many-photos",
                    images=[f"https://lh3.googleusercontent.com/review-{i}=w400" for i in range(8)],
                    source="scraper-pro",
                )],
            )

            detail = photos.resolve_place_photos(conn, "many-photos")
            conn.close()

        self.assertEqual(photos.PHOTO_DETAIL_LIMIT, 12)
        self.assertEqual(len(detail), 12)
        self.assertTrue(all(item["url"].startswith("https://") for item in detail))
        self.assertTrue(all("raw_json" not in item for item in detail))
        self.assertTrue(all("binary" not in item and "path" not in item for item in detail))

    def test_lightbox_has_visible_exact_source_url_contract(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("photo-lightbox-source", html)
        self.assertRegex(html, r'<a[^>]+id="photo-lightbox-source"')
        self.assertRegex(css, r"\.photo-lightbox-source\s*\{[^}]*word-break:\s*break-all", re.S)
        self.assertIn("#photo-lightbox-source", js)
        self.assertIn(".textContent = url", js)
        self.assertIn("variant === 'strip' ? 12 : 1", js)


if __name__ == "__main__":
    unittest.main()
