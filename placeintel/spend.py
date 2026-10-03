"""The one gate between a free scrape and a billable provider call.

Discovery (gosom in Docker) and reviews (vendored scraper-pro) both have a free
primary path and a SerpAPI fallback. The fallback used to fire on ANY primary
failure — a stopped Docker daemon, a missing vendor venv — logging one warning
and then spending the owner's credits. Silent degradation from free to paid is
indistinguishable from success in the timeline, so the bill was the first place
it showed up.

So the fallback is now opt-in and fails CLOSED: with no explicit permission the
paid path raises ``PaidPathBlocked`` naming the free-path failure and how to
allow it. Permission resolves, most specific first:

1. per-run override — ``--allow-serpapi`` / ``--no-serpapi``, or ``--force-serpapi``
   which is itself an explicit request for the paid engine;
2. ``PLACEINTEL_ALLOW_SERPAPI`` in the environment — how the deployed service is
   configured, since env survives restarts and lives in the deploy env file;
3. ``allow_serpapi`` in data/settings.json — the persisted owner choice, shared
   between CLI and web;
4. otherwise blocked.

Every SerpAPI key acquisition in this package goes through
:func:`require_serpapi_key`. Nothing else may read the key: a second door would
put the old silent-spend behaviour back one caller at a time.
"""

from __future__ import annotations

from . import config

ENV_VAR = "PLACEINTEL_ALLOW_SERPAPI"
SETTING_KEY = "allow_serpapi"

_TRUE = {"1", "true", "yes", "on", "allow"}
_FALSE = {"0", "false", "no", "off", "block"}

# Kept short and imperative: this text is what the owner sees in the job
# timeline when a scrape stops, so it has to say what to do next.
_REMEDY = (
    "Fix the free path (on macOS: open -a Docker; on the VPS: systemctl start docker), "
    f"or allow the paid path explicitly with --allow-serpapi, {ENV_VAR}=1, "
    "or `placeintel spend --allow`."
)


class PaidPathBlocked(RuntimeError):
    """The free path failed and nobody authorised spending money instead."""

    def __init__(self, context: str, cause: BaseException | None = None) -> None:
        detail = f" ({cause})" if cause else ""
        super().__init__(
            f"{context}{detail}. SerpAPI is a paid fallback and is not allowed "
            f"for this run, so nothing was spent. {_REMEDY}"
        )
        self.context = context
        self.cause = cause


def _parse_choice(raw: str | None) -> bool | None:
    """None means "not configured" — which must stay distinct from "blocked"."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def policy(override: bool | None = None) -> tuple[bool, str]:
    """Return (allowed, source) so callers can explain the verdict, not just apply it."""
    if override is not None:
        return override, "run"
    env_choice = _parse_choice(config.env_value(ENV_VAR))
    if env_choice is not None:
        return env_choice, "env"
    setting_choice = _parse_choice(config.setting(SETTING_KEY))
    if setting_choice is not None:
        return setting_choice, "settings"
    return False, "default"


def serpapi_allowed(override: bool | None = None) -> bool:
    return policy(override)[0]


def policy_status() -> dict:
    """Non-secret policy view for the System panel, doctor, and the CLI."""
    allowed, source = policy()
    return {
        "provider": "serpapi",
        "allowed": allowed,
        "source": source,
        "key_configured": bool(config.serpapi_api_key()),
        "env_var": ENV_VAR,
        "setting_key": SETTING_KEY,
    }


def require_serpapi_key(
    context: str,
    *,
    allow: bool | None = None,
    cause: BaseException | None = None,
) -> str:
    """Return the SerpAPI key, or refuse before a single billable request is sent.

    ``context`` says which free path failed, so the refusal names the real
    problem rather than the fallback that was blocked.
    """
    if not serpapi_allowed(allow):
        raise PaidPathBlocked(context, cause)
    key = config.serpapi_api_key()
    if not key:
        raise RuntimeError(
            f"{context}, and the SerpAPI fallback is allowed but has no key. "
            "Set SERPAPI_API_KEY, or fix the free path instead."
        )
    return key


def set_allowed(allowed: bool) -> None:
    """Persist the owner's choice. Env still wins — production is configured there."""
    config.save_setting(SETTING_KEY, "1" if allowed else "0")
