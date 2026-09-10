"""
jobs.py
-------
Background job processing for audits.

Why this exists: an audit involves a real network request plus parsing
HTML, typically 0.5-3 seconds, sometimes more for a slow site. Running
that synchronously inside a web request works, but it means the caller
(browser or API client) sits there blocking the whole time, and a slow
target site directly becomes a slow response from OUR server.

This module lets an audit be submitted as a background job: the caller
gets a job id back immediately, and can poll for the result. This is
the same basic pattern production systems use for anything slow
(image processing, report generation, sending emails, etc).

Design choice: plain Python `threading` + an in-memory dict, not
Celery/RQ/a real message queue. For a project at this scale (one
process, no need for multiple worker machines, no need for jobs to
survive a server restart), pulling in Redis + a task queue library
would add real operational complexity (a separate broker process to
run and monitor) for a benefit this project doesn't need yet. The
job-status pattern implemented here (submit -> poll -> get result) is
the same pattern Celery/RQ use under the hood, swapping the in-memory
store for Redis and this thread pool for Celery workers later would be
a natural next step if this tool needed to scale beyond one machine,
without changing the API shape callers depend on.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from report import build_report, report_to_dict

# A small fixed-size thread pool. Audits are I/O-bound (waiting on a
# network response), so threads (not processes) are the right tool here
# -- Python's GIL isn't a bottleneck for I/O-bound work like this.
_executor = ThreadPoolExecutor(max_workers=4)

# In-memory job store. Cleared on server restart -- acceptable for this
# scope (see module docstring); a real deployment would move this to
# Redis or a database table if jobs needed to survive a restart.
_jobs: dict[str, "Job"] = {}
_jobs_lock = threading.Lock()


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    url: str
    status: JobStatus = JobStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def _run_job(job_id: str, url: str, save_to_db: bool) -> None:
    """
    The actual work a background thread performs: run the audit, store
    the result (or error) on the Job object. This function runs on a
    worker thread, NOT the thread handling the original HTTP request.
    """
    with _jobs_lock:
        _jobs[job_id].status = JobStatus.RUNNING

    try:
        report = build_report(url)
        result_dict = report_to_dict(report)

        if save_to_db:
            # Imported here (not at module top) to avoid a circular
            # import: db.py doesn't need to know about jobs.py, but
            # this keeps that dependency direction explicit and local.
            import db
            audit_id = db.save_audit(report)
            result_dict["id"] = audit_id

        with _jobs_lock:
            job = _jobs[job_id]
            job.status = JobStatus.DONE
            job.result = result_dict
            job.finished_at = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.finished_at = datetime.now(timezone.utc).isoformat()


def submit_audit_job(url: str, save_to_db: bool = True) -> str:
    """
    Submit a new audit as a background job. Returns immediately with a
    job id the caller can use to poll for the result via get_job().
    """
    job_id = str(uuid.uuid4())
    job = Job(id=job_id, url=url)

    with _jobs_lock:
        _jobs[job_id] = job

    _executor.submit(_run_job, job_id, url, save_to_db)
    return job_id


def create_completed_job_from_cache(url: str, cached_result: dict) -> str:
    """
    Register a job that's already "done" because a cache hit made a
    fresh crawl unnecessary. This lets /api/jobs return a consistent
    job-shaped response (id, status, result) whether or not the audit
    actually ran on a worker thread, callers polling GET /api/jobs/<id>
    don't need to special-case cache hits.
    """
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    job = Job(
        id=job_id,
        url=url,
        status=JobStatus.DONE,
        result=cached_result,
        created_at=now,
        finished_at=now,
    )
    with _jobs_lock:
        _jobs[job_id] = job
    return job_id


def get_job(job_id: str) -> Optional[Job]:
    """Look up a job by id. Returns None if no such job exists."""
    with _jobs_lock:
        return _jobs.get(job_id)


def _reset_jobs_for_testing() -> None:
    """
    Test-only helper: clears the in-memory job store between tests so
    one test's jobs can't leak into another. Not used by the app itself.
    """
    with _jobs_lock:
        _jobs.clear()
