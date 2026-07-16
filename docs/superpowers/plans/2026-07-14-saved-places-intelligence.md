# Saved Places Intelligence Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. The PRD remains the
> live status owner; this file owns implementation order, interfaces, tests, and
> rollout details only.

**Goal:** Add a private, idempotent Google Takeout saved-place corpus to
PlaceIntel and use it for auditable saved-only recommendations.

**Architecture:** A focused `saved_places` domain module owns additive SQLite
tables, safe Takeout parsing, stable identities, import transactions, resolution
states, and recommendation filtering. A thin CLI adapter exposes stable human
text and JSON. Existing cache, pipeline, provider, backup, and deployment owners
are reused without changing their behavior.

**Tech Stack:** Python 3.13, stdlib CSV/ZIP/hash/URL tools, SQLite, existing
PlaceIntel CLI envelope and unittest suite.

**Status Owner:** `tasks/2026-07-14 - prd saved-places-intelligence.md`

## Global Constraints

- Never mutate Google Maps or upload a Takeout archive.
- Preserve source saved data separately from current place truth.
- No new runtime dependency, service, auth surface, or UI framework.
- Offline import requires no credentials, Docker, browser, or AI.
- Use parameterized SQL, atomic writes, deterministic IDs, bounded input, and
  machine-readable results.
- Do not touch the sibling worktree's uncommitted production-hardening changes.

## File Structure

| File | Responsibility |
| --- | --- |
| `placeintel/saved_places.py` | schema, limits, safe input discovery, CSV parsing, IDs, atomic import, inventory, later resolution/recommendation |
| `placeintel/saved_cli.py` | parser registration and command handlers only |
| `placeintel/cli.py` | one adapter call registering saved commands; no domain logic |
| `tests/test_saved_places_import.py` | parser/schema/idempotency/atomicity/security tests |
| `tests/test_saved_places_cli.py` | human/JSON/exit-code/global-option contract tests |
| `tests/fixtures/saved_takeout/` | synthetic non-private official-schema fixtures |
| `docs/API.md` | saved CLI JSON and database contract |
| `docs/architecture.md` | additive saved-place module/data flow |
| `docs/operations.md` | private Takeout/export/import/backup/deploy runbook |

## Task 1: Import Schema And Safe Takeout Parser

**Files:**
- Create: `placeintel/saved_places.py`
- Create: `tests/test_saved_places_import.py`
- Create: `tests/fixtures/saved_takeout/Saved/Date Places.csv`
- Create: `tests/fixtures/saved_takeout/Maps (your places)/Starred places.json`

**Interfaces:**

```python
@dataclass(frozen=True)
class SavedRow:
    source_product: str
    collection_name: str
    collection_description: str | None
    title: str | None
    url: str | None
    note: str | None
    tags: tuple[str, ...]
    comment: str | None
    source_member: str
    source_file_sha256: str
    row_number: int

def ensure_schema(conn: sqlite3.Connection) -> None: ...
def iter_takeout_rows(path: Path, limits: ImportLimits | None = None) -> Iterator[SavedRow]: ...
def import_takeout(
    conn: sqlite3.Connection,
    path: Path,
    *,
    limits: ImportLimits | None = None,
    emit_events: bool = False,
) -> ImportResult: ...
```

- [x] Write failing tests for official Saved CSV description/header parsing,
  Maps (your places) GeoJSON starred-place parsing, BOM/Unicode, missing optional
  fields, stable IDs, same item in multiple collections, and exact double-import
  counts.
- [x] Run `python -m unittest tests.test_saved_places_import -v`; verify RED for
  the missing module/interfaces.
- [x] Implement `ImportLimits`, safe directory/ZIP/CSV member iteration, schema
  aliases, URL normalization, deterministic IDs, and the four additive tables.
- [x] Add malicious ZIP traversal/symlink, oversized file/row, malformed CSV,
  missing-identity, and transaction rollback tests.
- [x] Run the focused suite; expected PASS with no raw private values in errors.
- [x] Update the PRD acceptance/status and commit the milestone atomically.

## Task 2: Human And Agent CLI Contracts

**Files:**
- Create: `placeintel/saved_cli.py`
- Modify: `placeintel/cli.py`
- Create: `tests/test_saved_places_cli.py`
- Modify: `docs/API.md`
- Modify: `docs/agent-cli.md`

**Interfaces:**

```text
placeintel saved-import PATH [--format text|json]
placeintel saved-inventory [--state STATE] [--collection NAME] [--format text|json]
```

