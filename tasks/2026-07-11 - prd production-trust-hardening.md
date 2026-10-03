# PRD: Production Trust Hardening

Created: 2026-07-11
Last Updated: 2026-07-11
Status: In Progress
Feature Type: Full-stack production reliability, evidence integrity, and launch measurement
Owner: Codex
Deployment Profile: hybrid
Deploy Targets: local FastAPI app, protected VPS/systemd lane, public code mirror
Related PRDs:
- `tasks/2026-07-10 - prd gmr-supabase-auth.md`
- `tasks/prd-placeintel-production-ops.md`
- `tasks/prd-placeintel-agent-cli-api.md`
- `tasks/prd-placeintel-world-class-ui-ux.md`

## 1. Introduction

PlaceIntel's core Scout, Shop, Library, Ask, report, translation, backup, job
event, and deployment workflows are mature. The next risk is not missing visible
features. It is that invited real users can create overlapping expensive jobs,
the only authentication boundary is an external proxy, AI artifacts lack full
source provenance, operations are not structurally observable, and local usage
cannot distinguish product value from test activity.

This PRD hardens the existing product without changing its purpose or provider
routing. It adds a bounded local job control plane, resource and provider budgets,
structured operations, content-addressed vectors and AI caches, source-verifiable
reports, privacy-safe launch measurement, and frontend/test headroom.

Application authentication remains owned by the related Supabase Auth PRD. This
PRD must strengthen proxy verification and remain auth-ready, but it must not
invent a second identity system.

### Assumptions

- The primary audience is a small invited team using one protected deployment.
- One heavy Scout/Shop job at a time is acceptable and safer than parallel
  Chrome/Docker activity.
- SQLite, systemd, and the no-build SPA remain appropriate at current scale.
- No external analytics, Redis, Celery, or vector database is justified yet.
- The user's autonomous-build directive approves the recommended approach
  without a new clarification interview.

## 2. Goals

- G1: Prevent overlapping heavy jobs from colliding or causing unbounded spend.
- G2: Make every queued/running/terminal state durable, transparent, and
  recoverable after restart.
- G3: Record and enforce provider usage without storing private content.
- G4: Make every vector and AI cache entry traceable to its exact source/model
  provenance.
- G5: Ensure every grounded report finding cites valid source review ids and all
  claimed source text is actually processed.
- G6: Ship structured local operations and privacy-safe launch measurement.
- G7: Remove frontend line-limit and Playwright discovery cliffs with zero visual
  or behavioral regression.
- G8: Preserve all project invariants and prove the release through unit,
  browser, runtime, GitNexus, backup, deploy-smoke, and security gates.

### Measured Baseline and Targets

| Metric | Baseline | Target |
| --- | --- | --- |
| Python tests | 124 pass | all existing plus new pass |
| Main-worktree Playwright | 37 pass when scoped by absolute path | root config always discovers exactly the intended suite |
| Active heavy job limit | unbounded daemon threads | 1 per process/host resource lane |
| Duplicate active requests | separate jobs | same job id, `reused=true` |
| Queue backpressure | none | bounded capacity, HTTP 429 before work/provider calls |
| Current vector provenance | id + dims + bytes | source hash + model + provider + dims + format version + timestamp |
| Eligible vector coverage | 1,340/1,340 current by presence only | 100% current by full provenance |
| Report findings lacking evidence | 25/312 in local historical reports | 0 in newly generated grounded reports |
| Invalid confidence values | 2 in local historical reports | 0 in newly generated reports |
| Silent text truncation | 43,560 source characters in audited report places | 0 characters omitted from coverage claim |
| Local product funnel | absent | activation/time-to-value/cache-return summary, tests excluded |

## 3. User Stories

### US-001: Stable Build and Frontend Headroom

As a maintainer, I want deterministic test discovery and purpose-owned frontend
files so that unrelated worktrees and line limits cannot create false failures or
force unsafe compact code.

