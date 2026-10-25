# iOS Platform Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Visto a first-class iOS platform — simulator and USB iPhone — behind the existing `Device` port, with the same commands, console, API, CLI and evidence as Android.

**Architecture:** The platform-specific parts of the current Android adapter are the Appium capability set, the geometry of a frame, and the translation of a `DeviceCommand` into wire calls. Everything else — the HTTP wire, PNG framing checks, the fail-closed lease marker, the single-operation thread guard, source-frame validation and the receipt/uncertainty semantics — is platform-neutral and moves into a shared `adapters/appium` core that both adapters orchestrate. iOS adds a geometry module that converts screenshot pixels into the points the gesture API expects, an inventory over Xcode's command-line tools, and its own instruction notes rendered from a shared instruction core. Platform travels from the console through the API into composition, which picks the adapter; domain and application stay platform-neutral.

**Tech Stack:** Python 3.13 + FastAPI, Appium 3 (XCUITest driver, WebDriverAgent), Xcode 26.2 command-line tools (`simctl`, `devicectl`), React 19 + TypeScript, SQLite, `pytest`, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-20-ios-platform-support-design.md`

## Global Constraints

- Dependency direction domain <- application <- adapters, wired in composition; no Appium, FastAPI, SDK or UI imports in `domain`/`application`. `backend/tests/test_architecture.py` enforces this.
- Adapter version strings: Android stays `appium-wire-v1`; iOS is `appium-xcuitest-v1`. Instruction versions: Android stays `android-agent-v3`; iOS is `ios-agent-v1`.
- Android's rendered instruction text must stay byte-identical; its prompt version is not bumped and its live evidence stays valid.
- No generic shell for the product AI. Inventory commands are fixed, bounded, read-only, and never echo raw output; `PortError` and inventory errors carry no local paths, process output or credentials.
- Device execution after possible dispatch returns `ReceiptStatus.UNCERTAIN`, never an exception that invites a retry. The lease marker is released only when it is certain no remote session exists.
- A run never boots a simulator and never shuts one down; readiness is an operator pre-step. The existing 60000 ms `max_command_timeout_ms` cap is unchanged and no startup budget is added to `RunLimits`, the API, the console or the CLI.
- Signing inputs for WebDriverAgent (team identifier, signing identity, bundle identifier) are operator-supplied configuration, never committed. A free Apple team re-signs every seven days.
- Anonymity: no device serials, UDIDs, model or marketing names, build fingerprints, account names, real application names or package identifiers in source, tests, fixtures, docs, commit messages or reports. Fixtures use invented names such as `device-A`, `Example Phone 1`.
- Checks: `python scripts/verify.py` for code, `python scripts/check_project.py` after editing docs. Do not commit beyond the per-task commits this plan specifies; do not push or change remotes.

## Review Focus

- **Scale drift**: a screenshot-to-point ratio that is non-integral, non-uniform across axes, or inconsistent with the captured image must refuse the device with an explicit failure, never silently round. Pinned in Task 3.
- **Platform/device mismatch**: an Android serial requested as iOS (or the reverse) must fail closed at session start with no leftover lease that a later run cannot explain. Pinned in Task 5.
- **Missing platform tooling**: with Xcode absent (any Windows or Linux host) the listing still returns Android devices and explains iOS in a note, never a global error; with `adb` absent the reverse holds. Pinned in Task 4.
- **Runs stored before this change**: history, reports and the run-configuration view must still render runs whose configuration says `appium-wire-v1` and carries no platform. Pinned in Task 7.
- **`type_text` with no focused field on iOS**: a `REJECTED` receipt saying nothing was typed, exactly as Android behaves, rather than text sent to whatever happens to be focused. Pinned in Task 5.

---

### Task 1: Shared Appium session core

**Files:**
- Create: `backend/src/visto/adapters/appium/__init__.py`
- Create: `backend/src/visto/adapters/appium/wire.py`
- Create: `backend/src/visto/adapters/appium/png.py`
- Create: `backend/src/visto/adapters/appium/session.py`
- Modify: `backend/src/visto/adapters/android/device.py` (orchestration moves out; capabilities, rotation, image and command translation stay)
- Test: `backend/tests/test_appium_core.py` (new), `backend/tests/test_android.py` (must stay unmodified and green)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `wire.Wire` protocol with `request(method: str, path: str, body: dict | None, timeout_ms: int) -> dict`, `wire.HttpWire(server_url: str)`, `wire.MAX_RESPONSE: int`.
  - `png.png_size(content: bytes, component: str) -> tuple[int, int]` raising `PortError` prefixed with `component`.
  - `session.AppiumSession`, the base class both adapters extend:
    - `__init__(self, component: str, version: str, wire: Wire, lease_directory: Path, *, request_timeout_ms: int = 30000, cleanup_timeout_ms: int = 5000)`
    - `async acquire(run_id: str, device_id: str, timeout_ms: int) -> DeviceLease`
    - `async release(lease: DeviceLease) -> None`
    - `async observe(lease: DeviceLease, timeout_ms: int) -> CapturedImage`
    - `async execute(lease: DeviceLease, action: Action, source: Observation) -> TechnicalReceipt`
    - abstract hooks a subclass implements: `capabilities(device_id: str) -> dict`, `capture(lease, deadline, stop) -> CapturedImage`, `translate(command: DeviceCommand, lease, deadline, stop) -> tuple[str, dict]`
    - protected helpers available to subclasses: `_request`, `_owned`, `_path`, `_capture` (last capture), `_uncertain`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_appium_core.py`, with a `FakeWire` like the one in `test_android.py` and a minimal `AppiumSession` subclass named `StubDevice` whose `capabilities` returns `{"platformName": "Stub"}`, `capture` returns a fixed `CapturedImage`, and `translate` returns `("/actions", {})`:

```python
def test_session_component_prefixes_sanitized_errors()      # PortError text starts with "stub: "
def test_second_session_on_same_device_is_refused()          # two StubDevice instances, same lease dir and device id -> PortError
def test_marker_is_retained_when_session_creation_fails()    # wire raises on POST /session -> marker file still exists
def test_dispatch_failure_after_mutation_returns_uncertain() # receipt status UNCERTAIN, further execute rejected
def test_release_without_acquire_is_a_noop()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_appium_core.py -v`
Expected: FAIL with an import error for `visto.adapters.appium`.

- [ ] **Step 3: Create the shared core**

Move `Wire`, `HttpWire`, `MAX_RESPONSE` into `wire.py` and `_png_size` into `png.py` as `png_size(content, component)`. Move `_positive`, `_run`, `_request`, `_owned`, `_path`, `acquire`, `release`, `observe`, `_validate_source` and `execute` into `AppiumSession`, replacing the hard-coded `"android: "` message prefix with the `component` argument and the hard-coded capability dict, image capture and command translation with the three hooks. Keep `_NoFocusedField` in the core, since the `REJECTED` receipt it produces is shared semantics.

- [ ] **Step 4: Make the Android adapter a subclass**

`AppiumDevice(AppiumSession)` in `backend/src/visto/adapters/android/device.py` keeps `version = "appium-wire-v1"`, its existing constructor signature (`server_url`, `lease_directory`, `request_timeout_ms`, `cleanup_timeout_ms`, `wire`), passes `component="android"`, and implements the three hooks with today's code: the UiAutomator2 capability dict, `_rotation`/`_image` as `capture`, and the keycode/actions/`element/value` translation. Observable behaviour, message strings and public names do not change.

- [ ] **Step 5: Run both test files**

Run: `cd backend && python -m pytest tests/test_appium_core.py tests/test_android.py -v`
Expected: PASS, with `tests/test_android.py` unmodified (`git diff --exit-code tests/test_android.py` is clean).

- [ ] **Step 6: Run the architecture guard and linter**