```json
{
  "ok": true,
  "version": "<app-version>",
  "command": "saved-import",
  "data": {
    "run_id": "...",
    "source_digest": "...",
    "files": 2,
    "rows": 10,
    "skipped": 0,
    "created": {"collections": 2, "items": 8, "memberships": 10},
    "updated": {"collections": 0, "items": 0, "memberships": 0},
    "states": {"pending": 8}
  }
}
```

- [x] Write RED CLI tests for global/local format placement, stable envelope,
  text counts, usage errors, missing input, empty corpus, and duplicate import.
- [x] Register commands through one `saved_cli.register(subparsers)` adapter and
  keep domain behavior out of `cli.py`.
- [x] Verify existing `tests/test_cli_json_contract.py` remains green.
- [x] Document exact fields, nullable rules, exit codes, and examples.
- [x] Update PRD/router and commit atomically.

## Task 3: Resolution State Machine

**Files:**
- Modify: `placeintel/saved_places.py`
- Modify: `placeintel/saved_cli.py`
- Create: `tests/test_saved_places_resolution.py`
- Modify: `docs/API.md`

**Interfaces:**

```python
def resolution_candidates(conn, *, city=None, state=("pending", "failed"), limit=25) -> list[dict]: ...
def resolve_saved_item(conn, saved_item_id: str, *, refresh=False, dry_run=True) -> ResolutionResult: ...
```

```text
placeintel saved-resolve [--city "Da Nang"] [--limit 25] [--dry-run|--run]
```

- [ ] Write RED tests for exact cached match, renamed/closed/coordinate-only/
  ambiguous/failed states, safe transitions, retry, caps, and source immutability.
- [ ] Reuse cached `place_id` and exact Maps identity before external work.
- [ ] Route bounded live work through existing single-place/provider budgets.
- [ ] Prove interruption leaves committed prior resolutions and retryable pending
  items without duplicate provider calls.
- [ ] Update PRD/router/docs and commit atomically.

## Task 4: Saved-Only Recommendation

**Files:**
- Modify: `placeintel/saved_places.py`
- Modify: `placeintel/saved_cli.py`
- Create: `tests/test_saved_places_recommend.py`
- Modify: `docs/API.md`

**Interfaces:**

```python
def recommend_saved_places(
    conn,
    *,
    origin: str,
    radius_km: float,
    categories: tuple[str, ...],
    budget_min: int,
    budget_max: int,
    currency: str,
    budget_basis: Literal["per_person", "total_for_two"],
    occasion: str = "date",
    limit: int = 10,
) -> list[dict]: ...
```

```text
placeintel saved-recommend --near ORIGIN --radius-km 5 --category cafe \
  --category restaurant --budget-min 100000 --budget-max 200000 \
  --currency VND --budget-basis per_person --occasion date --format json
```

- [ ] Write RED tests proving saved-only membership, distance ordering, closed
  exclusion, budget-basis behavior, unknown-evidence flags, and stable output.
- [ ] Implement deterministic filtering before any optional evidence explanation.
- [ ] Ensure optional AI can explain/rank only the bounded saved candidate set.
- [ ] Run a synthetic E2E and then the real Da Nang five-record acceptance sample.
- [ ] Update PRD/router/docs and commit atomically.

## Task 5: Operations, Release, And Production Proof

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `.env.example`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml` and the package version owner
- Update: installed PlaceIntel skill if CLI surface changes

- [x] Document the narrow official Takeout URL using product ids `save` and
  `local_actions`; keep final export creation deliberate.
- [x] Add input-limit env variables to `.env.example` and config validation.
- [x] Prove backup/restore retains saved tables and raw archives remain excluded.
- [ ] Start/check local Docker or record the bounded resolution fallback; retry
  the Google embedding live check before AI recommendation acceptance.
- [ ] Run focused tests, full Python suite, PRD contract gate, npm/browser gate if
  UI changed, GitNexus detect-changes, secret/privacy scan, and diff check.
- [ ] Deploy only through the private GitHub Actions owner; verify SSH/systemd,
  deploy-smoke, saved inventory, and no new production errors.
- [ ] Update the infrastructure registry only if the long-lived runtime contract
  materially changes; this additive feature alone does not create a new service.
- [ ] Mark the PRD complete, bump minor version, update CHANGELOG, and create the
  release commit/tag only after every acceptance item is proven.

## Plan Self-Review

- PRD coverage: US-001 through US-004 map to Tasks 1-5.
- Placeholders: none; exact interfaces, files, commands, and gates are named.
- Type consistency: saved item, membership, resolution, and recommendation names
  match the PRD data-resolution contracts.
- Scope: first shippable milestone is offline import + inventory; provider/live
  resolution and recommendation remain later bounded milestones.
