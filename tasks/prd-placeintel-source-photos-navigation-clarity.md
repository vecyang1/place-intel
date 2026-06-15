# PRD: placeintel Source Photos and Navigation Clarity

Status: ✅ Complete
Last Updated: 2026-06-15
Deployment Profile: hybrid
Deploy Targets: local FastAPI web app on `127.0.0.1:9618`, protected VPS/systemd lane when deployed
Parent PRD: `tasks/prd-placeintel-world-class-ui-ux.md`
Mode: Built and verified in `v0.4.35`.

## Research and Context Snapshot

Existing project facts:

- Stack is Python/FastAPI + SQLite + a 3-file no-build web shell: `web/index.html`, `web/app.css`, `web/app.js`.
- Current line counts are tight: `web/index.html` 214, `web/app.css` 799, `web/app.js` 775. Any implementation must compact first or perform an approved no-build module split.
- Reviews already support source image URLs: `reviews.images_json` exists in SQLite, `cache.Review.images` exists, `reviews.py` stores `user_images` from scraper-pro and `images` from SerpAPI.
- `reviews.py` sets `download_images: False` for scraper-pro, which is the right default for disk safety.
- Current `/api/places/{place_id}` omits review image fields, so the web UI cannot show them yet.
- Current tabs are accessible and hash-backed (`#scout/#shop/#library/#ask`), but the visible nav uses variable-width flex tabs, which makes the Chinese/English labels and underline feel misaligned in the provided screenshot.
- Current Ask already has exact-scope QA caching and history. The product clarity issue is vocabulary: users do not immediately know that Scout creates/fetches evidence while Ask only queries existing cached evidence.

External docs checked:

- Google Place Photos (New): photos require a photo resource name from Place Details/Nearby/Text Search, an API key, and max width or height; the media endpoint returns a short-lived `photoUri` and requires attribution when provided.
- SerpAPI Google Maps and Reviews APIs: current endpoints expose Google Maps place/review data and cache behavior, and the project already uses these as fallback sources.

Clarification Gate decisions made from the user's prompt:

| Question | Default Decision |
| --- | --- |
| Store images locally or use web URLs? | URL-first. Store source URL metadata only; do not download binary photos by default. |
| Use official Google Places Photos now? | No by default. Leave as optional future source because it may require Places billing/API enablement and photo URI refresh handling. |
| Where should photos appear first? | Dossier first, then Library/Compare small thumbnails. Scout results may show only one thumbnail when already cached. |
| What should Ask mean? | "Ask cached evidence." It must not imply a new Google Maps search. |
| What should Scout mean? | "Scout new places / refresh evidence." It may search Maps, filter, scrape reviews, embed, and generate reports. |

## 1. Overview

This feature makes placeintel more visually grounded and less mode-confusing. Users should be able to see what a place actually looks like from Google Maps/review source material before deciding whether to open a dossier, compare shops, or walk in. The implementation must stay lightweight: source URLs and metadata, bounded thumbnails, lazy loading, no local photo downloads by default.

The same pass fixes two UX clarity issues visible in the screenshots:

- Top navigation looks uneven because tab widths are content-driven.
- "提问 Ask" is unclear beside "侦察 Scout"; the UI needs to explain that Ask queries cached evidence while Scout creates or refreshes evidence.

## 2. Goals

- G1: Show source photos for cached places without increasing local disk usage beyond small URL metadata.
- G2: Make every photo visibly source-grounded with a fallback link to Google Maps or the source review.
- G3: Keep the web shell lightweight and under project line-budget rules.
- G4: Make top tabs visually aligned on desktop and mobile while preserving keyboard roving and hash deep links.
- G5: Make Scout vs Ask understandable within 2 seconds on the first screen.
- G6: Preserve existing Ask exact-scope caching, Scout/Shop job behavior, dossier focus trap, raw review originality, and XSS safety.

### Performance Impact Summary

