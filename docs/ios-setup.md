# iOS device setup

The iOS adapter drives an iOS Simulator or a USB-attached iPhone through Appium's
XCUITest driver and WebDriverAgent, using the same W3C wire code as Android. It
needs a Mac with Xcode, with the backend running on that Mac.

## Evidence

Local checks cover iOS with unit tests against a faked Appium wire and faked
`xcrun` output. On a phone, with a prebuilt WebDriverAgent found through an
explicit derived data folder and the developer profile trusted, a session
started and a run executed actions. A completed run, the simulator path, the
`connected` state mapping and rotation on hardware have not been observed. The
Appium and Xcode commands below follow the vendors' documentation (see
[references](references.md#ios)); treat their exact output as unconfirmed until
you run them. A run on iOS is not a validated acceptance.

## Where iOS runs

iOS needs macOS with Xcode. On a Mac the same Visto lists Android and iOS devices
in one picker, through one Appium with both drivers. Follow
[installation](local-development.md) first; this page adds what iOS needs.

## Prerequisites

- Visto installed and `visto setup` completed (see
  [installation](local-development.md)).
- macOS with Xcode installed and launched once so it accepts its license and
  installs its components. `xcrun simctl` and `xcrun devicectl` must resolve;
  `visto doctor` checks both.
- An Apple ID added in Xcode (Settings, Accounts). A free personal team is
  enough for a physical iPhone. A simulator needs no signing.
- For a phone: a USB cable, the phone unlocked, Developer Mode enabled
  (Settings, Privacy and Security, Developer Mode; the phone restarts and asks
  to confirm), UI Automation enabled (Settings, Developer) and the Mac trusted
  on the phone.

## Appium with both drivers

On macOS, `visto setup` installs Appium with the UiAutomator2 and XCUITest drivers
from the macOS lockfile shipped in the wheel (its source is
`tools/appium/macos/`; `tools/appium/` on Windows and Linux has only the Android
driver). The install lives in its own folder,
`~/.visto/toolchain/appium/macos-<hash>/`, where `<hash>` identifies the lockfile;
a release with a changed lockfile installs into a new folder and removes the old
one. `visto start` runs that Appium on `127.0.0.1:4723` with the Android SDK and
JDK paths in its own environment, so Android sessions work from the same server.

The installed driver ships the WebDriverAgent Xcode project inside that folder.
`visto doctor` and the Settings page show its exact path ("WebDriverAgent
project"). Because each Appium install is a new folder, edits made to the project
in Xcode, such as its bundle identifier, do not carry over to the next install; a
build already in its derived data folder stays usable.

Behind a TLS-inspecting proxy, see
[installation](local-development.md#behind-a-tls-inspecting-proxy).

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

Enter the values in the **iOS signing** section of the console's Settings page,
which appears only when Visto runs on macOS, and press **Save settings**. They are
stored in `settings.json` in the Visto home, are never printed (`visto doctor` and
`visto settings show` report only whether each one is set) and apply to the next
run without a restart.

| Settings field | Appium capability | Meaning |
|---|---|---|
| Development team ID | `appium:xcodeOrgId` | Apple team identifier |
| Signing identity | `appium:xcodeSigningId` | Signing identity name |
| WebDriverAgent bundle ID | `appium:updatedWDABundleId` | Your unique WebDriverAgent bundle identifier |
| Use a prebuilt WebDriverAgent | `appium:usePrebuiltWDA` | Use the WebDriverAgent you built and installed in the pre-step |
| Derived data folder | `appium:derivedDataPath` | Derived data folder of your WebDriverAgent build; a leading `~` is expanded |

Each capability is omitted when its field is empty (or the box is unticked).
`appium:xcodeOrgId` has no effect unless `appium:xcodeSigningId` is also set, so
set the team and signing values together. Re-signing every seven days is a normal
operator step: rebuild and reinstall WebDriverAgent with the same values, then
trust the developer profile on the phone again.

### After an XCUITest driver change

Saving the iOS values records the installed XCUITest driver version. When a later
release installs a different driver version, `visto doctor` and the Settings page
say so. Rebuild and re-sign WebDriverAgent from the project path now shown (see the
pre-step below), update the derived data folder if it changed, then save the iOS
settings again to clear the notice.

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
and why the "Use a prebuilt WebDriverAgent" setting matters. You do these first.

- Simulator: boot it (Xcode, or `xcrun simctl boot <simulator-id>`). A shut-down
  simulator is listed in the console but cannot be selected; the console hint
  says to start it from Xcode.
- WebDriverAgent: build and install it on the target with your signing values,
  then tick "Use a prebuilt WebDriverAgent" in Settings so a run uses it. Without
  it the driver applies its own default, which may build WebDriverAgent while the
  session starts and can exceed the startup timeout. For a phone:
  1. Open the project the installed driver ships, at the "WebDriverAgent
     project" path shown by `visto doctor` and the Settings page.
  2. For the `WebDriverAgentRunner` target, choose your team under Signing and
     Capabilities and replace the bundle identifier with one unique to you; use
     the same team for `WebDriverAgentLib`.
  3. Select the `WebDriverAgentRunner` scheme and the phone as destination, then
     run Product, Test. Stop it once the runner app is installed and running.
  4. On the phone, [trust the developer profile](#trust-the-developer-profile).

  Use that team, the signing identity Xcode chose and that bundle identifier as
  the signing values above. Set "Derived data folder" to the build's derived data
  folder: the `~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*`
  folder whose `Build/Products/Debug-iphoneos` holds
  `WebDriverAgentRunner-Runner.app` (Xcode, Settings, Locations shows the root).
  Even with a prebuilt WebDriverAgent the driver still runs `xcodebuild
  test-without-building`, which installs and launches that build. Without a
  derived data folder, Xcode picks the folder from the project path the driver
  opens, which is the symlink-resolved path. If you opened the project in Xcode
  through a different path, for example through a symbolic link, the driver looks
  in another, empty folder, and the startup fails with
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
visto doctor
```

Doctor reads the local toolchain and settings only. It contacts neither an iOS
device nor the provider. On macOS it adds the `xcrun simctl` and `xcrun devicectl`
checks, whether the three signing values are set (values are never shown), the
WebDriverAgent project path and the driver-change notice. Signing and device
tooling are needed for a phone only, so a simulator-only setup can ignore them.

`visto doctor --json --platform ios` adds `xcrun_present`,
`simulator_tooling_present`, `device_tooling_present` and
`wda_signing_configured` to the JSON output. It exits 2 when any check fails or
`xcrun` or the simulator tooling is missing; device tooling and signing are
reported but do not change the exit code.

The console and `GET /readiness` expose `platforms`. It lists which device
sources are configured on the server, not what the machine can drive.

## Start a run

Pick the device in the console list (iOS entries show their platform), or pass
the platform on the CLI (`--platform ios` exists only on macOS):

```sh
visto run --platform ios --device <udid> --goal "..."
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

- The Appium log, `~/.visto/logs/appium.log`. At Visto's `--log-level warn` it
  shows `Unable to launch WebDriverAgent` and the `xcodebuild` exit code, not the
  reason. The log is private: it may contain entered text.
- The `xcodebuild` test result in the derived data folder the driver used,
  `<derived-data>/Logs/Test/Test-WebDriverAgentRunner-<timestamp>.xcresult`.
  Print its errors with
  `xcrun xcresulttool get build-results --path <xcresult>`. These results name
  the phone; do not copy them into reports.

| Error in the test result | Cause and fix |
|---|---|
| "Failed to install the app on the device" … "The file doesn't exist" | No runner build in that folder: set "Derived data folder" in Settings to the folder that holds it and save |
| "The Developer App Certificate is not trusted" | [Trust the developer profile](#trust-the-developer-profile) on the phone |

A new `WebDriverAgent-*` folder that appears under derived data with no
`Build/Products` is the trace of the first case.

## Recovery of a retained lease

An uncertain mutation, an unusable session, a failed startup or a failed cleanup
retains the ownership marker, as on Android. A retained lease needs manual
recovery:

1. Stop the runner (which stops the Appium it started), and confirm no WebDriverAgent session is still
   active on the target. Appium refuses `GET /appium/sessions` unless its
   `session_discovery` feature is enabled; a session start that failed before
   WebDriverAgent launched, as in the table above, created no session.
2. Inspect the marker in `~/.visto/data/device-leases` (device, run, PID;
   `visto doctor` lists it) and the run's
   stored intent and receipt. Do not infer a verdict from a lost transport.
3. Delete only that marker once the target is idle. Its name is the SHA-256 of
   the device identifier: `printf %s '<udid>' | shasum -a 256`, plus `.lease`.
4. Start Visto again and start a new run from a fresh observation.

Screenshots may contain private data and Appium logs may contain entered text;
see [Android setup](android-setup.md#exclusive-ownership-and-crash-recovery)
for the shared lease model.
