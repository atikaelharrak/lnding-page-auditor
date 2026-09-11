"""
test_form_checks.py
--------------------
Tests for form_checks.py — the Week 3 lead-form quality checks.

Covers form analysis (CAPTCHA detection, honeypot detection, lead-form
classification) plus each of the 5 checks that run when at least one
lead-capture form is found, using synthetic HTML (no network required).
"""

from conftest import make_page
from form_checks import (
    run_form_checks,
    _analyze_form,
    _check_forms_present,
    _check_captcha_presence,
    _check_honeypot_presence,
    _check_required_field_validation,
    _check_form_action_configured,
    _check_https_form_submission,
)


class TestAnalyzeForm:
    def test_detects_recaptcha_high_confidence(self):
        html = '''
        <form action="/submit" method="post">
            <input type="email" name="email">
            <div class="g-recaptcha" data-sitekey="x"></div>
        </form>
        '''
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.has_captcha_signal is True
        assert analysis.captcha_confidence == "high"

    def test_detects_hcaptcha_high_confidence(self):
        html = '<form action="/submit"><input type="email" name="email"><div class="h-captcha"></div></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.captcha_confidence == "high"

    def test_generic_captcha_word_is_low_confidence(self):
        html = '<form action="/submit"><input type="email" name="email"><p>Please solve the captcha</p></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.has_captcha_signal is True
        assert analysis.captcha_confidence == "low"

    def test_no_captcha_signal_detected(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.has_captcha_signal is False
        assert analysis.captcha_confidence == "none"

    def test_detects_honeypot_field_by_name(self):
        html = '''
        <form action="/submit">
            <input type="email" name="email">
            <input type="text" name="honeypot_field">
        </form>
        '''
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert len(analysis.honeypot_fields) == 1

    def test_no_honeypot_when_none_present(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.honeypot_fields == []

    def test_form_with_email_field_classified_as_lead_form(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.looks_like_lead_form is True

    def test_form_with_name_field_classified_as_lead_form(self):
        html = '<form action="/submit"><input type="text" name="full_name"></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.looks_like_lead_form is True

    def test_form_with_unrelated_fields_not_classified_as_lead_form(self):
        html = '<form action="/search"><input type="text" name="query"></form>'
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert analysis.looks_like_lead_form is False

    def test_required_fields_captured(self):
        html = '''
        <form action="/submit">
            <input type="email" name="email" required>
            <input type="text" name="company">
        </form>
        '''
        page = make_page(html)
        analysis = _analyze_form(0, page.forms[0])
        assert len(analysis.required_fields) == 1
        assert analysis.required_fields[0]["name"] == "email"


class TestFormsPresentCheck:
    def test_no_forms_passes_informationally(self):
        page = make_page("<p>No forms here.</p>")
        result = _check_forms_present(page, [])
        assert result.passed is True

    def test_forms_present_but_none_are_lead_forms(self):
        html = '<form action="/search"><input type="text" name="q"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_forms_present(page, analyses)
        assert result.passed is True
        assert "none look like lead-capture" in result.message

    def test_lead_forms_detected(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_forms_present(page, analyses)
        assert result.passed is True
        assert "1 likely lead-capture form" in result.message


class TestCaptchaCheck:
    def test_all_forms_have_captcha_passes(self):
        html = '<form action="/submit"><input type="email" name="email"><div class="g-recaptcha"></div></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_captcha_presence(analyses)
        assert result.passed is True

    def test_missing_captcha_is_critical(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_captcha_presence(analyses)
        assert result.passed is False
        assert result.severity == "critical"

    def test_low_confidence_captcha_is_warning_not_critical(self):
        html = '<form action="/submit"><input type="email" name="email"><p>captcha required</p></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_captcha_presence(analyses)
        assert result.passed is False
        assert result.severity == "warning"


class TestHoneypotCheck:
    def test_honeypot_present_passes(self):
        html = '''
        <form action="/submit">
            <input type="email" name="email">
            <input type="text" name="hp_field">
        </form>
        '''
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_honeypot_presence(analyses)
        assert result.passed is True

    def test_honeypot_missing_is_warning(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_honeypot_presence(analyses)
        assert result.passed is False
        assert result.severity == "warning"


class TestRequiredFieldCheck:
    def test_has_required_field_passes(self):
        html = '<form action="/submit"><input type="email" name="email" required></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_required_field_validation(analyses)
        assert result.passed is True

    def test_no_required_fields_is_warning(self):
        html = '<form action="/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_required_field_validation(analyses)
        assert result.passed is False
        assert result.severity == "warning"


class TestFormActionCheck:
    def test_distinct_action_passes(self):
        html = '<form action="/submit-lead"><input type="email" name="email"></form>'
        page = make_page(html, url="https://example.com/landing")
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_form_action_configured(analyses, page)
        assert result.passed is True

    def test_empty_action_is_critical(self):
        html = '<form action=""><input type="email" name="email"></form>'
        page = make_page(html, url="https://example.com/landing")
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_form_action_configured(analyses, page)
        assert result.passed is False
        assert result.severity == "critical"

    def test_action_pointing_at_same_page_is_critical(self):
        html = '<form action="https://example.com/landing"><input type="email" name="email"></form>'
        page = make_page(html, url="https://example.com/landing")
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_form_action_configured(analyses, page)
        assert result.passed is False
        assert result.severity == "critical"


class TestHttpsFormSubmissionCheck:
    def test_https_action_passes(self):
        html = '<form action="https://example.com/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_https_form_submission(analyses)
        assert result.passed is True

    def test_http_action_is_critical(self):
        html = '<form action="http://example.com/submit"><input type="email" name="email"></form>'
        page = make_page(html)
        analyses = [_analyze_form(0, page.forms[0])]
        result = _check_https_form_submission(analyses)
        assert result.passed is False
        assert result.severity == "critical"


class TestRunFormChecksIntegration:
    def test_returns_error_result_if_page_had_fetch_error(self):
        page = make_page("<html></html>")
        page.error = "Connection error: refused"
        results = run_form_checks(page)
        assert len(results) == 1
        assert results[0].passed is False

    def test_no_forms_returns_single_informational_result(self):
        page = make_page("<p>No forms here.</p>")
        results = run_form_checks(page)
        assert len(results) == 1
        assert results[0].passed is True

    def test_non_lead_form_skips_deep_checks(self):
        """A search form (no email/phone/name fields) shouldn't trigger CAPTCHA/honeypot checks."""
        html = '<form action="/search"><input type="text" name="q"></form>'
        page = make_page(html)
        results = run_form_checks(page)
        assert len(results) == 1  # only "Lead form presence", no deep checks run

    def test_well_built_lead_form_passes_everything(self):
        html = '''
        <form action="/submit-lead" method="post">
            <input type="text" name="full_name" required>
            <input type="email" name="email" required>
            <input type="text" name="honeypot_field" style="display:none">
            <div class="g-recaptcha" data-sitekey="xyz"></div>
        </form>
        '''
        page = make_page(html, url="https://example.com/landing")
        results = run_form_checks(page)
        assert all(r.passed for r in results)

    def test_broken_lead_form_fails_multiple_checks(self):
        html = '<form action=""><input type="email" name="email"></form>'
        page = make_page(html, url="https://example.com/landing")
        results = run_form_checks(page)
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 3  # captcha, honeypot, required, action all fail
