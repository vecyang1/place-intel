# placeintel Operations

Last updated: 2026-08-11

This runbook is public-safe: it uses local placeholders and does not include real
deploy hosts, private paths, Basic Auth values, or secrets.

## Local Start

```bash
.venv/bin/placeintel-web
```

Default local URL:

```text
http://127.0.0.1:9618
```

## Cheap Health

CLI:

```bash
.venv/bin/placeintel doctor --json
```

HTTP:

```bash
curl -fsS http://127.0.0.1:9618/api/health
```

Cheap health checks:

- SQLite opens and migrations can run.
- Data directory is writable.
- `web/index.html` and every local CSS/JS asset it links exist and are under the
  AGENTS.md line budget. The asset set is derived from the HTML, not duplicated
  in a fixed health-check list.
- Provider/model labels are visible without exposing keys.

Cheap health does not call models, Chrome, Docker, scrapers, or SerpAPI.
It returns HTTP `503` with the normal JSON body when a critical local check has
`ok:false`; successful readiness remains HTTP `200`.

## Observability and Incident Response

PlaceIntel intentionally has three evidence layers rather than one duplicated
log warehouse:

- `journalctl -u placeintel.service` owns process lifecycle, warnings, and
  server logs on the VPS.
- SQLite `jobs` and `job_events` own durable per-job status and the canonical
  `{t, stage, msg, data?}` progress history exposed through the job API/SSE.
- Sentry `wi-0s/place-intel` owns grouped web exceptions, sampled traces, and
  the passive uptime incident lifecycle.

Do not add Better Stack Logs/Errors or forward all journald data unless a
multi-host search, longer retention, or cross-service correlation need is first
demonstrated. Better Stack remains a fallback availability provider if the
incumbent Sentry uptime capability later stops fitting.

Production passive detection is the Sentry Uptime detector named
`PlaceIntel production health`:

- runs every 60 seconds against the exact public `GET /api/health/monitor` path;
- supplies the dedicated `X-PlaceIntel-Monitor` header and expects HTTP 200;
- opens after three consecutive failed checks and recovers after one successful
  check, avoiding noise from the known few-second in-place deploy restart;
- is owned by the project team, tagged to `production`, and attaches the
  existing high-priority email workflow;
- disables failed-response capture so health bodies/headers are not retained.

The proxy bypasses owner Basic Auth only for this exact monitor path. The app
then compares the dedicated token in constant time and returns a minimal
`{"ok":true|false}` body. That token authorizes no mutable API and must never be
the broad owner credential. Its non-secret owners are the 1Password item
`PlaceIntel Sentry Uptime Monitor Token`, the private-repository GitHub Actions
secret `PLACEINTEL_MONITOR_TOKEN`, and the production environment variable of
the same name.

The owner token for the destructive/global routes follows the same rule and the
same shape. Its non-secret owners are the 1Password item `PlaceIntel Owner
Token` in the `Agent Automation` vault, the private-repository GitHub Actions
secret `PLACEINTEL_OWNER_TOKEN`, and the production environment variable of the
same name. It is deliberately unrelated to the shared proxy credential: guests
receive the proxy password and never this token. Rotate it by updating those
three owners together; the deploy fails closed if the secret is absent, and the
routes refuse rather than open if the variable is missing.

### Paid-fallback permission (`PLACEINTEL_ALLOW_SERPAPI`)

Scraping has a free primary path (gosom in Docker for discovery, the vendored
review scraper for reviews) and a billable SerpAPI fallback. Production pins the
permission to `0` from the deploy env file, so a free-path failure raises a
clean refusal instead of spending credits nobody authorized. This is not a
capability the app lacks — the box is provisioned for the free lane by
`deploy/remote-bootstrap.sh` (docker group membership, `google-chrome`, the
vendored scraper venv), so a fallback there means something broke and needs
fixing, not paying around.

Deliberately environment-owned rather than request-owned: the proxy credential
is shared with guests, so anything a request could set, a guest could spend.
Flip it for a deploy by setting the repository **variable** (not secret)
`PLACEINTEL_ALLOW_SERPAPI=1` and re-running the workflow; the value is
non-secret and the System panel shows the resolved policy and its source.

