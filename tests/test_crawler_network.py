"""
test_crawler_network.py
------------------------
Tests for crawler.py's network-facing behavior: does fetch_page() handle
real HTTP responses, timeouts, and errors correctly?

These tests DO make real network requests (or mock them), unlike
test_crawler.py which tests pure HTML-parsing logic offline.

Marked with @pytest.mark.network so they can be skipped in offline
environments:
    pytest -m "not network"
"""

import pytest
from unittest.mock import patch, MagicMock
import requests

from crawler import fetch_page


pytestmark = pytest.mark.network


class TestUrlNormalization:
    def test_adds_https_scheme_if_missing(self):
        """
        We can't guarantee network access in every test environment, so
        this test only checks the URL normalization happens BEFORE the
        request is sent, it mocks requests.get to avoid a real call.
        """
        with patch("crawler.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.url = "https://example.com"
            mock_response.status_code = 200
            mock_response.ok = True
            mock_response.text = "<html></html>"
            mock_response.headers = {}
            mock_response.history = []
            mock_get.return_value = mock_response

            page = fetch_page("example.com")

            assert page.url == "https://example.com"
            called_url = mock_get.call_args[0][0]
            assert called_url == "https://example.com"

    def test_leaves_existing_scheme_untouched(self):
        with patch("crawler.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.url = "http://example.com"
            mock_response.status_code = 200
            mock_response.ok = True
            mock_response.text = "<html></html>"
            mock_response.headers = {}
            mock_response.history = []
            mock_get.return_value = mock_response

            page = fetch_page("http://example.com")
            assert page.url == "http://example.com"


class TestErrorHandling:
    def test_timeout_is_captured_as_error_not_exception(self):
        with patch("crawler.requests.get", side_effect=requests.exceptions.Timeout()):
            page = fetch_page("https://example.com", timeout=5)
            assert page.error is not None
            assert "timed out" in page.error.lower()

    def test_connection_error_is_captured_as_error_not_exception(self):
        with patch("crawler.requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            page = fetch_page("https://example.com")
            assert page.error is not None
            assert "connection error" in page.error.lower()

    def test_ssl_error_is_captured_as_error_not_exception(self):
        with patch("crawler.requests.get", side_effect=requests.exceptions.SSLError("bad cert")):
            page = fetch_page("https://example.com")
            assert page.error is not None
            assert "ssl" in page.error.lower()

    def test_non_2xx_status_sets_error(self):
        with patch("crawler.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.url = "https://example.com/missing"
            mock_response.status_code = 404
            mock_response.ok = False
            mock_response.text = "Not Found"
            mock_response.headers = {}
            mock_response.history = []
            mock_get.return_value = mock_response

            page = fetch_page("https://example.com/missing")
            assert page.error is not None
            assert "404" in page.error
            assert page.soup is None

    def test_successful_response_has_no_error(self):
        with patch("crawler.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.url = "https://example.com"
            mock_response.status_code = 200
            mock_response.ok = True
            mock_response.text = "<html><body>Hi</body></html>"
            mock_response.headers = {"Content-Type": "text/html"}
            mock_response.history = []
            mock_get.return_value = mock_response

            page = fetch_page("https://example.com")
            assert page.error is None
            assert page.soup is not None


@pytest.mark.integration
class TestRealNetworkCall:
    """
    A small number of tests that hit the real network, to catch
    integration issues mocks can't (e.g. actual redirect behavior).
    Run separately: pytest -m integration
    Skip in restricted/offline environments: pytest -m "not integration"
    """

    def test_fetch_real_reachable_page(self):
        page = fetch_page("https://raw.githubusercontent.com")
        assert page.status_code == 200
        assert page.error is None
        assert page.soup is not None

    def test_fetch_nonexistent_domain_fails_gracefully(self):
        page = fetch_page("https://this-domain-should-not-exist-abc123xyz.com")
        assert page.error is not None
