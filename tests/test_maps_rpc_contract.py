"""Contract tests for the qv9Egd reviews RPC client.

The fixture is a REAL captured response with personal data redacted, not a
hand-written one. That matters: both bugs this module exists to survive live in
the envelope, and a fixture written from a description of the format would have
had neither. Specifically it keeps

  * a length prefix that does NOT match its frame (the real capture said 36757
    for a 36,852-char / 36,890-byte frame), and
  * multibyte UTF-8 review text, which is why byte-vs-character slicing differ.

`vecyang1/place-intel` is a public mirror, so reviewer names, profile URLs, photo
URLs, contributor ids and review text are substituted. The rating spread is kept
verbatim, because an all-5s fixture would let a wrong rating path pass.
"""
import os
import re
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401  — pins DATA_DIR before placeintel imports

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from placeintel import maps_rpc  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "maps_rpc_qv9Egd_page.txt"
EMPTY_ENVELOPE = b")]}'\n\n27\n[[\"wrb.fr\",\"qv9Egd\",null,null,null,[],\"generic\"]]\n"


class ParsePageTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.page = maps_rpc.parse_page(self.raw)

    def test_parses_the_captured_envelope(self):
        self.assertTrue(self.page.has_payload)
        self.assertEqual(len(self.page.reviews), 10)
        self.assertTrue(self.page.next_cursor)

    def test_length_prefix_in_fixture_is_wrong_and_parsing_survives_it(self):
        """The regression that made a healthy 36 KB response read as 0 reviews."""
        text = self.raw.decode("utf-8")
        prefix = int(text.split("\n")[2])
        frame = text.split("\n")[3]
        self.assertNotEqual(prefix, len(frame),
                            "fixture no longer exercises the stale-prefix hazard")
        self.assertNotEqual(prefix, len(frame.encode("utf-8")),
                            "fixture no longer exercises the stale-prefix hazard")
        self.assertTrue(self.page.has_payload)

    def test_fixture_carries_multibyte_content(self):
        self.assertNotEqual(len(self.raw), len(self.raw.decode("utf-8")),
                            "a pure-ASCII fixture cannot distinguish byte from char slicing")

    def test_rating_path_is_discriminating_not_all_fives(self):
        ratings = [r.rating for r in self.page.reviews]
        self.assertEqual(len(ratings), 10)
        self.assertGreater(len(set(ratings)), 1,
                           "an all-identical rating column would pass with a wrong path")
        self.assertIn(3, ratings)
        for value in ratings:
            self.assertIn(value, range(1, 6))

    def test_core_fields_present(self):
        for review in self.page.reviews:
            self.assertTrue(review.review_id)
            self.assertTrue(review.author)
        self.assertTrue(any(r.text for r in self.page.reviews))

    def test_absent_text_is_none_not_empty_string(self):
        blanks = [r for r in self.page.reviews if r.text is None]
        self.assertTrue(blanks, "fixture should keep one rating-only review")
        self.assertIsNone(blanks[0].text)
        self.assertIsNotNone(blanks[0].rating)

    def test_both_review_id_namespaces_parse(self):
        prefixes = {r.review_id[:3] for r in self.page.reviews if r.review_id}
        self.assertGreater(len(prefixes), 1,
                           "Google emits two id encodings; the fixture must hold both")


class EmptyEnvelopeTests(unittest.TestCase):
    """Every failure of this RPC is HTTP 200 with an empty envelope: a wrong
    bgkey, missing cookies, a non-browser UA, or a page size over 20. Status
    codes carry no signal, so the parser must make the distinction."""

    def test_empty_envelope_is_not_an_exception_and_not_a_success(self):
        page = maps_rpc.parse_page(EMPTY_ENVELOPE)
        self.assertFalse(page.has_payload)
        self.assertEqual(page.reviews, ())
        self.assertIsNone(page.next_cursor)

    def test_garbage_does_not_raise(self):
        self.assertFalse(maps_rpc.parse_page(b"not json at all").has_payload)
        self.assertFalse(maps_rpc.parse_page(b"").has_payload)


