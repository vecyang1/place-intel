# Changelog — place-intel

## v0.4.48 — 2026-06-19 — dossier UX: photo opens the dossier, reports generate in place, sharper photos
Three real-user UX fixes on the web app, all front-end (no API/contract change). New module
`web/dossier.js` (loaded before `app.js`; keeps `app.js` under its 780-line budget).
- **Card photo → dossier.** Clicking a library/compare card's photo now opens the shop
  dossier (打开档案), not the image lightbox — the photo is the card's biggest target and
  belongs to the place, not a viewer. `photoSourcesHtml(photos, variant, placeId)` renders
  card/compare photos with `data-open-place` (+ `cursor: pointer`, aria "Open dossier")
  instead of `data-photo-url`. The dossier's own gallery strip still opens the zoomable
  lightbox — gallery viewing is unchanged.
- **Reports generate in place, with live progress.** "生成报告 / Generate report" no longer
  closes the dossier and jumps to the Shop tab. `generateReportInline` runs `/api/shop` and
  streams the live timeline into the dossier's report slot (EventSource + polling fallback,
  mirroring the tab job runners); on completion the dossier refreshes in place to show the
  new report. Closing the dossier mid-run tears the stream down cleanly (the server job
  finishes on its own and the library picks up the report).
- **Sharper photos.** Card and lightbox images were Google thumbnails (`=w400`-class tokens)
  upscaled on retina and zoom. `hiRes()` bumps the size token of `googleusercontent`/`ggpht`/
  `gstatic` URLs — cards request `=w800`, the lightbox `=w1600` — while the lightbox's
  "view original" link keeps the unmodified source URL. Non-Google/non-http URLs pass through.

## v0.4.47 — 2026-06-19 — batch /api/places photo thumbnails (N+1 → 2 queries)
The library list resolved a source-photo thumbnail per place — 1–2 indexed queries each,
~218 for a 109-place cache. Replaced with `photos.resolve_place_thumbnails`, a single
batched pass (one chunked review-image query + one raw-photo fallback query) that mirrors
the per-place resolver exactly. Measured **218 → 2 queries (109× fewer)** on the live
cache, **0 result mismatches** across all 109 places (+ a contract test). This was the
last residual N+1 from the v0.4.45 photo-feature merge — the twin of the activity-risk
batch already in the same loop.

## v0.4.46 — 2026-06-19 — photo-lightbox + language accessibility hardening
Adversarial audit of the just-merged photo + language feature code (0 security issues —
the scraped-photo URLs are correctly `safeUrl()` + `esc()` guarded). Fixed 6 a11y/UX
defects, all in the new feature surface:
- **Photo-lightbox focus trap** now includes the source-URL `<a>`, so Tab can't escape
  the modal onto background controls, and the "view original" link is keyboard /
  screen-reader reachable (was buttons-only).
- The lightbox opens focus on the always-enabled close button (was the nav button, which
  is disabled for single-photo galleries — leaving focus outside the just-opened modal).
- Opening the lightbox from a dossier now sets the dossier `inert`, so the layered second
  modal no longer leaves the first one exposed to the screen-reader virtual cursor.
- The "no source photo" empty/broken-image label is localized via a CSS variable (was
  hardcoded English and double-rendered over the localized empty label); the lightbox
  toolbar aria-labels and the language save-status now follow the UI language switch.
- **Contrast:** the active command-mode chip's help text was 3.89:1 — `opacity: 0.72`
  dragged `--on-accent` below AA on the coral chip; `opacity: 1` on the active state
  restores AA. Lighthouse accessibility back to 100.

## v0.4.45 — 2026-06-19 — merge: source photos + language switch ⊕ production hardening
Reconciles two lines that diverged at v0.4.34: the **source-photo galleries + lightbox**
and the **UI/answer/report language switch** (entries v0.4.35→v0.4.44 below) with a
**production-hardening line** that ran in parallel. Both are now in. The hardening is
folded in here (its parallel v0.4.35–v0.4.37 entries were collapsed into this merge to
avoid version collisions):
- **Security:** SerpAPI API key no longer leaks via `requests` exception text into job
  events / error fields (`config.redact_secrets`, applied at the SerpAPI raise sites and
  the job-error sink); `discover.py` now catches `RequestException` around `raise_for_status`.
- **Reliability:** `/api/jobs/{id}/events` is async + `is_disconnected()`-aware so abandoned
  streams don't pin threadpool threads; `/api/searches`, `/api/reports`, `/api/reports/{id}`
  and `pipeline.ask()` release their SQLite connection via `try/finally`; SQLite opens in
  **WAL** with a 15s busy-timeout (kills "database is locked" under concurrency).
