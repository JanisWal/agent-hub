"""The interface of the runner (Claude Code on the Pi, later also on the Mac).

Only the runner calls these routes, from inside the Docker network. The runner always asks (it is
never called), so a Mac runner can use the same routes with nothing but an outgoing connection.
Three safeguards, because the site itself is public:
- Requests that came through the Cloudflare tunnel (they carry `CF-Connecting-IP`) get 404.
- The runner proves itself with a token; `.env` of the web service holds only its SHA-256
  (`HUB_RUNNER_TOKEN_HASH`), and without it the whole interface is off (404).
- Wrong tokens are counted per IP like wrong passwords (`throttle.py`, own counter).
The runner passes no user: a job carries the user from the database (see agents.py).
"""
import dataclasses
import hashlib
import json
import hmac
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from .. import agents, ai_link, chat, claude_link, devices, exports, models, power, throttle, users
from ..deps import fail, ok

TOKEN_HASH_ENV = "HUB_RUNNER_TOKEN_HASH"


def runner_only(request: Request) -> None:
    """Dependency of every route below: 404 unless this is the runner with the right token."""
    expected = os.environ.get(TOKEN_HASH_ENV, "").strip().lower()
    if not expected or request.headers.get("cf-connecting-ip"):
        raise HTTPException(status_code=404)
    key = "runner:" + throttle.client_ip(request)
    if throttle.seconds_locked(key):
        raise HTTPException(status_code=429)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    digest = hashlib.sha256(token.strip().encode()).hexdigest()
    if scheme.lower() != "bearer" or not token.strip() or not hmac.compare_digest(digest, expected):
        throttle.record_failure(key)
        raise HTTPException(status_code=401)


router = APIRouter(prefix="/runner", dependencies=[Depends(runner_only)])


@router.post("/claim")
def claim(can_mac: str = Form("0")):
    job = agents.claim_next(can_mac == "1")
    return ok(job=None if job is None else dataclasses.asdict(job))


@router.post("/runs/{run_id}/finish")
def finish(run_id: int, result: str = Form(""), report: str = Form(""), tokens_in: int = Form(0),
           tokens_out: int = Form(0), seconds: int = Form(0), diff_stat: str | None = Form(None),
           diff: str | None = Form(None), tests_exit: int = Form(-1), tests: str = Form("")):
    try:
        done = agents.finish_run(run_id, result, report, tokens_in, tokens_out, seconds,
                                 change=None if diff is None else (diff_stat or "", diff),
                                 tests=(tests_exit, tests) if tests_exit >= 0 else None)
    except ValueError:
        return fail(400)   # a result that does not fit the role
    return ok() if done else fail(409)   # the run is over already, or the task has moved on


@router.get("/merges")
def merges():
    """Approved tasks whose branch the runner merges into the project's main (agents.pending_merges)."""
    return ok(merges=agents.pending_merges())


@router.post("/merges/{task_id}/done")
def merge_done(task_id: int, success: str = Form("0")):
    return ok() if agents.merge_done(task_id, success == "1") else fail(409)


@router.get("/exports")
def export_requests():
    """Requests for a ZIP of a project's code (exports.py); old ones and their files go on the way."""
    exports.sweep()
    return ok(exports=exports.pending(), limit=exports.limit())


@router.post("/exports/{export_id}")
async def export_deliver(export_id: int, request: Request):
    """The ZIP as the raw body (application/zip); an empty body: it could not be made."""
    data = await request.body()
    if not data:
        exports.fail(export_id)
        return ok()
    return ok() if exports.deliver(export_id, data) else fail(409)


@router.get("/cleanups")
def cleanups():
    """Finished tasks: the runner deletes their work folders. `wipes`: the code and work folders of deleted projects.
    The runner asks all the time, so this is also where accounts deleted long ago go for good (users.purge_deleted)."""
    users.purge_deleted()
    return ok(task_ids=agents.finished_tasks(), wipes=agents.pending_wipes())


@router.post("/cleanups/done")
def cleanup_done(kind: str = Form(""), ref: int = Form(0)):
    if kind not in agents.WIPE_KINDS:
        return fail(400)
    return ok() if agents.wipe_done(kind, ref) else fail(409)


@router.post("/chat/claim")
def chat_claim():
    """The next question of the chat window (see chat.py), or null."""
    job = chat.claim_next()
    return ok(job=None if job is None else dataclasses.asdict(job))


@router.post("/chat/{chat_id}/thoughts")
def chat_thoughts(chat_id: int, text: str = Form("")):
    """More thoughts of a question that is being answered (chat.add_thoughts)."""
    return ok() if chat.add_thoughts(chat_id, text) else fail(409)


@router.post("/chat/{chat_id}/finish")
def chat_finish(chat_id: int, success: str = Form("0"), answer: str = Form(""), tokens_in: int = Form(0),
                tokens_out: int = Form(0), tools_asked: str = Form(""),
                tools_seen: str | None = Form(None)):
    """`tools_seen`: the tools the AI's program named at its start (comma separated), missing = it named none we
    could read (toolcheck.py)."""
    tools = (_names(tools_asked), _names(tools_seen)) if isinstance(tools_seen, str) and tools_asked else None
    return ok() if chat.finish(chat_id, success == "1", answer, tokens_in, tokens_out, tools) else fail(409)


