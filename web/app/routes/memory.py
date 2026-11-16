"""Earlier versions of the memory files (archive of the Manager view): read one, put one back. Foreign ones are 404."""
from fastapi import APIRouter, Depends

from .. import memory, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.get("/memory/versions/{version_id}")
def version_text(version_id: int, user: users.User = Depends(api_user)):
    text = memory.version_text(user.id, version_id)
    return fail(404) if text is None else ok(text=text)


@router.post("/memory/versions/{version_id}/restore")
def version_restore(version_id: int, user: users.User = Depends(api_user)):
    return fail(404) if memory.restore(user.id, version_id) is None else ok()
