"""The chain of the agents as a pure state machine: no database, no HTTP, easy to test.

A task walks through stages, each stage belongs to one role:

    coding (programmer) -> testing (tester) -> reviewing (reviewer) -> awaiting_approval (the user)
        -> documenting (documenter) -> done

A failed test or an objection of the reviewer sends the task back to coding and counts as a new
round. After MAX_ROUNDS the task goes to the user (`escalated`). Agents never talk to each other:
the hub passes on the reports (see agents.py). Terminal states: done, escalated (waits for the
user's decision), cancelled.
"""
from dataclasses import dataclass

ROLES = ("chef", "programmer", "tester", "reviewer", "documenter")
STAGES = ("coding", "testing", "reviewing", "awaiting_approval", "documenting")
STAGE_ROLE = {"coding": "programmer", "testing": "tester", "reviewing": "reviewer",
              "documenting": "documenter"}
RESULTS = {
    "programmer": ("done", "failed"),
    "tester": ("pass", "fail", "not_testable", "skipped"),
    "reviewer": ("ok", "objections"),
    "documenter": ("done", "failed"),
}
MAX_ROUNDS = 3
STRICTNESS = ("loose", "normal", "strict")


@dataclass(frozen=True)
class Step:
    status: str          # a stage, or "done" / "escalated"
    round: int
    manual_check: bool   # nobody could test it: the user has to check it by hand


def _first_enabled(stage: str, enabled: frozenset[str], manual_check: bool) -> Step:
    """Go to `stage`, skipping stages whose role the user has switched off."""
    index = STAGES.index(stage)
    while index < len(STAGES):
        name = STAGES[index]
        role = STAGE_ROLE.get(name)
        if role is None or role in enabled:
            return Step(name, 0, manual_check)   # round is filled in by the caller
        if name == "testing":
            manual_check = True                  # no tester: nothing was tested
        index += 1
    return Step("done", 0, manual_check)


def _again(round_: int, manual_check: bool) -> Step:
    """Back to the programmer, or to the user when the rounds are used up."""
    if round_ + 1 > MAX_ROUNDS:
        return Step("escalated", round_, manual_check)
    return Step("coding", round_ + 1, manual_check)


def advance(status: str, round_: int, manual_check: bool, result: str,
            enabled: frozenset[str]) -> Step:
    """The task is in stage `status`; its agent reported `result`. Where does it go next?

    `enabled` are the roles the user has switched on (the programmer is always one of them).
    Raises ValueError for a stage that has no agent or a result the role cannot give.
    """
    role = STAGE_ROLE.get(status)
    if role is None:
        raise ValueError("Stufe hat keinen Agenten")
    if result not in RESULTS[role]:
        raise ValueError("Ergebnis passt nicht zur Rolle")
    if status == "coding":
        if result == "failed":
            return Step("escalated", round_, manual_check)
        nxt = _first_enabled("testing", enabled, manual_check)
    elif status == "testing":
        if result == "fail":
            return _again(round_, manual_check)
        nxt = _first_enabled("reviewing", enabled, manual_check or result in ("not_testable", "skipped"))
    elif status == "reviewing":
        if result == "objections":
            return _again(round_, manual_check)
        nxt = _first_enabled("awaiting_approval", enabled, manual_check)
    else:  # documenting: the change is merged already, a failed note does not undo it
        return Step("done", round_, manual_check)
    return Step(nxt.status, round_, nxt.manual_check)


def after_approval(round_: int, manual_check: bool, enabled: frozenset[str]) -> Step:
    """The user approved: documenting if the documenter is on, else done."""
    nxt = _first_enabled("documenting", enabled, manual_check)
    return Step(nxt.status, round_, nxt.manual_check)


def after_rejection(manual_check: bool) -> Step:
    """The user said no (or reopened an escalated task): a fresh cycle from the programmer."""
    return Step("coding", 1, manual_check)


def test_may_be_skipped(strictness: str, kind: str) -> bool:
    """The Mac is not reachable and the task needs it: may the test be left out?

    loose skips tests of small updates and bugs, normal only of small updates, strict never
    (the task waits for the Mac). Major updates are never skipped.
    """
    if strictness not in STRICTNESS:
        raise ValueError("Unbekannte Strenge")
    return {"loose": kind in ("minor", "bug"), "normal": kind == "minor", "strict": False}[strictness]
