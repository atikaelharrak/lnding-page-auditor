"""
test_db.py
----------
Tests for db.py : the SQLite persistence layer.

Every test uses a temporary, isolated database file (via pytest's
tmp_path fixture) so tests never touch the real audits.db and can run
in parallel/repeatedly without interfering with each other.
"""

from unittest.mock import patch

import pytest

import db
from conftest import make_page
from report import build_report


@pytest.fixture
def temp_db(tmp_path):
    """A fresh, isolated SQLite database file for each test."""
    db_path = tmp_path / "test_audits.db"
    db.init_db(db_path)
    return db_path


def _fake_report(url="https://example.com", score_html=None):
    html = score_html or '<html><body><img src="/a.png" alt="A"></body></html>'
    page = make_page(html, url=url)
    page.load_time_ms = 300
    with patch("report.fetch_page", return_value=page):
        return build_report(url)


class TestInitDb:
    def test_creates_audits_table(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        db.init_db(db_path)
        with db.get_connection(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='audits'"
            ).fetchall()
        assert len(tables) == 1

    def test_is_idempotent_safe_to_call_twice(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        db.init_db(db_path)
        db.init_db(db_path)  


class TestSaveAudit:
    def test_save_returns_an_id(self, temp_db):
        report = _fake_report()
        audit_id = db.save_audit(report, temp_db)
        assert isinstance(audit_id, int)
        assert audit_id > 0

    def test_successive_saves_get_incrementing_ids(self, temp_db):
        report = _fake_report()
        id1 = db.save_audit(report, temp_db)
        id2 = db.save_audit(report, temp_db)
        assert id2 > id1

    def test_saves_all_three_categories(self, temp_db):
        report = _fake_report()
        audit_id = db.save_audit(report, temp_db)
        fetched = db.get_audit_by_id(audit_id, temp_db)
        assert len(fetched["categories"]) == 3

    def test_saves_fetch_error_when_present(self, temp_db):
        page = make_page("<html></html>")
        page.error = "Connection error: refused"
        with patch("report.fetch_page", return_value=page):
            report = build_report("https://unreachable.example")
        audit_id = db.save_audit(report, temp_db)
        fetched = db.get_audit_by_id(audit_id, temp_db)
        assert fetched["fetch_error"] == "Connection error: refused"

    def test_saves_null_fetch_error_when_absent(self, temp_db):
        report = _fake_report()
        audit_id = db.save_audit(report, temp_db)
        fetched = db.get_audit_by_id(audit_id, temp_db)
        assert fetched["fetch_error"] is None


class TestGetAuditById:
    def test_returns_none_for_nonexistent_id(self, temp_db):
        assert db.get_audit_by_id(99999, temp_db) is None

    def test_returns_correct_audit(self, temp_db):
        report = _fake_report(url="https://specific-site.com")
        audit_id = db.save_audit(report, temp_db)
        fetched = db.get_audit_by_id(audit_id, temp_db)
        assert fetched["url"] == "https://specific-site.com"
        assert fetched["overall_score"] == report.overall_score


class TestGetAuditHistory:
    def test_empty_history_for_unaudited_url(self, temp_db):
        history = db.get_audit_history("https://never-audited.com", db_path=temp_db)
        assert history == []

    def test_returns_most_recent_first(self, temp_db):
        report = _fake_report(url="https://example.com")
        id1 = db.save_audit(report, temp_db)
        id2 = db.save_audit(report, temp_db)
        history = db.get_audit_history("https://example.com", db_path=temp_db)
        assert history[0]["id"] == id2
        assert history[1]["id"] == id1

    def test_respects_limit(self, temp_db):
        report = _fake_report(url="https://example.com")
        for _ in range(5):
            db.save_audit(report, temp_db)
        history = db.get_audit_history("https://example.com", limit=3, db_path=temp_db)
        assert len(history) == 3

    def test_only_returns_matching_url(self, temp_db):
        db.save_audit(_fake_report(url="https://site-a.com"), temp_db)
        db.save_audit(_fake_report(url="https://site-b.com"), temp_db)
        history = db.get_audit_history("https://site-a.com", db_path=temp_db)
        assert len(history) == 1
        assert history[0]["url"] == "https://site-a.com"


class TestGetMostRecentAudit:
    def test_returns_none_for_unaudited_url(self, temp_db):
        assert db.get_most_recent_audit("https://never-audited.com", temp_db) is None

    def test_returns_the_latest_one(self, temp_db):
        report = _fake_report(url="https://example.com")
        db.save_audit(report, temp_db)
        id2 = db.save_audit(report, temp_db)
        most_recent = db.get_most_recent_audit("https://example.com", temp_db)
        assert most_recent["id"] == id2


class TestGetRecentAudits:
    def test_empty_db_returns_empty_list(self, temp_db):
        assert db.get_recent_audits(db_path=temp_db) == []

    def test_returns_across_multiple_urls_most_recent_first(self, temp_db):
        id1 = db.save_audit(_fake_report(url="https://a.com"), temp_db)
        id2 = db.save_audit(_fake_report(url="https://b.com"), temp_db)
        recent = db.get_recent_audits(db_path=temp_db)
        assert len(recent) == 2
        assert recent[0]["id"] == id2
        assert recent[1]["id"] == id1


class TestGetScoreTrend:
    def test_empty_trend_for_unaudited_url(self, temp_db):
        assert db.get_score_trend("https://never-audited.com", temp_db) == []

    def test_returns_oldest_first(self, temp_db):
        report = _fake_report(url="https://example.com")
        db.save_audit(report, temp_db)
        db.save_audit(report, temp_db)
        trend = db.get_score_trend("https://example.com", temp_db)
        assert len(trend) == 2
        assert trend[0]["created_at"] <= trend[1]["created_at"]

    def test_trend_entries_have_score_and_timestamp(self, temp_db):
        report = _fake_report(url="https://example.com")
        db.save_audit(report, temp_db)
        trend = db.get_score_trend("https://example.com", temp_db)
        assert "score" in trend[0]
        assert "created_at" in trend[0]
        assert trend[0]["score"] == report.overall_score
