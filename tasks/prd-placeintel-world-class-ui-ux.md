# PRD: placeintel World-Class UI/UX

Status: 📋 Draft
Last Updated: 2026-06-14
Parent PRD: `tasks/prd-placeintel-production-grade-master.md`
Scope: Web UI, interaction design, mobile/desktop responsiveness, accessibility, and product workflows.

## 1. Overview

The current app has the right raw material: Scout, Shop, Library, Ask, dossier modal, live timeline, language/rating review lens, translation, model picker, past scouts, and protected deployment. This PRD turns those parts into a cohesive field-intelligence product.

The target experience: the user opens placeintel, types what they need, sees what the app is doing, gets a short decision brief first, can inspect evidence deeply, and can ask precise follow-ups without losing trust or context.

## 2. Goals

- G1: First screen is immediately useful and not a marketing page.
- G2: Main flows require <=2 clicks from intent to job start.
- G3: Dossier first viewport answers "go, caution, avoid, or verify" before long report reading.
- G4: Evidence is always inspectable: listing facts, review snippets, ratings, dates, language, freshness.
- G5: The app works on a phone in a shop doorway as well as on a desktop in planning mode.
- G6: UI remains accessible: keyboard tabs, modal focus trap, labelled controls, no horizontal overflow.
- G7: The no-build 3-file SPA rule remains true unless separately approved.

## 3. User Stories

### US-UI-001: Command Center

As a user, I want one primary input that can handle a need, shop name, or Maps URL so I do not need to choose the perfect tab first.

Acceptance Criteria:
- [ ] First visible field accepts any-language need, shop name, or Maps URL.
- [ ] Input analysis recommends Scout, Shop, or Ask before submit.
- [ ] User can override recommendation manually.
- [ ] Past scouts remain visible below the form.
- [ ] No duplicate scrape starts when the same query has fresh cache; UI explains cache reuse.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-002: Better Scout Results

As a user, I want Scout output to explain what was searched, which candidates were excluded, and what should be read first.

Acceptance Criteria:
- [ ] Plan card shows intent, actual bilingual queries, location, profile, and reasoning.
- [ ] Results show kept vs excluded candidates with reason pills.
- [ ] Deep-dived shops are visually distinct from non-deep-dived candidates.
- [ ] Timeline groups retries and cache hits clearly.
- [ ] User can add result places to Compare without opening each dossier.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-003: Library as Workspace

As a repeat user, I want the Library to feel like a useful workspace, not just a grid of cached cards.

Acceptance Criteria:
- [ ] Library includes search/filter controls for name, category, freshness, risk, language cohorts, cached review count, and report profile.
- [ ] Cards show cache freshness, latest report age, activity risk, review count, cached count, and favorite state.
- [ ] User can select 2-5 cards and open Compare.
- [ ] Empty state guides user back to Scout without technical jargon.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-004: Dossier Decision Brief

As a user near a shop, I want the dossier to show the most actionable information first.

Acceptance Criteria:
- [ ] First viewport includes: verdict, risk level, top hard facts, top 3 walk-in bullets, freshness, and Ask-this-shop.
- [ ] Report body remains available below the brief.
- [ ] Review lens remains available below the report or in an evidence tab.
- [ ] Original review text remains original; translation UI is opt-in/remembered.
- [ ] Dossier focus trap and restoration regressions still pass.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-005: Evidence-Centered Ask

As a user asking follow-up questions, I want an answer and the evidence behind it in the same view.

Acceptance Criteria:
- [ ] Answer card has a compact answer first.
- [ ] Evidence section lists listing facts and review snippets separately.
- [ ] Evidence rows include place, rating/date when available, and original-language tag for translated snippets.
- [ ] Cached-answer banner explains scope and freshness.
- [ ] Re-reason action does not delete the prior cached answer.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-006: Compare Board

As a user deciding between shops, I want side-by-side comparison with evidence and risk.

Acceptance Criteria:
- [ ] Compare supports 2-5 places.
- [ ] Columns include facts, review volume, cached coverage, latest scrape/report age, risk, language mix, low-rating themes, and walk-in advice.
- [ ] User can jump from a comparison cell to the underlying dossier/evidence.
- [ ] Compare does not generate new reports unless explicitly requested.
- [ ] Mobile compare becomes stacked cards with sticky section labels.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-UI-007: Settings and System Status

