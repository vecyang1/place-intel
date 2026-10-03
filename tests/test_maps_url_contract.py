import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, pipeline, planner, reviews


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


class MapsUrlConsentInterstitialTest(unittest.TestCase):
    def test_consent_redirect_recovers_real_maps_url(self) -> None:
        import urllib.parse
        consent = ("https://consent.google.com/m?continue="
                   + urllib.parse.quote(EXPANDED_URL, safe="") + "&gl=DE&pc=m")
        self.assertEqual(planner._strip_consent_interstitial(consent), EXPANDED_URL)
        # Non-consent URLs pass through untouched
        self.assertEqual(planner._strip_consent_interstitial(EXPANDED_URL), EXPANDED_URL)

    def test_fallback_plan_hides_queries_for_identity_locked_urls(self) -> None:
        with mock.patch.object(planner, "_resolve_short_maps_url",
                               return_value=EXPANDED_URL, create=True):
            plan = planner._fallback_plan(SHORT_URL, None)
        self.assertEqual(plan["mode"], "single")
        self.assertEqual(plan["queries"], [])  # no search will run — show none


class MapsUrlIdentityLockTest(unittest.TestCase):
    """A share link carries the shop's unique identity (ftid) — resolving it must
    never fall back to a Maps text search or name-based guessing."""

    def _common_patches(self, data_dir: Path, fetched_place_id: str = FTID):
        fetched = [cache.Review(review_id="r1", place_id=fetched_place_id,
                                rating=5, text="ok")]
        return [
            mock.patch.object(pipeline.config, "DB_PATH", data_dir / "placeintel.db"),
            mock.patch.object(pipeline.config, "DATA_DIR", data_dir),
            mock.patch.object(pipeline.planner, "_resolve_short_maps_url",
                              return_value=EXPANDED_URL, create=True),
            mock.patch.object(pipeline.profiles, "load_profile", return_value=_profile()),
            mock.patch.object(pipeline.discover, "discover"),
            mock.patch.object(pipeline.planner, "pick_target"),
            mock.patch.object(pipeline.reviews, "fetch_reviews", return_value=fetched),
            mock.patch.object(pipeline.embed, "index_pending", return_value=0),
        ]

    def test_hex_cid_url_locks_target_without_any_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            patches = self._common_patches(Path(tmp))
            with patches[0], patches[1], patches[2], patches[3], \
                    patches[4] as discover_mock, patches[5] as pick_target, \
                    patches[6] as fetch_reviews, patches[7]:
                result = pipeline.scout_single(
                    SHORT_URL, max_reviews=20, skip_reports=True, use_ai=False,
                    on_event=lambda e: events.append((e["stage"], e["msg"])),
                )

        discover_mock.assert_not_called()
        pick_target.assert_not_called()
        place = fetch_reviews.call_args.args[0]
        self.assertEqual(place.place_id, FTID)
        self.assertEqual(place.maps_url, EXPANDED_URL)
        self.assertFalse(result.errors)
        self.assertTrue(any("跳过搜索" in msg for stage, msg in events if stage == "search"))

    def test_cached_identity_match_beats_same_name_lookalike(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conn = cache.connect(data_dir / "placeintel.db")
            cache.upsert_place(conn, cache.Place(
                place_id="ChIJreal", name="Xóm Mèo Coffee", review_count=674,
                maps_url="https://maps.google.com/?cid=real",
                raw={"data_id": FTID},
            ))
            # Same name, different identity, refreshed later — the old name-first
            # lookup would have picked this one.
            cache.upsert_place(conn, cache.Place(
                place_id="ChIJlookalike", name="Xóm Mèo Coffee", review_count=12,
                maps_url="https://maps.google.com/?cid=fake",
                raw={"data_id": "0xdead:0xbeef"},
            ))
            conn.close()

            patches = self._common_patches(data_dir, fetched_place_id="ChIJreal")
            with patches[0], patches[1], patches[2], patches[3], \
                    patches[4] as discover_mock, patches[5] as pick_target, \
                    patches[6] as fetch_reviews, patches[7]:
                result = pipeline.scout_single(
                    SHORT_URL, max_reviews=20, skip_reports=True, use_ai=False,
                )

        discover_mock.assert_not_called()
        pick_target.assert_not_called()
        place = fetch_reviews.call_args.args[0]
        self.assertEqual(place.place_id, "ChIJreal")
        self.assertEqual(result.places[0]["place_id"], "ChIJreal")

    def test_scout_delegates_url_identity_to_single_mode(self) -> None:
        # scout() used to pass only plan["target"] (the parsed NAME) down to
        # single mode, dropping the link's identity and forcing a name search.
        with tempfile.TemporaryDirectory() as tmp:
            patches = self._common_patches(Path(tmp))
            with patches[0], patches[1], patches[2], patches[3], \
                    patches[4] as discover_mock, patches[5] as pick_target, \
                    patches[6] as fetch_reviews, patches[7]:
                result = pipeline.scout(
                    SHORT_URL, max_reviews=20, skip_reports=True, use_ai=False,
                )

        discover_mock.assert_not_called()
        pick_target.assert_not_called()
        self.assertEqual(result.mode, "single")
        place = fetch_reviews.call_args.args[0]
        self.assertEqual(place.place_id, FTID)


class SerpApiPlaceInfoBackfillTest(unittest.TestCase):
    def test_place_info_fills_missing_listing_fields(self) -> None:
        place = cache.Place(place_id=FTID, name="Xóm Mèo Coffee",
                            maps_url=EXPANDED_URL, source="maps-url",
                            raw={"data_id": FTID})
        payload = {
            "reviews": [{"review_id": f"r{i}"} for i in range(20)],
            "place_info": {"title": "Xóm Mèo Coffee", "rating": 4.8,
                           "reviews": 674, "address": "88 Mỹ An 7, Đà Nẵng"},
        }
        # allow=True: this asserts what the paid path does once permitted. The
        # permission rules themselves live in tests/test_spend_gate.py.
        with mock.patch.object(reviews.config, "serpapi_api_key", return_value="k"), \
                mock.patch.object(reviews, "_serpapi_get", return_value=payload):
            got = reviews._fetch_via_serpapi(place, max_reviews=20, allow=True)

        self.assertEqual(len(got), 20)
        self.assertEqual(place.rating, 4.8)
        self.assertEqual(place.review_count, 674)
        self.assertEqual(place.address, "88 Mỹ An 7, Đà Nẵng")


if __name__ == "__main__":
    unittest.main()
