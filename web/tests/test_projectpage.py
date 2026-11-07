"""The project page as Janis sketched it (07.11.2026): name in the top bar, trash and archive next to
the gear, a board of lines with green and red buttons, angular stations on the left."""
import dataclasses
import os
import tempfile
import unittest

from app import board, db, projectpage, projects, ui, users


def css_of(name: str) -> str:
    return open(os.path.join(os.path.dirname(__file__), "..", "app", "static", name), encoding="utf-8").read()


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
                                 styles=projectpage.STYLES, top_center=projectpage.title_html(self.project), top_left=projectpage.back_html(lang),
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
        self.assertNotIn("Alle Projekte", nav)                                # the way back is in the top bar now
        self.assertNotIn("station-back", page)
        self.assertNotIn("clip-path", css_of("project.css"))                 # sharp edges, no arrows

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

    def test_back_link_is_in_the_top_bar_right_of_the_brand(self):
        page = self.html()
        bar = page[page.index('<header class="topbar">'):page.index("</header>")]
        self.assertLess(bar.index('class="brand"'), bar.index('class="topbar-back"'))
        self.assertLess(bar.index('class="topbar-back"'), bar.index('class="project-title"'))
        self.assertIn('href="/"', bar[bar.index("topbar-back"):])
        self.assertIn("Alle Projekte", bar)

    def test_chat_is_a_dock_outside_the_board_with_a_button_for_narrow_screens(self):
        page = self.html()
        self.assertEqual(page.count('id="chat"'), 1)
        self.assertGreater(page.index('id="chat"'), page.index('id="board"'))
        self.assertGreater(page.index('id="chat"'), page.index('class="project"'))
        board_area = page[page.index('class="boardwrap"'):page.index('id="chat"')]
        self.assertNotIn('id="chat"', board_area)
        self.assertIn('id="chat-toggle"', page)
        css = css_of("project.css")
        self.assertIn("position: fixed", css[css.index(".chat {"):css.index(".chat-head")])
        self.assertIn("padding-right", css)                                     # a strip is kept free on wide screens

    def test_scrollbars_are_styled(self):
        css = css_of("app.css")
        for part in ("::-webkit-scrollbar-thumb", "::-webkit-scrollbar-track", "scrollbar-color"):
            self.assertIn(part, css)
        self.assertIn("@supports not selector(::-webkit-scrollbar)", css)       # standard properties only where no parts

    def test_project_title_is_big_with_air(self):
        css = css_of("app.css")
        self.assertIn("clamp(1.8rem, 3.2vw, 2.8rem)", css)
        self.assertIn(".project-page .topbar { min-height: 90px; }", css)
    def test_back_link_is_a_round_icon_button(self):
        page = self.html()
        link = page[page.index('class="topbar-back"'):]
        link = link[:link.index("</a>")]
        self.assertIn('aria-label="Alle Projekte"', link)
        self.assertIn("<svg", link)
        self.assertNotIn("<span", link)                                         # an icon, no text beside the brand

    def test_columns_and_chat_end_on_the_same_line_above_the_theme_button(self):
        project, app = css_of("project.css"), css_of("app.css")
        self.assertIn("main { padding-bottom: 96px; }", app)                    # columns stretch down to here
        chat = project[project.index(".chat {"):project.index(".chat-head")]
        self.assertIn("bottom: 96px", chat)                                     # the chat ends on the same line
        self.assertIn(".project-page main { display: flex; align-items: stretch;", project)
        self.assertIn(".board { flex: 1;", project)
        self.assertNotIn("64vh", project)                                       # no fixed height any more
        self.assertIn(".theme-fab { position: fixed; right: 24px; bottom: 24px; width: 52px; height: 52px;", app)

    def test_responsive_rules(self):
        app, project = css_of("app.css"), css_of("project.css")
        self.assertIn("@media (max-width: 1100px)", project)                    # board and stations stack, like the title
        self.assertNotIn("@media (max-width: 1000px)", project)
        phone = app[app.index("/* Phone: the bar has two rows"):]
        phone = phone[:phone.index("}\n", phone.index(".project-title"))]
        self.assertIn("flex: 0 0 100%", phone)                                  # the name gets a row of its own
        self.assertIn("flex-wrap: wrap", app[app.index("/* Phone: the bar has two rows"):][:400])
        self.assertIn("-webkit-line-clamp: 2", phone)
        self.assertIn("overflow-x: auto", project)                              # stations: swipeable row, never a wider page

    def test_chat_window_is_final_not_a_test(self):
        for lang in ("de", "en"):
            page = self.html(lang)
            chat = page[page.index('id="chat"'):page.index("</aside>")]
            for word in ("Vorübergehend", "Temporary", "testen", "Testfenster", "chat-badge", "TEMPORARY"):
                self.assertNotIn(word, chat)
            self.assertIn('<h2>Claude</h2>', chat)
        self.assertIn("Kurze Einzelfragen an dein Claude.", self.html("de"))
        for lang in ("de", "en"):
            hint = __import__("app.i18n", fromlist=["t"]).t(lang, "chat_hint")
            self.assertLess(len(hint), 60, hint)                                  # one short sentence, no explanations
            self.assertEqual(hint.count("."), 1)
        for name in ("project.css", "chat.js"):
            self.assertNotIn("TEMPORARY", css_of(name))

    def test_chat_and_columns_share_the_top_line(self):
        project = css_of("project.css")
        chat = project[project.index(".chat {"):project.index(".chat-head")]
        self.assertIn("top: 94px", chat)                                        # = top bar (26 + 38 + 26) + 4 px of main
        app = css_of("app.css")
        self.assertIn(".project-page .topbar { min-height: 90px; }", app)
        self.assertIn("main { display: flex; align-items: stretch; place-items: initial; padding-top: 4px; }", project)

    def test_gear_handle_is_an_oval_with_the_outline_of_the_round_buttons(self):
        app = css_of("app.css")
        handle = app[app.index(".drawer-handle {"):app.index(".drawer-handle:hover")]
        for part in ("height: 38px", "border: 1px solid var(--glass-border)", "border-radius: 999px", "margin-top: 3px"):
            self.assertIn(part, handle)
        extra = app[app.index(".drawer-extra {"):app.index(".drawer-extra svg")]
        self.assertIn("width: 38px", extra)                                     # same height as the round buttons
        self.assertIn("margin-top: 3px", extra)                                 # and the same line
    def test_brand_back_button_and_round_buttons_share_one_line(self):
        app = css_of("app.css")
        self.assertIn("--line: 34px;", app)                                      # the line of the round buttons ...
        drawer = app[app.index(".drawer {"):app.index(".drawer.open")]
        self.assertIn("top: calc(var(--line) - 22px)", drawer)                   # ... buttons: 3 px + 38 px / 2 = 22 px
        self.assertIn(".brand { margin-top: calc(var(--line) - 12px);", app)     # brand: 24 px line height / 2 = 12 px
        self.assertIn("margin-top: calc(var(--line) - 19px)", app[app.index(".topbar-back {"):app.index(".topbar-back::after")])
        bar = app[app.index(".topbar {"):app.index(".brand {")]
        self.assertIn("align-items: flex-start", bar)                            # items hang from the line, not centred
        self.assertIn(":root { --line: 30px; }", app)                           # on the phone the gear sits 4 px higher
        low = css_of("dashboard.css")
        self.assertIn("--line: 24px", low)                                       # low windows move the line, and the gear with it
    def test_answers_with_links_are_built_safely(self):
        script = css_of("chat.js")
        self.assertNotIn("innerHTML", script)
        self.assertIn("(https?:", script)                                       # only http(s) links, never javascript:
        self.assertIn("noopener noreferrer", script)
        self.assertIn("createTextNode", script)
        self.assertIn("fillBlocks(body, text)", script)
        self.assertIn("line(\"claude\", box.dataset.claude, m.answer, true)", script)   # only Claude answers, not the questions
        self.assertLess(len(__import__("app.i18n", fromlist=["t"]).t("en", "chat_hint")), 60)       # one short sentence

    def test_chat_has_the_web_and_code_switches(self):
        page = self.html()
        modes = page[page.index('id="chat-modes"'):page.index('id="chat-form"')]
        self.assertIn('data-mode="web" aria-pressed="true"', modes)               # web is on at first
        self.assertIn('data-mode="code" aria-pressed="false"', modes)
        self.assertIn("ohne Internet", modes)                                      # the title says what code can not do
        self.assertLess(page.index('id="chat-modes"'), page.index('id="chat-form"'))
        script = css_of("chat.js")
        self.assertIn("data.append(\"mode\", currentMode())", script)
        self.assertIn("\"plain\"", script)                                         # both off: Claude just answers
        self.assertIn("fillBlocks", script)
        self.assertIn("createElement(\"pre\")", script)                            # code blocks, built from nodes
        self.assertNotIn("innerHTML", script)
        css = css_of("project.css")
        self.assertIn(".chat-mode[aria-pressed=\"true\"]", css)
        self.assertIn(".chat-text pre", css)
    def test_tooltips_are_our_own(self):
        core, app = css_of("core.js"), css_of("app.css")
        for part in ('className = "tip"', "removeAttribute(\"title\")", "aria-label", "mouseover", "showTip", "focusin"):
            self.assertIn(part, core)
        self.assertIn(".tip {", app)
        self.assertIn("backdrop-filter", app[app.index(".tip {"):app.index(".tip.show")])
        # a title is adopted, never lost: icon buttons keep it as their name for screen readers
        self.assertIn("textContent.trim()", core)

if __name__ == "__main__":
    unittest.main()
