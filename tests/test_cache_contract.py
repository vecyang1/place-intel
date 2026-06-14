import tempfile
import unittest
from pathlib import Path

from placeintel import cache


class CacheContractTest(unittest.TestCase):
    def test_upsert_place_coerces_list_category_to_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            place = cache.Place(
                place_id="place-list-category",
                name="List Category Cafe",
                category=["Cafe", "Coffee shop"],
                address="1 Test St",
                source="test",
            )

            cache.upsert_place(conn, place)

            row = cache.get_place(conn, "place-list-category")
            self.assertIsNotNone(row)
            self.assertEqual(row["category"], "Cafe · Coffee shop")
            conn.close()

    def test_activity_risk_flags_popular_place_with_stale_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            cache.upsert_place(conn, cache.Place(
                place_id="stale-popular",
                name="Stale Popular Cafe",
                review_count=240,
                source="test",
            ))
            cache.upsert_reviews(conn, [
                cache.Review(
                    review_id="old-1",
                    place_id="stale-popular",
                    rating=5,
                    text="Great back then",
                    review_date="2025-01-01",
                )
            ])

            risk = cache.activity_risk(
                conn,
                "stale-popular",
                now_ts=cache._review_date_ts("2026-01-01"),
            )

            self.assertIsNotNone(risk)
            self.assertEqual(risk["kind"], "stale_review_activity")
            self.assertEqual(risk["severity"], "high")
            self.assertEqual(risk["days_since_newest_review"], 365)
            conn.close()

    def test_activity_risk_ignores_recent_or_low_volume_places(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            for place_id, review_count, review_date in (
                ("recent-popular", 300, "2025-12-01"),
                ("stale-small", 12, "2025-01-01"),
            ):
                cache.upsert_place(conn, cache.Place(
                    place_id=place_id,
                    name=place_id,
                    review_count=review_count,
                    source="test",
                ))
                cache.upsert_reviews(conn, [
                    cache.Review(
                        review_id=f"{place_id}-1",
                        place_id=place_id,
                        rating=4,
                        text="Useful review",
                        review_date=review_date,
                    )
                ])

            now_ts = cache._review_date_ts("2026-01-01")
            self.assertIsNone(cache.activity_risk(conn, "recent-popular", now_ts=now_ts))
            self.assertIsNone(cache.activity_risk(conn, "stale-small", now_ts=now_ts))
            conn.close()


if __name__ == "__main__":
    unittest.main()
