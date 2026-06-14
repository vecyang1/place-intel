# PRD: placeintel Production Operations Readiness

Status: 🔨 In Progress — US-OPS-006 complete; favorite refresh remains
Last Updated: 2026-06-14
Parent PRD: `tasks/prd-placeintel-production-grade-master.md`
Scope: Reliability, deployment, health checks, job durability, backups, observability, and operational safety.

## 1. Overview

`placeintel` is already deployed privately and protected, but its production-readiness story is uneven:

- web jobs are in memory.
- health is mainly `/api/meta`.
- deployment exists but needs a product-level runbook.
- backup/restore is CLI-first with manifest verification; deploy/refresh remain.
- provider/scraper diagnostics are scattered across runtime behavior and docs.

This PRD makes the product survivable: restart-safe jobs, health checks, visible diagnostics, backup/restore, cost guardrails, scheduled refresh with opt-in safety, and deployment verification.

## 2. Goals

- G1: A local or VPS operator can tell whether the app is healthy in under 10 seconds.
- G2: Restarting the web service does not make active or recent jobs disappear silently.
- G3: A failed provider/scraper path produces an actionable diagnostic, not a vague UI error.
- G4: Cache and reports are backupable and restorable.
- G5: Protected deployment has a repeatable smoke test and rollback plan.
- G6: Scheduled refresh exists only for opt-in favorites and respects cost/credit controls.
- G7: Public code remains privacy-safe and free of real domains/secrets unless explicitly intended.

## 3. User Stories

### US-OPS-001: Cheap Health Check

As an operator, I want `/api/health` and `placeintel doctor --json` to verify basic health without spending API credits.

Acceptance Criteria:
- [x] `/api/health` returns 200 with version, DB connectivity, data dir writability, static web file status, and current provider labels.
- [x] It performs no model, scraper, SerpAPI, Docker, or Chrome calls.
- [x] CLI doctor reports the same cheap checks without web server.
- [x] Missing live keys are warnings unless a required path is requested.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed by `placeintel/doctor.py`,
`GET /api/health`, and `placeintel doctor --json`. Verified with
`tests/test_doctor_contract.py`, full Python unit discovery, CLI doctor smoke,
compileall, JS syntax check, line budget, and `git diff --check`.

### US-OPS-002: Deep Diagnostics

As an operator or agent, I want a live diagnostic mode so I can know which external wheel is broken.

Acceptance Criteria:
- [x] `/api/health/deep` or `placeintel doctor --live --json` can check reasoning model, embedding model, translation model, Chrome, Docker, gosom image, review scraper vendor, and optional SerpAPI.
- [x] Each check reports `ok`, `latency_ms`, `severity`, and `next_action`.
- [x] Live checks are opt-in and clearly marked cost-bearing when they may call providers.
- [x] Failed checks do not crash unrelated read-only UI.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with `doctor.deep_health()`,
`placeintel doctor --live --json`, and `GET /api/health/deep`. Deep checks are
warnings by default and become failures only when required by the CLI.

### US-OPS-003: Durable Jobs

As a user, I want long jobs to survive reloads/restarts enough that I can see whether they finished, failed, or were interrupted.

Acceptance Criteria:
- [x] Job records are persisted in SQLite before worker thread start.
- [x] Job events are persisted append-only.
- [x] `/api/jobs/{id}` reads from durable state.
- [x] On startup, running jobs older than the current process are marked `interrupted` with a retry hint.
- [x] UI can show interrupted state and "retry using cache" action.
- [x] Existing event stage contract remains unchanged.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with SQLite `jobs` and `job_events`
tables in `cache.py`, durable server job helpers in `server.py`, startup stale
job interruption, and an interrupted-state web retry button. Coverage:
`tests/test_durable_jobs.py` and
`tests/test_web_static_contract.py::test_interrupted_jobs_show_retry_using_cache_action`.

### US-OPS-004: Streaming Progress

As a user or agent, I want progress to stream promptly without wasteful polling.

