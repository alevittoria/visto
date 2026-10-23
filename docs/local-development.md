# Local development

The recommended environment is the VS Code dev container or the Docker stack:
see [Docker and dev container](docker.md). Appium always runs in its container.
This page lists the pinned toolchain and the commands used inside the dev
container (they also work on a host with the same tools).

For provider configuration, put `OPENAI_API_KEY=...` in the local root `.env`,
which is ignored. `.env.example` is the credential-free template. The backend and
the CLI load it on use; process environment takes precedence. See
[provider setup](provider-setup.md). The frontend never receives this key.

## What each mode can drive

| Mode | Android | iOS | Appium |
|---|---|---|---|
| Docker Compose stack | yes | no | container |
| Dev container | yes | no | container |
| Backend started natively on macOS | yes | yes | local install |

Only the native mode lists both platforms in one device picker. It needs a
locally installed Appium with the UiAutomator2 and XCUITest drivers, a local
Android SDK with `ANDROID_HOME` exported to the Appium process (UiAutomator2
refuses every Android session without it), and Xcode for iOS; install the
pinned Appium stack from
`tools/appium/macos` as described in [iOS setup](ios-setup.md). The native
Android path is not yet re-checked on a phone. The containers cannot reach
Xcode, so under Docker the iOS part of the device list reports a note instead
of devices.

## Tool versions

Python 3.12.10, uv 0.11.32, Node 24.19.0 and pnpm 11.25.0. Application
dependencies are exact and locked in `backend/uv.lock` and
`frontend/pnpm-lock.yaml`. Do not commit local tool/cache directories or
credentials.

## Install from the repository root

```sh
uv sync --project backend --locked --all-groups
(cd frontend && pnpm install --frozen-lockfile)
```

pnpm runs from inside `frontend/` because corepack picks the pnpm version from
the `packageManager` field of the current directory, and the repository root has
none. Behind a TLS-inspecting proxy, see the proxy note in
[iOS setup](ios-setup.md#behind-a-tls-inspecting-proxy).

The build group is intentional: verification builds the backend using the exact
installed build tools instead of resolving an independent isolated environment.

## Verify

```sh
python3 scripts/verify.py
```

The verifier runs companion checks, backend tests/Ruff/distribution build and
frontend compiler lint, native Node tests and production build. It does not
install dependencies or contact a model/device. `--backend-only` and
`--frontend-only` limit application checks; companion checks still run. Frontend
lint is TypeScript compiler diagnostics, not ESLint.

## Start the servers

```sh
uv run --project backend --locked --no-sync python -m uvicorn visto.composition:create_app --factory --host 127.0.0.1 --port 8000
(cd frontend && pnpm dev)
```

For iOS, the backend reads its `VISTO_IOS_*` settings from the process
environment only; see [iOS setup](ios-setup.md#signing-values-physical-phone)
for exporting them from `.env` before this command.

Open <http://127.0.0.1:5173>. The Vite development proxy forwards `/api` to the
backend. For a different backend port, set `VISTO_API_URL` in the frontend
process environment. Both development servers bind loopback. In the dev container
`docker/dev-start.sh` starts both automatically.
