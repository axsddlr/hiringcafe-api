# syntax=docker/dockerfile:1

# uv binary is taken from the official image, so the build never bootstraps pip.
FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

# Create the runtime user up front so dependencies and sources can be written
# with the right ownership directly. A trailing `chown -R` would copy the whole
# virtualenv into a new layer (~400 MB here).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
RUN chown appuser:appuser /app

# Dependency layer: only rebuilt when the lockfile changes. uv's download cache
# is mounted, not committed, so wheels do not end up in the image.
#
# playwright is a transitive dependency of scrapling[fetchers] and is 140 MB of
# browser automation this service never touches -- only the HTTP fetcher is used.
# It is excluded from the install, and the import below fails the build rather
# than the container if a future Scrapling starts importing it eagerly.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
USER appuser
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=10001,gid=10001 \
    uv sync --frozen --no-dev --no-install-package playwright \
 && python -c "from scrapling.fetchers import Fetcher; print('scrapling HTTP fetcher importable')"

# Application layer. The GeoNames SQLite DB ships with the image so the service
# starts without a download step; the raw dump is excluded in .dockerignore.
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data/us_zips.db ./data/us_zips.db

EXPOSE 8070

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8070/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8070", "--log-level", "info"]
