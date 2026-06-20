import atexit
import logging
import threading
import time
from pathlib import Path

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.base import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from django.utils.text import get_valid_filename

from config import (
    INSTAGRAM_PASSWORD,
    INSTAGRAM_USERNAME,
    LOG_FILE,
    PLAYWRIGHT_HEADLESS,
    SESSION_STATE_PATH,
)
from instagram_bot import InstagramBot
from constants import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MEDIA_TYPE_IMAGE,
    STATUS_PENDING,
    STATUS_PUBLISHED,
)
from utils import get_timezone, sanitize_error, validate_media_file

from .models import ScheduledPost


logger = logging.getLogger(__name__)

JOB_PREFIX = "instagram_post_"
LOADER_JOB_ID = "load_pending_instagram_posts"
PAST_SCHEDULE_ERROR = "Scheduled time is in the past or current time. Choose a future time."

_scheduler_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None
_stop_requested = threading.Event()
_running_lock = threading.Lock()
_running_post_ids: set[int] = set()


def save_uploaded_media(uploaded_file, media_type: str) -> Path:
    validate_upload_extension(uploaded_file.name, media_type)
    target_dir = Path(settings.MEDIA_ROOT) / (
        "images" if media_type == MEDIA_TYPE_IMAGE else "videos"
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = get_valid_filename(Path(uploaded_file.name).name) or "media"
    target_path = _unique_media_path(target_dir, filename)

    with target_path.open("wb") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    validate_media_file(target_path, media_type)
    return target_path


def validate_upload_extension(filename: str, media_type: str) -> None:
    extension = Path(filename).suffix.lower().lstrip(".")
    allowed_extensions = (
        ALLOWED_IMAGE_EXTENSIONS if media_type == MEDIA_TYPE_IMAGE else ALLOWED_VIDEO_EXTENSIONS
    )
    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"{media_type.title()} file must be one of: {allowed}")


def instagram_connection_status() -> dict[str, object]:
    username_set = bool(INSTAGRAM_USERNAME)
    password_set = bool(INSTAGRAM_PASSWORD)
    configured = username_set and password_set
    session_saved = SESSION_STATE_PATH.exists()
    ready = configured and session_saved
    if ready:
        status_label = "Connected"
        status_class = "published"
    elif configured:
        status_label = "Login Needed"
        status_class = "pending"
    else:
        status_label = "Missing Setup"
        status_class = "failed"

    return {
        "username_set": username_set,
        "password_set": password_set,
        "configured": configured,
        "ready": ready,
        "session_saved": session_saved,
        "status_label": status_label,
        "status_class": status_class,
        "username_label": _masked_username(INSTAGRAM_USERNAME) if username_set else "Not set",
        "browser_mode": "Hidden browser" if PLAYWRIGHT_HEADLESS else "Visible browser",
        "session_filename": SESSION_STATE_PATH.name,
    }


def check_instagram_login() -> None:
    InstagramBot().verify_login()


