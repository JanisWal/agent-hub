"""The reply format of the manager: questions, tasks and status (reply.py)."""
import unittest

from app import reply


class AskTest(unittest.TestCase):
    def test_a_choice_with_options_is_cut_out_of_the_text(self):
        got = reply.parse('Sure.\n<ask kind="choice">Relay at 12 V or 24 V?<option>12 V</option><option>24 V</option></ask>')
        self.assertEqual(got.text, "Sure.")
        self.assertEqual(got.asks, [reply.Ask("Relay at 12 V or 24 V?", "choice", "small", ["12 V", "24 V"])])

    def test_unknown_values_fall_back_and_choice_without_options_becomes_text(self):
        got = reply.parse('<ask kind="radio" size="huge">Which?</ask><ask kind="choice">Free?</ask>')
        self.assertEqual([(a.kind, a.size, a.options) for a in got.asks], [("text", "small", []), ("text", "small", [])])

    def test_text_questions_drop_their_options(self):
        got = reply.parse('<ask kind="text">Name?<option>x</option></ask>')
        self.assertEqual(got.asks[0].options, [])

    def test_many_options_or_a_long_question_open_large(self):
        many = "".join(f"<option>{i}</option>" for i in range(5))
        self.assertEqual(reply.parse(f"<ask>Pick?{many}</ask>").asks[0].size, "large")
        self.assertEqual(reply.parse("<ask>" + "x" * 400 + "</ask>").asks[0].size, "large")

    def test_limits_options_duplicates_and_count(self):
        many = "".join(f"<option>{i}</option>" for i in range(10)) + "<option>1</option><option>  </option>"
        self.assertEqual(len(reply.parse(f"<ask>Pick?{many}</ask>").asks[0].options), reply.MAX_OPTIONS)
        self.assertEqual(len(reply.parse("<ask>q</ask>" * 5).asks), reply.MAX_ASKS)
        self.assertEqual(len(reply.parse(f"<ask>{'x' * 5000}</ask>").asks[0].text), reply.MAX_QUESTION)

    def test_an_empty_question_is_dropped_but_still_cut_out(self):
        got = reply.parse("a<ask>   </ask>b")
        self.assertEqual((got.text, got.asks), ("ab", []))


class TaskTest(unittest.TestCase):
    def test_a_task_needs_a_known_kind_and_a_title(self):
        got = reply.parse(
            '<task kind="bug" title="Login  fails\nsometimes">Steps\nand criteria</task>'
            '<task kind="epic" title="x">no</task><task kind="minor">no title</task><task kind="major" title=""></task>')
        self.assertEqual(got.tasks, [reply.Task("bug", "Login fails sometimes", "Steps\nand criteria")])
        self.assertEqual(got.text, "")

    def test_limits(self):
        self.assertEqual(len(reply.parse('<task kind="bug" title="t">b</task>' * 9).tasks), reply.MAX_TASKS)
        got = reply.parse('<task kind="bug" title="' + "t" * 500 + '">' + "b" * 9000 + "</task>").tasks[0]
        self.assertEqual((len(got.title), len(got.body)), (reply.MAX_TITLE, reply.MAX_BODY))

    def test_tags_inside_attributes_do_not_parse(self):
        self.assertEqual(reply.parse('<task kind="bug" title="a<b>c">x</task>').tasks, [])


class StatusTest(unittest.TestCase):
    def test_the_last_valid_status_wins(self):
        got = reply.parse('<status level="green">fine</status> text <status level="red">broken</status><status level="blue">x</status>')
        self.assertEqual(got.status, reply.Status("red", "broken"))
        self.assertEqual(got.text, "text")

    def test_invalid_or_empty_status_is_ignored(self):
        self.assertIsNone(reply.parse('<status level="pink">x</status><status level="red"> </status>').status)
        self.assertIsNone(reply.parse("no markers at all").status)


class MixedTest(unittest.TestCase):
    def test_plain_text_and_other_markers_pass_through(self):
        text = "Hello <memory>keep</memory> <read>a.md</read> <b>"
        self.assertEqual(reply.parse(text).text, text)

    def test_control_characters_are_removed(self):
        got = reply.parse('<status level="green">ok\x00\x07 fine</status>')
        self.assertEqual(got.status.text, "ok fine")


if __name__ == "__main__":
    unittest.main()
