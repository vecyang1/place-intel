"""Private Google saved-place import and inventory contracts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import stat
import time
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SAVED_STATES = (
    "pending",
    "resolved",
    "renamed",
    "temporarily_closed",
    "permanently_closed",
    "coordinate_only",
    "ambiguous",
    "not_a_place",
    "failed",
)
SOURCE_LABEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedRow:
    source_product: str
    collection_name: str
    collection_description: str | None
    title: str | None
    url: str | None
    note: str | None
    tags: tuple[str, ...]
    comment: str | None
    source_member: str
    source_file_sha256: str
    row_number: int
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    saved_at: str | None = None


@dataclass(frozen=True)
class ImportLimits:
    max_files: int = 5_000
    max_rows: int = 250_000
    max_file_bytes: int = 25 * 1024 * 1024
    max_total_bytes: int = 1_024 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "ImportLimits":
        return cls(
            max_files=_positive_env_int("PLACEINTEL_SAVED_IMPORT_MAX_FILES", 5_000),
            max_rows=_positive_env_int("PLACEINTEL_SAVED_IMPORT_MAX_ROWS", 250_000),
            max_file_bytes=(
                _positive_env_int("PLACEINTEL_SAVED_IMPORT_MAX_FILE_MB", 25)
                * 1024
                * 1024
            ),
            max_total_bytes=(
                _positive_env_int("PLACEINTEL_SAVED_IMPORT_MAX_TOTAL_MB", 1_024)
                * 1024
                * 1024
            ),
        )


@dataclass(frozen=True)
class ImportResult:
    run_id: str
    source_digest: str
    source_label: str | None
    file_count: int
    row_count: int
    skipped_rows: int
    adopted_collections: int
    created_collections: int
    created_items: int
    created_memberships: int
    updated_collections: int
    updated_items: int
    updated_memberships: int


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS saved_import_runs (
            run_id TEXT PRIMARY KEY,
            source_digest TEXT NOT NULL,
            source_label TEXT,
            status TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            row_count INTEGER NOT NULL DEFAULT 0,
            skipped_rows INTEGER NOT NULL DEFAULT 0,
            adopted_collections INTEGER NOT NULL DEFAULT 0,
            created_collections INTEGER NOT NULL DEFAULT 0,
            created_items INTEGER NOT NULL DEFAULT 0,
            created_memberships INTEGER NOT NULL DEFAULT 0,
            updated_collections INTEGER NOT NULL DEFAULT 0,
            updated_items INTEGER NOT NULL DEFAULT 0,
            updated_memberships INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            started_at REAL NOT NULL,
            completed_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_saved_import_runs_digest
            ON saved_import_runs(source_digest, started_at);

        CREATE TABLE IF NOT EXISTS saved_collections (
            collection_id TEXT PRIMARY KEY,
            source_product TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            description TEXT,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            UNIQUE(source_product, normalized_name)
        );

        CREATE TABLE IF NOT EXISTS saved_items (
            saved_item_id TEXT PRIMARY KEY,
            source_title TEXT,
            source_url TEXT,
            source_address TEXT,
            source_lat REAL,
            source_lng REAL,
            state TEXT NOT NULL DEFAULT 'pending',
            resolved_place_id TEXT,
            resolved_at REAL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_saved_items_state
            ON saved_items(state, last_seen_at);

        CREATE TABLE IF NOT EXISTS saved_memberships (
            membership_id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL REFERENCES saved_collections(collection_id),
            saved_item_id TEXT NOT NULL REFERENCES saved_items(saved_item_id),
            note TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            comment TEXT,
            saved_at TEXT,
            source_member TEXT NOT NULL,
            source_file_sha256 TEXT NOT NULL,
            source_row_number INTEGER NOT NULL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            UNIQUE(collection_id, saved_item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_memberships_item
            ON saved_memberships(saved_item_id, collection_id);
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(saved_import_runs)")
    }
    if "skipped_rows" not in columns:
        conn.execute(
            "ALTER TABLE saved_import_runs "
            "ADD COLUMN skipped_rows INTEGER NOT NULL DEFAULT 0"
        )
    if "source_label" not in columns:
        conn.execute("ALTER TABLE saved_import_runs ADD COLUMN source_label TEXT")
    if "adopted_collections" not in columns:
        conn.execute(
            "ALTER TABLE saved_import_runs "
            "ADD COLUMN adopted_collections INTEGER NOT NULL DEFAULT 0"
        )


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("saved_import_invalid_limit_config") from exc
    if value < 1:
        raise ValueError("saved_import_invalid_limit_config")
    return value


def iter_takeout_rows(path: Path, limits: ImportLimits | None = None) -> Iterator[SavedRow]:
    """Yield supported Takeout rows without accumulating the whole corpus in memory."""
    limits = limits or ImportLimits()
    path = Path(path)
    if path.is_symlink():
        raise ValueError("saved_import_unsafe_source_member")
    if path.is_file() and path.suffix.casefold() == ".csv":
        if path.stat().st_size > limits.max_file_bytes:
            raise ValueError("saved_import_file_too_large")
        digest = _sha256_path(path)
        with path.open("rb") as stream:
            yield from _bounded_rows(
                _iter_saved_csv(stream, path.name, digest),
                limits,
            )
        return
    if path.is_file() and path.suffix.casefold() == ".zip":
        yield from _bounded_rows(_iter_takeout_zip(path, limits), limits)
        return
    if path.is_dir():
        files = _bounded_directory_files(path, limits)
        yield from _bounded_rows(_iter_directory_rows(path, files, limits), limits)


def _bounded_rows(rows: Iterable[SavedRow], limits: ImportLimits) -> Iterator[SavedRow]:
    count = 0
    for row in rows:
        count += 1
        if count > limits.max_rows:
            raise ValueError("saved_import_too_many_rows")
        yield row


def _bounded_directory_files(path: Path, limits: ImportLimits) -> list[Path]:
    files: list[Path] = []
    total_bytes = 0
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("saved_import_unsafe_source_member")
        if not candidate.is_file():
            continue
        files.append(candidate)
        if len(files) > limits.max_files:
            raise ValueError("saved_import_too_many_files")
        total_bytes += candidate.stat().st_size
        if total_bytes > limits.max_total_bytes:
            raise ValueError("saved_import_total_too_large")
    return sorted(files)


def _iter_directory_rows(
    root: Path,
    files: Iterable[Path],
    limits: ImportLimits,
) -> Iterator[SavedRow]:
    for candidate in files:
        member = candidate.relative_to(root).as_posix()
        member_parts = {part.casefold() for part in PurePosixPath(member).parts}
        suffix = candidate.suffix.casefold()
        if suffix == ".csv" and (
            root.name.casefold() == "saved" or "saved" in member_parts
        ):
            if candidate.stat().st_size > limits.max_file_bytes:
                raise ValueError("saved_import_file_too_large")
            digest = _sha256_path(candidate)
            with candidate.open("rb") as stream:
                yield from _iter_saved_csv(stream, member, digest)
        elif suffix in {".json", ".geojson"}:
            with candidate.open("rb") as stream:
                data = _read_limited(stream, limits.max_file_bytes)
            if _is_maps_saved_geojson(PurePosixPath(member)):
                yield from _parse_starred_geojson(data, member)
            elif _is_localized_saved_geojson(data):
                yield from _parse_starred_geojson(data, member, collection_name="Saved Places")


def _iter_takeout_zip(path: Path, limits: ImportLimits) -> Iterator[SavedRow]:
    try:
        with zipfile.ZipFile(path) as bundle:
            files = []
            total_bytes = 0
            for info in bundle.infolist():
                member = PurePosixPath(info.filename)
                unix_mode = info.external_attr >> 16
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or "\x00" in info.filename
                    or stat.S_ISLNK(unix_mode)
                ):
                    raise ValueError("saved_import_unsafe_archive_member")
                if info.is_dir():
                    continue
                files.append(info)
                if len(files) > limits.max_files:
                    raise ValueError("saved_import_too_many_files")
                total_bytes += info.file_size
                if total_bytes > limits.max_total_bytes:
                    raise ValueError("saved_import_total_too_large")
                if info.file_size > limits.max_file_bytes:
                    raise ValueError("saved_import_file_too_large")
            for info in files:
                member = PurePosixPath(info.filename)
                member_name = member.as_posix()
                suffix = member.suffix.casefold()
                if suffix == ".csv" and "saved" in {part.casefold() for part in member.parts}:
                    with bundle.open(info) as stream:
                        digest = _sha256_stream(stream)
                    with bundle.open(info) as stream:
                        yield from _iter_saved_csv(stream, member_name, digest)
                elif suffix in {".json", ".geojson"}:
                    with bundle.open(info) as stream:
                        data = _read_limited(stream, limits.max_file_bytes)
                    if _is_maps_saved_geojson(member):
                        yield from _parse_starred_geojson(data, member_name)
                    elif _is_localized_saved_geojson(data):
                        yield from _parse_starred_geojson(
                            data,
                            member_name,
                            collection_name="Saved Places",
                        )
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as exc:
        raise ValueError("saved_import_invalid_archive") from exc


def _is_maps_saved_geojson(member: PurePosixPath) -> bool:
    return (
        member.suffix.casefold() in {".json", ".geojson"}
        and member.stem.casefold() in {"starred places", "saved places"}
        and any(part.casefold() == "maps (your places)" for part in member.parts)
    )


def _is_localized_saved_geojson(data: bytes) -> bool:
    """Recognize only the current localized saved-place GeoJSON shape.

    Localized Takeout filenames are not stable. We accept the documented point
    feature shape only when every feature has a Maps URL and comment field, and
    reject the neighboring review export schema explicitly.
    """
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    features = payload.get("features")
    if payload.get("type") != "FeatureCollection" or not isinstance(features, list) or not features:
        return False
    saw_comment = False
    for feature in features:
        if not isinstance(feature, dict):
            return False
        properties = feature.get("properties") or feature.get("property") or {}
        geometry = feature.get("geometry") or {}
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            return False
        property_names = {str(key).casefold() for key in properties}
        if {"review_text_published", "five_star_rating_published"} & property_names:
            return False
        if geometry.get("type") != "Point":
            return False
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            return False
        if not _geojson_has_text(properties.get("google_maps_url")):
            return False
        saw_comment = saw_comment or "comment" in property_names
    return saw_comment


def _iter_saved_csv(
    stream: BinaryIO,
    source_member: str,
    digest: str,
) -> Iterator[SavedRow]:
    text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    try:
        reader = csv.reader(text_stream)
        first_row: list[str] | None = None
        previous_row: list[str] | None = None
        header_index = None
        headers: list[str] = []
        for index, row in enumerate(reader):
            if first_row is None:
                first_row = row
            cells = {cell.strip().casefold() for cell in row}
            if cells & {"title", "item_content_url"}:
                header_index = index
                headers = [cell.strip().casefold() for cell in row]
                break
            previous_row = row
        if header_index is None:
            raise ValueError("saved_import_missing_header")
        description = None
        if (
            header_index >= 2
            and previous_row is not None
            and not any(cell.strip() for cell in previous_row)
        ):
            description = ",".join(first_row or []).strip() or None
        for index, values in enumerate(reader, start=header_index + 2):
            if not any(value.strip() for value in values):
                continue
            fields = dict(zip(headers, values))
            tag_text = fields.get("tags", "")
            yield SavedRow(
                source_product="saved",
                collection_name=Path(source_member).stem,
                collection_description=description,
                title=fields.get("title", "").strip() or None,
                url=fields.get("item_content_url", "").strip() or None,
                note=fields.get("note", "").strip() or None,
                tags=tuple(tag.strip() for tag in tag_text.split(";") if tag.strip()),
                comment=fields.get("comment", "").strip() or None,
                source_member=source_member,
                source_file_sha256=digest,
                row_number=index,
            )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("saved_import_invalid_csv") from exc
    finally:
        try:
            text_stream.detach()
        except ValueError:
            pass


def _parse_starred_geojson(
    data: bytes,
    source_member: str,
    *,
    collection_name: str | None = None,
) -> Iterator[SavedRow]:
    digest = hashlib.sha256(data).hexdigest()
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("saved_import_invalid_geojson") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("saved_import_invalid_geojson")
    features = payload["features"]
    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict):
            raise ValueError("saved_import_invalid_geojson")
        properties = feature.get("properties") or feature.get("property") or {}
        if not isinstance(properties, dict):
            raise ValueError("saved_import_invalid_geojson")
        location = properties.get("location") or feature.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        if not isinstance(location, dict):
            raise ValueError("saved_import_invalid_geojson")
        geometry = feature.get("geometry") or {}
        if not isinstance(geometry, dict):
            raise ValueError("saved_import_invalid_geojson")
        coordinates = geometry.get("coordinates") or []
        if not isinstance(coordinates, (list, tuple)):
            raise ValueError("saved_import_invalid_geojson")
        if coordinates and len(coordinates) < 2:
            raise ValueError("saved_import_invalid_geojson")
        lng = _geojson_coordinate(coordinates[0]) if len(coordinates) >= 2 else None
        lat = _geojson_coordinate(coordinates[1]) if len(coordinates) >= 2 else None
        if lat == 0.0 and lng == 0.0:
            lat = None
            lng = None
        yield SavedRow(
            source_product="local_actions",
            collection_name=collection_name or Path(source_member).stem,
            collection_description=None,
            title=_geojson_text(
                location.get("name") or properties.get("name") or feature.get("name")
            ),
            url=_geojson_text(
                properties.get("google_maps_url") or feature.get("google_maps_url")
            ),
            note=None,
            tags=(),
            comment=_geojson_text(
                properties.get("comment")
                or properties.get("Comment")
                or feature.get("comment")
            ),
            source_member=source_member,
            source_file_sha256=digest,
            row_number=index,
            address=_geojson_text(location.get("address") or properties.get("address")),
            lat=lat,
            lng=lng,
            saved_at=_geojson_text(properties.get("date") or feature.get("date")),
        )


def _geojson_coordinate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("saved_import_invalid_geojson")
    return float(value)


def _geojson_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("saved_import_invalid_geojson")
    return value or None


def _geojson_has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("saved_import_file_too_large")
    return data


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def import_takeout(
    conn: sqlite3.Connection,
    path: Path,
    *,
    limits: ImportLimits | None = None,
    emit_events: bool = False,
    source_label: str | None = None,
    adopt_unlabeled: bool = False,
) -> ImportResult:
    limits = limits or ImportLimits()
    path = Path(path)
    source_label = normalize_source_label(source_label) if source_label else None
    if adopt_unlabeled and not source_label:
        raise ValueError("saved_import_adoption_requires_source_label")
    ensure_schema(conn)
    conn.commit()
    run_id = uuid.uuid4().hex
    started_at = time.time()
    unavailable_digest = _sha256_text("saved-import-source-unavailable")
    try:
        source_digest = _source_digest(path, limits)
    except BaseException as exc:
        _insert_import_run(conn, run_id, unavailable_digest, source_label, started_at)
        error_code = _saved_import_error_code(exc)
        _mark_import_failed(conn, run_id, error_code)
        if emit_events:
            log.error("saved_import_failed run_id=%s error_code=%s", run_id, error_code)
        raise

    _insert_import_run(conn, run_id, source_digest, source_label, started_at)
    if emit_events:
        log.info("saved_import_started run_id=%s source_digest=%s", run_id, source_digest[:12])

    source_parts: set[tuple[str, str]] = set()
    row_count = 0
    skipped_rows = 0
    adopted_collections: set[str] = set()
    created_collections: set[str] = set()
    created_items: set[str] = set()
    created_memberships: set[str] = set()
    updated_collections: set[str] = set()
    updated_items: set[str] = set()
    updated_memberships: set[str] = set()

    try:
        with conn:
            for row in iter_takeout_rows(path, limits):
                row_count += 1
                source_parts.add((row.source_member, row.source_file_sha256))
                if _is_skippable_placeholder(row):
                    skipped_rows += 1
                    continue
                item_id = saved_item_id(row)
                normalized_name = _normalize_text(row.collection_name)
                source_product = scoped_source_product(row.source_product, source_label)
                collection_id = collection_identity(source_product, normalized_name)
                collection_exists = conn.execute(
                    "SELECT 1 FROM saved_collections WHERE collection_id=?",
                    (collection_id,),
                ).fetchone()
                if not collection_exists and adopt_unlabeled and _adopt_unlabeled_collection(
                    conn,
                    row,
                    source_product=source_product,
                    normalized_name=normalized_name,
                    started_at=started_at,
                ):
                    adopted_collections.add(collection_id)
                    collection_exists = True
                if collection_exists:
                    if collection_id not in created_collections:
                        updated_collections.add(collection_id)
                else:
                    created_collections.add(collection_id)
                conn.execute(
                    """
                    INSERT INTO saved_collections (
                        collection_id, source_product, normalized_name, original_name,
                        description, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collection_id) DO UPDATE SET
                        original_name=excluded.original_name,
                        description=COALESCE(excluded.description, saved_collections.description),
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        collection_id,
                        source_product,
                        normalized_name,
                        row.collection_name,
                        row.collection_description,
                        started_at,
                        started_at,
                    ),
                )

                if conn.execute(
                    "SELECT 1 FROM saved_items WHERE saved_item_id=?",
                    (item_id,),
                ).fetchone():
                    if item_id not in created_items:
                        updated_items.add(item_id)
                else:
                    created_items.add(item_id)
                conn.execute(
                    """
                    INSERT INTO saved_items (
                        saved_item_id, source_title, source_url, source_address,
                        source_lat, source_lng, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(saved_item_id) DO UPDATE SET
                        source_title=COALESCE(excluded.source_title, saved_items.source_title),
                        source_url=COALESCE(excluded.source_url, saved_items.source_url),
                        source_address=COALESCE(excluded.source_address, saved_items.source_address),
                        source_lat=COALESCE(excluded.source_lat, saved_items.source_lat),
                        source_lng=COALESCE(excluded.source_lng, saved_items.source_lng),
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        item_id,
                        row.title,
                        normalize_url(row.url) if row.url else None,
                        row.address,
                        row.lat,
                        row.lng,
                        started_at,
                        started_at,
                    ),
                )

                membership_id = _sha256_text(f"{collection_id}\0{item_id}")
                if conn.execute(
                    "SELECT 1 FROM saved_memberships WHERE membership_id=?",
                    (membership_id,),
                ).fetchone():
                    if membership_id not in created_memberships:
                        updated_memberships.add(membership_id)
                else:
                    created_memberships.add(membership_id)
                conn.execute(
                    """
                    INSERT INTO saved_memberships (
                        membership_id, collection_id, saved_item_id, note, tags_json,
                        comment, saved_at, source_member, source_file_sha256,
                        source_row_number, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(membership_id) DO UPDATE SET
                        note=excluded.note,
                        tags_json=excluded.tags_json,
                        comment=excluded.comment,
                        saved_at=COALESCE(excluded.saved_at, saved_memberships.saved_at),
                        source_member=excluded.source_member,
                        source_file_sha256=excluded.source_file_sha256,
                        source_row_number=excluded.source_row_number,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        membership_id,
                        collection_id,
                        item_id,
                        row.note,
                        json.dumps(row.tags, ensure_ascii=False),
                        row.comment,
                        row.saved_at,
                        row.source_member,
                        row.source_file_sha256,
                        row.row_number,
                        started_at,
                        started_at,
                    ),
                )

            if not row_count:
                raise ValueError("saved_import_no_supported_rows")
            conn.execute(
                """
                UPDATE saved_import_runs SET
                    status='completed', file_count=?, row_count=?, skipped_rows=?,
                    adopted_collections=?,
                    created_collections=?, created_items=?, created_memberships=?,
                    updated_collections=?, updated_items=?, updated_memberships=?,
                    completed_at=?
                WHERE run_id=?
                """,
                (
                    len(source_parts),
                    row_count,
                    skipped_rows,
                    len(adopted_collections),
                    len(created_collections),
                    len(created_items),
                    len(created_memberships),
                    len(updated_collections),
                    len(updated_items),
                    len(updated_memberships),
                    time.time(),
                    run_id,
                ),
            )
    except BaseException as exc:
        conn.rollback()
        error_code = _saved_import_error_code(exc)
        _mark_import_failed(conn, run_id, error_code)
        if emit_events:
            log.error("saved_import_failed run_id=%s error_code=%s", run_id, error_code)
        if isinstance(exc, sqlite3.Error):
            raise ValueError(error_code) from exc
        raise

    if emit_events:
        log.info(
            "saved_import_completed run_id=%s files=%d rows=%d elapsed_ms=%d",
            run_id,
            len(source_parts),
            row_count,
            int((time.time() - started_at) * 1000),
        )
    return ImportResult(
        run_id=run_id,
        source_digest=source_digest,
        source_label=source_label,
        file_count=len(source_parts),
        row_count=row_count,
        skipped_rows=skipped_rows,
        adopted_collections=len(adopted_collections),
        created_collections=len(created_collections),
        created_items=len(created_items),
        created_memberships=len(created_memberships),
        updated_collections=len(updated_collections),
        updated_items=len(updated_items),
        updated_memberships=len(updated_memberships),
    )


