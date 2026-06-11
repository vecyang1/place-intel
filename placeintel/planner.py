"""AI query planner — the brain that makes the tool AI-native.

Three jobs, all via the reasoning model (VectorEngine-routed, cheap):
  make_plan(text)          raw user input in ANY language → structured search plan
                           (queries to run, location, profile, report language,
                           single-shop vs discovery mode)
  filter_candidates(...)   judge discovered places against the user's intent —
                           kills the "motorbike rental for a guitar query" class
                           of bug. Fail-OPEN: if the LLM call breaks, nothing is
                           dropped.
  pick_target(...)         match a user-named shop to one discovered candidate.

Every function degrades gracefully — AI planning must never block the pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from functools import lru_cache

from google import genai
from google.genai import types

from . import cache, config, profiles

log = logging.getLogger(__name__)

MAPS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:maps\.google\.[a-z.]+|google\.[a-z.]+/maps|"
    r"goo\.gl/maps|maps\.app\.goo\.gl)\S*",
    re.IGNORECASE,
)
_PLACE_PATH_RE = re.compile(r"/maps/place/([^/@?]+)")
_CID_RE = re.compile(r"[?&]cid=(\d+)")
_HEX_PAIR_RE = re.compile(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
_CJK_RE = re.compile(r"[一-鿿]")


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    api_key, http_options = config.reason_credentials()
    return genai.Client(api_key=api_key, http_options=http_options)


def _generate_json(system: str, user: str, temperature: float = 0.1) -> dict:
    response = _client().models.generate_content(
        model=config.reason_model(),
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=temperature,
            response_mime_type="application/json",
        ),
    )
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (response.text or "").strip())
    return json.loads(cleaned)


# -- URL handling --------------------------------------------------------------

def parse_maps_url(text: str) -> dict | None:
    """Extract {url, name?, cid?} if the text contains a Google Maps URL."""
    match = MAPS_URL_RE.search(text)
    if not match:
        return None
    url = match.group(0)
    info: dict = {"url": url}
    path_match = _PLACE_PATH_RE.search(url)
    if path_match:
        name = urllib.parse.unquote_plus(path_match.group(1)).replace("+", " ")
        info["name"] = name.strip()
    cid_match = _CID_RE.search(url) or _HEX_PAIR_RE.search(url)
    if cid_match:
        info["cid"] = cid_match.group(1)
    return info


# -- plan ----------------------------------------------------------------------

def _fallback_plan(user_text: str, near: str | None) -> dict:
    """No-LLM plan: pass the query through untouched. Keeps the pipeline alive."""
    url_info = parse_maps_url(user_text)
    return {
        "intent": user_text,
        "mode": "single" if url_info else "discover",
        "target": (url_info or {}).get("name") or (url_info or {}).get("url"),
        "near": near,
        "queries": [user_text],
        "scrape_lang": "en",
        "profile": profiles.guess_profile(user_text),
        "report_lang": "zh" if _CJK_RE.search(user_text) else "en",
        "relevance": user_text,
        "reasoning": "(AI 规划不可用，按原文搜索)",
        "ai": False,
    }


def make_plan(user_text: str, near: str | None = None) -> dict:
    """Turn raw user input (any language, maybe a URL) into a structured plan."""
    url_info = parse_maps_url(user_text)
    profile_names = profiles.list_profiles()
    system = f"""You are the query-planning brain of a Google-Maps local-business
intelligence tool. The user gives free text in ANY language (Chinese, English, ...) —
possibly a specific shop name or a Google Maps URL. Decide what to actually search.

Return STRICT JSON:
{{
  "intent": "one English sentence: what the user wants",
  "mode": "discover" | "single",
  "target": "exact business name if mode=single, else null",
  "near": "city, country in English (extract from the text if present; null if truly unknown)",
  "queries": ["1-3 Google Maps search queries: FIRST in English, then in the destination's local language (e.g. Vietnamese for Vietnam)"],
  "scrape_lang": "2-letter review-scrape language code, usually 'en'",
  "profile": "one of: {', '.join(profile_names)}",
  "report_lang": "the language the user wrote in: 'zh', 'en', ...",
  "relevance": "one English sentence: what makes a search result RELEVANT (used to reject off-category places, e.g. a motorbike-rental shop is NOT relevant to a guitar-rental query)",
  "reasoning": "≤2 short sentences IN THE USER'S LANGUAGE explaining what you decided to search and why"
}}

