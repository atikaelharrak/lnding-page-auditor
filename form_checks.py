"""
form_checks.py
--------------
Week 3 scope: Lead Form Quality Checks.

Analyzes the forms already extracted by crawler.py (PageData.forms) and
checks for basic quality/anti-fraud signals relevant to affiliate lead
generation — this is where "traffic quality" ultimately gets tested,
since a broken or fraud-prone form is where bad leads get captured.

Follows the same pattern as checks.py (Week 1) and utm_checks.py (Week 2):
pure functions that take a PageData and return a list of CheckResult
objects, so main.py can combine all categories into one report.
"""

import re
from dataclasses import dataclass

from crawler import PageData
from checks import CheckResult  # reuse the same result shape as other weeks

# Common CAPTCHA/anti-bot service signatures to look for in a form's raw HTML.
# Checking the raw HTML (not just parsed fields) because CAPTCHA widgets are
# usually injected via <script>/<div> tags, not <input> fields.
CAPTCHA_SIGNATURES = [
    "recaptcha",
    "g-recaptcha",
    "hcaptcha",
    "h-captcha",
    "turnstile",       # Cloudflare Turnstile
    "cf-turnstile",
    "captcha",         # generic catch-all, checked last / lowest confidence
]

# Field names/types commonly used as honeypots (hidden fields meant to
# trap bots, since real users never fill them in).
HONEYPOT_NAME_HINTS = ["honeypot", "hp_", "bot_field", "trap", "winnie", "do_not_fill"]

# A minimal set of field types/names that suggest this is a genuine lead
# capture form (as opposed to e.g. a newsletter-only email field or a
# site search box) — used to decide whether deeper checks are worth running.
LEAD_FORM_FIELD_HINTS = ["email", "phone", "tel", "name", "first_name", "last_name"]


@dataclass
class FormAnalysis:
    index: int
    action: str
    method: str
    field_count: int
    has_captcha_signal: bool
    captcha_confidence: str  # "high" | "low" | "none"
    honeypot_fields: list
    required_fields: list
    looks_like_lead_form: bool


def run_form_checks(page: PageData) -> list[CheckResult]:
    """Run all Week 3 lead-form quality checks and return the results."""
    if page.error:
        return [CheckResult(
            name="Lead form analysis",
            passed=False,
            severity="critical",
            message=f"Could not analyze forms: {page.error}",
        )]

    analyses = [_analyze_form(i, f) for i, f in enumerate(page.forms)]
    lead_forms = [a for a in analyses if a.looks_like_lead_form]

    results = []
    results.append(_check_forms_present(page, analyses))
    if lead_forms:
        results.append(_check_captcha_presence(lead_forms))
        results.append(_check_honeypot_presence(lead_forms))
        results.append(_check_required_field_validation(lead_forms))
        results.append(_check_form_action_configured(lead_forms, page))
        results.append(_check_https_form_submission(lead_forms))
    return results


def _analyze_form(index: int, form: dict) -> FormAnalysis:
    raw_html_lower = form.get("raw_html", "").lower()

    captcha_hits = [sig for sig in CAPTCHA_SIGNATURES if sig in raw_html_lower]
    has_captcha_signal = len(captcha_hits) > 0
    # "high" confidence if a specific named provider matched, "low" if only
    # the generic word "captcha" appeared without a recognizable provider.
    specific_hits = [h for h in captcha_hits if h != "captcha"]
    if specific_hits:
        captcha_confidence = "high"
    elif has_captcha_signal:
        captcha_confidence = "low"
    else:
        captcha_confidence = "none"

    fields = form.get("fields", [])
    field_names_lower = [(f.get("name") or "").lower() for f in fields]

    honeypot_fields = [
        f for f, name_lower in zip(fields, field_names_lower)
        if any(hint in name_lower for hint in HONEYPOT_NAME_HINTS)
    ]

    required_fields = [f for f in fields if f.get("required")]

    looks_like_lead_form = any(
        any(hint in name_lower for hint in LEAD_FORM_FIELD_HINTS)
        for name_lower in field_names_lower
    ) or any(f.get("type") == "email" for f in fields)

    return FormAnalysis(
        index=index,
        action=form.get("action", ""),
        method=form.get("method", "get"),
        field_count=len(fields),
        has_captcha_signal=has_captcha_signal,
        captcha_confidence=captcha_confidence,
        honeypot_fields=honeypot_fields,
        required_fields=required_fields,
        looks_like_lead_form=looks_like_lead_form,
    )


