# Easy installation and in-console settings — design

## Intent

Installing Visto today means assembling four ecosystems by hand (uv/Python,
Node/corepack/pnpm, Android SDK + JDK, Appium + drivers), setting `ANDROID_HOME`,
`JAVA_HOME` and `PATH`, writing a `.env` with the provider key, and starting three
processes in three terminals. The steps where people actually get stuck are the
environment variables and the API key.

The target user is a **developer** comfortable with a terminal. Success means:
install uv, run one install command and `visto setup`, run `visto start`, and land
in the console with nothing but the provider key (and, on a Mac, iOS signing
values) left to enter — in the console, not in a file.

## Goals

1. Distribute Visto as a prebuilt Python wheel attached to **GitHub Releases**
   (no PyPI), containing the backend and the compiled web console.
2. A `visto` command with `setup`, `start` and `doctor` (alongside the existing
   `run` and `inspect`).
3. `visto setup` downloads pinned, checksum-verified, portable toolchain
   components into a private Visto home; nothing is installed system-wide and no
   system environment variable or `PATH` is changed.
4. `visto start` runs Appium and the backend (which also serves the console) from
   one terminal, opens the browser, and stops everything on Ctrl+C.
5. A **settings page** in the console replaces `.env` and the `VISTO_*`
   environment variables. Changes apply without restarting.
6. Android and iOS are both covered from the start, platform-aware: Windows and
   Linux never mention iOS.
7. Upgrades keep user data and settings; toolchain components realign to the new
   release's pins.
8. A GitHub Action builds the wheel and attaches it to a release.

## Non-goals

- Publishing to PyPI.
- Any "new version available" check or other update notification. Visto makes no
  network call to look for releases.
