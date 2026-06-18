import re
import unittest
from html import unescape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class WebStaticContractTest(unittest.TestCase):
    def test_no_build_web_files_stay_under_project_budget(self) -> None:
        for path in [WEB / "index.html", WEB / "app.css", WEB / "app.js", WEB / "i18n.js"]:
            with self.subTest(path=path.name):
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(
                    line_count,
                    800,
                    f"{path.name} has {line_count} lines; AGENTS.md keeps web files below 800",
                )
                if path.name == "app.js":
                    self.assertLessEqual(
                        line_count,
                        780,
                        "app.js should keep at least 19 spare lines for future urgent UX fixes",
                    )

    def test_stream_job_honors_pause_flag(self) -> None:
        # Regression guard (v0.4.36 leak, v0.4.37 fix): a job paused on a hidden tab —
        # including one paused while its startJob POST is still in flight — must not open
        # an EventSource. streamJob must check job.paused before `new EventSource`.
        js = (WEB / "app.js").read_text(encoding="utf-8")
        body = js[js.index("function streamJob"):][:500]
        self.assertIn("new EventSource", body, "streamJob should open the EventSource")
        self.assertLess(
            body.index("paused"),
            body.index("new EventSource"),
            "streamJob must honor job.paused before opening an EventSource (hidden-tab SSE leak)",
        )

    def test_resume_clears_pause_even_mid_post(self) -> None:
        # Companion guard: returning to a tab while the startJob POST is still in flight
        # (job.id is null) must still clear job.paused — otherwise the later
        # streamJob() call is blocked and the job freezes (stuck timeline, disabled submit).
        js = (WEB / "app.js").read_text(encoding="utf-8")
        body = js[js.index("function resumeJobStream"):][:300]
        guard = body[: body.index("job.paused = false")]
        self.assertNotIn(
            "job.id",
            guard,
            "resumeJobStream must clear job.paused independent of job.id (mid-POST tab round-trip must not freeze the job)",
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

    def test_browser_chrome_matches_light_dark_theme(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertRegex(
            html,
            r'<meta name="theme-color" content="[^"]+" media="\(prefers-color-scheme: light\)">',
        )
        self.assertRegex(
            html,
            r'<meta name="theme-color" content="[^"]+" media="\(prefers-color-scheme: dark\)">',
        )
        self.assertRegex(css, r"html\s*\{[^}]*color-scheme:\s*light dark;", re.S)

    def test_accent_buttons_use_on_accent_text_token(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn("--on-accent:", css)
        for selector in [".btn-primary", ".btn-small"]:
            self.assertRegex(
                css,
                rf"{re.escape(selector)}\s*\{{[^}}]*color:\s*var\(--on-accent\);",
            )
            self.assertNotRegex(
                css,
                rf"{re.escape(selector)}\s*\{{[^}}]*color:\s*var\(--paper\);",
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

    def test_placeholders_use_example_pattern_and_ellipsis(self) -> None:
        sources = [
            ("index.html", (WEB / "index.html").read_text(encoding="utf-8")),
            ("app.js", (WEB / "app.js").read_text(encoding="utf-8")),
        ]
        for source_name, source in sources:
            for raw in re.findall(r'(?<!-)placeholder="([^"]+)"', source):
                placeholder = unescape(raw)
                with self.subTest(source=source_name, placeholder=placeholder):
                    self.assertIn("例", placeholder)
                    self.assertTrue(
                        placeholder.rstrip().endswith("…"),
                        "placeholder should end with ellipsis",
                    )

    def test_shell_has_skip_link_main_target_and_named_controls(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertRegex(html, r"<main[^>]+id=\"main\"")
        for field_id in [
            "scout-query", "scout-near", "scout-profile", "scout-top",
            "scout-maxr", "scout-refresh", "scout-noai", "shop-target",
            "shop-near", "shop-profile", "shop-maxr", "shop-refresh",
            "library-search", "library-sort", "library-category", "library-freshness",
            "library-risk", "library-language", "library-cached", "library-report",
            "ask-question", "model-select", "model-custom",
        ]:
            with self.subTest(field_id=field_id):
                match = re.search(rf'<(?:input|select|textarea)[^>]+id="{field_id}"[^>]*>', html)
                self.assertIsNotNone(match)
                self.assertRegex(match.group(0), r'\sname="[^"]+"')

    def test_interrupted_jobs_show_retry_using_cache_action(self) -> None:
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("interrupted", js)
        self.assertIn("data-retry-job", js)
        self.assertIn("用缓存重试", js)

    def test_jobs_use_eventsource_stream_with_polling_fallback(self) -> None:
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("EventSource", js)
        self.assertIn("/events?after=", js)
        self.assertIn("streamJob(kind)", js)
        self.assertIn("pollJob(kind)", js)

    def test_stale_job_submission_cannot_poll_newer_job(self) -> None:
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("state.jobs[kind] !== job", js)

    def test_top_tabs_use_aligned_tracks_and_clear_mode_vocabulary(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "app.css").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        i18n = (WEB / "i18n.js").read_text(encoding="utf-8")
        dynamic_copy = js + i18n

        self.assertIn("侦察新店", html)
        self.assertIn("问缓存", html)
        self.assertRegex(css, r"\.tabs\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)", re.S)
        self.assertRegex(css, r"\.tab::after\s*\{[^}]*left:\s*50%", re.S)
        self.assertIn("问缓存只问已有证据", dynamic_copy)
        self.assertIn("侦察会搜索或刷新地图与评价证据", dynamic_copy)

    def test_locale_catalog_owns_core_ui_language_copy(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        i18n = (WEB / "i18n.js").read_text(encoding="utf-8")

        self.assertIn('/static/i18n.js?v=__PLACEINTEL_VERSION__"', html)
        self.assertIn("PI18N", i18n)
        self.assertIn("supportedUiLocales", i18n)
        self.assertIn("placeintel.languagePreference", i18n)
        self.assertIn("applyStaticText", i18n)
        self.assertIn("initLanguage", js)
        self.assertIn("language_hint", js + i18n)
        self.assertIn("report_lang", js + i18n)
        self.assertIn("renderLanguageControls", js)
        self.assertIn("data-i18n", html)

    def test_photo_ui_uses_lazy_source_images_and_safe_links(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "app.css").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")

        self.assertIn("photoSourcesHtml", js)
        self.assertIn("photo-lightbox", html)
        self.assertIn("photo-lightbox-toolbar", html)
        self.assertIn("photo-lightbox-zoom-in", html)
        self.assertIn("photo-lightbox-prev", html)
        self.assertIn("photo-lightbox-next", html)
        self.assertIn("openPhotoLightbox", js)
        self.assertIn("setPhotoZoom", js)
        self.assertIn("shiftPhoto", js)
        self.assertIn("wheel", js)
        self.assertIn("data-photo-zoom", js + html)
        self.assertIn("data-photo-step", html)
        self.assertIn("data-photo-url", js)
        self.assertIn('loading="lazy"', js)
        self.assertIn('decoding="async"', js)
        self.assertNotIn('target="_blank" rel="noopener noreferrer"><img class="source-photo-img"', js)
        self.assertIn("source photo", js)
        self.assertIn("review photo", js)
        self.assertRegex(css, r"\.source-photo\s*\{[^}]*aspect-ratio:\s*4\s*/\s*3", re.S)
        self.assertIn("cursor: zoom-in", css)
        self.assertIn("object-fit: cover", css)
        self.assertIn("background: rgba(0, 0, 0, 0.86)", css)
        self.assertIn("overflow: auto", css)


if __name__ == "__main__":
    unittest.main()