Verify after any deploy:

```bash
.venv/bin/placeintel spend --format json
.venv/bin/placeintel doctor --json   # check the spend_policy entry
```

Never put the public URL, any credential value, or Sentry API token in tracked
files, commands, receipts, screenshots, or incident notes. Sentry detector API
responses contain configured header values: query only an allow-list of detector
fields and header names; do not print raw detector JSON.

This is a service-path readiness check: it covers DNS, TLS, proxy routing,
process reachability, SQLite migration/open, data-dir writability, and static
shell presence. It does not prove model providers, scrapers, Docker, or an
end-to-end Scout/Shop customer journey; those stay behind deep diagnostics and
intentional release/E2E checks.

Triage order:

1. Use the Sentry issue/detector id as the canonical incident identity. Record
   its state as open, acknowledged, mitigated, or resolved; do not create a
   parallel free-text incident id.
2. Run the authenticated `placeintel deploy-smoke` against loopback or the
   approved tunnel to separate app health from proxy/DNS/TLS health.
3. Query recent service evidence without dumping normal traffic:

   ```bash
   journalctl -u placeintel.service --since "30 minutes ago" \
     -p warning..alert --no-pager
   ```

4. Use `/api/jobs/{job_id}` and its event stream for a named failed job. Keep
   scraped review text and request payloads out of Sentry comments.
5. Acknowledge only after an owner begins work. Resolve only after cheap health,
   exact-version `deploy-smoke`, and the Sentry detector all recover. Reopen the
   same incident for the same unresolved cause; create a new incident for a
   later regression after a proven recovery.

Sentry sends nothing for local runs unless `SENTRY_DSN` is present. Production
request bodies and frame locals are disabled. The outbound callback drops user,
extra, message, exception-value, breadcrumb-message/data, span-description/data,
and request URL/header/body fields while retaining route, exception type,
sanitized stack-frame metadata, trace ids, timings, release, and environment.
Common credential forms and private home paths are redacted defensively;
default PII remains off and trace sampling defaults to `0.1`.

There is no permanent crash endpoint. Verify error delivery with a one-off,
dummy-only exception from the production shell, confirm its exact Sentry event,
then remove the test issue. Never attach customer input to verification events.

## System Panel and Safe Config

The web footer has a compact `系统 System` panel backed by `GET /api/config`.
It is read-only and public-safe:

- shows app version, reasoning model, translation model, default answer
  language, evidence language, cache TTL, and provider labels.
- shows data-dir status as configured/hidden without exposing the local path.
- links to `/api/health` and `/api/health/deep`.
- shows setup-required state per feature, so missing live credentials degrade
  only the affected capability.
- keeps dangerous cache/restore actions out of the web panel. Use
  `placeintel backup` / `placeintel restore --yes` for destructive workflows.

## Deep Diagnostics

Deep diagnostics are opt-in because they may spend provider credits or touch
external tools.

CLI:

```bash
.venv/bin/placeintel doctor --live --json
```

HTTP:

```bash
curl -fsS http://127.0.0.1:9618/api/health/deep
```

Deep diagnostics check:

- reasoning provider/model ping.
- embedding provider ping.
- translation model availability.
- Chrome availability.
- Docker daemon and gosom image availability.
- review scraper vendor path.
- optional SerpAPI fallback.

Use `--require` in CLI when a missing external wheel should fail the command:

```bash
.venv/bin/placeintel doctor --live --json --require google,vectorengine,chrome,docker
```

## Durable Jobs

Scout and Shop jobs are persisted in SQLite:

- `jobs` stores `job_id`, kind, status, request, result/error, process id, and
  timestamps.
- `job_events` stores append-only pipeline events with the existing
  `{t, stage, msg, data?}` contract.
- `GET /api/jobs/{job_id}` reads SQLite, so page reloads do not lose known job
  state.
- `GET /api/jobs/{job_id}/events?after=N` streams Server-Sent Events from
  durable `job_events`; `Last-Event-ID` is also accepted for browser resume.
