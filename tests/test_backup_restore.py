import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, cli, config


class BackupRestoreTest(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _patch_data_dir(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        data_dir = Path(tmp.name) / "data"
        patcher = mock.patch.multiple(
            config,
            DATA_DIR=data_dir,
            DB_PATH=data_dir / "placeintel.db",
            SETTINGS_PATH=data_dir / "settings.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        return tmp, data_dir

    def _seed_runtime_data(self, data_dir: Path) -> None:
        conn = cache.connect()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
        cache.save_report(conn, "place-1", "generic", "test-model", {"summary": "ok"}, "# Report", 1)
        conn.close()
        (data_dir / "settings.json").write_text('{"reason_model":"test-model"}', encoding="utf-8")
        reports = data_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "dclass.md").write_text("# Dossier\n", encoding="utf-8")
        scraper = sqlite3.connect(data_dir / "scraper_pro_reviews.db")
        scraper.execute("CREATE TABLE scraped_reviews (id TEXT PRIMARY KEY)")
        scraper.execute("INSERT INTO scraped_reviews VALUES ('r1')")
        scraper.commit()
        scraper.close()
        (data_dir / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")

    def test_backup_json_manifest_includes_safe_artifacts_and_hashes(self) -> None:
        _, data_dir = self._patch_data_dir()
        self._seed_runtime_data(data_dir)

        code, stdout, stderr = self._run_cli(["backup", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "backup")
        manifest_path = Path(payload["data"]["manifest_path"])
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(manifest_path.is_relative_to(data_dir / "backups"))

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("placeintel.db", paths)
        self.assertIn("scraper_pro_reviews.db", paths)
        self.assertIn("settings.json", paths)
        self.assertIn("reports/dclass.md", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("server.log", paths)
        self.assertEqual(payload["data"]["file_count"], len(manifest["files"]))

        for item in manifest["files"]:
            target = manifest_path.parent / item["path"]
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(item["sha256"], digest)
            self.assertEqual(item["size"], target.stat().st_size)

    def test_restore_requires_explicit_confirmation_and_leaves_data_untouched(self) -> None:
        _, data_dir = self._patch_data_dir()
        self._seed_runtime_data(data_dir)
        backup_code, backup_out, _ = self._run_cli(["backup", "--format", "json"])
        self.assertEqual(backup_code, 0)
        manifest_path = json.loads(backup_out)["data"]["manifest_path"]
        conn = cache.connect()
        conn.execute("UPDATE places SET name='Changed' WHERE place_id='place-1'")
        conn.commit()
        conn.close()

        code, stdout, stderr = self._run_cli(["restore", manifest_path, "--format", "json"])

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "confirmation_required")
        conn = cache.connect()
        self.assertEqual(cache.get_place(conn, "place-1")["name"], "Changed")
        conn.close()

    def test_restore_round_trips_database_reports_and_settings(self) -> None:
        _, data_dir = self._patch_data_dir()
        self._seed_runtime_data(data_dir)
        backup_code, backup_out, _ = self._run_cli(["backup", "--format", "json"])
        self.assertEqual(backup_code, 0)
        manifest_path = json.loads(backup_out)["data"]["manifest_path"]
        (data_dir / "placeintel.db").unlink()
        shutil.rmtree(data_dir / "reports")
        (data_dir / "settings.json").unlink()

        code, stdout, stderr = self._run_cli(["restore", manifest_path, "--yes", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "restore")
        self.assertGreaterEqual(payload["data"]["restored_files"], 3)
        conn = cache.connect()
        self.assertEqual(cache.get_place(conn, "place-1")["name"], "D'Class Guitar")
        conn.close()
        self.assertEqual((data_dir / "reports" / "dclass.md").read_text(encoding="utf-8"), "# Dossier\n")
        self.assertIn("test-model", (data_dir / "settings.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
