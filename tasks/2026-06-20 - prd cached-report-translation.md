# PRD: Cached Report Translation

Created: 2026-06-20
Last Updated: 2026-06-20
Status: 📋 Draft
Feature Type: Full-stack UI feature
Owner: Codex
Deployment Profile: hybrid
Deploy Targets: local FastAPI web app on `127.0.0.1:9618`, protected VPS/systemd lane via existing deploy-smoke contract
Related PRDs:
- `tasks/prd-placeintel-language-adaptation.md`
- `tasks/prd-dossier-ux.md`
- `tasks/prd-placeintel-agent-cli-api.md`

## 1. Introduction

The web UI can already localize its chrome and translate raw review cards on demand, but cached generated reports remain stuck in the language used when the report was created. The screenshot that triggered this PRD shows a Chinese UI surrounding an English dossier report. The user should be able to switch a report into Chinese without regenerating the scout, while preserving the original report exactly.

This feature adds cached report markdown translation. It reuses the existing review-translation pattern: normalize the target language, hash the source text, use the cheap translation model, store the display translation in SQLite, and never overwrite source evidence or generated report originals.

## 2. Goals

- G1: Add a cache-backed translation function for generated report markdown.
- G2: Let the dossier report switch between original and translated target language in one click.
- G3: Preserve original report markdown, raw reviews, report language metadata, and existing Ask/report cache rules.
- G4: Reuse the existing translation provider role and language normalizer; add no new secrets or dependencies.
- G5: Keep the no-build SPA, dossier accessibility contract, and static file line budgets intact.

## 3. User Stories

### US-001: Translate Cached Report

As a Chinese-reading user looking at an English dossier report, I want to translate the cached report to Chinese so I can read the decision brief without regenerating the report.

Acceptance Criteria:
- [ ] `POST /api/reports/translate` accepts a cached `report_id` and safe `target_lang`.
- [ ] The API returns translated markdown, source report language, target language, model, provider, `cached`, and `created_at`.
- [ ] The first call uses `config.translation_model()` via the existing translate provider role.
- [ ] A second call for the same report and target returns from SQLite cache without another provider call.
- [ ] Original `reports.report_md` remains unchanged.
- [ ] Unsafe target tags return a 400-class error and do not call the provider.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-002: Switch Report Display In Dossier

As a user reading a shop dossier, I want a small report-language switch so I can toggle translated and original report text without losing my place in the modal.

Acceptance Criteria:
- [ ] Dossier payload includes the latest report `id`.
- [ ] Dossier report section shows an original/translated switch only when a report exists.
- [ ] Translation target defaults to the active report output language, then falls back to the app translation target.
- [ ] Clicking translate renders the translated markdown in the same report body and shows whether it came from cache.
- [ ] Clicking original restores the untouched original markdown without an API call.
- [ ] Translation failure leaves the original report visible with an actionable retry state.
- [ ] Existing dossier focus trap, Escape close, opener focus restoration, photo lightbox, scoped Ask, review translation, and inline report generation still work.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-003: Keep Future Agents Oriented

As a future agent, I want the new cache table, API contract, and UI behavior documented so I do not rebuild or confuse it with raw review translation.

Acceptance Criteria:
- [ ] `docs/API.md` documents `POST /api/reports/translate`.
- [ ] `AGENTS.md` records that report translations are display-layer only and never replace `reports.report_md`.
- [ ] `CHANGELOG.md`, `progress.md`, and this PRD record the shipped feature and verification evidence.
- [ ] `tasks/README.md` routes this PRD with current status and next action.
- [ ] Typecheck/lint passes.

## 4. Functional Requirements

- FR-001: Add a SQLite `report_translations` table with `report_id`, `target_lang`, `source_hash`, `source_lang`, `translation_md`, `model`, `provider`, and `created_at`.
- FR-002: `report_translations` must be allow-listed backup data only if backups later include it through the existing declared artifact rules; this PRD does not change backup scope.
- FR-003: Add `cache.cached_report_translation()` and `cache.save_report_translation()` mirroring the review translation helpers.
- FR-004: Add `pipeline.translate_report(report_id, target_lang)` as the single backend report-translation owner.
- FR-005: `translate_report()` must call `language.resolve_translation_target()` before provider access.
- FR-006: `translate_report()` must hash current `reports.report_md`; if the source markdown changes, stale translated text must not be reused.
- FR-007: Translation prompt must treat markdown as untrusted content, preserve headings/list structure, names, addresses, prices, dates, ratings, and evidence caveats, and return markdown only.
- FR-008: Add `POST /api/reports/translate` with request fields `report_id` and optional `target_lang`.
- FR-009: Add latest report `id` to `GET /api/places/{place_id}` detail payload.
- FR-010: The web app must render translated report markdown through the existing `mdToHtml()` escape pipeline.
- FR-011: The original report must stay available in memory for instant restoration.
- FR-012: The report translation UI must not share state with review-card batch translation except for target-language defaults.
- FR-013: Failed translation must not clear or mutate the original report body.

