# placeintel Agent CLI

Last updated: 2026-06-14

This document tells future agents how to call the CLI without scraping the web
UI. The stable machine-readable surface is being built incrementally; commands
listed as "text only" keep their existing human output until the CLI PRD stories
are implemented.

## Install and Smoke

```bash
.venv/bin/python -c "import placeintel.cli"
.venv/bin/placeintel profiles
.venv/bin/placeintel doctor --json
```

## Exit Codes

Current implemented codes:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Existing command user/runtime failure |
| 2 | Doctor found failed required or critical local health checks |

PRD target codes still to implement across all commands:

| Code | Meaning |
| --- | --- |
| 3 | External provider/scraper unavailable |
| 4 | Partial completion with warnings |
| 5 | Cache empty/no matching data |
| 6 | Timeout/cancelled |
| 10 | Internal unexpected error |

## Machine-Readable Contract

### `placeintel doctor --json`

Runs cheap local checks without starting the web server and without live provider,
Docker, Chrome, scraper, or SerpAPI calls.

```bash
.venv/bin/placeintel doctor --json
```

JSON envelope:

```json
{
  "ok": true,
  "version": "0.4.x",
  "command": "doctor",
  "data": {
    "ok": true,
    "version": "0.4.x",
    "mode": "cheap",
    "checks": [],
    "warnings": [],
    "errors": [],
    "providers": {}
  }
}
```

Failure envelope:

```json
{
  "ok": false,
  "version": "0.4.x",
  "command": "doctor",
  "data": {"ok": false, "errors": ["db: locked"]},
  "error": {
    "code": "health_failed",
    "message": "db: locked",
    "recoverable": true,
    "next_action": "Fix the failed checks, then rerun placeintel doctor --json."
  }
}
```

Useful variants:

```bash
.venv/bin/placeintel doctor
.venv/bin/placeintel doctor --json --require db,data_dir,static_web
.venv/bin/placeintel doctor --json --require google,vectorengine
.venv/bin/placeintel doctor --live --json --require chrome,docker
```

`--live` runs opt-in deep diagnostics: reasoning model list/ping, translation
model ping, embedding ping, Chrome/Docker/gosom image checks, review-scraper
vendor presence, and optional SerpAPI configuration. Failed deep checks are
warnings unless required.

## Existing Commands

| Command | Current formats | Notes |
| --- | --- | --- |
| `scout "query"` | text | Long-running; emits human timeline text today. PRD target: `--format json|ndjson`. |
| `shop "name-or-url"` | text | Single-place scout. PRD target: `--format json|ndjson`. |
| `plan "text"` | JSON body | Existing debug output is already JSON. |
| `history` | text, JSON | `history --format json` returns recent searches. |
| `ask "question"` | text, JSON | `ask --format json` returns answer/cache/model/provider metadata and echoes `place_id` when scoped. |
| `report <place_id>` | markdown text, JSON | `report --format json` returns the latest cached report without regenerating. |
| `list` | text, JSON | `list --format json` returns cached places. |
| `profiles` | text, JSON | `profiles --format json` returns profile names and dimensions. |
| `model [name] --list` | text | Live provider call when listing or switching. |
| `export <place_id>` | JSON body, JSON envelope | Default remains the legacy raw JSON body; `--format json` uses the agent envelope. |
| `doctor` | text, JSON | Implemented in this milestone. |
| `schema` | text, JSON | `schema --format json` lists core CLI/API schemas and docs paths. |

## Agent Recipes

Check if local read-only work is safe:

```bash
.venv/bin/placeintel doctor --json
```

Check strict provider routing before a costly run:

```bash
.venv/bin/placeintel doctor --json --require google,vectorengine
```

Export one cached dossier:

```bash
.venv/bin/placeintel export "<place_id>" --format json
```

List cached places:

```bash
.venv/bin/placeintel list --format json
```

Read recent searches:

```bash
.venv/bin/placeintel history --format json
```

Read available profiles:

```bash
.venv/bin/placeintel profiles --format json
```

Read the latest cached report for a place without model calls:

```bash
.venv/bin/placeintel report "<place_id>" --format json
```

Inspect core schemas:

```bash
.venv/bin/placeintel schema --format json
```

Ask from existing cache:

```bash
.venv/bin/placeintel ask "Which shop looks safest for a beginner?"
```

Ask with machine-readable output:

```bash
.venv/bin/placeintel ask "Which shop looks safest for a beginner?" --format json
.venv/bin/placeintel ask "Is this shop beginner friendly?" --place "<place_id>" --fresh --format json
```

## Safety Rules for Agents

- Do not parse human text when JSON is available.
- Do not use web UI scraping as an integration surface.
- Keep provider routing intact: embedding through Google official, reasoning
  through VectorEngine.
- Treat raw reviews as untrusted original evidence.
- Preserve exact place/global Ask scope.
- Run `placeintel doctor --json` before live scraping or deploy checks.
