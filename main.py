import logging

from database import fetch_all_posts, init_db, insert_scheduled_post
from models import MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO
from scheduler import run_scheduler_forever
from utils import (
    ensure_project_directories,
    parse_scheduled_datetime,
    setup_logging,
    store_media_file,
    validate_media_type,
)


logger = logging.getLogger(__name__)


def main() -> None:
    ensure_project_directories()
    setup_logging()
    init_db()

    while True:
        print("\nInstagram Post Scheduler")
        print("1. Add scheduled post")
        print("2. View scheduled posts")
        print("3. Start scheduler")
        print("4. Exit")

        choice = input("Select option: ").strip()

        if choice == "1":
            add_scheduled_post()
        elif choice == "2":
            view_scheduled_posts()
        elif choice == "3":
            print("Scheduler running. Press Ctrl+C to stop.")
            run_scheduler_forever()
        elif choice == "4":
            print("Goodbye.")
            break
        else:
            print("Invalid option. Choose 1, 2, 3, or 4.")


def add_scheduled_post() -> None:
    media_path = input("Enter media path: ").strip().strip('"')
    media_type = input(f"Select media type ({MEDIA_TYPE_IMAGE}/{MEDIA_TYPE_VIDEO}): ").strip()
    caption = input("Enter caption: ")
    scheduled_value = input("Enter schedule datetime (YYYY-MM-DD HH:MM): ").strip()

    try:
        normalized_media_type = validate_media_type(media_type)
        scheduled_at = parse_scheduled_datetime(scheduled_value)
        stored_media_path = store_media_file(media_path, normalized_media_type)
        post_id = insert_scheduled_post(
            media_path=str(stored_media_path),
            media_type=normalized_media_type,
            caption=caption,
            scheduled_time=scheduled_at,
        )
        print(f"Scheduled post saved with ID {post_id}.")
        logger.info("Scheduled post %s for %s.", post_id, scheduled_at.isoformat())
    except Exception as exc:
        print(f"Could not add post: {exc}")
        logger.warning("Could not add scheduled post: %s", exc)


def view_scheduled_posts() -> None:
    posts = fetch_all_posts()
    if not posts:
        print("No scheduled posts found.")
        return

    print(
        f"{'ID':<5} {'Type':<7} {'Scheduled Time':<25} {'Status':<10} "
        f"{'Retries':<8} {'Caption':<32} Media Path"
    )
    print("-" * 120)
    for post in posts:
        caption = post["caption"] or ""
        caption_preview = caption if len(caption) <= 29 else f"{caption[:29]}..."
        retries = f"{post['retry_count']}/{post['max_retries']}"
        print(
            f"{post['id']:<5} {post['media_type']:<7} {post['scheduled_time']:<25} "
            f"{post['status']:<10} {retries:<8} {caption_preview:<32} {post['media_path']}"
        )


if __name__ == "__main__":
    main()
