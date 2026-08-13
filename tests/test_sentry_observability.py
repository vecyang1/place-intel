import json
import unittest
from pathlib import Path
from unittest import mock

from placeintel import config, server


class SentryObservabilityTest(unittest.TestCase):
    def test_redactor_covers_common_credentials_and_private_home_paths(self) -> None:
        home = str(Path.home())
        event = {
            "request": {
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer dummy-bearer-value",
                    "Cookie": "session=dummy-cookie-value",
                },
                "url": "https://dummy-user:dummy-pass@example.invalid/path",
            },
            "extra": {
                "password": "dummy-password-value",
                "message": (
                    "api_key=dummy-query-value "
                    "sk-dummyvectorsecretvalue123456 "
                    "AIzaDummyGoogleSecretValue1234567890 "
                    f"{home}/private/placeintel.db"
                ),
            },
            "token=dummy-key-name": "visible",
        }

        scrubbed = server._scrub_sentry_value(event)
        payload = json.dumps(scrubbed, ensure_ascii=False)

        for marker in (
            "dummy-bearer-value",
            "dummy-cookie-value",
            "dummy-user",
            "dummy-pass",
            "dummy-password-value",
            "dummy-query-value",
            "dummyvectorsecretvalue",
            "DummyGoogleSecretValue",
            "dummy-key-name",
        ):
            self.assertNotIn(marker, payload)
        self.assertNotIn(home, payload)
        self.assertIn("REDACTED", payload)
        self.assertIn("~/private/placeintel.db", payload)

    def test_event_scrubber_keeps_diagnostic_metadata_not_customer_content(self) -> None:
        event = {
            "request": {
                "method": "POST",
                "url": "https://example.invalid/api/ask",
                "data": {"question": "private customer question"},
                "headers": {"Content-Type": "application/json"},
            },
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "failed for private customer question",
                        "module": "placeintel.pipeline",
                    }
                ]
            },
            "extra": {"review_text": "private customer review"},
            "breadcrumbs": {
                "values": [
                    {
                        "type": "default",
                        "category": "request",
                        "level": "info",
                        "message": "private customer question",
                        "data": {"query": "private customer question"},
                    }
                ]
            },
            "user": {"email": "private@example.invalid"},
            "contexts": {
                "trace": {
                    "trace_id": "a" * 32,
                    "span_id": "b" * 16,
                    "op": "http.server",
                    "description": "POST /api/ask private customer question",
                }
            },
        }

        scrubbed = server._scrub_sentry_event(event, {})
        payload = json.dumps(scrubbed, ensure_ascii=False)

        self.assertNotIn("private customer", payload)
        self.assertNotIn("private@example.invalid", payload)
        self.assertNotIn("extra", scrubbed)
        self.assertNotIn("user", scrubbed)
        self.assertEqual(scrubbed["request"], {"method": "POST"})
        self.assertEqual(
            scrubbed["exception"]["values"][0],
            {"type": "RuntimeError", "module": "placeintel.pipeline"},
        )
        breadcrumb = scrubbed["breadcrumbs"]["values"][0]
        self.assertEqual(
            breadcrumb,
            {"type": "default", "category": "request", "level": "info"},
        )
        self.assertEqual(
            scrubbed["contexts"]["trace"],
            {"trace_id": "a" * 32, "span_id": "b" * 16, "op": "http.server"},
        )

    def test_init_applies_scrubber_to_errors_transactions_and_breadcrumbs(self) -> None:
        with mock.patch.object(server.config, "SENTRY_DSN", "https://public@example.invalid/1"), \
                mock.patch("sentry_sdk.init") as sentry_init:
            server._init_sentry()

        options = sentry_init.call_args.kwargs
        self.assertIs(options["before_send"], server._scrub_sentry_event)
        self.assertIn("before_send_transaction", options)
        self.assertIn("before_breadcrumb", options)
        self.assertIs(options["before_send_transaction"], server._scrub_sentry_event)
        self.assertIs(options["before_breadcrumb"], server._scrub_sentry_breadcrumb)
        self.assertFalse(options["send_default_pii"])
        self.assertEqual(options["max_request_body_size"], "never")
        self.assertFalse(options["include_local_variables"])

    def test_sentry_sdk_accepts_the_privacy_options_without_network(self) -> None:
        import sentry_sdk

        client = sentry_sdk.Client(
            dsn=None,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            before_send=server._scrub_sentry_event,
            before_send_transaction=server._scrub_sentry_event,
            before_breadcrumb=server._scrub_sentry_breadcrumb,
        )

        self.assertEqual(client.options["max_request_body_size"], "never")
        self.assertFalse(client.options["include_local_variables"])

    def test_deploy_requires_and_writes_the_dedicated_monitor_token(self) -> None:
        workflow = (config.PROJECT_DIR / ".github/workflows/deploy-contabo.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "PLACEINTEL_MONITOR_TOKEN: ${{ secrets.PLACEINTEL_MONITOR_TOKEN }}",
            workflow,
        )
        self.assertIn("VECTORENGINE_API_KEY PLACEINTEL_MONITOR_TOKEN; do", workflow)
        self.assertIn("printf 'PLACEINTEL_MONITOR_TOKEN=%s\\n'", workflow)

    def test_trace_sample_rate_parser_is_bounded_and_fail_safe(self) -> None:
        parser = getattr(config, "_bounded_sample_rate", None)
        self.assertIsNotNone(parser)
        assert parser is not None
        self.assertEqual(parser("0.25", default=0.1), 0.25)
        self.assertEqual(parser("0", default=0.1), 0.0)
        self.assertEqual(parser("1", default=0.1), 1.0)
        self.assertEqual(parser(None, default=0.1), 0.1)
        self.assertEqual(parser("not-a-number", default=0.1), 0.1)
        self.assertEqual(parser("-0.1", default=0.1), 0.1)
        self.assertEqual(parser("1.1", default=0.1), 0.1)


if __name__ == "__main__":
    unittest.main()
