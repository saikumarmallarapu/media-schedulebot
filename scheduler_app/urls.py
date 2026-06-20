from django.urls import path

from . import views


app_name = "scheduler_app"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("posts/", views.create_post, name="create_post"),
    path("posts/<int:post_id>/edit/", views.edit_post, name="edit_post"),
    path("posts/<int:post_id>/cancel/", views.cancel_post, name="cancel_post"),
    path("posts/<int:post_id>/retry/", views.retry_post, name="retry_post"),
    path("posts/<int:post_id>/delete/", views.delete_post, name="delete_post"),
    path("scheduler/start/", views.start_scheduler_view, name="start_scheduler"),
    path("scheduler/refresh/", views.refresh_scheduler_view, name="refresh_scheduler"),
    path("scheduler/stop/", views.stop_scheduler_view, name="stop_scheduler"),
    path("instagram/check/", views.check_instagram_view, name="check_instagram"),
]
