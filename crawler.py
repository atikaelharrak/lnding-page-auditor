"""
crawler.py
----------
Core crawler for the Landing Page Health Auditor.

Responsibilities (Week 1 scope):
- Fetch a given URL safely (timeouts, error handling, redirects)
- Parse the HTML with BeautifulSoup
- Extract raw building blocks other checkers will need:
  images, links, forms, meta tags, response headers, timing

This module does NOT decide what's "good" or "bad" — it just gathers
facts. Scoring/judgement logic lives in checks.py, kept separate on
purpose so each part is easy to test and extend in later weeks.
"""

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 10  # seconds
USER_AGENT = "CubeHead-LandingPageAuditor/0.1 (+internal QA tool)"


@dataclass
class PageData:
    """Container for everything the crawler extracted from one page."""
    url: str
    final_url: str = ""
    status_code: int | None = None
    load_time_ms: float | None = None
    html: str = ""
    soup: BeautifulSoup | None = None
    headers: dict = field(default_factory=dict)
    redirect_chain: list = field(default_factory=list)
    error: str | None = None

    # Extracted building blocks (filled in after a successful fetch)
    images: list = field(default_factory=list)
    links: list = field(default_factory=list)
    forms: list = field(default_factory=list)
    meta_tags: dict = field(default_factory=dict)


def fetch_page(url: str, timeout: int = DEFAULT_TIMEOUT) -> PageData:
    """
    Fetch a URL and return a PageData object with raw HTML + metadata.
    Never raises on network/HTTP errors — errors are captured in
    PageData.error so the rest of the pipeline can report them gracefully
    instead of crashing mid-audit.
    """
    data = PageData(url=url)

    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        data.url = url

    headers = {"User-Agent": USER_AGENT}

    try:
        start = time.perf_counter()
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        data.final_url = response.url
        data.status_code = response.status_code
        data.load_time_ms = round(elapsed_ms, 1)
        data.headers = dict(response.headers)
        data.redirect_chain = [r.url for r in response.history]
        data.html = response.text

        if response.ok:
            data.soup = BeautifulSoup(response.text, "html.parser")
            _extract_building_blocks(data)
        else:
            data.error = f"HTTP {response.status_code} returned by server"

    except requests.exceptions.Timeout:
        data.error = f"Request timed out after {timeout}s"
    except requests.exceptions.SSLError as e:
        data.error = f"SSL error: {e}"
    except requests.exceptions.ConnectionError as e:
        data.error = f"Connection error: {e}"
    except requests.exceptions.RequestException as e:
        data.error = f"Request failed: {e}"

    return data


def _extract_building_blocks(data: PageData) -> None:
    """Populate images, links, forms, and meta_tags from the parsed soup."""
    soup = data.soup
    base_url = data.final_url or data.url

    # --- Images ---
    for img in soup.find_all("img"):
        src = img.get("src", "")
        data.images.append({
            "src": urljoin(base_url, src) if src else "",
            "alt": img.get("alt"),
            "has_alt": img.has_attr("alt") and img.get("alt", "").strip() != "",
        })

    # --- Links (a[href]) ---
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        is_internal = urlparse(absolute).netloc == urlparse(base_url).netloc
        data.links.append({
            "href": absolute,
            "raw_href": href,
            "text": a.get_text(strip=True),
            "is_internal": is_internal,
        })

    # --- Forms ---
    for form in soup.find_all("form"):
        fields = []
        for field_tag in form.find_all(["input", "textarea", "select"]):
            fields.append({
                "tag": field_tag.name,
                "type": field_tag.get("type", "text"),
                "name": field_tag.get("name"),
                "required": field_tag.has_attr("required"),
            })
        data.forms.append({
            "action": urljoin(base_url, form.get("action", "")),
            "method": (form.get("method") or "get").lower(),
            "fields": fields,
            "raw_html": str(form),
        })

    # --- Meta tags ---
    for meta in soup.find_all("meta"):
        key = meta.get("name") or meta.get("property")
        if key:
            data.meta_tags[key.lower()] = meta.get("content", "")

    # robots meta is common enough to deserve a direct field
    robots_tag = soup.find("meta", attrs={"name": "robots"})
    data.meta_tags["_robots_meta_present"] = robots_tag is not None
    if robots_tag:
        data.meta_tags["robots"] = robots_tag.get("content", "")
