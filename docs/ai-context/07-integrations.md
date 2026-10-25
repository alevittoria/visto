# Integration boundaries

Exact contracts and sources are recorded in [references](../references.md).
See [architecture](03-architecture.md) and [data model](06-data-model.md).

## Android device adapter

Appium/UiAutomator2 is the Android backend; a fixed, bounded `adb devices -l`
provides the device inventory, and the backend runs a bounded `adb start-server`
at startup so that inventory finds the server ready. It translates typed commands, captures screenshot bytes and
reports technical receipts. It does not inspect text labels to declare progress
or test success. Accessibility data, if later added, is optional observation
content, never a second deterministic semantic verifier.

The port must cover device ownership, observe and execute. Each command has a
deadline and capability check, source image identity and run/device scope.
Session/device setup failures are infrastructure errors. Rejected arguments
produce explicit technical feedback. Transport loss after dispatch is uncertain;
reobserve before deciding what to do next rather than blindly repeating a tap or
text entry. A new backend must preserve these semantics and pass the same fake
contract tests before real-device checks. No live device is needed for
documentation or unit tests. An iOS backend implements the same port.

## iOS device adapter

The iOS adapter implements the same port over Appium's XCUITest driver and
WebDriverAgent, sharing the Appium session core with Android. It runs only with
the backend running on macOS. iOS
inventory uses fixed, read-only `xcrun simctl` and `xcrun devicectl` commands.
Visto never boots a simulator, builds WebDriverAgent or shuts a device down; the
XCUITest driver will boot or build if a session targets something not ready (see
the prebuilt WebDriverAgent and derived data settings and the pre-step). Signing
values come from the settings store, entered on the console's Settings page.
Local checks only: no simulator or phone run is recorded. See
[iOS setup](../ios-setup.md).

## Multimodal agent adapter

The provider adapter translates the application decision protocol to the chosen
model's image/tool/structured-response format. It maintains one logical runtime
conversation, including any provider continuation handle. Application context
assembly always preserves original goal and constraints independently of an
opaque provider conversation ID.

Input consists of trusted instructions, immutable goal/constraints, available
technical commands, bounded history/working plan, receipts and identified images.
Images over the provider's size limits are downscaled in the adapter, which maps
coordinates between the sent image and the source screenshot in both directions;
the rest of the system works in source-screenshot pixels.
Visible app text is data. Output is a typed decision plus concise evidence-based
assessment; provider syntax errors and unsupported commands are not semantic
failures. Bounded repair/retry policy belongs to the application; the adapter
must surface timeout, rate limit, refusal, malformed output and usage clearly.
Missing usage is unknown, not zero. Do not hide unlimited retries inside SDKs.

Provider replacement requires explicit capability checks for images, structured
decisions, context limits, timeouts and reported usage. Preserve the internal
decision contract while recording model/instruction version changes. Provider
conversation reconstruction may summarize old turns but must retain goal and
evidence provenance. Model quality needs labelled evaluation; adapter contract
tests only establish correct translation and error handling.

## Persistence adapters

SQLite stores runs, decisions, observations, receipts and terminal records;
local files store screenshot artifacts by reference. Ordinary transactions and
unique IDs are sufficient initially. The adapter must support append integrity
and a single terminal transition. It must expose missing writes/artifacts as
errors and provide enough durable intent to identify an interrupted action.

Avoid wrapping the SQLite connection in a public generic query interface.
Expose use-case operations through store ports. An alternative database or object
store should change adapter/composition code, not the runner. Cross-file/database
consistency and orphan cleanup are implementation concerns; never claim a record
is complete before its required artifact is durably available.

## API, console and configuration

FastAPI maps start/pause/resume/cancel, pending-question answer and run/evidence
reads to application use cases. Answers carry question/run IDs and are appended
as attributed clarifications, never edits of the original goal. Resumption must
reacquire the lease, check remaining budgets and capture fresh evidence. The
React/TypeScript console renders recorded observations, decisions,
technical errors and terminal assessments without deriving its own verdict.
The console polls; routes are in the [API contract](../api-contract.md).
Do not expose raw filesystem paths, credentials or an unrestricted device shell.

The composition root injects adapters, clock and stores, including the settings
store of the Visto home and the managed toolchain paths (`adb`, WebDriverAgent
project). The provider key comes only from the settings store, never from the
process environment; sample configuration contains placeholders. Use fake adapters and a controllable
clock by default in local tests. Billable inference and real-device evaluation
are opt-in, require recorded prerequisites and must be reported separately.

Which screenshots/text leave the computer for inference, where artifacts are
stored and retention controls are documented in [artifact storage](../artifact-storage.md)
and [provider setup](../provider-setup.md). Local-first storage does not imply
local inference or provider zero retention.

## Current configuration

Appium/UiAutomator2, OpenAI Responses with a model from the console/CLI
allowlist and the latest `android-agent-v*` instructions, SQLite metadata and
owned screenshot files, all through the declared ports. The Appium URL is
loopback-only. `--observe-only` supplies no device mutation capabilities.

Settings live in the Visto home: `settings.json` (price refresh, iOS signing)
and `secrets.json` (provider key in plain text, mode 0600 on POSIX, user-profile
ACL on Windows). Backend and CLI read them when used, so a change applies to the
next run; a run snapshots what it uses at start. The settings API is write-only
for the key and uses the console write guard. The frontend never receives the
provider key.

## Toolchain and processes

`visto setup` installs pinned, checksum-verified Node, JDK and Android SDK tools,
then Appium from the shipped lock, into `<home>/toolchain/` side by side; nothing
system-wide changes. `visto start` realigns components, migrates the run database
(with a backup), starts Appium as a child with `ANDROID_HOME`, `JAVA_HOME` and
`PATH` set only in its environment, and serves API and console on loopback.
Every Visto process registers in `<home>/instances/`; setup and data upgrades
refuse while another is registered. Device leases are separate and stay
fail-closed. See [installation](../local-development.md).

Operator details: [first device test](../first-device-test.md),
[Android setup](../android-setup.md), [iOS setup](../ios-setup.md), [provider setup](../provider-setup.md),
[artifact storage](../artifact-storage.md).
