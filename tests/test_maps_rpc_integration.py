"""How `reviews.py` uses the RPC — the ladder, the guard, and the id namespace.

`test_maps_rpc_contract.py` owns the parser. This file owns the wiring, which is
where the risk actually is: a new primary path that can silently REPLACE a
working one, and an identity guard whose whole job is to refuse.
"""
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401  — pins DATA_DIR before placeintel imports

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from placeintel import maps_rpc  # noqa: E402
from placeintel import maps_rpc_fetch  # noqa: E402
from placeintel import reviews  # noqa: E402
from placeintel.cache import Place, Review  # noqa: E402

FEATURE = "0x314a455ad6407235:0xe121f190cbc130e7"
OTHER = "0x314a443465a12319:0x5daa3b5a1ada17ce"


def _place(**kw):
    base = dict(place_id="P1", name="Vu Binh Exchange & ATM",
                maps_url=f"https://maps.google.com/?q=Vu+Binh&ftid={FEATURE}")
    return Place(**(base | kw))


class OptInSwitchTests(unittest.TestCase):
    """OPT-IN, not opt-out. The RPC enumerates Google's relevance list rather
    than the newest list on every place measured; the parity gate catches it and
    the DOM path takes over, so nothing wrong is stored — but the failed attempt
    still costs a ~100 s browser bootstrap. Absence of the flag must mean OFF."""

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLACEINTEL_ENABLE_MAPS_RPC", None)
            self.assertFalse(reviews.maps_rpc_enabled())

    def test_on_only_for_an_affirmative_value(self):
        for value in ("1", "true", "TRUE", "yes", "on", " 1 "):
            with mock.patch.dict(os.environ, {"PLACEINTEL_ENABLE_MAPS_RPC": value}):
                self.assertTrue(reviews.maps_rpc_enabled(), value)
        for value in ("0", "", "no", "off", "maybe"):
            with mock.patch.dict(os.environ, {"PLACEINTEL_ENABLE_MAPS_RPC": value}):
                self.assertFalse(reviews.maps_rpc_enabled(), value)


class ExpectedFeatureIdTests(unittest.TestCase):
    def test_reads_identity_from_the_url_or_the_raw_record(self):
        self.assertEqual(reviews.expected_feature_id(_place()), FEATURE)
        self.assertEqual(
            reviews.expected_feature_id(
                Place(place_id="P", name="n", maps_url=None, raw={"data_id": FEATURE})),
            FEATURE)

    def test_no_identity_is_none_not_a_guess(self):
        """A place with no stated feature id must report that it cannot be
        checked, rather than supplying a value the guard would then 'confirm'."""
        self.assertIsNone(reviews.expected_feature_id(
            Place(place_id="P", name="n",
                  maps_url="https://www.google.com/maps/place/?q=place_id:ChIJabc")))


class ReviewMappingTests(unittest.TestCase):
    ITEM = {"review_id": "Ci9DQUlRQUNvZENodDBaWEp0",
            "rating": 5, "text": "Good rate, fast service.",
            "author": "A Person", "author_id": "1",
            "timestamp_us": 1_785_542_400_000_000, "photos": ["https://x/p.jpg"]}

    def test_shares_the_dom_path_id_namespace_so_the_two_paths_dedupe(self):
        """`review_id` is the reviews table's primary key. If the RPC prefixed
        its ids differently, a place fetched both ways would store every review
        twice and the counts would silently double."""
        mapped = reviews._rpc_review_to_review(self.ITEM, "P1")
        self.assertEqual(mapped.review_id, "gsp:Ci9DQUlRQUNvZENodDBaWEp0")
        dom = reviews._scraper_row_to_review(
            {"review_id": "Ci9DQUlRQUNvZENodDBaWEp0", "rating": 5,
             "review_text": "{}", "owner_responses": "{}", "user_images": "[]",
             "review_date": "2026-08-01"}, "P1")
        self.assertEqual(mapped.review_id, dom.review_id)

    def test_absent_fields_stay_none_rather_than_becoming_zero(self):
        sparse = reviews._rpc_review_to_review({"review_id": "X"}, "P1")
        self.assertIsNone(sparse.rating)
        self.assertIsNone(sparse.text)
        self.assertIsNone(sparse.review_date)
        self.assertIsNone(sparse.author)
        self.assertEqual(sparse.images, [])

    def test_records_which_path_produced_the_row(self):
        self.assertEqual(reviews._rpc_review_to_review(self.ITEM, "P1").source,
                         "maps-rpc")
        self.assertEqual(reviews._rpc_review_to_review(self.ITEM, "P1").review_date,
                         "2026-08-01")


