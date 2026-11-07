"""Every user has his own world: nobody sees, changes or deletes what belongs to somebody else.

Two users, A with projects and board items in every state, B tries everything with A's ids.
Afterwards A's data must be exactly as before.
"""
import os
import tempfile
import types
import unittest

from fastapi import HTTPException

from app import board, dashboard, db, projectpage, projects, resets, throttle, ui, users
from app.routes import board as board_routes, projects as project_routes, resets as reset_routes


def snapshot() -> dict:
    """Everything of the projects and boards, to compare before and after."""
    with db.connect() as conn:
        return {
            "projects": [tuple(r) for r in conn.execute("SELECT * FROM projects ORDER BY id")],
            "items": [tuple(r) for r in conn.execute("SELECT * FROM board_items ORDER BY id")],
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

    def tearDown(self):
        self.tmp.cleanup()

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

    # --- the data layer
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
