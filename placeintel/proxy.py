"""Residential proxy resolver for PlaceIntel.

Integrates with ultra-low-cost-scraper / DataImpulse residential proxy pools.
Provides auto-fallback when direct machine/datacenter IP scraping encounters rate limits or blocks.

Two measured properties of this pool, 2026-08-31, that callers must design around:

GEO WORKS, STICKINESS DOES NOT. `__cr-<country>` is honoured — requesting `vn`
returned 14.186.211.156 / 171.225.206.13 / 123.24.202.249, all Vietnamese. The
`session_id` parameter below is *accepted and ignored*: five username syntaxes
(`__session-`, `__sess-`, `__sticky-`, `-session-`, and combined with `__cr-`)
each returned a different exit IP on every one of three consecutive requests.
The parameter is kept because callers pass it and a future plan or port may
honour it, but **do not assume two requests share an IP.** Whether a dedicated
sticky port exists on this plan is UNKNOWN — ports 10000/10001/10500/9999 did
not answer within 25 s.

PER-CONNECTION FAILURE RATE IS REAL. Measured 2 failures in 6 HTTPS requests
through the pool, and 1 in 6 on the same test without the relay in the path — so
the loss is the pool's exit nodes, not our plumbing. Single API-style fetches
should retry. Driving a *browser* through it is the poor fit: one page load
opens many connections, each landing on a different exit IP with an independent
chance of dropping mid-handshake.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_FILE = Path.home() / ".cache" / "ultra-low-cost-scraper" / "proxy_cache.json"


def resolve_residential_proxy(geo: str | None = None, session_id: str | None = None) -> str | None:
    """Resolve a residential proxy URL if configured.

    Checks:
    1. Direct in-process resolution via ulcs.proxy (preferred)
    2. Environment variables: PLACEINTEL_RESIDENTIAL_PROXY_URL, DATAIMPULSE_PROXY_URL, SCRAPER_PROXY_URL
    3. Legacy proxy_resolver.py subprocess fallback
    4. Local proxy cache fallback (~/.cache/ultra-low-cost-scraper/proxy_cache.json)
    """
    env_url = (
        os.getenv("PLACEINTEL_RESIDENTIAL_PROXY_URL")
        or os.getenv("DATAIMPULSE_PROXY_URL")
        or os.getenv("SCRAPER_PROXY_URL")
    )
    if env_url:
        return _format_proxy_url(env_url, geo=geo, session_id=session_id)

    try:
        from ulcs.proxy import resolve_proxy_url
        url = resolve_proxy_url(geo=geo, session_id=session_id)
        if url:
            return url
    except ImportError:
        pass

    resolver_script = Path.home() / ".agents" / "skills" / "ultra-low-cost-scraper" / "scripts" / "proxy_resolver.py"
    if resolver_script.exists():
        try:
            cmd = [sys.executable, str(resolver_script), "--format", "url"]
            if geo:
                cmd.extend(["--geo", geo])
            if session_id:
                cmd.extend(["--session", session_id])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception as exc:
            logger.debug("Failed to invoke proxy_resolver.py: %s", exc)

    if CACHE_FILE.exists():
        try:
            import json
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            login = cached.get("login")
            pwd = cached.get("password")
            host = cached.get("hostname", "proxy.example.com")  # nosec: mock
            port = cached.get("port", "823")
            if login and pwd:
                base_url = f"http://{login}:{pwd}@{host}:{port}"
                return _format_proxy_url(base_url, geo=geo, session_id=session_id)
        except Exception:
            pass

    return None


def is_residential_proxy_available() -> bool:
    return bool(resolve_residential_proxy())


def mask_proxy(url: str | None) -> str:
    if not url:
        return "None"
    m = re.match(r"(https?://)([^:]+):([^@]+)@([^:]+):(\d+)", url)
    if m:
        scheme, user, _, host, port = m.groups()
        masked_user = f"{user[:4]}***" if len(user) > 4 else "***"
        return f"{scheme}{masked_user}:***@{host}:{port}"
    return "http://***:***@proxy"


def _format_proxy_url(url: str, geo: str | None = None, session_id: str | None = None) -> str:
    if (geo or session_id) and ("dataimpulse.com" in url or "proxy.example.com" in url):  # nosec: mock
        m = re.match(r"(https?://)([^:]+):([^@]+)@([^:]+:\d+)", url)
        if m:
            scheme, user, pwd, hostport = m.groups()
            clean_user = re.split(r"__(cr|country|session)", user)[0]
            addons = []
            if geo:
                addons.append(f"__cr-{geo.lower()}")
            if session_id:
                addons.append(f"__session-{session_id}")
            return f"{scheme}{clean_user}{''.join(addons)}:{pwd}@{hostport}"
    return url