Acceptance Criteria:
- [ ] Playwright config restricts discovery to the root `tests/` directory.
- [ ] The normal `npm run test:web` command discovers one copy of each test.
- [ ] CSS is split by responsibility and every no-build file remains under 800 lines.
- [ ] New operations/evidence behavior lives outside the near-limit `app.js`.
- [ ] The four hash routes, language modes, dossier dialog/focus, and visual layout are unchanged.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via Playwright screenshots at 375, 768, 1024, and 1440 widths passes.

### US-002: Bounded Durable Jobs and Cost Controls

As an invited user, I want heavy work to queue safely and explain delays so that
my request never collides with another scrape or silently drains provider credit.

Acceptance Criteria:
- [ ] Scout/Shop jobs persist as `queued` before execution and become `running` only when claimed.
- [ ] A bounded runner executes one heavy job at a time with queue capacity 8 by default.
- [ ] A duplicate active request returns the existing job id and `reused=true`.
- [ ] Queue saturation returns HTTP 429 with `Retry-After` and no phantom running job.
- [ ] Discovery and scraper-pro use cross-process named locks below `DATA_DIR`.
- [ ] SerpAPI units are reserved/recorded and a configurable daily limit blocks calls before spend.
- [ ] Startup/restart safely interrupts stale queued/running rows from other processes.
- [ ] Job timeline renders queued, running, interrupted, budget-blocked, failed, and done states.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via Playwright queued/error flows passes.

### US-003: Structured Operations and Launch Measurement

As the operator, I want safe local logs, usage summaries, and funnel measurements
so that I can diagnose failures and decide what to build from evidence rather
than memory.

Acceptance Criteria:
- [ ] Structured events cover job lifecycle, provider attempts, retries/failures, scraper fallback, cache outcomes, queue/budget rejection, and report validation.
- [ ] Every event has timestamp, level, event name, component, outcome, duration where applicable, and job id where applicable.
- [ ] Logs redact keys and omit raw queries, questions, reviews, precise locations, and local paths by default.
- [ ] `docs/logging.md` contains the event registry and triage ledger.
- [ ] Local product events track first submit, dossier open, scoped Ask, Maps open, cache reuse, and bounded duration/count values only.
- [ ] Browser/test automation events are excluded from product summaries.
- [ ] Metrics are disableable and retained for 90 days by default.
- [ ] System API/UI exposes only non-secret queue, budget, vector, and funnel summaries.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via the System panel passes.

### US-004: Content-Addressed Vector and Ask Provenance

As a user asking cached evidence, I want retrieval and cached answers tied to the
exact source/model state so that old vectors or mislabeled cached answers cannot
quietly influence results.

Acceptance Criteria:
- [ ] `review_vectors` stores source hash, model, provider, dimensions, input version, and created time.
- [ ] Index selection includes missing or any provenance-mismatched eligible row.
- [ ] Review text/rating changes cause reindex without deleting unrelated vectors.
- [ ] A read-only vector health surface reports current, stale, missing, ineligible, and orphaned counts.
- [ ] Vector repair supports dry-run and checkpointed run modes.
- [ ] Ask indexes current eligible evidence before retrieval or returns an actionable completeness warning.
- [ ] QA cache stores original provider and evidence references; cache hits preserve both.
- [ ] QA/report fingerprints include listing and ordered review source state plus language/model/prompt/profile provenance.
- [ ] Typecheck/lint passes.

### US-005: Source-Verifiable Full-Evidence Reports

As a user reading a report, I want every finding tied to raw source reviews and
every claimed review character processed so that I can audit the recommendation.

Acceptance Criteria:
- [ ] Complete review text and owner responses are segmented with stable review/segment ids.
- [ ] Single-pass vs map-reduce is selected by both review count and character budget.
- [ ] Coverage states cached rows, text-bearing rows, processed characters, and segment count.
- [ ] Report JSON is validated for required fields, configured dimensions, confidence enum, and evidence references before save.
- [ ] Every persisted finding has at least one valid review id from the analyzed set.
- [ ] Unsupported findings are removed or explicitly marked unsupported, never shown as normal grounded findings.
- [ ] Legacy report string evidence remains readable.
- [ ] Dossier evidence controls focus the matching raw review without breaking language/rating filters or modal focus.
- [ ] A sanitized offline corpus measures citation precision, unsupported-claim rate, full-text coverage, retrieval hit@k, contradiction/recency behavior, and cache invalidation.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dossier evidence navigation passes.

