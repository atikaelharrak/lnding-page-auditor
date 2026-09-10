"""
utm_checks.py
-------------
Week 2 scope: Tracking & UTM Integrity Checks.

Analyzes the outbound links already extracted by crawler.py (PageData.links)
and checks how well they're set up for campaign tracking, critical for an
affiliate/performance marketing business where every click needs to be
attributable to a source, campaign, and medium.

Follows the same pattern as checks.py (Week 1): pure functions that take
a PageData and return a list of CheckResult objects, so main.py can combine
Week 1 + Week 2 (+ future weeks) results into one final report.
"""

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

from crawler import PageData
from checks import CheckResult  


REQUIRED_UTM_PARAMS = {"utm_source", "utm_medium", "utm_campaign"}
OPTIONAL_UTM_PARAMS = {"utm_term", "utm_content"}
ALL_UTM_PARAMS = REQUIRED_UTM_PARAMS | OPTIONAL_UTM_PARAMS


@dataclass
class LinkAnalysis:
    """Per-link breakdown, useful for detailed reporting/debugging."""
    href: str
    has_any_utm: bool
    present_params: set
    missing_required: set
    query_params: dict


def run_utm_checks(page: PageData) -> list[CheckResult]:
    """Run all Week 2 tracking/UTM checks and return the results."""
    if page.error:
        return [CheckResult(
            name="Tracking link analysis",
            passed=False,
            severity="critical",
            message=f"Could not analyze links: {page.error}",
        )]


    external_links = [l for l in page.links if not l["is_internal"]]
    analyses = [_analyze_link(l["href"]) for l in external_links]

    results = []
    results.append(_check_utm_coverage(analyses))
    results.append(_check_required_params_complete(analyses))
    results.append(_check_naming_consistency(analyses))
    results.append(_check_duplicate_tracking_links(external_links))
    results.append(_check_malformed_query_strings(external_links))
    return results


def _analyze_link(href: str) -> LinkAnalysis:
    """Parse a single URL's query string and classify its UTM coverage."""
    parsed = urlparse(href)
    query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

    present_utm = {k for k in query_params if k.lower() in ALL_UTM_PARAMS}
    missing_required = REQUIRED_UTM_PARAMS - {k.lower() for k in present_utm}

    return LinkAnalysis(
        href=href,
        has_any_utm=len(present_utm) > 0,
        present_params=present_utm,
        missing_required=missing_required,
        query_params=query_params,
    )


def _check_utm_coverage(analyses: list[LinkAnalysis]) -> CheckResult:
    """What fraction of external links have any UTM tagging at all?"""
    if not analyses:
        return CheckResult(
            "UTM coverage", True, "info",
            "No external links found on this page to check."
        )

    tagged = [a for a in analyses if a.has_any_utm]
    coverage_pct = round(100 * len(tagged) / len(analyses))

    if coverage_pct == 0:
        return CheckResult(
            "UTM coverage", False, "critical",
            f"None of the {len(analyses)} external link(s) have UTM tracking parameters. "
            "Traffic from this page cannot be attributed to a source/campaign."
        )
    elif coverage_pct < 100:
        untagged = len(analyses) - len(tagged)
        return CheckResult(
            "UTM coverage", False, "warning",
            f"{coverage_pct}% of external links are UTM-tagged "
            f"({untagged} of {len(analyses)} link(s) have no tracking parameters)."
        )
    return CheckResult(
        "UTM coverage", True, "info",
        f"All {len(analyses)} external link(s) carry UTM tracking parameters."
    )


def _check_required_params_complete(analyses: list[LinkAnalysis]) -> CheckResult:
    """
    For links that DO have some UTM tagging, are utm_source/medium/campaign
    all present? Partial tagging (e.g. only utm_source) is a common mistake
    that breaks attribution in analytics tools.
    """
    tagged = [a for a in analyses if a.has_any_utm]
    if not tagged:
        return CheckResult(
            "Required UTM parameters", True, "info",
            "No UTM-tagged links to check yet (see UTM coverage check)."
        )

    incomplete = [a for a in tagged if a.missing_required]
    if not incomplete:
        return CheckResult(
            "Required UTM parameters", True, "info",
            f"All {len(tagged)} tagged link(s) include utm_source, utm_medium, "
            "and utm_campaign."
        )

    details = [
        f"{a.href[:70]}{'...' if len(a.href) > 70 else ''} ,missing: {', '.join(sorted(a.missing_required))}"
        for a in incomplete
    ]
    return CheckResult(
        "Required UTM parameters", False, "warning",
        f"{len(incomplete)} of {len(tagged)} tagged link(s) are missing required "
        "UTM parameters (utm_source, utm_medium, or utm_campaign), incomplete "
        "tagging breaks attribution in analytics tools.",
        details=details,
    )