## 5. Non-Goals

- Do not regenerate or re-reason a report just to change language.
- Do not translate raw reviews at scrape time or overwrite `reviews.text`.
- Do not replace generated `reports.report_md` or `reports.report_json`.
- Do not add a new translation provider, new API key, external SaaS, or frontend build tool.
- Do not make cheap health call a model or check translation availability.

## 6. Stack and Dependencies

No new dependency. The existing stack is Python/FastAPI + SQLite + no-build vanilla JS. The existing `google-genai` client and `config.translation_model()` provider role are already used for review translation.

Rejected alternatives:

| Alternative | Decision | Reason |
| --- | --- | --- |
| Regenerate report in target language | Reject | Expensive, slow, and loses quick switchability. |
| Store translated report in `reports.report_md` | Reject | Breaks original-report preservation and report-language metadata. |
| Add i18n/markdown library | Reject | Existing `mdToHtml()` and locale helpers cover the UI safely. |
| Browser-only translation | Reject | Would require user browser APIs/extensions and no durable cache. |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Feature | Files Touched | Risk Level | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| Dossier modal rendering | `web/app.js::renderDetail` | HIGH by GitNexus | New Playwright report-translation test plus existing dossier focus tests | Yes |
| Review translation | `placeintel/pipeline.py`, `placeintel/cache.py`, `web/app.js` nearby handlers | Low by GitNexus, product-critical | `tests/test_review_translation.py`, UI review translation tests | Yes |
| Place detail API | `placeintel/server.py::place_detail` | Low by GitNexus API impact | Server contract test for report id payload | Yes |
| SQLite migrations | `placeintel/cache.py::_migrate` | Low by GitNexus | Cache/report translation unit tests on temp DB | Yes |
| Inline report generation | `web/dossier.js`, `web/app.js::openDetail` consumers | Covered by `renderDetail` HIGH impact | Existing inline report Playwright path and node syntax check | Yes |

### 7.2 Security Hardening

| Attack Surface | Threat | Impact if Exploited | Mitigation | Verification |
| --- | --- | --- | --- | --- |
| `target_lang` | Prompt/path injection in language tag | Provider prompt manipulation or cache pollution | Shared BCP-47-like `resolve_translation_target()` validation | Unit/API tests |
| Report markdown content | Prompt injection embedded in report text | Translation model follows report instructions | System prompt says source markdown is untrusted content and translation only | Unit test inspects prompt |
| Rendered markdown | XSS from translated text | Script injection in dossier | Existing `mdToHtml()` escapes before inline markdown formatting | Playwright/UI smoke |
| Secrets | Provider error leaks key | Key exposure in API/UI | Existing `config.redact_secrets()` on job surfaces; endpoint returns normal HTTP errors only | Existing config/server tests |

### 7.3 Error Boundaries

| Component | Failure Mode | User Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| Report lookup | Unknown report id | 404 response; UI keeps original report visible | Reopen dossier or refresh Library | FastAPI HTTP error |
| Target validation | Unsafe target tag | 400 response; UI shows translation failed with retry | Choose a safe target | FastAPI HTTP error |
| Provider call | Timeout/empty response/provider error | Original report remains visible; retry button/control stays enabled | Click translate again; cache hit when available | Server log via existing pipeline logging |
| Cache write | SQLite busy/error | API fails without replacing original | Retry after DB available | Exception trace in server logs |

## 8. UI/UX Architecture

### 8.1 Audience Map

| Audience | Description | Primary Goal | Entry Point |
| --- | --- | --- | --- |
| PlaceIntel owner/user | Non-coder using cached dossiers before visiting shops | Read the latest report in preferred language | Dossier modal from Scout, Shop, or Library |
| Future agent | Maintains the cache/API/UI contract | Extend translation safely without duplicate logic | PRD router, AGENTS.md, tests |

### 8.2 View-to-Interface Dependency Map

