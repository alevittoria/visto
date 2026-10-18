# Appium 3 + UiAutomator2 with adb, build-tools and a JRE. Pinned versions come
# from tools/appium (frozen lockfile) and docker/install-android-tools.sh.
FROM node:24.19.0-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Optional extra CAs (e.g. a TLS-inspecting proxy); see docker/certs/README.md.
COPY docker/certs/ /usr/local/share/ca-certificates/visto/
RUN update-ca-certificates
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

ENV ANDROID_HOME=/opt/android-sdk \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    APPIUM_HOME=/opt/appium \
    HOME=/home/node
ENV PATH=$ANDROID_HOME/platform-tools:$PATH

COPY docker/install-android-tools.sh /usr/local/bin/install-android-tools
RUN chmod 0755 /usr/local/bin/install-android-tools \
    && install-android-tools platform-tools build-tools \
    && npm install -g pnpm@11.25.0 \
    && mkdir -p /opt/appium /home/node/.android \
    && chown node:node /opt/appium /home/node/.android

USER node
WORKDIR /opt/appium
COPY --chown=node:node tools/appium/package.json tools/appium/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts --node-linker=hoisted \
    && pnpm store prune \
    && node node_modules/appium/index.js driver list --installed

COPY --chmod=0755 docker/appium-entrypoint.sh /usr/local/bin/appium-entrypoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD node -e "fetch('http://127.0.0.1:4723/status').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"
ENTRYPOINT ["/usr/local/bin/appium-entrypoint"]
