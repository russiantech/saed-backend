# import os
# from pathlib import Path


# BASE_DIR = Path(__file__).resolve().parent.parent


# def _load_env(path):
#     if not path.exists():
#         return
#     for line in path.read_text(encoding="utf-8").splitlines():
#         line = line.strip()
#         if not line or line.startswith("#"):
#             continue
#         key, _, value = line.partition("=")
#         key = key.strip()
#         value = value.strip().strip("\"'")
#         if key and key not in os.environ:
#             os.environ[key] = value


# _load_env(BASE_DIR / ".env")

# def env_bool(name, default=False):
#     return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# def env_list(name, default=""):
#     return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# DEBUG = env_bool("DJANGO_DEBUG", True)
# SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-saed-secret-key" if DEBUG else "")
# if not SECRET_KEY:
#     raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false.")

# ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# if not DEBUG and not ALLOWED_HOSTS:
#     raise RuntimeError("DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG is false.")

# INSTALLED_APPS = [
#     "django.contrib.admin",
#     "django.contrib.auth",
#     "django.contrib.contenttypes",
#     "django.contrib.sessions",
#     "django.contrib.messages",
#     "django.contrib.staticfiles",
#     "corsheaders",
#     "saed",
# ]

# # MIDDLEWARE = [
# #     "corsheaders.middleware.CorsMiddleware",
# #     "django.middleware.security.SecurityMiddleware",
# #     "django.contrib.sessions.middleware.SessionMiddleware",
# #     "django.middleware.common.CommonMiddleware",
# #     "django.middleware.csrf.CsrfViewMiddleware",
# #     "django.contrib.auth.middleware.AuthenticationMiddleware",
# #     "saed.middleware.RequestLogMiddleware",
# #     "django.contrib.messages.middleware.MessageMiddleware",
# #     "django.middleware.clickjacking.XFrameOptionsMiddleware",
# # ]
# # 
# MIDDLEWARE = [
#     "django.middleware.security.SecurityMiddleware",
#     "corsheaders.middleware.CorsMiddleware",  # <-- Must be BEFORE CommonMiddleware
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "saed.middleware.RequestLogMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
# ]

# ROOT_URLCONF = "config.urls"

# TEMPLATES = [
#     {
#         "BACKEND": "django.template.backends.django.DjangoTemplates",
#         "DIRS": [],
#         "APP_DIRS": True,
#         "OPTIONS": {
#             "context_processors": [
#                 "django.template.context_processors.request",
#                 "django.contrib.auth.context_processors.auth",
#                 "django.contrib.messages.context_processors.messages",
#             ],
#         },
#     },
# ]

# WSGI_APPLICATION = "config.wsgi.application"

# # if os.getenv("DATABASE_ENGINE"):
# #     DATABASES = {
# #         "default": {
# #             "ENGINE": os.getenv("DATABASE_ENGINE"),
# #             "NAME": os.getenv("DATABASE_NAME"),
# #             "USER": os.getenv("DATABASE_USER", ""),
# #             "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
# #             "HOST": os.getenv("DATABASE_HOST", ""),
# #             "PORT": os.getenv("DATABASE_PORT", ""),
# #             "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
# #         }
# #     }
    
# # else:
# #     DATABASES = {
# #         "default": {
# #             "ENGINE": "django.db.backends.sqlite3",
# #             "NAME": os.getenv("SQLITE_NAME", BASE_DIR / "db.sqlite3"),
# #         }
# #     }


# # v2
# database_engine = os.getenv("DATABASE_ENGINE", "").strip()

# if database_engine:
#     DATABASES = {
#         "default": {
#             "ENGINE": database_engine,
#             "NAME": os.getenv("DATABASE_NAME"),
#             "USER": os.getenv("DATABASE_USER", ""),
#             "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
#             "HOST": os.getenv("DATABASE_HOST", ""),
#             "PORT": os.getenv("DATABASE_PORT", ""),
#             "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
#         }
#     }
# else:
#     DATABASES = {
#         "default": {
#             "ENGINE": "django.db.backends.sqlite3",
#             "NAME": os.getenv("SQLITE_NAME", BASE_DIR / "db.sqlite3"),
#         }
#     }

# AUTH_PASSWORD_VALIDATORS = [
#     {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
#     {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
#     {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
#     {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
# ]

# LANGUAGE_CODE = "en-us"
# TIME_ZONE = "Africa/Lagos"
# USE_I18N = True
# USE_TZ = True

