"""Every user has his own world: nobody sees, changes or deletes what belongs to somebody else.

Two users, A with projects and board items in every state, B tries everything with A's ids.
Afterwards A's data must be exactly as before.
"""
import os
import tempfile
import types
import unittest

from fastapi import HTTPException

from app import board, checks, dashboard, db, files, memory, power, projectpage, projects, resets, throttle, ui, users
from app.routes import board as board_routes, checks as check_routes, files as file_routes, projects as project_routes, resets as reset_routes


def snapshot() -> dict:
    """Everything of the projects and boards, to compare before and after."""
    with db.connect() as conn:
        return {
            "projects": [tuple(r) for r in conn.execute("SELECT * FROM projects ORDER BY id")],
            "items": [tuple(r) for r in conn.execute("SELECT * FROM board_items ORDER BY id")],
            "checks": [tuple(r) for r in conn.execute("SELECT * FROM checks ORDER BY id")],
            "files": [tuple(r) for r in conn.execute("SELECT * FROM files ORDER BY id")],
        }


class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.project = projects.create_project(self.a.id, "Secret project of A")
        self.second = projects.create_project(self.a.id, "Second of A")
        self.open = board.create_item(self.a.id, self.project.id, "bug", "Open of A")
        self.proposed = board.create_suggestion(self.a.id, self.project.id, "minor", "Idea of A")
        dropped = board.create_item(self.a.id, self.project.id, "major", "Trash of A")
        board.discard(self.a.id, dropped.id)
        self.trashed = dropped
        self.mine = projects.create_project(self.b.id, "Project of B")
        self.mine_item = board.create_item(self.b.id, self.mine.id, "bug", "Item of B")
        self.check = checks.create(self.a.id, self.project.id, "Secret check of A", "weekly")
        self.my_check = checks.create(self.b.id, self.mine.id, "Check of B", "daily")

    def tearDown(self):
        self.tmp.cleanup()

    def test_model_and_effort_of_b_never_change_those_of_a(self):
        from app import agents
        agents.configure(self.a.id, "chef", model="opus", effort="max")
        agents.configure(self.b.id, "chef", model="haiku", effort="low")
        agents.configure(self.b.id, "reviewer", effort="xhigh")
        mine = agents.settings(self.a.id)["roles"]
        self.assertEqual((mine["chef"]["model"], mine["chef"]["effort"]), ("opus", "max"))
        self.assertEqual(mine["reviewer"]["effort"], "high")                  # still the default of A

    # --- agents and the Claude connection
    def test_b_cannot_touch_the_agents_of_a(self):
        from pathlib import Path
        from app import agents, claude_link
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        task = agents.start_task(self.a.id, self.project.id, self.open.id)
        with self.assertRaises(ValueError):
            agents.start_task(self.b.id, self.project.id, self.open.id)       # A's item, A's project
        with self.assertRaises(ValueError):
            agents.start_task(self.b.id, self.mine.id, self.open.id)          # own project, A's item
        self.assertIsNone(agents.get_task(self.b.id, task.id))
        self.assertEqual(agents.list_tasks(self.b.id, self.project.id), [])
        self.assertEqual(agents.task_runs(self.b.id, task.id), [])
        self.assertIsNone(agents.pick_next(self.b.id, self.project.id))
        for decision in ("approve", "reject", "cancel"):
            self.assertFalse(agents.decide(self.b.id, task.id, decision))
        self.assertEqual(agents.usage(self.b.id)["runs"], 0)
        # B is not connected: B's own task would wait, A's connection is never a stand-in
        mine = agents.start_task(self.b.id, self.mine.id, self.mine_item.id)
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.user_id, job.task_id), (self.a.id, task.id))
        self.assertTrue(agents.finish_run(job.run_id, "done"))
        self.assertEqual(agents.claim_next(can_mac=True).task_id, task.id)    # the tester of A, not B's task
        self.assertEqual(agents.get_task(self.b.id, mine.id).status, "coding")
        self.assertEqual(claude_link.status(self.b.id), "none")
        self.assertFalse(claude_link.disconnect(self.b.id))
        self.assertTrue(claude_link.is_connected(self.a.id))

    def test_b_cannot_touch_the_chat_of_a(self):
        from pathlib import Path
        from app import chat, claude_link
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        chat.send(self.a.id, self.project.id, "private question of A")
        with self.assertRaises(ValueError):
            chat.send(self.b.id, self.project.id, "planted")                   # A's project
        self.assertEqual(chat.list_messages(self.b.id, self.project.id), [])
        self.assertEqual(chat.delete_all(self.b.id), 0)                        # B's "delete all" never reaches A
        self.assertEqual([m.prompt for m in chat.list_messages(self.a.id, self.project.id)],
                         ["private question of A"])

    def test_b_cannot_touch_the_regular_checks_of_a(self):
        before = snapshot()
        self.assertEqual(checks.list_checks(self.b.id, self.project.id), [])
        self.assertIsNone(checks.update(self.b.id, self.check.id, "hacked", "daily"))
        self.assertFalse(checks.mark_done(self.b.id, self.check.id))
        self.assertFalse(checks.delete(self.b.id, self.check.id))
        with self.assertRaises(ValueError):
            checks.create(self.b.id, self.project.id, "planted", "daily")          # A's project
        check_routes.create_check(self.project.id, "planted", "daily", self.b)      # silently refused
        check_routes.change_check(self.check.id, "hacked", "daily", self.b)
        self.assertEqual(check_routes.check_done(self.check.id, self.b).status_code, 404)
        self.assertEqual(check_routes.check_delete(self.check.id, self.b).status_code, 404)
        self.assertEqual(snapshot(), before)
        page = projectpage.render(self.b, self.mine, [], checks.list_checks(self.b.id, self.mine.id))
        self.assertIn("Check of B", page)
        self.assertNotIn("Secret check", page)

    def test_b_cannot_touch_the_files_of_a(self):
        from pathlib import Path
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        item = files.start_upload(self.a.id, self.project.id, "secret.md", 6)
        files.append_chunk(self.a.id, item.id, 0, b"secret")
        files.finish_upload(self.a.id, item.id)
        link = files.add_link(self.a.id, self.project.id, "https://example.org", "Secret link")
        half = files.start_upload(self.a.id, self.project.id, "half.bin", 3)
        before = snapshot()
        self.assertEqual(files.list_files(self.b.id, self.project.id), [])
        for call in (
            lambda: files.start_upload(self.b.id, self.project.id, "planted.md", 1),      # A's project
            lambda: files.add_link(self.b.id, self.project.id, "https://evil.example"),
            lambda: files.append_chunk(self.b.id, half.id, 0, b"abc"),                      # A's upload
            lambda: files.finish_upload(self.b.id, half.id),
            lambda: files.update(self.b.id, item.id, "hacked.md"),
            lambda: files.update(self.b.id, link.id, "hacked", url="https://evil.example"),
        ):
            with self.assertRaises(files.FileError):
                call()
        self.assertIsNone(files.open_file(self.b.id, item.id))
        self.assertIsNone(files.check_names(self.b.id, self.project.id, ["secret.md"]))   # B learns no names of A
        self.assertIsNone(files.zip_entries(self.b.id, self.project.id, [item.id]))       # nor gets A's files as a ZIP
        self.assertEqual(files.zip_entries(self.b.id, self.mine.id, [item.id]), [])       # not even through his own project
        self.assertIsNone(files.read_text(self.b.id, item.id))
        self.assertFalse(files.write_text(self.b.id, item.id, "hacked"))
        self.assertFalse(files.delete(self.b.id, item.id))
        self.assertEqual(file_routes.serve(item.id, 0, self.b).status_code, 404)
        self.assertEqual(file_routes.serve(item.id, 1, self.b).status_code, 404)
        self.assertEqual(file_routes.read_text(item.id, self.b).status_code, 404)
        self.assertEqual(file_routes.delete(item.id, self.b).status_code, 404)
        self.assertEqual(file_routes.upload_progress(half.id, self.b).status_code, 404)   # A's unfinished upload
        self.assertIsNone(files.open_thumb(self.b.id, item.id))
        self.assertFalse(files.save_thumb(self.b.id, item.id, b"\xff\xd8\xff planted"))   # A's file
        self.assertEqual(file_routes.thumb(item.id, self.b).status_code, 404)
        self.assertEqual(snapshot(), before)
        self.assertEqual(files.read_text(self.a.id, item.id), "secret")
        page = projectpage.render(self.b, self.mine, [], [], files.list_files(self.b.id, self.mine.id))
        self.assertNotIn("secret.md", page)
        self.assertNotIn("Secret link", page)

    def test_the_manager_of_b_never_sees_the_memory_or_files_of_a(self):
        from pathlib import Path
        from app import chat, claude_link
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        secret = files.start_upload(self.a.id, self.project.id, "secret-plan.md", 6)
        files.append_chunk(self.a.id, secret.id, 0, b"SECRET")
        files.finish_upload(self.a.id, secret.id)
        self.assertTrue(memory.save_memory(self.a.id, self.project.id, "# Status\nSECRET MEMORY OF A"))
        before = snapshot()
        self.assertFalse(memory.save_memory(self.b.id, self.project.id, "planted"))        # A's project
        for user in (self.a, self.b):
            claude_link.begin(user.id)
            claude_link.complete(user.id, True)
        chat.send(self.b.id, self.mine.id, "What do you know?")
        job = chat.claim_next()
        self.assertNotIn("SECRET", job.prompt)
        self.assertNotIn("secret-plan.md", job.prompt)
        self.assertTrue(chat.finish(job.chat_id, True, "<read>secret-plan.md</read><memory>planted</memory>"))
        text = chat.claim_next().prompt                                                  # asked again with files
        self.assertIn("(there is no such file in this project)", text)
        self.assertNotIn("SECRET", text)
        with db.connect() as conn:
            self.assertEqual(memory.read_memory(conn, self.b.id, self.project.id), None)  # A's memory, B asks
            self.assertIn("no such file", memory.contents(conn, self.b.id, self.project.id, ["secret-plan.md"]))
            self.assertEqual(memory.listing(conn, self.b.id, self.project.id), "")
        self.assertEqual(snapshot()["files"], before["files"])                           # nothing of A's changed

    def test_the_manager_of_b_never_sees_the_checks_of_a(self):
        from app import chat, claude_link
        from pathlib import Path
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        claude_link.begin(self.b.id)
        claude_link.complete(self.b.id, True)
        chat.send(self.b.id, self.mine.id, "Question of B")
        text = chat.claim_next().prompt
        self.assertIn("Check of B", text)
        self.assertNotIn("Secret check", text)

    # --- the data layer
    def test_the_manager_of_b_never_sees_the_project_of_a(self):
        from app import chat, claude_link
        from pathlib import Path
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        for user in (self.a, self.b):
            claude_link.begin(user.id)
            claude_link.complete(user.id, True)
        projects.update_details(self.a.id, self.project.id, "Secret project of A", "Secret description of A")
        chat.send(self.a.id, self.project.id, "Question of A")
        job = chat.claim_next()
        chat.finish(job.chat_id, True, "Secret answer for A")
        chat.send(self.b.id, self.mine.id, "Question of B")
        text = chat.claim_next().prompt
        self.assertIn("Project of B", text)
        self.assertIn("Item of B", text)
        for secret in ("Secret project", "Secret description", "Open of A", "Idea of A", "Question of A",
                       "Secret answer"):
            self.assertNotIn(secret, text)
        with self.assertRaises(ValueError):
            chat.send(self.b.id, self.project.id, "Planted in A")                 # B can not ask in A's project

    def test_b_cannot_read_anything_of_a(self):
        self.assertIsNone(projects.get_project(self.b.id, self.project.id))
        self.assertIsNone(projects.display_page(self.b.id, self.project.id))
        self.assertEqual(board.list_items(self.b.id, self.project.id), [])
        names = [p.name for page in projects.layout(self.b.id) for p in page]
        self.assertEqual(names, ["Project of B"])

    def test_b_cannot_change_anything_of_a(self):
        before = snapshot()
        for item in (self.open, self.proposed, self.trashed):
            self.assertIsNone(board.update_title(self.b.id, item.id, "hacked"))
            for action in (board.accept, board.reject, board.discard, board.restore, board.delete_item):
                self.assertFalse(action(self.b.id, item.id), action.__name__)
        self.assertEqual(board.empty_trash(self.b.id, self.project.id), 0)
        self.assertFalse(projects.delete_project(self.b.id, self.project.id))
        for call in (
            lambda: board.create_item(self.b.id, self.project.id, "bug", "planted"),
            lambda: board.create_suggestion(self.b.id, self.project.id, "bug", "planted by an agent"),
            lambda: projects.move(self.b.id, self.project.id, 1, 0),
            lambda: board.reorder(self.b.id, "bug", [self.open.id]),
            lambda: board.reorder(self.b.id, "bug", [self.mine_item.id, self.open.id]),  # one own, one foreign
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(snapshot(), before)

    def test_moving_projects_around_never_touches_other_users(self):
        projects.move(self.b.id, self.mine.id, 1, 0)
        projects.move(self.a.id, self.second.id, 1, 0)
        self.assertEqual([p.name for page in projects.layout(self.b.id) for p in page], ["Project of B"])
        self.assertEqual(
            [p.name for page in projects.layout(self.a.id) for p in page], ["Second of A", "Secret project of A"]
        )

    # --- the pages and routes
    def test_pages_of_b_do_not_contain_anything_of_a(self):
        shown = projects.layout(self.b.id)
        page = ui.logged_in_page(self.b, "Home", dashboard.render(self.b, shown, 1, False))
        for secret in ("Secret project", "Second of A", "Open of A", "Idea of A", "Trash of A", "a@example.com"):
            self.assertNotIn(secret, page)
        with self.assertRaises(HTTPException) as foreign:
            project_routes.project_view(self.project.id, self.b)
        self.assertEqual(foreign.exception.status_code, 404)
        mine = projectpage.render(self.b, self.mine, board.list_items(self.b.id, self.mine.id))
        self.assertNotIn("Open of A", mine)

    def test_routes_answer_404_for_foreign_things_and_change_nothing(self):
        before = snapshot()
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="203.0.113.9"))
        self.assertEqual(project_routes.delete_project(request, self.project.id, "Bbbb!pass12", self.b).status_code, 404)
        for action in board_routes.ITEM_ACTIONS:
            self.assertEqual(board_routes.item_action(self.open.id, action, self.b).status_code, 404, action)
        self.assertEqual(board_routes.empty_trash(self.project.id, self.b), {"ok": True})  # nothing to empty for B
        board_routes.create_item(self.project.id, "bug", "planted", self.b)             # silently refused
        board_routes.rename_item(self.open.id, "hacked", self.b)
        with self.assertRaises(HTTPException) as settings:
            project_routes.project_settings(self.project.id, "hacked", "hacked", self.b)   # Manager settings
        self.assertEqual(settings.exception.status_code, 404)
        self.assertEqual(snapshot(), before)
        own = project_routes.project_settings(self.mine.id, "Renamed", "Described", self.b)
        self.assertEqual((own.status_code, own.headers["location"]), (303, f"/projects/{self.mine.id}#manager"))
        self.assertEqual(projects.get_project(self.b.id, self.mine.id).description, "Described")
        self.assertEqual(projects.get_project(self.a.id, self.project.id).description, "")

    # --- accounts
    def test_a_normal_user_has_no_power_over_accounts(self):
        for call in (
            lambda: users.list_users(self.b),
            lambda: users.add_user(self.b, "x@example.com", "Start1234"),
            lambda: users.reset_password(self.b, self.a.id, "Start1234"),
            lambda: users.delete_user(self.b, self.a.id),
            lambda: users.set_admin(self.b, self.a.id, True),
            lambda: users.transfer_owner(self.b, self.a.id),
        ):
            with self.assertRaises(PermissionError):
                call()
        self.assertIsNotNone(users.check_login("a@example.com", "Aaaa!pass12"))

    def test_nobody_but_the_owner_restarts_or_shuts_down_the_pi(self):
        admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        for who in (self.a, self.b, admin):
            for action in power.ACTIONS:
                with self.assertRaises(PermissionError):
                    power.request_action(who, action)
        self.assertIsNone(power.claim_next())

    def test_profile_theme_and_password_only_change_the_own_account(self):
        users.set_profile(self.b.id, "Bee", "en")
        users.set_theme(self.b.id, "dark")
        users.change_own_password(self.b, "Bbbb!pass12", "Neu!Pass1234")
        again = users.get_by_id(self.a.id)
        self.assertEqual((again.display_name, again.language, again.theme), (None, "de", "light"))
        self.assertIsNotNone(users.check_login("a@example.com", "Aaaa!pass12"))

    def test_sessions_belong_to_one_user(self):
        token_a, token_b = users.create_session(self.a.id), users.create_session(self.b.id)
        self.assertEqual(users.get_user(token_a).id, self.a.id)
        self.assertEqual(users.get_user(token_b).id, self.b.id)
        users.delete_session(token_b)
        self.assertEqual(users.get_user(token_a).id, self.a.id)   # B logging out does not log A out
        users.set_password(self.b.id, "Neu!Pass1234")              # nor does B's new password
        self.assertEqual(users.get_user(token_a).id, self.a.id)

    def test_a_reset_link_changes_only_its_own_account(self):
        user, token = resets.create_token("b@example.com")
        self.assertEqual(user.id, self.b.id)
        self.assertTrue(resets.consume(token, "Neu!Pass1234"))
        self.assertIsNotNone(users.check_login("a@example.com", "Aaaa!pass12"))
        self.assertIsNone(users.check_login("b@example.com", "Bbbb!pass12"))
        self.assertIsNotNone(users.check_login("b@example.com", "Neu!Pass1234"))

    def test_deleting_an_account_leaves_the_others_alone(self):
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.b.id)
        self.assertEqual(len(board.list_items(self.a.id, self.project.id)), 3)
        self.assertEqual(len(projects.layout(self.a.id)[0]), 2)
        self.assertEqual(board.list_items(self.b.id, self.mine.id), [])


class PasswordResetRequestsAreLimitedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        users.create_user("a@example.com", "Aaaa!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, host="203.0.113.1"):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host=host))

    def test_an_ip_is_locked_after_too_many_requests_and_others_are_not(self):
        background = types.SimpleNamespace(add_task=lambda *args: None)
        def status(answer):   # the route returns the page itself (200) or a response with a status
            return getattr(answer, "status_code", 200)

        for _ in range(throttle.MAX_FAILURES):
            self.assertEqual(status(reset_routes.forgot(self.request(), background, "x@example.com")), 200)
        self.assertEqual(status(reset_routes.forgot(self.request(), background, "x@example.com")), 429)
        self.assertEqual(status(reset_routes.forgot(self.request("203.0.113.2"), background, "x@example.com")), 200)
        # the counter is separate from the one for wrong passwords: login still works for that IP
        self.assertEqual(throttle.seconds_locked("203.0.113.1"), 0)

    def test_a_flooded_address_gets_one_mail_per_cooldown(self):
        sent = []
        background = types.SimpleNamespace(add_task=lambda *args: sent.append(args))
        for host in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
            reset_routes.forgot(self.request(host), background, "a@example.com")
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
