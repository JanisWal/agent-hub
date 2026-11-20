"""The tool loop for an AI that has only an API, no program of its own (Janis, 20.11.2026: every AI must be usable).
Standard library only; runs inside the run's container (image agent-hub-agent) as the run user, like Claude Code or
Mistral Vibe would.

Any API that speaks the OpenAI chat format (`POST /v1/chat/completions`: OpenRouter, Groq, DeepSeek, a local Ollama or
LM Studio, ...) works. The loop sends the package (stdin) to the model, runs the tools the model asks for (hub_tools.py)
and sends the results back, until the model answers without a tool call, or the steps or the time run out.
- Tool calls the API's own way ("tools", "tool_calls") when the model can; if the API refuses that (400), the same
  tools in plain text: <tool name="NAME">{"arg": "value"}</tool>, the result comes back as <tool-result>. A weaker model
  that can do neither still answers; it just has no tools.
- Every request goes to the egress gateway (HUB_GATEWAY, port 3132) with the run's ticket; the gateway knows the real
  address and key of the user's AI (runner/tokens.py, runner/egress.py). The run never sees either.

Environment (checked values only, launcher.build_hubloop_command): HUB_GATEWAY, HUB_KEY (the ticket), HUB_MODEL (the
model name at the user's AI), HUB_JOB (chat-all, chat-apart, chat-brief, run, run-brief), HUB_TURNS, HUB_SECONDS,
HUB_IMAGES. Output like runner/vibe_entry.py: lines {"thought": ...} and once {"outside": true} while it runs, then ONE
last line {"ok", "text", "tokens_in", "tokens_out", "outcome", "error"}.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_tools  # noqa: E402  (next to this file in the image)

# The tools per job; the rest of the job's limits come from the launcher (turns, seconds, proxy).
JOB_TOOLS = {
    "chat-all": ("look", "list_files", "read_file", "grep", "run", "fetch"),
    "chat-apart": ("look", "list_files", "read_file", "grep", "run"),
    "chat-brief": (),
    "run": ("look", "list_files", "read_file", "grep", "write_file", "edit_file", "run", "fetch"),
    "run-brief": (),
}
OUTSIDE = {"chat-all": ("fetch", "run"), "chat-apart": (), "chat-brief": (), "run": ("fetch", "run"), "run-brief": ()}
MAX_RESULT = 30000            # characters of one tool result that go back to the model
REQUEST_SECONDS = 240
_TEXT_TOOL = re.compile(r"<tool\s+name=\"([a-z_]{1,20})\">(.*?)</tool>", re.S)
TEXT_RULE = (
    "Tools: you can use these tools. To use one, answer with only <tool name=\"NAME\">{JSON arguments}</tool> (one or "
    "more); the result comes back in <tool-result>. When you have the answer, write it without any <tool>.\n")


class Stop(Exception):
    """The API refused (with the reason) or could not be reached."""

    def __init__(self, reason: str, status: int = 0):
        super().__init__(reason)
        self.status = status


def post(path: str, body: dict) -> dict:
    gateway, key = os.environ.get("HUB_GATEWAY", "http://egress:3132"), os.environ.get("HUB_KEY", "")
    request = urllib.request.Request(gateway.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the gateway is reached directly
    try:
        with opener.open(request, timeout=REQUEST_SECONDS) as answer:
            return json.load(answer)
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", "replace")
        raise Stop(f"HTTP {error.code} {detail[:300]}", error.code) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise Stop(f"not reachable: {type(error).__name__}") from None


def _result_text(content: list[dict]) -> str:
    parts = [c.get("text", "") if c.get("type") == "text" else "[a picture this model can not be shown here]"
             for c in content]
    text = "\n".join(parts)
    return text if len(text) <= MAX_RESULT else text[:MAX_RESULT] + "\n[cut]"


def use_tool(name: str, args, enabled: tuple = ()) -> str:
    try:
        if isinstance(args, str):
            args = json.loads(args or "{}")
        return _result_text(hub_tools.call(name, args, images=False, enabled=enabled))
    except hub_tools.Refused as reason:
        return f"(refused: {reason})"
    except (ValueError, TypeError):
        return "(the arguments must be a JSON object)"
    except OSError:
        return "(the tool could not do it)"


def say(data: dict) -> None:
    print(json.dumps(data), flush=True)


def loop(prompt: str, model: str, job: str, turns: int, seconds: int, clock=time.time) -> dict:
    enabled = JOB_TOOLS.get(job, ())
    tools = hub_tools.schemas(enabled)
    native = bool(tools)
    messages = [{"role": "user", "content": prompt}]
    tokens_in = tokens_out = 0
    went_out = False
    end = clock() + seconds
    for _ in range(max(1, turns)):
        if clock() > end:
            return {"ok": False, "text": "", "tokens_in": tokens_in, "tokens_out": tokens_out, "outcome": "time",
                    "error": "time limit"}
        body = {"model": model, "messages": messages}
        if native:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["inputSchema"]}} for t in tools]
        try:
            data = post("/v1/chat/completions", body)
        except Stop as stop:
            if native and stop.status in (400, 404, 422):   # this model or API can not call tools: say them as text
                native = False
                names = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
                messages[0] = {"role": "user", "content": TEXT_RULE + names + "\n\n" + prompt}
                continue
            return {"ok": False, "text": "", "tokens_in": tokens_in, "tokens_out": tokens_out, "outcome": "refused",
                    "error": str(stop)}
        usage = data.get("usage") or {}
        tokens_in += int(usage.get("prompt_tokens") or 0)
        tokens_out += int(usage.get("completion_tokens") or 0)
        message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        thought = message.get("reasoning_content") or message.get("reasoning")
        if isinstance(thought, str) and thought.strip():
            say({"thought": thought.strip()})
        text = message.get("content") if isinstance(message.get("content"), str) else ""
        calls = message.get("tool_calls") or []
        if native and calls:
            messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
            for item in calls:
                function = item.get("function") or {}
                name = function.get("name", "")
                if name in OUTSIDE.get(job, ()) and not went_out:
                    went_out = True
                    say({"outside": True})
                messages.append({"role": "tool", "tool_call_id": item.get("id", ""),
                                 "content": use_tool(name, function.get("arguments") or "{}", enabled)})
            continue
        found = _TEXT_TOOL.findall(text) if tools and not native else []
        if found:
            results = []
            for name, args in found[:5]:
                if name in OUTSIDE.get(job, ()) and not went_out:
                    went_out = True
                    say({"outside": True})
                results.append(f'<tool-result name="{name}">\n{use_tool(name, args.strip(), enabled)}\n</tool-result>')
            messages += [{"role": "assistant", "content": text}, {"role": "user", "content": "\n\n".join(results)}]
            continue
        return {"ok": bool(text.strip()), "text": text, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "outcome": "finished", "error": "" if text.strip() else "empty answer"}
    return {"ok": False, "text": "", "tokens_in": tokens_in, "tokens_out": tokens_out, "outcome": "steps",
            "error": "Too many steps"}


def main() -> int:
    model, job = os.environ.get("HUB_MODEL", ""), os.environ.get("HUB_JOB", "")
    turns, seconds = os.environ.get("HUB_TURNS", "12"), os.environ.get("HUB_SECONDS", "180")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}", model) or job not in JOB_TOOLS
            or not turns.isdigit() or not seconds.isdigit()):
        say({"ok": False, "text": "", "tokens_in": 0, "tokens_out": 0, "outcome": "usage_error", "error": "bad settings"})
        return 0
    say(loop(sys.stdin.read(), model, job, int(turns), int(seconds)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
