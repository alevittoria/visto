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
  identified Base64 image content, multiple images and source-image pixel contract.
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