| Metric | Before | Target After | Constraint |
| --- | --- | --- | --- |
| Local photo binaries | 0 bytes | 0 bytes by default | No default binary download/cache. |
| Stored photo metadata | none in API, existing DB URLs hidden | max 6 place photos + max 12 review image references per dossier payload | Text URL metadata only. |
| First Library payload | no photo fields | at most 1 thumbnail URL per place | Keep list fast; detail endpoint carries more. |
| Dossier image rendering | none | lazy-loaded, fixed aspect-ratio strip | Broken images collapse to placeholder, not layout shift. |
| Web file size | CSS 799 / JS 775 lines | implementation must keep files under test budgets | Prefer compaction before adding UI. |

## 3. User Stories

### US-001: Source Photo Data Contract

As a user, I want place photos to come from Google Maps/review source material so that I can recognize the real storefront, trail, cafe, or service before deciding.

Acceptance Criteria:

- [x] `/api/places` returns at most one lightweight `thumbnail` object per cached place when a source photo URL is available.
- [x] `/api/places/{place_id}` returns a bounded `photos[]` array with source URL metadata and no binary image data.
- [x] Review image URLs from existing `reviews.images_json` are exposed only through a safe backend resolver; frontend does not parse raw JSON columns.
- [x] The source contract includes `url`, `source`, `kind`, optional `review_id`, optional `author`, optional `rating`, optional `date`, and optional `attribution`.
- [x] No photo files are downloaded or written to `data/` during the default path.
- [x] `docs/API.md` documents the new fields and their no-binary guarantee.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

### US-002: Photo Strip in Dossier, Library, and Compare

As a user browsing cached places, I want small source thumbnails in the right places so that the UI feels grounded without becoming heavy or distracting.

Acceptance Criteria:

- [x] Dossier header shows a horizontal source-photo strip above or directly below the decision brief when `photos[]` exists.
- [x] Library cards show one thumbnail only when a lightweight `thumbnail` exists; cards without photos keep their current readable layout.
- [x] Compare cards show the same one thumbnail only if it does not push key facts below the fold on mobile.
- [x] Every image uses a stable 4:3 or 1:1 aspect-ratio box, `object-fit: cover`, `loading="lazy"`, and a broken-image fallback.
- [x] Clicking a photo opens the source URL or Google Maps place URL in a new tab with `rel="noopener noreferrer"`.
- [x] The UI labels the media as "source photo" or "review photo" and never presents it as an AI-generated image.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

### US-003: Aligned Accessible Top Tabs

As a user, I want the Scout/Shop/Library/Ask tabs to look intentionally aligned so that navigation feels stable and professional.

Acceptance Criteria:

- [x] Top tabs use equal or measured tracks at desktop widths so labels and active underline align visually.
- [x] On narrow mobile widths, tabs remain horizontally scroll-safe or compact to a stable 4-column layout without clipped labels.
- [x] Existing IDs, roles, `aria-selected`, roving `tabindex`, Arrow/Home/End keyboard behavior, and `#scout/#shop/#library/#ask` hash contract remain intact.
- [x] Active underline width is consistent and centered within each tab track.
- [x] Playwright proves tab navigation by click, keyboard, and direct hash load.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

### US-004: Clear Scout vs Ask Vocabulary

As a non-coder user, I want to know whether I am searching Google Maps or asking cached evidence so that I do not accidentally expect Ask to discover new places.

Acceptance Criteria:

- [x] Scout is labeled/copy-described as the path that searches/refreshes Google Maps evidence: "侦察新店 Scout" or equivalent.
- [x] Ask is labeled/copy-described as the path that queries existing cache: "问缓存 Ask" or equivalent.
- [x] The Command Center chips each have a short visible helper line or compact sublabel; do not rely only on hidden tooltip text.
- [x] Ask empty-cache state says to run Scout or Shop first, and does not imply it can search the web.
- [x] Scout mode reason says it may search Maps, filter candidates, scrape reviews, and generate reports.
- [x] Top-level Ask history keeps mixed display navigation while exact-scope cache safety remains unchanged.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

