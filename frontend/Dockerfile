# Frontend Dockerfile
# Supports two targets:
#   --target dev   — install deps only, run `pnpm dev` at container start
#   --target prod  -- prebuild once, start Node directly (default target)

ARG PNPM_STORE_PATH=/root/.local/share/pnpm/store
ARG NPM_REGISTRY

# ── Base: shared setup ────────────────────────────────────────────────────────
FROM node:22-alpine AS base
ARG PNPM_STORE_PATH
ARG NPM_REGISTRY
# Configure corepack registry before installing pnpm so the download itself
# succeeds in restricted networks (COREPACK_NPM_REGISTRY controls where
# corepack fetches package managers from).
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      export COREPACK_NPM_REGISTRY="${NPM_REGISTRY}"; \
    fi && \
    corepack enable && corepack install -g pnpm@10.26.2
RUN pnpm config set store-dir ${PNPM_STORE_PATH}
# Optionally override npm registry for restricted networks (e.g. NPM_REGISTRY=https://registry.npmmirror.com)
RUN if [ -n "${NPM_REGISTRY}" ]; then pnpm config set registry "${NPM_REGISTRY}"; fi
WORKDIR /app
COPY frontend ./frontend

# ── Dev: install only, CMD is overridden by docker-compose ───────────────────
FROM base AS dev
RUN cd /app/frontend && pnpm install --frozen-lockfile
EXPOSE 3000

# ── Builder: install + compile Next.js ───────────────────────────────────────
FROM base AS builder
RUN cd /app/frontend && pnpm install --frozen-lockfile
# Skip env validation — runtime vars are injected by nginx/container
# App version stamp for the About page. Nightly CI passes
# APP_VERSION=<base>-nightly.<date>-<sha>; release/local builds leave it empty
# and the frontend falls back to package.json's version.
ARG APP_VERSION=""
ENV NEXT_PUBLIC_APP_VERSION=$APP_VERSION
RUN cd /app/frontend && SKIP_ENV_VALIDATION=1 pnpm build

# ── Prod: minimal runtime with pre-built output ───────────────────────────────
FROM node:22-alpine AS prod
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/frontend
COPY --from=builder /app/frontend ./
EXPOSE 3000
# Keep compilation/package downloads out of startup and let Node receive SIGTERM.
# Local Compose overrides must not replace this with `build && start`.
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
