# Contributing to Visto

Thanks for your interest! Visto is an early-stage project, so contributions of
any size help: bug reports, docs, tests, new adapters, design feedback.

## Where help is most wanted

- **iOS verification**: the iOS adapter (`backend/src/visto/adapters/ios/`) has
  had local checks only. Runs on simulators and iPhones, and fixes for what they
  reveal, are the most wanted contribution. Please open an issue to discuss a
  design change before writing a large PR.
- **AI providers**: adapters for multimodal models beyond OpenAI.
- **Evaluation**: labelled scenarios on fictional sample apps that measure how
  well a model judges outcomes (see `docs/evaluation/`).
- **Web console UX**, **documentation**, and a real **demo recording** for the README.

Issues labelled `good first issue` and `help wanted` are good starting points.

## Ground rules

These keep the project true to its design. PRs that break them are likely to be
declined, so ask first if in doubt:

1. **The AI owns semantic verdicts.** Do not add static UI predicates, label
   dictionaries, app-specific rules or a deterministic "did it work" checker.
   The executor only reports technical command outcomes.
2. **Clean Architecture.** `domain ← application ← adapters`. Domain and
   application code must not import FastAPI, Appium, provider SDKs, database
   drivers or UI code. `backend/tests/test_architecture.py` enforces this.
3. **No generic shell for the AI.** Device operations stay typed, scoped and
   timeout-bound. Never blindly retry an uncertain mutation.
4. **Privacy.** Never commit credentials, screenshots from real devices, device
   identifiers (serials, IPs, models), or names/content of real third-party apps.
   Use invented, clearly fictional names in fixtures and examples.

## Development setup

Clone the repository, install the locked dependencies and run Visto from the
checkout with its own home, as described in
[installation, contributing](docs/local-development.md#contributing):

```sh
uv sync --project backend --locked --all-groups
cd frontend
pnpm install --frozen-lockfile
cd ..
uv run --project backend visto start --home .work/home --no-browser
# second terminal: cd frontend && pnpm dev, then open http://127.0.0.1:5173
```

Then run the checks:

```sh
python scripts/verify.py
```

`scripts/verify.py` runs the backend tests, Ruff lint and format checks, a
package build, TypeScript checks, frontend tests and the production build. It
never contacts a device or an AI provider. All checks must pass before a PR
is merged.

Live checks against a real device or a paid provider are optional for
contributors. If you ran one, describe what you tested in the PR without
identifying the device or the apps involved.

## Pull requests

1. Fork the repository and create a branch from `master`.
2. Keep each PR focused on one change. Add or update tests for behaviour changes.
3. Run `python scripts/verify.py`, then describe what changed, why, and how you
   verified it.
4. Update documentation when behaviour or setup changes.

By submitting a contribution you agree that it is licensed under the
[MIT License](LICENSE) of this project.

## Working with AI coding agents

The repository includes instructions for AI coding agents ([AGENTS.md](AGENTS.md),
[docs/ai-context/](docs/ai-context/00-index.md), [agents/](agents/README.md)).
You are welcome to use them, but you are responsible for every line you submit:
review generated code and include real verification results.

## Conduct

Be respectful and constructive. Harassment or personal attacks are not tolerated
in issues, pull requests or any other project space.