### US-005: Lightweight Implementation Guardrail

As the project owner, I want this UI feature to stay small so that placeintel remains maintainable and disk-light.

Acceptance Criteria:

- [x] Implementation begins by running `wc -l web/index.html web/app.css web/app.js` and recording counts in `progress.md`.
- [x] If `web/app.css` or `web/app.js` would exceed current tests, implementation first compacts duplicated CSS/JS or proposes a no-build module split PRD before adding features.
- [x] Default thumbnail cache size is `0 MB`; enabling a future cache requires an explicit setting and cap.
- [x] Backups do not include photo binaries or arbitrary image cache directories.
- [x] Existing `placeintel backup` allow-list remains unchanged unless a separate backup PRD approves photo-cache handling.
- [x] Typecheck/lint passes.
- [x] Visual verification via dev-browser or preview skill.

### US-006: Verification and Release Hygiene

As a future agent, I want exact tests and docs to prove this feature so that it does not become a pretty-but-fragile patch.

Acceptance Criteria:

- [x] Add Python tests for photo URL extraction, caps, and API payload shape.
- [x] Add static web tests for tab structure, copy vocabulary, lazy image attributes, and line budgets.
- [x] Add Playwright tests for desktop/mobile photo rendering, tab alignment, Ask empty-cache copy, and no console errors.
- [x] Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.
- [x] Run `npx playwright test tests/ui-audit.spec.js` against a fresh `placeintel-web` runtime.
- [x] Run `.venv/bin/placeintel doctor --json`, `.venv/bin/placeintel deploy-smoke --base-url http://127.0.0.1:9618 --format json`, `node --check web/app.js`, `git diff --check`, and the web line-budget test.
- [x] Update `docs/API.md`, `progress.md`, `CHANGELOG.md`, and this PRD as build status changes.

## 4. Functional Requirements

### 4.1 Photo Source Contract

- FR-001: Add one backend resolution owner for displayable photo metadata, for example `placeintel/photos.py::resolve_place_photos(conn, place_id, *, list_mode=False)`. Frontend code must consume resolved fields only.
- FR-002: The resolver must read from existing persisted sources first:
  1. `reviews.images_json` from scraper-pro `user_images` and SerpAPI review `images`.
  2. `places.raw_json` image/thumbnail-like fields if present from discovery providers.
  3. Optional future official Google Places Photo metadata only when explicitly configured.
- FR-003: The resolver must output `PhotoSource` dictionaries:

```json
{
  "url": "https://...",
  "thumb_url": "https://...",
  "source": "scraper-pro|serpapi|google-places",
  "kind": "place|review",
  "place_id": "place-id",
  "review_id": "review-id-or-null",
  "author": "review-author-or-null",
  "rating": 5,
  "date": "2026-06-01",
  "attribution": "required attribution if available"
}
```

- FR-004: The resolver must reject non-HTTP(S), `javascript:`, `data:`, empty, and malformed URLs.
- FR-005: The resolver must dedupe by normalized URL and preserve the earliest useful source metadata.
- FR-006: List payloads must expose at most one `thumbnail` per place; detail payloads must expose at most 6 place-level/display photos and at most 12 review-image sources total.
- FR-007: Photo payloads must not include raw provider JSON, keys, cookies, local paths, or temporary file paths.
- FR-008: If no usable photo exists, APIs return `thumbnail: null` and/or `photos: []`, not an error.
- FR-009: Official Google Place Photos support is optional and disabled by default. If added later, it must request bounded dimensions, store only resource names/temporary URI metadata, include required attribution, and avoid persisting short-lived `photoUri` as a durable source of truth.

### 4.2 UI Behavior

