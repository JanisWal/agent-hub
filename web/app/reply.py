"""The reply format of the manager: questions, tasks and a status (KONZEPT-AGENTEN.md 9.3, 9.4, 9.5, 9.7; 15.11.2026).

Every AI writes the same markers, so nothing depends on one provider. The hub reads them strictly and cuts them out of
the text the user reads. Memory and read markers stay in memory.py; this module only knows the three new ones:

    <ask kind="choice|text" size="small|large">Question<option>Answer</option>...</ask>
    <task kind="bug|minor|major" title="...">Description and acceptance criteria</task>
    <status level="green|yellow|red">One sentence</status>

`parse` is a pure function: it knows no user, no project and no database. Whoever stores the result (a later module)
must save it under the project of the question and nowhere else. Anything that does not fit (unknown value, empty text,
too many, too long) is dropped or cut; the marker is removed from the text either way, so the user never reads raw tags.
Standard library only.
"""
import re
from dataclasses import dataclass, field

MAX_ASKS = 3
MAX_TASKS = 5
MAX_TITLE = 200
MAX_BODY = 4000
MAX_QUESTION = 1000
MAX_OPTIONS = 6
MAX_OPTION = 200
MAX_STATUS = 300
ASK_KINDS = ("choice", "text")
ASK_SIZES = ("small", "large")
TASK_KINDS = ("bug", "minor", "major")
LEVELS = ("green", "yellow", "red")
LARGE_QUESTION = 300   # a question this long opens large even if the AI said small (KONZEPT 9.4)

_ASK = re.compile(r"<ask(\s[^<>]*)?>(.*?)</ask>", re.DOTALL)
_TASK = re.compile(r"<task(\s[^<>]*)?>(.*?)</task>", re.DOTALL)
_STATUS = re.compile(r"<status(\s[^<>]*)?>(.*?)</status>", re.DOTALL)
_OPTION = re.compile(r"<option>(.*?)</option>", re.DOTALL)
_ATTR = re.compile(r"([a-z]+)=\"([^\"<>]*)\"")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Ask:
    text: str
    kind: str                # "choice" (buttons plus a free field) or "text" (free field only)
    size: str                # "small" (answered in the tile) or "large" (opens big)
    options: list[str] = field(default_factory=list)


@dataclass
class Task:
    kind: str                # "bug", "minor" or "major"
    title: str
    body: str


@dataclass
class Status:
    level: str               # "green", "yellow" or "red"
    text: str


@dataclass
class Signals:
    text: str                # the answer without these markers
    asks: list[Ask] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    status: Status | None = None   # the last valid one


def _attrs(raw: str | None) -> dict:
    return dict(_ATTR.findall(raw or ""))


def _line(value: str, limit: int) -> str:
    """One line: control characters gone, white space collapsed, cut at the limit."""
    return " ".join(_CONTROL.sub("", value).split())[:limit]


def _block(value: str, limit: int) -> str:
    """Several lines allowed; control characters gone, cut at the limit."""
    return _CONTROL.sub("", value).strip()[:limit]


def _ask(raw: str | None, inner: str) -> Ask | None:
    attrs = _attrs(raw)
    options = [o for o in (_line(o, MAX_OPTION) for o in _OPTION.findall(inner)) if o]
    text = _block(_OPTION.sub("", inner), MAX_QUESTION)
    if not text:
        return None
    options = list(dict.fromkeys(options))[:MAX_OPTIONS]
    kind = attrs.get("kind") if attrs.get("kind") in ASK_KINDS else ("choice" if options else "text")
    if kind == "choice" and not options:
        kind = "text"            # buttons without answers make no sense; the free field remains
    if kind == "text":
        options = []
    size = attrs.get("size") if attrs.get("size") in ASK_SIZES else "small"
    if len(text) > LARGE_QUESTION or len(options) > 3:
        size = "large"
    return Ask(text, kind, size, options)


def parse(answer: str) -> Signals:
    """Cut questions, tasks and the status out of an answer and read them strictly."""
    asks = [a for a in (_ask(raw, inner) for raw, inner in _ASK.findall(answer)) if a][:MAX_ASKS]
    tasks: list[Task] = []
    for raw, inner in _TASK.findall(answer):
        attrs = _attrs(raw)
        title, body = _line(attrs.get("title", ""), MAX_TITLE), _block(inner, MAX_BODY)
        if attrs.get("kind") in TASK_KINDS and title and len(tasks) < MAX_TASKS:
            tasks.append(Task(attrs["kind"], title, body))
    status = None
    for raw, inner in _STATUS.findall(answer):
        level, text = _attrs(raw).get("level"), _line(inner, MAX_STATUS)
        if level in LEVELS and text:
            status = Status(level, text)
    text = _STATUS.sub("", _TASK.sub("", _ASK.sub("", answer))).strip()
    return Signals(text, asks, tasks, status)
