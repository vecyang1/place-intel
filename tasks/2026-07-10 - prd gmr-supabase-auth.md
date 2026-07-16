# PRD: GMR Supabase Auth

Created: 2026-07-10
Last Updated: 2026-07-10
Status: ⏸ Paused — credential-gated before production build
Feature Type: Full-stack auth and production operations feature
Owner: Codex
Deployment Profile: hybrid
Deploy Targets: local FastAPI web app on `127.0.0.1:9618`, protected GMR VPS/systemd lane, Supabase hosted Auth
Related PRDs:
- `tasks/prd-placeintel-production-ops.md`
- `tasks/prd-placeintel-agent-cli-api.md`
- `tasks/prd-placeintel-world-class-ui-ux.md`

## 1. Introduction

The production origin is currently protected at the proxy/browser layer with Basic Auth. Its real hostname stays in deployment secrets, not this public PRD. The PlaceIntel FastAPI app itself is still a single-user local/protected tool: `placeintel/server.py` has no login model, no session route, and no server-side JWT validation. This works for one operator, but it forces repeated browser credential prompts and gives the app no way to understand a signed-in person, enforce invite-only team access, or protect API routes if the proxy boundary changes.

This feature adds production invite-only Supabase Auth for a small friends/team audience. It must support email+password and Google login, verify Supabase JWTs server-side, protect all cost-bearing/private routes by default, and keep proxy Basic Auth in place until app auth, API protection, deploy smoke, authenticated browser/API proof, and rollback are verified.

## 2. Goals

- G1: Replace repeated browser Basic Auth prompts with app-level Supabase login for invited users.
- G2: Keep Basic Auth/proxy protection as a rollback boundary until Supabase auth is proven in production.
- G3: Protect all cost-bearing/private FastAPI routes by default while leaving only designed health/static routes public.
- G4: Support email+password, password reset/confirmation, and Google login when OAuth credentials are available.
- G5: Enforce small-team invite access through an allow-list or admin approval path.
- G6: Preserve PlaceIntel provider routing, durable jobs, report/review semantics, QA cache safety, cheap health, line budgets, and deploy-smoke contracts.
- G7: Document every env var, secret class, setup step, smoke test, and rollback path so future agents do not reconstruct the auth model from memory.

## 3. User Stories

### US-001: Credential and Project Gate

As the project owner, I want the build to verify access and stop cleanly when production auth credentials are missing so secrets are not guessed, leaked, or hardcoded.

Acceptance Criteria:
- [ ] First-action audit records current auth boundary, Supabase org/project counts, and missing credential classes without printing secrets.
- [ ] Supabase Management API access is verified with metadata only.
- [ ] GitHub Secrets and 1Password are searched for secret classes without printing values.
- [ ] The build stops before production Supabase/Google/SMTP configuration if Google OAuth client credentials, SMTP/Resend API key, Cloudflare API token/browser access, or Supabase project/JWT values are unavailable.
- [ ] Typecheck/lint passes.

### US-002: Supabase Project and Auth Configuration

As an operator, I want a dedicated GMR Supabase project configured with correct Auth URLs so production and local login redirects work predictably.

Acceptance Criteria:
- [ ] A GMR Supabase project exists in a separate organization if Management API, quota, and billing rules permit.
- [ ] Safe Auth config shows `site_url` for the production GMR domain.
- [ ] Redirect allow-list includes production and localhost loopback development URLs with scheme-qualified wildcard paths.
- [ ] Email+password is enabled with production email confirmation policy.
- [ ] Custom SMTP is configured only when a Resend/SMTP key and verified sender/domain are available.
- [ ] Google provider is configured only when OAuth client ID/secret and redirect URI are available.
- [ ] No service-role key, OAuth secret, SMTP key, deploy path, VPS name, proxy credential, or private URL appears in tracked files, chat, test logs, or docs.
- [ ] Typecheck/lint passes.

### US-003: Server-Side Auth Boundary

As a signed-in team member, I want private/cost-bearing API actions to require my Supabase session so an unauthenticated visitor cannot spend provider credits or inspect cached intelligence.

