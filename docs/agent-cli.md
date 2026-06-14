# placeintel Agent CLI

Last updated: 2026-06-14

This document tells future agents how to call the CLI without scraping the web
UI. The stable machine-readable surface is JSON for read commands and JSON or
NDJSON for long-running Scout/Shop commands.

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
| 3 | Deployment smoke or external runtime target unavailable/unhealthy |

PRD target codes still to implement across all commands:

| Code | Meaning |
| --- | --- |
| 4 | Partial completion with warnings |
| 5 | Cache empty/no matching data |
| 6 | Timeout/cancelled |
| 10 | Internal unexpected error |

## Machine-Readable Contract

### Long-Running Scout/Shop

`scout` and `shop` support three formats:

- `--format text`: backwards-compatible human output with timeline text.
- `--format json`: one final JSON envelope on stdout after the run finishes.
- `--format ndjson`: one compact JSON object per line; event lines arrive as
  progress is emitted, and the final line has `type:"result"`.

Scout NDJSON:

```bash
.venv/bin/placeintel scout "guitar lesson" --near "Hoi An" --format ndjson
```

Event line:

```json
{"type":"event","version":"0.4.x","command":"scout","t":1781440000.0,"stage":"search","msg":"human readable","data":{}}
```

Final result line:

```json
{"type":"result","ok":true,"version":"0.4.x","command":"scout","data":{"result":{"query":"guitar lesson","location":"Hoi An","profile":"generic","mode":"discover","plan":{},"places":[],"filtered":[],"reports":[],"errors":[]}}}
```

`data.result` mirrors the web job `result` object: `query`, `location`,
`profile`, `mode`, `plan`, `places`, `filtered`, `reports`, and `errors`.
In JSON/NDJSON modes, human progress text is suppressed from stdout.

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
| `scout "query"` | text, JSON, NDJSON | Long-running; NDJSON event lines preserve `{t, stage, msg, data?}` and end with `type:"result"`. |
| `shop "name-or-url"` | text, JSON, NDJSON | Single-place scout with the same machine formats as `scout`. |
| `plan "text"` | JSON body | Existing debug output is already JSON. |
| `history` | text, JSON | `history --format json` returns recent searches. |
| `ask "question"` | text, JSON | `ask --format json` returns answer/cache/model/provider metadata and echoes `place_id` when scoped. |
| `report <place_id>` | markdown text, JSON | `report --format json` returns the latest cached report without regenerating. |
| `list` | text, JSON | `list --format json` returns cached places. |
| `profiles` | text, JSON | `profiles --format json` returns profile names and dimensions. |
| `model [name] --list` | text | Live provider call when listing or switching. |
| `export <place_id>` | JSON body, JSON envelope | Default remains the legacy raw JSON body; `--format json` uses the agent envelope. |
| `doctor` | text, JSON | Implemented in this milestone. |
| `schema` | text, JSON | `schema --format json` lists core CLI/API schemas, including `pipeline_result`, `backup_manifest`, and docs paths. |
| `backup` | text, JSON | `backup --format json` creates a non-secret backup package with manifest hashes. |
| `restore <manifest-or-dir>` | text, JSON | Requires `--yes`; verifies hashes and DB schema before replacing local runtime data. |
| `deploy-smoke` | text, JSON | Read-only deployment proof for `/api/meta`, `/api/health`, versioned static asset, Library, dossier, and optional unauthenticated public rejection. |

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

Create a backup before destructive work:

```bash
.venv/bin/placeintel backup --format json
```

Restore from the returned manifest path:

```bash
.venv/bin/placeintel restore "data/backups/placeintel-backup-YYYYMMDDTHHMMSSZ/manifest.json" --yes --format json
```

Restore refuses paths outside `data/backups/` unless `--force` is supplied for a
trusted path. The JSON result includes `restored_files`; failure envelopes use
codes such as `confirmation_required`, `outside_backup_root`,
`bad_manifest`, and `hash_mismatch`.

Verify a local or SSH-tunneled deployment after release:

```bash
EXPECTED_VERSION=$(.venv/bin/python -c "import placeintel; print(placeintel.__version__)")
.venv/bin/placeintel deploy-smoke \
  --base-url "http://127.0.0.1:9618" \
  --expected-version "$EXPECTED_VERSION" \
  --format json
```

When a protected public URL exists, verify that unauthenticated traffic is
rejected without putting credentials in the command:

```bash
EXPECTED_VERSION=$(.venv/bin/python -c "import placeintel; print(placeintel.__version__)")
.venv/bin/placeintel deploy-smoke \
  --base-url "http://127.0.0.1:9618" \
  --public-url "https://PLACEHOLDER_PROTECTED_DOMAIN" \
  --expected-version "$EXPECTED_VERSION" \
  --format json
```

Failure exits with code `3` and a `deploy_smoke_failed` error envelope.

Run a scout from another agent and stream events:

```bash
.venv/bin/placeintel scout "guitar lesson" --near "Hoi An" --format ndjson
```

Run a single shop and parse only the final result:

```bash
.venv/bin/placeintel shop "D'Class Guitar" --near "Hoi An" --format json
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
