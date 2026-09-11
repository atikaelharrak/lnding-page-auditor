"""
test_crawler.py
----------------
Tests for crawler.py's extraction logic: given raw HTML, does it
correctly pull out images, links, forms, and meta tags into PageData?

These tests do NOT make real network requests, they build PageData
objects directly from HTML strings (see conftest.py's make_page helper).
Network behavior (timeouts, SSL errors, etc.) is tested separately in
test_crawler_network.py.
"""

from conftest import make_page


class TestImageExtraction:
    def test_extracts_image_with_src_and_alt(self):
        html = '<img src="/logo.png" alt="Company logo">'
        page = make_page(html)
        assert len(page.images) == 1
        assert page.images[0]["alt"] == "Company logo"
        assert page.images[0]["has_alt"] is True

    def test_flags_image_missing_alt_attribute(self):
        html = '<img src="/banner.jpg">'
        page = make_page(html)
        assert page.images[0]["has_alt"] is False

    def test_flags_image_with_empty_alt_as_missing(self):
        """An alt="" is present in the DOM but empty, should still count as missing."""
        html = '<img src="/banner.jpg" alt="">'
        page = make_page(html)
        assert page.images[0]["has_alt"] is False

    def test_flags_image_with_empty_src(self):
        html = '<img src="" alt="broken">'
        page = make_page(html)
        assert page.images[0]["src"] == ""

    def test_relative_image_src_resolved_to_absolute(self):
        html = '<img src="/images/hero.png" alt="hero">'
        page = make_page(html, url="https://example.com/landing")
        assert page.images[0]["src"] == "https://example.com/images/hero.png"

    def test_no_images_returns_empty_list(self):
        page = make_page("<p>No images here.</p>")
        assert page.images == []


class TestLinkExtraction:
    def test_internal_link_flagged_correctly(self):
        html = '<a href="/about">About us</a>'
        page = make_page(html, url="https://example.com/")
        assert len(page.links) == 1
        assert page.links[0]["is_internal"] is True

    def test_external_link_flagged_correctly(self):
        html = '<a href="https://partner-network.com/offer">Offer</a>'
        page = make_page(html, url="https://example.com/")
        assert page.links[0]["is_internal"] is False

    def test_anchor_only_links_are_skipped(self):
        html = '<a href="#section2">Jump</a>'
        page = make_page(html)
        assert page.links == []

    def test_mailto_and_tel_links_are_skipped(self):
        html = '''
        <a href="mailto:hello@example.com">Email us</a>
        <a href="tel:+1234567890">Call us</a>
        '''
        page = make_page(html)
        assert page.links == []

    def test_javascript_links_are_skipped(self):
        html = '<a href="javascript:void(0)">Click</a>'
        page = make_page(html)
        assert page.links == []

    def test_link_text_captured(self):
        html = '<a href="https://x.com">Visit our site</a>'
        page = make_page(html)
        assert page.links[0]["text"] == "Visit our site"


class TestFormExtraction:
    def test_extracts_form_action_and_method(self):
        html = '<form action="/submit" method="post"><input name="email"></form>'
        page = make_page(html, url="https://example.com/")
        assert len(page.forms) == 1
        assert page.forms[0]["action"] == "https://example.com/submit"
        assert page.forms[0]["method"] == "post"

    def test_form_method_defaults_to_get(self):
        html = '<form action="/submit"><input name="q"></form>'
        page = make_page(html)
        assert page.forms[0]["method"] == "get"

    def test_extracts_form_fields(self):
        html = '''
        <form action="/submit">
            <input type="email" name="email" required>
            <input type="text" name="name">
            <textarea name="message"></textarea>
        </form>
        '''
        page = make_page(html)
        fields = page.forms[0]["fields"]
        assert len(fields) == 3
        email_field = next(f for f in fields if f["name"] == "email")
        assert email_field["required"] is True
        assert email_field["type"] == "email"

    def test_no_forms_returns_empty_list(self):
        page = make_page("<p>No forms here.</p>")
        assert page.forms == []


class TestMetaTagExtraction:
    def test_extracts_named_meta_tags(self):
        html = '<meta name="description" content="A great landing page">'
        page = make_page(html)
        assert page.meta_tags["description"] == "A great landing page"

    def test_robots_meta_detected_when_present(self):
        html = '<meta name="robots" content="noindex,nofollow">'
        page = make_page(html)
        assert page.meta_tags["_robots_meta_present"] is True
        assert page.meta_tags["robots"] == "noindex,nofollow"

    def test_robots_meta_flagged_absent_when_missing(self):
        page = make_page("<p>No meta tags.</p>")
        assert page.meta_tags["_robots_meta_present"] is False

    def test_meta_tag_keys_are_lowercased(self):
        html = '<meta name="Description" content="Test">'
        page = make_page(html)
        assert "description" in page.meta_tags
