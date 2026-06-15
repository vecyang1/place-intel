"""Resolved source-photo metadata for API/UI display.

The app stays URL-first: this module never downloads images and never writes
cache files. It only normalizes already persisted provider/review URLs.
"""

from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlsplit, urlunsplit

PHOTO_LIST_LIMIT = 1
PHOTO_DETAIL_LIMIT = 6
PHOTO_REVIEW_SCAN_LIMIT = 120
PHOTO_REVIEW_IMAGE_LIMIT = 12
_IMAGE_KEYS = ("image", "original", "thumbnail", "thumb_url", "photo", "src", "url", "link")
_RAW_IMAGE_KEYS = ("image", "original", "thumbnail", "thumb_url", "photo", "src")
_RAW_IMAGE_CONTAINERS = ("photos", "images", "photo", "thumbnail", "media")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
_IMAGE_HOST_HINTS = ("googleusercontent.", "ggpht.", "gstatic.", "static.", "images.", "img.", "photo.", "cdn.")


def _safe_url(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))


def _looks_like_image_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        path.endswith(_IMAGE_EXTENSIONS)
        or any(hint in host for hint in _IMAGE_HOST_HINTS)
        or any(token in path for token in ("/image", "/photo", "/thumbnail"))
        or any(token in query for token in ("image=", "photo=", "thumbnail="))
    )


def _loads_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _image_entry(entry, *, require_image_url: bool = False) -> tuple[str | None, str | None]:
    if isinstance(entry, str):
        url = _safe_url(entry)
        if require_image_url and not _looks_like_image_url(url):
            return None, None
        return url, url
    if not isinstance(entry, dict):
        return None, None
    url = _safe_url(next((entry.get(key) for key in _IMAGE_KEYS if entry.get(key)), None))
    if require_image_url and not _looks_like_image_url(url):
        return None, None
    thumb = _safe_url(entry.get("thumbnail") or entry.get("thumb_url") or url)
    if require_image_url and thumb and not _looks_like_image_url(thumb):
        thumb = url
    return url, thumb or url


def _append(out: list[dict], seen: set[str], item: dict, limit: int) -> None:
    url = _safe_url(item.get("url"))
    if not url or url in seen or len(out) >= limit:
        return
    seen.add(url)
    item["url"] = url
    item["thumb_url"] = _safe_url(item.get("thumb_url")) or url
    out.append(item)


def _review_photos(conn: sqlite3.Connection, place_id: str, *, limit: int) -> list[dict]:
    rows = conn.execute(
        """SELECT review_id, author, rating, review_date, images_json, source
           FROM reviews WHERE place_id=? AND images_json IS NOT NULL
           ORDER BY CASE source WHEN 'scraper-pro' THEN 0 ELSE 1 END,
                    review_date DESC, scraped_at DESC LIMIT ?""",
        (place_id, PHOTO_REVIEW_SCAN_LIMIT),
    ).fetchall()
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        for entry in _loads_json(row["images_json"], []):
            url, thumb = _image_entry(entry)
            _append(out, seen, {
                "url": url, "thumb_url": thumb, "source": row["source"] or "review",
                "kind": "review", "place_id": place_id, "review_id": row["review_id"],
                "author": row["author"], "rating": row["rating"], "date": row["review_date"],
                "attribution": None,
            }, limit)
            if len(out) >= limit:
                return out
    return out


def _walk_raw_images(value):
    if isinstance(value, dict):
        if any(key in value for key in _RAW_IMAGE_KEYS):
            yield value
        for key in _RAW_IMAGE_CONTAINERS:
            nested = value.get(key)
            if isinstance(nested, (dict, list)):
                yield from _walk_raw_images(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_raw_images(item)


def _place_raw_photos(conn: sqlite3.Connection, place_id: str, *, limit: int, seen: set[str]) -> list[dict]:
    row = conn.execute("SELECT raw_json, source FROM places WHERE place_id=?", (place_id,)).fetchone()
    raw = _loads_json(row["raw_json"], {}) if row else {}
    out: list[dict] = []
    for entry in _walk_raw_images(raw):
        url, thumb = _image_entry(entry, require_image_url=True)
        _append(out, seen, {
            "url": url, "thumb_url": thumb, "source": row["source"] if row else "place",
            "kind": "place", "place_id": place_id, "review_id": None,
            "author": None, "rating": None, "date": None, "attribution": None,
        }, limit)
        if len(out) >= limit:
            return out
    return out


def resolve_place_photos(conn: sqlite3.Connection, place_id: str, *, list_mode: bool = False):
    """Return bounded source-photo metadata, or one thumbnail in list mode."""
    limit = PHOTO_LIST_LIMIT if list_mode else PHOTO_DETAIL_LIMIT
    review_limit = min(PHOTO_REVIEW_IMAGE_LIMIT, limit)
    reviews = _review_photos(conn, place_id, limit=review_limit)
    seen = {item["url"] for item in reviews}
    photos = reviews + _place_raw_photos(conn, place_id, limit=limit - len(reviews), seen=seen)
    if list_mode:
        return photos[0] if photos else None
    return photos[:limit]
