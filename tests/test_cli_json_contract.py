import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, cli, config


class CliJsonContractTest(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _with_temp_db(self):
        tmp = tempfile.TemporaryDirectory()
        data_dir = Path(tmp.name) / "data"
        db_path = data_dir / "placeintel.db"
        patcher = mock.patch.multiple(config, DATA_DIR=data_dir, DB_PATH=db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        return cache.connect()

    def test_profiles_format_json_returns_profile_dimensions(self) -> None:
        code, stdout, stderr = self._run_cli(["profiles", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "profiles")
        self.assertTrue(payload["data"]["profiles"])
        self.assertIn("dimensions", payload["data"]["profiles"][0])

    def test_list_format_json_returns_cached_places(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar", rating=4.8))
        cache.upsert_reviews(conn, [
            cache.Review(review_id="r1", place_id="place-1", text="kind teacher", rating=5)
        ])
        conn.close()

        code, stdout, stderr = self._run_cli(["list", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "list")
        self.assertEqual(payload["data"]["places"][0]["place_id"], "place-1")
        self.assertEqual(payload["data"]["places"][0]["cached"], 1)

    def test_history_format_json_returns_searches(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
        cache.save_search(conn, "guitar rental", "Hoi An", ["place-1"], "test")
        conn.execute(
            "UPDATE searches SET verdicts_json=?",
            (json.dumps([{"place_id": "place-1", "relevant": True, "reason": "matches"}]),),
        )
        conn.commit()
        conn.close()

        code, stdout, stderr = self._run_cli(["history", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "history")
        self.assertEqual(payload["data"]["searches"][0]["query"], "guitar rental")
        self.assertEqual(payload["data"]["searches"][0]["place_count"], 1)
        self.assertEqual(payload["data"]["searches"][0]["places"][0]["place_id"], "place-1")
        self.assertEqual(payload["data"]["searches"][0]["places"][0]["name"], "D'Class Guitar")
        self.assertEqual(payload["data"]["searches"][0]["places"][0]["reason"], "matches")

    def test_report_format_json_returns_latest_report_without_markdown_only_output(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
        cache.save_report(conn, "place-1", "generic", "test-model", {"summary": "ok"}, "# Report", 1)
        conn.close()

        code, stdout, stderr = self._run_cli(["report", "place-1", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "report")
        self.assertEqual(payload["data"]["report"]["place_id"], "place-1")
        self.assertEqual(payload["data"]["report"]["md"], "# Report")

    def test_export_format_json_uses_agent_envelope(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
        conn.close()

        code, stdout, stderr = self._run_cli(["export", "place-1", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "export")
        self.assertEqual(payload["data"]["place"]["place_id"], "place-1")
        self.assertEqual(payload["data"]["reviews"], [])


if __name__ == "__main__":
    unittest.main()
