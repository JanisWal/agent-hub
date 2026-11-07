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
        self.assertEqual(len(links), 4)  # app.css, dashboard.css, core.js, dashboard.js
        for link in links:
            self.assertRegex(link, r"\?v=[0-9a-f]{10}$")


if __name__ == "__main__":
    unittest.main()