# STATIC_URL = "static/"
# STATIC_ROOT = BASE_DIR / "staticfiles"
# MEDIA_URL = "media/"
# MEDIA_ROOT = BASE_DIR / "media"
# DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# # Allow these headers
# CORS_ALLOW_HEADERS = [
#     "accept",
#     "accept-encoding",
#     "authorization",
#     "content-type",
#     "dnt",
#     "origin",
#     "user-agent",
#     "x-csrftoken",
#     "x-requested-with",
# ]
# # Allow these methods
# CORS_ALLOW_METHODS = [
#     "DELETE",
#     "GET",
#     "OPTIONS",
#     "PATCH",
#     "POST",
#     "PUT",
# ]
# CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001")
# CORS_ALLOW_CREDENTIALS = True
# CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001")
# SESSION_COOKIE_SAMESITE = "Lax"
# CSRF_COOKIE_SAMESITE = "Lax"
# SESSION_COOKIE_SECURE = not DEBUG
# CSRF_COOKIE_SECURE = not DEBUG
# SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
# SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
# SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
# SECURE_HSTS_PRELOAD = not DEBUG
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
# EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
# EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
# EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
# EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
# EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
# DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@saed-ims.com")
# MD_EMAIL = os.getenv("MD_EMAIL", "")
# FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")

# PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")

# # 
# # Prevents SMTP from hanging requests
# EMAIL_TIMEOUT = 5

# LOGGING = {
#     "version": 1,
#     "disable_existing_loggers": False,
#     "formatters": {
#         "verbose": {
#             "format": "{levelname} {asctime} {name} {message}",
#             "style": "{",
#         },
#     },
#     "handlers": {
#         "console": {
#             "class": "logging.StreamHandler",
#             "formatter": "verbose",
#         },
#         "file": {
#             "class": "logging.FileHandler",
#             "filename": BASE_DIR / "debug.log",
#             "formatter": "verbose",
#         },
#     },
#     "loggers": {
#         "saed": {
#             "handlers": ["console", "file"],
#             "level": "INFO",
#             "propagate": False,
#         },
#         "saed.requests": {
#             "handlers": ["console", "file"],
#             "level": "INFO",
#             "propagate": False,
#         },
#     },
# }





# v2
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
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(BASE_DIR / ".env")

def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-saed-secret-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
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
    "saed",
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

# if os.getenv("DATABASE_ENGINE"):
#     DATABASES = {
#         "default": {
#             "ENGINE": os.getenv("DATABASE_ENGINE"),
#             "NAME": os.getenv("DATABASE_NAME"),
#             "USER": os.getenv("DATABASE_USER", ""),
#             "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
#             "HOST": os.getenv("DATABASE_HOST", ""),
#             "PORT": os.getenv("DATABASE_PORT", ""),
#             "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
#         }
#     }
    
# else:
#     DATABASES = {
#         "default": {
#             "ENGINE": "django.db.backends.sqlite3",
#             "NAME": os.getenv("SQLITE_NAME", BASE_DIR / "db.sqlite3"),
#         }
#     }


# v2
database_engine = os.getenv("DATABASE_ENGINE", "").strip()

if database_engine:
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
# ─── CORS ─────────────────────────────────────────────────────────────────────
# Override via .env: CORS_ALLOWED_ORIGINS=http://localhost:3002,https://saed.dunistech.ng
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3002,http://127.0.0.1:3002",
)
# Required for fetch(..., credentials:"include") to work cross-origin.
# Never combine with CORS_ALLOW_ALL_ORIGINS=True — browsers reject that.
CORS_ALLOW_CREDENTIALS = True

# ─── CSRF ─────────────────────────────────────────────────────────────────────
# Must mirror CORS_ALLOWED_ORIGINS so Django accepts cross-origin POST/PATCH/DELETE.
# Override via .env: CSRF_TRUSTED_ORIGINS=http://localhost:3002,https://saed.dunistech.ng
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3002,http://127.0.0.1:3002",
)
# False = JS can read the cookie to send X-CSRFToken header. Must not be True.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
# Secure cookies require HTTPS. In dev (DEBUG=True) we must keep these False
# or the browser silently drops them on plain HTTP.
CSRF_COOKIE_SECURE = not DEBUG

# ─── Sessions ─────────────────────────────────────────────────────────────────
SESSION_COOKIE_SAMESITE = "Lax"
# Same rule: False in dev so the cookie is sent over plain HTTP localhost.
SESSION_COOKIE_SECURE = not DEBUG
# Keep sessions alive for 7 days; without this they expire when the browser closes.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
# Only write the session back to the DB when something actually changed.
SESSION_SAVE_EVERY_REQUEST = False

# ─── HTTPS / HSTS (production only) ───────────────────────────────────────────
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@saed-ims.com")
MD_EMAIL = os.getenv("MD_EMAIL", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")

# 
# Prevents SMTP from hanging requests
EMAIL_TIMEOUT = 5

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

