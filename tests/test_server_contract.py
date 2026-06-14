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
        with mock.patch.object(server.config, "provider_info", return_value=info), \
                mock.patch.object(server.config, "reason_model", return_value="reason-model"), \
                mock.patch.object(server.config, "translation_model", return_value="translate-model"), \
                mock.patch.object(server.config, "EVIDENCE_LANG", "original"), \
                mock.patch.object(server.config, "PLACE_TTL_DAYS", 9), \
                mock.patch.object(server.config, "DATA_DIR", Path("/private/user/data")):
            response = TestClient(server.app).get("/api/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["settings"]["reason_model"], "reason-model")
        self.assertEqual(payload["settings"]["translation_model"], "translate-model")
        self.assertEqual(payload["settings"]["default_answer_language"], "zh")
        self.assertEqual(payload["settings"]["evidence_language"], "original")
        self.assertEqual(payload["settings"]["cache_ttl_days"], 9)
        self.assertEqual(payload["runtime"]["data_dir"], {"configured": True, "path_visible": False})
        self.assertEqual(payload["health"]["cheap_url"], "/api/health")
        self.assertEqual(payload["health"]["deep_url"], "/api/health/deep")
        self.assertFalse(payload["feature_status"]["reasoning"]["available"])
        self.assertNotIn("/private/user/data", str(payload))
        self.assertNotIn("AIza", str(payload))
        self.assertNotIn("sk-", str(payload))

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