Acceptance Criteria:
- [x] `/api/jobs/{job_id}/events` streams events as SSE or NDJSON.
- [x] Web UI uses stream when available and falls back to polling.
- [x] CLI `scout/shop --format ndjson` can use the same event source internally or equivalent pipeline callback.
- [x] Stream reconnect can resume from last event id or timestamp.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with FastAPI
`StreamingResponse`/SSE over durable `job_events`, query/header resume cursors,
and a web `EventSource` path that falls back to the existing polling final-state
reader. CLI NDJSON uses the same pipeline event contract through callback output.
Coverage: `tests/test_durable_jobs.py`, `tests/test_web_static_contract.py`,
`npm run test:web`, and an ad-hoc Playwright stream smoke.

### US-OPS-005: Backup and Restore

As the product owner, I want cache/report/settings backups before destructive operations or deployment changes.

Acceptance Criteria:
- [x] `placeintel backup --format json` creates a timestamped backup manifest.
- [x] Backup includes `placeintel.db`, scraper DB if present, reports, and settings.
- [x] Backup excludes keys and `.env`.
- [x] Restore requires explicit confirmation and validates schema after restore.
- [x] Temp DB test proves backup/restore round trip.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with `placeintel/backup.py`,
`placeintel backup`, and `placeintel restore`. Backups are manifest directories
under `data/backups/` by default, use SQLite's online backup API for databases,
copy only declared non-secret artifacts, and verify SHA-256 + required DB tables
before restore. Restore requires `--yes` and refuses external paths unless
`--force` is passed. Coverage: `tests/test_backup_restore.py`.

### US-OPS-006: Deployment Runbook

As an operator, I want deployment verification that proves the actual protected service is serving the new build.

Acceptance Criteria:
- [x] `docs/operations.md` documents local, private VPS, protected domain, and public code-only mirror.
- [x] Post-deploy smoke verifies `/api/meta`, `/api/health`, static asset version, Library read, Dossier read, and auth protection if domain is public.
- [x] Rollback plan is executable in under 60 seconds.
- [x] Deployment docs do not expose private paths, hostnames, credentials, or secrets in public-safe docs.
- [x] Typecheck/lint passes.

Implementation note 2026-06-14: Completed with `placeintel/deploy_smoke.py`
and `placeintel deploy-smoke --format json`. The smoke is read-only, verifies
`/api/meta`, `/api/health`, versioned `/static/app.js`, Library load, one
dossier read when cache is non-empty, and optional unauthenticated public-domain
rejection. `docs/operations.md` now documents local/private/protected/public
deployment surfaces with placeholders only, and README points to the runbook
without exposing the real protected domain.

### US-OPS-007: Favorite Refresh

As a repeat user, I want selected places to refresh on a safe schedule so the app warns me when evidence gets stale.

Acceptance Criteria:
- [ ] User can mark cached places as favorites.
- [ ] Refresh schedule is opt-in and disabled by default.
- [ ] Refresh respects max reviews, provider availability, and cost guardrails.
- [ ] Refresh emits normal job events and writes history.
- [ ] Failed refresh does not delete old reports or reviews.
- [ ] Typecheck/lint passes.

## 4. Functional Requirements

### 4.1 Health

- FR-OPS-001: Add `placeintel/doctor.py` or equivalent shared health module.
- FR-OPS-002: Cheap health must check:
  - package import.
  - version.
  - config paths.
  - DB connect and migrations.
  - data dir writable.
  - web static files present and under line budget.
  - provider labels from `config.provider_info()`.
- FR-OPS-003: Deep health must check:
  - `config.list_reason_models()` or a tiny model ping.
  - embedding ping with one tiny content item.
  - translation model availability.
  - Chrome binary.
  - Docker daemon and gosom image availability.
  - vendor scraper path and import/start prerequisites.
  - optional SerpAPI key presence, not mandatory.
- FR-OPS-004: Health JSON must not include keys or full private deploy values.

### 4.2 Durable Jobs

- FR-OPS-005: Add SQLite tables:
  - `jobs(job_id, kind, status, request_json, result_json, error, created_at, updated_at, process_id?)`.
  - `job_events(id, job_id, t, stage, msg, data_json)`.
- FR-OPS-006: Use transactions for job status transitions.
- FR-OPS-007: Keep in-memory cache optional for performance, but SQLite is source of truth.
- FR-OPS-008: Mark stale `running` jobs as `interrupted` on startup.
- FR-OPS-009: Job result serialization must match the current web result shape unless versioned.

### 4.3 Streaming

