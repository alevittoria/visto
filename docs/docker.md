# Docker and dev container

The whole tool runs from Docker with no host Python, Node, Appium, JDK or Android
SDK. Only Docker with Compose v2 (or Docker Desktop) is needed.
A VS Code dev container provides the same pinned toolchain for development.

## Services

| Service | Image | Role |
|---|---|---|
| `net` | `alpine:3.22` | Owns the network namespace shared by `backend` and `appium` |
| `appium` | `docker/appium.Dockerfile` | adb server, Appium 3.8.0 + UiAutomator2 8.7.0, JRE, build-tools |
| `backend` | `docker/backend.Dockerfile` | FastAPI API, SQLite history, screenshots, adb client |
| `web` | `docker/web.Dockerfile` | Production React build behind nginx, `/api` proxied to `backend` |

`backend` and `appium` join the `net` service's network namespace (the pod
pattern, `network_mode: service:net`). The backend therefore reaches Appium at
`127.0.0.1:4723` and the adb server at `127.0.0.1:5037`, keeping the runner's
loopback-only Appium policy unchanged, and either service can be rebuilt or
recreated alone. Neither port is published to the host; only the console is, on
`127.0.0.1:8080`. The adb server must belong to `appium` (which owns USB devices):
`backend` starts after it, and the Appium entrypoint replaces any server the
backend's adb client may have spawned while `appium` was restarting.

Pinned inputs: Python 3.12.10, uv 0.11.32, Node 24.19.0, pnpm 11.25.0, nginx 1.30,
Alpine 3.22, Android platform-tools 37.0.1 and build-tools 37.0.0. The Android archives are
downloaded from Google's SDK repository and checked against the SHA-1 published in
its manifest (`docker/install-android-tools.sh`). They are distributed under the
Android SDK license. Application dependencies come from the frozen lockfiles.

Google publishes Linux platform-tools for x86_64 only. The Android-related images
are built for `linux/amd64` and run emulated on arm64 hosts (Apple Silicon).

## Start the stack

Behind a TLS-inspecting proxy, image builds fail with curl exit code 60 or npm
certificate errors. Export the proxy's root CA in PEM format to
`docker/certs/<name>.crt` (git-ignored) and rebuild; every image then trusts it
for curl, apt, npm/pnpm, uv and Python. On macOS, for example:
`security find-certificate -a -c "<CA common name>" -p
/Library/Keychains/System.keychain > docker/certs/proxy-ca.crt`.

From the repository root:

```sh
cp .env.example .env        # then set OPENAI_API_KEY (an empty key is allowed)
docker compose up --build -d
```

Open <http://localhost:8080>. `.env` must exist: it is bind-mounted read-only into
the backend, which reads the key itself. The key is never copied into an image
(`.dockerignore` excludes `.env`) or into the container environment. Use
`VISTO_WEB_PORT=9090 docker compose up -d` for another host port.

Open the console as `localhost` or `127.0.0.1`. The backend refuses console writes
whose Host is not loopback; publishing the port on another interface does not make
remote control work, by design.

Stop with `docker compose down`. Run history, screenshots and device leases live in
the `work` volume and survive restarts; `docker compose down -v` deletes them along
with the adb authorization key. Screenshots may contain private data: treat the
volume as private.

## Connect a device

The adb server runs in the `appium` container, so the device must be visible from
there. Check with `docker compose exec appium adb devices` or the console's device
Refresh button.

### USB phone on a Windows or macOS host: console Refresh

Docker Desktop on Windows and macOS cannot pass USB devices to containers, but it
forwards `host.docker.internal` to the host's loopback, where the host adb server
owns the phone. With the phone attached by USB, authorized for the host adb and on
the same Wi-Fi as the computer, press **Refresh** next to the device list
(`POST /api/devices/refresh`). The backend then, with fixed commands only:

1. lists the host server's USB devices (`adb -H host.docker.internal -P 5037 devices -l`);
2. reads each authorized device's `wlan0` IPv4 address;
3. tries `adb connect <ip>:5555` from the container server; only if that does not
   attach does it run `adb tcpip 5555` on the host server (which restarts adbd on
   the phone, at most once per device per refresh) and connect again.

The first time, the phone shows the USB debugging prompt for the container's adb
key: allow it ("Always allow") and press Refresh again. Problems (host adb not
running, no Wi-Fi address, connection refused) appear as notes under the list.
The host adb server must be running (`adb start-server`, or any host adb command).
Opening the console (`GET /api/devices`) only lists; it never connects or switches
devices. Refresh skips the bridge while a run is active, because `adb tcpip`
restarts adbd on the phone.

`VISTO_HOST_ADB` (default `host.docker.internal:5037` in both compose files)
selects the host server; set it empty to disable the bridge. `compose.usb.yaml`
(Linux USB passthrough) disables it.

### USB phone without the console: `scripts/connect-device.ps1`

The same switch from a host PowerShell, which also records the target so the
`appium` container keeps reconnecting it every 15 seconds. With the phone on USB
(authorized for the host adb) and on the same Wi-Fi as the computer, run from the
repository on the host:

```powershell
.\scripts\connect-device.ps1            # -Serial <usb-serial> if several are attached
```

