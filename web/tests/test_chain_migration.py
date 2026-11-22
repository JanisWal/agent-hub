"""The one-time conversion of a database from before the chain was rebuilt (db._convert_chain, 22.11.2026)."""
import os
import sqlite3
import tempfile
import unittest

from app import db

OLD = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL);
CREATE TABLE projects (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL, position INTEGER NOT NULL, created_at INTEGER NOT NULL, page INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '');
INSERT INTO users (id, email, password_hash, created_at) VALUES (1, 'a@example.com', 'x', 1);
INSERT INTO projects (id, user_id, name, position, created_at) VALUES (1, 1, 'P', 0, 1);
CREATE TABLE agent_tasks (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, item_id INTEGER, title TEXT NOT NULL,
    kind TEXT NOT NULL, needs TEXT NOT NULL DEFAULT 'any', status TEXT NOT NULL, round INTEGER NOT NULL DEFAULT 1,
    manual_check INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
    deadline INTEGER NOT NULL, finished_at INTEGER, merged INTEGER NOT NULL DEFAULT 0,
    diff_stat TEXT NOT NULL DEFAULT '', diff TEXT NOT NULL DEFAULT '', tests TEXT NOT NULL DEFAULT '', tests_exit INTEGER);
CREATE INDEX agent_tasks_by_project ON agent_tasks (project_id, status);
CREATE TABLE board_items (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'open', position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL, details TEXT NOT NULL DEFAULT '', auto INTEGER NOT NULL DEFAULT 0);
CREATE TABLE questions (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, task_id INTEGER, role TEXT NOT NULL,
    text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text', options TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open', answer TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, answered_at INTEGER);
CREATE TABLE run_stops (run_id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL);
CREATE TABLE agent_settings (user_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (user_id, key));
"""


class ChainMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "old.db")
        raw = sqlite3.connect(db.DB_PATH)
        raw.executescript(OLD)
        raw.executemany("INSERT INTO agent_tasks (id, project_id, item_id, title, kind, status, created_at, deadline,"
                        " merged) VALUES (?, 1, ?, ?, 'minor', ?, 1, 2, ?)",
                        [(1, 10, "escalated", "escalated", -1), (2, 11, "waiting", "awaiting_approval", 0),
                         (3, 12, "finished", "done", 1), (4, None, "stopped", "cancelled", 0)])
        raw.executemany("INSERT INTO board_items (id, project_id, kind, title, status, created_at, auto) VALUES"
                        " (?, 1, 'minor', ?, ?, 1, ?)",
                        [(10, "escalated", "open", 1), (11, "waiting", "open", 1), (12, "finished", "archived", 1),
                         (13, "queued", "open", 1), (14, "from before", "open", 0), (15, "idea", "proposed", 0)])
        raw.executemany("INSERT INTO questions (project_id, task_id, role, text, kind, status, created_at) VALUES"
                        " (1, ?, ?, ?, ?, 'open', 1)",
                        [(None, "tester", "Kein Browser", "note"), (None, "chef", "Chat question?", "text"),
                         (1, "programmer", "12 or 24 V?", "text")])
        raw.executemany("INSERT INTO agent_settings (user_id, key, value) VALUES (1, ?, ?)",
                        [("model.chef", "opus"), ("effort.chef", "max"), ("strictness", "loose"),
                         ("model.tester.claude", "haiku")])
        raw.commit()
        raw.close()
        db._ready.discard(db.DB_PATH)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_tasks_wait_for_a_decision_and_the_rest_is_converted_once(self):
        with db.connect() as conn:
            tasks = {r["id"]: (r["stage"], r["hold"], r["hold_why"]) for r in conn.execute("SELECT * FROM agent_tasks")}
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(agent_tasks)")}
            items = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM board_items")}
            item_columns = {r["name"] for r in conn.execute("PRAGMA table_info(board_items)")}
            notes = [tuple(r) for r in conn.execute("SELECT text, source FROM todos")]
            asked = {r["text"]: r["status"] for r in conn.execute("SELECT text, status FROM questions")}
            keys = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM agent_settings")}
            stops = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'run_stops'").fetchone()[0]
        self.assertEqual(tasks, {1: ("coding", "decision", "old"), 2: ("merging", "decision", "old"),
                                 3: ("done", "", ""), 4: ("cancelled", "", "")})
        self.assertFalse(columns & {"status", "round", "note", "deadline", "merged"})
        self.assertEqual(items, {10: "working", 11: "working", 12: "archived", 13: "open", 14: "proposed",
                                 15: "proposed"})
        self.assertNotIn("auto", item_columns)
        self.assertEqual(notes, [("Kein Browser", "tester")])                 # a note became an entry in "For you"
        self.assertEqual(asked, {"Kein Browser": "delivered", "Chat question?": "dropped", "12 or 24 V?": "open"})
        self.assertEqual(keys, {"model.chef.claude": "opus", "effort.chef.claude": "max",
                                "model.tester.claude": "haiku"})              # old keys rewritten, strictness gone
        self.assertEqual(stops, 0)
        db._ready.discard(db.DB_PATH)
        with db.connect() as conn:                                            # a second start changes nothing
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT hold FROM agent_tasks WHERE id = 1").fetchone()[0], "decision")


if __name__ == "__main__":
    unittest.main()
