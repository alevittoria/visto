# iOS device setup

The iOS adapter drives an iOS Simulator or a USB-attached iPhone through Appium's
XCUITest driver and WebDriverAgent, using the same W3C wire code as Android. It
needs a Mac with Xcode, with the backend running on that Mac.

## Evidence

Local checks cover iOS with unit tests against a faked Appium wire and faked
`xcrun` output. On a phone, with the prebuilt WebDriverAgent found through
`VISTO_IOS_WDA_DERIVED_DATA` and the developer profile trusted, a session
started and a run executed actions. A completed run, the simulator path, the
`connected` state mapping and rotation on hardware have not been observed. The Appium and Xcode commands below follow the vendors' documentation
(see [references](references.md#ios)); treat their exact output as
unconfirmed until you run them. A run on iOS is not a validated acceptance.

## Where iOS runs

iOS needs macOS with Xcode. On a Mac the same backend lists Android and iOS
devices in one picker, through one Appium with both drivers and the local Android
SDK. Follow [installation](local-development.md) for the common steps, using
`tools/appium/macos` as the Appium package; this page adds what iOS needs.

## Prerequisites

- macOS with Xcode installed and launched once so it accepts its license and
  installs its components. `xcrun simctl` and `xcrun devicectl` must resolve.
- Node as required by `tools/appium/macos/package.json` (the pinned version is in
  [local development](local-development.md)) and pnpm 11.25.0.
- An Apple ID added in Xcode (Settings, Accounts). A free personal team is
  enough for a physical iPhone. A simulator needs no signing.
- For a phone: a USB cable, the phone unlocked, Developer Mode enabled
  (Settings, Privacy and Security, Developer Mode; the phone restarts and asks
  to confirm), UI Automation enabled (Settings, Developer) and the Mac trusted
  on the phone.

## Install Appium with both drivers

`tools/appium/macos/package.json` pins Appium, the UiAutomator2 driver and the
XCUITest driver to exact versions, and `tools/appium/macos/pnpm-lock.yaml` locks
the full dependency tree. `tools/appium/package.json`, used on Windows and
Linux, has only the Android driver.

Run pnpm from inside that directory, not with `--dir` from the repository root:
corepack picks the pnpm version from the `packageManager` field of the current
directory, and the root has none. Appium's install script is skipped and the
drivers are discovered from a hoisted `node_modules`.

```sh
cd tools/appium/macos
pnpm install --frozen-lockfile --ignore-scripts --node-linker=hoisted
export ANDROID_HOME=<android-sdk>   # for example ~/Library/Android/sdk
pnpm start
```

The XCUITest driver does not need `ANDROID_HOME`, but the same Appium serves
Android too: started without it, UiAutomator2 refuses every Android session at
once. The run then ends as an infrastructure failure at `device.acquire` whose
detail says to export `ANDROID_HOME` for Appium, restart it and recover the
retained device lease (see [Android setup](android-setup.md#exclusive-ownership-and-crash-recovery)).
`pnpm doctor:android` reports a missing `ANDROID_HOME` too. Exporting it from
the shell profile (for example `~/.zshrc`) keeps it set for every terminal.

Keep `--node-linker=hoisted` on every reinstall. A plain `pnpm install` switches
to pnpm's default isolated layout, moves the previous packages into
`node_modules/.ignored_*` and puts the drivers behind symlinks, which changes the
path the XCUITest driver opens WebDriverAgent from (see the pre-step below).
Any reinstall also replaces the WebDriverAgent project, so edits made to it in
Xcode, such as its bundle identifier, are lost; a build already in derived data
stays usable.

Run from that directory, Appium finds both drivers without `APPIUM_HOME`;
`node node_modules/appium/index.js driver list --installed` lists them. Appium
listens on `127.0.0.1:4723`, which is the default Appium URL of the backend and
the CLI. Run only one Appium on that port at a time. Check each driver's own
prerequisites with
`pnpm doctor:ios` and `pnpm doctor:android` from the same directory.

### Behind a TLS-inspecting proxy

A proxy that re-signs HTTPS traffic with its own certificate authority makes
corepack, pnpm and npm fail with `SELF_SIGNED_CERT_IN_CHAIN`, and makes the
backend's provider requests fail certificate verification, because neither Node
nor Python reads the macOS keychain by default. Export the proxy's certificates
from the System keychain into a PEM file, then point each runtime at it:

- Node, corepack and pnpm: `NODE_EXTRA_CA_CERTS=<proxy-ca.pem>`, which adds to
  Node's own roots.
- The backend's Python: `SSL_CERT_FILE=<bundle.pem>`, which *replaces* the
  default roots, so the bundle must be the usual roots (for a Homebrew Python,
  `/opt/homebrew/etc/openssl@3/cert.pem`) followed by the proxy certificates.

Rebuild the bundle when the proxy's certificate authority or the base roots
change. On Windows and Linux, export the proxy certificates from the system
certificate store instead; the two variables work the same way.

## Signing values (physical phone)

WebDriverAgent runs on the phone as a signed app. With a free Apple team the
following holds. These limits come from the project's design; Apple's own
provisioning guide was not read when this page was written, so confirm them
against it:

- the provisioning profile expires after seven days;
- the WebDriverAgent bundle identifier must be unique to you, because free
  teams cannot share one;
- after you re-sign, the phone asks you to trust the developer profile again
  (see [Trust the developer profile](#trust-the-developer-profile)).

Set these in the environment of the process that starts the backend or the CLI.
They are read from the process environment only, not from `.env`, and are never
committed or echoed. To keep them in the ignored `.env` file anyway, export the
file into the shell that starts the backend, from the repository root:

```sh
set -a; source .env; set +a
uv run --project backend --locked --no-sync python -m uvicorn visto.composition:create_app --factory --host 127.0.0.1 --port 8000
```

A running backend does not see later changes: restart it after editing them.

| Variable | Appium capability | Meaning |
|---|---|---|
| `VISTO_IOS_TEAM_ID` | `appium:xcodeOrgId` | Apple team identifier |
| `VISTO_IOS_SIGNING_ID` | `appium:xcodeSigningId` | Signing identity name |
| `VISTO_IOS_WDA_BUNDLE_ID` | `appium:updatedWDABundleId` | Your unique WebDriverAgent bundle identifier |
| `VISTO_IOS_PREBUILT_WDA` | `appium:usePrebuiltWDA` | Set to any value other than empty, `0`, `false` or `no` to use an already installed WebDriverAgent |
| `VISTO_IOS_WDA_DERIVED_DATA` | `appium:derivedDataPath` | Derived data folder of your WebDriverAgent build; a leading `~` is expanded |

Each capability is omitted when its variable is unset. `appium:xcodeOrgId` has no
effect unless `appium:xcodeSigningId` is also set, so set the team and signing
values together. Re-signing every seven
days is a normal operator step: rebuild and reinstall WebDriverAgent with the
same values, then trust the developer profile on the phone again.

### Trust the developer profile

iOS installs a runner signed with a personal team but refuses to launch it until
the profile is trusted on the phone. Once WebDriverAgent is installed:

1. Open Settings, General, VPN and Device Management.
2. Under Developer App, tap the `Apple Development: …` entry of your account.
3. Tap Trust and confirm.

The Developer App section appears only once an app signed with that profile is
installed. If it is missing, check that Developer Mode is on and that the
runner was installed. An untrusted profile makes the session start fail with
`xcodebuild failed with code 65`; the test result then says "the Developer App
Certificate is not trusted" (see [When a run does not start](#when-a-run-does-not-start)).

## Pre-step before every run

Visto never boots a simulator, builds WebDriverAgent or shuts a device down. The
XCUITest driver will boot a shut-down simulator or build WebDriverAgent itself if
a session is pointed at a target that is not ready, which is why this pre-step
exists, why the console refuses a shut-down simulator (the CLI consults no
inventory, so a shut-down simulator id given to it will be booted by the driver)
and why `VISTO_IOS_PREBUILT_WDA` matters. You do these first.

- Simulator: boot it (Xcode, or `xcrun simctl boot <simulator-id>`). A shut-down
  simulator is listed in the console but cannot be selected; the console hint
  says to start it from Xcode.
- WebDriverAgent: build and install it on the target with your signing values,
  then set `VISTO_IOS_PREBUILT_WDA` so a run uses it. Without that variable the
  driver applies its own default, which may build WebDriverAgent while the
  session starts and can exceed the startup timeout. For a phone:
  1. Open the project the installed driver ships, found with
     `find tools/appium/macos/node_modules -name WebDriverAgent.xcodeproj`.
  2. For the `WebDriverAgentRunner` target, choose your team under Signing and
     Capabilities and replace the bundle identifier with one unique to you; use
     the same team for `WebDriverAgentLib`.
  3. Select the `WebDriverAgentRunner` scheme and the phone as destination, then
     run Product, Test. Stop it once the runner app is installed and running.
  4. On the phone, [trust the developer profile](#trust-the-developer-profile).

  Use that team, the signing identity Xcode chose and that bundle identifier as
  the signing values above. Set `VISTO_IOS_WDA_DERIVED_DATA` to the build's
  derived data folder: the `~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*`
  folder whose `Build/Products/Debug-iphoneos` holds
  `WebDriverAgentRunner-Runner.app` (Xcode, Settings, Locations shows the root).
  Even with `VISTO_IOS_PREBUILT_WDA` the driver still runs `xcodebuild
  test-without-building`, which installs and launches that build. Without the
  derived data variable, Xcode picks the folder from the project path the driver
  opens, which is the symlink-resolved path. If you opened the project in Xcode
  through a different path, for example a symlink after a non-hoisted install,
  the driver looks in another, empty folder, and the startup fails with
  `xcodebuild failed with code 65` because the runner app does not exist there.
  The
  [XCUITest device setup guide](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)
  is the reference.
- Phone: unlock it, trust the developer profile, and open the application under
  test in its starting state. The adapter does not install or launch apps.

`acquire` fails closed when the target is not ready. A failure before the
ownership marker is created leaves nothing behind: the adapter already owns a
device, the lease directory cannot be created, or a marker for the device
already exists and is left untouched. Once the marker exists, a startup that
fails or is ambiguous retains it on purpose, because the remote session may
exist; that is the normal outcome of a failed startup and needs the recovery
below. If the session was created but is unusable, the adapter makes one bounded
attempt to delete it and releases the marker only when that delete succeeded.

## Check readiness

```sh
python -m visto.cli doctor --platform ios --device <udid>
```

`doctor` reads the local toolchain and environment only. It contacts neither a
device nor the provider. For iOS it adds `xcrun_present`,
`simulator_tooling_present`, `device_tooling_present` and
`wda_signing_configured` (all three signing variables set; values are never
shown). Exit code 0 needs the API key, a device identifier, `xcrun` and the
simulator tooling. Device tooling and signing are reported but not required, so
a simulator-only setup exits 0; check those two fields yourself before using a
phone. Exit code 2 means one of the required items is missing.

The console and `GET /readiness` expose `platforms`. It lists which device
sources are configured on the server, not what the machine can drive. On
Windows or Linux it still names iOS; the device list then carries a note that
`xcrun` was not found.

## Start a run

Pick the device in the console list (iOS entries show their platform), or pass
the platform on the CLI:

```sh
python -m visto.cli run --platform ios --device <udid> --goal "..."
```

`POST /runs` takes `"platform": "ios"`. There is no separate
platform check in the adapter: a device that does not suit the requested
platform fails when Appium cannot start a session for it, so expect the
retained-lease recovery below after such a mistake. See
[first device test](first-device-test.md).

## Behaviour to expect

- Gestures use screenshot pixels converted to points with a scale checked per
  capture; a non-uniform or inconsistent scale refuses the device.
- `back` is a swipe from the left edge. It may not navigate; the executor
  reports only that the gesture was sent, and the AI is told to adapt.
- Do not rotate the device or touch it during a run. A rotated screen will most
  likely refuse the session with `ios: inconsistent screen scale`, because
  WebDriverAgent commonly returns the screenshot in the native portrait pixel
  frame while the window rect reports the rotated point frame. That is the
  designed fail-closed outcome.

## When a run does not start

A failed session start ends the run as an infrastructure failure at
`device.acquire` with a generic detail, and retains the device lease (see the
recovery below). The cause is not stored with the run. Look in two places:

- The Appium server output. With the pinned `--log-level warn` it shows
  `Unable to launch WebDriverAgent` and the `xcodebuild` exit code, not the
  reason.
- The `xcodebuild` test result in the derived data folder the driver used,
  `<derived-data>/Logs/Test/Test-WebDriverAgentRunner-<timestamp>.xcresult`.
  Print its errors with
  `xcrun xcresulttool get build-results --path <xcresult>`. These results name
  the phone; do not copy them into reports.

| Error in the test result | Cause and fix |
|---|---|
| "Failed to install the app on the device" … "The file doesn't exist" | No runner build in that folder: set `VISTO_IOS_WDA_DERIVED_DATA` to the folder that holds it, restart the backend |
| "The Developer App Certificate is not trusted" | [Trust the developer profile](#trust-the-developer-profile) on the phone |

A new `WebDriverAgent-*` folder that appears under derived data with no
`Build/Products` is the trace of the first case.

## Recovery of a retained lease

An uncertain mutation, an unusable session, a failed startup or a failed cleanup
retains the ownership marker, as on Android. A retained lease needs manual
recovery:

1. Stop the runner and Appium, and confirm no WebDriverAgent session is still
   active on the target. Appium refuses `GET /appium/sessions` unless its
   `session_discovery` feature is enabled; a session start that failed before
   WebDriverAgent launched, as in the table above, created no session.
2. Inspect the marker in `.work/device-leases` (device, run, PID) and the run's
   stored intent and receipt. Do not infer a verdict from a lost transport.
3. Delete only that marker once the target is idle. Its name is the SHA-256 of
   the device identifier: `printf %s '<udid>' | shasum -a 256`, plus `.lease`.
4. Restart Appium and start a new run from a fresh observation.

Screenshots may contain private data and Appium logs may contain entered text;
see [Android setup](android-setup.md#exclusive-ownership-and-crash-recovery)
for the shared lease model.
