from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from flask import Flask, jsonify, render_template, request

from capture_media_urls import capture_media_urls

app = Flask(__name__)


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

    except Exception as exc:
        with jobs_lock:
            jobs[job_id].status = "error"
            jobs[job_id].error = str(exc)
            jobs[job_id].finished_at = time.time()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start_capture():
    data = request.get_json(force=True)

    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    profile_dir = (data.get("profile_dir") or ".playwright_profile").strip()
    wait_before_capture = int(data.get("wait_before_capture") or 60)
    timeout_seconds = int(data.get("timeout_seconds") or 120)

    # Keep profile inside the project folder unless the user provides an absolute path.
    profile_path = Path(profile_dir)
    if not profile_path.is_absolute():
        profile_dir = str((Path.cwd() / profile_path).resolve())

    job_id = str(uuid.uuid4())
    job = CaptureJob(id=job_id)

    with jobs_lock:
        jobs[job_id] = job

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
    app.run(host="127.0.0.1", port=5000, debug=True)
