"""Language preference and target-language helpers.

This module is deliberately provider-free. It owns safe tag normalization and
preference precedence so API, CLI, web, Ask, reports, and review translation do
not each invent a slightly different language rule.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import config

FALLBACK_LANGUAGE = "en"
SUPPORTED_UI_LOCALES = ("en", "zh")
EVIDENCE_LANGUAGE_MODES = ("report", "original")
COMMON_LANGUAGE_LABELS = {
    "en": "English",
    "zh": "Simplified Chinese",
    "vi": "Vietnamese",
    "ko": "Korean",
    "ja": "Japanese",
    "th": "Thai",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
}

_ALIASES = {
    "auto": "auto",
    "cn": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    "chinese": "zh",
    "中文": "zh",
    "english": "en",
}
_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8}){0,3}$")
_BAD_CHARS_RE = re.compile(r"[\x00-\x1f\x7f/\\<>;:'\"`{}()[\]|]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_KO_RE = re.compile(r"[\uac00-\ud7af]")
_JA_RE = re.compile(r"[\u3040-\u30ff]")
_TH_RE = re.compile(r"[\u0e00-\u0e7f]")
_VI_RE = re.compile(
    r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩị"
    r"óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LanguageChoice:
    tag: str
    source: str


@dataclass(frozen=True)
class TranslationTarget:
    tag: str
    instruction: str
    label: str


def normalize_language_tag(value: object, *, allow_auto: bool = False) -> str | None:
    """Return a safe, canonical BCP-47-like tag or None.

    This is intentionally stricter than full BCP-47. The app only needs safe
    target tags for prompts, cache keys, settings, and html lang values.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    lowered = raw.replace("_", "-").casefold()
    if allow_auto and lowered == "auto":
        return "auto"
    raw = _ALIASES.get(lowered, raw).replace("_", "-")
    lowered = raw.casefold()
    if allow_auto and lowered == "auto":
        return "auto"
    if lowered in _ALIASES and _ALIASES[lowered] != "auto":
        raw = _ALIASES[lowered]
    if len(raw) > 35 or _BAD_CHARS_RE.search(raw) or not _TAG_RE.match(raw):
        return None
    parts = raw.split("-")
    lang = parts[0].lower()
    if len(lang) not in (2, 3) or not lang.isalpha():
        return None
    out = [lang]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            out.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            out.append(part.title())
        else:
            out.append(part.lower())
    tag = "-".join(out)
    return _ALIASES.get(tag.casefold(), tag)


def _first_choice(candidates: list[tuple[str, object]]) -> LanguageChoice | None:
    for source, value in candidates:
        tag = normalize_language_tag(value, allow_auto=True)
        if tag and tag != "auto":
            return LanguageChoice(tag, source)
    return None


def resolve_output_language(
    *,
    explicit: object = None,
    saved: object = None,
    browser: object = None,
    planner: object = None,
    fallback: str = FALLBACK_LANGUAGE,
) -> LanguageChoice:
    return (
        _first_choice([
            ("request", explicit),
            ("settings", saved),
            ("browser", browser),
            ("planner", planner),
        ])
        or LanguageChoice(normalize_language_tag(fallback) or FALLBACK_LANGUAGE, "default")
    )


def resolve_ui_language(
    *,
    explicit: object = None,
    saved: object = None,
    browser: object = None,
) -> LanguageChoice:
    choice = _first_choice([
        ("request", explicit),
        ("settings", saved),
        ("browser", browser),
    ])
    if choice and choice.tag.split("-")[0] in SUPPORTED_UI_LOCALES:
        return LanguageChoice(choice.tag.split("-")[0], choice.source)
    return LanguageChoice(FALLBACK_LANGUAGE, "fallback" if choice else "default")


