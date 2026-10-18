#!/bin/bash
# Dev container postStartCommand: start the backend (8000) and the Vite console
# (5173) in the background, detached from the calling exec session. Idempotent:
# a port that already accepts connections is left alone. Logs: .work/dev-logs/.
# The script waits until each port listens: VS Code runs this through a TTY exec
# session, and a Node process still starting when that session closes is killed
# (Node resets the SIGHUP disposition nohup set), so returning early loses Vite.
set -eu

cd /workspaces/visto
log_dir=.work/dev-logs
mkdir -p "$log_dir"

listening() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

start() {
    local name=$1 port=$2
    shift 2
    if listening "$port"; then
        echo "$name already listening on 127.0.0.1:$port"
        return
    fi
    setsid nohup "$@" >"$log_dir/$name.log" 2>&1 </dev/null &
    local pid=$! waited=0
    echo "$name starting on 127.0.0.1:$port (log: $log_dir/$name.log)"
    until listening "$port"; do
        if ! kill -0 "$pid" 2>/dev/null || [ "$waited" -ge 60 ]; then
            echo "$name did not start listening on 127.0.0.1:$port; log tail:" >&2
            tail -n 20 "$log_dir/$name.log" >&2
            return 1
        fi
        sleep 0.5
        waited=$((waited + 1))
    done
    echo "$name listening on 127.0.0.1:$port"
}

start backend 8000 uv run --project backend --locked --no-sync python -m uvicorn \
    visto.composition:create_app --factory --host 127.0.0.1 --port 8000
# The Windows bind mount sends no file events; Vite polls instead (vite.config.ts).
export VISTO_VITE_POLL=1
start frontend 5173 pnpm --dir frontend dev
