# config/settings.py

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ[key] = value


_load_env(BASE_DIR / ".env")

def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-saed-secret-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "saed.dunistech.ng,localhost,127.0.0.1")
# ALLOWED_HOSTS = ['*']
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ALLOWED_HOSTS = ["saed.dunistech.ng", "saed-api.simplylovely.ng"]
if not DEBUG and not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG is false.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "saed",
    'drf_yasg',
]


MIDDLEWARE = [
    # CorsMiddleware must be first — before SecurityMiddleware — so that
    # preflight OPTIONS requests receive CORS headers before any other
    # middleware can short-circuit them (e.g. with a redirect or 403).
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "saed.middleware.RequestLogMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

database_url = os.getenv("DATABASE_URL", "").strip()
database_engine = os.getenv("DATABASE_ENGINE", "").strip()

if database_url:
    import urllib.parse
    url = urllib.parse.urlparse(database_url)
    engine = "django.db.backends.postgresql" if url.scheme in ("postgres", "postgresql") else f"django.db.backends.{url.scheme}"
    DATABASES = {
        "default": {
            "ENGINE": engine,
            "NAME": url.path.lstrip("/"),
            "USER": urllib.parse.unquote(url.username or ""),
            "PASSWORD": urllib.parse.unquote(url.password or ""),
            "HOST": url.hostname or "",
            "PORT": str(url.port or ("5432" if "postgres" in engine else "")),
            "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
        }
    }
elif database_engine:
    DATABASES = {
        "default": {
            "ENGINE": database_engine,
            "NAME": os.getenv("DATABASE_NAME"),
            "USER": os.getenv("DATABASE_USER", ""),
            "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
            "HOST": os.getenv("DATABASE_HOST", ""),
            "PORT": os.getenv("DATABASE_PORT", ""),
            "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_NAME", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Production Storage (Cloudinary / AWS S3)
USE_S3 = os.getenv("USE_S3", "").strip().lower() in ("true", "1", "yes")
USE_CLOUDINARY = os.getenv("USE_CLOUDINARY", "").strip().lower() in ("true", "1", "yes")

if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = {
        "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME", ""),
        "API_KEY": os.getenv("CLOUDINARY_API_KEY", ""),
        "API_SECRET": os.getenv("CLOUDINARY_API_SECRET", ""),
    }
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
elif USE_S3:
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "")
    AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_S3_CUSTOM_DOMAIN", f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com" if AWS_STORAGE_BUCKET_NAME else "")
    AWS_DEFAULT_ACL = None
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# Sentry Performance & Error Monitoring
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2")),
            send_default_pii=False,
            environment=os.getenv("ENVIRONMENT", "production"),
        )
    except ImportError:
        pass

# Allow these headers
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]
# Allow these methods
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]


# # ─── CORS ─────────────────────────────────────────────────────────────────────
# # Override via .env: CORS_ALLOWED_ORIGINS=http://localhost:3002,https://saed.dunistech.ng
# CORS_ALLOWED_ORIGINS = env_list(
#     "CORS_ALLOWED_ORIGINS",
#     "http://localhost:3002,http://127.0.0.1:3002",
# )
# # Required for fetch(..., credentials:"include") to work cross-origin.
# # Never combine with CORS_ALLOW_ALL_ORIGINS=True — browsers reject that.
# CORS_ALLOW_CREDENTIALS = True

CORS_ORIGIN_WHITELIST = [
    'https://saed.dunistech.ng',
    'http://localhost:8000',
]

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Override via .env: CORS_ALLOWED_ORIGINS=http://localhost:3002,https://saed.dunistech.ng
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "https://saed.dunistech.ng,http://localhost:3002,http://127.0.0.1:3002",
)

# Required for fetch(..., credentials:"include") to work cross-origin.
# Never combine with CORS_ALLOW_ALL_ORIGINS=True — browsers reject that.
CORS_ALLOW_CREDENTIALS = True

# ─── CSRF ─────────────────────────────────────────────────────────────────────
# Must mirror CORS_ALLOWED_ORIGINS so Django accepts cross-origin POST/PATCH/DELETE.
# Override via .env: CSRF_TRUSTED_ORIGINS=http://localhost:3002,https://saed.dunistech.ng
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "https://saed.dunistech.ng,http://localhost:3002,http://127.0.0.1:3002",
)
# False = JS can read the cookie to send X-CSRFToken header. Must not be True.
CSRF_COOKIE_HTTPONLY = False
# IMPORTANT: SameSite=None + Secure=True is required in BOTH dev and prod
# whenever frontend and backend are on different hostnames (even localhost
# vs 127.0.0.1 counts as cross-site). Do NOT branch this on DEBUG — that was
# the cause of session cookies being silently dropped on every cross-origin
# request in development, producing 403s and logout-on-refresh.
# localhost/127.0.0.1 are treated as secure contexts by browsers even over
# plain HTTP, so Secure=True still works in dev without HTTPS.
# Still overridable via .env for edge cases (e.g. same-origin deployments).
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "None")
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)

# Set cookie domain for cross-origin deployments (e.g. .dunistech.ng)
# Override via .env: CSRF_COOKIE_DOMAIN=.dunistech.ng
CSRF_COOKIE_DOMAIN = os.getenv("CSRF_COOKIE_DOMAIN", None)

# ─── Sessions ─────────────────────────────────────────────────────────────────
# Same reasoning as CSRF above — always None/Secure, never DEBUG-dependent.
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "None")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
SESSION_COOKIE_HTTPONLY = True
# Keep sessions alive for 7 days; without this they expire when the browser closes.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
# Only write the session back to the DB when something actually changed.
SESSION_SAVE_EVERY_REQUEST = False
# Ensure session persists across browser restarts (respects SESSION_COOKIE_AGE)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# Set cookie domain for cross-origin deployments (e.g. .dunistech.ng)
# Override via .env: SESSION_COOKIE_DOMAIN=.dunistech.ng
SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", None)

# # Store CSRF in its own cookie, not in the session.
# # This way a stale sessionid won't break CSRF validation.
CSRF_USE_SESSIONS=False

# ─── HTTPS / HSTS (production only) ───────────────────────────────────────────
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))

# Enforce strict mutual exclusivity: EMAIL_USE_SSL and EMAIL_USE_TLS can NEVER both be True.
if env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465) or EMAIL_PORT == 465:
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
else:
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@saed-ims.com")
MD_EMAIL = os.getenv("MD_EMAIL", "")

# CRITICAL: Unset these to prevent Django from passing them to starttls()
EMAIL_SSL_KEYFILE = None
EMAIL_SSL_CERTFILE = None

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3002")

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_API_URL = os.getenv("PAYSTACK_API_URL", "https://api.paystack.co")
PAYSTACK_DEFAULT_AMOUNT = int(os.getenv("PAYSTACK_DEFAULT_AMOUNT", "50000"))

# Secret key required for hidden admin signup endpoint
ADMIN_SIGNUP_SECRET = os.getenv("ADMIN_SIGNUP_SECRET", "")

# Prevents SMTP from hanging requests
EMAIL_TIMEOUT = 5

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON_RATE", "100/minute"),
        "user": os.getenv("THROTTLE_USER_RATE", "1000/minute"),
    },
    "UNAUTHENTICATED_USER": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "debug.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "saed": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "saed.requests": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