def start_scheduler() -> int:
    global _scheduler

    with _scheduler_lock:
        _stop_requested.clear()
        if _scheduler is not None and _scheduler.running:
            return schedule_pending_posts(_scheduler)

        scheduler = _create_scheduler()
        scheduled_count = schedule_pending_posts(scheduler)
        scheduler.add_job(
            schedule_pending_posts,
            trigger="interval",
            minutes=1,
            args=[scheduler],
            id=LOADER_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        _scheduler = scheduler
        logger.info("Django scheduler started with %s pending post(s).", scheduled_count)
        return scheduled_count


def stop_scheduler() -> bool:
    global _scheduler

    with _scheduler_lock:
        _stop_requested.set()
        scheduler = _scheduler
        _scheduler = None

        if scheduler is None or not scheduler.running:
            _scheduler = None
            return False

        _shutdown_scheduler_instance(scheduler)
        return True


def refresh_scheduler() -> int:
    with _scheduler_lock:
        if _scheduler is None or not _scheduler.running:
            return 0
        return schedule_pending_posts(_scheduler)


def unschedule_post(post_id: int) -> None:
    with _scheduler_lock:
        if _scheduler is None or not _scheduler.running:
            return
        try:
            _scheduler.remove_job(_job_id(post_id))
        except JobLookupError:
            return


def scheduler_status() -> dict[str, object]:
    with _scheduler_lock:
        if _scheduler is None or not _scheduler.running:
            return {"running": False, "jobs": 0}
        post_jobs = [
            job for job in _scheduler.get_jobs() if job.id != LOADER_JOB_ID
        ]
        return {"running": True, "jobs": len(post_jobs)}


def schedule_pending_posts(scheduler: BackgroundScheduler) -> int:
    close_old_connections()
    if _stop_requested.is_set():
        close_old_connections()
        return 0

    now = timezone.now()
    scheduled_count = 0

    for post in ScheduledPost.objects.filter(status=STATUS_PENDING).order_by(
        "scheduled_time", "id"
    ):
        if _is_post_running(post.pk):
            continue

        run_time = post.scheduled_time
        if timezone.is_naive(run_time):
            run_time = timezone.make_aware(run_time, get_timezone())
        if run_time <= now:
            post.mark_failed(PAST_SCHEDULE_ERROR)
            logger.warning(
                "Post %s was not queued because its scheduled time is not in the future.",
                post.pk,
            )
            continue

        scheduler.add_job(
            publish_scheduled_post,
            trigger="date",
            run_date=run_time,
            args=[post.pk],
            id=_job_id(post.pk),
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=None,
        )
        scheduled_count += 1

    close_old_connections()
    return scheduled_count


def publish_scheduled_post(post_id: int) -> None:
    close_old_connections()
    if not _mark_post_running(post_id):
        logger.info("Post %s is already publishing; skipping duplicate trigger.", post_id)
        return

    try:
        try:
            post = ScheduledPost.objects.get(pk=post_id)
        except ScheduledPost.DoesNotExist:
            logger.warning("Scheduled post %s no longer exists.", post_id)
            return

        if post.status != STATUS_PENDING:
            logger.info("Scheduled post %s is already %s.", post_id, post.status)
            return

        max_retries = max(1, int(post.max_retries))
        while int(post.retry_count) < max_retries:
            if _stop_requested.is_set():
                logger.info("Publishing post %s stopped before the next retry.", post_id)
                return

            try:
                logger.info(
                    "Publishing Instagram post %s, attempt %s of %s.",
                    post_id,
                    int(post.retry_count) + 1,
                    max_retries,
                )
                InstagramBot().publish_post(
                    media_path=post.media_path,
                    media_type=post.media_type,
                    caption=post.caption or "",
                )
                post.mark_published()
                logger.info("Published Instagram post %s.", post_id)
                return
            except Exception as exc:
                safe_error = sanitize_error(exc)
                retry_count = post.record_failure(safe_error)
                logger.exception("Publishing post %s failed: %s", post_id, safe_error)

                if retry_count >= max_retries:
                    post.mark_failed(safe_error)
                    logger.error("Post %s marked failed after %s attempts.", post_id, retry_count)
                    return

                _interruptible_sleep(min(60, 2**retry_count))
                if _stop_requested.is_set():
                    logger.info("Publishing post %s stopped after retry delay.", post_id)
                    return
                post.refresh_from_db()
    finally:
        _unmark_post_running(post_id)
        close_old_connections()


def recent_logs(limit: int = 25) -> list[str]:
    if not LOG_FILE.exists():
        return []

    try:
        return LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


def _create_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(
        timezone=get_timezone(),
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": None,
        },
    )


def _unique_media_path(target_dir: Path, filename: str) -> Path:
    path = Path(filename)
    stem = path.stem or "media"
    suffix = path.suffix
    candidate = target_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    return target_dir / f"{stem}_{timestamp}{suffix}"


def _masked_username(username: str) -> str:
    if len(username) <= 3:
        return f"{username[0]}***" if username else "Not set"
    return f"{username[:2]}***{username[-1]}"


def _job_id(post_id: int) -> str:
    return f"{JOB_PREFIX}{post_id}"


def _mark_post_running(post_id: int) -> bool:
    with _running_lock:
        if post_id in _running_post_ids:
            return False
        _running_post_ids.add(post_id)
        return True


def _unmark_post_running(post_id: int) -> None:
    with _running_lock:
        _running_post_ids.discard(post_id)


def _is_post_running(post_id: int) -> bool:
    with _running_lock:
        return post_id in _running_post_ids


def _interruptible_sleep(seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _stop_requested.is_set():
            return
        time.sleep(min(0.5, deadline - time.monotonic()))


def _shutdown_scheduler_instance(scheduler: BackgroundScheduler) -> None:
    try:
        scheduler.pause()
    except SchedulerNotRunningError:
        return
    except Exception as exc:
        logger.debug("Could not pause scheduler during shutdown: %s", exc)

    try:
        scheduler.remove_all_jobs()
    except Exception as exc:
        logger.debug("Could not remove scheduler jobs during shutdown: %s", exc)

    try:
        scheduler.shutdown(wait=False)
    except SchedulerNotRunningError:
        pass
    except RuntimeError as exc:
        logger.debug("Scheduler was already shutting down: %s", exc)

    logger.info("Django scheduler stopped.")


def _shutdown_scheduler_at_exit() -> None:
    global _scheduler

    _stop_requested.set()
    with _scheduler_lock:
        scheduler = _scheduler
        _scheduler = None

    if scheduler is not None:
        _shutdown_scheduler_instance(scheduler)


atexit.register(_shutdown_scheduler_at_exit)
