# PRD: placeintel Agent-Friendly CLI and API

Status: 🔨 In Progress — US-CLI stories implemented; global-option hardening remains
Last Updated: 2026-06-14
Parent PRD: `tasks/prd-placeintel-production-grade-master.md`
Scope: CLI contracts, HTTP contracts, machine-readable output, agent handoff docs, and command ergonomics.

## 1. Overview

`placeintel` already has a useful CLI (`scout`, `shop`, `plan`, `history`, `ask`, `report`, `list`, `profiles`, `model`, `export`) and a FastAPI web API. The missing production layer is a stable agent interface.

Other agents should be able to:

- diagnose environment readiness.
- run Scout or Shop jobs and stream events.
- ask cached evidence questions.
- inspect places, reports, reviews, models, and health.
- export evidence for another workflow.
- recover from failures using exit codes and JSON errors.

They should not need a browser, DOM parsing, local code knowledge, or private chat memory.

## 2. Goals

- G1: Every agent-facing command has machine-readable output.
- G2: Long-running operations can stream the existing job-event contract as NDJSON.
- G3: CLI stdout is parseable when `--format json|ndjson` is selected; human logs go to stderr.
- G4: Exit codes are stable and documented.
- G5: HTTP API schemas and CLI examples are documented in files future agents will read.
- G6: CLI can run doctor/status checks without starting the web UI.
- G7: Agent interface preserves all product safety contracts: fail-open planning, exact QA scope, original reviews, provider routing, and cache-first economics.

## 3. User Stories

### US-CLI-001: Doctor for Agents

As another agent, I want `placeintel doctor --json` so I can tell what is configured before running costly work.

Acceptance Criteria:
- [x] `placeintel doctor --json` exits 0 when local DB/data dirs and import paths are healthy.
- [x] `placeintel doctor --live --json` performs safe live checks: model list or tiny reasoning ping, optional embedding ping, Chrome/Docker/scraper availability.
- [x] Output includes `ok`, `checks[]`, `warnings[]`, `errors[]`, `version`, and provider roles without keys.
- [x] `--require google,vectorengine,chrome,docker` exits non-zero if required checks fail.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed by `placeintel/doctor.py`; cheap
doctor remains local-only, while `--live` runs model/provider pings and local
external-wheel checks. Required checks are enforced by name.

### US-CLI-002: Machine-Readable Scout and Shop

As another agent, I want to run Scout/Shop and watch structured events so I can update task state without parsing prose.

Acceptance Criteria:
- [x] `placeintel scout "query" --format ndjson` prints one JSON event per line.
- [x] Final line includes `type:"result"` with the same core fields as the web job result.
- [x] Human progress text moves to stderr or is suppressed.
- [x] `--format json` prints only final result JSON after completion.
- [x] Text mode remains backwards compatible.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with machine output adapters in
`placeintel/cli.py`. `scout` and `shop` now support `--format json|ndjson`;
NDJSON event lines include `type:"event"` plus the existing `{t, stage, msg,
data?}` contract, and the final line includes `type:"result"` with the shared
pipeline result object. Coverage lives in `tests/test_cli_json_contract.py`.

### US-CLI-003: Stable Read Commands

As another agent, I want read commands to output JSON so I can compose workflows.

Acceptance Criteria:
- [x] `placeintel list --format json` returns cached places.
- [x] `placeintel history --format json` returns searches with verdicts and places.
- [x] `placeintel report <place_id> --format json` returns report metadata/body without markdown-only output.
- [x] `placeintel export <place_id> --format json` remains JSON and follows documented schema.
- [x] `placeintel profiles --format json` returns profile names and dimensions.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with JSON envelopes in
`placeintel/cli.py` and coverage in `tests/test_cli_json_contract.py`. Text-mode
defaults remain for backwards compatibility; `export --format json` uses the new
agent envelope while legacy `export` remains raw JSON.

### US-CLI-004: Ask as an Agent Tool

As another agent, I want Ask to return answer plus evidence metadata so I can cite or inspect the answer.

Acceptance Criteria:
- [x] `placeintel ask "question" --format json` returns `answer`, `cached`, `created_at`, `model`, `provider`, `matched?`, `place_id?`.
- [x] If evidence cards are implemented in backend, JSON includes `evidence[]` with type `listing|review`.
- [x] `--place` preserves exact scope.
- [x] `--fresh` bypasses cache.
- [x] Empty cache exits with documented code and JSON message, not a stack trace.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with `ask --format json` in
`placeintel/cli.py`; scoped JSON echoes `place_id`, `--fresh` maps to
`no_cache=True`, and empty cache returns exit code 5 with `cache_empty`. The
`evidence[]` criterion is satisfied as not-applicable until the backend exposes
evidence cards; once backend evidence exists, the CLI must pass it through.

### US-CLI-005: Schemas and Examples

