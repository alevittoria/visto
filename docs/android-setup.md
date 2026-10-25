# Android device setup

This adapter implements the application's Device port over W3C WebDriver and
Appium extensions with Python's standard library; no Python Appium SDK is needed.
Local fake-wire checks do not establish real-device compatibility. Live use
requires an authorized Android device and a separately configured provider (see
the [first device test](first-device-test.md)).

## Server versions and prerequisites

Appium **3.8.0** and UiAutomator2 **8.7.0** are installed from
`tools/appium/package.json` and its frozen pnpm lock (on macOS from
`tools/appium/macos`, which adds the XCUITest driver). They use the local
Android SDK and JDK; see [installation](local-development.md) for the
prerequisites, the environment variables and starting Appium. The backend
reaches Appium on loopback at `http://127.0.0.1:4723`.

## Connect a device

UiAutomator2 8 requires Android 8/Oreo (API 26) or newer.

1. On the phone, enable Developer options (tap Build number seven times), then
   USB debugging.
2. Connect it by USB and accept the "Allow USB debugging" prompt for this
   computer ("Always allow" keeps it authorized).
3. Unlock the screen and manually open the application under test in its
   intended initial state.
4. Check that the device is listed as `device`; `unauthorized` means the prompt
   was not accepted yet:

```sh
adb devices -l
```

The backend starts the adb server when it starts (`adb start-server`), so the
console lists devices right away; the server keeps running when the backend
stops. The runner never chooses the first attached device: pick the serial
explicitly in the console or pass it to the CLI.

### Wireless debugging

On Android 11 or newer the phone can also connect over Wi-Fi, on the same network
as the computer. In Developer options open Wireless debugging, choose "Pair
device with pairing code", then:

```sh
adb pair <ip>:<pairing-port>       # enter the six-digit code
adb connect <ip>:<port>            # the port shown on the Wireless debugging screen
```

The device then appears in `adb devices` as `<ip>:<port>`. Press Refresh in the
console to list it. Reconnect with `adb connect` after the phone or the computer
restarts.

Do not enable relaxed security or the adb_shell insecure feature: this product
exposes no shell command. Appium may install its on-device automation helpers
during the first session. The adapter does not install/reset the target app,
grant its runtime permissions, launch it or automatically terminate it.

## Wire and coordinate contract

Session capabilities bind appium:udid to the exact supplied serial, select
UiAutomator2, set noReset=true, fullReset=false, autoLaunch=false,
shouldTerminateApp=false and skipLogcatCapture=true. Server command inactivity
timeout is 120 seconds; lengthy AI decisions may therefore expire a session and
produce an infrastructure error. No automatic session recreation occurs.

