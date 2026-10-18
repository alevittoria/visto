# Local development

The recommended environment is the VS Code dev container or the Docker stack:
see [Docker and dev container](docker.md). Appium always runs in its container.
This page lists the pinned toolchain and the commands used inside the dev
container (they also work on a host with the same tools).

For provider configuration, put `OPENAI_API_KEY=...` in the local root `.env`,
which is ignored. `.env.example` is the credential-free template. The backend and
the CLI load it on use; process environment takes precedence. See
[provider setup](provider-setup.md). The frontend never receives this key.

## Tool versions

Python 3.12.10, uv 0.11.32, Node 24.19.0 and pnpm 11.25.0. Application
dependencies are exact and locked in `backend/uv.lock` and
`frontend/pnpm-lock.yaml`. Do not commit local tool/cache directories or
credentials.

## Install from the repository root

```sh
uv sync --project backend --locked --all-groups
pnpm --dir frontend install --frozen-lockfile
```

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
pnpm --dir frontend dev
```

Open <http://127.0.0.1:5173>. The Vite development proxy forwards `/api` to the
backend. For a different backend port, set `VISTO_API_URL` in the frontend
process environment. Both development servers bind loopback. In the dev container
`docker/dev-start.sh` starts both automatically.
