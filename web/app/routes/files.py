"""Files and links of the Manager view: upload in chunks, add a link, rename or move, edit text, delete, serve.

All calls are fetch() calls (answers `{"ok": ...}`); the file itself is served by GET /files/{id}.
"""
import logging
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from .. import files, users
from ..deps import api_user, error, fail, ok

router = APIRouter()
log = logging.getLogger("uvicorn.error")

# error code -> (status, text key in i18n.py)
ERRORS = {
    "bad_name": (400, "files_err_name"), "bad_url": (400, "files_err_url"), "bad_category": (400, "files_err_category"),
    "disk_full": (507, "files_err_disk_full"), "not_found": (404, "files_err_missing"),
    "too_big": (413, "files_err_too_big"), "bad_offset": (409, "files_err_offset"),
    "incomplete": (409, "files_err_offset"), "bad_type": (400, "files_err_type"),
}


def _fail(user: users.User, problem: files.FileError) -> JSONResponse:
    status, key = ERRORS.get(problem.code, (400, "files_err_name"))
    return error(user.language, key, status)


def _info(item: files.StoredFile) -> dict:
    return {"id": item.id, "name": item.name, "category": item.category, "size": item.size}


@router.post("/files/preferences")
def preferences(confirm: str = Form("1"), user: users.User = Depends(api_user)):
    """The red trash circle of the file tile: "0" = deleting a file does not ask first. Kept with the account."""
    users.set_files_confirm(user.id, confirm != "0")
    return ok()


@router.post("/projects/{project_id}/files/start")
def start_upload(project_id: int, name: str = Form(""), size: int = Form(0), user: users.User = Depends(api_user)):
    try:
        return ok(**_info(files.start_upload(user.id, project_id, name, size)))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/files/{file_id}/chunk")
async def upload_chunk(file_id: int, offset: int, request: Request, user: users.User = Depends(api_user)):
    if int(request.headers.get("content-length") or 0) > files.MAX_REQUEST:
        return _fail(user, files.FileError("too_big"))
    try:
        started = time.monotonic()
        body = await request.body()
        # How long the body took to arrive here: with the browser's own timing (window.__uploadLog) this shows on which
        # leg of the way a slow upload is slow.
        log.info("upload chunk file=%s offset=%s bytes=%s body_seconds=%.2f", file_id, offset, len(body), time.monotonic() - started)
        return ok(received=await run_in_threadpool(files.append_chunk, user.id, file_id, offset, body))
    except files.FileError as problem:
        return _fail(user, problem)


@router.get("/files/{file_id}/progress")
def upload_progress(file_id: int, user: users.User = Depends(api_user)):
    """What the server has of an unfinished upload (see files.upload_progress); the browser resumes from this."""
    found = files.upload_progress(user.id, file_id)
    return fail(404) if found is None else ok(size=found[0], block=files.BLOCK_SIZE, parts=found[1])


@router.post("/files/{file_id}/finish")
def finish_upload(file_id: int, user: users.User = Depends(api_user)):
    try:
        return ok(**_info(files.finish_upload(user.id, file_id)))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/projects/{project_id}/links")
def add_link(project_id: int, url: str = Form(""), name: str = Form(""), user: users.User = Depends(api_user)):
    try:
        return ok(**_info(files.add_link(user.id, project_id, url, name)))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/files/{file_id}")
def update(file_id: int, name: str = Form(""), url: str | None = Form(None), category: str | None = Form(None),
           user: users.User = Depends(api_user)):
    try:
        return ok(**_info(files.update(user.id, file_id, name, url, category)))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/files/{file_id}/delete")
def delete(file_id: int, user: users.User = Depends(api_user)):
    return ok() if files.delete(user.id, file_id) else fail(404)


@router.get("/files/{file_id}/text")
def read_text(file_id: int, user: users.User = Depends(api_user)):
    try:
        text = files.read_text(user.id, file_id)
    except files.FileError as problem:
        return _fail(user, problem)
    return fail(404) if text is None else ok(text=text)


@router.post("/files/{file_id}/text")
def write_text(file_id: int, text: str = Form(""), user: users.User = Depends(api_user)):
    try:
        return ok() if files.write_text(user.id, file_id, text) else fail(404)
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/files/{file_id}/thumb")
async def save_thumb(file_id: int, request: Request, user: users.User = Depends(api_user)):
    """The small preview picture, made by the browser (JPEG, a few KB)."""
    if int(request.headers.get("content-length") or 0) > files.THUMB_MAX:
        return _fail(user, files.FileError("too_big"))
    try:
        return ok() if files.save_thumb(user.id, file_id, await request.body()) else fail(404)
    except files.FileError as problem:
        return _fail(user, problem)


@router.get("/files/{file_id}/thumb")
def thumb(file_id: int, user: users.User = Depends(api_user)):
    path = files.open_thumb(user.id, file_id)
    if path is None:
        return fail(404)
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline", headers={
        "Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, max-age=86400"})


@router.get("/files/{file_id}")
def serve(file_id: int, download: int = 0, user: users.User = Depends(api_user)):
    """The file itself. Type from a fixed table, `nosniff`, and a sandbox policy so that even an SVG or HTML
    file can run nothing here; only images, video and audio are shown (for the viewer), the rest is a download,
    and `?download=1` makes any file a download."""
    found = files.open_file(user.id, file_id)
    if found is None:
        return fail(404)
    path, item = found
    media_type, inline = files.content_type(item.name)
    return FileResponse(
        path, media_type=media_type, filename=item.name,
        content_disposition_type="inline" if inline and not download else "attachment",
        headers={"Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'",
                 "Cache-Control": "private, max-age=60"},
    )
