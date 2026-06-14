"""Local cache: SQLite for places, reviews, reports, searches + embedded vectors.

Vectors are stored as float32 BLOBs and searched with numpy brute-force cosine —
at <100k reviews this is milliseconds and avoids native sqlite extensions.
All rows keep the raw source payload in *_json columns so nothing is lost.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config

ACTIVITY_RISK_MIN_TOTAL_REVIEWS = 80
ACTIVITY_RISK_STALE_DAYS = 180
ACTIVITY_RISK_HIGH_DAYS = 365

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    place_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT,
    address       TEXT,
    lat           REAL,
    lng           REAL,
    rating        REAL,
    review_count  INTEGER,
    phone         TEXT,
    website       TEXT,
    hours_json    TEXT,
    price_level   TEXT,
    maps_url      TEXT,
    source        TEXT,
    first_seen    REAL NOT NULL,
    last_refreshed REAL NOT NULL,
    raw_json      TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id     TEXT PRIMARY KEY,
    place_id      TEXT NOT NULL REFERENCES places(place_id),
    author        TEXT,
    rating        REAL,
    text          TEXT,
    lang          TEXT,
    review_date   TEXT,
    owner_response TEXT,
    images_json   TEXT,
    source        TEXT,
    scraped_at    REAL NOT NULL,
    raw_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_place ON reviews(place_id);
CREATE TABLE IF NOT EXISTS review_vectors (
    review_id     TEXT PRIMARY KEY REFERENCES reviews(review_id),
    dims          INTEGER NOT NULL,
    vector        BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS review_translations (
    review_id     TEXT NOT NULL REFERENCES reviews(review_id),
    target_lang   TEXT NOT NULL,
    source_hash   TEXT NOT NULL,
    source_lang   TEXT,
    translation   TEXT NOT NULL,
    model         TEXT,
    provider      TEXT,
    created_at    REAL NOT NULL,
    PRIMARY KEY (review_id, target_lang)
);
CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id      TEXT NOT NULL REFERENCES places(place_id),
    profile       TEXT NOT NULL,
    model         TEXT,
    report_json   TEXT NOT NULL,
    report_md     TEXT NOT NULL,
    review_count  INTEGER,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    query         TEXT NOT NULL,
    location      TEXT,
    place_ids_json TEXT NOT NULL,
    source        TEXT,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS qa (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question      TEXT NOT NULL,
    place_id      TEXT,
    answer        TEXT NOT NULL,
    model         TEXT,
    question_vec  BLOB,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_place ON qa(place_id);
"""


@dataclass
class Place:
    place_id: str
    name: str
    category: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    review_count: int | None = None
    phone: str | None = None
    website: str | None = None
    hours: dict | list | None = None
    price_level: str | None = None
    maps_url: str | None = None
    source: str = "gosom"
    raw: dict = field(default_factory=dict)


@dataclass
class Review:
    review_id: str
    place_id: str
    author: str | None = None
    rating: float | None = None
    text: str | None = None
    lang: str | None = None
    review_date: str | None = None
    owner_response: str | None = None
    images: list = field(default_factory=list)
    source: str = "scraper-pro"
    raw: dict = field(default_factory=dict)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for DBs created by earlier versions."""
    for ddl in (
        "ALTER TABLE searches ADD COLUMN plan_json TEXT",
        "ALTER TABLE searches ADD COLUMN verdicts_json TEXT",
        "ALTER TABLE review_translations ADD COLUMN provider TEXT",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def _text_or_none(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [_text_or_none(item) for item in value]
        return " · ".join(part for part in parts if part) or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def upsert_place(conn: sqlite3.Connection, place: Place) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO places (place_id, name, category, address, lat, lng, rating,
            review_count, phone, website, hours_json, price_level, maps_url,
            source, first_seen, last_refreshed, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(place_id) DO UPDATE SET
            name=excluded.name, category=excluded.category, address=excluded.address,
            lat=excluded.lat, lng=excluded.lng, rating=excluded.rating,
            review_count=excluded.review_count, phone=excluded.phone,
            website=excluded.website, hours_json=excluded.hours_json,
            price_level=excluded.price_level, maps_url=excluded.maps_url,
            source=excluded.source, last_refreshed=excluded.last_refreshed,
            raw_json=excluded.raw_json
        """,
        (
            place.place_id, place.name, _text_or_none(place.category),
            _text_or_none(place.address), place.lat,
            place.lng, place.rating, place.review_count,
            _text_or_none(place.phone), _text_or_none(place.website),
            json.dumps(place.hours, ensure_ascii=False) if place.hours else None,
            _text_or_none(place.price_level), _text_or_none(place.maps_url),
            _text_or_none(place.source), now, now,
            json.dumps(place.raw, ensure_ascii=False, default=str),
        ),
    )
    conn.commit()


