import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return int(raw_value)


INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "").strip()
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"

DATABASE_PATH = _resolve_path(os.getenv("DATABASE_PATH", "schedulebot.db"))
MEDIA_DIR = _resolve_path(os.getenv("MEDIA_DIR", "media"))
LOG_FILE = _resolve_path(os.getenv("LOG_FILE", "logs/app.log"))

SESSION_STATE_PATH = _resolve_path(os.getenv("SESSION_STATE_PATH", ".instagram_session.json"))
PLAYWRIGHT_HEADLESS = _bool_env("PLAYWRIGHT_HEADLESS", False)
PUBLISH_TIMEOUT_MS = _int_env("PUBLISH_TIMEOUT_MS", 180000)
MAX_RETRIES = _int_env("MAX_RETRIES", 3)
