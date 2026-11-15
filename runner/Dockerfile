# Image of one agent run (started by launcher.py as user 10000+id, read-only, see KONZEPT-AGENTEN.md 6a).
# Claude Code is installed in a folder every user may read: the run user has no home of its own. A run's HOME is an
# empty folder in memory (launcher._claude_env); it holds no login, only a ticket (runner/tokens.py).
FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git ripgrep python3 \
 && rm -rf /var/lib/apt/lists/*
ENV HOME=/opt/claude-install
RUN mkdir -p "$HOME" && curl -fsSL https://claude.ai/install.sh | bash \
 && chmod -R a+rX /opt/claude-install
ENV PATH="/opt/claude-install/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1
WORKDIR /work
