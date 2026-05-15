#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Set

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Matches streaming manifests / top-level URLs — excludes noisy per-segment fetches
# (.ts, .m4s) so results favor playlists (.m3u8), DASH manifests (.mpd), clear MP4, etc.
MEDIA_PATTERN = re.compile(
    r"(\.m3u8|\.mpd|\.mp4|/hls/|/dash/|/manifest|stream\.mux\.com)",
    re.IGNORECASE,
)

_MUX_FASTLY_V1_CHUNK_URL = re.compile(
    r"\.fastly\.mux\.com/v1/chunk/",
    re.IGNORECASE,
)

# Matches Mux thumbnail URLs so we can derive the stream URL from the video ID.
MUX_THUMBNAIL_PATTERN = re.compile(
    r"https://image\.mux\.com/([A-Za-z0-9]+)/thumbnail\.",
    re.IGNORECASE,
)

MUX_STREAM_TEMPLATE = "https://stream.mux.com/{video_id}.m3u8"


def _profile_lock_help_message(profile_path: str) -> str:
    return (
        "\n\nThe Chrome profile folder is locked. Another Chrome instance may be using it, "
        "or a stale lock was left after a crash.\n"
        "1) Quit Chrome completely (macOS: Cmd+Q; also stop this app’s capture if running).\n"
        "2) If needed: killall \"Google Chrome\"\n"
        "3) If Chrome is definitely not running, remove stale lock files:\n"
        f'   rm -f "{profile_path}/SingletonLock" "{profile_path}/SingletonCookie" "{profile_path}/SingletonSocket"\n'
        "4) Do not run manual Chrome with --user-data-dir for this folder at the same time as the capture app."
    )


