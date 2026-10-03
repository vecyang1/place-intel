"""Backup and restore helpers for local placeintel data.

The backup package is intentionally boring: SQLite's online backup API for DBs,
normal file copies for generated reports/settings, and a manifest with hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import __version__, config

MANIFEST_NAME = "manifest.json"
REQUIRED_TABLES = {"places", "reviews", "reports", "searches", "qa", "jobs", "job_events"}


@dataclass
class BackupError(Exception):
    code: str
    message: str
    next_action: str

    def __str__(self) -> str:
        return self.message


def default_backup_root() -> Path:
    return config.DATA_DIR / "backups"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_record(base: Path, path: Path, kind: str) -> dict:
    rel = path.relative_to(base).as_posix()
    return {"path": rel, "kind": kind, "size": path.stat().st_size, "sha256": _sha256(path)}


def _backup_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def create_backup(destination: Path | str | None = None) -> dict:
    config.ensure_dirs()
    backup_dir = Path(destination) if destination else default_backup_root() / f"placeintel-backup-{_stamp()}"
    backup_dir = backup_dir.expanduser()
    if backup_dir.exists():
        raise BackupError(
            "backup_exists",
            f"backup destination already exists: {backup_dir}",
            "Choose a new --output path or remove the incomplete backup after inspection.",
        )
    backup_dir.mkdir(parents=True, exist_ok=False)
    records: list[dict] = []
    try:
        if config.DB_PATH.exists():
            target = backup_dir / "placeintel.db"
            _backup_sqlite(config.DB_PATH, target)
            records.append(_manifest_record(backup_dir, target, "sqlite"))
        scraper_db = config.DATA_DIR / "scraper_pro_reviews.db"
        if scraper_db.exists():
            target = backup_dir / "scraper_pro_reviews.db"
            _backup_sqlite(scraper_db, target)
            records.append(_manifest_record(backup_dir, target, "sqlite"))
        settings = config.SETTINGS_PATH
        if settings.exists():
            target = backup_dir / "settings.json"
            _copy_file(settings, target)
            records.append(_manifest_record(backup_dir, target, "settings"))
        reports_dir = config.DATA_DIR / "reports"
        if reports_dir.exists():
            for src in sorted(p for p in reports_dir.rglob("*") if p.is_file() and not p.is_symlink()):
                target = backup_dir / "reports" / src.relative_to(reports_dir)
                _copy_file(src, target)
                records.append(_manifest_record(backup_dir, target, "report"))
        manifest = {
            "app": "placeintel",
            "version": __version__,
            "created_at": _now_iso(),
            "source_data_dir": str(config.DATA_DIR),
            "files": records,
        }
        manifest_path = backup_dir / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "manifest_path": str(manifest_path),
            "backup_dir": str(backup_dir),
            "created_at": manifest["created_at"],
            "file_count": len(records),
            "total_bytes": sum(item["size"] for item in records),
            "files": records,
        }
    except Exception:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise


def _manifest_path(source: Path | str) -> Path:
    path = Path(source).expanduser()
    return path / MANIFEST_NAME if path.is_dir() else path


def _safe_rel(path: str) -> PurePosixPath:
    rel = PurePosixPath(path)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise BackupError("bad_manifest", f"unsafe manifest path: {path}", "Use a manifest created by placeintel backup.")
    if any(part.startswith(".env") for part in rel.parts):
        raise BackupError("bad_manifest", f"secret-like path refused: {path}", "Remove secret files from the backup.")
    return rel


def _validate_placeintel_db(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise BackupError(
            "invalid_backup",
            f"placeintel.db missing required tables: {', '.join(missing)}",
            "Create a new backup from a migrated database, then retry restore.",
        )


def _load_and_validate_manifest(manifest_path: Path) -> tuple[dict, list[dict]]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("bad_manifest", f"cannot read backup manifest: {exc}", "Pass a valid manifest.json path.")
    if manifest.get("app") != "placeintel":
        raise BackupError("bad_manifest", "manifest is not a placeintel backup", "Use a manifest created by placeintel backup.")
    base = manifest_path.parent.resolve()
    records = []
    for item in manifest.get("files") or []:
        rel = _safe_rel(str(item.get("path", "")))
        target = (base / rel.as_posix()).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise BackupError("bad_manifest", f"backup file missing: {rel}", "Create a fresh backup and retry.")
        if target.stat().st_size != int(item.get("size", -1)):
            raise BackupError("hash_mismatch", f"size mismatch for {rel}", "Discard this backup and create a fresh one.")
        if _sha256(target) != item.get("sha256"):
            raise BackupError("hash_mismatch", f"SHA-256 mismatch for {rel}", "Discard this backup and create a fresh one.")
        records.append({**item, "path": rel.as_posix(), "_source": target})
    place_db = next((r["_source"] for r in records if r["path"] == "placeintel.db"), None)
    if place_db:
        _validate_placeintel_db(place_db)
    return manifest, records


def _stage_file(src: Path, dst: Path) -> Path:
    tmp = dst.with_name(f".{dst.name}.restore.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, tmp)
    return tmp


def _replace_sqlite(tmp: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, dst)
    for suffix in ("-wal", "-shm"):
        Path(str(dst) + suffix).unlink(missing_ok=True)


def restore_backup(source: Path | str, *, yes: bool = False, force: bool = False) -> dict:
    manifest_path = _manifest_path(source).resolve()
    allowed_root = default_backup_root().resolve()
    if not force and not manifest_path.is_relative_to(allowed_root):
        raise BackupError(
            "outside_backup_root",
            f"restore source is outside {allowed_root}",
            "Re-run with --force only if you trust this backup path.",
        )
    if not yes:
        raise BackupError(
            "confirmation_required",
            "restore replaces local runtime data and requires --yes",
            "Re-run with --yes after confirming the backup manifest path.",
        )
    _, records = _load_and_validate_manifest(manifest_path)
    staged: list[tuple[str, Path, Path]] = []
    report_records = [r for r in records if str(r["path"]).startswith("reports/")]
    try:
        for rel, dst in (
            ("placeintel.db", config.DB_PATH),
            ("scraper_pro_reviews.db", config.DATA_DIR / "scraper_pro_reviews.db"),
            ("settings.json", config.SETTINGS_PATH),
        ):
            record = next((r for r in records if r["path"] == rel), None)
            if record:
                staged.append((rel, _stage_file(record["_source"], dst), dst))
        temp_reports = None
        if report_records:
            temp_reports = config.DATA_DIR / f".reports.restore-{_stamp()}"
            if temp_reports.exists():
                shutil.rmtree(temp_reports)
            for record in report_records:
                rel = PurePosixPath(record["path"]).relative_to("reports")
                _copy_file(record["_source"], temp_reports / rel.as_posix())
        restored = []
        for rel, tmp, dst in staged:
            _replace_sqlite(tmp, dst) if rel.endswith(".db") else os.replace(tmp, dst)
            restored.append(rel)
        if temp_reports:
            reports_dir = config.DATA_DIR / "reports"
            previous = config.DATA_DIR / f".reports.previous-{_stamp()}"
            if reports_dir.exists():
                reports_dir.rename(previous)
            temp_reports.rename(reports_dir)
            shutil.rmtree(previous, ignore_errors=True)
            restored.extend(r["path"] for r in report_records)
    finally:
        for _, tmp, _ in staged:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    return {
        "manifest_path": str(manifest_path),
        "restored_files": len(restored),
        "restored": restored,
    }
