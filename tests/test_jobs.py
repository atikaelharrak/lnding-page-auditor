"""
test_jobs.py
------------
Tests for jobs.py : background job processing.

These tests exercise real threading (the ThreadPoolExecutor is not
mocked), since the whole point of this module is concurrent execution.
Tests poll with a short sleep loop and a generous timeout to avoid
flakiness, rather than asserting on exact timing.

IMPORTANT pattern used throughout this file: every `_wait_for_job()`
call happens INSIDE the `with patch("report.fetch_page", ...)` block,
not after it. The audit itself runs on a background worker thread, and
if the `with` block exits before that thread actually calls
fetch_page, the mock patch is already undone and the REAL network call
runs instead, a genuine race condition that showed up during
development as an intermittent test failure. Keeping the wait inside
the patch context guarantees the mock is still active for the whole
time the worker thread might need it.

fetch_page is still mocked (no real network calls), and slow_fetch()
is used in one test to add an artificial delay, this proves jobs are
genuinely asynchronous (status is not immediately "done"), rather than
the executor just running so fast the async behavior can't be observed.
"""

import time
from unittest.mock import patch

import pytest

import jobs
from conftest import make_page

POLL_TIMEOUT_SECONDS = 5
POLL_INTERVAL_SECONDS = 0.02


@pytest.fixture(autouse=True)
def reset_job_store():
    """Ensure each test starts with a clean job store, so one test's
    jobs can't be mistaken for another's."""
    jobs._reset_jobs_for_testing()
    yield
    jobs._reset_jobs_for_testing()


def _wait_for_job(job_id: str, timeout: float = POLL_TIMEOUT_SECONDS):
    """
    Poll a job until it reaches a terminal state (done/failed) or times
    out. MUST be called while any relevant mock.patch() context is
    still active, see module docstring.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get_job(job_id)
        if job.status in (jobs.JobStatus.DONE, jobs.JobStatus.FAILED):
            return job
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


def _mock_page():
    page = make_page('<html><body><img src="/a.png" alt="A"></body></html>', url="https://example.com")
    page.load_time_ms = 300
    return page


class TestSubmitAuditJob:
    def test_returns_a_job_id(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            _wait_for_job(job_id)
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_job_is_immediately_retrievable(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = jobs.get_job(job_id)
            assert job is not None
            assert job.url == "https://example.com"
            _wait_for_job(job_id)

    def test_successive_submissions_get_different_ids(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            id1 = jobs.submit_audit_job("https://example.com", save_to_db=False)
            id2 = jobs.submit_audit_job("https://example.com", save_to_db=False)
            _wait_for_job(id1)
            _wait_for_job(id2)
        assert id1 != id2


class TestJobLifecycle:
    def test_job_eventually_reaches_done_status(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.status == jobs.JobStatus.DONE

    def test_done_job_has_a_result(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.result is not None
        assert "overall_score" in job.result

    def test_done_job_has_no_error(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.error is None

    def test_done_job_has_a_finished_at_timestamp(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.finished_at is not None

    def test_job_is_genuinely_asynchronous_not_immediately_done(self):
        """
        Regression-style test: proves submit_audit_job() returns BEFORE
        the audit finishes, using an artificial delay in fetch_page.
        If this ever becomes accidentally synchronous (e.g. someone
        removes the ThreadPoolExecutor), this test should fail.
        """
        def slow_fetch(url, timeout=10):
            time.sleep(0.3)
            return _mock_page()

        with patch("report.fetch_page", side_effect=slow_fetch):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            # Check status immediately -- the slow fetch should not have
            # completed yet, so status must not be a terminal state
            job = jobs.get_job(job_id)
            assert job.status in (jobs.JobStatus.PENDING, jobs.JobStatus.RUNNING)
            _wait_for_job(job_id)  


class TestJobFailureHandling:
    def test_exception_in_fetch_marks_job_as_failed(self):
        with patch("report.fetch_page", side_effect=RuntimeError("simulated crash")):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.status == jobs.JobStatus.FAILED

    def test_failed_job_captures_the_error_message(self):
        with patch("report.fetch_page", side_effect=RuntimeError("simulated crash")):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert "simulated crash" in job.error

    def test_failed_job_has_no_result(self):
        with patch("report.fetch_page", side_effect=RuntimeError("simulated crash")):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        assert job.result is None


class TestGetJob:
    def test_nonexistent_job_id_returns_none(self):
        assert jobs.get_job("this-job-id-does-not-exist") is None


class TestJobToDict:
    def test_to_dict_has_expected_keys(self):
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        as_dict = job.to_dict()
        assert set(as_dict.keys()) == {
            "id", "url", "status", "result", "error", "created_at", "finished_at"
        }

    def test_to_dict_status_is_a_plain_string_not_an_enum(self):
        """Important for JSON serialization -- Flask's jsonify can't
        serialize a raw Enum member, only its .value string."""
        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            job = _wait_for_job(job_id)
        as_dict = job.to_dict()
        assert isinstance(as_dict["status"], str)
        assert as_dict["status"] == "done"


class TestSaveToDbFlag:
    def test_save_to_db_true_persists_audit(self, tmp_path, monkeypatch):
        import db
        test_db_path = tmp_path / "test_audits.db"
        monkeypatch.setattr(db, "DB_PATH", test_db_path)
        db.init_db(test_db_path)

        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=True)
            job = _wait_for_job(job_id)

        assert job.result["id"] is not None  # db.save_audit's returned id was attached
        history = db.get_audit_history("https://example.com", db_path=test_db_path)
        assert len(history) == 1

    def test_save_to_db_false_does_not_persist(self, tmp_path, monkeypatch):
        import db
        test_db_path = tmp_path / "test_audits.db"
        monkeypatch.setattr(db, "DB_PATH", test_db_path)
        db.init_db(test_db_path)

        with patch("report.fetch_page", return_value=_mock_page()):
            job_id = jobs.submit_audit_job("https://example.com", save_to_db=False)
            _wait_for_job(job_id)

        history = db.get_audit_history("https://example.com", db_path=test_db_path)
        assert history == []
