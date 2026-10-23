# Design — iOS platform support

Status: approved design, not yet implemented. Written for a builder who knows
mobile automation but not this repository's history.

## Intent and why

Visto claims to be a platform-neutral mobile testing tool, but only Android is
implemented. The owner wants iOS to do everything Android already does, with the
same perceived quality: the same conversational AI loop, the same command
vocabulary, the same console, API and CLI, the same evidence and reports. iOS is
not an experimental subset bolted to the side; it is the second first-class
platform, and its arrival is the proof that the platform-neutral architecture was
real rather than aspirational.

Two target kinds are in scope from the start: the iOS Simulator and an iPhone
attached over USB. Both are verifiable on the owner's machine: Xcode is installed
with an Apple ID configured for signing, and a physical iPhone is available for
testing.

## Goals

- A new `Device` adapter for iOS behind the existing `visto.application.ports.Device`
  port, with no change to the port's meaning.
- The same seven commands on both platforms: `tap`, `long_press`, `swipe`,
  `type_text`, `back`, `home`, `enter`.
- Device discovery for iOS: booted or bootable simulators and USB-attached
  iPhones, listed by the same inventory surface the console already uses.
- One web console serving both platforms: the device dropdown shows Android and
  iOS entries together, with the platform visible, and a run records which
  platform it ran on.
- Platform-aware AI instructions: a shared core with an iOS variant, versioned the
  way `android-agent-v3` is versioned today.
- Honest coordinate fidelity: a tap the AI aims at a pixel in the screenshot it was
  shown lands on that point on the device.
- Documented setup for both target kinds, including the WebDriverAgent signing
  requirement for the physical device.

## Non-goals

- Building, installing or launching an application under test. Android attaches to
  whatever is already on screen (`autoLaunch` false, `noReset` true); iOS does the
  same. No bundle identifier is part of a run.
- Running iOS from the Docker Compose stack. A Linux container cannot reach Xcode,
  `simctl` or a USB-attached iPhone, and no bridge equivalent to the Android host
  adb server exists for iOS.
- Cloud device farms, remote iOS hosts, Android emulators, iPadOS, tvOS.
- Reintroducing static UI predicates, label dictionaries, fixed semantic step
  categories or a deterministic verdict verifier. The AI owns semantic conclusions
  on iOS exactly as it does on Android.
- Changing the domain or application layers' platform neutrality. iOS is an
  adapter plus wiring, not a new concept in the inner layers.

## Anti-goals

These would make the work a failure even if every test passed.

- **Silent coordinate drift.** On iOS the screenshot is in pixels and the gesture
  API speaks points; on a 3x display the numbers differ by a factor of three. A
  conversion that is wrong, or right only on one device class, produces taps that
  land somewhere else while every technical receipt reports success. This is the
  single most dangerous failure mode in this work.
- **A physical path claimed as verified when it was only compiled.** Both target
  kinds are testable here, so both get live evidence, separately reported.
- **Platform leakage inward.** An `if ios` in domain or application, or an iOS SDK
  import above the adapter layer, defeats the purpose of doing this at all.
- **Identifying information in the repository.** Device serials, UDIDs, model or
  marketing names, build fingerprints, account names, and the names or package
  identifiers of real applications and real on-screen content must not appear in
  source, tests, fixtures, docs, commit messages or reports. Use generic
  placeholders and invented, clearly fictional example names.

## Decisions already made

These were settled with the owner and are not open for the builder to revisit.

### Both target kinds, from the start

Simulator and USB iPhone are designed and implemented together, not sequenced.

### `back` is an edge swipe, and the AI adapts when it fails

iOS has no back button. The command vocabulary stays identical across platforms —
the AI does not learn a different alphabet per platform — and on iOS `back` is
executed as a swipe from the left screen edge.

That gesture does not always navigate: modal sheets, pickers and some screens
ignore it. This is accepted, not worked around. The executor reports only that the
gesture was dispatched; it never reports that navigation happened. The AI sees the
following observation, notices the screen did not change, and adapts on its own —
typically by tapping the visible back control at the top left, or a "done" or
"close" affordance. The iOS instructions state this explicitly, so the adaptation
is designed behaviour rather than a lucky recovery.

### iOS runs with the backend started natively on macOS