Acceptance Criteria:
- [ ] FastAPI verifies Supabase JWTs server-side using the project JWKS or equivalent safe verification path.
- [ ] Public routes are explicitly allow-listed: `/`, `/static/*`, cheap public auth metadata if needed, and designed health/meta endpoints.
- [ ] Cost-bearing/private routes require auth by default, including Scout, Shop, Ask, translation, Library, reports, settings, favorites, and destructive cache actions.
- [ ] Local development remains usable through an explicit non-production bypass env, defaulting to safe behavior in production.
- [ ] Auth failures return stable 401/403 JSON errors without leaking config or stack traces.
- [ ] Durable job creation, SSE replay, QA cache freshness, report translation, and review translation keep their existing contracts.
- [ ] Typecheck/lint passes.

### US-004: Invite-Only Team Access

As the owner, I want only invited friends/team members to use GMR so the tool stays private even though login is user-friendly.

Acceptance Criteria:
- [ ] Invite access is enforced by allow-listed emails or an admin approval flow.
- [ ] Unknown/self-signup users are blocked from private routes until approved.
- [ ] Admin/system settings are admin-only if roles are implemented in this phase.
- [ ] The first owner/admin bootstrap path is documented and does not require storing a human password.
- [ ] Disposable auth test users are cleaned up or clearly isolated.
- [ ] Typecheck/lint passes.

### US-005: Web Login Experience

As an invited user, I want a polished login screen with email+password and Google login so I can enter GMR without a browser credential pop-up.

Acceptance Criteria:
- [ ] The no-build SPA includes a login/session module instead of bloating `web/app.js`, `web/app.css`, or `web/i18n.js` over 800 lines.
- [ ] The UI supports email+password sign-in, reset/confirmation handling, Google sign-in button, signed-in identity, logout, and friendly auth errors.
- [ ] Signed-out users cannot see app data before authentication.
- [ ] Session refresh/logout update the UI without a full reload where practical.
- [ ] The login UI is responsive, accessible, and visually consistent with the existing app shell.
- [ ] Visual verification via browser preview/Playwright passes.
- [ ] Typecheck/lint passes.

### US-006: Deploy, Smoke, and Cutover

As the operator, I want proof that Supabase auth works in production before Basic Auth is removed, plus a rollback that restores the old boundary quickly.

Acceptance Criteria:
- [ ] Loopback `placeintel deploy-smoke` passes.
- [ ] Private GMR deploy and authenticated API/browser smoke pass.
- [ ] Public unauthenticated URL exposes no app content.
- [ ] Public authenticated browser/API flow works without credential leakage.
- [ ] Cutover keeps proxy Basic Auth until all proof gates are green.
- [ ] Rollback to proxy-only protection is documented and works in under 60 seconds.
- [ ] Typecheck/lint passes.

## 4. Functional Requirements

- FR-001: Add a single backend auth owner module or section that resolves auth mode from env and validates Supabase JWTs server-side.
- FR-002: Add explicit public-route allow-listing; all other `/api/*` routes are private by default unless intentionally documented as public.
- FR-003: Auth config must support production required mode and local explicit bypass mode; bypass must not be the production default.
- FR-004: Add stable auth metadata endpoint exposing only non-secret fields needed by the browser: auth mode, Supabase URL, anon/publishable key if configured, enabled providers, and current session requirement.
- FR-005: Add `/api/auth/session` or equivalent endpoint that validates the current bearer token and returns safe identity/role metadata.
- FR-006: Add logout/session refresh behavior compatible with Supabase Auth client sessions.
- FR-007: Enforce invite-only access through a server-side allow-list, Supabase metadata/role, or approval table; do not rely on hiding the UI.
- FR-008: Admin-only operations must check server-side role/claim if roles are introduced.
- FR-009: JWT verification must reject expired, malformed, wrong-project, wrong-audience, and unapproved-user tokens.
- FR-010: Auth errors must return a safe JSON envelope and never include keys, tokens, raw JWTs, OAuth secrets, SMTP secrets, local paths, VPS names, or Basic Auth values.
- FR-011: The web app must centralize authenticated `fetch` behavior so all existing API callers inherit bearer-token handling.
- FR-012: The web app must render signed-out, loading, signed-in, reset, and error states without showing private cached data.
- FR-013: Supabase Auth Management API changes must be partial PATCHes based on read-before-write config so redirect allow-lists are not clobbered.
- FR-014: `.env.example` must document every auth env var with placeholders only.
- FR-015: `docs/API.md` must document public/private route policy, auth headers, session endpoint, and error codes.
- FR-016: `docs/operations.md` must document setup, GitHub/VPS secret names, deploy-smoke, public unauth rejection, authenticated smoke, and rollback.
- FR-017: `placeintel deploy-smoke` must support proving unauthenticated public rejection and authenticated/private app readiness without printing credentials.
- FR-018: Tests must cover auth bypass, required-auth rejection, valid JWT acceptance, invite rejection, public route allow-listing, and web login/session UI.

