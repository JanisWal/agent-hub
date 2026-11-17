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
                                 styles=projectpage.STYLES, top_center=projectpage.title_html(self.project, lang), top_left=projectpage.back_html(lang),
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
        board_html = page[page.index('id="board"'):page.index('id="manager-view"')]
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
        self.assertEqual(nav.count('class="station off"'), 0)                  # every station has a view (15.11.2026)
        for name in ("programmer", "tester", "reviewer", "me"):
            self.assertIn(f'href="#{name}" data-seg data-station="{name}"', nav)
            self.assertIn(f'data-view-panel="{name}"', page)
        self.assertEqual(nav.count('class="station active"'), 1)
        self.assertIn('href="#manager" data-seg data-station="manager"', nav)
        self.assertIn('href="#board" data-seg data-station="board"', nav)
        self.assertNotIn("Alle Projekte", nav)                                # the way back is in the top bar now
        self.assertNotIn("station-back", page)
        self.assertNotIn("clip-path", css_of("project.css"))                 # sharp edges, no arrows

    def test_manager_view_has_three_columns_as_sketched(self):
        page = self.html()
        manager = page[page.index('<section class="manager" id="manager-view"'):]
        end = "</section>\n  </div>\n</section>"
        manager = manager[:manager.index(end) + len(end)]
        self.assertIn(" hidden>", manager.split("\n")[0])                      # the board is shown first
        columns = manager.split('<div class="mcol">')[1:]
        self.assertEqual(len(columns), 3)
        order = [[t for t in ("Status", "Geräte", "Regelmäßige Prüfungen", "Dateien", "Manager-Chat", "Wartet auf dich")
                  if f"<h2>{t}</h2>" in column] for column in columns]
        self.assertEqual(order, [["Status", "Geräte"], ["Regelmäßige Prüfungen", "Dateien"],
                                 ["Manager-Chat", "Wartet auf dich"]])        # left | middle | right, top to bottom
        for column in columns:                                                # within a column, in this order
            titles = [column.index(f"<h2>{t}</h2>") for t in ("Status", "Regelmäßige Prüfungen", "Manager-Chat")
                      if f"<h2>{t}</h2>" in column]
            self.assertEqual(titles, sorted(titles))
        self.assertEqual(manager.count('class="mtile glass m-soon'), 0)       # nothing is announced any more
        for tall in ("m-grow", "m-chat"):
            self.assertIn(tall, manager)
        self.assertIn("nicht Teil des Boards", manager)                       # the checks are not board items
        self.assertNotIn("/projects/", manager)                               # name and description moved to the pencil
        self.assertIn("stations.js", page)
        self.assertNotIn('id="manager"', page)                                # the hash must not make the page scroll

    def test_pencil_next_to_the_title_opens_the_drop_down_for_name_and_description(self):
        projects.update_details(self.user.id, self.project.id, "My <b>project</b>", "About <script>x</script> %BODY%")
        self.project = projects.get_project(self.user.id, self.project.id)
        page = self.html()
        bar = page[page.index('<header class="topbar">'):page.index("</header>")]
        wrap = bar[bar.index('<div class="title-wrap">'):]
        self.assertLess(wrap.index('class="project-title"'), wrap.index('id="title-edit"'))
        self.assertLess(wrap.index('id="title-edit"'), wrap.index('id="title-menu"'))
        self.assertIn('aria-expanded="false"', wrap)
        self.assertIn('aria-label="Projekt bearbeiten"', wrap)
        menu = wrap[wrap.index('<form class="title-menu glass"'):]
        self.assertIn(" hidden", menu.split(">")[0])                          # closed until the pencil is pressed
        self.assertIn(f'action="/projects/{self.project.id}/settings"', menu)
        self.assertIn('value="My &lt;b&gt;project&lt;/b&gt;"', menu)
        self.assertIn("About &lt;script&gt;x&lt;/script&gt; %BODY%", menu)    # escaped, not expanded
        self.assertNotIn("<script>x", page)
        self.assertIn("Projektbeschreibung", menu)
        self.assertIn("titlemenu.js", page)
        self.assertIn("Edit project", self.html("en"))
        self.assertIn("left: 38.2%", css_of("app.css")[css_of("app.css").index(".title-wrap"):][:200])  # still at the golden section
        pencil = css_of("app.css")[css_of("app.css").index(".title-edit {"):]
        pencil = pencil[:pencil.index("}")]
        for part in ("width: 38px", "border-radius: 50%", "translate: 0 calc(var(--line) - 45px)"):
            self.assertIn(part, pencil)                                       # like the round buttons, on their line

    def test_the_manager_chat_is_the_big_tile_and_the_old_window_is_gone(self):
        page = self.html()
        self.assertEqual(page.count('id="chat"'), 1)
        tile = page[page.index('class="mtile glass m-chat" id="chat"'):]
        tile = tile[:tile.index("</section>")]
        self.assertIn("<h2>Manager-Chat</h2>", tile)
        self.assertIn('data-claude="Manager"', tile)                          # the answers come from the manager
        for part in ('id="chat-log"', 'id="chat-form"', 'id="manager-model"'):
            self.assertIn(part, tile)
        self.assertGreater(page.index('id="chat"'), page.index('id="manager-view"'))   # inside the Manager view
        for gone in ("<aside", 'id="chat-toggle"', "Kurze Einzelfragen"):
            self.assertNotIn(gone, page)
        css = css_of("project.css")
        for gone in (".chat {", ".chat-toggle", "padding-right: 356px", "view-manager"):
            self.assertNotIn(gone, css)
        self.assertNotIn("chat-toggle", css_of("chat.js"))

    def test_model_and_autonomy_are_settings_of_the_manager_in_our_own_drop_downs(self):
        from app import agents
        agents.configure(self.user.id, "chef", model="opus", autonomy="all")
        page = self.html()

        def select(name):
            start = page.index(f'id="manager-{name}"')
            return page[page.rindex("<label", 0, start):page.index("</label>", start)]
        model, autonomy = select("model"), select("autonomy")
        for part in ('class="m-select has-select"', "<svg", 'data-setting='):
            self.assertIn(part, model)                                        # core.js styles it like the language select
            self.assertIn(part, autonomy)
        self.assertIn('value="opus" label="Opus" data-ai="Claude" selected', model)                         # what the server has
        self.assertIn('value="all" selected', autonomy)
        self.assertIn("Fragt bei Großem", autonomy)
        chat_tile = page[page.index('id="chat"'):]
        self.assertIn('id="manager-model"', chat_tile[:chat_tile.index("</header>")])        # in the chat header
        self.assertIn('id="manager-effort"', chat_tile[:chat_tile.index("</header>")])       # the level next to it
        self.assertIn("picker.js", page)
        waiting = page[page.index('class="mtile glass m-waiting"'):]
        self.assertIn('id="manager-autonomy"', waiting[:waiting.index("</header>")])        # at "waiting for you"
        script = css_of("manager.js")
        self.assertIn("fetch(area.dataset.settingsUrl", script)                  # one script for every agent's area
        self.assertIn('data-settings-url="/manager/settings"', page)
        self.assertIn("manager.js", page)
        self.assertIn("Decides alone", self.html("en"))

    def test_the_closed_drawer_does_not_cover_the_page(self):
        app = css_of("app.css")
        drawer = app[app.index(".drawer {"):app.index(".drawer.open")]
        self.assertIn("pointer-events: none;", drawer)                          # it covered the send button
        self.assertIn(".drawer > * { pointer-events: auto; }", app)             # its buttons and panel still work

    def test_one_switch_for_web_and_code_together_or_apart(self):
        from app import agents
        page = self.html()
        for gone in ("chat-mode", "data-mode=", 'id="chat-modes"'):
            self.assertNotIn(gone, page)                                       # the old Web/Code buttons are gone
        header = page[page.index('id="chat"'):]
        header = header[:header.index('id="chat-log"')]
        # a pill next to the model in the chat header (Janis, 14.11.2026), red while pressed (open internet)
        tools = header[header.index('class="m-chat-tools"'):header.index("</header>")]
        self.assertIn('id="manager-net"', tools)
        self.assertLess(tools.index('id="manager-net"'), tools.index('id="manager-model"'))   # left of the model
        self.assertIn('data-on="together" data-off="apart" aria-pressed="true"', tools)      # on by default (open internet)
        self.assertIn('aria-label="Code mit Internet"', tools)
        self.assertIn('class="info-dot"', header)                                           # the hint is an "i" now
        self.assertNotIn("m-chat-sub", header)
        agents.configure(self.user.id, "chef", net="apart")
        self.assertIn('aria-pressed="false"', self.html()[self.html().index('id="manager-net"') - 200:][:400])
        self.assertNotIn("chatMode", css_of("chat.js"))
        self.assertIn("pill.dataset.on", css_of("manager.js"))
        self.assertIn('.m-pill[aria-pressed="true"] { color: var(--on-danger); background: var(--danger);', css_of("project.css"))
        self.assertNotIn(".m-switch", css_of("project.css"))

    def test_the_waiting_line_names_the_ai_in_use(self):
        """Janis, 14.11.2026: "Claude answers" must follow the provider, another AI brings its own name."""
        html = self.html()
        self.assertIn('data-waiting="{name} antwortet" data-ai="Claude"', html)   # chat.js fills in the chosen model's AI

    def test_segment_slider_for_stations_and_file_tabs(self):
        page = self.html()
        nav = page[page.index('class="stations"'):page.index("</nav>")]
        self.assertIn('class="station-thumb"', nav)                            # the shared slider, upright
        self.assertEqual(nav.count("data-seg"), 6)                              # every station, also those not built
        self.assertIn('data-seg data-cat="memory"', page)                      # the file tabs use the same slider
        self.assertIn("segment.js", page)
        self.assertLess(page.index("motion.js"), page.index("segment.js"))     # it needs the springs
        script = css_of("segment.js")
        for needle in ("Motion.spring", "Motion.rubberband", "Motion.velocityOf", "setPointerCapture", "seg-over"):
            self.assertIn(needle, script)
        self.assertIn("Segment.attach", css_of("stations.js"))
        self.assertIn("Segment.attach", css_of("files.js"))

    def test_splitters_between_the_tiles(self):
        page = self.html()
        middle = page[page.index('id="checks"'):page.index('id="files"')]
        self.assertIn('data-split="checks-files" role="separator"', middle)
        right = page[page.index('id="chat"'):page.index("m-waiting")]
        self.assertIn('data-split="chat-waiting"', right)
        self.assertIn("splitter.js", page)
        css = css_of("project.css")
        self.assertIn(".m-split:hover::after", css)
        self.assertIn(".m-split { display: none; }", css)                     # not in the one-column layout

    def test_stations_script_swaps_the_views_by_the_address(self):
        script = css_of("stations.js")
        for needle in ("location.hash", "replaceState", "data-station", "drawer-extra", "data-view-panel", "manager-open"):
            self.assertIn(needle, script)
        self.assertIn(".manager {", css_of("project.css"))
        self.assertIn("[hidden] { display: none !important; }", css_of("project.css"))

    def test_each_view_has_its_own_pair_of_round_buttons(self):
        """Janis, 11.11.2026: each area keeps its own controls. Since 14.11.2026 the Manager view has the same two
        buttons with its own jobs (chat archive, trash of the files); the board's pair is hidden there and vice versa."""
        script = css_of("stations.js")
        self.assertIn('document.body.classList.toggle("manager-open", name === "manager")', script)
        self.assertNotIn('show("board", true)', script)                        # no longer a way back to the board
        css = css_of("project.css")
        self.assertIn('.manager-open .drawer-extra[aria-controls="vault"] { display: none; }', css)
        self.assertIn("body:not(.manager-open) .drawer-extra.m-extra { display: none; }", css)
        buttons = projectpage.drawer_buttons("de")
        self.assertIn('id="marchive-toggle"', buttons)
        self.assertIn('id="mtrash-toggle"', buttons)
        self.assertNotIn("data-action", buttons)                                  # board.js never acts on them
        self.assertIn('.drawer-extra[aria-controls="vault"]', css_of("board.js"))

    def test_manager_tile_classes_do_not_clash_with_the_settings_bar(self):
        css = css_of("project.css")
        for clash in (".mtile.status", ".mtile.settings", ".mtile.soon", ".lamp {", ".tag {"):
            self.assertNotIn(clash, css)                                      # `.status` is the Claude row of the drawer

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

    def test_columns_end_on_one_line_above_the_theme_button(self):
        project, app = css_of("project.css"), css_of("app.css")
        self.assertIn("main { padding-bottom: 96px; }", app)                    # columns stretch down to here
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
            chat = page[page.index('id="chat"'):]
            chat = chat[:chat.index("</section>")]
            for word in ("Vorübergehend", "Temporary", "testen", "Testfenster", "chat-badge", "TEMPORARY"):
                self.assertNotIn(word, chat)
        for lang in ("de", "en"):
            hint = __import__("app.i18n", fromlist=["t"]).t(lang, "manager_chat_hint")
            self.assertLess(len(hint), 60, hint)                                  # one short sentence, no explanations
            self.assertEqual(hint.count("."), 1)
        for name in ("project.css", "chat.js"):
            self.assertNotIn("TEMPORARY", css_of(name))

    def test_the_page_starts_below_the_top_bar(self):
        project = css_of("project.css")
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

    def test_chat_answers_show_code_blocks_safely(self):
        script = css_of("chat.js")
        self.assertIn("fillBlocks", script)
        self.assertIn("createElement(\"pre\")", script)                            # code blocks, built from nodes
        self.assertNotIn("innerHTML", script)
        self.assertIn(".chat-text pre", css_of("project.css"))
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