- **Hidden-tab job streams:** Scout/Shop `EventSource` streams pause when their tab is
  hidden and re-attach on return; both `streamJob` and `resumeJobStream` honor the pause
  flag (a tab switch during the submit POST can neither leak a stream nor freeze the job),
  guarded by two regression tests.
- **Performance:** `/api/places` activity-risk is a single scoped scan over risk-eligible
  places (no per-row N+1).
- **Accessibility / UX (carried from the hardening line):** risk badges use a real
  `--danger` token; WCAG AA contrast on accent buttons (dark ink on coral in dark mode);
  the no-risk state gets a calm green `✓`; the dossier modal sets the background `inert`
  and exposes `aria-live` regions for job progress, library/history status, and answers;
  standalone tap targets meet the 24px minimum; mobile library filters pair into two columns;
  API request models enforce Pydantic `Field` bounds at the trust boundary.

## v0.4.44 — 2026-06-16 — report-aware scout history
- Past Scout rows now carry per-place `report_count` from `/api/searches`, so
  places that already have generated reports can be visually emphasized in the
  Scout history chips.
- Dossiers without a report now show an in-modal "Generate report" action that
  starts the existing single-shop job for that cached place instead of sending
  the user to retype it in Shop manually.
- Added backend and Playwright regressions for report-marked search history and
  no-report dossier report generation.

## v0.4.43 — 2026-06-16 — selected-language UI chrome
- Chinese UI mode now renders app chrome in Chinese only instead of paired
  Chinese/English glossary labels across tabs, Library filters, System,
  dossiers, Ask evidence, Compare, translations, and source-photo controls.
- English UI mode now keeps the same surfaces English-only, including dynamic
  empty states, history labels, language-lens filters, and cached-answer notes.
- Added Playwright regressions for both selected-language directions plus the
  System panel so future UI copy changes do not reintroduce mixed-language
  labels.

## v0.4.42 — 2026-06-15 — eager photo gallery preload
- Source-photo lightboxes now preload the rest of the active gallery as soon as
  the viewer opens or a card thumbnail expands into the full place gallery, so
  next/previous arrow navigation is warm before the user clicks.
- Preloading is browser-memory only through URL-backed `Image()` objects. The
  project still stores no image binaries and adds no photo cache to disk.

## v0.4.41 — 2026-06-15 — card photo gallery lazy expansion
- Library and Compare card photo clicks now lazy-load the existing
  `/api/places/{place_id}` photo metadata before building the lightbox gallery,
  so a card thumbnail can browse the same multi-photo set as the dossier.
- Kept the photo storage policy lightweight: the app still uses source URLs
  only, downloads no image binaries, and falls back to the clicked thumbnail if
  a detail-photo lookup fails.

## v0.4.40 — 2026-06-15 — language adaptation
- Added a shared language owner for safe BCP-47-like output tags, UI defaults,
  translation targets, and language-settings validation.
- Ask, Scout, Shop, reports, CLI JSON, `/api/config`, and review translation no
  longer force Chinese defaults. Ask cache entries are now language-specific, and
  reports store `report_lang` plus `evidence_lang`.
- Added `web/i18n.js` as the no-build locale catalog for English/Chinese UI
  chrome, browser-language detection, `Intl` formatting, and request language
  hints.
- Added Settings/System controls for UI language, Ask/report output language,
  review translation target, and optional app-wide defaults through
  `/api/settings/language`.

## v0.4.39 — 2026-06-15 — source URL photo gallery extension
- The source-photo lightbox now quotes the exact original image URL in the
  viewer, with an explicit clickable source link for user inspection.
- Dossier source-photo strips now render up to 12 URL-only images, keeping the
  no-binary-cache storage policy while making richer Google/source photo sets
  browsable with the existing arrows and keyboard navigation.

## v0.4.38 — 2026-06-15 — scrollable photo gallery lightbox
- Added previous/next controls and keyboard ArrowLeft/ArrowRight navigation to
  the source-photo lightbox so multi-photo Google/source sets can be reviewed
  without closing the dossier.
- Added mouse/trackpad wheel zoom inside the lightbox. Zoom now grows a real
  scrollable canvas instead of transform-scaling an unscrollable image.
- Kept the URL-only photo policy: the gallery uses existing source URLs and
  still does not download or store image binaries.

## v0.4.37 — 2026-06-15 — darker zoomable photo lightbox
- Darkened and polished the source-photo lightbox so clicked Google/source
  photos read as an intentional in-app viewer instead of a loose overlay.
- Added in-lightbox zoom controls with visible 100%/125% state, reset support,
  keyboard +/- zoom, and focus trapping across the photo controls.
- Preserved the URL-only photo policy: no image binaries are downloaded, cached,
  or added to the backup surface.

## v0.4.36 — 2026-06-15 — aligned photo cards and lightbox
- Library cards no longer promote the first results into wider featured tiles;
  cached shop cards now keep comparable widths and align cleanly across the grid.
