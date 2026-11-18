"""Files and links of the Manager view: upload in chunks, add a link, rename or move, edit text, delete, serve.

All calls are fetch() calls (answers `{"ok": ...}`); the file itself is served by GET /files/{id}.
"""
import logging
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.requests import ClientDisconnect

from .. import autofolders, chat, files, i18n, memory, users
from ..deps import api_user, error, fail, ok

router = APIRouter()
log = logging.getLogger("uvicorn.error")

# error code -> (status, text key in i18n.py)
ERRORS = {
    "bad_name": (400, "files_err_name"), "bad_url": (400, "files_err_url"), "bad_category": (400, "files_err_category"),
    "disk_full": (507, "files_err_disk_full"), "not_found": (404, "files_err_missing"),
    "too_big": (413, "files_err_too_big"), "bad_offset": (409, "files_err_offset"),
    "incomplete": (409, "files_err_offset"), "bad_type": (400, "files_err_type"),
    "name_taken": (409, "files_err_name_taken"),
}


def _fail(user: users.User, problem: files.FileError) -> JSONResponse:
    status, key = ERRORS.get(problem.code, (400, "files_err_name"))
    return error(user.language, key, status)


def _info(item: files.StoredFile) -> dict:
    return {"id": item.id, "name": item.name, "category": item.category, "size": item.size, "parent": item.parent_id,
            "folder": item.is_folder}


def _folder_id(value: str) -> int | None:
    """A folder number from a form ("" = none); anything else than digits counts as none."""
    return int(value) if isinstance(value, str) and value.isdigit() else None


@router.post("/files/preferences")
def preferences(confirm: str = Form("1"), user: users.User = Depends(api_user)):
    """The red trash circle of the file tile: "0" = deleting a file does not ask first. Kept with the account."""
    users.set_files_confirm(user.id, confirm != "0")
    return ok()


@router.post("/projects/{project_id}/files/check")
def check_names(project_id: int, names: list[str] = Form([]), category: str = Form(""),
                user: users.User = Depends(api_user), folder: str = Form("")):
    """Before an upload: which names exist already in the place the files go to, each with a free name (files.check_names)."""
    taken = files.check_names(user.id, project_id, names[:1000], category or None, _folder_id(folder))
    return fail(404) if taken is None else ok(taken=taken)


@router.post("/projects/{project_id}/files/start")
def start_upload(project_id: int, name: str = Form(""), size: int = Form(0), user: users.User = Depends(api_user),
                 folder: str = Form("")):
    try:
        return ok(**_info(files.start_upload(user.id, project_id, name, size, folder_id=_folder_id(folder))))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/projects/{project_id}/folders")
def create_folder(project_id: int, name: str = Form(""), category: str = Form(""), parent: str = Form(""),
                  reuse: str = Form("0"), user: users.User = Depends(api_user)):
    """A new folder (the folder circle, or one folder of an uploaded tree: reuse=1 joins one of that name)."""
    try:
        return ok(**_info(files.create_folder(user.id, project_id, category, name, _folder_id(parent), reuse == "1")))
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/projects/{project_id}/files/move")
def move(project_id: int, ids: str = Form(""), category: str = Form(""), folder: str = Form(""),
         user: users.User = Depends(api_user)):
    """Marked rows dragged onto a folder, a segment of the folder bar, a tree entry or a tab (files.move)."""
    wanted = [int(part) for part in ids.split(",")[:1000] if part.strip().isdigit()]
    try:
        return ok(moved=files.move(user.id, project_id, wanted, category or None, _folder_id(folder)))
    except files.FileError as problem:
        return _fail(user, problem)


# Structure the folders automatically (autofolders.py): ask for a plan, look at it, apply or drop it.
TIDY_REFUSED = {"wait": "tidy_err_wait", "none": "chat_err_none", "empty": "tidy_err_empty"}


@router.post("/projects/{project_id}/files/structure")
def structure_request(project_id: int, contents: str = Form("0"), user: users.User = Depends(api_user)):
    """The AI is asked for a plan (with "include contents" it may look into the files)."""
    result = autofolders.request(user.id, project_id, contents == "1")
    if result == "missing":
        return fail(404)
    return ok() if result == "queued" else error(user.language, TIDY_REFUSED[result], 409)


@router.get("/projects/{project_id}/files/structure")
def structure_state(project_id: int, user: users.User = Depends(api_user)):
    """Where the plan stands and, once answered, the tree after it (nothing is moved by looking)."""
    plan = autofolders.state(user.id, project_id)
    if plan is None:
        return fail(404)
    nodes = [{"depth": n.depth, "name": n.name, "kind": n.kind, "area": n.area, "moved": n.moved, "new": n.new}
             for n in plan.nodes]
    return ok(status=plan.status, contents=plan.contents, note=plan.note, moved=plan.moved, folders=plan.folders,
              failure=chat.failure_kind(plan.answer) if plan.status == "failed" else "", nodes=nodes)