def upsert_reviews(conn: sqlite3.Connection, reviews: list[Review]) -> int:
    """Insert reviews; existing review_ids are refreshed. Returns count of NEW rows."""
    now = time.time()
    new_count = 0
    for r in reviews:
        existed = conn.execute(
            "SELECT 1 FROM reviews WHERE review_id=?", (r.review_id,)
        ).fetchone()
        if not existed:
            new_count += 1
        conn.execute(
            """
            INSERT INTO reviews (review_id, place_id, author, rating, text, lang,
                review_date, owner_response, images_json, source, scraped_at, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(review_id) DO UPDATE SET
                text=excluded.text, rating=excluded.rating,
                owner_response=excluded.owner_response, images_json=excluded.images_json,
                scraped_at=excluded.scraped_at, raw_json=excluded.raw_json
            """,
            (
                r.review_id, r.place_id, r.author, r.rating, r.text, r.lang,
                r.review_date, r.owner_response,
                json.dumps(r.images, ensure_ascii=False) if r.images else None,
                r.source, now, json.dumps(r.raw, ensure_ascii=False, default=str),
            ),
        )
    conn.commit()
    return new_count


def place_is_fresh(conn: sqlite3.Connection, place_id: str) -> bool:
    row = conn.execute(
        "SELECT last_refreshed FROM places WHERE place_id=?", (place_id,)
    ).fetchone()
    if not row:
        return False
    return (time.time() - row["last_refreshed"]) < config.PLACE_TTL_DAYS * 86400