class BuildBodyTests(unittest.TestCase):
    def setUp(self):
        inner = ('[[["0xA:0xB"],null],[10,\\"CjEabc0123456789012345678901:20\\"],'
                 'null,null,["ei",null,null,null,null,null,81]]')
        outer = f'[[["qv9Egd","{inner}",null,"generic"]]]'
        self.template = "f.req=" + urllib.parse.quote(outer, safe="") + "&"

    def test_cursor_swap_changes_only_the_cursor(self):
        new = maps_rpc.build_body(self.template, cursor="CjEzzz0123456789012345678901:40")
        before = urllib.parse.unquote(self.template)
        after = urllib.parse.unquote(new)
        self.assertIn("CjEzzz0123456789012345678901:40", after)
        self.assertNotIn("CjEabc0123456789012345678901:20", after)
        self.assertEqual(before.replace("CjEabc0123456789012345678901:20", "X"),
                         after.replace("CjEzzz0123456789012345678901:40", "X"))

    def test_page_size_over_the_measured_ceiling_is_refused_locally(self):
        """Measured: 25/30/40/50/100/200 all return an EMPTY HTTP 200. Sending
        one would report success and yield nothing, so refuse before the wire."""
        maps_rpc.build_body(self.template, page_size=20)
        for size in (21, 25, 50, 100, 200):
            with self.assertRaises(ValueError):
                maps_rpc.build_body(self.template, page_size=size)

    def test_cursor_of_reads_the_template(self):
        self.assertEqual(maps_rpc.cursor_of(self.template),
                         "CjEabc0123456789012345678901:20")

    def test_template_without_page_argument_raises(self):
        with self.assertRaises(maps_rpc.MapsRpcError):
            maps_rpc.build_body("f.req=%5B%5D&")


class FeatureIdentityTests(unittest.TestCase):
    """The landed-listing guard.

    A scrape that lands on a different shop of a similar name reports success
    and stores the wrong reviews — measured 2026-08-31 as 314 rows sharing 3 of
    291 texts with the page they claimed to come from. The RPC does not fix that
    by itself; it faithfully answers about whatever feature id the captured
    `f.req` names. What makes the failure loud is that the request STATES the id,
    so it can be compared with the one the caller's URL asked for.
    """

    def setUp(self):
        inner = ('[[["0x314a443465a12319:0x5daa3b5a1ada17ce"],null],'
                 '[10,\\"CjEabc:20\\"],null,null,["ei"]]')
        self.template = "f.req=" + urllib.parse.quote(
            f'[[["qv9Egd","{inner}",null,"generic"]]]', safe="") + "&"

    def test_reads_the_feature_id_the_request_actually_asks_about(self):
        self.assertEqual(maps_rpc.feature_id_of(self.template),
                         "0x314a443465a12319:0x5daa3b5a1ada17ce")

    def test_absent_feature_id_is_none_not_a_guess(self):
        self.assertIsNone(maps_rpc.feature_id_of("f.req=%5B%5D&"))

    def test_normalisation_survives_case_and_leading_zeros(self):
        self.assertEqual(
            maps_rpc.normalize_feature_id("0X314A443465A12319:0X05DAA3B5A1ADA17CE"),
            maps_rpc.normalize_feature_id("0x314a443465a12319:0x5daa3b5a1ada17ce"),
        )

    def test_non_hex_pair_normalises_to_none(self):
        for junk in ("", None, "ChIJGSOhZTRESjERzhfaGlo7ql0", "0x314a443465a12319",
                     "notahex:alsonot"):
            self.assertIsNone(maps_rpc.normalize_feature_id(junk))

    def test_unknown_is_never_a_match(self):
        """Absent is not equal. A missing id must not read as agreement, or the
        guard passes exactly when it has nothing to check."""
        real = "0x314a443465a12319:0x5daa3b5a1ada17ce"
        self.assertTrue(maps_rpc.same_feature(real, real.upper()))
        self.assertFalse(maps_rpc.same_feature(real, None))
        self.assertFalse(maps_rpc.same_feature(None, real))
        self.assertFalse(maps_rpc.same_feature(None, None))
        self.assertFalse(
            maps_rpc.same_feature(real, "0x314a455ad6407235:0xe121f190cbc130e7"))

    def test_reads_the_expected_id_out_of_a_real_maps_url(self):
        """The other half of the guard: what the CALLER asked for. Both sides go
        through one normaliser so they cannot disagree about formatting."""
        url = ("https://maps.google.com?q=Vu+Binh+Exchange+%26+ATM&"
               "ftid=0x314a455ad6407235:0xe121f190cbc130e7&entry=gps")
        self.assertEqual(maps_rpc.feature_id_in(url),
                         "0x314a455ad6407235:0xe121f190cbc130e7")
        self.assertEqual(
            maps_rpc.feature_id_in("/maps/place/X/data=!4m5!1s0x314A455AD6407235:0xE121F190CBC130E7"),
            "0x314a455ad6407235:0xe121f190cbc130e7")
        self.assertIsNone(maps_rpc.feature_id_in(
            "https://www.google.com/maps/place/?q=place_id:ChIJGSOhZTRESjERzhfaGlo7ql0"))
        self.assertIsNone(maps_rpc.feature_id_in(None))

    def test_cursor_offset_is_how_far_into_the_list_a_template_starts(self):
        """The bootstrap captures a request mid-scroll, so its cursor carries an
        offset and a walk from it silently SKIPS everything before it. Measured:
        1,385 of 1,395 reviews, which reads as Google returning fewer."""
        self.assertEqual(maps_rpc.cursor_offset("CjEabc:20"), 20)
        self.assertEqual(maps_rpc.cursor_offset("CjEabc:0"), 0)
        self.assertIsNone(maps_rpc.cursor_offset("CjEabcNoOffset"))
        self.assertIsNone(maps_rpc.cursor_offset(None))


