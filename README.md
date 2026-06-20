# Instagram Media ScheduleBot

A single Django app for scheduling Instagram image and video posts. It stores scheduled posts in SQLite, uploads media into local project folders, runs an APScheduler background scheduler from the web dashboard, and publishes through Instagram Web with Playwright.

## Project Status

Status: Django web app prototype.

Implemented:

- Django dashboard for scheduled posts
- Add image or video posts with file upload
- Edit pending posts
- Cancel pending posts
- Retry failed or cancelled posts
- Delete post records
- Start, refresh, and stop the scheduler from the browser
- SQLite-backed `ScheduledPost` Django model
- Migration that can use the existing `scheduled_posts` table
- Recent log display on the dashboard
- Playwright Instagram publishing service
- Django admin registration
- Basic Django and utility tests

Needs attention before production:

- Instagram login can require 2FA, captcha, or account challenge approval
- Instagram UI changes can break Playwright selectors
- The scheduler runs inside the Django process, so keep the server running
- Live Instagram publishing is not covered by automated tests
- Use a strong `DJANGO_SECRET_KEY` and protect `.env`

## Requirements

- Python 3.10+
- Django 4.2
- Playwright Chromium browser
- Instagram account credentials

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright Chromium:

```bash
python -m playwright install chromium
```

Create `.env` in the project root:

```env
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_PASSWORD=your_instagram_password
TIMEZONE=Asia/Kolkata
DATABASE_PATH=schedulebot.db
MEDIA_DIR=media
LOG_FILE=logs/app.log
SESSION_STATE_PATH=.instagram_session.json
PLAYWRIGHT_HEADLESS=false
PUBLISH_TIMEOUT_MS=180000
MAX_RETRIES=3
DJANGO_SECRET_KEY=change-this-local-secret
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
```

Apply database migrations:

```bash
python manage.py migrate
```

## Run

Start the Django web app:

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000
```

You can also run:

```bash
python main.py
```

## Connect Instagram

Set these values in `.env`:

```env
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_PASSWORD=your_instagram_password
PLAYWRIGHT_HEADLESS=false
```

Then restart Django and open the dashboard. Use **Check Instagram Login** first. This opens Instagram in a browser, logs in, and saves the browser session to `.instagram_session.json`. It does not publish a post.

After the login check succeeds:

1. Upload an image or video in **Schedule New Post**.
2. Pick a future **Publish Time**.
3. Click **Save Scheduled Post**.
4. Click **Start Scheduler**.

Keep the Django server running when posts are due.

## How It Works

1. Django loads `media_schedulebot.settings`.
2. `scheduler_app` renders the dashboard and handles post forms/actions.
3. Uploaded media is saved under `media/images` or `media/videos`.
4. Scheduled posts are stored in the `scheduled_posts` table.
5. Starting the scheduler loads pending posts into APScheduler.
6. When a post is due, `scheduler_app.services.publish_scheduled_post` calls `InstagramBot`.
7. `instagram_bot.py` opens Instagram Web with Playwright, logs in, uploads media, fills the caption, and publishes.
8. The Django model updates status to `published` or `failed`.

## Supported Media

Images:

- `.jpg`
- `.jpeg`
- `.png`

Videos:

- `.mp4`
- `.mov`

## Main Files

- `manage.py` - Django command entry point
- `main.py` - convenience entry point that starts Django by default
- `media_schedulebot/settings.py` - Django settings
- `media_schedulebot/urls.py` - root URL routing
- `scheduler_app/models.py` - Django scheduled post model
- `scheduler_app/forms.py` - add, edit, and retry forms
- `scheduler_app/views.py` - dashboard and post actions
- `scheduler_app/services.py` - media storage, scheduler control, publishing
- `scheduler_app/migrations/0001_initial.py` - database setup/migration
- `constants.py` - shared status, media type, and extension constants
- `instagram_bot.py` - Playwright Instagram automation
- `utils.py` - shared validation/logging helpers
- `config.py` - environment variable configuration

## Tests

Run Django tests:

```bash
python manage.py test
```

Run utility tests:

```bash
python -m unittest discover tests
```

Run syntax checks:

```bash
python -m compileall manage.py main.py media_schedulebot scheduler_app instagram_bot.py constants.py utils.py config.py tests
```

## Notes

For the first Instagram login, keep:

```env
PLAYWRIGHT_HEADLESS=false
```

This lets you handle login prompts, 2FA, captcha, or challenge approvals in the visible browser.

For production-grade publishing, the official Meta Graph API is more stable than browser automation.
