# Production Trust Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to implement this plan task-by-task.
> Every production behavior change follows `superpowers:test-driven-development`.
> Steps use checkbox (`- [ ]`) syntax for durable tracking.

**Goal:** Make PlaceIntel safe to operate for a small invited team by bounding
expensive work, recording privacy-safe operational truth, tying AI artifacts to
their exact sources, and proving releases without changing the product's core
flows or provider routing.

**Architecture:** Keep the current single-host FastAPI, SQLite, systemd, and
no-build SPA architecture. Add a one-worker bounded in-process dispatcher backed
by durable SQLite job rows, `fcntl` locks for cross-process scarce resources,
local usage/product ledgers, content-addressed vector and QA/report provenance,
and source-validated report evidence. Supabase authentication remains owned by
the separate auth PRD; this plan strengthens and verifies the existing proxy
boundary without inventing a second auth system.

**Tech Stack:** Python 3.10+, FastAPI/Pydantic, SQLite/WAL, Python stdlib
`queue`/`threading`/`contextvars`/`hashlib`/`fcntl`/`logging`, NumPy,
Google GenAI SDK, vanilla JavaScript/CSS, Playwright, unittest.

## Global Constraints

- Preserve embedding through Google official credentials and reasoning through
  VectorEngine credentials in `placeintel/config.py`.
- Preserve `types.Content` list batching, vector-count validation, and per-item
  fallback in `placeintel/embed.py`.
- Preserve AI planner/filter fail-open behavior; evidence completeness, budget,
  and source validation may fail closed.
- Preserve live Google relevance order, exact-place routing, short Maps URL
  identity, original review/report storage, display-only translations, and
  all-review report coverage.
- Preserve canonical pipeline event stages: `plan`, `search`, `filter`,
  `reviews`, `embed`, `report`, `done`.
- Preserve two-layer Ask grounding: place listings plus review evidence.
- Keep cheap health local and no-cost. Provider, Docker, Chrome, and scraper
  calls remain explicit deep operations.
- Keep the four accessible hash routes and dossier dialog/focus contract.
- Keep every no-build SPA file below 800 lines. Scraped/dynamic strings must
  continue through `esc()` before HTML insertion.
- In this Python/vanilla-JS repository, the PRD's typecheck/lint gate means
  `compileall`, `node --check` for every script, `git diff --check`, and the
  contract suites; no TypeScript or standalone linter is currently configured.
- Migrations are additive, repeatable, and compatible with v0.4.70 data.
- Do not hand-edit `data/` or `vendor/`; tests use temporary copied databases.
- Before editing an existing symbol, run
  `node .gitnexus/run.cjs impact <symbol> --repo place-intel --direction upstream`
  and record the result. Warn before any HIGH/CRITICAL edit.
- After each task, run
  `node .gitnexus/run.cjs detect-changes --repo place-intel --scope unstaged`
  (or the supported equivalent) and the task's focused regression command.
- Update `docs/API.md` or `docs/agent-cli.md` in the same task as every route,
  exported function, CLI command, or public data-contract change.
- Do not version, push, deploy, or claim production verification until Task 12.

## Verified Baseline

- Current commit: `7889902`, branch `codex/production-trust-hardening`.
- Python baseline: 124 tests passed before implementation.
- Browser baseline: 37 UI tests passed when explicitly scoped to
  `tests/ui-audit.spec.js`; the root also owns 2 photo tests, for 39 intended
  browser tests in the normal command.
- `npm run test:web -- --list` currently discovers 74 tests because 37 root
  tests are duplicated under `.claude/worktrees`; Task 1 owns this defect.
- `web/app.js:startJob` is HIGH graph risk (direct callers `bindForms` and
  `bindGlobal`, then `init`); `renderDetail` is also HIGH. Tasks 6 and 10 must
  run all browser tests after focused tests.
- Product baseline: 127 places, 1,891 reviews, 28 reports, 15 QA rows, 9 jobs,
  and 8 searches in the local evidence audit. Generated runtime data is not
  edited by this plan.

## File Responsibility Map

| File | Responsibility after this plan |
| --- | --- |
| `playwright.config.js` | Root-only browser test discovery and deterministic output paths. |
| `web/app.css` | Base shell, forms, tabs, shared controls and tokens. |
| `web/jobs.css` | Job timeline, queued/error state, and result styles. |
| `web/workspace.css` | Library, compare, Ask, and workspace styles. |
| `web/dossier.css` | Dossier, review, report, photo and evidence-focus styles. |
| `web/system.css` | Footer, System panel, operations and responsive overrides. |
| `web/jobs.js` | Scout/Shop job response, queue timeline, SSE and polling behavior. |
| `web/ops.js` | System summary and local product-event client. |
| `web/evidence.js` | Report evidence controls and raw-review focus behavior. |
| `placeintel/jobs.py` | Canonical request hashing, bounded admission, worker claim, shutdown. |
| `placeintel/locks.py` | Fixed-name cross-process `fcntl` resource locks below `DATA_DIR`. |
| `placeintel/usage.py` | SerpAPI reservations, provider usage, product events, retention and summaries. |
| `placeintel/observability.py` | Structured event registry, job context and redacted logging. |
| `placeintel/evidence.py` | Full-text segmentation, source fingerprints and report validation. |
| `placeintel/evals.py` | Deterministic offline trust-corpus metrics. |
| `placeintel/cache.py` | Additive SQLite schema plus narrow persistence/query functions. |
| `placeintel/server.py` | FastAPI validation and adapters into the bounded runner/ops APIs. |
| `placeintel/embed.py` | Exact embedding input, provenance-aware index/health/repair. |
| `placeintel/analyze.py` | Segmented prompts, char-bounded map-reduce, strict validated reports. |
| `placeintel/pipeline.py` | Existing orchestration plus completeness/provenance checks. |
| `placeintel/deploy_smoke.py` | Loopback proof and public unauthenticated route matrix. |

### Task 1: Deterministic Browser Discovery and Frontend File Headroom

**Files:**
- Create: `playwright.config.js`
- Create: `web/jobs.js`
- Create: `web/jobs.css`
- Create: `web/workspace.css`
- Create: `web/dossier.css`
- Create: `web/system.css`
- Modify: `web/app.css`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `package.json`
- Modify: `placeintel/doctor.py`
- Test: `tests/test_web_static_contract.py`
- Test: `tests/test_doctor_contract.py`

**Interfaces:**
- Produces: Playwright `testDir: './tests'`; deterministic CSS/script load order;
  `startJob` remains globally callable from extracted `jobs.js`; every loaded
  local no-build asset remains below 800 lines.
- Preserves: all selectors and computed visual behavior; this is a mechanical
  style extraction, not a redesign.

- [ ] **Step 1: Add failing root-discovery and asset-contract tests**

Add static assertions equivalent to:

```python
def test_playwright_is_scoped_to_root_tests(self):
    cfg = (ROOT / "playwright.config.js").read_text()
    self.assertIn("testDir: './tests'", cfg)
    self.assertNotIn(".claude/worktrees", cfg)

def test_dossier_styles_are_loaded_after_base_styles(self):
    html = (ROOT / "web/index.html").read_text()
    expected = ["app.css", "jobs.css", "workspace.css", "dossier.css", "system.css"]
    positions = [html.index(name) for name in expected]
    self.assertEqual(positions, sorted(positions))
    for path in (ROOT / "web").iterdir():
        if path.suffix in {".js", ".css", ".html"}:
            self.assertLess(len(path.read_text().splitlines()), 800, path.name)
```

- [ ] **Step 2: Prove the tests fail for the missing config/style file**

Run:

```bash
.venv/bin/python -m unittest tests.test_web_static_contract -v
npm run test:web -- --list
```

Expected: the static contract fails because `playwright.config.js` and
`dossier.css` do not exist; browser listing shows duplicate worktree tests.

- [ ] **Step 3: Add the root Playwright configuration**

Create exactly this bounded configuration (keep the existing command's browser
selection and reporter overrides compatible):

```javascript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: 'output/playwright/test-results',
  fullyParallel: false,
  webServer: {
    command: '.venv/bin/placeintel-web',
    url: 'http://127.0.0.1:9618/api/health',
    // The deploy gate starts this exact checkout for deploy-smoke first.
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [{
    name: 'chromium',
    use: {
      browserName: 'chromium',
      extraHTTPHeaders: { 'X-PlaceIntel-Test': 'playwright' },
    },
  }],
});
```

Change the script to `playwright test --reporter=list
--output=output/playwright/test-results`. Root `testDir` must discover exactly
39 intended tests: 37 in `ui-audit.spec.js` and 2 in
`photo-lightbox-source-url.spec.js`.

- [ ] **Step 4: Mechanically extract purpose-owned CSS and job JavaScript**

Move, without selector or declaration changes, the current job timeline/result
blocks to `jobs.css`, Library/compare/Ask workspace blocks to `workspace.css`,
detail/report/review/photo blocks to `dossier.css`, and footer/System/responsive
blocks to `system.css`. Load them in that order after `app.css`; do not duplicate
selectors.

