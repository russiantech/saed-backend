# Changed / added / removed

## Removed
* **Modules** (model, API, UI) — lessons now belong directly to a course.
* **Course-level price** and any "pay for the whole course" flow.
* **Fast Track** (videos, payments, pages, dashboard stats).
* **Content-locking subscription / feature payments** and the trainer "settings" for it (history kept as `legacy_feature` payments).
* **"Free Preview" checkbox** — a lesson is free unless it is locked with a price.
* **Orientation Camp management UI** from Dunis Admin (camps still exist and drive In-Camp access; backend endpoints kept).
* Separate payment-callback pages per product (one `/app/payment/callback` now).
* Insecure SSL-verification bypass in the old Paystack client; debug CSRF endpoints; stale `.bak`/`_0` files.
* Bank/subaccount fields from the generic profile-update API (they bypassed verification).

## Added
* **Unified `Payment` ledger** (trainer activation, video upload fee, lesson access, legacy) with statuses pending/success/failed/abandoned/mismatch/refunded.
* **Paystack**: server-side verification, `requested_amount` comparison, signed + idempotent webhook, subaccounts, split payments, bank list + account-name resolution.
* **Premium lessons**: pay with Paystack or bank transfer; trainer confirms/grants/revokes; Dunis access-activity report.
* **Video upload fee** (default ₦2,000, once per lesson; Dunis Admin can change or disable).
* **Private file storage** + signed, expiring, entitlement-checked streaming (Range support); in-app video/PDF/text viewers.
* **UUID course URLs** (legacy integer ids still resolve).
* **Catalogue** with filters (text, skill, type, state, LGA, trainer), newest first, paginated; **In-Camp SAED** section; **My Enrollments** with progress.
* **Trainer discovery** with no default filters; optional name/skill/state/LGA/PPA/location filters.
* **Trainer Earnings** page (summary, payments, payout bank account).
* **Dunis "Payments & Fees"**: fee settings, payments monitor, mismatch review (approve/reject), trainer activation re-verify, lesson access activity.
* **Notifications with direct links** (in-app and email) — API now returns `link`.
* Role-specific, consolidated sidebars exactly as specified; legacy URLs redirect.

## Fixed
* **"Paid: 2548224, Expected: 2500000"** — Paystack's `amount` includes processing fees when the customer bears them. The server now verifies against the amount *we requested* (strict, no tolerance), alongside currency/reference/customer. Real differences become a `mismatch` flagged to Dunis Admin; a genuine success is never shown as failed, and the user is told "under review — you haven't lost your money".
* Video-fee bypasses (generic image upload, document-link slot, link schemes), free-lesson grants by admins, admin write access to other trainers' lessons, legacy-path file reads, race conditions on payment initialisation (found in independent review).

## Roles at a glance
| Role | Sidebar |
|---|---|
| Corps member | Dashboard, Courses, In-Camp SAED, My Enrollments, Trainers, Profile, Notifications |
| Trainer | Dashboard, My Courses, In-Camp Sessions, Corps Members, Earnings, Profile, Notifications |
| SAED Admin | Dashboard, Users, Courses, Enrollments, Profile, Notifications |
| Dunis Admin | SAED Admin items + Payments & Fees |

Dunis Admin has final authority on fees and disputed payments; SAED Admin keeps its existing roles (read-only on fees).


## v2.1.0 — tooling, production hardening and API docs
* **Frontend**: CRA/`react-scripts` removed → Vite 8, React 19, react-router 7, vitest, ESLint 10. `npm run dev` and `npm start` both work (also on Windows); `npm install` shows no deprecation warnings and `npm audit` reports 0 vulnerabilities. Env vars are `VITE_API_URL` / `VITE_BACKEND_URL`. `src/setupProxy.js` replaced by the Vite proxy.
* **Database**: `DATABASE_URL` (SQLite or PostgreSQL) via dj-database-url + psycopg 3; SQLite uses IMMEDIATE transactions. Full suite and legacy-data migration verified on both.
* **Settings**: environment-driven and secure by default (no insecure fallbacks, required secret/hosts, HTTPS/HSTS/secure cookies, password validators, whitenoise, structured logging, optional Redis cache).
* **Auth hardening**: throttling on login/signup/reset/verification endpoints; `/api/health/ready/` readiness probe.
* **API documentation**: OpenAPI 3.1 generated from the URLconf, Swagger UI `/api/docs/` (`/docs/`), ReDoc `/api/redoc/`, `/api/openapi.json`, `docs/API.md`, `manage.py export_openapi`; access via `API_DOCS=public|staff|off`.
* **Ops**: Dockerfiles, docker-compose (Postgres + Redis + gunicorn + nginx), nginx config, GitHub Actions CI (SQLite + PostgreSQL matrix).
* Tests: 114 backend (7 new API-doc tests), 9 frontend.


