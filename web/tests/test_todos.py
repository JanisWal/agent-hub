"""The "For you" list (todos.py): data rules, the routes and the manager's context."""
import os
import tempfile
import unittest

from app import board, chat, claude_link, db, projects, todos, users
from app.routes import todos as todo_routes


class TodosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, text="Lay cable", now=1_000):
        return todos.create(self.user.id, self.project.id, text, now=now)

    def test_open_ones_first_then_the_done_ones_last_done_first(self):
        a, b, c, d = self.make("A", 1), self.make("B", 2), self.make("C", 3), self.make("D", 4)
        todos.finish(self.user.id, a, "", now=10)
        todos.finish(self.user.id, c, "", now=20)
        self.assertEqual([t.id for t in todos.list_todos(self.user.id, self.project.id)], [b, d, c, a])
        self.assertEqual(todos.open_count(self.user.id, self.project.id), 2)

    def test_bad_input_is_refused(self):
        self.assertIsNone(self.make("   "))
        self.assertIsNone(self.make("x" * (todos.MAX_TEXT + 1)))
        self.assertIsNone(todos.create(self.user.id, self.project.id, "Job", source="stranger"))
        self.assertIsNone(todos.create(self.user.id, self.project.id, "Job", task_id=999))   # no such task
        todo = self.make()
        self.assertFalse(todos.update(self.user.id, todo, ""))
        self.assertFalse(todos.finish(self.user.id, todo, "x" * (todos.MAX_NOTE + 1)))
        self.assertEqual(todos.list_todos(self.user.id, self.project.id)[0].text, "Lay cable")

    def test_a_project_holds_at_most_the_limit(self):
        with db.connect() as conn:
            conn.executemany("INSERT INTO todos (project_id, text, created_at) VALUES (?, 'x', 0)",
                             [(self.project.id,)] * todos.MAX_PER_PROJECT)
        self.assertIsNone(self.make())

    def test_finish_keeps_the_first_time_and_reopen_keeps_the_note(self):
        todo = self.make()
        self.assertTrue(todos.finish(self.user.id, todo, "  Done with M4 screws  ", now=50))
        self.assertTrue(todos.finish(self.user.id, todo, "Done with M5 screws", now=90))   # only the note changes
        entry = todos.list_todos(self.user.id, self.project.id)[0]
        self.assertEqual((entry.done_at, entry.note), (50, "Done with M5 screws"))
        self.assertTrue(todos.reopen(self.user.id, todo))
        entry = todos.list_todos(self.user.id, self.project.id)[0]
        self.assertEqual((entry.done, entry.note), (False, "Done with M5 screws"))
        self.assertTrue(todos.update(self.user.id, todo, "Lay cable again"))
        self.assertEqual(todos.list_todos(self.user.id, self.project.id)[0].text, "Lay cable again")

    def test_delete_and_deleting_the_project_removes_them(self):
        first, second = self.make("A"), self.make("B")
        self.assertTrue(todos.delete(self.user.id, first))
        self.assertFalse(todos.delete(self.user.id, first))
        projects.delete_project(self.user.id, self.project.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0], 0)

    def test_the_routes(self):
        answer = todo_routes.create_todo(self.project.id, "Fit relay", self.user)
        todo = answer["id"]
        self.assertEqual(todo_routes.create_todo(self.project.id, "", self.user).status_code, 404)
        self.assertTrue(todo_routes.edit_todo(todo, "Fit the relay", self.user)["ok"])
        self.assertTrue(todo_routes.finish_todo(todo, "Fitted", self.user)["ok"])
        self.assertTrue(todo_routes.reopen_todo(todo, self.user)["ok"])
        self.assertTrue(todo_routes.delete_todo(todo, self.user)["ok"])
        self.assertEqual(todo_routes.delete_todo(todo, self.user).status_code, 404)

    def test_the_manager_reads_open_and_done_ones_in_its_context(self):
        claude_link.begin(self.user.id)
        claude_link.complete(self.user.id, True)
        self.make("Buy fuse")
        done = self.make("Lay cable")
        todos.finish(self.user.id, done, "Laid along the frame")
        chat.send(self.user.id, self.project.id, "What is next?")
        text = chat.claim_next().prompt
        self.assertIn("For you (work the user does himself", text)
        self.assertIn("- Buy fuse (open)", text)
        self.assertIn("- Lay cable (done; what the user did: Laid along the frame)", text)


if __name__ == "__main__":
    unittest.main()