- FR-OPS-010: Add stream endpoint:
  - Option A: SSE `text/event-stream`.
  - Option B: NDJSON `application/x-ndjson`.
  - Default recommendation: SSE for browser, NDJSON for CLI if simpler.
- FR-OPS-011: Stream endpoint must support reconnect after a given event id or timestamp.
- FR-OPS-012: Polling fallback must remain for older browsers and tests.

### 4.4 Backup/Restore

- FR-OPS-013: Backup command must use SQLite-safe backup API or locked copy method.
- FR-OPS-014: Backup manifest includes file list, size, SHA-256, app version, created_at.
- FR-OPS-015: Restore validates required tables and migrations after restoring.
- FR-OPS-016: Destructive cache delete should suggest a fresh backup when recent backup is absent.

### 4.5 Provider and Cost Guardrails

- FR-OPS-017: Add config registry for cost-bearing defaults:
  - max review count.
  - top N deep dives.
  - place TTL days.
  - map chunk size.
  - max reviews prompt.
  - translation model.
  - reasoning model.
  - SerpAPI fallback enabled.
- FR-OPS-018: Settings/System UI must show cost-bearing actions clearly.
- FR-OPS-019: Scheduled refresh must have daily and per-run caps.

### 4.6 Deployment

- FR-OPS-020: Keep service loopback-only unless protected by explicit auth/proxy.
- FR-OPS-021: Add `/api/health` to GitHub Actions and remote deploy smoke.
- FR-OPS-022: Add a smoke command that can run locally or via SSH:
  - verify version.
  - verify health.
  - verify static assets include version.
  - verify one read-only API route.
- FR-OPS-023: Document protected domain checks without committing secrets.

## 5. Non-Goals

- Do not add Kubernetes, Docker Compose app deployment, Redis, Celery, or PostgreSQL unless job durability needs exceed SQLite.
- Do not build public registration/auth.
- Do not auto-refresh every cached place.
- Do not run live provider pings by default on every page load.
- Do not back up `.env`, keys, or private credentials.

## 6. Stack and Dependencies

Use existing stack:

| Capability | First Choice | Reason |
| --- | --- | --- |
| Durable jobs | SQLite tables | App already uses SQLite and is single-user/local-first |
| Streaming | FastAPI native StreamingResponse/SSE | Avoid new dependency until needed |
| Scheduling | Manual CLI first, then simple local scheduler | Avoid background complexity before favorites exist |
| Backup | Python stdlib + SQLite backup | No new dependency |
| Logs | Python logging structured format | Existing logging in pipeline/server |

Rejected for first pass:

| Alternative | Reason |
| --- | --- |
| Redis/RQ/Celery | Too heavy for local-first single-user app |
| APScheduler daemon | Useful later, but favorites + guardrails must exist first |
| External monitoring SaaS | Privacy and local-first mismatch |
| Full Docker app packaging | Existing native systemd deploy already works |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Behavior | Risk | Verification |
| --- | --- | --- |
| In-memory job API shape | Durable storage could change result shape | Server contract tests for `/api/jobs/{id}` |
| Timeline rendering | Streaming could break polling | Playwright with stream success and polling fallback |
| CLI text commands | JSON additions could alter text output | Text smoke snapshots |
| Deployment | Health checks could require secrets in public mirror | CI secret validation and public repo skip rule |
| Backup/restore | Data loss | Temp DB round trip and restore validation |

### 7.2 Security

- Health endpoints must not return keys.
- Protected public domain must stay authenticated.
- Backup files must be local and not tracked.
- Restore must refuse paths outside allowed backup directory unless explicitly forced.
- Logs must not include API keys or full prompts with private user queries unless local debug is explicitly enabled.

### 7.3 Failure Boundaries

| Component | Failure | Recovery |
| --- | --- | --- |
| Durable job write | SQLite locked | retry short, then fail job before expensive work starts |
| Streaming | client disconnect | job continues; event persists |
| Backup | file copy/hash mismatch | delete partial backup and report failure |
| Restore | schema invalid | refuse restore and keep current DB |
| Deep health provider ping | provider down | report degraded, no crash |
| Scheduled refresh | one place fails | continue others, old data remains |

## 8. Architecture

### 8.1 Job Lifecycle

```text
submit request
  -> create jobs row status=running
  -> append initial event
  -> worker thread runs pipeline with on_event writer
  -> append events
  -> status=done with result_json OR status=error with error
  -> startup later marks stale running as interrupted
```

