# Deploying the API (VPS / Docker / any Linux host)

For cPanel see `DEPLOY-CPANEL.md`. The web app is a separate deployment (frontend repo).

## 1. Docker (PostgreSQL + Redis + gunicorn)
```bash
cp deploy/.env.example deploy/.env       # set secrets, host names
POSTGRES_PASSWORD=... docker compose up --build        # API on :8002
```
The container runs `migrate` and `collectstatic` at start. Put a TLS-terminating reverse proxy in front (nginx/Caddy/your
load balancer) and forward `X-Forwarded-Proto`. *(The compose file could not be executed in the build sandbox — smoke-test once.)*

Example nginx for the API host:
```nginx
server {
    listen 443 ssl http2;
    server_name saed-api.example.com;
    client_max_body_size 520m;               # >= SAED_MAX_VIDEO_BYTES
    proxy_read_timeout 300s;
    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Range $http_range;   # video seeking
        proxy_request_buffering off;
    }
    # NEVER publish PRIVATE_MEDIA_ROOT; lesson files are only reachable through /api/lessons/<id>/media/...
}
```

## 2. Same site or different sites (cookies)
Sign-in is a cookie session. Choose one:

1. **Same site (recommended):** app `https://saed.example.com`, API `https://saed-api.example.com`. Defaults work (`SameSite=Lax`).
   Optionally `SESSION_COOKIE_DOMAIN=.example.com`.
2. **Same origin:** serve the app and proxy `/api` to this API from the same host (the frontend repo's nginx image does this with
   `API_UPSTREAM`). No CORS involved at all.
3. **Different sites** (e.g. `app.a.com` + `api.b.org`): set `CROSS_SITE_COOKIES=1` (cookies become `SameSite=None; Secure`, HTTPS
   mandatory), list the app in `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`, and build the app with an absolute API address.
   Safari, Firefox strict mode and some privacy extensions still block third-party cookies, so some users will not be able to sign in.
   Use options 1 or 2 whenever you can.

`python manage.py check --deploy` warns (`saed.W002`) when the two URLs are on different sites with `SameSite=Lax`.

## 3. Production checklist
1. Back up the database, then `python manage.py migrate` (see `MIGRATION.md`).
2. `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `FRONTEND_URL`, `BACKEND_URL`, CORS/CSRF origins.
3. `python manage.py create_saed_admin --email ...` for the first administrator.
4. Paystack live keys; webhook `https://<api-host>/api/webhooks/paystack/` (HMAC-SHA512 verified).
5. E-mail via SMTP (invites, verification, notifications).
6. Never expose `PRIVATE_MEDIA_ROOT`; raise the body-size limit for videos; forward `Range`.
7. Daily job: `python manage.py deactivate_incamp`.
8. `REDIS_URL` and `TRUSTED_PROXY_COUNT` when running more than one worker / behind proxies (rate limiting).
9. Health probes: `GET /api/health/` (liveness), `GET /api/health/ready/` (database + media storage, 503 if not ready).
10. Choose `API_DOCS`: `public`, `staff` (404 unless signed in as admin) or `off`.

## 4. Integrating into an existing Django project
Copy the `saed/` package. Your settings need `rest_framework`, `corsheaders`, `saed` in `INSTALLED_APPS`,
SessionAuthentication, `FRONTEND_URL`, `BACKEND_URL`, CORS/CSRF settings, `MEDIA_*`, **`PRIVATE_MEDIA_ROOT`**, size limits,
`PAYSTACK_*`, e-mail — see `config/settings.py`. Your URLconf must include `path("api/", include("saed.urls"))`.