mode=single ONLY when the text clearly names ONE specific business (or is a Maps URL);
generic category searches ("guitar rental", "按摩") are mode=discover.
Queries must be category searches a Maps search box would accept — never include
rating/price wishes in them; those belong in "relevance"."""
    user = f"USER INPUT: {user_text}\n"
    if near:
        user += f"KNOWN LOCATION (from a separate field, trust it): {near}\n"
    if url_info:
        user += (f"NOTE: input contains a Google Maps URL → mode MUST be \"single\". "
                 f"Parsed from URL: {json.dumps(url_info, ensure_ascii=False)}\n")
    try:
        plan = _generate_json(system, user)
        plan["mode"] = "single" if url_info else plan.get("mode", "discover")
        if url_info and url_info.get("name"):
            plan["target"] = url_info["name"]
        plan["near"] = plan.get("near") or near
        if plan.get("profile") not in profile_names:
            plan["profile"] = profiles.guess_profile(user_text)
        queries = [q for q in plan.get("queries") or [] if isinstance(q, str) and q.strip()]
        plan["queries"] = queries[:3] or [user_text]
        plan["report_lang"] = plan.get("report_lang") or "zh"
        plan["ai"] = True
        return plan
    except Exception as exc:  # noqa: BLE001 — planning must never block the pipeline
        log.warning("AI planning failed (%s) — falling back to raw query", exc)
        return _fallback_plan(user_text, near)


# -- relevance filter ------------------------------------------------------------

def filter_candidates(intent: str, relevance: str, places: list,
                      report_lang: str = "zh") -> list[dict]:
    """Judge each candidate against the intent. Returns verdicts in input order:
    [{place_id, name, relevant, reason}]. Fail-open on any error."""
    if not places:
        return []
    listing = "\n".join(
        f"{i}. id={p.place_id} | {p.name} | category: {p.category or '?'} | "
        f"★{p.rating or '?'} ({p.review_count or '?'} reviews) | {p.address or '?'}"
        for i, p in enumerate(places)
    )
    lang_rule = "中文" if report_lang == "zh" else report_lang
    system = f"""You judge Google Maps search results for relevance to a user's intent.
Be strict on CATEGORY (a motorbike rental is NOT relevant to a guitar rental query)
but lenient on details — a music shop that likely rents guitars IS relevant even if
the listing doesn't say "rental". When genuinely unsure, keep it (relevant=true).
Return STRICT JSON: {{"verdicts": [{{"index": <int>, "relevant": true|false,
"reason": "..."}}]}} — one verdict per candidate, same order.
Every "reason" MUST be written in {lang_rule} (≤12 words), regardless of the
language of the candidate listings."""
    user = f"USER INTENT: {intent}\nRELEVANCE TEST: {relevance}\n\nCANDIDATES:\n{listing}"
    try:
        raw = _generate_json(system, user)
        by_index = {v.get("index"): v for v in raw.get("verdicts", [])
                    if isinstance(v, dict)}
        return [
            {
                "place_id": p.place_id,
                "name": p.name,
                "relevant": bool(by_index.get(i, {}).get("relevant", True)),
                "reason": str(by_index.get(i, {}).get("reason", "")),
            }
            for i, p in enumerate(places)
        ]
    except Exception as exc:  # noqa: BLE001 — fail-open: never drop places on error
        log.warning("relevance filter failed (%s) — keeping all candidates", exc)
        return [{"place_id": p.place_id, "name": p.name, "relevant": True,
                 "reason": "(筛选不可用)"} for p in places]


# -- single-target resolution ----------------------------------------------------

_norm = cache.norm_name  # diacritic-insensitive: 'Hội An' matches 'hoi an'


def pick_target(target: str, places: list) -> object | None:
    """Match the user-named shop to one discovered candidate.
    Cheap fuzzy match first; LLM pick only when ambiguous."""
    if not places:
        return None
    wanted = _norm(target)
    if wanted:
        hits = [p for p in places if wanted in _norm(p.name) or _norm(p.name) in wanted]
        if len(hits) == 1:
            return hits[0]
        if hits:
            places = hits  # narrow the LLM's choice to the fuzzy matches
    if len(places) == 1:
        return places[0]
    listing = "\n".join(f"{i}. {p.name} | {p.address or '?'}" for i, p in enumerate(places))
    try:
        raw = _generate_json(
            'Pick the single candidate that IS the named business. Return STRICT JSON: '
            '{"index": <int>, "confident": true|false}',
            f"NAMED BUSINESS: {target}\n\nCANDIDATES:\n{listing}",
        )
        index = int(raw.get("index", 0))
        return places[index] if 0 <= index < len(places) else places[0]
    except Exception:  # noqa: BLE001
        return places[0]
