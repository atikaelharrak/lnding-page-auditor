"""
test_report.py
---------------
Tests for report.py — the shared report-building module used by both
main.py (CLI) and app.py (web frontend).

Uses unittest.mock to replace fetch_page so these tests don't depend on
the network, and to verify build_report() correctly wires together all
three check categories with the right weighting.
"""

from unittest.mock import patch

from conftest import make_page
from report import build_report, report_to_dict, CATEGORIES


class TestCategoriesConfig:
    def test_three_categories_registered(self):
        assert len(CATEGORIES) == 3

    def test_category_weights_sum_to_one(self):
        total_weight = sum(weight for _, _, weight in CATEGORIES)
        assert abs(total_weight - 1.0) < 0.0001

    def test_category_names_match_expected(self):
        names = {name for name, _, _ in CATEGORIES}
        assert names == {"Technical Health", "Tracking & UTM Integrity", "Lead Form Quality"}


class TestBuildReport:
    def test_fetch_error_still_produces_a_report(self):
        """Even if the page fails to load, build_report should not crash —
        every category's check function handles page.error gracefully."""
        page = make_page("<html></html>")
        page.error = "Connection error: refused"

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://unreachable-site.example")

        assert report.fetch_error == "Connection error: refused"
        assert len(report.categories) == 3
        # every category should report a critical failure due to the fetch error
        for cat in report.categories:
            assert cat.score < 100

    def test_perfect_page_scores_100_overall(self):
        html = '''
        <html>
        <head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
        <body>
            <img src="/hero.png" alt="Hero image">
            <a href="https://partner.com/offer?utm_source=facebook&utm_medium=cpc&utm_campaign=x">Offer</a>
            <form action="/submit-lead" method="post">
                <input type="email" name="email" required>
                <input type="text" name="honeypot_field" style="display:none">
                <div class="g-recaptcha"></div>
            </form>
        </body>
        </html>
        '''
        page = make_page(html, url="https://example.com")
        page.load_time_ms = 300

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        assert report.overall_score == 100

    def test_overall_score_is_weighted_average_of_categories(self):
        page = make_page("<html></html>", url="https://example.com")
        page.load_time_ms = 300

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        expected = round(sum(
            cat.score * weight
            for cat, (_, _, weight) in zip(report.categories, CATEGORIES)
        ))
        assert report.overall_score == expected

    def test_final_url_falls_back_to_original_url_when_not_set(self):
        page = make_page("<html></html>", url="https://example.com")
        page.final_url = ""  # simulate no redirect info available

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        assert report.final_url == "https://example.com"


class TestReportToDict:
    def test_produces_json_serializable_structure(self):
        import json

        page = make_page("<html></html>", url="https://example.com")
        page.load_time_ms = 300

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        as_dict = report_to_dict(report)
        # Should not raise — confirms every nested value is JSON-safe
        serialized = json.dumps(as_dict)
        assert "overall_score" in serialized

    def test_dict_has_expected_top_level_keys(self):
        page = make_page("<html></html>", url="https://example.com")
        page.load_time_ms = 300

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        as_dict = report_to_dict(report)
        assert set(as_dict.keys()) == {
            "url", "final_url", "fetch_error", "overall_score", "categories"
        }

    def test_each_category_dict_has_results_list(self):
        page = make_page("<html></html>", url="https://example.com")
        page.load_time_ms = 300

        with patch("report.fetch_page", return_value=page):
            report = build_report("https://example.com")

        as_dict = report_to_dict(report)
        for cat in as_dict["categories"]:
            assert "name" in cat
            assert "score" in cat
            assert isinstance(cat["results"], list)
            assert len(cat["results"]) > 0
