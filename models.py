STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"

VALID_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_PUBLISHED,
        STATUS_FAILED,
    }
)

MEDIA_TYPE_IMAGE = "image"
MEDIA_TYPE_VIDEO = "video"

VALID_MEDIA_TYPES = frozenset(
    {
        MEDIA_TYPE_IMAGE,
        MEDIA_TYPE_VIDEO,
    }
)

ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})
ALLOWED_VIDEO_EXTENSIONS = frozenset({"mp4", "mov"})


def normalize_media_type(value: str) -> str:
    media_type = value.strip().lower()
    if media_type not in VALID_MEDIA_TYPES:
        raise ValueError("Media type must be image or video.")
    return media_type
