from __future__ import annotations

import os
import threading
import time
import uuid
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


@dataclass
class CaptureJob:
    id: str
    status: str = "starting"
    logs: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
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

        with jobs_lock:
            jobs[job_id].urls = results
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
        wait_before_capture = 60
    else:
        try:
            wait_before_capture = int(wc_raw)
        except (TypeError, ValueError):
            return _bad_json("wait_before_capture must be an integer")
    if wait_before_capture < 0 or wait_before_capture > 86400:
        return _bad_json("wait_before_capture must be between 0 and 86400")

    ts_raw = data.get("timeout_seconds")
    if ts_raw is None:
        timeout_seconds = 120
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
                "error": job.error,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
        )


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
