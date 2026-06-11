"""Central configuration: paths, API keys, model names.

Key discovery order (no key ever hardcoded here):
  Gemini/VectorEngine: $GEMINI_API_KEY or $VECTORENGINE_API_KEY,
    else parsed from the gemini-embedding-2-guide skill .env.
  SerpAPI: $SERPAPI_API_KEY, else parsed from the serpapi-mcp skill .mcp.json.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Load a project-local `.env` if present (external users: copy `.env.example`).
# Never overrides variables already exported in the environment.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
except ModuleNotFoundError:  # declared dependency, but stay resilient
    pass

DATA_DIR = Path(os.getenv("PLACEINTEL_DATA_DIR", PROJECT_DIR / "data"))
DB_PATH = DATA_DIR / "placeintel.db"
VENDOR_DIR = PROJECT_DIR / "vendor"
PROFILES_DIR = PROJECT_DIR / "profiles"

VECTORENGINE_BASE_URL = os.getenv("VECTORENGINE_BASE_URL", "https://api.vectorengine.ai")
VECTORENGINE_API_VERSION = "v1beta"
EMBED_MODEL = os.getenv("PLACEINTEL_EMBED_MODEL", "gemini-embedding-2-preview")
EMBED_DIMS = int(os.getenv("PLACEINTEL_EMBED_DIMS", "768"))
# Last-resort default only. The ACTIVE reasoning model is reason_model():
# settings.json (user-picked, persisted) > $PLACEINTEL_REASON_MODEL > this.
# Available models must always be listed LIVE from the provider (list_reason_models)
# — never from training-data knowledge, which goes stale.
DEFAULT_REASON_MODEL = "gemini-2.5-flash"

SETTINGS_PATH = DATA_DIR / "settings.json"

# Cached-place details considered stale after this many days (hours/price drift).
PLACE_TTL_DAYS = int(os.getenv("PLACEINTEL_PLACE_TTL_DAYS", "14"))

# Quoted review evidence in reports/answers: "report" = translated into the report
# language with an original-language tag; "original" = quoted verbatim.
EVIDENCE_LANG = os.getenv("PLACEINTEL_EVIDENCE_LANG", "report")

GOSOM_IMAGE = "gosom/google-maps-scraper"

# Author-local convenience only: if keys aren't in the environment or a project
# `.env`, fall back to these skill config files. External users should ignore
# these and just set GOOGLE_API_KEY / VECTORENGINE_API_KEY / SERPAPI_API_KEY.
_EMBED_SKILL_ENV = Path.home() / ".claude/skills/gemini-embedding-2-guide/.env"
_READ_MEDIA_ENV = Path.home() / ".claude/skills/Read-Media-Gemini/.env"
_SERPAPI_SKILL_MCP = Path.home() / ".claude/skills/serpapi-mcp/.mcp.json"


def _parse_env_file(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    match = re.search(rf"^{key}=(.+)$", path.read_text(), flags=re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else None


# Role-based provider routing (user decision 2026-06-11):
#   embedding → Google official (AIza key): VectorEngine is slow on embedding
#               uploads and aggregates batched contents into one vector.
#   reasoning → VectorEngine (sk- key): same Gemini models, cheaper.
# Either role falls back to the other provider's key if its preferred one is absent.


def _google_key() -> str | None:
    key = os.getenv("GOOGLE_API_KEY") or _parse_env_file(_READ_MEDIA_ENV, "GOOGLE_API_KEY")
    if key and key.startswith("AIza"):
        return key
    env_key = os.getenv("GEMINI_API_KEY") or _parse_env_file(_EMBED_SKILL_ENV, "GEMINI_API_KEY")
    return env_key if env_key and env_key.startswith("AIza") else None


def _vectorengine_key() -> str | None:
    for candidate in (
        os.getenv("VECTORENGINE_API_KEY"),
        _parse_env_file(_READ_MEDIA_ENV, "VECTORENGINE_API_KEY"),
        _parse_env_file(_EMBED_SKILL_ENV, "VECTORENGINE_API_KEY"),
    ):
        if candidate and candidate.startswith("sk-"):
            return candidate
    return None


def _credentials(preferred: str) -> tuple[str, dict | None]:
    """Return (api_key, http_options); http_options is None on Google official."""
    google, vectorengine = _google_key(), _vectorengine_key()
    ve_options = {
        "base_url": VECTORENGINE_BASE_URL,
        "api_version": VECTORENGINE_API_VERSION,
    }
    if preferred == "google" and google:
        return google, None
    if vectorengine:
        return vectorengine, ve_options
    if google:
        return google, None
    raise RuntimeError(
        "No Gemini API key found. Set GOOGLE_API_KEY (AIza...) or "
        f"VECTORENGINE_API_KEY (sk-...), or add one to {_READ_MEDIA_ENV}"
    )


def embed_credentials() -> tuple[str, dict | None]:
    return _credentials(preferred="google")


def reason_credentials() -> tuple[str, dict | None]:
    return _credentials(preferred="vectorengine")


# -- Runtime settings (user-picked model, persisted across restarts) -----------
# settings.json holds NON-SECRET preferences only — never keys.


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_setting(key: str, value: str) -> None:
    ensure_dirs()
    settings = {**_load_settings(), key: value}
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    os.replace(tmp, SETTINGS_PATH)


def reason_model() -> str:
    """Active reasoning model: user setting > env > default."""
    return (
        _load_settings().get("reason_model")
        or os.getenv("PLACEINTEL_REASON_MODEL")
        or DEFAULT_REASON_MODEL
    )


def list_reason_models() -> list[str]:
    """LIVE generateContent-capable model list from the reasoning provider.

    Queried from the provider's /models endpoint at call time — model
    availability must never come from baked-in knowledge. Raises on failure;
    callers surface the error instead of substituting a stale list."""
    from google import genai  # lazy: keep config import light

    api_key, http_options = reason_credentials()
    client = genai.Client(api_key=api_key, http_options=http_options)
    names = []
    for m in client.models.list():
        name = (m.name or "").removeprefix("models/")
        actions = getattr(m, "supported_actions", None)
        if actions and "generateContent" not in actions:
            continue
        if not actions and ("embedding" in name or "embed" in name.split("-")):
            continue
        if name:
            names.append(name)
        if len(names) >= 200:
            break
    return sorted(set(names))


def verify_reason_model(model: str) -> None:
    """One tiny real generateContent call — proves the model works on the
    current provider before we persist it. Raises with the provider's error."""
    from google import genai
    from google.genai import types

    api_key, http_options = reason_credentials()
    client = genai.Client(api_key=api_key, http_options=http_options)
    client.models.generate_content(
        model=model, contents="ping",
        config=types.GenerateContentConfig(max_output_tokens=5, temperature=0),
    )


