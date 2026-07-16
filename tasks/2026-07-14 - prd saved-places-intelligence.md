# PRD: Saved Places Intelligence

Created: 2026-07-14
Last Updated: 2026-07-16
Status: 🔨 In Progress — US-001 real Takeout E2E complete; US-002–004 pending
Feature Type: Backend, local data import, agent-facing CLI, and production integration
Owner: Vec + Codex
Deployment Profile: hybrid
Deploy Targets: local PlaceIntel CLI/SQLite and the existing protected VPS/systemd runtime
Related PRDs:
- `tasks/prd-placeintel-agent-cli-api.md`
- `tasks/prd-placeintel-production-ops.md`
- `tasks/2026-07-11 - prd production-trust-hardening.md`
Source Design:
- 2nd Brain `02 - Processing/initiatives/2026-07-13-google-maps-saved-places-intelligence/00-workbench.md`

## 1. Introduction

Vec has many Google Maps saved lists across cities. Some entries remain current,
some are renamed or closed, and some degraded to a coordinate-only pin. Manually
opening lists cannot reliably answer a narrow question such as: which places Vec
already saved near the current location in Da Nang are still operating, suitable
for a date, and supported by price evidence around 100k-200k VND?

This feature adds a private, auditable saved-place layer to PlaceIntel. Google
Takeout is the V1 source. Import is offline and idempotent; original saved data is
kept separate from current PlaceIntel truth; later resolution and recommendation
steps consume stable records through machine-readable CLI contracts.

### Approved Direction

Vec approved the prior workbench recommendation on 2026-07-14 and asked to begin
a real production build after checking access. This PRD is a conversation
synthesis and implementation tracker, not a fresh product interview.

### Assumptions

- V1 imports Google Takeout products `Saved` (`data-id=save`) and `Maps (your
  places)` (`data-id=local_actions`). It does not require Data Portability OAuth.
- The candidate universe is saved-only unless a future command explicitly says
  otherwise.
- Budget basis is required or explicitly defaulted by the caller; the system does
  not silently assume per-person versus total-for-two.
- Query origin is supplied at runtime as coordinates or a place/area string.
- The existing SQLite, CLI JSON envelope, provider routing, backup, systemd, and
  deploy-smoke contracts remain the owners of their current concerns.

## 2. Goals

- G1: Import a real Takeout directory, ZIP, or CSV without uploading it to a
  third party and without mutating Google Maps.
- G2: Re-import the same archive with zero duplicate collections, items, or
  memberships and with deterministic counts.
- G3: Preserve source title, URL, collection, description, note, tags, comment,
  row provenance, and import hash separately from current place truth.
- G4: Classify each saved item as `pending`, `resolved`, `renamed`,
  `temporarily_closed`, `permanently_closed`, `coordinate_only`, `ambiguous`,
  `not_a_place`, or `failed` without destroying its source record.
- G5: Return saved-only Da Nang date-place candidates with current status,
  distance, category, price/budget evidence, date-fit evidence, and
  last-verified timestamps.
- G6: Keep the workflow usable by a human through clear CLI inventory/review
  output and callable by agents through stable JSON.

### Initial Measured Baseline And Targets

| Metric | Baseline | Target |
| --- | --- | --- |
| Python regression suite | 129 tests pass at feature-branch baseline | all existing plus new tests pass |
| Existing local Takeout archive | none found in Downloads or CloudStorage | one real private archive imported for E2E |
| Google Maps access | correct account is logged in; many private lists are visible | narrow Takeout export can be requested without new login setup |
| Repeat import | no importer | second identical import creates zero new logical records |
| Saved-only guarantee | no saved corpus contract | every recommendation proves at least one saved membership |
| Source mutation | manual Maps UI only | importer and resolver never mutate Google Maps |

## 3. User Stories

### US-001: Offline Takeout Import And Inventory

As Vec, I want to import my Takeout saved-place files locally so that every list
and membership becomes auditable without opening Google Maps one list at a time.