After recording GitNexus HIGH impact for `startJob`, mechanically move `jobEls`,
event append/fail helpers, `pauseJobStream`, `resumeJobStream`, `startJob`,
`streamJob`, and `pollJob` into `jobs.js` without behavior changes. Load
`jobs.js` before `app.js`; preserve `window.__pi.startJob`.

Update `doctor._static_web_check()` and its tests to validate every local CSS/JS
asset referenced by `index.html` instead of a fixed historical filename list.

- [ ] **Step 5: Prove root discovery, syntax and browser behavior**

Run:

```bash
.venv/bin/python -m unittest tests.test_web_static_contract -v
npm run test:web -- --list
npm run test:web
node --check web/app.js
node --check web/jobs.js
```

Expected: exactly 39 intended root tests are listed and pass, and
every no-build file is below 800 lines.

- [ ] **Step 6: Capture responsive visual evidence**

Use Playwright against `http://127.0.0.1:9618` at widths 375, 768, 1024, and
1440. Store screenshots under `output/playwright/visual/task-01/` and inspect for
horizontal overflow, text clipping, modal overlap, and changed tab/dossier
layout. The output directory stays untracked.

- [ ] **Step 7: Commit the isolated milestone**

```bash
git add playwright.config.js package.json web/app.js web/jobs.js web/app.css web/jobs.css web/workspace.css web/dossier.css web/system.css web/index.html placeintel/doctor.py tests/test_web_static_contract.py tests/test_doctor_contract.py
git commit -m "test: isolate browser suite and split dossier styles"
```

### Task 2: Additive Durable Job Lifecycle Contract

**Files:**
- Modify: `placeintel/cache.py`
- Modify: `tests/test_durable_jobs.py`
- Modify: `tests/test_cache_contract.py`
- Modify: `docs/API.md`

**Interfaces:**
- Produces:
  `create_job(..., status='queued', request_hash=None)`,
  `claim_job(conn, job_id, process_id) -> bool`,
  `find_active_job(conn, request_hash) -> dict | None`, and
  `interrupt_active_jobs(conn, process_id) -> int`, plus
  `queue_position(conn, job_id) -> int` (1-based among queued rows by creation).
- `finish_job(..., error_code=None)` stores a stable failure class separately
  from the redacted human error. `get_job()` returns additive `request_hash`,
  `claimed_at`, `queue_position`, and `error_code` only when available; legacy
  rows remain readable.

- [ ] **Step 1: Run GitNexus impact before changing cache job symbols**

```bash
node .gitnexus/run.cjs impact create_job --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact interrupt_running_jobs --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact get_job --repo place-intel --file placeintel/cache.py --direction upstream
```

Record direct callers and affected flows in the task report before editing.

- [ ] **Step 2: Add failing migration and transition tests**

Tests must create a v0.4.70-shaped database, call `cache.connect()`, and assert:

```python
cache.create_job(conn, "job-1", "scout", {"query": "x"},
                 request_hash="abc", status="queued")
self.assertEqual(cache.get_job(conn, "job-1")["status"], "queued")
self.assertTrue(cache.claim_job(conn, "job-1", process_id=222))
self.assertFalse(cache.claim_job(conn, "job-1", process_id=333))
self.assertEqual(cache.get_job(conn, "job-1")["status"], "running")
self.assertEqual(cache.find_active_job(conn, "abc")["job_id"], "job-1")
```

Also assert stale `queued` and `running` rows from another process become
`interrupted`, while terminal rows and current-process rows do not change.

- [ ] **Step 3: Prove the new contract fails**

```bash
.venv/bin/python -m unittest tests.test_durable_jobs tests.test_cache_contract -v
```

Expected: failures show missing columns/signatures and absent claim helpers.

- [ ] **Step 4: Add the repeatable schema migration**

Add nullable columns to `jobs`: `request_hash TEXT`, `claimed_at REAL`,
`worker_id TEXT`, and `error_code TEXT`. Add indexes for `(status, created_at)`
and `request_hash`.
Do not add a partial unique index until legacy duplicate rows are normalized;
duplicate serialization is owned by `placeintel/jobs.py` in Task 3.

Implement `claim_job` as one conditional update:

```python
cur = conn.execute(
    """UPDATE jobs SET status='running', process_id=?, worker_id=?,
              claimed_at=?, updated_at=?
       WHERE job_id=? AND status='queued'""",
    (process_id, worker_id, now, now, job_id),
)
conn.commit()
return cur.rowcount == 1
```

- [ ] **Step 5: Update cache callers/tests and API docs**

Keep a compatibility wrapper named `interrupt_running_jobs` that delegates to
`interrupt_active_jobs` until all callers move. Document the expanded lifecycle
and additive fields in `docs/API.md`.

- [ ] **Step 6: Prove migration idempotency and lifecycle behavior**

```bash
.venv/bin/python -m unittest tests.test_durable_jobs tests.test_cache_contract tests.test_backup_restore -v
.venv/bin/python -m compileall placeintel
```

- [ ] **Step 7: Commit the lifecycle contract**

```bash
git add placeintel/cache.py tests/test_durable_jobs.py tests/test_cache_contract.py docs/API.md
git commit -m "feat: add queued and claimed durable job states"
```

### Task 3: Bounded Job Runner, Duplicate Reuse, and Backpressure

**Files:**
- Create: `placeintel/jobs.py`
- Modify: `placeintel/server.py`
- Modify: `tests/test_durable_jobs.py`
- Modify: `tests/test_server_contract.py`
- Modify: `docs/architecture.md`
- Modify: `docs/API.md`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class JobSubmission:
    job_id: str
    status: str
    reused: bool
    queue_position: int

class QueueSaturated(RuntimeError):
    retry_after: int

class BoundedJobRunner:
    def submit(self, kind: str, request: dict) -> JobSubmission: ...
    def start(self) -> None: ...
    def shutdown(self, drain_seconds: float = 5.0) -> None: ...
```

- Consumes Task 2's queued/claim/cache interfaces.
- Preserves API response `job_id`; adds `status`, `reused`, and
  `queue_position`. Queue saturation is HTTP 429 with `Retry-After`.

- [ ] **Step 1: Run impact on server job entry points**

```bash
node .gitnexus/run.cjs impact _new_job --repo place-intel --file placeintel/server.py --direction upstream
node .gitnexus/run.cjs impact start_scout --repo place-intel --file placeintel/server.py --direction upstream
node .gitnexus/run.cjs impact start_shop --repo place-intel --file placeintel/server.py --direction upstream
node .gitnexus/run.cjs impact _run_scout --repo place-intel --file placeintel/server.py --direction upstream
node .gitnexus/run.cjs impact _run_shop --repo place-intel --file placeintel/server.py --direction upstream
```

- [ ] **Step 2: Add failing canonical hash, coalescing, capacity and claim tests**

Use a blocking fake executor and a temporary DB. Required assertions:

```python
first = runner.submit("scout", {"query": "x", "near": None})
same = runner.submit("scout", {"near": None, "query": "x"})
self.assertEqual(first.job_id, same.job_id)
self.assertFalse(first.reused)
self.assertTrue(same.reused)

with self.assertRaises(QueueSaturated):
    runner.submit("shop", {"target": "overflow"})
