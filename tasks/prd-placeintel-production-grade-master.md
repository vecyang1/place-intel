# PRD: placeintel Production-Grade Master Plan

Status: 🔨 In Progress — US-001 through US-003 complete; Compare story and CLI global-option hardening remain
Last Updated: 2026-06-15
Product Version Observed: 0.4.31 in working tree
Deployment Profile: hybrid (local-first product with private protected web deployment)
Primary Owner: next `/goal` implementation agent
Related PRDs:
- `tasks/prd-placeintel-world-class-ui-ux.md`
- `tasks/prd-placeintel-agent-cli-api.md`
- `tasks/prd-placeintel-production-ops.md`

## 0. Clarification Assumptions

The user explicitly asked to write PRD(s), not implement. The PRD skill normally asks a clarification gate before planning. For this turn, the gate is resolved by these assumptions:

1. Build toward a world-class, production-ready, customer-facing app, but preserve the local-first intelligence product rather than turning it into a generic SaaS.
2. Keep the existing stack unless a PRD section proves the current pattern blocks production quality: Python package, FastAPI web shell, SQLite cache, no-build web UI, Playwright tests, Gemini/VectorEngine provider routing.
3. Preserve all project constitution rules in `AGENTS.md`, especially fail-open AI planning, exact-scope QA cache, all-review coverage, original review storage, and web file line limits.
4. Add an agent-friendly CLI/API surface as a first-class product requirement, not an implementation afterthought.
5. Do not add user accounts, payments, public multi-tenant features, or a full frontend framework in the first production-grade pass.

## 1. Introduction

`placeintel` already works as a local Google Maps review intelligence tool: any-language intent in, AI-planned search, candidate filtering, full review scraping, local cache, review embedding, long-context report generation, shop dossier, Ask, translation, language/rating review lens, and protected web deployment.

The next product step is not "more features." It is to turn the app into a coherent production-grade decision system:

- for a traveler or local operator, it should answer "should I go, what should I ask, what should I avoid, and what evidence supports that?"
- for the user, it should be fast, calm, bilingual, resilient, and inspectable on desktop and phone.
- for future agents, it should expose a stable machine interface so agents can scout, ask, export, refresh, test, and diagnose without scraping the UI.

## 2. Goals

### 2.1 Product Goals

- G1: Make the first screen a working command center that gets a user from vague intent to actionable place intelligence in two clicks or fewer.
- G2: Make every major answer evidence-first: report claims, Ask answers, risk tags, and walk-in advice must link back to listing metadata, review excerpts, review dates, ratings, or scrape freshness.
- G3: Make dossiers readable before they are exhaustive: show a pinned walk-in card first, then facts, risks, Ask, report, review lens, and raw evidence.
- G4: Make repeat use cheaper and calmer: surface past scouts, favorite places, cache freshness, scheduled refresh candidates, and "no new evidence" reuse.
- G5: Make the UI production-grade across 375px mobile, 768px tablet, desktop, dark mode, keyboard-only, screen-reader basics, and protected public domain use.
- G6: Make the CLI/API agent-native: stable JSON/NDJSON, exit codes, schemas, dry-run, job status, health checks, and docs that future agents can call directly.
- G7: Make operations boring: health endpoints, durable job records, backup/restore, deployment smoke, provider diagnostics, privacy controls, and rollback instructions.

### 2.2 Measurable Success Metrics

