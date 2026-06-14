import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import analyze, cache, config, pipeline


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _TranslateModels:
    def __init__(self) -> None:
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        return _Response("通往这里的路有点难走，但景色很漂亮。")


class _TranslateClient:
    def __init__(self) -> None:
        self.models = _TranslateModels()


class ReviewTranslationTest(unittest.TestCase):
    def test_translate_review_uses_reasoning_provider_once_then_cache(self) -> None:
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
                    "reason": {"model": "test-model", "provider": "test-provider"},
                    "embed": {"model": "embed-test", "provider": "test-provider"},
                }
                with mock.patch.object(analyze, "_client", return_value=client), \
                        mock.patch.object(config, "provider_info", return_value=provider):
                    first = pipeline.translate_review("review-vi-1", "zh")
                    second = pipeline.translate_review("review-vi-1", "zh")

        self.assertEqual(client.models.calls, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["text"], "通往这里的路有点难走，但景色很漂亮。")
        self.assertEqual(second["text"], first["text"])
        self.assertEqual(first["source_lang"], "vi")
        self.assertEqual(first["target_lang"], "zh")
        self.assertEqual(first["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
