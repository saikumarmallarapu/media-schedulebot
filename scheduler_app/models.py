from pathlib import Path

from django.db import models
from django.utils import timezone

from config import MAX_RETRIES
from constants import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PUBLISHED,
)
from utils import sanitize_error


class ScheduledPost(models.Model):
    MEDIA_TYPE_CHOICES = (
        (MEDIA_TYPE_IMAGE, "Image"),
        (MEDIA_TYPE_VIDEO, "Video"),
    )
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    media_path = models.CharField(max_length=1024)
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPE_CHOICES)
    caption = models.TextField(blank=True, default="")
    scheduled_time = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=MAX_RETRIES)
    last_error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "scheduled_posts"
        ordering = ("scheduled_time", "id")
        indexes = [
            models.Index(fields=("status", "scheduled_time"), name="idx_posts_status_time"),
        ]

    def __str__(self) -> str:
        return f"Post {self.pk} - {self.status}"

    def save(self, *args, **kwargs) -> None:
        self.updated_at = timezone.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "updated_at" not in update_fields:
            kwargs["update_fields"] = tuple(update_fields) + ("updated_at",)
        super().save(*args, **kwargs)

    @property
    def can_edit(self) -> bool:
        return self.status == STATUS_PENDING

    @property
    def can_cancel(self) -> bool:
        return self.status == STATUS_PENDING

    @property
    def can_retry(self) -> bool:
        return self.status in {STATUS_FAILED, STATUS_CANCELLED}

    @property
    def media_filename(self) -> str:
        return Path(self.media_path).name

    def mark_published(self) -> None:
        now = timezone.now()
        self.status = STATUS_PUBLISHED
        self.last_error = None
        self.updated_at = now
        self.published_at = now
        self.save(update_fields=("status", "last_error", "updated_at", "published_at"))

    def record_failure(self, error: object) -> int:
        self.retry_count += 1
        self.last_error = sanitize_error(error)
        self.updated_at = timezone.now()
        self.save(update_fields=("retry_count", "last_error", "updated_at"))
        return self.retry_count

    def mark_failed(self, error: object) -> None:
        self.status = STATUS_FAILED
        self.last_error = sanitize_error(error)
        self.updated_at = timezone.now()
        self.published_at = None
        self.save(update_fields=("status", "last_error", "updated_at", "published_at"))

    def cancel(self) -> None:
        self.status = STATUS_CANCELLED
        self.last_error = None
        self.updated_at = timezone.now()
        self.published_at = None
        self.save(update_fields=("status", "last_error", "updated_at", "published_at"))

    def reset_for_retry(self, scheduled_time) -> None:
        self.status = STATUS_PENDING
        self.scheduled_time = scheduled_time
        self.retry_count = 0
        self.last_error = None
        self.updated_at = timezone.now()
        self.published_at = None
        self.save(
            update_fields=(
                "status",
                "scheduled_time",
                "retry_count",
                "last_error",
                "updated_at",
                "published_at",
            )
        )
