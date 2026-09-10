"""
main.py
-------
CLI entry point for the Landing Page Health Auditor.

Usage:
    python main.py https://example.com
    python main.py cubehead.info

Combines all available check categories into one report:
  - Week 1: Technical Health Checks (checks.py)
  - Week 2: Tracking & UTM Integrity Checks (utm_checks.py)
  - Week 3: Lead Form Quality Checks (form_checks.py)

As of Week 4, the actual "fetch + run checks + combine score" logic
lives in report.py, shared with the new web frontend (app.py) so the
CLI and the web UI can never drift out of sync. This file is now just
responsible for printing that shared report to the terminal.
"""

import sys

from report import build_report


SEVERITY_ICON = {
    "critical": "[CRITICAL]",
    "warning": "[WARNING] ",
    "info": "[OK]      ",
}


def print_report(url: str) -> None:
    print(f"\nAuditing: {url}")
    print("=" * 60)

    report = build_report(url)

    for category in report.categories:
        print(f"\n--- {category.name} ---")
        for r in category.results:
            icon = SEVERITY_ICON.get(r.severity, "[--]")
            status = "PASS" if r.passed else "FAIL"
            print(f"{icon} {status:5} | {r.name:28} | {r.message}")
            if r.details:
                for d in r.details[:5]:
                    print(f"              -> {d}")
        print(f"{category.name} score: {category.score}/100")

    print("\n" + "=" * 60)
    print(f"OVERALL LANDING PAGE HEALTH SCORE: {report.overall_score}/100")
    print("=" * 60)


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <url>")
        print("Example: python main.py cubehead.info")
        sys.exit(1)

    url = sys.argv[1]
    print_report(url)


if __name__ == "__main__":
    main()