- Source/review photo tiles now open an in-app lightbox instead of launching a
  new browser tab. Escape closes the image viewer and returns to the dossier.
- Cards without source photos get a fixed placeholder slot, keeping Library and
  Compare layouts stable while still avoiding any image binary cache.

## v0.4.35 — 2026-06-15 — source photos and navigation clarity
- Added a URL-only photo resolver for cached places, exposing bounded
  `thumbnail` and `photos[]` metadata without downloading image binaries or
  changing backup scope.
- Library cards, dossiers, and Compare cards now render lazy source/review
  photos with stable fallback tiles and safe source links.
- Aligned the top tabs into equal tracks and clarified Scout/Shop/Library/Ask
  labels so Ask reads as cached-evidence Q&A, not a new Google Maps search.

## v0.4.34 — 2026-06-15 — agent CLI global hardening
- Added root-level agent options before subcommands:
  `--format text|json|ndjson`, `--quiet`, `--no-color`, and `--timeout`.
- Global `--format json` now maps to `doctor --json`; global NDJSON works for
  long-running Scout/Shop streams while command-local `--format` remains
  backwards compatible.
- CLI user errors now return exit code `1`, timeouts return `6` with machine
  errors, and unexpected internal failures return `10` without stack traces in
  normal output.

## v0.4.33 — 2026-06-15 — Settings/System status
- Added `GET /api/config`, a non-secret runtime settings endpoint for owner and
  agent status checks.
- Added a compact footer System panel showing reasoning/translation models,
  default answer language, evidence language, cache TTL, hidden data-dir status,
  provider availability, and links to cheap/deep health.
- Dangerous cache/restore actions remain separated in the CLI and require
  explicit confirmation; the web panel is read-only and does not reveal keys or
  private local paths.

## v0.4.32 — 2026-06-15 — cached evidence Compare Board
- Scout result picks and Library picks now open a cached-evidence Compare Board
  once 2-5 places are selected.
- Compare cards show listing facts, review volume, cached coverage, latest
  scrape/report age, report verdict, activity risk, language mix, low-rating
  themes, and walk-in advice.
- The board reads existing dossiers only and does not start Scout, Shop, or
  report generation; each card links back to its dossier.

## v0.4.31 — 2026-06-15 — evidence-centered Ask
- Ask answers can now include separate listing-fact and review-evidence cards,
  keeping the compact answer first while exposing the source material nearby.
- Fresh Ask results return `evidence[]`, `cache_scope`, and
  `evidence_fresh_after` through the web API and CLI JSON envelope.
- Cached-answer banners now explain exact scope and freshness while preserving
  the existing `重新推理` cache-bypass behavior.

## v0.4.30 — 2026-06-15 — dossier decision brief
- Dossiers now open with a compact decision brief before the long report:
  verdict, risk/freshness, top hard facts, and up to three walk-in bullets.
- The scoped Ask form still appears before the full report, and the full report
  remains readable below the brief.
- The review lens, original raw review text, opt-in translation UI, and modal
  focus trap remain covered by focused Playwright regressions.

## v0.4.29 — 2026-06-14 — Library workspace filters
- Added Library filters for category, cache freshness, activity risk, language
  cohort, cached-review threshold, and newest report profile.
- Library cards now show newest report age/profile when available, while keeping
  cache freshness, risk, favorite, review count, and cached count visible.
- Added a Library-local Compare tray for selecting 2-5 cached places without
  opening dossiers. The full side-by-side evidence board remains a later UI PRD
  story.
- Extended `GET /api/places` with `latest_report_at` and
  `latest_report_profile` for list-level report context.

## v0.4.28 — 2026-06-14 — clearer Scout results
- Scout results now repeat the AI plan, bilingual queries, location/profile,
  and reasoning in the final result area.
- AI filter verdicts render kept/excluded places with reason pills, making
  rejected candidates easier to scan without reading the raw timeline.
- Result rows now distinguish shops that received a deep report from candidates
  that were only discovered.
- Timeline rows visually tag retry and cache-hit events.
- Scout result rows can be added to a local Compare pick tray without opening
  each dossier. The full comparison board remains a later UI PRD story.

## v0.4.27 — 2026-06-14 — command center
- Turned the first Scout input into a command center: it accepts broad needs,
  shop names, Maps URLs, and cached-evidence questions without forcing the user
  to choose the right tab first.
- Added local mode recommendation for Scout, Shop, and Ask with a visible reason
  and manual override chips.
- Maps links and shop-name style input can now start Shop from the first field;
  question-style input can route directly into Ask.
- Exact fresh Scout history matches are reused from the visible past-scout list
  unless the user chooses force refresh, avoiding duplicate scrape jobs.

