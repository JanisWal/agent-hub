"""One adapter per AI (KONZEPT-AGENTEN.md 9.2): how the runner starts it in a container and reads its answer.

The hub builds the same package for every AI (web/app/chat.py, web/app/runtask.py) and stores every answer itself;
an adapter only knows its program. Both programs run in a throwaway container with a ticket instead of the key:
- claude: Claude Code (runner/Dockerfile), ticket to the gateway on port 3130.
- mistral: Mistral Vibe (runner/Dockerfile.vibe), ticket to the gateway on port 3131.
Interface: `secret(runner, user_id)` (the credential the ticket stands for, or None), `chat_command(...)`,
`run_command(...)` and `parse(stdout) -> (ok, text, tokens_in, tokens_out, login_problem)`.
"""
import json

from . import launcher


class Claude:
    provider = "claude"

    def secret(self, runner, user_id: int):
        return runner.vault.load(user_id)

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort):
        return launcher.build_chat_command(chat_id=chat_id, user_id=user_id, model=model, ticket=ticket, mode=mode,
                                           effort=effort)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir):
        return launcher.build_command(run_id=run_id, user_id=user_id, model=model, work_dir=work_dir, ticket=ticket,
                                      net=net, effort=effort)

    def parse_chat(self, stdout: str):
        return launcher.parse_chat_output(stdout)

    def parse_run(self, stdout: str):
        """(ok, text, tokens_in, tokens_out, login_problem) of an agent run of Claude Code."""
        try:
            data = json.loads(stdout)
            usage = data.get("usage") or {}
            tokens_in = sum(int(usage.get(k) or 0) for k in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            text, failed = str(data.get("result", "")), bool(data.get("is_error"))
            return not failed, text, tokens_in, int(usage.get("output_tokens") or 0), \
                failed and launcher.parse_chat_output(stdout)[4]
        except (ValueError, AttributeError, TypeError):
            return False, "No readable answer from Claude Code.", 0, 0, False


class Mistral:
    provider = "mistral"

    def secret(self, runner, user_id: int):
        return runner.keys.load(user_id, "mistral")

    def chat_command(self, *, chat_id, user_id, model, ticket, mode, effort):
        return launcher.build_vibe_command(name=f"agent-chat-{int(chat_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="chat-apart" if mode == "apart" else "chat-all",
                                           effort=effort)

    def run_command(self, *, run_id, user_id, model, ticket, net, effort, work_dir):
        return launcher.build_vibe_command(name=f"agent-run-{int(run_id)}", user_id=user_id, model=model,
                                           ticket=ticket, job="run", effort=effort, net=net, work_dir=work_dir)

    def parse_chat(self, stdout: str):
        return launcher.parse_vibe(stdout)

    parse_run = parse_chat


ADAPTERS = {"claude": Claude(), "mistral": Mistral()}
