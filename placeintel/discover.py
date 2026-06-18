"""Place discovery on Google Maps.

Primary path: gosom/google-maps-scraper run in Docker (foreground, temp-dir
mounts for queries/results, named volume for the Playwright cache). Fallback:
SerpAPI google_maps engine — on any gosom failure or force_serpapi=True, and
only if a key is discoverable via config. gosom field mapping follows the
json struct tags of the Entry type in gmaps/entry.go (verified upstream):
title, category, address, open_hours, web_site, phone, review_count,
review_rating, latitude, longitude/longtitude (legacy spelling), price_range,
link, place_id/cid/data_id.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from . import config
from .cache import Place

log = logging.getLogger(__name__)

GOSOM_CONTAINER = "gmaps-scraper"
GOSOM_VOLUME = "gmaps-playwright-cache"
GOSOM_TIMEOUT_S = 20 * 60
GOSOM_PULL_TIMEOUT_S = 15 * 60
DOCKER_INFO_TIMEOUT_S = 30
DOCKER_START_POLL_S = 5
DOCKER_START_MAX_WAIT_S = 90
SERPAPI_URL = "https://serpapi.com/search"
SERPAPI_TIMEOUT_S = 90

_CID_QUERY_RE = re.compile(r"[?&]cid=(\d+)")
_HEX_PAIR_RE = re.compile(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")


def discover(
    query: str,
    location: str | None = None,
    depth: int = 1,
    lang: str = "en",
    force_serpapi: bool = False,
) -> list[Place]:
    """Discover places on Google Maps; returns deduplicated Place objects."""
    search_query = f"{query} in {location}" if location else query

    gosom_error: Exception | None = None
    if not force_serpapi:
        try:
            return _dedupe(_discover_gosom(search_query, depth=depth, lang=lang))
        except Exception as exc:  # noqa: BLE001 — any gosom failure triggers fallback
            gosom_error = exc
            log.warning("gosom discovery failed: %s — trying SerpAPI fallback", exc)

    api_key = config.serpapi_api_key()
    if not api_key:
        reason = f"gosom failed ({gosom_error})" if gosom_error else "force_serpapi=True"
        raise RuntimeError(f"{reason}, and no SerpAPI key is configured") from gosom_error

    return _dedupe(_discover_serpapi(search_query, lang=lang, api_key=api_key))


# -- gosom / Docker path -----------------------------------------------------

def _docker_is_up() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=DOCKER_INFO_TIMEOUT_S
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _ensure_docker_daemon() -> None:
    if _docker_is_up():
        return
    if sys.platform != "darwin":
        raise RuntimeError("Docker daemon is not running and auto-start is macOS-only")
    log.info("Docker daemon not running — launching Docker Desktop")
    subprocess.run(["open", "-a", "Docker"], capture_output=True, check=False)
    deadline = time.monotonic() + DOCKER_START_MAX_WAIT_S
    while time.monotonic() < deadline:
        time.sleep(DOCKER_START_POLL_S)
        if _docker_is_up():
            log.info("Docker daemon is up")
            return
    raise RuntimeError(f"Docker daemon did not come up within {DOCKER_START_MAX_WAIT_S}s")


def _ensure_gosom_image() -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", config.GOSOM_IMAGE], capture_output=True
    )
    if inspect.returncode == 0:
        return
    log.info("Pulling image %s (first run only)", config.GOSOM_IMAGE)
    pull = subprocess.run(
        ["docker", "pull", config.GOSOM_IMAGE],
        capture_output=True, text=True, timeout=GOSOM_PULL_TIMEOUT_S,
    )
    if pull.returncode != 0:
        raise RuntimeError(f"docker pull failed: {pull.stderr.strip()[-500:]}")


def _discover_gosom(search_query: str, depth: int, lang: str) -> list[Place]:
    _ensure_docker_daemon()
    _ensure_gosom_image()

    with tempfile.TemporaryDirectory(prefix="placeintel-gosom-") as tmp:
        queries_dir = Path(tmp) / "queries"
        results_dir = Path(tmp) / "results"
        queries_dir.mkdir()
        results_dir.mkdir()
        (queries_dir / "queries.txt").write_text(search_query + "\n", encoding="utf-8")

        subprocess.run(["docker", "rm", "-f", GOSOM_CONTAINER], capture_output=True)
        cmd = [
            "docker", "run", "--name", GOSOM_CONTAINER,
            "-v", f"{GOSOM_VOLUME}:/opt",
            "-v", f"{queries_dir}:/queries",
            "-v", f"{results_dir}:/results",
            config.GOSOM_IMAGE,
            "-depth", str(depth), "-lang", lang, "-json",
            "-results", "/results/results.json",
            "-input", "/queries/queries.txt",
            "-exit-on-inactivity", "3m",
        ]
        log.info("Running gosom for %r (depth=%d lang=%s)", search_query, depth, lang)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=GOSOM_TIMEOUT_S)

        results_file = results_dir / "results.json"
        if not results_file.exists():
            raise RuntimeError(
                f"gosom produced no results file (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '').strip()[-500:]}"
            )
        if proc.returncode != 0:
            log.warning("gosom exited %d but wrote results — using them", proc.returncode)
        entries = _parse_results_json(results_file.read_text(encoding="utf-8"))

    places = [place for place in map(_gosom_entry_to_place, entries) if place]
    log.info("gosom returned %d entries → %d places", len(entries), len(places))
    return places


def _parse_results_json(text: str) -> list[dict]:
    """Handle both a JSON array and newline-delimited JSON objects."""
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            log.debug("Results not a valid JSON array; trying NDJSON")
    entries: list[dict] = []
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            log.debug("Skipping unparseable results line: %.80s", candidate)
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def _gosom_entry_to_place(entry: dict) -> Place | None:
    name = entry.get("title")
    if not name:
        return None
    place_id = (
        entry.get("place_id")
        or entry.get("cid")
        or entry.get("data_id")
        or _cid_from_link(entry.get("link"))
    )
    if not place_id:
        log.warning("Skipping entry %r: no stable identifier", name)
        return None
    categories = entry.get("categories") or []
    return Place(
        place_id=str(place_id), name=str(name),
        category=entry.get("category") or (categories[0] if categories else None),
        address=entry.get("address") or None,
        lat=_as_float(entry.get("latitude")),
        lng=_as_float(entry.get("longitude", entry.get("longtitude"))),
        rating=_as_float(entry.get("review_rating")),
        review_count=_as_int(entry.get("review_count")),
        phone=entry.get("phone") or None, website=entry.get("web_site") or None,
        hours=entry.get("open_hours") or None,
        price_level=entry.get("price_range") or None,
        maps_url=entry.get("link") or None, source="gosom", raw=dict(entry),
    )


def _cid_from_link(link: Any) -> str | None:
    if not link or not isinstance(link, str):
        return None
    cid_match = _CID_QUERY_RE.search(link)
    if cid_match:
        return cid_match.group(1)
    hex_match = _HEX_PAIR_RE.search(link)
    return hex_match.group(1) if hex_match else None


# -- SerpAPI fallback path ---------------------------------------------------

def _discover_serpapi(search_query: str, lang: str, api_key: str) -> list[Place]:
    params = {
        "engine": "google_maps",
        "q": search_query,
        "type": "search",
        "hl": lang,
        "api_key": api_key,
    }
    log.info("Querying SerpAPI google_maps for %r", search_query)
    response = requests.get(SERPAPI_URL, params=params, timeout=SERPAPI_TIMEOUT_S)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:  # malformed / non-JSON body (JSONDecodeError ⊂ ValueError)
        raise RuntimeError(
            f"SerpAPI returned a non-JSON response (HTTP {response.status_code}); "
            f"body starts: {response.text[:120]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"SerpAPI returned unexpected JSON type: {type(payload).__name__}")
    if payload.get("error"):
        raise RuntimeError(f"SerpAPI error: {payload['error']}")

    results = payload.get("local_results") or []
    if not results and isinstance(payload.get("place_results"), dict):
        results = [payload["place_results"]]  # single-place responses

    places = [place for place in map(_serpapi_result_to_place, results) if place]
    log.info("SerpAPI returned %d results → %d places", len(results), len(places))
    return places


def _serpapi_result_to_place(item: dict) -> Place | None:
    name = item.get("title")
    if not name:
        return None
    place_id = item.get("place_id") or item.get("data_id")
    if not place_id:
        log.warning("Skipping SerpAPI result %r: no place_id/data_id", name)
        return None
    gps = item.get("gps_coordinates") or {}
    fallback_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
    maps_url = item.get("link") or fallback_url
    return Place(
        place_id=str(place_id), name=str(name),
        category=item.get("type") or None, address=item.get("address") or None,
        lat=_as_float(gps.get("latitude")), lng=_as_float(gps.get("longitude")),
        rating=_as_float(item.get("rating")),
        review_count=_as_int(item.get("reviews")),
        phone=item.get("phone") or None, website=item.get("website") or None,
        hours=item.get("operating_hours") or item.get("hours") or None,
        price_level=item.get("price") or None, maps_url=maps_url,
        source="serpapi", raw=dict(item),  # raw keeps data_id for reviews module
    )


# -- shared helpers ----------------------------------------------------------

def _dedupe(places: list[Place]) -> list[Place]:
    seen: set[str] = set()
    unique: list[Place] = []
    for place in places:
        if place.place_id in seen:
            continue
        seen.add(place.place_id)
        unique.append(place)
    return unique


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None
