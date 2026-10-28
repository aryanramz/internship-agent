import unittest
from internship_agent.sources import _validate_feed_url, _NoRedirect


class NetworkGuardTests(unittest.TestCase):
    def test_rejects_internal_addresses(self):
        for url in [
            "http://example.org/x", "https://127.0.0.1/api",
            "https://[::1]/", "https://localhost/jobs",
            "https://wiki.internal/jobs", "https://user:pass@example.org/jobs",
            "https://example.org:8443/jobs",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_feed_url(url)

    def test_allows_public_https(self):
        _validate_feed_url("https://boards.greenhouse.io/example/jobs/42")

    def test_redirects_never_follow(self):
        handler = _NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://127.0.0.1/"))