class WorkerResultTests(unittest.TestCase):
    """Every failure of this endpoint is an HTTP 200. The worker's `ok` flag is
    the only verdict, so the caller must key on it and not on an exit code."""

    def _run(self, payload):
        def fake(cmd, *, cwd, env, timeout_s=None):
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(__import__("json").dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(reviews, "_run_in_own_process_group", side_effect=fake):
            return reviews._fetch_via_maps_rpc_unproxied(_place(), 10, "https://u")

    def test_identity_mismatch_is_refused_not_stored(self):
        """The failure this guard exists for: the RPC answers correctly, about
        the wrong business, and every other signal reads as success."""
        with self.assertRaises(reviews.ScraperProError) as ctx:
            self._run({"ok": False, "identity": "mismatch", "reviews": [],
                       "error": f"landed on {OTHER}, expected {FEATURE}"})
        self.assertIn("mismatch", str(ctx.exception))
        self.assertIn(OTHER, str(ctx.exception))

    def test_an_empty_walk_is_a_failure_not_a_place_without_reviews(self):
        with self.assertRaises(reviews.ScraperProError):
            self._run({"ok": False, "identity": "match", "reviews": [],
                       "error": "walk returned no reviews (empty envelope)"})

    def test_a_good_result_maps_through(self):
        got = self._run({"ok": True, "identity": "match", "pages": 2,
                         "reviews": [{"review_id": "A", "rating": 5},
                                     {"review_id": "B", "rating": 3},
                                     {"rating": 4}]})
        self.assertEqual([r.review_id for r in got], ["gsp:A", "gsp:B"])

    def test_a_worker_that_writes_nothing_is_reported_with_its_stderr(self):
        with mock.patch.object(
                reviews, "_run_in_own_process_group",
                return_value=subprocess.CompletedProcess([], 3, "", "boom")):
            with self.assertRaises(reviews.ScraperProError) as ctx:
                reviews._fetch_via_maps_rpc_unproxied(_place(), 10, "https://u")
        self.assertIn("boom", str(ctx.exception))


class RewindTests(unittest.TestCase):
    """The bootstrap can only capture a request the PAGE chose to make, and that
    cursor carries an offset. Walking from it drops the newest N reviews and
    still reports `no next cursor — end of reviews`."""

    FIXTURE = (Path(__file__).parent / "fixtures" / "maps_rpc_qv9Egd_page.txt")
    EMPTY = b")]}'\n\n27\n[[\"wrb.fr\",\"qv9Egd\",null,null,null,[],\"generic\"]]\n"

    def _template(self, cursor):
        import urllib.parse
        inner = ('[[["0xA:0xB"],null],[10,\\"%s\\"],null,null,["ei"]]' % cursor)
        return "f.req=" + urllib.parse.quote(
            f'[[["qv9Egd","{inner}",null,"generic"]]]', safe="") + "&"

    def test_a_template_already_at_the_start_is_not_probed(self):
        """Asserted with a trap: an extra POST is invisible in the return value
        but is a real request against Google on every single scrape."""
        from placeintel import maps_rpc_fetch

        def trap(_body):
            raise AssertionError("must not probe a template already at offset 0")
        for cursor in ("CjEabc:0", "CjEabcNoOffset"):
            same = maps_rpc_fetch._rewind(trap, self._template(cursor), 20, lambda _m: None)
            self.assertEqual(same, self._template(cursor))

    def test_an_accepted_rewind_is_used(self):
        """A rewind that genuinely moved: the rewound request answers with a
        DIFFERENT first review than the captured one. Modelling both responses
        is the point — the previous version of this test returned one page for
        every POST, which made a real rewind and a no-op indistinguishable, and
        the no-op is what the live server actually does."""
        from placeintel import maps_rpc, maps_rpc_fetch
        original = self.FIXTURE.read_bytes()
        first = maps_rpc.parse_page(original).reviews[0].review_id
        earlier = original.replace(first.encode(), b"A" * len(first), 1)
        self.assertNotEqual(earlier, original, "fixture must differ to be evidence")
        replies = [earlier, original]
        got = maps_rpc_fetch._rewind(lambda _b: replies.pop(0),
                                     self._template("CjEabc:10"), 20, lambda _m: None)
        self.assertEqual(maps_rpc.cursor_of(got), "CjEabc:0")

    def test_a_rewind_that_returns_the_same_rows_is_not_a_rewind(self):
        """The server ACCEPTS `<blob>:0` and answers with the identical page —
        the numeric suffix is decorative, the position lives in the blob. A
        check that only asks "did it answer" passes on that, and then reports a
        walk starting at 0 which in fact starts at 10."""
        from placeintel import maps_rpc_fetch
        page = self.FIXTURE.read_bytes()
        posts = []

        def post(body):
            posts.append(body)
            return page

        template = self._template("CjEabc:10")
        self.assertEqual(
            maps_rpc_fetch._rewind(post, template, 20, lambda _m: None), template)
        self.assertEqual(len(posts), 2, "must compare against the original page")

    def test_a_rejected_rewind_falls_back_rather_than_walking_nothing(self):
        """The cursor is an opaque blob and the server may refuse a hand-edited
        one — as an empty HTTP 200, like every other failure here. Fewer reviews
        beats none."""
        from placeintel import maps_rpc, maps_rpc_fetch
        got = maps_rpc_fetch._rewind(lambda _b: self.EMPTY,
                                     self._template("CjEabc:10"), 20, lambda _m: None)
        self.assertEqual(maps_rpc.cursor_of(got), "CjEabc:10")


class ParityVerdictTests(unittest.TestCase):
    def test_only_a_complete_disjointness_on_an_adequate_sample_fails(self):
        from placeintel.maps_rpc_fetch import PARITY_MIN_SAMPLE
        from placeintel.maps_rpc_fetch import parity_verdict as verdict
        enough = [f"d{i}" for i in range(PARITY_MIN_SAMPLE)]
        self.assertEqual(verdict(["a", "b"], ["b", "c"])["verdict"], "match")
        self.assertEqual(verdict(enough, ["z"])["verdict"], "no-overlap")
        # Either side empty means "could not check", which is not a pass and not
        # a failure. Calling it a match would make the gate agree with itself.
        self.assertEqual(verdict([], ["z"])["verdict"], "unverified")
        self.assertEqual(verdict(enough, [])["verdict"], "unverified")
        self.assertEqual(verdict(None, None)["verdict"], "unverified")

    def test_a_sample_too_small_to_conclude_from_reports_unverified(self):
        """Measured on prod: a 3-card DOM sample, read while the re-sorted pane
        was still filling in, was completely disjoint from a walk that was
        independently correct — identity matched and all 75 reviews were there.
        Below the floor the honest answer is "could not check"."""
        from placeintel.maps_rpc_fetch import PARITY_MIN_SAMPLE
        from placeintel.maps_rpc_fetch import parity_verdict as verdict
        small = [f"d{i}" for i in range(PARITY_MIN_SAMPLE - 1)]
        self.assertEqual(verdict(small, ["z"])["verdict"], "unverified")
        big = [f"d{i}" for i in range(PARITY_MIN_SAMPLE)]
        self.assertEqual(verdict(big, ["z"])["verdict"], "no-overlap")
        # A real overlap still wins regardless of sample size — one shared id is
        # positive evidence, which a small sample cannot fake.
        self.assertEqual(verdict(["d0"], ["d0", "z"])["verdict"], "match")

    def test_blank_ids_are_not_counted_as_agreement(self):
        from placeintel.maps_rpc_fetch import parity_verdict as verdict
        self.assertEqual(verdict(["", None], ["", None])["verdict"], "unverified")


class VerifyAndWalkTests(unittest.TestCase):
    """Drives the terminal branches of the worker with a fake browser and a fake
    transport.

    These branches only run against a live Google, which is exactly why one of
    them shipped with a `NameError` in its error message: the code was correct
    everywhere a test had ever reached. An error string is still code.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "maps_rpc_qv9Egd_page.txt"
    EMPTY = b")]}'\n\n27\n[[\"wrb.fr\",\"qv9Egd\",null,null,null,[],\"generic\"]]\n"

    class _Driver:
        def __init__(self):
            self.quits = 0

        def quit(self):
            self.quits += 1
            if self.quits > 1:          # a real driver raises on a second quit
                raise RuntimeError("connection refused")

    def _capture(self, feature="0xA:0xB", dom_ids=("R1",), cursor="CjEabc:0"):
        import urllib.parse
        inner = (f'[[["{feature}"],null],[10,\\"{cursor}\\"],null,null,["ei"]]')
        body = "f.req=" + urllib.parse.quote(
            f'[[["qv9Egd","{inner}",null,"generic"]]]', safe="") + "&"
        return {"url": "https://www.google.com/x", "body": body,
                "headers": {"Content-Type": "t", "User-Agent": "u", "X-maps-bgkey": "k"},
                "cookies": {}, "dom_review_ids": list(dom_ids),
                "landed_url": "https://maps", "navigation": {}, "start_offset": 0}

    def _run(self, capture, pages, expected):
        from placeintel import maps_rpc_fetch
        queue = list(pages)

        class _Session:
            proxies = {}

            def post(self, *a, **kw):
                class R:
                    content = queue.pop(0) if queue else VerifyAndWalkTests.EMPTY
                return R()

        driver = self._Driver()
        with mock.patch("requests.Session", _Session):
            result = maps_rpc_fetch._verify_and_walk(
                driver, capture, __import__("time").time(), log=lambda _m: None,
                proxy_url=None, expected_feature_id=expected, page_size=20,
                max_reviews=None)
        return result, driver

    def test_identity_mismatch_refuses_and_never_walks(self):
        result, driver = self._run(self._capture(feature="0xA:0xB"),
                                   [self.FIXTURE.read_bytes()], "0xC:0xD")
        self.assertFalse(result["ok"])
        self.assertEqual(result["identity"], "mismatch")
        self.assertEqual(result["reviews"], [])
        self.assertIn("0xa:0xb", result["error"])
        # Teardown on this path is `fetch`'s `finally`, not here — asserted for
        # real in FetchTeardownTests, which goes through the public entry point.
        self.assertEqual(driver.quits, 0)

    def test_a_head_that_does_not_overlap_the_walk_is_the_normal_case(self):
        """The retired `no-overlap` gate, and why retiring it is not a weakening.

        It blocked when no review on screen appeared in the walk. That was a TRUE
        positive every time it fired — the walk began at cursor offset 10 while
        the pane showed reviews 0-9, so the two were disjoint BY CONSTRUCTION.
        Now that the head is merged in deliberately, disjointness is the healthy
        shape and blocking on it would refuse every correct run.

        What replaces it is strictly stronger, because both replacements are
        exact rather than heuristic: `contiguity` proves nothing sits between the
        head and the walk, and `coverage` measures the result against a count
        read off the page — a source independent of the walk.
        """
        capture = self._capture(dom_ids=tuple(f"unrelated-{i}" for i in range(10)))
        capture["head_reviews"] = [maps_rpc.Review(review_id=f"unrelated-{i}")
                                   for i in range(10)]
        capture["start_offset"] = 10
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertEqual(result["merge"]["verdict"], "contiguous")
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["merge"]["merged"], 20)   # 10 head + 10 walked

    def test_forcing_english_covers_navigations_the_vendor_makes_itself(self):
        """`Accept-Language` and a PREF cookie do not reach the vendor's own
        `maps/search/<name>/` URL, which is the navigation that decides the UI
        language — and the UI language decides whether the sort control works."""
        from placeintel import maps_rpc_fetch

        class _D:
            def __init__(self): self.urls = []
            def get(self, url): self.urls.append(url)

        d = _D()
        maps_rpc_fetch._force_english(d)
        d.get("https://www.google.com/maps/search/Some+Shop/")
        d.get("https://www.google.com/maps/place/X?q=1")
        d.get("https://www.google.com/maps?hl=de")     # explicit choice respected
        d.get("https://example.com/nothing")           # untouched
        self.assertEqual(d.urls, [
            "https://www.google.com/maps/search/Some+Shop/?hl=en",
            "https://www.google.com/maps/place/X?q=1&hl=en",
            "https://www.google.com/maps?hl=de",
            "https://example.com/nothing",
        ])

    def test_coverage_is_none_when_google_did_not_state_a_total(self):
        """`no next cursor` is the server saying it has no more to give, which
        is not the same claim as "you have them all". Without a stated total the
        two are indistinguishable, so coverage must be unknown, not 100%."""
        capture = self._capture(dom_ids=("R1",))
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertIsNone(result["coverage"])
        self.assertIsNone(result["listed_review_count"])

    def test_coverage_below_the_floor_is_refused_so_the_complete_path_runs(self):
        """Changed contract, deliberately: a shortfall used to be reported and
        stored. It is now refused.

        The point of this path is that it is ~100x faster than the DOM scraper,
        not that it is the only one. Storing 10 of 40 reviews spends the speed on
        an answer no reader can tell from a complete one, while falling back
        costs ~70s and returns all 40 — measured 85/85 on the place this was
        built against."""
        capture = self._capture(dom_ids=("R1",)) | {"listed_review_count": 40}
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertEqual(result["coverage"], 0.25)   # 10 of 40
        self.assertFalse(result["ok"])
        self.assertIn("40", result["error"])

    def test_full_coverage_passes(self):
        capture = self._capture(dom_ids=("R1",)) | {"listed_review_count": 10}
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertEqual(result["coverage"], 1.0)
        self.assertTrue(result["ok"], result["error"])

    def test_the_coverage_floor_is_operator_tunable(self):
        capture = self._capture(dom_ids=("R1",)) | {"listed_review_count": 40}
        with mock.patch.dict(os.environ,
                             {"PLACEINTEL_MAPS_RPC_MIN_COVERAGE": "0.2"}):
            result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertTrue(result["ok"], result["error"])

    def test_an_unreadable_listed_count_cannot_silently_pass_the_gate(self):
        # Google not stating a total is a page quirk, not evidence of a short
        # read — so it must not refuse. It must also not report 100%.
        capture = self._capture(dom_ids=("R1",)) | {"listed_review_count": None}
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertIsNone(result["coverage"])
        self.assertTrue(result["ok"], result["error"])

    def test_a_gap_between_the_head_and_the_walk_is_refused(self):
        """The failure this whole merge exists to make impossible.

        A 7-card head against a walk starting at 10 loses reviews 7, 8 and 9 —
        and every other signal still looks healthy: the walk ends cleanly, the
        ids are all distinct, and the total is only a little short of what Google
        listed, which reads exactly like Google listing more than it serves."""
        capture = self._capture(dom_ids=tuple(f"h{i}" for i in range(7)),
                                cursor="CjEabc:10")
        capture["head_reviews"] = [maps_rpc.Review(review_id=f"h{i}")
                                   for i in range(7)]
        page = self.FIXTURE.read_bytes()
        # Every response identical, so the rewind probe sees the same first
        # review twice and correctly concludes the cursor did not move.
        result, _ = self._run(capture, [page, page, page], "0xA:0xB")
        self.assertEqual(result["merge"]["gap"], 3)
        self.assertFalse(result["ok"])
        self.assertIn("gap", result["error"])

    def test_the_head_is_first_so_a_cap_keeps_the_newest(self):
        capture = self._capture(dom_ids=("h0",))
        capture["head_reviews"] = [maps_rpc.Review(review_id="h0",
                                                   timestamp_us=9_999_999_999_000_000)]
        capture["start_offset"] = 1
        result, _ = self._run(capture, [self.FIXTURE.read_bytes()], "0xA:0xB")
        self.assertEqual(result["reviews"][0]["review_id"], "h0")

    def test_an_empty_first_page_is_a_failure_not_an_empty_place(self):
        result, _ = self._run(self._capture(), [self.EMPTY], "0xA:0xB")
        self.assertFalse(result["ok"])
        self.assertIn("no reviews", result["error"])

    def test_a_healthy_run_reports_ok_with_matching_parity(self):
        from placeintel import maps_rpc
        raw = self.FIXTURE.read_bytes()
        first_id = maps_rpc.parse_page(raw).reviews[0].review_id
        result, driver = self._run(self._capture(dom_ids=(first_id,)), [raw], "0xA:0xB")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["identity"], "match")
        self.assertEqual(result["parity"]["verdict"], "match")
        self.assertEqual(len(result["reviews"]), 10)
        self.assertIsNone(result["error"])

    def test_unverifiable_identity_still_runs(self):
        """A place whose URL states no feature id cannot be checked. That is a
        recorded gap, not a refusal — refusing would break every place we hold
        only a name for."""
        from placeintel import maps_rpc
        raw = self.FIXTURE.read_bytes()
        first_id = maps_rpc.parse_page(raw).reviews[0].review_id
        result, _ = self._run(self._capture(dom_ids=(first_id,)), [raw], None)
        self.assertEqual(result["identity"], "unverified")
        self.assertTrue(result["ok"], result.get("error"))

    def test_the_walk_closes_the_browser_before_the_first_rpc_call(self):
        """The whole point of this path: pagination is HTTP, so ~70 s of Chrome
        should not stay resident for it."""
        from placeintel import maps_rpc
        raw = self.FIXTURE.read_bytes()
        first_id = maps_rpc.parse_page(raw).reviews[0].review_id
        _, driver = self._run(self._capture(dom_ids=(first_id,)), [raw], "0xA:0xB")
        self.assertEqual(driver.quits, 1)


class FetchTeardownTests(unittest.TestCase):
    """Whatever happens, the Chrome process tree goes with it.

    Measured on prod before this path existed: timeouts that reaped only the
    direct child left ~13-process browsers as PPid-1 orphans holding 4.7 GB.
    """

    def _fetch_with(self, verify_side_effect):
        from placeintel import maps_rpc_fetch
        driver = VerifyAndWalkTests._Driver()
        with mock.patch.object(maps_rpc_fetch, "_bootstrap",
                               return_value=(driver, {"body": "f.req=x&"})),              mock.patch.object(maps_rpc_fetch, "_verify_and_walk",
                               side_effect=verify_side_effect):
            try:
                maps_rpc_fetch.fetch("https://u")
            except RuntimeError:
                pass
        return driver

    def test_closed_once_on_the_happy_path(self):
        self.assertEqual(self._fetch_with(lambda *a, **k: {"ok": True}).quits, 1)

    def test_closed_once_when_the_walk_raises(self):
        def boom(*_a, **_k):
            raise RuntimeError("walk exploded")
        self.assertEqual(self._fetch_with(boom).quits, 1)

    def test_a_walk_that_already_closed_it_is_not_closed_twice(self):
        """A second quit() on a dead driver raises, and raising from a `finally`
        would replace a good result with a connection error."""
        def already_closed(driver, *_a, **_k):
            driver.quit()
            return {"ok": True}
        driver = self._fetch_with(already_closed)
        self.assertEqual(driver.quits, 2, "the second quit must be attempted and swallowed")


class LadderTests(unittest.TestCase):
    """DOM 兜底 — the property the user asked for, asserted in both directions."""

    def setUp(self):
        self.dom_rows = [Review(review_id="gsp:D1", place_id="P1", source="scraper-pro")]
        patches = [
            mock.patch.object(reviews, "_primary_blockers", return_value=[]),
            mock.patch.object(reviews, "_read_scraper_db", return_value=[]),
            mock.patch.object(reviews, "_scraper_has_known_empty_review_rows",
                              return_value=False),
            # The RPC is opt-in, so these tests turn it on explicitly. Without
            # this they would pass by never running the code under test.
            mock.patch.dict(os.environ, {"PLACEINTEL_ENABLE_MAPS_RPC": "1"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_rpc_failure_falls_back_to_the_dom_scraper(self):
        with mock.patch.object(reviews, "_fetch_via_maps_rpc",
                               side_effect=reviews.ScraperProError("bgkey rejected")), \
             mock.patch.object(reviews, "_fetch_via_scraper_pro",
                               return_value=self.dom_rows) as dom:
            got = reviews.fetch_reviews(_place(), max_reviews=5)
        self.assertEqual([r.review_id for r in got], ["gsp:D1"])
        dom.assert_called_once()

    def test_an_unexpected_rpc_crash_still_falls_back(self):
        """A brand-new path must never be the reason an established one stops
        running, so the guard is on BaseException-shaped surprises too."""
        with mock.patch.object(reviews, "_fetch_via_maps_rpc",
                               side_effect=RuntimeError("selenium exploded")), \
             mock.patch.object(reviews, "_fetch_via_scraper_pro",
                               return_value=self.dom_rows) as dom:
            got = reviews.fetch_reviews(_place(), max_reviews=5)
        self.assertEqual([r.review_id for r in got], ["gsp:D1"])
        dom.assert_called_once()

    def test_a_successful_rpc_does_not_also_launch_the_dom_scraper(self):
        """Asserted with a trap rather than a call count: a second browser run
        costs ~70 s and would not fail any assertion about the returned rows."""
        rpc_rows = [Review(review_id="gsp:R1", place_id="P1", source="maps-rpc")]
        with mock.patch.object(reviews, "_fetch_via_maps_rpc", return_value=rpc_rows), \
             mock.patch.object(reviews, "_fetch_via_scraper_pro",
                               side_effect=AssertionError("DOM path must not run")):
            got = reviews.fetch_reviews(_place(), max_reviews=5)
        self.assertEqual([r.review_id for r in got], ["gsp:R1"])

    def test_the_switch_off_skips_the_rpc_entirely(self):
        with mock.patch.dict(os.environ, {"PLACEINTEL_ENABLE_MAPS_RPC": "0"}), \
             mock.patch.object(reviews, "_fetch_via_maps_rpc",
                               side_effect=AssertionError("RPC must not run")), \
             mock.patch.object(reviews, "_fetch_via_scraper_pro",
                               return_value=self.dom_rows):
            got = reviews.fetch_reviews(_place(), max_reviews=5)
        self.assertEqual([r.review_id for r in got], ["gsp:D1"])


class HeadCardMappingTests(unittest.TestCase):
    """The DOM head card -> the same Review shape the RPC walk produces.

    One shape, so `reviews.py` keeps ONE mapper and the two halves dedupe on the
    same primary key. The trap is that the vendor's RawReview defaults are 0.0
    and "" — "not extracted", not "the page said zero" — and passing those
    through would publish a confident 0-star review.
    """

    @staticmethod
    def _raw(**kw):
        base = dict(id="abc", author="", rating=0.0, date="", text="",
                    photos=[], avatar="", profile="")
        return types.SimpleNamespace(**(base | kw))

    def test_unextracted_fields_become_none_not_zero(self):
        review = maps_rpc_fetch._head_review(self._raw())
        self.assertIsNone(review.rating)
        self.assertIsNone(review.author)
        self.assertIsNone(review.text)
        self.assertIsNone(review.relative_date)

    def test_a_real_card_maps_across(self):
        review = maps_rpc_fetch._head_review(self._raw(
            author="A Reviewer", rating=4.0, text="good", date="2 weeks ago",
            photos=["https://example.test/p.jpg"]))
        self.assertEqual(review.review_id, "abc")
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.author, "A Reviewer")
        self.assertEqual(review.photos, ("https://example.test/p.jpg",))

    def test_the_head_carries_a_timestamp_or_it_sorts_last_and_gets_capped(self):
        # _order_and_cap sorts on `review_date or ""` descending, so a head row
        # with no date sinks to the BOTTOM and is the first thing a max_reviews
        # cap discards — losing exactly the newest reviews this merge exists to
        # recover. The relative string is the only date the DOM offers.
        review = maps_rpc_fetch._head_review(self._raw(date="2 weeks ago"))
        self.assertIsInstance(review.timestamp_us, int)
        self.assertGreater(review.timestamp_us, 0)

    def test_a_review_hours_old_gets_a_date(self):
        """The newest review on a page is the one most likely to be under a day
        old, and it is the one this whole merge exists to recover. The vendor's
        converter matched only day/week/month/year until 2026-08-31, so
        "2 hours ago" produced None — which sorts LAST and is capped FIRST.
        Measured on a live place: exactly one of 85 reviews had no date, and it
        was the most recent."""
        for text in ("2 hours ago", "an hour ago", "5 minutes ago", "just now"):
            with self.subTest(text):
                review = maps_rpc_fetch._head_review(self._raw(date=text))
                self.assertIsInstance(review.timestamp_us, int, text)

    def test_the_head_timestamp_is_read_as_utc(self):
        """The vendor builds these from `utcnow()` and returns them NAIVE, so
        `.timestamp()` would read them as local time. Prod runs CEST: a two-hour
        shift, enough to file a review under the wrong day near midnight and to
        date a "2 hours ago" review in the future."""
        import datetime as dt
        review = maps_rpc_fetch._head_review(self._raw(date="2 hours ago"))
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        drift = abs(now - review.timestamp_us / 1_000_000 - 7200)
        self.assertLess(drift, 120, "head timestamp is off by a timezone")

    def test_an_unparseable_relative_date_is_none_not_now(self):
        # "now" would be a fabricated date on a review of unknown age, and it
        # would sort that review to the very top.
        self.assertIsNone(maps_rpc_fetch._head_review(
            self._raw(date="sometime last winter")).timestamp_us)

    def test_the_contributor_id_is_read_from_the_profile_url(self):
        review = maps_rpc_fetch._head_review(self._raw(
            profile="https://www.google.com/maps/contrib/123456789/reviews"))
        self.assertEqual(review.author_id, "123456789")

    def test_a_profile_url_without_a_contributor_id_yields_none(self):
        self.assertIsNone(maps_rpc_fetch._head_review(
            self._raw(profile="https://example.test/nope")).author_id)


class SettledDomIdsTests(unittest.TestCase):
    """The head sample is a COUNT OF REVIEWS, so it must be deduplicated.

    Measured on the live page: `div[data-review-id]` matches TWO elements per
    card, so a 20-element read was 10 reviews. The constant said 20 and the
    denominator was 10 — and the same number is what the contiguity gate
    compares against the walk's start offset, so an inflated head would report a
    clean merge across a real gap.
    """

    class _Driver:
        def __init__(self, *reads):
            self.reads, self.calls = list(reads), 0

        def execute_script(self, _script):
            value = self.reads[min(self.calls, len(self.reads) - 1)]
            self.calls += 1
            return value

    def test_duplicate_elements_per_card_collapse_to_one_id_each(self):
        driver = self._Driver(["a", "a", "b", "b"], ["a", "a", "b", "b"])
        ids = maps_rpc_fetch._settled_dom_ids(driver, lambda _m: None)
        self.assertEqual(ids, ["a", "b"])

    def test_it_waits_for_the_pane_to_stop_growing(self):
        driver = self._Driver(["a"], ["a", "b"], ["a", "b", "c"],
                              ["a", "b", "c"], ["a", "b", "c"])
        ids = maps_rpc_fetch._settled_dom_ids(driver, lambda _m: None)
        self.assertEqual(ids, ["a", "b", "c"])

    def test_order_is_preserved_because_it_is_the_newest_first_order(self):
        driver = self._Driver(["c", "a", "b"], ["c", "a", "b"])
        self.assertEqual(maps_rpc_fetch._settled_dom_ids(driver, lambda _m: None),
                         ["c", "a", "b"])


if __name__ == "__main__":
    unittest.main()
