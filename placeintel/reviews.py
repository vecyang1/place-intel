"""Review fetching: vendored google-reviews-scraper-pro primary, SerpAPI fallback.

PRIMARY — we write a one-off config.yaml to a temp dir, run `start.py scrape
  --config <path>` (cwd=vendor dir, its own .venv) with db_path on a persistent
  SQLite file in DATA_DIR so incremental change-detection works across runs.
  The scraper keys reviews by its own URL-derived place_id, so rows are mapped
  back to OUR place via its `places.original_url` column.
FALLBACK — SerpAPI `google_maps_reviews` engine (paginated, ~20 reviews/page).
  Billable, so it runs only with explicit permission (see spend.py). A missing
  vendor venv is a setup problem to fix, not a reason to start paying per page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
import yaml

from . import (config, language, maps_rpc, proxy as proxy_mod, proxy_relay,
               scrape_lock, spend)
from .cache import Place, Review

logger = logging.getLogger(__name__)

SCRAPER_DIR = config.VENDOR_DIR / "google-reviews-scraper-pro"
SCRAPER_PYTHON = SCRAPER_DIR / ".venv" / "bin" / "python"
SCRAPER_TIMEOUT_S = 30 * 60
# Grace between SIGTERM (lets the vendor close its scrape_session row) and
# SIGKILL of the whole process group. Without the group kill, a timeout reaped
# only the direct child and left ~13 orphaned Chrome processes per run behind;
# measured on prod as 4.7 GB of PPid-1 browsers.
SCRAPER_TERM_GRACE_S = 10
# Reuse an existing scrape rather than re-launching Chrome when the caller named
# no ceiling. Below this a run is more likely to have been cut short than to be
# a genuinely small place.
SCRAPER_REUSE_FLOOR = 50

REPO_ROOT = Path(__file__).resolve().parent.parent
# The RPC replaces the scrolling, not the browser, so it still pays one bootstrap
# — but the walk is HTTP. Measured 0.060 s/review against 0.47 s/review for the
# DOM path, so a ceiling well under SCRAPER_TIMEOUT_S is right.
MAPS_RPC_TIMEOUT_S = 20 * 60

SERPAPI_URL = "https://serpapi.com/search"
SERPAPI_TIMEOUT_S = 60
# When max_reviews is None we still cap pagination to protect API credits.
SERPAPI_DEFAULT_MAX_PAGES = 10
SERPAPI_PAGE_SIZE = 20
SERPAPI_INITIAL_PAGE_SIZE = 8


class ScraperProError(RuntimeError):
    """Primary (scraper-pro) path failed; caller should fall back to SerpAPI."""


class PartialReviewsError(RuntimeError):
    """Review fetch returned only a known-underfilled first page."""


def fetch_reviews(
    place: Place,
    max_reviews: int | None = None,
    newest_first: bool = True,
    force_serpapi: bool = False,
    allow_serpapi: bool | None = None,
    refresh: bool = False,
) -> list[Review]:
    """Fetch reviews for *place*, newest-N semantics regardless of final order.

    Primary path runs the vendored scraper-pro when its venv exists and
    place.maps_url is set. Every way that path can fail leads to the same paid
    fallback, so permission is checked inside :func:`_fetch_via_serpapi` rather
    than at each of the four branches below — one gate cannot drift out of sync
    with itself. ``force_serpapi`` is an explicit request for the paid engine
    and therefore grants permission on its own.
    """
    allow = True if force_serpapi else allow_serpapi
    if force_serpapi:
        logger.info("force_serpapi=True — skipping scraper-pro for %s", place.place_id)
        return _order_and_cap(
            _fetch_via_serpapi(place, max_reviews, context="force_serpapi=True", allow=allow),
            max_reviews, newest_first,
        )

    blockers = _primary_blockers(place)
    if blockers:
        reason = "; ".join(blockers)
        logger.info(
            "scraper-pro unavailable for %s (%s) — considering SerpAPI fallback",
            place.place_id, reason,
        )
        return _order_and_cap(
            _fetch_via_serpapi(
                place, max_reviews,
                context=f"free review scraper unavailable ({reason})", allow=allow,
            ),
            max_reviews, newest_first,
        )

    target_url = _scraper_target_url(place)
    if not refresh:
        # Both reads below must hold the place lock. Unlocked, they observe
        # whatever a concurrent scrape has written so far and return it as if it
        # were a finished result — measured on 2026-08-31 as a caller receiving
        # 92 rows mid-scrape and skipping the scrape entirely.
        with scrape_lock.place_scrape_lock(_place_lock_key(place, target_url)):
            try:
                existing = _read_scraper_db(place, target_url)
            except ScraperProError:
                existing = []
            known_empty = (
                _scraper_has_known_empty_review_rows(place, target_url)
                if not existing else False
            )
        if existing:
            logger.info(
                "reusing %d existing scraper-pro reviews for %s before launching Chrome",
                len(existing), place.place_id,
            )
            return _order_and_cap(existing, max_reviews, newest_first)

        if known_empty:
            logger.warning(
                "scraper-pro has a known zero-row scrape for %s despite %s listed reviews "
                "— considering SerpAPI fallback",
                place.place_id, place.review_count,
            )
            return _order_and_cap(
                _fetch_via_serpapi(
                    place, max_reviews,
                    context="free review scraper returned zero rows for a place Google lists reviews for",
                    allow=allow,
                ),
                max_reviews, newest_first,
            )
    # RPC first: same browser bootstrap, but the pagination is plain HTTP
    # (0.060 s/review measured, against 0.47 s/review through the DOM). Every
    # way it can fail raises ScraperProError, so the DOM ladder below is reached
    # by exactly the path it already had.
    if maps_rpc_enabled():
        try:
            with scrape_lock.place_scrape_lock(_place_lock_key(place, target_url)):
                with scrape_lock.scrape_slot():
                    rpc_reviews = _fetch_via_maps_rpc(place, max_reviews, target_url)
            if rpc_reviews:
                return _order_and_cap(rpc_reviews, max_reviews, newest_first)
        except ScraperProError as exc:
            logger.warning("maps-rpc unavailable for %s (%s) — falling back to the "
                           "DOM scraper", place.place_id, exc)
        except Exception as exc:  # noqa: BLE001 - a new path must never be the
            # reason an established one stops running.
            logger.warning("maps-rpc raised %s for %s — falling back to the DOM "
                           "scraper", type(exc).__name__, place.place_id, exc_info=True)

    scraper_error: ScraperProError | None = None
    try:
        reviews = _fetch_via_scraper_pro(place, max_reviews, refresh=refresh)
        return _order_and_cap(reviews, max_reviews, newest_first)
    except ScraperProError as exc:
        scraper_error = exc
        logger.warning(
            "scraper-pro direct failed for %s: %s", place.place_id, exc
        )
        residential_proxy = proxy_mod.resolve_residential_proxy()
        if residential_proxy:
            masked = proxy_mod.mask_proxy(residential_proxy)
            logger.warning(
                "[fallback] ⚠️ scraper-pro 直连受限 (%s)，已自动切换至住宅 IP 代理池 (%s) 重试...",
                exc, masked,
            )
            try:
                reviews = _fetch_via_scraper_pro(
                    place, max_reviews, proxy_url=residential_proxy, refresh=refresh
                )
                if reviews:
                    logger.info("[fallback] 住宅 IP 代理池重试成功，共获取 %d 条评价", len(reviews))
                    return _order_and_cap(reviews, max_reviews, newest_first)
            except ScraperProError as proxy_exc:
                logger.warning(
                    "[fallback] 住宅 IP 代理池抓取亦未成功: %s — 准备考虑 SerpAPI 备用降级", proxy_exc
                )
                scraper_error = proxy_exc

    return _order_and_cap(
        _fetch_via_serpapi(
            place, max_reviews, context="free review scraper failed",
            allow=allow, cause=scraper_error,
        ),
        max_reviews, newest_first,
    )


# ---------------------------------------------------------------------------
# Primary path: the qv9Egd batchexecute RPC (browser bootstrap + HTTP walk)
# ---------------------------------------------------------------------------

def maps_rpc_enabled() -> bool:
    """True only when PLACEINTEL_ENABLE_MAPS_RPC is set. OPT-IN, deliberately.

    The RPC is wired, guarded and fast, and it is off by default because on
    every place measured so far it enumerates Google's RELEVANCE list rather
    than the newest list — 74 reviews whose newest was six months old for a page
    whose top card was a week old, reported as `no next cursor — end of
    reviews`. The parity gate catches that and the DOM scraper takes over, so
    the data is never wrong; but a path that reliably fails still costs a ~100 s
    browser bootstrap before it does, and that is not a good default.

    Turn it on once a captured request can be pinned to the newest ordering
    (see the plan doc, E9). Until then this is one env var, not a deploy.
    """
    return os.environ.get("PLACEINTEL_ENABLE_MAPS_RPC", "").strip().lower() in (
        "1", "true", "yes", "on")


def expected_feature_id(place: Place) -> str | None:
    """The listing the caller actually asked for, as a `0x…:0x…` feature id.

    None when nothing states it — which is not a failure, only an admission that
    the landed-identity check cannot run for this place.
    """
    raw = place.raw if isinstance(place.raw, dict) else {}
    for candidate in (place.maps_url, raw.get("data_id"), raw.get("ftid"),
                      raw.get("cid")):
        found = maps_rpc.feature_id_in(candidate)
        if found:
            return found
    return None


def _rpc_review_to_review(item: dict[str, Any], place_id: str) -> Review:
    """One RPC review into the app's model.

    The `gsp:` prefix is deliberately the SAME one the DOM path uses. It names
    the id NAMESPACE, not the fetcher: `data-review-id` in the DOM and
    `review_id` from the RPC are the same value (verified 10/10 in one session),
    and `review_id` is the reviews table's primary key — so sharing it makes the
    two paths deduplicate against each other instead of storing every review
    twice. Which path produced a row is recorded in `source`.
    """
    text = item.get("text") or None
    micros = item.get("timestamp_us")
    review_date = None
    if isinstance(micros, int) and micros > 0:
        review_date = time.strftime("%Y-%m-%d", time.gmtime(micros / 1_000_000))
    rating = item.get("rating")
    return Review(
        review_id=f"gsp:{item.get('review_id')}",
        place_id=place_id,
        author=item.get("author") or None,
        rating=float(rating) if isinstance(rating, (int, float)) else None,
        text=text,
        lang=language.detect_text_language(text) if text else None,
        review_date=review_date,
        owner_response=None,
        images=list(item.get("photos") or []),
        source="maps-rpc",
        raw=item,
    )


def _fetch_via_maps_rpc(
    place: Place, max_reviews: int | None, target_url: str,
    proxy_url: str | None = None,
) -> list[Review]:
    """Run the RPC worker in the vendor venv and map its result back.

    Raises :class:`ScraperProError` on every failure so the caller's existing
    ladder (DOM, then SerpAPI) handles it with no new branch. An empty walk is a
    failure: this endpoint answers HTTP 200 with an empty envelope for a bad
    token, a wrong cookie jar and an over-large page size alike.
    """
    if proxy_relay.needs_relay(proxy_url):
        with proxy_relay.local_relay(proxy_url) as relay_url:
            return _fetch_via_maps_rpc_unproxied(place, max_reviews, target_url, relay_url)
    return _fetch_via_maps_rpc_unproxied(place, max_reviews, target_url, proxy_url)


def _fetch_via_maps_rpc_unproxied(
    place: Place, max_reviews: int | None, target_url: str,
    proxy_url: str | None = None,
) -> list[Review]:
    config.ensure_dirs()
    home_dir = _scraper_home_dir()
    work_dir = _scraper_work_dir()
    driver_dir = _scraper_driver_dir()
    for path in (work_dir, driver_dir):
        path.mkdir(parents=True, exist_ok=True)
    for sub in (".cache", ".config", ".local/share"):
        (home_dir / sub).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "HOME": str(home_dir),
        "XDG_CACHE_HOME": str(home_dir / ".cache"),
        "XDG_CONFIG_HOME": str(home_dir / ".config"),
        "XDG_DATA_HOME": str(home_dir / ".local" / "share"),
        "PYTHONPATH": str(REPO_ROOT),
        "PLACEINTEL_SCRAPER_DIR": str(SCRAPER_DIR),
        "PLACEINTEL_RPC_DRIVER_DIR": str(driver_dir),
    })
    expected = expected_feature_id(place)
    with tempfile.TemporaryDirectory(prefix="placeintel-rpc-") as tmp_dir:
        out_path = Path(tmp_dir) / "reviews.json"
        cmd = [str(SCRAPER_PYTHON), "-m", "placeintel.maps_rpc_fetch",
               target_url, "--out", str(out_path)]
        if max_reviews:
            cmd += ["--max", str(int(max_reviews))]
        if expected:
            cmd += ["--expect-feature", expected]
        if proxy_url:
            cmd += ["--proxy", proxy_url]
        try:
            proc = _run_in_own_process_group(
                # A WRITABLE cwd, not the vendor checkout: SeleniumBase drops a
                # lock file into `downloaded_files/` relative to it, and the
                # checkout is root-owned while the service runs as `placeintel`.
                cmd, cwd=work_dir, env=env, timeout_s=MAPS_RPC_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise ScraperProError(f"maps-rpc worker timed out after {MAPS_RPC_TIMEOUT_S}s") from exc
        if not out_path.exists():
            raise ScraperProError(
                f"maps-rpc worker exited {proc.returncode} without writing a result: "
                f"{(proc.stderr or '')[-400:]}")
        payload = json.loads(out_path.read_text(encoding="utf-8"))

    identity = payload.get("identity")
    merge = payload.get("merge") or {}
    contiguity = merge.get("verdict")
    total = len(payload.get("reviews") or [])
    logger.info(
        "maps-rpc %s: %d reviews (%s on screen + %s walked), identity=%s "
        "contiguity=%s coverage=%s of %s pages=%s bootstrap=%ss walk=%ss",
        place.place_id, total, merge.get("head"), merge.get("walked"), identity,
        contiguity, payload.get("coverage"), payload.get("listed_review_count"),
        payload.get("pages"), payload.get("bootstrap_secs"), payload.get("walk_secs"),
    )
    # NOT keyed on start_offset. A non-zero offset is the NORMAL, healthy case —
    # Maps renders the first ~10 cards server-side, so the page's own earliest
    # request already starts after them and the head merge is what covers it.
    # Warning on the offset would print "the newest N reviews were not reachable"
    # on every correct run, which is both noise and false.
    if contiguity == "gap":
        logger.warning(
            "maps-rpc %s: %s review(s) fall between the %s on screen and the "
            "walk's start at offset %s — they are in neither half",
            place.place_id, merge.get("gap"), merge.get("head"),
            merge.get("start_offset"),
        )
    elif contiguity == "unverified":
        logger.warning(
            "maps-rpc %s: could not tell where the walk started, so the merge is "
            "unverified rather than proven complete", place.place_id,
        )
    coverage = payload.get("coverage")
    if coverage is None:
        logger.info(
            "maps-rpc %s: Google did not state a review count — coverage is "
            "unverified, not 100%%", place.place_id,
        )
    elif coverage < 1.0:
        logger.warning(
            "maps-rpc %s got %d of the %s reviews Google lists (%.0f%%) — the "
            "DOM path may still find more",
            place.place_id, total, payload.get("listed_review_count"), coverage * 100,
        )
    if not payload.get("ok"):
        raise ScraperProError(
            f"maps-rpc failed (identity={identity}, contiguity={contiguity}): "
            f"{payload.get('error') or 'no reason reported'}")
    return [_rpc_review_to_review(item, place.place_id)
            for item in payload["reviews"] if item.get("review_id")]


# ---------------------------------------------------------------------------
# Primary path: vendored google-reviews-scraper-pro
# ---------------------------------------------------------------------------

def _place_lock_key(place: Place, target_url: str | None) -> str:
    """Stable identity for the place lock.

    Every path that touches this place's rows must derive the same key, so the
    key is computed here rather than at each call site — two call sites that
    disagree hold two different locks and serialise nothing.
    """
    return place.place_id or target_url or place.name or "unknown-place"


def _primary_blockers(place: Place) -> list[str]:
    """Reasons the scraper-pro path cannot run (empty list == runnable)."""
    blockers: list[str] = []
    if not _scraper_target_url(place):
        blockers.append("place.maps_url is missing")
    if not SCRAPER_PYTHON.exists():
        blockers.append(f"venv python not found at {SCRAPER_PYTHON}")
    if not (SCRAPER_DIR / "start.py").exists():
        blockers.append(f"start.py not found in {SCRAPER_DIR}")
    return blockers


def _fetch_via_scraper_pro(
    place: Place, max_reviews: int | None, proxy_url: str | None = None,
    refresh: bool = False,
) -> list[Review]:
    """Scrape *place* under a machine-wide lock, then read the rows back.

    Everything that touches the vendor's SQLite file for this place — the
    refresh wipe, the subprocess, the read-back — happens inside one lock. Two
    processes scraping one place is what produced `FOREIGN KEY constraint
    failed` and a 300-scraped/91-stored run: the second run's wipe deleted the
    `places` row the first run's in-flight INSERTs referenced.

    A caller that blocks on the lock and finds the work already done reuses the
    result instead of scraping again — that is the point of waiting, not a
    stale-cache shortcut. The check is inside the lock so it cannot observe a
    half-written table.
    """
    target_url = _scraper_target_url(place)
    requested_at = time.time()
    with scrape_lock.place_scrape_lock(_place_lock_key(place, target_url)):
        if refresh:
            # Someone else may have finished a scrape while we queued. A scrape
            # that COMPLETED AFTER WE ASKED already satisfies "give me fresh
            # data", so re-running Chrome for 15 minutes would buy nothing —
            # and would wipe their rows to re-fetch the same reviews.
            # Note the boundary: a scrape that completed BEFORE we asked does
            # not count, or "refresh" would silently mean "recent enough".
            if _scrape_completed_since(place, target_url, requested_at):
                try:
                    fresh = _read_scraper_db(place, target_url)
                except ScraperProError:
                    fresh = []
                if fresh:
                    logger.info(
                        "another scrape of %s finished while we waited — reusing its "
                        "%d reviews instead of re-scraping", place.place_id, len(fresh),
                    )
                    return fresh
            _clear_scraper_db_entry(place, target_url)
        else:
            try:
                existing = _read_scraper_db(place, target_url)
            except ScraperProError:
                existing = []
            if existing and len(existing) >= (max_reviews or SCRAPER_REUSE_FLOOR):
                logger.info(
                    "scraper-db already holds %d reviews for %s — reusing without "
                    "launching Chrome", len(existing), place.place_id,
                )
                return existing
        with scrape_lock.scrape_slot():
            _run_scraper_pro(place, max_reviews, target_url, proxy_url=proxy_url)
        return _read_scraper_db(place, target_url)


def _scraper_target_url(place: Place) -> str | None:
    """Return a Google Maps URL that scraper-pro can search from reliably."""
    maps_url = place.maps_url or ""
    if _maps_url_has_place_name(maps_url) or _maps_url_has_query_identity(maps_url):
        return maps_url
    if not place.name or not place.place_id:
        return maps_url or None
    name = urllib.parse.quote_plus(place.name)
    pid = urllib.parse.quote(str(place.place_id), safe=":")
    return f"https://www.google.com/maps/place/{name}/?q=place_id:{pid}"


def _maps_url_has_place_name(maps_url: str) -> bool:
    parsed = urllib.parse.urlparse(maps_url)
    marker = "/maps/place/"
    if marker not in parsed.path:
        return False
    return bool(parsed.path.split(marker, 1)[1].strip("/"))


def _maps_url_has_query_identity(maps_url: str) -> bool:
    parsed = urllib.parse.urlparse(maps_url)
    params = urllib.parse.parse_qs(parsed.query)
    return bool(params.get("q") and (params.get("ftid") or params.get("cid")))


def _build_scraper_config(
    place: Place, max_reviews: int | None, target_url: str | None = None, proxy_url: str | None = None
) -> dict[str, Any]:
    """Minimal config.yaml content (keys per vendor config.sample.yaml)."""
    target_url = target_url or _scraper_target_url(place)
    target_limit = int(max_reviews) if max_reviews else 0
    calculated_scroll_attempts = (
        max(200, (target_limit // 10) + 50) if target_limit > 0
        else max(300, (int(place.review_count or 1000) // 10) + 50)
    )
    cfg: dict[str, Any] = {
        "headless": True,
        "sort_by": "newest",
        "scrape_mode": "refresh" if (target_limit > 50) else "update",
        "stop_threshold": 0 if (target_limit > 50) else 3,
        "convert_dates": True,            # relative dates -> ISO in review_date
        "download_images": False,         # URLs are kept in user_images regardless
        "backup_to_json": False,
        "use_mongodb": False,
        "use_s3": False,
        "max_reviews": target_limit,      # 0 = unlimited
        "max_scroll_attempts": calculated_scroll_attempts,
        "scroll_idle_limit": 25,
        "db_path": str(_scraper_db_path()),  # persistent: incremental runs stay cheap
        "log_dir": str(_scraper_log_dir()),
        "log_file": "scraper.log",
        "businesses": [
            {
                "url": target_url,
                "custom_params": {"company": place.place_id},
            }
        ],
    }
    if proxy_url:
        cfg["proxy"] = proxy_url
    return cfg


def _run_scraper_pro(
    place: Place, max_reviews: int | None, target_url: str | None = None, proxy_url: str | None = None
) -> None:
    """Launch the vendored scraper, routing an authenticated proxy via a relay.

    Chrome has no flag for proxy credentials, and SeleniumBase's workaround is a
    generated extension that does not load in this headless mode. Handing it
    ``user:pass@host:port`` therefore produces a blank page and no exception —
    measured 2026-08-31: egress ``""``, no title, no tabs. The relay gives Chrome
    a credential-free ``127.0.0.1`` address instead; same call, same minute,
    egress ``113.182.209.222`` (Vietnamese residential).
    """
    if proxy_relay.needs_relay(proxy_url):
        with proxy_relay.local_relay(proxy_url) as relay_url:
            _run_scraper_pro_unproxied(place, max_reviews, target_url, relay_url)
        return
    _run_scraper_pro_unproxied(place, max_reviews, target_url, proxy_url)


def _run_scraper_pro_unproxied(
    place: Place, max_reviews: int | None, target_url: str | None = None, proxy_url: str | None = None
) -> None:
    config.ensure_dirs()
    work_dir = _scraper_work_dir()
    driver_dir = _scraper_driver_dir()
    home_dir = _scraper_home_dir()
    work_dir.mkdir(parents=True, exist_ok=True)
    driver_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".cache").mkdir(parents=True, exist_ok=True)
    (home_dir / ".config").mkdir(parents=True, exist_ok=True)
    (home_dir / ".local" / "share").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "HOME": str(home_dir),
        "XDG_CACHE_HOME": str(home_dir / ".cache"),
        "XDG_CONFIG_HOME": str(home_dir / ".config"),
        "XDG_DATA_HOME": str(home_dir / ".local" / "share"),
    })
    scraper_config = _build_scraper_config(place, max_reviews, target_url, proxy_url=proxy_url)
    proxy_setup = f"\nsb_config.proxy = {proxy_url!r}\nsb_config.proxy_string = {proxy_url!r}\n" if proxy_url else ""
    with tempfile.TemporaryDirectory(prefix="placeintel-scraper-") as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(scraper_config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        # Bootstrap via -c to force SeleniumBase UC onto a genuinely free debug
        # port: its 9222 probe misreads half-dead listeners (e.g. a devtools-MCP
        # Chrome holding 9222 but refusing connections) as "free" and collides.
        # sb_config.multi_proxy=True short-circuits straight to free_port().
        # NEW_DRIVER_DIR keeps chromedriver downloads out of read-only site-packages.
        # setup_driver is wrapped to pre-seed Google consent cookies (SOCS=CAI):
        # EU datacenter IPs get the "Bevor Sie zu Google Maps weitergehen"
        # interstitial and the vendor's dismissal only matches English buttons,
        # so every scrape recorded the consent page with zero review rows.
        bootstrap = f'''
from pathlib import Path
from seleniumbase import config as sb_config
from seleniumbase.config import settings as sb_settings
driver_dir = {str(driver_dir)!r}
Path(driver_dir).mkdir(parents=True, exist_ok=True)
sb_config.multi_proxy = True
sb_settings.NEW_DRIVER_DIR = driver_dir
sb_config.settings = sb_settings{proxy_setup}
import sys, runpy
sys.path.insert(0, {str(SCRAPER_DIR)!r})
try:
    import modules.scraper as _scraper_mod
    _original_setup_driver = _scraper_mod.GoogleReviewsScraper.setup_driver
    def _consent_seeded_setup_driver(self, headless):
        driver = _original_setup_driver(self, headless)
        _raw_get = driver.get
        def _en_get(url):
            if isinstance(url, str) and "google.com" in url and "hl=" not in url:
                sep = "&" if "?" in url else "?"
                url = f"{{url}}{{sep}}hl=en"
            return _raw_get(url)
        driver.get = _en_get
        try:
            driver.get("https://www.google.com/robots.txt")
            driver.add_cookie(dict(name="SOCS", value="CAI", domain=".google.com"))
            driver.add_cookie(dict(name="CONSENT", value="PENDING+987", domain=".google.com"))
            driver.add_cookie(dict(name="PREF", value="hl=en", domain=".google.com"))
        except Exception as exc:
            print("consent cookie seeding failed:", exc, file=sys.stderr)
        try:
            driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {{"headers": {{"Accept-Language": "en-US,en;q=0.9"}}}})
        except Exception as exc:
            print("accept-language header setting failed:", exc, file=sys.stderr)
        return driver
    _scraper_mod.GoogleReviewsScraper.setup_driver = _consent_seeded_setup_driver

    _original_navigate_to_place = _scraper_mod.GoogleReviewsScraper.navigate_to_place
    def _en_forced_navigate_to_place(self, driver, url, wait):
        if url and "hl=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{{url}}{{sep}}hl=en"
        return _original_navigate_to_place(self, driver, url, wait)
    _scraper_mod.GoogleReviewsScraper.navigate_to_place = _en_forced_navigate_to_place
except Exception as exc:
    print("consent patch skipped:", exc, file=sys.stderr)
sys.argv = ["start.py"] + sys.argv[1:]
runpy.run_path({str(SCRAPER_DIR / "start.py")!r}, run_name="__main__")
'''
        cmd = [str(SCRAPER_PYTHON), "-c", bootstrap, "scrape",
               "--config", str(config_path)]
        logger.info("Running scraper-pro for %s: %s", place.place_id, " ".join(cmd))
        try:
            proc = _run_in_own_process_group(cmd, cwd=work_dir, env=env)
        except subprocess.TimeoutExpired as exc:
            raise ScraperProError(f"timed out after {SCRAPER_TIMEOUT_S}s") from exc
        except OSError as exc:
            raise ScraperProError(f"could not launch scraper: {exc}") from exc

    if proc.stdout:
        logger.debug("scraper-pro stdout (tail): %s", proc.stdout[-2000:])
    if proc.stderr:
        logger.debug("scraper-pro stderr (tail): %s", proc.stderr[-2000:])
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        raise ScraperProError(f"exit code {proc.returncode}: {tail}")


def _run_in_own_process_group(
    cmd: list[str], *, cwd: Path, env: dict[str, str],
    timeout_s: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* in its own process group and reap the WHOLE tree on timeout.

    `subprocess.run(..., timeout=)` sends SIGKILL to the direct child only, and
    the child here is a Python launcher whose real cost is a chromedriver and a
    ~13-process Chrome tree two levels down. Those survive as PPid-1 orphans —
    measured on prod as four abandoned trees holding 4.7 GB while systemd
    reported the service at 82 MB, because the orphans sat outside its cgroup.

    `start_new_session=True` makes the child a process-group leader so
    `killpg` reaches every descendant. SIGTERM first, so the vendor's own
    handlers get a chance to close the `scrape_sessions` row it opened; SIGKILL
    after the grace period for anything that ignores it.
    """
    # Resolved here, not as a default argument: a default is evaluated once at
    # import, which silently detaches it from the module attribute. Doing that
    # made the grandchild-reaping test wait out its own child instead of timing
    # out, and it reported as a failure two minutes later rather than as a hang.
    timeout_s = SCRAPER_TIMEOUT_S if timeout_s is None else timeout_s
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=stdout, stderr=stderr)
    except BaseException:
        # Cancellation, KeyboardInterrupt, a caller giving up — every exit that
        # is not a clean return must still take the browser tree with it.
        _kill_process_group(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    """SIGTERM then SIGKILL the child's whole process group. Never raises."""
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        return  # already reaped
    for sig, wait_s in ((signal.SIGTERM, SCRAPER_TERM_GRACE_S), (signal.SIGKILL, 5)):
        try:
            os.killpg(pgid, sig)
        except OSError:
            return  # group is gone
        try:
            proc.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue
    logger.warning("scraper process group %d survived SIGKILL", pgid)


def _read_scraper_db(place: Place, target_url: str | None = None) -> list[Review]:
    """Map rows for THIS place from the scraper's SQLite db into Review objects."""
    db_path = _scraper_db_path()
    if not db_path.exists():
        raise ScraperProError(f"scraper db never created at {db_path}")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ScraperProError(f"cannot open scraper db: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        urls = []
        for url in (target_url, place.maps_url):
            if url and url not in urls:
                urls.append(url)
        internal_ids: list[str] = []
        for url in urls:
            for internal_id in _scraper_internal_place_ids(conn, url, place_name=place.name):
                if internal_id not in internal_ids:
                    internal_ids.append(internal_id)
        if not internal_ids:
            raise ScraperProError(
                f"no scraper-db place row matches urls {urls!r}"
            )
        marks = ",".join("?" for _ in internal_ids)
        rows = conn.execute(
            f"SELECT * FROM reviews WHERE place_id IN ({marks}) AND is_deleted = 0",
            internal_ids,
        ).fetchall()
        if not rows and place.review_count != 0:
            # review_count None = unknown (URL-locked place that skipped
            # discovery) — treat zero rows as a failed scrape, not "no reviews".
            raise ScraperProError(
                f"scraper-pro returned zero review rows for {place.name}; "
                f"Google lists {place.review_count or 'an unknown number of'} reviews"
            )
    except sqlite3.Error as exc:
        raise ScraperProError(f"scraper db query failed: {exc}") from exc
    finally:
        conn.close()
    reviews = [_scraper_row_to_review(dict(row), place.place_id) for row in rows]
    logger.info("scraper-pro yielded %d reviews for %s", len(reviews), place.place_id)
    return reviews


def _scrape_completed_since(place: Place, target_url: str | None, since_epoch: float) -> bool:
    """True when a scrape of this place COMPLETED after *since_epoch*.

    Read from the vendor's own `scrape_sessions.completed_at`, which it writes in
    UTC ISO-8601. Only `status='completed'` counts: a row left at `'running'` is
    a killed process, and an `'empty'` one found nothing worth reusing.

    Any doubt returns False, which costs a re-scrape. The opposite default would
    hand a caller someone else's stale rows while reporting them as fresh.
    """
    db_path = _scraper_db_path()
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error:
        return False
    conn.row_factory = sqlite3.Row
    try:
        internal_ids: list[str] = []
        for url in [u for u in (target_url, place.maps_url) if u]:
            for iid in _scraper_internal_place_ids(conn, url, place_name=place.name):
                if iid not in internal_ids:
                    internal_ids.append(iid)
        if not internal_ids:
            return False
        marks = ",".join("?" for _ in internal_ids)
        row = conn.execute(
            f"SELECT MAX(completed_at) AS latest FROM scrape_sessions "
            f"WHERE place_id IN ({marks}) AND status = 'completed' "
            f"AND completed_at IS NOT NULL",
            internal_ids,
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    latest = (row or {})["latest"] if row else None
    if not latest:
        return False
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(latest)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() > since_epoch


def _scraper_has_known_empty_review_rows(place: Place, target_url: str | None) -> bool:
    """True when a previous scraper-pro run mapped this URL but collected nothing."""
    if not target_url or place.review_count == 0:
        return False  # a known zero-review place legitimately yields zero rows
    db_path = _scraper_db_path()
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    conn.row_factory = sqlite3.Row
    try:
        urls = []
        for url in (target_url, place.maps_url):
            if url and url not in urls:
                urls.append(url)
        internal_ids: list[str] = []
        for url in urls:
            for internal_id in _scraper_internal_place_ids(conn, url):
                if internal_id not in internal_ids:
                    internal_ids.append(internal_id)
        if not internal_ids:
            return False
        marks = ",".join("?" for _ in internal_ids)
        count = conn.execute(
            f"SELECT COUNT(*) AS n FROM reviews WHERE place_id IN ({marks}) AND is_deleted = 0",
            internal_ids,
        ).fetchone()["n"]
        return int(count or 0) == 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _clear_scraper_db_entry(place: Place, target_url: str | None) -> None:
    """Wipe this place's rows from the scraper db so a refresh re-scrapes clean.

    Caller must already hold the place scrape lock — these DELETEs remove the
    `places` row that any concurrent run's review INSERTs reference.

    The vendor holds write locks with a 30 s budget, so this connection matches
    it rather than taking sqlite3's 5 s default. A failure here is reported, not
    swallowed: the caller is about to re-scrape believing the table is empty,
    and a silent no-op turns "refresh" into "append to stale rows".
    """
    db_path = _scraper_db_path()
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}", uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error as exc:
        raise ScraperProError(f"cannot open scraper db to clear {place.place_id}: {exc}") from exc
    try:
        urls = [u for u in (target_url, place.maps_url) if u]
        internal_ids: list[str] = []
        for url in urls:
            for iid in _scraper_internal_place_ids(conn, url):
                if iid not in internal_ids:
                    internal_ids.append(iid)
        if internal_ids:
            marks = ",".join("?" for _ in internal_ids)
            conn.execute(f"DELETE FROM reviews WHERE place_id IN ({marks})", internal_ids)
            conn.execute(f"DELETE FROM places WHERE place_id IN ({marks})", internal_ids)
            conn.execute(f"DELETE FROM place_aliases WHERE canonical_id IN ({marks})", internal_ids)
        for url in urls:
            conn.execute("DELETE FROM places WHERE original_url = ? OR resolved_url = ?", (url, url))
            conn.execute("DELETE FROM place_aliases WHERE original_url = ?", (url,))
        conn.commit()
    except sqlite3.Error as exc:
        raise ScraperProError(
            f"could not clear scraper db rows for {place.place_id}: {exc}"
        ) from exc
    finally:
        conn.close()


def _scraper_db_path() -> Path:
    return (config.DATA_DIR / "scraper_pro_reviews.db").resolve()


def _scraper_log_dir() -> Path:
    return (config.DATA_DIR / "vendor" / "google-reviews-scraper-pro" / "logs").resolve()


def _scraper_work_dir() -> Path:
    return (config.DATA_DIR / "vendor" / "google-reviews-scraper-pro" / "work").resolve()


def _scraper_driver_dir() -> Path:
    return (config.DATA_DIR / "vendor" / "google-reviews-scraper-pro" / "drivers").resolve()


def _scraper_home_dir() -> Path:
    return (config.DATA_DIR / "vendor" / "google-reviews-scraper-pro" / "home").resolve()


def _scraper_internal_place_ids(conn: sqlite3.Connection, maps_url: str, place_name: str | None = None) -> list[str]:
    """The scraper keys reviews by its own URL-derived id; match via original_url, base path, hex, or place name."""
    import re
    parsed = urllib.parse.urlparse(maps_url or "")
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else ""
    hex_m = re.search(r"0x[0-9a-fA-F]+", maps_url or "")
    hex_prefix = f"{hex_m.group(0)}:%" if hex_m else ""
    name_like = f"%{place_name[:25]}%" if place_name else ""

    rows = conn.execute(
        """
        SELECT place_id FROM places 
        WHERE original_url = ? OR resolved_url = ?
           OR (original_url LIKE ? AND ? != '')
           OR (resolved_url LIKE ? AND ? != '')
           OR (place_id LIKE ? AND ? != '')
           OR (place_name LIKE ? AND ? != '')
        UNION
        SELECT canonical_id FROM place_aliases 
        WHERE original_url = ?
           OR (original_url LIKE ? AND ? != '')
        """,
        (
            maps_url, maps_url,
            f"{clean_url}%", clean_url,
            f"{clean_url}%", clean_url,
            hex_prefix, hex_prefix,
            name_like, name_like,
            maps_url,
            f"{clean_url}%", clean_url,
        ),
    ).fetchall()
    return [row["place_id"] for row in rows]


def _scraper_row_to_review(row: dict[str, Any], place_id: str) -> Review:
    text_by_lang = _loads_json(row.get("review_text"), {})
    lang, text = next(iter(text_by_lang.items()), (None, None))
    owner_by_lang = _loads_json(row.get("owner_responses"), {})
    owner_response = next(
        (
            entry["text"]
            for entry in owner_by_lang.values()
            if isinstance(entry, dict) and entry.get("text")
        ),
        None,
    )
    images = _loads_json(row.get("user_images"), [])
    return Review(
        review_id=f"gsp:{row['review_id']}",
        place_id=place_id,
        author=row.get("author") or None,
        rating=float(row["rating"]) if row.get("rating") is not None else None,
        text=text or None,
        lang=lang,
        review_date=row.get("review_date") or row.get("raw_date") or None,
        owner_response=owner_response,
        images=images if isinstance(images, list) else [],
        source="scraper-pro",
        raw=row,
    )


# ---------------------------------------------------------------------------
# Fallback path: SerpAPI google_maps_reviews
# ---------------------------------------------------------------------------

def _fetch_via_serpapi(
    place: Place,
    max_reviews: int | None,
    context: str = "free review scraper unavailable",
    allow: bool | None = None,
    cause: BaseException | None = None,
) -> list[Review]:
    # Single choke point: the key is acquired here and nowhere else in this
    # module, so every fallback branch above is gated by construction.
    api_key = (spend.require_serpapi_key)(context, allow=allow, cause=cause)
    data_id = place.raw.get("data_id") or place.place_id
    if max_reviews is None:
        max_pages = SERPAPI_DEFAULT_MAX_PAGES
        logger.info(
            "max_reviews is None — capping SerpAPI at %d pages (~%d reviews) "
            "to protect credits",
            max_pages, max_pages * SERPAPI_PAGE_SIZE,
        )
    else:
        # First page carries only SERPAPI_INITIAL_PAGE_SIZE items — a flat
        # 20-per-page estimate stops one page short for small caps (8 ≠ 20).
        remaining = max(0, max_reviews - SERPAPI_INITIAL_PAGE_SIZE)
        max_pages = 1 + -(-remaining // SERPAPI_PAGE_SIZE)  # ceil division

    params: dict[str, str] = {
        "engine": "google_maps_reviews",
        "data_id": str(data_id),
        "hl": "en",
        "sort_by": "newestFirst",
        "api_key": api_key,
    }
    collected: list[Review] = []
    for page in range(1, max_pages + 1):
        try:
            payload = _serpapi_get(params, page)
            if page == 1:
                # URL-locked places skip discovery, so listing metadata (rating,
                # review_count, address) arrives here via place_info instead.
                _backfill_place_info(place, payload)
        except RuntimeError:
            # A later page timing out must not void reviews already in hand — a report
            # on the newest 20 beats reverting the user to an empty dossier. Only a
            # first-page failure (nothing collected) has nothing to salvage, so re-raise.
            if collected:
                if serpapi_first_page_only_gap(
                    place, len(collected), max_reviews, had_next_page=True
                ):
                    raise PartialReviewsError(
                        f"SerpAPI stopped after its first {len(collected)} reviews "
                        f"for {place.name}; Google lists {place.review_count or 'more'} "
                        "and the next reviews page failed"
                    )
                logger.warning(
                    "SerpAPI page %d failed — salvaging %d reviews already collected for %s",
                    page, len(collected), place.place_id,
                )
                break
            raise
        batch = payload.get("reviews") or []
        collected = collected + [_serp_item_to_review(item, place.place_id) for item in batch]
        logger.debug("SerpAPI page %d: %d reviews (total %d)", page, len(batch), len(collected))
        if max_reviews is not None and len(collected) >= max_reviews:
            break
        next_token = (payload.get("serpapi_pagination") or {}).get("next_page_token")
        if not next_token:
            if serpapi_first_page_only_gap(place, len(collected), max_reviews):
                raise PartialReviewsError(
                    f"SerpAPI returned only its first {len(collected)} reviews for "
                    f"{place.name} and no next_page_token; Google lists "
                    f"{place.review_count or 'more'}"
                )
            break
        params = {**params, "next_page_token": next_token}
    logger.info("SerpAPI yielded %d reviews for %s", len(collected), place.place_id)
    return collected


def _backfill_place_info(place: Place, payload: dict[str, Any]) -> None:
    """Fill listing gaps in *place* from google_maps_reviews' place_info block.
    Only missing fields are touched — discovered places keep their search data."""
    info = payload.get("place_info")
    if not isinstance(info, dict):
        return
    if place.rating is None and info.get("rating") is not None:
        try:
            place.rating = float(info["rating"])
        except (TypeError, ValueError):
            pass
    if place.review_count is None and info.get("reviews") is not None:
        try:
            place.review_count = int(info["reviews"])
        except (TypeError, ValueError):
            pass
    if not place.address and info.get("address"):
        place.address = str(info["address"])
    if not place.name and info.get("title"):
        place.name = str(info["title"])


def _serpapi_get(params: dict[str, str], page: int) -> dict[str, Any]:
    try:
        resp = requests.get(SERPAPI_URL, params=params, timeout=SERPAPI_TIMEOUT_S)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        # requests embeds the full URL (incl. api_key=…) in str(exc) — redact before it
        # propagates into job events / client-facing error fields.
        raise RuntimeError(config.redact_secrets(f"SerpAPI request failed on page {page}: {exc}")) from exc
    if payload.get("error"):
        raise RuntimeError(f"SerpAPI error on page {page}: {payload['error']}")
    return payload


def _serp_item_to_review(item: dict[str, Any], place_id: str) -> Review:
    user = item.get("user") or {}
    rid = item.get("review_id") or _serp_synthetic_id(item, user)
    response = item.get("response") or {}
    return Review(
        review_id=f"serp:{rid}",
        place_id=place_id,
        author=user.get("name"),
        rating=float(item["rating"]) if item.get("rating") is not None else None,
        text=item.get("snippet") or _extracted_snippet_text(item),
        lang=None,
        review_date=item.get("iso_date") or item.get("date"),
        owner_response=response.get("snippet"),
        images=_serp_images(item),
        source="serpapi",
        raw=item,
    )


def _serp_synthetic_id(item: dict[str, Any], user: dict[str, Any]) -> str:
    basis = "|".join((
        user.get("name") or "",
        item.get("iso_date") or item.get("date") or "",
        item.get("snippet") or "",
    ))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _extracted_snippet_text(item: dict[str, Any]) -> str | None:
    extracted = item.get("extracted_snippet")
    if isinstance(extracted, dict):
        return extracted.get("original") or extracted.get("translated")
    return extracted if isinstance(extracted, str) else None


def _serp_images(item: dict[str, Any]) -> list:
    images = []
    for entry in item.get("images") or []:
        if isinstance(entry, dict):
            url = entry.get("thumbnail") or entry.get("image") or entry.get("link")
        else:
            url = entry
        if url:
            images.append(url)
    return images


#: Fetchers that walk a place's WHOLE review list, as opposed to SerpAPI's
#: 8-row first page. Kept as one predicate rather than a literal at each call
#: site: the two sites in pipeline.py both compared against "scraper-pro", so
#: adding the RPC as a second full-history source would have silently stopped
#: the stale-first-page cleanup from ever firing again — a gate that keeps
#: passing while its subject set shrinks to nothing.
FULL_HISTORY_SOURCES = ("scraper-pro", "maps-rpc")


def is_full_history(rows: list[Review]) -> bool:
    """True when *rows* came from a fetcher that reads the entire review list."""
    return any(r.source in FULL_HISTORY_SOURCES for r in rows)


def serpapi_first_page_only_gap(
    place: Place,
    review_count: int,
    max_reviews: int | None,
    *,
    had_next_page: bool = False,
) -> bool:
    """True when an 8-review SerpAPI first page is known to be underfilled."""
    if review_count <= 0 or review_count > SERPAPI_INITIAL_PAGE_SIZE:
        return False
    requested_more = max_reviews is None or max_reviews > review_count
    listed_more = had_next_page or (
        place.review_count is not None and place.review_count > review_count
    )
    return requested_more and listed_more


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _order_and_cap(
    reviews: list[Review], max_reviews: int | None, newest_first: bool
) -> list[Review]:
    """Sort newest-first, truncate to the most recent N, then honor final order."""
    ordered = sorted(reviews, key=lambda r: r.review_date or "", reverse=True)
    if max_reviews is not None:
        ordered = ordered[:max_reviews]
    return ordered if newest_first else list(reversed(ordered))


def _loads_json(value: Any, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value if value not in (None, "") else default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