@router.post("/projects/{project_id}/files/structure/apply")
def structure_apply(project_id: int, user: users.User = Depends(api_user)):
    moved = autofolders.apply(user.id, project_id)
    return fail(404) if moved is None else ok(moved=moved)


@router.post("/projects/{project_id}/files/structure/discard")
def structure_discard(project_id: int, user: users.User = Depends(api_user)):
    return ok() if autofolders.discard(user.id, project_id) else fail(404)


@router.post("/files/{file_id}/chunk")
async def upload_chunk(file_id: int, offset: int, request: Request, user: users.User = Depends(api_user)):
    """One run of blocks, written to disk while it arrives (files.Run). A run that breaks off keeps what came in."""
    announced = request.headers.get("content-length")
    try:
        run = await run_in_threadpool(files.Run, user.id, file_id, offset, int(announced) if announced else None)
    except ValueError:
        return _fail(user, files.FileError("bad_offset"))
    except files.FileError as problem:
        return _fail(user, problem)
    started, problem = time.monotonic(), None
    try:
        async for piece in request.stream():
            run.write(piece)
    except files.FileError as too_much:
        problem = too_much
    except ClientDisconnect:
        problem = files.FileError("bad_offset")      # nobody is listening any more; what arrived is kept below
    finally:
        received = await run_in_threadpool(run.close)
    seconds = time.monotonic() - started
    # How fast this request came in: with the browser's own timing (window.__uploadLog) it shows where an upload is slow.
    log.info("upload run file=%s offset=%s bytes=%s seconds=%.2f mb_per_s=%.2f", file_id, offset, run.written, seconds,
             run.written / 1048576 / seconds if seconds > 0 else 0)
    if problem is None and announced and run.written < int(announced):
        problem = files.FileError("bad_offset")      # the body ended before its announced end
    return _fail(user, problem) if problem else ok(received=received)


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
    """Into the trash (files.TRASH_DAYS); the trash list in the Manager view restores or deletes for good."""
    return ok() if files.delete(user.id, file_id) else fail(404)


@router.post("/files/{file_id}/restore")
def restore(file_id: int, user: users.User = Depends(api_user)):
    item = files.restore(user.id, file_id)
    return ok(name=item.name, category=item.category) if item else fail(404)


@router.post("/files/{file_id}/purge")
def purge(file_id: int, user: users.User = Depends(api_user)):
    """Delete a file in the trash for good (the page asks first)."""
    return ok() if files.purge(user.id, file_id) else fail(404)


@router.post("/projects/{project_id}/files/trash/empty")
def empty_trash(project_id: int, user: users.User = Depends(api_user)):
    return ok(deleted=files.empty_trash(user.id, project_id))


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
        return ok() if memory.write_by_user(user.id, file_id, text) else fail(404)   # a memory file keeps a version
    except files.FileError as problem:
        return _fail(user, problem)


@router.post("/files/{file_id}/thumb")
async def save_thumb(file_id: int, request: Request, user: users.User = Depends(api_user)):
    """The small preview picture, made by the browser (JPEG, a few KB)."""
    return await _save_picture(file_id, request, user, False)


@router.post("/files/{file_id}/preview")
async def save_preview(file_id: int, request: Request, user: users.User = Depends(api_user)):
    """The big preview of a TIFF, HEIC or raw picture for the viewer, made by the browser (JPEG, 2048 px)."""
    return await _save_picture(file_id, request, user, True)


async def _save_picture(file_id: int, request: Request, user: users.User, large: bool):
    if int(request.headers.get("content-length") or 0) > (files.PREVIEW_MAX if large else files.THUMB_MAX):
        return _fail(user, files.FileError("too_big"))
    try:
        return ok() if files.save_thumb(user.id, file_id, await request.body(), large) else fail(404)
    except files.FileError as problem:
        return _fail(user, problem)


@router.get("/files/{file_id}/preview")
def preview(file_id: int, user: users.User = Depends(api_user)):
    return _serve_picture(file_id, user, True)


@router.get("/files/{file_id}/thumb")
def thumb(file_id: int, user: users.User = Depends(api_user)):
    return _serve_picture(file_id, user, False)


def _serve_picture(file_id: int, user: users.User, large: bool):
    path = files.open_thumb(user.id, file_id, large)
    if path is None:
        return fail(404)
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline", headers={
        "Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, max-age=86400"})


@router.get("/projects/{project_id}/files/zip")
def download_zip(project_id: int, ids: str = "", user: users.User = Depends(api_user)):
    """Several files as one ZIP (dragging marked files out of the tile); made while it is sent (files.zip_stream)."""
    wanted = [int(part) for part in ids.split(",")[:1000] if part.strip().isdigit()]
    entries = files.zip_entries(user.id, project_id, wanted)
    if not entries:
        return fail(404)
    name = i18n.t(user.language, "files_zip_name", n=len(entries)) + ".zip"
    return StreamingResponse(files.zip_stream(entries), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename=\"files.zip\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, no-store"})


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
