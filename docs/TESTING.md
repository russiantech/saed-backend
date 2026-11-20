# Testing payments and protected content

## Automated
```bash
python manage.py test saed         # 204 tests: payments, webhook, permissions, uploads, streaming, discovery, in-camp
```
Key automated cases: the 2,548,224 vs 2,500,000 scenario (success, no false failure); real amount/currency/customer/reference mismatches (no access, flagged); duplicate webhooks and verify+webhook races (single grant); bad signature rejected; token reuse for another lesson/kind rejected; revoked access stops streaming; fee bypass attempts rejected.

## Manual — Paystack TEST mode
Use test keys (`sk_test_…`, `pk_test_…`) and test cards from Paystack's docs (e.g. `4084 0840 8408 4081`, any future expiry, CVV `408`).
1. **Trainer activation**: log in as an authorised, unpaid trainer → *Pay to activate* → pay → you land on the dashboard activated.
2. **Bank + subaccount**: Earnings → choose bank, enter a Paystack test account number, *Verify account* (name appears) → *Save*. Status shows Verified.
3. **Video fee**: create a lesson → attach a video → fee prompt shows the Dunis-configured amount → pay → upload continues automatically. Attach a second video to the same lesson: no second charge. In Dunis → set fee off → upload is free.
4. **Premium lesson**: as a corps member enrol, open a locked lesson → *Pay* → success → content opens. Check the trainer's Earnings and Dunis → Payments show the split.
5. **Fee-bearing customer** (reproduces the original bug): in Paystack dashboard set *Who bears charges = Customer*; pay a lesson. Paystack's `amount` will exceed the price; the payment must still end **successful** with the fee shown as gateway fee.
6. **Mismatch review**: in test mode, tamper by editing the lesson price between initialising and verifying (or use the unit tests) → payment shows *under review*; Dunis approves/rejects.
7. **Webhook**: with a tunnel (ngrok) set the dashboard webhook to `/api/webhooks/paystack/`; close the browser mid-payment — access must still appear. Send the same event twice — no duplicates.
8. **Bank transfer**: corps member presses *I have paid by transfer*; trainer sees the request and *Confirm payment received & unlock*; revoke and confirm the student is locked out again.

## Manual — protected content
* Copy a lesson's stream URL (from browser dev tools), open it in a private window within the hour: it works only with a valid token and while the student still has access; after *Revoke* it returns 403.
* Try `/api/lessons/<id>/media/video/` logged out → 401; as an unenrolled student → 403.
* Confirm `PRIVATE_MEDIA_ROOT` is not reachable by URL from your web server.
* Seek in a video (Range requests) and open a PDF in-app (no download page).

## v2.2 additions
* Backend: `saed/tests/test_letters_incamp.py` – private letter streaming (owner/admin only, inline, CSP, no X-Frame-Options), missing-file and legacy-path handling, path traversal, replace-deletes-old, format validation (signup/profile/admin), in-app-only lesson formats, external document links rejected, legacy Office files refused, In-Camp catalogue per role.
* Frontend: `src/__tests__/viewer.test.jsx` – viewer fetches same-origin with the session, renders images, shows server errors, refuses unsupported formats, never renders links/new tabs; LetterField validation and preview.
* Totals: 131 backend tests (SQLite and PostgreSQL), 16 frontend tests.

## v2.3 additions
* Backend: query-budget tests (no N+1 regressions), In-Camp course detail for every role, JSON gzip, camp administration (add/edit/duplicate/validation/in-use delete/permissions).
* Frontend: camps page, client-side date validation, auth logo → home link.
* Totals: 145 backend tests (SQLite and PostgreSQL), 22 frontend tests.

## Stack matrix (all 204 tests green)
```bash
python3.13 -m venv v && v/bin/pip install -r requirements-dev.txt && DJANGO_DEBUG=1 v/bin/python manage.py test          # Django 5.2
pip install -r requirements-cpanel.txt "Django>=4.2,<4.3" openapi-spec-validator                                         # Django 4.2, Python 3.13
pip install -r requirements-legacy.txt openapi-spec-validator    # Python 3.11 only: Django 3.2, DRF 3.14, dj-database-url 0.5
```
New in 2.5: `saed/tests/test_streams.py` (streams, tracks, life-cycle, proposals, reports) and `saed/tests/test_deploy.py`
(root route, docs URLs, cross-site cookie switch, deployment checks, engine alias, Passenger entry point, `create_saed_admin`).
