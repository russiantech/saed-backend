# SAED API — backend (Django REST)

The server for the NYSC SAED learning platform: accounts, **streams**, In-Camp and Post-Camp courses, lessons, enrolment,
payments (Paystack), protected lesson media, partnership letters, notifications and reports.

This repository is **only the API**. The web app is a separate repository (`saed-frontend`) that talks to this API over HTTPS.

| | |
|---|---|
| Version | **2.5.0** (API contract version in `saed/apidocs/curated.py`) |
| Runtime | Python 3.10 – 3.13 · Django 5.2 (4.2 and 3.2 supported, see below) · Django REST Framework |
| Database | SQLite (development) or PostgreSQL 16 — one setting, `DATABASE_URL` |
| Auth | Cookie session + CSRF header (`X-CSRFToken`), no tokens in `localStorage` |
| Companion | `saed-frontend` ≥ 2.5.0 (see compatibility table) |

## Contents
1. [Quick start](#1-quick-start)
2. [Where it is deployed — pick one guide](#2-deployment-guides)
3. [Configuration reference](#3-configuration-reference)
4. [Two programmes, one API: In-Camp vs Post-Camp](#4-in-camp-vs-post-camp-streams)
5. [API documentation](#5-api-documentation)
6. [Supported stacks](#6-supported-stacks)
7. [Tests and CI](#7-tests-and-ci)
8. [Project layout](#8-project-layout)
9. [Compatibility with the frontend](#9-compatibility-with-the-frontend)
10. [Troubleshooting](#10-troubleshooting)

## 1. Quick start
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                   # DJANGO_DEBUG=1 for local work
python manage.py migrate
python manage.py createsuperuser                       # optional, for /admin/
python manage.py runserver 127.0.0.1:8002
```
Open <http://127.0.0.1:8002/> — you should see a small JSON status page. Health: `/api/health/`. Docs: `/api/docs/`.
Run the web app from the frontend repo (`npm run dev`, <http://localhost:3002>); its dev server proxies `/api` to port 8002.

## 2. Deployment guides
| Where | Guide |
|---|---|
| **cPanel / shared hosting** ("Setup Python App", Passenger) | [`docs/DEPLOY-CPANEL.md`](docs/DEPLOY-CPANEL.md) |
| VPS / Docker / any Linux host (gunicorn + nginx, PostgreSQL) | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |

**The one rule that decides whether sign-in works in production:** the web app and the API must be on the **same site**
(for example `https://saed.example.com` and `https://saed-api.example.com`). If they are on unrelated domains, browsers
treat the session cookie as third-party and may drop it ("*Your sign-in session could not be established*").
The server warns about this at start-up (`python manage.py check --deploy`, warning `saed.W002`).
Details and the fallback (`CROSS_SITE_COOKIES=1`) are in `docs/DEPLOYMENT.md`.

## 3. Configuration reference
Everything is an environment variable (or a line in `.env`). With `DJANGO_DEBUG=0` the app refuses to start without
`DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`. A commented template is in `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_DEBUG` | `0` | `1` only for local development |
| `DJANGO_SECRET_KEY` | – | **required** in production |
| `DJANGO_ALLOWED_HOSTS` | – | **required** in production: the API's host name(s), comma separated |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | `postgres://user:pass@host:5432/db` for PostgreSQL |
| `FRONTEND_URL` | `http://localhost:3002` | public origin of the web app (CORS, CSRF, e-mail links, invite links) |
| `BACKEND_URL` | – | public origin of this API (media links, deployment checks) |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | `FRONTEND_URL` | comma separated origins incl. scheme |
| `CROSS_SITE_COOKIES` | `0` | `1` = `SameSite=None; Secure` cookies when app and API are on different sites (HTTPS only) |
| `SESSION_COOKIE_DOMAIN`, `CSRF_COOKIE_DOMAIN` | – | optional shared parent domain, e.g. `.example.com` |
| `SECURE_SSL_REDIRECT`, `USE_X_FORWARDED_PROTO`, `SECURE_HSTS_SECONDS`, `TRUSTED_PROXY_COUNT` | on in production | transport security behind a proxy |
| `API_DOCS` | `public` in DEBUG, `staff` in production | who may open `/api/docs/`: `public`, `staff` (others get 404) or `off` |
| `WHITENOISE_USE_FINDERS` | `1` | serve bundled static files (Swagger UI, admin CSS) even if `collectstatic` was not run |
| `REDIS_URL` | – | shared throttle counters for multi-worker deployments |
| `MEDIA_ROOT`, `PRIVATE_MEDIA_ROOT` | `./media`, `./protected_media` | public images / **private** lesson files (never expose the latter) |
| `SAED_MAX_VIDEO_BYTES`, `SAED_MAX_DOCUMENT_BYTES` | 500 MB / 100 MB | upload limits |
| `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` | – | Paystack (use `sk_live_`/`pk_live_` in production) |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console in DEBUG | outgoing mail (verification, invites, notifications) |
| `AUTH_THROTTLE_RATE` | `30/min` | sign-in / sign-up / reset throttling per IP |
| `TIME_ZONE`, `LOG_LEVEL`, `DJANGO_ADMIN_URL`, `STATIC_ROOT`, `DB_CONN_MAX_AGE` | see `.env.example` | housekeeping |

## 4. In-Camp vs Post-Camp (streams)
One API, two **separate** programmes. Every account belongs to exactly one *track*; the two never see each other's
courses, trainers or earnings (cross-over attempts return `403`). Full description: [`docs/STREAMS.md`](docs/STREAMS.md).

* **Streams** — year + number 1–6 (e.g. *2026 Stream 3*), start/end dates and optional grace days. Created by the SAED admin.
* **Life-cycle** — In-Camp corps members and In-Camp trainers are active only for their stream; afterwards the API
  answers `403 stream_expired` (profile, notifications, dashboard and complaints still work). Re-activation is per stream.
* **In-Camp trainers** are created by the admin (stream, name, e-mail, phone, skill); they receive an invite e-mail and set their own password.
* **Proposals** — trainers propose what they will run in the stream; the admin approves (publishes) or declines with a note.
* **Reports** — per stream/year: corps members, trainers, courses, enrolments, by skill, by camp, CSV export.
* **Daily job** — `python manage.py deactivate_incamp` records and announces expiries (access is cut off on time even if it does not run).

## 5. API documentation
Generated from the live URL configuration (a test fails if a route is undocumented).

| URL | |
|---|---|
| `/` | status page (JSON) – proves the app is running |
| `/api/docs/` (also `/docs/`) | Swagger UI |
| `/api/redoc/` | ReDoc |
| `/api/openapi.json` | OpenAPI 3.1 |
| `docs/API.md`, `docs/openapi.json` | offline copies — regenerate: `DJANGO_DEBUG=1 python manage.py export_openapi` |

`API_DOCS=staff` (the production default) answers **404** to anyone who is not a signed-in admin — set `API_DOCS=public`
if you want the reference to be openly readable.

## 6. Supported stacks
All three profiles pass the complete test-suite (204 tests).

| Profile | Install | Python | Django |
|---|---|---|---|
| Current (recommended) | `pip install -r requirements.txt` | 3.10 – 3.13 | 5.2 LTS |
| cPanel / shared hosting | `pip install -r requirements-cpanel.txt` | 3.10 – 3.13 | 4.2 – 5.2 |
| Legacy (last resort) | `pip install -r requirements-legacy.txt` | **≤ 3.11 only** (tested on 3.11) | 3.2 (end-of-life) |

Django 3.2 imports the `cgi` module that Python 3.12+ removed, so it **cannot** run on a Python 3.12/3.13 app.
Older `dj-database-url` (0.5.x) is supported (no `conn_health_checks`), as are the older CSRF/`STORAGES` conventions.

## 7. Tests and CI
```bash
DJANGO_DEBUG=1 python manage.py test                                   # SQLite
DATABASE_URL=postgres://user:pw@localhost:5432/saed python manage.py test   # PostgreSQL
python manage.py makemigrations --check --dry-run
```
`.github/workflows/ci.yml` runs SQLite, PostgreSQL, the cPanel profile and the legacy profile. See `docs/TESTING.md`
for the manual Paystack/protected-content checklist.

## 8. Project layout
```
config/            settings, root urls, wsgi (reference harness; copy `saed/` into an existing project if you prefer)
saed/              the app: models, migrations, services/, views/, urls.py, apidocs/, management/commands/, tests/
  services/streams.py   stream life-cycle (active / upcoming / expired), expiry job
  services/access.py    track + stream access rules for courses
  views/streams.py      streams, In-Camp trainers, proposals review, reports
passenger_wsgi.py  cPanel/Passenger entry point
requirements*.txt  current / cpanel / legacy / dev
docs/              README guides, API.md, openapi.json, CHANGES, MIGRATION, TESTING, WALKTHROUGHS
```

## 9. Compatibility with the frontend
| Backend | Frontend | Notes |
|---|---|---|
| 2.5.x | **2.5.x** | streams, tracks, proposals, reports, `config.js` runtime API address |
| 2.5.x | 2.4.x | **not compatible**: sign-up now takes `accountMode` `in_camp`/`post_camp` (no `both`) and In-Camp needs a `streamId` |
| 2.4.x | 2.4.x | previous release |

Deploy order for an upgrade: **backend first** (`migrate`), then the frontend.

## 10. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Every URL is 404 on cPanel | wrong Application root / startup file, or you opened a path that does not exist. `/` must show the JSON status page. See `docs/DEPLOY-CPANEL.md` §6 |
| `/api/docs/` is 404 | `API_DOCS=staff` and you are not signed in as an admin on the API host → set `API_DOCS=public` |
| Swagger page is blank | static files not served: leave `WHITENOISE_USE_FINDERS=1` or run `collectstatic` |
| `TypeError: config() got an unexpected keyword argument 'conn_health_checks'` | fixed in 2.5.0 (older `dj-database-url` is detected automatically) |
| `ModuleNotFoundError: No module named 'cgi'` | Django 3.2 on Python 3.12/3.13 — use `requirements-cpanel.txt` (Django 4.2+) or a Python ≤ 3.11 app |
| `'transaction_mode' is an invalid keyword argument` | fixed in 2.5.0 (only used on Django ≥ 5.1) |
| "Your sign-in session could not be established" | app and API on different sites → `docs/DEPLOYMENT.md` §2 |
| 403 `CSRF Failed: Origin checking failed` | the app's origin is missing from `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS` (include `https://`; on Django 3.2 the scheme is stripped automatically) |