def set_reason_model(model: str, verify: bool = True) -> None:
    model = model.strip().removeprefix("models/")
    if not model:
        raise ValueError("model name is empty")
    if verify:
        verify_reason_model(model)
    save_setting("reason_model", model)


def _provider_label(http_options: dict | None) -> str:
    if http_options is None:
        return "Google 官方"
    base = str(http_options.get("base_url", ""))
    if "vectorengine" in base:
        return "VectorEngine"
    return base.replace("https://", "").replace("http://", "") or "custom"


def provider_info() -> dict:
    """Resolved model + provider per role — for UI transparency. Never leaks keys."""
    def describe(creds_fn, model: str) -> dict:
        try:
            _, http_options = creds_fn()
            provider = _provider_label(http_options)
        except RuntimeError:
            provider = "未配置"
        return {"model": model, "provider": provider}
    return {
        "reason": describe(reason_credentials, reason_model()),
        "embed": describe(embed_credentials, f"{EMBED_MODEL} ({EMBED_DIMS}d)"),
    }


def serpapi_api_key() -> str | None:
    """SerpAPI key is optional — used only as scraping fallback."""
    key = os.getenv("SERPAPI_API_KEY")
    if key:
        return key
    if _SERPAPI_SKILL_MCP.exists():
        try:
            mcp = json.loads(_SERPAPI_SKILL_MCP.read_text())
            return mcp["mcpServers"]["serpapi-mcp"]["env"]["SERPAPI_API_KEY"]
        except (KeyError, json.JSONDecodeError):
            return None
    return None


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
