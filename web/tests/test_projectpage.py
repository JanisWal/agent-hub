"""The project page as Janis sketched it (07.11.2026): name in the top bar, trash and archive next to
the gear, a board of lines with green and red buttons, angular stations on the left."""
import dataclasses
import os
import tempfile
import unittest

from app import board, db, projectpage, projects, ui, users


class ProjectPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "My <b>project</b>")
        uid, pid = self.user.id, self.project.id
        self.bug = board.create_item(uid, pid, "bug", "A bug")
        self.agent_bug = board.create_suggestion(uid, pid, "bug", "Found by Claude")
        self.idea = board.create_suggestion(uid, pid, "minor", "An idea")
        self.done = board.create_item(uid, pid, "major", "Finished thing")
        board.archive(uid, self.done.id)
        self.thrown = board.create_item(uid, pid, "bug", "Thrown away")
        board.discard(uid, self.thrown.id)

    def tearDown(self):
        self.tmp.cleanup()

    def html(self, lang="de"):
        user = dataclasses.replace(self.user, language=lang)
        body = projectpage.render(user, self.project, board.list_items(user.id, self.project.id))
        return ui.logged_in_page(user, self.project.name, body, scripts=projectpage.SCRIPTS,
                                 styles=projectpage.STYLES, top_center=projectpage.title_html(self.project),
                                 drawer_extras=projectpage.drawer_buttons(lang), body_class="project-page")

    def test_project_name_is_in_the_top_bar_and_escaped(self):
        page = self.html()
        bar = page[page.index('<header class="topbar">'):page.index("</header>")]
        self.assertIn('class="project-title"', bar)
        self.assertIn("My &lt;b&gt;project&lt;/b&gt;", bar)
        self.assertNotIn("<b>project</b>", page)
        self.assertEqual(page.count("<h1"), 1)                                # the name is the one headline

    def test_trash_and_archive_sit_in_the_drawer_left_of_the_gear(self):
        page = self.html()
        drawer = page[page.index('id="settings"'):]
        order = [drawer.index(x) for x in ('id="archive-toggle"', 'id="trash-toggle"', 'id="settings-toggle"')]
        self.assertEqual(order, sorted(order))                                # archive, trash, then the gear
        self.assertEqual(page.count('class="drawer-extra"'), 2)
        for view in ("trash", "archive"):
            self.assertIn(f'data-view="{view}"', page)
        self.assertNotIn('class="count"><', page[page.index("drawer-extra"):page.index("settings-toggle")])  # no number
        self.assertNotIn("board-head", page)

    def test_both_buttons_are_identical_apart_from_view_and_icon(self):
        extras = projectpage.drawer_buttons("de")
        archive, trash = extras.split("</button>")[:2]
        norm = lambda s, v: s.replace(v, "X")
        self.assertEqual(norm(archive, "archive").count("drawer-extra"), norm(trash, "trash").count("drawer-extra"))
        self.assertEqual(archive.count('aria-pressed="false"'), trash.count('aria-pressed="false"'))
        self.assertIn('aria-label="Archiv"', archive)
        self.assertIn('aria-label="Papierkorb"', trash)

    def test_board_shows_open_and_suggested_items_only(self):
        page = self.html()
        board_html = page[page.index('id="board"'):page.index('id="chat"')]
        for title in ("A bug", "Found by Claude", "An idea"):
            self.assertIn(title, board_html)
        for title in ("Finished thing", "Thrown away"):
            self.assertNotIn(title, board_html)
        vault = page[page.index('id="vault"'):page.index('id="board"')]
        self.assertIn("Finished thing", vault[vault.index('data-view="archive"'):])
        self.assertIn("Thrown away", vault[vault.index('data-view="trash"'):vault.index('data-view="archive"')])

    def test_only_small_and_major_suggestions_have_green_and_red_buttons(self):
        page = self.html()
        self.assertEqual(page.count("card-btn go"), 1)
        self.assertEqual(page.count("card-btn stop"), 1)
        idea = page[page.index("An idea") - 200:page.index("An idea") + 700]
        self.assertIn("proposed", idea)
        self.assertLess(idea.index("card-btn stop"), idea.index("card-btn go"))   # reject left, take over right
        agent_bug = page[page.index("Found by Claude") - 160:page.index("Found by Claude") + 40]
        self.assertIn("from-claude", agent_bug)
        self.assertNotIn("proposed", agent_bug)

    def test_stations_follow_the_cycle(self):
        page = self.html()
        nav = page[page.index('<nav class="stations"'):page.index("</nav>")]
        names = ["Board", "Manager", "Programmierer", "Tester", "Prüfer", "Für dich"]
        positions = [nav.index(f">{name}<") for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(nav.count('class="station off"'), 5)                  # only the board exists so far
        self.assertEqual(nav.count('class="station active"'), 1)
        self.assertIn("Alle Projekte", nav)

    def test_english(self):
        page = self.html("en")
        for text in ("Archive", "Trash", "Programmer", "Reviewer", "For you", "All projects"):
            self.assertIn(text, page)
        self.assertNotIn("%t.", page)

    def test_layout_places_the_title_at_the_golden_section(self):
        css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "app.css"), encoding="utf-8").read()
        self.assertIn("left: 38.2%", css)
        self.assertIn(".drawer-extra", css)
        for token in ("--go:", "--on-go:", "--success:"):
            self.assertEqual(css.count(token), 3 if token != "--success:" else 3, token)   # light, dark, dark by system


if __name__ == "__main__":
    unittest.main()
