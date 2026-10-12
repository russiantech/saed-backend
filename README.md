# SAED Backend

Django REST API for the NYSC Skills Acquisition and Entrepreneurship Development Information Management System.

## Stack

- Django 6
- Django REST Framework
- SQLite (local dev) / PostgreSQL (production)
- Session-based authentication
- `drf-yasg` for API schema generation

## Setup

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_saed          # optional: load demo data
python manage.py runserver 8002     # http://127.0.0.1:8002/api/
```

## Project Structure

```
saed-backend/
├── config/
│   ├── settings.py       Django settings, CORS, CSRF, DB config
│   ├── urls.py           Root URL routing + Swagger schema
│   └── wsgi.py           WSGI entry point
├── saed/
│   ├── models.py         Profile, Program, Application, Course, FastTrackVideo, Connection, Notification, Complaint
│   ├── admin.py          Django admin with role-based fieldsets
│   ├── urls.py           API route declarations
│   ├── views/
│   │   ├── __init__.py   Re-exports all views
│   │   ├── base.py       Shared helpers, permissions, constants
│   │   ├── auth.py       Login, signup, trainer signup, password reset, email verify
│   │   ├── programs.py   Program CRUD, application management
│   │   ├── trainers.py   Trainer connections, selection
│   │   ├── courses.py    Course CRUD, fast track videos
│   │   ├── payments.py   Paystack integration, enrollment
│   │   ├── users.py      User management (admin)
│   │   ├── notifications.py   In-app notifications
│   │   ├── complaints.py      DUNIS complaints
│   │   ├── dunis.py       DUNIS admin operations
│   │   ├── fast_track.py  Fast track video management
│   │   └── profile.py     Profile updates
│   └── management/
│       └── commands/
│           ├── seed_saed.py              Seed demo accounts and programs
│           └── fix_program_categories.py Fix historical category values
├── requirements.txt
├── manage.py
└── documentation.md      Full API and model reference
```

## API Endpoints

All routes are under `/api/`. Full list in [documentation.md](documentation.md).

| Endpoint | Method | Access | Purpose |
|----------|--------|--------|---------|
| `/api/auth/login/` | POST | Public | Login (requires verified email) |
| `/api/auth/signup/` | POST | Public | Corps member registration (sends 6-digit OTP) |
| `/api/auth/trainer-signup/` | POST | Public | Trainer registration (sends 6-digit OTP) |
| `/api/auth/admin-signup/` | POST | Secret | Admin registration (requires secret, sends 6-digit OTP) |
| `/api/auth/send-code/` | POST | Public | Send/resend 6-digit email OTP |
| `/api/auth/verify-code/` | POST | Public | Verify 6-digit email OTP & auto-login |
| `/api/programs/` | GET | Public | List active programs |
| `/api/applications/` | GET | Corps Member | My applications |
| `/api/manage/programs/` | GET/POST/PATCH | Dunis/Trainer | Manage programs (SAED admin: restrict/unrestrict only) |
| `/api/manage/applications/` | GET/PATCH | Admin/Trainer | Review applications |
| `/api/manage/users/` | GET/PATCH | Admin | User management (DUNIS handles activation) |
| `/api/trainers/` | GET | Authenticated | Available trainers |
| `/api/courses/` | GET | Authenticated | Active courses |
| `/api/notifications/` | GET | Authenticated | Notifications |

## Models

| Model | Purpose |
|-------|---------|
| `Profile` | Extended user data — role, phone, NYSC code, trainer fields |
| `Program` | SAED training programs |
| `Application` | Corps member applications to programs |
| `Course` | Trainer-created courses |
| `FastTrackVideo` | Video content for fast track |
| `Connection` | Trainer-corps member connections |
| `Notification` | In-app notifications |
| `Complaint` | User complaints to DUNIS admin |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DJANGO_DEBUG` | `true` for local dev |
| `DJANGO_SECRET_KEY` | Required when `DJANGO_DEBUG=false` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts |
| `CORS_ALLOWED_ORIGINS` | Allowed frontend origins |
| `CSRF_TRUSTED_ORIGINS` | Trusted origins for CSRF |
| `DATABASE_*` | External database config (optional) |

## Commands

```bash
python manage.py migrate              # apply migrations
python manage.py makemigrations       # create new migrations
python manage.py seed_saed            # seed demo data
python manage.py check                # run Django checks
python manage.py test saed            # run tests
python manage.py runserver 8002       # start dev server
```

## Production

- Set `DJANGO_DEBUG=false`
- Set a strong `DJANGO_SECRET_KEY`
- Use PostgreSQL instead of SQLite
- Configure CORS and CSRF for your frontend domain
- Create admin accounts through trusted processes only

See [documentation.md](documentation.md) for the full API reference, model fields, access rules, and demo account credentials.
