import os
import re
import tempfile
import unittest

from app import board, dashboard, db, layout, projectpage, projects, ui, users


class PagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("me@example.com", "correct horse")

    def tearDown(self):
        self.tmp.cleanup()

    def all_pages(self, lang):
        users.set_profile(self.user.id, "Jan <b>", lang)
        user = users.check_login("me@example.com", "correct horse")
        project = projects.create_project(user.id, '<script>alert("x")</script> %BODY%')
        board.create_item(user.id, project.id, "bug", "<img src=x onerror=1>")
        board.create_suggestion(user.id, project.id, "minor", "Idea")
        dropped = board.create_item(user.id, project.id, "major", "Dropped")
        board.discard(user.id, dropped.id)
        items = board.list_items(user.id, project.id)
        shown = projects.layout(user.id)
        return [
            ui.logged_in_page(user, "Home", dashboard.render(user, shown, 1, False)),
            ui.logged_in_page(user, "Project", projectpage.render(user, project, items)),
            ui.login_page(failed=True),
        ]

    def test_no_placeholder_is_left_over_and_user_text_is_escaped(self):
        for lang in ("de", "en"):
            for page in self.all_pages(lang):
                self.assertIsNone(re.search(r"%[A-Z_]+%", page.replace("&lt;/script&gt; %BODY%", "")),
                                  "unfilled placeholder in " + lang)
                self.assertNotIn("<script>alert", page)
                self.assertNotIn("<img src=x", page)
                self.assertNotIn("Jan <b>", page)

    def test_settings_show_connection_state(self):
        user = users.check_login("me@example.com", "correct horse")
        self.assertIn("Nicht verknüpft", ui.settings_bar(user))
        users.set_profile(user.id, "", "en")
        user = users.check_login("me@example.com", "correct horse")
        self.assertIn("Not connected", ui.settings_bar(user))

    def test_pages_before_the_login_follow_the_browsers_language(self):
        from app import i18n
        for header, lang in (("en-US,en;q=0.9,de;q=0.8", "en"), ("de-DE,de;q=0.9,en;q=0.8", "de"), ("fr-FR,en;q=0.5", "en"),
                             ("fr,it", "de"), ("", "de"), (None, "de"), ("EN", "en")):
            self.assertEqual(i18n.from_header(header), lang, header)
        self.assertIn("Welcome back.", ui.login_page(lang="en"))
        self.assertIn('<html lang="en">', ui.login_page(lang="en"))
        self.assertIn("Willkommen zurück.", ui.login_page())

    def test_the_dashboard_has_no_quota_bar(self):
        user = users.check_login("me@example.com", "correct horse")
        self.assertNotIn("quota", dashboard.render(user, [], 1, True))

    def test_brand_links_to_the_repository(self):
        page = layout.page("Home", "", "de")
        self.assertIn('href="https://github.com/JanisWal/agent-hub"', page)
        self.assertIn('rel="noopener noreferrer"', page)


if __name__ == "__main__":
    unittest.main()
