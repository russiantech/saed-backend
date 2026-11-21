# Deploying the API on cPanel ("Setup Python App")

Tested profile: **Python 3.13 + `requirements-cpanel.txt`** (Django 4.2–5.2). All 205 tests pass on it.
The web app is deployed separately (see the frontend repo's `docs/DEPLOYMENT.md`).

## 0. Decide the host names first (this prevents the #1 production problem)
Sign-in uses a cookie. Browsers only send it reliably when the app and the API are on the **same site**:

| App | API | Result |
|---|---|---|
| `saed.dunistech.ng` | `saed-api.dunistech.ng` | ✅ works (same site `dunistech.ng`) |
| `saed.dunistech.ng` | `saed-api.simplylovely.ng` | ⚠️ different sites: needs `CROSS_SITE_COOKIES=1`, and Safari / strict privacy modes will still block sign-in |

So create the API sub-domain **under the same domain as the web app**. If you truly cannot, see "Different sites" in `DEPLOYMENT.md`.

## 1. Create the Python app
cPanel → **Setup Python App** → *Create Application*

| Field | Value |
|---|---|
| Python version | the newest offered (3.13 recommended) |
| Application root | `saed-api` (a folder under your home directory, **outside** `public_html`) |
| Application URL | the API sub-domain, e.g. `saed-api.dunistech.ng` |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Create it. cPanel shows a command like `source /home/USER/virtualenv/saed-api/3.13/bin/activate && cd /home/USER/saed-api` — copy it.

## 2. Upload the code
Upload the contents of this repository **into the application root** so that `manage.py` and `passenger_wsgi.py` sit
directly in `saed-api/` (not in a nested folder). Replace the placeholder `passenger_wsgi.py` cPanel created with the one from this repo.
Create the folders for uploads if they are missing: `mkdir -p media protected_media tmp`.

## 3. Install dependencies
In **Terminal** (or the app's *Run Pip Install* box):
```bash
source /home/USER/virtualenv/saed-api/3.13/bin/activate
cd /home/USER/saed-api
# If an older/other stack was installed before, remove it first:
pip uninstall -y Django djangorestframework django-cors-headers dj-database-url drf-yasg
pip install -r requirements-cpanel.txt
```
* `drf-yasg` is **not** needed — the API documentation is built in.
* Python 3.12/3.13 cannot run Django 3.2 (`No module named 'cgi'`). Keep `requirements-cpanel.txt`. Use `requirements-legacy.txt` only on a Python ≤ 3.11 app.

## 4. Settings (environment variables)
Either add them in the Python App screen (*Environment variables*) or put them in a file named `.env` in the application root
(copy `.env.example`; the app reads it automatically). **Never** upload `.env` to a public folder.

```ini
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<64+ random characters:  python -c "import secrets;print(secrets.token_urlsafe(64))">
DJANGO_ALLOWED_HOSTS=saed-api.dunistech.ng
FRONTEND_URL=https://saed.dunistech.ng
BACKEND_URL=https://saed-api.dunistech.ng
CORS_ALLOWED_ORIGINS=https://saed.dunistech.ng
CSRF_TRUSTED_ORIGINS=https://saed.dunistech.ng
DATABASE_URL=postgres://DBUSER:DBPASSWORD@localhost:5432/DBNAME      # or leave unset for SQLite (small pilots only)
API_DOCS=public                      # staff = admins only (404 for everyone else)
PAYSTACK_SECRET_KEY=sk_live_...
PAYSTACK_PUBLIC_KEY=pk_live_...
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=mail.dunistech.ng
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=noreply@dunistech.ng
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=NYSC SAED IMS <noreply@dunistech.ng>
# Only if the app and API are on different sites:  CROSS_SITE_COOKIES=1
```
`DATABASE_URL` for PostgreSQL created in cPanel → *PostgreSQL Databases*: user and database names are prefixed with your account name.
Special characters in the password must be URL-encoded (`@` → `%40`).

## 5. Create the tables and the first administrator
```bash
python manage.py check --deploy          # read the warnings; saed.W002 means app and API are on different sites
python manage.py migrate
python manage.py create_saed_admin --email you@example.org --first-name Ada --last-name Obi --phone 08012345678
python manage.py collectstatic --noinput # optional (static files are also served without it)
mkdir -p tmp && touch tmp/restart.txt    # restart the app (or press Restart in Setup Python App)
```

## 6. Verify (in a browser)
| URL | Expected |
|---|---|
| `https://saed-api.dunistech.ng/` | small JSON: `{"service": "SAED IMS API", "status": "ok", ...}` |
| `/api/health/` | `{"status": "ok", ...}` |
| `/api/health/ready/` | `{"status": "ok", "checks": {...}}` (database + private media writable; 503 otherwise) |
| `/api/docs/` | Swagger UI (needs `API_DOCS=public`, otherwise 404) |

If **everything** is 404 or shows "It works!/Incomplete response": the Application root/URL/startup file is wrong or the app
was not restarted — see the table below and check `stderr.log` in the application root.

## 7. Scheduled job (daily)
cPanel → **Cron Jobs**, once a day (e.g. 01:15):
```
/home/USER/virtualenv/saed-api/3.13/bin/python /home/USER/saed-api/manage.py deactivate_incamp
```
This records and announces stream expiries (access is cut off on time even if the job does not run).

## 8. Paystack webhook
Paystack dashboard → *Settings → API Keys & Webhooks* → webhook URL `https://saed-api.dunistech.ng/api/webhooks/paystack/`.

## 9. Uploads on shared hosting
Lesson videos/documents go to `protected_media/` (outside `public_html`, never web-accessible). Large videos need the
host's request-size/time limits raised (ask the host, or have trainers use YouTube/Vimeo links for big videos).

## 10. Updating
```bash
cd /home/USER/saed-api && source /home/USER/virtualenv/saed-api/3.13/bin/activate
# upload the new code over the old, then:
pip install -r requirements-cpanel.txt
python manage.py migrate
touch tmp/restart.txt
```
Update the **backend first**, then the web app.

## Troubleshooting
| What you see | Cause and fix |
|---|---|
| All routes 404, or the default cPanel "It works!" page | Application URL/root/startup file wrong, `passenger_wsgi.py` not the one from this repo, or no restart. `/` must show the JSON status. Check `stderr.log` |
| 404 only at `/api/docs/` and `/api/openapi.json` | `API_DOCS=staff` (default in production) — set `API_DOCS=public` and restart |
| Docs page loads but is blank | static files unavailable — keep `WHITENOISE_USE_FINDERS=1` (default) or run `collectstatic` |
| `TypeError: config() got an unexpected keyword argument 'conn_health_checks'` | old `dj-database-url` with an old release; fixed in 2.5.0 — upload the current code |
| `ModuleNotFoundError: No module named 'cgi'` | Django 3.2 on Python 3.12+; `pip install -r requirements-cpanel.txt` |
| `TypeError: 'transaction_mode' is an invalid keyword argument` | old release with Django < 5.1; fixed in 2.5.0 |
| `DisallowedHost` / 400 Bad Request | host missing in `DJANGO_ALLOWED_HOSTS` |
| 500 on every request, `ImproperlyConfigured: DJANGO_SECRET_KEY` | env vars not set (Setup Python App → Environment variables, or `.env`) |
| `CSRF Failed: Origin checking failed` | app origin missing in `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS` |
| App signs in but is immediately logged out ("session could not be established") | app and API on different sites → section 0 |
| Redirect loop | the proxy does not send `X-Forwarded-Proto`; set `SECURE_SSL_REDIRECT=0` only if HTTPS is enforced by cPanel/AutoSSL redirects |
| Changes not visible | `touch tmp/restart.txt` |