As an implementation agent, I want schemas and examples checked into the repo so I can call the tool correctly in future sessions.

Acceptance Criteria:
- [x] `docs/API.md` documents HTTP endpoints and response shapes.
- [x] `docs/agent-cli.md` documents CLI commands, formats, exit codes, and examples.
- [x] `placeintel schema --format json` prints schemas for core payloads or points to versioned schema files.
- [x] README links to both docs.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with `placeintel schema --format json`,
core schema entries for `cli_envelope`, `health`, `pipeline_result`, and
`job_event`, and docs links from README. Verified by
`tests/test_cli_json_contract.py` plus full local verification.

## 4. Functional Requirements

### 4.1 Global CLI Options

- FR-CLI-001: Add global `--format text|json|ndjson`; default remains `text`.
- FR-CLI-002: Add global `--quiet` to suppress non-essential stderr logs.
- FR-CLI-003: Add global `--no-color` even if current text output does not use color; this prevents future ambiguity.
- FR-CLI-004: Add global `--timeout SECONDS` for long-running commands.
- FR-CLI-005: Add `--yes` for destructive commands; if absent, destructive CLI actions must prompt in TTY and fail non-interactively.

### 4.2 Output Contract

- FR-CLI-006: JSON stdout must contain exactly one JSON document.
- FR-CLI-007: NDJSON stdout must contain one JSON object per line.
- FR-CLI-008: Human logs must go to stderr for JSON/NDJSON.
- FR-CLI-009: Every JSON error must include:
  - `ok: false`
  - `error.code`
  - `error.message`
  - `error.recoverable`
  - `error.next_action`
- FR-CLI-010: Every success JSON must include:
  - `ok: true`
  - `version`
  - `command`
  - `data`

### 4.3 Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | User/input error |
| 2 | Missing configuration or credentials |
| 3 | External provider/scraper unavailable |
| 4 | Partial completion with warnings |
| 5 | Cache empty/no matching data |
| 6 | Timeout/cancelled |
| 10 | Internal unexpected error |

### 4.4 Command Set

Existing commands must remain:
- `scout`
- `shop`
- `plan`
- `history`
- `ask`
- `report`
- `list`
- `profiles`
- `model`
- `export`

New or expanded commands:

| Command | Purpose | Required Formats |
| --- | --- | --- |
| `doctor` | local/live readiness checks | text, json |
| `status` | app/db/provider summary | text, json |
| `schema` | print CLI/API schema refs | text, json |
| `jobs` or `job` | list/status/watch durable jobs once ops PRD is implemented | text, json, ndjson watch |
| `config` | get/set/test non-secret settings | text, json |
| `backup` | create/verify local DB backup | text, json |
| `restore` | restore with confirmation | text, json |

### 4.5 NDJSON Event Types

Long-running commands must emit:

```json
{"type":"event","t":1781440000.0,"stage":"search","msg":"...","data":{}}
{"type":"warning","t":1781440001.0,"code":"scraper_fallback","message":"..."}
{"type":"result","t":1781440030.0,"ok":true,"data":{}}
```

Rules:
- `type` is required.
- Existing event stage enum is preserved.
- Final result object is required for successful NDJSON commands.
- Errors use `type:"error"` and exit non-zero.

### 4.6 HTTP API Requirements

The following endpoints are current and must be documented:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/scout` | POST | Start Scout job |
| `/api/shop` | POST | Start Shop job |
| `/api/jobs/{job_id}` | GET | Poll job state |
| `/api/ask` | POST | Ask cache/global or scoped question |
| `/api/reviews/translate` | POST | Display-layer review translation |
| `/api/qa` | GET | QA history exact/all display |
| `/api/places` | GET | Cached places |
| `/api/places/{place_id}` | GET | Place dossier data |
| `/api/places/{place_id}` | DELETE | Delete cached place |
| `/api/searches` | GET | Past searches |
| `/api/reports` | GET | Report list |
| `/api/reports/{report_id}` | GET | Report detail |
| `/api/profiles` | GET | Profiles |
| `/api/meta` | GET | Version/provider/model info |
| `/api/models` | GET | Live reason-model list |
| `/api/settings` | POST | Smoke-test and persist reasoning model |

New endpoints required by this PRD suite:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/health` | GET | cheap health |
| `/api/health/deep` | GET/POST | live readiness checks |
| `/api/jobs/{job_id}/events` | GET | SSE or NDJSON stream |
| `/api/config` | GET | non-secret runtime config/status |
| `/api/config/{key}` | PUT | update allowed non-secret config |
| `/api/config/test/{key}` | POST | validate config before save |

## 5. Non-Goals

- Do not create an MCP server in this PRD. The CLI/API should be strong enough that an MCP wrapper can be built later.
- Do not require the web server for read-only CLI commands.
- Do not expose secrets through config/status commands.
- Do not break existing human text output.
- Do not make destructive commands non-interactive without `--yes`.

