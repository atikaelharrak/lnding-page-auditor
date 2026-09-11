"""
conftest.py
-----------
Shared pytest fixtures/helpers for the test suite.

The key idea: checks.py and utm_checks.py both operate on a PageData
object, not on live network responses. So tests build PageData objects
directly from synthetic HTML strings: fast, reliable, and don't depend
on any real website being reachable or staying in a particular state.

Network-dependent tests (does the crawler actually work against a real
URL) are kept separate and marked so they can be skipped in offline/CI
environments, see test_crawler_network.py.
"""

from urllib.parse import urlparse

import pytest
from bs4 import BeautifulSoup

from crawler import PageData, _extract_building_blocks


def make_page(html: str, url: str = "https://example-landingpage.com", status_code: int = 200) -> PageData:
    """
    Build a PageData object from a raw HTML string, without making any
    network request. Reuses crawler.py's own _extract_building_blocks
    so tests exercise the real extraction logic, not a re-implementation
    of it.
    """
    page = PageData(url=url)
    page.final_url = url
    page.status_code = status_code
    page.load_time_ms = 100.0
    page.html = html
    page.soup = BeautifulSoup(html, "html.parser")
    _extract_building_blocks(page)
    return page


@pytest.fixture
def make_page_fixture():
    """Expose make_page as a fixture too, for tests that prefer fixture injection."""
    return make_page