## v0.4.26 — 2026-06-14 — favorite refresh
- Added SQLite-backed favorite metadata for cached places. Refresh remains
  opt-in and disabled by default for every newly favorited place.
- Added `POST /api/places/{place_id}/favorite`; `/api/places` and
  `/api/places/{place_id}` now expose favorite and refresh metadata for the
  Library and dossier surfaces.
- Added agent-safe `placeintel favorite`, `placeintel favorites`, and
  `placeintel refresh-favorites` commands. Refresh defaults to dry-run, checks
  cheap provider routing, caps places/reviews, emits NDJSON pipeline events in
  run mode, and writes search history before each refresh attempt.
- The Library now shows a compact favorite toggle while preserving the dossier
  open action and the no-build web line budget.
- Hardened touched read endpoints to close SQLite connections cleanly.

## v0.4.25 — 2026-06-14 — deployment smoke
- Added `placeintel deploy-smoke --format json`, a read-only runtime verifier
  for `/api/meta`, `/api/health`, versioned static assets, Library reads, and
  one cached dossier read.
- Added optional `--public-url` auth-protection smoke: the unauthenticated public
  URL must return 401/403 while the operator verifies the authenticated or
  loopback `--base-url`.
- Deploy-smoke failures now use the agent JSON error envelope with
  `deploy_smoke_failed` and exit code 3.
- Documented deployment smoke and rollback commands in the operations and agent
  CLI runbooks.
- Sanitized README deployment guidance to use placeholders instead of a real
  protected domain or private proxy topology.
- Updated the private deployment workflow to run the same smoke check after
  restart and to accept `PLACEINTEL_*` deployment secrets while remaining
  compatible with the legacy secret names.

## v0.4.24 — 2026-06-14 — backup and restore
- Added `placeintel backup --format json`, creating an allow-listed local backup
  package under `data/backups` with `manifest.json`, file sizes, and SHA-256
  hashes.
- Backups include `placeintel.db`, `scraper_pro_reviews.db` when present,
  `settings.json`, and generated `reports/`, while excluding `.env` and other
  unlisted files.
- Added `placeintel restore <manifest-or-dir> --yes --format json`, with hash
  verification, required explicit confirmation, default restore-root safety, and
  post-restore SQLite schema validation.
- Added temp-data backup/restore round-trip tests.

## v0.4.23 — 2026-06-14 — resumable job event stream
- Added `GET /api/jobs/{id}/events` as an SSE stream over durable
  `job_events`, with `after` and `Last-Event-ID` resume support.
- Job event payloads now include the append-only event `id`, so the web timeline
  can dedupe streamed events from fallback polling.
- The web UI uses `EventSource` for Scout/Shop progress when available and
  falls back to the existing polling path for final state/results.
- Guarded stale job submissions so a slower previous submit cannot start
  polling a newer job.

## v0.4.22 — 2026-06-14 — durable web jobs
- Persisted Scout/Shop job records in SQLite before worker threads start.
- Added append-only `job_events` storage while preserving the existing
  `{t, stage, msg, data?}` event contract.
- Changed `/api/jobs/{id}` to read durable state, including results, errors,
  request payloads, and retry hints.
- Startup now marks old `running` jobs from a previous process as
  `interrupted` instead of silently losing them.
- The web UI shows interrupted jobs with a `用缓存重试` action that resubmits the
  same request with cache reuse.

## v0.4.21 — 2026-06-14 — Scout/Shop machine output
- Added `--format json|ndjson` to `placeintel scout` and `placeintel shop`.
- NDJSON mode emits one compact `type:"event"` object per pipeline event using
  the existing `{t, stage, msg, data?}` contract, followed by a final
  `type:"result"` envelope.
- JSON mode suppresses human progress text and prints only the final agent-safe
  result envelope, while text mode remains backward compatible.
- Fixed the CLI schema contract so health mode allows both `cheap` and `deep`.

## v0.4.20 — 2026-06-14 — deep doctor + agent CLI contracts
- Added opt-in deep health diagnostics through `placeintel doctor --live --json`
  and `GET /api/health/deep`.
- Deep diagnostics check reasoning model listing/ping, translation ping,
  embedding ping, Chrome, Docker, gosom image, review-scraper vendor path, and
  SerpAPI fallback configuration without exposing secrets.
- Agent-facing CLI contracts now include schema output and machine-readable Ask
  JSON, preserving exact place scope when a question is scoped to one shop.

## v0.4.19 — 2026-06-14 — cleaner lists + Library controls
- Past scout rows now hide AI-excluded place chips instead of showing a long
  struck-through wall of rejected candidates.
- The row meta still keeps the useful summary, such as `AI 排除 15 家`, while
  the chip list focuses only on places the user may actually open.
