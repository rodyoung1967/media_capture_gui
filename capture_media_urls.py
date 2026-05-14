#!/usr/bin/env python3
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Set

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Intentionally broad: many streaming platforms do not expose clean .m3u8/.mp4 URLs.
MEDIA_PATTERN = re.compile(
    r"(m3u8|mpd|mp4|m4s|\.ts|mux|stream|video|playback|manifest|media|hls|dash)",
    re.IGNORECASE,
)


def is_media_url(url: str) -> bool:
    return bool(MEDIA_PATTERN.search(url))


def capture_media_urls(
    url: str,
    profile_dir: str = ".playwright_profile",
    timeout_seconds: int = 120,
    wait_before_capture: int = 60,
    logger: Callable[[str], None] | None = None,
) -> list[str]:
    """
    Launches a visible Chrome browser, lets the user authenticate/interact,
    then captures likely media URLs from network request/response events.

    This does not bypass security checks. It only captures URLs that load during
    a normal visible browser session controlled by Playwright.
    """
    found: Set[str] = set()

    def log(message: str) -> None:
        if logger:
            logger(message)

    profile_path = str(Path(profile_dir).resolve())

    with sync_playwright() as p:
        log(f"Using browser profile: {profile_path}")
        log("Launching Chrome window...")

        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )

        page = None
        try:
            page = context.new_page()

            def handle_request(request):
                request_url = request.url
                if is_media_url(request_url):
                    found.add(request_url)
                    log(f"[media-request] {request_url}")

            def handle_response(response):
                response_url = response.url
                if is_media_url(response_url):
                    found.add(response_url)
                    log(f"[media-response] {response_url}")

            page.on("request", handle_request)
            page.on("response", handle_response)

            log(f"Opening URL: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            except PlaywrightTimeoutError:
                log("Page load timed out, but continuing capture because the browser is open.")

            log("Browser is open. Authenticate or navigate as needed in that Chrome window.")
            log("Start playing the video during the capture window.")

            if wait_before_capture > 0:
                log(f"Waiting {wait_before_capture} seconds for login/navigation/play interaction...")
                page.wait_for_timeout(wait_before_capture * 1000)

            log(f"Capturing likely media URLs for {timeout_seconds} seconds...")
            deadline = time.time() + max(1, timeout_seconds)

            while time.time() < deadline:
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    log("Browser or page was closed during capture.")
                    break

            log(f"Capture complete. Found {len(found)} likely media URL(s).")

        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            try:
                context.close()
            except Exception:
                pass

    return sorted(found)