def resolve_translation_target(value: object = None, *, fallback: object = None) -> TranslationTarget:
    has_value = value is not None and str(value).strip() != ""
    tag = normalize_language_tag(value) if has_value else None
    if has_value and not tag:
        raise ValueError("invalid target_lang")
    tag = tag or normalize_language_tag(fallback) or FALLBACK_LANGUAGE
    base = tag.split("-")[0]
    label = COMMON_LANGUAGE_LABELS.get(tag) or COMMON_LANGUAGE_LABELS.get(base) or tag
    return TranslationTarget(
        tag=tag,
        label=label,
        instruction=f"{label} (target language tag: {tag})",
    )


def language_instruction(tag: object) -> str:
    return resolve_translation_target(tag).instruction


def detect_text_language(text: str | None) -> str | None:
    s = str(text or "")
    if not s.strip():
        return None
    if _CJK_RE.search(s):
        return "zh"
    if _KO_RE.search(s):
        return "ko"
    if _JA_RE.search(s):
        return "ja"
    if _TH_RE.search(s):
        return "th"
    if _VI_RE.search(s):
        return "vi"
    return "en" if re.search(r"[A-Za-z]", s) else None


def _setting(key: str, default: str = "auto") -> str:
    value = config._load_settings().get(key) or default
    return normalize_language_tag(value, allow_auto=True) or default


def default_language_setting(key: str, *, fallback_env: bool = True) -> str:
    default = os.getenv("PLACEINTEL_DEFAULT_LANGUAGE", "auto") if fallback_env else "auto"
    return _setting(key, default)


def evidence_language() -> str:
    value = (config._load_settings().get("evidence_language") or config.EVIDENCE_LANG or "report").strip().lower()
    return value if value in EVIDENCE_LANGUAGE_MODES else "report"


def config_language_status(browser_hint: object = None) -> dict:
    ui_default = default_language_setting("ui_language")
    answer_default = default_language_setting("default_answer_language")
    report_default = default_language_setting("default_report_language")
    translation_default = default_language_setting("translation_target")
    ui = resolve_ui_language(saved=ui_default, browser=browser_hint)
    answer = resolve_output_language(saved=answer_default, browser=browser_hint)
    report = resolve_output_language(saved=report_default, browser=browser_hint)
    translation = resolve_translation_target(
        None if translation_default == "auto" else translation_default,
        fallback=answer.tag,
    )
    return {
        "ui_language": ui.tag,
        "answer_language": answer.tag,
        "report_language": report.tag,
        "translation_target": translation.tag,
        "evidence_language": evidence_language(),
        "source": answer.source,
        "fallback_language": FALLBACK_LANGUAGE,
        "supported_ui_locales": list(SUPPORTED_UI_LOCALES),
        "common_languages": COMMON_LANGUAGE_LABELS,
        "app_defaults": {
            "ui_language": ui_default,
            "answer_language": answer_default,
            "report_language": report_default,
            "translation_target": translation_default,
        },
    }


def validate_language_settings(payload: dict) -> dict:
    updates: dict[str, str] = {}
    key_map = {
        "ui_language": "ui_language",
        "default_answer_language": "default_answer_language",
        "default_report_language": "default_report_language",
        "translation_target": "translation_target",
    }
    for api_key, setting_key in key_map.items():
        if api_key not in payload or payload[api_key] in (None, ""):
            continue
        tag = normalize_language_tag(payload[api_key], allow_auto=True)
        if not tag:
            raise ValueError(f"invalid {api_key}")
        if setting_key == "ui_language" and tag != "auto" and tag.split("-")[0] not in SUPPORTED_UI_LOCALES:
            raise ValueError("invalid ui_language")
        updates[setting_key] = tag.split("-")[0] if setting_key == "ui_language" and tag != "auto" else tag
    if "evidence_language" in payload and payload["evidence_language"] not in (None, ""):
        mode = str(payload["evidence_language"]).strip().lower()
        if mode not in EVIDENCE_LANGUAGE_MODES:
            raise ValueError("invalid evidence_language")
        updates["evidence_language"] = mode
    return updates
