from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Agent-Hub")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return "<h1>Agent-Hub läuft</h1>"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
