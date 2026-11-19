"""SAED IMS — environment-driven Django settings (SQLite for development, PostgreSQL for production).

Everything that differs between machines is read from environment variables (or a ``.env`` file next to
``manage.py``). See ``.env.example`` for the complete list. Defaults are *secure*: DEBUG is off unless you
turn it on, and a real ``DJANGO_SECRET_KEY`` is required whenever DEBUG is off.
"""
import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # real environment variables always win over .env

TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"


# ── helpers ─────────────────────────────────────────────────────────────────
def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    raw = os.environ.get(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# ── core ────────────────────────────────────────────────────────────────────
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver" if (DEBUG or TESTING) else "")
if not ALLOWED_HOSTS and not DEBUG:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS to your API host name(s), comma separated.")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "corsheaders", "saed",
]
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "saed.middleware.JsonGZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = env("SAED_URLCONF", "config.urls")
WSGI_APPLICATION = "config.wsgi.application"
ADMIN_URL = env("DJANGO_ADMIN_URL", "admin/").strip("/") + "/"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages"]},
}]

# ── database: DATABASE_URL works for SQLite *and* PostgreSQL ────────────────
#   sqlite:///db.sqlite3                      (default; development)
#   postgres://user:pass@host:5432/dbname     (production; add ?sslmode=require for managed databases)
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}",
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        # conn_health_checks=True,  # TypeError: config() got an unexpected keyword argument 'conn_health_checks' happens on older django versions using dj_database_url
    )
}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # Writers wait instead of failing with "database is locked"; IMMEDIATE makes transactions take the
    # write lock up front, which is what select_for_update() relies on in the payment code.
    DATABASES["default"].setdefault("OPTIONS", {}).update({"timeout": 20, "transaction_mode": "IMMEDIATE"})
    DATABASES["default"]["CONN_MAX_AGE"] = 0
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── auth / passwords / sessions ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", "Lax")

# ── i18n / static ───────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = Path(env("STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ── REST framework ──────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Brute-force protection for sign-in / sign-up / code endpoints (scope "auth").
    "DEFAULT_THROTTLE_RATES": {"auth": env("AUTH_THROTTLE_RATE", "10000/min" if TESTING else "30/min")},
    # Number of reverse proxies in front of Django (nginx = 1). 0 trusts REMOTE_ADDR only.
    "NUM_PROXIES": env_int("TRUSTED_PROXY_COUNT", 0 if (DEBUG or TESTING) else 1),
}
CACHES = {"default": (
    {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL")}
    if env("REDIS_URL") else
    {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "saed"}
)}

# ── URLs, CORS, CSRF ────────────────────────────────────────────────────────
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:3002").rstrip("/")
BACKEND_URL = env("BACKEND_URL", "").rstrip("/")   # public origin of this API, e.g. https://api.example.com
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", FRONTEND_URL)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", FRONTEND_URL)

# ── transport security (defaults are on whenever DEBUG is off) ──────────────
_PROD = not DEBUG and not TESTING
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", _PROD)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("USE_X_FORWARDED_PROTO", _PROD) else None
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", _PROD)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", _PROD)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000 if _PROD else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", _PROD)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_REDIRECT_EXEMPT = [r"^api/health/"]   # load-balancer probes use plain HTTP
X_FRAME_OPTIONS = "DENY"                     # lesson stream endpoints opt out and set frame-ancestors themselves

# ── media: public images vs private lesson files ────────────────────────────
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))                            # public images only
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", str(BASE_DIR / "protected_media")))  # lesson videos/docs
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
SAED_MAX_VIDEO_BYTES = env_int("SAED_MAX_VIDEO_BYTES", 500 * 1024 * 1024)
SAED_MAX_DOCUMENT_BYTES = env_int("SAED_MAX_DOCUMENT_BYTES", 100 * 1024 * 1024)
SAED_MEDIA_TOKEN_TTL = env_int("SAED_MEDIA_TOKEN_TTL", 3600)

# ── Paystack ────────────────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY")
PAYSTACK_BASE_URL = env("PAYSTACK_BASE_URL", "https://api.paystack.co")
PAYSTACK_DEFAULT_AMOUNT = env_int("PAYSTACK_DEFAULT_AMOUNT", 50000)  # kobo; trainer-activation fallback

# ── email ───────────────────────────────────────────────────────────────────
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend" if (DEBUG or TESTING)
                    else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "NYSC SAED IMS <noreply@saed-ims.ng>")
SERVER_EMAIL = env("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# ── API documentation (Swagger UI / Redoc / OpenAPI) ────────────────────────
# "public": anyone | "staff": signed-in staff/admin users only | "off": not served
API_DOCS = env("API_DOCS", "public" if (DEBUG or TESTING) else "staff").lower()

# ── logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}, "django.security": {"level": "WARNING"}},
}
