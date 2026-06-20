# PRD: placeintel Agent-Readiness Governance

Created: 2026-06-20
Last Updated: 2026-06-20
Status: ✅ Complete
Feature Type: Internal governance
Owner: Codex
Deployment Profile: local-first governance; no runtime product behavior change
Deploy Targets: local repo, private VPS/systemd lane inherits existing deploy-smoke contract
Related PRDs:
- `tasks/prd-placeintel-production-grade-master.md`
- `tasks/prd-placeintel-agent-cli-api.md`
- `tasks/prd-placeintel-production-ops.md`

## 1. Introduction

PlaceIntel is already agent-friendly at the product interface layer: `docs/agent-cli.md` documents machine-readable CLI output, stable exit codes, cheap health checks, deploy smoke, backup/restore, and safe language behavior. The remaining gap is PRD governance. Future agents need a routed PRD index and an executable PRD contract gate so they can tell which planning records are canonical before editing.

## 2. Goals

- G1: Route every current PlaceIntel PRD from `tasks/README.md`.
- G2: Preserve legacy PRD filenames without pretending they satisfy the new filename contract.
- G3: Add `scripts/validate-prd-contract.sh` so agents can verify PRD routing and required headers.
- G4: Keep the change product-safe: no web UI, API, scraper, provider routing, cache, or data migration behavior changes.

## 3. User Stories

### US-001: PRD Router

As a future agent, I want one PRD router so I can find the correct owner record before editing docs or code.

Acceptance Criteria:
- [x] `tasks/README.md` lists every PRD under `tasks/`.
- [x] Router rows include status, created date when known, last updated date, owner surface, and next action.
- [x] Router explicitly states that it is navigation only, not the source of requirements.
- [x] Typecheck/lint passes.

### US-002: PRD Contract Gate

As a future agent, I want an executable PRD contract check so I can prove new PRDs are well-formed and legacy PRDs are deliberately handled.

Acceptance Criteria:
- [x] `scripts/validate-prd-contract.sh --allow-legacy .` passes for the current repo.
- [x] Strict `scripts/validate-prd-contract.sh .` rejects legacy `tasks/prd-*.md` files until they are migrated.
- [x] The gate requires new PRDs to use `YYYY-MM-DD - prd feature-slug.md`.
- [x] The gate requires new PRD header fields: `Created`, `Last Updated`, `Status`, `Feature Type`, and `Owner`.
- [x] The gate fails when a PRD file is not routed in `tasks/README.md`.
- [x] Automated regression tests cover the gate.
- [x] Typecheck/lint passes.

## 4. Functional Requirements

- FR-1 ✅: The router must include all existing task PRDs and this current-format PRD.
- FR-2 ✅: The validator must support `--allow-legacy` because this repo has historical `tasks/prd-*.md` records.
- FR-3 ✅: In strict mode, the validator must fail on legacy filenames so migration remains explicit.
- FR-4 ✅: In all modes, the validator must fail if `tasks/README.md` is missing.
- FR-5 ✅: In all modes, the validator must fail if any PRD file is not mentioned in `tasks/README.md`.
- FR-6 ✅: New-format PRDs must satisfy the current `prd` skill header contract.
- FR-7 ✅: The implementation must not add external dependencies or require model/network calls.

## 5. Non-Goals

- Rename or migrate all historical PRD files in this pass.
- Change PlaceIntel runtime behavior, APIs, UI, provider routing, or deployment.
- Add a Notion, GitHub Issues, or external project-management source of truth.
- Backfill every historical PRD acceptance checkbox.

## 6. Stack and Dependencies

No new dependency. The gate is a small Bash script because the requirement is a repository contract check that should run before Python package install, in CI, or by future agents from a cold checkout.

Rejected alternatives:

| Alternative | Reason Rejected |
| --- | --- |
| Python validator module | More moving pieces for a simple file contract. |
| Node validator | This Python-first repo only uses Node for Playwright smoke tests. |
| GitHub-only workflow | Agents need a local pre-commit/pre-claim gate. |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Feature | Files Touched | Risk Level | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| Product runtime | docs/scripts/version only; no web/server/pipeline behavior touched | Low | Import smoke and cheap doctor | Yes |
| PRD discovery | `tasks/README.md`, `tasks/*.md`, validator | Medium | `tests.test_prd_contract` + validator command | Yes |
| Version fingerprint | `placeintel/__init__.py`, `pyproject.toml` | Low | import smoke + existing version tests when full suite runs | Yes |

### 7.2 Security Hardening

The validator reads local Markdown only. It does not source files, execute PRD content, read secrets, traverse `data/`, call providers, or inspect generated evidence. No auth or credential surface changes.

### 7.3 Error Boundaries

| Component | Failure Mode | User/Agent Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| PRD validator | Missing router, malformed PRD, or legacy strict mismatch | Non-zero exit with actionable stderr bullet | Add route/header or rerun with `--allow-legacy` during migration | stderr only |
| Router | Stale next action | Future agent sees wrong handoff | Update router in same change as PRD status | N/A |

## 8. Architecture

This is a file-governance feature:

1. `tasks/README.md` is the PRD router.
2. `scripts/validate-prd-contract.sh` enforces routing and header invariants.
3. `tests/test_prd_contract.py` proves current-repo and failure-case behavior.

No frontend components, backend routes, schemas, database migrations, or provider clients are added.

## 9. Design System

No UI surface. The human-facing design is document readability: a short table with stable columns, explicit legacy policy, and runnable commands.

## 10. Responsiveness

Not applicable; no visual UI change.

## 11. Health, Monitoring, and Logging

The PRD gate is a cheap local health check for planning records. It should run alongside `.venv/bin/placeintel doctor --json` when future agents claim the repository is ready for new work.

## 12. Analytics

No analytics.

## 13. Implementation Principles

- Existing-project-first: preserve the historical PRD files and links.
- Agentic-first: add the missing router/gate directly because the gap is mechanically verifiable.
- Contract-first: make the PRD contract executable before claiming readiness.
- No duplicate source of truth: router contains status/next action only; requirements stay inside PRDs.

## 14. Documentation Discipline

Update `AGENTS.md`, `progress.md`, and `CHANGELOG.md` with this governance rule. Do not update the installed `place-intel` skill because the CLI surface is unchanged.

## 15. Technical Considerations

The validator intentionally uses conservative filename/header checks rather than parsing Markdown ASTs. The contract is simple enough that regex checks are easier for future agents to maintain.

## 16. Success Metrics

- `scripts/validate-prd-contract.sh --allow-legacy .` exits 0.
- `scripts/validate-prd-contract.sh .` exits non-zero while legacy filenames remain.
- `tests.test_prd_contract` passes.
- GitNexus `detect-changes` reports only expected docs/test/script/version surfaces.

## 17. Open Questions

- Should legacy PRDs be migrated to current filenames in a later cleanup branch? Default answer: only when each PRD is materially reopened.

## 18. Deployment and Configuration

Deployment profile is `local-first governance`. No runtime deploy config changes. The package version bump updates existing `/api/meta` and static asset fingerprint surfaces; deploy proof remains `placeintel deploy-smoke`.

## Build Progress

- 2026-06-20: RED test added for missing PRD contract script.
- 2026-06-20: GREEN implementation added `scripts/validate-prd-contract.sh`, `tasks/README.md`, and this current-format PRD.
- 2026-06-20: Verification passed with `.venv/bin/python -m unittest tests.test_prd_contract -v` and `scripts/validate-prd-contract.sh --allow-legacy .`; strict mode intentionally rejects the 7 legacy PRD filenames.
