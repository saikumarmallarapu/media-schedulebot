from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from constants import STATUS_CANCELLED, STATUS_FAILED, STATUS_PENDING

from .forms import EditScheduledPostForm, RetryPostForm, ScheduledPostForm
from .models import ScheduledPost
from .services import (
    check_instagram_login,
    instagram_connection_status,
    recent_logs,
    refresh_scheduler,
    save_uploaded_media,
    scheduler_status,
    start_scheduler,
    stop_scheduler,
    unschedule_post,
)


def dashboard(request):
    posts = ScheduledPost.objects.all()
    return render(
        request,
        "scheduler_app/dashboard.html",
        _dashboard_context(form=ScheduledPostForm(), posts=posts),
    )


@require_POST
def create_post(request):
    form = ScheduledPostForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "scheduler_app/dashboard.html",
            _dashboard_context(form=form, posts=ScheduledPost.objects.all()),
            status=400,
        )

    media_path = save_uploaded_media(
        form.cleaned_data["media_file"],
        form.cleaned_data["media_type"],
    )
    ScheduledPost.objects.create(
        media_path=str(media_path),
        media_type=form.cleaned_data["media_type"],
        caption=form.cleaned_data["caption"],
        scheduled_time=form.cleaned_data["scheduled_time"],
    )
    refresh_scheduler()
    messages.success(request, "Post added.")
    return redirect("scheduler_app:dashboard")


def edit_post(request, post_id: int):
    post = get_object_or_404(ScheduledPost, pk=post_id)
    if post.status != STATUS_PENDING:
        messages.error(request, "Only pending posts can be edited.")
        return redirect("scheduler_app:dashboard")

    if request.method == "POST":
        form = EditScheduledPostForm(request.POST, request.FILES, post=post)
        if form.is_valid():
            post.media_type = form.cleaned_data["media_type"]
            post.caption = form.cleaned_data["caption"]
            post.scheduled_time = form.cleaned_data["scheduled_time"]

            media_file = form.cleaned_data.get("media_file")
            if media_file:
                post.media_path = str(save_uploaded_media(media_file, post.media_type))

            post.last_error = None
            post.save(
                update_fields=(
                    "media_type",
                    "caption",
                    "scheduled_time",
                    "media_path",
                    "last_error",
                    "updated_at",
                )
            )
            refresh_scheduler()
            messages.success(request, "Post updated.")
            return redirect("scheduler_app:dashboard")
    else:
        form = EditScheduledPostForm(post=post)

    return render(
        request,
        "scheduler_app/edit_post.html",
        {
            "form": form,
            "post": post,
            "scheduler": scheduler_status(),
        },
    )


@require_POST
def cancel_post(request, post_id: int):
    post = get_object_or_404(ScheduledPost, pk=post_id)
    if post.status != STATUS_PENDING:
        messages.error(request, "Only pending posts can be cancelled.")
    else:
        post.cancel()
        unschedule_post(post.pk)
        messages.success(request, "Post cancelled.")
    return redirect("scheduler_app:dashboard")


@require_POST
def retry_post(request, post_id: int):
    post = get_object_or_404(ScheduledPost, pk=post_id)
    if not post.can_retry:
        messages.error(request, "Only failed or cancelled posts can be retried.")
        return redirect("scheduler_app:dashboard")

    form = RetryPostForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Retry time must be in the future.")
        return redirect("scheduler_app:dashboard")

    post.reset_for_retry(form.cleaned_data["scheduled_time"])
    refresh_scheduler()
    messages.success(request, "Post reset to pending.")
    return redirect("scheduler_app:dashboard")


@require_POST
def delete_post(request, post_id: int):
    post = get_object_or_404(ScheduledPost, pk=post_id)
    post.delete()
    unschedule_post(post_id)
    messages.success(request, "Post deleted.")
    return redirect("scheduler_app:dashboard")


@require_POST
def start_scheduler_view(request):
    instagram = instagram_connection_status()
    if not instagram["ready"]:
        if instagram["configured"]:
            messages.error(request, "Check Instagram login before starting the scheduler.")
        else:
            messages.error(request, "Add Instagram username and password in .env first.")
        return redirect("scheduler_app:dashboard")

    scheduled_count = start_scheduler()
    messages.success(request, f"Scheduler running. Loaded {scheduled_count} pending post(s).")
    return redirect("scheduler_app:dashboard")


@require_POST
def refresh_scheduler_view(request):
    scheduled_count = refresh_scheduler()
    messages.success(request, f"Scheduler refreshed. Loaded {scheduled_count} pending post(s).")
    return redirect("scheduler_app:dashboard")


@require_POST
def stop_scheduler_view(request):
    if stop_scheduler():
        messages.success(request, "Scheduler stopped.")
    else:
        messages.info(request, "Scheduler was not running.")
    return redirect("scheduler_app:dashboard")


@require_POST
def check_instagram_view(request):
    try:
        check_instagram_login()
    except Exception as exc:
        messages.error(request, f"Instagram login check failed: {exc}")
    else:
        messages.success(request, "Instagram login is connected and the browser session was saved.")
    return redirect("scheduler_app:dashboard")


def _statuses() -> dict[str, str]:
    return {
        "pending": STATUS_PENDING,
        "failed": STATUS_FAILED,
        "cancelled": STATUS_CANCELLED,
    }


def _dashboard_context(form, posts):
    return {
        "form": form,
        "posts": posts,
        "scheduler": scheduler_status(),
        "logs": recent_logs(),
        "statuses": _statuses(),
        "instagram": instagram_connection_status(),
        "config_warnings": _config_warnings(),
        "pending_count": ScheduledPost.objects.filter(status=STATUS_PENDING).count(),
        "failed_count": ScheduledPost.objects.filter(status=STATUS_FAILED).count(),
    }


def _config_warnings() -> list[str]:
    warnings: list[str] = []
    instagram = instagram_connection_status()
    if not instagram["configured"]:
        warnings.append("Instagram username and password are not set in .env.")
    elif not instagram["session_saved"]:
        warnings.append("Instagram credentials are set, but no saved login session exists yet.")
    return warnings