- Long kept-candidate lists are capped with a `+N 家` chip so past scouts stay
  readable even when a cached search returned many places.
- The Library tab now has a cached-shop search box, sort control, and a 12-card
  initial cap with `显示更多`, so large caches are easier to scan.
- Default Library ordering is now a smart score instead of raw cached-review
  count only: reports, cached evidence, total review volume, rating, freshness,
  and activity-risk signals all contribute.

## v0.4.18 — 2026-06-14 — Scout past scouts
- Added a visible **已侦察 / past scouts** section directly under the Scout form,
  showing recent cached search runs before users start a new scout.
- Reused `/api/searches` and the existing history row renderer, so past query,
  location, source/cache age, AI-excluded chips, and clickable shop dossiers stay
  consistent with the Library tab.
- Scout history refreshes on tab load, manual refresh, and after a Scout job
  completes, reducing accidental duplicate scraping/reasoning work.

## v0.4.17 — 2026-06-14 — review rating filters
- Added a rating filter row to the dossier raw-review lens: all, 5-star, 4-star,
  and `≤3★` issue reviews.
- Rating filters combine with the existing language filters, making it easier to
  isolate low-score comments and understand which concrete issues caused bad
  ratings.
- Translation batches continue to respect the currently visible filtered review
  list, so users can translate only the low-rating issue set when needed.

## v0.4.16 — 2026-06-14 — cheaper batch review translation
- Review translations now use a separate low-cost translation model role,
  defaulting to `gemini-3.1-flash-lite` via the VectorEngine reasoning route,
  instead of sharing the main report/Ask reasoning model.
- Clicking any review translation button now translates every currently visible
  review in that dossier section, respecting the active language filter and
  skipping already translated cards.
- Batch translation is guarded against rapid duplicate clicks and target changes
  while requests are in flight, so stale responses do not overwrite the current
  target-language view.
- Added a remembered target-language selector in the review lens. The browser
  default is Chinese (`zh` / CN), users can switch to English, and the choice is
  saved in local storage for later dossiers.
- The translation endpoint now accepts `cn` as a Chinese alias and `/api/meta`
  exposes the separate `translate` model/provider for transparency.
- Cached review translations now store provider metadata, keeping old cache rows
  from being mislabeled after a future provider route change.

## v0.4.15 — 2026-06-14 — optional review translation
- Added per-review on-demand translation in shop dossiers. Raw reviews remain
  original by default; users can click a compact `译文` control on a specific
  review to see a translated overlay.
- Added `POST /api/reviews/translate`, backed by the existing reasoning provider
  rather than scrape-time Google translation. Translations are cached by
  `review_id`, target language, and raw-text hash so refreshed reviews invalidate
  stale translations.
- Added tests for translation caching, API delegation, and the browser click path.

## v0.4.14 — 2026-06-14 — compact review language lens
- Kept the review language tabs visible, but moved the large per-language
  insight cards behind a collapsed disclosure so raw comments remain easy to
  read.
- Tightened the language lens spacing and prevented nested insight summaries
  from inheriting the raw-review disclosure marker style.

## v0.4.13 — 2026-06-14 — review language lens
- Added a language-aware lens to the shop dossier's raw reviews section. Reviews
  are grouped by detected original language, with Chinese and English surfaced
  first when present for Vec's reading flow.
- Each language cohort now shows count, average rating, likely audience signal,
  recurring topic chips, and a representative excerpt from the cached review
  text.
- Added review-language filter pills so users can switch the raw comments list
  between all reviews and a single language cohort without leaving the dossier.
- Fingerprinted the no-build `app.css` and `app.js` URLs with the server-injected
  package version so already-open browser tabs pick up fresh styling after restart.
- Kept country/region wording honest: the current cache has review text but no
  reliable reviewer-country field, so the UI treats language as a signal rather
  than inventing nationality.
- Added a Playwright regression proving the language lens renders Chinese,
  English, Vietnamese, and Korean cohorts and filters raw review cards, plus a
  server contract for static asset fingerprinting.

## v0.4.12 — 2026-06-14 — dossier ask placement polish
- Moved the shop-scoped **只问这家店 / Ask this shop** form above the long dossier
  report body, so users can ask follow-up questions immediately after opening a
  shop instead of scrolling past the analysis.
- Preserved the existing per-shop `place_id` ask scope, scoped QA history chips,
  modal focus behavior, and report/review ordering.
- The web shell now sends `Cache-Control: no-store` for `/` and `/static/*`, so
  existing browser tabs do not keep running a stale no-build `app.js` after a
  local patch/restart.
- Added a Playwright regression proving the scoped ask form renders before the
  report body while keeping its `data-place-id`, plus a server contract for
  no-cache web assets.