The Compose stack remains an Android-only mode. Run natively on the Mac, the
backend sees both `adb` and Xcode, which is what makes a single dropdown with both
platforms possible. The documentation must say plainly which capabilities each mode
has, so a user in Docker understands why no iOS device appears.

### One console, one dropdown

No separate iOS screen, tab or mode in the UI. The existing device picker lists
both platforms with the platform visible on each entry, and everything downstream
of device selection looks and behaves as it does today.

### Shared instruction core with an iOS variant

Not one prompt with conditionals, and not two unrelated prompts. The invariants —
the user's goal is the authority, screenshots are observation data, no invented
conclusions, no blind repetition of an uncertain mutation — are shared. The iOS
variant adds what is true only there: `back` is a gesture that may have no effect;
the home screen has multiple pages that may need swiping to find an app; primary
navigation controls sit at the top of the screen.

### Acceptance scenario

The owner's own first run, to be executed on both the simulator and the physical
phone. Described generically here because the repository must not name real
applications or sites: *open a web browser from the home screen, navigate to a
public search page, search for a short term, and open a specific well-known result
if it appears among the results.* It exercises the home screen, finding an app icon
among several pages, keyboard entry, submitting with `enter`, scrolling, web
content inside a rendered page, and a result recognised visually rather than by any
accessibility identifier. If that run behaves the way its Android equivalent does,
iOS is done.

### Signing is a free personal Apple team

The operator signs WebDriverAgent with a free Apple ID. That means a seven-day
provisioning expiry, a WebDriverAgent bundle identifier that must be unique per
operator, and device trust that has to be granted again after re-signing. Treat
recurring re-signing as a normal documented operator step rather than an error
state, and make the signing inputs (team identifier, signing identity, updated
bundle identifier) operator-supplied configuration. None of those values are
identifying repository content and none of them are committed.

### Session startup is an operator pre-step, not a new runtime budget

The operator boots the simulator and installs WebDriverAgent before a run. The
existing per-operation timeout cap stays as it is, no startup budget is added to
`RunLimits`, the API, the console or the CLI, and `acquire` fails closed with a
clear, actionable message when the target is not ready. `doctor` gains a readiness
check for the iOS prerequisites so the operator learns this before a run rather
than during one. A shut-down simulator is therefore listed but not selectable,
with a hint; a run never boots a device itself, and `release` never shuts one down.

### Acceptance means a `passed` conclusion on both targets

The acceptance scenario is complete when the AI concludes `passed` on the simulator
and on the physical phone. Tuning the iOS instruction variant against real live runs
is therefore part of this work, with a declared cap on attempts and provider spend;
when the cap is reached, the work stops and reports the evidence rather than
continuing to iterate.

One prohibition goes with that goal, because it is exactly how this requirement
could be met dishonestly: the pass must come from the run actually performing the
scenario. Nothing in the instructions, the verdict path or the goal may be loosened
to make a pass easier to obtain — no weakening of what counts as success, no hinting
at the expected outcome, no narrowing of the scenario. The project already has a
known false-pass pattern on procedure-shaped goals; producing another one here would
make the acceptance evidence worthless.

## Constraints

- Clean Architecture dependency direction: domain <- application <- adapters, wired
  in composition. No FastAPI, Appium or SDK imports in domain or application.
- `RunConfiguration` already carries `capabilities: tuple[CommandKind, ...]` and
  `device_adapter_version: str`. Platform differences ride on those existing
  fields; resist inventing a new domain concept for platform if these suffice.
- No generic shell is exposed to the product AI. Device operations stay typed,
  scoped and timeout-bound. Inventory commands are fixed, bounded, read-only and
  never echo their raw output.
- Fail-closed, repository-scoped device leases, one active owner per device, keyed
  so that a simulator and a phone cannot be confused. A failed session start must
  not leave an orphan lease; this is a known Android defect and must not be
  reproduced on iOS.
- Boundary errors are sanitized: safe component/code/detail, no local paths, no
  credentials, no raw provider or process output.
- Device execution after possible dispatch returns an UNCERTAIN receipt instead of
  raising in a way that invites a blind retry.
- Version-sensitive framework APIs are verified against official documentation and
  referenced in `docs/references.md` before being relied upon. This applies to the
  XCUITest driver capabilities, the WebDriverAgent gesture endpoints and the Xcode
  command-line tools used for inventory.
