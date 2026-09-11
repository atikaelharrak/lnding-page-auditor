"""
test_app.py
-----------
Tests for app.py : the Flask web frontend.

Uses Flask's built-in test client, which simulates HTTP requests
in-process without needing a real running server. Network-dependent
behavior (build_report's fetch_page call) is mocked so these tests
stay fast and offline. Each test uses a temporary, isolated database
(same pattern as test_api.py) so these tests never touch the real
audits.db file.
"""

from unittest.mock import patch

import pytest

import db
from conftest import make_page
from app import app as flask_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db_path = tmp_path / "test_audits.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    db.init_db(test_db_path)

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


class TestIndexGet:
    def test_get_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_get_shows_empty_form_no_report(self, client):
        resp = client.get("/")
        assert b"Landing Page Health Auditor" in resp.data
        assert b"Overall Health Score" not in resp.data


class TestIndexPost:
    def _mock_page(self):
        html = '''
        <html><body>
            <img src="/a.png" alt="A">
            <a href="https://partner.com/o?utm_source=x&utm_medium=y&utm_campaign=z">Go</a>
            <form action="/submit"><input type="email" name="email" required></form>
        </body></html>
        '''
        page = make_page(html, url="https://example.com")
        page.load_time_ms = 300
        return page

    def test_valid_url_renders_report(self, client):
        with patch("report.fetch_page", return_value=self._mock_page()):
            resp = client.post("/", data={"url": "https://example.com"})
        assert resp.status_code == 200
        assert b"Overall Health Score" in resp.data
        assert b"Technical Health" in resp.data
        assert b"Tracking &amp; UTM Integrity" in resp.data or b"Tracking & UTM Integrity" in resp.data
        assert b"Lead Form Quality" in resp.data

    def test_empty_url_shows_error_not_report(self, client):
        resp = client.post("/", data={"url": ""})
        assert resp.status_code == 200
        assert b"Please enter a URL" in resp.data
        assert b"Overall Health Score" not in resp.data

    def test_whitespace_only_url_treated_as_empty(self, client):
        resp = client.post("/", data={"url": "   "})
        assert b"Please enter a URL" in resp.data

    def test_submitted_url_is_preserved_in_input_field(self, client):
        with patch("report.fetch_page", return_value=self._mock_page()):
            resp = client.post("/", data={"url": "https://example.com"})
        assert b"https://example.com" in resp.data

    def test_fetch_error_shown_as_alert(self, client):
        page = make_page("<html></html>")
        page.error = "Connection error: refused"
        with patch("report.fetch_page", return_value=page):
            resp = client.post("/", data={"url": "https://unreachable.example"})
        assert b"Connection error" in resp.data

    def test_unexpected_exception_does_not_crash_the_page(self, client):
        """
        Defensive test: if something inside build_report raised an
        unexpected exception, the page should show a friendly error
        instead of a raw 500 traceback.
        """
        with patch("report.fetch_page", side_effect=RuntimeError("boom")):
            resp = client.post("/", data={"url": "https://example.com"})
        assert resp.status_code == 200
        assert b"Something went wrong" in resp.data

    def test_successful_audit_is_saved_to_database(self, client):
        with patch("report.fetch_page", return_value=self._mock_page()):
            client.post("/", data={"url": "https://example.com"})
        history = db.get_audit_history("https://example.com", db_path=db.DB_PATH)
        assert len(history) == 1

    def test_history_not_shown_after_only_one_audit(self, client):
        """History table only makes sense with 2+ past audits to compare."""
        with patch("report.fetch_page", return_value=self._mock_page()):
            resp = client.post("/", data={"url": "https://example.com"})
        assert b"Audit History" not in resp.data

    def test_history_shown_after_multiple_audits_of_same_url(self, client):
        with patch("report.fetch_page", return_value=self._mock_page()):
            client.post("/", data={"url": "https://example.com"})
            resp = client.post("/", data={"url": "https://example.com"})
        assert b"Audit History" in resp.data

    def test_failed_audit_is_not_saved_to_database(self, client):
        """If build_report itself raises, there's nothing valid to save."""
        with patch("report.fetch_page", side_effect=RuntimeError("boom")):
            client.post("/", data={"url": "https://example.com"})
        history = db.get_audit_history("https://example.com", db_path=db.DB_PATH)
        assert history == []