def _chrome_cmdline_uses_profile(profile_path: str) -> bool:
    """
    True if pgrep finds a process whose argv references this exact --user-data-dir= path.
    Uses regex escaping for macOS/BSD pgrep. If pgrep is unavailable, returns True (skip auto-unlock).
    """
    if sys.platform == "win32":
        return False
    try:
        pattern = "user-data-dir=" + re.escape(profile_path)
        r = subprocess.run(
            ["pgrep", "-qf", pattern],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def _any_singleton_held_by_process(prof: Path) -> bool:
    """
    True if lsof reports a process using any Singleton* path.
    Raises FileNotFoundError if lsof is not available.
    """
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = prof / name
        if not path.exists() and not path.is_symlink():
            continue
        r = subprocess.run(
            ["lsof", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
    return False


def _attempt_clear_singleton_locks(profile_path: str, log: Callable[[str], None]) -> None:
    """
    Removes Singleton* entries when lsof shows no process is using them (macOS/Linux).
    Falls back gracefully if lsof is missing. Skip with PLAYWRIGHT_NO_AUTO_UNLOCK=1/true/yes.
    """
    if sys.platform == "win32":
        return

    env = os.environ.get("PLAYWRIGHT_NO_AUTO_UNLOCK", "").strip().lower()
    if env in ("1", "true", "yes"):
        log("Stale lock auto-cleanup skipped (PLAYWRIGHT_NO_AUTO_UNLOCK set).")
        return

    prof = Path(profile_path)
    names = ("SingletonLock", "SingletonCookie", "SingletonSocket")

    try:
        if _any_singleton_held_by_process(prof):
            log(
                "[profile] Singleton locks still held by a process — quit Chrome / wait for helpers "
                "to exit, then try again."
            )
            return
    except FileNotFoundError:
        log("[profile] lsof not available; falling back to pgrep for live Chrome check.")
        if _chrome_cmdline_uses_profile(profile_path):
            log(
                "[profile] A process still references this profile in argv; not removing Singleton locks."
            )
            return
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"[profile] Could not inspect Singleton locks ({exc}); skipping automatic cleanup.")
        return

    removed = False
    for name in names:
        p = prof / name
        try:
            if p.exists() or p.is_symlink():
                p.unlink(missing_ok=True)
                removed = True
        except OSError:
            pass

    if removed:
        time.sleep(0.4)
        log("[profile] Removed stale Chrome Singleton* locks (nothing had those files open in lsof).")


def _launch_args_from_env() -> list[str]:
    """
    Optional Chromium flags to reduce freezes on some macOS setups (heavy login pages).

    PLAYWRIGHT_DISABLE_GPU=1  -> --disable-gpu --disable-software-rasterizer
    PLAYWRIGHT_CHROME_EXTRA_ARGS  -> parsed with shlex (e.g. --disable-extensions)
    """
    args: list[str] = []

    disable_gpu = os.environ.get("PLAYWRIGHT_DISABLE_GPU", "").strip().lower()
    if disable_gpu in ("1", "true", "yes"):
        args.extend(["--disable-gpu", "--disable-software-rasterizer"])

    extra = os.environ.get("PLAYWRIGHT_CHROME_EXTRA_ARGS", "").strip()
    if extra:
        args.extend(shlex.split(extra))

    return args


def _page_goto_timeout_ms() -> int:
    raw = os.environ.get("PAGE_GOTO_TIMEOUT_MS", "180000")
    try:
        ms = int(raw)
    except ValueError:
        ms = 180_000
    return max(10_000, min(ms, 600_000))


def _cdp_endpoint_from_env() -> str:
    raw = os.environ.get("PLAYWRIGHT_CDP_URL", "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        return "http://" + raw.lstrip("/")
    return raw


def is_media_url(url: str) -> bool:
    if _MUX_FASTLY_V1_CHUNK_URL.search(url):
        return False
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
    Captures likely media URLs from network traffic during a browsing session.

    Default: Playwright launches Google Chrome against ``profile_dir`` (shows the automation
    infobar — many sites reject Google SSO there).

    **CDP mode** (recommended for Google/login-heavy sites): set env ``PLAYWRIGHT_CDP_URL`` to
    the HTTP DevTools endpoint of **Chrome YOU start manually**, e.g. ``http://127.0.0.1:9222``.
    That session usually **does not** show “controlled by automated test software”; Playwright
    only attaches and opens a tab for navigation.

    Also auto-derives Mux HLS stream URLs from any Mux thumbnail URLs seen.

    Network listeners attach to every tab/window opened during the session
    (OAuth popups, SSO, etc.), not only the first page.

    This does not bypass security checks. It only captures URLs that load during
    a normal visible browser session.
    """
    found: Set[str] = set()
    derived_streams: Set[str] = set()
    all_results: list[str] = []

    def log(message: str) -> None:
        if logger:
            logger(message)

    profile_path = str(Path(profile_dir).resolve())

    with sync_playwright() as p:
        log(f"Using browser profile (expected on disk): {profile_path}")
        cdp_endpoint = _cdp_endpoint_from_env()
        browser_attached = None
        persistent_launch = False

        if cdp_endpoint:
            log(f"Connecting to your Chrome session over CDP: {cdp_endpoint}")
            log(
                "[cdp] Avoid the grey “automated test software” bar — you started Chrome; "
                "Playwright attaches only."
            )
            browser_attached = p.chromium.connect_over_cdp(cdp_endpoint)
            if not browser_attached.contexts:
                try:
                    browser_attached.close()
                except Exception:
                    pass
                raise RuntimeError(
                    "Chrome CDP connected, but no browser contexts were reported. "
                    "Open at least one regular window and retry."
                )
            context = browser_attached.contexts[0]
        else:
            log(
                "[launch] Playwright-managed Chrome (--enable-automation). "
                "Google sign-in inside this window is often rejected; see README “CDP workflow” "
                "or PLAYWRIGHT_CDP_URL."
            )
            _attempt_clear_singleton_locks(profile_path, log)

            context = None
            exc_last: Exception | None = None
            for attempt in range(2):
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=profile_path,
                        channel="chrome",
                        headless=False,
                        viewport={"width": 1400, "height": 900},
                        args=_launch_args_from_env(),
                    )
                    persistent_launch = True
                    break
                except Exception as exc:
                    exc_last = exc
                    low = str(exc).lower()
                    lockish = (
                        "singleton" in low
                        or "processsingleton" in low
                        or "profile is already in use" in low
                    )
                    if attempt == 0 and lockish:
                        log("[profile] Launch blocked on profile lock — cleaning and retrying once...")
                        time.sleep(0.5)
                        _attempt_clear_singleton_locks(profile_path, log)
                        continue
                    if lockish:
                        raise RuntimeError(
                            str(exc) + _profile_lock_help_message(profile_path)
                        ) from exc
                    raise

            if context is None and exc_last is not None:
                raise exc_last

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
            try:
                page.set_viewport_size({"width": 1400, "height": 900})
            except Exception:
                pass

            log(f"Opening URL: {url}")
            goto_timeout_ms = _page_goto_timeout_ms()
            log(
                f"[nav] Waiting up to {goto_timeout_ms / 1000:.0f}s for DOMContentLoaded "
                f"(PAGE_GOTO_TIMEOUT_MS; if the tab hangs try PLAYWRIGHT_DISABLE_GPU=1)."
            )
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
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
            if browser_attached is not None:
                try:
                    browser_attached.close()
                except Exception:
                    pass
            elif persistent_launch:
                try:
                    context.close()
                except Exception:
                    pass

    return all_results