### 8.2 Health Schema

Example:

```json
{
  "ok": true,
  "version": "0.4.18",
  "mode": "cheap",
  "checks": [
    {"name": "db", "ok": true, "severity": "critical", "latency_ms": 3, "message": "connected"},
    {"name": "data_dir", "ok": true, "severity": "critical", "message": "writable"}
  ],
  "warnings": [],
  "errors": []
}
```

### 8.3 Configuration Registry

| Config Key | Default | Tier | UI Location | Notes |
| --- | --- | --- | --- | --- |
| `PLACEINTEL_PORT` | `9618` | env | System Info | read-only runtime |
| `PLACEINTEL_DATA_DIR` | `./data` | env | System Info | read-only unless future config |
| `PLACEINTEL_PLACE_TTL_DAYS` | `14` | env/admin future | Settings > Cache | cache freshness |
| `PLACEINTEL_REASON_MODEL` | `gemini-2.5-flash` fallback | env/admin | Settings > Models | current settings.json overrides |
| `PLACEINTEL_TRANSLATION_MODEL` | `gemini-3.1-flash-lite` | env/admin | Settings > Models | cheap display translation |
| `PLACEINTEL_EVIDENCE_LANG` | `report` | env/user | Settings > Language | report/original |
| `PLACEINTEL_MAX_REVIEWS_PROMPT` | existing default | env/admin | Settings > Performance | report prompt cap |
| `PLACEINTEL_MAP_CHUNK` | existing default | env/admin | Settings > Performance | map-reduce chunk size |
| `SERPAPI_API_KEY` | empty | secret | System Info configured yes/no | optional fallback |

## 9. Observability

Structured log events:

| Event | Level | Component |
| --- | --- | --- |
| `job.started` | info | server/jobs |
| `job.event` | debug/info | pipeline |
| `job.completed` | info | server/jobs |
| `job.failed` | error | server/jobs |
| `provider.retry` | warn | analyze/embed |
| `provider.unavailable` | error | doctor |
| `scraper.fallback` | warn | reviews/discover |
| `backup.created` | info | backup |
| `restore.completed` | warn | restore |
| `health.deep_failed` | warn | doctor |

No external log shipping by default.

## 10. Deployment Runbook Requirements

`docs/operations.md` must document:

1. Local start:
   - `.venv/bin/placeintel-web`
   - `curl http://127.0.0.1:9618/api/health`
2. Local verification:
   - Python tests.
   - Playwright tests.
   - CLI doctor.
3. Private VPS deploy:
   - GitHub Actions secret requirements.
   - systemd service.
   - loopback binding.
4. Protected domain:
   - Basic Auth check.
   - `/api/meta` and `/api/health`.
   - static asset version check.
5. Rollback:
   - revert to previous commit or previous deployed directory snapshot.
   - restart service.
   - verify health.
6. Backup/restore:
   - before deploy.
   - before destructive cleanup.
   - restore validation.

## 11. Performance

- Cheap health target: <100ms local.
- Deep health target: <15s with provider pings.
- Job event append overhead: <10ms/event.
- Stream update latency target: <=1s perceived.
- Backup for normal local DB target: <10s, with progress for larger stores.

## 12. Success Metrics

- Restarting `placeintel-web` during a job results in visible `interrupted` status, not a missing job.
- `curl /api/health` works with no live provider keys.
- `placeintel doctor --json` works without web server.
- A backup can be restored into a temp data dir and pass `doctor`.
- Deploy workflow checks `/api/health` before claiming success.

## 13. Open Questions

- Should scheduled refresh use launchd on the Mac or an app-internal scheduler? Default: CLI/manual first, launchd/systemd optional after favorites exist.
- Should backups be compressed? Default: yes for manifest packages if DB/report size warrants; not required for first test.
- Should health endpoints be protected by Basic Auth on public domain? Default: yes through existing proxy protection.

## 14. Documentation Checklist

- [x] `docs/operations.md`
- [x] `docs/API.md` health/job sections
- [x] `docs/agent-cli.md` doctor/backup/job examples
- [x] `README.md` local verify and operations links
- [x] `AGENTS.md` new invariants if durable jobs or backup rules are added
- [x] `CHANGELOG.md`
- [x] `progress.md`
