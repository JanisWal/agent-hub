import re
import unittest

from app import layout


class StaticUrlTest(unittest.TestCase):
    def test_url_carries_content_hash(self):
        self.assertRegex(layout.static_url("core.js"), r"^/static/core\.js\?v=[0-9a-f]{10}$")

    def test_different_files_get_different_hashes(self):
        self.assertNotEqual(layout.static_url("core.js"), layout.static_url("app.css"))

    def test_page_links_only_versioned_static_files(self):
        html = layout.page("T", "", "de", scripts=("dashboard.js",), styles=("dashboard.css",))
        links = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
        # app.css, dashboard.css, theme.js, core.js, dashboard.js and the three icons (svg, png, iPhone)
        self.assertEqual(len(links), 8)
        for link in links:
            self.assertRegex(link, r"\?v=[0-9a-f]{10}$")

    def test_no_page_has_inline_script(self):
        """The content security policy allows scripts from /static only: an inline script would not run."""
        from app.main import CONTENT_POLICY
        self.assertIn("script-src 'self'", CONTENT_POLICY)
        self.assertNotIn("unsafe-inline'; script", CONTENT_POLICY)
        html = layout.page("T", "<p>x</p>", "de", scripts=("dashboard.js",))
        for tag in re.findall(r"<script\b[^>]*>", html):
            self.assertIn(' src="/static/', tag)
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", html))                 # no inline event handlers either
        self.assertLess(html.index("theme.js"), html.index("app.css"))        # the theme is set before the first paint

    def test_every_page_has_the_logo(self):
        html = layout.page("T", "", "de")
        self.assertIn('<link rel="icon" href="/static/icon.svg?v=', html)
        self.assertIn('<link rel="apple-touch-icon" href="/static/icon-180.png?v=', html)
        self.assertIn('name="theme-color" content="#EFDCC6"', html)

    def test_favicon_route(self):
        from app.main import favicon
        response = favicon()                       # no test client needed: the route returns the file response
        self.assertEqual(response.media_type, "image/png")
        with open(response.path, "rb") as icon:
            self.assertTrue(icon.read(4) == b"\x89PNG")


if __name__ == "__main__":
    unittest.main()
