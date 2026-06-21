import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, pipeline


def _place() -> cache.Place:
    return cache.Place(
        place_id="flow",
        name="HoiAn Flow",
        rating=4.8,
        review_count=210,
        source="test",
    )


def _profile() -> dict:
    return {
        "name": "generic",
        "dimensions": {"red_flags": {"title": "Red flags", "goal": "Risks"}},
        "output_extras": {"walk_in_brief": "One practical line."},
    }


class PipelineReviewFailureFallbackTest(unittest.TestCase):
    def test_fetch_failure_without_cached_reviews_skips_analyze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conn = cache.connect(data_dir / "placeintel.db")
            place = _place()
            cache.upsert_place(conn, place)
            result = pipeline.ScoutResult(query="HoiAn Flow", location=None, profile="generic")
            events = []

            with mock.patch.object(pipeline.config, "DATA_DIR", data_dir), \
                    mock.patch.object(pipeline.reviews, "fetch_reviews",
                                      side_effect=RuntimeError("SerpAPI request failed on page 1: reset")), \
                    mock.patch.object(pipeline.embed, "index_pending", return_value=0), \
                    mock.patch.object(pipeline.analyze, "analyze_place") as analyze_place:
                pipeline._deep_dive(
                    conn, [place], _profile(), 300, "zh", True, True, False,
                    result, lambda stage, msg, data=None: events.append((stage, msg)),
                )

            analyze_place.assert_not_called()
            self.assertEqual(result.reports, [])
            self.assertEqual(len(result.errors), 1)
            self.assertIn("reviews:HoiAn Flow: SerpAPI request failed", result.errors[0])
            self.assertTrue(any(stage == "report" and "没有缓存评价" in msg for stage, msg in events))
            conn.close()

    def test_fetch_failure_with_cached_reviews_generates_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conn = cache.connect(data_dir / "placeintel.db")
            place = _place()
            cache.upsert_place(conn, place)
            cache.upsert_reviews(conn, [
                cache.Review(
                    review_id="flow-1",
                    place_id="flow",
                    rating=5,
                    text="Great wind and patient instruction.",
                    review_date="2026-06-07",
                )
            ])
            result = pipeline.ScoutResult(query="HoiAn Flow", location=None, profile="generic")
            events = []

            with mock.patch.object(pipeline.config, "DATA_DIR", data_dir), \
                    mock.patch.object(pipeline.reviews, "fetch_reviews",
                                      side_effect=RuntimeError("SerpAPI request failed on page 1: reset")), \
                    mock.patch.object(pipeline.embed, "index_pending", return_value=0), \
                    mock.patch.object(pipeline.analyze, "analyze_place",
                                      return_value=({"verdict": "use-cache"}, "# Cached report")) as analyze_place:
                pipeline._deep_dive(
                    conn, [place], _profile(), 300, "zh", True, True, False,
                    result, lambda stage, msg, data=None: events.append((stage, msg)),
                )

            analyze_place.assert_called_once()
            self.assertEqual(len(result.reports), 1)
            self.assertEqual(result.reports[0]["report"]["verdict"], "use-cache")
            self.assertTrue(any(stage == "reviews" and "使用已缓存 1 条评价继续" in msg
                                for stage, msg in events))
            conn.close()


if __name__ == "__main__":
    unittest.main()
