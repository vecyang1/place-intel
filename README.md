# placeintel — Walk In Armed 🎯

进店之前，先读完它的几百条评价。Never get quoted a "tourist price" unprepared again.

Say *"会安 吉他租赁"* — in **any language** — and the AI plans the search itself:
translates into bilingual Google Maps queries, extracts the location, picks the
report profile, discovers places, **filters out off-category junk with stated
reasons** (no more motorbike rentals in a guitar search), scrapes the **full review
history** (hundreds of reviews — the official API caps at 5), caches everything
locally, embeds reviews for semantic search, and has Gemini reason out an intel
report: **价格情报 · 硬信息核实 · 红旗预警 · 30-second walk-in brief**.

## Install

```bash
git clone https://github.com/vecyang1/place-intel.git
cd place-intel
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"          # add the web app; use `pip install -e .` for CLI-only

# Review scraper (vendored separately, MIT) to keep this repo lean:
git clone https://github.com/georgekhananaev/google-reviews-scraper-pro.git \
  vendor/google-reviews-scraper-pro

cp .env.example .env             # then add at least one Gemini key
```

## Quick start

```bash
.venv/bin/placeintel scout "会安 吉他租赁"                 # AI plans everything
.venv/bin/placeintel shop "D'Class Guitar" --near "Hoi An" # ONE shop (name or Maps URL)
.venv/bin/placeintel ask "哪家有耐心的老师?"               # RAG over everything cached
.venv/bin/placeintel plan "在岘港学冲浪"                   # debug: see the AI's plan
.venv/bin/placeintel-web                                   # web app → http://127.0.0.1:9618
```

The web app has four views: **侦察 Scout** (free text + live progress timeline showing
the AI's plan, filter verdicts, and every pipeline stage), **单店 Shop** (one name/URL →
focused dossier), **资料库 Library** (cached shops + past searches → shop dossier with
report, scoped ask, review browser), **提问 Ask** (cross-shop RAG).

## Private VPS deploy

The private deployment path is GitHub Actions → SSH → native systemd service. It
keeps the FastAPI web app on VPS loopback (`127.0.0.1:9618`) by default; use an
SSH tunnel or add a deliberate HTTPS/auth proxy before exposing it publicly.

Required private-repo secrets:

```text
GMR_DEPLOY_HOST
GMR_DEPLOY_USER
GMR_DEPLOY_PORT
GMR_DEPLOY_SSH_KEY
GMR_DEPLOY_DIR
GOOGLE_API_KEY
VECTORENGINE_API_KEY
SERPAPI_API_KEY
PLACEINTEL_REASON_MODEL
```

After deploy, tunnel the frontend from your Mac:

```bash
ssh -N -L 9619:127.0.0.1:9618 <vps-ssh-alias>
open http://127.0.0.1:9619
```

## How it works

```
free text ─► planner.py ──── AI plan: intent, bilingual queries, location, profile,
              │              discover-vs-single mode  (fail-open: raw passthrough)
              ▼
        discover.py ──────── gosom/google-maps-scraper (Docker, free)
              │              └ fallback: SerpAPI google_maps
              ▼
        planner.filter ───── AI relevance verdicts per candidate (fail-open: keep all)
              ▼
        reviews.py ────────── vendor/google-reviews-scraper-pro (Selenium, incremental)
              │              └ fallback: SerpAPI google_maps_reviews
              ▼
        cache.py ──────────── data/placeintel.db (SQLite: places/reviews/reports/vectors)
              │
        embed.py ──────────── Gemini Embedding 2, Google official (768-dim, true batch)
              │
        analyze.py ────────── Gemini Flash (VectorEngine) long-context over ALL reviews
              │
        cli.py / server.py (events → live timeline) / web/ SPA / Claude skill
```

Design choices that matter:
- **AI is fail-open everywhere**: a dead LLM degrades to raw-query passthrough and
  keep-all-candidates — it never blocks the scrape pipeline.
- **Reasoning over retrieval for per-place reports**: a place's full review set fits in
  Flash's context, so the report reads *everything* — embeddings serve cross-place
  `ask` queries over the growing cache instead.
- **Cache-first**: same search within 7 days = no re-discovery; reviews are scraped
  incrementally; reports are **reused** when no new reviews arrived.
- **Provider split** (user decision): embedding → Google official (true Content-list
  batching, 64 docs/2s); reasoning → VectorEngine (same models, cheaper).
- **Profiles** (`profiles/*.yaml`): `_core.yaml` (price/hard-facts/red-flags) merges
  into every profile; add a YAML to add a domain (lessons, rental, ...).
- **Transparency is a feature**: every stage emits events `{t, stage, msg}` rendered
  as a live timeline in both CLI and web — including *why* each shop was excluded.

## Requirements & keys

- Docker (for free discovery) — auto-started on macOS; otherwise `--force-serpapi`
- Chrome (for the review scraper)
- Keys via `.env` or environment variables (see `.env.example`): `GOOGLE_API_KEY`
  (AIza…, embedding), `VECTORENGINE_API_KEY` (sk-…, reasoning), and optional
  `SERPAPI_API_KEY` (fallback). At least one Gemini key is required.

## Gotchas (hard-won)

- A plain list-of-strings embed input is **aggregated into ONE vector** on both
  providers — true batching needs explicit `types.Content` objects (embed.py).
- Reasoning prompts must include **today's date** or the model flags recent reviews
  as "future-dated fakes" (analyze.py).
- Vietnamese diacritics break naive name matching ("Hội An" ≠ "Hoi An") — use
  `cache.norm_name` (NFD strip + đ→d + token-AND).
- `genai.Client` must be constructed before fanning out threads.
- gosom output may be NDJSON or a JSON array; reviews-scraper-pro maps back via
  `places.original_url`; SeleniumBase needs the 9222-collision bootstrap (reviews.py).

## Credits

Stands on the shoulders of open source — please ⭐ them:

- [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) — free place discovery (Docker)
- [georgekhananaev/google-reviews-scraper-pro](https://github.com/georgekhananaev/google-reviews-scraper-pro) — full review-history scraping (MIT)
- [Google Gemini](https://ai.google.dev/) — embedding + reasoning · [SerpAPI](https://serpapi.com) — optional fallback

## License

MIT — see [LICENSE](LICENSE).
