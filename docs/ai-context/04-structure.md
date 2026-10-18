# Structure

Code:

- `backend/src/visto/domain/`: immutable values, lifecycle and technical
  cross-reference validation.
- `backend/src/visto/application/`: context/ports, conversational loop,
  clock and cooperative runtime controls.
- `backend/src/visto/adapters/`: `ai`, `android`, `storage`, `api`, `pricing`,
  `reports` and the technical `command_codec.py`.
- `backend/src/visto/{composition,configuration,runner,cli}.py`: ASGI factory,
  settings, headless composition and terminal use.
- `backend/prompts/`: versioned runtime instructions, included as wheel resources.
- `backend/tests/`: backend tests, including the import-direction guard.
- `frontend/`: React/TypeScript console, native Node tests and Vite build; see
  `frontend/README.md` for its source layout.
- `tools/appium/`: pinned Appium/UiAutomator2 package and lock for the appium image.
- `compose.yaml`, `compose.usb.yaml`, `docker/`: containerized stack (net, appium,
  backend, web) and nginx proxy; `.devcontainer/`: VS Code dev container.
- `scripts/verify.py`: fixed-command local test/lint/build orchestration.
- `scripts/check_project.py`: companion-file integrity check.
- `scripts/connect-device.ps1`: host helper that switches a USB phone to adb over
  TCP for the appium container (Windows hosts).

Docs:

- `AGENTS.md`: repository-wide instructions for AI coding agents.
- `agents/`: development role briefs and Codex profile templates.
- `docs/ai-context/`: this context pack and STATUS.
- `docs/product/vision.md`: product intent.
- `docs/evaluation/`: model-judgement evaluation protocol, scenarios, run template.
- `docs/*.md`: operator guides (setup, Docker, console, API, reports, storage)
  and `references.md` (official technical references).

Local runtime data lives under the ignored `.work/` directory.

See [architecture](03-architecture.md) for layer rules. Do not create an empty
package for a proposed interface before it has a use.