| Metric | Current Baseline | Production Target |
| --- | --- | --- |
| First useful action | Scout/Shop/Ask tabs exist; user chooses manually | Command center suggests Scout/Shop/Ask path from input and starts in <=2 clicks |
| Job progress | Polling every 2s via `/api/jobs/{id}` | SSE or NDJSON stream with <=1s perceived update latency and polling fallback |
| Dossier readability | Long report plus review lens; ask form already moved high | Above-fold walk-in card, risk/fact/evidence tabs, raw review controls below |
| Agent parsing | Some commands print text; `export` prints JSON | Every data command supports `--format json`; job streams support NDJSON |
| Evidence coverage | Reports cover all cached reviews; Ask uses vector hits | UI visibly shows coverage, newest scrape, source blocks, and answer evidence cards |
| Mobile quality | Playwright smoke catches overflow and first action | Full viewport matrix: 375/390/768/1024/1440, light/dark, modal, dossier, Ask |
| Reliability | Retry for report reasoning; fail-open planning/filtering | Durable jobs, restart-safe status, retry policy registry, provider health checks |
| Deployment | Private repo deploy and protected domain exist | Documented runbook, `/api/health`, backup/restore, deploy smoke, rollback <60s |

## 3. User Stories

### US-001: Start From Intent, Not From App Structure

As a traveler or operator, I want one obvious input that accepts a need, a shop name, or a Maps URL so that I do not need to understand the app's internal modes first.

Acceptance Criteria:
- [x] User can paste a Maps URL, type a shop name, or type a broad need from the first visible input.
- [x] UI recommends the detected mode: Scout, Shop, or Ask, with a one-sentence reason.
- [x] User can accept the recommendation and start the job in <=2 clicks.
- [x] Existing `#scout/#shop/#library/#ask` deep links still work.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

Implementation note 2026-06-14: Completed in v0.4.27 by adding Scout-page
command-mode chips, local mode recommendation, first-input routing into Shop and
Ask, and exact fresh-history reuse before duplicate Scout submission. Coverage:
focused command-center Playwright tests plus the full UI smoke matrix.

### US-002: Read a Dossier Like a Decision Brief

As a user standing near a business, I want the dossier to lead with facts, risk, confidence, and a 30-second walk-in brief so that I can act before reading the full report.

Acceptance Criteria:
- [x] Dossier first viewport contains: place name, rating/review count, cache freshness, activity risk, top 3 walk-in bullets, and Ask-this-shop.
- [x] Generated report remains available and complete; no report sampling or coverage regression.
- [x] Raw reviews remain original text; translations remain display-layer only.
- [x] Dossier modal keeps focus trap, Escape close, opener restoration, `role="dialog"`, `aria-modal`.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

Implementation note 2026-06-15: Completed in v0.4.30 via the UI PRD
`US-UI-004` milestone. The dossier now opens with a compact decision brief
derived from saved report JSON and listing facts, while the complete report,
review lens, original reviews, opt-in translation, and focus-trap behavior stay
intact.

### US-003: Ask With Evidence, Not Vibes

As a user asking follow-up questions, I want answers to show which listing facts and review snippets were used so that I can judge trust quickly.

Acceptance Criteria:
- [x] Ask answer includes separate "Listing facts used" and "Review evidence used" sections when available.
- [x] Cached-answer banner preserves exact-scope semantics and shows why reuse is safe.
- [x] Scoped dossier questions remain visible in top-level Ask history with shop names.
- [x] `--fresh` and "重新推理" still bypass QA cache without deleting cached history.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

Implementation note 2026-06-15: Completed in v0.4.31 via the UI PRD
`US-UI-005` milestone. Fresh Ask responses now expose `cache_scope`,
`evidence_fresh_after`, and listing/review evidence cards through `/api/ask`
and CLI JSON; the web answer card keeps the answer first, then separates
listing facts from review evidence. Cached answers retain exact-scope reuse and
the existing `重新推理` bypass path.

### US-004: Compare Places Before Choosing

As a user choosing among multiple candidates, I want a comparison board so that price, risk, evidence volume, freshness, and fit can be scanned side by side.

Acceptance Criteria:
- [ ] User can select 2-5 cached places from Scout results or Library.
- [ ] Comparison shows listing facts, review count, cached count, latest scrape, report verdict, activity risk, low-rating themes, and top evidence tags.
- [ ] No new report is generated if current reports are fresh under existing cache rules.
- [ ] A compare board links back to each shop dossier.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-005: Agent-Native CLI/API

