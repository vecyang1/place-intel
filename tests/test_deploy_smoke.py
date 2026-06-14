import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from placeintel import cli


class _SmokeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: str, content_type: str = "application/json") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            html = '<script src="/static/app.js?v=0.4.99" defer></script>'
            return self._send(200, html, "text/html")
        if path == "/api/meta":
            return self._send(200, json.dumps({"version": "0.4.99"}))
        if path == "/api/health":
            return self._send(200, json.dumps({"ok": True, "version": "0.4.99"}))
        if path == "/api/places":
            return self._send(200, json.dumps([{"place_id": "place-1", "name": "D'Class"}]))
        if path == "/api/places/place-1":
            return self._send(200, json.dumps({"place": {"place_id": "place-1"}, "reviews": [], "report": None}))
        self._send(404, json.dumps({"detail": "not found"}))

    def log_message(self, *_args) -> None:
        pass


class _ProtectedHandler(_SmokeHandler):
    def do_GET(self) -> None:
        self._send(401, "auth required", "text/plain")


@contextlib.contextmanager
def _server(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


class DeploySmokeTest(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, dict, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_deploy_smoke_json_verifies_read_only_runtime_flow(self) -> None:
        with _server(_SmokeHandler) as base_url:
            code, payload, stderr = self._run_cli([
                "deploy-smoke", "--base-url", base_url,
                "--expected-version", "0.4.99", "--format", "json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "deploy-smoke")
        checks = {c["name"]: c for c in payload["data"]["checks"]}
        for name in ["meta", "health", "static_version", "library", "dossier"]:
            self.assertTrue(checks[name]["ok"], name)
        self.assertEqual(checks["dossier"]["data"]["place_id"], "place-1")

    def test_deploy_smoke_checks_public_unauthenticated_rejection_when_requested(self) -> None:
        with _server(_SmokeHandler) as base_url, _server(_ProtectedHandler) as public_url:
            code, payload, stderr = self._run_cli([
                "deploy-smoke", "--base-url", base_url, "--public-url", public_url,
                "--expected-version", "0.4.99", "--format", "json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        checks = {c["name"]: c for c in payload["data"]["checks"]}
        self.assertTrue(checks["public_auth"]["ok"])
        self.assertEqual(checks["public_auth"]["data"]["status"], 401)

    def test_deploy_smoke_json_failure_uses_agent_error_envelope(self) -> None:
        with _server(_SmokeHandler) as base_url:
            code, payload, stderr = self._run_cli([
                "deploy-smoke", "--base-url", base_url,
                "--expected-version", "0.5.0", "--format", "json",
            ])

        self.assertEqual(code, 3)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["command"], "deploy-smoke")
        self.assertEqual(payload["error"]["code"], "deploy_smoke_failed")
        self.assertTrue(payload["error"]["recoverable"])
        self.assertIn("expected version 0.5.0", payload["error"]["message"])
        self.assertIn("Check the deployed commit", payload["error"]["next_action"])


if __name__ == "__main__":
    unittest.main()