Acceptance Criteria:
- [x] Directory, ZIP, individual CSV, and the official Maps `Starred places` /
  `Saved Places` GeoJSON names are supported.
- [x] Official `title`, `item_content_url`, `note`, `tags`, `comment`, and optional
  first-line collection description are parsed case-insensitively.
- [x] UTF-8 BOM, Unicode list names, missing optional columns, blank rows, and
  non-place saved links are handled deterministically.
- [x] Import stores stable collections, items, memberships, and one import-run
  receipt with counts and archive/file hashes.
- [x] Re-importing identical input creates zero duplicate logical records.
- [x] Invalid/truncated/unsafe archives fail atomically and preserve prior data.
- [x] Multiple account exports can use opaque source labels so same-named lists
  stay separate; matching prior unlabelled imports can be adopted only after
  source-file digest verification.
- [x] Text output is human-readable and JSON output uses the existing CLI envelope.
- [x] Compile, contract, focused, and full regression gates pass.

US-001 real-data E2E completed locally on 2026-07-16. The approved private
two-product archive produced 88 collections, 4,037 unique items, and 4,097
memberships; its second import created zero logical records. Five blank/tag-only
placeholders were skipped and receipted, while the 2,132-row `Saved Places.json`
member was parsed under its current official filename. The archive remains
outside the repository and no provider, browser, or deployment action was used.

Account-scoped E2E completed locally on 2026-07-16: the legacy corpus was
adopted without logical duplicates, while a second localized-name archive added
one collection, 47 memberships, and 38 previously unseen items. The localized
review GeoJSON was excluded by strict schema. Repeating each scoped import
created zero logical records; the private aggregate is 89 collections, 4,075
items, and 4,144 memberships.

### US-002: Current-Truth Resolution And Review Queue

As Vec, I want each saved record reconciled with current Maps/PlaceIntel truth so
that renamed, closed, ambiguous, and coordinate-only entries are explicit.

Acceptance Criteria:
- [ ] Resolution is opt-in, bounded, resumable, and dry-run-first.
- [ ] Exact Maps URLs and existing PlaceIntel `place_id` matches are reused before
  any provider or browser work.
- [ ] Source data is immutable; resolution fields are additive and timestamped.
- [ ] Permanently closed items are excluded by default; temporary closure is
  separately represented; ambiguous/coordinate-only items enter a review queue.
- [ ] Provider failure leaves the item retryable and does not corrupt memberships.
- [ ] Resolution output includes counts by state and no private note text in logs.
- [ ] Typecheck/lint passes.

### US-003: Saved-Only Date Recommendation

As Vec, I want to query my saved places near a supplied Da Nang origin so that I
receive a short, evidence-backed date shortlist instead of manually checking lists.

Acceptance Criteria:
- [ ] Only records with a saved membership are candidates.
- [ ] Query accepts origin, radius, café/restaurant categories, budget minimum,
  budget maximum, currency, and budget basis (`per_person` or `total_for_two`).
- [ ] Results show distance, current business status, price evidence quality,
  date-fit evidence, saved collections, and verification timestamp.
- [ ] Permanently closed results are excluded; unknown/temporary status and weak
  budget evidence are clearly flagged rather than silently normalized.
- [ ] Stable JSON supports agent calls; text mode explains why each result ranks.
- [ ] A real Da Nang run manually verifies at least five source records and the
  final shortlist contains no unsaved place.
- [ ] Typecheck/lint passes.

### US-004: Private Production Operation And Recovery

As the operator, I want repeatable export, import, backup, deploy, and rollback
gates so that the feature survives updates without leaking the private archive.

Acceptance Criteria:
- [ ] Operations docs provide the narrow Takeout route for `save,local_actions`;
  final export creation remains a deliberate account action.
- [ ] Raw archives and extracted CSVs remain outside git and outside public logs.
- [ ] Existing backup/restore covers saved-place tables through the SQLite DB.
- [ ] GitHub Actions deploy, SSH/systemd, rollback, and deploy-smoke use existing
  owners rather than a second deployment path.