## v0.4.11 — 2026-06-14 — all-scope Ask history display
- The top-level **提问 Ask** history now shows previously asked single-shop
  questions as well as global questions, with the shop name appended to each
  scoped chip.
- Clicking a shop-scoped history chip from the Ask tab re-asks with the original
  `place_id`, preserving the exact-scope QA cache rule instead of treating a
  single-shop answer as global evidence.
- Added `GET /api/qa?scope=all` as a display-only history mode. The default
  `/api/qa` response remains global-only, and `/api/qa?place_id=...` remains
  per-shop exact-scope.
- Added server and Playwright regressions for all-scope history display and
  scoped re-ask behavior.
- Gated the VPS deploy workflow to the private deployment repo so the public
  code-only mirror no longer creates false-red deploy runs when private secrets
  are intentionally absent.

## v0.4.10 — 2026-06-13 — report reasoning retry
- Report generation now retries transient reasoning-model failures before giving
  up: rate limits, 5xx provider errors, connection failures, and timeouts get
  three exponential-backoff attempts.
- The retry wrapper covers both single-pass report generation and map-reduce
  evidence chunk mining, so large-review dossiers no longer fail on one temporary
  model hiccup.
- Report-stage progress now surfaces automatic retry activity in CLI/Web events
  while preserving the existing fail-after-final-attempt behavior for real errors.
- Added deterministic unit regressions with a flaky fake reasoning client.
- Added API and Playwright regressions proving previously asked questions are
  viewable from `/api/qa`, rendered on the Ask tab, and re-askable from chips.
- Closed the `/api/qa` SQLite connection after each history read.

## v0.4.9 — 2026-06-12 — browser chrome theming
- Added light/dark `theme-color` metadata so mobile and desktop browser chrome
  matches the app surface instead of falling back to default colors.
- Declared CSS `color-scheme: light dark` on the document root so native form
  controls and scrollbars align with the app's light/dark tokens.
- Added an explicit on-accent text token so primary buttons stay readable and
  intentional in dark mode.
- Added static regressions for browser chrome metadata, CSS theme support, and
  accent-button text color.

## v0.4.8 — 2026-06-12 — placeholder polish + JS headroom
- Tightened input placeholders against the Web Interface Guidelines: every
  placeholder now shows an example pattern and ends with an ellipsis.
- Added a static regression so future placeholders keep that shape across the
  HTML shell and rendered shop-dossier ask form.
- Reduced `web/app.js` from 799 to 780 lines, leaving budget headroom for urgent
  no-build SPA fixes while staying inside the 3-file app constraint.

## Deployment — 2026-06-12 — protected public domain
- Added a protected public-domain deployment path through a private proxy stack.
- Kept the app process loopback-only on `127.0.0.1:9618`; public traffic enters
  only through an authenticated proxy.
- Stored public-domain login values in local gitignored env files or deployment
  secrets; the remote host stores only the Basic Auth hash.

## v0.4.7 — 2026-06-12 — dossier modal focus trap
- The shop dossier now traps Tab and Shift+Tab inside the modal while it is open,
  so keyboard users do not land on hidden background controls.
- Extended the deterministic Playwright dossier test to prove focus entry,
  backward edge trapping, forward edge trapping, Escape close, and opener focus
  restoration from the same mocked detail response.

## v0.4.6 — 2026-06-12 — dossier dialog keyboard focus polish
- The shop dossier overlay now moves keyboard focus to the close control as soon
  as it opens, including while data is still loading.
- Closing a dossier with Escape, the close button, backdrop, or cache-delete flow
  restores focus to the opener when that opener is still present in the document.
- Added a deterministic Playwright regression that mocks the detail API response,
  opens a synthetic dossier, and verifies focus entry plus focus return without
  depending on local cached places.

## v0.4.5 — 2026-06-12 — accessibility + deep-link navigation polish
- Added a skip link and main landmark target so keyboard users can jump past the
  masthead/tabs into the primary app surface.
- Tightened tab semantics: tabs now use roving `tabindex`, URL hash deep links
  (`#scout`, `#shop`, `#library`, `#ask`), and Arrow/Home/End keyboard navigation.
- Added stable `name` attributes and numeric input hints to form controls, making
  the no-build SPA friendlier to browser autofill, accessibility tooling, and
  future form instrumentation.
- Fixed FastAPI app metadata drift by deriving `app.version` from the package
  version instead of a stale literal.
- Added regression coverage for the accessibility shell, app-version contract,
  and hash/keyboard tab behavior.

## v0.4.4 — 2026-06-12 — stale review activity risk tag
- Added a deterministic `activity_risk` signal for places with many historical
  reviews but no recent known reviews. Current thresholds are conservative:
  80+ total reviews, newest parsed review at least 180 days old, high severity at
  365+ days. The tag warns to verify current operation; it does not claim closure.
