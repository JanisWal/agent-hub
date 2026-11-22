"""The "For you" list of the project page: add, change, mark as done with a note, open again, delete.
All are sent with fetch (static/todos.js); afterwards only the list is swapped. Foreign or bad things are 404. Done or
deleted, an entry a role asked for lets its waiting task go on (agents.check_todos)."""
from fastapi import APIRouter, Depends, Form

from .. import agents, todos, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/projects/{project_id}/todos")
def create_todo(project_id: int, text: str = Form(""), user: users.User = Depends(api_user)):
    todo_id = todos.create(user.id, project_id, text)
    return fail(404) if todo_id is None else ok(id=todo_id)


@router.post("/todos/{todo_id}/edit")
def edit_todo(todo_id: int, text: str = Form(""), user: users.User = Depends(api_user)):
    return ok() if todos.update(user.id, todo_id, text) else fail(404)


@router.post("/todos/{todo_id}/done")
def finish_todo(todo_id: int, note: str = Form(""), user: users.User = Depends(api_user)):
    if not todos.finish(user.id, todo_id, note):
        return fail(404)
    agents.check_todos(user.id)
    return ok()


@router.post("/todos/{todo_id}/reopen")
def reopen_todo(todo_id: int, user: users.User = Depends(api_user)):
    return ok() if todos.reopen(user.id, todo_id) else fail(404)


@router.post("/todos/{todo_id}/delete")
def delete_todo(todo_id: int, user: users.User = Depends(api_user)):
    if not todos.delete(user.id, todo_id):
        return fail(404)
    agents.check_todos(user.id)
    return ok()
