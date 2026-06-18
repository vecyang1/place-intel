# PRD: placeintel Language Adaptation System

Status: ✅ Implemented in v0.4.40
Last Updated: 2026-06-15
Deployment Profile: hybrid
Deploy Targets: local FastAPI web app on `127.0.0.1:9618`, protected VPS/systemd lane when deployed
Parent PRDs:
- `tasks/prd-placeintel-production-grade-master.md`
- `tasks/prd-placeintel-world-class-ui-ux.md`
- `tasks/prd-placeintel-agent-cli-api.md`
Mode: Implemented. Keep this PRD as the owner record for the language contract.

## 0. Clarification Assumptions

The user asked to write PRD(s) to make the app adapt to any language user because the current language experience is messy. The PRD skill normally stops for a clarification gate. For this draft, the gate is resolved by these explicit assumptions so implementation can start later without more guessing:

| Question | Assumed Decision |
| --- | --- |
| Scope | Whole-product language contract: web shell, Scout/Shop, Ask, reports, review translation, settings, CLI/API docs. |
| Default behavior | Auto-detect browser language on first web load, persist the user's choice, and fall back to English when no confident user preference exists. |
| UI locale coverage | Built-in UI copy ships in English and Simplified Chinese first. The architecture must accept BCP-47 language tags and allow more locale packs without touching business logic. |
| AI output coverage | Ask answers, reports, evidence summaries, planner messages, and review translations must be able to target any normalized BCP-47 language tag supported by the reasoning/translation provider, not only `zh` and `en`. |
| Raw evidence | Scraped reviews stay original forever. Source language and display language are tagged separately. Translations are display-layer and cached by target language. |
| Web architecture | Preserve the no-build SPA and current accessibility contracts. If the 3-file rule blocks a maintainable locale catalog, implementation must update `AGENTS.md` first to approve a bounded no-build static module split. |
| Deployment | No new secrets, no new auth, no paid translation service, and no model calls in cheap health. |

## Research and Context Snapshot

Existing project facts at planning time:

- Stack is Python/FastAPI + SQLite + a no-build web shell served from `web/`.
- Current static line counts before this PRD work: `web/index.html` 232, `web/app.css` 793, `web/app.js` 779. Language work could not be added safely without compaction or an approved static module split.
- The app already accepts any-language Scout input through `planner.py`, but output defaults are uneven: `AskRequest.report_lang = "zh"`, `/api/config` returns `"default_answer_language": "zh"`, `pipeline.ask()` defaults to `"zh"`, CLI `ask/report` default to `"zh"`, and review translation target defaults to `zh`.
- The web UI has hardcoded Chinese plus English fragments in `web/index.html` and `web/app.js`, including relative-time strings, stage labels, empty states, error states, system-status copy, cached-answer copy, review translation labels, and language-lens labels.
- Current review translation is intentionally display-layer only: `POST /api/reviews/translate` writes `review_translations`, never overwrites `reviews.text`, and uses the cheap translation role.
- Current `TRANSLATION_TARGETS` in `placeintel/pipeline.py` only allows `zh` and `en`. That is the main backend blocker for "any language" review translation.
- Current `LANG_META` and `detectReviewLang()` are client-side heuristics that describe language cohorts, not country. The existing product rule forbids inventing reviewer country from text language.
- GitNexus is current at commit `1f43d30`. `renderDetail` is HIGH risk because it affects `openDetail`, `bindGlobal`, and `init`. `/api/ask`, `pipeline.ask`, `/api/reviews/translate`, `pipeline.translate_review`, and `/api/config` are graph LOW risk but product-critical.
- `ui-ux-pro-max` is not installed in this environment. This PRD anchors design to the existing placeintel design system, not a new visual direction.

## Implementation Status — v0.4.40

Implemented on 2026-06-15:

- Backend language owner: `placeintel/language.py` now normalizes safe
  BCP-47-like tags, resolves output-language precedence, validates settings,
  exposes supported UI locales, and owns translation-target instructions.
- API/CLI contract: Scout, Shop, Ask, reports, `/api/config`, and
  `/api/settings/language` now use optional language overrides plus shared
  defaults instead of hardcoded Chinese. Ask cache rows include `answer_lang`;
  reports include `report_lang` and `evidence_lang`.
- Review translation: `/api/reviews/translate` accepts safe targets beyond
  `zh/en` while keeping raw `reviews.text` original and using the cheap
  translation model.
- Web contract: `web/i18n.js` owns English/Chinese locale packs, browser
  language detection, local preference migration, `Intl` formatting, and request
  payload language hints. The no-build app is now an approved bounded static
  split: `index.html`, `app.css`, `app.js`, and `i18n.js`.
- Settings/System: the System panel exposes UI, Ask/report, and review
  translation language controls, with browser-only save plus optional app-wide
  default persistence.
- Regression proof: focused unit/static/API/CLI language contracts are green,
  and the full verification loop is recorded in `progress.md` for v0.4.40.

Stack research:

| Candidate | Current Version Checked | Decision | Why |
| --- | --- | --- | --- |
| Native browser `Intl.*` | built into target browsers | Use | Best fit for relative time, dates, numbers, locale display labels, and no new dependency. |
| Project-owned locale catalog | local static file or compact in-app object | Use | Keeps UI copy deterministic, reviewable, and offline-friendly. |
| Existing VectorEngine translation model | `config.translation_model()` default | Use | Already routed, cheap, and provider-visible. |
| i18next | npm `26.3.1`, MIT | Defer | Excellent ecosystem, but too much for the first no-build SPA pass unless locale complexity grows. |
| `intl-messageformat` | npm `11.2.8`, BSD-3-Clause | Defer | Useful for ICU plural rules later; not needed while native `Intl` plus small templates covers the current UI. |
| `@formatjs/intl` | npm `4.1.13`, MIT | Defer | Good if the app moves to a packaged frontend; unnecessary for the current static shell. |

