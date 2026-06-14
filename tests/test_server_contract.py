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


if __name__ == "__main__":
    unittest.main()