## 6. Stack and Dependencies

### 6.1 Decision

Use existing `argparse` for the first agent interface pass.

Rationale:
- Existing CLI is small and already uses `argparse`.
- Agent-friendliness is mostly output and schema discipline, not parser framework.
- Typer is excellent and current, but migration would add risk before contracts are defined.

### 6.2 Revisit Typer When

Reconsider Typer only if:
- commands exceed maintainable `argparse` structure.
- docs/help generation becomes a bottleneck.
- type-hinted command models would reduce duplication.

If switching, it must be a separate refactor with compatibility tests for existing commands.

## 7. Safety and Security

### 7.1 Zero-Regression

| Feature | Verification |
| --- | --- |
| Existing text CLI | Golden-output smoke for `profiles`, `list`, `history` |
| JSON output | JSON parse tests for every command |
| NDJSON output | line-by-line parser test |
| Exit codes | Unit tests with fake missing config/provider |
| Ask scope | Exact place/global scope tests |
| Model switch | Fake bad model rejection still works |

### 7.2 Security

- JSON output must never include API keys.
- `doctor --json` may show `configured: true|false`, provider label, model, and missing variable names.
- Local paths can be shown in local CLI, but public docs/examples must use placeholders.
- Scraped review text in JSON is data, not HTML; consumers must escape if rendered.

### 7.3 Error Boundaries

| Failure | CLI JSON Behavior |
| --- | --- |
| Missing keys | code 2, next_action references `.env.example` |
| Provider down | code 3, recoverable true, suggest retry or model check |
| Empty cache | code 5, suggest Scout |
| Job timeout | code 6, include job_id if persisted |
| Partial Scout | code 4 if reports/errors mixed |

## 8. Architecture

### 8.1 Suggested Internal Structure

Add only if needed:

| File | Responsibility |
| --- | --- |
| `placeintel/contracts.py` | JSON-friendly response helpers and schemas |
| `placeintel/doctor.py` | readiness checks used by CLI and API |
| `placeintel/jobs.py` | durable job records and event storage, if ops PRD builds it |
| `docs/API.md` | HTTP contract |
| `docs/agent-cli.md` | CLI contract |

Do not duplicate pipeline logic in CLI. CLI must call shared pipeline/server-safe helpers.

### 8.2 Data Resolution Contract

| Data Type | Resolution Owner | Consumers Must Not |
| --- | --- | --- |
| Provider/model labels | `config.provider_info()` | Rebuild from env names |
| Place facts | `cache.get_place` plus server payload shaping | Parse raw_json in frontend/agents |
| Review translation | `pipeline.translate_review()` | Overwrite `reviews.text` |
| QA cache scope | `cache.find_cached_answer()` | Reuse across place/global scopes |
| Job events | pipeline `_emitter` plus durable jobs | Invent new stage names |

## 9. Documentation

`docs/agent-cli.md` must include:

- Install prerequisites.
- Environment variables.
- Command table.
- Output formats.
- Exit codes.
- NDJSON examples.
- Safe destructive command pattern.
- Common agent recipes:
  - "Check if ready."
  - "Run a Scout and watch events."
  - "Ask a cached question."
  - "Export a place dossier as JSON."
  - "Switch model safely."
  - "Back up before deletion."

`docs/API.md` must include:

- Endpoint table.
- Request/response examples.
- Error shape.
- Event shape.
- Cache and scope rules.
- Version compatibility note.

## 10. Performance

- JSON output should not load entire DB unless command asks for all data.
- `export` for one place can include all reviews; large exports should support `--limit`, `--include reviews|reports|vectors?`.
- NDJSON streaming should flush events as they happen.
- `doctor` default must be cheap; live checks require `--live`.

## 11. Implementation Sequence

1. Add response helper and exit-code constants.
2. Add `doctor --json` cheap checks.
3. Add `--format json` to read-only commands.
4. Add JSON/NDJSON to `ask`, `scout`, and `shop`.
5. Add docs.
6. Add tests for parseability and exit codes.
7. Only then consider durable job commands from ops PRD.

## 12. Success Metrics

- `placeintel doctor --json | jq .ok` works.
- `placeintel profiles --format json` parses as JSON.
- `placeintel ask "..." --format json` parses and preserves cache fields.
- `placeintel scout "..." --format ndjson` can be consumed by a simple line parser.
- All examples in `docs/agent-cli.md` are copy-paste runnable.

## 13. Open Questions

- Should `--format` be global before or after subcommand in argparse? Default: support both if feasible; at minimum document the accepted order.
- Should schemas be generated from Pydantic? Default: no new dependency; use simple JSON examples first.
- Should CLI include MCP-ready `tools` metadata? Default: defer until agent CLI is stable.
