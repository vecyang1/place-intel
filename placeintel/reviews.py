"""Review fetching: vendored google-reviews-scraper-pro primary, SerpAPI fallback.

PRIMARY — we write a one-off config.yaml to a temp dir, run `start.py scrape
  --config <path>` (cwd=vendor dir, its own .venv) with db_path on a persistent
  SQLite file in DATA_DIR so incremental change-detection works across runs.
  The scraper keys reviews by its own URL-derived place_id, so rows are mapped
  back to OUR place via its `places.original_url` column.
FALLBACK — SerpAPI `google_maps_reviews` engine (paginated, ~20 reviews/page).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import requests
import yaml

from . import config
from .cache import Place, Review

logger = logging.getLogger(__name__)

SCRAPER_DIR = config.VENDOR_DIR / "google-reviews-scraper-pro"
SCRAPER_PYTHON = SCRAPER_DIR / ".venv" / "bin" / "python"
SCRAPER_TIMEOUT_S = 30 * 60

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
) -> list[Review]:
    """Fetch reviews for *place*, newest-N semantics regardless of final order.

    Primary path runs the vendored scraper-pro when its venv exists and
    place.maps_url is set; any primary failure logs the reason and falls back
    to SerpAPI (requires a key — see config.serpapi_api_key()).
    """
    if force_serpapi:
        logger.info("force_serpapi=True — skipping scraper-pro for %s", place.place_id)
        return _order_and_cap(_fetch_via_serpapi(place, max_reviews), max_reviews, newest_first)

    blockers = _primary_blockers(place)
    if blockers:
        logger.info(
            "scraper-pro unavailable for %s (%s) — using SerpAPI fallback",
            place.place_id, "; ".join(blockers),
        )
        return _order_and_cap(_fetch_via_serpapi(place, max_reviews), max_reviews, newest_first)

    try:
        reviews = _fetch_via_scraper_pro(place, max_reviews)
        return _order_and_cap(reviews, max_reviews, newest_first)
    except ScraperProError as exc:
        logger.warning(
            "scraper-pro failed for %s: %s — falling back to SerpAPI", place.place_id, exc
        )
    return _order_and_cap(_fetch_via_serpapi(place, max_reviews), max_reviews, newest_first)


# ---------------------------------------------------------------------------
# Primary path: vendored google-reviews-scraper-pro
# ---------------------------------------------------------------------------

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


def _fetch_via_scraper_pro(place: Place, max_reviews: int | None) -> list[Review]:
    target_url = _scraper_target_url(place)
    _run_scraper_pro(place, max_reviews, target_url)
    return _read_scraper_db(place, target_url)


def _scraper_target_url(place: Place) -> str | None:
    """Return a Google Maps URL that scraper-pro can search from reliably."""
    maps_url = place.maps_url or ""
    if _maps_url_has_place_name(maps_url):
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


def _build_scraper_config(
    place: Place, max_reviews: int | None, target_url: str | None = None
) -> dict[str, Any]:
    """Minimal config.yaml content (keys per vendor config.sample.yaml)."""
    target_url = target_url or _scraper_target_url(place)
    return {
        "headless": True,
        "sort_by": "newest",
        "scrape_mode": "update",
        "convert_dates": True,            # relative dates -> ISO in review_date
        "download_images": False,         # URLs are kept in user_images regardless
        "backup_to_json": False,
        "use_mongodb": False,
        "use_s3": False,
        "max_reviews": int(max_reviews) if max_reviews else 0,  # 0 = unlimited
        "db_path": str(_scraper_db_path()),  # persistent: incremental runs stay cheap
        "businesses": [
            {
                "url": target_url,
                "custom_params": {"company": place.place_id},
            }
        ],
    }


def _run_scraper_pro(
    place: Place, max_reviews: int | None, target_url: str | None = None
) -> None:
    config.ensure_dirs()
    scraper_config = _build_scraper_config(place, max_reviews, target_url)
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
        bootstrap = (
            "from seleniumbase import config as sb_config; "
            "sb_config.multi_proxy = True; "
            "import sys, runpy; "
            "sys.argv = ['start.py'] + sys.argv[1:]; "
            "runpy.run_path('start.py', run_name='__main__')"
        )
        cmd = [str(SCRAPER_PYTHON), "-c", bootstrap, "scrape",
               "--config", str(config_path)]
        logger.info("Running scraper-pro for %s: %s", place.place_id, " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                cwd=SCRAPER_DIR,
                capture_output=True,
                text=True,
                timeout=SCRAPER_TIMEOUT_S,
            )
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
            for internal_id in _scraper_internal_place_ids(conn, url):
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
    except sqlite3.Error as exc:
        raise ScraperProError(f"scraper db query failed: {exc}") from exc
    finally:
        conn.close()
    reviews = [_scraper_row_to_review(dict(row), place.place_id) for row in rows]
    logger.info("scraper-pro yielded %d reviews for %s", len(reviews), place.place_id)
    return reviews


def _scraper_db_path() -> Path:
    return (config.DATA_DIR / "scraper_pro_reviews.db").resolve()


def _scraper_internal_place_ids(conn: sqlite3.Connection, maps_url: str) -> list[str]:
    """The scraper keys reviews by its own URL-derived id; match via original_url."""
    rows = conn.execute(
        """
        SELECT place_id FROM places WHERE original_url = ?
        UNION
        SELECT canonical_id FROM place_aliases WHERE original_url = ?
        """,
        (maps_url, maps_url),
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

def _fetch_via_serpapi(place: Place, max_reviews: int | None) -> list[Review]:
    api_key = config.serpapi_api_key()
    if not api_key:
        raise RuntimeError(
            "SerpAPI fallback unavailable: no key (set SERPAPI_API_KEY or "
            "install the serpapi-mcp skill)."
        )
    data_id = place.raw.get("data_id") or place.place_id
    if max_reviews is None:
        max_pages = SERPAPI_DEFAULT_MAX_PAGES
        logger.info(
            "max_reviews is None — capping SerpAPI at %d pages (~%d reviews) "
            "to protect credits",
            max_pages, max_pages * SERPAPI_PAGE_SIZE,
        )
    else:
        max_pages = max(1, -(-max_reviews // SERPAPI_PAGE_SIZE))  # ceil division

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
