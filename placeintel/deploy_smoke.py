"""Read-only deployment smoke checks for placeintel services."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass
class SmokeError(Exception):
    message: str


def _join(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _request(url: str, timeout: float) -> tuple[int, str, str]:
    req = Request(url, headers={"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, response.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body, exc.headers.get("Content-Type", "")
    except URLError as exc:
        raise SmokeError(str(exc.reason)) from exc


def _json_get(base_url: str, path: str, timeout: float) -> tuple[int, dict | list]:
    status, body, _ = _request(_join(base_url, path), timeout)
    if status >= 400:
        raise SmokeError(f"GET {path} returned HTTP {status}")
    try:
        return status, json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"GET {path} did not return JSON: {exc}") from exc


def _check(name: str, fn) -> dict:
    started = perf_counter()
    try:
        data = fn()
        return {"name": name, "ok": True, "latency_ms": int((perf_counter() - started) * 1000), "data": data or {}}
    except Exception as exc:
        return {"name": name, "ok": False, "latency_ms": int((perf_counter() - started) * 1000), "error": str(exc), "data": {}}


def run(
    base_url: str, *, expected_version: str | None = None, public_url: str | None = None,
    timeout: float = 5.0,
) -> dict:
    version_seen: dict[str, str | None] = {"meta": None}

    def meta():
        _, payload = _json_get(base_url, "/api/meta", timeout)
        version = payload.get("version") if isinstance(payload, dict) else None
        version_seen["meta"] = version
        if expected_version and version != expected_version:
            raise SmokeError(f"expected version {expected_version}, got {version}")
        return {"version": version}

    def health():
        _, payload = _json_get(base_url, "/api/health", timeout)
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise SmokeError("health endpoint did not report ok")
        return {"version": payload.get("version"), "mode": payload.get("mode")}

    def static_version():
        status, html, _ = _request(_join(base_url, "/"), timeout)
        if status >= 400:
            raise SmokeError(f"GET / returned HTTP {status}")
        match = re.search(r"/static/app\.js\?v=([^\"']+)", html)
        if not match:
            raise SmokeError("index did not include versioned app.js asset")
        asset_version = match.group(1)
        if expected_version and asset_version != expected_version:
            raise SmokeError(f"expected static version {expected_version}, got {asset_version}")
        return {"asset_version": asset_version}

    def library():
        _, payload = _json_get(base_url, "/api/places", timeout)
        if not isinstance(payload, list):
            raise SmokeError("/api/places did not return a list")
        first = next((p for p in payload if isinstance(p, dict) and p.get("place_id")), None)
        return {"place_count": len(payload), "first_place_id": first.get("place_id") if first else None}

    def dossier():
        _, places = _json_get(base_url, "/api/places", timeout)
        first = next((p for p in places if isinstance(p, dict) and p.get("place_id")), None)
        if not first:
            return {"skipped": "library is empty"}
        place_id = first["place_id"]
        _, payload = _json_get(base_url, f"/api/places/{place_id}", timeout)
        if not isinstance(payload, dict) or not isinstance(payload.get("place"), dict):
            raise SmokeError("dossier response missing place object")
        return {"place_id": place_id}

    checks = [
        _check("meta", meta),
        _check("health", health),
        _check("static_version", static_version),
        _check("library", library),
        _check("dossier", dossier),
    ]
    if public_url:
        def public_auth():
            status, _, _ = _request(_join(public_url, "/"), timeout)
            if status not in {401, 403}:
                raise SmokeError(f"expected public unauthenticated 401/403, got HTTP {status}")
            return {"status": status}
        checks.append(_check("public_auth", public_auth))
    return {
        "base_url": base_url,
        "public_url": public_url,
        "expected_version": expected_version,
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
    }
