# placeintel API Contract

Last updated: 2026-06-15

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

`ok` is false when a critical local check fails. Missing provider credentials are
warnings for cheap health unless a caller requires a provider through the CLI.

### `GET /api/health/deep`

Opt-in live diagnostics. This endpoint may call provider/model endpoints, run
an embedding ping, inspect Docker, and check local tool availability. Do not call
it on every page load.

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

Failed deep checks are warnings unless a caller explicitly requires them through
the CLI.

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
  "report_lang": "zh",
  "refresh": false,
  "no_ai": false
}
```

Response:

```json
{"job_id": "abc123def456"}
```

### `POST /api/shop`

Starts a single-place deep dive. `target` may be a plain name or Google Maps URL.

Request:

```json
{"target": "D'Class Guitar", "near": "Hoi An", "max_reviews": 300, "refresh": false}
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
  "errors": []
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
{"question": "哪家有耐心的老师?", "place_id": null, "report_lang": "zh", "fresh": false}
```

Response:

```json
{
  "answer": "押金通常需要现场确认，停车入口也要提前问清。",
  "cached": false,
  "created_at": 1781459000.0,
  "model": "gemini-3-flash-preview",
  "provider": "VectorEngine",
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
answer, not a frozen copy of prior evidence. The `cache_scope` and
`evidence_fresh_after` fields explain why reuse is safe: cache lookup is still
exact-scope, and cached answers are valid only while no newer reviews exist in
that same scope.

### `GET /api/qa`

Recent global Q&A by default.

Variants:

- `GET /api/qa?place_id=<place_id>`: exact place-scoped history.
- `GET /api/qa?scope=all`: display-only mixed history with `place_name` where
  available. This must not relax exact-scope cache reuse.

## Places and Reports

### `GET /api/places`

Returns cached place cards with activity risk, cache counts, favorite metadata,
latest report summary fields, and at most one source thumbnail per place.

Report/list fields:

- `cached_reviews`: number of locally cached review rows for the place.
- `report_count`: number of saved reports for the place.
- `latest_report_at`: unix timestamp for the newest saved report, or null.
- `latest_report_profile`: profile name for the newest saved report, or null.
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
  "report": {"md": "...", "json": {}, "profile": "generic", "model": "model", "created_at": 1781440000.0}
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

Recent reports.

### `GET /api/reports/{report_id}`

One report body and structured JSON.

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
  "version": "0.4.33",
  "settings": {
    "reason_model": "gemini-3-flash-preview",
    "translation_model": "gemini-3.1-flash-lite",
    "default_answer_language": "zh",
    "evidence_language": "report",
    "cache_ttl_days": 14
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
{"review_id": "review-1", "target_lang": "zh"}
```

Response:

```json
{
  "review_id": "review-1",
  "target_lang": "zh",
  "source_lang": "vi",
  "text": "translated display text",
  "cached": false,
  "model": "gemini-3.1-flash-lite",
  "provider": "VectorEngine",
  "created_at": 1781440000.0
}
```