| View | Interface/API It Reads | Fields Used | If Interface Changes -> Impact | Hardcoded? |
| --- | --- | --- | --- | --- |
| Dossier modal | `GET /api/places/{place_id}` | `report.id`, `report.md`, `report.report_lang`, `report.created_at`, `place.*`, `reviews[]` | Report switch cannot call translation or restore original | No |
| Dossier report switch | `POST /api/reports/translate` | `report_id`, `target_lang` request; `md`, `cached`, `target_lang`, `model`, `provider` response | Toggle/status breaks | No |
| Scout/Shop results | job result `reports[].md` | Markdown display only | May optionally reuse renderer; no API call needed | No |

### 8.3 Component Reuse Map

| Component | Used In | Props/Config | If Changed -> Affected |
| --- | --- | --- | --- |
| `mdToHtml()` | Report body, Ask answer, translated report body | Markdown string | Report/Ask rendering and XSS safety |
| `renderDetail()` | `openDetail()`, inline report completion refresh, tests | Full place detail payload | Dossier modal, report controls, reviews, scoped Ask |
| `PI18N.languageOptionsHtml()` | Review translation target, System language controls, report translation target | selected tag, auto flag | Language selectors across dossier and settings |

### 8.4 Interaction Pattern

Flow: Dossier opens -> report section shows original report -> user clicks `Translate to 中文` -> button shows loading -> API returns translated markdown -> same report body swaps to translated markdown -> user clicks `Original` -> body restores original markdown.

The happy path is one click after the dossier opens. A target selector is available for non-Chinese targets but defaults to the app's report language/translation target.

## 9. Design System

Use the existing PlaceIntel report and language-lens visual language: compact mono metadata, ghost buttons, small select controls, and no decorative card-in-card pattern. The report translation control sits in a slim toolbar above the report body. It must not compete with the report title or decision brief.

Component details:

| Element | Specification |
| --- | --- |
| Report translation toolbar | Flex row, wraps on mobile, `0.45rem` gap, mono `0.7rem` metadata text |
| Original/translated buttons | Existing `btn-ghost`; selected state uses accent border/background only |
| Target select | Reuse `.translation-target` dimensions and colors |
| Status text | `aria-live="polite"`, mono `0.68rem`, muted ink |

## 10. Responsiveness

At 375px the toolbar wraps into two lines without horizontal scroll. Buttons and select controls keep at least 32px height. The report body width and modal scroll behavior are unchanged.

## 11. Health, Monitoring, and Logging

No cheap health expansion. Translation availability remains visible through existing System provider status and deep diagnostics. Runtime errors are logged by FastAPI/pipeline logs; UI displays a short localized retry message.

## 12. Analytics

No analytics.

## 13. Implementation Principles

- Existing-project-first: mirror review translation instead of inventing a second cache/provider path.
- Contract-first: add the backend cache/API contract before wiring UI.
- No duplicate source of truth: original report markdown remains in `reports`; translations live only in `report_translations`.
- TDD: add failing backend/API/UI tests before implementation.
- Deploy-aware: no hardcoded hostnames, paths, or secrets; feature works locally and in the existing VPS lane.

## 14. Documentation Discipline

Update `AGENTS.md` for the new invariant, `docs/API.md` for the endpoint, `CHANGELOG.md` for the release note, and `progress.md` for verification evidence. The installed `place-intel` skill is unchanged because the CLI surface does not change.

## 15. Technical Considerations

- Translation is display-layer only and may slightly differ from a freshly reasoned target-language report. The UI labels it as translated report text, not as a new analysis.
- Cache invalidation uses source markdown hash, not report creation time alone.
- The first translated report may take a model-call latency; later toggles must be local/cache-fast.
- `report_id` is safer than place id because one place may have multiple reports over time.

## 16. Success Metrics

- Backend report translation unit test observes one provider call for first call and zero for second call.
- API contract test proves `report.id` is exposed and `/api/reports/translate` delegates safely.
- Playwright test proves translated report appears, cached status is shown, and original restore works.
- Existing review translation tests still pass.

## 17. Open Questions

None blocking. Assumption: Chinese should be the primary visible target in the screenshot scenario, while the implementation supports any normalized safe target tag just like review translation.

## 18. Deployment and Configuration

No new environment variables, secrets, ports, process managers, deploy scripts, or reverse proxy rules. Existing deployment profile remains `hybrid`; post-deploy proof remains `placeintel deploy-smoke`.

## Build Progress

- 2026-06-20: PRD drafted after reading `AGENTS.md`, `VAULT.md`, prior language/dossier PRDs, PRD skill references, GitNexus impact reports, and the screenshot evidence.