Every capture requests a fresh base64 PNG, validates PNG chunk framing and CRCs,
reads its IHDR width/height, and reads the device's z rotation before/after.
Rotation uses `GET /session/:id/rotation`, the native UiAutomator2 route declared
by the installed AndroidDriver 14.2.0 method map. This is a pinned-stack
compatibility exception: the generic Appium `/appium/device/rotation` route
returns HTTP405 not implemented on Appium 3.8.0 / UiAutomator2 8.7.0, whereas
the native route and screenshot succeed on a real device. See
[references](references.md#android-rotation-compatibility).
The adapter selects this route directly; it does not retry failed requests or
substitute an inferred orientation. That protocol diagnosis is separate from a
successful complete test run or semantic application verification.
Rotation must be 0, 90, 180 or 270 degrees and stable across capture. Bytes are
never cropped, scaled or rotated locally. Observation IDs are assigned by the
application; the adapter returns CapturedImage with timestamp and lease metadata.
The supported coordinate frame is the native screenshot in display pixels,
including system bars. W3C touch actions use the same viewport coordinates.
Before dispatch, the adapter captures again for geometry/rotation checks and
rejects changed geometry, stale source capture metadata/hash, reused source IDs,
wrong scope and out-of-range coordinates. This check does not inspect UI meaning
or prove the screen has remained semantically unchanged. Do not rotate/resize or
interact with the device manually during a run. OEM screenshot/viewport mapping
must be verified on the chosen device; there is no inferred coordinate scaling.

Tap/long_press/swipe use W3C touch pointer actions, ending in pointerUp;
long_press holds with a pointer `pause` of `duration_ms`. Long-press and swipe
durations must fit the action deadline. type_text reads the focused element (W3C Get Active
Element, read-only) and sets its whole value in one W3C Element Send Keys request
with UiAutomator2 `replace: true`, never key by key. No focused field yields a
rejected receipt before any mutation; a failure after dispatch is uncertain. The
active-element lookup is a technical focus query, not a semantic UI predicate.
Home/Back/Enter use mobile:pressKey with Android keycodes 3/4/66. No generic keycode,
shell, element finder or app-specific semantic predicate is exposed.

## Timeouts and uncertain work

Acquire/observe obey their supplied total deadlines; execute uses Action.timeout_ms.
Each wire call receives the smaller remaining budget and request_timeout_ms
(default 30000). Session deletion has a separate cleanup_timeout_ms (default 5000).
Initial on-device helper installation can exceed 30 seconds. Increase the CLI's
explicit command timeout/startup budget before first use if needed, and preserve
a finite wall-time budget. Do not repeatedly start sessions after a timeout.

The async deadline cannot kill an already executing OS thread or a remote server
command. The adapter tracks the shielded worker, prevents new calls/release while
it remains active, and prevents a delayed preflight from dispatching after its
deadline/cancellation. A mutation whose dispatch may have started returns
UNCERTAIN on error/timeout and is never retried. That session permits observation
but rejects further mutations; release attempts session deletion and retains the
lease marker for manual reconciliation. Cleanup failures also retain ownership.
COMPLETED is a technical receipt and says nothing about application success.

## Exclusive ownership and crash recovery

Use one shared lease directory for **all runner processes on this host**. The
CLI composition root resolves `.work/device-leases` from the repository-root
working directory, independently of the run's data directory. Start every CLI
from that same repository root so its absolute lease directory is shared. An O_EXCL file
named SHA256(serial).lease is created before session startup and contains a
random ownership token, PID, run and device IDs. Only the same live adapter/token
may delete it after confirmed session cleanup. There is no automatic stealing,
PID-based reclamation or stale timeout. Failed/unknown session startup retains
its marker too. The marker is a local-process coordination mechanism; separate
machines or unrelated Appium clients are outside that lock, so use one host and
prevent competing manual automation clients.

After a crash, unknown startup, uncertain mutation or cleanup failure:

1. Stop the affected runner and its Appium server; verify its process has exited
   and no automation command/session is still active. Reconcile the device's
   actual state manually. Stop any other client using this device.
2. Inspect the single marker's device_id/run_id/PID and the run's persisted intent
   and receipt. Do not infer an application verdict from a lost transport.
3. Only after the device is idle, delete that exact marker file,
   `.work/device-leases/<hash>.lease`, where `<hash>` is the SHA-256 of the
   serial (`printf %s '<serial>' | sha256sum`; `shasum -a 256` on macOS).
   Never clear all leases while another run might own a device.
4. Restart Appium and create a new run from fresh observations. Automatic resume
   of an interrupted mutation is unsupported.

Screenshot bytes/text may be private. The adapter keeps the latest capture in
process memory; the artifact store persists evidence, and the AI adapter may send
it to the configured provider. Appium itself can log request bodies, entered text,
or device data even at reduced log levels. Treat its local logs as private, keep
them outside source control, and review storage/provider handling before use.

## Official sources

- [Appium 3.8.0 release](https://github.com/appium/appium/releases/tag/appium@3.8.0)
- [UiAutomator2 8.7.0 release](https://github.com/appium/appium-uiautomator2-driver/releases/tag/v8.7.0)
- [Appium requirements](https://appium.io/docs/en/latest/quickstart/requirements/)
- [Extension CLI install specifications](https://appium.io/docs/en/latest/reference/cli/extensions/#install)
- [Package-root extension management](https://appium.io/docs/en/latest/guides/managing-exts/#do-it-yourself-with-npm)
- [UiAutomator2 capabilities and prerequisites](https://github.com/appium/appium-uiautomator2-driver#capabilities)
- [Element Send Keys](https://www.w3.org/TR/webdriver2/#element-send-keys) and
  [Get Active Element](https://www.w3.org/TR/webdriver2/#get-active-element)
- [Android key commands](https://github.com/appium/appium-uiautomator2-driver#mobile-presskey)
- [Appium rotation](https://appium.io/docs/en/latest/reference/api/appium/#getappiumrotation)
- [W3C actions](https://www.w3.org/TR/webdriver2/#perform-actions)
- [W3C screenshot](https://www.w3.org/TR/webdriver2/#take-screenshot)
