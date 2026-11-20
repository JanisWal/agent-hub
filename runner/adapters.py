"""One adapter per AI (KONZEPT-AGENTEN.md 9.2): how the runner starts it in a container and reads its answer.

The hub builds the same package for every AI (web/app/chat.py, web/app/runtask.py) and stores every answer itself;
an adapter only knows its program. Both programs run in a throwaway container with a ticket instead of the key:
- claude: Claude Code (runner/Dockerfile), ticket to the gateway on port 3130.
- mistral: Mistral Vibe (runner/Dockerfile.vibe), ticket to the gateway on port 3131.
Interface: `secret(runner, user_id)` (the credential the ticket stands for, or None), `route(job)` (what the ticket must
know besides: the address of the user's own AI; {} for the others), `chat_command(...)`, `brief_command(...)`,
`run_command(...)`, `parse(stdout) -> (ok, text, tokens_in, tokens_out, login_problem)`, `thought(line)`: the
thought text in one line of a chat's output while it runs ("" if the line has none; shown in the chat) and
`outside(line)`: True when the line shows the AI reading from outside (a web search or page, a shell with internet), so
the hub lets the board items of that answer wait for the user (anything read there could carry instructions). `images` says whether the
model sees pictures (catalog of the hub); Claude Code looks at images and PDFs with its own Read tool, Vibe through the
tool `look` of hub_tools.py.
"""
import json

from . import launcher


class Claude:
    provider = "claude"

    def route(self, job: dict) -> dict:
        return {}   # its gateway knows its one address

    def secret(self, runner, user_id: int):
        return runner.vault.load(user_id)

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None):
        return launcher.build_chat_command(chat_id=chat_id, user_id=user_id, model=model, ticket=ticket, mode=mode,
                                           effort=effort, files_dir=files_dir, code_dir=code_dir)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None):
        return launcher.build_command(run_id=run_id, user_id=user_id, model=model, work_dir=work_dir, ticket=ticket,
                                      net=net, effort=effort, files_dir=files_dir)

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None):
        """A run without tools and without /work: one answer to the package (prompts.brief_run)."""
        return launcher.build_chat_command(chat_id=run_id, user_id=user_id, model=model, ticket=ticket, mode="brief",
                                           effort=effort, name=f"agent-run-{int(run_id)}")

    def parse_chat(self, stdout: str):
        return launcher.parse_chat_output(stdout)

    def thought(self, line: str) -> str:
        return launcher.claude_thought(line)

    def outside(self, line: str) -> bool:
        return launcher.claude_outside(line)

    def parse_run(self, stdout: str):
        """(ok, text, tokens_in, tokens_out, login_problem) of an agent run of Claude Code."""
        try:
            data = json.loads(stdout)
            tokens_in, tokens_out = launcher.claude_tokens(data)
            text, failed = str(data.get("result", "")), bool(data.get("is_error"))
            return not failed, text, tokens_in, tokens_out, failed and launcher.parse_chat_output(stdout)[4]
        except (ValueError, AttributeError, TypeError):
            return False, "No readable answer from Claude Code.", 0, 0, False


class Mistral:
    provider = "mistral"

    def route(self, job: dict) -> dict:
        return {}

    def secret(self, runner, user_id: int):
        return runner.keys.load(user_id, "mistral")

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None):
        return launcher.build_vibe_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job={"apart": "chat-apart", "brief": "chat-brief"}.get(mode, "chat-all"),
                                           effort=effort, files_dir=files_dir, code_dir=code_dir, images=images)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None):
        return launcher.build_vibe_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="run", effort=effort, net=net, work_dir=work_dir,
                                           files_dir=files_dir, images=images)

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None):
        return launcher.build_vibe_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="run-brief", effort=effort)

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat

    def thought(self, line: str) -> str:
        return launcher.vibe_thought(line)

    def outside(self, line: str) -> bool:
        return launcher.vibe_outside(line)


class Custom:
    """The user's own AI: any API in the OpenAI chat format, run by the hub's tool loop (runner/hubloop.py) with the
    hub's tools (hub_tools.py). The address and the model name come with the job (`route`, from the hub's database);
    the address goes into the ticket, so the gateway (port 3132) sends the requests there and nowhere else."""
    provider = "custom"

    def secret(self, runner, user_id: int):
        return runner.keys.load(user_id, "custom")

    def route(self, job: dict) -> dict:
        route = job.get("route") or {}
        return {"upstream": str(route.get("endpoint") or ""), "lan": route.get("lan") is True}

    def _model(self, job_route) -> str:
        return str((job_route or {}).get("remote_model") or "")

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort, files_dir=None, code_dir=None,
                     images=False, route=None):
        return launcher.build_hubloop_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket,
                                              job={"apart": "chat-apart", "brief": "chat-brief"}.get(mode, "chat-all"),
                                              files_dir=files_dir, code_dir=code_dir)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir, files_dir=None, images=False,
                    route=None):
        return launcher.build_hubloop_command(name=f"agent-run-{int(run_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket, job="run", net=net,
                                              work_dir=work_dir, files_dir=files_dir)

    def brief_command(self, *, run_id, user_id, model, ticket, effort, route=None):
        return launcher.build_hubloop_command(name=f"agent-run-{int(run_id)}", user_id=user_id,
                                              model=self._model(route), ticket=ticket, job="run-brief")

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat

    def thought(self, line: str) -> str:
        return launcher.vibe_thought(line)

    def outside(self, line: str) -> bool:
        return launcher.vibe_outside(line)


ADAPTERS = {"claude": Claude(), "mistral": Mistral(), "custom": Custom()}
