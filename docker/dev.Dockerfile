# VS Code dev container: the pinned Python/uv/Node/pnpm toolchain plus an adb
# client. Appium and the adb server run in the sibling `appium` service.
FROM node:24.19.0-bookworm-slim AS node

FROM python:3.12.10-bookworm

# Optional extra CAs (e.g. a TLS-inspecting proxy); see docker/certs/README.md.
# uv, pip and Python's ssl read SSL_CERT_FILE; Node adds NODE_EXTRA_CA_CERTS.
COPY docker/certs/ /usr/local/share/ca-certificates/visto/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /usr/local/bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g pnpm@11.25.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo unzip \
    && rm -rf /var/lib/apt/lists/*

ENV ANDROID_HOME=/opt/android-sdk
COPY docker/install-android-tools.sh /usr/local/bin/install-android-tools
# Link adb into /usr/local/bin: login shells reset PATH from /etc/profile.
RUN chmod 0755 /usr/local/bin/install-android-tools \
    && install-android-tools platform-tools \
    && ln -s $ANDROID_HOME/platform-tools/adb /usr/local/bin/adb

ARG WORKSPACE=/workspaces/visto
# Linux-only trees live in named volumes over these paths, so they never collide
# with a host checkout's own .work/.venv/dist/node_modules. Pre-creating them here
# gives the volumes the right owner on first use.
RUN useradd --create-home --uid 1000 --shell /bin/bash vscode \
    && echo 'vscode ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vscode \
    && mkdir -p $WORKSPACE/.work $WORKSPACE/backend/.venv $WORKSPACE/backend/dist \
        $WORKSPACE/frontend/node_modules /home/vscode/.cache \
    && chown -R vscode:vscode /workspaces /home/vscode/.cache

# Keep pnpm's store in the cache volume, not in the mounted workspace root.
ENV pnpm_config_store_dir=/home/vscode/.cache/pnpm-store \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

USER vscode
