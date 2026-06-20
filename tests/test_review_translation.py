import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import analyze, cache, config, pipeline


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _TranslateModels:
    def __init__(self, text: str = "通往这里的路有点难走，但景色很漂亮。") -> None:
        self.calls = 0
        self.models = []
        self.kwargs = []
        self.text = text

    def generate_content(self, **kwargs):
        self.calls += 1
        self.models.append(kwargs.get("model"))
        self.kwargs.append(kwargs)
        return _Response(self.text)


class _TranslateClient:
    def __init__(self, text: str = "通往这里的路有点难走，但景色很漂亮。") -> None:
        self.models = _TranslateModels(text)


class ReviewTranslationTest(unittest.TestCase):
    def test_translation_model_defaults_to_flash_lite_and_stays_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            with mock.patch.object(config, "SETTINGS_PATH", settings), \
                    mock.patch.dict("os.environ", {
                        "PLACEINTEL_REASON_MODEL": "gemini-3-flash-preview",
                        "PLACEINTEL_TRANSLATION_MODEL": "",
                    }, clear=False):
                self.assertEqual(config.translation_model(), "gemini-3.1-flash-lite")

    def test_translate_review_uses_translation_model_once_then_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="View Point"))
                cache.upsert_reviews(conn, [
                    cache.Review(
                        review_id="review-vi-1",
                        place_id="place-1",
                        rating=5,
                        text="Đường vào hơi khó nhưng cảnh rất đẹp.",
                        lang="vi",
                        review_date="2026-06-01",
                    )
                ])
                conn.close()

                client = _TranslateClient()
                provider = {
                    "reason": {"model": "expensive-model", "provider": "test-provider"},
                    "translate": {"model": "gemini-3.1-flash-lite", "provider": "test-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                changed_provider = {
                    "reason": {"model": "expensive-model", "provider": "other-provider"},
                    "translate": {"model": "gemini-3.1-flash-lite", "provider": "other-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=provider):
                    first = pipeline.translate_review("review-vi-1", "cn")
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=changed_provider):
                    second = pipeline.translate_review("review-vi-1", "zh")

        self.assertEqual(client.models.calls, 1)
        self.assertEqual(client.models.models, ["gemini-3.1-flash-lite"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["text"], "通往这里的路有点难走，但景色很漂亮。")
        self.assertEqual(second["text"], first["text"])
        self.assertEqual(first["source_lang"], "vi")
        self.assertEqual(first["target_lang"], "zh")
        self.assertEqual(first["model"], "gemini-3.1-flash-lite")
        self.assertEqual(first["provider"], "test-provider")
        self.assertEqual(second["provider"], "test-provider")

    def test_translate_review_accepts_non_zh_en_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="View Point"))
                cache.upsert_reviews(conn, [
                    cache.Review(
                        review_id="review-en-1",
                        place_id="place-1",
                        rating=5,
                        text="Helpful owner and transparent prices.",
                        lang="en",
                    )
                ])
                conn.close()

                client = _TranslateClient()
                provider = {
                    "reason": {"model": "expensive-model", "provider": "test-provider"},
                    "translate": {"model": "gemini-3.1-flash-lite", "provider": "test-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=provider):
                    vi = pipeline.translate_review("review-en-1", "vi")
                    fr = pipeline.translate_review("review-en-1", "fr-FR")

        self.assertEqual(client.models.calls, 2)
        self.assertEqual(vi["target_lang"], "vi")
        self.assertEqual(fr["target_lang"], "fr-FR")
        self.assertEqual(vi["source_lang"], "en")

    def test_translate_review_rejects_unsafe_target_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="View Point"))
                cache.upsert_reviews(conn, [
                    cache.Review(
                        review_id="review-en-1",
                        place_id="place-1",
                        rating=5,
                        text="Helpful owner and transparent prices.",
                        lang="en",
                    )
                ])
                conn.close()

                client = _TranslateClient()
                with mock.patch.object(analyze, "_client", return_value=client):
                    with self.assertRaises(ValueError):
                        pipeline.translate_review("review-en-1", "../zh")

        self.assertEqual(client.models.calls, 0)

    def test_translate_report_uses_translation_model_once_then_cache(self) -> None:
        source_md = "# Hoian Flow Report\n\nVerdict: verify pricing in person."
        translated_md = "# Hoian Flow 报告\n\n结论：到店当面确认价格。"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="Hoian Flow"))
                cache.save_report(
                    conn,
                    "place-1",
                    "generic",
                    "reason-model",
                    {"verdict": "verify pricing in person"},
                    source_md,
                    10,
                    report_lang="en",
                    evidence_lang="report",
                )
                report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
                conn.close()

                client = _TranslateClient(translated_md)
                provider = {
                    "reason": {"model": "expensive-model", "provider": "test-provider"},
                    "translate": {"model": "gemini-3.1-flash-lite", "provider": "test-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                changed_provider = {
                    "reason": {"model": "expensive-model", "provider": "other-provider"},
                    "translate": {"model": "gemini-3.1-flash-lite", "provider": "other-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=provider):
                    first = pipeline.translate_report(report_id, "zh")
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=changed_provider):
                    second = pipeline.translate_report(report_id, "zh")
                conn = cache.connect()
                original = conn.execute("SELECT report_md FROM reports WHERE id=?", (report_id,)).fetchone()["report_md"]
                conn.close()

        self.assertEqual(client.models.calls, 1)
        self.assertEqual(client.models.models, ["gemini-3.1-flash-lite"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["md"], translated_md)
        self.assertEqual(second["md"], translated_md)
        self.assertEqual(first["source_lang"], "en")
        self.assertEqual(first["target_lang"], "zh")
        self.assertEqual(first["model"], "gemini-3.1-flash-lite")
        self.assertEqual(first["provider"], "test-provider")
        self.assertEqual(second["provider"], "test-provider")
        self.assertEqual(original, source_md)
        prompt = client.models.kwargs[0]
        self.assertIn("Target language tag: zh", prompt["contents"])
        self.assertIn("Return only translated markdown", prompt["config"].system_instruction)

    def test_translate_report_rejects_unsafe_target_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                cache.upsert_place(conn, cache.Place(place_id="place-1", name="Hoian Flow"))
                cache.save_report(conn, "place-1", "generic", "reason-model", {}, "# Report", 1)
                report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
                conn.close()

                client = _TranslateClient("# 中文报告")
                with mock.patch.object(analyze, "_client", return_value=client):
                    with self.assertRaises(ValueError):
                        pipeline.translate_report(report_id, "../zh")

        self.assertEqual(client.models.calls, 0)


if __name__ == "__main__":
    unittest.main()