Run: `cd backend && python -m pytest tests/test_architecture.py -v && python -m ruff check src tests && python -m ruff format --check src tests`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/visto/adapters/appium backend/src/visto/adapters/android/device.py backend/tests/test_appium_core.py
git commit -m "refactor: extract platform-neutral Appium session core"
```

---

### Task 2: Platform-neutral device inventory types

**Files:**
- Create: `backend/src/visto/adapters/devices.py`
- Modify: `backend/src/visto/adapters/android/inventory.py` (re-export the shared dataclass, tag entries `Platform.ANDROID`)
- Modify: `backend/src/visto/adapters/api/service.py:205-245` (`devices()` payload)
- Modify: `docs/api-contract.md:30-36`
- Test: `backend/tests/test_device_inventory.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `devices.Platform` — `StrEnum` with `ANDROID = "android"`, `IOS = "ios"`.
  - `devices.AttachedDevice` — frozen slots dataclass `(platform: Platform, serial: str, state: str, model: str | None = None, product: str | None = None)` with `selectable: bool` as a property: `True` for `(ANDROID, "device")`, `(IOS, "booted")` and `(IOS, "connected")`, `False` otherwise.
  - `devices.InventoryUnavailable` — the existing exception, moved here and re-exported from the Android module.
  - `GET /devices` entries gain `"platform"`; `selectable` now comes from the property.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_device_inventory.py`:

```python
def test_selectability_is_platform_specific():
    assert AttachedDevice(Platform.ANDROID, "device-A", "device").selectable is True
    assert AttachedDevice(Platform.ANDROID, "device-A", "unauthorized").selectable is False
    assert AttachedDevice(Platform.IOS, "device-B", "booted").selectable is True
    assert AttachedDevice(Platform.IOS, "device-B", "shutdown").selectable is False
    assert AttachedDevice(Platform.IOS, "device-B", "connected").selectable is True

def test_adb_parsing_tags_every_entry_as_android():  # parse_devices output, unchanged fields
```

In `backend/tests/test_api.py`, extend the existing `/devices` test so each returned entry has `"platform": "android"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_device_inventory.py tests/test_api.py -k devices -v`
Expected: FAIL with an import error for `visto.adapters.devices`.

- [ ] **Step 3: Implement the shared module and update the listing**

Create `devices.py` as specified; keep `find_adb`, `parse_devices`, `_run` and `list_devices` in the Android module, importing the shared dataclass and passing `Platform.ANDROID`. In `service.devices()`, serialize `"platform": item.platform.value` and `"selectable": item.selectable`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_device_inventory.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Document the contract change**

In `docs/api-contract.md`, update the `GET /devices` entry to `{available, devices:[{serial,platform,state,model,product,selectable}], error, notes}`, state that `platform` is `"android"` or `"ios"`, and that selectability is platform-specific (`device` for Android; `booted` or `connected` for iOS). Leave the adb description in place and add that iOS entries come from Xcode's command-line tools.

- [ ] **Step 6: Run the docs check**

Run: `python scripts/check_project.py`
Expected: `Companion integrity OK`.

- [ ] **Step 7: Commit**

```bash
git add backend/src/visto/adapters/devices.py backend/src/visto/adapters/android/inventory.py backend/src/visto/adapters/api/service.py backend/tests/test_device_inventory.py backend/tests/test_api.py docs/api-contract.md
git commit -m "feat: tag device inventory entries with their platform"
```

---

### Task 3: iOS frame geometry

**Files:**
- Create: `backend/src/visto/adapters/ios/__init__.py`
- Create: `backend/src/visto/adapters/ios/geometry.py`
- Test: `backend/tests/test_ios_geometry.py`

**Interfaces:**
- Consumes: `PortError` from `visto.application.ports`.
- Produces:
  - `geometry.Frame` — frozen slots dataclass `(width: int, height: int, point_width: int, point_height: int, scale: float)` where `width`/`height` are screenshot pixels.
  - `geometry.frame(pixel_width: int, pixel_height: int, point_width: int, point_height: int, *, tolerance: float = 0.02) -> Frame` — derives the scale, requires both axes to agree within `tolerance` relative difference, and raises `PortError("ios: inconsistent screen scale")` otherwise. A zero or negative dimension raises `PortError("ios: invalid screen dimensions")`.
  - `geometry.to_points(frame: Frame, x: int, y: int) -> tuple[int, int]` — converts a source-screenshot pixel to the integer point the gesture API receives, rounding half away from zero and clamping to `point_width - 1` / `point_height - 1`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ios_geometry.py`:

```python
def test_integral_scales_are_accepted():          # 2x: 750x1334 px over 375x667 pt -> scale 2.0; 3x likewise
def test_non_integral_scale_is_supported():       # 1080x1920 px over 414x736 pt -> scale ~2.6087, both axes agree
def test_non_uniform_scale_is_refused():          # 1080x1920 px over 414x667 pt -> PortError "ios: inconsistent screen scale"
def test_invalid_dimensions_are_refused():        # a zero or negative dimension -> PortError
def test_points_round_half_away_from_zero_and_clamp():
    f = frame(1080, 1920, 414, 736)
    assert to_points(f, 0, 0) == (0, 0)
    assert to_points(f, 1079, 1919) == (413, 735)
    assert to_points(f, 540, 960) == (207, 368)
def test_landscape_frame_uses_the_reported_orientation_dimensions():  # 1920x1080 px over 736x414 pt
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ios_geometry.py -v`
Expected: FAIL with an import error for `visto.adapters.ios`.

