"""Cheap health checks shared by CLI and web.

Default checks are local-only: no model calls, scraper starts, Docker probes, or
Chrome launches. Deep live diagnostics belong behind an explicit future flag.
"""

from __future__ import annotations

import time
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import __version__, cache, config, photos, spend

PHOTO_LIVENESS_SAMPLE = 8
PHOTO_LIVENESS_TIMEOUT = 8
PHOTO_LIVENESS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"

Check = dict[str, object]


class _StaticAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            ref = values.get("href")
        elif tag == "script":
            ref = values.get("src")
        else:
            return
        if ref:
            self.references.append(ref)


def _referenced_static_assets(index_html: str) -> list[str]:
    parser = _StaticAssetParser()
    parser.feed(index_html)
    assets = []
    for reference in parser.references:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            continue
        path = unquote(parsed.path)
        if not path.startswith("/static/"):
            continue
        relative = Path(path.removeprefix("/static/"))
        if not relative.name or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe static asset path: {reference}")
        if relative.suffix not in {".css", ".js"}:
            continue
        name = relative.as_posix()
        if name not in assets:
            assets.append(name)
    return assets


def _now_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _check(name: str, severity: str, fn) -> Check:
    start = time.perf_counter()
    try:
        message, data = fn()
        return {
            "name": name,
            "ok": True,
            "severity": severity,
            "latency_ms": _now_ms(start),
            "message": message,
            "next_action": "none",
            "data": data or {},
        }
    except Exception as exc:  # health output must be actionable, not a stack trace
        return {
            "name": name,
            "ok": False,
            "severity": severity,
            "latency_ms": _now_ms(start),
            "message": str(exc),
            "next_action": "Fix this check, or rerun with --require only for checks that must pass.",
            "data": {},
        }


def _db_check() -> tuple[str, dict]:
    conn = cache.connect()
    try:
        conn.execute("SELECT 1").fetchone()
        return "connected", {}
    finally:
        conn.close()


def _data_dir_check() -> tuple[str, dict]:
    config.ensure_dirs()
    probe: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            dir=config.DATA_DIR,
            prefix=".placeintel-healthcheck.",
            delete=False,
        ) as handle:
            probe = Path(handle.name)
            handle.write("ok")
            handle.flush()
            handle.seek(0)
            if handle.read() != "ok":
                raise RuntimeError("write/read probe mismatch")
    finally:
        if probe is not None:
            probe.unlink(missing_ok=True)
    return "writable", {}


def _static_web_check() -> tuple[str, dict]:
    web_dir = config.PROJECT_DIR / "web"
    index_path = web_dir / "index.html"
    if not index_path.exists():
        raise RuntimeError("index.html missing")
    index_html = index_path.read_text(encoding="utf-8")
    files = {}
    for name in ["index.html", *_referenced_static_assets(index_html)]:
        path = web_dir / name
        if not path.exists():
            raise RuntimeError(f"{name} missing")
        lines = len(path.read_text(encoding="utf-8").splitlines())
        files[name] = {"present": True, "lines": lines, "under_800": lines < 800}
        if lines >= 800:
            raise RuntimeError(f"{name} has {lines} lines; AGENTS.md limit is <800")
    return "static shell present and under line budget", {"files": files}


def _reason_models_check() -> tuple[str, dict]:
    models = config.list_reason_models()
    return f"{len(models)} reasoning models listed", {
        "count": len(models),
        "current": config.reason_model(),
    }


def _reason_ping_check() -> tuple[str, dict]:
    model = config.reason_model()
    config.verify_reason_model(model)
    return "reasoning model generateContent ping ok", {"model": model}


def _translation_ping_check() -> tuple[str, dict]:
    model = config.translation_model()
    config.verify_reason_model(model)
    return "translation model generateContent ping ok", {"model": model}


def _embed_ping_check() -> tuple[str, dict]:
    from . import embed

    vec = embed.embed_query("placeintel health ping")
    return "embedding ping ok", {"dims": len(vec)}


def _chrome_check() -> tuple[str, dict]:
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac_chrome.exists():
        candidates.append(str(mac_chrome))
    found = next((item for item in candidates if item), None)
    if not found:
        raise RuntimeError("Chrome binary not found")
    return "Chrome binary found", {"path_detected": True}


def _run_command(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or f"{cmd[0]} exited {proc.returncode}")


def _docker_check() -> tuple[str, dict]:
    if not shutil.which("docker"):
        raise RuntimeError("docker command not found")
    _run_command(["docker", "info"])
    return "Docker daemon responds", {}


def _gosom_image_check() -> tuple[str, dict]:
    if not shutil.which("docker"):
        raise RuntimeError("docker command not found")
    _run_command(["docker", "image", "inspect", config.GOSOM_IMAGE])
    return "gosom image available", {"image": config.GOSOM_IMAGE}


def _review_scraper_check() -> tuple[str, dict]:
    path = config.VENDOR_DIR / "google-reviews-scraper-pro"
    if not path.exists():
        raise RuntimeError("vendor/google-reviews-scraper-pro missing")
    return "review scraper vendor present", {}


def _serpapi_check() -> tuple[str, dict]:
    if not config.serpapi_api_key():
        raise RuntimeError("SERPAPI_API_KEY not configured")
    return "SerpAPI fallback key configured", {"configured": True}


