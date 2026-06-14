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

First-class backup/restore commands are not implemented yet. Before destructive
manual work, back up the data directory with the app stopped or use SQLite's
safe backup mechanism.

PRD target:

- `placeintel backup --format json`
- backup manifest with file sizes and SHA-256 hashes.
- restore requiring explicit confirmation.
- temp DB round-trip test.

## Rollback

Target rollback time: under 60 seconds after a bad deploy is identified.

Generic rollback path:

1. Restore the previous deployed commit or directory snapshot.
2. Restart the service.
3. Run `/api/health`.
4. Run `/api/meta` and confirm the version.
5. Open one read-only UI flow.

Do not roll back by editing `data/` or `vendor/` by hand.