## 5. Non-Goals

- Do not remove proxy Basic Auth until app-level auth and rollback are proven.
- Do not implement a public SaaS signup flow; this is invite-only for a small team.
- Do not store user passwords in PlaceIntel or create passwords on behalf of users.
- Do not put service-role, OAuth, SMTP, or deploy secrets in browser JavaScript, tracked docs, test fixtures, logs, or chat.
- Do not move provider routing away from Google official embeddings and VectorEngine reasoning.
- Do not change scraper/review/report semantics, durable job storage, QA cache freshness, or cheap health behavior except for auth protection.
- Do not introduce a frontend build pipeline.

## 6. Stack and Dependencies

### 6.1 Existing Stack

PlaceIntel is Python/FastAPI + SQLite + no-build vanilla JavaScript. The web shell is bounded by `AGENTS.md`: `web/index.html`, `web/app.css`, `web/app.js`, and `web/i18n.js` must each remain under 800 lines. At audit time, `web/app.css` is already 799 lines and `web/app.js` is 780 lines, so auth UI must be added through a small new module/style file or a deliberate split rather than by growing those files.

### 6.2 Backend Decision

Supabase is the correct auth provider for this feature because the user explicitly chose app-level auth with email+password and Google login, the audience is a small invited team, and Supabase Auth provides email confirmation/reset and OAuth without PlaceIntel owning password storage. PlaceIntel keeps its existing SQLite data/cache; Supabase is used for identity and auth configuration, not as the primary application database in this phase.

### 6.3 Dependencies

| Dependency | Version | Purpose | Declared In | Decision |
| --- | --- | --- | --- | --- |
| Supabase Auth hosted service | Managed | Email+password, Google OAuth, JWT issuer/JWKS | Supabase project config | Use |
| Supabase Management API | v1 REST | Site URL, redirect allow-list, SMTP/provider config | ops scripts/runbook | Use |
| Supabase JS Auth client | Version selected during implementation | Browser login/session management | likely `web/` vendored CDN/module or no-build script tag | Evaluate before code; keep no-build |
| Python JWT/JWKS verification library | Version selected during implementation | Server-side JWT verification | `pyproject.toml` if needed | Evaluate before code; avoid hand-rolled crypto |
| Resend/custom SMTP | Managed | Auth confirmation/reset email deliverability | Supabase Auth config | Use only when key/domain available |

Rejected alternatives:

| Alternative | Decision | Reason |
| --- | --- | --- |
| Keep only proxy Basic Auth | Reject | Solves privacy but not user-friendly sessions, Google login, invite roles, or API awareness. |
| Build password auth in PlaceIntel | Reject | Unnecessary password storage and reset/email burden. |
| Cloudflare Access only | Defer | Good perimeter auth but less app-native for invite roles/session UI; could remain as outer layer. |
| Move all app data to Supabase Postgres | Reject for this phase | Larger migration, unrelated to replacing the credential pop-up. |

## 7. Safety and Security

### 7.1 Current-State Audit

| Fact | Evidence |
| --- | --- |
| Current app auth boundary | `placeintel/server.py` states single-user local tool with no auth; production docs describe protected proxy Basic Auth. |
| Supabase account state | Earlier metadata audit returned 2 organizations and 6 projects: 1 active healthy, 5 inactive. A fresh 2026-07-10 audit now gets HTTP 403 from the only local PAT for Management API org/project endpoints, so usable Management access must be restored or replaced before production config. |
| GitHub secret state | The private deploy repository has deploy/provider secrets but no Supabase, Google OAuth, SMTP/Resend, or Cloudflare API-token secret names. |
| 1Password state | Earlier metadata found Supabase, Resend, and Cloudflare/dashboard login items. A fresh bridge audit cannot verify them because the 1Password account is not signed in from the Terminal Bridge. |
| Local tool state | Supabase CLI is not installed; the local PAT location exists but currently lacks usable Management API access. |

### 7.2 Zero-Regression Contract

