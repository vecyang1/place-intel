"""Gemini long-context reasoning over a place's full review history.

Small review sets (≤MAX_REVIEWS_IN_PROMPT): one call, ALL reviews in the prompt.
Large sets: map-reduce — every cached review is mined chunk-by-chunk into dense
evidence digests, then one reduce pass writes the report from ALL digests plus the
raw low-star reviews. Nothing scraped is left unread. Embeddings are NOT used here —
they serve cross-place search in ask/search flows.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Callable

from google import genai
from google.genai import types

from . import cache, config

log = logging.getLogger(__name__)

MAX_REVIEWS_IN_PROMPT = int(os.getenv("PLACEINTEL_MAX_REVIEWS_PROMPT", "400"))
MAP_CHUNK = int(os.getenv("PLACEINTEL_MAP_CHUNK", "200"))
DIGEST_WORKERS = 3
NEWEST_RAW_IN_REDUCE = 30
MAX_REVIEW_CHARS = 800
LOW_STAR_THRESHOLD = 2  # low-star reviews are always included — red-flag fuel


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    """Reasoning client — VectorEngine preferred (cheaper for generate_content)."""
    api_key, http_options = config.reason_credentials()
    return genai.Client(api_key=api_key, http_options=http_options)


def _evidence_rule(report_lang: str, evidence_lang: str) -> str:
    lang_name = "Chinese (中文)" if report_lang == "zh" else report_lang
    if evidence_lang == "original":
        return (f"Write all analysis in {lang_name}, but keep quoted review evidence "
                "in its original language.")
    return (f"Write all analysis in {lang_name}. TRANSLATE every quoted review "
            f"excerpt into {lang_name} as well; when the original language differs, "
            "tag it inside the quote's bracket header, e.g. "
            "[2026-05-21|★5.0|原文:韩语] <translated quote>. Never leave untranslated "
            "quotes in the output.")


def _format_review(r: sqlite3.Row) -> str:
    text = (r["text"] or "").strip()[:MAX_REVIEW_CHARS]
    parts = [f"[{r['review_date'] or '?'} | ★{r['rating'] or '?'} | {r['author'] or 'anon'}]", text]
    if r["owner_response"]:
        parts.append(f"|| OWNER REPLY: {r['owner_response'][:300]}")
    return " ".join(parts)


def _build_prompt(place: sqlite3.Row, body: str, coverage: str, profile: dict,
                  report_lang: str, evidence_lang: str) -> tuple[str, str]:
    dims = "\n".join(
        f"- KEY `{key}` — {d.get('title', key)}: {d.get('goal', '').strip()}"
        for key, d in profile["dimensions"].items()
    )
    extras = "\n".join(f"- `{k}`: {v.strip()}" for k, v in profile["output_extras"].items())
    lang_rule = _evidence_rule(report_lang, evidence_lang)
    today = time.strftime("%Y-%m-%d")
    system = f"""You are a ruthless local-intelligence analyst. Today is {today} —
judge review recency against THIS date, not your training cutoff. A traveler is about
to walk into this place and must not be the unprepared one. Mine the evidence below for
the requested dimensions. Rules:
- Evidence or it didn't happen: every finding cites 1-3 short review quotes with date+rating.
- Prices: always note the review date next to any amount (prices drift).
- Weigh recent reviews heavier; call out when old and new reviews disagree.
- Detect fake-review patterns (bursts of thin same-day 5★) and say so.
- {lang_rule}

ANALYSIS DIMENSIONS:
{dims}