As another agent, I want stable machine-readable commands and endpoints so that I can call `placeintel` without scraping the UI or interpreting human text.

Acceptance Criteria:
- [x] Every read-only data command supports `--format json`.
- [x] Long-running operations can emit NDJSON events with the existing `{t, stage, msg, data?}` contract.
- [ ] CLI has stable exit codes and a documented `placeintel doctor` command.
- [x] API schemas and examples are documented in `docs/API.md` and `docs/agent-cli.md`.
- [x] Agent examples run without requiring a browser.
- [ ] Typecheck/lint passes.

### US-006: Production Operations Are Visible

As the product owner, I want health, provider status, backups, and deploy smoke results to be visible so that I can trust the product outside a coding session.

Acceptance Criteria:
- [x] `/api/health` returns fast local health without model calls.
- [x] `/api/health/deep` or CLI `doctor --live` verifies provider/model/scraper availability safely.
- [x] SQLite backup and restore commands are documented and tested on a temp DB.
- [x] Deploy runbook verifies protected domain, Basic Auth, `/api/meta`, `/api/health`, one read-only UI flow, and logs.
- [x] Typecheck/lint passes.

## 4. Functional Requirements

### 4.1 Product and UI

- FR-001: The app must preserve the four top-level views and hash contract: `#scout`, `#shop`, `#library`, `#ask`.
- FR-002: The first visible Scout surface must include past scouts, mode recommendation, and a start action without creating duplicate scraping work.
- FR-003: The Shop flow must accept both plain names and Google Maps URLs, preserving the current target-picking and cache-hit behavior.
- FR-004: Library must support scan-friendly filters: freshness, risk, category, report profile, cached review count, language cohorts, and favorites.
- FR-005: Dossier must lead with a compact decision brief before long report content.
- FR-006: Review lens must combine language, rating, topic, and translation controls without overwriting original review text.
- FR-007: Ask must show evidence cards and preserve exact-scope cache safety.
- FR-008: Compare mode must reuse cached places and reports before generating anything new.
- FR-009: Every UI action that can cost API credits or mutate cache must show a clear state and recovery path.
- FR-010: Every dynamic text path must keep using `esc()` or safe DOM text APIs because reviews are hostile scraped input.

### 4.2 Data and Contracts

- FR-011: API response shapes used by the web UI and CLI must be documented in `docs/API.md`.
- FR-012: Job events must keep the existing stage enum: `plan`, `search`, `filter`, `reviews`, `embed`, `report`, `done`.
- FR-013: Job events may add fields but must not remove `t`, `stage`, or `msg`.
- FR-014: Long-running jobs must get a durable row in SQLite before thread start.
- FR-015: Job status must survive server restart at least as `done`, `error`, or `interrupted`.
- FR-016: Reports must state review coverage and preserve the all-cached-review analysis rule.
- FR-017: QA cache validity must remain exact-scope and tied to newest review scrape.
- FR-018: Review translations must remain keyed by raw text hash and target language.
- FR-019: Activity risk remains deterministic first and cautious in wording.
- FR-020: Model availability must remain live-provider queried and smoke-tested before persistence.

### 4.3 Agent CLI/API

- FR-021: Add a global CLI output option: `--format text|json|ndjson` where applicable.
- FR-022: Add `--quiet`, `--no-color`, and `--timeout` for automation-safe use.
- FR-023: Add `placeintel doctor` with `--json`, `--live`, and `--require` checks.
- FR-024: Add machine-readable job commands: submit, status, watch, cancel if cancellation is implemented.
- FR-025: Add `placeintel schema` to print JSON schema snippets for CLI/API payloads.
- FR-026: CLI JSON must not include ANSI color or unescaped logs.
- FR-027: CLI NDJSON streams one JSON object per line and never mixes human prose on stdout.
- FR-028: Human logs go to stderr when `--format json|ndjson` is active.

### 4.4 Operations