- [ ] **Step 3: Implement `frame` and `to_points` in `geometry.py`**

Compute each axis's ratio in floating point, compare them relative to the larger, and keep the mean as `scale`. Use `decimal` or an explicit `floor(value + 0.5)` for rounding; Python's built-in `round` is banker's rounding and would be off by one at exact halves.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ios_geometry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/visto/adapters/ios backend/tests/test_ios_geometry.py
git commit -m "feat: add iOS screenshot-to-point geometry with explicit scale validation"
```

---

### Task 4: iOS device inventory

**Files:**
- Create: `backend/src/visto/adapters/ios/inventory.py`
- Modify: `backend/src/visto/adapters/api/service.py` (`devices()` merges both platforms and reports per-platform notes)
- Modify: `backend/src/visto/composition.py:30-40` (wire the iOS lister)
- Test: `backend/tests/test_ios_inventory.py` (new), `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `devices.AttachedDevice`, `devices.Platform`, `devices.InventoryUnavailable` (Task 2).
- Produces:
  - `inventory.find_xcrun(environ: dict[str, str] | None = None) -> Path | None`
  - `inventory.parse_simulators(payload: str) -> tuple[AttachedDevice, ...]` — from `xcrun simctl list devices --json`; state `Booted` becomes `"booted"`, anything else `"shutdown"`; unavailable simulators are skipped; `model` is the simulator's device-type name, `product` is its runtime identifier.
  - `inventory.parse_physical(payload: str) -> tuple[AttachedDevice, ...]` — from `xcrun devicectl list devices --json`; a paired, connected device becomes `"connected"`, anything else `"unavailable"`.
  - `async inventory.list_devices(xcrun: Path | None, timeout_s: float = 10.0) -> tuple[AttachedDevice, ...]` — runs both fixed commands in a worker thread with `stdin=DEVNULL`, output capped at 1 MiB, and raises `InventoryUnavailable` with a safe message when `xcrun` is missing, times out or exits non-zero.
  - `ExecutionService.ios_device_lister` — optional callable with the same shape as `device_lister`.
  - `GET /devices` returns the concatenation of both platforms' entries; when one platform's tooling is unavailable the other platform's devices are still returned and the reason appears in `notes`. `available` is `false` only when neither platform can be listed.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ios_inventory.py`, with invented fixture payloads (device-type names like `"Example Simulator 1"`, UDIDs like `"00000000-0000-0000-0000-00000000000A"`):

```python
def test_booted_simulator_is_selectable_and_shutdown_is_not()
def test_unavailable_simulator_runtimes_are_skipped()
def test_connected_physical_device_is_selectable()
def test_unpaired_physical_device_is_listed_as_unavailable()
def test_malformed_payload_raises_inventory_unavailable_without_echoing_it()
def test_missing_xcrun_explains_the_prerequisite()
```

In `backend/tests/test_api.py`:

```python
async def test_devices_merges_platforms_and_notes_a_missing_toolchain()
    # android lister returns one device, ios lister raises InventoryUnavailable
    # -> available is True, one android entry, the iOS reason present in notes
async def test_devices_unavailable_only_when_both_platforms_fail()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ios_inventory.py tests/test_api.py -k "devices or inventory" -v`
Expected: FAIL with an import error for `visto.adapters.ios.inventory`.

- [ ] **Step 3: Verify the inventory commands against official documentation**

Confirm the JSON shapes of `xcrun simctl list devices --json` and `xcrun devicectl list devices --json` on Xcode 26.2 and add both to `docs/references.md` under a new "iOS" heading, alongside the Appium XCUITest driver's capability reference. Record the fixtures from a real local invocation with every identifying value replaced by invented placeholders.

- [ ] **Step 4: Implement the inventory and the merged listing**

