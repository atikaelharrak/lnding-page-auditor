"""
report.py
---------
Week 4 scope: shared report-building logic.

Both main.py (CLI) and app.py (web frontend) need to do the same thing:
fetch a URL, run all check categories, and combine them into one
overall score. Previously this logic lived only inside main.py's
print_report() function, which meant the web frontend would have had
to duplicate it or import CLI-printing code by mistake.

This module extracts that logic into a single build_report() function
that returns a plain, JSON-serializable-friendly data structure —
CATEGORIES stays the single source of truth for which check categories
exist and how they're weighted, used by both the CLI and the web app.
"""

from dataclasses import dataclass, asdict

from crawler import fetch_page
from checks import run_technical_checks, compute_category_score
from utm_checks import run_utm_checks
from form_checks import run_form_checks

# Each category: (display name, check function, weight toward overall score)
CATEGORIES = [
    ("Technical Health", run_technical_checks, 1 / 3),
    ("Tracking & UTM Integrity", run_utm_checks, 1 / 3),
    ("Lead Form Quality", run_form_checks, 1 / 3),
]


@dataclass
class CategoryReport:
    name: str
    score: int
    results: list  # list of CheckResult (from checks.py)


@dataclass
class AuditReport:
    url: str
    final_url: str
    fetch_error: str | None
    overall_score: int
    categories: list  # list of CategoryReport


def build_report(url: str) -> AuditReport:
    """
    Fetch the given URL once, run every check category against it, and
    return a single combined AuditReport. This is the one place both
    main.py and app.py call into — keeps them from drifting out of sync.
    """
    page = fetch_page(url)

    categories = []
    overall_score = 0.0

    for name, check_fn, weight in CATEGORIES:
        results = check_fn(page)
        score = compute_category_score(results)
        categories.append(CategoryReport(name=name, score=score, results=results))
        overall_score += score * weight

    return AuditReport(
        url=url,
        final_url=page.final_url or page.url,
        fetch_error=page.error,
        overall_score=round(overall_score),
        categories=categories,
    )


def report_to_dict(report: AuditReport) -> dict:
    """
    Convert an AuditReport (which contains CheckResult dataclass instances)
    into a plain dict/list structure, for use in JSON APIs or templates.
    """
    return {
        "url": report.url,
        "final_url": report.final_url,
        "fetch_error": report.fetch_error,
        "overall_score": report.overall_score,
        "categories": [
            {
                "name": cat.name,
                "score": cat.score,
                "results": [asdict(r) for r in cat.results],
            }
            for cat in report.categories
        ],
    }