## 1. Overview

placeintel should feel native to the person using it, regardless of whether they search in Chinese, English, Vietnamese, Korean, Japanese, Thai, French, Spanish, or another language. Today the app partly does this at the AI planning layer, but the product experience is inconsistent: the UI shell is mostly Chinese with English fragments, Ask/report defaults often force Chinese, review translation only supports two targets, and raw review languages sometimes leak into answers without clear source-language tagging.

This feature introduces one language adaptation contract with four separate concepts:

1. `ui_language`: language of buttons, labels, navigation, empty states, dates, numbers, and static app chrome.
2. `answer_language`: default language for Ask answers.
3. `report_language`: default language for Scout/Shop reports.
4. `source_language`: detected or provider-supplied language of original reviews and evidence.

The product promise is simple: the user picks or is detected as a language user once, and the app adapts consistently while preserving original evidence.

## 2. Goals

- G1: Replace scattered `zh` defaults with a single language preference contract that every web, API, CLI, report, Ask, and review-translation path can consume.
- G2: Make the first web load choose a sensible language automatically from browser preferences, then persist explicit user overrides.
- G3: Keep raw scraped evidence original while making displayed reports, Ask answers, evidence quotes, dates, numbers, and review translations follow the user's language.
- G4: Support any normalized BCP-47 target language for AI outputs and review translations, with English fallback for UI locale packs that do not exist yet.
- G5: Keep provider routing, all-review coverage, exact-scope QA cache invalidation, fail-open planning/filtering, and display-layer translation invariants intact.
- G6: Make implementation maintainable under the no-build SPA constraint by centralizing UI copy and language state rather than sprinkling string conditionals through `web/app.js`.
- G7: Add targeted regression gates for high-risk UI paths before implementation claims completion.

### 2.1 Success Metrics

| Metric | Current Baseline | Target |
| --- | --- | --- |
| First-load UI language | `<html lang="zh">` and hardcoded Chinese/English mix | Browser language detected, `html.lang` updated, English fallback if no locale pack. |
| Ask default language | `"zh"` unless caller overrides | Explicit request > persisted preference > browser preference > input-language heuristic > English fallback. |
| Report default language | Planner may infer, but several callers fall back to `zh` | Scout/Shop/report use the same preference precedence and show the selected output language. |
| Review translation target | localStorage `zh`, only `zh/en` backend allow-list | Any normalized target tag accepted for AI translation, built-in UI labels for common languages, cached by target. |
| Source/display separation | Heuristic language lens plus mixed report snippets | Every evidence display distinguishes original source language from display target. |
| Web copy ownership | strings scattered across HTML/JS | All non-review UI copy comes from a translation helper/catalog or documented fallback. |

## 3. User Stories

### US-LANG-001: Detect and Persist User Language

As any-language user, I want placeintel to start in my language when possible so that I do not feel like I landed in someone else's private tool.

Acceptance Criteria:

- [ ] On first web load, the app reads `navigator.languages` and normalizes the first usable BCP-47 tag.
- [ ] If `placeintel.userLanguage` exists in localStorage, it overrides browser detection.
- [ ] If backend `settings.json` has a saved default language, `/api/config` exposes it and the web app uses it when localStorage is absent.
- [ ] If neither persisted nor browser preference is usable, the app falls back to `en`.
- [ ] `document.documentElement.lang` updates to the active `ui_language`.
- [ ] Existing `placeintel.translationTarget` migrates into the new preference only as `translation_target`; it must not silently force the whole UI to Chinese for a non-Chinese browser.
- [ ] Language changes take effect without a server restart.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-LANG-002: Localize Web Chrome and Time/Number Formatting

As a user reading the web app, I want labels, buttons, statuses, dates, counts, and error states to be consistently in my selected UI language.

Acceptance Criteria:

- [ ] All static app chrome in `web/index.html` is rendered from localized strings or updated by the startup localization pass.
- [ ] All dynamic non-review UI strings in `web/app.js` use a shared `t(key, params)` helper or equivalent safe text-rendering path.
- [ ] `relTime()`, numeric counts, and clock/date labels use native `Intl.RelativeTimeFormat`, `Intl.NumberFormat`, and `Intl.DateTimeFormat` with the active locale.
- [ ] Missing locale keys fall back to English and log one dev-visible warning per missing key, without breaking the UI.
- [ ] User-generated or scraped text still goes through `esc()` or safe DOM text APIs.
- [ ] Existing tab roles, roving `tabindex`, skip link, modal focus trap, photo lightbox controls, and hash deep links remain intact.
- [ ] Static file line budgets still pass. If they cannot pass cleanly, implementation must first update `AGENTS.md` and tests to allow a bounded no-build locale module split.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-LANG-003: Make Scout, Shop, Ask, and Reports Follow the Preference Contract

As a user asking or scouting in my language, I want the app's AI outputs to answer in that language unless I explicitly choose otherwise.

Acceptance Criteria:

- [ ] `ScoutRequest`, `ShopRequest`, `AskRequest`, CLI `scout`, CLI `shop`, CLI `ask`, and CLI `report` all accept an optional `report_lang` / output language override.
- [ ] When no override is provided, all paths resolve language through the shared precedence: explicit request > saved preference > browser/web request hint > planner/input-language heuristic > `en`.
- [ ] `planner.py` may still infer the language of the user's query, but it must not override an explicit saved or request-level preference.
- [ ] Reasoning prompts continue to include today's date.
- [ ] Ask cache keys and cache freshness rules remain exact-scope. Changing language must not incorrectly reuse an answer written in a different target language unless the cache key includes the target language.
- [ ] Report rows preserve their `report_lang`; UI clearly shows which language a cached report was generated in.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-LANG-004: Preserve Raw Evidence While Translating Display Output