Mirror the Android module's shape: fixed argument vectors, no shell, bounded output, sanitized exceptions. In `service.devices()`, call each configured lister, collect successes, and turn each `InventoryUnavailable` into a note.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ios_inventory.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/visto/adapters/ios/inventory.py backend/src/visto/adapters/api/service.py backend/src/visto/composition.py backend/tests/test_ios_inventory.py backend/tests/test_api.py docs/references.md
git commit -m "feat: list iOS simulators and attached devices alongside Android"
```

---

### Task 5: iOS device adapter

**Files:**
- Create: `backend/src/visto/adapters/ios/device.py`
- Modify: `backend/src/visto/adapters/ios/__init__.py` (export `XCUITestDevice`)
- Test: `backend/tests/test_ios_device.py`

**Interfaces:**
- Consumes: `AppiumSession`, `wire.Wire`, `png.png_size` (Task 1); `geometry.frame`, `geometry.to_points` (Task 3).
- Produces: `device.XCUITestDevice(AppiumSession)` with `version = "appium-xcuitest-v1"`, constructor `(server_url: str, lease_directory: Path, *, request_timeout_ms: int = 30000, cleanup_timeout_ms: int = 5000, wire: Wire | None = None)` and `component="ios"`.

**Platform specifics this task fixes:**
- Capabilities: `platformName: "iOS"`, `appium:automationName: "XCUITest"`, `appium:udid`, `appium:noReset: True`, `appium:fullReset: False`, `appium:autoLaunch: False`, `appium:shouldTerminateApp: False`, `appium:newCommandTimeout: 120`, plus the WebDriverAgent signing values read from the environment (`VISTO_IOS_TEAM_ID`, `VISTO_IOS_SIGNING_ID`, `VISTO_IOS_WDA_BUNDLE_ID`) and omitted when unset. `appium:usePrebuiltWDA` is on for a physical device so a run never rebuilds WebDriverAgent; the operator pre-step installs it.
- `capture`: read the orientation, the screenshot and the window size, build a `Frame`, and re-read the orientation afterwards, failing with `PortError("ios: orientation changed during screenshot")` when it moved. The `CapturedImage` carries screenshot pixels and the rotation in the same vocabulary Android uses (0/90/180/270).
- `translate`: pointer actions in points via `to_points`; `back` is a pointer swipe from `x = 0` to `x = point_width // 2` at the vertical middle over 300 ms; `home` is `mobile: pressButton` with `{"name": "home"}`; `enter` is `\n` sent to the focused element; `type_text` sets the focused element's value in one call, reusing the core's focused-element lookup and its `REJECTED` receipt when nothing has focus.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ios_device.py`, with the `FakeWire`/`png` helpers from `test_android.py` extended to answer the window-size and orientation routes:

```python
async def test_session_capabilities_target_xcuitest_and_do_not_launch_an_app()
async def test_signing_capabilities_appear_only_when_configured()
async def test_tap_is_dispatched_in_points_not_pixels()        # 3x frame, pixel (300, 600) -> point (100, 200)
async def test_back_is_dispatched_as_a_swipe_from_the_left_edge()
async def test_home_uses_the_press_button_script()
async def test_enter_sends_a_newline_to_the_focused_element()
async def test_type_text_without_focus_is_rejected_and_types_nothing()
async def test_orientation_change_during_capture_is_an_error()
async def test_inconsistent_scale_refuses_the_device()          # window size disagreeing with the screenshot
async def test_android_serial_fails_closed_and_leaves_no_usable_lease()
    # session creation refused by the wire -> PortError, marker retained, a second
    # XCUITestDevice on the same device id is refused rather than silently sharing
async def test_mutation_failure_after_dispatch_returns_uncertain()
async def test_a_session_created_despite_a_failed_startup_is_reconciled()
    # the wire answers POST /session with a session id and then fails the first
    # follow-up call: the adapter deletes that session within the cleanup timeout
    # and releases the marker, so a later run can take the device
async def test_a_reconciliation_that_itself_fails_retains_the_marker()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ios_device.py -v`
Expected: FAIL with an import error for `XCUITestDevice`.

- [ ] **Step 3: Verify the XCUITest routes against official documentation**

Confirm the window-size, orientation, screenshot, `mobile: pressButton` and element-value routes for the pinned XCUITest driver, and add the reference to `docs/references.md`.

- [ ] **Step 4: Implement `XCUITestDevice` in `device.py`**

