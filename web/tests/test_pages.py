import os
import re
import tempfile
import unittest

from app import board, dashboard, layout, projectpage, projects, users


class PagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        users.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("me@example.com", "correct horse")

    def tearDown(self):
        self.tmp.cleanup()

    def all_pages(self, lang):
        users.set_profile(self.user.id, "Jan <b>", lang)
        user = users.check_login("me@example.com", "correct horse")
        project = projects.create_project(user.id, '<script>alert("x")</script> %BODY%')
        board.create_item(user.id, project.id, "bug", "<img src=x onerror=1>")
        board.create_suggestion(project.id, "minor", "Idea")
        dropped = board.create_item(user.id, project.id, "major", "Dropped")
        board.discard(user.id, dropped.id)
        items = board.list_items(user.id, project.id)
        shown = projects.list_projects(user.id)
        return [
            layout.page("Home", dashboard.render(user, shown, 1, 1, False), lang,
                        dashboard.settings_bar(user)),
            layout.page("Project", projectpage.render(user, project, items), lang,
                        dashboard.settings_bar(user)),
        ]

    def test_no_placeholder_is_left_over_and_user_text_is_escaped(self):
        for lang in ("de", "en"):
            for page in self.all_pages(lang):
                self.assertIsNone(re.search(r"%[A-Z_]+%", page.replace("%BODY%</", "")),
                                  "unfilled placeholder in " + lang)
                self.assertNotIn("<script>alert", page)
                self.assertNotIn("<img src=x", page)
                self.assertNotIn("Jan <b>", page)

    def test_settings_show_connection_state(self):
        user = users.check_login("me@example.com", "correct horse")
        self.assertIn("Nicht verknüpft", dashboard.settings_bar(user))
        users.set_profile(user.id, "", "en")
        user = users.check_login("me@example.com", "correct horse")
        self.assertIn("Not connected", dashboard.settings_bar(user))

    def test_brand_links_to_the_repository(self):
        page = layout.page("Home", "", "de")
        self.assertIn('href="https://github.com/JanisWal/agent-hub"', page)
        self.assertIn('rel="noopener noreferrer"', page)


if __name__ == "__main__":
    unittest.main()