- The web UI uses `EventSource` first and falls back to `/api/jobs/{job_id}`
  polling, so live progress works without making polling the only path.
- On web-server startup, old `running` jobs from another process are marked
  `interrupted` with a retry hint.
- The web UI shows interrupted jobs with a `用缓存重试` action that resubmits the
  same request with `refresh:false`, so completed cached work is reused.

## Local Verification

Cheap smoke:

```bash
.venv/bin/python -c "import placeintel.cli"
.venv/bin/placeintel profiles
.venv/bin/placeintel doctor --json
.venv/bin/python -m unittest tests.test_doctor_contract -v
```

Full local gate before a release claim:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --check web/jobs.js
node --check web/app.js
npm run test:web
.venv/bin/python -m compileall placeintel
git diff --check
```

Run the full Scout E2E only when pipeline or scraper behavior changed; it can
take minutes and adds scraping load.

## Deployment Smoke

Protected deployment should prove the running service matches the intended build.
Use the CLI smoke against the authenticated service URL or an SSH tunnel:

```bash
EXPECTED_VERSION=$(.venv/bin/python -c "import placeintel; print(placeintel.__version__)")
.venv/bin/placeintel deploy-smoke \
  --base-url "http://127.0.0.1:9618" \
  --expected-version "$EXPECTED_VERSION" \
  --format json
```

The smoke is read-only and verifies:

- `GET /api/meta` returns the expected app version.
- `GET /api/health` reports `ok:true`.
- `/` includes the versioned `app.js` entrypoint for the expected build; cheap
  doctor separately proves every linked local CSS/JS asset exists and is within
  the line budget.
- `GET /api/places` loads the Library data shape.
- `GET /api/places/{place_id}` opens one cached dossier when the Library is not
  empty.

When a protected public domain exists, pass the public URL without credentials to
prove unauthenticated access is rejected by the proxy:

```bash
EXPECTED_VERSION=$(.venv/bin/python -c "import placeintel; print(placeintel.__version__)")
.venv/bin/placeintel deploy-smoke \
  --base-url "http://127.0.0.1:9618" \
  --public-url "https://PLACEHOLDER_PROTECTED_DOMAIN" \
  --expected-version "$EXPECTED_VERSION" \
  --format json
