import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, pipeline


def _profile() -> dict:
    return {
        "name": "generic",
        "dimensions": {"red_flags": {"title": "Red flags", "goal": "Risks"}},
    }


class PipelineExactPlaceRefreshTest(unittest.TestCase):
    def test_scout_single_place_id_refresh_uses_cached_place_without_rediscovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conn = cache.connect(data_dir / "placeintel.db")
            cache.upsert_place(conn, cache.Place(
                place_id="exact-bay-mau",
                name="Bay Mau Coconut Forest",
                address="Cam Thanh Coconut Village",
                review_count=90,
                maps_url="https://www.google.com/maps/place/Bay+Mau+Coconut+Forest/",
            ))
            conn.close()

            events = []
            with mock.patch.object(pipeline.config, "DB_PATH", data_dir / "placeintel.db"), \
                    mock.patch.object(pipeline.config, "DATA_DIR", data_dir), \
                    mock.patch.object(pipeline.profiles, "load_profile", return_value=_profile()), \
                    mock.patch.object(pipeline.discover, "discover") as discover, \
                    mock.patch.object(pipeline.reviews, "fetch_reviews",
                                      return_value=[cache.Review(
                                          review_id="fresh-1",
                                          place_id="exact-bay-mau",
                                          text="Fresh exact-place review.",
                                      )]) as fetch_reviews, \
                    mock.patch.object(pipeline.embed, "index_pending", return_value=0):
                result = pipeline.scout_single(
                    "Bay Mau Coconut Forest",
                    place_id="exact-bay-mau",
                    max_reviews=90,
                    refresh=True,
                    skip_reports=True,
                    use_ai=False,
                    on_event=lambda event: events.append((event["stage"], event["msg"])),
                )

            discover.assert_not_called()
            fetch_reviews.assert_called_once()
            self.assertEqual(result.places[0]["place_id"], "exact-bay-mau")
            self.assertTrue(any("缓存命中" in msg for stage, msg in events if stage == "search"))


if __name__ == "__main__":
    unittest.main()
