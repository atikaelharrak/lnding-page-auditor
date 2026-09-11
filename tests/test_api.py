"""
test_api.py
-----------
Tests for api.py — the REST API blueprint.

Uses Flask's test client against the real app (with the API blueprint
registered), and a temporary database per test so these tests never
touch the real audits.db and can't interfere with each other.

fetch_page is mocked so these tests stay fast and offline — same
pattern as the rest of the test suite.

Job-endpoint tests (TestSubmitJobEndpoint, TestGetJobStatusEndpoint)
poll while the mock.patch() context is still active, for the same
reason documented in test_jobs.py: the audit runs on a background
worker thread, and letting the patch context exit before that thread
runs would let a real network call slip through.
"""

import time
from unittest.mock import patch

import pytest

import db
from conftest import make_page
from app import app as flask_app

POLL_TIMEOUT_SECONDS = 5
POLL_INTERVAL_SECONDS = 0.02


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    A Flask test client wired to a temporary, isolated database.
    We monkeypatch db.DB_PATH so every db.* call in api.py/app.py
    (which use the module-level default) writes to this temp file
    instead of the real audits.db.
    """
    test_db_path = tmp_path / "test_audits.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    db.init_db(test_db_path)

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


def _poll_job_via_api(client, job_id, timeout=POLL_TIMEOUT_SECONDS):
    """Poll GET /api/jobs/<id> until it reaches a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        data = resp.get_json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


