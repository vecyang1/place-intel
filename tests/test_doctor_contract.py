import contextlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient

import placeintel
from placeintel import cli, config, server


class DoctorContractTest(unittest.TestCase):
    def test_cheap_health_reports_local_state_without_live_calls(self) -> None:
        from placeintel import doctor

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            db_path = data_dir / "placeintel.db"
            provider_info = {
                "reason": {"model": "reason-model", "provider": "VectorEngine"},
                "translate": {"model": "translate-model", "provider": "VectorEngine"},
                "embed": {"model": "embed-model (768d)", "provider": "Google official"},
            }
            with mock.patch.object(config, "DATA_DIR", data_dir), \
                    mock.patch.object(config, "DB_PATH", db_path), \
                    mock.patch.object(config, "provider_info", return_value=provider_info), \
                    mock.patch.object(config, "list_reason_models") as models:
                report = doctor.cheap_health()

        self.assertTrue(report["ok"])
        self.assertEqual(report["version"], placeintel.__version__)
        self.assertEqual(report["mode"], "cheap")
        self.assertEqual(report["providers"], provider_info)
        self.assertIn("checks", report)
        self.assertTrue(any(check["name"] == "db" and check["ok"] for check in report["checks"]))
        self.assertTrue(any(check["name"] == "data_dir" and check["ok"] for check in report["checks"]))
        self.assertTrue(any(check["name"] == "static_web" and check["ok"] for check in report["checks"]))
        models.assert_not_called()
        payload = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("AIza", payload)
        self.assertNotIn("sk-", payload)

    def test_api_health_uses_shared_cheap_health_contract(self) -> None:
        expected = {
            "ok": True,
            "version": placeintel.__version__,
            "mode": "cheap",
            "checks": [],
            "warnings": [],
            "errors": [],
            "providers": {},
        }
        with mock.patch.object(server.doctor, "cheap_health", return_value=expected):
            response = TestClient(server.app).get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_doctor_json_outputs_one_machine_readable_document(self) -> None:
        report = {
            "ok": True,
            "version": placeintel.__version__,
            "mode": "cheap",
            "checks": [{"name": "db", "ok": True, "severity": "critical", "message": "connected"}],
            "warnings": [],
            "errors": [],
            "providers": {},
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(cli.doctor, "cheap_health", return_value=report), \
                contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            code = cli.main(["doctor", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        parsed = json.loads(stdout.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["command"], "doctor")
        self.assertEqual(parsed["data"], report)

    def test_doctor_json_exits_nonzero_when_required_check_fails(self) -> None:
        report = {
            "ok": False,
            "version": placeintel.__version__,
            "mode": "cheap",
            "checks": [{"name": "db", "ok": False, "severity": "critical", "message": "locked"}],
            "warnings": [],
            "errors": ["db: locked"],
            "providers": {},
        }
        stdout = io.StringIO()
        with mock.patch.object(cli.doctor, "cheap_health", return_value=report), \
                contextlib.redirect_stdout(stdout):
            code = cli.main(["doctor", "--json"])

        self.assertEqual(code, 2)
        parsed = json.loads(stdout.getvalue())
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"]["code"], "health_failed")


if __name__ == "__main__":
    unittest.main()
