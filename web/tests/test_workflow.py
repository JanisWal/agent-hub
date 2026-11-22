"""The chain as a pure state machine (workflow.py, KONZEPT-AGENTEN.md 10)."""
import unittest

from app import workflow
from app.workflow import Step

ALL = frozenset(workflow.ROLES)


class WorkflowTest(unittest.TestCase):
    def test_the_good_way_ends_merged_and_documented(self):
        step = workflow.after_run("coding", "done", 0, False, ALL, tests=True)
        self.assertEqual(step, Step("testing", "", 0, False))
        step = workflow.after_run("testing", "pass", 0, False, ALL)
        self.assertEqual(step.stage, "reviewing")
        step = workflow.after_run("reviewing", "ok", 0, False, ALL)
        self.assertEqual(step.stage, "merging")                       # no approval: the reviewer's ok merges
        self.assertEqual(workflow.after_merge(True, 0, False, ALL).stage, "documenting")
        self.assertEqual(workflow.after_run("documenting", "done", 0, False, ALL).stage, "done")
        self.assertEqual(workflow.after_run("documenting", "failed", 0, False, ALL).stage, "done")   # merged already

    def test_every_flaw_goes_back_to_the_programmer_and_counts(self):
        self.assertEqual(workflow.after_run("coding", "done", 2, False, ALL, tests=False), Step("coding", "", 3, False))
        self.assertEqual(workflow.after_run("testing", "fail", 0, False, ALL), Step("coding", "", 1, False))
        self.assertEqual(workflow.after_run("reviewing", "objections", 1, False, ALL), Step("coding", "", 2, False))
        self.assertEqual(workflow.after_merge(False, 1, False, ALL), Step("coding", "", 2, False))

    def test_too_many_returns_wait_for_the_users_decision(self):
        step = workflow.after_run("testing", "fail", workflow.MAX_RETURNS, False, ALL)
        self.assertEqual(step, Step("coding", "decision", workflow.MAX_RETURNS, False, "returns"))

    def test_questions_and_work_for_the_user_hold_the_stage(self):
        self.assertEqual(workflow.after_run("testing", "question", 1, False, ALL), Step("testing", "question", 1, False))
        self.assertEqual(workflow.after_run("reviewing", "blocked", 0, True, ALL), Step("reviewing", "todo", 0, True))

    def test_failed_stuck_and_unchanged_need_a_decision(self):
        self.assertEqual(workflow.after_run("coding", "failed", 0, False, ALL).why, "failed")
        self.assertEqual(workflow.after_run("coding", "done", 1, False, ALL, stuck=True).why, "stuck")
        self.assertEqual(workflow.after_run("coding", "done", 0, False, ALL, changed=False).why, "nothing")
        with self.assertRaises(ValueError):
            workflow.decision("coding", 0, False, "bored")

    def test_switched_off_roles_are_skipped(self):
        no_tester = frozenset({"programmer", "reviewer", "chef"})
        self.assertEqual(workflow.after_run("coding", "done", 0, False, no_tester), Step("reviewing", "", 0, True))
        alone = frozenset({"programmer"})
        self.assertEqual(workflow.after_run("coding", "done", 0, False, alone).stage, "merging")
        self.assertEqual(workflow.after_merge(True, 0, False, alone).stage, "done")   # no manager: no documentation

    def test_not_testable_must_be_checked_by_hand(self):
        self.assertEqual(workflow.after_run("testing", "not_testable", 0, False, ALL), Step("reviewing", "", 0, True))

    def test_bad_input_is_refused(self):
        for call in (lambda: workflow.after_run("merging", "done", 0, False, ALL),
                     lambda: workflow.after_run("coding", "pass", 0, False, ALL),
                     lambda: workflow.after_decision("approve", "coding", 0, False, True)):
            with self.assertRaises(ValueError):
                call()

    def test_the_users_decision(self):
        self.assertEqual(workflow.after_decision("again", "testing", 4, False, True), Step("testing", "", 0, False))
        self.assertEqual(workflow.after_decision("accept", "coding", 4, False, True), Step("merging", "", 4, True))
        self.assertEqual(workflow.after_decision("accept", "coding", 0, False, False).stage, "done")   # nothing to merge
        self.assertEqual(workflow.after_decision("cancel", "reviewing", 1, False, True).stage, "cancelled")


if __name__ == "__main__":
    unittest.main()
