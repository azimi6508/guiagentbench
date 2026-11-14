# Pinned Claude Code CLI (native linux-x64 build from the npm registry).
FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS fetch
ADD https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.323.tgz /tmp/claude.tgz
RUN echo 'd12423fbd90e7239c073e87179f6996aa69130359fa311022a49ae98f0ebcce2  /tmp/claude.tgz' | sha256sum -c - && mkdir /claude && tar --strip-components=1 -xzf /tmp/claude.tgz -C /claude package/claude && chmod 755 /claude/claude

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS agent
COPY --from=fetch /claude/claude /opt/claude/claude
COPY runtime/claude/entrypoint.py runtime/claude/guard.py runtime/claude/mcp_transport.py /opt/bench/
RUN mkdir /session /policy /ipc && chmod 755 /session
# Fixed, non-secret client configuration. The credential placeholder is set by
# the entrypoint; the real credential only exists in the separate gateway.
ENV PATH=/opt/claude:/usr/local/bin:/usr/bin:/bin HOME=/run/home TMPDIR=/run/tmp \
    CLAUDE_CONFIG_DIR=/run/home/.claude ANTHROPIC_BASE_URL=http://provider:8080 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 \
    DISABLE_ERROR_REPORTING=1 CLAUDE_CODE_MAX_RETRIES=0 ENABLE_TOOL_SEARCH=false \
    DISABLE_AUTO_COMPACT=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 MAX_MCP_OUTPUT_TOKENS=1000000 \
    MCP_TIMEOUT=30000 MCP_TOOL_TIMEOUT=120000 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /session
USER 1000:1000
ENTRYPOINT ["python", "/opt/bench/entrypoint.py"]

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS bridge
COPY runtime/codex/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && mkdir /workspace /policy /audit /ipc
COPY src/gui_agent_bench/ /opt/bench/gui_agent_bench/
ENV PYTHONPATH=/opt/bench PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "-m", "gui_agent_bench.codex_bridge"]

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS gateway
COPY runtime/claude/gateway.py /opt/bench/gateway.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "/opt/bench/gateway.py"]