- FR-029: Add `/api/health` for cheap health and `/api/health/deep` or equivalent for live provider/scraper checks.
- FR-030: Add structured logs for job lifecycle, provider calls, scraper fallbacks, cache hits, and user-visible failures.
- FR-031: Add backup and restore procedures for `data/placeintel.db`, reports, settings, and scraper DB.
- FR-032: Add startup validation for required keys only when the feature path needs them; local read-only Library should still load with missing live keys.
- FR-033: Add rate/cost guardrails for protected web deployment.
- FR-034: Add privacy controls: data export, cache delete, favorite refresh opt-in, and no telemetry by default.
- FR-035: Add post-deploy verification runbook and automated smoke for the protected public domain.

## 5. Non-Goals

- NG-001: Do not build multi-user SaaS accounts, billing, teams, or public onboarding in this PRD suite.
- NG-002: Do not replace the existing free-scraping-first architecture with official Places-only summaries.
- NG-003: Do not change provider routing: embedding stays Google official, reasoning stays VectorEngine unless the user changes settings.
- NG-004: Do not store translated reviews as original evidence.
- NG-005: Do not relax QA cache scope safety to make history simpler.
- NG-006: Do not infer reviewer country from review language.
- NG-007: Do not introduce React/Vite/Tailwind in the first implementation pass unless the web line-budget gate proves the no-build shell cannot carry the planned UI.
- NG-008: Do not expose the protected web app publicly without authentication and cost controls.

## 6. Stack and Dependencies

### 6.1 Wheel Check Summary

| Area | Decision | Evidence |
| --- | --- | --- |
| Place discovery | Keep `gosom/google-maps-scraper` | GitHub: 4,324 stars, updated 2026-06-14; already integrated via Docker |
| Deep review scraping | Keep `georgekhananaev/google-reviews-scraper-pro` | GitHub: 251 stars, updated 2026-06-14; incremental DB and SeleniumBase path already hardened |
| Official Places summaries | Reference, not replacement | Google now offers Gemini AI place/review summaries, but app's edge is full local review evidence |
| UI framework | Keep no-build SPA for first pass | Project hard rule: `web/index.html`, `web/app.css`, `web/app.js`, each <800 lines |
| Streaming job progress | Prefer native FastAPI `StreamingResponse`/SSE | Official FastAPI docs support streaming responses/SSE patterns; no new dependency needed first |
| CLI library | Keep `argparse` first, evaluate Typer later | Typer is strong and current, but existing CLI is stdlib and small; agent mode mainly needs output contracts |
| Tests | Keep Python unittest + Playwright | Existing CI/deploy gate uses both and matches current web architecture |

### 6.2 Dependency Table

| Dependency | Version / Source | Purpose | Status | Why |
| --- | --- | --- | --- | --- |
| `fastapi` | `>=0.110` optional `[web]` | Web API and static shell | Keep | Already deployed and tested |
| `uvicorn` | `>=0.29` | Local/prod web server | Keep | Existing `placeintel-web` entry point |
| `google-genai` | `>=1.0` | Gemini embedding/reasoning/translation | Keep | Provider routing is a locked decision |
| `pyyaml` | `>=6.0` | Report profiles | Keep | Profiles are the extension mechanism |
| `numpy` | `>=1.26` | Local vector search | Keep | Simple and adequate below 100k reviews |
| `requests` | `>=2.31` | External HTTP calls | Keep | Existing stack |
| `@playwright/test` | `^1.56.1` | Web smoke and accessibility regressions | Keep | Owns key UI contracts |
| `typer` | GitHub 19k+ stars, current | Potential CLI DX migration | Reject for Phase 1 | Adds dependency without solving agent output contracts |
| `fastapi-sse` | small third-party library | SSE helper | Reject for Phase 1 | Native streaming is enough until proven otherwise |

### 6.3 Build-vs-Buy