- A graphical installer, desktop app, Docker image or code signing of binaries.
- Building or signing WebDriverAgent automatically (the project rule "Visto never
  builds WebDriverAgent" stays).
- A device/prerequisite status panel in the console (doctor stays a CLI command).
- Windows on ARM and Linux on ARM.
- Importing an existing `.env` or migrating existing `.work/` data.

## Anti-goals (a failure even if it works)

- Modifying system or user environment variables, `PATH`, shell profiles, or
  requiring administrator rights.
- Requiring Android Studio.
- The provider key ever reaching the frontend, a log, a report, an error message
  or a response body.
- Downloads that are not pinned and checksum-verified.
- Silently replacing a component while a device is leased or a run is active.
- iOS wording, options or checks shown on Windows/Linux.

## Decisions made with the user

- **Distribution**: wheel attached to GitHub Releases, built by a GitHub Action.
  Installed with `uv tool install <release wheel URL>`. uv is the single manual
  prerequisite.
- **Visto home**: `~/.visto/` holds the toolchain, data (run history, screenshots,
  device leases) and settings. Android Studio is no longer needed.
- **No `.env`, no environment variables for settings.** `OPENAI_API_KEY`, the five
  `VISTO_IOS_*` values and `VISTO_PRICE_REFRESH` are read **only** from the
  settings store written by the console. The process environment is not consulted
  for them, by the backend or by the CLI. `.env.example` and the `.env` parser
  (`backend/src/visto/configuration.py`) are removed.
- **Variables the toolchain makes obsolete** (`ANDROID_HOME`, `ANDROID_SDK_ROOT`,
  `JAVA_HOME`, `PATH` edits, `VISTO_API_URL` for end users) do not appear in the
  settings page at all.
- **Both platforms now.** macOS gets Appium with UiAutomator2 + XCUITest and the
  Xcode checks; Windows/Linux get Android only and no iOS mention anywhere
  (setup output, doctor, settings page).
- **No update notification.**
- **Android is always installed**, on macOS too: `setup` has no platform
  selection; a Mac always gets the Android toolchain plus the XCUITest driver.
- **Key storage**: an owner-only secrets file in the Visto home, no OS credential
  store.

## Design

### 1. Packaging and release

- The wheel includes the compiled console (`frontend` production build) as package
  data, and the two Appium package manifests with their pnpm lockfiles
  (`tools/appium/` and `tools/appium/macos/`) as resources, so `visto setup`
  installs exactly the locked tree.
- `[project.scripts]` gains `visto = "visto.cli:main"` (or equivalent).
- The backend serves the built console at `/` with SPA fallback; the API stays
  under `/api`. The Vite dev server and its `/api` proxy remain for contributors.
- GitHub Action on a pushed `v*` tag: check the tag equals the `pyproject` version,
  build the frontend, build the wheel, run `python scripts/verify.py`, create the
  release and attach the wheel plus its SHA-256. Pin action versions.
- Wheel filenames must carry the version, so there is no stable "latest" URL; the
  README shows the install command per release. Upgrade is
  `uv tool install --force <new wheel URL>`.

### 2. Visto home and toolchain (`visto setup`)

Layout (builder may refine names):

```
~/.visto/
  toolchain/<component>/<version>/   node, jdk, android-platform-tools,
                                     android-build-tools, appium
  toolchain/manifest.json            what is installed and active
  data/                              runs, artifacts, SQLite, device-leases
  settings.json                      non-secret settings, versioned format
```

- A pinned component manifest ships inside the wheel: per component, per
  supported host (win-x64, macos-arm64, macos-x64, linux-x64), the exact version,
  download URL and checksum.
- Components: portable Node (also provides corepack/pnpm for the Appium install),
  a Temurin JDK, Android platform-tools and build-tools (UiAutomator2 needs
  `apksigner`), and Appium + drivers installed from the shipped lockfile with
  `--frozen-lockfile --ignore-scripts --node-linker=hoisted` using the portable
  Node. macOS uses the macOS Appium package (adds XCUITest).
- Every download is verified against its pinned checksum before extraction;
  extraction goes into a fresh temporary directory and is moved into place only on
  success. A failed step leaves the previous active version intact.
- Versioned side-by-side directories: switching is a manifest update; the old
  version is removed only after the new one is installed. Re-running `setup` is
  idempotent and only fetches what changed.
- Before installing the Android SDK packages, `setup` shows the Android SDK
  license and requires explicit acceptance (interactive prompt, or a flag such as
  `--accept-android-license` for non-interactive use). Redistributing the SDK is
  not allowed; downloading on the user's host after acceptance is.
- Behind a TLS-inspecting proxy, `setup` accepts a CA bundle option; the path is
  remembered and applied by `start` to Node (`NODE_EXTRA_CA_CERTS`) and Python
  (`SSL_CERT_FILE`) child/runtime environments. This is the one certificate
  setting and it lives outside the settings page because it is needed before any
  page exists.
- `setup` refuses to replace components while another Visto process is running
  (see 3b).
- Network endpoints contacted by `setup` are documented (Node distribution,
  Google Android repository, Adoptium, npm registry).

### 3. `visto start`

- Holds a single-instance lock in the Visto home.
- If the installed toolchain does not match the wheel's manifest (typically after
  an upgrade), it runs the needed setup steps first, stating what it fetches; a
  newly required license acceptance still prompts.
- Runs database migrations (section 6), then starts Appium as a child process on
  `127.0.0.1:4723` with `ANDROID_HOME`, `JAVA_HOME` and `PATH` set **only in the
  child environment**, then starts the backend in-process on loopback, then opens
  the browser at the console.
- The backend locates `adb` (and `apksigner` via Appium) from the managed
  toolchain, passed explicitly from composition rather than read from the
  environment.
- Ctrl+C stops the backend and Appium; a crash of Appium is reported, not hidden.
  Port, data location and Visto home are command-line options with sensible
  defaults; port collisions produce a clear message.
- Repository-relative defaults (`REPOSITORY`, `.work/`, `.env` in
  `composition.py`, `cli.py`, `runner.py`) are replaced by Visto-home paths, since
  an installed wheel has no repository root.

