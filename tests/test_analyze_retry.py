import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import analyze, cache


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _FlakyModels:
    def __init__(self, response_text: str) -> None:
        self.attempts = 0
        self.response_text = response_text

    def generate_content(self, **_kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise TimeoutError("temporary reasoning timeout")
        return _Response(self.response_text)


class _FlakyClient:
    def __init__(self, response_text: str) -> None:
        self.models = _FlakyModels(response_text)


def _report_json() -> str:
    return json.dumps({
        "place_summary": "Useful summary.",
        "dimensions": {
            "red_flags": {
                "title": "Red flags",
                "findings": [],
            },
        },
        "negotiation_baseline": "No clear price.",
        "walk_in_brief": ["Ask first."],
        "verdict": "go-with-caution",
    })


class AnalyzeRetryTest(unittest.TestCase):
    def test_analyze_place_retries_transient_report_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            cache.upsert_place(conn, cache.Place(
                place_id="flaky-report",
                name="Flaky Report Cafe",
                review_count=1,
                source="test",
            ))
            cache.upsert_reviews(conn, [
                cache.Review(
                    review_id="flaky-report-1",
                    place_id="flaky-report",
                    rating=5,
                    text="Helpful staff and clear price.",
                    review_date="2026-01-01",
                )
            ])
            profile = {
                "name": "generic",
                "dimensions": {"red_flags": {"title": "Red flags", "goal": "Risks"}},
                "output_extras": {"walk_in_brief": "One practical line."},
            }
            client = _FlakyClient(_report_json())

            with mock.patch.object(analyze, "_client", return_value=client), \
                    mock.patch.object(analyze.time, "sleep", return_value=None), \
                    mock.patch.object(analyze.log, "warning"):
                report, md = analyze.analyze_place(conn, "flaky-report", profile, "en")

            self.assertEqual(client.models.attempts, 2)
            self.assertEqual(report["verdict"], "go-with-caution")
            self.assertIn("Flaky Report Cafe", md)
            saved = cache.latest_report(conn, "flaky-report", "generic")
            self.assertIsNotNone(saved)
            conn.close()

    def test_digest_chunk_retries_transient_generation_failure(self) -> None:
        client = _FlakyClient("fact [2026-01-01|★5] helpful")
        rows = [{
            "text": "Helpful staff.",
            "rating": 5,
            "author": "A",
            "review_date": "2026-01-01",
            "owner_response": None,
        }]

        with mock.patch.object(analyze, "_client", return_value=client), \
                mock.patch.object(analyze.time, "sleep", return_value=None), \
                mock.patch.object(analyze.log, "warning"):
            digest = analyze._digest_chunk("Flaky Report Cafe", rows, 1, 1, "en", "report")

        self.assertEqual(client.models.attempts, 2)
        self.assertIn("helpful", digest)


if __name__ == "__main__":
    unittest.main()