- Local checks are `python scripts/verify.py`; `python scripts/check_project.py`
  runs after editing docs. Do not commit, push or change remotes unless asked.

## Calls made while writing this document

Decisions taken by the designer, not by the owner, after a builder review of this
document raised them. They can be overridden, but they are settled enough to plan
against.

- **Where live work happens.** The builder works on the owner's Mac, with the
  simulator available and the iPhone attachable for the physical layer. Live
  verification is a task to complete here, not a procedure handed to someone else.
- **Toolchain floor.** The target machine runs Xcode 26.2, with `simctl` and
  `devicectl` both present. Assume modern Xcode command-line tooling and verify the
  exact commands against current official documentation before relying on them;
  deprecated inventory paths are not an option.
- **Scale factor.** No device class is excluded by assumption. The ratio between
  screenshot dimensions and the reported window size is computed per session,
  required to be uniform across both axes within a stated tolerance, and non-integral
  ratios are supported with a documented rounding rule. A ratio that is not uniform,
  or that disagrees with the captured image, refuses the device with an explicit
  failure rather than guessing a factor.
- **Instruction refactoring is extraction-only.** Android's rendered prompt stays
  byte-identical, proven by a test that hashes the rendered text, and
  `android-agent-v3` is not bumped. iOS ships as its own version alongside it, and
  the instruction version becomes per-platform rather than a single constant. The
  working Android path does not pay for the iOS prompt.
- **Device inventory contract.** The device listing gains an explicit platform field
  and a platform-neutral selectability signal; iOS entries never imitate adb's state
  vocabulary, and the console never derives a platform by parsing an adapter version
  string. Runs already stored with the current Android adapter version keep rendering
  correctly in history, reports and the run-configuration view.
- **Labels versus anonymity.** A human-readable device label at runtime is fine and
  necessary for choosing a target; nothing identifying is written into source, tests,
  fixtures, docs or reports.
- **Ambiguous iOS session start.** The lease marker is released only when it is
  certain no remote session was created; iOS attempts a bounded reconciliation of a
  possibly created session within its own timeout, and when reconciliation is itself
  uncertain the marker is retained fail-closed and surfaced. The equivalent Android
  behaviour is not modified by this work, since that adapter is live-verified; it
  remains a known issue in STATUS.
- **Partial tooling.** When one platform's tooling is absent, the listing reports a
  per-platform note and still returns the other platform's devices. A Docker-mode
  user sees an explanatory note about iOS, not an error.
- **Native mode serves both platforms.** One dropdown with Android and iOS together
  means the macOS-native configuration must drive Android too, so the native Android
  path becomes a documented, exercised mode and gets its own live re-check with an
  Android phone. Compose remains Android-only.

## What is left to the builder

The following are engineering choices, to be made with the constraints above and
recorded where the repository already records such things.

- The Appium capability set for simulator and for device, session bootstrap and
  teardown, timeouts, and how WebDriverAgent's lifecycle is kept bounded.
- How the point/pixel scale factor is determined for a given session and how it is
  validated rather than assumed, including what happens when the screenshot
  dimensions and the reported window size disagree, and how rotation interacts
  with it. Treat a disagreement as an explicit failure, not a guess.
- Which Xcode command-line tools provide the simulator and physical-device
  inventory, verified against current official documentation, and how their output
  is parsed safely and bounded.
- How the chosen platform travels from the console and the API to adapter
  selection in composition, and how a mismatch between the requested platform and
  the attached device fails closed.
- The exact wording of the iOS instruction variant and how the shared core is
  factored without duplicating it.
- The console labels for platform, and whether the existing refresh action needs
  different behaviour for iOS.
- The CLI surface for selecting an iOS target, consistent with the existing flags.
- Test placement and fixtures mirroring the Android adapter's test strategy.

## Verification plan

Four layers, reported separately, never merged into one claim:

1. Local checks: `python scripts/verify.py` and `python scripts/check_project.py`.
2. Simulator live: the acceptance scenario and each of the seven commands.
3. Physical iPhone over USB: the same, including the WebDriverAgent signing path.
4. Failure handling: an unavailable Appium server, a refused session and a lease
   conflict yield infrastructure failures, not test verdicts.

Model judgement quality is explicitly out of scope for these checks; the product
remains unevaluated in that sense until the labelled evaluation protocol runs.
