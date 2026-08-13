# placeintel API Contract

Last updated: 2026-08-11

This document is the agent-readable HTTP contract for the local FastAPI app. The
server is a single-user local/protected tool; examples use loopback URLs and do
not include private deploy hosts or credentials.

## Base URL

Local default:

```bash
http://127.0.0.1:9618
```

## Response Rules

- JSON responses must never include API keys.
- Scraped review text is untrusted data. UI and downstream tools must escape it
  before rendering HTML.
- Job events preserve the stage contract:

```json
{"t": 1781440000.0, "stage": "search", "msg": "human readable", "data": {}}
```

Allowed stages: `plan`, `search`, `filter`, `reviews`, `embed`, `report`, `done`.

## Health

### `GET /api/health`

Cheap local readiness check. This endpoint performs no model calls, scraper
starts, Docker probes, Chrome launches, or SerpAPI calls.

Example response:

```json
{
  "ok": true,
  "version": "0.4.x",
  "mode": "cheap",
  "checks": [
    {"name": "db", "ok": true, "severity": "critical", "latency_ms": 3, "message": "connected", "next_action": "none", "data": {}},
    {"name": "data_dir", "ok": true, "severity": "critical", "latency_ms": 1, "message": "writable", "next_action": "none", "data": {}},
    {"name": "static_web", "ok": true, "severity": "critical", "latency_ms": 1, "message": "static shell present and under line budget", "next_action": "none", "data": {"files": {"index.html": {"present": true, "lines": 189, "under_800": true}}}}
  ],
  "warnings": [],
  "errors": [],
  "providers": {
    "reason": {"model": "gemini-3-flash-preview", "provider": "VectorEngine"},
    "translate": {"model": "gemini-3.1-flash-lite", "provider": "VectorEngine"},
    "embed": {"model": "gemini-embedding-2-preview (768d)", "provider": "Google official"}
  }
}
```

Successful cheap health returns HTTP `200`. When a critical local check fails,
the same JSON contract returns HTTP `503` with `ok:false`, so an external
status-code monitor cannot false-green a broken database, data directory, or
static shell. Missing provider credentials are warnings for cheap health unless
a caller requires a provider through the CLI.

### `GET /api/health/monitor`

Minimal off-host readiness endpoint. It exists so an uptime provider never
needs the owner-facing Basic Auth credential. The reverse proxy may expose only
this exact path without owner auth; every request must still carry the dedicated
`X-PlaceIntel-Monitor` header whose value comes from
`PLACEINTEL_MONITOR_TOKEN`.

- Missing server token, missing header, or a wrong header returns HTTP `404`
  without running health checks.
- A valid header returns only `{"ok":true}` with HTTP `200`, or
  `{"ok":false}` with HTTP `503`.
- The response never includes versions, provider labels, paths, or check error
  details and is marked `Cache-Control: no-store`.
- The token authorizes no other route. Never reuse the broad proxy credential
  for this endpoint or store it with an uptime vendor.

### `GET /api/health/deep`

Opt-in live diagnostics. This endpoint may call provider/model endpoints, run
an embedding ping, inspect Docker, check local tool availability, and fetch a
small sample of stored photo URLs. Do not call it on every page load.

Additional deep check names:

- `reason_models`
- `reason_ping`
- `translation_ping`
- `embed_ping`
- `chrome`
- `docker`
- `gosom_image`
- `review_scraper`
- `serpapi`
- `photo_liveness`

Failed deep checks are warnings unless a caller explicitly requires them through
the CLI.

`photo_liveness` samples stored provider photo URLs and returns
`data: {"sampled": N, "alive": M}`. Provider photo URLs are time-limited
tokens, so a cached place can keep a well-formed URL long after the asset stops
resolving. It fails when **no** sampled URL resolves, and reports an empty
sample as inconclusive rather than as a pass — a zero-item check that returns
green is the failure mode this check exists to prevent.

Acting on it: a failure means the stored URLs expired, not that the app is
misconfigured. Re-acquire them with a re-scrape; a server-side image proxy does
not help, because the server receives the same rejection the browser does. Note
that `refresh-favorites --run` processes only places with `refresh_enabled`
set, so it exits successfully having done nothing when none are opted in.

## Owner-only routes

The proxy credential is shared with every guest, so it cannot tell the owner
from a friend. These three routes additionally require the header
`X-PlaceIntel-Owner`, compared in constant time against `PLACEINTEL_OWNER_TOKEN`:

- `DELETE /api/places/{place_id}` — destroys cached intel that cost real money
- `POST /api/settings` — switches the reasoning model for everyone
- `POST /api/settings/language` — changes app-wide language defaults

