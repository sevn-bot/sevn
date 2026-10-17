# Multi-stage image: node:22 builds the SPA, then uv installs the host on
# python:3.13-slim. The server runs as the non-root user sevn (uid 10001).
#
# SEVN_ALLOWED_HOSTS (D8): comma-separated Host values the Origin/Host guard
# accepts in addition to 127.0.0.1:<port>, localhost:<port>, and [::1]:<port>.
# /health is not guarded. Set this before clients use /ws or /auth through a
# published port, for example:
#   docker run --rm -p 8787:8787 -e SEVN_ALLOWED_HOSTS=127.0.0.1:8787 sevn:dev

FROM node:22 AS web

WORKDIR /src/web

RUN npm install -g pnpm@11.8.0

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/tsconfig.json web/tsconfig.app.json web/tsconfig.node.json web/vite.config.ts web/index.html ./
COPY web/src ./src
RUN pnpm run build

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sevn \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/sevn sevn \
    && mkdir -p /data \
    && chown sevn:sevn /data

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
ENV PATH="/app/.venv/bin:${PATH}"
ENV SEVN_HOME=/data

COPY pyproject.toml uv.lock ./
COPY host/pyproject.toml host/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --package sevn

COPY host/alembic.ini host/alembic.ini
COPY host/src host/src
COPY --from=web /src/web/dist host/src/sevn/_web
RUN uv sync --frozen --no-dev --package sevn \
    && chown -R sevn:sevn /app

VOLUME /data
EXPOSE 8787

USER sevn

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8787/health || exit 1

CMD ["sevn", "serve", "--host", "0.0.0.0", "--port", "8787", "--allow-remote-bind"]
