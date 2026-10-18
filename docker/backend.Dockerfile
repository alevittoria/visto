# FastAPI backend. The project is installed editable from /app/backend so its
# repository-relative defaults resolve to /app/.work (volume) and /app/.env.
FROM python:3.12.10-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Optional extra CAs (e.g. a TLS-inspecting proxy); see docker/certs/README.md.
# uv, curl and Python's ssl (provider clients included) read SSL_CERT_FILE.
COPY docker/certs/ /usr/local/share/ca-certificates/visto/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

ENV ANDROID_HOME=/opt/android-sdk
COPY docker/install-android-tools.sh /usr/local/bin/install-android-tools
# adb client only (device inventory); the server runs in the Appium container.
RUN chmod 0755 /usr/local/bin/install-android-tools && install-android-tools platform-tools \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/.work && chown app:app /app/.work

ENV PATH=/opt/venv/bin:$ANDROID_HOME/platform-tools:$PATH \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

# Repository root: CLI defaults (.work/runs, .env, .work/device-leases) then match
# the web service's paths, so both share history, key and device leases.
WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
# 0.0.0.0 inside the private compose network only; the host reaches it via `web`.
CMD ["uvicorn", "visto.composition:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
