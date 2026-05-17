from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

from capture_media_urls import capture_media_urls

app = Flask(__name__)

try:
    CAPTURE_JOB_STORE_MAX = max(10, int(os.environ.get("CAPTURE_JOB_STORE_MAX", "100")))
except ValueError:
    CAPTURE_JOB_STORE_MAX = 100


DOWNLOAD_STATUS_VERSION = 2


def _console_print(msg: str) -> None:
    """Avoid UnicodeEncodeError on Windows terminals when logging from worker threads."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _format_subprocess_returncode(rc: int | None) -> str:
    if rc is None:
        return "(none)"
    if rc < 0 or rc > 255:
        u32 = rc & 0xFFFFFFFF
        return f"{rc} (unsigned 32-bit: {u32} / 0x{u32:08x})"
    return str(rc)


def _tail_stderr(stderr: str, max_chars: int = 12000) -> str:
    """ffmpeg may print a long banner first; useful errors are usually near the end."""
    if not stderr:
        return ""
    text = stderr.strip()
    if len(text) <= max_chars:
        return text
    return f"... ({len(text) - max_chars} chars omitted from start of stderr) ...\n{text[-max_chars:]}"


def cookie_header_from_playwright_records(cookies: object, media_url: str) -> str:
    """
    Build a single ``Cookie: ...`` value body for the host in ``media_url``,
    matching Playwright ``context.cookies()`` records (domain/path aware enough for FFmpeg).
    """
    if not isinstance(cookies, list) or not media_url:
        return ""
    parsed = urlparse(media_url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""

    scoped: List[tuple[int, str, str]] = []
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue
        domain_raw = (c.get("domain") or "").strip()
        domain = domain_raw.lstrip(".").lower()
        if not domain:
            continue
        if hostname == domain or hostname.endswith("." + domain):
            scoped.append((len(domain), str(name), str(value)))

    scoped.sort(key=lambda t: -t[0])

    seen_names: set[str] = set()
    parts: List[str] = []
    for _, nm, val in scoped:
        if nm in seen_names:
            continue
        seen_names.add(nm)
        parts.append(f"{nm}={val}")
    return "; ".join(parts)


def merge_cookie_header_values(*chunks: str) -> str:
    """Join non-empty cookie header bodies; manual entries can supplement capture cookies."""
    return "; ".join(ch.strip() for ch in chunks if ch and ch.strip())


@dataclass
class CaptureJob:
    id: str
    status: str = "starting"
    logs: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    cookies: List[dict] = field(default_factory=list)
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


jobs: Dict[str, CaptureJob] = {}
jobs_lock = threading.Lock()


def prune_terminal_jobs_unlocked() -> None:
    """Drop oldest finished jobs when the map grows past CAPTURE_JOB_STORE_MAX."""
    while len(jobs) > CAPTURE_JOB_STORE_MAX:
        finished = [
            (jid, job)
            for jid, job in jobs.items()
            if job.status in ("complete", "error") and job.finished_at is not None
        ]
        if not finished:
            break
        oldest_id = min(finished, key=lambda item: item[1].finished_at or 0.0)[0]
        del jobs[oldest_id]


def add_log(job_id: str, message: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job.logs.append(message)


def run_capture_job(
    job_id: str,
    url: str,
    profile_dir: str,
    wait_before_capture: int,
    timeout_seconds: int,
) -> None:
    with jobs_lock:
        jobs[job_id].status = "running"

    try:
        results = capture_media_urls(
            url=url,
            profile_dir=profile_dir,
            wait_before_capture=wait_before_capture,
            timeout_seconds=timeout_seconds,
            logger=lambda msg: add_log(job_id, msg),
        )
        urls_payload = results.get("urls") if isinstance(results, dict) else results
        cookie_payload = results.get("cookies") if isinstance(results, dict) else ()
        if not isinstance(urls_payload, list):
            urls_payload = []

        with jobs_lock:
            jobs[job_id].urls = urls_payload
            jobs[job_id].cookies = list(cookie_payload) if isinstance(cookie_payload, list) else []
            jobs[job_id].status = "complete"
            jobs[job_id].finished_at = time.time()
            prune_terminal_jobs_unlocked()

    except Exception as exc:
        with jobs_lock:
            jobs[job_id].status = "error"
            jobs[job_id].error = str(exc)
            jobs[job_id].finished_at = time.time()
            prune_terminal_jobs_unlocked()


@app.route("/")
def index():
    return render_template("index.html")


def _bad_json(msg: str):
    return jsonify({"error": msg}), 400


@app.route("/start", methods=["POST"])
def start_capture():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad_json("Expected a JSON object body")

    url = (data.get("url") or "").strip()
    if not url:
        return _bad_json("URL is required")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return _bad_json("URL must use http:// or https://")

    profile_dir = (data.get("profile_dir") or ".playwright_profile").strip()

    wc_raw = data.get("wait_before_capture")
    if wc_raw is None:
        wait_before_capture = 15
    else:
        try:
            wait_before_capture = int(wc_raw)
        except (TypeError, ValueError):
            return _bad_json("wait_before_capture must be an integer")
    if wait_before_capture < 0 or wait_before_capture > 86400:
        return _bad_json("wait_before_capture must be between 0 and 86400")

    ts_raw = data.get("timeout_seconds")
    if ts_raw is None:
        timeout_seconds = 45
    else:
        try:
            timeout_seconds = int(ts_raw)
        except (TypeError, ValueError):
            return _bad_json("timeout_seconds must be an integer")
    if timeout_seconds < 1 or timeout_seconds > 86400:
        return _bad_json("timeout_seconds must be between 1 and 86400")

    # Keep profile inside the project folder unless the user provides an absolute path.
    profile_path = Path(profile_dir)
    if not profile_path.is_absolute():
        profile_dir = str((Path.cwd() / profile_path).resolve())

    job_id = str(uuid.uuid4())
    job = CaptureJob(id=job_id)

    with jobs_lock:
        jobs[job_id] = job
        prune_terminal_jobs_unlocked()

    thread = threading.Thread(
        target=run_capture_job,
        args=(job_id, url, profile_dir, wait_before_capture, timeout_seconds),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

        return jsonify(
            {
                "id": job.id,
                "status": job.status,
                "logs": job.logs,
                "urls": job.urls,
                "cookies": job.cookies,
                "error": job.error,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
        )


@app.route("/download-stream", methods=["POST"])
def download_stream():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        # Allow form posts too, in case you later wire this to a normal HTML form.
        data = request.form.to_dict()

    download_url = (data.get("download_url") or "").strip()
    output_file = (data.get("output_file") or "").strip()
    download_cookie = (data.get("download_cookie") or "").strip()
    capture_cookies_raw = data.get("cookies")
    if isinstance(capture_cookies_raw, list):
        capture_cookies = [c for c in capture_cookies_raw if isinstance(c, dict)]
    else:
        capture_cookies = []

    if not download_url:
        return _bad_json("download_url is required")
    if not output_file:
        return _bad_json("output_file is required")
    if shutil.which("ffmpeg") is None:
        return _bad_json("ffmpeg not found on PATH")

    output_path = Path(output_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    status_file = output_path.parent / f".{output_path.name}.download_status.json"
    try:
        if status_file.is_file():
            status_file.unlink()
    except OSError:
        pass

    initial_status = {
        "status_version": DOWNLOAD_STATUS_VERSION,
        "status": "queued",
        "output_file": str(output_path),
        "progress": "Queued; starting download...",
        "error": None,
    }
    status_file.write_text(json.dumps(initial_status), encoding="utf-8")

    def write_status(payload: dict) -> None:
        status_file.write_text(json.dumps(payload), encoding="utf-8")

    def run_download() -> None:
        try:
            write_status(
                {
                    "status_version": DOWNLOAD_STATUS_VERSION,
                    "status": "starting",
                    "output_file": str(output_path),
                    "progress": "Starting ffmpeg...",
                    "error": None,
                }
            )
            _console_print(f"[Download] Starting download to: {output_path}")

            from_capture = cookie_header_from_playwright_records(capture_cookies, download_url)
            combined_cookie = merge_cookie_header_values(from_capture, download_cookie)
            if from_capture:
                _console_print("[Download] Applying cookies from last capture for this media host (plus any manual cookie box).")
            elif capture_cookies:
                _console_print(
                    "[Download] Capture cookies were sent but none matched this URL’s hostname — "
                    "try manual Cookie header or capture again after playback."
                )

            ffmpeg_cmd = [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-i",
                download_url,
            ]

            headers: List[str] = []
            if combined_cookie:
                headers.append(f"Cookie: {combined_cookie}")
            if headers:
                ffmpeg_cmd.extend(["-headers", "\r\n".join(headers) + "\r\n"])

            ffmpeg_cmd.extend(["-c", "copy", "-y", str(output_path)])
            _console_print("[Download] Running ffmpeg...")

            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode == 0:
                file_size = output_path.stat().st_size if output_path.exists() else 0
                write_status(
                    {
                        "status_version": DOWNLOAD_STATUS_VERSION,
                        "status": "completed",
                        "output_file": str(output_path),
                        "file_size_mb": round(file_size / 1024 / 1024, 1),
                        "progress": f"Download completed ({file_size / 1024 / 1024:.1f} MB)",
                        "error": None,
                    }
                )
                _console_print(f"[Download] OK completed: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
            else:
                err_raw = _tail_stderr(result.stderr or "", 12000)
                rc_fmt = _format_subprocess_returncode(result.returncode)
                write_status(
                    {
                        "status_version": DOWNLOAD_STATUS_VERSION,
                        "status": "failed",
                        "output_file": str(output_path),
                        "progress": "Download failed",
                        "error": err_raw if err_raw else f"ffmpeg exit code {rc_fmt} (no stderr text)",
                        "exit_code": result.returncode,
                        "exit_code_formatted": rc_fmt,
                    }
                )
                _console_print(f"[Download] FAIL exit code {rc_fmt}")
        except Exception as exc:
            err_text = str(exc).encode("ascii", errors="replace").decode("ascii")
            write_status(
                {
                    "status_version": DOWNLOAD_STATUS_VERSION,
                    "status": "error",
                    "output_file": str(output_path),
                    "progress": "Download error",
                    "error": f"Exception: {err_text}",
                }
            )
            _console_print(f"[Download] ERROR for {output_path}: {err_text}")

    thread = threading.Thread(target=run_download, daemon=True)
    thread.start()

    return jsonify(
        {
            "message": "Download started. Monitoring status...",
            "output_file": str(output_path),
            "status_file": str(status_file),
        }
    )


def _read_download_status_file() -> tuple[str | None, dict | None]:
    status_file = ""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        status_file = (payload.get("file") or "").strip()
    if not status_file:
        status_file = (request.args.get("file") or "").strip()
    if not status_file:
        return "No status file provided", None

    try:
        status_file_path = Path(status_file)
        if not status_file_path.is_file():
            return None, {
                "status_version": DOWNLOAD_STATUS_VERSION,
                "status": "pending",
                "progress": "Download initializing...",
                "error": None,
            }
        return None, json.loads(status_file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Could not read status: {exc}", None


def _enrich_download_status(data: dict) -> dict:
    out = dict(data)
    out_path = (out.get("output_file") or "").strip()
    if out_path:
        p = Path(out_path)
        try:
            if p.is_file():
                size = p.stat().st_size
                out["output_exists"] = True
                out["output_size_bytes"] = size
                out["output_size_mb"] = round(size / (1024 * 1024), 2)
            else:
                out["output_exists"] = False
                out["output_size_bytes"] = 0
                out["output_size_mb"] = None
        except OSError:
            out["output_exists"] = False
            out["output_size_bytes"] = 0
            out["output_size_mb"] = None

    status = out.get("status") or ""
    if status == "queued":
        out["hint"] = "Queued: ffmpeg will start in a moment."
    elif status == "starting":
        out["hint"] = "ffmpeg is running. For long streams, the file size should grow over time."
    elif status == "pending":
        out["hint"] = "Waiting for the status file. If this sticks, restart the app and submit again."
    elif status == "completed":
        out["hint"] = "Finished. Open the output path in File Explorer and play the file."
    elif status in ("failed", "error"):
        out["hint"] = "See the error detail below. Common causes: bad URL, missing cookies, or unsupported input."
    else:
        out["hint"] = ""

    if out.get("status_version") != DOWNLOAD_STATUS_VERSION:
        out["hint"] = (
            (out.get("hint") or "")
            + " This status file is from an older server build. Delete the .download_status.json file and retry."
        ).strip()
    out["server_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return out


@app.route("/check-download-status", methods=["GET", "POST"])
def check_download_status():
    err, data = _read_download_status_file()
    if err:
        return jsonify({"error": err}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid status payload"}), 400
    return jsonify(_enrich_download_status(data))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    dbg_env = os.environ.get("FLASK_DEBUG")
    if dbg_env is None:
        debug = True  # Preserve previous default when unset
    else:
        debug = dbg_env.strip().lower() not in ("0", "false", "no")
    # Dev reloader spawns two processes — bad for Chrome + persistent profiles unless you opt in.
    use_reloader = os.environ.get("FLASK_USE_RELOADER", "").lower() in ("1", "true", "yes")

    mode = (
        "debug=False"
        if not debug
        else ("debug=True, use_reloader=True" if use_reloader else "debug=True, use_reloader=False")
    )
    print(f"* Listening on http://127.0.0.1:{port} ({mode}; PORT / FLASK_DEBUG / FLASK_USE_RELOADER)")

    app.run(
        host="127.0.0.1",
        port=port,
        debug=debug,
        use_reloader=(debug and use_reloader),
    )