| Existing Feature | Likely Files Touched | Risk Level | Verification Method | Automated? |
| --- | --- | --- | --- | --- |
| FastAPI route access and API contracts | `placeintel/server.py`, new auth helper, `tests/test_server_contract.py` | High, because auth wraps most API routes | New server auth tests plus full unittest discovery | Yes |
| Durable Scout/Shop jobs and SSE | `start_scout`, `start_shop`, `job_status`, `job_events` | Medium/high | `tests/test_durable_jobs.py`, server auth tests for bearer access | Yes |
| Ask/QA cache safety | `/api/ask`, `/api/qa`, `pipeline.ask` unchanged | Medium | `tests/test_ask_evidence_contract.py`, auth route tests | Yes |
| Review/report translation | translate endpoints and dossier UI | Medium | `tests/test_review_translation.py`, Playwright translation tests | Yes |
| Web no-build shell | `web/index.html`, `web/app.js`, `web/dossier.js`, new auth JS/CSS | High UI risk, line-budget risk | `tests/test_web_static_contract.py`, `npm run test:web`, browser visual proof | Yes |
| Deploy smoke and proxy boundary | `placeintel/deploy_smoke.py`, `docs/operations.md` | High production risk | `tests/test_deploy_smoke.py`, loopback/private/public smoke | Yes |
| Cheap health stays cheap | `/api/health`, `doctor.cheap_health` | Medium | `tests/test_doctor_contract.py` | Yes |

Before editing functions/classes/methods, run GitNexus impact for the exact target and warn if impact is HIGH/CRITICAL.

### 7.3 Security Hardening

| Attack Surface | Threat | Impact | Mitigation | Verification |
| --- | --- | --- | --- | --- |
| Browser token storage | Token theft/XSS | Full user session compromise | Use Supabase client storage pattern; keep service-role out of browser; preserve escaping of scraped data | Playwright XSS/login regression |
| API bearer token | Forged/expired/wrong-project JWT | Unauthorized API use and provider spend | Server-side JWT verification against configured project/JWKS/audience | Unit tests with invalid/expired/wrong tokens |
| Invite policy | Unknown user self-signup | Private app exposure | Server-side allow-list/approval check after JWT validation | Invite rejection tests |
| Route allow-list | Accidentally public cost route | Provider spend/cache exposure | Private-by-default middleware with explicit public route table | Route matrix tests |
| Supabase config writes | Clobbered redirect list or insecure auto-confirm | Broken login or unverified access | Read-before-write Management API, patch only intended fields, keep production confirmation policy | Safe config readback |
| Logs/errors | Secret leakage | Credential exposure | Redact tokens/secrets, never print Management PAT/project keys/OAuth/SMTP values | Grep/diff review |
| Cutover | Removing Basic Auth too early | Public unauthenticated exposure | Gate cutover on app-auth smoke, public unauth rejection, rollback proof | Deploy-smoke |

### 7.4 Error Boundaries

| Component | Failure Mode | User Experience | Recovery | Logging |
| --- | --- | --- | --- | --- |
| Supabase config missing | Production auth required but env incomplete | Startup or auth metadata returns actionable setup-required state; private routes reject | Add required secrets/env and restart | Safe config error without values |
| JWT verification | Expired/invalid token | Login screen asks user to sign in again | Refresh session or re-login | 401 reason class only |
| Invite rejection | Valid Supabase user not approved | Friendly "not invited yet" state | Owner approves email/role | 403 with user id/email masked or omitted in logs |
| Google OAuth not configured | User clicks Google login | Button hidden/disabled with setup message | Configure OAuth and Supabase provider | Non-secret provider status |
| SMTP missing/rate-limited | Confirmation/reset email cannot send | Email sign-up/reset disabled or warned until custom SMTP configured | Configure Resend/SMTP or manual invite/bootstrap | Management/Auth error class |
| Supabase outage | Auth calls fail | Existing page stays safe; private actions blocked | Retry after service recovers | Error class and endpoint, no token |

## 8. Architecture

### 8.1 Route Policy

Default: authenticated unless explicitly public.

Public candidates:
- `GET /`
- `GET /static/*`
- `GET /api/health`
- `GET /api/meta` if it remains non-secret
- `GET /api/auth/config` or equivalent non-secret auth metadata

Private candidates:
- all cost-bearing routes: Scout, Shop, Ask, translations, model switch
- all cached intelligence routes: places, reports, searches, QA history
- all mutations: delete, favorite, settings, language defaults
- durable job status/events unless the job was created by the same authenticated user or the deployment accepts single-team visibility

### 8.2 Auth Flow