- [ ] Production health and one saved-inventory smoke pass after deploy.
- [ ] Version and CHANGELOG are updated only when all release criteria pass.
- [ ] Typecheck/lint passes.

## 4. Functional Requirements

- FR-001: `saved_import_runs` must record a stable run id, source digest, status,
  bounded counts (including identity-less placeholder skips and legacy adoption),
  timestamps, an opaque source label when supplied, and error code without
  storing raw private values or account addresses in operational logs.
- FR-002: `saved_collections` must use a stable identity derived from source product,
  optional opaque source label, and normalized collection name while preserving
  original name and description.
- FR-003: `saved_items` must represent one logical saved target independent of the
  lists that reference it and independent of its current resolved place.
- FR-004: `saved_memberships` must represent list membership and own membership-level
  note, tags, comment, source file digest, and row number.
- FR-005: The logical item key must prefer a normalized Maps/content URL and fall
  back to a content fingerprint when a URL is absent.
- FR-006: Multiple collections may reference the same item; repeated membership in
  the same collection must upsert instead of duplicate.
- FR-007: Import must validate ZIP paths, reject links/traversal, cap files, rows,
  per-file bytes, and total expanded bytes, and use parameterized SQL only.
- FR-008: One import is atomic. Failure or interruption must leave previously
  committed corpus data unchanged and mark the run retryable/failed.
- FR-009: Re-import is idempotent and updates `last_seen_at` without deleting items
  absent from a newer snapshot. Deletion/tombstoning requires a separate decision.
- FR-010: `saved_places.resolve_saved_item()` is the single resolution owner;
  callers and future UI must consume its stored result and must not re-resolve.
- FR-011: Resolver transitions must be explicit and timestamped; source title/URL,
  collection membership, notes, tags, and comments remain unchanged.
- FR-012: Recommendation prefiltering must be deterministic before AI reasoning:
  saved membership, status, geography, category, and budget evidence boundaries.
- FR-013: AI may explain/rank evidence but may not introduce unsaved candidates or
  convert unknown price/status into a confirmed claim.
- FR-014: CLI commands must follow current JSON/text exit-code contracts and must
  accept global `--format`, `--quiet`, `--no-color`, and `--timeout` behavior.
- FR-015: Existing backups require no second archive mechanism because SQLite is
  already included; raw Takeout files are deliberately excluded.
- FR-016: Every external provider step must be opt-in, bounded, checkpointed, and
  retryable. Offline inventory must require no API key, Docker, model, or browser.
- FR-017: No import, resolution, recommendation, or test may mutate a Google Maps
  list, share a private list, upload a Takeout archive, or print credentials.

### Data Resolution Contracts

| Data Type | Resolution Logic | Resolution Owner | Fallback Chain | Consumers |
| --- | --- | --- | --- | --- |
| Import input | safe directory/ZIP/CSV discovery and official schema aliases | `saved_places.iter_takeout_rows()` | declared fields -> case-insensitive aliases -> actionable parse error | import CLI/tests |
| Logical saved item | normalized content URL, else content fingerprint | `saved_places.saved_item_id()` | canonical URL -> title/note fingerprint | importer, inventory, resolver |
| Current place truth | exact cached identity before bounded refresh | `saved_places.resolve_saved_item()` | cached `place_id` -> exact Maps URL -> PlaceIntel single-place flow -> review state | resolver, recommendation |
| Recommendation candidate | saved membership plus deterministic current filters | `saved_places.recommend_saved_places()` | strict evidence -> flagged unknown -> excluded closed/unsaved | CLI/agent callers |

## 5. Non-Goals

- No Data Portability OAuth app in V1.
- No scraping of Google Maps list DOM as the canonical import source.
- No mutation, cleanup, deletion, or reorganization of Google Maps lists.
- No third-party SaaS upload of the private Takeout archive.
- No new database service, queue, vector store, UI framework, or auth system.
- No automatic deletion merely because a place is absent from a later snapshot.
- No claim that every coordinate-only pin can be recovered automatically.
- No new top-level web view in the first production slice; CLI and existing
  PlaceIntel evidence surfaces are sufficient to prove value first.