def _check_forms_present(page: PageData, analyses: list[FormAnalysis]) -> CheckResult:
    if not page.forms:
        return CheckResult(
            "Lead form presence", True, "info",
            "No forms found on this page. If this page is meant to capture "
            "leads, that's worth double-checking — otherwise no action needed."
        )
    lead_forms = [a for a in analyses if a.looks_like_lead_form]
    if not lead_forms:
        return CheckResult(
            "Lead form presence", True, "info",
            f"Found {len(page.forms)} form(s), but none look like lead-capture "
            "forms (no email/phone/name fields detected) — likely search or "
            "newsletter forms. Skipping deeper lead-form checks."
        )
    return CheckResult(
        "Lead form presence", True, "info",
        f"Found {len(lead_forms)} likely lead-capture form(s) out of "
        f"{len(page.forms)} total form(s) on the page."
    )


def _check_captcha_presence(lead_forms: list[FormAnalysis]) -> CheckResult:
    missing = [f for f in lead_forms if not f.has_captcha_signal]
    low_confidence = [f for f in lead_forms if f.captcha_confidence == "low"]

    if not missing and not low_confidence:
        return CheckResult(
            "CAPTCHA / anti-bot protection", True, "info",
            f"All {len(lead_forms)} lead form(s) show signs of a recognized "
            "CAPTCHA/anti-bot service (reCAPTCHA, hCaptcha, or Turnstile)."
        )
    if missing:
        return CheckResult(
            "CAPTCHA / anti-bot protection", False, "critical",
            f"{len(missing)} of {len(lead_forms)} lead form(s) have no detectable "
            "CAPTCHA or anti-bot protection — these forms are exposed to bot "
            "submissions, which directly hurts lead quality."
        )
    return CheckResult(
        "CAPTCHA / anti-bot protection", False, "warning",
        f"{len(low_confidence)} lead form(s) mention 'captcha' generically but "
        "no specific recognized provider (reCAPTCHA/hCaptcha/Turnstile) was "
        "detected — worth confirming it's actually functional, not just a label."
    )


def _check_honeypot_presence(lead_forms: list[FormAnalysis]) -> CheckResult:
    without_honeypot = [f for f in lead_forms if not f.honeypot_fields]
    if not without_honeypot:
        return CheckResult(
            "Honeypot fields", True, "info",
            f"All {len(lead_forms)} lead form(s) include a honeypot-style field "
            "(an extra layer of bot protection alongside CAPTCHA)."
        )
    return CheckResult(
        "Honeypot fields", False, "warning",
        f"{len(without_honeypot)} of {len(lead_forms)} lead form(s) have no "
        "honeypot field detected. Not required if CAPTCHA is already present, "
        "but honeypots are a cheap, invisible extra layer of bot filtering."
    )


def _check_required_field_validation(lead_forms: list[FormAnalysis]) -> CheckResult:
    without_required = [f for f in lead_forms if not f.required_fields]
    if not without_required:
        return CheckResult(
            "Required field validation", True, "info",
            f"All {len(lead_forms)} lead form(s) mark at least one field as "
            "required, enabling basic client-side validation."
        )
    return CheckResult(
        "Required field validation", False, "warning",
        f"{len(without_required)} of {len(lead_forms)} lead form(s) have no "
        "'required' attribute on any field — this allows empty submissions, "
        "which can inflate junk lead volume."
    )


def _check_form_action_configured(lead_forms: list[FormAnalysis], page: PageData) -> CheckResult:
    broken = []
    for f in lead_forms:
        action = f.action.strip()
        page_url = (page.final_url or page.url).rstrip("/")
        # A form with no action, or an action identical to the page's own
        # URL with no path change, may indicate a misconfigured/placeholder
        # form (common cause: template forms left unwired to a real endpoint).
        if not action or action.rstrip("/") == page_url:
            broken.append(f)

    if not broken:
        return CheckResult(
            "Form submission endpoint", True, "info",
            f"All {len(lead_forms)} lead form(s) have a distinct submission "
            "action configured."
        )
    return CheckResult(
        "Form submission endpoint", False, "critical",
        f"{len(broken)} of {len(lead_forms)} lead form(s) have a missing or "
        "suspicious 'action' attribute (empty, or pointing back at the same "
        "page) — this form may not actually submit anywhere.",
    )


def _check_https_form_submission(lead_forms: list[FormAnalysis]) -> CheckResult:
    insecure = [f for f in lead_forms if f.action.strip().lower().startswith("http://")]
    if not insecure:
        return CheckResult(
            "Secure form submission", True, "info",
            "No lead form submits to an insecure (http://) endpoint."
        )
    return CheckResult(
        "Secure form submission", False, "critical",
        f"{len(insecure)} lead form(s) submit to an insecure http:// endpoint "
        "— lead data (name, email, phone) would be sent unencrypted.",
    )