class RoleViewsTest(unittest.TestCase):
    """The views of programmer, tester, reviewer and "For you" (rolepage.py, 15.11.2026)."""
    setUp, tearDown, html = ProjectPageTest.setUp, ProjectPageTest.tearDown, ProjectPageTest.html

    def run_task(self, results):
        from app import agents, claude_link
        claude_link.begin(self.user.id)
        claude_link.complete(self.user.id, True)
        task = agents.start_task(self.user.id, self.project.id, self.bug.id)
        for result, report in results:
            job = agents.claim_next(can_mac=True)
            self.assertTrue(agents.finish_run(job.run_id, result, report, tokens_in=1200, tokens_out=30, seconds=12))
        return task

    def test_each_role_shows_its_settings_its_runs_and_its_usage(self):
        from app import agents
        agents.configure(self.user.id, "tester", enabled=True, net="apart")
        self.run_task([("done", "Built <it>"), ("pass", "All green")])
        page = self.html()
        prog = page[page.index('id="view-programmer"'):page.index('id="view-tester"')]
        tester = page[page.index('id="view-tester"'):page.index('id="view-reviewer"')]
        self.assertIn('data-settings-url="/roles/programmer/settings"', prog)
        self.assertNotIn('id="role-programmer-enabled"', prog)               # the programmer is always on
        self.assertIn('id="role-tester-enabled"', tester)
        self.assertIn('id="role-tester-model"', tester)
        self.assertIn('id="role-tester-net" data-setting="net" data-on="together" data-off="apart" aria-pressed="false"', tester)
        self.assertIn("Built &lt;it&gt;", prog)                               # the report, escaped
        self.assertIn("Fertig", prog)
        self.assertIn("Bestanden", tester)
        self.assertIn("Läufe: 1", prog)
        self.assertIn("1.2k", prog)
        reviewer = page[page.index('id="view-reviewer"'):page.index('id="view-me"')]
        self.assertIn("Prüfer", page)
        self.assertIn('class="r-now queued"', reviewer)                       # the reviewer's run waits
        self.assertIn("Gerade nichts zu tun.", prog)
        self.assertIn("roles.js", page)
        self.assertIn("Your jobs", self.html("en"))

    def test_decisions_wait_in_the_manager_tile_not_in_for_you(self):
        page = self.html()
        self.assertIn("Nichts wartet auf dich.", page)
        self.run_task([("done", "Built"), ("pass", "Green"), ("ok", "Fine by me")])
        page = self.html()
        waiting = page[page.index('id="waiting"'):page.index("</section>", page.index('id="waiting"'))]
        self.assertIn("A bug", waiting)
        self.assertIn("Wartet auf deine Freigabe", waiting)
        self.assertIn("Fine by me", waiting)
        self.assertIn('data-goto="board"', waiting)
        self.assertIn('<span class="count">1</span>', waiting)
        self.assertNotIn("agent-approve", waiting)                            # deciding stays on the board card
        me = page[page.index('id="view-me"'):]
        self.assertNotIn("A bug", me)

    def test_for_you_lists_own_jobs_with_notes_and_counts_open_ones_at_the_station(self):
        from app import todos
        page = self.html()
        self.assertIn("Gerade steht nichts für dich an.", page)
        self.assertIn('<span class="station-count" id="me-badge" hidden>0</span>', page)
        self.assertIn('id="todo-dialog"', page)                               # dialogs outside the hidden view
        self.assertIn("todos.js", page)
        first = todos.create(self.user.id, self.project.id, "Lay <cable>")
        second = todos.create(self.user.id, self.project.id, "Fit relay")
        todos.finish(self.user.id, second, "Fitted, screws M4")
        page = self.html()
        me = page[page.index('id="view-me"'):]
        self.assertIn("Lay &lt;cable&gt;", me)
        self.assertIn('class="todo-note">Fitted, screws M4', me)
        self.assertLess(me.index("Lay &lt;cable&gt;"), me.index("Fit relay"))  # open ones first
        self.assertIn('<span class="count" id="me-count">1</span>', me)
        self.assertIn('<span class="station-count" id="me-badge">1</span>', page)
        self.assertIn(f'data-id="{first}"', me)


    def test_the_settings_route_takes_only_the_three_roles(self):
        from app import agents
        from app.routes import roles as routes

        def call(role, **form):
            values = {"enabled": "", "model": "", "net": "", "effort": ""} | form
            return routes.role_settings(role, user=self.user, **values)
        answer = call("tester", enabled="0", net="apart")
        self.assertEqual((answer["enabled"], answer["net"]), ("0", "apart"))
        self.assertFalse(agents.settings(self.user.id)["roles"]["tester"]["enabled"])
        self.assertEqual(call("reviewer", model="opus", effort="max")["effort"], "max")
        self.assertEqual(call("programmer", enabled="0").status_code, 400)    # the programmer stays on
        self.assertEqual(call("chef", net="apart").status_code, 400)          # the manager has its own route
        self.assertEqual(call("tester", enabled="yes").status_code, 400)
        self.assertEqual(call("tester", model="gpt-9").status_code, 400)