- FR-010: Dossier photos render in a compact strip with stable boxes before the long report body.
- FR-011: Library and Compare use one thumbnail maximum per card and must keep rating/name/facts visible without scrolling on common mobile widths.
- FR-012: Image elements must use `loading="lazy"`, `decoding="async"`, safe `alt`, and broken-image fallback behavior.
- FR-013: Photo UI must include a visible source label: "source photo", "review photo", or equivalent Chinese/English pair.
- FR-014: Photo click targets open source URLs in a new tab only; the app does not proxy or download images.
- FR-015: Users must always have a non-photo way to open the dossier and Google Maps link.

### 4.3 Navigation and Vocabulary

- FR-016: Keep exactly the existing tab IDs and hash routes: `tab-scout`, `tab-shop`, `tab-library`, `tab-ask`; `#scout`, `#shop`, `#library`, `#ask`.
- FR-017: Desktop nav should use four equal tracks within the current content width; mobile may keep equal 4-track layout if it passes 375px/390px no-overflow, otherwise use horizontal scroll with snap and stable underline.
- FR-018: Tab label copy must differentiate action types:
  - Scout = find/refresh evidence from Maps and reviews.
  - Shop = deep-dive one known place.
  - Library = browse cached places.
  - Ask = ask existing cached evidence.
- FR-019: The Command Center mode reason must be visible and update with mode selection.
- FR-020: Ask empty-cache and Ask placeholder copy must explain that Ask cannot discover new Google Maps places.

### 4.4 Data Resolution Ownership

| Data Type | Resolution Logic | Resolution Owner | Fallback Chain | Consumers Must NOT Re-resolve |
| --- | --- | --- | --- | --- |
| Place thumbnail | Choose first safe source image for list/card use | backend photo resolver | review image -> place raw thumbnail -> null | Library cards, Scout cached result cards, Compare cards |
| Dossier photos | Deduped bounded source image list | backend photo resolver | review images -> place raw images -> optional Google Places photo resource -> empty list | Dossier photo strip |
| Photo source URL | Validate and normalize display URL | backend photo resolver | safe URL -> reject | All web image components |

## 5. Non-Goals

- Do not download Google Maps or review images by default.
- Do not add a heavy image CDN, image proxy, thumbnail generator, or background image crawler.
- Do not enable official Google Places Photos by default.
- Do not use generated placeholder art as a substitute for source photos.
- Do not add a full map canvas in this feature.
- Do not change raw review text storage, review translation behavior, QA exact-scope cache rules, provider routing, or Scout relevance sorting.
- Do not weaken the no-build SPA constitution without a separate architecture decision.

## 6. Stack and Dependencies

### 6.1 Dependency Decision

No new dependency by default.

| Option | Use | Decision | Reason |
| --- | --- | --- | --- |
| Existing scraper-pro `user_images` URL data | Review-source photos | Chosen | Already captured without downloading; matches disk-light requirement. |
| Existing SerpAPI review `images` URL data | Fallback review photos | Chosen | Already mapped in `_serp_images`; no new package. |
| Existing `places.raw_json` | Provider thumbnails if present | Chosen | Raw payload is already stored for evidence preservation. |
| Official Google Place Photos (New) | Optional future source | Deferred | Requires photo resource names, API key/billing, attribution handling, and short-lived URI refresh. |
| Local image proxy/cache | Thumbnail performance | Rejected for default | Adds disk/bandwidth and backup complexity. |
| React/Vite/Tailwind/gallery lib | UI rendering | Rejected | Violates current no-build shell and line budget. |

### 6.2 Constants and Thresholds

| Constant | Value | Rationale |
| --- | --- | --- |
| `PHOTO_LIST_LIMIT` | 1 per place | Keeps `/api/places` payload small and Library cards scannable. |
| `PHOTO_DETAIL_LIMIT` | 6 per place | Enough to recognize a place without making dossier a gallery. |
| `PHOTO_REVIEW_SCAN_LIMIT` | newest 120 reviews | Bounds SQL/API work while prioritizing recent visual evidence. |
| `PHOTO_REVIEW_IMAGE_LIMIT` | 12 URLs | Prevents a few photo-heavy reviews from bloating the dossier payload. |
| `PHOTO_CACHE_MB_DEFAULT` | 0 | No local image binaries by default. |
| `PHOTO_BOX_ASPECT` | 4:3 | Good for storefront/trail/cafe recognition and stable layout. |
| `PHOTO_LOAD_STRATEGY` | lazy + async decode | Avoids slowing first paint. |