### What This Does Not Change

- Existing Scout/Shop discovery, review scraping, report generation, Ask, provider
  routing, language behavior, favorites, and live relevance order.
- Existing place/review/report source records and display-only translation rules.
- Existing protected VPS, systemd service, GitHub Actions deployment, backup,
  rollback, and deploy-smoke paths.

## 6. Stack And Dependencies

Use Python stdlib `csv`, `zipfile`, `hashlib`, `json`, `urllib.parse`, and SQLite.
No new runtime dependency or service is justified. Reuse the existing PlaceIntel
CLI envelope and database connection.

| Decision | Choice | Why | Rejected |
| --- | --- | --- | --- |
| Source | Google Takeout `Saved` + `Maps (your places)` | official, exportable, private, no developer OAuth | Maps DOM scraping: fragile; Data Portability: premature OAuth/policy overhead |
| Parser | stdlib CSV/ZIP | small auditable surface, streamed, no dependency | pandas: unnecessary runtime weight for canonical CSV |
| Storage | additive SQLite tables | existing backupable project owner | Supabase/Postgres: no multi-user need and existing VPS/SQLite are sufficient |
| Resolution | existing PlaceIntel cache/single-place pipeline | reuses current truth and review evidence | second place app or parallel scraper |
| Agent surface | existing CLI JSON envelope | already stable and documented | MCP-only interface: agent-required and harder for humans |

### Configuration Registry

| Key | Default | Type/Tier | UI | Description |
| --- | --- | --- | --- | --- |
| `PLACEINTEL_SAVED_IMPORT_MAX_FILES` | `5000` | int/env | System read-only later | maximum candidate CSV files per import |
| `PLACEINTEL_SAVED_IMPORT_MAX_ROWS` | `250000` | int/env | System read-only later | maximum parsed rows per import |
| `PLACEINTEL_SAVED_IMPORT_MAX_FILE_MB` | `25` | int/env | System read-only later | maximum uncompressed bytes for one supported member |
| `PLACEINTEL_SAVED_IMPORT_MAX_TOTAL_MB` | `1024` | int/env | System read-only later | maximum total uncompressed archive bytes |
| Budget min/max/basis | no hidden default | runtime/CLI | command input | query-specific spending boundary |
| Radius | caller supplied; later preference allowed | runtime/CLI | command input | geographic candidate boundary |

## 7. Safety And Security

### 7.1 Zero-Regression Contract

| Existing Feature | Planned Owner Files | GitNexus Risk | Verification |
| --- | --- | --- | --- |
| CLI parsing/global agent flags | `placeintel/cli.py`, new saved CLI module | LOW (`main`: one direct file caller) | existing CLI JSON suite plus saved command tests |
| SQLite connection/migrations | additive saved schema; avoid changing core tables | LOW (`_migrate`: one direct caller) | cache contract + fresh/legacy DB tests |
| Backup/restore | SQLite file unchanged | operationally medium | existing backup/restore round trip with saved tables |
| Scout/Shop/Ask/favorites | no first-slice behavior change | low | full 129-test baseline and focused CLI tests |
| Deployment | existing workflow/systemd only | operationally high | remote cheap health + deploy-smoke after release |

### 7.2 Security Hardening

| Attack Surface | Threat | Mitigation | Verification |
| --- | --- | --- | --- |
| ZIP input | path traversal, symlink, zip bomb | normalized member paths, regular files only, file/row/expanded-byte caps | malicious archive fixtures |
| CSV values | SQL injection or terminal/log leakage | parameterized SQL; counts/hashes only in logs; text escaping | hostile Unicode/SQL-shaped fixture |
| Source paths | private machine path disclosure | store relative member name or digest; JSON errors redact roots | JSON contract/privacy test |
| Re-import | duplicates or destructive overwrite | deterministic ids and UPSERT; never delete on absence | double-import test |
| Resolution | provider drain/private note leakage | opt-in caps, existing budgets, never send note/comment unless a later contract authorizes it | mock provider and log capture tests |