They answer `403` on a wrong or missing header, and **also `403` when the token
is unset**. That asymmetry is deliberate: the monitor endpoint is opt-in and
hides itself when unconfigured, but a destructive route must not fall open
because an environment variable is missing.

Everything else — scout, shop, ask, the translate routes, favorite, and all
reads — stays open to guests, because sharing is the point.

## Job budget

`POST /api/scout` and `POST /api/shop` spend the owner's provider budget on
every call. Both refuse with `429` once `PLACEINTEL_DAILY_JOB_LIMIT` billable
jobs have started in the rolling previous 24 hours (default 50; `0` disables the
cap). The count is read from the `jobs` table rather than a separate counter, so
it cannot drift from what actually ran and needs no reset job. A malformed limit
falls back to the default rather than silently removing the ceiling.

Authentication does not substitute for this: a guest who is legitimately let in
still spends the budget.

## Jobs

### `POST /api/scout`

Starts an AI-planned multi-place scout.

Request:

```json
{
  "query": "会安 吉他租赁",
  "near": "Hoi An",
  "profile": "rental",
  "top": 3,
  "max_reviews": 300,
  "report_lang": "vi",
  "language_hint": "vi-VN",
  "refresh": false,
  "no_ai": false
}
```

`report_lang` is optional. When omitted, output language resolves through:
explicit request > saved app default > browser `language_hint` > planner/input
language > English.

Response:

```json
{"job_id": "abc123def456"}
```

### `POST /api/shop`

Starts a single-place deep dive. `target` may be a plain name or Google Maps
URL. When refreshing or regenerating a dossier for an already cached place,
send `place_id` as well; the backend will use that exact cached place and skip
rediscovery, avoiding ambiguous-name drift.

Request:

```json
{
  "target": "D'Class Guitar",
  "place_id": "cached-place-id",
  "near": "Hoi An",
  "max_reviews": 300,
  "report_lang": "en",
  "language_hint": "en-US",
  "refresh": false
}
```

Response:

```json
{"job_id": "abc123def456"}
```

### `GET /api/jobs/{job_id}`

Current job state. Jobs are persisted in SQLite before the worker thread starts;
events are appended to `job_events`, and this endpoint reads the durable row.

Running:

```json
{"job_id": "abc123def456", "status": "running", "kind": "scout", "request": {}, "events": [{"id": 1, "t": 1781450000.0, "stage": "plan", "msg": "planning"}]}
```

Done:

```json
{"status": "done", "kind": "shop", "events": [], "result": {}}
```

`result` has the shared pipeline result shape used by the web job table and
`placeintel scout/shop --format json|ndjson`:

```json
{
  "query": "guitar lesson",
  "location": "Hoi An",
  "profile": "generic",
  "mode": "discover",
  "plan": {},
  "places": [],
  "filtered": [],
  "reports": [],
  "errors": [],
  "report_lang": "en",
  "language_source": "browser"
}
```

Error:

```json
{"status": "error", "kind": "scout", "events": [], "error": "message"}
```

Interrupted after process restart:

```json
{
  "status": "interrupted",
  "kind": "shop",
  "events": [],
  "error": "job interrupted by server restart",
  "retry_hint": "Retry the same Scout/Shop request; completed work will be reused from cache."
}
```

### `GET /api/jobs/{job_id}/events`

Resumable Server-Sent Events stream over the same durable `job_events` rows.
The browser uses this for live Scout/Shop progress and falls back to
`GET /api/jobs/{job_id}` polling if streaming is unavailable.

Resume controls:

- Query: `?after=12`
- Header: `Last-Event-ID: 12`

Event frame:

```text
id: 13
data: {"id":13,"t":1781450000.0,"stage":"reviews","msg":"抓取评价","data":{"count":80}}
```

Completed or interrupted jobs replay events after the cursor and then close the
stream. Running jobs keep the connection open until a terminal state or browser
fallback. The stream uses default EventSource `message` frames so browser
clients can consume it with `source.onmessage`.

## Ask and Evidence

### `POST /api/ask`

Ask a global or place-scoped question over cached listing and review evidence.

Request:

```json
{
  "question": "Which teacher is most patient?",
  "place_id": null,
  "report_lang": null,
  "language_hint": "en-US",
  "fresh": false
}
```

Response:

```json
{
  "answer": "押金通常需要现场确认，停车入口也要提前问清。",
  "cached": false,
  "created_at": 1781459000.0,
  "model": "gemini-3-flash-preview",
  "provider": "VectorEngine",
  "report_lang": "en",
  "language_source": "browser",
  "cache_scope": {"kind": "place", "place_id": "place-1", "label": "D'Class Guitar"},
  "evidence_fresh_after": 1781451000.0,
  "evidence": [
    {"type": "listing", "place_id": "place-1", "place_name": "D'Class Guitar", "label": "address", "value": "49/9 Nguyen Tat Thanh"},
    {"type": "review", "place_id": "place-1", "place_name": "D'Class Guitar", "review_id": "r1", "rating": 2, "date": "2026-06-01", "source_lang": "ko", "text": "Parking was difficult.", "score": 0.82}
  ]
}
```

`evidence[]` is split by `type`:

- `listing`: authoritative Google Maps metadata such as address, phone, hours,
  website, rating, review count, and Maps link.
- `review`: retrieved original review snippets with place name, rating/date
  when available, source language, and vector score.

Cached responses may return `evidence: []` because the saved QA row stores the
answer, not a frozen copy of prior evidence. The `cache_scope`,
`report_lang`, and `evidence_fresh_after` fields explain why reuse is safe:
cache lookup is exact-scope, exact-language, and cached answers are valid only
while no newer reviews exist in that same scope.

### `GET /api/qa`

Recent global Q&A by default.

Variants:

- `GET /api/qa?place_id=<place_id>`: exact place-scoped history.
- `GET /api/qa?scope=all`: display-only mixed history with `place_name` where
  available. This must not relax exact-scope cache reuse.

History rows include `answer_lang` when known; clicking a history chip should
re-ask with the original scope and current language preference instead of
assuming all cached answers are interchangeable.

## Places and Reports

### `GET /api/places`

Returns cached place cards with activity risk, cache counts, favorite metadata,
latest report summary fields, and at most one source thumbnail per place.

Report/list fields:

- `cached_reviews`: number of locally cached review rows for the place.
- `report_count`: number of saved reports for the place.
- `latest_report_at`: unix timestamp for the newest saved report, or null.
- `latest_report_profile`: profile name for the newest saved report, or null.
- `latest_report_lang`: language tag for the newest saved report, or null.
- `thumbnail`: a bounded photo metadata object, or null. The list endpoint
  exposes at most one thumbnail per place and never includes image bytes.

Favorite fields:

- `favorite`: boolean; true only after the user/agent marks the cached place.
- `refresh_enabled`: boolean; false by default. Only true favorites are refresh
  candidates.
- `refresh_interval_days`: integer or null; default favorite interval is 14.
- `max_reviews`: integer or null; per-refresh cap, clamped by the CLI guardrail.
- `last_refresh_at`: unix timestamp or null.

Photo metadata fields:

- `url`: HTTP(S) source URL used when the user opens the photo.
- `thumb_url`: HTTP(S) image URL used for the thumbnail; falls back to `url`.
- `source`: source label such as `scraper-pro`, `serpapi`, or `gosom`.
- `kind`: `review` or `place`.
- `place_id`: owning cached place ID.
- `review_id`, `author`, `rating`, `date`, `attribution`: optional source
  context when the photo came from a review or provider metadata.

### `GET /api/places/{place_id}`

Returns one dossier payload:

```json
{
  "place": {
    "place_id": "id",
    "name": "name",
    "activity_risk": null,
    "favorite": false,
    "refresh_enabled": false
  },
  "photos": [
    {
      "url": "https://example.com/source.jpg",
      "thumb_url": "https://example.com/source.jpg",
      "source": "scraper-pro",
      "kind": "review",
      "place_id": "id",
      "review_id": "review-id",
      "author": "review author",
      "rating": 5,
      "date": "2026-06-01",
      "attribution": "review author"
    }
  ],
  "reviews": [],
  "report": {
    "id": 42,
    "md": "...",
    "json": {},
    "profile": "generic",
    "model": "model",
    "report_lang": "en",
    "evidence_lang": "report",
    "created_at": 1781440000.0
  }
}
```

`photos[]` is opportunistic source metadata derived by the backend photo
resolver from existing review image URLs and provider thumbnail fields. It is
bounded, deduped, HTTP(S)-only, and contains no raw provider JSON, keys,
cookies, local paths, or binary image data. Raw review text remains original
scraped text.

### `POST /api/places/{place_id}/favorite`

Marks or unmarks one cached place as a favorite. Unknown `place_id` returns
`404`.

Request:

```json
{
  "favorite": true,
  "refresh_enabled": false,
  "refresh_interval_days": 14,
  "max_reviews": 300
}
```

All fields except `favorite` are optional. Refresh is opt-in and remains disabled
unless `refresh_enabled:true` is sent.

Response:

