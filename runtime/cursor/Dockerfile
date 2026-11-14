FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS fetch
ADD https://downloads.cursor.com/lab/2026.10.22-27dcf5f/linux/x64/agent-cli-package.tar.gz /tmp/cursor.tar.gz
RUN echo '85296944e4600a83c4b764f578d1502bf9c416db200d33a593e8f3ecabfdc294  /tmp/cursor.tar.gz' | sha256sum -c - && mkdir /cursor && tar --strip-components=1 -xzf /tmp/cursor.tar.gz -C /cursor

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS agent
COPY --from=fetch /cursor/ /opt/cursor/
COPY runtime/cursor/entrypoint.py runtime/cursor/guard.py /opt/bench/
COPY runtime/cursor/mcp_transport.py /opt/bench/mcp_transport.py
RUN mkdir /session /policy /ipc && chmod 755 /session
ENV PATH=/opt/cursor:/usr/local/bin:/usr/bin:/bin HOME=/run/home XDG_CONFIG_HOME=/run/xdg CURSOR_CONFIG_DIR=/run/home/.cursor PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
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
COPY runtime/cursor/gateway.py /opt/bench/gateway.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "/opt/bench/gateway.py"]