class RequiredHeaderTests(unittest.TestCase):
    """One-at-a-time ablation measured these three as load-bearing; dropping
    X-Same-Domain, Referer or x-maps-diversion-context-bin changed nothing."""

    def test_flags_each_load_bearing_header(self):
        full = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": "Mozilla/5.0", "X-maps-bgkey": "!abc"}
        self.assertEqual(maps_rpc.missing_headers(full), ())
        for drop in ("Content-Type", "User-Agent", "X-maps-bgkey"):
            partial = {k: v for k, v in full.items() if k != drop}
            self.assertEqual(maps_rpc.missing_headers(partial), (drop,))

    def test_header_check_is_case_insensitive(self):
        self.assertEqual(maps_rpc.missing_headers(
            {"content-type": "x", "user-agent": "y", "x-maps-bgkey": "z"}), ())


class WalkTests(unittest.TestCase):
    def setUp(self):
        inner = ('[[["0xA:0xB"],null],[10,\\"CjEabc0123456789012345678901:20\\"],null]')
        self.template = "f.req=" + urllib.parse.quote(
            f'[[["qv9Egd","{inner}",null,"generic"]]]', safe="") + "&"
        self.raw = FIXTURE.read_bytes()

    def test_walk_stops_when_cursor_stops_advancing(self):
        """A cursor that is accepted and ignored returns a full, healthy page
        forever. Without this guard the walk never terminates and every page
        looks like a success."""
        stats = maps_rpc.WalkStats()
        out = list(maps_rpc.walk(lambda body: self.raw, self.template, stats=stats))
        self.assertEqual(len(out), 10)
        self.assertEqual(stats.pages, 2)
        self.assertIn("no new reviews", stats.stopped_because)

    def test_walk_stops_on_empty_envelope(self):
        stats = maps_rpc.WalkStats()
        out = list(maps_rpc.walk(lambda body: EMPTY_ENVELOPE, self.template, stats=stats))
        self.assertEqual(out, [])
        self.assertEqual(stats.empty_pages, 1)
        self.assertIn("empty envelope", stats.stopped_because)

    def test_walk_honours_max_reviews(self):
        stats = maps_rpc.WalkStats()
        out = list(maps_rpc.walk(lambda body: self.raw, self.template,
                                 max_reviews=4, stats=stats))
        self.assertEqual(len(out), 4)
        self.assertEqual(stats.stopped_because, "max_reviews reached")

    def test_walk_advances_the_cursor_between_pages(self):
        seen_bodies = []

        def post(body):
            seen_bodies.append(body)
            return self.raw if len(seen_bodies) == 1 else EMPTY_ENVELOPE

        list(maps_rpc.walk(post, self.template))
        self.assertEqual(len(seen_bodies), 2)
        self.assertNotEqual(seen_bodies[0], seen_bodies[1])
        page_cursor = maps_rpc.parse_page(self.raw).next_cursor
        self.assertEqual(maps_rpc.cursor_of(seen_bodies[1]), page_cursor)


