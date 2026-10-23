# Stack

| Concern | Choice | Resolution |
|---|---|---|
| Core/backend | Python 3.12, uv | `backend/.python-version`, `pyproject.toml`, `uv.lock` |
| HTTP | FastAPI, Pydantic, Uvicorn | Local execution API under `/api` |
| Console | React, TypeScript, Vite | `frontend/package.json`, `pnpm-lock.yaml` |
| JS tools | Node 24, pnpm | Native Node test runner; no extra test framework |
| Backend checks/build | pytest, Ruff, httpx2, hatchling | Locked development/build groups |
| Persistence | Python stdlib SQLite + local screenshot files | Transactional tagged JSON and immutable artifacts |
| Android | Appium 3 / UiAutomator2 | `tools/appium` lock, installed in the appium container; stdlib REST adapter |
| iOS | Appium 3 / XCUITest driver, Xcode `xcrun` | `tools/appium/macos` manifest (no lockfile), native macOS only; stdlib REST adapter |
| AI | OpenAI Responses API, Pillow | Versioned instructions in `backend/prompts/`; stdlib HTTPS in a fixed child process, no SDK; Pillow downscales screenshots to the provider's image limits |
| Containers | Docker Compose, VS Code dev container | `compose.yaml`, `docker/`, `.devcontainer/` |
| Companion checks | Python 3.12+ standard library | No package install required |

Exact versions are in the lockfiles; do not duplicate them in docs. Domain and
application do not depend on Pydantic/FastAPI. Current Starlette TestClient uses
httpx2. Setup: [local development](../local-development.md).
