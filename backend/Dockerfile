FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.29 AS uv

FROM python:3.12-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:$PATH"
WORKDIR /app/backend
COPY --from=uv /uv /uvx /bin/
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
RUN uv sync --frozen --no-dev

FROM backend-base AS runtime
COPY --from=frontend-build /app/frontend/dist /app/frontend-dist
COPY backend/scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV TRAINLAB_FRONTEND_DIST=/app/frontend-dist
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]

FROM backend-base AS test
RUN uv sync --frozen --extra dev
COPY backend/tests ./tests
COPY frontend/tests/fixtures/614797758_ACTIVITY.fit /app/frontend/tests/fixtures/614797758_ACTIVITY.fit
COPY docs/api/openapi.json /app/docs/api/openapi.json
CMD ["pytest"]
