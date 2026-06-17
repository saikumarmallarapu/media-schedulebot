import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import DATABASE_PATH, MAX_RETRIES
from models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PUBLISHED,
    VALID_STATUSES,
)
from utils import sanitize_error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_path TEXT NOT NULL,
                media_type TEXT NOT NULL
                    CHECK(media_type IN ('{MEDIA_TYPE_IMAGE}', '{MEDIA_TYPE_VIDEO}')),
                caption TEXT NOT NULL DEFAULT '',
                scheduled_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '{STATUS_PENDING}'
                    CHECK(status IN ('{STATUS_PENDING}', '{STATUS_PUBLISHED}', '{STATUS_FAILED}')),
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT {MAX_RETRIES},
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time
            ON scheduled_posts(status, scheduled_time)
            """
        )


def insert_scheduled_post(
    media_path: str,
    media_type: str,
    caption: str,
    scheduled_time: datetime,
    max_retries: int = MAX_RETRIES,
) -> int:
    now = _utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO scheduled_posts (
                media_path,
                media_type,
                caption,
                scheduled_time,
                status,
                retry_count,
                max_retries,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                str(media_path),
                media_type,
                caption,
                scheduled_time.isoformat(timespec="seconds"),
                STATUS_PENDING,
                max_retries,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)


def fetch_all_posts() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM scheduled_posts
                ORDER BY scheduled_time ASC, id ASC
                """
            )
        )


def fetch_pending_posts() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM scheduled_posts
                WHERE status = ?
                ORDER BY scheduled_time ASC, id ASC
                """,
                (STATUS_PENDING,),
            )
        )


def get_post(post_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM scheduled_posts
            WHERE id = ?
            """,
            (post_id,),
        ).fetchone()


def update_post_status(post_id: int, status: str, error: object | None = None) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    now = _utc_now()
    last_error = sanitize_error(error) if error else None
    published_at = now if status == STATUS_PUBLISHED else None

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE scheduled_posts
            SET status = ?,
                last_error = ?,
                updated_at = ?,
                published_at = ?
            WHERE id = ?
            """,
            (status, last_error, now, published_at, post_id),
        )


def record_publish_failure(post_id: int, error: object) -> int:
    now = _utc_now()
    safe_error = sanitize_error(error)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE scheduled_posts
            SET retry_count = retry_count + 1,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (safe_error, now, post_id),
        )
        row = connection.execute(
            """
            SELECT retry_count
            FROM scheduled_posts
            WHERE id = ?
            """,
            (post_id,),
        ).fetchone()

    if row is None:
        return 0
    return int(row["retry_count"])
