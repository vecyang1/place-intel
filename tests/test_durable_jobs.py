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

from placeintel import cache, config, server


class DurableJobsTest(unittest.TestCase):
    def _patch_db(self):
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "placeintel.db"
        patcher = mock.patch.object(config, "DB_PATH", db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        return db_path

    def test_start_scout_persists_job_before_thread_start(self) -> None:
        self._patch_db()

        class NoStartThread:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def start(self):
                return None

        with mock.patch.object(server.threading, "Thread", NoStartThread):
            response = server.start_scout(
                server.ScoutRequest(query="guitar lesson", near="Hoi An")
            )

        job_id = response["job_id"]
        conn = cache.connect()
        try:
            job = cache.get_job(conn, job_id)
        finally:
            conn.close()
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["kind"], "scout")
        self.assertEqual(job["request"]["query"], "guitar lesson")
        self.assertEqual(job["events"], [])

    def test_job_events_are_persisted_append_only(self) -> None:
        self._patch_db()
        job_id, on_event = server._new_job("shop", {"target": "Lazy Gecko"})

        on_event({"t": 1.0, "stage": "search", "msg": "first"})
        on_event({"t": 2.0, "stage": "done", "msg": "second", "data": {"ok": True}})

        conn = cache.connect()
        try:
            job = cache.get_job(conn, job_id)
        finally:
            conn.close()
        self.assertEqual([event["msg"] for event in job["events"]], ["first", "second"])
        self.assertEqual(job["events"][1]["data"], {"ok": True})
        self.assertEqual([event["id"] for event in job["events"]], [1, 2])

    def test_job_events_after_id_supports_resume(self) -> None:
        self._patch_db()
        conn = cache.connect()
        try:
            cache.create_job(conn, "job-test", "scout", {"query": "x"}, process_id=111)
            cache.append_job_event(conn, "job-test", {"t": 1.0, "stage": "plan", "msg": "first"})
            cache.append_job_event(conn, "job-test", {"t": 2.0, "stage": "search", "msg": "second"})
            resumed = cache.job_events_after(conn, "job-test", after_id=1)
        finally:
            conn.close()

        self.assertEqual([event["msg"] for event in resumed], ["second"])
        self.assertEqual(resumed[0]["id"], 2)

    def test_api_job_status_reads_durable_state(self) -> None:
        self._patch_db()
        conn = cache.connect()
        try:
            cache.create_job(conn, "job-test", "scout", {"query": "x"}, process_id=111)
            cache.append_job_event(conn, "job-test", {"t": 1.0, "stage": "plan", "msg": "ok"})
            cache.finish_job(conn, "job-test", result={"query": "x", "reports": []})
        finally:
            conn.close()

        response = TestClient(server.app).get("/api/jobs/job-test")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["result"], {"query": "x", "reports": []})
        self.assertEqual(payload["events"][0]["stage"], "plan")

    def test_api_job_event_stream_replays_after_id_as_sse(self) -> None:
        self._patch_db()
        conn = cache.connect()
        try:
            cache.create_job(conn, "job-stream", "scout", {"query": "x"}, process_id=111)
            cache.append_job_event(conn, "job-stream", {"t": 1.0, "stage": "plan", "msg": "first"})
            cache.append_job_event(conn, "job-stream", {"t": 2.0, "stage": "done", "msg": "second"})
            cache.finish_job(conn, "job-stream", result={"query": "x"})
        finally:
            conn.close()

        response = TestClient(server.app).get("/api/jobs/job-stream/events", params={"after": 1})

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertNotIn("id: 1\n", response.text)
        self.assertIn("id: 2\n", response.text)
        self.assertIn('"stage":"done"', response.text)

    def test_api_job_event_stream_resumes_from_last_event_id_header(self) -> None:
        self._patch_db()
        conn = cache.connect()
        try:
            cache.create_job(conn, "job-stream", "scout", {"query": "x"}, process_id=111)
            cache.append_job_event(conn, "job-stream", {"t": 1.0, "stage": "plan", "msg": "first"})
            cache.append_job_event(conn, "job-stream", {"t": 2.0, "stage": "search", "msg": "second"})
            cache.finish_job(conn, "job-stream", result={"query": "x"})
        finally:
            conn.close()

        response = TestClient(server.app).get(
            "/api/jobs/job-stream/events",
            headers={"Last-Event-ID": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("id: 1\n", response.text)
        self.assertIn("id: 2\n", response.text)

    def test_startup_marks_old_running_jobs_interrupted(self) -> None:
        self._patch_db()
        conn = cache.connect()
        try:
            cache.create_job(conn, "old-job", "shop", {"target": "Lazy Gecko"}, process_id=111)
        finally:
            conn.close()

        with mock.patch.object(server.os, "getpid", return_value=222), \
                mock.patch.object(server.log, "warning"):
            with TestClient(server.app):
                pass

        conn = cache.connect()
        try:
            job = cache.get_job(conn, "old-job")
        finally:
            conn.close()
        self.assertEqual(job["status"], "interrupted")
        self.assertIn("retry", job["retry_hint"].lower())


if __name__ == "__main__":
    unittest.main()
