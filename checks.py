"""
checks.py
---------
Week 1 scope: Technical Health Checks.

Takes a PageData object (from crawler.py) and runs a set of independent
checks against it. Each check returns a CheckResult so the report layer
can display pass/fail/warning + a human-readable message + score impact.

Later weeks (UTM/tracking, lead-form quality) will add their own
check modules following this same pattern, and main.py will combine
all of them into one final score.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from crawler import PageData

# Simple severity weights, used to compute the category score out of 100.
SEVERITY_WEIGHTS = {
    "critical": 25,
    "warning": 10,
    "info": 0,  
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str  # "critical" | "warning" | "info"
    message: str
    details: list = None


def run_technical_checks(page: PageData) -> list[CheckResult]:
    """Run all Week 1 technical health checks and return the results."""
    if page.error:
        return [CheckResult(
            name="Page reachability",
            passed=False,
            severity="critical",
            message=f"Could not audit page: {page.error}",
        )]

    results = []
    results.append(_check_status_code(page))
    results.append(_check_https(page))
    results.append(_check_load_time(page))
    results.append(_check_broken_images(page))
    results.append(_check_alt_text(page))
    results.append(_check_meta_robots(page))
    results.append(_check_broken_links_sample(page))
    results.append(_check_viewport_meta(page))
    return results


def _check_status_code(page: PageData) -> CheckResult:
    if page.status_code and 200 <= page.status_code < 300:
        return CheckResult(
            "HTTP status", True, "info",
            f"Page responded with {page.status_code} OK."
        )
    return CheckResult(
        "HTTP status", False, "critical",
        f"Page responded with status {page.status_code}."
    )


def _check_https(page: PageData) -> CheckResult:
    scheme = urlparse(page.final_url or page.url).scheme
    if scheme == "https":
        return CheckResult("HTTPS/SSL", True, "info", "Page is served over HTTPS.")
    return CheckResult(
        "HTTPS/SSL", False, "critical",
        "Page is NOT served over HTTPS — this hurts trust and can trigger browser warnings."
    )


def _check_load_time(page: PageData) -> CheckResult:
    t = page.load_time_ms or 0
    if t < 1500:
        return CheckResult("Load time", True, "info", f"Page loaded in {t} ms (good).")
    elif t < 3500:
        return CheckResult(
            "Load time", False, "warning",
            f"Page loaded in {t} ms — a bit slow. Aim for under 1500 ms for landing pages."
        )
    return CheckResult(
        "Load time", False, "critical",
        f"Page loaded in {t} ms — this is likely hurting conversion rate significantly."
    )


def _check_broken_images(page: PageData) -> CheckResult:
    broken = [img for img in page.images if not img["src"]]
    if not broken:
        return CheckResult(
            "Image sources", True, "info",
            f"All {len(page.images)} image tag(s) have a src attribute."
        )
    return CheckResult(
        "Image sources", False, "warning",
        f"{len(broken)} of {len(page.images)} image tag(s) have an empty/missing src.",
        details=[str(i) for i in range(len(broken))],
    )


def _check_alt_text(page: PageData) -> CheckResult:
    if not page.images:
        return CheckResult("Alt text", True, "info", "No images found on page.")
    missing = [img for img in page.images if not img["has_alt"]]
    if not missing:
        return CheckResult(
            "Alt text", True, "info",
            f"All {len(page.images)} image(s) have alt text."
        )
    return CheckResult(
        "Alt text", False, "warning",
        f"{len(missing)} of {len(page.images)} image(s) are missing alt text "
        "(hurts accessibility and SEO)."
    )


def _check_meta_robots(page: PageData) -> CheckResult:
    robots = page.meta_tags.get("robots", "")
    if not robots:
        return CheckResult(
            "Meta robots / indexability", True, "info",
            "No robots meta tag found (page is indexable by default)."
        )
    robots_lower = robots.lower()
    if "noindex" in robots_lower or "nofollow" in robots_lower:
        return CheckResult(
            "Meta robots / indexability", False, "warning",
            f"Page has robots meta set to '{robots}'. This blocks search engines "
            "from indexing/following the page, intentional for private pages, "
            "but a problem if this page is meant to attract organic or referral traffic."
        )
    return CheckResult(
        "Meta robots / indexability", True, "info",
        f"Robots meta present and not blocking indexing ('{robots}')."
    )


def _check_broken_links_sample(page: PageData, sample_size: int = 8) -> CheckResult:
    """
    Checks a sample of internal links for reachability (HEAD request).
    Sampled (not exhaustive) to keep audits fast, full-site link
    checking is a good Week 2+ extension.
    """
    import requests

    internal_links = [l for l in page.links if l["is_internal"]][:sample_size]
    if not internal_links:
        return CheckResult("Internal links", True, "info", "No internal links found to check.")

    broken = []
    for link in internal_links:
        try:
            r = requests.head(link["href"], timeout=5, allow_redirects=True)
            if r.status_code >= 400:
                broken.append((link["href"], r.status_code))
        except requests.exceptions.RequestException:
            broken.append((link["href"], "unreachable"))

    if not broken:
        return CheckResult(
            "Internal links", True, "info",
            f"Checked {len(internal_links)} internal link(s), all reachable."
        )
    return CheckResult(
        "Internal links", False, "critical",
        f"{len(broken)} of {len(internal_links)} sampled internal link(s) are broken.",
        details=[f"{url} -> {status}" for url, status in broken],
    )


def _check_viewport_meta(page: PageData) -> CheckResult:
    viewport = page.meta_tags.get("viewport", "")
    if viewport:
        return CheckResult(
            "Mobile viewport", True, "info",
            "Viewport meta tag present, page is configured for responsive/mobile display."
        )
    return CheckResult(
        "Mobile viewport", False, "warning",
        "No viewport meta tag found, page may not render well on mobile devices."
    )


def compute_category_score(results: list[CheckResult]) -> int:
    """Turn a list of CheckResults into a 0-100 score for this category."""
    score = 100
    for r in results:
        if not r.passed:
            score -= SEVERITY_WEIGHTS.get(r.severity, 0)
    return max(0, score)