PlaceIntel remains behind the existing proxy boundary. This feature adds no auth
endpoint, cookie, bearer token, upload API, or public Takeout surface.

### 7.3 Error Boundaries

| Component | Failure | User Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| Input discovery | no supported files | actionable `no_saved_csv` result; no DB mutation | select correct Takeout product/root | count + error code |
| CSV schema | required URL/title identity absent | file/row reported without raw value | correct/export again | file digest + row + code |
| ZIP safety/limit | unsafe or oversized archive | import refused atomically | narrower export or explicit config review | limit name + counts |
| SQLite | migration/write failure | prior corpus preserved | fix disk/schema and retry same input | central DB error path |
| Resolution provider | timeout/unavailable | item stays retryable `failed`; source remains visible | retry bounded queue | item id + safe code |
| Recommendation evidence | unknown status/price | candidate flagged or omitted by explicit strictness | resolve/refresh evidence | aggregate counts only |

## 8. Architecture

The first slice adds a focused `saved_places` domain module and a thin CLI
adapter. The module owns schema creation, safe input iteration, stable identity,
transactional import, inventory, resolution states, and later recommendation.
It consumes `cache.connect()` but does not place Takeout parsing in `cache.py`.

Data flow:

`private Takeout file -> safe bounded parser -> atomic saved corpus tables ->
inventory/review queue -> bounded resolver -> existing places/reviews/reports ->
saved-only recommendation`

No frontend work is required for US-001. A later review UI must consume these
contracts instead of duplicating parser or resolver logic.

## 9. Design

Not applicable to US-001: no new visual surface. Human UX is concise CLI text,
stable exit codes, clear counts, actionable next steps, and machine JSON. Any
later web UI must reuse the existing PlaceIntel `DESIGN.md` and components.

## 10. Responsiveness

Not applicable until a web review surface is approved.

## 11. Health, Monitoring, And Logging

| Event | Level | Component | Safe Data |
| --- | --- | --- | --- |
| `saved_import_started` | info | saved_places | run id, source digest prefix, file count |
| `saved_import_completed` | info | saved_places | counts and elapsed time |
| `saved_import_failed` | error | saved_places | error code, file digest, row number, no raw value |
| `saved_resolution_completed` | info | saved_places | aggregate state counts, provider units |
| `saved_recommendation_completed` | info | saved_places | candidate/result counts, no query/private notes |

Cheap health remains no-cost. A future saved-corpus local check may count tables
and unfinished imports; it must not open archives or call providers. Live
resolution diagnostics stay behind explicit commands.

## 12. Analytics

No external analytics. Import receipts and local aggregate counts are the only
measurement. Raw titles, URLs, notes, comments, precise locations, and archive
paths are excluded from product/ops telemetry.

## 13. Implementation Principles

- Existing project conventions and CLI envelopes win.
- Original saved source and current place truth are separate contracts.
- Offline import is always available without agents, credentials, Docker, or AI.
- Data operations are idempotent, atomic, resumable by retry, and non-destructive.
- New resolution/provider behavior is opt-in, bounded, and budget-aware.
- Schema/interface changes update `docs/API.md`, architecture, tests, and the
  installed PlaceIntel skill in the same release.
- PRD status and `tasks/README.md` change with each verified user story.

## 14. Documentation

- PRD/live tracker: this file.
- Implementation sequence: `docs/superpowers/plans/2026-07-14-saved-places-intelligence.md`.
- Current API/CLI contract: `docs/API.md` and `docs/agent-cli.md`.
- System map: `docs/architecture.md`.
- Operation/Takeout/deploy runbook: `docs/operations.md`.
- 2nd Brain research and approval: linked workbench under the initiative owner.

## 15. Technical Considerations

- Google documents collection descriptions as a first CSV line followed by a
  blank line; exports may omit fields based on user action, so aliases are
  case-insensitive and optional fields remain nullable.
