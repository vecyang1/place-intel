"""Guards for a site that is shared, but not shared equally.

The reverse proxy holds one credential that the owner hands to guests, so by
construction it cannot tell the owner from a friend. Two things follow, and
neither is solved by adding a login:

- some routes destroy cached intel or reconfigure the app for everyone, and
  should answer only to the owner;
- every scout or shop spends the owner's provider budget, so a guest who is
  legitimately let in still needs a ceiling.
"""

from __future__ import annotations

import hmac
import time

from fastapi import Depends, Header, HTTPException

from . import cache, config

BILLABLE_JOB_KINDS = ("scout", "shop")
BILLABLE_WINDOW_SECONDS = 24 * 60 * 60


def require_owner(
    x_placeintel_owner: str | None = Header(default=None, alias="X-PlaceIntel-Owner"),
) -> None:
    """Gate the routes that destroy cached intel or reconfigure the app globally.

    Fails CLOSED: an unset token refuses rather than allows. The monitor
    endpoint may hide itself when unconfigured because it is opt-in, but a
    destructive route falling open on a missing env var is a different class of
    mistake.
    """
    expected = config.PLACEINTEL_OWNER_TOKEN
    if not expected:
        raise HTTPException(403, "owner-only route: PLACEINTEL_OWNER_TOKEN is not configured")
    if not x_placeintel_owner or not hmac.compare_digest(x_placeintel_owner, expected):
        raise HTTPException(403, "owner only")


OWNER_ONLY = [Depends(require_owner)]


def enforce_job_budget() -> None:
    """Refuse a billable job once the rolling-24h ceiling is reached.

    Counted off the jobs table rather than a separate counter, so the budget can
    never drift from what actually ran and needs no reset job.
    """
    limit = config.PLACEINTEL_DAILY_JOB_LIMIT
    if limit <= 0:
        return
    conn = cache.connect()
    try:
        used = cache.count_jobs_since(
            conn, BILLABLE_JOB_KINDS, time.time() - BILLABLE_WINDOW_SECONDS
        )
    finally:
        conn.close()
    if used >= limit:
        raise HTTPException(
            429,
            f"daily job budget reached ({used}/{limit} in the last 24h); "
            "raise PLACEINTEL_DAILY_JOB_LIMIT or wait for the window to roll",
        )