### US-006: Release, Deploy, and Auth-Ready Boundary

As the owner, I want reproducible release proof and a stronger proxy gate so that
the hardened build can be deployed without overstating application auth.

Acceptance Criteria:
- [ ] Public deploy-smoke checks representative private API paths, not only `/`.
- [ ] Dependency/vendor inputs used by production are pinned or checksummed.
- [ ] Deployment keeps one Uvicorn worker and documents why.
- [ ] Backup/restore covers new tables through the existing allow-list database backup.
- [ ] Rollback remains under 60 seconds and preserves old data/contracts.
- [ ] Full local gates pass and loopback deploy-smoke proves the release version.
- [ ] Production proxy/auth/E2E is either freshly proven or plainly marked unverified with the exact external blocker.
- [ ] Version and CHANGELOG are updated only after all non-external acceptance criteria pass.
- [ ] Typecheck/lint passes.

## 4. Functional Requirements

- FR-001: `jobs.status` must support `queued`, `running`, `done`, `error`, and `interrupted` while preserving legacy rows.
- FR-002: Active request identity must be a deterministic hash of job kind and canonical non-secret request JSON.
- FR-003: The dispatcher must admit at most `queue_capacity + active_workers` jobs and never block the HTTP request thread waiting for capacity.
- FR-003a: `active_workers` must equal 1 in this architecture; any other configured value is rejected until a separate cross-process runner design exists.
- FR-003b: Shutdown stops admission, drains for at most the configured interval, and leaves unfinished rows recoverable as interrupted.
- FR-004: Duplicate detection and admission must be serialized within the server process.
- FR-005: Named resource locks must work across CLI and web processes on macOS/Linux and fail with bounded timeouts.
- FR-006: SerpAPI budget reservation must occur before each network request and use UTC-day windows.
- FR-007: Usage records must never contain credentials, raw user text, precise location, or provider response bodies.
- FR-008: Operational writes and product-event writes are fail-open relative to the core pipeline; their failure cannot corrupt or abort user data.
- FR-009: Product events accept only an allow-listed event name and bounded numeric/enum fields.
- FR-010: Test automation must identify itself so its events are excluded from product metrics.
- FR-011: Vector currentness requires exact source hash, model, provider, dimensions, and input-format version match.
- FR-012: Vector repair must be idempotent and persist after every batch.
- FR-013: Updating a review must not leave a vector current when its embedded input changed.
- FR-014: QA cache hits must return the generation provider and saved evidence references from the original answer.
- FR-015: Review segmentation must preserve every source character and stable review attribution.
- FR-016: Evidence validation must accept legacy reports for display but enforce the new contract for new persistence.
- FR-017: New report fingerprints must change when listing metadata, ordered review hashes, profile YAML, prompt version, language/evidence mode, model, or provider changes.
- FR-018: UI source-reference actions must consume backend review ids and must not re-resolve evidence identity.
- FR-019: System/metrics endpoints must be read-only, bounded, and non-secret.
- FR-020: Job/event/product-event retention must be explicit and cleanup idempotent.
- FR-021: Public smoke must reject unauthenticated representative private API routes with 401 or 403 when a public URL is supplied.
- FR-022: Cheap health must remain local and no-cost; it may count local rows but cannot call providers or launch tools.
- FR-023: All SQLite migrations must be additive, repeatable, and compatible with v0.4.70 data.
- FR-024: Original review text, report Markdown, translations, live relevance order, exact-place routing, and provider routing must remain unchanged except for additive provenance/validation metadata.

### Data Resolution Contracts

| Data | Resolution owner | Contract | Consumers |
| --- | --- | --- | --- |
| Active job reuse | job runner | canonical request hash -> one active job id | Scout/Shop API, web timeline |
| Provider usage | usage module | UTC window + provider/operation units | request guards, System summary |
| Vector currentness | embed/cache | source hash + provider/model/dims/version | indexer, Ask, doctor/System |
| Report evidence | evidence module | review id + segment id + source hash | analyzer, report store, dossier |
| Product event privacy | usage module | event allow-list + safe-field schema | browser event API, local summary |

