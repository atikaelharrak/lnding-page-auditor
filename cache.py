"""
cache.py
--------
Caching / rate-limiting layer for audits.

Why this exists: crawling a page makes real HTTP requests to a
third-party site (the technical checks fetch the page, the link
checker sends HEAD requests to sampled internal links). If the same
URL gets audited repeatedly in a short window — someone refreshing the
web page, a script polling in a loop, a demo running the same URL
several times — that's unnecessary load on the target site and slower
for the person waiting on the result.

This module checks the database (via db.get_most_recent_audit) before
running a fresh crawl. If a recent-enough audit already exists, its
result is reused instead of crawling again.

Design choice: this cache lives in the SAME SQLite database as audit
history, not a separate cache store (e.g. Redis / an in-memory dict).
Reasoning: we already store every audit with a timestamp for history
purposes, so "is there a recent one?" is one query against data we
already have — no second source of truth to keep in sync, no
additional infrastructure. The tradeoff: this cache doesn't survive
being asked "give me a sub-second lookup at high request volume" the
way an in-memory/Redis cache would, but at this project's scale
(an internal QA tool, not a high-traffic service) that's the right
call. A Redis-backed cache would be the natural upgrade if this needed
to serve many concurrent users.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import db

# How fresh a past audit needs to be to count as a cache hit. Chosen as
# a reasonable default for a QA tool -- long enough to meaningfully
# reduce repeat load on a target site, short enough that a real fix
# someone just made to their landing page shows up again soon.
DEFAULT_CACHE_TTL_MINUTES = 10


@dataclass
class CacheResult:
    hit: bool
    audit: dict | None  # the cached audit row (from db.py), if hit is True
    age_seconds: float | None  # how old the cached audit is, if hit is True


def _parse_iso_timestamp(ts: str) -> datetime:
    """
    Parse the ISO-8601 timestamps db.py stores (via datetime.isoformat()
    with timezone.utc) back into a datetime object for age comparison.
    """
    return datetime.fromisoformat(ts)


def check_cache(url: str, ttl_minutes: int = DEFAULT_CACHE_TTL_MINUTES, db_path=None) -> CacheResult:
    """
    Check whether a recent-enough audit already exists for this URL.

    Returns a CacheResult with hit=True and the cached audit if one
    exists within the TTL window, or hit=False if no audit exists yet
    or the most recent one is too old to reuse.
    """
    most_recent = db.get_most_recent_audit(url, db_path=db_path)
    if most_recent is None:
        return CacheResult(hit=False, audit=None, age_seconds=None)

    audited_at = _parse_iso_timestamp(most_recent["created_at"])
    now = datetime.now(timezone.utc)
    age = now - audited_at
    age_seconds = age.total_seconds()

    if age <= timedelta(minutes=ttl_minutes):
        return CacheResult(hit=True, audit=most_recent, age_seconds=age_seconds)

    return CacheResult(hit=False, audit=None, age_seconds=age_seconds)


def cached_audit_to_report_dict(cached_audit: dict) -> dict:
    """
    Reshape a cached database row (db.py's dict shape) into the same
    dict shape report.report_to_dict() produces, so callers (the API,
    the web frontend) can treat a cache hit exactly like a fresh
    report — no special-casing needed downstream.
    """
    return {
        "url": cached_audit["url"],
        "final_url": cached_audit["final_url"],
        "fetch_error": cached_audit["fetch_error"],
        "overall_score": cached_audit["overall_score"],
        "categories": cached_audit["categories"],
        "id": cached_audit["id"],
        "cached": True,
        "cached_at": cached_audit["created_at"],
    }