- Fed the activity signal into the reasoning prompt and saved report JSON/Markdown
  so generated reports include the current-status caveat even when the model is
  otherwise focused on price/facts/review complaints.
- Exposed `activity_risk` on `/api/places` and `/api/places/{id}`, and rendered a
  small cautious badge in the library plus a fuller warning line in shop detail.
- Added unit coverage for stale/recent/low-volume boundaries and Playwright
  coverage for visible badge/detail rendering.

## v0.4.3 — 2026-06-12 — list-valued Google category binding fix
- Fixed a single-shop Google Maps failure where provider payloads could carry a
  list-valued category/metadata field into a SQLite `TEXT` column, causing
  `Error binding parameter 3: type 'list' is not supported`.
- Added a cache contract regression that writes a `Place` with a list category and
  verifies it is stored as readable text instead of crashing. Raw provider payloads
  remain preserved in `raw_json`.

## v0.4.2 — 2026-06-12 — mobile UX hardening + repeatable web smoke
- Strengthened the web UI contrast system so helper text, placeholders, and the
  primary Scout action read as active controls instead of disabled chrome on mobile.
- Enlarged the natural-language query textarea and shortened the mobile placeholder
  copy so examples no longer clip in the first viewport.
- Added repeatable web guards: Python static contract tests for the no-build SPA
  limits/contrast/copy, plus a Playwright smoke test for console errors, horizontal
  overflow, and first-action visibility.
- The private VPS deploy workflow now runs those checks against a local web server
  before SSH sync/restart, so broken UI changes fail before touching systemd.

## v0.4.1 — 2026-06-12 — private VPS deployment lane
- Added a private GitHub Actions deployment workflow for a native systemd service
  on a protected VPS. The service stays bound to `127.0.0.1:9618` by default
  so the AI-key-backed web UI is not exposed publicly without an explicit proxy.
- Added `deploy/remote-bootstrap.sh`: idempotent remote setup for Python venv,
  Google Chrome, vendored review scraper, service restart, and local health check.
- Expanded secret hygiene: `.env.*` is ignored, app/runtime keys are expected via
  local/VPS env files and GitHub Secrets, never committed.

## Open-sourced — 2026-06-11 (MIT)
- First public release on GitHub: <https://github.com/vecyang1/place-intel>.
- Added `LICENSE` (MIT), `.env.example`, and install/setup docs (including cloning
  the vendored MIT review scraper). Config now also loads a project-local `.env`.
- Open-source credits added (gosom maps scraper, google-reviews-scraper-pro, Gemini, SerpAPI).

## v0.4.0 — 2026-06-11 — front-end model switching (live list, persisted)
- **The reasoning model is now user-switchable and remembered**: footer 「更换模型 ⇄」
  opens a picker; the choice is persisted in `data/settings.json` and shared by
  Web + CLI across restarts. CLI: `placeintel model [--list] [name]`.
- **Model list is LIVE from the provider** (`GET /api/models` →
  VectorEngine `/v1beta/models`), never a baked-in list — agent training
  knowledge of model names is stale by definition (the live list surfaced
  gemini-3.5-flash / gemini-3-flash-preview / gemini-flash-latest, all unknown
  to the agent). Free-text input also accepted for unlisted names.
- **Smoke test before save**: `POST /api/settings` runs one real generateContent
  call with the candidate model; failure → HTTP 400 with the provider's error,
  nothing persisted. Verified live: fake model rejected (503 surfaced), real
  switch to gemini-3-flash-preview saved and used by the next ask.
- Precedence: settings.json > $PLACEINTEL_REASON_MODEL > default. settings.json
  never holds keys.

## v0.3.1 — 2026-06-11 — model/provider transparency
- `GET /api/meta` exposes resolved models + providers (never keys); footer shows
  "推理 gemini-2.5-flash @ VectorEngine · 向量 gemini-embedding-2-preview (768d)
  @ Google 官方 · vX".
- Timeline events name the model+provider when reasoning/embedding actually runs;
  report meta line in the dossier shows the report's stored model; every ask answer
  (cached included) carries a `model @ provider` tag.

## v0.3.0 — 2026-06-11 — full-coverage analysis (map-reduce) + evidence translation
- **Map-reduce review mining**: when a place has more cached reviews than fit one
  prompt (>400), every chunk of 200 is mined into a dense evidence digest (3-wide
  parallel), then a reduce pass writes the report from ALL digests + raw low-star +
  newest raw reviews — nothing scraped goes unread (was: newest-400 + low-star cap).
  Live progress: "分 N 块全量深读，一条不漏". Report header states exact coverage.
