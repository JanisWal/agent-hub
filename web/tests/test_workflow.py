"""The chain of the agents (workflow.py): every transition, without a database."""
import unittest

from app import workflow as w

ALL = frozenset(w.ROLES)


class AdvanceTest(unittest.TestCase):
    def test_happy_path(self):
        step = w.advance("coding", 1, False, "done", ALL)
        self.assertEqual(step, w.Step("testing", 1, False))
        step = w.advance("testing", 1, False, "pass", ALL)
        self.assertEqual(step, w.Step("reviewing", 1, False))
        step = w.advance("reviewing", 1, False, "ok", ALL)
        self.assertEqual(step, w.Step("awaiting_approval", 1, False))
        self.assertEqual(w.after_approval(1, False, ALL), w.Step("documenting", 1, False))
        self.assertEqual(w.advance("documenting", 1, False, "done", ALL).status, "done")

    def test_failed_test_and_objection_go_back_as_a_new_round(self):
        self.assertEqual(w.advance("testing", 1, False, "fail", ALL), w.Step("coding", 2, False))
        self.assertEqual(w.advance("reviewing", 2, False, "objections", ALL), w.Step("coding", 3, False))

    def test_after_three_rounds_the_task_goes_to_the_user(self):
        self.assertEqual(w.advance("testing", 3, False, "fail", ALL).status, "escalated")
        self.assertEqual(w.advance("reviewing", 3, False, "objections", ALL).status, "escalated")

    def test_a_failed_agent_goes_to_the_user(self):
        for stage in ("coding", "testing", "reviewing"):
            self.assertEqual(w.advance(stage, 1, False, "failed", ALL).status, "escalated", stage)
        self.assertEqual(w.advance("documenting", 1, False, "failed", ALL).status, "done")

    def test_not_testable_continues_but_marks_a_manual_check(self):
        for result in ("not_testable", "skipped"):
            step = w.advance("testing", 1, False, result, ALL)
            self.assertEqual((step.status, step.manual_check), ("reviewing", True))
        # and the mark is never lost on the way
        self.assertTrue(w.advance("reviewing", 1, True, "ok", ALL).manual_check)

    def test_switched_off_roles_are_skipped(self):
        no_tester = ALL - {"tester"}
        step = w.advance("coding", 1, False, "done", no_tester)
        self.assertEqual((step.status, step.manual_check), ("reviewing", True))  # nothing was tested
        no_review = ALL - {"reviewer"}
        self.assertEqual(w.advance("testing", 1, False, "pass", no_review).status, "awaiting_approval")
        self.assertEqual(w.after_approval(1, False, ALL - {"chef"}).status, "done")
        bare = frozenset({"programmer"})
        self.assertEqual(w.advance("coding", 1, False, "done", bare).status, "awaiting_approval")

    def test_rejection_starts_a_fresh_cycle(self):
        self.assertEqual(w.after_rejection(True), w.Step("coding", 1, True))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            w.advance("awaiting_approval", 1, False, "ok", ALL)   # the user's own stage
        with self.assertRaises(ValueError):
            w.advance("coding", 1, False, "pass", ALL)            # a tester result for the programmer
        with self.assertRaises(ValueError):
            w.advance("done", 1, False, "done", ALL)

    def test_skipping_a_test_without_the_mac(self):
        self.assertFalse(any(w.test_may_be_skipped("strict", k) for k in ("bug", "minor", "major")))
        self.assertTrue(w.test_may_be_skipped("normal", "minor"))
        self.assertFalse(w.test_may_be_skipped("normal", "bug"))
        self.assertTrue(w.test_may_be_skipped("loose", "bug"))
        self.assertFalse(w.test_may_be_skipped("loose", "major"))
        with self.assertRaises(ValueError):
            w.test_may_be_skipped("wild", "bug")


if __name__ == "__main__":
    unittest.main()