Three hooks, plus the bounded startup reconciliation the design requires: when
session creation returns an id but the session is not usable, attempt one delete
within `cleanup_timeout_ms` and release the marker only if that delete is certain;
otherwise retain the marker and raise with the recovery message. Everything else
comes from `AppiumSession`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ios_device.py tests/test_android.py tests/test_appium_core.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/visto/adapters/ios backend/tests/test_ios_device.py docs/references.md
git commit -m "feat: add the iOS XCUITest device adapter"
```

---

### Task 6: Instruction core and platform notes

**Files:**
- Create: `backend/prompts/agent-core.md`
- Modify: `backend/prompts/android-agent-v3.md` (becomes the Android notes fragment)
- Create: `backend/prompts/ios-agent-v1.md`
- Modify: `backend/src/visto/adapters/ai/openai.py:21-42`
- Modify: `backend/src/visto/adapters/ai/__init__.py` (export the renderer and the version map)
- Modify: `docs/provider-setup.md:46`
- Test: `backend/tests/test_ai.py`

**Interfaces:**
- Consumes: `devices.Platform` (Task 2).
- Produces:
  - `openai.INSTRUCTION_VERSIONS: dict[Platform, str]` — `{ANDROID: "android-agent-v3", IOS: "ios-agent-v1"}`.
  - `openai.load_instructions(platform: Platform = Platform.ANDROID) -> str` — renders `agent-core.md` with `{{PLATFORM}}` replaced by `"Android"`/`"iOS"` and `{{PLATFORM_NOTES}}` replaced by that platform's notes file, both resolved as packaged resources with the existing source-tree fallback.
  - `OpenAIAgent(api_key, model, *, platform: Platform = Platform.ANDROID, ...)`, whose identity check compares `identity.instruction_version` with `INSTRUCTION_VERSIONS[platform]`.
  - `INSTRUCTION_VERSION` remains exported as the Android value so existing importers keep working.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ai.py`:

```python
ANDROID_INSTRUCTIONS_SHA256 = "<digest of git show HEAD:backend/prompts/android-agent-v3.md>"

def test_android_instructions_are_byte_identical_after_refactoring():
    rendered = load_instructions(Platform.ANDROID)
    assert hashlib.sha256(rendered.encode()).hexdigest() == ANDROID_INSTRUCTIONS_SHA256

def test_ios_instructions_name_the_platform_and_its_navigation_reality():
    text = load_instructions(Platform.IOS)
    assert "iOS test agent" in text and "Android" not in text
    assert "may not navigate" in text and "home screen" in text

def test_identity_mismatch_rejects_the_other_platform_version():
    # an iOS agent given a run configured with android-agent-v3 raises PortError
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ai.py -v`
Expected: FAIL — `load_instructions` takes no argument.

- [ ] **Step 3: Split the prompt**

Compute the digest with `git show HEAD:backend/prompts/android-agent-v3.md | shasum -a 256` and put it in the test. Copy the current text into `agent-core.md`, replacing `Android` in the first sentence with `{{PLATFORM}}` and the sentence `back and home are device keys.` with `{{PLATFORM_NOTES}}`. Reduce `android-agent-v3.md` to exactly `back and home are device keys.` (no trailing newline beyond what reproduces the original bytes). Write `ios-agent-v1.md` with the iOS reality in the same terse register: `back` is a swipe from the left screen edge that may not navigate — when the screen is unchanged, use the visible back control at the top left or the sheet's own dismiss control; the home screen has several pages that may need swiping to find an app; primary navigation controls sit at the top of the screen.

- [ ] **Step 4: Implement the renderer**

