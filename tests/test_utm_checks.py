"""
test_utm_checks.py
-------------------
Tests for utm_checks.py : the Week 2 tracking & UTM integrity checks.

Covers each of the 5 checks individually, plus the edge case that was
caught and fixed during manual testing: duplicate query parameter keys
(e.g. ?utm_source=a&utm_source=b) causing parse_qs to return a list
instead of a string, which originally crashed the naming-consistency
check.
"""

from conftest import make_page
from utm_checks import (
    run_utm_checks,
    _analyze_link,
    _check_utm_coverage,
    _check_required_params_complete,
    _check_naming_consistency,
    _check_duplicate_tracking_links,
    _check_malformed_query_strings,
)


class TestAnalyzeLink:
    def test_fully_tagged_link(self):
        href = "https://partner.com/offer?utm_source=facebook&utm_medium=cpc&utm_campaign=summer"
        analysis = _analyze_link(href)
        assert analysis.has_any_utm is True
        assert analysis.missing_required == set()

    def test_untagged_link(self):
        analysis = _analyze_link("https://partner.com/offer")
        assert analysis.has_any_utm is False
        assert analysis.missing_required == {"utm_source", "utm_medium", "utm_campaign"}

    def test_partially_tagged_link_reports_missing(self):
        href = "https://partner.com/offer?utm_source=facebook"
        analysis = _analyze_link(href)
        assert analysis.has_any_utm is True
        assert analysis.missing_required == {"utm_medium", "utm_campaign"}


class TestUtmCoverageCheck:
    def test_no_external_links_passes_trivially(self):
        result = _check_utm_coverage([])
        assert result.passed is True

    def test_full_coverage_passes(self):
        html = '<a href="https://partner.com/o?utm_source=a&utm_medium=b&utm_campaign=c">Go</a>'
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        result = _check_utm_coverage(analyses)
        assert result.passed is True

    def test_zero_coverage_is_critical(self):
        html = '<a href="https://partner.com/offer">Go</a>'
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        result = _check_utm_coverage(analyses)
        assert result.passed is False
        assert result.severity == "critical"

    def test_partial_coverage_is_warning(self):
        html = '''
        <a href="https://partner.com/o1?utm_source=a&utm_medium=b&utm_campaign=c">Tagged</a>
        <a href="https://partner.com/o2">Untagged</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        result = _check_utm_coverage(analyses)
        assert result.passed is False
        assert result.severity == "warning"


class TestRequiredParamsCheck:
    def test_no_tagged_links_passes_trivially(self):
        result = _check_required_params_complete([])
        assert result.passed is True

    def test_complete_tagging_passes(self):
        analysis = _analyze_link("https://p.com/o?utm_source=a&utm_medium=b&utm_campaign=c")
        result = _check_required_params_complete([analysis])
        assert result.passed is True

    def test_incomplete_tagging_fails_with_details(self):
        analysis = _analyze_link("https://p.com/o?utm_source=a&utm_medium=b")  # missing campaign
        result = _check_required_params_complete([analysis])
        assert result.passed is False
        assert result.severity == "warning"
        assert result.details is not None
        assert "utm_campaign" in result.details[0]


class TestNamingConsistencyCheck:
    def test_fewer_than_two_tagged_links_passes_trivially(self):
        result = _check_naming_consistency([])
        assert result.passed is True

    def test_consistent_casing_passes(self):
        html = '''
        <a href="https://p.com/o1?utm_source=facebook&utm_medium=cpc&utm_campaign=a">L1</a>
        <a href="https://p.com/o2?utm_source=facebook&utm_medium=cpc&utm_campaign=b">L2</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        result = _check_naming_consistency(analyses)
        assert result.passed is True

    def test_inconsistent_casing_fails(self):
        html = '''
        <a href="https://p.com/o1?utm_source=Facebook&utm_medium=cpc&utm_campaign=a">L1</a>
        <a href="https://p.com/o2?utm_source=facebook&utm_medium=cpc&utm_campaign=b">L2</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        result = _check_naming_consistency(analyses)
        assert result.passed is False
        assert result.severity == "warning"

    def test_duplicate_param_key_does_not_crash(self):
        """
        Regression test for the bug caught during Week 2 manual testing:
        parse_qs returns a list when a query key is duplicated
        (e.g. ?utm_source=a&utm_source=b), which originally crashed
        this check with 'list' object has no attribute 'lower'.
        """
        html = '''
        <a href="https://p.com/o1?utm_source=google&utm_source=bing&utm_medium=cpc&utm_campaign=a">L1</a>
        <a href="https://p.com/o2?utm_source=google&utm_medium=cpc&utm_campaign=b">L2</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        analyses = [_analyze_link(l["href"]) for l in external]
        # Should not raise
        result = _check_naming_consistency(analyses)
        assert result is not None