Return STRICT JSON (no markdown fences) with this exact shape:
{{
  "place_summary": "2-3 sentences",
  "dimensions": {{"<dimension KEY>": {{"title": "...", "findings": [
      {{"finding": "...", "evidence": ["[date|★n] quote", ...], "confidence": "high|medium|low"}}
  ]}}}},
  "negotiation_baseline": "expected fair price range + the walk-away number, with reasoning",
  "walk_in_brief": ["5 lines, see spec below"],
  "verdict": "one sentence: go / go-with-caution / skip + why"
}}
walk_in_brief / verdict spec:
{extras}"""

    hours = place["hours_json"] or "unknown"
    listing = (
        f"PLACE LISTING\nname: {place['name']}\ncategory: {place['category']}\n"
        f"address: {place['address']}\nlisted rating: {place['rating']} "
        f"({place['review_count']} reviews)\nphone: {place['phone']}\n"
        f"website: {place['website']}\nlisted hours: {hours}\n"
        f"price level: {place['price_level']}\n"
    )
    user = f"{listing}\nREVIEW EVIDENCE ({coverage}):\n{body}"
    return system, user


def _digest_chunk(place_name: str, chunk: list[sqlite3.Row], idx: int, total: int,
                  report_lang: str, evidence_lang: str) -> str:
    """Map pass: mine one chunk of reviews into a dense, citable evidence digest."""
    body = "\n".join(_format_review(r) for r in chunk)
    system = (
        f"You are an evidence miner reading customer reviews of \"{place_name}\" "
        f"(chunk {idx}/{total}). Extract EVERY concrete, decision-relevant fact: "
        "prices/fees/durations with dates, schedules, booking methods, named staff, "
        "languages spoken, complaints, contradictions between reviews, fake-review "
        "signals (same-day bursts, thin 5★), service quirks, safety issues. "
        "One bullet per fact: the fact, then its supporting quote with [date|★rating] "
        f"header. {_evidence_rule(report_lang, evidence_lang)} "
        "Dense bullets only — no conclusions, no fluff, no headers."
    )
    response = _client().models.generate_content(
        model=config.reason_model(),
        contents=body,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.1),
    )
    return response.text or ""


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def render_markdown(report: dict, place: sqlite3.Row, profile_name: str,
                    review_count: int) -> str:
    lines = [
        f"# {place['name']} — Intel Report",
        f"> {place['address'] or ''} · ★{place['rating']} ({place['review_count']} listed reviews, "
        f"{review_count} analyzed) · profile: {profile_name}",
        "",
        f"**Verdict:** {report.get('verdict', '?')}",
        "",
        "## 🚪 Walk-in Brief（进门前 30 秒）",
    ]
    lines += [f"{i + 1}. {line}" for i, line in enumerate(report.get("walk_in_brief", []))]
    lines += ["", f"**谈价基准:** {report.get('negotiation_baseline', '?')}", "",
              f"_{report.get('place_summary', '')}_", ""]
    for dim in report.get("dimensions", {}).values():
        lines.append(f"## {dim.get('title', '?')}")
        for f in dim.get("findings", []):
            lines.append(f"- **{f.get('finding', '')}** ({f.get('confidence', '?')})")
            lines += [f"  - {ev}" for ev in f.get("evidence", [])]
        lines.append("")
    return "\n".join(lines)


def analyze_place(conn: sqlite3.Connection, place_id: str, profile: dict,
                  report_lang: str = "zh", model: str | None = None,
                  evidence_lang: str | None = None,
                  on_progress: Callable[[str], None] | None = None) -> tuple[dict, str]:
    """Run the reasoning pass for one place; saves and returns (report_json, markdown).

    ≤MAX_REVIEWS_IN_PROMPT cached reviews → single pass over ALL of them.
    More → map-reduce: every chunk mined into a digest (nothing skipped), reduce
    pass writes the report from all digests + raw low-star + newest raw reviews."""
    evidence_lang = evidence_lang or config.EVIDENCE_LANG
    progress = on_progress or (lambda msg: None)
    place = cache.get_place(conn, place_id)
    if not place:
        raise ValueError(f"place {place_id} not in cache")
    reviews = cache.get_reviews(conn, place_id)
    if not reviews:
        raise ValueError(f"no cached reviews for {place['name']} ({place_id})")

    if len(reviews) <= MAX_REVIEWS_IN_PROMPT:
        body = "\n".join(_format_review(r) for r in reviews)
        coverage = (f"ALL {len(reviews)} cached reviews, single pass; "
                    f"{place['review_count'] or '?'} listed on Google")
    else:
        chunks = [reviews[i:i + MAP_CHUNK] for i in range(0, len(reviews), MAP_CHUNK)]
        progress(f"评价较多（{len(reviews)} 条），分 {len(chunks)} 块全量深读，一条不漏…")
        _client()  # pre-warm before fanning out threads
        with ThreadPoolExecutor(max_workers=DIGEST_WORKERS) as pool:
            digests = list(pool.map(
                lambda item: _digest_chunk(place["name"], item[1], item[0] + 1,
                                           len(chunks), report_lang, evidence_lang),
                enumerate(chunks),
            ))
        progress(f"{len(chunks)} 块证据挖掘完成，正在综合成报告…")
        low_star = [r for r in reviews if (r["rating"] or 5) <= LOW_STAR_THRESHOLD]
        parts = ["MINED EVIDENCE DIGESTS (every cached review was read, in chunks):"]
        parts += [f"--- chunk {i + 1}/{len(chunks)} ---\n{d}" for i, d in enumerate(digests)]
        if low_star:
            parts.append("RAW LOW-STAR REVIEWS (full text — red-flag fuel):\n"
                         + "\n".join(_format_review(r) for r in low_star))
        parts.append(f"RAW NEWEST {NEWEST_RAW_IN_REDUCE} REVIEWS (recency texture):\n"
                     + "\n".join(_format_review(r) for r in reviews[:NEWEST_RAW_IN_REDUCE]))
        body = "\n\n".join(parts)
        coverage = (f"ALL {len(reviews)} cached reviews mined via {len(chunks)} "
                    f"map-reduce digests; {place['review_count'] or '?'} listed on Google")

    system, user = _build_prompt(place, body, coverage, profile, report_lang, evidence_lang)
    model = model or config.reason_model()
    log.info("analyzing %s: %d reviews → %s", place["name"], len(reviews), model)

    response = _client().models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
    )
    report = _parse_json(response.text)
    md = render_markdown(report, place, profile["name"], len(reviews))
    cache.save_report(conn, place_id, profile["name"], model, report, md, len(reviews))
    return report, md
