# Installation

Visto runs directly on your machine as three local processes: Appium, the
backend and the web console. Android works on Windows, Linux and macOS; iOS
needs macOS.

| Host | Android | iOS | Appium package |
|---|---|---|---|
| Windows, Linux | yes | no | `tools/appium` |
| macOS | yes | yes | `tools/appium/macos` (see [iOS setup](ios-setup.md)) |

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.11.32 | Installs Python 3.12.10 from `backend/.python-version` when it is missing |
| Node | 24.19.0 | Run `corepack enable` once; corepack then provides pnpm 11.25.0 |
| Android SDK | platform-tools, build-tools | `adb` lists devices; UiAutomator2 needs `apksigner` from build-tools |
| JDK | 17 or newer | Needed by UiAutomator2 |
| OpenAI API key | | With access to a vision model; see [provider setup](provider-setup.md) |

Android Studio installs the SDK with both packages and bundles a JDK, so it is
the quickest way to get all three.

## 2. Environment variables

Appium needs `ANDROID_HOME` and `JAVA_HOME` in the terminal that starts it;
without `ANDROID_HOME`, UiAutomator2 refuses every Android session. Put
`platform-tools` on `PATH` so `adb` works in any terminal.

Windows (PowerShell, saved for new terminals; open a new terminal afterwards):

```powershell
setx ANDROID_HOME "$env:LOCALAPPDATA\Android\Sdk"
setx JAVA_HOME "C:\Program Files\Android\Android Studio\jbr"
```

Then add `%ANDROID_HOME%\platform-tools` to `Path` in the user environment
variables.

macOS and Linux (add to `~/.zshrc` or `~/.bashrc`):

```sh
export ANDROID_HOME="$HOME/Library/Android/sdk"   # Linux: $HOME/Android/Sdk
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
```

Adjust the paths if the SDK or the JDK live elsewhere.

## 3. Install

From the repository root:

```sh
cp .env.example .env          # then set OPENAI_API_KEY in .env
uv sync --project backend --locked --all-groups
cd frontend
pnpm install --frozen-lockfile
cd ../tools/appium            # on macOS: cd ../tools/appium/macos
pnpm install --frozen-lockfile --ignore-scripts --node-linker=hoisted
```

`.env` is ignored by git; `.env.example` is the credential-free template. The
backend and the CLI read it on use, and a variable already set in the process
environment takes precedence. The frontend never receives the key.

pnpm runs from inside each directory because corepack picks the pnpm version
from the `packageManager` field of the current directory, and the repository
root has none. Keep `--node-linker=hoisted` on every Appium reinstall: Appium
discovers its drivers from a hoisted `node_modules`.

Check the Android prerequisites from the Appium directory:

```sh
pnpm doctor          # on macOS: pnpm doctor:android and pnpm doctor:ios
```

Behind a TLS-inspecting proxy, see
[iOS setup](ios-setup.md#behind-a-tls-inspecting-proxy); the same variables
apply on every OS.

## 4. Start

Use one terminal per process, each from the repository root:

```sh
# Appium on 127.0.0.1:4723
cd tools/appium               # on macOS: cd tools/appium/macos
pnpm start
```

```sh
# Backend on 127.0.0.1:8000
uv run --project backend --locked --no-sync python -m uvicorn visto.composition:create_app --factory --host 127.0.0.1 --port 8000
```

```sh
# Web console on 127.0.0.1:5173
cd frontend
pnpm dev
```

Open <http://127.0.0.1:5173>. The Vite development proxy forwards `/api` to the
backend; for a different backend port, set `VISTO_API_URL` in the frontend
process environment. All three processes bind loopback only.

The terminal CLI needs Appium but not the backend or the console; see
[first device test](first-device-test.md). For iOS, the backend reads its
`VISTO_IOS_*` settings from the process environment only; see
[iOS setup](ios-setup.md#signing-values-physical-phone).

## Verify

```sh
python scripts/verify.py
```

The verifier runs companion checks, backend tests/Ruff/distribution build and
frontend compiler lint, native Node tests and production build. It does not
install dependencies or contact a model/device. `--backend-only` and
`--frontend-only` limit application checks; companion checks still run. Frontend
lint is TypeScript compiler diagnostics, not ESLint. The `build` dependency
group installed above is intentional: verification builds the backend with the
exact installed build tools instead of resolving an isolated environment.
