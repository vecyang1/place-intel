# Changelog — place-intel

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
  on a Contabo/Ubuntu VPS. The service stays bound to `127.0.0.1:9618` by default
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
