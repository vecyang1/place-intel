import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cli, config


FIXTURES = Path(__file__).parent / "fixtures" / "saved_takeout"


class SavedPlacesCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name) / "data"
        self.patcher = mock.patch.multiple(
            config,
            DATA_DIR=data_dir,
            DB_PATH=data_dir / "placeintel.db",
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_saved_import_json_uses_agent_envelope_and_safe_counts(self) -> None:
        code, stdout, stderr = self._run_cli(
            ["saved-import", str(FIXTURES), "--format", "json"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "saved-import")
        self.assertEqual(payload["data"]["files"], 3)
        self.assertEqual(payload["data"]["rows"], 4)
        self.assertEqual(payload["data"]["skipped"], 0)
        self.assertEqual(payload["data"]["created"], {
            "collections": 3,
            "items": 3,
            "memberships": 4,
        })
        self.assertIn("states", payload["data"])
        self.assertEqual(payload["data"]["states"], {"pending": 3})
        self.assertNotIn("Quiet courtyard", stdout)

    def test_saved_import_and_inventory_support_an_opaque_source_label(self) -> None:
        code, stdout, stderr = self._run_cli(
            [
                "saved-import",
                str(FIXTURES),
                "--source-label",
                "account-a",
                "--format",
                "json",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["data"]["source_label"], "account-a")
        self.assertEqual(payload["data"]["adopted_collections"], 0)

        code, stdout, stderr = self._run_cli(
            ["saved-inventory", "--source-label", "account-a", "--format", "json"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["data"]["filters"]["source_label"], "account-a")
        self.assertEqual(
            {item["source_label"] for item in payload["data"]["collections"]},
            {"account-a"},
        )

    def test_saved_inventory_reports_states_and_collection_counts(self) -> None:
        self._run_cli(["saved-import", str(FIXTURES), "--format", "json"])

        code, stdout, stderr = self._run_cli(
            ["--format", "json", "saved-inventory"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "saved-inventory")
        self.assertEqual(payload["data"]["totals"], {
            "collections": 3,
            "items": 3,
            "memberships": 4,
        })
        self.assertEqual(payload["data"]["states"], {"pending": 3})
        self.assertEqual(
            {item["name"] for item in payload["data"]["collections"]},
            {"Date Places", "Favorites", "Starred places"},
        )

    def test_saved_inventory_filters_collection_and_returns_bounded_safe_items(self) -> None:
        self._run_cli(["saved-import", str(FIXTURES), "--format", "json"])

        code, stdout, stderr = self._run_cli(
            [
                "saved-inventory",
                "--collection",
                "Favorites",
                "--state",
                "pending",
                "--limit",
                "10",
                "--format",
                "json",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["data"]["filters"], {
            "collection": "Favorites",
            "state": "pending",
            "limit": 10,
        })
        self.assertEqual(payload["data"]["matched_items"], 1)
        self.assertEqual(payload["data"]["items"][0]["title"], "Lantern Café")
        self.assertEqual(
            payload["data"]["items"][0]["collections"],
            ["Date Places", "Favorites"],
        )
        self.assertNotIn("url", payload["data"]["items"][0])
        self.assertNotIn("note", payload["data"]["items"][0])

    def test_saved_import_empty_input_returns_recoverable_machine_error(self) -> None:
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()

        code, stdout, stderr = self._run_cli(
            ["saved-import", str(empty), "--format", "json"]
        )

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "saved_import_no_supported_rows")
        self.assertTrue(payload["error"]["recoverable"])
        self.assertNotIn(str(empty), stdout)

    def test_saved_import_truncated_zip_returns_safe_machine_error(self) -> None:
        archive = Path(self.tmp.name) / "takeout.zip"
        archive.write_bytes(b"not a zip")

        code, stdout, stderr = self._run_cli(
            ["saved-import", str(archive), "--format", "json"]
        )

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "saved_import_invalid_archive")
        self.assertNotIn(str(archive), stdout)

    def test_saved_import_invalid_csv_encoding_returns_safe_machine_error(self) -> None:
        source = Path(self.tmp.name) / "Saved.csv"
        source.write_bytes(b"\xff\xfetitle,item_content_url")

        code, stdout, stderr = self._run_cli(
            ["saved-import", str(source), "--format", "json"]
        )

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "saved_import_invalid_csv")
        self.assertNotIn(str(source), stdout)

    def test_saved_import_uses_environment_row_limit(self) -> None:
        with mock.patch.dict(os.environ, {"PLACEINTEL_SAVED_IMPORT_MAX_ROWS": "1"}):
            code, stdout, stderr = self._run_cli(
                ["saved-import", str(FIXTURES), "--format", "json"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "saved_import_too_many_rows")

    def test_saved_commands_reject_global_ndjson_instead_of_printing_text(self) -> None:
        code, stdout, stderr = self._run_cli(
            ["--format", "ndjson", "saved-inventory"]
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("usage error", stderr)
        self.assertIn("ndjson", stderr)


if __name__ == "__main__":
    unittest.main()