As the owner/operator, I want model, language, cache, provider, and privacy settings to be visible and safe.

Acceptance Criteria:
- [ ] Settings exposes reasoning model, translation model, default answer language, evidence language, data directory, and cache TTL.
- [ ] Dangerous settings are separated and require confirmation.
- [ ] Provider status is visible without revealing keys.
- [ ] Health checks are reachable from Settings.
- [ ] Missing keys show setup-required state for affected features only.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

## 4. Functional Requirements

### 4.1 Navigation

- FR-UI-001: Keep top-level hash tabs: `#scout`, `#shop`, `#library`, `#ask`.
- FR-UI-002: Add a Settings/System entry without breaking tab roving keyboard behavior. It may be a fifth tab only if the 375px tab bar remains horizontally scroll-safe.
- FR-UI-003: Add Compare as an overlay or inline panel launched from Scout/Library, not a permanent top-level tab.
- FR-UI-004: Every modal/overlay must support Escape close, focus entry, focus trap, and opener restoration.

### 4.2 Command Center

- FR-UI-005: The first form detects input shape locally before submit:
  - URL-like Google Maps input -> recommend Shop.
  - broad need with location -> recommend Scout.
  - question mark or interrogative phrase and non-empty cache -> recommend Ask.
- FR-UI-006: Recommendation must be overrideable and non-blocking.
- FR-UI-007: Advanced controls remain collapsed by default.
- FR-UI-008: The primary action label must reflect the selected mode.

### 4.3 Dossier

- FR-UI-009: Dossier brief must include:
  - verdict or report summary if present.
  - activity risk if present.
  - address, phone, website, hours, map link when present.
  - review coverage: cached count and listed count.
  - latest scrape/report freshness.
  - top 3 walk-in bullets from report JSON/Markdown if parseable.
- FR-UI-010: If no report exists, Dossier must still show listing facts, reviews, Ask-this-shop, and "Generate report" path through Shop.
- FR-UI-011: Long report body must be in a readable section with headings, not a wall of text.
- FR-UI-012: Low-rating review filter must be one tap from the dossier.
- FR-UI-013: Translation target must stay user-selectable and remembered.

### 4.4 Ask

- FR-UI-014: Ask answer component must render:
  - answer label.
  - model/provider tag.
  - cached/fresh status.
  - answer body.
  - evidence drawer/list when backend provides evidence.
- FR-UI-015: Place-scoped history chips must carry original `place_id`.
- FR-UI-016: Top-level Ask history may aggregate scopes for navigation only; cache reuse remains exact-scope.

### 4.5 Compare

- FR-UI-017: Compare source is selected cached `place_id`s.
- FR-UI-018: Compare must read existing `/api/places/{place_id}` or future batch endpoint; no frontend re-resolution of facts.
- FR-UI-019: Compare must include "unknown" states instead of blank cells.
- FR-UI-020: Compare must support clearing selection.

### 4.6 Line Budget and File Strategy

- FR-UI-021: Before adding UI code, implementation agent must run `wc -l web/index.html web/app.css web/app.js`.
- FR-UI-022: If any target file would exceed 800 lines, agent must first compact duplicate code or defer the feature.
- FR-UI-023: If compaction would harm maintainability, agent must stop and write an architecture PRD proposing a no-build ES-module split and AGENTS.md update.

## 5. Non-Goals

- Do not build a marketing landing page.
- Do not add decorative illustration-only sections.
- Do not add a map canvas unless it directly supports place decision-making.
- Do not add account management or billing.
- Do not replace the current bilingual Chinese/English product voice.

## 6. Stack and Dependencies

No new frontend dependency by default. Reuse:

| Existing Asset | Use |
| --- | --- |
| `web/index.html` | Structure and accessible landmarks |
| `web/app.css` | Token system, layout, light/dark |
| `web/app.js` | Existing render helpers, state, API wrappers |
| `tests/ui-audit.spec.js` | Browser behavior coverage |
| `tests/test_web_static_contract.py` | Static and line-budget contracts |

Rejected for first pass:

| Alternative | Reason |
| --- | --- |
| React/Vite | Violates current 3-file no-build constitution unless separately approved |
| Tailwind | Adds build/config surface and duplicates existing token system |
| Heavy map library | Not needed for immediate decision flow; source Google Maps links already exist |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Area | Risk | Must Verify |
| --- | --- | --- |
| Dossier render path | HIGH per GitNexus `renderDetail` impact | open detail, ask form, report, reviews, filters, translation, focus trap |
| Tabs/deep links | Medium | `#scout/#shop/#library/#ask`, Arrow/Home/End, skip link |
| Dynamic scraped text | High security risk | XSS fixture renders escaped |
| Mobile layout | Medium | 375px and 390px no overflow |
| Dark mode | Medium | core views and modal |

### 7.2 Error States

| View | State | Display |
| --- | --- | --- |
| Command Center | setup-required | Missing key/provider message with Settings link |
| Scout/Shop | running | Timeline with live current stage |
| Scout/Shop | partial | Results plus warnings, not total failure |
| Library | empty | "No cached shops yet" plus Scout action |
| Dossier | no report | Facts/reviews visible plus report generation path |
| Ask | empty cache | Explain to run Scout first |
| Compare | less than 2 selected | Disabled compare action with hint |

## 8. UI Architecture

### 8.1 Audience-Page Matrix

| View | Primary Audience | Job |
| --- | --- | --- |
| Command Center | Traveler/user | Start right workflow quickly |
| Scout results | Traveler/user | See candidates, AI exclusions, progress |
| Library | Repeat user/operator | Manage cache and revisit evidence |
| Dossier | Traveler/user | Decide what to do at one place |
| Ask | Traveler/user | Ask global or scoped evidence questions |
| Compare | Traveler/user | Choose among places |
| Settings/System | Operator/agent | Inspect health, model, config, privacy |

### 8.2 Navigation Flow

```text
Command Center -> Scout job -> Results -> Dossier
Command Center -> Shop job -> Dossier
Command Center -> Ask -> Answer evidence
Library -> Dossier
Library -> Compare -> Dossier
Dossier -> Ask-this-shop -> Scoped answer -> QA history
Settings -> Health/Provider diagnostics -> return to previous tab
```

### 8.3 View-to-Interface Map

| View | Interface | Fields Used | Hardcoded? |
| --- | --- | --- | --- |
| Command Center | `/api/searches`, future mode detector | query, location, source, places | No |
| Scout job | `/api/scout`, `/api/jobs/{id}` | job_id, status, events, result | No |
| Shop job | `/api/shop`, `/api/jobs/{id}` | job_id, status, events, result | No |
| Library | `/api/places`, `/api/searches` | place facts, risk, counts, history | No |
| Dossier | `/api/places/{place_id}` | place, reviews, report | No |
| Ask | `/api/ask`, `/api/qa` | answer, cached, model, provider, history | No |
| Model picker | `/api/meta`, `/api/models`, `/api/settings` | provider info, model list | No |
| Settings | future `/api/health`, `/api/config` | health, config tiers | No |

### 8.4 Component Reuse Map

| Component / Function | Used In | If Changed |
| --- | --- | --- |
| `renderSearchRow` | Scout past scouts, Library history | Verify both surfaces |
| `renderDetail` | Dossier, synthetic tests | Verify all dossier tests |
| `renderLanguageLens` | Dossier raw reviews | Verify language/rating/translation filters |
| `renderAnswer` | Ask, Dossier Ask | Verify cached/fresh/scoped answers |
| `startJob/pollJob` | Scout, Shop | Verify timelines, cache hits, errors |
| `apiGet/apiPost/apiDelete` | All web API calls | Verify error messaging and JSON handling |

## 9. Design System

### 9.1 Visual Philosophy

Field notebook meets command center: calm paper surface, strong ink hierarchy, red accent only for primary action and meaningful risk, monospaced metadata for traceability, readable report typography, compact controls for mobile use.

Reference principles:
- Google Maps current AI direction: conversational local queries and review/place summaries.
- Perplexity-style evidence discipline: answer first, sources close by.
- WAI-ARIA APG: modal focus must stay inside the dialog.
- Material 3 token thinking: semantic roles instead of arbitrary one-off colors.

### 9.2 Color Tokens

| Token | Light | Dark | Rule |
| --- | --- | --- | --- |
| Paper | `#f7f5ef` | `#171720` | Main background only |
| Ink | `#303038` | `#ecebe5` | Primary text |
| Muted ink | token mix | token mix | Secondary text; must pass AA for body-sized labels |
| Accent red | `#c8473d` | `#e47a62` | Primary actions, not decoration |
| Success green | `#4c8f6c` | `#8bc8a4` | Verified/cache/safe status |
| Warning amber | `#a96f1f` | `#e5b15a` | Caution, stale, verify status |
| Border | `#d8d6d0` | `#484852` | Separators and cards |

