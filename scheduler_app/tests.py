import os
import unittest
from datetime import timedelta

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise unittest.SkipTest("Run Django tests with python manage.py test.")

from apscheduler.schedulers.background import BackgroundScheduler
from django.test import TestCase
from django.utils import timezone

from constants import STATUS_CANCELLED, STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED

from .models import ScheduledPost
from .services import PAST_SCHEDULE_ERROR, schedule_pending_posts


class ScheduledPostModelTests(TestCase):
    def test_status_lifecycle_helpers(self) -> None:
        post = ScheduledPost.objects.create(
            media_path="media/images/test.jpg",
            media_type="image",
            caption="Caption",
            scheduled_time=timezone.now() + timedelta(days=1),
        )

        self.assertEqual(post.status, STATUS_PENDING)

        post.cancel()
        post.refresh_from_db()
        self.assertEqual(post.status, STATUS_CANCELLED)

        retry_time = timezone.now() + timedelta(hours=2)
        post.reset_for_retry(retry_time)
        post.refresh_from_db()
        self.assertEqual(post.status, STATUS_PENDING)
        self.assertEqual(post.retry_count, 0)

        retry_count = post.record_failure("Failed once")
        post.refresh_from_db()
        self.assertEqual(retry_count, 1)
        self.assertIn("Failed once", post.last_error)

        post.mark_failed("Final failure")
        post.refresh_from_db()
        self.assertEqual(post.status, STATUS_FAILED)

        post.mark_published()
        post.refresh_from_db()
        self.assertEqual(post.status, STATUS_PUBLISHED)
        self.assertIsNotNone(post.published_at)


class SchedulerRuleTests(TestCase):
    def test_past_pending_post_is_not_queued(self) -> None:
        post = ScheduledPost.objects.create(
            media_path="media/images/test.jpg",
            media_type="image",
            caption="Past post",
            scheduled_time=timezone.now() - timedelta(minutes=1),
        )
        scheduler = BackgroundScheduler(timezone=timezone.get_current_timezone())

        scheduled_count = schedule_pending_posts(scheduler)

        post.refresh_from_db()
        self.assertEqual(scheduled_count, 0)
        self.assertEqual(len(scheduler.get_jobs()), 0)
        self.assertEqual(post.status, STATUS_FAILED)
        self.assertEqual(post.last_error, PAST_SCHEDULE_ERROR)

    def test_future_pending_post_is_queued(self) -> None:
        post = ScheduledPost.objects.create(
            media_path="media/images/test.jpg",
            media_type="image",
            caption="Future post",
            scheduled_time=timezone.now() + timedelta(minutes=5),
        )
        scheduler = BackgroundScheduler(timezone=timezone.get_current_timezone())

        scheduled_count = schedule_pending_posts(scheduler)

        post.refresh_from_db()
        self.assertEqual(scheduled_count, 1)
        self.assertEqual(len(scheduler.get_jobs()), 1)
        self.assertEqual(post.status, STATUS_PENDING)
