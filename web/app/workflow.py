"""The chain of the agents as a pure state machine: no database, no HTTP (KONZEPT-AGENTEN.md 10; Janis, 22.11.2026).

A task walks through stages; every stage but merging belongs to one role:

    coding (programmer) -> [the project's tests, run by the hub] -> testing (tester) -> reviewing (reviewer)
        -> merging (the runner brings the branch into main) -> documenting (chef, the manager) -> done

A failed test, a failing tester or an objection of the reviewer sends the task back to coding (`returns` + 1); after a
return the whole chain runs again. There is no approval by the user: the reviewer's ok merges. A task can stand still
without leaving its stage (`hold`): "question" (a role waits for an answer of the manager or the user), "todo" (a role
waits for something only the user can do, in "For you") and "decision" (the user decides how it goes on: again, accept
as it is, or cancel). Every role is always on (Janis, 22.11.2026: no switch for tester and reviewer). Ends: done,
cancelled.
"""
from dataclasses import dataclass

ROLES = ("chef", "programmer", "tester", "reviewer")
STAGES = ("coding", "testing", "reviewing", "merging", "documenting")   # a task on its way
ENDS = ("done", "cancelled")
STAGE_ROLE = {"coding": "programmer", "testing": "tester", "reviewing": "reviewer", "documenting": "chef"}
RESULTS = {
    "programmer": ("done", "question", "blocked", "failed"),
    "tester": ("pass", "fail", "not_testable", "question", "blocked", "failed"),
    "reviewer": ("ok", "objections", "question", "blocked", "failed"),
    "chef": ("done", "failed"),
}
HOLDS = ("question", "todo", "decision")
CHOICES = ("again", "accept", "cancel")          # the user's answers to a decision
# Why a task waits for a decision (the hub's facts; the manager explains them in plain words, prompts.explain):
WHY = ("returns",   # sent back MAX_RETURNS times
       "stuck",     # the programmer was sent back and changed nothing
       "failed",    # a run failed or stopped twice in a row
       "nothing",   # the programmer says done but the task changed nothing
       "asks",      # the roles asked more than MAX_ASKS questions that hold the task
       "format",    # a role's answer had no valid result, also when asked again
       "old")       # a task from before the rebuild (22.11.2026, db.py)
MAX_RETURNS = 6
MAX_ASKS = 3


@dataclass(frozen=True)
class Step:
    stage: str              # a stage or an end
    hold: str = ""          # "" or one of HOLDS
    returns: int = 0
    manual_check: bool = False   # somebody has to check it by hand (not testable, accepted as it is)
    why: str = ""           # one of WHY when hold is "decision"


def forward(stage: str, returns: int, manual_check: bool) -> Step:
    """The stage after `stage` went well; after documenting the task is done."""
    index = STAGES.index(stage) + 1
    return Step(STAGES[index] if index < len(STAGES) else "done", "", returns, manual_check)


def back(returns: int, manual_check: bool) -> Step:
    """Back to the programmer; after MAX_RETURNS returns the user decides (the task still waits at coding)."""
    if returns + 1 > MAX_RETURNS:
        return Step("coding", "decision", returns, manual_check, "returns")
    return Step("coding", "", returns + 1, manual_check)


def decision(stage: str, returns: int, manual_check: bool, why: str) -> Step:
    if why not in WHY:
        raise ValueError("Unbekannter Grund")
    return Step(stage, "decision", returns, manual_check, why)


def after_run(stage: str, result: str, returns: int, manual_check: bool, *,
              tests: bool | None = None, changed: bool = True, stuck: bool = False) -> Step:
    """The role of `stage` reported `result` (already a valid one, RESULTS). Where does the task go?

    `tests` (programmer only): the project's tests the hub ran after him, True passed, False failed, None none.
    `changed`: the task changed something against main. `stuck`: the programmer was sent back and committed nothing.
    A failed run reaches this only when it failed twice (agents.py tries once more first)."""
    role = STAGE_ROLE.get(stage)
    if role is None:
        raise ValueError("Stufe hat keinen Agenten")
    if result not in RESULTS[role]:
        raise ValueError("Ergebnis passt nicht zur Rolle")
    if stage == "documenting":            # the change is merged already: a failed note does not undo it
        return Step("done", "", returns, manual_check)
    if result == "question":
        return Step(stage, "question", returns, manual_check)
    if result == "blocked":
        return Step(stage, "todo", returns, manual_check)
    if result == "failed":
        return decision(stage, returns, manual_check, "failed")
    if stage == "coding":
        if stuck:
            return decision(stage, returns, manual_check, "stuck")
        if not changed:
            return decision(stage, returns, manual_check, "nothing")
        if tests is False:
            return back(returns, manual_check)
        return forward(stage, returns, manual_check)
    if stage == "testing":
        if result == "fail":
            return back(returns, manual_check)
        return forward(stage, returns, manual_check or result == "not_testable")
    if result == "objections":            # reviewing
        return back(returns, manual_check)
    return forward(stage, returns, manual_check)


def after_merge(ok: bool, returns: int, manual_check: bool) -> Step:
    """The runner merged the branch into main (on to the documentation), or main had moved and conflicts (back to the
    programmer, who gets main into his branch first)."""
    if ok:
        return forward("merging", returns, manual_check)
    return back(returns, manual_check)


def after_decision(choice: str, stage: str, returns: int, manual_check: bool, changed: bool) -> Step:
    """The user's decision on a task that waits for one. again: the stage where it stands runs once more, with a fresh
    count of returns; accept: the work as it is goes into main (to be checked by hand); cancel: it is dropped."""
    if choice == "again":
        return Step(stage, "", 0, manual_check)
    if choice == "accept":
        return Step("merging" if changed else "done", "", returns, True)
    if choice == "cancel":
        return Step("cancelled", "", returns, manual_check)
    raise ValueError("Unbekannte Entscheidung")