- Build: JSON/NDJSON CLI output, health schemas, comparison view, evidence cards, job persistence, settings UI, because these are product-specific.
- Reuse: current scrapers, FastAPI, Playwright, provider SDK, SQLite.
- Defer: full frontend framework, queue system, Redis, multi-user auth, hosted analytics.

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Feature | Likely Files Touched | GitNexus Risk | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| CLI command parser and human commands | `placeintel/cli.py` | LOW for `main` | `python -c "import placeintel.cli"` plus command snapshots | Add/extend |
| Scout pipeline and event contract | `placeintel/pipeline.py` | LOW for `scout_single`, but core product flow | Unit tests + one smoke with cached DB; live full scout only when pipeline changes | Partial |
| Ask cache and scoped history | `placeintel/pipeline.py`, `placeintel/cache.py`, `placeintel/server.py`, `web/app.js` | LOW by symbol, high product sensitivity | Server contract tests for exact/global/all scopes + Playwright Ask history | Yes |
| Dossier rendering | `web/app.js`, `web/app.css`, `web/index.html` | HIGH for `renderDetail` | Playwright: open detail, focus trap, ask form, review filters, translation, mobile | Yes, expand |
| API consumers in web shell | `placeintel/server.py`, `web/app.js` | LOW per route, one dense consumer file | `route_map`, API contract tests, Playwright smoke | Partial |
| Web line-budget rule | `web/app.js`, `web/app.css` | Project hard rule | `wc -l` or existing static contract | Yes |
| Provider/model settings | `placeintel/config.py`, `server.py`, `web/app.js` | Medium product risk | Fake model rejection, live model list graceful failure, `/api/meta` | Yes |
| Protected deployment lane | `.github/workflows/deploy-contabo.yml`, `deploy/remote-bootstrap.sh` | Operational risk | CI local gate, SSH deploy smoke, protected-domain auth rejection smoke | Partial |

### 7.2 Security Hardening

| Attack Surface | Threat | Mitigation | Verification |
| --- | --- | --- | --- |
| Scraped review text | HTML/script injection | Continue `esc()` for every dynamic string; no raw review HTML | Static contract and Playwright XSS fixture |
| API keys | Leak through UI/logs/docs | Provider info never returns keys; `.env*` gitignored; docs use variable names only | Secret scan before public push |
| Protected web app | API credit abuse | Basic Auth remains; add rate/cost controls before broader exposure | Protected domain smoke and unauthenticated 401 check |
| Delete endpoints | Accidental data loss | Confirm UI; CLI `--yes` required for destructive calls; backup docs | Playwright and CLI tests |
| SQLite DB | Corruption during backup/job writes | Use SQLite transactions; backup via SQLite backup API or `.backup`, not raw copy during writes | Temp DB backup/restore test |
| Model prompts | Prompt injection from reviews | Treat reviews as evidence, never instructions; keep system prompts explicit | Unit prompt snapshot |

### 7.3 Error Boundaries

| Component | Failure Mode | User Experience | Recovery |
| --- | --- | --- | --- |
| AI planner/filter | Provider down | Raw query passthrough / keep all candidates | Existing fail-open behavior preserved |
| Report reasoning | transient 429/5xx/timeout | Retry shown in timeline | Existing retry wrapper preserved |
| Embedding | provider error | Report can still run; Ask may degrade | Event says vectorization failed but report unaffected |
| Review scraper | Selenium/Chrome failure | Place warning, rest of batch continues | SerpAPI fallback when enabled |
| Web server restart | In-memory jobs lost | New durable job table marks `interrupted` | User can resume/retry with cache hits |
| SSE unsupported | Stream fails | Polling fallback to `/api/jobs/{id}` | UI switches automatically |

## 8. UI/UX Architecture

Detailed UI requirements live in `tasks/prd-placeintel-world-class-ui-ux.md`.

### 8.1 Audience Map