```json
{
  "place_id": "id",
  "favorite": true,
  "refresh_enabled": false,
  "refresh_interval_days": 14,
  "max_reviews": 300,
  "last_refresh_at": null,
  "updated_at": 1781454000.0
}
```

### `DELETE /api/places/{place_id}`

Deletes a cached place. UI should confirm destructive actions. Future CLI
destructive commands require `--yes`.

### `GET /api/searches`

Recent searches, including filtered verdicts for display.

### `GET /api/reports`

Recent reports. Rows include `report_lang` and `evidence_lang`.

### `GET /api/reports/{report_id}`

One report body and structured JSON, including `report_lang` and
`evidence_lang`.

### `POST /api/reports/translate`

Display-layer report translation only. It must never overwrite
`reports.report_md` or regenerate the report.

Request:

```json
{"report_id": 42, "target_lang": "zh"}
```

Response:

```json
{
  "report_id": 42,
  "target_lang": "zh",
  "source_lang": "en",
  "md": "# translated markdown",
  "cached": false,
  "model": "gemini-3.1-flash-lite",
  "provider": "VectorEngine",
  "created_at": 1781440000.0
}
```

`target_lang` is optional in the web UI path; when omitted, the server uses the
saved translation target. Cache reuse is allowed only when the requested
`report_id`, normalized target language, and current source-markdown hash all
match the saved row.

## Profiles, Models, and Settings

### `GET /api/profiles`

Returns profile names.

### `GET /api/meta`

Returns app version plus non-secret provider/model labels.

### `GET /api/config`

Returns non-secret runtime settings for the owner System panel and agent status
checks. The endpoint intentionally hides local data paths and never returns API
keys, tokens, private hosts, or deploy values.

Example response:

```json
{
  "version": "0.4.54",
  "settings": {
    "reason_model": "gemini-3-flash-preview",
    "translation_model": "gemini-3.1-flash-lite",
    "ui_language": "auto",
    "default_answer_language": "auto",
    "default_report_language": "auto",
    "translation_target": "auto",
    "evidence_language": "report",
    "cache_ttl_days": 14
  },
  "language": {
    "ui_language": "en",
    "answer_language": "en",
    "report_language": "en",
    "translation_target": "en",
    "evidence_language": "report",
    "source": "default",
    "fallback_language": "en",
    "supported_ui_locales": ["en", "zh"],
    "common_languages": {"en": "English", "zh": "Simplified Chinese"},
    "app_defaults": {
      "ui_language": "auto",
      "answer_language": "auto",
      "report_language": "auto",
      "translation_target": "auto"
    }
  },
  "runtime": {
    "port": 9618,
    "data_dir": {"configured": true, "path_visible": false}
  },
  "providers": {
    "reason": {"model": "gemini-3-flash-preview", "provider": "VectorEngine"},
    "translate": {"model": "gemini-3.1-flash-lite", "provider": "VectorEngine"},
    "embed": {"model": "gemini-embedding-2-preview (768d)", "provider": "Google official"}
  },
  "feature_status": {
    "reasoning": {"available": true, "provider": "VectorEngine", "model": "gemini-3-flash-preview", "next_action": "none"},
    "translation": {"available": true, "provider": "VectorEngine", "model": "gemini-3.1-flash-lite", "next_action": "none"},
    "embedding": {"available": true, "provider": "Google official", "model": "gemini-embedding-2-preview (768d)", "next_action": "none"}
  },
  "spend_policy": {
    "provider": "serpapi",
    "allowed": false,
    "source": "env",
    "key_configured": true,
    "env_var": "PLACEINTEL_ALLOW_SERPAPI",
    "setting_key": "allow_serpapi"
  },
  "health": {"cheap_url": "/api/health", "deep_url": "/api/health/deep"},
  "danger_zone": {
    "destructive_changes": false,
    "message": "Destructive cache/restore actions stay in the CLI and require explicit confirmation."
  }
}
```

`feature_status.*.available` is feature-specific: missing reasoning credentials
must not block read-only Library access, and missing embedding credentials must
not hide already-cached dossier evidence.

`spend_policy` reports whether a failed free scrape may fall back to the
billable SerpAPI engine, and which layer decided (`run`, `env`, `settings`, or
the fail-closed `default`). It is **read-only over HTTP**: no request field sets
it, because the proxy credential is shared with guests and anything a request
could set, a guest could spend. Change it with the deploy environment variable
or `placeintel spend --allow|--block` on the host. When `allowed` is false, a
scout or shop whose free path fails finishes with the job error
`paid_path_blocked` and nothing is charged.

### `POST /api/settings/language`