### 3b. CLI commands, locking, leases and adb

- `visto run` and `visto inspect` use the same Visto home, data directory, lease
  directory and settings store as `start`. `run` uses the Appium started by
  `visto start` when it is up; otherwise it starts its own managed Appium child for
  the duration of the run, with the same child-only environment. SQLite access is
  shared; device ownership stays enforced by the lease markers, which live in the
  Visto home (one lease directory per home).
- Every Visto process (`start`, `run`, `inspect`) registers itself in the home
  (an instance lock or registry). `setup`, automatic realignment and migrations
  refuse while another Visto process is registered. Device leases do **not** block
  setup: the toolchain does not affect the fail-closed lease rule, and a stale
  lease must not block upgrades.
- Leases stay fail-closed. Doctor lists retained leases with their device id, run
  id and PID; recovery stays the documented manual step (with the new path). No
  automatic clearing.
- A headless way to set the key exists: `visto settings set-key` reading the key
  from stdin (never from an argument), plus `delete-key` and `verify-key`. This
  serves SSH/CI hosts without a browser.
- `adb`: Visto always uses the managed platform-tools `adb`. Doctor warns when an
  adb server of a different version is already running on the host (starting a
  different version replaces that server).

### 4. `visto doctor`

- Human-readable checks with a `--json` mode (the current doctor already emits
  JSON; keep that shape available).
- All hosts: toolchain matches manifest, Appium reachable when running, `adb`
  works, devices listed with state (`unauthorized` explained), provider key
  configured (presence only, never echoed).
- macOS only: Xcode present and license accepted (`xcrun simctl`,
  `xcrun devicectl`), iOS signing values configured (presence only), the exact
  path of the WebDriverAgent project inside the managed Appium install, and a
  warning when the installed XCUITest driver version differs from the one
  recorded when the iOS values were last saved (WebDriverAgent must be rebuilt and
  re-signed).
- Doctor is read-only, contacts no device beyond listing, and makes no billable
  call.

### 5. Settings (store, API, page)

Settings:

| Setting | Kind | Shown on |
|---|---|---|
| OpenAI API key | secret | all hosts |
| iOS team ID, signing ID, WDA bundle ID, prebuilt WDA (bool), WDA derived data (path) | plain | macOS only |
| Model price refresh (bool, default on) | plain | all hosts |

- **Store**: non-secret values in `~/.visto/settings.json` (versioned format).
  The key goes to a separate secrets file in the Visto home (user decision: no OS
  credential store, no extra dependency). It is written atomically and readable by
  the user only: mode 0600 on POSIX; on Windows the file inherits the user-profile
  ACL, which the docs state honestly. The key is stored in plain text, as it was
  in `.env`; the page and `docs/artifact-storage.md` say so.
- **Read at use**: the backend and the CLI read settings when they need them, so a
  change applies without restart. A run snapshots the settings it uses at start;
  changes affect the next run only. The stored run records which model was used,
  never the key. The price-refresh switch is read when a refresh would happen, no
  longer only at app creation.
- **API** (under `/api`): read non-secret settings plus key status
  (`configured`, last four characters, storage kind) and host capabilities (whether
  iOS is supported); update non-secret settings; set and delete the key; verify the
  key. The key is write-only: no endpoint returns it. Verification uses a
  non-billable provider call (e.g. listing models), confirms access to a
  vision-capable allowlisted model, and returns only a sanitized category. Verify
  the endpoint in the provider's official docs first.
- **Write protection**: reuse the existing console write guard in
  `adapters/api/execution.py` (loopback `Host`, `x-visto: local-console` header,
  same-origin `Origin`, `Sec-Fetch-Site`) for every settings write. Request
  validation errors keep naming fields only, never values.