| Audience | Primary Goal | Entry Point |
| --- | --- | --- |
| Traveler / shopper | Decide whether to visit and what to ask | Command center, shared URL, phone |
| Product owner | Maintain cache, favorites, model choices, deployment | Library, Settings/System |
| Future agent | Call functions, fetch evidence, diagnose health | CLI/API, docs/API.md |
| Developer/operator | Deploy, verify, recover, inspect logs | CLI doctor, `/api/health`, runbooks |

### 8.2 Page/View Inventory

| View | Type | Purpose |
| --- | --- | --- |
| Command Center / Scout | tab view | Intent input, mode recommendation, past scouts, live job |
| Shop | tab view | Single-place deep dive |
| Library | tab view | Cache browser, filters, favorites, compare entry |
| Ask | tab view | Global and scoped Q&A history |
| Dossier | modal dialog | Place facts, walk-in brief, report, Ask, raw evidence |
| Compare | inline/overlay | Side-by-side decision board |
| Settings/System | tab or modal | Models, language, cache, provider health, privacy |
| Agent docs | docs/CLI/API | Machine interface contract |

### 8.3 Shared State Contract

| State Key | Owner | Subscribers | Update Mechanism |
| --- | --- | --- | --- |
| `profiles[]` | `/api/profiles` | Scout, Shop | Startup fetch |
| `places[]` | `/api/places` | Library, Compare, Dossier links | Fetch on Library and job completion |
| `searches[]` | `/api/searches` | Scout past scouts, Library history | Fetch on Scout/Library and job completion |
| `qa_history[]` | `/api/qa` | Ask, Dossier | Fetch on Ask/Dossier open and Ask completion |
| `job.events[]` | `/api/jobs` or SSE | Scout/Shop timelines, CLI watch | Stream/poll |
| `provider_info` | `/api/meta` | Footer, Settings, CLI doctor | Startup fetch + settings save |
| `translationTarget` | localStorage / future setting | Review cards | Immediate DOM update |

## 9. Design System

Detailed design requirements live in `tasks/prd-placeintel-world-class-ui-ux.md`.

Visual direction: editorial field notebook + operational command center. Preserve the current paper/ink/red identity but make information density more scannable and mobile-native.

| Token | Light | Dark | Usage |
| --- | --- | --- | --- |
| `--paper` | `#f7f5ef` approx / current `oklch(97% 0.005 90)` | `#171720` approx / current `oklch(20% 0.01 270)` | Page background |
| `--ink` | `#303038` approx | `#ecebe5` approx | Primary text |
| `--accent` | `#c8473d` approx | `#e47a62` approx | Primary actions, risk emphasis |
| `--accent-soft` | `#f1d9d2` approx | `#3c2626` approx | Selection, subtle badges |
| `--ok` | `#4c8f6c` approx | `#8bc8a4` approx | Success/verified |
| `--line` | `#d8d6d0` approx | `#484852` approx | Borders |

Typography:
- UI body: system sans with PingFang SC.
- Product title / labels / data chips: SF Mono or ui-monospace.
- Report body: existing Markdown-rendered report typography; keep readable line length under 72 characters desktop.

Motion:
- Keep existing `--dur-fast: 150ms`, `--dur: 300ms`, `--ease: cubic-bezier(0.16, 1, 0.3, 1)`.
- Do not animate report text, raw review lists, or job event insertion beyond small opacity/position changes.

## 10. Responsiveness

Required verification matrix:

| View | 375px | 390px | 768px | 1024px | 1440px | Dark |
| --- | --- | --- | --- | --- | --- | --- |
| Command Center | required | required | required | required | required | required |
| Dossier | required | required | required | required | required | required |
| Compare | required | required | required | required | required | required |
| Ask | required | required | required | required | required | required |
| Settings/System | required | required | required | required | required | required |

No horizontal scroll. Touch targets >=44px. Button text must not clip in Chinese or English.

## 11. Health, Monitoring, and Logging

Detailed operational requirements live in `tasks/prd-placeintel-production-ops.md`.