def _source_digest(path: Path, limits: ImportLimits) -> str:
    if path.is_symlink():
        raise ValueError("saved_import_unsafe_source_member")
    if path.is_file():
        size = path.stat().st_size
        if size > limits.max_total_bytes:
            raise ValueError("saved_import_total_too_large")
        if path.suffix.casefold() != ".zip" and size > limits.max_file_bytes:
            raise ValueError("saved_import_file_too_large")
        return _sha256_path(path)
    if path.is_dir():
        digest = hashlib.sha256()
        for candidate in _bounded_directory_files(path, limits):
            member = candidate.relative_to(path).as_posix()
            digest.update(member.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_sha256_path(candidate).encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()
    return _sha256_text("saved-import-unsupported-source")


def _insert_import_run(
    conn: sqlite3.Connection,
    run_id: str,
    source_digest: str,
    source_label: str | None,
    started_at: float,
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO saved_import_runs (
                run_id, source_digest, source_label, status, started_at
            ) VALUES (?, ?, ?, 'started', ?)
            """,
            (run_id, source_digest, source_label, started_at),
        )


def _mark_import_failed(conn: sqlite3.Connection, run_id: str, error_code: str) -> None:
    with conn:
        conn.execute(
            """
            UPDATE saved_import_runs
            SET status='failed', error_code=?, completed_at=?
            WHERE run_id=?
            """,
            (error_code, time.time(), run_id),
        )


def _saved_import_error_code(exc: BaseException) -> str:
    code = str(exc)
    if code.startswith("saved_import_"):
        return code
    if isinstance(exc, sqlite3.Error):
        return "saved_import_database_error"
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return "saved_import_interrupted"
    return "saved_import_failed"


def _normalize_text(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def normalize_source_label(value: str) -> str:
    """Return a safe opaque local source label, never an account address."""
    normalized = _normalize_text(value)
    if not SOURCE_LABEL_PATTERN.fullmatch(normalized):
        raise ValueError("saved_import_invalid_source_label")
    return normalized


def scoped_source_product(source_product: str, source_label: str | None) -> str:
    return f"{source_product}:{source_label}" if source_label else source_product


def split_source_product(source_product: str) -> tuple[str, str | None]:
    base, separator, source_label = source_product.rpartition(":")
    return (base, source_label) if separator else (source_product, None)


def collection_identity(source_product: str, normalized_name: str) -> str:
    return _sha256_text(f"{source_product}\0{normalized_name}")


def _adopt_unlabeled_collection(
    conn: sqlite3.Connection,
    row: SavedRow,
    *,
    source_product: str,
    normalized_name: str,
    started_at: float,
) -> bool:
    """Move a proven matching legacy collection into a scoped identity once."""
    old_id = collection_identity(row.source_product, normalized_name)
    new_id = collection_identity(source_product, normalized_name)
    existing = conn.execute(
        """
        SELECT original_name, description, first_seen_at
        FROM saved_collections
        WHERE collection_id=?
        """,
        (old_id,),
    ).fetchone()
    if not existing:
        return False
    source_digests = {
        item[0]
        for item in conn.execute(
            "SELECT DISTINCT source_file_sha256 FROM saved_memberships WHERE collection_id=?",
            (old_id,),
        )
    }
    if source_digests != {row.source_file_sha256}:
        raise ValueError("saved_import_unlabeled_adoption_mismatch")
    memberships = conn.execute(
        "SELECT membership_id, saved_item_id FROM saved_memberships WHERE collection_id=?",
        (old_id,),
    ).fetchall()
    conn.execute(
        """
        INSERT INTO saved_collections (
            collection_id, source_product, normalized_name, original_name,
            description, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id,
            source_product,
            normalized_name,
            existing[0],
            existing[1],
            existing[2],
            started_at,
        ),
    )
    for membership_id, saved_item_id in memberships:
        conn.execute(
            """
            UPDATE saved_memberships
            SET membership_id=?, collection_id=?
            WHERE membership_id=?
            """,
            (_sha256_text(f"{new_id}\0{saved_item_id}"), new_id, membership_id),
        )
    conn.execute("DELETE FROM saved_collections WHERE collection_id=?", (old_id,))
    return True


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def saved_item_id(row: SavedRow) -> str:
    if row.url:
        return _sha256_text(f"url\0{normalize_url(row.url)}")
    if row.lat is not None and row.lng is not None:
        return _sha256_text(f"coordinates\0{row.lat:.7f}\0{row.lng:.7f}")
    fallback = "\0".join(
        (_normalize_text(row.title), _normalize_text(row.address), _normalize_text(row.note))
    )
    if fallback.replace("\0", ""):
        return _sha256_text(f"content\0{fallback}")
    raise ValueError("saved_import_missing_identity")


def _is_skippable_placeholder(row: SavedRow) -> bool:
    return not any((
        row.title,
        row.url,
        row.address,
        row.note,
        row.comment,
        row.lat is not None and row.lng is not None,
    ))


def inventory(
    conn: sqlite3.Connection,
    *,
    state: str | None = None,
    collection: str | None = None,
    source_label: str | None = None,
    limit: int = 100,
) -> dict:
    ensure_schema(conn)
    normalized_collection = _normalize_text(collection) if collection else None
    normalized_source_label = normalize_source_label(source_label) if source_label else None
    where_sql = """
        WHERE (? IS NULL OR i.state = ?)
          AND (
            (? IS NULL AND ? IS NULL) OR EXISTS (
                SELECT 1
                FROM saved_memberships fm
                JOIN saved_collections fc ON fc.collection_id = fm.collection_id
                WHERE fm.saved_item_id = i.saved_item_id
                  AND (? IS NULL OR fc.normalized_name = ?)
                  AND (? IS NULL OR fc.source_product LIKE '%:' || ?)
            )
          )
    """
    where_params = (
        state,
        state,
        normalized_collection,
        normalized_source_label,
        normalized_collection,
        normalized_collection,
        normalized_source_label,
        normalized_source_label,
    )
    totals = {
        "collections": conn.execute(
            """
            SELECT COUNT(*) FROM saved_collections
            WHERE (? IS NULL OR source_product LIKE '%:' || ?)
            """,
            (normalized_source_label, normalized_source_label),
        ).fetchone()[0],
        "items": conn.execute(
            """
            SELECT COUNT(DISTINCT m.saved_item_id)
            FROM saved_memberships m
            JOIN saved_collections c ON c.collection_id = m.collection_id
            WHERE (? IS NULL OR c.source_product LIKE '%:' || ?)
            """,
            (normalized_source_label, normalized_source_label),
        ).fetchone()[0],
        "memberships": conn.execute(
            """
            SELECT COUNT(*)
            FROM saved_memberships m
            JOIN saved_collections c ON c.collection_id = m.collection_id
            WHERE (? IS NULL OR c.source_product LIKE '%:' || ?)
            """,
            (normalized_source_label, normalized_source_label),
        ).fetchone()[0],
    }
    states = {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT i.state, COUNT(DISTINCT i.saved_item_id)
            FROM saved_items i
            JOIN saved_memberships m ON m.saved_item_id = i.saved_item_id
            JOIN saved_collections c ON c.collection_id = m.collection_id
            WHERE (? IS NULL OR c.source_product LIKE '%:' || ?)
            GROUP BY i.state ORDER BY i.state
            """,
            (normalized_source_label, normalized_source_label),
        )
    }
    collections = [
        {
            "name": row[0],
            "source_product": split_source_product(row[1])[0],
            "source_label": split_source_product(row[1])[1],
            "memberships": row[2],
        }
        for row in conn.execute(
            """
            SELECT c.original_name, c.source_product, COUNT(m.membership_id)
            FROM saved_collections c
            LEFT JOIN saved_memberships m ON m.collection_id = c.collection_id
            WHERE (? IS NULL OR c.source_product LIKE '%:' || ?)
            GROUP BY c.collection_id
            ORDER BY c.original_name COLLATE NOCASE
            """,
            (normalized_source_label, normalized_source_label),
        )
    ]
    matched_items = conn.execute(
        f"SELECT COUNT(*) FROM saved_items i {where_sql}",
        where_params,
    ).fetchone()[0]
    item_rows = conn.execute(
        f"""
        SELECT i.saved_item_id, i.source_title, i.source_address,
               i.source_lat, i.source_lng, i.state
        FROM saved_items i
        {where_sql}
        ORDER BY COALESCE(i.source_title, i.source_address, i.saved_item_id) COLLATE NOCASE
        LIMIT ?
        """,
        (*where_params, limit),
    ).fetchall()
    items = []
    for row in item_rows:
        item_collection_rows = [
            (collection_row[0], *split_source_product(collection_row[1]))
            for collection_row in conn.execute(
                """
                SELECT c.original_name, c.source_product
                FROM saved_memberships m
                JOIN saved_collections c ON c.collection_id = m.collection_id
                WHERE m.saved_item_id = ?
                  AND (? IS NULL OR c.source_product LIKE '%:' || ?)
                ORDER BY c.original_name COLLATE NOCASE
                """,
                (row[0], normalized_source_label, normalized_source_label),
            )
        ]
        items.append(
            {
                "saved_item_id": row[0],
                "title": row[1],
                "address": row[2],
                "lat": row[3],
                "lng": row[4],
                "state": row[5],
                "collections": [collection_row[0] for collection_row in item_collection_rows],
                "collection_refs": [
                    {
                        "name": collection_row[0],
                        "source_product": collection_row[1],
                        "source_label": collection_row[2],
                    }
                    for collection_row in item_collection_rows
                ],
            }
        )
    filters = {"collection": collection, "state": state, "limit": limit}
    if normalized_source_label:
        filters["source_label"] = normalized_source_label
    return {
        "totals": totals,
        "states": states,
        "collections": collections,
        "filters": filters,
        "matched_items": matched_items,
        "items": items,
    }