- Google documents Saved collections as CSV and Maps (your places) starred
  places as GeoJSON. The real current export names the latter `Saved Places.json`;
  the importer accepts that explicit filename alongside `Starred places.json`
  without accepting unrelated Maps JSON such as reviews.
- A saved item can belong to many collections; membership cannot be collapsed
  into the current `places` row or favorites table.
- Google official embedding live diagnostics currently stalls at network connect
  on this Mac; US-001 has no embedding dependency.
- Local Docker is currently stopped; exact-place/cache paths and SerpAPI fallback
  remain available, and Docker is a later live-resolution gate.
- The sibling `codex/production-trust-hardening` worktree has unrelated
  uncommitted work. This feature stays isolated and must not overwrite it.

## 16. Success Metrics

- One real private Takeout archive imports successfully.
- Identical second import reports zero newly created logical records.
- Inventory counts reconcile with sampled Google Maps lists.
- At least five Da Nang entries are manually reconciled through current Maps
  evidence, including one closed/coordinate-only/ambiguous case when present.
- A saved-only date query returns an auditable shortlist and zero unsaved places.

## 17. Open Questions

| Question | Current Decision | Unblocker |
| --- | --- | --- |
| Is 100k-200k VND per person or total for two? | No hidden assumption; query requires/records `budget_basis`. | Vec may choose a preferred default after first real run. |
| Should Takeout run once or every two months? | Start with one-time proof; scheduled export is optional after E2E. | Vec after observing update frequency. |
| Should Data Portability OAuth be added? | No in V1; only if Takeout cadence is materially too slow. | Future measured need. |

## 18. Production Readiness And Deployment

### 18.0 Readiness Snapshot — 2026-07-14

| Gate | Status | Evidence Or Non-Secret Pointer | Next Action |
| --- | --- | --- | --- |
| Project/root owner | ready | PlaceIntel root + this PRD; 2nd Brain workbench routes research | keep PRD/router current |
| Architecture/API contract | ready with scoped update due | existing `docs/architecture.md`, `docs/API.md`, agent CLI | update only for shipped saved interfaces |
| Required Google access | ready | correct Maps account and Takeout `authuser=1` verified in Chrome | create narrow export at real-data E2E gate |
| Offline import credentials | n/a | no OAuth/API key required | none |
| Enrichment providers | ready with warning | Google, VectorEngine, SerpAPI configured; reason/translation checks passed before embed check | retry Google embed live check before AI recommendation release |
| Local tools | partial | Chrome/vendor present; local Docker daemon stopped | start Docker before live gosom resolution or use bounded fallback |
| Test/QA gate | ready | 161 Python tests pass after real-format compatibility and receipt-migration regressions | rerun before resolver/recommendation work |
| Source control/CI | ready | GitHub authenticated; private `gmr` repo owns deploy workflow and required secrets | push only after milestone gates |
| Deploy/rollback | ready | SSH works, deploy root exists, systemd service active, operations rollback owner exists | use existing GitHub Actions path only |
| Production verification | ready baseline | remote `/api/health` reports `ok:true`, v0.4.70 | run deploy-smoke and saved-inventory smoke after release |
| Real data artifact | complete locally | narrow archive imported twice into local SQLite; source stays outside git | begin opt-in bounded resolver only when requested |

### 18.1 Environment Matrix

| Environment | Data | Secrets | Saved Archive |
| --- | --- | --- | --- |
| Test | generated fixtures + temp SQLite | none | synthetic only |
| Local | private Takeout + local SQLite | existing local approved env/skill sources | outside git under a private user-selected path |
| Production | imported SQLite corpus | existing GitHub/VPS secret owners | do not deploy raw archive; deploy/restore DB only |

### 18.2 Local Setup

Use the existing editable Python environment and project commands. US-001 tests
must run without `.env`. Real resolution uses the existing approved credential
routes and must pass explicit provider/tool readiness first.

### 18.3 Deploy And Rollback

