from django.contrib import admin

from .models import ScheduledPost


@admin.register(ScheduledPost)
class ScheduledPostAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "media_type",
        "scheduled_time",
        "status",
        "retry_count",
        "max_retries",
        "created_at",
        "published_at",
    )
    list_filter = ("status", "media_type")
    search_fields = ("caption", "media_path", "last_error")
    readonly_fields = ("created_at", "updated_at", "published_at")
    ordering = ("scheduled_time", "id")