1. Browser loads public shell and auth metadata.
2. If auth is required and no Supabase session exists, private app content stays hidden and login UI appears.
3. User signs in through email+password or Google OAuth.
4. Browser attaches `Authorization: Bearer <access_token>` through the centralized API wrapper.
5. FastAPI verifies JWT, checks invite/role, and attaches safe identity to request state.
6. Private handlers run unchanged business logic after auth passes.
7. Logout clears Supabase session and private UI state.

### 8.3 Data Ownership

Supabase owns identity, OAuth, email confirmation/reset, and user auth metadata. PlaceIntel owns cached places, reviews, reports, settings, jobs, and QA data in SQLite. Invite access can start as an env allow-list and later move to a Supabase table/profile if admin roles require runtime edits.

## 9. Design System

Use the existing operational app aesthetic: dense, calm, work-focused, no landing page. The login screen is the first usable screen when signed out; it should feel like a secure workspace entry, not marketing. Use compact form controls, clear labels, visible error/recovery states, and an icon+text Google button. The signed-in identity and logout action should live in the existing top/footer system area without crowding core Scout/Shop/Library/Ask workflows.

Because `web/app.css` and `web/app.js` are near the 800-line cap, implementation should add `web/auth.js` and a small `web/auth.css` or split existing CSS intentionally. Do not put cards inside cards; do not add decorative blobs/orbs.

## 10. Responsiveness and Accessibility

- Login and reset states must fit at 360px mobile width and desktop without text overlap.
- Forms must have labels, focus states, keyboard submit, and `aria-live` error/status updates.
- Signed-out content must not rely on color alone to explain blocked access.
- Existing tab deep links, roving tab behavior, dossier focus trap, and skip link must remain intact.

## 11. Observability

- Auth metadata endpoint reports only non-secret setup state.
- Server logs auth failures by class, not token/user secret.
- Deploy-smoke reports private/auth/public gate status in JSON without credentials.
- Cheap health remains cheap and does not call Supabase, Google, SMTP, Chrome, Docker, or model providers.

## 12. Metrics

- Unauthenticated public route matrix passes.
- Authenticated route matrix passes.
- Login-to-Scout happy path works in browser.
- Password reset/confirmation links redirect to production/local allow-list URLs.
- Deploy rollback can restore proxy-only protection in under 60 seconds.

## 13. Implementation Principles

- TDD: write failing route/auth tests before production auth code.
- GitNexus: run impact before editing every function/class/method target.
- Config first: document env names before consuming them.
- Least privilege: browser gets only anon/publishable Supabase config, never service-role or Management PAT.
- Private by default: new API routes inherit auth unless explicitly public.
- Keep current business logic stable: auth wraps routes; it does not rewrite pipeline, cache, scraper, or provider code.
- No fake production: if OAuth/SMTP/Supabase project secrets are missing, mark blocked/gated instead of simulating completion.

## 14. Documentation Requirements

- `docs/API.md`: public/private route policy, bearer header, auth metadata/session endpoint, error codes.
- `docs/operations.md`: Supabase project setup, OAuth/SMTP setup, secret placement, smoke tests, cutover, rollback.
- `.env.example`: auth mode, Supabase URL/anon key/JWKS or JWT settings, invite allow-list, local bypass flag, OAuth/SMTP secret names as placeholders.
- `AGENTS.md`: auth contract if new route policy becomes a hard rule.
- `CHANGELOG.md` and `progress.md`: shipped changes and proof.
- `tasks/README.md`: PRD routing and current credential-gated status.

## 15. Open Questions and Credential Gates

Blocking credential classes found missing or not machine-confirmed on 2026-07-10:

| Class | Current Evidence | Needed Before Production |
| --- | --- | --- |
| Google OAuth client ID/secret | Not present in GitHub Secrets or 1Password metadata search | Create OAuth client for GMR/Supabase redirect URI and store secret securely |
| SMTP/Resend API key + verified sender/domain | Resend login metadata exists, but no stored value found | Add Resend/SMTP key and sender/domain for Supabase Auth emails |
| Cloudflare API token | Dashboard login exists; no API token secret found | Provide API token or permit logged-in browser configuration |
| Supabase project/JWT keys | Current PAT returns HTTP 403; dedicated GMR project not yet created/selected in this run | Restore Management API access or create/select project manually, then store anon/JWT/JWKS config and server-only secrets safely |

Recommended human action: create/provide the four credential classes above through 1Password or GitHub/VPS secret stores. Do not paste raw values into chat.

