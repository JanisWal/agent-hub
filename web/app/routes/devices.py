"""Devices of the Manager view: create, change, delete. Sent with fetch (static/devices.js); the key is only ever
received, never sent back. Errors answer 400 with the code of devices.py in `error`, a foreign device is 404."""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse

from .. import devices, users
from ..deps import api_user, fail, ok

router = APIRouter()


def _bad(code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code}, status_code=400)


@router.post("/projects/{project_id}/devices")
def create_device(project_id: int, name: str = Form(""), hostname: str = Form(""), description: str = Form(""),
                  key: str = Form(""), user: users.User = Depends(api_user)):
    try:
        device = devices.create(user.id, project_id, name, hostname, description, key)
    except ValueError as exc:
        return _bad(str(exc))
    return fail(404) if device is None else ok(id=device.id)


@router.post("/devices/{device_id}")
def change_device(device_id: int, name: str = Form(""), hostname: str = Form(""), description: str = Form(""),
                  key: str = Form(""), remove_key: str = Form(""), user: users.User = Depends(api_user)):
    try:
        project_id = devices.update(user.id, device_id, name, hostname, description, key, remove_key == "1")
    except ValueError as exc:
        return _bad(str(exc))
    return fail(404) if project_id is None else ok()


@router.post("/devices/{device_id}/delete")
def delete_device(device_id: int, user: users.User = Depends(api_user)):
    return ok() if devices.delete(user.id, device_id) else fail(404)
