import tempfile
import unittest
from pathlib import Path

from placeintel import analyze, cache


class AnalyzeActivityRiskTest(unittest.TestCase):
    def test_prompt_and_markdown_include_activity_risk_tag(self) -> None:
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
            place = cache.get_place(conn, "stale-popular")
            risk = cache.activity_risk(
                conn,
                "stale-popular",
                now_ts=cache._review_date_ts("2026-01-01"),
            )
            profile = {
                "dimensions": {"red_flags": {"title": "Red flags", "goal": "Risks"}},
                "output_extras": {"walk_in_brief": "Mention current-status risks."},
            }

            _, user = analyze._build_prompt(
                place,
                "review body",
                "ALL 1 cached reviews",
                profile,
                "en",
                "en",
                risk,
            )
            md = analyze.render_markdown(
                {"verdict": "go-with-caution", "activity_risk": risk},
                place,
                "generic",
                1,
            )

            self.assertIn("ACTIVITY RISK SIGNAL: HIGH", user)
            self.assertIn("Activity risk tag", md)
            self.assertIn("Stale Popular Cafe", md)
            conn.close()


if __name__ == "__main__":
    unittest.main()
