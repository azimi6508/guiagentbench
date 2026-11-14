FROM node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e AS fetch
WORKDIR /fetch
COPY runtime/codex/package.json runtime/codex/package-lock.json ./
RUN npm ci --ignore-scripts

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS agent
COPY --from=fetch /fetch/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/ /opt/codex/
COPY runtime/codex/entrypoint.py runtime/codex/mcp_stdio_client.py /opt/bench/
COPY runtime/codex/hooks/ /opt/bench/hooks/
COPY configs/codex/requirements.toml /etc/codex/requirements.toml
RUN ln -s /opt/codex/codex-resources/bwrap /usr/local/bin/bwrap && mkdir -p /session /config /auth-input /ipc /run/codex /run/home /run/control && chmod 755 /session && \
    echo '50ed828f357c655a3c82054d346cab8434f24901f14ec19b8267571bdd008b38  /opt/codex/bin/codex' | sha256sum -c -
ENV PATH=/opt/codex/bin:/usr/local/bin:/usr/bin:/bin HOME=/run/home CODEX_HOME=/run/codex PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /session
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/python", "/opt/bench/entrypoint.py"]

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS bridge
COPY runtime/codex/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && mkdir /workspace /policy /audit /ipc
COPY src/gui_agent_bench/ /opt/bench/gui_agent_bench/
ENV PYTHONPATH=/opt/bench PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "-m", "gui_agent_bench.codex_bridge"]

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS egress
COPY runtime/codex/egress_proxy.py /opt/bench/egress_proxy.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "/opt/bench/egress_proxy.py"]
