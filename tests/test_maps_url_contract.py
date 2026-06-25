import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, pipeline, planner


SHORT_URL = "https://maps.app.goo.gl/2hHNF5Q1Xy8S1H6P6?g_st=ic"
EXPANDED_URL = (
    "https://www.google.com/maps?q=X%C3%B3m+M%C3%A8o+Coffee,+88+M%E1%BB%B9+An+7"
    "&ftid=0x3142192f0319d6eb:0xf873e96faa231d34"
)
FTID = "0x3142192f0319d6eb:0xf873e96faa231d34"


def _profile() -> dict:
    return {
        "name": "generic",
        "dimensions": {"red_flags": {"title": "Red flags", "goal": "Risks"}},
    }


class MapsUrlContractTest(unittest.TestCase):
    def test_parse_maps_short_url_expands_name_and_ftid(self) -> None:
        with mock.patch.object(
            planner, "_resolve_short_maps_url", return_value=EXPANDED_URL, create=True
        ):
            info = planner.parse_maps_url(SHORT_URL)

        self.assertEqual(info["url"], EXPANDED_URL)
        self.assertEqual(info["name"], "Xóm Mèo Coffee")
        self.assertEqual(info["cid"], FTID)

    def test_short_url_can_deep_dive_when_discovery_returns_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            events = []
            fetched = [
                cache.Review(
                    review_id="xom-meo-1",
                    place_id=FTID,
                    rating=5,
                    text="Calm coffee spot.",
                )
            ]

            with mock.patch.object(pipeline.config, "DB_PATH", data_dir / "placeintel.db"), \
                    mock.patch.object(pipeline.config, "DATA_DIR", data_dir), \
                    mock.patch.object(pipeline.planner, "_resolve_short_maps_url",
                                      return_value=EXPANDED_URL, create=True), \
                    mock.patch.object(pipeline.profiles, "load_profile", return_value=_profile()), \
                    mock.patch.object(pipeline.discover, "discover", return_value=[]), \
                    mock.patch.object(pipeline.reviews, "fetch_reviews",
                                      return_value=fetched) as fetch_reviews, \
                    mock.patch.object(pipeline.embed, "index_pending", return_value=0):
                result = pipeline.scout_single(
                    SHORT_URL,
                    max_reviews=20,
                    refresh=True,
                    skip_reports=True,
                    use_ai=False,
                    on_event=lambda event: events.append((event["stage"], event["msg"])),
                )

        fetch_reviews.assert_called_once()
        place = fetch_reviews.call_args.args[0]
        self.assertEqual(place.place_id, FTID)
        self.assertEqual(place.name, "Xóm Mèo Coffee")
        self.assertEqual(place.maps_url, EXPANDED_URL)
        self.assertEqual(place.raw["data_id"], FTID)
        self.assertEqual(result.places[0]["place_id"], FTID)
        self.assertFalse(result.errors)
        self.assertTrue(any("Maps URL" in msg for stage, msg in events if stage == "search"))

    def test_discovered_place_keeps_resolved_exact_url_for_review_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            discovered = cache.Place(
                place_id="ChIJ69YZAy8ZQjERNB0jqm_pc_g",
                name="Xóm Mèo Coffee",
                review_count=674,
                maps_url="https://www.google.com/maps/place/X%C3%B3m+M%C3%A8o+Coffee/@16,108/data=!3m1",
                raw={},
            )

            with mock.patch.object(pipeline.config, "DB_PATH", data_dir / "placeintel.db"), \
                    mock.patch.object(pipeline.config, "DATA_DIR", data_dir), \
                    mock.patch.object(pipeline.planner, "_resolve_short_maps_url",
                                      return_value=EXPANDED_URL, create=True), \
                    mock.patch.object(pipeline.profiles, "load_profile", return_value=_profile()), \
                    mock.patch.object(pipeline.discover, "discover", return_value=[discovered]), \
                    mock.patch.object(pipeline.reviews, "fetch_reviews",
                                      return_value=[cache.Review(review_id="r1", place_id=discovered.place_id)]) as fetch_reviews, \
                    mock.patch.object(pipeline.embed, "index_pending", return_value=0):
                pipeline.scout_single(
                    SHORT_URL,
                    max_reviews=20,
                    refresh=True,
                    skip_reports=True,
                    use_ai=False,
                )

        place = fetch_reviews.call_args.args[0]
        self.assertEqual(place.maps_url, EXPANDED_URL)
        self.assertEqual(place.raw["data_id"], FTID)


if __name__ == "__main__":
    unittest.main()