def _names(text: str) -> list[str]:
    return [n for n in (part.strip() for part in text.split(",")) if n.isidentifier() and len(n) <= 40][:60]


@router.get("/logins")
def logins():
    return ok(logins=[{"user_id": uid, "login_url": url} for uid, url in claude_link.pending_logins()])


@router.post("/logins/{user_id}/url")
def login_url(user_id: int, url: str = Form("")):
    try:
        done = claude_link.set_login_url(user_id, url)
    except ValueError:
        return fail(400)
    return ok() if done else fail(409)


@router.post("/logins/{user_id}/code")
def login_code(user_id: int):
    """Hands over the code the user typed, once; null while there is none."""
    return ok(code=claude_link.take_code(user_id))


@router.post("/logins/{user_id}/done")
def login_done(user_id: int, success: str = Form("0")):
    return ok() if claude_link.complete(user_id, success == "1") else fail(409)


@router.get("/wipes")
def wipes():
    """Users who disconnected: the runner deletes their Claude folders."""
    return ok(user_ids=claude_link.pending_wipes())


@router.get("/expired")
def expired():
    """Users whose token ran out or was refused: the runner deletes the saved token (the state stays "expired")."""
    return ok(user_ids=claude_link.expired_users())


@router.post("/wipes/{user_id}/done")
def wipe_done(user_id: int):
    return ok() if claude_link.wiped(user_id) else fail(409)


@router.post("/power/claim")
def power_claim():
    """What the owner asked for on the Pi (restart, shutdown, backup; once), or null."""
    job = power.claim_next()
    return ok(id=None if job is None else job[0], action=None if job is None else job[1])


@router.post("/wake/claim")
def wake_claim():
    """The MAC address of a device the user switched on (devices.request_wake), handed out once, or null."""
    return ok(mac=devices.claim_wake())


@router.post("/power/{request_id}/result")
def power_result(request_id: int, success: str = Form("0")):
    """How a manual backup ended."""
    return ok() if power.finish(request_id, success == "1") else fail(409)


@router.post("/logins/{user_id}/expired")
def login_expired(user_id: int):
    return ok() if claude_link.mark_expired(user_id) else fail(409)


# --- AIs with an API key (ai_link.py, Mistral): the runner fetches pasted keys once, checks them with the provider,
# keeps them encrypted and reports how it went; it deletes the keys of disconnected or deleted users.
def _key_provider(provider: str) -> None:
    if provider not in ai_link.PROVIDERS and provider not in ai_link.API_KEYS and provider not in ai_link.SLOTS:
        raise HTTPException(status_code=404)


@router.post("/keys/claim")
def keys_claim():
    """The keys users pasted, each handed over once (never stored by the hub)."""
    return ok(keys=ai_link.take_keys())


@router.post("/keys/{user_id}/{provider}/done")
def key_done(user_id: int, provider: str, success: str = Form("0")):
    _key_provider(provider)
    return ok() if ai_link.complete(user_id, provider, success == "1") else fail(409)


@router.post("/keys/{user_id}/{provider}/expired")
def key_expired(user_id: int, provider: str):
    _key_provider(provider)
    return ok() if ai_link.mark_expired(user_id, provider) else fail(409)


@router.get("/device-logins")
def device_logins():
    """ChatGPT sign-ins with a one-time code the runner has to run (ai_link.begin_login)."""
    return ok(logins=ai_link.pending_device_logins())


@router.post("/device-logins/{user_id}/{provider}/url")
def device_login_url(user_id: int, provider: str, url: str = Form(""), code: str = Form("")):
    _key_provider(provider)
    try:
        return ok() if ai_link.set_device_prompt(user_id, provider, url, code) else fail(409)
    except ValueError:
        return fail(400)


@router.post("/keys/{user_id}/{provider}/noplan")
def key_noplan(user_id: int, provider: str):
    _key_provider(provider)
    return ok() if ai_link.mark_noplan(user_id, provider) else fail(409)


@router.get("/model-checks")
def model_checks():
    """The users' AIs whose model list the runner asks for now (models.due)."""
    return ok(checks=models.due())


@router.post("/models/{user_id}/{provider}")
def model_list(user_id: int, provider: str, models_json: str = Form("", alias="models")):
    """The list the user's AI offered (raw, as the AI gave it); empty or broken = it could not be asked."""
    if provider not in models.FETCHABLE:
        return fail(404)
    try:
        raw = json.loads(models_json) if models_json else None
    except ValueError:
        raw = None
    return ok(stored=models.save(user_id, provider, raw if isinstance(raw, list) else None))


@router.get("/keys/wipes")
def key_wipes():
    return ok(wipes=[{"user_id": uid, "provider": p} for uid, p in ai_link.pending_wipes()])


@router.post("/keys/{user_id}/{provider}/wiped")
def key_wiped(user_id: int, provider: str):
    _key_provider(provider)
    return ok() if ai_link.wiped(user_id, provider) else fail(409)
