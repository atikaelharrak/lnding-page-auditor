"""
test_cache.py
-------------
Tests for cache.py : the caching/rate-limiting layer.

Uses a temporary, isolated database per test (same pattern as
test_db.py). Where a test needs to simulate an "old" cached audit
(past the TTL), it inserts a row directly with a manipulated
created_at timestamp rather than waiting in real time, waiting
several real minutes in a test suite would be impractical.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import cache
import db
from conftest import make_page
from report import build_report


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_audits.db"
    db.init_db(db_path)
    return db_path


def _fake_report(url="https://example.com"):
    page = make_page('<html><body><img src="/a.png" alt="A"></body></html>', url=url)
    page.load_time_ms = 300
    with patch("report.fetch_page", return_value=page):
        return build_report(url)


def _insert_audit_with_timestamp(db_path, url, created_at_iso, score=80):
    """Directly insert a row with a specific timestamp, bypassing
    db.save_audit()'s automatic 'now' timestamp -- needed to simulate
    an audit that happened N minutes ago without actually waiting."""
    with db.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audits (url, final_url, overall_score, fetch_error, categories_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (url, url, score, None, json.dumps([]), created_at_iso),
        )
        conn.commit()


class TestCheckCache:
    def test_miss_when_url_never_audited(self, temp_db):
        result = cache.check_cache("https://never-audited.com", db_path=temp_db)
        assert result.hit is False
        assert result.audit is None
        assert result.age_seconds is None

    def test_hit_when_audit_is_fresh(self, temp_db):
        report = _fake_report()
        db.save_audit(report, temp_db)

        result = cache.check_cache("https://example.com", db_path=temp_db)
        assert result.hit is True
        assert result.audit is not None
        assert result.age_seconds < 5  

    def test_miss_when_audit_is_older_than_ttl(self, temp_db):
        old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        _insert_audit_with_timestamp(temp_db, "https://example.com", old_timestamp)

        result = cache.check_cache("https://example.com", ttl_minutes=10, db_path=temp_db)
        assert result.hit is False
        assert result.age_seconds > 1000  

    def test_hit_when_older_audit_is_within_a_longer_ttl(self, temp_db):
        old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        _insert_audit_with_timestamp(temp_db, "https://example.com", old_timestamp)

        result = cache.check_cache("https://example.com", ttl_minutes=30, db_path=temp_db)
        assert result.hit is True

    def test_just_inside_ttl_boundary_counts_as_hit(self, temp_db):
        """An audit just inside the TTL window should still be usable."""
        just_inside_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=9, seconds=55)).isoformat()
        _insert_audit_with_timestamp(temp_db, "https://example.com", just_inside_timestamp)

        result = cache.check_cache("https://example.com", ttl_minutes=10, db_path=temp_db)
        assert result.hit is True

    def test_just_outside_ttl_boundary_counts_as_miss(self, temp_db):
        """An audit just past the TTL window should no longer be usable."""
        just_outside_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10, seconds=5)).isoformat()
        _insert_audit_with_timestamp(temp_db, "https://example.com", just_outside_timestamp)

        result = cache.check_cache("https://example.com", ttl_minutes=10, db_path=temp_db)
        assert result.hit is False

    def test_different_urls_have_independent_cache_entries(self, temp_db):
        db.save_audit(_fake_report(url="https://site-a.com"), temp_db)

        result_a = cache.check_cache("https://site-a.com", db_path=temp_db)
        result_b = cache.check_cache("https://site-b.com", db_path=temp_db)

        assert result_a.hit is True
        assert result_b.hit is False

    def test_uses_most_recent_audit_when_multiple_exist(self, temp_db):
        old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        _insert_audit_with_timestamp(temp_db, "https://example.com", old_timestamp, score=50)
        db.save_audit(_fake_report(), temp_db)

        result = cache.check_cache("https://example.com", db_path=temp_db)
        assert result.hit is True
        assert result.audit["overall_score"] != 50  # should be the fresh one, not the old 50


class TestCachedAuditToReportDict:
    def test_includes_cached_flag(self, temp_db):
        report = _fake_report()
        db.save_audit(report, temp_db)
        result = cache.check_cache("https://example.com", db_path=temp_db)

        as_dict = cache.cached_audit_to_report_dict(result.audit)
        assert as_dict["cached"] is True

    def test_includes_cached_at_timestamp(self, temp_db):
        report = _fake_report()
        db.save_audit(report, temp_db)
        result = cache.check_cache("https://example.com", db_path=temp_db)

        as_dict = cache.cached_audit_to_report_dict(result.audit)
        assert "cached_at" in as_dict
        assert as_dict["cached_at"] == result.audit["created_at"]

    def test_preserves_original_score_and_categories(self, temp_db):
        report = _fake_report()
        db.save_audit(report, temp_db)
        result = cache.check_cache("https://example.com", db_path=temp_db)

        as_dict = cache.cached_audit_to_report_dict(result.audit)
        assert as_dict["overall_score"] == report.overall_score
        assert len(as_dict["categories"]) == 3

    def test_shape_matches_report_to_dict_keys(self, temp_db):
        """
        A cache hit should be indistinguishable in shape from a fresh
        report (plus the two extra 'cached'/'cached_at' fields) -- this
        is what lets callers treat both cases uniformly.
        """
        from report import report_to_dict

        report = _fake_report()
        fresh_dict = report_to_dict(report)
        db.save_audit(report, temp_db)
        result = cache.check_cache("https://example.com", db_path=temp_db)
        cached_dict = cache.cached_audit_to_report_dict(result.audit)

        core_keys = {"url", "final_url", "fetch_error", "overall_score", "categories"}
        assert core_keys.issubset(fresh_dict.keys())
        assert core_keys.issubset(cached_dict.keys())
