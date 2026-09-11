"""
test_checks.py
---------------
Tests for checks.py — the Week 1 technical health checks.

Each check is tested for both its "pass" and "fail" branches, using
synthetic PageData objects built from HTML (no network required).
"""

from conftest import make_page
from checks import (
    run_technical_checks,
    compute_category_score,
    _check_https,
    _check_load_time,
    _check_broken_images,
    _check_alt_text,
    _check_meta_robots,
    _check_viewport_meta,
    _check_status_code,
)


class TestHttpsCheck:
    def test_https_passes(self):
        page = make_page("<html></html>", url="https://example.com")
        result = _check_https(page)
        assert result.passed is True

    def test_http_fails(self):
        page = make_page("<html></html>", url="http://example.com")
        result = _check_https(page)
        assert result.passed is False
        assert result.severity == "critical"


class TestLoadTimeCheck:
    def test_fast_load_passes(self):
        page = make_page("<html></html>")
        page.load_time_ms = 500
        result = _check_load_time(page)
        assert result.passed is True

    def test_slow_load_is_warning(self):
        page = make_page("<html></html>")
        page.load_time_ms = 2500
        result = _check_load_time(page)
        assert result.passed is False
        assert result.severity == "warning"

    def test_very_slow_load_is_critical(self):
        page = make_page("<html></html>")
        page.load_time_ms = 5000
        result = _check_load_time(page)
        assert result.passed is False
        assert result.severity == "critical"


class TestBrokenImagesCheck:
    def test_all_images_have_src_passes(self):
        page = make_page('<img src="/a.png"><img src="/b.png">')
        result = _check_broken_images(page)
        assert result.passed is True

    def test_missing_src_fails(self):
        page = make_page('<img src="/a.png"><img src="">')
        result = _check_broken_images(page)
        assert result.passed is False
        assert result.severity == "warning"


class TestAltTextCheck:
    def test_no_images_passes_trivially(self):
        page = make_page("<p>No images.</p>")
        result = _check_alt_text(page)
        assert result.passed is True

    def test_all_images_have_alt_passes(self):
        page = make_page('<img src="/a.png" alt="A"><img src="/b.png" alt="B">')
        result = _check_alt_text(page)
        assert result.passed is True

    def test_missing_alt_fails(self):
        page = make_page('<img src="/a.png" alt="A"><img src="/b.png">')
        result = _check_alt_text(page)
        assert result.passed is False
        assert "1 of 2" in result.message


class TestMetaRobotsCheck:
    def test_no_robots_tag_passes(self):
        page = make_page("<p>No meta.</p>")
        result = _check_meta_robots(page)
        assert result.passed is True

    def test_noindex_fails(self):
        page = make_page('<meta name="robots" content="noindex,nofollow">')
        result = _check_meta_robots(page)
        assert result.passed is False
        assert result.severity == "warning"

    def test_indexable_robots_tag_passes(self):
        page = make_page('<meta name="robots" content="index,follow">')
        result = _check_meta_robots(page)
        assert result.passed is True


class TestViewportCheck:
    def test_viewport_present_passes(self):
        page = make_page('<meta name="viewport" content="width=device-width, initial-scale=1">')
        result = _check_viewport_meta(page)
        assert result.passed is True

    def test_viewport_missing_fails(self):
        page = make_page("<p>No viewport tag.</p>")
        result = _check_viewport_meta(page)
        assert result.passed is False
        assert result.severity == "warning"


class TestStatusCodeCheck:
    def test_200_passes(self):
        page = make_page("<html></html>", status_code=200)
        result = _check_status_code(page)
        assert result.passed is True

    def test_404_fails(self):
        page = make_page("<html></html>", status_code=404)
        result = _check_status_code(page)
        assert result.passed is False
        assert result.severity == "critical"


class TestRunTechnicalChecksIntegration:
    def test_returns_error_result_if_page_had_fetch_error(self):
        page = make_page("<html></html>")
        page.error = "Connection error: refused"
        results = run_technical_checks(page)
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == "critical"

    def test_perfect_page_returns_high_score(self):
        html = '''
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <img src="/hero.png" alt="Hero image">
        </body>
        </html>
        '''
        page = make_page(html, url="https://example.com")
        page.load_time_ms = 400
        results = run_technical_checks(page)
        score = compute_category_score(results)
        assert score == 100

    def test_problematic_page_returns_lower_score(self):
        html = '''
        <html>
        <body>
            <img src="">
            <meta name="robots" content="noindex,nofollow">
        </body>
        </html>
        '''
        page = make_page(html, url="http://example.com")  # http, not https
        page.load_time_ms = 4000  # slow
        results = run_technical_checks(page)
        score = compute_category_score(results)
        assert score < 100


class TestComputeCategoryScore:
    def test_all_passing_gives_100(self):
        from checks import CheckResult
        results = [CheckResult("a", True, "info", "ok")]
        assert compute_category_score(results) == 100

    def test_critical_failure_deducts_25(self):
        from checks import CheckResult
        results = [CheckResult("a", False, "critical", "bad")]
        assert compute_category_score(results) == 75

    def test_score_never_goes_below_zero(self):
        from checks import CheckResult
        results = [CheckResult(f"check{i}", False, "critical", "bad") for i in range(10)]
        assert compute_category_score(results) == 0