Use `.github/workflows/deploy-contabo.yml` in the private `gmr` owner, native
systemd, and `deploy/remote-bootstrap.sh`. Do not add manual rsync. Before deploy,
create the existing allow-list backup. Roll back through the documented previous
commit/package path and restore only if additive migration compatibility fails.

### 18.4 Secrets

No new secret is required for US-001. Google login cookies and Takeout files are
never copied into `.env`, code, docs, CI, or Markdown. Existing provider and
deploy secret names remain in their current local/GitHub/VPS owners.

### 18.5 CI/CD

The existing private GitHub workflow remains the production path. The feature
branch must pass unit/contract/security gates before merge; deploy occurs only
from the established owner branch/workflow.

### 18.6 Post-Deploy Verification

1. `placeintel deploy-smoke` proves version, health, static shell, library, and
   representative private API behavior.
2. `placeintel saved-inventory --format json` returns `ok:true` and bounded counts.
3. Backup/restore round-trip proves saved tables persist.
4. One private saved-only query proves zero unsaved results without logging raw
   notes or archive paths.

## Build Progress

- 2026-07-14: Prior design approved; owner and code root resolved; isolated
  `codex/saved-places-intelligence` worktree created at committed baseline.
- 2026-07-14: Baseline 129 Python tests passed. Google Maps/Takeout login, local
  provider config, GitHub deploy secrets, SSH/systemd, deploy root, rollback
  owner, and remote v0.4.70 health were verified without exposing credentials.
- 2026-07-14: Local Docker is stopped and Google embed deep check timed out at
  network connect. Both are recorded as later live-resolution gates; neither
  blocks the offline import implementation.
- 2026-07-14: Implemented official Saved CSV and Maps starred GeoJSON adapters,
  non-extracting ZIP safety, additive saved corpus tables, idempotent import,
  bounded inventory filters, stable CLI JSON, and safe recoverable input errors.
- 2026-07-14: Fixture import proved 3 collections, 3 logical items, and 4
  memberships; the identical second import created zero logical duplicates.
  Backup/restore round-trip retained all saved-place tables.
- 2026-07-14: Requested one Google Takeout export containing exactly the two
  approved products, one-time frequency, ZIP format, and default 2 GB parts.
  Google reports that creation is in progress; no raw archive has entered git.
- 2026-07-14: Independent review found and then closed four import boundaries:
  unknown `(0,0)` coordinates, failed-run receipts, malformed GeoJSON structure,
  and eager corpus materialization. CSV/ZIP rows now iterate with bounded reads,
  defaults are 250k rows/25 MB per member/1 GB total, and global NDJSON is rejected
  rather than silently producing text. The full 158-test suite and focused review
  probes pass; no Critical or Important review blocker remains.
- 2026-07-16: Real archive E2E exposed two current-format boundaries before any
  corpus write: `Saved Places.json` was not recognized and five identity-less
  blank/tag-only rows aborted the transaction. TDD coverage added the explicit
  filename, receipt-schema migration, and placeholder-skip contract. Full 161
  tests pass; backup, first import, identical second import, inventory, and
  cheap local health all passed with no archive extraction, upload, or deploy.
- 2026-07-16: A second-account export exposed localized filenames that could not
  safely be recognized by the prior English-name whitelist. Account-scoped
  receipts, source labels, hash-verified legacy adoption, and strict localized
  saved-place schema detection now preserve separate same-named lists while
  excluding review GeoJSON. Both real archives repeat idempotently.

## Revision History

| Date | Version | Changes | Completed By |
| --- | --- | --- | --- |
| 2026-07-14 | 1.0 | Conversation-synthesis PRD, readiness evidence, and build start | Vec + Codex |
| 2026-07-14 | 1.1 | US-001 fixture-complete import/inventory slice and recovery proof | Codex |
| 2026-07-14 | 1.2 | Boundary hardening and independent-review closure | Codex |
| 2026-07-16 | 1.3 | Real Takeout E2E, current-format compatibility, and receipt audit proof | Vec + Codex |
| 2026-07-16 | 1.4 | Account-scoped multi-export intake and localized-schema compatibility | Vec + Codex |
