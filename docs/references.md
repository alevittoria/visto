# References

Official sources behind version-sensitive implementation choices. Add a source
here before relying on a new framework/provider behavior. These references do not
establish live integration acceptance.

- [Official OpenAI documentation — subagents and custom agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents):
  role-based task delegation, inherited permissions, explicit ownership and
  standalone project-agent TOML definitions.
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
  UiAutomator2 are installed from the locked `tools/appium` package, not globally.
- [Appium rotation](https://appium.io/docs/en/latest/reference/api/appium/#getappiumrotation),
  [Appium WebDriver reference](https://appium.io/docs/en/latest/reference/api/webdriver/):
  device adapter operations, including screenshots, actions and live frame checks; UiAutomator2 `mobile: pressKey` accepts allowlisted Android keys
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
- [Uvicorn](https://www.uvicorn.org/): `uvicorn.Config` plus
  `uvicorn.Server(config).run()` serve the app in-process for `visto start`.
  `visto start` also overrides `Server.on_tick(counter)`, which is not documented;
  this was read from the installed source of the pinned uvicorn 0.54.0
  (`uvicorn/server.py`), not from the documentation. There, `main_loop`
  calls it once after startup and then every 0.1 s, and returning true stops the
  server with the normal shutdown. The override reports readiness on the first tick
  and stops the server when the managed Appium has exited, delegating to the base
  method otherwise. The same source calls `sys.exit` when startup (binding or the
  lifespan) fails, which `visto start` turns into an error message. Recheck both
  when the uvicorn pin changes.
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) and
  [Starlette TestClient](https://starlette.dev/testclient/): in-process HTTP checks;
  current Starlette uses httpx2 and deprecates plain httpx. Follow the installed
  runtime's compatibility guidance when these examples differ.
- [Cross-Origin-Resource-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Resource-Policy)
  and the [Fetch standard's CORP check](https://fetch.spec.whatwg.org/#cross-origin-resource-policy-header):
  `same-origin` makes browsers block no-cors subresource loads (such as `<img>`) from
  other origins; it does not apply to top-level navigations or downloads, so the
  same-origin console and report downloads are unaffected.
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

## adb

- [adb (Android Debug Bridge)](https://developer.android.com/tools/adb):
  `devices -l` for the inventory, `pair`/`connect` for wireless debugging
  (Android 11+), single server per host.

## Price list

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

## Provider key check

- [Retrieve model reference](https://developers.openai.com/api/reference/resources/models/methods/retrieve):
  `GET /v1/models/{model}` with a bearer key returns the model object (`id`,
  `created`, `object`, `owned_by`) and runs no inference, so the settings key
  check probes the default model without cost. 401/403 mean a rejected key, 404
  an unavailable model.

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
  with `appium:xcodeSigningId`), `appium:xcodeSigningId` (certificate type such as `Apple Development`; a full
  certificate name conflicts with WebDriverAgent's automatic signing, which
  `xcodebuild` reports as conflicting provisioning settings) and
  `appium:updatedWDABundleId` (WebDriverAgent bundle identifier, which needs a matching
  provisioning profile) carry the signing values; they are configuration, never logged.
  `appium:usePreinstalledWDA` is the alternative for iOS 17 or newer, which launches an
  installed runner without `xcodebuild`; it is not used, since the pre-step builds and
  installs WebDriverAgent itself.
- `appium:useNewWDA`, read in the installed driver 12.19.1 source
  (`build/lib/commands/wda/startup.js`, `prepareForXcodebuild`): when true and
  `xcodebuild` is needed, the driver quits and uninstalls WebDriverAgent before starting
  a new one; when false it first tries to reuse a running WebDriverAgent
  (`setupCaching`). The adapter sets it only for one retry, after the session's first
  request answered "Not authorized for performing UI testing actions", or that a
  previously found element's application "is not running": the answers of a reused
  WebDriverAgent that a stopped Appium left on the phone. The capability page warns that real devices work best
  without reinstalling WebDriverAgent, hence once per run and only for that cause.
- The driver's `tunnel-creation` script (installed driver 12.19.1,
  `scripts/tunnel-creation.mjs`): must run as root, builds tunnels only for phones
  connected by USB when it starts (and for wireless Apple TV), exits when it finds
  none, and serves a registry on port 42314 with
  `GET /remotexpc/tunnels/:udid?waitMs=<ms>` ("long-poll until catalog ready"). Read
  from the script source and its log output, not from a separate documentation page.
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
  Appium 3.8.0 satisfies it) and the same Node engine range as `tools/appium/package.json`.
  Also checked: a frozen-lockfile install with the documented flags completes and
  Appium lists both drivers as installed. Not checked: that the driver runs a session,
  or any compatibility with a given Xcode release.
- [XCUITest device setup](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/):
  real devices need a trusted computer, Developer Mode (iOS 16 or newer), UI Automation
  enabled, and a WebDriverAgent with a valid provisioning profile. The page defers
  signing detail to a separate provisioning-profile guide that was not read; the
  seven-day expiry and per-operator bundle identifier of a free team come from the
  approved design, not from this page.

## Portable toolchain

`backend/src/visto/toolchain/components.json` pins every archive `visto setup`
downloads, per supported host, with the checksum published by the vendor. Every
download is verified before extraction. Only the vendors' metadata (and, for zip
archives, their central directories through HTTP range reads) were read to pick the
pins; no archive was downloaded or installed, so the layouts given below for tar
archives are the vendors' usual layouts, not observed ones.

- [Node.js 24.19.0 distribution](https://nodejs.org/dist/v24.19.0/) and its
  [SHASUMS256.txt](https://nodejs.org/dist/v24.19.0/SHASUMS256.txt): sha256 for
  `node-v24.19.0-win-x64.zip` and the `darwin-arm64`, `darwin-x64` and `linux-x64`
  `.tar.xz` archives. Each extracts to one top folder named after the file; on
  Windows `node.exe` is at its root, elsewhere `bin/node` (with `bin/npm`, `bin/npx`
  and `bin/corepack` as relative symbolic links into `lib/node_modules`). The Windows
  zip's central directory confirms the single top folder `node-v24.19.0-win-x64`.
- [Adoptium API v3](https://api.adoptium.net/q/swagger-ui/):
  [`/v3/assets/latest/17/hotspot`](https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse)
  lists the newest Temurin 17 GA JDK per OS and architecture, and
  [`/v3/assets/release_name/eclipse/jdk-17.0.20.1+1`](https://api.adoptium.net/v3/assets/release_name/eclipse/jdk-17.0.20.1%2B1?image_type=jdk&jvm_impl=hotspot&heap_size=normal)
  gives `package.link` and `package.checksum` (sha256) for each binary. The pin is
  `jdk-17.0.20.1+1`, the newest GA release published for all four hosts: the newer
  `jdk-17.0.21+9` had Linux x64 and macOS aarch64 binaries only. Archives extract to
  `jdk-17.0.20.1+1/`; macOS archives keep the bundle layout, so `JAVA_HOME` is
  `Contents/Home` there. The Windows zip's central directory confirms the top folder.
- [Android SDK repository](https://dl.google.com/android/repository/repository2-3.xml):
  `remotePackage` entries `platform-tools` (37.0.1) and `build-tools;37.0.0`, the
  newest on `channel-0` (stable), with per-`host-os` archives (`windows`, `macosx`,
  `linux`) whose `complete/url` is relative to `https://dl.google.com/android/repository/`
  and whose `checksum` is sha1. The macOS archives carry no `host-arch`, so both macOS
  hosts use the same files. Central directories (read by range requests) show the
  platform-tools zips extract to `platform-tools/` and the build-tools 37 zips to
  `android-37.0/`, not to the version number; neither contains symbolic links.
  The manifest publishes only sha1 for these archives, so they are pinned with sha1
  while Node and the JDK use sha256. This is an accepted residual risk: SHA-1 is
  exposed to chosen-prefix collisions, so substituting a colliding archive would
  also require control over the archive Google publishes or over the HTTPS
  connection; the pins move to sha256 if the manifest starts publishing it.
- [Python 3.12 `zipfile`](https://docs.python.org/3.12/library/zipfile.html),
  [`tarfile`](https://docs.python.org/3.12/library/tarfile.html) (with its
  [extraction-filter rationale](https://docs.python.org/3.12/library/tarfile.html#tarfile-extraction-filter)),
  [`hashlib`](https://docs.python.org/3.12/library/hashlib.html) and
  [`ssl.create_default_context`](https://docs.python.org/3.12/library/ssl.html#ssl.create_default_context)
  with `cafile`: stdlib verification, extraction and a custom CA bundle. Zip
  symbolic links are recognised from the Unix mode in the high 16 bits of
  `ZipInfo.external_attr` when `create_system` is 3. Extraction refuses absolute
  paths, drive letters, `..`, special files and any link whose target leaves the
  extraction folder, creating links last and resolving them afterwards.
- [Python 3.12 `urllib.request`](https://docs.python.org/3.12/library/urllib.request.html):
  downloads go through `build_opener` with an `HTTPSHandler(context=...)`, so the same
  TLS context verifies every hop, and an `HTTPRedirectHandler` subclass whose
  `redirect_request` refuses any target that is not HTTPS. The handler's own
  `max_redirections` limit bounds the chain.
- [Hatch wheel builder](https://hatch.pypa.io/latest/plugins/builder/wheel/): the
  package directory is packaged whole, so `components.json` needs no extra
  configuration; a locally built wheel lists `visto/toolchain/components.json`.
- [Corepack](https://github.com/nodejs/corepack) and the
  [Node.js 24 distribution](https://nodejs.org/dist/v24.19.0/): Corepack is distributed
  with Node.js from 14.19.0 up to (not including) 25.0.0, so the pinned Node 24 bundles it
  (`node_modules/corepack/dist/corepack.js` at the Windows root, `lib/node_modules/corepack/dist/corepack.js`
  elsewhere). `COREPACK_HOME` sets where package managers are stored and
  `COREPACK_ENABLE_DOWNLOAD_PROMPT=0` suppresses the download prompt. `packageManager`
  accepts `name@version+<algo>.<hex>`; Corepack's `corepackUtils.ts` compares that hex with
  the digest of the downloaded tarball and, for npm packages, derives the expected value from
  the registry `dist.integrity` (base64 sha512, hex-encoded). The pnpm 11.25.0 pin in
  `tools/appium` therefore uses the hex form of the registry integrity from
  `https://registry.npmjs.org/pnpm/11.25.0`. The check was read from source; Corepack was not run.
- [Android SDK License Agreement](https://dl.google.com/android/repository/repository2-3.xml):
  the `license` element with id `android-sdk-license` is stored verbatim (ends trimmed) in
  `backend/src/visto/toolchain/android-sdk-license.txt`; the recorded acceptance is the sha256
  of that text, so a changed text asks again.

## Release packaging

Releases are wheels attached to GitHub Releases by `.github/workflows/release.yml`;
`scripts/build_release.py` stages the console and Appium locks into the package and
`scripts/check_wheel.py` checks the result. The workflow has not been run from this
repository yet; only its scripts were exercised locally.

- [Hatch build configuration — artifacts](https://hatch.pypa.io/latest/config/build/#artifacts)
  (read at the `hatchling-v1.32.4` tag): `artifacts` includes VCS-ignored files and is
  otherwise equivalent to `include`. `backend/src/visto/console/` and
  `backend/src/visto/toolchain/appium/` are git-ignored build inputs listed there; a
  local wheel built without them still succeeds, and one built after
  `build_release.py` lists them. A plain `uv build` goes through the sdist, which does
  not carry them, so the release builds the wheel directly with `uv build --wheel`.
- [uv URL sources](https://docs.astral.sh/uv/concepts/projects/dependencies/#url)
  (uv 0.11.32 docs): a requirement may be an `https://` URL to a wheel ending in `.whl`,
  and `uv tool install <PACKAGE>` takes such a requirement, so the documented install is
  `uv tool install https://github.com/<owner>/<repo>/releases/download/v<version>/visto-<version>-py3-none-any.whl`.
  Not checked: an install from a published release URL.
- GitHub Actions, each pinned by the commit its release tag points to (lightweight tags,
  resolved with `git ls-remote`; inputs read from `action.yml` at that commit):
  [actions/checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
  `3d3c42e5aac5ba805825da76410c181273ba90b1` (`persist-credentials`),
  [astral-sh/setup-uv v10.3.2](https://github.com/astral-sh/setup-uv/releases/tag/v10.3.2)
  `07a047e608db84b3d8c06cd9a7c7dcc9c355c18e` (`version`, `enable-cache`),
  [actions/setup-node v7.1.0](https://github.com/actions/setup-node/releases/tag/v7.1.0)
  `949feb2413d6458794dcd2491c4babbbce0c15c1` (`node-version`, `package-manager-cache`).
- [GitHub CLI `gh release create`](https://cli.github.com/manual/gh_release_create):
  creates the release for an existing tag, uploads the listed files and
  `--generate-notes` writes the notes. Per
  [`gh help environment`](https://cli.github.com/manual/gh_help_environment) it
  authenticates with `GH_TOKEN`, here the job's token limited to `contents: write`, and
  targets `GH_REPO`. The workflow runs only for a pushed `v*` tag, so the tag exists
  and `gh` creates no tag of its own.