def _check_naming_consistency(analyses: list[LinkAnalysis]) -> CheckResult:
    """
    Flags inconsistent casing/format in utm_source and utm_medium values,
    e.g. 'Facebook' vs 'facebook' vs 'FB',these fragment reporting in
    analytics tools even though they mean the same thing.
    """
    tagged = [a for a in analyses if a.has_any_utm]
    if len(tagged) < 2:
        return CheckResult(
            "UTM naming consistency", True, "info",
            "Not enough tagged links to check naming consistency (need 2+)."
        )

    issues = []
    for param in ("utm_source", "utm_medium"):
        raw_values = [a.query_params.get(param) for a in tagged if a.query_params.get(param)]
        values = [v[0] if isinstance(v, list) else v for v in raw_values]
        if not values:
            continue
        lower_map = Counter(v.lower() for v in values)
        distinct_raw = set(values)
        for lower_val, count in lower_map.items():
            variants = {v for v in distinct_raw if v.lower() == lower_val}
            if len(variants) > 1:
                issues.append(f"{param}: found variants {sorted(variants)} — pick one casing/format")

    if not issues:
        return CheckResult(
            "UTM naming consistency", True, "info",
            "No casing/naming inconsistencies detected in utm_source or utm_medium."
        )
    return CheckResult(
        "UTM naming consistency", False, "warning",
        f"{len(issues)} naming inconsistency pattern(s) found, these fragment "
        "reporting in analytics tools even though they refer to the same source.",
        details=issues,
    )


def _check_duplicate_tracking_links(external_links: list[dict]) -> CheckResult:
    """
    Flags links pointing to the same destination + same UTM params more
    than once on the page, usually a copy-paste mistake, and can inflate
    or confuse click counts depending on how the tracking pixel fires.
    """
    href_counts = Counter(l["href"] for l in external_links)
    duplicates = {href: count for href, count in href_counts.items() if count > 1}

    if not duplicates:
        return CheckResult(
            "Duplicate tracking links", True, "info",
            "No duplicate external tracking links found."
        )
    details = [f"{href[:70]}{'...' if len(href) > 70 else ''} — appears {count} times"
               for href, count in duplicates.items()]
    return CheckResult(
        "Duplicate tracking links", False, "warning",
        f"{len(duplicates)} external link(s) appear more than once on the page "
        "with identical URLs/parameters, check whether this is intentional.",
        details=details,
    )


def _check_malformed_query_strings(external_links: list[dict]) -> CheckResult:
    """
    Flags obviously malformed tracking setups: empty parameter values
    (e.g. utm_source=), duplicated parameter keys (e.g. utm_source appears
    twice in the same URL), or stray '?' with no parameters at all.
    """
    malformed = []
    for link in external_links:
        href = link["href"]
        parsed = urlparse(href)
        if not parsed.query:
            continue

        raw_pairs = parsed.query.split("&")
        keys_seen = Counter()
        has_empty_value = False

        for pair in raw_pairs:
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            keys_seen[key] += 1
            if value.strip() == "":
                has_empty_value = True

        duplicate_keys = [k for k, c in keys_seen.items() if c > 1]

        if has_empty_value:
            malformed.append(f"{href[:70]}{'...' if len(href) > 70 else ''}, has empty parameter value(s)")
        if duplicate_keys:
            malformed.append(
                f"{href[:70]}{'...' if len(href) > 70 else ''}, duplicate parameter key(s): {', '.join(duplicate_keys)}"
            )

    if not malformed:
        return CheckResult(
            "Malformed tracking parameters", True, "info",
            "No malformed query strings detected in external links."
        )
    return CheckResult(
        "Malformed tracking parameters", False, "warning",
        f"{len(malformed)} issue(s) found in tracking link query strings.",
        details=malformed,
    )