### 6.3 Intermediate Data Strategy

| Artifact | Strategy | Rationale |
| --- | --- | --- |
| Source URL strings | Persist as JSON/text in existing DB columns | Already present; tiny footprint. |
| Resolved API photo payload | Compute on request | Avoids migrations unless implementation proves a cached resolver table is needed. |
| Image bytes | Browser cache only | No app disk growth. |
| Optional future thumb cache | Off by default; capped LRU under `data/photo-cache/` | Requires separate setting and backup decision before use. |

## 7. Safety and Security

### 7.1 Zero-Regression Contract

| Existing Feature | Files/Symbols Touched | Risk Level | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| Dossier open/render/focus trap | `web/app.js::renderDetail`, `openDetail` | HIGH by GitNexus | Playwright dossier tests: open, focus entry, Tab trap, Escape, return focus, report/reviews still visible | Yes |
| Ask from top tab and dossier | `web/app.js::runAsk`, `loadQaHistory`, `/api/ask`, `/api/qa` | HIGH by GitNexus | Ask evidence tests, exact-scope QA tests, Playwright Ask history/re-ask | Yes |
| Tab navigation and deep links | `web/app.js::switchTab`, `web/index.html` tabs | HIGH by GitNexus | Playwright click/keyboard/hash tests; static role/id tests | Yes |
| Place detail API | `placeintel/server.py::place_detail` | LOW by GitNexus | Server contract test for new `photos[]` while preserving existing fields | Yes |
| Review storage | `placeintel/cache.py::upsert_reviews`, `reviews.images_json` | LOW by GitNexus | Unit test proving image URLs persist and raw text unchanged | Yes |
| Web shell line budget | `web/index.html`, `web/app.css`, `web/app.js` | HIGH project risk | `tests/test_web_static_contract.py` and `wc -l` proof | Yes |

### 7.2 Security Hardening

| Attack Surface | Threat | Impact | Mitigation | Verification |
| --- | --- | --- | --- | --- |
| Photo URLs from scraped/provider data | XSS or unsafe protocols | Script execution or tracking | Backend rejects non-HTTP(S); frontend also uses `safeUrl`; all text goes through `esc()` | Unit + static tests |
| Image source metadata | Leaking provider raw JSON or keys | Privacy/security leak | API returns only normalized fields; never raw JSON | Server contract tests |
| `alt`, title, author, attribution text | HTML injection | XSS | Always escaped through `esc()` | Playwright XSS fixture |
| Official Places optional path | API key exposure | Key leak | Key used backend-only; never sent to web UI | API tests + grep |
| Broken/expired remote image | Broken layout | User confusion | Fixed placeholder and source link fallback | Playwright image-error test |

### 7.3 Error Boundaries

| Component | Failure Mode | User Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| Photo resolver | No valid URLs | UI shows no-photo placeholder or omits strip | User can still open Maps/dossier | debug count only |
| Remote image load | 403/404/expired | Broken image collapses to placeholder; facts remain visible | User can open Google Maps source link | browser console must stay clean |
| Optional Google Places photo lookup | quota/key/API error | Photos unavailable; Scout/Ask/Library still work | Disable optional source and rely on existing URLs | warn with provider label, no key |
| Line budget exceeded | CSS/JS cannot accept more code | Implementation stops before runtime edit | Compact or write module-split PRD | progress note |

## 8. UI/UX Architecture

### 8.1 Audience Map

