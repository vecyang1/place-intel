import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from placeintel import cache, config, language


class LanguageContractTest(unittest.TestCase):
    def test_normalize_language_tag_accepts_safe_bcp47_and_aliases(self) -> None:
        cases = {
            " EN_us ": "en-US",
            "zh-cn": "zh",
            "CN": "zh",
            "chinese": "zh",
            "pt_BR": "pt-BR",
            "sr-Latn-rs": "sr-Latn-RS",
            "fr": "fr",
            "vi": "vi",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(language.normalize_language_tag(raw), expected)

    def test_normalize_language_tag_rejects_prompt_or_path_like_values(self) -> None:
        for raw in ("", "../en", "en<script>", "en; ignore prior", "x" * 36, "en\nUS"):
            with self.subTest(raw=raw):
                self.assertIsNone(language.normalize_language_tag(raw))

    def test_resolve_output_language_respects_precedence_and_auto(self) -> None:
        self.assertEqual(
            language.resolve_output_language(explicit="fr", saved="zh", browser="vi", planner="en").tag,
            "fr",
        )
        self.assertEqual(
            language.resolve_output_language(explicit=None, saved="auto", browser="vi-VN", planner="zh").tag,
            "vi-VN",
        )
        self.assertEqual(
            language.resolve_output_language(explicit=None, saved=None, browser=None, planner="zh").tag,
            "zh",
        )
        self.assertEqual(
            language.resolve_output_language(explicit=None, saved=None, browser=None, planner=None).tag,
            "en",
        )

    def test_translation_target_accepts_common_and_custom_safe_tags(self) -> None:
        for raw, expected in (("vi", "vi"), ("fr-FR", "fr-FR"), ("es", "es"), ("de", "de"), ("zh-CN", "zh")):
            with self.subTest(raw=raw):
                target = language.resolve_translation_target(raw)
                self.assertEqual(target.tag, expected)
                self.assertTrue(target.instruction)

    def test_qa_cache_is_language_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                try:
                    vec = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
                    cache.save_qa(conn, "same question", None, "中文答案", "model", vec, answer_lang="zh")
                    cache.save_qa(conn, "same question", None, "English answer", "model", vec, answer_lang="en")

                    en = cache.find_cached_answer(conn, "same question", vec, None, answer_lang="en")
                    zh = cache.find_cached_answer(conn, "same question", vec, None, answer_lang="zh")
                    fr = cache.find_cached_answer(conn, "same question", vec, None, answer_lang="fr")
                    history = [dict(row) for row in cache.recent_qa(conn)]
                finally:
                    conn.close()

        self.assertEqual(en["answer"], "English answer")
        self.assertEqual(en["answer_lang"], "en")
        self.assertEqual(zh["answer"], "中文答案")
        self.assertIsNone(fr)
        self.assertEqual({row["answer_lang"] for row in history}, {"en", "zh"})

    def test_reports_store_language_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "DB_PATH", Path(tmp) / "placeintel.db"):
                conn = cache.connect()
                try:
                    cache.upsert_place(conn, cache.Place(place_id="p1", name="Place"))
                    cache.save_report(
                        conn, "p1", "generic", "model", {"ok": True}, "# Report", 1,
                        report_lang="fr", evidence_lang="original",
                    )
                    row = cache.latest_report(conn, "p1", "generic", report_lang="fr")
                    miss = cache.latest_report(conn, "p1", "generic", report_lang="zh")
                finally:
                    conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["report_lang"], "fr")
        self.assertEqual(row["evidence_lang"], "original")
        self.assertIsNone(miss)


if __name__ == "__main__":
    unittest.main()