## 5. Non-Goals

- No Redis, Celery, PostgreSQL migration, external queue, or multi-worker runner.
- No dedicated vector database or retrieval algorithm rewrite.
- No external analytics or transmission of cached/private content.
- No automatic favorite scheduler, PWA/offline mode, photo vision, or new top-level view.
- No framework rewrite or visual redesign.
- No replacement or duplication of the Supabase Auth PRD.
- No removal of proxy Basic Auth in this PRD.

### What This Does Not Change

- Planner and relevance filter remain fail-open.
- Live discovery results keep Google relevance order.
- Reports still cover all cached review evidence and Ask remains two-layer grounded.
- Embeddings remain Google official; reasoning/translation remain VectorEngine.
- Reviews and source reports remain original; translations remain display-only.
- Dossier exact-place identity, short Maps URL handling, backup allow-list, and cheap health stay intact.
- The four accessible hash tabs and dossier modal keyboard contract stay intact.

## 6. Stack and Dependencies

No new runtime service is added. Use Python stdlib `queue`, `threading`,
`contextvars`, `hashlib`, `fcntl`, `logging`, and SQLite. Reuse Pydantic through
FastAPI for API/report validation and existing vanilla JS/CSS for UI.

| Decision | Choice | Reason | Rejected |
| --- | --- | --- | --- |
| Job runner | bounded in-process runner + SQLite state | matches single-host scale and current deployment | Celery/Redis: operational overkill |
| Cross-process locks | `fcntl` lock files under `DATA_DIR` | no dependency, protects CLI + web | process-only mutex: cannot protect CLI/web collision |
| Usage/metrics | SQLite local ledgers | backupable, private, queryable | PostHog/Sentry product analytics: external privacy surface |
| Vector store | SQLite BLOB + NumPy cosine | current scale is ~1,900 reviews | vector DB: no measured need |
| Report validation | existing Pydantic/runtime validation | already installed and maintained | custom loose dict checks only: insufficient |
| Frontend | existing no-build HTML/CSS/JS | lowest regression/deploy risk | React/Vite rewrite: no user-value evidence |

### Constants and Configuration Registry

| Key | Default | Type/tier | UI | Rationale |
| --- | --- | --- | --- | --- |
| `PLACEINTEL_JOB_WORKERS` | `1` | int/env | System read-only | Docker/Chrome resources are single-host and collision-prone |
| `PLACEINTEL_JOB_QUEUE_CAPACITY` | `8` | int/env | System read-only | bounded small-team burst without unbounded memory/work |
| `PLACEINTEL_JOB_DRAIN_SECONDS` | `5` seconds | float/env | System read-only | bounded shutdown drain before durable interruption/retry |
| `PLACEINTEL_RESOURCE_LOCK_TIMEOUT` | `5` seconds | float/env | System read-only | fast actionable failure instead of hidden collision |
| `PLACEINTEL_DAILY_SERPAPI_LIMIT` | `50` units | int/env | System read-only | permits one normal fallback Scout while limiting repeated drains |
| `PLACEINTEL_USAGE_RETENTION_DAYS` | `90` | int/env | System read-only | sufficient launch trend without indefinite telemetry growth |
| `PLACEINTEL_JOB_RETENTION_DAYS` | `30` | int/env | System read-only | support window for jobs/events |
| `PLACEINTEL_VECTOR_INPUT_VERSION` | `1` | code | none | explicit invalidation on format changes |
| `PLACEINTEL_EVIDENCE_SEGMENT_CHARS` | `4000` | int/env | System read-only | preserves full text while bounding one evidence unit |
| `PLACEINTEL_SINGLE_PASS_CHARS` | `400000` | int/env | System read-only | keeps single pass inside a conservative long-context budget |
| `PLACEINTEL_MAP_CHARS` | `160000` | int/env | System read-only | bounded digest chunks with enough review context |
| `PLACEINTEL_PRODUCT_METRICS` | `true` | bool/env/admin-ready | System toggle after auth | local privacy-safe measurement; disableable |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing feature | Planned owner files | GitNexus risk | Verification |
| --- | --- | --- | --- |
| Scout/Shop API and durable jobs | server/cache/new job module | LOW graph result, operationally high | durable-job/server tests + browser submit/stream tests |
| Docker discovery | discover/lock module | LOW | discover contract + concurrent lock test |
| Review scraper and SerpAPI fallback | reviews/usage/lock modules | LOW | full review-salvage and pipeline fallback suites |
| Vector indexing and Ask | cache/embed/pipeline | LOW graph result, evidence-critical | cache/vector/Ask provenance tests |
| Report generation | analyze/evidence/cache | LOW graph result, evidence-critical | retry/activity/full-text/schema/eval tests |
| Web job start | app/new ops script | HIGH: init, bindGlobal, bindForms | all 37 Playwright flows + queued/429 additions |
| Dossier detail | app/dossier/new evidence script | HIGH: init, bindGlobal, pollFinal, openDetail | dossier focus, translation, review filters, evidence-focus tests |
| Backup/restore | cache schema + backup | medium | backup/restore round-trip with new tables |
| Deploy boundary | deploy-smoke/docs/workflow | high security | loopback smoke + public route rejection matrix |