As a user comparing reviews in multiple source languages, I want to know what language the original review was in and read translations in my language without losing the original.

Acceptance Criteria:

- [ ] `reviews.text` remains the scraped original and is never overwritten by display translation.
- [ ] Review cards show original language when known or detected, using language labels rather than reviewer-country claims.
- [ ] `POST /api/reviews/translate` accepts normalized target tags beyond `zh` and `en`, validates them safely, and uses the cheap translation model.
- [ ] `review_translations` cache lookup and save remain keyed by raw-text hash plus normalized target language.
- [ ] Translation prompt includes source language, target language tag, and an instruction to preserve concrete names, prices, dates, and quote meaning.
- [ ] If translation fails, the original review remains visible with a localized retry/recovery state.
- [ ] Evidence quotes in reports and Ask answers are translated into the output language by default and tagged with original language, unless `evidence_lang=original`.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-LANG-005: Add Language Controls to Settings/System

As the product owner, I want language behavior to be visible and changeable from the existing System area so that I do not need to edit code or remember hidden localStorage keys.

Acceptance Criteria:

- [ ] Settings/System exposes the active UI language, answer/report language, review translation target, and evidence-language mode.
- [ ] The language selector includes built-in `en` and `zh` choices plus an "Auto" option that follows browser preference.
- [ ] The review translation target selector accepts common quick picks and a safe custom BCP-47 tag entry.
- [ ] Saving a language preference writes to backend settings when the user chooses "make default for this app" and to localStorage for browser-only preference.
- [ ] `/api/config` exposes non-secret language config and supported UI locale metadata.
- [ ] The existing dangerous settings boundary remains intact; no destructive cache/restore actions move into the web UI.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

### US-LANG-006: Verify the Whole Language Contract

As a future agent, I want proof that language adaptation works across UI, API, CLI, Ask, reports, review translation, and dossier views.

Acceptance Criteria:

- [ ] Add unit tests for language normalization, preference precedence, cache-key language separation, and `target_lang` validation.
- [ ] Add server contract tests for `/api/config`, language settings save/load, `/api/ask` default language resolution, and `/api/reviews/translate` non-`zh/en` target acceptance.
- [ ] Add static web tests that fail on new hardcoded user-facing Chinese/English strings outside the locale catalog, while allowing scraped/evidence fixtures.
- [ ] Add Playwright tests for at least English, Chinese, and one non-built-in UI fallback language such as Vietnamese or French.
- [ ] Add CLI JSON tests proving `ask/report/scout/shop` expose or honor output language fields.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.
- [ ] Run `npx playwright test tests/ui-audit.spec.js`.
- [ ] Run `node --check web/app.js`, the web static contract test, `git diff --check`, `.venv/bin/placeintel doctor --json`, and local `placeintel deploy-smoke`.
- [ ] Typecheck/lint passes.
- [ ] Visual verification via dev-browser or preview skill.

## 4. Functional Requirements

### 4.1 Language Preference Contract

- FR-001: Add one backend language-resolution owner, for example `placeintel/language.py`, that normalizes language tags and resolves defaults for API/CLI/server code.
- FR-002: Add one frontend language state owner, for example a compact `languageState` section in `web/app.js` or an approved `web/i18n.js`, that resolves and broadcasts active UI/output languages.
- FR-003: The shared preference shape must be documented and exposed through `/api/config`:

```json
{
  "ui_language": "en",
  "answer_language": "en",
  "report_language": "en",
  "translation_target": "en",
  "evidence_language": "report",
  "source": "localStorage|settings|browser|request|planner|default",
  "fallback_language": "en",
  "supported_ui_locales": ["en", "zh"]
}
```

- FR-004: Language tags must be normalized to safe BCP-47-like tags with lowercase language subtags, uppercase region subtags where applicable, and a bounded length. Invalid tags fall back without raising user-visible raw errors.
- FR-005: Supported UI locales in the first implementation are `en` and `zh`. AI output targets may be any normalized safe tag, even when no UI locale catalog exists.
- FR-006: Precedence for output language is:
  1. Explicit per-request `report_lang` / `target_lang`.
  2. Persisted user/system preference.
  3. Browser language hint from the web request.
  4. Planner/input-language heuristic.
  5. English fallback.
- FR-007: Existing `PLACEINTEL_EVIDENCE_LANG` remains valid and controls whether quoted evidence is translated into the report language or shown in original form.
- FR-008: Existing model settings remain separate: reasoning model, translation model, and embedding model are not language preferences.
- FR-009: Cheap health must remain cheap and only report language config shape/readiness; it must not call translation or reasoning models.

### 4.2 Web UI Localization

- FR-010: Replace hardcoded UI copy in `web/index.html` with localized startup rendering or data-key placeholders. Product brand text `placeintel` may remain static.
- FR-011: Replace hardcoded UI copy in `web/app.js` with a catalog-backed helper for labels, commands, states, badges, errors, empty states, system panel text, stage labels, buttons, tooltips, and aria labels.
- FR-012: Locale catalog entries must use named parameters for dynamic values, for example `t("reviews.cached_count", {count})`.
- FR-013: The web app must not use negative letter spacing or viewport-scaled font sizes when adapting languages.
- FR-014: Layout must tolerate at least 35% text expansion in Latin-script locales without clipped controls at 375px, 390px, 768px, 1024px, and 1440px widths.
- FR-015: Dates, relative time, number formatting, and rating/count labels must use native `Intl` APIs in the active UI locale.
- FR-016: Locale fallback must be deterministic: missing key in active locale -> English key -> readable key name in dev mode.
- FR-017: Review text, place names, addresses, report markdown, Ask answers, and model output are content, not UI chrome. They must not be forcibly rewritten by the UI locale layer.

