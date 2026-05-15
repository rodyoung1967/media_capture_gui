#!/usr/bin/env python3
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Set

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Matches actual streaming manifests / segments — tightened to reduce noise.
MEDIA_PATTERN = re.compile(
    r"(\.m3u8|\.mpd|\.mp4|\.m4s|\.ts(\?|$)|/hls/|/dash/|/manifest|stream\.mux\.com)",
    re.IGNORECASE,
)

# Matches Mux thumbnail URLs so we can derive the stream URL from the video ID.
MUX_THUMBNAIL_PATTERN = re.compile(
    r"https://image\.mux\.com/([A-Za-z0-9]+)/thumbnail\.",
    re.IGNORECASE,
)

MUX_STREAM_TEMPLATE = "https://stream.mux.com/{video_id}.m3u8"


def is_media_url(url: str) -> bool:
    return bool(MEDIA_PATTERN.search(url))


def extract_mux_stream_urls(url: str) -> list[str]:
    """Derive Mux HLS stream URLs from thumbnail URLs (video ID is the same)."""
    matches = MUX_THUMBNAIL_PATTERN.findall(url)
    return [MUX_STREAM_TEMPLATE.format(video_id=vid_id) for vid_id in matches]


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

    Also auto-derives Mux HLS stream URLs from any Mux thumbnail URLs seen.

    Network listeners attach to every tab/window opened during the session
    (OAuth popups, SSO, etc.), not only the first page.

    This does not bypass security checks. It only captures URLs that load during
    a normal visible browser session controlled by Playwright.
    """
    found: Set[str] = set()
    derived_streams: Set[str] = set()
    all_results: list[str] = []

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

        listener_pages: Set[int] = set()

        def handle_request(request):
            request_url = request.url
            if is_media_url(request_url):
                found.add(request_url)
                log(f"[stream-request] {request_url}")
            for stream_url in extract_mux_stream_urls(request_url):
                if stream_url not in derived_streams:
                    derived_streams.add(stream_url)
                    log(f"[mux-derived-stream] {stream_url}")

        def handle_response(response):
            response_url = response.url
            if is_media_url(response_url):
                found.add(response_url)
                log(f"[stream-response] {response_url}")
            for stream_url in extract_mux_stream_urls(response_url):
                if stream_url not in derived_streams:
                    derived_streams.add(stream_url)
                    log(f"[mux-derived-stream] {stream_url}")

        def attach_listeners(pg) -> None:
            sid = id(pg)
            if sid in listener_pages:
                return
            listener_pages.add(sid)
            pg.on("request", handle_request)
            pg.on("response", handle_response)

        context.on("page", attach_listeners)

        page = None
        try:
            for existing in context.pages:
                attach_listeners(existing)

            page = context.new_page()
            attach_listeners(page)

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

            log(f"Capturing stream URLs for {timeout_seconds} seconds...")
            deadline = time.time() + max(1, timeout_seconds)

            while time.time() < deadline:
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    log("Browser or page was closed during capture.")
                    break

            all_results = sorted(found | derived_streams)
            log(
                f"Capture complete. Found {len(found)} live stream URL(s) + "
                f"{len(derived_streams)} derived Mux stream URL(s)."
            )

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

    return all_results
