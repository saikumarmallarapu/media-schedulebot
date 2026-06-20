from datetime import timedelta

from django import forms
from django.utils import timezone

from constants import MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO

from .models import ScheduledPost
from .services import validate_upload_extension


class ScheduledPostForm(forms.Form):
    media_file = forms.FileField(required=True)
    media_type = forms.ChoiceField(choices=ScheduledPost.MEDIA_TYPE_CHOICES)
    caption = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    scheduled_time = forms.DateTimeField(
        input_formats=("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"),
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    def clean_scheduled_time(self):
        scheduled_time = self.cleaned_data["scheduled_time"]
        if scheduled_time <= timezone.now():
            raise forms.ValidationError("Scheduled time must be in the future.")
        return scheduled_time

    def clean(self):
        cleaned_data = super().clean()
        media_file = cleaned_data.get("media_file")
        media_type = cleaned_data.get("media_type")
        if media_file and media_type:
            try:
                validate_upload_extension(media_file.name, media_type)
            except ValueError as exc:
                self.add_error("media_file", str(exc))
        return cleaned_data


class EditScheduledPostForm(ScheduledPostForm):
    media_file = forms.FileField(required=False)

    def __init__(self, *args, **kwargs):
        self.post = kwargs.pop("post")
        super().__init__(*args, **kwargs)
        self.fields["media_type"].initial = self.post.media_type
        self.fields["caption"].initial = self.post.caption
        self.fields["scheduled_time"].initial = self.post.scheduled_time

    def clean(self):
        cleaned_data = super().clean()
        media_file = cleaned_data.get("media_file")
        media_type = cleaned_data.get("media_type")
        if not media_file and media_type and media_type != self.post.media_type:
            expected_extensions = {
                MEDIA_TYPE_IMAGE: "jpg, jpeg, png",
                MEDIA_TYPE_VIDEO: "mp4, mov",
            }
            raise forms.ValidationError(
                f"Upload a new {media_type} file when changing media type. "
                f"Expected: {expected_extensions[media_type]}."
            )
        return cleaned_data


class RetryPostForm(forms.Form):
    scheduled_time = forms.DateTimeField(
        required=False,
        input_formats=("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"),
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    def clean_scheduled_time(self):
        scheduled_time = self.cleaned_data.get("scheduled_time")
        if scheduled_time is None:
            return timezone.now() + timedelta(minutes=1)
        if scheduled_time <= timezone.now():
            raise forms.ValidationError("Retry time must be in the future.")
        return scheduled_time
