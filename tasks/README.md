# PlaceIntel PRD Router

Last Updated: 2026-06-20
Owner Surface: `tasks/` PRDs, `AGENTS.md`, `VAULT.md`, `progress.md`, `CHANGELOG.md`

This file is a navigation surface, not a second source of requirements. Keep detailed requirements inside the PRD files. Historical PRDs keep their legacy filenames to preserve links; new PRDs must use `YYYY-MM-DD - prd feature-slug.md` and pass `scripts/validate-prd-contract.sh`.

## Current PRDs

| PRD | Status | Created | Last Updated | Owner Surface | Next Action |
| --- | --- | --- | --- | --- | --- |
| [Agent-Readiness Governance](<2026-06-20 - prd agent-readiness-governance.md>) | Complete | 2026-06-20 | 2026-06-20 | PRD router, contract gate, agent docs | Use before PRD work; migrate legacy files only when reopened. |
| [Cached Report Translation](<2026-06-20 - prd cached-report-translation.md>) | Complete | 2026-06-20 | 2026-06-20 | `report_translations`, `/api/reports/translate`, dossier report switch | Preserve original report markdown; extend only through the cached display-translation contract. |
| [Dossier UX](prd-dossier-ux.md) | Complete | 2026-06-19 | 2026-06-19 | `web/dossier.js`, `web/app.js`, `web/app.css` | Historical owner record; preserve modal/lightbox regressions. |
| [Language Adaptation System](prd-placeintel-language-adaptation.md) | Implemented in v0.4.40 | 2026-06-15 | 2026-06-15 | `placeintel/language.py`, `web/i18n.js`, language cache fields | Historical owner record; if reopened, migrate or backfill acceptance checkboxes. |
| [Source Photos and Navigation Clarity](prd-placeintel-source-photos-navigation-clarity.md) | Complete | 2026-06-15 | 2026-06-15 | `placeintel/photos.py`, `web/app.js`, `web/app.css` | Historical owner record; preserve URL-only photo policy. |
| [World-Class UI/UX](prd-placeintel-world-class-ui-ux.md) | Complete | 2026-06-14 | 2026-06-15 | Web tabs, Library, dossier, Ask, Compare, Settings/System | Historical owner record; use before UI work. |
| [Agent-Friendly CLI and API](prd-placeintel-agent-cli-api.md) | Complete | 2026-06-14 | 2026-06-15 | CLI JSON/NDJSON, API docs, stable exit codes | Historical owner record; use before CLI/API changes. |
| [Production Operations Readiness](prd-placeintel-production-ops.md) | Complete | 2026-06-14 | 2026-06-14 | health, durable jobs, backup/restore, deploy-smoke | Historical owner record; use before operations changes. |
| [Production-Grade Master Plan](prd-placeintel-production-grade-master.md) | Complete | 2026-06-14 | 2026-06-15 | umbrella production roadmap | Historical umbrella; route to child PRDs first. |

## Validation

Use the legacy-aware audit while historical filenames remain:

```bash
scripts/validate-prd-contract.sh --allow-legacy .
```

Use strict mode only after legacy files are deliberately migrated:

```bash
scripts/validate-prd-contract.sh .
```
