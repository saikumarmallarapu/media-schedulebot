import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "dev-only-change-this-key-before-deploying-media-schedulebot",
)
DEBUG = _bool_env("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "scheduler_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "media_schedulebot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "media_schedulebot.wsgi.application"
ASGI_APPLICATION = "media_schedulebot.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _resolve_path(os.getenv("DATABASE_PATH", "schedulebot.db")),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = _resolve_path(os.getenv("MEDIA_DIR", "media"))
LOG_FILE_PATH = _resolve_path(os.getenv("LOG_FILE", "logs/app.log"))
LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LOGIN_URL = "admin:login"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "app_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_FILE_PATH),
            "formatter": "standard",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "scheduler_app": {
            "handlers": ["app_file"],
            "level": "INFO",
            "propagate": True,
        },
        "instagram_bot": {
            "handlers": ["app_file"],
            "level": "INFO",
            "propagate": True,
        },
    },
}
