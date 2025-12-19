"""
Unified Django settings for the Nutrilift backend.

This consolidates the previous package `nutrilift.settings` (base.py, local.py,
staging.py, production.py) into a single module `nutrilift.settings`.

Derived from the original `base.py` with `local.py` and `staging.py` behavior
preserved via the DJANGO_ENV compatibility shim at the bottom.
"""

import os
from pathlib import Path
from celery.schedules import crontab
import json, sys

# PHASE 11
LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# IMPORTANT: this file lives at nutrilift/backend/nutrilift/settings.py
# We keep BASE_DIR pointing to /backend (same as before) by using .parent.parent
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-unsafe")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
#ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
ALLOWED_HOSTS=["*"]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # project apps
    "accounts",
    "orgs",
    "roster",
    "screening",
    "audit",
    "messaging",
    "assist",
    "program.apps.ProgramConfig",  # <- keep this dotted path
    "grants",
    "fulfillment",
    "reporting",                   # sprint 8
    "ops",                         # observability + backups
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # RBAC org scoping
    "accounts.middleware.CurrentOrganizationMiddleware",
    # PHASE 11
    "ops.middleware.RequestLogMiddleware",
]

# Templates (needed for Django admin)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # same location as before
        "APP_DIRS": True,                  # allows loading app templates (incl. admin)
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",   # admin needs this
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

ROOT_URLCONF = "nutrilift.urls"
WSGI_APPLICATION = "nutrilift.wsgi.application"
ASGI_APPLICATION = "nutrilift.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        #"NAME": os.getenv("MYSQL_DATABASE", "nutrilift"),
        "NAME": "nutrilift",
        #"USER": os.getenv("MYSQL_USER", "nutrilift"),
        "USER": "nutrilift",
        #"PASSWORD": os.getenv("MYSQL_PASSWORD", "nutrilift"),
        "PASSWORD": "q&cWMVFaV%BV%SrQ",
        #"HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "HOST": "localhost",
        "PORT": int(os.getenv("DB_PORT", "3306")),
        "OPTIONS": {
            "charset": "utf8mb4",
            "use_unicode": True,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Phase 2: Funding ---
# Amount allocated from a grant for each approved enrollment.
# Leave at 0 to disable grant bookkeeping.
NUTRILIFT_GRANT_COST_PER_ENROLLMENT = os.getenv("NUTRILIFT_GRANT_COST_PER_ENROLLMENT", "0")

# Admin URL (harden in staging/prod)
ADMIN_URL = os.getenv("ADMIN_URL", "admin")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_TIMEZONE = TIME_ZONE

# Celery beat schedules (copied as-is)
CELERY_BEAT_SCHEDULE = {
    "compliance-reminders-15min": {
        "task": "program.tasks.send_compliance_due_reminders",
        "schedule": crontab(minute="*/15"),
    },
    "milestones-overdue-and-enforcement-daily": {
        "task": "program.tasks.update_milestones_and_enforcement",
        "schedule": crontab(hour=2, minute=15),
    },
}

CELERY_BEAT_SCHEDULE.update({
    "reporting-rollup-nightly": {
        "task": "reporting.tasks.build_daily_rollups",
        "schedule": crontab(hour=1, minute=30),  # 01:30 every day
    },
    "reporting-send-due-reports-daily": {
        "task": "reporting.tasks.send_due_school_reports",
        "schedule": crontab(hour=3, minute=5),   # 03:05 every day
    },
})

# PHASE 11
CELERY_BEAT_SCHEDULE.update({
    "ops-beat-heartbeat-every-1m": {
        "task": "ops.tasks.beat_heartbeat",
        "schedule": crontab(minute="*/1")
    },
    "ops-nightly-backup": {
        "task": "ops.tasks.nightly_backup",
        "schedule": crontab(hour=2, minute=30)
    },
})

# ------------------------------------------------------------------------------
# Single-file environment profile (replaces settings.local/staging/production)
# ------------------------------------------------------------------------------
# Prefer DJANGO_ENV; if not set, fall back to the *suffix* of DJANGO_SETTINGS_MODULE
# (e.g. ".local", ".staging", ".production") for compatibility with existing env files.
DJANGO_ENV = os.getenv("DJANGO_ENV")
if not DJANGO_ENV:
    _dsm = os.getenv("DJANGO_SETTINGS_MODULE", "")
    if _dsm.endswith(".local"):
        DJANGO_ENV = "local"
    elif _dsm.endswith(".staging"):
        DJANGO_ENV = "staging"
    elif _dsm.endswith(".production"):
        DJANGO_ENV = "production"
    else:
        DJANGO_ENV = "local"  # safe default for development

DJANGO_ENV = DJANGO_ENV.lower()

if DJANGO_ENV == "local":
    # Match previous settings.local: always enable DEBUG in local dev
    DEBUG = True
elif DJANGO_ENV in {"staging", "production"}:
    # Match previous settings.staging (production imported staging)
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
# ------------------------------------------------------------------------------
