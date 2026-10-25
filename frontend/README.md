# Web console

React/TypeScript console for the local execution API (`docs/api-contract.md`).
Operator flow: [web console guide](../docs/web-console.md). The console shows
configuration readiness, starts a bounded run on a device picked from the
detected list, polls the selected run, and shows the latest screenshot (marked stale
when not live), the AI's rationale/working plan/effect assessments, the
chronological evidence history, pause/resume/cancel and question answering,
run history and report links. It never infers a test verdict: only the stored
AI conclusion is a verdict; technical receipts are labelled technical.

## Source layout

- `src/console.ts`: API types, `apiRequest` (distinguishes definite rejections
  from uncertain outcomes; mutations are never retried automatically),
  readiness parsing, run monitor with event paging, polling and control rules.
- `src/form.ts`: new-run form state, validation and contract limit bounds.
- `src/history.ts`: event-to-history projection, latest observation/decision,
  freshness, outcome and cleanup explanations.
- `src/App.tsx` and `src/components/*.tsx`: React views.
- `tests/*.test.mjs`: node:test coverage for the pure modules.

## Toolchain and commands

Use Node **24.19.0** and pnpm **11.25.0**. The root toolchain/setup guide is the
source for installation prerequisites. Dependencies are exact in `package.json`
and resolved with integrity hashes in `pnpm-lock.yaml`.

```powershell
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint
pnpm run test
pnpm run build
pnpm run dev
```

`lint` uses TypeScript compiler diagnostics for unused locals/parameters,
unreachable code and unused labels, in addition to strict type checking. It is
compiler lint, not ESLint or a React Hooks lint suite. Tests use Node's built-in
runner and TypeScript stripping; no Android or provider is required.

Vite uses its native configuration loader. It reads TSX and the automatic JSX
runtime directly; React Fast Refresh is not configured in this minimal shell.
Source edits may reload the page instead of preserving component state.

The development server binds to `127.0.0.1:5173`, with strict port selection.
It proxies `/api` to `http://127.0.0.1:8000`. To use another backend or frontend
port, set an explicit target before startup:

```powershell
$env:VISTO_API_URL = 'http://127.0.0.1:18000'
pnpm run dev --port 15173
```

The health check cancels in-flight checks on refresh/unmount, ignores older
responses and aborts after five seconds; API requests abort after ten seconds.
Run views poll about every second while active, back off while disconnected
and stop when the run has ended or was interrupted. A refresh clears the previous status
while checking. Errors do not display response bodies or internal diagnostics.

`pnpm run preview` serves the production build locally for inspection; it does
not configure an API proxy. Serve the API under the same origin when validating
a production deployment.

## Sources

- [Vite configuration](https://vite.dev/config/) and
  [proxy](https://vite.dev/config/server-options#server-proxy).
- [Vite TypeScript and JSX](https://vite.dev/guide/features.html#typescript).
- [React roots](https://react.dev/reference/react-dom/client/createRoot) and
  [effect cleanup](https://react.dev/reference/react/useEffect).
- [Node 24 test runner](https://nodejs.org/docs/latest-v24.x/api/test.html).
- [pnpm frozen installs](https://pnpm.io/cli/install).
- [TypeScript unused locals](https://www.typescriptlang.org/tsconfig/noUnusedLocals.html)
  and [parameters](https://www.typescriptlang.org/tsconfig/noUnusedParameters.html).
