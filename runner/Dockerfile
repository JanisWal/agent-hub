# Image of one agent run (started by launcher.py as user 10000+id, read-only, see KONZEPT-AGENTEN.md 6a).
# Claude Code is installed in a folder every user may read: the run user has no home of its own. A run's HOME is an
# empty folder in memory (launcher._claude_env); it holds no login, only a ticket (runner/tokens.py).
# poppler-utils (18.11.2026): Claude Code's Read draws PDF pages with pdftoppm; without it longer PDFs can not be read.
# Node.js and npm (20.11.2026): projects in JavaScript can be run and tested (the hub runs hub-test.sh, runner/workspace.py);
# Debian's own packages, pinned to their series (a security update of the same series still builds).
FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git ripgrep python3 poppler-utils \
      "nodejs=20.19.*" "npm=9.2.0*" \
 && rm -rf /var/lib/apt/lists/* \
 && node --version | grep -q "^v20\.19\."
ENV HOME=/opt/claude-install
# Pinned (15.11.2026): a new Claude Code version is tried on a branch first (its options and output may change).
RUN mkdir -p "$HOME" && curl -fsSL https://claude.ai/install.sh | bash -s 2.1.319 \
 && chmod -R a+rX /opt/claude-install
ENV PATH="/opt/claude-install/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1
# The hub's tool loop and tools for an AI that has only an API (20.11.2026, runner/hubloop.py, runner/hub_tools.py).
COPY hubloop.py hub_tools.py /opt/hub/
WORKDIR /work