## v2.2.0 — in-app documents, letters, In-Camp consistency, branding, forms
* **Fix – admin "127.0.0.1 is blocked (ERR_BLOCKED_BY_RESPONSE)"**: the global `X-Frame-Options: DENY` blocked the letter in the admin's frame. Letters now stream through an authenticated endpoint that is frame-allowed only for the app origin.
* **Fix – trainer "Page not found … /media/partnership_letters/…"**: letters were public `/media/` URLs. They are now private, served via `/api/users/<id>/partnership-letter/`, with a clear "file missing – upload again" state when the file is not on disk. Migration `0005` + `move_partnership_letters` command.
* **Everything opens in-app**: new pdf.js-based `DocumentViewer`; no download/new-tab/print actions; Microsoft Office-online embed removed; lesson documents limited to PDF/TXT/images; external document links rejected; stream never serves `attachment`.
* **Letters**: upload, replace (old file deleted), preview before saving, inline admin review; the signup form now actually validates the letter.
* **In-Camp**: trainers get the same In-Camp SAED page as corps members (own courses); redundant "In-Camp Sessions" page and API removed.
* **Logo** in sidebar, public nav and all auth pages (`BrandLogo`, `VITE_LOGO_URL`, bundled fallback).
* **Forms/controls**: one consistent, responsive style system; fixed the dark-sidebar Logout contrast and the 5-column users table.
* Frontend now requires Node ≥ 22.13 (pdfjs-dist 6.5.438 – the first release without the 2026 arbitrary-JS-execution advisory).


## v2.5.0 — Streams; In-Camp and Post-Camp as separate programmes; production hardening  *(backend)*
**Features**
* `Stream` and `StreamMembership` models; camps and courses belong to streams; per-stream account life-cycle with live expiry (`403 stream_expired`), `deactivate_incamp` job and `POST /api/admin/run-stream-expiry/`.
* Strict tracks: `Profile.account_mode` is `in_camp` or `post_camp` (the old `both` is gone). Cross-track access returns 403; Post-Camp-only trainer discovery/earnings.
* Sign-up split: In-Camp needs `streamId`, no LGA/PPA; Post-Camp unchanged.
* Admin CRUD for In-Camp trainers (create, edit, reactivate, deactivate, invite, delete) with invite e-mail → password reset.
* Trainer proposals with admin approve/decline; per-stream reports and CSV export; users list filters by stream and programme.
* Migrations `0007` (schema) and `0008` (data) — see MIGRATION.md.

**Production / hosting fixes**
* **cPanel & older stacks:** `dj-database-url` 0.5.x (no `conn_health_checks`), SQLite `transaction_mode` only on Django ≥ 5.1, `postgresql_psycopg2` engine alias normalised, `STATICFILES_STORAGE` for Django < 4.2, scheme-less `CSRF_TRUSTED_ORIGINS` on Django 3.2. New `requirements-cpanel.txt` and `requirements-legacy.txt`; verified: all 204 tests pass on Python 3.13 + Django 4.2/5.2 and Python 3.11 + Django 3.2.
* `passenger_wsgi.py` for cPanel/Passenger; `/` now returns a JSON status page instead of a bare 404.
* API docs: pages derive their `openapi.json`/CSRF URLs from where they are served; bundled static files are served even without `collectstatic` (`WHITENOISE_USE_FINDERS`). `API_DOCS=staff` (production default) is documented as the cause of docs 404s.
* **Cross-site sign-in:** `CROSS_SITE_COOKIES`, `SESSION_COOKIE_DOMAIN`, `CSRF_COOKIE_DOMAIN`; start-up check `saed.W002` warns when the app and API are on different sites with `SameSite=Lax`; `saed.W001`/`W003` for missing `BACKEND_URL` / non-HTTPS app URL.
* `manage.py create_saed_admin` to bootstrap the first administrator.
* Docs: README, `DEPLOY-CPANEL.md`, `DEPLOYMENT.md`, `STREAMS.md`.

## v2.4.0 — In-Camp skill sets
* In-Camp SAED: new **Skill set** filter; corps members land on their own skill set first (matches ranked first across pages, badge on cards). Empty skill sets show "nothing listed currently" instead of a blank page, and corps members whose skill set has no courses can optionally explore all other courses. Same filter for trainers (no re-ordering). 7 new backend and 3 new frontend tests.

## v2.3.0 — fixes, performance, camps, branding
* **Fix – 500 on opening some courses** (`ImportError: session_payload`): leftover import from the removed training-sessions feature in the course detail view. Removed; regression test covers In-Camp course detail for every role.
* **Performance** (see README §5b): N+1 queries removed from trainers, dashboard, my-courses, In-Camp; correlated sub-select counts replace multi-join aggregates; indexes; JSON gzip; request de-duplication.
* **Frontend toolchain**: jsdom 27.4 – installs without `EBADENGINE` warnings on Node 22.13+ (engine ranges of every package verified against 22.13, 22.x and 24), 0 deprecated packages, 0 vulnerabilities.
* **Logo & favicon**: official NYSC emblem (transparent background) in sidebar, public nav and auth pages; full favicon set. Auth-page logos link to home.
* **Admin SAED Camps page** with add/edit/activate/delete and usage counts; camp API hardened (validation, duplicate and in-use protection).
