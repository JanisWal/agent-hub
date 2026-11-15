import os
import sqlite3
import tempfile
import unittest

from app import db, users

OLD_SCHEMA = (
    "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,"
    " password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);"
    "CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    " expires_at INTEGER NOT NULL);"
    "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('a@x.de', 'h', 1, 1);"
    "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('b@x.de', 'h', 1, 2);"
    "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('c@x.de', 'h', 0, 3);"
    "INSERT INTO sessions (token, user_id, expires_at) VALUES ('plain-old-cookie-value', 1, 99999999999);"
)


def columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class DatabaseUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.db")
        db.DB_PATH = self.path

    def tearDown(self):
        self.tmp.cleanup()

    def old_database(self):
        old = sqlite3.connect(self.path)
        old.executescript(OLD_SCHEMA)
        old.commit()
        old.close()

    def reopen(self):
        db._ready.discard(self.path)   # as after a restart of the app

    def test_old_database_is_converted(self):
        self.old_database()
        with db.connect() as conn:
            roles = {r["email"]: r["role"] for r in conn.execute("SELECT email, role FROM users")}
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        self.assertEqual(roles, {"a@x.de": "owner", "b@x.de": "admin", "c@x.de": "user"})
        self.assertNotIn("is_admin", columns(self.path, "users"))
        self.assertIn("token_hash", columns(self.path, "sessions"))
        self.assertNotIn("token", columns(self.path, "sessions"))
        self.assertEqual(sessions, 0, "old sessions were stored in the clear and are dropped")

    def test_conversions_run_once_and_never_undo_later_changes(self):
        self.old_database()
        with db.connect():
            pass
        owner = users.get_by_id(1)
        other = users.get_by_id(2)
        users.set_admin(owner, other.id, False)      # b is a normal user now
        self.reopen()
        self.reopen()
        with db.connect() as conn:
            roles = {r["email"]: r["role"] for r in conn.execute("SELECT email, role FROM users")}
        self.assertEqual(roles["b@x.de"], "user", "a restart must not make him an admin again")

    def test_a_fresh_database_is_current(self):
        with db.connect():
            pass
        self.assertNotIn("is_admin", columns(self.path, "users"))
        self.assertIn("token_hash", columns(self.path, "sessions"))
        conn = sqlite3.connect(self.path)
        names = [row[1] for row in conn.execute("PRAGMA index_list(users)")]
        conn.close()
        self.assertIn("users_one_owner", names)

    def test_the_old_copy_of_the_style_goes_once(self):
        with db.connect():
            pass
        conn = sqlite3.connect(self.path)
        conn.execute("ALTER TABLE users ADD COLUMN theme TEXT NOT NULL DEFAULT 'light'")   # as until 15.11.2026
        conn.commit()
        conn.close()
        self.reopen()
        with db.connect():
            pass
        self.assertNotIn("theme", columns(self.path, "users"))

    def test_sessions_are_stored_only_as_hashes(self):
        user = users.create_user("a@example.com", "Aaaa!pass12")
        token = users.create_session(user.id)
        with db.connect() as conn:
            stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        self.assertEqual(stored, [users.hash_token(token)])
        self.assertNotEqual(stored[0], token)
        self.assertEqual(users.get_user(token).id, user.id)
        self.assertIsNone(users.get_user(stored[0]), "the stored hash is no login")

    def test_a_new_password_keeps_only_the_chosen_session_and_cancels_reset_links(self):
        from app import resets
        user = users.create_user("a@example.com", "Aaaa!pass12")
        keep, other = users.create_session(user.id), users.create_session(user.id)
        _, link = resets.create_token("a@example.com")
        users.set_password(user.id, "Neu!Pass1234", keep_token=keep)
        self.assertIsNotNone(users.get_user(keep))
        self.assertIsNone(users.get_user(other))
        self.assertIsNone(resets.user_for_token(link), "a reset link from before the change is dead")

    def test_overlong_addresses_are_refused(self):
        with self.assertRaises(users.UserError):
            users.create_user("a" * 250 + "@example.com", "Aaaa!pass12")


if __name__ == "__main__":
    unittest.main()
