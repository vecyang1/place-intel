"""Contract for the owner-only routes and the billable-job budget.

The site is shared with guests through one proxy credential, so the proxy cannot
tell the owner from a friend. These two guards are what stand between a shared
password and (a) a guest deleting cached intel that cost real money, and (b) a
guest spending the owner's provider budget without a ceiling.
"""

import unittest
import warnings
from unittest import mock

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient

from placeintel import config, server

OWNER_ROUTES = [
    ("delete", "/api/places/anything"),
    ("post", "/api/settings"),
    ("post", "/api/settings/language"),
]


class OwnerGuardTest(unittest.TestCase):
    def _call(self, method: str, path: str, headers: dict | None = None):
        client = TestClient(server.app)
        return getattr(client, method)(path, headers=headers or {}, **({} if method == "delete" else {"json": {}}))

    def test_unset_token_refuses_rather_than_opens(self) -> None:
        """The whole point: a missing env var must not make a destructive route public."""
        with mock.patch.object(config, "PLACEINTEL_OWNER_TOKEN", ""):
            for method, path in OWNER_ROUTES:
                with self.subTest(route=path):
                    self.assertEqual(self._call(method, path).status_code, 403)

    def test_wrong_token_is_rejected(self) -> None:
        with mock.patch.object(config, "PLACEINTEL_OWNER_TOKEN", "correct-token"):
            for method, path in OWNER_ROUTES:
                with self.subTest(route=path):
                    response = self._call(method, path, {"X-PlaceIntel-Owner": "wrong-token"})
                    self.assertEqual(response.status_code, 403)

    def test_missing_header_is_rejected(self) -> None:
        with mock.patch.object(config, "PLACEINTEL_OWNER_TOKEN", "correct-token"):
            for method, path in OWNER_ROUTES:
                with self.subTest(route=path):
                    self.assertEqual(self._call(method, path).status_code, 403)

    def test_correct_token_passes_the_guard(self) -> None:
        """Past the guard the route may still 4xx/5xx on its own body validation —
        what matters here is that it is no longer 403 from require_owner."""
        with mock.patch.object(config, "PLACEINTEL_OWNER_TOKEN", "correct-token"):
            response = self._call("delete", "/api/places/does-not-exist",
                                  {"X-PlaceIntel-Owner": "correct-token"})
        self.assertNotEqual(response.status_code, 403)

    def test_guest_routes_stay_open_without_the_header(self) -> None:
        """Sharing is the point: reads must not require the owner token."""
        with mock.patch.object(config, "PLACEINTEL_OWNER_TOKEN", "correct-token"):
            client = TestClient(server.app)
            self.assertEqual(client.get("/api/places").status_code, 200)
            self.assertEqual(client.get("/api/profiles").status_code, 200)


class JobBudgetTest(unittest.TestCase):
    def test_budget_refuses_once_the_ceiling_is_reached(self) -> None:
        with mock.patch.object(config, "PLACEINTEL_DAILY_JOB_LIMIT", 5), \
             mock.patch("placeintel.cache.count_jobs_since", return_value=5):
            with self.assertRaises(Exception) as caught:
                server.enforce_job_budget()
        self.assertEqual(getattr(caught.exception, "status_code", None), 429)

    def test_budget_allows_below_the_ceiling(self) -> None:
        with mock.patch.object(config, "PLACEINTEL_DAILY_JOB_LIMIT", 5), \
             mock.patch("placeintel.cache.count_jobs_since", return_value=4):
            server.enforce_job_budget()  # must not raise

    def test_zero_limit_disables_the_cap_without_touching_the_db(self) -> None:
        with mock.patch.object(config, "PLACEINTEL_DAILY_JOB_LIMIT", 0), \
             mock.patch("placeintel.cache.count_jobs_since") as counted:
            server.enforce_job_budget()
        counted.assert_not_called()

    def test_malformed_ceiling_falls_back_instead_of_disabling_the_cap(self) -> None:
        """A typo in the env var must not silently remove the spend ceiling."""
        self.assertEqual(config._positive_int("not-a-number", default=50), 50)
        self.assertEqual(config._positive_int(None, default=50), 50)
        self.assertEqual(config._positive_int("-3", default=50), 50)
        self.assertEqual(config._positive_int("7", default=50), 7)


if __name__ == "__main__":
    unittest.main()