### 7.2 Security Hardening

| Attack surface | Threat | Mitigation | Verification |
| --- | --- | --- | --- |
| Heavy job endpoints | denial of service/provider drain | bounded queue, duplicate reuse, budgets, auth-ready owner | 429, reuse, budget tests |
| SQLite event APIs | injection/oversized payload | parameterized SQL, enum allow-lists, bounded metadata | invalid payload tests |
| Logs/metrics | private text/key leakage | safe schemas and central redaction | seeded secret/private-text scan |
| Report evidence | fabricated source ids | analyzed-set validation | unsupported/unknown id tests |
| Dossier rendering | hostile scraped input/XSS | existing `esc()` path, no raw HTML | Playwright hostile-string test |
| Lock paths | traversal/symlink misuse | fixed names under resolved `DATA_DIR/locks` | path contract tests |
| Public proxy | unprotected `/api/*` | expanded unauthenticated route smoke | deploy-smoke tests |

Auth mechanism remains proxy Basic Auth outside FastAPI until the related
Supabase PRD is complete. This PRD adds no login endpoint or bearer token.

### 7.3 Error Boundaries

| Component | Failure | User experience | Recovery | Log event |
| --- | --- | --- | --- | --- |
| Queue | full | "Work queue is full. Retry shortly." + retry delay | retry; no job/data mutation | `job_rejected` |
| Duplicate | active match | existing job timeline opens | no duplicate work | `job_reused` |
| Resource lock | timeout | stage explains another job owns the resource | cache-first retry/fallback | `resource_lock_timeout` |
| Budget | exhausted | used/limit/reset shown, no provider call | wait/reset/admin config | `usage_budget_blocked` |
| Ops ledger | SQLite/log failure | core flow continues | stderr fallback and later retry | `ops_write_failed` |
| Vector repair | interruption/provider failure | completed batches retained; Ask warns if incomplete | resume mismatches only | `vector_repair_failed` |
| Report validation | invalid/unsupported output | previous report remains; actionable retry | retry/change model | `report_validation_failed` |
| Product metric | rejected/write failure | no visible user impact | drop event | `product_event_dropped` |

## 8. UI/UX Architecture

### 8.1 Audience Map

| Audience | Goal | Entry |
| --- | --- | --- |
| Invited researcher | get trustworthy place evidence quickly | Scout/Shop/Library/Ask after protected entry |
| Operator/owner | control cost, health, queue, and evidence integrity | System panel + CLI |
| Agent/automation | submit/watch/export with stable machine contracts | CLI JSON/NDJSON and HTTP API |

### 8.2 View Changes

No new top-level view. Existing views receive additive states:

- Scout/Shop timeline: queued, reused, budget-blocked, lock-wait/recovery.
- Dossier report: source-review controls and validation/coverage metadata.
- System panel: bounded queue, daily usage, vector health, local funnel summary.

### 8.3 Shared State

| State | Owner | Subscribers | Invalidation |
| --- | --- | --- | --- |
| job status/events | job API/SSE | Scout, Shop, dossier inline job | SSE then final poll |
| ops summary | `/api/config` or dedicated read API | System panel | reload/open + post-job refresh |
| report evidence refs | place/report detail API | dossier report/review list | dossier reload after job |
| metrics enabled | config API | browser event client/System | load + settings save |

### 8.4 View-to-Interface Map

| View | Interface | Additive fields | Hardcoded? |
| --- | --- | --- | --- |
| Scout/Shop | POST job + GET/SSE job | `status`, `reused`, `queue_position`, budget error | No |
| Dossier | place/report detail | coverage/validation/evidence refs | No |
| System | config/health/ops summary | queue, usage, vectors, funnel | No |
| All views | product event POST | allow-listed event + safe fields | No |

### 8.5 View States and Interaction

- Queued jobs retain the existing timeline footprint and show position/reuse.
- Budget/queue errors use `role="alert"` and a retry/reset next action.
- Evidence source controls are keyboard buttons; activating one clears only the
  necessary review filters, focuses the card, and preserves modal trapping.
- System summary uses text plus status tokens, not color alone.
- No action requires more than two clicks from its current view.

## 9. Design System

`DESIGN.md` is authoritative. This feature preserves the paper/ink/muted-red
system and system fonts. The selected auth reference is documented there but auth
UI remains owned by its PRD. New controls use at most 8px radius, 44px targets,
visible focus, no nested cards, no gradients, and no new decorative assets.

Motion is limited to 150-300ms opacity/color transitions and respects reduced
motion. Queue/status updates do not animate layout.

## 10. Responsiveness and Accessibility

- Verify 375, 768, 1024, and 1440px widths in light and dark modes.
- No horizontal scroll or text clipping.
- Job state and report evidence are announced through existing live regions.
- Evidence focus uses programmatic focus without breaking dossier Tab trapping.
- Color is never the only queue, health, validation, or budget indicator.

## 11. Health, Monitoring, and Logging

### Event Registry Seed

| Event | Level | Component | Purpose |
| --- | --- | --- | --- |
| `job_queued/reused/started/finished/failed/rejected` | info/warn/error | jobs | lifecycle and admission |
| `resource_lock_acquired/timeout` | debug/warn | locks | collision diagnosis |
| `provider_call/retry/failure` | info/warn/error | usage | usage, duration, outcome |
| `usage_budget_blocked` | warn | usage | cost protection |
| `vector_health/repair_batch/repair_failed` | info/error | embed | provenance state |
| `report_validated/report_validation_failed` | info/warn | evidence | trust gate |
| `product_event_dropped` | warn | usage | privacy/schema failure |

Cheap health adds only local row/schema checks. Deep health may expose local queue,
usage, vector, and report-validation summaries without automatically calling a
provider. `docs/logging.md` owns final names and triage state.

## 12. Analytics and Tracking

| Event | Safe fields | Purpose |
| --- | --- | --- |
| `first_submit` | view, fresh/cache, duration bucket | activation |
| `dossier_opened` | source view, report present bool | first value |
| `scoped_ask_completed` | cached bool, duration bucket | evidence engagement |
| `maps_opened` | source view | real-world intent |
| `cache_reused` | flow, age bucket | repeat value/economics |
| `session_returned` | days-since-first bucket | 7/30-day return |

No PII or content. Store locally for 90 days. Test sessions are excluded.

## 13. Implementation Principles

- Contract and migration tests precede implementation.
- Use the existing stack and smallest maintainable modules.
- Preserve fail-open AI planning/filtering but fail before incomplete/fabricated
  evidence or budget overspend.
- Checkpoint batch work and make every cleanup/repair idempotent.
- Update API/CLI/architecture/logging docs with contract changes.
- Run GitNexus `detect-changes` after each story and expand this PRD's regression
  table if the graph reveals an unlisted flow.