| Audience | Description | Primary Goal | Entry Point |
| --- | --- | --- | --- |
| Field user | Non-coder deciding where to go now | Recognize and evaluate a place quickly | Scout, Library, Dossier |
| Repeat researcher | User revisiting cached places | Scan cache and compare without re-scraping | Library |
| Agent/operator | Future Codex/CLI user | Verify contracts and avoid regressions | PRD, API docs, tests |

### 8.2 Page/View Matrix

| View | Primary Audience | Job |
| --- | --- | --- |
| Scout | Field user | Search/refresh Google Maps and reviews evidence |
| Shop | Field user | Deep-dive one known place |
| Library | Repeat researcher | Browse cached places with grounded thumbnails |
| Dossier | Field user | Decide from facts, photos, reviews, report, and scoped Ask |
| Ask | Field user | Query existing cached evidence |
| Compare | Repeat researcher | Compare cached places without new generation |

### 8.3 Reactive State Contract

| State Key | Owner | Subscribers | Update Mechanism | Fallback |
| --- | --- | --- | --- | --- |
| `state.places[].thumbnail` | `/api/places` | Library, Compare | `loadLibrary()` refresh | no-photo layout |
| `detail.photos[]` | `/api/places/{place_id}` | Dossier | `openDetail()` fetch | omit photo strip |
| `state.tab` | `switchTab()` | nav + panels | hash replacement + ARIA update | `scout` |
| `state.searches` | `/api/searches` | Command Center, Ask recommendation, Library history | `loadScoutPast()` / `loadLibrary()` | Ask manual override still works |

### 8.4 Navigation Model

```text
Scout/Library card photo -> open source URL (new tab)
Scout/Library card body -> Dossier overlay
Dossier photo -> source URL or Maps URL (new tab)
Dossier -> Ask this shop -> scoped cached/RAG answer
Ask tab -> cached evidence answer only
Scout tab -> new/refresh evidence job
```

### 8.5 View-to-Interface Dependency Map

| View | Interface/API It Reads | Fields Used | If Interface Changes -> Impact | Hardcoded? |
| --- | --- | --- | --- | --- |
| Library | `GET /api/places` | place facts, counts, `thumbnail` | Cards lose visual grounding | No |
| Dossier | `GET /api/places/{place_id}` | place, reviews, report, `photos[]` | Photo strip/facts/reviews affected | No |
| Compare | `GET /api/places/{place_id}` | place, reviews, report, `photos[]` or thumbnail | Compare card image/facts affected | No |
| Ask | `POST /api/ask`, `GET /api/qa` | answer, evidence, cache scope | Must not use photo resolver | No |
| Tabs | static HTML + `switchTab()` | tab IDs/hash | Deep links/accessibility affected | No |

### 8.6 Component Reuse Map

| Component / Function | Used In | Props/Config | If Changed -> Views Affected |
| --- | --- | --- | --- |
| new `photoSourcesHtml()` or equivalent | Library, Dossier, Compare | `photos`, `variant=list|detail|compare` | all photo UI surfaces |
| `renderDetail()` | Dossier | detail payload | Dossier facts, Ask-this-shop, report, reviews, focus tests |
| `renderShopCard()` | Library | place card payload | Library cards and compare entry |
| `compareCardHtml()` | Compare | place + detail payload | Compare Board |
| `switchTab()` | top nav | tab name | all top-level tabs |
| `runAsk()` | Ask tab + dossier Ask | question, place scope | Ask answer, cache history |

### 8.7 View States

| View | State | Trigger | Display |
| --- | --- | --- | --- |
| Library | no photos | cached places lack thumbnails | existing cards, no broken gap |
| Library | photos available | `thumbnail` present | one bounded thumbnail above name or as side media |
| Dossier | photos available | `photos[]` present | source-photo strip before long report |
| Dossier | photo load error | image request fails | placeholder tile + Maps/source link |
| Ask | empty cache | no cached evidence | "先跑 Scout/Shop；Ask 只问缓存证据" |
| Tabs | active | click/key/hash | centered underline and stable tab width |

## 9. Design System