Required health checks:
- `/api/health`: process alive, DB open, data dir writable, app version, no provider calls.
- `/api/health/deep`: model list, tiny reasoning ping, embedding ping, Chrome/scraper availability, Docker/gosom availability, SerpAPI optional state.
- CLI `placeintel doctor --json`: same as health checks, browser-free.

Required logs:
- job_started, job_event, job_finished, job_failed
- provider_retry, provider_failure, provider_model_switch
- scraper_primary_failed, scraper_fallback_used
- qa_cache_hit, qa_cache_miss, qa_cache_invalidated
- review_translation_hit, review_translation_generated

## 12. Analytics and Privacy

- No external analytics by default.
- Local-only usage counters may be stored in SQLite if they help product diagnostics.
- Any future telemetry must be opt-in, disableable, and documented.
- Never send raw review cache, personal notes, local paths, or API keys to a telemetry endpoint.

## 13. Implementation Principles

1. Existing-project-first: read `AGENTS.md`, `VAULT.md`, `task_plan.md`, `findings.md`, and the relevant PRD before editing.
2. Contract-first: update `docs/API.md` and `docs/agent-cli.md` before changing API/CLI shapes.
3. No-build SPA discipline: keep `web/index.html`, `web/app.css`, `web/app.js` under 800 lines unless a separate approved architecture PRD updates `AGENTS.md`.
4. Event transparency: do not remove existing job event emits.
5. Fail-open AI: planner/filter failures must not block scraping.
6. Evidence integrity: original reviews stay original; translations are display-layer.
7. Scope safety: QA cache reuse is exact-scope only.
8. Every meaningful implementation milestone updates PRD status, `progress.md`, and `CHANGELOG.md`.

## 14. Documentation Requirements

Implementation must create or update:

- `docs/API.md`: HTTP endpoints, payloads, response examples, error shapes.
- `docs/agent-cli.md`: CLI commands, JSON/NDJSON contracts, exit codes, examples.
- `docs/operations.md`: health, backups, restore, deploy smoke, rollback.
- `AGENTS.md`: add any new state contract, component reuse map, view-interface dependencies.
- `CHANGELOG.md`: user-facing changes per completed story.
- `progress.md`: dated proof and verification notes.

## 15. Technical Considerations

- Current web files are already near line budget: observed `web/app.css` 795 lines and `web/app.js` 779 lines.
- Major UI work must start with a line-budget strategy: compact existing code, remove duplication, or write a separate architecture PRD to allow no-build ES modules.
- Current server jobs are in-memory; durable jobs are required before the app can claim production-grade restart behavior.
- Current API has no auth because server binds loopback and protected deployment uses Basic Auth. Broader public exposure requires auth/rate-limit PRD first.
- Official Google Places policies require correct attribution when official Places data is displayed. The app should preserve source links and be conservative about attribution even when data is scraped/cached.

## 16. Success Metrics

- User can run a new Scout, open a dossier, ask a scoped question, compare two places, and export evidence from CLI without errors.
- Next agent can call `placeintel doctor --json`, `placeintel scout --format ndjson`, `placeintel job status --json`, and `placeintel export --format json` from docs alone.
- Playwright suite covers core UI at mobile and desktop, modal accessibility, Ask, compare, filters, translation, and settings.
- Full local verification passes: Python unit tests, Playwright web smoke, compileall, CLI import, profiles command, JS syntax, line budget, `git diff --check`.
- Production smoke passes through protected domain or SSH tunnel: `/api/meta`, `/api/health`, one Library load, one dossier open, no server log error spike.

## 17. Open Questions

| Question | Default Decision | Who Can Override |
| --- | --- | --- |
| Should the no-build SPA remain 3 files after v0.5? | Yes for first production pass; only change with separate architecture PRD | User |
| Should protected public domain stay Basic Auth only? | Yes until multi-user/auth PRD exists | User |
| Should scheduled refresh run automatically? | Favorites only, opt-in, with cost guardrails | User |
| Should Typer replace argparse? | No for first pass; add output contracts first | Implementing agent after CLI complexity review |

