#!/bin/sh
# Start the adb server and Appium on loopback. The backend shares the network
# namespace, so both stay reachable only as 127.0.0.1 from the backend container.
set -eu

# A server spawned by the backend's adb client (e.g. while this container was
# restarting) cannot see USB devices; replace it with one owned here.
adb kill-server >/dev/null 2>&1 || true
adb start-server

# Network adb targets (host:port): ADB_CONNECT (comma or space separated) plus the
# first field of each line in $TARGETS_FILE, which scripts/connect-device.ps1
# maintains in the adb-keys volume. A background loop reconnects any target that
# is not attached, so devices come back after container restarts or Wi-Fi drops.
TARGETS_FILE="$HOME/.android/connect-targets"

targets() {
    printf '%s\n' "${ADB_CONNECT:-}" | tr ', ' '\n\n'
    [ -f "$TARGETS_FILE" ] && cut -d' ' -f1 "$TARGETS_FILE"
    return 0
}

# Targets that are online or waiting for authorization on the phone are left
# alone; missing or offline ones are dropped and connected again.
reconnect_loop() {
    while :; do
        attached=$(adb devices 2>/dev/null | awk 'NR > 1 && ($2 == "device" || $2 == "unauthorized") { print $1 }' || true)
        for target in $(targets | sort -u); do
            if ! printf '%s\n' "$attached" | grep -qxF "$target"; then
                adb disconnect "$target" >/dev/null 2>&1 || true
                adb connect "$target" >/dev/null 2>&1 || true
            fi
        done
        sleep "${ADB_RECONNECT_SECONDS:-15}"
    done
}
reconnect_loop &

exec node /opt/appium/node_modules/appium/index.js \
    --address 127.0.0.1 --port 4723 --log-level "${APPIUM_LOG_LEVEL:-warn}"
