# Installation

Visto is a Python command, `visto`, installed with [uv](https://docs.astral.sh/uv/)
from a wheel attached to a GitHub release. The first `visto start` (or `visto
setup`) downloads everything else (Node, a JDK, the Android SDK tools and Appium)
into a private folder, the Visto home. Visto installs nothing system-wide, changes
no environment variable, `PATH` entry or shell profile, and needs no administrator
rights; the one `PATH` change is uv's, for its own tool folder.

| Host | Android | iOS |
|---|---|---|
| Windows x64, Linux x64 | yes | no |
| macOS (Apple silicon or Intel) | yes | yes, see [iOS setup](ios-setup.md) |

Android is always installed, on macOS too. Windows on ARM and Linux on ARM are not
supported.

## 1. Install uv and Visto

Install uv as described in its
[installation guide](https://docs.astral.sh/uv/getting-started/installation/). It is
the only tool you install by hand; it also provides the Python 3.12 that Visto
needs.

Open the release you want on the
[releases page](https://github.com/alevittoria/visto/releases), copy the URL of its
`visto-<version>-py3-none-any.whl` asset and install it:

```sh
uv tool install https://github.com/alevittoria/visto/releases/download/v<version>/visto-<version>-py3-none-any.whl
```

Then put uv's tool folder (on Windows `%USERPROFILE%\.local\bin`) on your `PATH`,
once per user, and open a new terminal:

```sh
uv tool update-shell
```

Terminals opened before this do not see the change: if `visto` is not recognised
as a command, open a new terminal, or call it by the full path `uv tool dir --bin`
prints. This is uv changing your user `PATH`, not Visto. The release also carries
`visto-<version>-py3-none-any.whl.sha256` if you want to check a downloaded copy.
Visto never checks for new releases.

## 2. Install the toolchain: `visto setup` (optional)

`visto start` installs a missing toolchain itself, so this step is optional: run it
to install ahead of time, without a browser, or with `--ca-bundle` behind a proxy.

```sh
visto setup
```

Setup shows the Android SDK License Agreement and asks you to accept it; nothing is
installed if you decline. For a non-interactive install, pass
`--accept-android-license` to accept it without the prompt. Setup then downloads,
into `~/.visto/toolchain/`:

- a portable Node (whose corepack provides pnpm for the Appium install);
- a Temurin JDK 17;
- Android platform-tools (`adb`) and build-tools (`apksigner`, needed by
  UiAutomator2);
- Appium with the UiAutomator2 driver (on macOS also the XCUITest driver), installed
  from the lockfile shipped in the wheel.

Every archive is pinned and checked against its published checksum before it is
extracted: sha256 for Node and the JDK, sha1 for the Android archives, the only
checksum Google publishes for them. Downloads follow redirects only to HTTPS. A
component is extracted into a temporary folder and moved into place only when
complete, so a failed step leaves the previous version usable. Running setup again
only fetches what changed. Setup contacts these hosts:

| Host | Used for |
|---|---|
| `nodejs.org` | Node distribution |
| `dl.google.com` | Google Android repository (platform-tools, build-tools) |
| `github.com` | Adoptium Temurin JDK release assets (download URLs) |
| `release-assets.githubusercontent.com` | Where GitHub redirects those downloads; setup follows the redirect |
| `registry.npmjs.org` | pnpm for corepack, Appium and its drivers |

The redirect target is the host GitHub uses for release assets today; if GitHub
changes it, a proxy allowlist must follow.

Exit codes: 0 done, 2 license not accepted, 3 failure (the message names the
cause), 4 another Visto process is using the same home (stop it and retry).

### Behind a TLS-inspecting proxy

A proxy that re-signs HTTPS traffic with its own certificate authority makes the
downloads fail certificate verification. Export the proxy's certificates into a PEM
file that also contains the usual public root certificates, and pass it once:

```sh
visto setup --ca-bundle <bundle.pem>
```

The path is remembered in the home. Setup's own downloads trust that bundle instead
of the system store. `visto start` and `visto run` give it to the Appium they start
as `NODE_EXTRA_CA_CERTS` and `SSL_CERT_FILE`, only in that child's environment.
`visto start`, `visto run` and `visto settings verify-key` also use it as
`SSL_CERT_FILE` for their provider requests (in the console: runs, key verification,
dictation) while they run. `SSL_CERT_FILE` replaces Python's default roots, which is
why the bundle must include them. Pass `--ca-bundle` again to point at a rebuilt
bundle.

## 3. Start Visto: `visto start`

```sh
visto start
```

`start` runs Appium on `127.0.0.1:4723` and the backend with the web console on
`127.0.0.1:8000`, both bound to loopback, then opens <http://127.0.0.1:8000/> in the
browser. Ctrl+C stops both. Options: `--port` (console and API, default 8000),
`--appium-port` (default 4723) and `--no-browser`. A port that is already in use is
reported with the option to change it. Appium's output goes to
`~/.visto/logs/appium.log`; if Appium stops unexpectedly, `start` says so and exits.

Before serving, `start` installs any toolchain component that does not match the
installed Visto (typically after an upgrade), stating what it fetches; a license
that is not yet accepted still prompts. It then prepares the run database (see
[upgrade](#upgrade)). Only one `start` runs per home; a second one reports that
Visto is already running and exits with code 4.

## 4. Enter the provider key

On first open without a key, the console shows its **Settings** page. Paste the
OpenAI API key there, save it and press **Verify**; see
[provider setup](provider-setup.md) for what the key needs and how it is stored.
On a host without a browser, use the terminal instead:

```sh
visto settings set-key       # reads one line: hidden prompt on a terminal, else stdin
visto settings verify-key    # ok, missing, unauthorized, model_unavailable or unreachable
visto settings show          # key status (last four characters only) and preferences
visto settings delete-key
```

The key is never a command-line argument and is never printed. Changes apply to the
next run without restarting Visto. On a Mac, the iOS signing values are entered on
the same Settings page; see [iOS setup](ios-setup.md#signing-values-physical-phone).

## 5. Check the setup: `visto doctor`

```sh
visto doctor
```

Doctor prints one line per check: the toolchain matches this Visto, the Android SDK
license is accepted, Appium answers on port 4723 (or the port of `--appium-url`, for
an Appium started with `visto start --appium-port`), the managed `adb` (with its path)
works, attached Android devices and their state (`unauthorized` means the USB
debugging prompt was not accepted), the provider key is configured, and any device
leases left behind (see
[Android setup](android-setup.md#exclusive-ownership-and-crash-recovery)). It warns
when an adb server of a different version, started by another tool, is already
running: Visto's `adb` would restart that server, so devices are not listed until
you quit the other tool. On macOS it adds `xcrun simctl`/`xcrun devicectl`, the iOS
signing values (presence only), the WebDriverAgent project path and a notice when
the XCUITest driver changed since the iOS values were saved.

Doctor changes nothing, contacts no AI provider and contacts no device beyond
listing them with `adb devices`. Exit code 0 means no check failed, 2 that at least
one did. `--json` prints the same checks as one JSON object; its `device_contacted`
field is true when devices were listed.

Then connect a device ([Android setup](android-setup.md)) and start a run from the
console ([web console](web-console.md)) or from the terminal
([first device test](first-device-test.md)).

## The Visto home

Everything Visto stores lives under `~/.visto/`: the toolchain, the settings and the
provider key, the run history with screenshots, device leases and the Appium log.
The layout and its privacy are described in [artifact storage](artifact-storage.md).
Every command takes `--home <folder>` to use another home; processes that use the
same home share run history, settings and device leases.

## Upgrade

1. Stop Visto: let active runs finish (or cancel them), then press Ctrl+C in the
   `visto start` terminal. Setup and data upgrades refuse while another Visto process
   uses the home.
2. Install the new release's wheel over the old one:

   ```sh
   uv tool install --force https://github.com/alevittoria/visto/releases/download/v<new-version>/visto-<new-version>-py3-none-any.whl
   ```

3. Run `visto start`. It fetches the toolchain components the new release pins and
   removes the versions it no longer uses. When the run database needs a newer
   format, it first copies it to `~/.visto/data/runs.sqlite3.v<N>-<UTC timestamp>.bak`
   and then upgrades it in place. Settings and the provider key are kept.

An older Visto refuses data written by a newer one and says so; install the newer
release again, or restore the matching backup by copying it over `runs.sqlite3`
while Visto is stopped.

## Uninstall

```sh
uv tool uninstall visto
```

Then delete `~/.visto` (on Windows `%USERPROFILE%\.visto`) once you have kept any run
evidence you need. It holds the toolchain, run history, screenshots and the provider
key. The managed adb server may still be running after Visto stops; stop it first
with `<adb> kill-server`, using the `adb` path doctor prints, so its files can be
removed.

## Contributing

Contributors run Visto from a checkout. You need uv, Node 24 with corepack
(`corepack enable` once; the pnpm version comes from each `packageManager` field)
and Git. From the repository root:

```sh
uv sync --project backend --locked --all-groups
cd frontend
pnpm install --frozen-lockfile
cd ..
```

Run the backend with a home inside the repository, so a development database never
touches an installed release's `~/.visto`:

```sh
uv run --project backend visto start --home .work/home --no-browser
```

The first start installs the toolchain into that home (with the license prompt)
and installs Appium from `tools/appium/` (on macOS `tools/appium/macos/`), the same
lockfiles a release ships. The backend serves a built console only after
`scripts/build_release.py` has copied one into the package, so during development
serve the console with the Vite development server in a second terminal:

```sh
cd frontend
pnpm dev
```

Open <http://127.0.0.1:5173>. The development server forwards `/api` to the backend
on `127.0.0.1:8000`; for a backend on another port see
[frontend/README.md](../frontend/README.md). Pass `--home .work/home` to every other
`visto` command (`uv run --project backend visto doctor --home .work/home`). When a
home has no managed toolchain, doctor and the console's device list fall back to an
`adb` found through `ANDROID_HOME`, `ANDROID_SDK_ROOT`, the default SDK location or
`PATH`; `visto start` always uses the managed one.

### Checks

```sh
python scripts/verify.py
```

The verifier runs the companion checks, backend tests, Ruff lint and format checks
and a backend build, then the frontend TypeScript checks, Node tests and production
build. It does not install dependencies and never contacts a device or an AI
provider. `--backend-only` and `--frontend-only` limit the application checks;
`--node` and `--uv` take an executable name or path when those tools are not on
`PATH`. The `build` dependency group installed above is intentional: verification
builds the backend with the exact installed build tools.

### Release wheel

`python scripts/build_release.py` builds the console, copies it and the Appium
lockfiles into the package and builds the wheel; `python scripts/check_wheel.py
<wheel>` checks that the wheel carries them. Pushing a `v<version>` tag that matches
the version in `backend/pyproject.toml` runs `.github/workflows/release.yml`, which
runs the checks, builds and checks the wheel and attaches it with its SHA-256 to a
GitHub release for that tag.