class WorkerEntryPointTests(unittest.TestCase):
    """The usage line is documentation that ships inside the program, and it is
    the first thing a new reader sees. Measured: an `except BaseException`
    top-level reporter swallowed argparse's SystemExit, so `--help` printed a
    traceback and exited 1. Nothing else in the suite could have seen that,
    because it only happens through the real entry point.

    Graded against `python -m placeintel.maps_rpc_fetch` — the ONE entry point.
    It used to grade `scripts/maps_rpc_probe.py`, a second bootstrap that opened
    a browser against Google with no identity check, no `hl=en` forcing, and a
    `chdir` into the root-owned vendor tree that had already been fixed in the
    real path. A test pointed at the shim rather than the thing is how the shim
    survives: it looked covered.
    """

    def _run(self, *argv, cwd):
        import subprocess
        env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
        return subprocess.run(
            [sys.executable, "-m", "placeintel.maps_rpc_fetch", *argv],
            cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60)

    def test_help_exits_zero_from_a_neutral_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as neutral:
            result = self._run("--help", cwd=neutral)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("usage:", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_the_command_its_usage_line_names_is_the_one_that_runs(self):
        """A `prog=` string is a claim about a runnable command, and nothing
        checks it. This module pins one because its relative import makes the
        path argparse would derive (`placeintel/maps_rpc_fetch.py`) unrunnable —
        so the pinned value has to be right."""
        import tempfile
        with tempfile.TemporaryDirectory() as neutral:
            usage = self._run("--help", cwd=neutral).stdout
        self.assertIn("usage: python -m placeintel.maps_rpc_fetch", usage)

    def test_missing_argument_is_a_usage_error_not_a_crash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as neutral:
            result = self._run(cwd=neutral)
        self.assertEqual(result.returncode, 2, result.stderr[-800:])
        self.assertNotIn("Traceback", result.stderr)


class FixtureHygieneTests(unittest.TestCase):
    """The public mirror must never carry real reviewers' data.

    Ranges over EVERY committed file that can hold a captured page, not just this
    module's own fixture. Measured 2026-08-31: while this test was green, the
    tracked `vendor-patches/*.patch` carried 4 real avatar URLs, 3 real
    contributor ids and 4 real display names inside a vendored HTML fixture —
    outside this gate's denominator by one filename, and one push from being
    permanent and public.

    Patterns are built from FRAGMENTS so this file does not match itself.
    """

    REPO = Path(__file__).resolve().parent.parent
    #: Where to look. Implementation — free to grow.
    SUBJECT_DIRS = ("tests/fixtures", "vendor-patches")
    #: What MUST end up graded, stated independently of where the sweep looks.
    #: Reading SUBJECT_DIRS here instead would be vacuous — it would only assert
    #: that the sweep covers whatever the sweep declares, which stays true when
    #: someone deletes an entry. A mutation proved exactly that: narrowing
    #: SUBJECT_DIRS left the test green because it was grading its own config.
    REQUIRED_COVERAGE = ("tests/fixtures", "vendor-patches")
    _G = "google" + "usercontent"

    def _subjects(self):
        found = []
        for name in self.SUBJECT_DIRS:
            root = self.REPO / name
            if root.is_dir():
                found += [p for p in root.rglob("*") if p.is_file()]
        return sorted(found)

    def test_there_are_subjects_to_grade(self):
        # A sweep that finds nothing passes every assertion beneath it.
        self.assertTrue(self._subjects(), "no fixture or patch files found")

    def test_no_committed_file_holds_real_reviewer_data(self):
        photo = re.compile(r"https://lh\d\." + self._G + r"\.com/")
        contrib = re.compile(r"/maps/contrib/" + r"1\d{15,}")
        graded = 0
        seen: list[Path] = []
        for path in self._subjects():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            graded += 1
            rel = path.relative_to(self.REPO)
            seen.append(rel)
            self.assertIsNone(photo.search(text),
                              f"{rel} holds a real reviewer photo/avatar URL")
            self.assertIsNone(contrib.search(text),
                              f"{rel} holds a real contributor id")
        # A COUNT is the wrong property here and a mutation proved it: dropping
        # `vendor-patches` from the sweep left enough files under tests/fixtures
        # to satisfy any threshold, so the probe escaped. Name the subjects that
        # must be covered instead — the patch is the file that gets published.
        for required in self.REQUIRED_COVERAGE:
            self.assertTrue(
                any(str(p).startswith(required) for p in seen),
                f"{required} contributed no graded file — the sweep no longer "
                "covers it, whatever its total says")
        print(f"\n  fixture hygiene: graded {graded} committed file(s) across "
              f"{len(self.REQUIRED_COVERAGE)} required location(s)")

    def test_the_named_reviewers_are_gone_from_this_modules_fixture(self):
        text = FIXTURE.read_text(encoding="utf-8")
        for token in ("100144025264761949764", "Florence", "Tallulah",
                      "Romain Maillot"):
            self.assertNotIn(token, text, f"{token!r} leaked into a public fixture")


class HeadMergeTests(unittest.TestCase):
    """Merging the on-screen head into the walk.

    Maps renders the first ~10 review cards server-side, so the earliest request
    the page ever makes is already at cursor offset 10 and no position-0 request
    exists to capture. The head therefore comes from the DOM and is CONCATENATED
    with the walk. The property that makes that safe is contiguity — the head has
    to reach at least as far as the walk starts — and it is decidable, so it is
    a gate rather than a hope.
    """

    @staticmethod
    def _r(rid, ts=None):
        return maps_rpc.Review(review_id=rid, timestamp_us=ts)

    def test_head_comes_first_so_the_newest_reviews_survive_a_cap(self):
        merged, report = maps_rpc.merge_head(
            [self._r("h1"), self._r("h2")], [self._r("w1")], start_offset=2)
        self.assertEqual([r.review_id for r in merged], ["h1", "h2", "w1"])
        self.assertEqual(report.verdict, "contiguous")
        self.assertEqual(report.gap, 0)

    def test_a_head_shorter_than_the_walk_start_is_a_gap_not_a_merge(self):
        # 7 cards settled but the walk begins at 10: reviews 7, 8 and 9 exist and
        # are in neither list. Reporting 81 of 85 here would look like Google
        # simply listing more than it serves.
        merged, report = maps_rpc.merge_head(
            [self._r(f"h{i}") for i in range(7)], [self._r("w")], start_offset=10)
        self.assertEqual(report.gap, 3)
        self.assertEqual(report.verdict, "gap")
        self.assertEqual(len(merged), 8)

    def test_an_unknown_start_offset_is_unverified_never_contiguous(self):
        _, report = maps_rpc.merge_head([self._r("h")], [self._r("w")],
                                        start_offset=None)
        self.assertEqual(report.verdict, "unverified")
        self.assertIsNone(report.gap)

    def test_overlap_dedupes_and_keeps_the_walked_row(self):
        # The head's timestamp is derived from a relative string ("2 weeks ago");
        # the walked one is exact. Same review, so keep the better copy — but at
        # the head's position, because that is the one that knows the ordering.
        merged, report = maps_rpc.merge_head(
            [self._r("a", ts=None), self._r("b")],
            [self._r("a", ts=1234), self._r("c")], start_offset=2)
        self.assertEqual([r.review_id for r in merged], ["a", "b", "c"])
        self.assertEqual(merged[0].timestamp_us, 1234)
        self.assertEqual(report.overlap, 1)
        self.assertEqual(report.merged, 3)

    def test_an_overlapping_head_cannot_report_a_gap(self):
        # Sharing a review proves the two lists touch, whatever the cursor said.
        _, report = maps_rpc.merge_head([self._r("a")], [self._r("a")],
                                        start_offset=10)
        self.assertEqual(report.verdict, "contiguous")

    def test_rows_without_an_id_are_kept_but_counted(self):
        # An id is how the two halves dedupe. Dropping the row would lose a real
        # review; silently keeping it would let one be stored twice.
        merged, report = maps_rpc.merge_head(
            [self._r(None), self._r("h")], [self._r("w")], start_offset=2)
        self.assertEqual(len(merged), 3)
        self.assertEqual(report.head_without_id, 1)

    def test_the_gap_counts_unique_reviews_not_duplicate_dom_elements(self):
        """The one way this gate passes while wrong: an inflated denominator.

        Maps renders two `div[data-review-id]` elements per card, so a 10-card
        head arrives as 20 rows. Counting rows, a head that truly stops at
        review 10 "reaches" a walk starting at 15 and a five-review hole reports
        as contiguous."""
        doubled = [self._r(f"h{i // 2}") for i in range(20)]   # 20 rows, 10 ids
        _, report = maps_rpc.merge_head(doubled, [self._r("w")], start_offset=15)
        self.assertEqual(report.gap, 5)
        self.assertEqual(report.verdict, "gap")

    def test_an_empty_head_is_reported_rather_than_read_as_a_full_merge(self):
        merged, report = maps_rpc.merge_head([], [self._r("w")], start_offset=10)
        self.assertEqual(report.head, 0)
        self.assertEqual(report.gap, 10)
        self.assertEqual(report.verdict, "gap")
        self.assertEqual([r.review_id for r in merged], ["w"])


if __name__ == "__main__":
    unittest.main()
