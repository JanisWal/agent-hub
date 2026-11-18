"""Every user has his own world: nobody sees, changes or deletes what belongs to somebody else.

Two users, A with projects and board items in every state, B tries everything with A's ids.
Afterwards A's data must be exactly as before.
"""
import os
import tempfile
import types
import unittest

from fastapi import HTTPException

from app import board, checks, dashboard, db, devices, status, files, memory, power, projectpage, projects, resets, throttle, todos, ui, users
from app.routes import board as board_routes, checks as check_routes, todos as todo_routes, files as file_routes, projects as project_routes, resets as reset_routes


def snapshot() -> dict:
    """Everything of the projects and boards, to compare before and after."""
    with db.connect() as conn:
        return {
            "projects": [tuple(r) for r in conn.execute("SELECT * FROM projects ORDER BY id")],
            "items": [tuple(r) for r in conn.execute("SELECT * FROM board_items ORDER BY id")],
            "checks": [tuple(r) for r in conn.execute("SELECT * FROM checks ORDER BY id")],
            "files": [tuple(r) for r in conn.execute("SELECT * FROM files ORDER BY id")],
            "todos": [tuple(r) for r in conn.execute("SELECT * FROM todos ORDER BY id")],
            "devices": [tuple(r) for r in conn.execute("SELECT * FROM devices ORDER BY id")],
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

    def test_b_cannot_see_change_or_delete_the_devices_of_a(self):
        import pyrage
        from app.routes import devices as device_routes
        os.environ["HUB_VAULT_PUBLIC"] = str(pyrage.x25519.Identity.generate().to_public())
        self.addCleanup(os.environ.pop, "HUB_VAULT_PUBLIC", None)
        mine = devices.create(self.a.id, self.project.id, "Roadster", "roadster.local", "Car", "secret")
        before = snapshot()
        self.assertEqual(devices.list_devices(self.b.id, self.project.id), [])
        self.assertIsNone(devices.create(self.b.id, self.project.id, "Mine", "x.local"))      # A's project
        self.assertIsNone(devices.update(self.b.id, mine.id, "Taken", "evil.local", "", "newkey", True))
        self.assertFalse(devices.delete(self.b.id, mine.id))
        self.assertEqual(device_routes.change_device(mine.id, "Taken", "evil.local", "", "", "", "other", "", user=self.b_user()).status_code, 404)
        self.assertEqual(device_routes.delete_device(mine.id, user=self.b_user()).status_code, 404)
        self.assertEqual(device_routes.create_device(self.project.id, "Mine", "x.local", "", "", "other", "", user=self.b_user()).status_code, 404)
        # the broker's side (17.11.2026): nothing of A's device for B, not even its state, log, window or setup
        self.assertIsNone(devices.payload(self.b.id, mine.id))
        self.assertIsNone(devices.get(self.b.id, mine.id))
        self.assertIsNone(devices.history(self.b.id, mine.id))
        self.assertFalse(devices.trust_host(self.b.id, mine.id, "ssh-ed25519 AAAA", "SHA256:x", "192.168.1.2"))
        self.assertFalse(devices.set_ai(self.b.id, mine.id, ["reboot"], True))
        self.assertFalse(devices.ai_may(self.b.id, mine.id, "reboot"))
        self.assertIsNone(devices.set_login(self.b.id, mine.id, "evil", 22))
        self.assertIsNone(devices.set_secret(self.b.id, mine.id, "key", "x"))
        self.assertFalse(devices.set_picture(self.b.id, mine.id, ""))
        self.assertFalse(devices.request_wake(self.b.id, mine.id))
        self.assertEqual(devices.open_requests(self.b.id, self.project.id), [])
        with db.connect() as conn:   # the manager of B can not ask for A's device, not even by its name
            self.assertFalse(devices.request_action(conn, self.b.id, self.project.id, "Roadster", "reboot"))
        for call in (lambda: device_routes.device_info(mine.id, user=self.b),
                     lambda: device_routes.device_setup(mine.id, user=self.b),
                     lambda: device_routes.device_history(mine.id, user=self.b),
                     lambda: device_routes.device_hostkey(mine.id, user=self.b),
                     lambda: device_routes.device_test(mine.id, user=self.b),
                     lambda: device_routes.device_keygen(mine.id, user=self.b),
                     lambda: device_routes.device_state(mine.id, user=self.b),
                     lambda: device_routes.device_ai(mine.id, ["reboot"], "1", user=self.b),
                     lambda: device_routes.device_login(mine.id, "evil", "22", None, user=self.b),
                     lambda: device_routes.device_secret(mine.id, "password", "x", "", user=self.b),
                     lambda: device_routes.device_picture(mine.id, "", user=self.b),
                     lambda: device_routes.device_request(1, "yes", user=self.b)):
            self.assertEqual(call().status_code, 404)
        self.assertEqual(snapshot(), before)

    def test_b_cannot_see_the_status_of_a(self):
        self.assertIsNone(status.assess(self.b.id, self.project.id))
        self.assertIsNotNone(status.assess(self.a.id, self.project.id))

    def b_user(self):
        return self.b

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
        self.assertEqual(agents.role_runs(self.b.id, self.project.id, "programmer"), [])      # role views (15.11.2026)
        self.assertEqual(agents.waiting_tasks(self.b.id, self.project.id), [])
        self.assertEqual(len(agents.role_runs(self.a.id, self.project.id, "programmer")), 1)
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
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        chat.send(self.a.id, self.project.id, "private question of A")
        with self.assertRaises(ValueError):
            chat.send(self.b.id, self.project.id, "planted")                   # A's project
        self.assertEqual(chat.list_messages(self.b.id, self.project.id), [])
        self.assertEqual(chat.delete_all(self.b.id), 0)                        # B's "delete all" never reaches A
        self.assertEqual([m.prompt for m in chat.list_messages(self.a.id, self.project.id)],
                         ["private question of A"])

    def test_b_cannot_touch_the_jobs_for_a(self):
        todo = todos.create(self.a.id, self.project.id, "Secret job of A")
        todos.finish(self.a.id, todos.create(self.a.id, self.project.id, "Done job of A"), "Secret note of A")
        mine = todos.create(self.b.id, self.mine.id, "Job of B")
        before = snapshot()
        self.assertEqual(todos.list_todos(self.b.id, self.project.id), [])
        self.assertEqual(todos.open_count(self.b.id, self.project.id), 0)
        self.assertIsNone(todos.create(self.b.id, self.project.id, "planted"))
        self.assertIsNone(todos.create(self.b.id, self.mine.id, "linked", task_id=1))   # no task of B's project
        self.assertFalse(todos.update(self.b.id, todo, "hacked"))
        self.assertFalse(todos.finish(self.b.id, todo, "hacked"))
        self.assertFalse(todos.reopen(self.b.id, todo))
        self.assertFalse(todos.delete(self.b.id, todo))
        self.assertEqual(todo_routes.create_todo(self.project.id, "planted", self.b).status_code, 404)
        for route in (todo_routes.edit_todo, todo_routes.finish_todo):
            self.assertEqual(route(todo, "hacked", self.b).status_code, 404)
        for route in (todo_routes.reopen_todo, todo_routes.delete_todo):
            self.assertEqual(route(todo, self.b).status_code, 404)
        self.assertEqual(snapshot(), before)
        page = projectpage.render(self.b, self.mine, [])
        self.assertIn("Job of B", page)
        self.assertNotIn("of A", page[page.index('id="view-me"'):])
        self.assertTrue(todos.delete(self.b.id, mine))

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
        files.delete(self.a.id, item.id)                                             # A's file in A's trash ...
        self.assertEqual(files.list_trash(self.b.id, self.project.id), [])          # ... B sees nothing of it
        self.assertIsNone(files.restore(self.b.id, item.id))
        self.assertFalse(files.purge(self.b.id, item.id))
        self.assertEqual(files.empty_trash(self.b.id, self.project.id), 0)
        self.assertEqual(file_routes.restore(item.id, self.b).status_code, 404)
        self.assertEqual(file_routes.purge(item.id, self.b).status_code, 404)
        self.assertTrue(files.path_of(self.project.id, item.id).exists())
        self.assertIsNotNone(files.restore(self.a.id, item.id))
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

    def test_b_cannot_see_use_or_move_the_folders_of_a(self):
        from pathlib import Path
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        folder = files.create_folder(self.a.id, self.project.id, "media", "Secret folder")
        inside = files.create_text_file(self.a.id, self.project.id, "x.txt", "secret")
        files.move(self.a.id, self.project.id, [inside.id], folder_id=folder.id)
        mine = files.create_folder(self.b.id, self.mine.id, "media", "Mine")
        before = snapshot()
        for call in (
            lambda: files.create_folder(self.b.id, self.project.id, "media", "planted"),        # A's project
            lambda: files.create_folder(self.b.id, self.mine.id, "media", "planted", folder.id), # A's folder as parent
            lambda: files.start_upload(self.b.id, self.mine.id, "planted.md", 1, folder_id=folder.id),
            lambda: files.move(self.b.id, self.project.id, [inside.id], "documents"),
            lambda: files.move(self.b.id, self.mine.id, [inside.id], folder_id=folder.id),
            lambda: files.update(self.b.id, folder.id, "hacked"),
        ):
            with self.assertRaises(files.FileError):
                call()
        self.assertEqual(files.move(self.b.id, self.mine.id, [inside.id, folder.id], folder_id=mine.id), 0)
        self.assertIsNone(files.check_names(self.b.id, self.mine.id, ["x.txt"], folder_id=folder.id))
        self.assertEqual(files.zip_entries(self.b.id, self.mine.id, [folder.id]), [])
        self.assertFalse(files.delete(self.b.id, folder.id))
        self.assertEqual(file_routes.create_folder(self.project.id, "planted", "media", "", "0", self.b).status_code, 404)
        self.assertEqual(file_routes.move(self.project.id, str(inside.id), "documents", "", self.b).status_code, 404)
        self.assertEqual(snapshot(), before)
        with db.connect() as conn:
            stored, _ = files.for_agents(conn, self.b.id, self.project.id)
        self.assertEqual(stored, [])

    def test_b_cannot_read_restore_or_edit_the_memory_versions_of_a(self):
        from pathlib import Path
        from app.routes import memory as memory_routes
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        memory.save_memory(self.a.id, self.project.id, "# Status\nSECRET ONE")
        memory.save_memory(self.a.id, self.project.id, "# Status\nSECRET TWO")
        [version] = memory.versions(self.a.id, self.project.id)
        before = snapshot()
        self.assertEqual(memory.versions(self.b.id, self.project.id), [])
        self.assertIsNone(memory.version_text(self.b.id, version.id))
        self.assertIsNone(memory.restore(self.b.id, version.id))
        self.assertEqual(memory_routes.version_text(version.id, self.b).status_code, 404)
        self.assertEqual(memory_routes.version_restore(version.id, self.b).status_code, 404)
        edit = memory.Edit("MEMORY.md", [("SECRET TWO", "planted")])
        self.assertFalse(memory.apply_edits(self.b.id, self.project.id, [edit])[0].ok)
        memo = next(f for f in files.list_files(self.a.id, self.project.id) if f.name == "MEMORY.md")
        self.assertFalse(memory.write_by_user(self.b.id, memo.id, "planted"))
        self.assertEqual(snapshot(), before)
        self.assertEqual(len(memory.versions(self.a.id, self.project.id)), 1)
        page = projectpage.render(self.b, self.mine, [])
        self.assertNotIn("MEMORY.md", page[page.index('id="mvault-versions"'):page.index('id="mvault-versions"') + 400])

    def test_the_manager_of_b_never_sees_the_memory_or_files_of_a(self):
        from pathlib import Path
        from app import chat, claude_link
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
            self.assertEqual(memory.folder(conn, self.b.id, self.project.id), "")         # nor A's memory folder
        self.assertEqual(memory.ensure_skeleton(self.b.id, self.project.id), 0)
        self.assertEqual(snapshot()["files"], before["files"])                           # nothing of A's changed

    def test_the_manager_of_b_never_sees_the_checks_of_a(self):
        from app import chat, claude_link
        from pathlib import Path
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
        for user in (self.a, self.b):
            claude_link.begin(user.id)
            claude_link.complete(user.id, True)
        projects.update_details(self.a.id, self.project.id, "Secret project of A", "Secret description of A")
        chat.send(self.a.id, self.project.id, "Question of A")
        job = chat.claim_next()
        chat.add_thoughts(job.chat_id, "Secret thought of A")
        chat.finish(job.chat_id, True, "Secret answer for A")
        chat.send(self.b.id, self.mine.id, "Question of B")
        text = chat.claim_next().prompt
        from app.routes import chat as chat_routes                               # B's page never gets A's thoughts
        self.assertEqual(chat_routes.messages(self.project.id, user=self.b)["messages"], [])
        self.assertNotIn("Secret thought", str(chat_routes.messages(self.mine.id, user=self.b)))
        self.assertIn("Project of B", text)
        self.assertIn("Item of B", text)
        for secret in ("Secret project", "Secret description", "Open of A", "Idea of A", "Question of A",
                       "Secret answer", "Secret thought"):
            self.assertNotIn(secret, text)
        with self.assertRaises(ValueError):
            chat.send(self.b.id, self.project.id, "Planted in A")                 # B can not ask in A's project

    def test_b_deleting_the_own_account_never_touches_a(self):
        from app import users as accounts
        token = accounts.create_session(self.a.id)
        accounts.delete_self(self.b)
        self.assertIsNotNone(accounts.get_user(token))                          # A stays signed in
        self.assertIsNotNone(projects.get_project(self.a.id, self.project.id))
        self.assertIsNone(accounts.get_by_id(self.b.id))

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
            lambda: users.set_superadmin(self.b, self.a.id, True),
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

    def test_profile_and_password_only_change_the_own_account(self):
        users.set_profile(self.b.id, "Bee", "en")
        users.change_own_password(self.b, "Bbbb!pass12", "Neu!Pass1234")
        again = users.get_by_id(self.a.id)
        self.assertEqual((again.display_name, again.language), (None, "de"))
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

    def test_the_mistral_connection_of_a_is_only_his(self):
        from app import agents, ai_link, chat
        from app.routes import ai as ai_routes
        key = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
        ai_link._keys.clear()
        ai_routes.connect("mistral", key, user=self.a)
        self.assertEqual(ai_routes.status("mistral", user=self.b)["status"], "none")
        ai_routes.disconnect("mistral", user=self.b)                                  # B can not cancel A's check
        self.assertEqual(ai_link.take_keys(), [(self.a.id, "mistral", key)])         # the user comes from the hub
        ai_link.complete(self.a.id, "mistral", True)
        agents.configure(self.b.id, "chef", model="mistral-small-2603")
        with self.assertRaisesRegex(ValueError, "none"):
            chat.send(self.b.id, self.mine.id, "Use the Mistral of A")               # no fallback to A's key
        from app import aichoice
        self.assertFalse(aichoice.set_default(self.b.id, "mistral"))                 # nor as his standard
        self.assertEqual(aichoice.connected(self.b.id), [])
        self.assertEqual(ai_link.status(self.a.id, "mistral"), "connected")

    def test_b_can_not_start_or_decide_tasks_of_a(self):
        from app import agents
        from app.routes import board as board_routes
        item = board.list_items(self.a.id, self.project.id)[0]
        for action in ("agent-start", "agent-approve", "agent-reject", "agent-cancel"):
            self.assertEqual(board_routes.item_action(item.id, action, user=self.b).status_code, 404)
        with self.assertRaises(ValueError):
            agents.start_item(self.b.id, item.id)
        self.assertEqual(agents.list_tasks(self.a.id, self.project.id), [])
        self.assertIsNone(agents.item_task(self.b.id, item.id))

    def test_deleting_an_account_leaves_the_others_alone(self):
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.b.id, now=1000)
        users.purge_deleted(now=1000 + (users.DELETED_DAYS + 1) * 86400)
        self.assertEqual(len(board.list_items(self.a.id, self.project.id)), 3)
        self.assertEqual(len(projects.layout(self.a.id)[0]), 2)
        self.assertEqual(board.list_items(self.b.id, self.mine.id), [])

    def test_bringing_an_account_back_gives_only_its_own_data(self):
        """Inviting the address of a deleted account restores that account, never anything of somebody else."""
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.b.id)
        back = users.add_user(owner, self.b.email, "Neustart1")
        self.assertEqual(back.id, self.b.id)
        self.assertEqual({p.id for page in projects.layout(back.id) for p in page}, {self.mine.id})
        self.assertEqual(board.list_items(back.id, self.project.id), [])       # A's project stays A's

    def test_the_folders_of_a_deleted_project_are_queued_for_its_owner_only(self):
        from app import agents
        self.assertFalse(projects.delete_project(self.b.id, self.project.id))  # not his: nothing is queued
        self.assertEqual(agents.pending_wipes(), [])
        self.assertTrue(projects.delete_project(self.b.id, self.mine.id))
        self.assertEqual(agents.pending_wipes(), [{"kind": "project", "ref": self.mine.id}])


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