def get_place(conn: sqlite3.Connection, place_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM places WHERE place_id=?", (place_id,)).fetchone()


def get_reviews(conn: sqlite3.Connection, place_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reviews WHERE place_id=? ORDER BY review_date DESC", (place_id,)
    ).fetchall()


def get_review(conn: sqlite3.Connection, review_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()


def review_source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def cached_review_translation(
    conn: sqlite3.Connection, review_id: str, target_lang: str, source_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM review_translations
           WHERE review_id=? AND target_lang=? AND source_hash=?""",
        (review_id, target_lang, source_hash),
    ).fetchone()


def save_review_translation(
    conn: sqlite3.Connection, review_id: str, target_lang: str, source_hash: str,
    source_lang: str | None, translation: str, model: str, provider: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO review_translations
           (review_id, target_lang, source_hash, source_lang, translation, model, provider, created_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(review_id, target_lang) DO UPDATE SET
             source_hash=excluded.source_hash, source_lang=excluded.source_lang,
             translation=excluded.translation, model=excluded.model, provider=excluded.provider,
             created_at=excluded.created_at""",
        (review_id, target_lang, source_hash, source_lang, translation, model, provider, time.time()),
    )
    conn.commit()


def reviews_missing_vectors(conn: sqlite3.Connection, limit: int = 2000) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.review_id, r.place_id, r.text, r.rating FROM reviews r
        LEFT JOIN review_vectors v ON v.review_id = r.review_id
        WHERE v.review_id IS NULL AND r.text IS NOT NULL AND length(r.text) > 10
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def store_vectors(conn: sqlite3.Connection, pairs: list[tuple[str, np.ndarray]]) -> None:
    for review_id, vec in pairs:
        arr = np.asarray(vec, dtype=np.float32)
        conn.execute(
            "INSERT OR REPLACE INTO review_vectors (review_id, dims, vector) VALUES (?,?,?)",
            (review_id, arr.shape[0], arr.tobytes()),
        )
    conn.commit()


def vector_search(
    conn: sqlite3.Connection, query_vec: np.ndarray, top_k: int = 20,
    place_id: str | None = None,
) -> list[dict]:
    """Brute-force cosine search over stored review vectors (vectors pre-normalized)."""
    where = "WHERE r.place_id=?" if place_id else ""
    params = (place_id,) if place_id else ()
    rows = conn.execute(
        f"""
        SELECT v.review_id, v.vector, r.place_id, r.text, r.rating, r.review_date,
               p.name AS place_name
        FROM review_vectors v
        JOIN reviews r ON r.review_id = v.review_id
        JOIN places p ON p.place_id = r.place_id
        {where}
        """,
        params,
    ).fetchall()
    if not rows:
        return []
    matrix = np.stack([np.frombuffer(row["vector"], dtype=np.float32) for row in rows])
    q = np.asarray(query_vec, dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    scores = matrix @ q
    order = np.argsort(-scores)[:top_k]
    return [
        {
            "review_id": rows[i]["review_id"],
            "place_id": rows[i]["place_id"],
            "place_name": rows[i]["place_name"],
            "text": rows[i]["text"],
            "rating": rows[i]["rating"],
            "review_date": rows[i]["review_date"],
            "score": float(scores[i]),
        }
        for i in order
    ]


def save_report(
    conn: sqlite3.Connection, place_id: str, profile: str, model: str,
    report_json: dict, report_md: str, review_count: int,
) -> None:
    conn.execute(
        """INSERT INTO reports (place_id, profile, model, report_json, report_md,
           review_count, created_at) VALUES (?,?,?,?,?,?,?)""",
        (place_id, profile, model, json.dumps(report_json, ensure_ascii=False),
         report_md, review_count, time.time()),
    )
    conn.commit()


def save_search(
    conn: sqlite3.Connection, query: str, location: str | None,
    place_ids: list[str], source: str, plan: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO searches (query, location, place_ids_json, source, created_at, "
        "plan_json) VALUES (?,?,?,?,?,?)",
        (query, location, json.dumps(place_ids), source, time.time(),
         json.dumps(plan, ensure_ascii=False) if plan else None),
    )
    conn.commit()


def latest_report(conn: sqlite3.Connection, place_id: str,
                  profile: str | None = None) -> sqlite3.Row | None:
    """Most recent report for a place (optionally for one profile)."""
    where = "AND profile=?" if profile else ""
    params = (place_id, profile) if profile else (place_id,)
    return conn.execute(
        f"SELECT * FROM reports WHERE place_id=? {where} "
        "ORDER BY created_at DESC LIMIT 1", params,
    ).fetchone()


def newest_review_scrape(conn: sqlite3.Connection, place_id: str | None = None) -> float | None:
    """Latest review scrape timestamp — for one place, or the whole cache (None)."""
    where = "WHERE place_id=?" if place_id else ""
    params = (place_id,) if place_id else ()
    row = conn.execute(
        f"SELECT MAX(scraped_at) AS ts FROM reviews {where}", params
    ).fetchone()
    return row["ts"] if row and row["ts"] else None


def _review_date_ts(value, now_ts: float | None = None) -> float | None:
    """Best-effort timestamp for provider review dates, including ISO and relative text."""
    if value is None or value == "":
        return None
    now_ts = now_ts or time.time()
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            numeric = None
        if numeric is None:
            lower = text.casefold()
            if lower in {"today", "just now", "now"}:
                return now_ts
            if lower == "yesterday":
                return now_ts - 86400
            match = re.search(
                r"\b(a|an|one|\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago\b",
                lower,
            )
            if match:
                amount = 1 if match.group(1) in {"a", "an", "one"} else int(match.group(1))
                unit_seconds = {
                    "second": 1,
                    "minute": 60,
                    "hour": 3600,
                    "day": 86400,
                    "week": 7 * 86400,
                    "month": 30 * 86400,
                    "year": 365 * 86400,
                }[match.group(2)]
                return now_ts - amount * unit_seconds
            match = re.search(r"(\d+)\s*(天|日|周|星期|个月|月|年)前", text)
            if match:
                amount = int(match.group(1))
                unit_seconds = {
                    "天": 86400,
                    "日": 86400,
                    "周": 7 * 86400,
                    "星期": 7 * 86400,
                    "个月": 30 * 86400,
                    "月": 30 * 86400,
                    "年": 365 * 86400,
                }[match.group(2)]
                return now_ts - amount * unit_seconds
            normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
            for candidate in (
                lambda s: datetime.fromisoformat(s),
                lambda s: datetime.strptime(s, "%Y-%m-%d"),
                lambda s: datetime.strptime(s, "%Y/%m/%d"),
            ):
                try:
                    dt = candidate(normalized)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    continue
            return None
    if numeric > 10_000_000_000:
        numeric /= 1000
    if numeric > 946684800:  # avoid interpreting bare years/counts as epochs
        return numeric
    return None


def activity_risk(
    conn: sqlite3.Connection,
    place_id: str,
    now_ts: float | None = None,
    min_total_reviews: int = ACTIVITY_RISK_MIN_TOTAL_REVIEWS,
    stale_days: int = ACTIVITY_RISK_STALE_DAYS,
    high_days: int = ACTIVITY_RISK_HIGH_DAYS,
) -> dict | None:
    """Flag popular places whose latest known review is stale enough to verify live status."""
    place = get_place(conn, place_id)
    if not place:
        return None
    cached_reviews = conn.execute(
        "SELECT COUNT(*) AS n FROM reviews WHERE place_id=?", (place_id,)
    ).fetchone()["n"]
    total_reviews = max(int(place["review_count"] or 0), int(cached_reviews or 0))
    if total_reviews < min_total_reviews:
        return None

    now_ts = now_ts or time.time()
    rows = conn.execute(
        "SELECT review_date FROM reviews WHERE place_id=? AND review_date IS NOT NULL",
        (place_id,),
    ).fetchall()
    parsed_dates = [
        ts for ts in (_review_date_ts(row["review_date"], now_ts) for row in rows)
        if ts is not None
    ]
    if not parsed_dates:
        return None
    newest_ts = max(parsed_dates)
    days_since = max(0, int((now_ts - newest_ts) // 86400))
    if days_since < stale_days:
        return None

    newest_date = datetime.fromtimestamp(newest_ts, tz=timezone.utc).date().isoformat()
    severity = "high" if days_since >= high_days else "medium"
    label = "可能已停业/低活跃" if severity == "high" else "近期活跃度偏低"
    return {
        "kind": "stale_review_activity",
        "severity": severity,
        "label": label,
        "reason": (
            f"历史累计约 {total_reviews} 条评价，但最新已知评价是 {newest_date}，"
            f"距今约 {days_since} 天；出发前应核实仍在营业。"
        ),
        "total_reviews": total_reviews,
        "cached_reviews": int(cached_reviews or 0),
        "newest_review_date": newest_date,
        "days_since_newest_review": days_since,
        "stale_days": stale_days,
    }


def norm_name(s: str) -> str:
    """Diacritic-stripped, lowercased, alphanumeric+CJK only — 'Hội An' == 'hoi an'."""
    decomposed = unicodedata.normalize("NFD", s or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9一-鿿]+", "", stripped.lower())


def find_places_by_name(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Diacritic-insensitive name match — single-shop mode checks here first.
    Whole-string containment, else every latin token of the query must appear
    (handles 'Gio Guitar Hoi An' vs 'Gió Guitar Cơ Sở Hội An')."""
    wanted = norm_name(name)
    if not wanted:
        return []
    tokens = [norm_name(t) for t in re.split(r"\s+", name) if len(norm_name(t)) >= 2]
    matches = []
    for row in conn.execute("SELECT * FROM places ORDER BY last_refreshed DESC"):
        candidate = norm_name(row["name"])
        if not candidate:
            continue
        if (wanted in candidate or candidate in wanted
                or (tokens and all(t in candidate for t in tokens))):
            matches.append(row)
    return matches


def recent_search(
    conn: sqlite3.Connection, query: str, location: str | None, max_age_days: float = 7,
) -> dict | None:
    """Return {'place_ids': [...], 'verdicts': [...]|None} for an equivalent recent
    search, else None. Cached verdicts let repeat scouts skip the AI filter call."""
    row = conn.execute(
        """SELECT place_ids_json, verdicts_json FROM searches
           WHERE lower(query)=lower(?) AND ifnull(lower(location),'')=ifnull(lower(?),'')
             AND created_at > ?
           ORDER BY created_at DESC LIMIT 1""",
        (query, location, time.time() - max_age_days * 86400),
    ).fetchone()
    if not row:
        return None
    return {
        "place_ids": json.loads(row["place_ids_json"]),
        "verdicts": json.loads(row["verdicts_json"]) if row["verdicts_json"] else None,
    }


def update_search_verdicts(
    conn: sqlite3.Connection, query: str, location: str | None, verdicts: list[dict],
) -> None:
    """Attach AI relevance verdicts to the most recent matching search row."""
    conn.execute(
        """UPDATE searches SET verdicts_json=? WHERE id = (
             SELECT id FROM searches
             WHERE lower(query)=lower(?) AND ifnull(lower(location),'')=ifnull(lower(?),'')
             ORDER BY created_at DESC LIMIT 1)""",
        (json.dumps(verdicts, ensure_ascii=False), query, location),
    )
    conn.commit()


def delete_place(conn: sqlite3.Connection, place_id: str) -> int:
    """Remove a place and ALL its derived data (reviews, vectors, reports, QA)."""
    cur = conn.execute("SELECT 1 FROM places WHERE place_id=?", (place_id,)).fetchone()
    if not cur:
        return 0
    conn.execute(
        "DELETE FROM review_translations WHERE review_id IN "
        "(SELECT review_id FROM reviews WHERE place_id=?)", (place_id,))
    conn.execute(
        "DELETE FROM review_vectors WHERE review_id IN "
        "(SELECT review_id FROM reviews WHERE place_id=?)", (place_id,))
    conn.execute("DELETE FROM reviews WHERE place_id=?", (place_id,))
    conn.execute("DELETE FROM reports WHERE place_id=?", (place_id,))
    conn.execute("DELETE FROM qa WHERE place_id=?", (place_id,))
    conn.execute("DELETE FROM places WHERE place_id=?", (place_id,))
    conn.commit()
    return 1


# -- QA cache: past reasoned answers double as a semantic answer source ----------

def save_qa(conn: sqlite3.Connection, question: str, place_id: str | None,
            answer: str, model: str, question_vec: np.ndarray | None) -> None:
    blob = (np.asarray(question_vec, dtype=np.float32).tobytes()
            if question_vec is not None else None)
    conn.execute(
        "INSERT INTO qa (question, place_id, answer, model, question_vec, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (question, place_id, answer, model, blob, time.time()),
    )
    conn.commit()


def find_cached_answer(
    conn: sqlite3.Connection, question: str, question_vec: np.ndarray,
    place_id: str | None, min_score: float = 0.90,
) -> dict | None:
    """Semantic QA-cache lookup, scope-exact (one place vs global). An answer is
    only valid while NO new reviews arrived in its scope after it was written."""
    where = "WHERE place_id=?" if place_id else "WHERE place_id IS NULL"
    params = (place_id,) if place_id else ()
    rows = conn.execute(
        f"SELECT * FROM qa {where} ORDER BY created_at DESC LIMIT 200", params
    ).fetchall()
    valid_after = newest_review_scrape(conn, place_id) or 0
    fresh = [r for r in rows if r["created_at"] >= valid_after and r["question_vec"]]
    if not fresh:
        return None
    wanted = question.strip().casefold()
    q = np.asarray(question_vec, dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    best, best_score = None, min_score
    for row in fresh:
        if row["question"].strip().casefold() == wanted:
            best, best_score = row, 1.0
            break
        vec = np.frombuffer(row["question_vec"], dtype=np.float32)
        score = float(vec @ q / (np.linalg.norm(vec) or 1.0))
        if score >= best_score:
            best, best_score = row, score
    if not best:
        return None
    return {"question": best["question"], "answer": best["answer"],
            "model": best["model"], "created_at": best["created_at"],
            "score": best_score}


def recent_qa(conn: sqlite3.Connection, place_id: str | None = None,
              limit: int = 8) -> list[sqlite3.Row]:
    """Recent Q&A for the UI history — scope-exact like find_cached_answer."""
    where = "WHERE place_id=?" if place_id else "WHERE place_id IS NULL"
    params: tuple = (place_id, limit) if place_id else (limit,)
    return conn.execute(
        f"SELECT id, question, answer, place_id, created_at FROM qa {where} "
        "ORDER BY created_at DESC LIMIT ?", params,
    ).fetchall()


def recent_qa_all(conn: sqlite3.Connection, limit: int = 12) -> list[sqlite3.Row]:
    """Recent Q&A across scopes for display only; cache lookup remains exact-scope."""
    return conn.execute(
        """SELECT qa.id, qa.question, qa.answer, qa.place_id, qa.created_at,
                  p.name AS place_name
           FROM qa LEFT JOIN places p ON p.place_id = qa.place_id
           ORDER BY qa.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