- **Page**: a Settings view in the console. On first open with no key configured,
  the console routes to it. iOS section rendered only when the backend reports
  iOS support. The key field shows status and last four characters, with replace,
  delete and verify actions. The page shows the WebDriverAgent project path on
  macOS (read-only).
- Clean Architecture: settings and secrets storage are adapters wired in
  composition; domain/application do not import them. Whether a small application
  port is warranted is left to the builder, per the "interfaces driven by concrete
  use cases" rule.

### 6. Data, migrations, upgrades

- The SQLite store (currently `PRAGMA user_version=1` and `ValueError` on anything
  else) gets numbered forward migrations. Before applying any migration, copy the
  database to a timestamped backup in the data directory. A database whose version
  is newer than the code supports is refused with a clear message (protects
  against running an older Visto on newer data).
- `settings.json` carries a format version with the same rule.
- Migrations run in `visto start` (and before CLI commands that open the store),
  never while another instance holds the lock.

### 7. Contributor workflow

- `uv sync` + pnpm remain for contributors. Contributors run the backend through
  `uv run visto start --home <repo>/.work/home` (separate from an installed
  release's `~/.visto`, so a dev schema never touches release data) with an option
  to skip opening the browser, and the console through the Vite dev server and its
  `/api` proxy. The raw `uvicorn` command leaves the docs. The home location is a
  command-line option, not an environment variable. There is no `.env`; the key
  is entered through the console or `visto settings set-key`.
- `tools/appium/` stays the source of the lockfiles shipped in the wheel. When no
  managed toolchain is installed in the selected home, the backend falls back to
  its current `adb` discovery.

### 8. Documentation

Rewrite `docs/local-development.md` into an end-user installation guide (uv,
install, setup, start, doctor, upgrade, uninstall) and a contributor section;
replace the environment-variable sections of `docs/ios-setup.md`,
`docs/provider-setup.md` and `docs/web-console.md` with the settings page; update
`docs/artifact-storage.md` for the new data location and the key storage
honestly; update README, STATUS and `docs/references.md`. Run
`python scripts/check_project.py` after doc edits.

## Constraints

- AGENTS.md applies in full: Clean Architecture direction, no generic shell for the
  product AI, device and app anonymity in all fixtures and docs, no device contact
  or billable inference to verify this work, docs describe current state only.
- Exact versions live in lockfiles/manifests; version-sensitive APIs (uv tool
  install, GitHub Actions, Node distribution, Android repository, Adoptium API,
  provider models endpoint) are verified against official docs and
  referenced.
- Local/fake checks must cover: manifest selection per host, download checksum
  failure, atomic install/rollback, idempotent re-run, single-instance and lease
  refusal, child-only environment, settings store and owner-only secrets file, key never present in any API response or log, write-guard on
  settings endpoints, platform-gated iOS fields, migration + backup + newer-schema
  refusal, wheel contains the console and lockfiles.
- Live checks (clean Windows host, clean Mac host) are separate, labelled, and run
  by the user; the builder does not perform them.

## Left to the builder

Exact module layout, CLI option names, manifest format, how `start` supervises
Appium, the frontend routing details for the settings view, and whether a small
settings port lives in application.

## Calls made by the coordinator (not yet confirmed by the user)

- No new access token for the console: the existing write guard already blocks
  cross-site and DNS-rebinding writes.
- No import of an existing `.env`; no migration of `.work/` data.
- `visto start` realigns changed toolchain components automatically.
- Supported hosts: win-x64, macos-arm64, macos-x64, linux-x64.
- A WebDriverAgent rebuild warning based on the XCUITest version recorded when iOS
  settings were last saved.
- `visto run` reuses the running Appium or starts its own; all Visto processes
  share one home; setup refuses while any other Visto process runs; stale leases
  never block setup and are never cleared automatically.
- `visto settings set-key` (stdin) for headless hosts.
- Visto always uses its managed `adb`; doctor warns about a different running adb
  server.
- Contributors use a separate home under the repository via `--home`.
