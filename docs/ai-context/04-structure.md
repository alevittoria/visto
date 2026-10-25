# Structure

Code:

- `backend/src/visto/domain/`: immutable values, lifecycle and technical
  cross-reference validation.
- `backend/src/visto/application/`: context/ports, conversational loop,
  clock and cooperative runtime controls.
- `backend/src/visto/adapters/`: `ai`, `appium` (shared session core), `android`, `ios`, `storage`, `api`, `pricing`,
  `reports` and the technical `command_codec.py`.
- `backend/src/visto/adapters/settings/`: settings and secrets store in the
  Visto home.
- `backend/src/visto/{composition,runner,cli}.py`: ASGI factory (also serves the
  packaged console), headless composition and the `visto` command.
- `backend/src/visto/commands/`: `setup`, `start` (with the managed Appium
  process), `doctor` and `settings` commands.
- `backend/src/visto/toolchain/`: pinned component manifest, verified download and
  extraction, side-by-side installs, Appium install and the Android SDK license.
- `backend/src/visto/{home,instances}.py`: Visto home layout and the registry of
  running Visto processes.
- `backend/prompts/`: versioned runtime instructions, included as wheel resources.
- `backend/tests/`: backend tests, including the import-direction guard.
- `frontend/`: React/TypeScript console, native Node tests and Vite build; see
  `frontend/README.md` for its source layout.
- `tools/appium/`: pinned Appium/UiAutomator2 package and lock (Windows, Linux);
  `tools/appium/macos/`: pinned Appium, UiAutomator2 and XCUITest package and lock
  (macOS). These are the lockfiles the wheel ships and `visto setup` installs.
- `scripts/verify.py`: fixed-command local test/lint/build orchestration.
- `scripts/build_release.py`, `scripts/check_wheel.py`: release wheel build and
  content check; `.github/workflows/release.yml` runs them for a `v*` tag.
- `scripts/check_project.py`: companion-file integrity check.

Docs:

- `AGENTS.md`: repository-wide instructions for AI coding agents.
- `agents/`: development role briefs and Codex profile templates.
- `docs/ai-context/`: this context pack and STATUS.
- `docs/product/vision.md`: product intent.
- `docs/evaluation/`: model-judgement evaluation protocol, scenarios, run template.
- `docs/*.md`: operator guides (installation, device setup, console, API, reports, storage)
  and `references.md` (official technical references).

Runtime data lives in the Visto home, `~/.visto/` by default (`--home` selects
another). Contributors use `--home .work/home` inside the ignored `.work/`
directory.

See [architecture](03-architecture.md) for layer rules. Do not create an empty
package for a proposed interface before it has a use.