### 9.3 Typography

| Style | Font | Size | Usage |
| --- | --- | --- | --- |
| Product title | SF Mono/ui-monospace | 28-38px responsive | Brand |
| Labels/chips | SF Mono/ui-monospace | 11-13px | Metadata, controls |
| Body | system sans/PingFang SC | 16px | UI copy |
| Report | current Markdown body | 16-18px | Generated long text |
| Data numbers | SF Mono/ui-monospace | 13-16px | ratings/counts/dates |

### 9.4 Component Specs

| Component | Spec |
| --- | --- |
| Primary button | min-height 44px, accent background, on-accent text, 8px radius |
| Ghost button | transparent, 1.5px border or subtle background, 8px radius |
| Chip | 28-34px height, mono label, active/pressed state via border + background |
| Dossier panel | mobile full-height, desktop right sheet max 760px, scroll body only |
| Walk-in brief | top card or band, not nested inside another card |
| Evidence row | rating/date/place metadata, snippet text, source action |
| Compare board | desktop table/cards, mobile stacked sections |

### 9.5 Motion

| Element | Animation | Duration | Easing |
| --- | --- | --- | --- |
| Tab panel enter | slight rise/fade | 300ms | `var(--ease)` |
| Dossier enter/exit | sheet translate + fade | 200ms | ease-out / ease-in |
| Chip active | color/background | 150ms | `var(--ease)` |
| Timeline event | subtle fade/slide | 150ms | ease-out |

Do not animate raw review text, long report body, or table layout changes.

## 10. Responsiveness

Breakpoints:
- 375px: primary mobile. Single-column, sticky action only if it does not cover content.
- 390px: iPhone common width. No clipped placeholders.
- 768px: tablet. Compare may use two-column grouping.
- 1024px+: desktop. Dossier right sheet, compare grid.
- 1440px+: max readable content width, no stretched report paragraphs.

## 11. Health and Monitoring UI

Settings/System must show:
- App version.
- Reason/embed/translation provider and model.
- DB path status without revealing local private paths on public screens.
- Data directory writable.
- Provider status last checked.
- Scraper status: Chrome/Docker/SerpAPI fallback.
- Last backup time once backup feature exists.

## 12. Analytics

Local-only counters may track:
- Scout jobs started/completed/failed.
- Cache hits vs live runs.
- Ask cache hits.
- Translation cache hits.
- Dossier opens and Compare opens.

No external analytics by default.

## 13. Implementation Principles

- Build on existing render helpers; do not duplicate rendering logic.
- Keep dynamic text escaped.
- Add tests before high-risk dossier changes.
- Use progressive disclosure: advanced settings and deep evidence below concise decisions.
- Preserve Chinese/English labels where they help the product voice.

## 14. Documentation

Update:
- `README.md` screenshots/usage after UI is built.
- `docs/API.md` if API shapes change.
- `AGENTS.md` component reuse map if components change.
- `CHANGELOG.md` and `progress.md` after every shipped story.

## 15. Technical Considerations

- The current web files are close to line budget. UI implementation must begin with a code-size plan.
- Native HTML controls and details/summary are preferred where they provide accessible behavior without JS weight.
- Dossier rendering is a shared hot path; any extraction or compaction must be tested.

## 16. Success Metrics

- A new user can run a Scout and understand progress without reading README.
- A phone user can open a dossier and see actionable facts in the first viewport.
- A power user can compare multiple cached places without repeated scraping.
- Keyboard-only user can navigate tabs, open/close dossier, use Ask, and change filters.
- Playwright screenshot or DOM checks cover mobile/desktop and dark mode.

## 17. Open Questions

- Should Compare persist named comparison sets? Default: no, only current session until favorites PRD.
- Should Settings be a fifth top-level tab? Default: use compact System panel first to protect mobile nav.
- Should screenshots be committed? Default: only if used as verification artifacts under existing output conventions.

## 18. Deployment Notes

The protected public domain can expose the same UI only if cost-bearing actions remain authenticated. If broader sharing is desired, create a separate public read-only report view PRD.