Replace `load_instructions` with the platform-aware version and thread `platform` through `OpenAIAgent`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ai.py -v`
Expected: PASS, including the byte-identical Android digest.

- [ ] **Step 6: Update the provider documentation**

In `docs/provider-setup.md`, describe the instruction resources as a shared core plus one versioned notes file per platform, naming both versions.

- [ ] **Step 7: Commit**

```bash
git add backend/prompts backend/src/visto/adapters/ai backend/tests/test_ai.py docs/provider-setup.md
git commit -m "feat: render agent instructions per platform from a shared core"
```

---

### Task 7: Platform plumbing through composition, API and CLI

**Files:**
- Modify: `backend/src/visto/runner.py` (`RunnerSettings.platform`, adapter selection, per-platform versions)
- Modify: `backend/src/visto/adapters/api/execution.py:34` (`RunRequest.platform`)
- Modify: `backend/src/visto/adapters/api/service.py` (pass the platform into `RunnerSettings`; readiness reports the platforms this process can drive)
- Modify: `backend/src/visto/cli.py:36-80,225-265` (`--platform`, iOS doctor checks)
- Modify: `docs/api-contract.md`
- Test: `backend/tests/test_api.py`, `backend/tests/test_cli.py`, `backend/tests/test_contracts.py`

**Interfaces:**
- Consumes: `XCUITestDevice` (Task 5), `INSTRUCTION_VERSIONS` and `load_instructions` (Task 6), `Platform` (Task 2).
- Produces:
  - `RunnerSettings(..., platform: Platform = Platform.ANDROID)`; `build_runtime` constructs `AppiumDevice` or `XCUITestDevice` from it; `new_run` writes `device_adapter_version` from the chosen adapter class's `version` and `instruction_version` from `INSTRUCTION_VERSIONS[platform]`.
  - `POST /runs` accepts optional `"platform": "android" | "ios"`, defaulting to `"android"`; an unknown value is 422.
  - `GET /readiness` gains `"platforms": ["android", ...]` listing what this process can drive, derived from which listers are configured.
  - `visto doctor --platform ios` reports `xcrun_present`, `simulator_tooling_present`, `device_tooling_present`, `wda_signing_configured` and `device_contacted: false`, exiting 2 when a prerequisite is missing.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_api.py`:

```python
async def test_run_creation_defaults_to_android_and_accepts_ios()
    # the ios request produces a RunnerSettings with Platform.IOS and a run whose
    # configuration carries "appium-xcuitest-v1" and "ios-agent-v1"
async def test_unknown_platform_is_rejected_with_422()
```

In `backend/tests/test_contracts.py`:

```python
def test_a_run_stored_before_platforms_existed_still_decodes()
    # a RunConfiguration with device_adapter_version "appium-wire-v1" and no platform
    # field round-trips through the storage codec and the public projection
```

In `backend/tests/test_cli.py`:

```python
def test_doctor_reports_ios_prerequisites_without_contacting_a_device()
def test_run_rejects_an_unknown_platform()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py tests/test_cli.py tests/test_contracts.py -v`
Expected: FAIL — `platform` is not accepted.

- [ ] **Step 3: Implement the plumbing**

Thread `platform` from request to `RunnerSettings` to `build_runtime`; select the adapter there and nowhere else. Keep `Platform` out of `domain` and `application`: the stored run records the platform only through the existing adapter and instruction version strings.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest -v`
Expected: PASS.

- [ ] **Step 5: Document the API change**

In `docs/api-contract.md`, add `platform` to the `POST /runs` body with its default and its 422, and add `platforms` to the readiness response.

- [ ] **Step 6: Commit**

```bash
git add backend/src/visto/runner.py backend/src/visto/adapters/api backend/src/visto/cli.py backend/tests docs/api-contract.md
git commit -m "feat: select the device adapter from the requested platform"
```

---

### Task 8: One console for both platforms

**Files:**
- Modify: `frontend/src/console.ts:261-309` (types, parsing, labels)
- Modify: `frontend/src/components/DeviceSelect.tsx` (platform in the option text and the refresh hint)
- Modify: `frontend/src/components/NewRunForm.tsx` and `frontend/src/form.ts` (send the selected device's platform)
- Test: `frontend/tests/devices.test.mjs`, `frontend/tests/form.test.mjs`

**Interfaces:**
- Consumes: the `GET /devices` and `POST /runs` shapes from Tasks 2, 4 and 7.
- Produces: `AttachedDevice` gains `platform: 'android' | 'ios'`; `parseDevices` drops entries whose platform it does not know; `deviceLabel` names the platform; the run request carries `platform`.

- [ ] **Step 1: Write the failing test**

In `frontend/tests/devices.test.mjs`:

```javascript
test('entries carry a known platform or are dropped')              // 'android', 'ios', and an unknown value
test('selectability follows the platform vocabulary')              // android 'device'; ios 'booted'/'connected'; ios 'shutdown' not selectable
test('labels say which platform a device is')                      // deviceLabel includes 'iOS'
test('a shut-down simulator explains that it must be booted first')
```

In `frontend/tests/form.test.mjs`: the submitted body carries the selected device's platform.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm test`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the console changes**

