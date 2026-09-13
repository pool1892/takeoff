FROM node:22-bookworm-slim AS codex
RUN npm install --global @openai/codex@0.154.0

FROM python:3.12-slim-bookworm
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && codex --version && codex app-server --help
ENV CODEX_HOME=/data/codex TAKEOFF_CLOUD_HOME=/data/suppliers PORT=8000
EXPOSE 8000
CMD ["python", "-m", "takeoff_suppliers.cloud_service"]