def _spend_policy_check() -> tuple[str, dict]:
    """Report whether a free-path failure can turn into a bill, and catch the
    incoherent state where spending is permitted but impossible."""
    status = spend.policy_status()
    if status["allowed"] and not status["key_configured"]:
        raise RuntimeError(
            "paid SerpAPI fallback is allowed but no key is configured — free-path "
            "failures will surface as a late error instead of a clean refusal"
        )
    verdict = "allowed" if status["allowed"] else "blocked (free paths only)"
    return f"paid fallback {verdict}, per {status['source']}", status


def _sample_stored_photo_urls(limit: int) -> list[str]:
    conn = cache.connect()
    try:
        rows = conn.execute(
            "SELECT place_id FROM places ORDER BY last_refreshed DESC LIMIT ?", (limit * 4,)
        ).fetchall()
        thumbnails = photos.resolve_place_thumbnails(conn, [row["place_id"] for row in rows])
    finally:
        conn.close()
    urls = [
        (thumb or {}).get("thumb_url") or (thumb or {}).get("url")
        for thumb in thumbnails.values()
    ]
    return [url for url in urls if url][:limit]


def _photo_liveness_check() -> tuple[str, dict]:
    """Prove stored photo URLs still resolve, instead of trusting that they do.

    Provider photo URLs are opaque, time-limited tokens. When they expire the UI
    swaps in a placeholder, so a fully broken photo layer looks exactly like
    "these shops have no photos" — which is how 113/113 dead thumbnails went
    unnoticed for seven weeks. Report the alive fraction, and treat an empty
    sample as inconclusive rather than as a pass.
    """
    urls = _sample_stored_photo_urls(PHOTO_LIVENESS_SAMPLE)
    if not urls:
        raise RuntimeError("no stored photo URLs to sample (inconclusive, not a pass)")
    alive = 0
    for url in urls:
        request = urllib.request.Request(url, headers={"User-Agent": PHOTO_LIVENESS_UA})
        try:
            with urllib.request.urlopen(request, timeout=PHOTO_LIVENESS_TIMEOUT) as response:
                if 200 <= response.status < 300:
                    alive += 1
        except (urllib.error.URLError, OSError, ValueError):
            continue
    data = {"sampled": len(urls), "alive": alive}
    if alive == 0:
        raise RuntimeError(
            f"0/{len(urls)} stored photo URLs resolve; provider tokens expired — re-scrape to refresh"
        )
    return f"{alive}/{len(urls)} sampled photo URLs resolve", data


def _provider_warnings(providers: dict) -> list[str]:
    warnings: list[str] = []
    for role, info in providers.items():
        if info.get("provider") == "未配置":
            warnings.append(f"{role}: provider not configured")
    return warnings


def _required_failures(checks: list[Check], providers: dict, require: list[str]) -> list[str]:
    failures: list[str] = []
    by_name = {str(check["name"]): check for check in checks}
    for item in require:
        key = item.strip().lower()
        if not key:
            continue
        if key in by_name:
            if not by_name[key]["ok"]:
                failures.append(f"{key}: {by_name[key]['message']}")
            continue
        if key == "google":
            if providers.get("embed", {}).get("provider") == "未配置":
                failures.append("google: embed provider not configured")
            continue
        if key == "vectorengine":
            if providers.get("reason", {}).get("provider") != "VectorEngine":
                failures.append("vectorengine: reasoning provider is not VectorEngine")
            continue
        failures.append(f"{key}: not checked by cheap health")
    return failures


def cheap_health(*, live: bool = False, require: list[str] | None = None) -> dict:
    """Return the production cheap-health contract.

    ``live`` is accepted so the CLI can expose the future flag without spending
    credits today. When true, callers get a warning and the cheap contract still
    runs.
    """
    checks = [
        _check("db", "critical", _db_check),
        _check("data_dir", "critical", _data_dir_check),
        _check("static_web", "critical", _static_web_check),
        _check("spend_policy", "warning", _spend_policy_check),
    ]
    providers = config.provider_info()
    warnings = _provider_warnings(providers)
    if live:
        warnings.append("live diagnostics are not implemented yet; ran cheap checks only")
    errors = [
        f"{check['name']}: {check['message']}"
        for check in checks
        if not check["ok"] and check["severity"] == "critical"
    ]
    errors.extend(_required_failures(checks, providers, require or []))
    return {
        "ok": not errors,
        "version": __version__,
        "mode": "cheap",
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "providers": providers,
    }


def deep_health(*, require: list[str] | None = None) -> dict:
    """Opt-in diagnostics that may touch providers or local external tools."""
    report = cheap_health(require=None)
    report["mode"] = "deep"
    report["checks"].extend([
        _check("reason_models", "warning", _reason_models_check),
        _check("reason_ping", "warning", _reason_ping_check),
        _check("translation_ping", "warning", _translation_ping_check),
        _check("embed_ping", "warning", _embed_ping_check),
        _check("chrome", "warning", _chrome_check),
        _check("docker", "warning", _docker_check),
        _check("gosom_image", "warning", _gosom_image_check),
        _check("review_scraper", "warning", _review_scraper_check),
        _check("serpapi", "warning", _serpapi_check),
        _check("photo_liveness", "warning", _photo_liveness_check),
    ])
    warnings = _provider_warnings(report["providers"])
    warnings.extend(
        f"{check['name']}: {check['message']}"
        for check in report["checks"]
        if not check["ok"] and check["severity"] == "warning"
    )
    errors = [
        f"{check['name']}: {check['message']}"
        for check in report["checks"]
        if not check["ok"] and check["severity"] == "critical"
    ]
    errors.extend(_required_failures(report["checks"], report["providers"], require or []))
    report["warnings"] = warnings
    report["errors"] = errors
    report["ok"] = not errors
    return report
