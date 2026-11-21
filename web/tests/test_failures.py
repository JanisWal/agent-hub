"""Why an AI failed and what happens then (Janis, 21.11.2026): the real messages of the programs, the next AI for chat
and runs, a used-up AI resting at the end of the order."""
import os
import tempfile
import unittest

from app import agents, ai_link, aichoice, board, chat, claude_link, db, failures, projects, serversettings, statusnote
from app import users

REAL = {
    "limit": ("You've hit your 5-hour limit · resets 1:10pm (UTC) (exit code 1)",
              "Claude AI usage limit reached|1795261582",
              "You've hit your weekly limit · resets Mon 9am",
              "Your organization is out of extra usage",
              "You've hit your usage limit. Upgrade to Pro or try again in 2 days 4 hours.",
              "unexpected status 429 Too Many Requests: Rate limit reached for gpt-6",
              "API error 429: Requests rate limit exceeded",
              "Credit balance is too low to access the Anthropic API"),
    "auth": ("Invalid API key · Please run /login",
             "OAuth token has expired. Please obtain a new token or refresh your existing token.",
             "401 Unauthorized: Incorrect API key provided",
             "Not logged in: no saved credential. Please run /login"),
    "plan": ("The AI's program stopped (plan): unexpected status 403",),
    "server": ("Server: the saved credential can not be read",),
    "timeout": ("Timeout: no answer in time.",),
    "other": ("The tests in calc.test.js failed: 3 of 13", "RESULT: failed\nThe build broke on line 12"),
}


class KindTest(unittest.TestCase):
    def test_the_real_messages(self):
        for kind, texts in REAL.items():
            for text in texts:
                self.assertEqual(failures.kind(text), kind, text)
        self.assertEqual(chat.failure_kind(REAL["limit"][0]), "limit")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        ai_link._keys.clear()
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        self.assertTrue(ai_link.begin_login(self.a.id, "chatgpt"))
        ai_link.set_device_prompt(self.a.id, "chatgpt", "https://auth.openai.com/codex/device", "AB12-CDE34")
        self.assertTrue(ai_link.complete(self.a.id, "chatgpt", True))
        aichoice.set_default(self.a.id, "claude")

    def tearDown(self):
        self.tmp.cleanup()


class OrderTest(Base):
    """The order arranges itself (Janis, 21.11.2026): the standard, the one before it, the other connected ones, then
    the ones that are not connected; nobody moves it by hand."""

    def test_the_standard_before_moves_to_the_second_place(self):
        ai_link.submit_key(self.a.id, "mistral", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6")
        ai_link.take_keys()
        ai_link.complete(self.a.id, "mistral", True)
        self.assertEqual(aichoice.ranked(self.a.id), ["claude", "mistral", "chatgpt"])   # catalog order after the first
        aichoice.set_default(self.a.id, "chatgpt")
        self.assertEqual(aichoice.ranked(self.a.id), ["chatgpt", "claude", "mistral"])
        aichoice.set_default(self.a.id, "mistral")
        self.assertEqual(aichoice.ranked(self.a.id), ["mistral", "chatgpt", "claude"])
        with db.connect() as conn:
            self.assertEqual(aichoice.order_in(conn, self.a.id), ["mistral", "chatgpt", "claude"])   # the fallback too

    def test_nothing_unconnected_between_connected_ones(self):
        from app import ui
        aichoice.set_default(self.a.id, "chatgpt")
        page = ui.settings_bar(self.a)
        chatgpt, claude, mistral = (page.index(x) for x in ('id="key-row-chatgpt"', 'id="claude-row"', 'id="key-row-mistral"'))
        self.assertLess(chatgpt, claude)                                         # the standard on top, the one before
        self.assertLess(claude, mistral)                                         # Mistral is not connected: after them


class ChatTest(Base):
    def test_a_used_up_claude_hands_the_question_to_chatgpt_and_rests(self):
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual(job.provider, "claude")
        chat.finish(job.chat_id, False, REAL["limit"][0], 0, 0)
        job = chat.claim_next()
        self.assertEqual(job.provider, "chatgpt")                            # the same question, the next AI
        chat.finish(job.chat_id, True, "Hi")
        with db.connect() as conn:
            self.assertTrue(aichoice.resting(conn, self.a.id, "claude"))
            self.assertEqual(aichoice.order_in(conn, self.a.id), ["chatgpt", "claude"])
        chat.send(self.a.id, self.pa.id, "Noch eine Frage")                  # asked of the standard, Claude ...
        self.assertEqual(chat.claim_next().provider, "chatgpt")              # ... but it rests: ChatGPT answers

    def test_no_rest_when_the_owner_turned_it_off(self):
        serversettings.set_choice("ai_rest", 0, serversettings.AI_REST)
        with db.connect() as conn:
            aichoice.rest(conn, self.a.id, "claude")
            self.assertFalse(aichoice.resting(conn, self.a.id, "claude"))

    def test_an_ordinary_failure_does_not_switch(self):
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        chat.finish(job.chat_id, False, "The model said something odd", 0, 0)
        self.assertIsNone(chat.claim_next())


class RunTest(Base):
    def start(self):
        item = board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        agents.start_item(self.a.id, item.id)
        return agents.claim_next(can_mac=False)

    def test_a_run_goes_on_with_the_next_ai_and_never_round_in_circles(self):
        run = self.start()
        self.assertEqual(run.provider, "claude")
        self.assertTrue(agents.finish_run(run.run_id, "failed", REAL["limit"][0]))
        again = agents.claim_next(can_mac=False)
        self.assertEqual((again.run_id, again.provider), (run.run_id, "chatgpt"))
        self.assertTrue(agents.finish_run(again.run_id, "failed", REAL["limit"][4]))   # ChatGPT is used up too
        self.assertIsNone(agents.claim_next(can_mac=False))                  # no third try: the run failed
        with db.connect() as conn:
            row = conn.execute("SELECT status, tried FROM agent_runs WHERE id = ?", (run.run_id,)).fetchone()
        self.assertEqual(row["tried"], "claude")
        self.assertNotEqual(row["status"], "queued")

    def test_a_failure_of_the_work_is_no_reason_to_switch(self):
        run = self.start()
        agents.finish_run(run.run_id, "failed", REAL["other"][0])
        with db.connect() as conn:
            self.assertFalse(aichoice.resting(conn, self.a.id, "claude"))
            row = conn.execute("SELECT provider, tried FROM agent_runs WHERE id = ?", (run.run_id,)).fetchone()
        self.assertEqual((row["provider"], row["tried"]), ("claude", ""))


if __name__ == "__main__":
    unittest.main()
