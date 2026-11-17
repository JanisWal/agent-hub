"""The written status of a project (statusnote.py): digest, when a round runs, the job, saving the answer, the lamp."""
import os
import tempfile
import time
import unittest

from app import board, chat, claude_link, db, managerpage, projects, status, statusnote, users

NOW = int(time.time())
DAY = 86400


class StatusNoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Roadster")
        self.pb = projects.create_project(self.b.id, "Secret of B")
        board.create_item(self.b.id, self.pb.id, "bug", "Only B may read this")
        statusnote._LAST_SCAN["at"] = 0

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)

    def scan(self, now=NOW):
        with db.connect() as conn:
            return statusnote.scan(conn, now, force=True)

    def queued(self):
        with db.connect() as conn:
            return conn.execute("SELECT * FROM chat_messages WHERE kind = 'status'").fetchall()

    def test_digest_is_short_from_the_owner_only_and_the_fingerprint_ignores_dates(self):
        board.create_item(self.a.id, self.pa.id, "bug", "Heater relay clicks")
        with db.connect() as conn:
            text = statusnote.digest(conn, self.a.id, self.pa.id, NOW)
            self.assertIn("Heater relay clicks", text)
            self.assertNotIn("Only B", text)
            self.assertLessEqual(len(text), statusnote.MAX_DIGEST)
            self.assertIsNone(statusnote.digest(conn, self.a.id, self.pb.id, NOW))       # foreign project
            self.assertEqual(statusnote.fingerprint(conn, self.a.id, self.pa.id, NOW),
                             statusnote.fingerprint(conn, self.a.id, self.pa.id, NOW + 3 * DAY))
            before = statusnote.fingerprint(conn, self.a.id, self.pa.id, NOW)
        board.create_item(self.a.id, self.pa.id, "minor", "New light")
        with db.connect() as conn:
            self.assertNotEqual(before, statusnote.fingerprint(conn, self.a.id, self.pa.id, NOW))

    def test_a_round_only_with_an_ai_with_something_in_it_and_when_facts_changed(self):
        board.create_item(self.a.id, self.pa.id, "bug", "Heater relay clicks")
        self.assertEqual(self.scan(), 0)                      # nobody has an AI
        self.connect(self.a)
        empty = projects.create_project(self.a.id, "Empty one")
        self.assertEqual(self.scan(), 1)                      # only the project with something in it
        rows = self.queued()
        self.assertEqual([(r["project_id"], r["mode"], r["model"], r["effort"]) for r in rows],
                         [(self.pa.id, "brief", "haiku", "low")])   # the cheapest choice of the list
        self.assertNotIn(empty.id, [r["project_id"] for r in rows])
        self.assertEqual(self.scan(), 0)                      # one is on its way
        job = chat.claim_next(NOW)
        self.assertEqual((job.mode, job.project_id, job.files), ("brief", 0, []))
        self.assertIn("Heater relay clicks", job.prompt)
        self.assertIn("<status", job.prompt)
        self.assertIn("German", job.prompt)
        self.assertTrue(chat.finish(job.chat_id, True, '<status level="yellow" title="Relais im Test">Der Fehler ist '
                                    'eingegrenzt. Als Nächstes der Austausch.</status>'))
        self.assertEqual(self.queued(), [])                   # the message goes, the note stays
        note = statusnote.latest(self.a.id, self.pa.id)
        self.assertEqual((note.level, note.title), ("yellow", "Relais im Test"))
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])   # never in the chat
        self.assertEqual(self.scan(NOW + 4 * 3600), 0)       # nothing changed: no new round
        board.create_item(self.a.id, self.pa.id, "minor", "New light")
        self.assertEqual(self.scan(NOW + 600), 0)             # changed, but too soon
        self.assertEqual(self.scan(NOW + 4 * 3600), 1)        # changed and the gap is over

    def test_a_failed_round_waits_longer_and_shows_nothing(self):
        board.create_item(self.a.id, self.pa.id, "bug", "X")
        self.connect(self.a)
        self.scan()
        job = chat.claim_next(NOW)
        chat.finish(job.chat_id, True, "I could not decide.")      # no valid <status>
        self.assertIsNone(statusnote.latest(self.a.id, self.pa.id))
        board.create_item(self.a.id, self.pa.id, "bug", "Y")
        self.assertEqual(self.scan(NOW + 4 * 3600), 0)           # FAILED_GAP not over
        self.assertEqual(self.scan(NOW + 7 * 3600), 1)

    def test_the_users_question_goes_first_and_the_daily_cap(self):
        board.create_item(self.a.id, self.pa.id, "bug", "X")
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "A question", now=NOW)
        self.assertEqual(self.scan(), 0)
        with db.connect() as conn:
            conn.execute("DELETE FROM chat_messages")
            for i in range(statusnote.DAILY_MAX):
                conn.execute("INSERT INTO project_status (project_id, source, fingerprint, created_at) VALUES (?, 'ai', ?, ?)",
                             (self.pa.id, f"x{i}", NOW - 20 * 3600))
        self.assertEqual(self.scan(), 0)

    def test_request_by_the_user(self):
        board.create_item(self.a.id, self.pa.id, "bug", "X")
        self.assertEqual(statusnote.request(self.a.id, self.pb.id, NOW), "missing")   # foreign
        self.assertEqual(statusnote.request(self.a.id, self.pa.id, NOW), "none")      # no AI
        self.connect(self.a)
        self.assertEqual(statusnote.request(self.a.id, self.pa.id, NOW), "queued")
        self.assertEqual(statusnote.request(self.a.id, self.pa.id, NOW), "wait")
        self.assertIsNone(statusnote.latest(self.b.id, self.pa.id))                    # foreign note is None

    def test_the_lamp_never_below_what_the_hub_knows(self):
        note = statusnote.Note("green", "T", "x", NOW)
        self.assertEqual(statusnote.lamp("red", note), "red")
        self.assertEqual(statusnote.lamp("green", statusnote.Note("yellow", "T", "x", NOW)), "yellow")
        self.assertEqual(statusnote.lamp("none", note), "green")
        self.assertEqual(statusnote.lamp("yellow", None), "yellow")

    def test_the_tile_shows_the_written_status_in_bold(self):
        board.create_item(self.a.id, self.pa.id, "bug", "X")
        a = status.assess(self.a.id, self.pa.id, NOW)
        html = managerpage._status_tile("de", a, NOW, statusnote.Note("green", "Heizung läuft", "Alles <gut>.", NOW - 60))
        self.assertIn("<strong>Heizung läuft</strong>", html)
        self.assertIn("Alles &lt;gut&gt;.", html)
        self.assertIn('id="status-again"', html)
        self.assertNotIn("Viel in Bewegung", html)

    def test_memory_files_of_the_hub_do_not_make_a_project_busy(self):
        from app import files
        with db.connect() as conn:
            for i in range(8):
                conn.execute("INSERT INTO files (project_id, name, category, created_at) VALUES (?, ?, 'memory', ?)",
                             (self.pa.id, f"M{i}.md", NOW - 60))
            for i in range(12):   # one upload of twelve files counts once
                conn.execute("INSERT INTO files (project_id, name, category, created_at) VALUES (?, ?, 'media', ?)",
                             (self.pa.id, f"p{i}.jpg", NOW - 120 + i))
        a = status.assess(self.a.id, self.pa.id, NOW)
        self.assertNotEqual(a.activity, "busy")
        self.assertEqual(a.events_week, 1)


if __name__ == "__main__":
    unittest.main()