def _mock_page(url="https://example.com"):
    html = '''
    <html><body>
        <img src="/a.png" alt="A">
        <a href="https://partner.com/o?utm_source=x&utm_medium=y&utm_campaign=z">Go</a>
        <form action="/submit"><input type="email" name="email" required></form>
    </body></html>
    '''
    page = make_page(html, url=url)
    page.load_time_ms = 300
    return page


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestRunAuditEndpoint:
    def test_valid_url_returns_201_with_report(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/audit", json={"url": "https://example.com"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert "overall_score" in data
        assert "id" in data
        assert len(data["categories"]) == 3

    def test_missing_url_returns_400(self, client):
        resp = client.post("/api/audit", json={})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_empty_url_returns_400(self, client):
        resp = client.post("/api/audit", json={"url": "   "})
        assert resp.status_code == 400

    def test_no_json_body_returns_400_not_500(self, client):
        """Should handle a missing/malformed body gracefully, not crash."""
        resp = client.post("/api/audit")
        assert resp.status_code == 400

    def test_audit_is_persisted_to_database(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/audit", json={"url": "https://example.com"})
        audit_id = resp.get_json()["id"]
        stored = db.get_audit_by_id(audit_id, db.DB_PATH)
        assert stored is not None
        assert stored["url"] == "https://example.com"

    def test_fetch_exception_returns_500_not_crash(self, client):
        with patch("report.fetch_page", side_effect=RuntimeError("boom")):
            resp = client.post("/api/audit", json={"url": "https://example.com"})
        assert resp.status_code == 500
        assert "error" in resp.get_json()


class TestListAuditsEndpoint:
    def test_empty_database_returns_empty_list(self, client):
        resp = client.get("/api/audits")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["audits"] == []
        assert data["count"] == 0

    def test_returns_saved_audits(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            client.post("/api/audit", json={"url": "https://example.com"})

        resp = client.get("/api/audits")
        data = resp.get_json()
        assert data["count"] == 1

    def test_limit_param_is_respected(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            # force=True bypasses the cache so each call is a genuinely
            # new audit row -- otherwise repeated identical requests
            # would correctly return the same cached result (see
            # TestAuditCaching below), and there'd only be 1 row to list.
            for _ in range(5):
                client.post("/api/audit", json={"url": "https://example.com", "force": True})

        resp = client.get("/api/audits?limit=2")
        data = resp.get_json()
        assert data["count"] == 2

    def test_limit_is_clamped_to_max_100(self, client):
        resp = client.get("/api/audits?limit=99999")
        assert resp.status_code == 200  # doesn't error, just clamps internally


class TestGetAuditByIdEndpoint:
    def test_existing_id_returns_200(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            post_resp = client.post("/api/audit", json={"url": "https://example.com"})
        audit_id = post_resp.get_json()["id"]

        resp = client.get(f"/api/audits/{audit_id}")
        assert resp.status_code == 200
        assert resp.get_json()["url"] == "https://example.com"

    def test_nonexistent_id_returns_404(self, client):
        resp = client.get("/api/audits/999999")
        assert resp.status_code == 404
        assert "error" in resp.get_json()


class TestHistoryEndpoint:
    def test_missing_url_param_returns_400(self, client):
        resp = client.get("/api/history")
        assert resp.status_code == 400

    def test_unaudited_url_returns_empty_history(self, client):
        resp = client.get("/api/history?url=https://never-audited.com")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["history"] == []
        assert data["count"] == 0

    def test_returns_history_for_audited_url(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            # force=True so both calls create separate history rows,
            # rather than the second being served from cache.
            client.post("/api/audit", json={"url": "https://example.com", "force": True})
            client.post("/api/audit", json={"url": "https://example.com", "force": True})

        resp = client.get("/api/history?url=https://example.com")
        data = resp.get_json()
        assert data["count"] == 2


class TestTrendEndpoint:
    def test_missing_url_param_returns_400(self, client):
        resp = client.get("/api/trend")
        assert resp.status_code == 400

    def test_unaudited_url_returns_empty_trend(self, client):
        resp = client.get("/api/trend?url=https://never-audited.com")
        assert resp.status_code == 200
        assert resp.get_json()["trend"] == []

    def test_returns_score_series(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            client.post("/api/audit", json={"url": "https://example.com"})

        resp = client.get("/api/trend?url=https://example.com")
        data = resp.get_json()
        assert data["count"] == 1
        assert "score" in data["trend"][0]
        assert "created_at" in data["trend"][0]


class TestSubmitJobEndpoint:
    def test_returns_202_with_job_id_and_pending_or_running_status(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/jobs", json={"url": "https://example.com"})
            data = resp.get_json()
            assert resp.status_code == 202
            assert "id" in data
            assert data["status"] in ("pending", "running")
            _poll_job_via_api(client, data["id"])  # let it finish before patch exits

    def test_missing_url_returns_400(self, client):
        resp = client.post("/api/jobs", json={})
        assert resp.status_code == 400

    def test_empty_url_returns_400(self, client):
        resp = client.post("/api/jobs", json={"url": "  "})
        assert resp.status_code == 400


class TestGetJobStatusEndpoint:
    def test_polling_reaches_done_with_result(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/jobs", json={"url": "https://example.com"})
            job_id = resp.get_json()["id"]
            final = _poll_job_via_api(client, job_id)

        assert final["status"] == "done"
        assert final["result"]["overall_score"] is not None

    def test_job_result_is_also_persisted_to_database(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/jobs", json={"url": "https://example.com"})
            job_id = resp.get_json()["id"]
            final = _poll_job_via_api(client, job_id)

        # The job's result should include the database id assigned by
        # db.save_audit, proving the background job persisted correctly.
        assert final["result"]["id"] is not None
        history_resp = client.get("/api/history?url=https://example.com")
        assert history_resp.get_json()["count"] == 1

    def test_nonexistent_job_id_returns_404(self, client):
        resp = client.get("/api/jobs/this-does-not-exist")
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_failed_job_reports_failed_status_and_error(self, client):
        with patch("report.fetch_page", side_effect=RuntimeError("boom")):
            resp = client.post("/api/jobs", json={"url": "https://example.com"})
            job_id = resp.get_json()["id"]
            final = _poll_job_via_api(client, job_id)

        assert final["status"] == "failed"
        assert "boom" in final["error"]


class TestAuditCaching:
    """
    End-to-end tests confirming POST /api/audit and POST /api/jobs
    actually use the cache -- i.e. a second identical request doesn't
    trigger a second real crawl (fetch_page is only called once).
    """

    def test_second_audit_request_is_served_from_cache(self, client):
        with patch("report.fetch_page", return_value=_mock_page()) as mock_fetch:
            client.post("/api/audit", json={"url": "https://example.com"})
            resp2 = client.post("/api/audit", json={"url": "https://example.com"})

        # fetch_page should only have been called ONCE -- the second
        # request should have been served from cache, not re-crawled.
        assert mock_fetch.call_count == 1
        assert resp2.get_json().get("cached") is True

    def test_first_audit_request_is_not_marked_as_cached(self, client):
        with patch("report.fetch_page", return_value=_mock_page()):
            resp = client.post("/api/audit", json={"url": "https://example.com"})
        assert resp.get_json().get("cached") is False
        assert resp.status_code == 201

    def test_cached_response_has_200_not_201(self, client):
        """201 Created makes sense for a freshly-run audit; a cache hit
        didn't create anything new, so it should be a 200 OK instead."""
        with patch("report.fetch_page", return_value=_mock_page()):
            client.post("/api/audit", json={"url": "https://example.com"})
            resp2 = client.post("/api/audit", json={"url": "https://example.com"})
        assert resp2.status_code == 200

    def test_force_true_bypasses_cache(self, client):
        with patch("report.fetch_page", return_value=_mock_page()) as mock_fetch:
            client.post("/api/audit", json={"url": "https://example.com"})
            resp2 = client.post("/api/audit", json={"url": "https://example.com", "force": True})

        # force=True should have triggered a SECOND real fetch_page call.
        assert mock_fetch.call_count == 2
        assert resp2.get_json().get("cached") is False

    def test_different_urls_are_not_confused_by_cache(self, client):
        with patch("report.fetch_page", return_value=_mock_page()) as mock_fetch:
            client.post("/api/audit", json={"url": "https://site-a.com"})
            client.post("/api/audit", json={"url": "https://site-b.com"})

        # Two distinct URLs should both trigger real crawls -- neither
        # should be treated as a cache hit for the other.
        assert mock_fetch.call_count == 2

    def test_job_endpoint_also_uses_cache(self, client):
        with patch("report.fetch_page", return_value=_mock_page()) as mock_fetch:
            resp1 = client.post("/api/audit", json={"url": "https://example.com"})
            resp2 = client.post("/api/jobs", json={"url": "https://example.com"})
            job_id = resp2.get_json()["id"]
            final = _poll_job_via_api(client, job_id)

        # The job should be immediately "done" from cache -- no second
        # real fetch_page call, and status 200 (not 202 Accepted, since
        # nothing was actually queued for background processing).
        assert mock_fetch.call_count == 1
        assert resp2.status_code == 200
        assert final["status"] == "done"
        assert final["result"]["cached"] is True
