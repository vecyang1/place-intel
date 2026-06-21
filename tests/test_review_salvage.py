"""SerpAPI partial-scrape salvage: a later page timing out must not discard the
reviews already collected (the v0.4.49 'report jumps back to nothing' fix). Only a
first-page failure — where nothing was collected — should propagate."""
import unittest
import tempfile
from pathlib import Path
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

    def test_first_serpapi_page_only_is_not_treated_as_complete_cache(self):
        place = _place()
        place.review_count = 300

        def fake_get(params, page):
            if page == 1:
                return _page1_payload(8)
            raise RuntimeError("SerpAPI request failed on page 2: Read timed out")

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            with self.assertRaises(reviews.PartialReviewsError):
                reviews._fetch_via_serpapi(place, max_reviews=300)

    def test_unknown_total_with_next_page_failure_is_partial(self):
        place = _place()

        def fake_get(params, page):
            if page == 1:
                return _page1_payload(8)
            raise RuntimeError("SerpAPI request failed on page 2: Read timed out")

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            with self.assertRaises(reviews.PartialReviewsError):
                reviews._fetch_via_serpapi(place, max_reviews=300)

    def test_unknown_total_without_next_page_allows_small_review_sets(self):
        place = _place()

        def fake_get(params, page):
            return {"reviews": [{"review_id": f"small-{i}"} for i in range(5)]}

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            got = reviews._fetch_via_serpapi(place, max_reviews=300)

        self.assertEqual(len(got), 5)

    def test_first_page_failure_still_raises(self):
        def fake_get(params, page):
            raise RuntimeError("SerpAPI request failed on page 1: Read timed out")

        with mock.patch.object(reviews, "_serpapi_get", side_effect=fake_get):
            with self.assertRaises(RuntimeError):
                reviews._fetch_via_serpapi(_place(), max_reviews=300)

    def test_scraper_target_url_repairs_place_id_only_maps_url(self):
        place = _place()
        place.name = "Melody Boutique Villa Hoi An"
        place.place_id = "ChIJ8_test"
        place.maps_url = "https://www.google.com/maps/place/?q=place_id:ChIJ8_test"

        target = reviews._scraper_target_url(place)

        self.assertIn("/maps/place/Melody+Boutique+Villa+Hoi+An/", target)
        self.assertIn("q=place_id:ChIJ8_test", target)

    def test_scraper_config_uses_absolute_db_path_for_vendor_cwd(self):
        cfg = reviews._build_scraper_config(_place(), max_reviews=90)

        self.assertTrue(Path(cfg["db_path"]).is_absolute(), cfg["db_path"])
        self.assertEqual(Path(cfg["db_path"]).name, "scraper_pro_reviews.db")
        self.assertTrue(Path(cfg["log_dir"]).is_absolute(), cfg["log_dir"])
        self.assertEqual(Path(cfg["log_dir"]).name, "logs")
        self.assertEqual(cfg["log_file"], "scraper.log")

    def test_scraper_subprocess_runs_from_writable_data_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            scraper_dir = root / "vendor" / "google-reviews-scraper-pro"
            scraper_dir.mkdir(parents=True)
            fake_proc = mock.Mock(stdout="", stderr="", returncode=0)
            with mock.patch.object(reviews.config, "DATA_DIR", data_dir), \
                    mock.patch.object(reviews, "SCRAPER_DIR", scraper_dir), \
                    mock.patch.object(
                        reviews,
                        "SCRAPER_PYTHON",
                        scraper_dir / ".venv" / "bin" / "python",
                    ), \
                    mock.patch.object(
                        reviews.subprocess,
                        "run",
                        return_value=fake_proc,
                    ) as run:
                reviews._run_scraper_pro(_place(), max_reviews=90)

        cmd = run.call_args.args[0]
        self.assertEqual(
            run.call_args.kwargs["cwd"],
            data_dir.resolve() / "vendor" / "google-reviews-scraper-pro" / "work",
        )
        self.assertIn(str(scraper_dir), cmd[2])
        self.assertIn(str(scraper_dir / "start.py"), cmd[2])


if __name__ == "__main__":
    unittest.main()
