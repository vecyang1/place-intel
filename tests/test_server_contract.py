import unittest
import tempfile
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient
import placeintel
from placeintel import cache, config, server


class ServerContractTest(unittest.TestCase):
    def test_fastapi_version_matches_package_version(self) -> None:
        self.assertEqual(server.app.version, placeintel.__version__)

    def test_web_shell_disables_browser_cache_for_no_build_assets(self) -> None:
        client = TestClient(server.app)

        for path in ("/", "/static/app.js", "/static/app.css"):
            with self.subTest(path=path):
                response = client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_web_shell_fingerprints_no_build_assets_with_package_version(self) -> None:
        response = TestClient(server.app).get("/")

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn(f'/static/app.css?v={placeintel.__version__}"', html)
        self.assertIn(f'/static/i18n.js?v={placeintel.__version__}"', html)
        self.assertIn(f'/static/app.js?v={placeintel.__version__}"', html)

    def test_meta_exposes_separate_translation_model(self) -> None:
        info = {
            "reason": {"model": "expensive-model", "provider": "VectorEngine"},
            "translate": {"model": "gemini-3.1-flash-lite", "provider": "VectorEngine"},
            "embed": {"model": "embed-model", "provider": "Google 官方"},
        }
        with mock.patch.object(server.config, "provider_info", return_value=info):
            response = TestClient(server.app).get("/api/meta")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["translate"]["model"], "gemini-3.1-flash-lite")

    def test_config_endpoint_exposes_non_secret_system_settings(self) -> None:
        info = {
            "reason": {"model": "reason-model", "provider": "未配置"},
            "translate": {"model": "translate-model", "provider": "VectorEngine"},
            "embed": {"model": "embed-model", "provider": "Google 官方"},
        }
        # Isolate SETTINGS_PATH so the contract asserts pristine defaults, not
        # whatever language prefs a developer persisted by using the app locally.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(server.config, "provider_info", return_value=info), \
                mock.patch.object(server.config, "reason_model", return_value="reason-model"), \
                mock.patch.object(server.config, "translation_model", return_value="translate-model"), \
                mock.patch.object(server.config, "EVIDENCE_LANG", "original"), \
                mock.patch.object(server.config, "PLACE_TTL_DAYS", 9), \
                mock.patch.object(server.config, "SETTINGS_PATH", Path(tmp) / "settings.json"), \
                mock.patch.object(server.config, "DATA_DIR", Path("/private/user/data")):
            response = TestClient(server.app).get("/api/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["settings"]["reason_model"], "reason-model")
        self.assertEqual(payload["settings"]["translation_model"], "translate-model")
        self.assertEqual(payload["settings"]["default_answer_language"], "auto")
        self.assertEqual(payload["settings"]["default_report_language"], "auto")
        self.assertEqual(payload["settings"]["evidence_language"], "original")
        self.assertEqual(payload["settings"]["cache_ttl_days"], 9)
        self.assertEqual(payload["language"]["ui_language"], "en")
        self.assertEqual(payload["language"]["answer_language"], "en")
        self.assertEqual(payload["language"]["report_language"], "en")
        self.assertEqual(payload["language"]["translation_target"], "en")
        self.assertEqual(payload["language"]["fallback_language"], "en")
        self.assertEqual(payload["language"]["supported_ui_locales"], ["en", "zh"])
        self.assertEqual(payload["runtime"]["data_dir"], {"configured": True, "path_visible": False})
        self.assertEqual(payload["health"]["cheap_url"], "/api/health")
        self.assertEqual(payload["health"]["deep_url"], "/api/health/deep")
        self.assertFalse(payload["feature_status"]["reasoning"]["available"])
        self.assertNotIn("/private/user/data", str(payload))
        self.assertNotIn("AIza", str(payload))
        self.assertNotIn("sk-", str(payload))

    def test_language_settings_endpoint_validates_and_persists_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            with mock.patch.object(config, "SETTINGS_PATH", settings):
                client = TestClient(server.app)
                saved = client.post("/api/settings/language", json={
                    "default_answer_language": "fr-FR",
                    "default_report_language": "vi",
                    "translation_target": "es",
                    "ui_language": "zh-CN",
                    "evidence_language": "original",
                    "make_default": True,
                })
                invalid = client.post("/api/settings/language", json={
                    "default_answer_language": "../zh",
                    "make_default": True,
                })
                status = client.get("/api/config")

        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["ok"])
        self.assertEqual(invalid.status_code, 400)
        payload = status.json()
        self.assertEqual(payload["settings"]["default_answer_language"], "fr-FR")
        self.assertEqual(payload["settings"]["default_report_language"], "vi")
        self.assertEqual(payload["settings"]["translation_target"], "es")
        self.assertEqual(payload["settings"]["ui_language"], "zh")
        self.assertEqual(payload["settings"]["evidence_language"], "original")

    def test_qa_history_endpoint_returns_recent_questions_by_exact_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "placeintel.db"
            with mock.patch.object(config, "DB_PATH", db_path):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
                with mock.patch.object(cache.time, "time", side_effect=[100.0, 200.0, 300.0]):
                    cache.save_qa(conn, "global older question", None, "older answer", "test-model", None)
                    cache.save_qa(conn, "scoped shop question", "place-1", "scoped answer", "test-model", None)
                    cache.save_qa(conn, "global newer question", None, "newer answer", "test-model", None)
                conn.close()

                client = TestClient(server.app)
                global_rows = client.get("/api/qa")
                scoped_rows = client.get("/api/qa", params={"place_id": "place-1"})
                all_rows = client.get("/api/qa", params={"scope": "all"})

        self.assertEqual(global_rows.status_code, 200)
        self.assertEqual(
            [row["question"] for row in global_rows.json()],
            ["global newer question", "global older question"],
        )
        self.assertEqual(scoped_rows.status_code, 200)
        self.assertEqual([row["question"] for row in scoped_rows.json()], ["scoped shop question"])
        self.assertEqual(all_rows.status_code, 200)
        self.assertEqual(
            [row["question"] for row in all_rows.json()],
            ["global newer question", "scoped shop question", "global older question"],
        )
        self.assertEqual(all_rows.json()[1]["place_name"], "D'Class Guitar")

    def test_review_translation_endpoint_delegates_to_pipeline(self) -> None:
        expected = {
            "review_id": "review-1",
            "target_lang": "zh",
            "source_lang": "vi",
            "text": "路有点难走，但景色很漂亮。",
            "cached": False,
            "model": "test-model",
            "provider": "test-provider",
            "created_at": 100.0,
        }
        with mock.patch.object(server.pipeline, "translate_review", return_value=expected) as translate:
            response = TestClient(server.app).post(
                "/api/reviews/translate",
                json={"review_id": "review-1", "target_lang": "zh"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        translate.assert_called_once_with("review-1", "zh")

    def test_ask_endpoint_resolves_browser_language_without_forcing_chinese(self) -> None:
        expected = {
            "answer": "French answer",
            "cached": False,
            "created_at": 100.0,
            "model": "test-model",
            "provider": "test-provider",
            "report_lang": "fr",
            "language_source": "browser",
            "evidence": [],
        }
        with mock.patch.object(server.pipeline, "ask", return_value=expected) as ask:
            response = TestClient(server.app).post(
                "/api/ask",
                json={"question": "Which shop is patient?", "language_hint": "fr-FR"},
            )

        self.assertEqual(response.status_code, 200)
        ask.assert_called_once_with(
            "Which shop is patient?", place_id=None,
            report_lang=None, language_hint="fr-FR", no_cache=False,
        )
        self.assertEqual(response.json()["report_lang"], "fr")

    def test_places_api_exposes_and_toggles_favorite_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "placeintel.db"
            with mock.patch.object(config, "DB_PATH", db_path):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(
                    place_id="place-1",
                    name="D'Class Guitar",
                    source="test",
                ))
                conn.execute(
                    """INSERT INTO reports (place_id, profile, model, report_json, report_md,
                       review_count, created_at) VALUES (?,?,?,?,?,?,?)""",
                    ("place-1", "generic", "test-model", "{}", "# Old", 1, 100.0),
                )
                conn.execute(
                    """INSERT INTO reports (place_id, profile, model, report_json, report_md,
                       review_count, created_at) VALUES (?,?,?,?,?,?,?)""",
                    ("place-1", "rental", "test-model", "{}", "# New", 1, 200.0),
                )
                conn.commit()
                conn.close()

                client = TestClient(server.app)
                toggle = client.post(
                    "/api/places/place-1/favorite",
                    json={"favorite": True},
                )
                places = client.get("/api/places")
                detail = client.get("/api/places/place-1")

        self.assertEqual(toggle.status_code, 200)
        self.assertTrue(toggle.json()["favorite"])
        self.assertFalse(toggle.json()["refresh_enabled"])
        self.assertEqual(places.status_code, 200)
        self.assertTrue(places.json()[0]["favorite"])
        self.assertFalse(places.json()[0]["refresh_enabled"])
        self.assertEqual(places.json()[0]["report_count"], 2)
        self.assertEqual(places.json()[0]["latest_report_at"], 200.0)
        self.assertEqual(places.json()[0]["latest_report_profile"], "rental")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["place"]["favorite"])

    def test_searches_api_marks_places_that_already_have_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "placeintel.db"
            with mock.patch.object(config, "DB_PATH", db_path):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(
                    place_id="with-report",
                    name="Trail With Report",
                    source="test",
                ))
                cache.upsert_place(conn, cache.Place(
                    place_id="without-report",
                    name="Trail Without Report",
                    source="test",
                ))
                conn.execute(
                    """INSERT INTO reports (place_id, profile, model, report_json, report_md,
                       review_count, created_at) VALUES (?,?,?,?,?,?,?)""",
                    ("with-report", "generic", "test-model", "{}", "# Existing", 1, 100.0),
                )
                cache.save_search(conn, "hiking", "Da Nang", ["with-report", "without-report"], "cache")
                conn.close()

                response = TestClient(server.app).get("/api/searches")

        self.assertEqual(response.status_code, 200)
        places = response.json()[0]["places"]
        by_id = {place["place_id"]: place for place in places}
        self.assertEqual(by_id["with-report"]["report_count"], 1)
        self.assertEqual(by_id["without-report"]["report_count"], 0)

    def test_places_api_exposes_bounded_photo_metadata_without_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "placeintel.db"
            with mock.patch.object(config, "DB_PATH", db_path):
                conn = cache.connect()
                cache.upsert_place(
                    conn,
                    cache.Place(
                        place_id="photo-place",
                        name="Photo Place",
                        maps_url="https://maps.google.com/?cid=456",
                    ),
                )
                cache.upsert_reviews(
                    conn,
                    [cache.Review(
                        review_id="review-photo",
                        place_id="photo-place",
                        author="Ana",
                        rating=4,
                        review_date="2026-06-03",
                        text="Visible storefront photo.",
                        images=["https://lh3.googleusercontent.com/photo=w400"],
                        source="scraper-pro",
                    )],
                )
                conn.close()

                client = TestClient(server.app)
                places = client.get("/api/places")
                detail = client.get("/api/places/photo-place")

        self.assertEqual(places.status_code, 200)
        card = places.json()[0]
        self.assertEqual(card["thumbnail"]["url"], "https://lh3.googleusercontent.com/photo=w400")
        self.assertEqual(card["thumbnail"]["kind"], "review")
        self.assertNotIn("images_json", str(card))

        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["photos"][0]["url"], "https://lh3.googleusercontent.com/photo=w400")
        self.assertEqual(payload["photos"][0]["review_id"], "review-photo")
        self.assertLessEqual(len(payload["photos"]), 6)
        self.assertNotIn("images_json", str(payload))
        self.assertNotIn("data:image", str(payload))

    def test_favorite_toggle_unknown_place_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "placeintel.db"
            with mock.patch.object(config, "DB_PATH", db_path):
                response = TestClient(server.app).post(
                    "/api/places/missing/favorite",
                    json={"favorite": True},
                )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