## 18. Deployment and Configuration

Deployment profile: hybrid.

Environment matrix:

| Environment | Purpose | URL/Host | Data Source | Secrets Source |
| --- | --- | --- | --- | --- |
| local | development and personal use | `http://127.0.0.1:9618` | `./data` | `.env`, local skill fallback |
| private VPS | protected remote use | loopback service + SSH tunnel or protected domain | VPS app data dir | GitHub Secrets + remote `.env` |
| protected domain | browser access | `https://PLACEHOLDER_PROTECTED_DOMAIN` | same VPS service | Basic Auth and service env |
| public mirror | code only | GitHub public repo | none | no deploy secrets |

Must-haves before production-ready claim:
- complete `.env.example`, including `PLACEINTEL_TRANSLATION_MODEL`, `PLACEINTEL_PORT`, and production-only vars if added.
- `/api/health`.
- backup/restore runbook.
- post-deploy smoke.
- rollback instructions under 60 seconds.
- secret scan before public push.

## 19. Next-Agent `/goal` Handoff

Use this goal after the PRD suite is reviewed:

```text
/goal Implement the placeintel production-grade PRD suite.

First action: read AGENTS.md, VAULT.md, tasks/prd-placeintel-production-grade-master.md, tasks/prd-placeintel-world-class-ui-ux.md, tasks/prd-placeintel-agent-cli-api.md, tasks/prd-placeintel-production-ops.md, then report the user-story count and the first milestone you will implement.

Scope: placeintel product hardening only: web/, placeintel/, tests/, docs/, deploy/, README.md, CHANGELOG.md, progress.md, task_plan.md, AGENTS.md when required.

Constraints:
  - Preserve provider routing: embedding Google official, reasoning VectorEngine.
  - Preserve exact-scope QA cache, all-review report coverage, original review storage, fail-open AI planning/filtering, and job event stage contract.
  - Keep web/index.html, web/app.css, web/app.js under 800 lines unless you first write and get approval for an architecture PRD that updates AGENTS.md.
  - Do not touch data/ or vendor/ by hand. Do not commit secrets or real private deploy values.
  - Use GitNexus impact before editing symbols and detect_changes before commits.

Done when:
  1. Each PRD user story implemented or explicitly deferred in the PRD with reason.
  2. docs/API.md, docs/agent-cli.md, and docs/operations.md exist and match implemented contracts.
  3. Python unit tests, Playwright web tests, compileall, CLI smoke, JS syntax, line-budget, and git diff whitespace checks pass.
  4. Runtime proof covers local web UI and agent CLI JSON/NDJSON examples.
  5. CHANGELOG.md, progress.md, task_plan.md, and relevant AGENTS.md rules are updated.

Stop if:
  - Any existing test fails and the fix would require weakening or deleting that test.
  - A change would relax QA scope safety, all-review coverage, provider routing, original review storage, or fail-open planning.
  - Required secrets/provider access are missing after local/env/1Password/notion checks.
  - Web UI work cannot fit the 800-line per-file rule without an approved architecture update.
```

## 20. Reference Links Used

- Google Maps with Gemini and Ask Maps direction: https://blog.google/products-and-platforms/products/maps/ask-maps-immersive-navigation/
- Google Maps Platform AI-powered place/review summaries: https://developers.google.com/maps/documentation/places/web-service/review-summaries
- Google Places API policies and attribution: https://developers.google.com/maps/documentation/places/web-service/policies
- WAI-ARIA modal dialog pattern: https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/
- FastAPI custom/streaming responses and SSE docs: https://fastapi.tiangolo.com/advanced/custom-response/ and https://fastapi.tiangolo.com/tutorial/server-sent-events/
- Typer official docs, evaluated but deferred: https://typer.tiangolo.com/
- Material Design 3 color/tokens reference: https://m3.material.io/styles/color/overview and https://m3.material.io/foundations/design-tokens
