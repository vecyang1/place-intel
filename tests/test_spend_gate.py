"""The paid fallback must never fire without permission.

Two failure modes are equally bad and this file asserts against both:

- a free-path failure silently becoming a SerpAPI bill (what shipped before);
- the gate refusing when the owner DID grant permission, which would push people
  back to ``--force-serpapi`` for everything and defeat the point.

Every test scrubs ``PLACEINTEL_ALLOW_SERPAPI``/``SERPAPI_API_KEY`` and points
settings.json at a temp dir. The policy is read from the environment, so a suite
that inherits the developer's shell would pass or fail based on who ran it —
and the dangerous direction (a machine with the variable exported) is exactly
the one that would go green while proving nothing.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from placeintel import cli, config, discover, pipeline, reviews, spend
from placeintel.cache import Place


class SpendGateTestCase(unittest.TestCase):
    """Base: no ambient policy, no ambient key, unless a test opts in."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        settings_path = Path(self._tmp.name) / "settings.json"
        patches = [
            mock.patch.dict(
                os.environ,
                {k: v for k, v in os.environ.items()
                 if k not in {spend.ENV_VAR, "SERPAPI_API_KEY"}},
                clear=True,
            ),
            mock.patch.object(config, "SETTINGS_PATH", settings_path),
            # The author-local skill-file fallback would otherwise supply a real
            # key on this machine and nowhere else.
            mock.patch.object(config, "_SERPAPI_SKILL_MCP", Path(self._tmp.name) / "absent.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _with_key(self) -> None:
        os.environ["SERPAPI_API_KEY"] = "test-key"


class PolicyResolutionTest(SpendGateTestCase):
    def test_default_is_blocked(self):
        allowed, source = spend.policy()
        self.assertFalse(allowed)
        self.assertEqual(source, "default")

    def test_environment_allows(self):
        os.environ[spend.ENV_VAR] = "1"
        self.assertEqual(spend.policy(), (True, "env"))

    def test_saved_setting_allows_when_environment_is_unset(self):
        spend.set_allowed(True)
        self.assertEqual(spend.policy(), (True, "settings"))

    def test_environment_beats_saved_setting(self):
        spend.set_allowed(True)
        os.environ[spend.ENV_VAR] = "0"
        self.assertEqual(spend.policy(), (False, "env"))

    def test_run_override_beats_everything(self):
        os.environ[spend.ENV_VAR] = "1"
        self.assertEqual(spend.policy(override=False), (False, "run"))
        self.assertEqual(spend.policy(override=True), (True, "run"))

    def test_unparseable_value_does_not_open_the_gate(self):
        os.environ[spend.ENV_VAR] = "maybe"
        self.assertEqual(spend.policy(), (False, "default"))

    def test_allowed_without_a_key_is_a_configuration_error_not_a_refusal(self):
        # Distinct exception types on purpose: one says "I stopped to protect
        # your credits", the other says "your config cannot do what it claims".
        os.environ[spend.ENV_VAR] = "1"
        with self.assertRaises(RuntimeError) as ctx:
            spend.require_serpapi_key("free path failed")
        self.assertNotIsInstance(ctx.exception, spend.PaidPathBlocked)

    def test_policy_status_reports_source_and_key_without_leaking_it(self):
        self._with_key()
        status = spend.policy_status()
        self.assertEqual(status["allowed"], False)
        self.assertEqual(status["source"], "default")
        self.assertTrue(status["key_configured"])
        self.assertNotIn("test-key", repr(status))


class DiscoveryGateTest(SpendGateTestCase):
    """gosom is down — the case that used to bill silently."""

    def _run_discovery(self, **kwargs):
        with mock.patch.object(discover, "_discover_gosom",
                               side_effect=RuntimeError("Docker daemon is not running")), \
                mock.patch.object(discover.requests, "get") as http:
            try:
                return discover.discover("guitar rental", "Hoi An", **kwargs), http
            except Exception as exc:
                return exc, http

    def test_blocked_by_default_and_sends_no_request(self):
        self._with_key()
        outcome, http = self._run_discovery()
        self.assertIsInstance(outcome, spend.PaidPathBlocked)
        http.assert_not_called()
        # The refusal has to name the real problem, not just the blocked lane.
        self.assertIn("Docker daemon is not running", str(outcome))

    def test_permission_lets_the_fallback_run(self):
        self._with_key()
        os.environ[spend.ENV_VAR] = "1"
        response = mock.Mock(status_code=200)
        response.json.return_value = {"local_results": []}
        with mock.patch.object(discover, "_discover_gosom",
                               side_effect=RuntimeError("Docker daemon is not running")), \
                mock.patch.object(discover.requests, "get", return_value=response) as http:
            places = discover.discover("guitar rental", "Hoi An")
        self.assertEqual(places, [])
        http.assert_called_once()

    def test_run_level_refusal_overrides_an_allowing_environment(self):
        self._with_key()
        os.environ[spend.ENV_VAR] = "1"
        outcome, http = self._run_discovery(allow_serpapi=False)
        self.assertIsInstance(outcome, spend.PaidPathBlocked)
        http.assert_not_called()

    def test_force_serpapi_is_its_own_permission(self):
        self._with_key()
        response = mock.Mock(status_code=200)
        response.json.return_value = {"local_results": []}
        with mock.patch.object(discover.requests, "get", return_value=response) as http:
            discover.discover("guitar rental", "Hoi An", force_serpapi=True)
        http.assert_called_once()

    def test_a_cached_search_never_probes_docker_or_the_paid_lane(self):
        """The gate must not turn a free cache hit into a Docker wait.

        A pre-scrape readiness probe looked attractive — fail before paying to
        plan a doomed search — but it also fired on cache hits, where the old
        code touched nothing. Refusing late is cheaper than being slow always.
        """
        source = Path(discover.__file__).with_name("pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("free_discovery_blocker", source)
        self.assertNotIn("_ensure_docker_daemon", source)


def _place() -> Place:
    return Place(place_id="ChIJtest", name="Test Place",
                 maps_url="https://maps.google.com/?cid=1", raw={"data_id": "0x:0x"},
                 review_count=674)


class ReviewFallbackGateTest(SpendGateTestCase):
    """All four routes from the free scraper to the paid one must be gated.

    They are separate branches in fetch_reviews, and a guard added to three of
    them would leave the fourth quietly spending — the exact shape of bug the
    single choke point inside _fetch_via_serpapi exists to prevent.
    """

    def setUp(self) -> None:
        super().setUp()
        self._with_key()
        self.http = mock.patch.object(reviews, "_serpapi_get").start()
        self.addCleanup(mock.patch.stopall)

    def _assert_blocked(self, **kwargs):
        with self.assertRaises(spend.PaidPathBlocked):
            reviews.fetch_reviews(_place(), max_reviews=100, **kwargs)
        self.http.assert_not_called()

    def test_missing_vendor_scraper_is_blocked(self):
        with mock.patch.object(reviews, "_primary_blockers", return_value=["venv missing"]):
            self._assert_blocked()

    def test_known_empty_scrape_is_blocked(self):
        with mock.patch.object(reviews, "_primary_blockers", return_value=[]), \
                mock.patch.object(reviews, "_read_scraper_db", return_value=[]), \
                mock.patch.object(reviews, "_scraper_has_known_empty_review_rows",
                                  return_value=True):
            self._assert_blocked()

    def test_scraper_crash_is_blocked(self):
        with mock.patch.object(reviews, "_primary_blockers", return_value=[]), \
                mock.patch.object(reviews, "_read_scraper_db", return_value=[]), \
                mock.patch.object(reviews, "_scraper_has_known_empty_review_rows",
                                  return_value=False), \
                mock.patch.object(reviews, "_fetch_via_scraper_pro",
                                  side_effect=reviews.ScraperProError("chrome died")):
            self._assert_blocked()

    def test_force_serpapi_still_works(self):
        self.http.return_value = {"reviews": []}
        with mock.patch.object(reviews, "_serp_item_to_review", side_effect=lambda i, p: i):
            reviews.fetch_reviews(_place(), max_reviews=100, force_serpapi=True)
        self.http.assert_called()

    def test_permission_lets_the_fallback_run(self):
        os.environ[spend.ENV_VAR] = "1"
        self.http.return_value = {"reviews": []}
        with mock.patch.object(reviews, "_primary_blockers", return_value=["venv missing"]):
            reviews.fetch_reviews(_place(), max_reviews=100)
        self.http.assert_called()


class SingleDoorTest(unittest.TestCase):
    """The gate is only worth anything if it is the ONLY way to the key.

    Prose in a docstring does not stop the next contributor from calling
    config.serpapi_api_key() directly and restoring the old silent spend one
    caller at a time. This fails the build instead.
    """

    ALLOWED = {
        "config.py",    # defines it
        "spend.py",     # the gate
        "doctor.py",    # reports whether a key exists; never spends
    }

    def test_only_the_gate_reads_the_serpapi_key(self):
        package = Path(config.__file__).parent
        offenders = sorted(
            path.name for path in package.glob("*.py")
            if path.name not in self.ALLOWED
            and "serpapi_api_key" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            offenders, [],
            "these modules reach the SerpAPI key without passing spend.require_serpapi_key: "
            f"{offenders}",
        )


class CliFlagTest(unittest.TestCase):
    """Assert the flag REACHES the pipeline, not merely that argparse stored it.

    A flag parsed into a namespace nobody forwards is the quietest kind of
    broken: --no-serpapi would print no error and change nothing.
    """

    def _shop(self, argv: list[str]) -> object:
        result = pipeline.ScoutResult(query="X", location=None, profile="generic")
        with mock.patch.object(pipeline, "scout_single", return_value=result) as scout:
            code = cli.main(["shop", "X", "--format", "json", *argv])
        self.assertIn(code, (0, 1))  # no reports in the stub result
        return scout.call_args.kwargs

    def test_default_forwards_no_opinion(self):
        self.assertIsNone(self._shop([])["allow_serpapi"])

    def test_allow_flag_is_forwarded(self):
        self.assertIs(self._shop(["--allow-serpapi"])["allow_serpapi"], True)

    def test_refusal_flag_is_forwarded(self):
        self.assertIs(self._shop(["--no-serpapi"])["allow_serpapi"], False)

    def test_contradicting_flags_are_refused_rather_than_ranked(self):
        with mock.patch.object(pipeline, "scout_single") as scout:
            code = cli.main(["shop", "X", "--force-serpapi", "--no-serpapi"])
        self.assertNotEqual(code, 0)
        scout.assert_not_called()

    def test_a_block_exits_7_not_as_an_internal_error(self):
        """Exit 10 would tell an agent to file a bug and retry the same thing."""
        blocked = spend.PaidPathBlocked("free review scraper unavailable")
        with mock.patch.object(pipeline, "scout_single", side_effect=blocked):
            code = cli.main(["shop", "X"])
        self.assertEqual(code, 7)


if __name__ == "__main__":
    unittest.main()
