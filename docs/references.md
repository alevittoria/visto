# References

Official sources behind version-sensitive implementation choices. Add a source
here before relying on a new framework/provider behavior. These references do not
establish live integration acceptance.

- [Official OpenAI documentation — subagents and custom agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents):
  role-based task delegation, inherited permissions, explicit ownership and
  standalone project-agent TOML definitions.
- [Appium WebDriver reference](https://appium.io/docs/en/3.0/reference/api/webdriver/):
  Android adapter operations, including screenshots and actions.
- [Computer-use agent loop](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool):
  conceptual reference for observe/act/observe; this does not select Anthropic as
  the product provider or imply a desktop tool works directly on Android.

## Provider error handling

- [OpenAI API error codes](https://developers.openai.com/api/docs/guides/error-codes):
  distinguish connection failures, timeouts, authentication, malformed requests
  and HTTP service errors. Preserve diagnostic categories without recording raw
  exception strings, provider bodies, proxy addresses or credentials.
- [Python 3.12 URL errors](https://docs.python.org/3.12/library/urllib.error.html),
  [DNS errors](https://docs.python.org/3.12/library/socket.html#socket.gaierror),
  [TLS errors](https://docs.python.org/3.12/library/ssl.html#ssl.SSLError):
  classify the typed `URLError.reason` without exposing its message or relying
  on platform-specific string matching.

## Runner, provider and Android

- [Responses image input](https://developers.openai.com/api/docs/guides/images-vision):
  identified Base64 image content and multiple images. Per-model sizing: `high`
  fits images within 2048 × 2048 pixels and 2,500 patches of 32 × 32 pixels on
  the models that list both limits, and the page advises, for coordinate-sensitive
  tasks, to "resize images to fit those limits before sending them" and "map
  returned coordinates back to the original image". `gpt-6-luna` is not in the
  page's sizing table; its observed offset (≈0.896 for a 1178 × 2556 screenshot)
  matches the documented 2,500-patch formula.
- [Pillow `Image.resize`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.resize)
  with `Image.Resampling.LANCZOS`: local downscaling of screenshots sent to the
  provider.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  strict JSON schema, nullable fields, refusal and incomplete-response handling.
- [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol): selectable
  model; image input, Responses and structured outputs. Account access and
  judgement quality require a separate live check.
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) and
  [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) (Luna is
  the default): selectable alternatives; both list image input, Responses and
  structured outputs. No GPT-6 Terra page exists (404), so Terra is the 5.6 model.
- [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data):
  `store: false` does not imply zero abuse-monitoring retention.
- [Python SQLite connections](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.connect),
  [transaction control](https://docs.python.org/3.12/library/sqlite3.html#transaction-control),
  [bound SQL values](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries):
  explicit transactions and parameterized storage boundaries.
- [Appium requirements](https://appium.io/docs/en/latest/quickstart/requirements/),
  [UiAutomator2 driver](https://github.com/appium/appium-uiautomator2-driver),
  [W3C WebDriver](https://www.w3.org/TR/webdriver2/): explicit serial capability,
  session lifecycle, screenshots and touch pointer actions. Appium 3 and current
  UiAutomator2 are installed in the appium container, not globally.
- [Appium rotation](https://appium.io/docs/en/latest/reference/api/appium/#getappiumrotation),
  [WebDriver wire methods](https://appium.io/docs/en/latest/reference/api/webdriver/):
  live frame checks; UiAutomator2 `mobile: pressKey` accepts allowlisted Android keys
  ([KeyEvent](https://developer.android.com/reference/android/view/KeyEvent):
  KEYCODE_HOME 3, KEYCODE_BACK 4, KEYCODE_ENTER 66). long_press is a touch pointer
  sequence with a [W3C pause action](https://www.w3.org/TR/webdriver2/#actions).
- [UiAutomator2 `mobile: type`](https://github.com/appium/appium-uiautomator2-driver#mobile-type)
  "emulates true typing" key by key; type_text instead uses
  [W3C Element Send Keys](https://www.w3.org/TR/webdriver2/#element-send-keys) on
  [W3C Get Active Element](https://www.w3.org/TR/webdriver2/#get-active-element)
  with UiAutomator2's `replace: true`, verified in the pinned 8.7.0 driver source
  (`build/lib/commands/element.js`: `active()`, `doSetElementValue`), so the whole
  value is set in one request.
- [Appium 3.8.0 release](https://github.com/appium/appium/releases/tag/appium@3.8.0),
  [UiAutomator2 8.7.0 release](https://github.com/appium/appium-uiautomator2-driver/releases/tag/v8.7.0):
  pinned versions; Node 24 meets the documented engine requirements, Android
  API 26 or later is required.
- [W3C WebDriver errors](https://w3c.github.io/webdriver/#errors): a failed command
  answers with `error` and `message` in `value`. The appium-adb bundled with
  UiAutomator2 8.7.0 (`build/lib/utils/helpers/sdk.js`) throws "Neither
  ANDROID_HOME nor ANDROID_SDK_ROOT environment variable was exported" when the
  Appium process has no SDK path; the Android adapter maps that message to a fixed
  operator hint and never shows the server text.
- [Appium package-root discovery](https://appium.io/docs/en/latest/guides/managing-exts/#do-it-yourself-with-npm):
  use own pinned package dependencies as local extensions without global npm links.
- [Python asyncio subprocesses](https://docs.python.org/3.12/library/asyncio-subprocess.html),
  [task timeout/shield](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.timeout),
  [subprocess lifecycle](https://docs.python.org/3.12/library/subprocess.html):
  fixed isolated HTTPS worker, secret stdin and bounded cancellation/reaping.
- [urllib redirect handling](https://docs.python.org/3.12/library/urllib.request.html#urllib.request.HTTPRedirectHandler.redirect_request):
  reject redirects rather than forward headers/body beyond the fixed provider
  endpoint, retaining normal TLS and configured proxy handling.

## Backend and frontend tooling

- [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/):
  app factory, typed routes and ASGI application entry point.
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) and
  [Starlette TestClient](https://starlette.dev/testclient/): in-process HTTP checks;
  current Starlette uses httpx2 and deprecates plain httpx. Follow the installed
  runtime's compatibility guidance when these examples differ.
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) and
  [building distributions](https://docs.astral.sh/uv/guides/package/): package lock,
  locked installation and distributable backend.
- [Vite configuration](https://vite.dev/config/) and
  [development server proxy](https://vite.dev/config/server-options#server-proxy):
  native configuration loading and local `/api` proxy.
- [React createRoot](https://react.dev/reference/react-dom/client/createRoot) and
  [useEffect](https://react.dev/reference/react/useEffect): React entry point and
  request lifecycle cleanup.
- [Node 24 test runner](https://nodejs.org/docs/latest-v24.x/api/test.html) and
  [TypeScript execution](https://nodejs.org/docs/latest-v24.x/api/typescript.html):
  native tests without an additional test framework.
- [pnpm install](https://pnpm.io/cli/install): frozen-lockfile installation.
- [Vite TypeScript support](https://vite.dev/guide/features.html#typescript) and
  [TypeScript unused-local](https://www.typescriptlang.org/tsconfig/noUnusedLocals.html)/
  [unused-parameter diagnostics](https://www.typescriptlang.org/tsconfig/noUnusedParameters.html):
  separate compiler checks from Vite transpilation.
- [pnpm 11 defaults](https://pnpm.io/blog/releases/11.0) and
  [release-age settings](https://pnpm.io/settings#minimumreleaseage):
  metadata-dependent publication-age checks.

## Inner contracts

- [Python 3.12 dataclasses](https://docs.python.org/3.12/library/dataclasses.html):
  frozen/slots value records; annotations do not validate input types, so
  technical construction invariants are explicit.
- [Python 3.12 Protocol](https://docs.python.org/3.12/library/typing.html#typing.Protocol):
  structural application ports without framework base classes or SDK objects.
- [Python 3.12 StrEnum](https://docs.python.org/3.12/library/enum.html#enum.StrEnum):
  explicit technical lifecycle and semantic-result values.

## Android rotation compatibility

The installed official AndroidDriver 14.2.0 package's
`build/lib/method-map.js` lines 39-43 declares `/session/:sessionId/rotation`
as a native UiAutomator2 proxy route. The installed UiAutomator2 8.7.0
inherits this AndroidDriver map; see its
[pinned source](https://github.com/appium/appium-uiautomator2-driver/blob/v8.7.0/lib/driver.ts).
The generic Appium replacement `/appium/device/rotation` exists in base-driver
but returns HTTP405 not implemented on the actual pinned native stack. A bounded
live diagnostic confirmed native `/rotation` returns x0/y0/z0 and screenshot
capture succeeds. Use the native route as an explicit pinned-stack compatibility
exception, retaining strict response validation and finite deadlines. Do not
retry arbitrary failures or infer orientation.

## Docker stack and dev container

Behaviour below was verified empirically with Docker Desktop; the pages are the
governing official references.

- [Compose `network_mode: service:<name>`](https://docs.docker.com/reference/compose-file/services/#network_mode):
  `backend`/`appium` join the `net` service namespace so Appium stays loopback-only.
  A joined container keeps the namespace of the container it joined; recreating
  that owner orphans it, hence the stable `net` owner.
- [Compose long-syntax bind mounts](https://docs.docker.com/reference/compose-file/services/#volumes):
  `bind.create_host_path: false` makes a missing `.env` an error instead of a
  host directory.
- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) and
  [BuildKit cache mounts](https://docs.docker.com/build/cache/optimize/#use-cache-mounts):
  `COPY --chmod`, `RUN --mount=type=cache` for the uv cache.
- [uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/):
  `COPY --from=ghcr.io/astral-sh/uv:<version>`, `UV_PROJECT_ENVIRONMENT`,
  `--no-install-project` dependency layer, `UV_LINK_MODE=copy`.
- [Android SDK repository manifest](https://dl.google.com/android/repository/repository2-3.xml):
  archive names and SHA-1 checksums for platform-tools 37.0.1 and build-tools 37.
- [adb (Android Debug Bridge)](https://developer.android.com/tools/adb):
  `pair`/`connect` for wireless debugging (Android 11+), single server per host;
  `-H`/`-P` select the server, `tcpip PORT` restarts adbd on TCP (also in
  `adb --help` of platform-tools 37).
- [Docker Desktop networking how-tos](https://docs.docker.com/desktop/features/networking/networking-how-tos/):
  `host.docker.internal` resolves to the host for container-to-host connections.
  That it also reaches the host adb server bound to 127.0.0.1 is not stated there;
  it is observed on Windows with Docker Desktop (macOS not checked).
- [Dev Container specification](https://containers.dev/implementors/json_reference/):
  `dockerComposeFile`, `service`, `runServices`, `workspaceFolder`,
  `postCreateCommand`, `forwardPorts`, `shutdownAction`.
- [AI Pricing Guru API](https://www.aipricing.guru/api-docs/):
  `GET https://www.aipricing.guru/api/pricing.json`, no authentication, static
  JSON refreshed daily at 04:00 UTC from provider price pages; `models[]` with
  `id`, `provider`, `pricing.inputPerM`/`outputPerM` in USD per 1M tokens, plus
  `lastUpdated`. Terms: personal/research/internal business use with attribution;
  commercial redistribution needs permission. OpenAI publishes no pricing API
  ([forum](https://community.openai.com/t/is-there-an-endpoint-to-programmatically-fetch-openai-model-pricing/1229924)).

## Dictated goals

- [Speech to text guide](https://developers.openai.com/api/docs/guides/speech-to-text):
  `POST /v1/audio/transcriptions`, multipart `file` + `model`; accepted formats
  mp3, mp4, mpeg, mpga, m4a, wav, webm; files up to 25 MB; JSON `text` reply.
  `gpt-transcribe` is the recommended model for recorded speech in its original
  language (no language hint is sent, so Italian or English goals keep theirs).
- [Create transcription reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create):
  `response_format` `json`; optional `language`/`prompt` are not used.
- [GPT-Transcribe model](https://developers.openai.com/api/docs/models/gpt-transcribe):
  model id `gpt-transcribe`, priced per audio minute.
- Browser side: [MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
  with `isTypeSupported` and [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia),
  which requires a secure context (localhost counts).

## iOS

- [Running your app in Simulator or on a device](https://developer.apple.com/documentation/xcode/running-your-app-in-simulator-or-on-a-device):
  Apple's overview of simulated and physical iOS targets; the inventory lists both.
- `xcrun simctl list devices --json` (Xcode command-line tools; `xcrun simctl help list`
  documents `-j/--json`): top-level `devices` maps a runtime identifier
  (`com.apple.CoreSimulator.SimRuntime.<platform>-<version>`) to simulators with
  `udid`, `name`, `state` (`Booted`, `Shutdown`, ...) and `isAvailable`. Non-iOS
  runtimes (watchOS, tvOS) share the list and are skipped.
- `xcrun devicectl list devices --json-output <path>` (CoreDevice command-line
  tool, Xcode 15 or newer; `xcrun devicectl list devices --help` documents it).
  Evidence level: the flag, the `result.devices[]` envelope, the `properties` keys
  and the deprecation of the three legacy keys were checked against the installed
  toolchain's own help and output, which contained only simulated entries. The
  values for a physical device (`connection.state` = `connected`,
  `connection.pairingState` = `paired`, `hardware.reality` = `physical`) are inferred
  from the help text and the legacy `tunnelState` semantics and have not been seen on
  real hardware; the physical path stays unverified until a phone is attached. There
  is no `--json` flag: JSON goes to a file, and `/dev/stdout` with `--quiet` yields
  it on standard output. The result is `result.devices[]`. The `properties`
  dictionary (`connection.state`, `connection.pairingState`, `hardware.udid`,
  `hardware.reality`, `hardware.marketingName`, `hardware.productType`) replaces the
  deprecated `hardwareProperties`, `deviceProperties` and `connectionProperties`
  keys. Simulators also appear with `reality` `simulated`; only `physical` entries
  are taken from this command.
- `xcrun xctrace list devices` is deprecated for device discovery and is not used.
- [Appium XCUITest driver capabilities](https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/):
  `appium:udid`, `appium:platformVersion`, `appium:deviceName` and
  `appium:usePreinstalledWDA` select the target and WebDriverAgent handling.
  The device adapter sends `appium:noReset`, `appium:fullReset`, `appium:autoLaunch`,
  `appium:shouldTerminateApp` and `appium:newCommandTimeout` so a run neither installs,
  launches nor terminates an application, plus `appium:usePrebuiltWDA`
  ("Skips the build phase of running the WDA app") when the operator declares that
  WebDriverAgent is already built, and `appium:derivedDataPath` ("Overrides the
  folder that should be used for derived data") when the operator names the
  build's derived data folder; with both, the installed driver runs
  `xcodebuild test-without-building -derivedDataPath <path>`. `appium:xcodeOrgId` (team identifier, effective only
  with `appium:xcodeSigningId`), `appium:xcodeSigningId` (certificate name) and
  `appium:updatedWDABundleId` (WebDriverAgent bundle identifier, which needs a matching
  provisioning profile) carry the signing values; they are configuration, never logged.
  `appium:usePreinstalledWDA` is the alternative for iOS 17 or newer, which launches an
  installed runner without `xcodebuild`; it is not used, since the pre-step builds and
  installs WebDriverAgent itself.
- [`mobile: pressButton`](https://appium.github.io/appium-xcuitest-driver/latest/reference/execute-methods/):
  execute method taking `name`, case-insensitive; on iOS `home` is accepted, while
  `volumeup`/`volumedown` are real devices only. `home` is the adapter's home command.
- XCUITest wire routes used by the device adapter, with the Appium route maps that
  register them and the driver methods that serve them:
  [`GET /session/:id/screenshot`](https://www.w3.org/TR/webdriver2/#take-screenshot)
  (driver `getScreenshot`, WebDriverAgent `/screenshot`, Base64 PNG),
  [`GET /session/:id/window/rect`](https://www.w3.org/TR/webdriver2/#get-window-rect)
  (driver `getWindowRect`, WebDriverAgent `/window/rect`; the window size is in points,
  which is the gesture coordinate space, while the screenshot is in pixels),
  [`POST /session/:id/actions`](https://www.w3.org/TR/webdriver2/#perform-actions)
  (driver `performActions`, which forces `pointerType: touch`, drops zero-duration
  pauses and passes the sequence to WebDriverAgent `/actions`),
  [`GET /session/:id/element/active`](https://www.w3.org/TR/webdriver2/#get-active-element)
  (driver `active`) and
  [`POST /session/:id/element/:id/value`](https://www.w3.org/TR/webdriver2/#element-send-keys)
  (driver `setValue`). The
  [W3C route map](https://github.com/appium/appium/blob/master/packages/base-driver/lib/protocol/routes/w3c.ts)
  declares `text` as the required parameter of the element-value route; XCUITest has no
  `replace` option as UiAutomator2 does, so the text is sent in one request and does
  not clear the field (the adapter does not clear it; the instructions tell the model to
  clear first), and `enter` is a newline sent the same way.
- Orientation on iOS: the adapter reads
  [`GET /session/:id/rotation`](https://github.com/appium/appium/blob/master/packages/base-driver/lib/protocol/routes/mjsonwp.ts),
  which the
  [driver's no-proxy list](https://github.com/appium/appium-xcuitest-driver/blob/master/lib/driver.ts)
  does not intercept, so it reaches
  [WebDriverAgent's `/rotation`](https://github.com/appium/WebDriverAgent/blob/master/WebDriverAgentLib/Commands/FBOrientationCommands.m).
  Its [rotation mapping](https://github.com/appium/WebDriverAgent/blob/master/WebDriverAgentLib/Categories/XCUIDevice%2BFBRotation.m)
  returns `x`/`y`/`z` with `z` in 0/90/180/270, the vocabulary the domain already uses,
  and no value for an unknown orientation, which the adapter refuses. `GET /orientation`
  is not used: WebDriverAgent maps upside-down to `PORTRAIT` and landscape-right to
  `LANDSCAPE`, so it cannot tell all four interface orientations apart. The rotation
  value is a stable frame label, not a derived angle: `/rotation` indexes a
  device-orientation table with the interface orientation, which swaps the two landscape
  senses. Only equality matters, since the frame guard compares the value before and
  after a capture and coordinates come from `to_points`.
- Evidence level for the four entries above: the XCUITest driver is pinned only in
  `tools/appium/macos/package.json` (below), and was not installed here, so these were
  checked against the driver's published documentation, the current driver and
  WebDriverAgent sources linked above, and Appium's base-driver route maps. Nothing here
  was exercised against a simulator or a phone, and the physical-device path, including
  WebDriverAgent signing, stays unverified until a phone is attached. Apple's own
  developer pages are JavaScript-rendered and could not be fetched.
- [XCUITest driver 12.19.1 release](https://github.com/appium/appium-xcuitest-driver/releases/tag/v12.19.1)
  and its [package manifest](https://github.com/appium/appium-xcuitest-driver/blob/v12.19.1/package.json):
  the version pinned in `tools/appium/macos/package.json` beside Appium 3.8.0 and
  UiAutomator2 8.7.0. Checked: the GitHub releases page listed 12.19.1 as the latest
  release, and its manifest declares the peer dependency `appium` `^3.0.0-rc.2` (so
  Appium 3.8.0 satisfies it) and the same Node engine range as the container manifest.
  Also checked: a frozen-lockfile install with the container's flags completes and
  Appium lists both drivers as installed. Not checked: that the driver runs a session,
  or any compatibility with a given Xcode release.
- [XCUITest device setup](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/):
  real devices need a trusted computer, Developer Mode (iOS 16 or newer), UI Automation
  enabled, and a WebDriverAgent with a valid provisioning profile. The page defers
  signing detail to a separate provisioning-profile guide that was not read; the
  seven-day expiry and per-operator bundle identifier of a free team come from the
  approved design, not from this page.