Keep the existing defence in depth: `selectable` requires both the server's flag and a state this console recognises for that platform. Add iOS hints to `STATE_HINTS` keyed by platform, including `shutdown: 'not booted: start the simulator from Xcode first'`.

- [ ] **Step 4: Run the frontend checks**

Run: `cd frontend && pnpm test && pnpm run lint && pnpm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat: show both platforms in the console device picker"
```

---

### Task 9: Operator documentation

**Files:**
- Create: `docs/ios-setup.md`
- Modify: `docs/local-development.md` (what each host can drive)
- Modify: `docs/web-console.md` (platform in the picker)
- Modify: `docs/first-device-test.md` (the iOS first run)
- Modify: `docs/ai-context/02-stack.md`, `docs/ai-context/07-integrations.md`, `docs/ai-context/04-structure.md`
- Test: `python scripts/check_project.py`

**Interfaces:**
- Consumes: the behaviour built in Tasks 1-8.
- Produces: `docs/ios-setup.md` covering the Appium XCUITest driver install, the free-Apple-team signing values and their seven-day expiry, the operator pre-step (boot the simulator, install WebDriverAgent, trust the developer on the phone), the environment variables Task 5 reads, how `doctor --platform ios` reports readiness, and the manual recovery path for a retained lease.

- [ ] **Step 1: Write `docs/ios-setup.md`**

Describe the current state only: no history, no dated notes, no machine-specific paths, no device identifiers. Say plainly that a run never boots a simulator and never builds WebDriverAgent, and what the operator does instead.

- [ ] **Step 2: State each host's capabilities**

In `docs/local-development.md`, add the host table: Windows and Linux drive Android only; macOS drives Android and iOS and is the only way to see both platforms in one picker. Note that macOS needs a locally installed Appium with both drivers.

- [ ] **Step 3: Run the docs check**

Run: `python scripts/check_project.py`
Expected: `Companion integrity OK`.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs: document iOS setup and what each execution mode can drive"
```

---

### Task 10: Live verification and acceptance

**Files:**
- Modify: `docs/ai-context/STATUS.md` (coordinator-owned; current state, verification state, known issues, next work)
- Test: the whole local suite, then live runs

**Interfaces:**
- Consumes: everything above.
- Produces: recorded evidence for each live layer, and the acceptance verdict.

- [ ] **Step 1: Run the full local suite**

Run: `python scripts/verify.py` and `python scripts/check_project.py`
Expected: PASS. Record the actual commands and results; never summarise a failure as a pass.

- [ ] **Step 2: Simulator live checks**

With a booted simulator and a locally running Appium: `visto doctor --platform ios`, then one short observe-only run, then one run exercising each of the seven commands. Record the receipts and the verdicts. Redact nothing into the repository that identifies the machine, and name no real application.

- [ ] **Step 3: Physical device live checks**

With the phone attached, WebDriverAgent installed and trusted: repeat Step 2's sequence. Confirm that a refused session leaves a lease the operator can recover following `docs/ios-setup.md`, and that an unreachable Appium server produces an infrastructure failure rather than a verdict.

- [ ] **Step 4: Android re-check on macOS**

One short Android run with the backend running on macOS and a locally
installed Appium with both drivers, to verify the setup the single picker depends
on. Record the result; a failure here is a finding about that setup, not about iOS.

- [ ] **Step 5: Acceptance scenario on both targets**

Run the owner's scenario — open a web browser from the home screen, navigate to a public search page, search a short term, open a specific result if present — on the simulator and on the phone. Acceptance is a `passed` conclusion on both.

Stop rule: at most six live attempts per target. Instruction changes between attempts may only add true platform facts; they may not weaken what counts as success, hint at the expected outcome, narrow the scenario, or touch the verdict path. If six attempts do not produce a pass, stop and report the transcripts and the suspected cause.

- [ ] **Step 6: Update STATUS and commit**

Record what is implemented, which layers were verified live and which were not, any new known issues, and the next work. State plainly that model judgement quality remains unevaluated until the labelled protocol runs.

```bash
git add docs/ai-context/STATUS.md
git commit -m "docs: record iOS implementation and verification state"
```