```

`public_auth` passes only for HTTP `401` or `403`. A failure exits with code `3`
and prints a standard JSON error envelope with `deploy_smoke_failed`.

Post-deploy human checklist:

1. Confirm the service is loopback-only behind the protected proxy.
2. Run `placeintel deploy-smoke` against the authenticated or tunneled service.
3. If a public domain exists, include `--public-url` to prove Basic Auth/proxy
   rejection for unauthenticated traffic.
4. Check service logs for new error spikes after the smoke.
5. Keep real URLs, hosts, paths, Basic Auth users/passwords, and credentials in
   deployment secrets or local gitignored files.

Public-safe deployment surfaces:

| Surface | Purpose | Secret handling |
| --- | --- | --- |
| local | development and verification on `127.0.0.1:9618` | `.env` / shell env |
| private VPS | native systemd service on loopback | GitHub Secrets + remote `.env` |
| protected domain | authenticated browser access | proxy auth outside repo |
| public mirror | code-only repository | no deploy/runtime secrets |

## Private Google Takeout Saved-Place Import

Use Google's narrow Takeout route:

<https://takeout.google.com/settings/takeout/custom/save,local_actions>

Select the intended account, keep `Saved` and `Maps (your places)` selected,
choose a one-time ZIP export, and deliberately press **Create export** only when
ready. Download the completed archive to a private path outside this repository.
The import itself needs no Google OAuth client, API key, Docker, browser, or AI:

```bash
.venv/bin/placeintel saved-import "/private/path/takeout.zip" --source-label account-a --format json
.venv/bin/placeintel saved-inventory --source-label account-a --format json
```

Operational rules:

- Do not extract the archive just to import it. CSV rows are iterated directly;
  GeoJSON is held one bounded member at a time after archive-path validation.
- Do not place Takeout data under git. Common `Takeout/`, `takeout-*.zip`, and
  `private-imports/` paths are ignored as a secondary guardrail.
- First reconcile inventory counts and repeat the same import once; the second
  result must show zero newly created collections, items, and memberships.
- Use a distinct opaque `--source-label` for each account; do not put email
  addresses into CLI arguments, receipts, logs, or documentation. The label
  scopes same-named collections but preserves deduplicated logical items.
- To scope an existing unlabelled real import without copying its memberships,
  rerun its exact archive with `--source-label <alias> --adopt-unlabeled`.
  Every prior source-file digest must match or the operation fails atomically.
- Some current localized Takeout exports do not retain the English
  `Saved Places` filename. The importer accepts only the strict saved-place
  point schema and rejects the adjacent review GeoJSON; do not rename or
  extract files merely to make filenames match.
- Record the JSON `skipped` count with the import receipt. It covers only blank
  or tag-only source placeholders with no place identity; rows with other
  orphaned content still fail atomically for operator review.
- Raw exports are not deployed. The SQLite database is the durable application
  owner and is already covered by the normal backup/restore path.
- Import never edits, deletes, shares, or reorganizes Google Maps lists.

### Protected VPS synchronization

When the private VPS needs the saved-place corpus, deploy the importer code
from the private repository first, then run the same CLI import on the
protected host. Do **not** commit an archive, copy the local `data/` directory,
or use a full-database restore merely to add saved places: that could replace
unrelated cached dossiers, jobs, and settings.

1. Verify the deployed app version with `placeintel deploy-smoke`.
2. Create a remote `placeintel backup --format json` before changing data.
3. Stage the two private ZIPs only in a permission-restricted temporary memory
   directory on the host. Use opaque source labels, run `saved-import` once
   per archive, then remove both ZIPs and the temporary directory in an
   `EXIT` cleanup path.
4. Repeat each exact import once; every created collection, item, and
   membership count must be zero on the replay.
5. Reconcile per-source and aggregate `saved-inventory` counts, run the cheap
   doctor, re-run deployment smoke, and assert no temporary ZIP remains.

This transfer is a protected operational data sync, not a deployment artifact:
the private repository and public code mirror must continue to exclude Takeout
archives and runtime `data/` files.

Input limits are configuration-driven and validated as positive integers:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `PLACEINTEL_SAVED_IMPORT_MAX_FILES` | `5000` | files inspected in a directory/ZIP |
| `PLACEINTEL_SAVED_IMPORT_MAX_ROWS` | `250000` | saved rows accepted per import |
| `PLACEINTEL_SAVED_IMPORT_MAX_FILE_MB` | `25` | uncompressed bytes for one supported member |
| `PLACEINTEL_SAVED_IMPORT_MAX_TOTAL_MB` | `1024` | total uncompressed bytes inspected |

Change these only in `.env` or the runtime secret/config owner; do not edit
parser code for one archive.

Reference schemas: [Saved CSV](https://developers.google.com/data-portability/schema-reference/save)
and [Maps (your places) starred GeoJSON](https://developers.google.com/data-portability/schema-reference/local_actions).

## Backup and Restore Status

First-class backup/restore is implemented through the CLI. Backups are
allow-list based and do not scan/copy `.env`, provider keys, logs, or arbitrary
project files.

Create a backup:

```bash
.venv/bin/placeintel backup --format json
```

Default destination:

```text
data/backups/placeintel-backup-<UTC>/
```

Included when present:

- `placeintel.db` through SQLite's online backup API.
- `scraper_pro_reviews.db` through SQLite's online backup API.
- `settings.json` (non-secret preferences only).
- generated `reports/`.

Each package has `manifest.json` with relative paths, file sizes, and SHA-256
hashes. Restore accepts either the backup directory or the manifest path:

```bash
.venv/bin/placeintel restore data/backups/placeintel-backup-YYYYMMDDTHHMMSSZ/manifest.json --yes --format json
```

Restore behavior:

- Refuses to run without `--yes`.
- Refuses paths outside `data/backups` unless `--force` is supplied for a
  trusted backup.
- Verifies file sizes, SHA-256 hashes, and required `placeintel.db` tables before
  replacing runtime files.
- Restores databases from the manifest package and removes stale SQLite
  `-wal`/`-shm` sidecars for those restored DB files.
- Verifies manifest hashes before replacing files.
- Validates the restored `placeintel.db` schema before and after restore.
- Replaces generated `reports/` atomically via a temporary directory.

## Favorite Refresh

Favorite refresh is manual/CLI-first in this release. There is no background
daemon yet, and newly favorited places are **not** refresh-enabled by default.

Mark a cached place as a favorite:

```bash
.venv/bin/placeintel favorite "<place_id>" --format json
```

Opt it into refresh candidates:

```bash
.venv/bin/placeintel favorite "<place_id>" --refresh-enabled --max-reviews 300 --format json
```

Preview due refresh work:

```bash
.venv/bin/placeintel refresh-favorites --dry-run --format json
```

Run due opt-in favorites manually:

```bash
.venv/bin/placeintel refresh-favorites --run --format ndjson
```

## Re-acquiring expired photo URLs

Provider place-photo URLs are time-limited tokens frozen at scrape time. They
rot after roughly a month, and nothing in the app re-resolves them. When
`photo_liveness` (deep health) reports few or no resolvable URLs, the fix is
re-acquisition, not a code change. A server-side image proxy does **not** help:
the server receives the same rejection the browser does.

Use `scripts/refresh_photos_bulk.py`, copied to the deploy directory and run
detached as the service user. It is idempotent (skips anything already
resolving) and resumable, and it logs to `data/photo-refresh.log`.

```bash
setsid nohup sudo -u placeintel -E .venv/bin/python refresh_photos_bulk.py 200 \
  > data/photo-refresh.out 2>&1 < /dev/null &
