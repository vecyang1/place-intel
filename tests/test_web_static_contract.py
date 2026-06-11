import re
import unittest
from html import unescape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class WebStaticContractTest(unittest.TestCase):
    def test_no_build_web_files_stay_under_project_budget(self) -> None:
        for path in [WEB / "index.html", WEB / "app.css", WEB / "app.js"]:
            with self.subTest(path=path.name):
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(
                    line_count,
                    800,
                    f"{path.name} has {line_count} lines; AGENTS.md keeps web files below 800",
                )

    def test_mobile_query_textarea_has_readable_height(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        match = re.search(r"textarea\.query-input\s*\{([^}]+)\}", css)
        self.assertIsNotNone(match, "textarea.query-input needs its own height rule")
        body = match.group(1)
        height = re.search(r"min-height:\s*([0-9.]+)em", body)
        self.assertIsNotNone(height, "textarea.query-input should use em min-height")
        self.assertGreaterEqual(float(height.group(1)), 5.0)

    def test_muted_text_tokens_are_not_transparent_on_paper(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        token_block = re.search(r":root\s*\{([^}]+)\}", css, re.S)
        self.assertIsNotNone(token_block)
        for token in ["--ink-70", "--ink-55", "--ink-40"]:
            with self.subTest(token=token):
                line = re.search(rf"{re.escape(token)}:\s*([^;]+);", token_block.group(1))
                self.assertIsNotNone(line)
                self.assertNotIn(
                    "transparent",
                    line.group(1),
                    f"{token} should mix against paper for predictable contrast",
                )

    def test_textarea_placeholder_lines_fit_mobile_width(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for field_id in ["scout-query", "ask-question"]:
            with self.subTest(field_id=field_id):
                match = re.search(rf'id="{field_id}"[\s\S]*?placeholder="([^"]+)"', html)
                self.assertIsNotNone(match)
                placeholder = unescape(match.group(1))
                longest = max(len(line) for line in placeholder.splitlines())
                self.assertLessEqual(longest, 48)

    def test_shell_has_skip_link_main_target_and_named_controls(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertRegex(html, r"<main[^>]+id=\"main\"")
        for field_id in [
            "scout-query", "scout-near", "scout-profile", "scout-top",
            "scout-maxr", "scout-refresh", "scout-noai", "shop-target",
            "shop-near", "shop-profile", "shop-maxr", "shop-refresh",
            "ask-question", "model-select", "model-custom",
        ]:
            with self.subTest(field_id=field_id):
                match = re.search(rf'<(?:input|select|textarea)[^>]+id="{field_id}"[^>]*>', html)
                self.assertIsNotNone(match)
                self.assertRegex(match.group(0), r'\sname="[^"]+"')


if __name__ == "__main__":
    unittest.main()