Use the existing paper/ink/red visual system. Do not introduce a new palette.

### 9.1 Visual Philosophy

Field notebook with source windows: photos should make the place recognizable, not become a glossy travel gallery. Facts and risk remain dominant.

### 9.2 Component Specifications

| Component | Spec |
| --- | --- |
| Source photo strip | Horizontal row, gap 8-10px, 4:3 tiles, max 6 items, no nested cards |
| Library thumbnail | One 4:3 or square thumbnail, fixed min-height, above or left of text depending viewport |
| Compare thumbnail | Optional 4:3 thumbnail only if key facts remain visible |
| Photo fallback | Same aspect box, subtle border, text "no source photo" |
| Tab track | Four equal tracks desktop; active underline centered and same width across tabs |
| Mode helper | One compact visible sentence under mode chips; no hover-only teaching |

### 9.3 Vocabulary

| Concept | Preferred Label | Avoid |
| --- | --- | --- |
| Scout | `侦察新店 Scout` / `找新证据 Scout` | vague `侦察` alone |
| Shop | `单店深挖 Shop` | generic `单店` alone when context is missing |
| Library | `资料库 Library` | unchanged |
| Ask | `问缓存 Ask` / `问已有证据 Ask` | `提问 Ask` alone |
| Photo | `source photo` / `review photo` | "AI image", "cover" unless source is explicit |

### 9.4 Motion

- Do not animate image layout reflow.
- Photo hover may use `150ms` border/opacity transition only.
- Tab active underline may use existing `var(--dur)` timing but must not shift layout.

## 10. Responsiveness

Breakpoints:

- 375px: no horizontal page overflow; photo strip scrolls horizontally within its own row if needed.
- 390px: tabs and Command Center copy fit without clipped labels.
- 768px: Library card thumbnail may sit left of text if it improves scan speed.
- 1024px+: four equal tab tracks and 2-column Library/Compare remain readable.
- 1440px+: keep current max content width; do not stretch thumbnails into a hero gallery.

## 11. Health, Monitoring, and Logging

| Event | Level | Component | Example Message |
| --- | --- | --- | --- |
| photo resolver drops unsafe URL | debug | photo resolver | `dropped unsafe photo url for place_id=...` |
| optional photo source fails | warn | photo resolver | `google places photo lookup failed: provider unavailable` |
| photo payload capped | debug | API | `photo sources capped at 6 for place_id=...` |
| web image fails | none/server | browser only | fallback should not create server noise |

Cheap health must stay cheap. Do not add photo provider pings to `GET /api/health`; optional deep diagnostics may include photo provider readiness later.

## 12. Analytics

Local-only counters may be added later, but are not required for v1:

- Dossier photo strip rendered count.
- Source photo click count.
- Ask empty-cache state shown count.

No external analytics.

## 13. Implementation Principles

- Existing-project-first: read `AGENTS.md`, this PRD, `tasks/prd-placeintel-world-class-ui-ux.md`, and current web line counts before editing.
- Contract-first: backend owns photo resolution; frontend renders resolved fields only.
- Disk-light by default: store URLs/metadata, never image bytes, unless a later explicit setting enables a capped cache.
- Escape everything: photo labels, authors, attributions, and review metadata are scraped input.
- Preserve Ask safety: exact-scope QA cache invalidation must not change.
- Preserve Scout behavior: live result ordering and AI fail-open filtering must not change.
- Preserve raw originals: photo UI must not mutate review text, translations, or source review rows.
- Verify visually on desktop and mobile after implementation.

## 14. Documentation

Update when built:

- `docs/API.md`: new `thumbnail` and `photos[]` response fields.
- `CHANGELOG.md`: add an unreleased entry when implementation starts; version only when shipped.
- `progress.md`: line-count baseline, tests run, visual proof.
- `AGENTS.md`: add a hard rule only if implementation introduces a durable photo-resolution invariant.
- `tasks/prd-placeintel-source-photos-navigation-clarity.md`: check off acceptance criteria as implemented.

