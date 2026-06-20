import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import utils


class UtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.original_media_dir = utils.MEDIA_DIR
        self.original_log_file = utils.LOG_FILE
        self.original_timezone = utils.TIMEZONE
        utils.MEDIA_DIR = self.root / "media"
        utils.LOG_FILE = self.root / "logs" / "app.log"
        utils.TIMEZONE = "UTC"

    def tearDown(self) -> None:
        utils.MEDIA_DIR = self.original_media_dir
        utils.LOG_FILE = self.original_log_file
        utils.TIMEZONE = self.original_timezone
        self.temp_dir.cleanup()

    def test_store_media_file_copies_images_into_media_folder(self) -> None:
        source = self.root / "source.jpg"
        source.write_bytes(b"fake image")

        stored_path = utils.store_media_file(source, "image")

        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path.parent, utils.MEDIA_DIR / "images")
        self.assertEqual(stored_path.read_bytes(), b"fake image")

    def test_validate_media_file_rejects_wrong_extension(self) -> None:
        source = self.root / "clip.mp4"
        source.write_bytes(b"fake video")

        with self.assertRaisesRegex(ValueError, "Image file must be one of"):
            utils.validate_media_file(source, "image")

    def test_parse_scheduled_datetime_uses_configured_timezone(self) -> None:
        future_value = (datetime.now(ZoneInfo("UTC")) + timedelta(days=1)).strftime(
            "%Y-%m-%d %H:%M"
        )

        scheduled_at = utils.parse_scheduled_datetime(future_value)

        self.assertEqual(scheduled_at.tzinfo, ZoneInfo("UTC"))