### 4.3 API, CLI, and Cache Contracts

- FR-018: `AskRequest.report_lang` default must stop being hardcoded to `"zh"` and must resolve through the language owner.
- FR-019: `/api/scout`, `/api/shop`, `/api/ask`, and CLI equivalents must include the resolved output language in job request metadata and result metadata.
- FR-020: QA cache lookup must include target answer language or must otherwise prove the answer language matches before returning cached content.
- FR-021: `/api/qa` display history may aggregate scopes as it does today, but each history item must retain its original language metadata for re-ask.
- FR-022: Reports must store and return `report_lang`, `evidence_lang`, and model/provider metadata.
- FR-023: CLI `--format json|ndjson` output must include language fields without ANSI or localized machine keys. Human prose may localize; machine field names must remain stable English identifiers.
- FR-024: `docs/API.md` and `docs/agent-cli.md` must document the language fields and precedence.

### 4.4 Review Translation and Evidence Language

- FR-025: Replace `TRANSLATION_TARGETS = {"zh", "en"}` with a safe language-target resolver that accepts normalized BCP-47 tags.
- FR-026: Built-in display labels for common targets must include at least `en`, `zh`, `vi`, `ko`, `ja`, `th`, `fr`, `es`, and `de`.
- FR-027: Unknown but valid target tags must be accepted with a generic target instruction such as `Target language tag: xx-YY`.
- FR-028: Translation request validation must reject blank, path-like, script-like, overlong, or control-character target values.
- FR-029: Translation cache rows must preserve `target_lang`, `source_lang`, `model`, `provider`, and `created_at`.
- FR-030: Batch translation in the dossier must continue to operate only on visible filtered reviews and must keep the existing stale-token/busy guard.
- FR-031: Source language detection must be conservative. If unknown, show "unknown source language" rather than guessing nationality.

### 4.5 Data Resolution Ownership

| Data Type | Resolution Logic | Resolution Owner | Fallback Chain | Consumers Must NOT Re-resolve |
| --- | --- | --- | --- | --- |
| UI language | Browser/localStorage/settings/request -> supported UI locale | `web` language state owner | supported locale -> English | All web views |
| Output language | explicit request/settings/browser/planner/default | backend language owner | explicit -> saved -> browser -> planner -> English | Scout, Shop, Ask, report, CLI |
| Review source language | provider value or conservative detector | cache/language owner, with web fallback only when absent | stored lang -> detector -> unknown | Review lens, translation prompt, evidence tags |
| Translation target | normalized user preference or request target | backend language owner | request -> saved target -> active output language -> English | `/api/reviews/translate`, review cards |
| Locale labels | known language display names | web locale catalog + native `Intl.DisplayNames` where available | catalog label -> native label -> tag | Selectors, badges, System panel |

## 5. Non-Goals

- NG-001: Do not translate or overwrite stored original reviews.
- NG-002: Do not infer reviewer country, nationality, or visitor segment from language alone.
- NG-003: Do not add user accounts, multi-user profiles, or SaaS locale settings in this PRD.
- NG-004: Do not add a new paid translation API or new secret.
- NG-005: Do not replace the current FastAPI/SQLite/no-build web stack with React, Vite, i18next, or FormatJS in the first implementation pass.
- NG-006: Do not localize machine-readable JSON field names. APIs and CLI JSON stay stable English-keyed contracts.
- NG-007: Do not put live model calls into `placeintel doctor --json` or `GET /api/health`.
- NG-008: Do not relax exact-scope QA cache invalidation to make multilingual history easier.

## 6. Stack and Dependencies

| Dependency | Version | Purpose | Decision | Declared In |
| --- | --- | --- | --- | --- |
| Native browser `Intl` APIs | browser built-in | Date, relative time, number, language display labels | Use | No dependency |
| Existing Python stdlib + small helper module | Python runtime | Normalize and validate tags, resolve precedence | Use | `placeintel/language.py` |
| Existing SQLite/settings.json | current project | Persist system language defaults and translation cache | Use | `placeintel/cache.py`, `placeintel/config.py` |
| Existing VectorEngine translation role | current project | Display-layer review translation | Use | `placeintel/config.py`, `placeintel/pipeline.py` |
| i18next | npm `26.3.1` | Full-featured web i18n | Defer | Not added |
| `intl-messageformat` | npm `11.2.8` | ICU message formatting | Defer | Not added |
| `@formatjs/intl` | npm `4.1.13` | Polyfills/message formatting | Defer | Not added |

Build-vs-buy decision:

- Use native `Intl` and a project-owned catalog because the first implementation needs deterministic static strings, no bundle/build step, and a small surface.
- Reconsider i18next or FormatJS only if future locale packs require plural/gender rules beyond simple templates or if the web shell moves to a packaged frontend.

Backend decision:

- No new backend platform is needed. The feature reuses FastAPI, SQLite, `settings.json`, and existing provider routing.

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Feature | Files Likely Touched | Risk Level | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| Dossier modal and review lens | `web/app.js`, `web/app.css`, `web/index.html` | HIGH - GitNexus `renderDetail` impacts `openDetail`, `bindGlobal`, `init` | Existing and new Playwright dossier tests: open, focus trap, review filters, translation, photo lightbox, no console errors | Yes |
| Ask exact-scope cache and history | `placeintel/pipeline.py`, `placeintel/server.py`, `web/app.js`, `docs/API.md` | MEDIUM product risk | Server contract tests for cache scope, language-specific cache separation, re-ask from history | Yes |
| Report generation over all reviews | `placeintel/analyze.py`, `placeintel/pipeline.py` | MEDIUM | Existing analyze/report tests plus prompt snapshot or fake-client tests for output language and evidence language | Yes |
| Review translation display layer | `placeintel/pipeline.py`, `placeintel/cache.py`, `placeintel/server.py`, `web/app.js` | MEDIUM | Existing translation tests plus non-`zh/en` target, cache hit, failure recovery, original text preserved | Yes |
| Settings/System status | `placeintel/server.py`, `web/app.js`, `tests/test_server_contract.py` | LOW graph risk, MEDIUM UX risk | Config endpoint contract tests and System panel Playwright checks | Yes |
| Static web contract and line budget | `web/*`, `tests/test_web_static_contract.py` | HIGH maintainability risk | Static contract tests for line counts, hardcoded string scanner, `esc()`/safe dynamic rendering | Yes |
| Provider routing and cheap health | `placeintel/config.py`, `placeintel/doctor.py`, `placeintel/server.py` | MEDIUM | `doctor --json`, `/api/health`, provider metadata tests without live model calls | Yes |

HIGH-risk warning for implementers: do not change `renderDetail` or shared web rendering helpers without running impact analysis, updating the regression table if GitNexus finds new affected flows, and verifying the dossier modal in a browser.

### 7.2 Security Hardening

| Attack Surface | Threat | Impact if Exploited | Mitigation | Verification |
| --- | --- | --- | --- | --- |
| Locale key rendering | XSS through malicious locale/string parameters | Script execution in web UI | Locale catalog is static/trusted; all dynamic params pass through `esc()` or text nodes | Static tests and Playwright malicious fixture |
| Scraped review text | Prompt injection or HTML injection | Unsafe UI or polluted LLM answer | Keep `esc()` path; prompts label reviews as evidence, not instructions | Existing hostile-review tests plus new language cases |
| `target_lang` input | Prompt injection or malformed tag | Translation prompt manipulation | Strict normalization and length/character validation | Unit tests |
| Cached multilingual answers | Wrong-language stale answer | User trusts answer in wrong language | Include language in cache identity or verify language match before reuse | Server tests |
| Settings save | Invalid default breaks all users | Broken UI language on reload | Validate before save; fallback to English; expose recovery in System panel | Server and Playwright tests |
| Provider prompts | Leaking keys or local paths | Privacy risk | No secrets in prompt; provider metadata non-secret only | grep checks and config tests |

Auth mechanism:

- Current local web shell is a single-user local tool and binds to `127.0.0.1` by default.
- Protected VPS deployment must keep the existing external auth/protection layer. This PRD adds no new public unauthenticated mutation surface beyond the existing local web API.

### 7.3 Error Boundaries

| Component | Failure Mode | User Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| Browser language detection | Unsupported or invalid locale | UI falls back to English | User can choose language in System panel | dev `warn` once |
| Locale catalog | Missing key | English fallback text appears | Catalog key added in next patch | dev `warn` once per key |
| Backend language settings | Corrupt `settings.json` value | English fallback; System shows recoverable warning | Saving a valid setting overwrites bad value | `warn` with key name only |
| Ask/report language resolution | Provider cannot answer in target language | Localized error plus retry with English fallback option | User can retry or choose another language | `error` with model/provider, no prompt body |
| Review translation | Provider timeout/rate limit | Original review stays visible; retry button remains | Existing retry path and cache reuse | `warn/error` by provider status |
| Static module split | Browser cannot load locale file | English inline fallback and visible health warning | Reload after deploy fix | console + server static test failure |

## 8. UI/UX Architecture

### 8.1 Audience Map

| Audience | Description | Primary Goal | Entry Point |
| --- | --- | --- | --- |
| Any-language traveler/operator | Non-coder user evaluating places in the field | Read the app in their language and get actionable advice | `/`, `#scout`, `#shop`, `#ask` |
| Power user / owner | User configuring local product behavior | Set default language, report language, evidence mode | Settings/System panel |
| Future agent | CLI/API caller and maintainer | Use stable language fields without scraping UI text | CLI, `docs/API.md`, `docs/agent-cli.md` |

### 8.2 Audience-Page Matrix

| Page/View | Primary Audience | Secondary Audience | Audience's Job on This Page |
| --- | --- | --- | --- |
| Scout | Any-language traveler/operator | Future agent via job API | Create or refresh evidence in preferred language. |
| Shop | Any-language traveler/operator | Future agent | Deep-dive one known place with preferred report language. |
| Library | Any-language traveler/operator | Owner | Browse cached places with localized filters and stable original evidence. |
| Ask | Any-language traveler/operator | Future agent | Ask cached evidence and get answer in preferred language. |
| Dossier modal | Any-language traveler/operator | Owner | Read facts, report, reviews, translations, and source-language tags. |
| Settings/System | Owner | Future agent | Inspect and change language/provider/config state safely. |

### 8.3 Cross-Audience Interaction Map

- Owner saves default language -> any later local web session without browser override starts with that default -> immediate after next `/api/config` fetch -> visible in System panel.
- Traveler changes browser-only language -> only that browser changes -> immediate DOM update -> System panel shows source as localStorage/browser.
- Future agent calls CLI/API with explicit `report_lang` -> one request output changes -> no persistent setting mutation -> metadata records request language.

### 8.3.1 Reactive State Contract

