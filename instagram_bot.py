import logging
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config import (
    INSTAGRAM_PASSWORD,
    INSTAGRAM_USERNAME,
    PLAYWRIGHT_HEADLESS,
    PUBLISH_TIMEOUT_MS,
    SESSION_STATE_PATH,
)
from utils import sanitize_error, validate_media_file


logger = logging.getLogger(__name__)


class InstagramPublishError(RuntimeError):
    pass


class InstagramBot:
    HOME_URL = "https://www.instagram.com/"
    LOGIN_URL = "https://www.instagram.com/accounts/login/"
    CREATE_URL = "https://www.instagram.com/create/select/"

    def __init__(
        self,
        username: str = INSTAGRAM_USERNAME,
        password: str = INSTAGRAM_PASSWORD,
        headless: bool = PLAYWRIGHT_HEADLESS,
    ) -> None:
        self.username = username
        self.password = password
        self.headless = headless

    def publish_post(self, media_path: str | Path, media_type: str, caption: str = "") -> None:
        if not self.username or not self.password:
            raise InstagramPublishError("Instagram username and password must be set in .env.")

        media_file = validate_media_file(media_path, media_type)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(60000)

            try:
                self._ensure_logged_in(page, context)
                self._publish_from_page(page, media_file, caption)
            except InstagramPublishError:
                raise
            except Exception as exc:
                raise InstagramPublishError(sanitize_error(exc)) from exc
            finally:
                context.close()
                browser.close()

    def _new_context(self, browser):
        context_options = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-US",
        }
        if SESSION_STATE_PATH.exists():
            context_options["storage_state"] = str(SESSION_STATE_PATH)

        try:
            return browser.new_context(**context_options)
        except Exception:
            context_options.pop("storage_state", None)
            return browser.new_context(**context_options)

    def _ensure_logged_in(self, page, context) -> None:
        page.goto(self.HOME_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)

        if self._is_logged_in(page):
            self._save_storage_state(context)
            return

        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)
        page.locator("input[name='username']").fill(self.username)
        page.locator("input[name='password']").fill(self.password)
        page.locator("button[type='submit']").click()

        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except PlaywrightTimeoutError:
            pass

        self._handle_optional_dialogs(page)
        self._raise_for_login_errors(page)

        if not self._is_logged_in(page):
            raise InstagramPublishError(
                "Instagram login did not complete. Check credentials, 2FA, captcha, or account challenge prompts."
            )

        self._save_storage_state(context)

    def _publish_from_page(self, page, media_file: Path, caption: str) -> None:
        self._open_create_dialog(page)
        page.locator("input[type='file']").first.wait_for(state="attached", timeout=60000)
        page.locator("input[type='file']").first.set_input_files(str(media_file))

        self._click_optional_buttons(page, ["OK", "Ok"])
        self._click_named_button(page, "Next", timeout=120000)
        self._click_optional_buttons(page, ["OK", "Ok"])
        self._click_named_button(page, "Next", timeout=120000)

        if caption:
            self._fill_caption(page, caption)

        self._click_named_button(page, "Share", timeout=120000)
        self._wait_for_publish_result(page)

    def _open_create_dialog(self, page) -> None:
        page.goto(self.HOME_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)

        selectors = [
            "a[href='/create/select/']",
            "svg[aria-label='New post']",
            "div[role='button']:has-text('Create')",
            "span:has-text('Create')",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.click(timeout=5000)
                self._click_optional_buttons(page, ["Post"])
                return
            except PlaywrightTimeoutError:
                continue

        page.goto(self.CREATE_URL, wait_until="domcontentloaded")

    def _is_logged_in(self, page) -> bool:
        selectors = [
            "a[href='/direct/inbox/']",
            "a[href='/create/select/']",
            "svg[aria-label='New post']",
            "span:has-text('Create')",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=3000)
                return True
            except PlaywrightTimeoutError:
                continue
        return False

    def _raise_for_login_errors(self, page) -> None:
        error_texts = [
            "Sorry, your password was incorrect",
            "Please check your username",
            "The username you entered",
            "challenge",
            "two-factor",
            "Two-factor",
            "Suspicious Login Attempt",
        ]
        page_text = ""
        try:
            page_text = page.locator("body").inner_text(timeout=3000)
        except PlaywrightTimeoutError:
            return

        for error_text in error_texts:
            if error_text.lower() in page_text.lower():
                raise InstagramPublishError(
                    "Instagram login requires attention before automation can continue."
                )

    def _fill_caption(self, page, caption: str) -> None:
        selectors = [
            "div[aria-label='Write a caption...'][contenteditable='true']",
            "textarea[aria-label='Write a caption...']",
            "div[role='textbox'][contenteditable='true']",
            "div[contenteditable='true']",
        ]

        for selector in selectors:
            try:
                caption_box = page.locator(selector).first
                caption_box.wait_for(state="visible", timeout=10000)
                caption_box.click()
                try:
                    caption_box.fill(caption)
                except Exception:
                    page.keyboard.insert_text(caption)
                return
            except PlaywrightTimeoutError:
                continue

        raise InstagramPublishError("Could not find the Instagram caption input.")

    def _wait_for_publish_result(self, page) -> None:
        success_texts = [
            "Your post has been shared.",
            "Your reel has been shared.",
            "Post shared",
            "Reel shared",
        ]
        failure_texts = [
            "Something went wrong",
            "Couldn't share your post",
            "Could not upload",
            "Try again",
        ]
        deadline = time.monotonic() + (PUBLISH_TIMEOUT_MS / 1000)

        while time.monotonic() < deadline:
            body_text = ""
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(1000)
                continue

            lower_text = body_text.lower()
            if any(success.lower() in lower_text for success in success_texts):
                return
            for failure in failure_texts:
                if failure.lower() in lower_text:
                    raise InstagramPublishError(f"Instagram publish failed: {failure}")

            page.wait_for_timeout(1000)

        raise InstagramPublishError("Timed out waiting for Instagram to confirm publishing.")

    def _handle_optional_dialogs(self, page) -> None:
        self._click_optional_buttons(
            page,
            [
                "Allow all cookies",
                "Accept all",
                "Not Now",
                "Not now",
                "Dismiss",
            ],
        )

    def _click_optional_buttons(self, page, names: list[str]) -> None:
        for name in names:
            try:
                self._button_locator(page, name).click(timeout=2500)
                page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                continue

    def _click_named_button(self, page, name: str, timeout: int = 60000) -> None:
        try:
            self._button_locator(page, name).click(timeout=timeout)
            page.wait_for_timeout(1000)
            return
        except PlaywrightTimeoutError as exc:
            raise InstagramPublishError(f"Could not click Instagram button: {name}") from exc

    def _button_locator(self, page, name: str):
        exact_name = re.compile(f"^{re.escape(name)}$", re.IGNORECASE)
        return page.get_by_role("button", name=exact_name).or_(
            page.get_by_text(exact_name, exact=True)
        ).first

    def _save_storage_state(self, context) -> None:
        SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            context.storage_state(path=str(SESSION_STATE_PATH))
        except Exception as exc:
            logger.warning("Could not save Instagram browser session: %s", sanitize_error(exc))
