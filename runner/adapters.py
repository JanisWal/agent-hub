"""One adapter per AI (KONZEPT-AGENTEN.md 9.2): how the runner starts it in a container and reads its answer.

The hub builds the same package for every AI (web/app/chat.py, web/app/runtask.py) and stores every answer itself;
an adapter only knows its program. Both programs run in a throwaway container with a ticket instead of the key:
- claude: Claude Code (runner/Dockerfile), ticket to the gateway on port 3130.
- mistral: Mistral Vibe (runner/Dockerfile.vibe), ticket to the gateway on port 3131.
Interface: `secret(runner, user_id)` (the credential the ticket stands for, or None), `route(job)` (what the ticket must
know besides: the address of the user's own AI; {} for the others), `chat_command(...)`, `brief_command(...)`,
`run_command(...)`, `parse(stdout) -> (ok, text, tokens_in, tokens_out, login_problem)`, `thought(line)`: the
thought text in one line of a chat's output while it runs ("" if the line has none; shown in the chat). `images` says whether the
model sees pictures (catalog of the hub); Claude Code looks at images and PDFs with its own Read tool, Vibe through the
tool `look` of hub_tools.py.
"""
import json
import threading

from . import codex, launcher, tokens


class Later(Exception):
    """The credential is there but could not be made ready now (its sign-in service not reachable): nothing deleted."""


class Claude:
    provider = "claude"

    def route(self, job: dict) -> dict:
        return {}   # its gateway knows its one address

    def secret(self, runner, user_id: int):
        return runner.vault.load(user_id)

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None, hub_tools=None, credential="plan"):
        return launcher.build_chat_command(chat_id=chat_id, user_id=user_id, model=model, ticket=ticket, mode=mode,
                                           effort=effort, files_dir=files_dir, code_dir=code_dir, hub_tools=hub_tools,
                                           api=credential == "api")

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None, hub_tools=None, credential="plan"):
        return launcher.build_command(run_id=run_id, user_id=user_id, model=model, work_dir=work_dir, ticket=ticket,
                                      net=net, effort=effort, files_dir=files_dir, hub_tools=hub_tools,
                                      api=credential == "api")

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None, hub_tools=None, credential="plan"):
        """A run without tools and without /work: one answer to the package (prompts.brief_run)."""
        return launcher.build_chat_command(chat_id=run_id, user_id=user_id, model=model, ticket=ticket, mode="brief",
                                           effort=effort, name=f"agent-run-{int(run_id)}", api=credential == "api")

    def parse_chat(self, stdout: str):
        return launcher.parse_chat_output(stdout)

    def thought(self, line: str) -> str:
        return launcher.claude_thought(line)

    def tools_seen(self, line: str):
        return launcher.claude_tools(line)


    parse_run = parse_chat   # agent runs stream like the chat since 22.11.2026 (launcher.build_command)


# The job of Vibe, Codex and the hub's loop for a mode of the chat (launcher.CHAT_MODES); "all" else.
CHAT_JOBS = {"apart": "chat-apart", "brief": "chat-brief", "sort": "chat-sort"}


class Mistral:
    provider = "mistral"

    def route(self, job: dict) -> dict:
        return {}

    def secret(self, runner, user_id: int):
        return runner.keys.load(user_id, "mistral")

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None, hub_tools=None, credential="plan"):
        return launcher.build_vibe_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job=CHAT_JOBS.get(mode, "chat-all"),
                                           effort=effort, files_dir=files_dir, code_dir=code_dir, images=images,
                                           hub_tools=hub_tools)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None, hub_tools=None, credential="plan"):
        return launcher.build_vibe_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="run", effort=effort, net=net, work_dir=work_dir,
                                           files_dir=files_dir, images=images, hub_tools=hub_tools)

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None, hub_tools=None, credential="plan"):
        return launcher.build_vibe_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="run-brief", effort=effort)

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat

    def thought(self, line: str) -> str:
        return launcher.vibe_thought(line)