| State Key | Owner | Subscribers | Update Mechanism | Example |
| --- | --- | --- | --- | --- |
| `language.ui` | web language state | All static/dynamic UI views | startup detection, localStorage save, System selector | User selects English -> nav, buttons, statuses, dates update. |
| `language.answer` | backend language owner + web state | Ask form, Ask history, answer renderer, CLI/API | `/api/config`, request metadata | Ask reuses English cache only for English target. |
| `language.report` | backend language owner + planner | Scout, Shop, reports, Library report metadata | job request metadata, report rows | Chinese user sees new reports in Chinese. |
| `language.translationTarget` | web state + backend validator | Review cards, language lens, translation endpoint | localStorage/settings + API target | User chooses Vietnamese target for visible reviews. |
| `language.evidenceMode` | backend config | report generation, Ask evidence formatting, System panel | `/api/config`, env/settings | `original` mode keeps quotes original. |
| `locale.messages` | static catalog | all web chrome | loaded at startup | Missing `fr` uses English chrome but keeps `fr` answer target. |

### 8.4 Page/View Inventory

| View | Type | Parent | Primary Audience | Purpose |
| --- | --- | --- | --- | --- |
| Language selector | inline section | Settings/System | Owner | Choose Auto, English, Chinese, or custom output target. |
| Translation target picker | inline control | Dossier review lens | Any-language user | Translate visible reviews to selected target. |
| Language/source badge | inline badge | Review cards, evidence cards | Any-language user | Separate original source language from display language. |
| Output language metadata | inline text/badge | Job timeline, report, Ask answer | Any-language user | Show what language generated content uses. |

### 8.5 Navigation Model

No new top-level tab is required.

```
Any tab --[System/Settings panel visible in existing footer/status area]--> Language controls (inline)
Dossier --[change translation target]--> Review cards update translations in place
Ask --[explicit output language optional]--> Answer card with same view
Scout/Shop --[resolved report language]--> Existing job timeline and dossier/report flow
```

### 8.5.1 View-to-Interface Dependency Map

| View | Interface/API It Reads | Fields Used | If Interface Changes -> Impact | Hardcoded? |
| --- | --- | --- | --- | --- |
| Startup/app shell | `GET /api/config` | `settings.default_answer_language`, new language fields | Wrong language on load | No after implementation |
| Settings/System | `GET /api/config`, `POST /api/settings/language` | language prefs, evidence mode, supported locales | User cannot inspect/save language | No after implementation |
| Ask | `POST /api/ask`, `GET /api/qa` | `answer`, `report_lang`, `cached`, `created_at`, evidence blocks | Wrong-language cache or display | No after implementation |
| Scout/Shop timeline | `/api/jobs/{id}`, job events | request `report_lang`, event messages | Timeline stage labels or result language mismatches | No after implementation |
| Dossier reviews | `GET /api/places/{id}`, `POST /api/reviews/translate` | reviews, source lang, target lang, translation text | Original/translation confusion | No after implementation |
| Library cards | `GET /api/places` | report language metadata, dates, counts | Stale or mixed labels | No after implementation |

### 8.8 View States

| View | State | Trigger | Display |
| --- | --- | --- | --- |
| App shell | first-use | No localStorage and no backend default | Uses browser language if possible; System shows Auto. |
| App shell | unsupported locale | Browser language has no UI catalog | English UI, output target keeps browser tag if valid. |
| System language controls | loading | `/api/config` pending | Existing compact status text with localized loading label. |
| System language controls | error | config fetch/save fails | Localized recovery message; browser-only preference remains usable. |
| Review translation | loading | batch translation active | Existing per-card/batch busy state localized. |
| Review translation | error | provider/validation failure | Original review visible; localized retry button. |
| Ask answer | cached | cache hit same scope and same output language | Localized cached banner showing language and freshness. |
| Ask answer | mismatch | cached question exists in another language | Localized "re-answer in current language" path, not silent reuse. |

### 8.9 Interaction Patterns

| Element | Click/Tap | Hover | Keyboard | Notes |
| --- | --- | --- | --- | --- |
| Language selector | Opens native select/menu | Browser default | Tab, arrows, Enter | Keep compact in System panel. |
| Custom target tag input | Saves on explicit action | Focus ring | Tab, Enter to save | Validate before save; never save invalid tag. |
| Translation target picker | Updates target and invalidates in-flight batch token | Existing hover | Tab, arrows | Preserve current stale-response guard. |
| Language/source badge | Non-interactive | Optional title | Screen-reader label | Must not imply country. |

### 8.11 Component Composition and Reuse Map

| Component / Helper | Used In | Inherits From | Props/Config It Accepts | If Changed -> Views Affected |
| --- | --- | --- | --- | --- |
| `t(key, params)` | all web views | static locale catalog | active locale, key, params | Entire web shell; run full Playwright. |
| `relTime(value)` | Library, Dossier, Ask, Scout history, timeline | native `Intl.RelativeTimeFormat` | active locale | All dated UI; run static + Playwright date assertions. |
| `languagePreference` resolver | Startup, System, Ask, jobs, translation | localStorage + `/api/config` | browser languages, settings, request hints | All language defaults; run server and UI language suite. |
| `renderReviewCard` | Dossier reviews, translation batch | review data, source lang, target lang | Dossier and review translation tests. |
| `renderSystemPanel` | Settings/System | config + health payload | System panel and provider visibility tests. |

### 8.12 Setup and First-Run Experience

No blocking setup wizard is required. Language adaptation must work zero-config:

1. First load reads browser language.
2. App fetches `/api/config`.
3. If saved app default exists, it applies unless browser-local override exists.
4. User can change language from System panel later.

### 8.13 Frontend Settings and Admin Configuration UI