It reads the phone's Wi-Fi address, switches it to adb over TCP (`adb tcpip
5555`), connects from the running `appium` container (dev container or full
stack) and records the target in `connect-targets` in the `adb-keys` volume. The
first time, allow USB debugging on the phone ("Always allow"). From then on the
container reconnects recorded targets every 15 seconds (`ADB_RECONNECT_SECONDS`),
including after container restarts or rebuilds. Rerun the script after the phone
reboots (TCP mode is lost) or its IP address changes.

The phone authorizes the container's adb key, stored in the `adb-keys` volume.
Rebuilding keeps the volume, so no new prompt. A new prompt appears once for a new
volume: another computer, `docker compose down -v`, or the other stack (the dev
container and `compose.yaml` have separate volumes).

### Wireless debugging (any host OS, Android 11+)

Without a USB cable, use wireless debugging with the phone and the computer on
the same network:

1. On the phone: Developer options → Wireless debugging → Pair device with pairing
   code. Note the pairing address and code.
2. Pair (interactive prompt for the code):
   `docker compose exec appium adb pair <ip>:<pairing-port>`
3. Connect to the address shown on the main Wireless debugging screen (a different
   port): `docker compose exec appium adb connect <ip>:<port>`

The adb key is stored in the `adb-keys` volume, so pairing survives restarts. The
connection port changes when wireless debugging is toggled; reconnect with step 3,
or set `ADB_CONNECT=<ip>:<port>` (comma-separated for several) in the shell or in
`.env` so the container keeps connecting it.

### USB on Linux hosts

```sh
docker compose -f compose.yaml -f compose.usb.yaml up --build -d
```

This mounts `/dev/bus/usb` into `appium` and runs it as root so the USB device
nodes are readable. Stop any host adb server first (`adb kill-server`): only one
server can own a USB device. Authorize the container's key on the phone when asked.

### Host adb or host Appium for runs (not supported)

The containers use the host adb server only for the Refresh bridge above: a fixed
set of commands (`devices`, a `wlan0` address read, `tcpip`), with no generic
shell. Runs always go through the container's adb server and Appium. Driving runs
through host adb or host Appium is intentionally not wired: it would relax the
loopback-only Appium policy. The host adb server
is reachable from containers through Docker Desktop's `host.docker.internal`
forwarding even though it listens on 127.0.0.1 only (observed on Windows 11; not
yet checked on macOS); no adb port is opened on the network.

## CLI inside the stack

The headless CLI runs in the backend container against the same Appium:

```sh
docker compose exec backend python -m visto.cli doctor --device <serial>
docker compose exec backend python -m visto.cli run --device <serial> --goal "..."
```

`doctor` checks configuration only. The container's working directory is `/app`,
so the CLI's relative defaults (`.work/runs`, `.env`, `.work/device-leases`) are
the same paths the console uses: history, key and device leases are shared. Do not
start a CLI run on a device while the console has an active run on it.

## VS Code dev container

Install the *Dev Containers* extension, open the repository and run
**Dev Containers: Reopen in Container**. `.devcontainer/compose.yaml` builds:

- `dev`: Python 3.12.10, uv, Node 24.19.0, pnpm 11.25.0 and an adb client, with
  the repository mounted at `/workspaces/visto`;
- `appium`: the same Appium image as above, sharing the `dev` network namespace.

On creation it runs the locked installs (`uv sync --all-groups`, `pnpm install
--frozen-lockfile`). Linux-specific trees live in named volumes over the host
paths: `.work/`, `backend/.venv`, `backend/dist`, `frontend/node_modules` and the
user cache. `.work/` on a volume avoids the slow host bind mount (one timing-bound API test
fails when SQLite lives on the Windows bind mount). Consequently the dev container
has its own run history, separate from the full stack's `work` volume.

On every container start `postStartCommand` runs `docker/dev-start.sh`, which
starts the backend (127.0.0.1:8000) and the Vite console (127.0.0.1:5173) in the
background, skipping any port that is already listening. Logs go to
`.work/dev-logs/backend.log` and `.work/dev-logs/frontend.log`. VS Code forwards
8000 and 5173 and opens the console in the host browser once Vite listens (the
local port may differ if 5173 is busy on the host; see the Ports panel).

To restart a server, stop it (`pkill -f uvicorn` or `pkill -f vite`) and run
`bash docker/dev-start.sh` again, or run it in the foreground instead:

```sh
python3 scripts/verify.py
uv run --project backend --locked --no-sync python -m uvicorn visto.composition:create_app --factory --host 127.0.0.1 --port 8000
pnpm --dir frontend dev
```

The root `.env` is read from the mounted workspace as on the host. Device
connection works as described above, using
`docker compose -f .devcontainer/compose.yaml exec appium adb ...` from a host
terminal, or plain `adb pair`/`adb connect` from the dev container terminal (its adb
client talks to the shared server).

## Platform coverage

The stack and dev container are exercised on Windows hosts with Docker Desktop,
including live runs on a phone bridged through the console Refresh. Linux USB
passthrough (`compose.usb.yaml`) and the host adb bridge on macOS are not yet
verified.