## 15. Technical Considerations

- `web/app.css` has only one line of budget left. Implementation must compact CSS or approve a no-build module split first.
- `/api/places/{place_id}` currently selects review columns without `images_json`; implementation must add this intentionally and update tests.
- If `places.raw_json` contains source-specific thumbnail fields, keep provider parsing inside the backend resolver, not in callers.
- Some remote image URLs may be short-lived or hotlink-protected; photo display must be opportunistic, not a dependency for decision facts.
- Attributions are source-dependent. If attribution is available, display it; if not, show source type and review author/date where applicable.

## 16. Success Metrics

- A user can identify what a cached place looks like from the dossier without opening Google Maps first.
- Library cards remain scannable and do not become image-heavy.
- Ask vs Scout is clear from labels and helper copy before the user submits.
- No default local photo cache or binary files are created.
- Playwright mobile screenshot has no horizontal overflow and no broken nav alignment.
- Existing Ask, Scout, Shop, Library, Compare, dossier focus, and translation tests still pass.

## 17. Open Questions

| Question | Default | Who Can Override |
| --- | --- | --- |
| Should official Google Places Photos be enabled? | No; URL sources from existing scrape/fallback first | User, if they approve Places billing/API enablement |
| Should source photos be included in backups? | No; backups remain URL/database/report only | User, via separate backup PRD |
| Should Ask tab be renamed to `问缓存 Ask` exactly? | Yes unless visual test shows label too long | UX implementer may choose `问证据 Ask` if more compact |
| Should tabs become equal 4-column on all widths? | Try equal tracks first; fallback to scroll-snap if 375px fails | UX implementer after Playwright proof |

## 18. Deployment and Configuration

### 18.0 Deployment Profile

Hybrid. Local-first web app with protected deployment lane. The feature must work on loopback and protected VPS without hardcoded private hosts, deploy paths, or local filesystem exposure.

### 18.1 Environment Matrix

| Environment | Purpose | URL/Host | Data Source | Secrets Source |
| --- | --- | --- | --- | --- |
| local | development and owner use | `http://127.0.0.1:9618` | local SQLite under configured data dir | existing env/skill secret discovery |
| protected VPS | owner remote access | private authenticated domain or loopback tunnel | deployed SQLite/data dir | server env/GitHub Secrets |
| public repo | source distribution | GitHub | no runtime data | no secrets |

### 18.2 Binary Asset Strategy

| Asset Type | Local Dev | Production | Fallback Chain | Bandwidth/Disk Impact |
| --- | --- | --- | --- | --- |
| Review/source photo URL | stored as text metadata | stored as text metadata | URL -> placeholder -> Google Maps link | tiny DB text only |
| Browser-rendered remote image | browser cache | browser cache | remote image -> placeholder | no app disk; remote bandwidth |
| Optional future photoUri | backend-resolved, short-lived | backend-resolved, short-lived | photo resource -> temporary URI -> placeholder | no durable image bytes |
| Optional future thumb cache | disabled by default | disabled by default | capped LRU -> remote URL -> placeholder | requires separate setting |

### 18.3 Post-Deploy Verification

After implementation and restart:

1. Run `placeintel deploy-smoke --base-url http://127.0.0.1:9618 --format json`.
2. Open Library and one dossier in browser at 390px and desktop width.
3. Confirm photos load lazily or fall back cleanly.
4. Confirm no local image cache directory was created unless explicitly enabled.
5. Confirm `GET /api/health` remains cheap and does not call photo providers.

## Revision History

| Date | Version | Summary | Author |
| --- | --- | --- | --- |
| 2026-06-15 | v1.0 | Built URL-only source photos, aligned navigation tabs, Scout/Ask vocabulary, tests, docs, and visual proof. | Codex |
| 2026-06-15 | v0.1 | Draft PRD for source photos, tab alignment, and Scout/Ask clarity. | Codex |