| Config Item | Tier | Who Can Change | Where in UI | Requires Restart? |
| --- | --- | --- | --- | --- |
| `ui_language` | user/browser | local browser user | System -> Language | No |
| `default_answer_language` | app setting | owner | System -> Language | No |
| `default_report_language` | app setting | owner | System -> Language | No |
| `translation_target` | user/browser + app default | local browser user / owner | Dossier reviews + System | No |
| `evidence_language` | env/app setting | owner | System readout, future selector | No if saved in settings, env fallback on restart |
| `supported_ui_locales` | code/static | developer | read-only System info | Static deploy |

## 9. Design System

### 9.1 Visual Philosophy

Keep the existing quiet operational product feel. Language controls should feel like part of the System surface, not a marketing preference center. The UI should make language state visible only where it helps trust: System status, report/Ask metadata, review source badges, and translation controls.

### 9.2 Color Palette

Do not introduce a new palette. Use existing CSS tokens. New language/source badges should reuse existing badge surfaces:

| Token | Usage |
| --- | --- |
| `var(--paper)` | System panel and selector backgrounds |
| `var(--line)` | subtle borders for selectors/badges |
| `var(--muted)` | secondary language metadata |
| `var(--accent)` | active selected language or save action |
| `var(--danger)` / existing risk tokens | validation errors only |

### 9.3 Typography and Copy

- Use the existing type scale.
- Avoid bilingual strings as the default UI pattern after localization. A selected English UI should not show every label as Chinese plus English.
- Keep product vocabulary stable: Scout creates/refreshes evidence, Ask queries cached evidence, Dossier shows one place, Library browses cache.
- Machine keys stay English even when human copy localizes.

### 9.4 Spacing and Layout

- Language controls must fit inside existing System panel density.
- Minimum interactive target remains 40px where space allows.
- Long language names must wrap or truncate gracefully inside controls without shifting the whole page.
- No nested cards inside cards.

### 9.5 Component Specifications

| Component | Spec |
| --- | --- |
| Language selector | Native select or segmented compact control; 8px or less radius; clear focus ring; labels localized. |
| Source-language badge | Small inline badge, same visual family as current cache/risk badges; text like `Original: Korean`. |
| Output-language metadata | Muted inline line near report/answer metadata, not a dominant banner. |
| Translation target custom input | Appears only when user chooses custom; validates on save; shows localized inline error. |

### 9.6 Motion and Animation

Use existing motion only. Language switches should update instantly without page reload. Do not animate all text changes; that makes language switching feel unstable.

### 9.8 Accessibility and Localization

- Screen-reader labels must localize for selectors and icon-only actions.
- `html[lang]` must match active UI language.
- Directionality is out of first-pass scope except `dir="auto"` for content blocks. Future RTL support must get its own PRD before claiming full Arabic/Hebrew UI quality.
- Test 35% expanded Latin text, CJK text, and long language names.

## 10. Responsiveness and Adaptive Layout

Breakpoints to verify:

| Breakpoint | Required Proof |
| --- | --- |
| 375px | No horizontal scroll, language selectors usable, Ask/Dossier text not clipped. |
| 390px | Existing mobile smoke still passes. |
| 768px | System panel language controls do not crowd provider status. |
| 1024px | Dossier/report metadata remains readable. |
| 1440px | Long localized labels do not create awkward sparse layout. |

Light/dark mode must be checked for language badges, validation messages, and System controls.

## 11. Health, Monitoring, and Logging

### 11.1 Log System

| Event | Level | Component | Example Message |
| --- | --- | --- | --- |
| `language.preference_resolved` | debug | web/server | `source=browser ui=en answer=en report=en` |
| `language.preference_saved` | info | server | `saved default_report_language=fr` |
| `language.invalid_tag` | warn | server | `invalid target_lang rejected` |
| `language.locale_missing_key` | warn | web dev console | `missing locale key ask.cached_banner for vi` |
| `translation.generated` | info | pipeline | `review_id=... target=fr provider=VectorEngine cached=false` |
| `translation.failed` | warn/error | pipeline | `review_id=... target=fr transient=true` |

Logs must not include prompts, full review text, keys, local paths, or private deploy URLs.

### 11.2 Health Checks

| Check | Frequency | What it verifies | Alert on Failure |
| --- | --- | --- | --- |
| `GET /api/health` | cheap, on demand | DB open, static files present, config readable, language defaults valid | Local readiness degraded |
| `placeintel doctor --json` | cheap, on demand | same plus non-secret provider labels | CLI readiness degraded |
| Deep diagnostics | explicit only | optional live translation/reason model availability | Provider degraded, not app-dead |

### 11.3 Remote Linkage Verification

No new external service is introduced. Translation continues through the existing provider routing. Deep diagnostics may add one explicit translation micro-ping later, but cheap health must stay local and cost-free.

## 12. Analytics and Tracking

No product telemetry is added. Local structured events may be logged for debugging only. If future analytics are added, they must be disableable and must not store review text, questions, precise user locations, or private place targets.

## 13. Implementation Principles

### 13.1 Existing-Project-First

Read `AGENTS.md`, `VAULT.md`, this PRD, existing production PRDs, and the current web line budget before editing. Match FastAPI + SQLite + no-build SPA patterns unless this PRD explicitly says to update the constitution first.

### 13.2 Contract-First Language Work

Define the language preference contract before changing UI copy. Backend, CLI, API docs, and web must consume the same semantics. Do not create separate meanings for `language`, `locale`, `report_lang`, `target_lang`, and `source_lang`.

### 13.3 No Hardcoded User-Facing Dynamic Values

UI chrome should come from the locale catalog. Dynamic values should come from state/API. Scraped content and report bodies remain content and must be safely escaped/rendered.

### 13.4 Git Discipline

Implementation should land in milestones:

1. Contract/tests.
2. Backend/API/CLI language resolution.
3. Web locale catalog and System controls.
4. Review translation and evidence language expansion.
5. Full visual/runtime verification and release docs.