class TestDuplicateTrackingLinksCheck:
    def test_no_duplicates_passes(self):
        html = '''
        <a href="https://p.com/o1?utm_source=a">L1</a>
        <a href="https://p.com/o2?utm_source=a">L2</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        result = _check_duplicate_tracking_links(external)
        assert result.passed is True

    def test_exact_duplicates_fail(self):
        html = '''
        <a href="https://p.com/offer?utm_source=a">L1</a>
        <a href="https://p.com/offer?utm_source=a">L1 again</a>
        '''
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        result = _check_duplicate_tracking_links(external)
        assert result.passed is False
        assert result.severity == "warning"


class TestMalformedQueryStringsCheck:
    def test_clean_query_strings_pass(self):
        html = '<a href="https://p.com/o?utm_source=a&utm_medium=b">L1</a>'
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        result = _check_malformed_query_strings(external)
        assert result.passed is True

    def test_empty_value_is_flagged(self):
        html = '<a href="https://p.com/o?utm_source=&utm_medium=email">L1</a>'
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        result = _check_malformed_query_strings(external)
        assert result.passed is False
        assert "empty parameter" in result.details[0]

    def test_duplicate_key_is_flagged(self):
        html = '<a href="https://p.com/o?utm_source=a&utm_source=b">L1</a>'
        page = make_page(html, url="https://example.com")
        external = [l for l in page.links if not l["is_internal"]]
        result = _check_malformed_query_strings(external)
        assert result.passed is False
        assert "duplicate parameter key" in result.details[0]


class TestRunUtmChecksIntegration:
    def test_returns_error_result_if_page_had_fetch_error(self):
        page = make_page("<html></html>")
        page.error = "Connection error: refused"
        results = run_utm_checks(page)
        assert len(results) == 1
        assert results[0].passed is False

    def test_internal_links_are_excluded_from_analysis(self):
        """Internal nav links shouldn't be expected to carry UTM tags."""
        html = '<a href="/about">About</a>'  # internal, no utm expected
        page = make_page(html, url="https://example.com")
        results = run_utm_checks(page)
        coverage_result = next(r for r in results if r.name == "UTM coverage")
        assert coverage_result.passed is True  # trivially passes: no external links to check

    def test_realistic_mixed_page_produces_five_checks(self):
        html = '''
        <a href="/internal-page">Home</a>
        <a href="https://partner.com/o1?utm_source=facebook&utm_medium=cpc&utm_campaign=summer">Full</a>
        <a href="https://partner.com/o2?utm_source=Facebook&utm_medium=cpc">Partial + casing</a>
        <a href="https://partner.com/o3">Untagged</a>
        '''
        page = make_page(html, url="https://example.com")
        results = run_utm_checks(page)
        assert len(results) == 5
        names = {r.name for r in results}
        assert "UTM coverage" in names
        assert "Required UTM parameters" in names
        assert "UTM naming consistency" in names
        assert "Duplicate tracking links" in names
        assert "Malformed tracking parameters" in names