```

Also assert only one fake executor is active, rows exist as `queued` before the
worker claims them, and saturation creates no extra `jobs` row.

- [ ] **Step 3: Prove runner and HTTP tests fail before implementation**

```bash
.venv/bin/python -m unittest tests.test_durable_jobs tests.test_server_contract -v
```

- [ ] **Step 4: Implement canonical request identity and bounded admission**

Canonical identity is SHA-256 over compact sorted JSON:

```python
def request_hash(kind: str, request: dict) -> str:
    body = json.dumps(
        {"kind": kind, "request": request},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
```

`submit()` must serialize duplicate lookup and non-blocking semaphore admission
under one process mutex. It acquires a capacity token before creating the row;
on any DB/queue failure it releases the token. A worker conditionally claims the
queued row, runs the executor, and releases the token in `finally`.
The internal `Queue` holds `queue_capacity + workers` items so a burst can admit
one eventual active item plus eight waiting items even before the worker thread
is first scheduled; the semaphore remains the authoritative admission count.

Read `PLACEINTEL_JOB_WORKERS` but reject any value other than `1` until a future
architecture PRD defines cross-process ownership. Add
`PLACEINTEL_JOB_DRAIN_SECONDS=5`; shutdown stops admission, waits at most that
duration, and leaves unfinished durable rows recoverable as interrupted.

- [ ] **Step 5: Replace per-request daemon threads at the FastAPI boundary**

Add one lazily constructed runner. Startup interrupts foreign active rows and
starts the runner; shutdown stops admission and drains for a bounded interval.
The executor reconstructs `ScoutRequest` or `ShopRequest` from durable JSON and
calls the existing `_run_scout`/`_run_shop` adapters. `_new_job` keeps only the
event callback responsibility or moves that callback into `jobs.py`; it must not
create a second row.

Map saturation without provider work:

```python
except jobs.QueueSaturated as exc:
    raise HTTPException(
        status_code=429,
        detail={"code": "queue_full", "message": "Work queue is full. Retry shortly."},
        headers={"Retry-After": str(exc.retry_after)},
    ) from exc
```

SSE remains open while status is either `queued` or `running`.

- [ ] **Step 6: Prove job and server contracts**

```bash
.venv/bin/python -m unittest tests.test_durable_jobs tests.test_server_contract -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

- [ ] **Step 7: Update architecture/API owners and commit**

Document the one-worker/single-process scaling boundary, queue capacity,
coalescing, restart behavior, and 429 response.

```bash
git add placeintel/jobs.py placeintel/server.py tests/test_durable_jobs.py tests/test_server_contract.py docs/architecture.md docs/API.md
git commit -m "feat: bound and coalesce heavy web jobs"
```

### Task 4: Cross-Process Resource Locks and SerpAPI Budget

**Files:**
- Create: `placeintel/locks.py`
- Create: `placeintel/usage.py`
- Modify: `placeintel/config.py`
- Modify: `placeintel/cache.py`
- Modify: `placeintel/discover.py`
- Modify: `placeintel/reviews.py`
- Create: `tests/test_resource_locks.py`
- Create: `tests/test_usage_controls.py`
- Modify: `tests/test_discover_contract.py`
- Modify: `tests/test_review_salvage.py`
- Modify: `.env.example`
- Modify: `docs/API.md`

**Interfaces:**
- Produces:

```python
@contextmanager
def resource_lock(name: Literal["discovery", "scraper"],
                  timeout: float | None = None): ...

class ResourceLockTimeout(RuntimeError): ...
class BudgetExceeded(RuntimeError): ...

@dataclass(frozen=True)
class UsageReservation:
    event_id: int
    provider: str
    operation: str
    units: int

def reserve_provider_call(provider: str, operation: str, units: int = 1,
                          daily_limit: int | None = None,
                          job_id: str | None = None) -> UsageReservation: ...
def finish_provider_call(reservation: UsageReservation, *, outcome: str,
                         duration_ms: int, metadata: dict | None = None) -> None: ...
```

- Budget windows use UTC dates. Usage payloads never contain request text,
  response bodies, keys, precise location, or filesystem paths.

- [ ] **Step 1: Run impact on scarce-resource/provider call symbols**

```bash
node .gitnexus/run.cjs impact _discover_gosom --repo place-intel --file placeintel/discover.py --direction upstream
node .gitnexus/run.cjs impact _discover_serpapi --repo place-intel --file placeintel/discover.py --direction upstream
node .gitnexus/run.cjs impact _run_scraper_pro --repo place-intel --file placeintel/reviews.py --direction upstream
node .gitnexus/run.cjs impact _fetch_via_serpapi --repo place-intel --file placeintel/reviews.py --direction upstream
```

If the review fallback function has a different current name, use GitNexus
`query "SerpAPI reviews request" --repo place-intel` and record the exact target.

- [ ] **Step 2: Add failing lock contention/security tests**

Spawn two processes against one temporary `DATA_DIR`. The first holds
`resource_lock("discovery")`; the second must raise `ResourceLockTimeout` within the
configured timeout. Assert only fixed names are accepted and the resolved lock
path remains below `DATA_DIR/locks`. Open lock files with no-follow semantics
where the platform supports them and reject pre-existing symlinks.

- [ ] **Step 3: Add failing budget reservation tests**

Freeze UTC time and assert reservations 1..limit succeed, limit+1 raises
`BudgetExceeded` before the fake HTTP call, concurrent reservations cannot
oversubscribe, and the next UTC day resets the count. Seed key/query/path-shaped
strings and assert none appears in stored metadata.

- [ ] **Step 4: Prove both focused suites fail**

```bash
.venv/bin/python -m unittest tests.test_resource_locks tests.test_usage_controls -v
```

- [ ] **Step 5: Add configuration and additive usage schema**

Add validated defaults:

```text
PLACEINTEL_RESOURCE_LOCK_TIMEOUT=5
PLACEINTEL_DAILY_SERPAPI_LIMIT=50
PLACEINTEL_USAGE_RETENTION_DAYS=90
PLACEINTEL_JOB_RETENTION_DAYS=30
```

Create `usage_events` with UTC day, provider, operation, units, outcome,
duration, optional job id, safe metadata JSON, and timestamps. Reservation uses
`BEGIN IMMEDIATE`, sums reserved/completed units for the UTC day, inserts only
when below limit, and commits before the network call. A failed or timed-out
provider request still consumes its reservation because provider charging
cannot be inferred safely from the client exception.

- [ ] **Step 6: Integrate locks and reservations at the narrowest boundaries**

Acquire `discovery` only around gosom Docker ownership and `scraper` only around
a new scraper-pro launch; persistent scraper DB reads stay lock-free. Wrap each
SerpAPI network request with reserve/finalize. Budget failure occurs before
`requests.get` and surfaces through existing fallback/error reporting without
mutating cached places/reviews/reports.

- [ ] **Step 7: Prove regressions and privacy**

```bash
.venv/bin/python -m unittest tests.test_resource_locks tests.test_usage_controls tests.test_discover_contract tests.test_review_salvage tests.test_pipeline_review_failure_fallback -v
.venv/bin/python -m compileall placeintel
```

- [ ] **Step 8: Document and commit**

```bash
git add placeintel/locks.py placeintel/usage.py placeintel/config.py placeintel/cache.py placeintel/discover.py placeintel/reviews.py tests/test_resource_locks.py tests/test_usage_controls.py tests/test_discover_contract.py tests/test_review_salvage.py .env.example docs/API.md
git commit -m "feat: lock scraper resources and cap SerpAPI usage"
```

### Task 5: Structured Operations, Private Product Events, and Retention

**Files:**
- Create: `placeintel/observability.py`
- Modify: `placeintel/usage.py`
- Modify: `placeintel/cache.py`
- Modify: `placeintel/server.py`
- Modify: `placeintel/cli.py`
- Modify: `placeintel/config.py`
- Modify: `placeintel/planner.py`
- Modify: `placeintel/analyze.py`
- Modify: `placeintel/embed.py`
- Modify: `placeintel/pipeline.py`
- Modify: `placeintel/discover.py`
- Modify: `placeintel/reviews.py`
- Create: `tests/test_observability.py`
- Extend: `tests/test_usage_controls.py`
- Modify: `tests/test_server_contract.py`
- Create: `docs/logging.md`
- Modify: `docs/API.md`
- Modify: `docs/agent-cli.md`

**Interfaces:**
- Produces:

```python
def bind_job(job_id: str | None): ...  # context manager
def event(name: str, *, level: str = "info", component: str,
          outcome: str, duration_ms: int | None = None,
          metadata: dict | None = None) -> None: ...

PRODUCT_EVENT_NAMES = frozenset({
    "first_submit", "dossier_opened", "scoped_ask_completed",
    "maps_opened", "cache_reused", "session_returned",
})
def record_product_event(name: str, session_id: str, *, is_test: bool,
                         view: str | None, fields: dict) -> bool: ...
def ops_summary(conn, *, now: float | None = None) -> dict: ...
def cleanup_retained_events(conn, *, now: float | None = None) -> dict: ...
```

- `POST /api/product-events` accepts only the allow-list and bounded enum/numeric
  fields. `GET /api/ops` returns queue, budget, funnel, and retention summaries;
  vector/report keys are additive empty summaries until Tasks 7 and 9 populate
  them from their canonical health functions.

- [ ] **Step 1: Run impact on logging, system and CLI surfaces**

```bash
node .gitnexus/run.cjs impact _setup_logging --repo place-intel --file placeintel/cli.py --direction upstream
node .gitnexus/run.cjs impact config_status --repo place-intel --file placeintel/server.py --direction upstream
node .gitnexus/run.cjs impact _emitter --repo place-intel --file placeintel/pipeline.py --direction upstream
node .gitnexus/run.cjs impact _generate_json --repo place-intel --file placeintel/planner.py --direction upstream
node .gitnexus/run.cjs impact _with_reason_retry --repo place-intel --file placeintel/analyze.py --direction upstream
node .gitnexus/run.cjs impact _with_retry --repo place-intel --file placeintel/embed.py --direction upstream
```

- [ ] **Step 2: Add failing structured-event privacy tests**

Capture one JSON log event and assert the stable envelope:

```python
self.assertEqual(set(payload) & {
    "timestamp", "level", "event", "component", "outcome"
}, {"timestamp", "level", "event", "component", "outcome"})
self.assertNotIn("AIza", serialized)
self.assertNotIn("sk-", serialized)
self.assertNotIn("raw query", serialized)
self.assertNotIn(str(Path.home()), serialized)
```

Also assert unknown event names/metadata fields are dropped, exceptions are
classified by type/status without serializing their raw message, and a copied
job context reaches work explicitly run through `contextvars.copy_context()` in
a `ThreadPoolExecutor`.

- [ ] **Step 3: Add failing product-event and summary tests**

Assert unknown events and string content fields return HTTP 422, count/duration
fields are clamped to documented bounds, `X-PlaceIntel-Test: playwright` marks
events as test traffic, summaries exclude test rows, metrics can be disabled,
and repeated 30/90-day cleanup is idempotent.

Retention deletes child `job_events` before terminal `jobs` older than 30 days,
and usage/product rows older than 90 days. Active queued/running jobs are never
deleted. The test runs cleanup twice and verifies the second run changes zero
rows.

- [ ] **Step 4: Prove the focused tests fail**

```bash
.venv/bin/python -m unittest tests.test_observability tests.test_usage_controls tests.test_server_contract -v
```

- [ ] **Step 5: Add the event schema and central redaction**

Every emitted operational record contains `timestamp`, `level`, `event`,
`component`, `outcome`, optional `duration_ms`, and optional `job_id`. Metadata
is accepted per event-name schema, not as an arbitrary dict. Human and JSON
formatters consume the same sanitized record. Logging failure writes one safe
fallback line to stderr and never raises into the pipeline.

Instrument job lifecycle, queue/budget rejection, resource locks, provider
attempt/retry/failure, scraper fallback, cache outcome, vector repair, and report
validation as their owning tasks land. Do not log raw queries/questions, place
names, reviews, provider bodies, commands, URLs containing keys, or local paths.

Add attempt/retry/failure events at the shared provider boundaries:
`planner._generate_json`, `analyze._with_reason_retry`, `embed._with_retry`,
Ask/translation reasoning, model list/verification, and both SerpAPI request
functions. `contextvars` do not automatically cross `ThreadPoolExecutor`; wrap
each submitted analyze/embed worker in an explicit copied context so its job id
is preserved without global mutable state.

- [ ] **Step 6: Add product-event storage and bounded summaries**

Create `product_events` with event name, anonymous session id hash, test flag,
view enum, safe fields JSON, and timestamp. The server hashes the client session
id before storage. `PLACEINTEL_PRODUCT_METRICS=false` makes the write a no-op.
The summary returns only aggregate counts and duration/age buckets; no raw row,
session hash, or location leaves the API.

- [ ] **Step 7: Add CLI-readable operations output**

Add `placeintel ops --format json` as a read-only local summary. Keep `doctor`
cheap and unchanged; `ops` performs only local SQLite queries. Register its
machine envelope in `docs/agent-cli.md` and `CORE_SCHEMAS`.

- [ ] **Step 8: Write the event registry and triage ledger**

`docs/logging.md` must list every event, level, component, allowed metadata,
trigger, likely cause, user impact, first diagnostic command, escalation rule,
and resolved-state criterion. It must state the privacy exclusions explicitly.

- [ ] **Step 9: Prove privacy, retention and API/CLI contracts**

```bash
.venv/bin/python -m unittest tests.test_observability tests.test_usage_controls tests.test_server_contract tests.test_cli_json_contract -v
.venv/bin/placeintel ops --format json
```

Scan the test payload/output for seeded secrets and private strings; the command
must exit 0 and return only aggregates.

- [ ] **Step 10: Commit the operations contract**

```bash
git add placeintel/observability.py placeintel/usage.py placeintel/cache.py placeintel/server.py placeintel/cli.py placeintel/config.py placeintel/planner.py placeintel/analyze.py placeintel/embed.py placeintel/pipeline.py placeintel/discover.py placeintel/reviews.py tests/test_observability.py tests/test_usage_controls.py tests/test_server_contract.py tests/test_cli_json_contract.py docs/logging.md docs/API.md docs/agent-cli.md
git commit -m "feat: add private structured operations ledger"
```

### Task 6: Queue and Operations Web Experience

**Files:**
- Modify: `web/jobs.js`
- Create: `web/ops.js`
- Modify: `web/jobs.css`
- Modify: `web/system.css`
- Modify: `web/app.js`
- Modify: `web/dossier.js`
- Modify: `web/app.css`
- Modify: `web/index.html`
- Modify: `web/i18n.js`
- Modify: `tests/test_web_static_contract.py`
- Modify: `tests/ui-audit.spec.js`

**Interfaces:**
- Consumes job admission `{job_id,status,reused,queue_position}` and stable 429
  details from Task 3, plus `/api/ops` and `/api/product-events` from Task 5.
- Produces queue/reuse/budget/interruption/error states in the existing timeline,
  a read-only System summary, and test-excluded local product events.
- Preserves existing `window.__pi.startJob` and dossier inline refresh behavior.

- [ ] **Step 1: Warn and record HIGH GitNexus impact before extraction**

```bash
node .gitnexus/run.cjs impact startJob --repo place-intel --file web/app.js --direction upstream
node .gitnexus/run.cjs impact bindForms --repo place-intel --file web/app.js --direction upstream
node .gitnexus/run.cjs impact bindGlobal --repo place-intel --file web/app.js --direction upstream
node .gitnexus/run.cjs impact generateReportInline --repo place-intel --file web/dossier.js --direction upstream
```

The task report must state that `startJob` is HIGH because `bindForms`,
`bindGlobal`, and `init` depend on it. Do not edit until this warning is recorded.

- [ ] **Step 2: Add failing static and Playwright behavior tests**

Static tests assert `jobs.js` loads before `app.js`, `ops.js` loads before
`app.js`, no function is duplicated, and all local assets stay below 800 lines.
Playwright intercepts `/api/scout` and covers:

```javascript
await page.route('**/api/scout', route => route.fulfill({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ job_id: 'queued-1', status: 'queued', reused: false, queue_position: 2 }),
}));
await expect(page.getByText(/queued|排队/i)).toBeVisible();
```

Add separate duplicate-reuse, HTTP 429 with retry action, budget-blocked terminal
job, interrupted job, queued dossier refresh, and System summary tests.

- [ ] **Step 3: Prove the new browser tests fail**

```bash
.venv/bin/python -m unittest tests.test_web_static_contract -v
npm run test:web -- --grep "queued|reused|queue full|budget|System summary"
```

- [ ] **Step 4: Extend the extracted job functions without changing their public surface**

Task 1 already moved `jobEls`, event append/fail helpers, `pauseJobStream`,
`resumeJobStream`, `startJob`, `streamJob`, and `pollJob` into `jobs.js` without
behavior changes. Extend those functions in place. Keep load order, global
surface, and dynamic-text escaping unchanged.

Treat `queued` and `running` as active in SSE/polling. Render admission status
before the first pipeline event. A reused response attaches to the existing job
without clearing its durable timeline. Parse 429 safely and show Retry-After.

- [ ] **Step 5: Update dossier inline jobs and stable states**

`generateReportInline()` must handle queued/reused responses and poll/stream
while either queued or running. Terminal display distinguishes `error_code`
values such as `budget_blocked` and `resource_busy`, while DB status remains one
of the five canonical lifecycle values.

- [ ] **Step 6: Add the private product-event client and System summary**

`ops.js` generates one random session id in localStorage, sends only allow-listed
events/fields, marks Playwright traffic when `navigator.webdriver` is true, and
swallows metrics failures. Emit at the actual interaction boundaries: first
Scout/Shop submit, dossier open, successful scoped Ask, external Maps open,
cache reuse, and returned session bucket.

System output uses text plus status tokens for queue capacity/active/queued,
SerpAPI used/limit/reset, metrics enabled/retention/funnel, and additive
vector/report validation summaries. No raw identifiers are rendered.

- [ ] **Step 7: Prove focused and full browser regressions**

```bash
node --check web/jobs.js
node --check web/ops.js
node --check web/app.js
node --check web/dossier.js
npm run test:web -- --grep "queued|reused|queue full|budget|System summary"
npm run test:web
```

Expected: all intended root browser tests pass, including four hash routes,
language modes, dossier focus trap/restoration, translations, and photo flows.

- [ ] **Step 8: Capture responsive System/timeline screenshots and commit**

Capture 375, 768, 1024, and 1440 widths under
`output/playwright/visual/task-06/`; inspect queued/error text wrapping and modal
overlap before committing.

```bash
git add web/jobs.js web/ops.js web/jobs.css web/system.css web/app.js web/dossier.js web/app.css web/index.html web/i18n.js tests/test_web_static_contract.py tests/ui-audit.spec.js
git commit -m "feat: explain queue cost and operations state in web"
```

### Task 7: Content-Addressed Vector Provenance and Repair

**Files:**
- Modify: `placeintel/cache.py`
- Modify: `placeintel/embed.py`
- Modify: `placeintel/config.py`
- Modify: `placeintel/cli.py`
- Create: `tests/test_vector_provenance.py`
- Modify: `tests/test_cache_contract.py`
- Modify: `tests/test_cli_json_contract.py`
- Modify: `.env.example`
- Modify: `docs/agent-cli.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class VectorSpec:
    model: str
    provider: str
    dims: int
    input_version: int

@dataclass(frozen=True)
class VectorWrite:
    review_id: str
    vector: np.ndarray
    source_hash: str
    spec: VectorSpec

def active_vector_spec() -> VectorSpec: ...
def review_document_input(row) -> str: ...
def review_document_hash(row) -> str: ...
def vector_health(conn, spec: VectorSpec, place_id: str | None = None) -> dict: ...
def repair_vectors(conn, *, dry_run: bool, spec: VectorSpec | None = None,
                   batch_size: int = 32, page_size: int = 2000,
                   total_limit: int = 100000,
                   place_id: str | None = None) -> dict: ...
```

- Currentness requires exact source hash, model, provider, dimensions, and input
  version. Eligibility remains `length(trim(text)) > 20`.
- `config.embedding_provenance()` returns a stable provider id (`google`,
  `vectorengine`, or a sanitized custom id), raw model id, dimensions, and input
  version. UI-localized provider labels are never provenance keys.

- [ ] **Step 1: Run impact before vector/cache changes**

```bash
node .gitnexus/run.cjs impact reviews_missing_vectors --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact store_vectors --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact index_pending --repo place-intel --file placeintel/embed.py --direction upstream
node .gitnexus/run.cjs impact embed_docs --repo place-intel --file placeintel/embed.py --direction upstream
node .gitnexus/run.cjs impact vector_search --repo place-intel --file placeintel/cache.py --direction upstream
```

- [ ] **Step 2: Add failing migration/currentness tests**

Seed missing, current, stale-text, wrong-model, wrong-provider, wrong-dims,
wrong-version, ineligible, and orphaned rows. Assert the health dict equals the
expected category counts and each eligible review appears in exactly one of
`current|stale|missing`.

Prove a rating-only change is stale because rating is part of the exact embedded
input. Prove changing one review selects only that review for repair.

- [ ] **Step 3: Prove the vector tests fail**

```bash
.venv/bin/python -m unittest tests.test_vector_provenance tests.test_cache_contract -v
```

- [ ] **Step 4: Define the exact embedded input once**

Use one function for both hashing and provider input:

```python
def document_input(text: str, title: str = DOC_TITLE_FALLBACK) -> str:
    return f"title: {title or DOC_TITLE_FALLBACK} | text: {text[:MAX_DOC_CHARS]}"

def review_text(row) -> str:
    return f"rating {row['rating']}/5 \u2014 {row['text']}"

def review_document_input(row) -> str:
    return document_input(review_text(row), DOC_TITLE_FALLBACK)
```

`embed_docs()` maps `document_input()` over inputs before `_embed_many()`.
`review_document_hash()` hashes the exact UTF-8 string returned by
`document_input(review_text(row))`; do not hash a different untruncated source.

- [ ] **Step 5: Add additive provenance columns and mismatch query**

Add nullable `source_hash`, `model`, `provider`, `input_version`, and
`created_at` columns to `review_vectors`. Legacy rows therefore classify stale,
not current. Update `store_vectors` to accept `VectorWrite` values and write
every field in the same transaction/batch checkpoint. `active_vector_spec()` is
resolved once per repair/search run; neither cache code nor per-row workers
re-resolve mutable settings midway through a batch.

- [ ] **Step 6: Implement dry-run and checkpointed repair**

`repair_vectors(dry_run=True)` performs no provider call and reports counts/ids
bounded by `page_size`. Run mode pages until scoped missing/stale counts reach
zero or `total_limit` is reached, embeds only stale/missing candidates, persists
each batch, and on interruption leaves completed rows current for the next run.
Search joins only current vectors for the active spec; orphaned rows are never
returned.

Add `PLACEINTEL_VECTOR_REPAIR_MAX=100000` as an explicit safety cap. Test 2,001
eligible rows with a 2,000-row page size to prove page limits do not masquerade
as completeness.

- [ ] **Step 7: Add CLI health/repair commands**

```text
placeintel vectors --format json
placeintel vectors --repair --dry-run --format json
placeintel vectors --repair --run --batch-size 32 --page-size 2000 --total-limit 100000 --format ndjson
```

Default is read-only health. `--run` is explicit because it calls the embedding
provider. Output reports spec and counts without raw review text.

- [ ] **Step 8: Prove migration, idempotency and CLI contracts**

```bash
.venv/bin/python -m unittest tests.test_vector_provenance tests.test_cache_contract tests.test_cli_json_contract tests.test_backup_restore -v
.venv/bin/placeintel vectors --format json
.venv/bin/placeintel vectors --repair --dry-run --format json
```

- [ ] **Step 9: Document and commit**

```bash
git add placeintel/cache.py placeintel/embed.py placeintel/config.py placeintel/cli.py tests/test_vector_provenance.py tests/test_cache_contract.py tests/test_cli_json_contract.py .env.example docs/agent-cli.md docs/architecture.md
git commit -m "feat: make review vectors content addressed"
```

### Task 8: Ask Completeness, Saved Evidence, and Source Fingerprints

**Files:**
- Create: `placeintel/evidence.py`
- Modify: `placeintel/cache.py`
- Modify: `placeintel/pipeline.py`
- Modify: `placeintel/server.py`
- Create: `tests/test_ask_provenance.py`
- Modify: `tests/test_ask_evidence_contract.py`
- Modify: `tests/test_language_contract.py`
- Modify: `docs/API.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces:

```python
QA_PROMPT_VERSION = 1

def canonical_listing(row) -> dict: ...
def canonical_ask_review(row, place_name: str) -> dict: ...
def source_fingerprint(*, artifact: str, listings: list[dict], reviews: list[dict],
                       language: str, model: str, provider: str,
                       prompt_version: int, profile_hash: str | None = None) -> str: ...
```

`canonical_listing` includes `place_id`, name, category, rating/review count,
address, phone, website, hours, Maps URL, and price level. Each canonical Ask
review includes `review_id`, `place_id`, place name, complete text used by Ask,
rating, review date, language, and source. This is an Ask-source hash, not Task
7's narrower embedding-input hash.

- `qa` gains nullable `provider`, `evidence_json`, and `fingerprint`. New cache
  hits require the exact current fingerprint and return the saved provider and
  evidence cards. Legacy QA rows remain visible in history but are not trusted
  as current grounded cache hits.

- [ ] **Step 1: Run impact before Ask/cache edits**

```bash
node .gitnexus/run.cjs impact ask --repo place-intel --file placeintel/pipeline.py --direction upstream
node .gitnexus/run.cjs impact save_qa --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact find_cached_answer --repo place-intel --file placeintel/cache.py --direction upstream
```

- [ ] **Step 2: Add failing cached-provenance tests**

Generate one answer with provider `VectorEngine-A` and evidence cards, then hit
the exact cache under the same provenance. Assert the response reports the saved
`VectorEngine-A` and original evidence refs rather than reconstructing either
from current UI labels. Change the active provider to `VectorEngine-B` and
assert the old cache is rejected because provider is part of the fingerprint.

Mutate listing hours, review text, review rating, ordered review membership,
review date, language, place identity/name, tied-date review-id ordering, model,
provider, or prompt version one at a time and assert the cached answer is
rejected. Assert an unrelated place mutation does not invalidate an exact
place-scoped answer.

- [ ] **Step 3: Add failing completeness tests**

Seed one stale/missing eligible vector. Mock repair success and assert Ask repairs
before retrieval. Mock repair failure and assert no reasoning call occurs and
the response contains:

```python
{
    "answer": "",
    "cached": False,
    "evidence_complete": False,
    "completeness": {"missing": 1, "stale": 0, "next_action": "..."},
}
```

- [ ] **Step 4: Prove Ask tests fail**

```bash
.venv/bin/python -m unittest tests.test_ask_provenance tests.test_ask_evidence_contract tests.test_language_contract -v
```

- [ ] **Step 5: Implement canonical fingerprints and additive QA storage**

Canonicalize only documented fields: listing metadata in stable field order,
reviews ordered by `(review_date DESC, review_id)`, each review source hash,
scope, answer language, reasoning model/provider, and prompt version. Use sorted
compact JSON and SHA-256. Do not include timestamps that would invalidate an
otherwise unchanged source state.

Save answer, model, provider, serialized evidence cards, fingerprint, language,
and question vector atomically. Cache lookup requires fingerprint equality in
addition to semantic score and exact scope.

- [ ] **Step 6: Enforce current vector evidence before Ask retrieval**

After embedding the question, check scoped vector health. If incomplete, call
checkpointed repair for the scope, paging until missing/stale reach zero or the
explicit total safety cap is reached; recheck and only then retrieve. If still
incomplete, return the actionable completeness response and skip reasoning.
Listing-only questions still retain the two-layer contract; they do not bypass
the evidence currentness gate silently.

- [ ] **Step 7: Prove Ask and existing cache behavior**

```bash
.venv/bin/python -m unittest tests.test_ask_provenance tests.test_ask_evidence_contract tests.test_language_contract tests.test_server_contract -v
```

- [ ] **Step 8: Document and commit**

```bash
git add placeintel/evidence.py placeintel/cache.py placeintel/pipeline.py placeintel/server.py tests/test_ask_provenance.py tests/test_ask_evidence_contract.py tests/test_language_contract.py docs/API.md docs/architecture.md
git commit -m "feat: preserve Ask evidence and source provenance"
```

### Task 9: Full-Text Report Segmentation, Validation, and Fingerprints

**Files:**
- Modify: `placeintel/evidence.py`
- Modify: `placeintel/analyze.py`
- Modify: `placeintel/cache.py`
- Modify: `placeintel/pipeline.py`
- Modify: `placeintel/profiles.py`
- Modify: `placeintel/config.py`
- Modify: `.env.example`
- Create: `tests/test_report_evidence.py`
- Create: `tests/test_report_validation.py`
- Modify: `tests/test_analyze_retry.py`
- Modify: `tests/test_analyze_activity_risk.py`
- Modify: `tests/test_pipeline_review_failure_fallback.py`
- Modify: `docs/API.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces:

```python
REPORT_PROMPT_VERSION = 1

@dataclass(frozen=True)
class ReviewSegment:
    segment_id: str
    review_id: str
    field: Literal["text", "owner_response"]
    start: int
    end: int
    text: str
    source_hash: str

class EvidenceRef(BaseModel):
    review_id: str
    segment_ids: list[str]
    source_quote: str
    quote: str | None = None

def segment_reviews(rows, max_chars: int) -> list[ReviewSegment]: ...
def coverage(rows, segments) -> dict: ...
def select_report_mode(*, review_count: int, source_chars: int,
                       review_limit: int, char_limit: int) -> Literal["single", "map_reduce"]: ...
def chunk_segments(segments: list[ReviewSegment], max_chars: int) -> list[list[ReviewSegment]]: ...
def validate_report(payload: dict, *, dimension_keys: set[str],
                    segments_by_id: dict[str, ReviewSegment]) -> tuple[dict, dict]: ...
```

- `reports` gains nullable `provider`, `fingerprint`, `validation_json`, and
  `coverage_json`. New reports use structured evidence references; legacy report
  JSON/string evidence stays readable.

- [ ] **Step 1: Run impact before report generation/storage edits**

```bash
node .gitnexus/run.cjs impact _format_review --repo place-intel --file placeintel/analyze.py --direction upstream
node .gitnexus/run.cjs impact _digest_chunk --repo place-intel --file placeintel/analyze.py --direction upstream
node .gitnexus/run.cjs impact _build_prompt --repo place-intel --file placeintel/analyze.py --direction upstream
node .gitnexus/run.cjs impact analyze_place --repo place-intel --file placeintel/analyze.py --direction upstream
node .gitnexus/run.cjs impact save_report --repo place-intel --file placeintel/cache.py --direction upstream
node .gitnexus/run.cjs impact render_markdown --repo place-intel --file placeintel/analyze.py --direction upstream
```

- [ ] **Step 2: Add failing lossless segmentation tests**

Seed text longer than 800 characters, owner response longer than 300, empty
fields, newlines, leading/trailing whitespace, CJK, and emoji. For each
non-empty `(review_id, field)`, assert:

```python
parts = sorted(field_segments, key=lambda item: item.start)
self.assertEqual("".join(item.text for item in parts), original_value)
self.assertEqual(parts[0].start, 0)
self.assertEqual(parts[-1].end, len(original_value))
self.assertEqual(len({item.segment_id for item in parts}), len(parts))
```

Changing a review changes its segment source hashes; unchanged review/segment
ids remain stable.

Null/empty fields produce zero segments and are excluded from reconstruction
indexing without affecting the review/owner-response coverage counts.

- [ ] **Step 3: Add failing selection, schema and source-reference tests**

Assert map-reduce is selected when either review count exceeds the count limit
or total source characters exceed `PLACEINTEL_SINGLE_PASS_CHARS`. Chunks are
bounded by `PLACEINTEL_MAP_CHARS` without omitting a segment.

Add exact-boundary cases for count/characters at and one above the single-pass
limit, and for segments exactly at/one character across a map-chunk boundary.
Configuration ownership is `config.py` plus `.env.example`:
`PLACEINTEL_EVIDENCE_SEGMENT_CHARS=4000`,
`PLACEINTEL_SINGLE_PASS_CHARS=400000`, and
`PLACEINTEL_MAP_CHARS=160000`.

Validate that missing required fields, unconfigured dimensions, invalid
confidence, unknown review ids, and unknown segment ids cannot persist as a
normal grounded finding. Unsupported/missing-evidence findings are removed and
counted in validation metadata. At least one supported finding remains or
generation fails and the prior report remains stored/displayable but is marked
stale against the changed source fingerprint.

Source-reference tests pass `segments_by_id` and reject: a segment owned by a
different declared review, repeated/missing segment ids, empty `source_quote`,
and a fabricated `source_quote` that is not an exact substring of the referenced
segments concatenated in source order. `quote` may be a translated display
quote; `source_quote` is always verbatim and validator-checkable.

Strict JSON tests reject fenced JSON, prefix/suffix prose, malformed JSON, and
duplicate object keys. The permissive substring-extraction parser must not be
used for new report persistence.

- [ ] **Step 4: Prove report trust tests fail**

```bash
.venv/bin/python -m unittest tests.test_report_evidence tests.test_report_validation tests.test_analyze_retry -v
```

- [ ] **Step 5: Implement lossless segments and coverage accounting**

Split each non-null `text` and `owner_response` by Python character offsets,
without `strip()` or normalization. Stable ids are
`<review_id>:text:<index>` and `<review_id>:owner:<index>`. Escape/encoding is a
prompt transport concern; stored originals are unchanged.

Coverage records:

```json
{
  "cached_reviews": 12,
  "text_bearing_reviews": 11,
  "owner_response_reviews": 3,
  "source_characters": 48123,
  "processed_characters": 48123,
  "segments": 19,
  "mode": "single|map_reduce"
}
```

`processed_characters` must equal `source_characters` before save.

- [ ] **Step 6: Change prompts to stable structured evidence ids**

Replace silent truncation with segment blocks carrying review/segment ids,
date/rating/author metadata, and exact segment text. Require findings shaped as:

```json
{
  "finding": "...",
  "evidence": [
    {
      "review_id": "r-1",
      "segment_ids": ["r-1:text:0"],
      "source_quote": "verbatim source excerpt",
      "quote": "optional report-language translation"
    }
  ],
  "confidence": "high"
}
```

Map digests preserve these ids verbatim. Reduce input includes every digest plus
raw low-star/newest segments as before, but it never claims full coverage unless
all source characters were assigned to a processed segment.

- [ ] **Step 7: Validate before persistence and preserve the previous report**

Parse strict JSON, validate required keys/dimension keys/confidence enums, then
source-validate segment ownership and the verbatim `source_quote` for each
evidence reference. Remove unsupported findings and record
counts. A structurally invalid report raises before `cache.save_report`; pipeline
records the error and leaves existing reports/translations intact.

Build the report fingerprint from listing metadata, ordered review source
hashes, profile YAML content hash, report/evidence language, model, provider,
and prompt version. Cache reuse requires exact fingerprint equality. Do not
rewrite legacy report rows; they remain stored/displayable and explicitly stale
instead of being called fingerprint-current.

- [ ] **Step 8: Make Markdown rendering backward compatible**

For legacy string evidence, render the string exactly as today. For a structured
reference, render its translated/model quote plus a stable machine-readable
source marker such as `[source:review_id]`; the browser turns backend refs into
buttons in Task 10 rather than trusting Markdown HTML.

- [ ] **Step 9: Prove full report and fallback regressions**

```bash
.venv/bin/python -m unittest tests.test_report_evidence tests.test_report_validation tests.test_analyze_retry tests.test_analyze_activity_risk tests.test_pipeline_review_failure_fallback tests.test_language_contract -v
```

- [ ] **Step 10: Document and commit**

```bash
git add placeintel/evidence.py placeintel/analyze.py placeintel/cache.py placeintel/pipeline.py placeintel/profiles.py placeintel/config.py .env.example tests/test_report_evidence.py tests/test_report_validation.py tests/test_analyze_retry.py tests/test_analyze_activity_risk.py tests/test_pipeline_review_failure_fallback.py docs/API.md docs/architecture.md
git commit -m "feat: validate reports against lossless review evidence"
```

### Task 10: Dossier Source Navigation and Offline Trust Evaluation

**Files:**
- Create: `web/evidence.js`
- Modify: `web/app.js`
- Modify: `web/dossier.js`
- Modify: `web/dossier.css`
- Modify: `web/index.html`
- Modify: `web/i18n.js`
- Modify: `placeintel/server.py`
- Create: `placeintel/evals.py`
- Modify: `placeintel/cli.py`
- Create: `tests/fixtures/trust_eval_cases.json`
- Create: `tests/test_trust_evals.py`
- Modify: `tests/test_server_contract.py`
- Modify: `tests/test_web_static_contract.py`
- Modify: `tests/ui-audit.spec.js`
- Modify: `docs/API.md`
- Modify: `docs/agent-cli.md`
- Modify: `DESIGN.md`

**Interfaces:**
- Consumes Task 9's structured report evidence and coverage/validation metadata.
- Produces review source buttons with `data-evidence-review`, review cards with
  `data-review-id`, exact `GET /api/reviews/{review_id}` lazy source loading, and
  `placeintel eval-trust --format json`.
- Evaluation is deterministic/offline and must not call models, embedding,
  Docker, Chrome, scraper, or network endpoints.

- [ ] **Step 1: Warn and record HIGH dossier blast radius**

```bash
node .gitnexus/run.cjs impact renderDetail --repo place-intel --file web/app.js --direction upstream
node .gitnexus/run.cjs impact renderReviewCard --repo place-intel --file web/app.js --direction upstream
node .gitnexus/run.cjs impact openDetail --repo place-intel --file web/app.js --direction upstream
```

The report must note `renderDetail` affects `init`, `bindGlobal`, `pollFinal`, and
`openDetail`; full browser verification is mandatory.

- [ ] **Step 2: Add failing API/static/source-focus tests**

Server detail must expose report `coverage`, `validation`, `fingerprint`, and
structured evidence refs without changing legacy fields. Add an exact raw-review
GET route so a report citing review 501 or later can load that source even though
the initial dossier response is bounded to 500 reviews. The route returns one
review plus `place_id`, performs no provider call, and 404s unknown ids. Static
tests assert `evidence.js` loads before `app.js` and dynamic values pass through
`esc()`.

Playwright opens a dossier with active language/rating filters, activates a
source button for both an initially loaded review and a mocked review beyond the
500-row detail cap, and asserts the matching raw review becomes visible,
receives programmatic focus, and remains inside the modal focus trap. Escape
closes the modal and restores opener focus exactly as before.

- [ ] **Step 3: Add failing deterministic eval tests**

The sanitized fixture includes separate `raw_report` and `validated_report`
states, long source text, precomputed retrieval rankings, old/new contradiction
pairs, scoped/unscoped cache before/after states, and no real place/user data.
Assert raw defects are detected and grounded output is clean:

```python
self.assertGreater(result["raw"]["unknown_review_ids"], 0)
self.assertGreater(result["raw"]["unsupported_claim_rate"], 0.0)
self.assertEqual(result["validated"]["citation_precision"], 1.0)
self.assertEqual(result["validated"]["unsupported_claim_rate"], 0.0)
self.assertEqual(result["full_text_coverage"], 1.0)
self.assertEqual(result["validated"]["unknown_review_ids"], 0)
self.assertGreaterEqual(result["retrieval_hit_at_k"], 0.9)
self.assertTrue(result["recency_contradiction_pass"])
self.assertTrue(result["cache_invalidation_pass"])
```

- [ ] **Step 4: Prove source/eval tests fail**

```bash
.venv/bin/python -m unittest tests.test_trust_evals tests.test_server_contract tests.test_web_static_contract -v
npm run test:web -- --grep "report source|evidence review"
```

- [ ] **Step 5: Render evidence controls outside Markdown HTML**

`evidence.js` consumes backend refs and builds keyboard `<button>` controls with
escaped text. Activation clears only the review language/rating filters required
to reveal the source, updates counts, scrolls with reduced-motion respect, and
focuses the exact review card. Review cards use `tabindex="-1"`. Locate hostile
review ids by iterating `[data-review-id]` elements and comparing
`element.dataset.reviewId === reviewId`; do not interpolate untrusted ids into a
CSS selector. If the card is absent, fetch the exact raw-review route, verify its
`place_id` matches the open dossier, render it through the existing escaped
review-card path, then focus it. It never resolves identity by quote text.

Add a visible coverage/validation line: analyzed rows, source characters,
segments, grounded findings, and removed unsupported findings. Status is text,
not color alone.

- [ ] **Step 6: Implement offline evaluation and CLI envelope**

`evals.run(corpus_path)` validates corpus schema and computes citation precision,
unsupported-claim rate, full-text coverage, retrieval hit@k, recency/
contradiction checks, and cache invalidation checks from fixture inputs. Add:

Retrieval cases provide `{relevant_review_ids, retrieved_review_ids, k}` and are
scored without embeddings. Recency/contradiction and cache cases provide explicit
before/after source states plus expected decisions; fixture booleans are outputs,
not trusted inputs.

```text
placeintel eval-trust --corpus tests/fixtures/trust_eval_cases.json --format json
```

The default corpus path is the shipped sanitized fixture. Return non-zero when a
required threshold fails; document thresholds and schema in `docs/agent-cli.md`.

- [ ] **Step 7: Prove focused and full browser behavior**

```bash
.venv/bin/python -m unittest tests.test_trust_evals tests.test_server_contract tests.test_web_static_contract -v
.venv/bin/placeintel eval-trust --format json
node --check web/evidence.js
node --check web/app.js
node --check web/dossier.js
npm run test:web -- --grep "report source|evidence review"
npm run test:web
```

- [ ] **Step 8: Capture dossier evidence screenshots and commit**

Capture filtered and source-focused dossier states at 375, 768, 1024, and 1440
widths under `output/playwright/visual/task-10/` and inspect focus outline,
wrapping, scroll target, and dialog boundaries.

```bash
git add web/evidence.js web/app.js web/dossier.js web/dossier.css web/index.html web/i18n.js placeintel/server.py placeintel/evals.py placeintel/cli.py tests/fixtures/trust_eval_cases.json tests/test_trust_evals.py tests/test_server_contract.py tests/test_web_static_contract.py tests/ui-audit.spec.js docs/API.md docs/agent-cli.md DESIGN.md
git commit -m "feat: link report findings to raw review sources"
```

### Task 11: Reproducible Deploy, Proxy Matrix, Backup, and Rollback

**Files:**
- Modify: `placeintel/deploy_smoke.py`
- Modify: `placeintel/backup.py`
- Modify: `placeintel/cli.py`
- Modify: `tests/test_deploy_smoke.py`
- Modify: `tests/test_backup_restore.py`
- Create: `tests/test_deploy_contract.py`
- Create: `deploy/vendor-lock.json`
- Create: `deploy/requirements-placeintel.lock`
- Create: `deploy/requirements-scraper-pro.lock`
- Create: `deploy/placeintel.service.in`
- Create: `deploy/activate-release.sh`
- Modify: `deploy/remote-bootstrap.sh`
- Modify: `.github/workflows/deploy-contabo.yml`
- Modify: `docs/operations.md`
- Modify: `docs/agent-cli.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- `deploy-smoke --public-url` remains proxy-mode proof: `/` and representative
  private APIs must return 401/403 without credentials. The future Supabase auth
  PRD must add a distinct app-auth mode because its public login shell changes
  root semantics.
- Production layout is immutable releases with atomic `current`/`previous`
  symlinks and one explicit Uvicorn worker.

- [ ] **Step 1: Record operationally HIGH risk and GitNexus impact**

```bash
node .gitnexus/run.cjs impact run --repo place-intel --file placeintel/deploy_smoke.py --direction upstream --include-tests
node .gitnexus/run.cjs impact restore_backup --repo place-intel --file placeintel/backup.py --direction upstream --include-tests
```

GitNexus cannot see workflow/shell/systemd/proxy callers; record this task as
operationally HIGH regardless of a LOW graph result.

- [ ] **Step 2: Add failing public proxy-matrix and redaction tests**

Probe `GET /`, `GET /api/places`, `GET /api/qa?scope=all`, and invalid-body
`POST` requests to `/api/scout`, `/api/ask`, and `/api/reviews/translate`.
Invalid JSON contracts prevent provider work if the proxy is accidentally
bypassed. Every public probe must return 401/403; one 200/404/422 makes smoke
fail. Never persist or print response bodies, full target URLs, credentials, or
query strings.

- [ ] **Step 3: Add failing reproducibility and rollback tests**

`tests/test_deploy_contract.py` asserts:

- every runtime requirement line is exact `==` or a hash-pinned artifact;
- vendor lock contains the reviewed 40-character commit
  `09bfa6215cb37edecc777bb40055d100e88ef767` (`v1.2.3`);
- bootstrap has no production `git pull` and checks out that commit;
- GitHub Actions uses immutable 40-character action SHAs;
- known hosts comes from a secret, not same-run `ssh-keyscan` trust;
- systemd contains `--host 127.0.0.1 --port 9618 --workers 1`;
- release activation retains `previous`, rolls back after failed restart/smoke,
  and completes the stubbed rollback path in under 60 seconds;
- workflow cleanup runs under `if: always()` and deploy cancellation cannot
  leave a half-mutated live directory.

- [ ] **Step 4: Add failing new-schema backup/restore tests**

Seed jobs/events, usage/product events, vector provenance, report validation/
coverage, and QA provenance. Backup, remove runtime state, restore, reconnect,
and compare representative rows/schema. Restore a v0.4.70-style DB and prove
additive migrations. Keep the legacy minimum `REQUIRED_TABLES`; new tables are
created on reconnect. Assert manifest has no absolute `source_data_dir` and no
file outside the existing allow-list.

- [ ] **Step 5: Prove all deployment tests fail before implementation**

```bash
.venv/bin/python -m unittest tests.test_deploy_smoke tests.test_deploy_contract tests.test_backup_restore -v
```

- [ ] **Step 6: Implement safe public matrix and sanitized output**

Extend `_request` with method and optional JSON body. Return only status and
content type to public checks; discard body. Smoke output reports target class
(`loopback`/`private` and `public_checked`) rather than raw URLs. Keep the CLI
human output useful without printing secret domains.

- [ ] **Step 7: Generate and consume reviewed lock files**

Build a clean temporary virtualenv, install `.[web]` plus the reviewed vendor
requirements, and export exact production closures into the two requirements
locks. Review platform markers and remove editable/local path entries. Record
vendor repo URL, tag, commit, and tree checksum in `vendor-lock.json`.
Bootstrap verifies the commit/checksum and installs lock files, then installs
PlaceIntel itself with `--no-deps`.

Resolve each GitHub Action tag to its official commit via GitHub API, verify the
tag's repository/release, then commit the immutable SHA. The test rejects tags
such as `@v4`; do not guess SHAs.

- [ ] **Step 8: Implement atomic release activation and rollback**

Use:

```text
DEPLOY_DIR/
  current -> releases/<sha>
  previous -> releases/<previous-sha>
  releases/<sha>/
  shared/.env
  shared/data/
```

Prepare source/venv and verify it before switching `current`. Atomically rotate
`previous`/`current`, restart, and smoke. On restart/smoke failure restore
`current` to `previous`, restart, and smoke automatically. Retain at least three
releases. `deploy/placeintel.service.in` explicitly runs one Uvicorn worker and
binds shared data/env paths.

- [ ] **Step 9: Prove shell, deployment, smoke and backup contracts**

```bash
.venv/bin/python -m unittest tests.test_deploy_smoke tests.test_deploy_contract tests.test_backup_restore -v
bash -n deploy/remote-bootstrap.sh
bash -n deploy/activate-release.sh
```

- [ ] **Step 10: Update runbooks and commit**

Document lock maintenance, one-worker rationale, immutable activation,
automatic/manual rollback, public proxy mode, future app-auth smoke distinction,
secret known-hosts handling, and backup compatibility.

```bash
git add placeintel/deploy_smoke.py placeintel/backup.py placeintel/cli.py tests/test_deploy_smoke.py tests/test_backup_restore.py tests/test_deploy_contract.py deploy/vendor-lock.json deploy/requirements-placeintel.lock deploy/requirements-scraper-pro.lock deploy/placeintel.service.in deploy/activate-release.sh deploy/remote-bootstrap.sh .github/workflows/deploy-contabo.yml docs/operations.md docs/agent-cli.md docs/architecture.md
git commit -m "feat: make deploy and rollback reproducible"
```

### Task 12: Release Gate, Version, Credential Audit, and Verifiable Delivery

**Files:**
- Create: `scripts/release-gate.sh`
- Create: `.github/workflows/ci.yml`
- Modify: `.github/workflows/deploy-contabo.yml`
- Modify: `pyproject.toml`
- Modify: `placeintel/__init__.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `CHANGELOG.md`
- Modify: `VAULT.md`
- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `tasks/2026-07-11 - prd production-trust-hardening.md`
- Modify: `tasks/README.md`

**Interfaces:**
- Produces one reusable local/CI release gate, a synchronized version, current
  project memory, and an evidence ledger distinguishing local, loopback,
  protected-production, and app-auth proof.
- Does not remove proxy Basic Auth or implement Supabase auth.

- [ ] **Step 1: Add the reusable release gate and ordinary CI**

`scripts/release-gate.sh` runs, in order, from the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python -m compileall placeintel
node --check web/app.js
node --check web/dossier.js
node --check web/i18n.js
node --check web/jobs.js
node --check web/ops.js
node --check web/evidence.js
npm ci
npm run test:web
.venv/bin/placeintel doctor --json
.venv/bin/placeintel vectors --format json
.venv/bin/placeintel eval-trust --format json
scripts/validate-prd-contract.sh --allow-legacy .
git diff --check
```

CI runs on pull requests and branch pushes independently of deploy secrets.
Deploy calls the same gate and is controlled by a documented repository
variable, not a hardcoded private repository name.

- [ ] **Step 2: Run GitNexus change detection against main**

```bash
node .gitnexus/run.cjs detect-changes --repo place-intel --scope compare --base-ref main
```

Review every changed symbol/process against the PRD zero-regression table. Any
unexpected HIGH/CRITICAL flow blocks the release until it has a focused test or
the change is removed.

- [ ] **Step 3: Run the complete local gate fresh**

```bash
scripts/release-gate.sh
```

Record exit codes and exact pass counts in `progress.md`. A partial suite or an
old result does not count.

- [ ] **Step 4: Prove migration, integrity, backup and loopback runtime**

Use `placeintel backup` to create an allow-list backup, restore it into a
temporary trusted `DATA_DIR`, run SQLite `PRAGMA integrity_check`, `doctor
--json`, vector dry-run health, and the offline trust eval. Start exactly one
loopback Uvicorn worker on an unused port and run:

```bash
.venv/bin/placeintel deploy-smoke --base-url http://127.0.0.1:<port> --expected-version <release-version> --format json
```

The actual command in the release report must contain the selected numeric port
and version; angle-bracket notation here describes runtime substitution, not a
claim or persisted configuration.

- [ ] **Step 5: Audit the separate auth credential gate safely**

Before accessing credentials, load and follow the `1password` and
`1password-cli` skills. Search only credential classes/metadata through the
approved Terminal Bridge and available logged-in browser state. Do not print or
store values. Re-evaluate Supabase Management access, Supabase project/JWT/JWKS,
Google OAuth, SMTP/Resend, Cloudflare/DNS, private deploy/tunnel, and proxy
access.

If any class remains unavailable, leave the auth PRD paused and record exactly
`unverified - credential-gated` with the missing class. Do not implement partial
JWT/login code and do not remove proxy Basic Auth.

- [ ] **Step 6: Bump version only after all non-external gates pass**

This is a backward-compatible feature release, so update both version owners
from `0.4.70` to `0.5.0` only after Steps 1-4 pass. Update CHANGELOG with shipped
behavior and proof, then rerun the full release gate and loopback deploy-smoke
against `0.5.0`.

- [ ] **Step 7: Run independent task and whole-branch review**

Generate a review package from `git merge-base main HEAD` through the
`superpowers:requesting-code-review` workflow. Fix all Critical/Important
findings with focused red-green tests, regenerate the package, and obtain a clean
spec-compliance and code-quality verdict. Record remaining Minor items in the
progress ledger.

- [ ] **Step 8: Commit release metadata and push the feature branch**

```bash
git add scripts/release-gate.sh .github/workflows/ci.yml .github/workflows/deploy-contabo.yml pyproject.toml placeintel/__init__.py AGENTS.md README.md .env.example CHANGELOG.md VAULT.md task_plan.md progress.md "tasks/2026-07-11 - prd production-trust-hardening.md" tasks/README.md
git commit -m "release: placeintel 0.5.0 production trust hardening"
git push -u origin codex/production-trust-hardening
```

Push only after a secret/path/privacy scan of the complete branch diff. Do not
merge or trigger production cutover merely because the branch pushed.

- [ ] **Step 9: Perform only production actions that can be freshly proved**

If verified private deploy/tunnel/proxy credentials are available, prepare the
immutable release, activate it, run authenticated/loopback smoke, run the public
proxy rejection matrix, observe redacted structured logs for five minutes,
measure rollback to `previous` under 60 seconds, reactivate, and smoke again.

If credentials or safe access are unavailable, stop after branch delivery and
state production deploy/proxy/auth E2E as unverified. Local and loopback proof
must not be described as production proof.

## PRD Coverage Map

| PRD requirement | Owning tasks |
| --- | --- |
| US-001 / G7 deterministic tests and frontend headroom | Task 1, then Tasks 6 and 10 keep new behavior in owned files |
| US-002 / G1-G3 bounded durable jobs, locks, and budget | Tasks 2-4 backend, Task 6 browser states |
| US-003 / G6 structured operations and launch measurement | Tasks 4-6, with vector/report summaries completed by Tasks 7 and 9 |
| US-004 / G4 vector and Ask provenance | Tasks 7-8 |
| US-005 / G5 source-verifiable full-evidence reports | Tasks 9-10 |
| US-006 / G8 release, proxy, rollback, and proof | Tasks 11-12 |
| FR-001 through FR-004 job identity/admission | Tasks 2-3 |
| FR-005 cross-process locks | Task 4 |
| FR-006 through FR-010 usage/privacy/product events | Tasks 4-6 |
| FR-011 through FR-013 vector currentness/repair | Task 7 |
| FR-014 QA saved provider/evidence | Task 8 |
| FR-015 through FR-018 segmentation/evidence/UI identity | Tasks 9-10 |
| FR-019 and FR-020 bounded summaries/retention | Task 5 |
| FR-021 public proxy rejection matrix | Task 11 |
| FR-022 cheap health remains no-cost | Tasks 1, 5, 7, 9 and full gate in Task 12 |
| FR-023 additive v0.4.70 migrations | Tasks 2, 4, 5, 7-9; round-trip proof Task 11 |
| FR-024 source/provider/routing compatibility | Global constraints and full regression Task 12 |
| API/CLI/architecture/logging/operations/design docs | Same owning task as each contract, consolidated in Tasks 11-12 |
| Version/changelog/project memory | Task 12 after fresh gates |
| Separate Supabase Auth PRD and credential gates | Task 12 audit only; no auth implementation in this plan |

## Plan Self-Review Gate

Before Task 1 implementation:

- [ ] Re-read every PRD goal, acceptance criterion, functional requirement,
  non-goal, and documentation requirement; map each to a task above.
- [ ] Search this plan for deferred-implementation markers and replace any
  ambiguity with a concrete contract.
- [ ] Verify signatures and field names are consistent across producer and
  consumer tasks, especially job admission, vector provenance, QA/report
  fingerprints, structured evidence, and ops summaries.
- [ ] Resolve the accepted cross-story sequencing: US-003's vector and report
  summary sections close only after Tasks 7 and 9 populate them.
- [ ] Set the hardening PRD status to `In Progress` only when Task 1's first
  failing test is written and observed.