```

Two traps, both of which produce a confident green while doing nothing:

- **Do not pass `place_id` to `scout_single`.** It then reuses the cached row
  and skips discovery entirely, so the photo URLs are never re-issued. A run
  like that returns in about a tenth of a second, reports no error, and changes
  nothing. Re-acquisition must go by NAME.
- **`refresh-favorites --run` is not the tool for this.** It only processes
  places with `refresh_enabled`, which defaults to false, so it exits
  successfully having done nothing unless places were opted in first.

Cost shape, so the run is not mistaken for a hang: discovery is keyed by name
and refreshes every match it returns, so one query can restore a whole chain.
Measured on this library, roughly 4.6 minutes per query on the local gosom
scraper, which is free; SerpAPI is faster but spends the monthly quota. Back up
the database before a bulk run, and judge progress by completed `query` lines
in the log — a live process with a scraper container exiting `0` looks
identical to a stalled one for the first several minutes.

Thumbnails sourced from review images (`kind: "review"`) are not fixed by this
script; those need a review re-scrape, which is considerably more expensive.

Operational guardrails:

- `refresh_enabled` defaults to `false`.
- `refresh-favorites` defaults to dry-run unless `--run` is passed.
- Default run cap is 5 places and 300 reviews per place; per-favorite
  `max_reviews` can lower the cap.
- Cheap provider routing (`google` for embeddings, `vectorengine` for reasoning)
  is checked before run mode without exposing keys.
- Each attempted refresh writes a `favorite-refresh` row to search history before
  scraping starts, so operators can audit what was attempted.
- A failed place refresh records an error in the CLI result and keeps old
  places, reviews, reports, translations, and QA answers intact.

## Rollback

Target rollback time: under 60 seconds after a bad deploy is identified.

Generic rollback path:

1. Restore the previous deployed commit or directory snapshot.
2. Restart the service.
3. Run the deployment smoke against the restored loopback service:

   ```bash
   .venv/bin/placeintel deploy-smoke \
     --base-url "http://127.0.0.1:9618" \
     --expected-version "PREVIOUS_VERSION" \
     --format json
   ```

4. If a protected public URL exists, rerun the smoke with `--public-url` to
   confirm unauthenticated traffic is still rejected.
5. Check service logs before sending real users back to the restored process.

Do not roll back by editing `data/` or `vendor/` by hand.
