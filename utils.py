import logging
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import (
    INSTAGRAM_PASSWORD,
    LOG_FILE,
    MEDIA_DIR,
    TIMEZONE,
)
from constants import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    normalize_media_type,
)


def setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def ensure_project_directories() -> None:
    (MEDIA_DIR / "images").mkdir(parents=True, exist_ok=True)
    (MEDIA_DIR / "videos").mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)


def get_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone configured: {TIMEZONE}") from exc


def parse_scheduled_datetime(value: str) -> datetime:
    try:
        scheduled_at = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Schedule datetime must use YYYY-MM-DD HH:MM format.") from exc

    timezone = get_timezone()
    scheduled_at = scheduled_at.replace(tzinfo=timezone)
    if scheduled_at <= datetime.now(timezone):
        raise ValueError("Scheduled time must be in the future.")
    return scheduled_at


def validate_media_type(value: str) -> str:
    return normalize_media_type(value)


def validate_media_file(media_path: str | Path, media_type: str) -> Path:
    normalized_type = validate_media_type(media_type)
    path = Path(media_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()

    if not path.exists():
        raise ValueError(f"Media file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Media path must be a file: {path}")

    extension = path.suffix.lower().lstrip(".")
    if normalized_type == MEDIA_TYPE_IMAGE and extension not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise ValueError(f"Image file must be one of: {allowed}")
    if normalized_type == MEDIA_TYPE_VIDEO and extension not in ALLOWED_VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
        raise ValueError(f"Video file must be one of: {allowed}")

    return path


def store_media_file(media_path: str | Path, media_type: str) -> Path:
    source_path = validate_media_file(media_path, media_type)
    target_dir = MEDIA_DIR / "images" if media_type == MEDIA_TYPE_IMAGE else MEDIA_DIR / "videos"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir = target_dir.resolve()

    if _is_relative_to(source_path, target_dir):
        return source_path

    target_path = target_dir / source_path.name
    if target_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        target_path = target_dir / f"{source_path.stem}_{timestamp}{source_path.suffix}"

    shutil.copy2(source_path, target_path)
    return target_path


def sanitize_error(message: object) -> str:
    text = str(message)
    if INSTAGRAM_PASSWORD:
        text = text.replace(INSTAGRAM_PASSWORD, "[hidden]")
    return text


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
