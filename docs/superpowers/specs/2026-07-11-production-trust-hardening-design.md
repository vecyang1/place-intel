# Production Trust Hardening Design

Created: 2026-07-11
Status: approved by the user's autonomous-build directive
Owner: Codex

## Decision

Build a bounded in-process production-control layer around the existing
FastAPI/SQLite pipeline, then make AI artifacts content-addressed and
source-verifiable. Preserve the no-build SPA, SQLite, systemd, provider routing,
and current user flows. Keep application authentication in the existing
Supabase Auth PRD.

## Approaches Considered

### A. Minimal locks and log lines

Add a mutex around discovery and a few log messages. This is low effort but
leaves unbounded web threads, no durable queued state, no request coalescing,
no cost ledger, stale vectors, and unsupported report claims. Rejected because
it treats symptoms independently.

### B. Bounded local control plane (selected)

Use a single-process bounded dispatcher backed by the existing SQLite job rows,
cross-process file locks for browser/container resources, a local usage/event
ledger, content-addressed vector/report inputs, and schema-validated evidence.
This matches current scale and deployment, adds no infrastructure service, and
has a clear later migration path to a separate worker.

### C. Redis/Celery/PostgreSQL/vector database

Move jobs, budgets, metrics, and vectors into specialized services. This offers
horizontal scaling but adds deployment, backup, auth, monitoring, and failure
surfaces disproportionate to roughly 1,900 reviews and a small invited team.
Rejected until measured load proves the bounded local design insufficient.

## Components

### Job admission

`placeintel/jobs.py` owns one `BoundedJobRunner` for Scout and Shop. Submission
is serialized, active duplicate requests coalesce by a stable request hash, and
accepted rows move `queued -> running -> done|error|interrupted`. Queue capacity
is finite; rejection returns HTTP 429 with a retry hint and creates no misleading
running row. One worker is deliberate because discovery and Chrome are scarce
single-host resources.

Old queued/running rows from another process become interrupted at startup.
SIGTERM stops accepting work, allows a bounded drain window, then leaves any
unfinished row recoverable through the existing cache-first retry path.

### Resource locks

`placeintel/locks.py` owns named `fcntl` file locks below `DATA_DIR/locks`.
Discovery and scraper-pro acquire separate locks so CLI and web processes cannot
delete the same Docker container or launch competing Chrome sessions. Lock
timeouts degrade through the existing fallback/error paths and emit structured
events.

### Usage and operations

`placeintel/usage.py` owns `usage_events` and `product_events`. Provider calls
record operation, provider, units, duration, outcome, optional job id, and safe
metadata. SerpAPI reserves one unit before each request and refuses work after a
configurable UTC-day budget. No raw query, review, question, credential, local
path, or precise location is stored.

`placeintel/observability.py` owns structured event names and job context. Local
development can render human logs; production can emit JSON without changing
call sites. `docs/logging.md` is the registry and triage owner.

### Vector provenance

Each vector stores the hash of the exact embedded input plus model, provider,
dimensions, input format version, and timestamp. Eligibility remains reviews
with more than 20 text characters. Indexing selects missing or provenance-
mismatched rows and checkpoints each batch. A dry-run health command reports
current, stale, missing, ineligible, and orphaned rows without provider calls.

### Report evidence

`placeintel/evidence.py` segments complete review text and owner responses into
stable review/segment ids. Single-pass vs map-reduce selection uses both review
count and character budget. Prompts require structured evidence references.

Before save, the validator checks required report fields, configured dimensions,
confidence enum, non-empty evidence, and that every evidence review id exists in
the analyzed set. Unsupported findings are removed and counted in validation
metadata. Existing saved reports and legacy string evidence remain readable.

The dossier renders source-reference controls outside the Markdown HTML path.
Activating one focuses the matching raw review card. Scraped strings still pass
through `esc()`.

### Launch measurement

The browser emits a small allow-listed set of local product events with an
anonymous installation/session id. Payloads contain only event name, timestamp,
view, cache/fresh flag, and bounded duration/count values. Automated tests mark
their session and are excluded from product summaries. Metrics remain local and
disableable.

### Frontend structure

Add `playwright.config.js` with root `tests/` as the only test directory.
Mechanically extract coherent CSS sections from the 799-line file. New
operations/evidence/auth behavior lives in small purpose-owned scripts rather
than expanding `app.js`. Loading order is explicit and contract-tested.

## Data Flow

```text
POST Scout/Shop
  -> validate request
  -> stable request hash
  -> reuse active job OR admit queued job OR 429
  -> one worker claims job
  -> bind job context
  -> acquire discovery/scraper locks as stages need them
  -> reserve/record provider usage
  -> persist canonical events and result
  -> release admission slot

Review upsert
  -> compute current embed input hash
  -> vector health identifies missing/stale rows
  -> checkpointed embed batches write full provenance

Report
  -> full-text evidence segmentation
  -> single pass or character-bounded map-reduce
  -> strict JSON parse
  -> schema and source-reference validation
  -> persist report + validation/evidence fingerprint
  -> dossier source buttons focus raw review cards
```

## Failure Handling

- Queue full: 429 with retry hint; no phantom job.
- Duplicate active request: return existing job id with `reused=true`.
- Lock timeout: actionable stage error; current cache remains untouched.
- Usage budget exceeded: fail before provider call; report used/limit/reset time.
- Log/metric write failure: never kills the core job; emits stderr fallback.
- Vector reindex interruption: completed batches remain current; next repair
  resumes only mismatches.
- Invalid report JSON: retry transient/provider failure policy, then keep the
  previous report and return an actionable error.
- Unsupported finding: remove from grounded output and record validation count.
- Product event failure: ignored by the user flow.

## Compatibility

- Existing API fields remain; new job response fields are additive.
- Legacy `running` jobs and reports remain readable.
- Planner/filter fail-open rules do not change.
- Review originals, source reports, translations, QA scope, live result order,
  exact place identity, and provider routing do not change.
- The web remains a no-build SPA and the four hash routes remain stable.

## Test Strategy

1. Unit tests for job lifecycle, duplicate coalescing, queue rejection, lock
   timeout, usage budget, structured redaction, vector mismatch selection,
   report validation, full-text segmentation, and privacy event allow-list.
2. Server contract tests for additive job responses, 429, ops summary, and
   product event boundary.
3. Existing pipeline/review/cache/Ask tests plus new legacy compatibility tests.
4. Playwright root-only discovery, all existing 37 flows, queued state, report
   source focus, metrics exclusion, auth gate when configured.
5. Cheap doctor and deploy-smoke remain no-cost; deep diagnostics add read-only
   local health counts, not automatic provider calls.
6. Full runtime smoke on loopback. Production proxy/auth/deploy claims require
   authenticated tunnel or verified production credentials.

## Self-Review

- No placeholder or unresolved architecture decision remains in this design.
- Auth is explicitly excluded and linked to its existing owner PRD.
- External queue/vector/analytics platforms are explicitly rejected at current
  scale.
- Every new store has an owner, retention/privacy boundary, and failure path.
- High-risk `startJob` and `renderDetail` flows are protected by the full browser
  suite and targeted new tests.
