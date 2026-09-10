"""
api.py
------
REST API for the Landing Page Health Auditor.

This is a proper JSON API, separate from the HTML-rendering routes in
app.py. The goal: any client (the web frontend, a script, a future
Slack bot, a scheduled job) can trigger an audit or read history by
calling these endpoints, nobody has to parse HTML to use this tool
programmatically.

Implemented as a Flask Blueprint rather than routes directly on `app`,
so it can be registered under a URL prefix (/api) and tested/reasoned
about independently of the HTML frontend.

Endpoints:
    POST /api/audit                 Audit a URL (cache-aware), save it, return it as JSON
    GET  /api/audits                List recent audits (across all URLs)
    GET  /api/audits/<id>           Get a single audit by its database id
    GET  /api/history?url=...       Get audit history for a specific URL
    GET  /api/trend?url=...         Get just the (timestamp, score) series for a URL
    GET  /api/health                Simple liveness check

    POST /api/jobs                  Submit an audit as a background job (cache-aware), returns immediately
    GET  /api/jobs/<job_id>         Poll a background job's status/result

Caching: both POST /api/audit and POST /api/jobs check cache.py before
running a fresh crawl. If a recent-enough audit already exists for the
requested URL (see cache.DEFAULT_CACHE_TTL_MINUTES), that cached result
is returned instead of re-crawling, protects target sites from being
hit repeatedly and speeds up repeated checks. Pass "force": true in the
request body to bypass the cache and always run a fresh crawl.
"""

from flask import Blueprint, jsonify, request

import cache
import db
import jobs
from report import build_report, report_to_dict

api = Blueprint("api", __name__, url_prefix="/api")


def error_response(message: str, status: int = 400):
    return jsonify({"error": message}), status


@api.route("/health", methods=["GET"])
def health():
    """Simple liveness check, useful for uptime monitors or quick sanity checks."""
    return jsonify({"status": "ok"})


@api.route("/audit", methods=["POST"])
def run_audit():
    """
    Audit a URL and return the report as JSON.

    By default, checks the cache first (db.py's audits table) and
    returns a cached result if the URL was audited within the last
    DEFAULT_CACHE_TTL_MINUTES, this avoids hammering a target site
    with repeated crawls in a short window. Set "force": true in the
    request body to always run a fresh crawl regardless of cache.

    Expects JSON body: {"url": "https://example.com", "force": false}
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    force = bool(data.get("force", False))

    if not url:
        return error_response("Missing required field: 'url'")

    if not force:
        cache_result = cache.check_cache(url)
        if cache_result.hit:
            return jsonify(cache.cached_audit_to_report_dict(cache_result.audit)), 200

    try:
        report = build_report(url)
    except Exception as e:
        return error_response(f"Failed to audit URL: {e}", status=500)

    audit_id = db.save_audit(report)

    result = report_to_dict(report)
    result["id"] = audit_id
    result["cached"] = False
    return jsonify(result), 201


@api.route("/jobs", methods=["POST"])
def submit_job():
    """
    Submit an audit as a BACKGROUND job. Returns immediately with a job
    id, the audit itself runs on a worker thread, unless a
    recent-enough cached result already exists (see /api/audit's cache
    behavior), in which case the job is created already "done".
    Poll GET /api/jobs/<job_id> to check progress and retrieve the
    result once it's ready.

    Expects JSON body: {"url": "https://example.com", "force": false}
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    force = bool(data.get("force", False))

    if not url:
        return error_response("Missing required field: 'url'")

    if not force:
        cache_result = cache.check_cache(url)
        if cache_result.hit:
            cached_dict = cache.cached_audit_to_report_dict(cache_result.audit)
            job_id = jobs.create_completed_job_from_cache(url, cached_dict)
            job = jobs.get_job(job_id)
            return jsonify(job.to_dict()), 200  # already done, not "accepted for processing"

    job_id = jobs.submit_audit_job(url)
    job = jobs.get_job(job_id)
    return jsonify(job.to_dict()), 202  # 202 Accepted: request accepted, processing not complete


@api.route("/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str):
    """Poll the status/result of a previously submitted background job."""
    job = jobs.get_job(job_id)
    if job is None:
        return error_response(f"No job found with id {job_id}", status=404)
    return jsonify(job.to_dict())


@api.route("/audits", methods=["GET"])
def list_recent_audits():
    """
    List the most recent audits across all URLs.
    Optional query param: ?limit=N (default 20, max 100).
    """
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))  # clamp to a sane range
    audits = db.get_recent_audits(limit=limit)
    return jsonify({"audits": audits, "count": len(audits)})


@api.route("/audits/<int:audit_id>", methods=["GET"])
def get_audit(audit_id: int):
    """Fetch a single stored audit by its database id."""
    audit = db.get_audit_by_id(audit_id)
    if audit is None:
        return error_response(f"No audit found with id {audit_id}", status=404)
    return jsonify(audit)


@api.route("/history", methods=["GET"])
def get_history():
    """
    Get audit history for a specific URL, most recent first.
    Required query param: ?url=...
    Optional query param: ?limit=N (default 20, max 100).
    """
    url = (request.args.get("url") or "").strip()
    if not url:
        return error_response("Missing required query parameter: 'url'")

    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))

    history = db.get_audit_history(url, limit=limit)
    return jsonify({"url": url, "history": history, "count": len(history)})


@api.route("/trend", methods=["GET"])
def get_trend():
    """
    Get the (timestamp, score) trend series for a URL, oldest first,
    exactly what a frontend chart needs.
    Required query param: ?url=...
    """
    url = (request.args.get("url") or "").strip()
    if not url:
        return error_response("Missing required query parameter: 'url'")

    trend = db.get_score_trend(url)
    return jsonify({"url": url, "trend": trend, "count": len(trend)})
