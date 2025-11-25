import os
from pathlib import Path
from celery.schedules import crontab
import json, sys

#PHASE 11
LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-unsafe")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

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
    "program.apps.ProgramConfig",  # <- make sure it's this dotted path
    "reporting",   # NEW (Sprint 8)
    "ops",               # NEW (observability + backups)
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
    #PHASE 11
    "ops.middleware.RequestLogMiddleware",
]

# Templates (needed for Django admin)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # keep for project templates later
        "APP_DIRS": True,                  # lets Django load app templates (incl. admin)
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
        "NAME": os.getenv("MYSQL_DATABASE", "nutrilift"),
        "USER": os.getenv("MYSQL_USER", "nutrilift"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "nutrilift"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
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

# Admin URL (harden in staging/prod)
ADMIN_URL = os.getenv("ADMIN_URL", "admin")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

# BROKER_HOST = os.getenv("BROKER_HOST", "localhost")  # override to 'redis' inside Docker
# CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"redis://{BROKER_HOST}:6379/0")
# CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"redis://{BROKER_HOST}:6379/1")
CELERY_TIMEZONE = TIME_ZONE

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

#PHASE 11
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