## 16. Verification Plan

Required final gate:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --check web/app.js web/dossier.js web/i18n.js web/auth.js
npm run test:web
.venv/bin/python -m compileall placeintel
scripts/validate-prd-contract.sh --allow-legacy .
git diff --check
```

Deployment proof:

```bash
.venv/bin/placeintel deploy-smoke --base-url "http://127.0.0.1:9618" --expected-version "$EXPECTED_VERSION" --format json
.venv/bin/placeintel deploy-smoke --base-url "$PRIVATE_OR_TUNNELED_URL" --public-url "$PLACEINTEL_PUBLIC_URL" --expected-version "$EXPECTED_VERSION" --format json
```

Authenticated browser/API proof must include: signed-out public URL reveals no app data; login succeeds; private route succeeds with bearer token; private route rejects without bearer token; logout blocks private data again.

## 17. Build Progress

- 2026-07-10: First-action audit completed. Current auth boundary is proxy Basic Auth only; FastAPI has no app auth. Earlier Supabase metadata showed 2 orgs and 6 projects, with 1 active healthy and 5 inactive; a later fresh audit gets HTTP 403 from the only local PAT, so Management access is not currently usable. GitHub Secrets lack Supabase/OAuth/SMTP/Cloudflare auth secrets. 1Password metadata cannot currently be reverified because the bridge account is not signed in. PRD created as credential-gated.

## 18. Deployment and Configuration

### 18.1 Environment Matrix

| Environment | Purpose | URL/Host | Who Uses It | Data Source | Secrets Source |
| --- | --- | --- | --- | --- | --- |
| local | development and tests | loopback `127.0.0.1:9618` | owner/agents | local SQLite data dir | `.env`, shell env, 1Password |
| staging/private tunnel | pre-cutover auth proof | loopback or authenticated tunnel | owner/agents | VPS SQLite data dir | GitHub Secrets + VPS env |
| production | protected GMR app | GMR domain behind proxy | invited friends/team | VPS SQLite data dir + Supabase Auth | GitHub Secrets, VPS env, Supabase project config |

### 18.2 Secrets Inventory

| Variable/Class | Description | Browser-visible? | Where to Store |
| --- | --- | --- | --- |
| Supabase URL | Project API/Auth URL | Yes | `.env`/GitHub/VPS env |
| Supabase anon/publishable key | Browser Supabase client key | Yes | `.env`/GitHub/VPS env |
| Supabase JWT/JWKS settings | Server verification config | No raw secrets if JWKS public | `.env`/GitHub/VPS env |
| Supabase service role | Admin-only server operations if ever needed | No | VPS env/secret manager only |
| Supabase Management PAT | Project config automation | No | local/1Password only, not app runtime |
| Invite allow-list | Approved emails/domains | No if private emails; maybe metadata only | VPS env or gitignored config |
| Google OAuth client secret | Google login provider | No | Supabase Auth config/1Password |
| SMTP/Resend key | Auth emails | No | Supabase Auth config/1Password |
| Cloudflare API token | DNS/proxy config automation | No | 1Password/GitHub secret if used |

### 18.3 Cutover Plan

1. Implement and verify app auth locally with explicit local bypass tests.
2. Configure Supabase Auth site URL, redirect allow-list, email policy, SMTP, and Google provider when credential gates are satisfied.
3. Deploy to private/protected GMR without removing proxy Basic Auth.
4. Run loopback deploy-smoke and private authenticated smoke.
5. Verify public unauthenticated access exposes no app content.
6. Verify browser login and authenticated API route access.
7. Only then consider removing or relaxing proxy Basic Auth.

### 18.4 Rollback

Rollback keeps proxy Basic Auth as the outer boundary. If app auth breaks after deploy, revert app code or disable production auth via the documented server env only while proxy Basic Auth remains active. Rollback target is under 60 seconds: restore prior service version or restart with previous env, then run `placeintel deploy-smoke` and public unauth rejection proof.

## Revision History

| Date | Version | Summary | Author |
| --- | --- | --- | --- |
| 2026-07-10 | v0.2 | Marked paused after repeated credential-gate audit: Supabase Management access, Google OAuth, SMTP/Resend, and Cloudflare/DNS/deploy classes remain unavailable or unverified. | Codex |
| 2026-07-10 | v0.1 | Initial credential-gated PRD for invite-only Supabase Auth. | Codex |