- Commit code and checked acceptance criteria together on the feature branch.

## 14. Documentation Requirements

Update in the same release:

- `docs/API.md` for additive job, ops, evidence, and event endpoints.
- `docs/agent-cli.md` for vector/usage/repair commands and outputs.
- `docs/architecture.md` for the job control plane and new provenance stores.
- `docs/operations.md` for budgets, retention, single-worker deploy, smoke, and rollback.
- `docs/logging.md` for events and triage.
- `DESIGN.md` for intentional evidence/ops UI changes.
- `AGENTS.md` for new hard invariants.
- PRD/router, task plan, progress, CHANGELOG, and version.

## 15. Technical Considerations

- SQLite remains WAL with busy timeout; new operational writes need bounded retry.
- Queue execution remains single-process and explicitly not horizontally scalable.
- `fcntl` supports the documented macOS/Linux targets; Windows is not a deploy target.
- Provider call counts are exact; token/currency estimates must be labeled estimates.
- Historical report/QA rows lack new provenance and remain legacy, not silently rewritten.
- Large report evidence must stay within model limits through character-bounded map-reduce.

## 16. Success Metrics

- All newly admitted heavy jobs are bounded, durable, and collision-free in tests.
- No provider call occurs after a budget rejection.
- 100% of eligible current vectors match full provenance after repair.
- 100% of new grounded findings carry valid source ids.
- Offline trust corpus has zero unknown review ids and zero silently unsupported findings.
- Normal Web test command discovers one root suite and all flows pass.
- System summary exposes actionable state without any seeded private/secret string.
- Five non-author user tasks are documented before the next visible-feature PRD.

## 17. Open Questions

| Question | Decision/owner |
| --- | --- |
| Can current Supabase/OAuth/SMTP/deploy credentials be verified? | Existing Auth PRD; Codex must audit via approved credential/browser paths. |
| Are production proxy rules protecting every private API? | Must be proven by expanded deploy-smoke; not assumed. |
| What queue/budget defaults fit real invited usage? | Start with documented conservative defaults; adjust only from local usage evidence. |
| Which visible feature follows hardening? | Decide only after five non-author tasks and activation/return evidence. |

## 18. Deployment and Configuration

### Environment Matrix

| Environment | Runtime | Data | Secrets |
| --- | --- | --- | --- |
| local | one Uvicorn process on loopback | local `DATA_DIR` | env/local approved discovery |
| staging/tunnel | VPS-equivalent systemd behind protected access | staging data dir | staging GitHub/VPS env |
| production | one Uvicorn process on loopback behind proxy | persistent VPS data dir | GitHub Secrets + VPS env |

The deploy chain remains GitHub Actions -> SSH -> native systemd -> deploy-smoke.
The service must explicitly run one worker. New config variables are documented
in `.env.example` and exposed read-only in System status. Backups continue using
SQLite online backup, so new tables are included automatically.

Production release proof requires:

1. Full local Python/browser/compile/syntax/PRD/diff gates.
2. Vector/usage/job migration against a copied real DB and integrity check.
3. Loopback deploy-smoke at the release version.
4. Public unauthenticated rejection matrix when a public URL is used.
5. Authenticated key user flow through tunnel/protected URL.
6. Log/metrics secret scan and five-minute post-deploy error review.
7. Rollback proof using the previous release/service configuration.

## Build Progress

- 2026-07-11: Source-backed audit, baseline tests, design owner, and design spec completed.
- 2026-07-11: Task 1 implemented and locally verified under red-green TDD:
  root Playwright discovery owns exactly 39 tests, purpose-owned CSS/JS assets
  remain below 800 lines, and cheap doctor validates the asset graph derived
  from `index.html`. Independent task review is next; Task 2 has not started.

## Revision History

| Date | Version | Change | Author |
| --- | --- | --- | --- |
| 2026-07-11 | v0.2 | Marked In Progress after locally verified Task 1 frontend/test isolation milestone. | Codex |
| 2026-07-11 | v0.1 | Conversation-synthesis PRD from parallel product, reliability/security, and AI-evidence audits. | Codex |
