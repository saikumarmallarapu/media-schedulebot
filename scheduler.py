import logging
import threading
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from database import (
    fetch_pending_posts,
    get_post,
    record_publish_failure,
    update_post_status,
)
from instagram_bot import InstagramBot
from models import STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED
from utils import get_timezone, sanitize_error


logger = logging.getLogger(__name__)
JOB_PREFIX = "instagram_post_"

_running_lock = threading.Lock()
_running_post_ids: set[int] = set()


def create_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(
        timezone=get_timezone(),
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": None,
        },
    )


def schedule_pending_posts(scheduler: BackgroundScheduler) -> int:
    timezone = get_timezone()
    now = datetime.now(timezone)
    scheduled_count = 0

    for post in fetch_pending_posts():
        post_id = int(post["id"])
        if _is_post_running(post_id):
            continue

        run_time = _parse_scheduled_time(post["scheduled_time"])
        if run_time <= now:
            run_time = now + timedelta(seconds=1)

        scheduler.add_job(
            publish_scheduled_post,
            trigger="date",
            run_date=run_time,
            args=[post_id],
            id=_job_id(post_id),
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=None,
        )
        scheduled_count += 1

    return scheduled_count


def publish_scheduled_post(post_id: int) -> None:
    if not _mark_post_running(post_id):
        logger.info("Post %s is already publishing; skipping duplicate trigger.", post_id)
        return

    try:
        post = get_post(post_id)
        if post is None:
            logger.warning("Scheduled post %s no longer exists.", post_id)
            return
        if post["status"] != STATUS_PENDING:
            logger.info("Scheduled post %s is already %s.", post_id, post["status"])
            return

        max_retries = max(1, int(post["max_retries"]))
        retry_count = int(post["retry_count"])

        while retry_count < max_retries:
            try:
                logger.info(
                    "Publishing Instagram post %s, attempt %s of %s.",
                    post_id,
                    retry_count + 1,
                    max_retries,
                )
                InstagramBot().publish_post(
                    media_path=post["media_path"],
                    media_type=post["media_type"],
                    caption=post["caption"] or "",
                )
                update_post_status(post_id, STATUS_PUBLISHED)
                logger.info("Published Instagram post %s.", post_id)
                return
            except Exception as exc:
                safe_error = sanitize_error(exc)
                retry_count = record_publish_failure(post_id, safe_error)
                logger.exception("Publishing post %s failed: %s", post_id, safe_error)

                if retry_count >= max_retries:
                    update_post_status(post_id, STATUS_FAILED, safe_error)
                    logger.error("Post %s marked failed after %s attempts.", post_id, retry_count)
                    return

                time.sleep(min(60, 2**retry_count))
    finally:
        _unmark_post_running(post_id)


def run_scheduler_forever() -> None:
    scheduler = create_scheduler()
    initial_count = schedule_pending_posts(scheduler)
    scheduler.add_job(
        schedule_pending_posts,
        trigger="interval",
        minutes=1,
        args=[scheduler],
        id="load_pending_instagram_posts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Scheduler started with %s pending post(s).", initial_count)

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping scheduler.")
        scheduler.shutdown(wait=False)


def _parse_scheduled_time(value: str) -> datetime:
    timezone = get_timezone()
    scheduled_at = datetime.fromisoformat(value)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone)
    return scheduled_at.astimezone(timezone)


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
