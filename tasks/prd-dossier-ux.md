# PRD — Dossier UX: photo-opens-dossier, inline report generation, sharp photos

**Status:** ✅ Complete — all 5 US implemented, browser-verified, adversarial audit passed (1 LOW fixed, 4 refuted). Released as v0.4.48.
**Owner:** autonomous build (place-intel)
**Created:** 2026-06-19
**Scope class:** UI modification (no-build vanilla-JS SPA + FastAPI). No backend contract change.
**Version target:** v0.4.48

---

## S1. Introduction / Problem

Three real-user complaints on the place-intel web UI (127.0.0.1:9618):

1. **Clicking a card photo pops the image lightbox** when the user expected it to *open the shop dossier* (打开档案). The photo is the most prominent click target on a library/compare card, yet it routes to a single-image viewer instead of the place's full record.
2. **"Generate report" jumps outside the card.** `generateReportFromDetail` closes the dossier, switches to the Shop tab, and runs the job there — the user loses their place and can't watch progress in context.
3. **Photos look blurry.** Card thumbnails and the lightbox display Google `googleusercontent` images at their small thumbnail size token (e.g. `=w400`, `=w529-h298-k-no`), upscaled on retina displays and when zoomed.

## S2. Goals

| Goal | Measure (before → after) |
|---|---|
| Card/compare photo opens the dossier | click card photo → lightbox **(before)** → dossier overlay **(after)** |
| Report generates in place with live progress | dossier closes + tab switch **(before)** → dossier stays open, live timeline streams inline, report renders in place on completion **(after)** |
| Photos are sharp | card `<img>` `=w400`-class src **(before)** → `=w800` request **(after)**; lightbox `=w1600` |
| No regressions | 94 Python tests stay green; web line budgets respected (app.js ≤780, others <800) |

## S3. User Stories

- **US-001** — As a user browsing the Library, when I click a shop's photo on its card, the **shop dossier opens** (same as 打开档案), not an image viewer.
- **US-002** — As a user comparing shops, clicking a compare-card photo also opens that shop's dossier.
- **US-003** — As a user viewing a dossier with no report yet, when I click **生成报告 / Generate report**, the report **generates inline inside the dossier** with a **live progress timeline**, without closing the dossier or switching tabs. On completion the dossier refreshes in place to show the new report.
- **US-004** — As a user, the dossier's gallery strip photos still open the zoomable lightbox (gallery viewing is preserved).
- **US-005** — As a user, card photos and the lightbox image render **sharply** on retina and when zoomed.

## S4. Functional Requirements

- **FR-1 ✅**: `photoSourcesHtml(photos, variant, placeId)` — for `variant` ∈ {`card`,`compare`} **and** a non-empty `placeId`, render the photo button with `data-open-place="<placeId>"` (no `data-photo-url`) and `aria-label` "打开档案 / Open dossier". The existing global click delegation (`[data-open-place]` → `openDetail`) then opens the dossier.
- **FR-2 ✅**: For `variant === 'strip'` (the in-dossier gallery), keep the lightbox trigger (`data-photo-url`/`data-photo-src`/`data-photo-caption`) unchanged.
- **FR-3 ✅**: Card/compare `<img src>` is requested at a higher resolution via `hiRes(src, 800)`; the lightbox display image and its preloads via `hiRes(url, 1600)`. The lightbox **source link** (`<a href>` and visible URL) keeps the original, unmodified URL (honest provenance).
- **FR-4 ✅**: `hiRes(url, w)` rewrites the size token of `googleusercontent.com` / `ggpht.com` / `gstatic.com` URLs (`=…` suffix → `=w<w>`, or appends `=w<w>` when absent). Non-Google or non-http URLs pass through unchanged. Self-contained (no dependency on app.js load order).
- **FR-5 ✅**: `generateReportInline(btn)` runs the `/api/shop` pipeline (same body as the removed `generateReportFromDetail`), streams events into a `.timeline` rendered inside the dossier's report slot (`[data-report-slot]`), with EventSource + polling fallback (mirrors `streamJob`/`pollJob`). On success it refreshes the dossier via `openDetail(placeId)` and reloads the library in the background.
- **FR-6 ✅**: Closing the dossier mid-generation tears down the inline EventSource/timer (`state.dossierJob`) in `closeDetail`; the server job is left to finish (its report appears on next library/dossier load). No DOM writes occur after close (an `alive()` guard checks overlay visibility + current place).
- **FR-7 ✅**: New logic lives in `web/dossier.js` (loaded before app.js) because app.js is at its 780-line hard budget. `generateReportFromDetail` is removed; the `[data-generate-report]` handler calls `generateReportInline`.

