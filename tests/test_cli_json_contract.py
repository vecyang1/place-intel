import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cache, cli, config, pipeline


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

    def test_schema_format_json_lists_core_agent_contracts(self) -> None:
        code, stdout, stderr = self._run_cli(["schema", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "schema")
        schemas = payload["data"]["schemas"]
        self.assertIn("cli_envelope", schemas)
        self.assertIn("health", schemas)
        self.assertIn("pipeline_result", schemas)
        self.assertIn("job_event", schemas)
        self.assertIn("backup_manifest", schemas)
        self.assertIn("deploy_smoke", schemas)
        self.assertIn("deep", schemas["health"]["properties"]["mode"]["enum"])
        health_item_required = schemas["health"]["properties"]["checks"]["items"]["required"]
        self.assertIn("next_action", health_item_required)
        self.assertIn("reports", schemas["pipeline_result"]["required"])
        self.assertEqual(schemas["job_event"]["required"], ["t", "stage", "msg"])
        self.assertIn("checks", schemas["deploy_smoke"]["required"])

    def test_ask_format_json_wraps_answer_and_preserves_scope_flags(self) -> None:
        answer = {
            "answer": "D'Class has the strongest beginner evidence.",
            "cached": True,
            "created_at": 100.0,
            "matched": "Which guitar shop is beginner friendly?",
            "model": "test-model",
            "provider": "VectorEngine",
        }
        with mock.patch("placeintel.pipeline.ask", return_value=answer) as ask:
            code, stdout, stderr = self._run_cli([
                "ask", "Which shop?", "--place", "place-1", "--fresh", "--format", "json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        ask.assert_called_once_with(
            "Which shop?", place_id="place-1", top_k=20, report_lang="zh", no_cache=True,
        )
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "ask")
        self.assertEqual(payload["data"], {**answer, "place_id": "place-1"})
        self.assertEqual(payload["data"]["place_id"], "place-1")

    def test_ask_format_json_empty_cache_exits_with_machine_error(self) -> None:
        answer = {
            "answer": "Cache is empty (or nothing relevant) — run a scout first.",
            "cached": False,
            "created_at": 100.0,
            "model": "test-model",
            "provider": "VectorEngine",
        }
        with mock.patch("placeintel.pipeline.ask", return_value=answer):
            code, stdout, stderr = self._run_cli(["ask", "Which shop?", "--format", "json"])

        self.assertEqual(code, 5)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "cache_empty")
        self.assertEqual(payload["data"], answer)

    def test_scout_format_ndjson_emits_events_and_final_result(self) -> None:
        result = pipeline.ScoutResult(
            query="guitar lesson",
            location="Hoi An",
            profile="generic",
            places=[{"place_id": "place-1", "name": "D'Class Guitar"}],
            reports=[{"place_id": "place-1", "name": "D'Class Guitar", "md": "# Report"}],
        )

        def fake_scout(**kwargs):
            kwargs["on_event"]({"t": 123.0, "stage": "plan", "msg": "planned"})
            return result

        with mock.patch("placeintel.pipeline.scout", side_effect=fake_scout) as scout:
            code, stdout, stderr = self._run_cli([
                "scout", "guitar lesson", "--near", "Hoi An", "--format", "ndjson",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        scout.assert_called_once()
        lines = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(lines[0]["type"], "event")
        self.assertEqual(lines[0]["stage"], "plan")
        self.assertEqual(lines[0]["msg"], "planned")
        self.assertEqual(lines[-1]["type"], "result")
        self.assertTrue(lines[-1]["ok"])
        self.assertEqual(lines[-1]["command"], "scout")
        self.assertEqual(lines[-1]["data"]["result"]["query"], "guitar lesson")

    def test_shop_format_json_prints_only_final_result(self) -> None:
        result = pipeline.ScoutResult(
            query="Lazy Gecko Cafe",
            location="Hoi An",
            profile="generic",
            mode="single",
            places=[{"place_id": "place-1", "name": "Lazy Gecko Cafe"}],
            reports=[{"place_id": "place-1", "name": "Lazy Gecko Cafe", "md": "# Report"}],
        )

        def fake_shop(**kwargs):
            if kwargs["on_event"]:
                kwargs["on_event"]({"t": 123.0, "stage": "search", "msg": "would be hidden"})
            return result

        with mock.patch("placeintel.pipeline.scout_single", side_effect=fake_shop) as shop:
            code, stdout, stderr = self._run_cli([
                "shop", "Lazy Gecko Cafe", "--near", "Hoi An", "--format", "json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        shop.assert_called_once()
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "shop")
        self.assertEqual(payload["data"]["result"]["mode"], "single")
        self.assertNotIn("would be hidden", stdout)

    def test_favorite_and_favorites_commands_are_machine_readable(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="place-1", name="D'Class Guitar"))
        conn.close()

        code, stdout, stderr = self._run_cli(["favorite", "place-1", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "favorite")
        self.assertTrue(payload["data"]["favorite"]["favorite"])
        self.assertFalse(payload["data"]["favorite"]["refresh_enabled"])

        code, stdout, stderr = self._run_cli(["favorites", "--format", "json"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "favorites")
        self.assertEqual(payload["data"]["favorites"][0]["place_id"], "place-1")

    def test_refresh_favorites_dry_run_lists_only_opt_in_due_places(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="due", name="Due Guitar"))
        cache.upsert_place(conn, cache.Place(place_id="manual", name="Manual Guitar"))
        cache.set_favorite(conn, "due", True, refresh_enabled=True, max_reviews=90)
        cache.set_favorite(conn, "manual", True, refresh_enabled=False)
        conn.close()

        health = {"ok": True, "providers": {"embed": {}, "reason": {}}, "errors": []}
        with mock.patch.object(cli.doctor, "cheap_health", return_value=health):
            code, stdout, stderr = self._run_cli([
                "refresh-favorites", "--dry-run", "--format", "json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "refresh-favorites")
        self.assertTrue(payload["data"]["dry_run"])
        self.assertEqual([p["place_id"] for p in payload["data"]["candidates"]], ["due"])
        self.assertEqual(payload["data"]["candidates"][0]["max_reviews"], 90)

    def test_refresh_favorites_run_streams_events_and_keeps_old_data_on_failure(self) -> None:
        conn = self._with_temp_db()
        cache.upsert_place(conn, cache.Place(place_id="due", name="Due Guitar"))
        cache.upsert_reviews(conn, [
            cache.Review(review_id="old-review", place_id="due", text="old useful review")
        ])
        cache.set_favorite(conn, "due", True, refresh_enabled=True, max_reviews=75)
        conn.close()

        def fail_refresh(**kwargs):
            kwargs["on_event"]({"t": 10.0, "stage": "reviews", "msg": "starting"})
            raise RuntimeError("scraper unavailable")

        health = {"ok": True, "providers": {"embed": {}, "reason": {}}, "errors": []}
        with mock.patch.object(cli.doctor, "cheap_health", return_value=health), \
                mock.patch("placeintel.pipeline.scout_single", side_effect=fail_refresh) as refresh:
            code, stdout, stderr = self._run_cli([
                "refresh-favorites", "--run", "--format", "ndjson",
            ])

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        refresh.assert_called_once()
        kwargs = refresh.call_args.kwargs
        self.assertEqual(kwargs["target"], "Due Guitar")
        self.assertTrue(kwargs["refresh"])
        self.assertEqual(kwargs["max_reviews"], 75)
        lines = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(lines[0]["type"], "event")
        self.assertEqual(lines[-1]["type"], "result")
        self.assertFalse(lines[-1]["ok"])
        conn = cache.connect()
        try:
            self.assertIsNotNone(cache.get_place(conn, "due"))
            self.assertEqual(len(cache.get_reviews(conn, "due")), 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
