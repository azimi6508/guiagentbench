FROM node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e
RUN npm install --global opencode-ai@1.18.34 && opencode --version
COPY entrypoint.sh /usr/local/bin/bench-agent
COPY run-ready.cjs /usr/local/lib/bench-run-ready.cjs
RUN chmod 755 /usr/local/bin/bench-agent
USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/bench-agent"]
