import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
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
                self._close_browser(context, browser)

    def verify_login(self) -> None:
        if not self.username or not self.password:
            raise InstagramPublishError("Instagram username and password must be set in .env.")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(60000)

            try:
                self._ensure_logged_in(page, context)
            except InstagramPublishError:
                raise
            except Exception as exc:
                raise InstagramPublishError(sanitize_error(exc)) from exc
            finally:
                self._close_browser(context, browser)

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

        self._wait_for_login_completion(page)
        self._save_storage_state(context)

    def _wait_for_login_completion(self, page) -> None:
        deadline = time.monotonic() + max(60, PUBLISH_TIMEOUT_MS / 1000)

        while time.monotonic() < deadline:
            self._handle_optional_dialogs(page)
            self._raise_for_login_errors(page)
            if self._is_logged_in(page, timeout=1000):
                return
            page.wait_for_timeout(1500)

        raise InstagramPublishError(
            "Instagram login did not complete. Complete any 2FA, captcha, or account challenge in the browser and retry."
        )

    def _publish_from_page(self, page, media_file: Path, caption: str) -> None:
        self._open_create_dialog(page)
        page.locator("input[type='file']").first.wait_for(state="attached", timeout=60000)
        page.locator("input[type='file']").first.set_input_files(str(media_file))

        self._advance_to_share_step(page)

        if caption:
            if not self._fill_caption(page, caption):
                logger.warning(
                    "Instagram caption input was not found; publishing without caption."
                )

        self._click_share_button(page, timeout=120000)
        self._wait_for_publish_result(page, share_clicked=True)

    def _open_create_dialog(self, page) -> None:
        page.goto(self.HOME_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)

        page.goto(self.CREATE_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)
        if self._file_input_ready(page):
            return

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
                if self._file_input_ready(page):
                    return
            except PlaywrightTimeoutError:
                continue

        page.goto(self.CREATE_URL, wait_until="domcontentloaded")
        self._handle_optional_dialogs(page)

    def _file_input_ready(self, page, timeout: int = 5000) -> bool:
        try:
            page.locator("input[type='file']").first.wait_for(state="attached", timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    def _advance_to_share_step(self, page) -> None:
        for _ in range(4):
            self._click_optional_buttons(page, ["OK", "Ok"])
            if self._is_share_button_visible(page, timeout=2500):
                return
            if self._is_named_button_visible(page, "Next", timeout=30000):
                self._click_named_button(page, "Next", timeout=120000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1500)
                continue
            break

        if not self._is_share_button_visible(page, timeout=10000):
            raise InstagramPublishError("Could not reach the Instagram Share step.")

    def _is_logged_in(self, page, timeout: int = 3000) -> bool:
        selectors = [
            "a[href='/direct/inbox/']",
            "a[href='/create/select/']",
            "svg[aria-label='New post']",
            "span:has-text('Create')",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=timeout)
                return True
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError as exc:
                if self._is_target_closed_error(exc):
                    raise InstagramPublishError(
                        "Instagram browser closed before login check finished."
                    ) from exc
                continue
        return False

    def _raise_for_login_errors(self, page) -> None:
        error_texts = [
            "Sorry, your password was incorrect",
            "Please check your username",
            "The username you entered",
        ]
        page_text = ""
        try:
            page_text = page.locator("body").inner_text(timeout=3000)
        except PlaywrightTimeoutError:
            return
        except PlaywrightError as exc:
            if self._is_target_closed_error(exc):
                raise InstagramPublishError(
                    "Instagram browser closed before login check finished."
                ) from exc
            return

        for error_text in error_texts:
            if error_text.lower() in page_text.lower():
                raise InstagramPublishError(
                    "Instagram login requires attention before automation can continue."
                )

    def _fill_caption(self, page, caption: str) -> bool:
        selectors = [
            "textarea[placeholder*='caption' i]",
            "textarea[aria-label='Write a caption...']",
            "textarea",
            "[aria-label*='caption' i][contenteditable='true']",
            "[placeholder*='caption' i][contenteditable='true']",
            "[role='textbox'][contenteditable='true']",
            "[role='textbox']",
            "div[contenteditable='true']",
        ]

        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 5)
            except PlaywrightError:
                continue

            for index in range(count):
                caption_box = locator.nth(index)
                if not self._looks_like_editable_caption(caption_box):
                    continue
                try:
                    caption_box.click(timeout=5000)
                    try:
                        caption_box.fill(caption, timeout=5000)
                    except PlaywrightError:
                        page.keyboard.press("Control+A")
                        page.keyboard.insert_text(caption)
                    return True
                except PlaywrightError:
                    continue

        return False

    def _looks_like_editable_caption(self, locator) -> bool:
        try:
            if not locator.is_visible():
                return False
            box = locator.bounding_box()
        except PlaywrightError:
            return False

        if not box:
            return False
        return box["width"] >= 80 and box["height"] >= 16

    def _wait_for_publish_result(self, page, share_clicked: bool = False) -> None:
        success_texts = [
            "Your post has been shared.",
            "Your reel has been shared.",
            "Post shared",
            "Reel shared",
            "has been shared",
        ]
        failure_texts = [
            "Something went wrong",
            "Couldn't share your post",
            "Could not upload",
            "Try again",
        ]
        progress_texts = [
            "sharing",
            "posting",
            "uploading",
            "processing",
        ]
        deadline = time.monotonic() + (PUBLISH_TIMEOUT_MS / 1000)
        dialog_success_deadline = time.monotonic() + 12

        while time.monotonic() < deadline:
            body_text = ""
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(1000)
                continue
            except PlaywrightError as exc:
                if share_clicked and self._is_target_closed_error(exc):
                    logger.info(
                        "Instagram page closed after Share was clicked; treating post as submitted."
                    )
                    return
                raise InstagramPublishError(
                    "Instagram browser closed before publish confirmation finished."
                ) from exc

            lower_text = body_text.lower()
            if any(success.lower() in lower_text for success in success_texts):
                return
            for failure in failure_texts:
                if failure.lower() in lower_text:
                    raise InstagramPublishError(f"Instagram publish failed: {failure}")
            if any(progress in lower_text for progress in progress_texts):
                page.wait_for_timeout(1000)
                continue

            if (
                share_clicked
                and time.monotonic() >= dialog_success_deadline
                and self._publish_dialog_is_gone(page, lower_text)
            ):
                logger.info(
                    "Instagram publish dialog closed after Share was clicked; treating post as submitted."
                )
                return

            page.wait_for_timeout(1000)

        if share_clicked:
            logger.warning(
                "Timed out waiting for Instagram confirmation after Share was clicked; "
                "treating the post as submitted to avoid duplicate retries."
            )
            return

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
                if self._click_named_action_if_ready(page, name):
                    page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError as exc:
                if "Target page, context or browser has been closed" in str(exc):
                    raise InstagramPublishError(
                        "Instagram browser closed before login or publishing finished."
                    ) from exc
                continue

    def _click_named_button(self, page, name: str, timeout: int = 60000) -> None:
        deadline = time.monotonic() + (timeout / 1000)
        last_error = None

        while time.monotonic() < deadline:
            try:
                if self._click_named_action_if_ready(page, name):
                    page.wait_for_timeout(1000)
                    return
            except PlaywrightError as exc:
                last_error = exc
            page.wait_for_timeout(500)

        raise InstagramPublishError(f"Could not click Instagram button: {name}") from last_error

    def _click_share_button(self, page, timeout: int = 60000) -> None:
        deadline = time.monotonic() + (timeout / 1000)
        last_result = None

        while time.monotonic() < deadline:
            try:
                last_result = self._click_exact_visible_text(page, "Share", prefer_top_right=True)
                if last_result and last_result.get("clicked"):
                    logger.info("Clicked Instagram Share action.")
                    page.wait_for_timeout(1000)
                    return
            except PlaywrightError:
                pass
            page.wait_for_timeout(500)

        raise InstagramPublishError(
            f"Could not click Instagram Share action. Last result: {last_result}"
        )

    def _is_share_button_visible(self, page, timeout: int = 3000) -> bool:
        deadline = time.monotonic() + (timeout / 1000)
        while time.monotonic() < deadline:
            if self._exact_visible_text_exists(page, "Share", prefer_top_right=True):
                return True
            page.wait_for_timeout(250)
        return False

    def _is_named_button_visible(self, page, name: str, timeout: int = 3000) -> bool:
        deadline = time.monotonic() + (timeout / 1000)
        while time.monotonic() < deadline:
            if self._visible_named_action(page, name) is not None:
                return True
            page.wait_for_timeout(250)
        return False

    def _click_named_action_if_ready(self, page, name: str) -> bool:
        action = self._visible_named_action(page, name)
        if action is None:
            return False
        action.click(timeout=5000)
        return True

    def _visible_named_action(self, page, name: str):
        for locator in self._named_action_locators(page, name):
            try:
                count = min(locator.count(), 8)
            except PlaywrightError:
                continue

            for index in range(count):
                candidate = locator.nth(index)
                if self._looks_clickable(candidate):
                    return candidate
        return None

    def _named_action_locators(self, page, name: str):
        exact_name = re.compile(f"^{re.escape(name)}$", re.IGNORECASE)
        partial_name = re.compile(re.escape(name), re.IGNORECASE)
        return [
            page.get_by_role("button", name=exact_name),
            page.get_by_role("link", name=exact_name),
            page.locator("button", has_text=exact_name),
            page.locator("a", has_text=exact_name),
            page.locator("[role='button']", has_text=exact_name),
            page.locator("[role='link']", has_text=exact_name),
            page.locator("span", has_text=exact_name),
            page.locator("div", has_text=exact_name),
            page.locator("button, a, [role='button'], [role='link'], span, div", has_text=partial_name),
        ]

    def _looks_clickable(self, locator) -> bool:
        try:
            if not locator.is_visible():
                return False
            box = locator.bounding_box()
        except PlaywrightError:
            return False

        if not box:
            return False
        return box["width"] >= 8 and box["height"] >= 8

    def _exact_visible_text_exists(
        self,
        page,
        text: str,
        prefer_top_right: bool = False,
    ) -> bool:
        result = page.evaluate(
            """
            ({ text, preferTopRight }) => {
              const candidate = findExactVisibleTextAction(text, preferTopRight);
              return Boolean(candidate);

              function findExactVisibleTextAction(targetText, preferTopRight) {
                const ignoredTags = new Set(["TITLE", "SVG", "PATH", "SCRIPT", "STYLE"]);
                const selectors = "button, a, [role='button'], [role='link'], span, div";
                const candidates = Array.from(document.querySelectorAll(selectors))
                  .filter((element) => {
                    if (ignoredTags.has(element.tagName)) return false;
                    const value = (element.innerText || element.textContent || "").trim();
                    return value === targetText && isVisible(element);
                  })
                  .map((element) => scoreElement(element, preferTopRight));

                candidates.sort((left, right) => left.score - right.score);
                return candidates[0]?.element || null;
              }

              function isVisible(element) {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return (
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity || 1) > 0 &&
                  rect.width > 0 &&
                  rect.height > 0
                );
              }

              function scoreElement(element, preferTopRight) {
                const rect = element.getBoundingClientRect();
                const role = (element.getAttribute("role") || "").toLowerCase();
                let score = rect.width * rect.height;

                if (element.tagName === "BUTTON" || element.tagName === "A") score -= 10000;
                if (role === "button" || role === "link") score -= 9000;
                if (preferTopRight) {
                  score += Math.max(0, window.innerWidth * 0.55 - rect.left) * 200;
                  score += Math.max(0, rect.top - window.innerHeight * 0.45) * 100;
                }
                return { element, score };
              }
            }
            """,
            {"text": text, "preferTopRight": prefer_top_right},
        )
        return bool(result)

    def _click_exact_visible_text(
        self,
        page,
        text: str,
        prefer_top_right: bool = False,
    ) -> dict[str, object] | None:
        return page.evaluate(
            """
            ({ text, preferTopRight }) => {
              const candidate = findExactVisibleTextAction(text, preferTopRight);
              if (!candidate) return { clicked: false, reason: "not-found" };

              const clickable = nearestClickable(candidate) || candidate;
              const clickTarget = isVisible(clickable) ? clickable : candidate;
              const rect = clickTarget.getBoundingClientRect();
              clickTarget.click();
              return {
                clicked: true,
                tag: clickTarget.tagName,
                role: clickTarget.getAttribute("role") || "",
                text: (candidate.innerText || candidate.textContent || "").trim(),
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };

              function findExactVisibleTextAction(targetText, preferTopRight) {
                const ignoredTags = new Set(["TITLE", "SVG", "PATH", "SCRIPT", "STYLE"]);
                const selectors = "button, a, [role='button'], [role='link'], span, div";
                const candidates = Array.from(document.querySelectorAll(selectors))
                  .filter((element) => {
                    if (ignoredTags.has(element.tagName)) return false;
                    const value = (element.innerText || element.textContent || "").trim();
                    return value === targetText && isVisible(element);
                  })
                  .map((element) => scoreElement(element, preferTopRight));

                candidates.sort((left, right) => left.score - right.score);
                return candidates[0]?.element || null;
              }

              function nearestClickable(element) {
                return element.closest("button, a, [role='button'], [role='link']");
              }

              function isVisible(element) {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return (
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity || 1) > 0 &&
                  rect.width > 0 &&
                  rect.height > 0
                );
              }

              function scoreElement(element, preferTopRight) {
                const rect = element.getBoundingClientRect();
                const role = (element.getAttribute("role") || "").toLowerCase();
                let score = rect.width * rect.height;

                if (element.tagName === "BUTTON" || element.tagName === "A") score -= 10000;
                if (role === "button" || role === "link") score -= 9000;
                if (preferTopRight) {
                  score += Math.max(0, window.innerWidth * 0.55 - rect.left) * 200;
                  score += Math.max(0, rect.top - window.innerHeight * 0.45) * 100;
                }
                return { element, score };
              }
            }
            """,
            {"text": text, "preferTopRight": prefer_top_right},
        )

    def _publish_dialog_is_gone(self, page, lower_body_text: str) -> bool:
        if "create new post" in lower_body_text or "new post" in lower_body_text:
            return False
        try:
            return not self._exact_visible_text_exists(page, "Share", prefer_top_right=True)
        except PlaywrightError as exc:
            return self._is_target_closed_error(exc)

    def _is_target_closed_error(self, exc: Exception) -> bool:
        return "Target page, context or browser has been closed" in str(exc)

    def _close_browser(self, context, browser) -> None:
        for item in (context, browser):
            try:
                item.close()
            except PlaywrightError:
                continue

    def _save_storage_state(self, context) -> None:
        SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            context.storage_state(path=str(SESSION_STATE_PATH))
        except Exception as exc:
            logger.warning("Could not save Instagram browser session: %s", sanitize_error(exc))