Each milestone gets its own commit and PRD status update.

### 13.5 Configuration Registry

| Config Key | Default | Type | Tier | UI Location | Description |
| --- | --- | --- | --- | --- | --- |
| `PLACEINTEL_DEFAULT_LANGUAGE` | `auto` | string | env/app | System -> Language | Optional app-wide default when browser setting absent. |
| `default_answer_language` | `auto` | string | app/user | System -> Language | Default Ask output target. |
| `default_report_language` | `auto` | string | app/user | System -> Language | Default Scout/Shop/report output target. |
| `translation_target` | active output language | string | user | Dossier reviews + System | Review display translation target. |
| `PLACEINTEL_EVIDENCE_LANG` | existing config | enum | env/app | System readout | `report` translates quotes into output language; `original` keeps originals. |
| `supported_ui_locales` | `["en","zh"]` | array | code/static | read-only | Locale packs bundled in the app. |

### 13.6 State Invalidation

| Data Type | Update Source | Invalidation Method | Max Staleness |
| --- | --- | --- | --- |
| Local UI language | Browser selector | immediate DOM rerender | 0s |
| App default language | System save API | re-fetch `/api/config` after save | 0s |
| Ask language | Ask request metadata | answer render from response | 0s |
| Report language | job request/report row | report render from response | job completion |
| Translation target | review selector | cancel stale batch token and rerender visible reviews | 0s |

### 13.7 Documentation Discipline

Implementation must update:

- This PRD status and checked acceptance criteria.
- `docs/API.md` for `/api/config`, `/api/settings/language`, `/api/ask`, `/api/reviews/translate`, and report fields.
- `docs/agent-cli.md` for language flags/fields.
- `AGENTS.md` if the no-build static architecture changes from exactly three files.
- `progress.md`, `task_plan.md`, and `CHANGELOG.md` when runtime behavior ships.

## 14. Technical Considerations

- The strongest first move is a `placeintel/language.py` module with pure tests. Keep it provider-free and cheap.
- Browser-supported UI locale and AI output language are not the same. A user can run English UI and ask for Vietnamese reports.
- API/CLI machine fields must stay stable English identifiers even when human output localizes.
- If UI locale packs move into new static files, the server static route must serve them with the same no-store behavior as `app.js`.
- Static tests should allow localized strings in the locale catalog but fail on new scattered copy in render functions.
- Prompt wording should say "target language tag" and "answer in the user's selected language" rather than assuming English language names are always available.

## 15. Success Metrics

- SM-001: English browser first load shows English UI chrome, English relative times, and `html lang="en"`.
- SM-002: Chinese browser or user setting shows Chinese UI chrome and `html lang="zh"`.
- SM-003: Vietnamese or French browser without a bundled UI catalog shows English UI chrome but uses the chosen target tag for Ask/report when selected.
- SM-004: Ask cache does not return a Chinese answer for an English request or vice versa unless explicitly requested and tagged.
- SM-005: Review translation accepts at least `vi`, `fr`, and `es` in tests, while preserving original text.
- SM-006: Full web line-budget/static contract and Playwright suite pass.

## 16. Open Questions

None blocking. The assumptions in Section 0 are the default build plan. The user can still override them before implementation, especially the default fallback language and whether to approve a no-build locale-file split.

## 17. Deployment and Configuration

### 17.0 Deployment Profile Decision

Deployment Profile: hybrid.

The app is local-first but has a protected VPS/systemd lane. Language adaptation must work in local dev and protected deployment without hardcoded localhost-only assumptions beyond existing local binding defaults.

### 17.1 Environment Matrix

| Environment | Purpose | URL/Host | Who Uses It | Data Source | Secrets Source |
| --- | --- | --- | --- | --- | --- |
| local | development and daily use | `127.0.0.1:9618` | owner/agents | local SQLite + settings | existing local env/skill configs |
| protected VPS | private remote access | private protected host | owner | deployed SQLite/data dir | server env/secrets |
| CI/local tests | regression gates | ephemeral | agents | fixtures/temp DB | no live secrets |

### 17.2 Local Setup

No new setup command is required. Existing local setup remains:

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npx playwright test tests/ui-audit.spec.js`
- `.venv/bin/placeintel doctor --json`
- `.venv/bin/placeintel deploy-smoke --base-url http://127.0.0.1:9618 --format json`

### 17.3 Secrets Management

No new secrets. Continue to resolve provider credentials through existing `config.py` logic. Language preferences are non-secret settings and may be stored in `settings.json`, SQLite, and localStorage.

### 17.4 Post-Deploy Verification

After implementation deploy/restart, run:

| Check | Method | Expected Result | Action on Failure |
| --- | --- | --- | --- |
| Cheap health | `placeintel deploy-smoke` against loopback/protected URL | health ok and version current | rollback or restart from active checkout |
| English UI | Playwright with `navigator.languages=["en-US"]` | English UI, no console errors | fix locale/state |
| Chinese UI | Playwright with `navigator.languages=["zh-CN"]` | Chinese UI, no console errors | fix locale/state |
| Fallback UI | Playwright with `navigator.languages=["fr-FR"]` and no `fr` catalog | English UI fallback, output target `fr` available | fix fallback |
| Ask language | API/CLI fixture | answer language metadata matches request | fix cache/resolution |
| Translation | API fixture target `vi` or `fr` | original text preserved, translated display cached | fix validation/prompt/cache |

## 18. Revision History

| Date | Version | Changes | Completed By |
| --- | --- | --- | --- |
| 2026-06-15 | v0.1 | Drafted PRD for language adaptation across web UI, API, CLI, Ask, reports, review translation, and settings. | Codex |