class Custom:
    """The user's own AI: any API in the OpenAI chat format, run by the hub's tool loop (runner/hubloop.py) with the
    hub's tools (hub_tools.py). The address and the model name come with the job (`route`, from the hub's database);
    the address goes into the ticket, so the gateway (port 3132) sends the requests there and nowhere else."""
    provider = "custom"

    def secret(self, runner, user_id: int):
        return None   # the key sits at the AI's place, which only the job knows (Runner._secret, _key_name)

    def route(self, job: dict) -> dict:
        route = job.get("route") or {}
        return {"upstream": str(route.get("endpoint") or ""), "lan": route.get("lan") is True}

    def _model(self, job_route) -> str:
        return str((job_route or {}).get("remote_model") or "")

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None, hub_tools=None, credential="plan"):
        return launcher.build_hubloop_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket,
                                              job=CHAT_JOBS.get(mode, "chat-all"),
                                              files_dir=files_dir, code_dir=code_dir)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None, hub_tools=None, credential="plan"):
        return launcher.build_hubloop_command(name=f"agent-run-{int(run_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket, job="run", net=net,
                                              work_dir=work_dir, files_dir=files_dir)

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None, hub_tools=None, credential="plan"):
        return launcher.build_hubloop_command(name=f"agent-run-{int(run_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket, job="run-brief")

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat

    def thought(self, line: str) -> str:
        return launcher.vibe_thought(line)



class Codex:
    """ChatGPT through Codex with the user's ChatGPT sign-in (21.11.2026, runner/codex.py). The runner keeps the tokens
    and refreshes them here, right before a job; the run gets an auth.json with its ticket in a wrapper."""
    provider = "chatgpt"

    def __init__(self):
        self.kept: dict[int, dict] = {}     # user -> tokens of the job being started (account and plan for its files)
        self.lock = threading.Lock()

    def secret(self, runner, user_id: int):
        text = runner.keys.load(user_id, "chatgpt")
        if text is None:
            return None
        try:
            kept, changed = codex.fresh(codex.loads(text))
        except codex.Refused:
            return None                                  # OpenAI says no: the user signs in again
        except (OSError, ValueError) as error:
            raise Later(type(error).__name__) from None
        if changed:
            runner.keys.save(user_id, "chatgpt", codex.dumps(kept))
        with self.lock:
            self.kept[user_id] = kept
        return kept["access"]

    def route(self, job: dict) -> dict:
        with self.lock:
            kept = self.kept.get(int(job["user_id"]), {})
        return {"upstream": kept.get("account", "")}

    def _auth(self, ticket: str, user_id: int, credential: str = "plan") -> str:
        """The run's auth.json for the plan; "" for an API key (the ticket then goes as the key, launcher)."""
        if credential == "api":
            return ""
        with self.lock:
            kept = self.kept.get(int(user_id), {})
        return codex.run_auth(ticket, kept)

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None, hub_tools=None, credential="plan"):
        return launcher.build_codex_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id, model=model,
                                            effort=effort, auth=self._auth(ticket, user_id, credential),
                                            job=CHAT_JOBS.get(mode, "chat-all"),
                                            files_dir=files_dir, code_dir=code_dir, key_ticket=ticket if credential == "api" else "")

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None, hub_tools=None, credential="plan"):
        return launcher.build_codex_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model, effort=effort,
                                            auth=self._auth(ticket, user_id, credential), job="run", net=net,
                                            work_dir=work_dir, files_dir=files_dir,
                                            key_ticket=ticket if credential == "api" else "")

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None, hub_tools=None, credential="plan"):
        return launcher.build_codex_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model, effort=effort,
                                            auth=self._auth(ticket, user_id, credential), job="run-brief",
                                            key_ticket=ticket if credential == "api" else "")

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat

    def thought(self, line: str) -> str:
        return launcher.vibe_thought(line)



ADAPTERS = {"claude": Claude(), "mistral": Mistral(), "custom": Custom(), "chatgpt": Codex()}
