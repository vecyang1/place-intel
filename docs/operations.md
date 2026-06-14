# placeintel Operations

Last updated: 2026-06-14

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
- `web/index.html`, `web/app.css`, and `web/app.js` exist and are under the
  AGENTS.md line budget.
- Provider/model labels are visible without exposing keys.

Cheap health does not call models, Chrome, Docker, scrapers, or SerpAPI.

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
node --check web/app.js
npm run test:web
.venv/bin/python -m compileall placeintel
git diff --check
```

Run the full Scout E2E only when pipeline or scraper behavior changed; it can
take minutes and adds scraping load.

## Deployment Smoke

Protected deployment should prove the running service matches the intended build:

1. Confirm the service is loopback-only behind the protected proxy.
2. Verify unauthenticated public access is rejected by the proxy.
3. Verify authenticated `GET /api/meta`.
4. Verify authenticated `GET /api/health`.
5. Verify one read-only UI flow: Library load or one cached dossier open.
6. Check service logs for new error spikes.

Keep real URLs, hosts, paths, and credentials in deployment secrets or local
gitignored files, not in public docs.

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

## Rollback

Target rollback time: under 60 seconds after a bad deploy is identified.

Generic rollback path:

1. Restore the previous deployed commit or directory snapshot.
2. Restart the service.
3. Run `/api/health`.
4. Run `/api/meta` and confirm the version.
5. Open one read-only UI flow.

Do not roll back by editing `data/` or `vendor/` by hand.