Validates and optionally persists non-secret language defaults. With
`make_default:false`, the endpoint returns the resolved language contract without
writing settings; the browser can still keep local-only preferences in
localStorage.

Request:

```json
{
  "ui_language": "en",
  "default_answer_language": "fr-FR",
  "default_report_language": "fr-FR",
  "translation_target": "fr-FR",
  "evidence_language": "report",
  "make_default": true
}
```

Response:

```json
{"ok": true, "saved": {"default_answer_language": "fr-FR"}, "language": {}}
```

`ui_language` may be `auto`, `en`, or `zh` in the first locale-pack release.
Ask/report/translation targets accept safe BCP-47-like tags such as `vi`,
`fr-FR`, or `pt-BR`. Blank, path-like, script-like, overlong, or control-character
values are rejected.

### `GET /api/models`

Live reasoning-model list from the configured provider. Provider failure returns
the current model with `models: []` and an `error` string.

### `POST /api/settings`

Smoke-tests and saves a new reasoning model.

Request:

```json
{"reason_model": "gemini-3-flash-preview"}
```

Response:

```json
{"ok": true, "reason": {}, "translate": {}, "embed": {}}
```

## Saved Places (CLI-only)

The first saved-place production slice is deliberately CLI-only. No HTTP upload
endpoint accepts private Takeout data.

### `placeintel saved-import PATH --format json`

`PATH` may be an official Saved CSV, a Takeout directory, or a ZIP. The command
reads locally, never extracts ZIP contents, never mutates Google Maps, and emits
only hashes and counts rather than source titles, URLs, notes, or comments.

```json
{
  "ok": true,
  "version": "0.4.x",
  "command": "saved-import",
  "data": {
    "run_id": "opaque-run-id",
    "source_digest": "sha256",
    "files": 3,
    "rows": 4,
    "skipped": 0,
    "created": {"collections": 3, "items": 3, "memberships": 4},
    "updated": {"collections": 0, "items": 0, "memberships": 0}
  }
}
```

An identical second import creates zero new logical records. It writes a new
completed run receipt and updates the distinct collection/item/membership
`last_seen_at` timestamps.

`skipped` is the count of identity-less Google export placeholders (blank or
tag-only rows) that cannot be connected to a place. The count is stored in the
local run receipt. A row with other orphaned content that could indicate a
source problem still fails safely instead of being silently discarded.

Invalid, empty, unsafe, truncated, or over-limit input exits `1` with the normal
error object. Stable codes begin with `saved_import_`; messages and next actions
never echo the private source path or row values. A failed attempt preserves no
partial corpus writes but does retain one local `failed` run receipt with its
safe error code so operators can audit and retry it.

### `placeintel saved-inventory --format json`

```json
{
  "ok": true,
  "version": "0.4.x",
  "command": "saved-inventory",
  "data": {
    "totals": {"collections": 3, "items": 3, "memberships": 4},
    "states": {"pending": 3},
    "collections": [
      {"name": "Date Places", "source_product": "saved", "memberships": 2}
    ],
    "filters": {"collection": null, "state": null, "limit": 100},
    "matched_items": 3,
    "items": [
      {
        "saved_item_id": "opaque-stable-id",
        "title": "Lantern Café",
        "address": null,
        "lat": null,
        "lng": null,
        "state": "pending",
        "collections": ["Date Places", "Favorites"]
      }
    ]
  }
}
```

Use `--collection NAME`, `--state STATE`, and `--limit 1..1000` for bounded
review. The inventory contains user-readable titles and collection names but
never membership notes, comments, source paths, or URLs.

## Backup and Restore

Backup and restore are CLI-only operations, not HTTP endpoints. Use
`placeintel backup --format json` and
`placeintel restore <manifest-or-dir> --yes --format json`; see
`docs/agent-cli.md` and `docs/operations.md` for the machine contract and
runbook. This keeps destructive restore actions out of the unauthenticated local
web surface.

## Review Translation

### `POST /api/reviews/translate`

Display-layer translation only. It must never overwrite `reviews.text`.

Request:

```json
{"review_id": "review-1", "target_lang": "fr-FR"}
```

Response:

```json
{
  "review_id": "review-1",
  "target_lang": "fr-FR",
  "source_lang": "vi",
  "text": "translated display text",
  "cached": false,
  "model": "gemini-3.1-flash-lite",
  "provider": "VectorEngine",
  "created_at": 1781440000.0
}
```

`target_lang` is optional in the web UI path; when omitted, the server uses the
saved review translation target, then the active answer language, then English.
The endpoint accepts safe BCP-47-like tags beyond `zh/en` and rejects blank,
path-like, script-like, overlong, or control-character values before any model
call.
