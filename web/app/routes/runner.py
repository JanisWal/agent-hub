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
import hmac
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from .. import agents, chat, claude_link, throttle
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
           tokens_out: int = Form(0), seconds: int = Form(0)):
    try:
        done = agents.finish_run(run_id, result, report, tokens_in, tokens_out, seconds)
    except ValueError:
        return fail(400)   # a result that does not fit the role
    return ok() if done else fail(409)   # the run is over already, or the task has moved on


@router.post("/chat/claim")
def chat_claim():
    """TEMPORARY (see chat.py): the next question of the test chat, or null."""
    job = chat.claim_next()
    return ok(job=None if job is None else dataclasses.asdict(job))


@router.post("/chat/{chat_id}/finish")
def chat_finish(chat_id: int, success: str = Form("0"), answer: str = Form(""), tokens_in: int = Form(0),
                tokens_out: int = Form(0)):
    return ok() if chat.finish(chat_id, success == "1", answer, tokens_in, tokens_out) else fail(409)


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


@router.post("/wipes/{user_id}/done")
def wipe_done(user_id: int):
    return ok() if claude_link.wiped(user_id) else fail(409)


@router.post("/logins/{user_id}/expired")
def login_expired(user_id: int):
    return ok() if claude_link.mark_expired(user_id) else fail(409)
