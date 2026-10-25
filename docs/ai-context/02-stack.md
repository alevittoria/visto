# Stack

| Concern | Choice | Resolution |
|---|---|---|
| Core/backend | Python 3.12, uv | `backend/.python-version`, `pyproject.toml`, `uv.lock` |
| HTTP | FastAPI, Pydantic, Uvicorn | Local execution API under `/api` |
| Console | React, TypeScript, Vite | `frontend/package.json`, `pnpm-lock.yaml` |
| JS tools | Node 24, pnpm | Native Node test runner; no extra test framework |
| Backend checks/build | pytest, Ruff, httpx2, hatchling | Locked development/build groups |
| Persistence | Python stdlib SQLite + local screenshot files | Transactional tagged JSON and immutable artifacts |
| Distribution | Wheel on GitHub Releases, `uv tool install` | `.github/workflows/release.yml`, `scripts/build_release.py`; the wheel carries the built console and the Appium locks |
| Toolchain | Portable Node, Temurin JDK, Android platform-tools/build-tools | `backend/src/visto/toolchain/components.json` pins URL and checksum per host; `visto setup` installs into the Visto home |
| Android | Appium 3 / UiAutomator2, adb | `tools/appium` lock installed by `visto setup` with the managed Node, SDK and JDK; stdlib REST adapter |
| iOS | Appium 3 / XCUITest driver, Xcode `xcrun` | `tools/appium/macos` lock (Android and iOS drivers), macOS only; stdlib REST adapter |
| Settings | JSON files in the Visto home | `settings.json` and `secrets.json` (provider key, plain text, owner-only on POSIX) |
| AI | OpenAI Responses API, Pillow | Versioned instructions in `backend/prompts/`; stdlib HTTPS in a fixed child process, no SDK; Pillow downscales screenshots to the provider's image limits |
| Companion checks | Python 3.12+ standard library | No package install required |

Exact versions are in the lockfiles; do not duplicate them in docs. Domain and
application do not depend on Pydantic/FastAPI. Current Starlette TestClient uses
httpx2. Setup: [installation](../local-development.md).