- **Evidence language is configurable** (default: translated): quoted review
  excerpts in reports AND ask answers are translated into the report language with
  an original-language tag (`[2026-05-21|★5.0|原文:韩语] …`). Reviews are stored as
  scraped originals (e.g. the E-Taxi shop's 237/300 Korean reviews are genuine
  Korean originals, not Google auto-translate). `--evidence-lang original` /
  `PLACEINTEL_EVIDENCE_LANG=original` keeps verbatim quotes.
- Knobs: `PLACEINTEL_MAX_REVIEWS_PROMPT` (single-pass ceiling, default 400),
  `PLACEINTEL_MAP_CHUNK` (default 200).

## v0.2.1 — 2026-06-11 — grounded asks, persisted verdicts, QA answer cache
- **Ask is now metadata-grounded**: place listing facts (address, hours, phone,
  website, rating) are fed to the model as the authoritative source alongside
  review evidence — "几点开门/地址在哪" questions answer from the listing instead
  of "unknown".
- **AI filter verdicts are persisted** on the search row and (a) reused on repeat
  scouts (no re-judging, no extra LLM cost), (b) shown in 历史搜索 — excluded shops
  render struck-through with the AI's reason (`AI 排除 N 家`).
- **Semantic QA answer cache** (user idea): every reasoned answer is stored with its
  question embedding; an identical or semantically similar question (same scope,
  cosine ≥0.90) returns the cached answer instantly (~0.5s vs ~15s) with a
  "⚡ 缓存答案" label + 重新推理 button. Invalidation: any new review scrape in the
  scope voids older answers. CLI: `ask --fresh` bypasses.
- **Q&A history**: recent questions render as re-askable chips under the Ask tab and
  in each shop dossier (`GET /api/qa`).
- **Delete from cache**: `DELETE /api/places/{id}` + dossier button removes a place
  and all derived data (reviews/vectors/reports/QA) — for purging v0.1-era junk
  like the 300-review E-Taxi; deleted places drop out of history rows.

## v0.2.0 — 2026-06-11 — AI-native upgrade
- **AI query planner** (`planner.py`): free-text input in ANY language → structured
  plan (intent, bilingual search queries, location extraction, profile, report
  language, discover-vs-single mode). Fail-open passthrough if the LLM dies.
- **AI relevance filter**: one LLM call judges all discovered candidates against the
  user's intent with per-place reasons — kills the motorbike-for-guitar bug class.
  Live-verified: excluded motorbike rental / theme park / e-taxi / bar / clothing
  store from a guitar-rental query.
- **Single-shop mode** (`scout_single`, CLI `shop`, `POST /api/shop`): shop name or
  Google Maps URL → focused report on that one place. Diacritic-insensitive cache
  name matching (`Hội An` == `hoi an`).
- **Live progress events**: pipeline emits `{t, stage, msg, data}` through `on_event`;
  web UI renders a transparent timeline (AI plan card, filter verdicts ✓/✕, per-place
  scrape/embed/report progress); CLI prints the same events.
- **Report reuse**: skip re-analysis when no new reviews since the last report
  (profile-aware; `generic` accepts any profile's report).
- **Date-aware analysis**: today's date injected into reasoning prompts — kills false
  "future-dated reviews" red flags from the model's stale training-cutoff sense of time.
- **Web UI v2** (3-file SPA, no build step): tabs 侦察/单店/资料库/提问, live timeline,
  shop dossier overlay (facts + report + scoped ask + review browser), library cards
  with featured hierarchy, past-searches history, XSS-safe markdown, 320px responsive,
  deliberate light/dark. Static assets served from `/static`.
- New CLI commands: `shop`, `plan` (debug the AI's plan), `history`; new flags
  `--no-ai`, `--report-lang` defaults to the language you typed in.
- API: `/api/shop`, `/api/places/{id}` detail, `/api/searches`; job objects now
  stream `events`.

## v0.1.1 — 2026-06-11
- Provider split (user decision): embedding → Google official, reasoning → VectorEngine.
- True batch embedding via explicit `types.Content` lists: 64 docs in ~2s (was ~40s
  per-item via VT thread pool); per-item fallback retained for aggregating gateways.
- V.A.U.L.T. docs: VAULT.md router, project AGENTS.md, CHANGELOG, vault/ evidence dirs.

## v0.1.0 — 2026-06-11
- Initial release, live-verified e2e (Hoi An guitar-rental scout).
- Pipeline: gosom discovery (Docker) → reviews-scraper-pro (incremental, vendored)
  → SQLite cache → Gemini Embedding 2 vectors → Gemini Flash profile-driven reports.
- SerpAPI fallback for both discovery and reviews.
- CLI (`scout/ask/report/list/profiles/export`), FastAPI web shell (port 9618),
  Claude skill `place-intel` (3-root symlinks).
- Fixes during verification: VT key routing, batch-aggregation guard, genai client
  thread race, SeleniumBase UC 9222 collision bootstrap, live-result ordering.