## S5. Non-Goals

- No backend/API change. `photos.py` URL passthrough and all API contracts are untouched (the photo-size tests in `test_photos_contract.py` keep their exact-URL assertions).
- The dossier gallery strip and the lightbox zoom/keyboard/focus-trap behavior are unchanged except for the higher-res displayed image.
- No change to scout/shop tab job runners.

## S6. Stack & constants

- Vanilla JS (no build), FastAPI static mount serves `web/` → new `web/dossier.js` at `/static/dossier.js`. `__PLACEINTEL_VERSION__` cache-bust applied to the script tag in `index.html`.
- Constants (with rationale): card image **800w** (retina-sharp at ~340px CSS card, DPR≤2); lightbox **1600w** (sharp full-screen + up to 3× zoom without re-upscaling); `DOSSIER_POLL_MS=2000`, `DOSSIER_MAX_FAILS=5` (parity with `POLL_MS`/`MAX_POLL_FAILS`).

## S7. Safety / Zero-Regression Contract

| Must keep working | How verified |
|---|---|
| Dossier strip photos open the lightbox | contract test (`data-photo-url` present) + browser |
| Lightbox zoom / keyboard / focus-trap / source link | browser E2E |
| Scout/Shop tab jobs (EventSource pause/resume) | static contract tests unchanged + browser |
| Web line budgets (app.js ≤780, all <800) | `test_no_build_web_files_stay_under_project_budget` (now also covers `dossier.js`) |
| 94 Python tests | full `unittest` run |

**Error boundaries:** inline generation surfaces submit/poll/interrupt/error states inline via `errorHtml`; EventSource failure falls back to polling; poll failure after 5 tries shows a recoverable message.

## S8.3 Interaction deltas

- Card/compare photo: `cursor: zoom-in` → `cursor: pointer` (`.opens-dossier`), since it now navigates rather than zooms.
- Dossier no-report state wrapped in `<div data-report-slot>`; replaced in place by the live timeline during generation.

## S9.5 Vocabulary

- Photo control aria-label: 打开档案 / Open dossier.
- Inline progress header: 正在生成报告 · 实时进度 / Generating report · live progress.
- Waiting state: 已提交，等待后端… / Submitted, waiting for backend…

## E / Observability

Reuses existing `renderEvent` timeline (stage labels, retry/cache tones) and job event stream; no new telemetry surface.

## F. Principles

Existing-project-first (reuse `renderEvent`, `errorHtml`, `apiPost`, `openDetail`, `.timeline` CSS); agentic-first; GitNexus impact run before edits (photoSourcesHtml CRITICAL → backward-compatible defaulted param; verified all 3 call sites).

## Acceptance Checklist

- [x] US-001 card photo opens dossier (Library) — browser: `dossierOpen:true, lightboxOpen:false`
- [x] US-002 compare-card photo opens dossier — `compareCardHtml` passes `p.place_id`; same `opens-dossier` path as US-001
- [x] US-003 inline report generation with live progress, dossier stays open, refreshes on completion — browser: `tabSwitched:false, earlyTimeline:true, finalDossierOpen:true, reportShown:true`
- [x] US-004 dossier strip photos still open lightbox — browser: strip `data-photo-url` present, lightbox opens
- [x] US-005 sharp card + lightbox images — card `=w800`, lightbox `=w1600`, source link raw
- [x] 94 Python tests green; app.js =775 (≤780), all web files <800 (dossier.js added to budget test)
- [x] Browser E2E verified at 127.0.0.1:9618 — console clean (0 errors/warnings)
- [x] Lighthouse a11y stays 100 (navigation audit: Accessibility 100, Best Practices 100, SEO 100)

## Revision History

| Date | Version | Change | By |
|---|---|---|---|
| 2026-06-19 | 0.1 | Initial PRD | autonomous build |
| 2026-06-19 | 1.0 | All 5 US built + browser-verified; 10-agent adversarial audit (1 LOW confirmed → fixed: removed duplicate `aria-live` from inline timeline `<ol>`, restoring single-live-region parity; + defensive `clearTimeout` in `stop()`; 4 findings refuted). Released v0.4.48. | autonomous build |
