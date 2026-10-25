# Multimodal provider setup

The first runner uses the OpenAI Responses HTTPS API. `gpt-6-luna` is the default
model; it, `gpt-5.6-terra` and `gpt-6-sol` all list image
input and structured outputs in their official capability references. `--model` is explicit and configurable; account access and
judgement quality are unverified until a live run. There is no provider fallback.

## The provider key

An OpenAI API account and key with model access and billing are required; a
ChatGPT session is not an API credential. Enter the key on the console's
**Settings** page (opened automatically while no key is configured) or with
`visto settings set-key`, which reads one line from standard input (a hidden prompt
on a terminal) and never takes the key as an argument. Visto reads the key from its
settings store only: no environment variable or other file is consulted, and
the frontend never receives it.

The key is saved in plain text in `secrets.json` in the Visto home, written
atomically; on macOS and Linux the file is readable by your user only (mode 0600),
on Windows it inherits the access rules of your user profile folder. See
[artifact storage](artifact-storage.md#visto-home). No API response, log line,
error message, report or command output contains the key; the console and
`visto settings show` show only whether one is configured and its last four
characters. Replace or remove it from the Settings page, or with `visto settings
set-key` and `visto settings delete-key`. A change applies to the next run without
a restart; a running run keeps the key it started with.

**Verify** on the Settings page, or `visto settings verify-key`, retrieves the
default model's metadata (`GET https://api.openai.com/v1/models/<model>`) with the
stored key. It runs no inference and is not billed. The result is one word: `ok`,
`missing` (no key stored), `unauthorized` (the key was rejected),
`model_unavailable` (the key cannot see the default model) or `unreachable`
(network, proxy or TLS problem). Do not put a real key into goals, answers,
screenshots, example files or source.

## Requests

The adapter uses the documented REST wire format directly, with standard-library
HTTPS and no provider SDK dependency. A fixed hidden Python child performs one
HTTPS request; the parent sends the key/request through stdin and removes any
`OPENAI_API_KEY` variable from the inherited child environment, preserving
proxy/TLS settings.
HTTP redirects are rejected so credentials/images stay bound to the fixed endpoint.
Deadline/cancellation kills and reaps that child and joins its local pipe task.
OS process creation itself is not interruptible; startup time counts against the
deadline and an expired startup receives no request packet. Killing a client
cannot guarantee remote processing or billing stopped after dispatch.
It submits one bounded structured decision
per inference with no automatic retries. Errors, refusal, incomplete output,
timeouts, invalid coordinates and references are technical failures. They do not
become a failed application test. Missing reported token usage remains unknown.

The instructions are a shared core (`agent-core.md`) plus one versioned notes
file per platform, `android-agent-v3` and `ios-agent-v1`, rendered together for
the run's platform. All of them live under `backend/prompts/` and are included
in the wheel. Every turn rebuilds the same logical conversation
from immutable goal/constraints, bounded recent decisions, working plan, actual
pre/post images, technical receipt and attributed user answers. There are no
opaque remote continuation handles. Context overflow fails explicitly rather
than silently discarding original constraints. This is one conversational AI,
not an actor/judge pair. Software validates evidence references; model quality
requires the separately labelled evaluation protocol.
v2 changes only type_text semantics: one whole-value set on the
focused field; runs recorded with v1 keep their original identity.
v3 adds the `long_press` and `enter` commands; v2 runs keep theirs.

A screenshot larger than the provider's `high` detail limits (2048 pixels per
side, 2,500 patches of 32×32 pixels) is downscaled locally, keeping its aspect
ratio, before it is sent; the provider would otherwise resize it itself and the
model would answer in coordinates of an image it was never told about. The
dimensions sent with each image are those of the image actually sent, the model
answers in its pixels, and the adapter maps commands back to source-screenshot
pixels; commands in the history are shown in the same scale. Stored screenshots,
evidence and reports keep the original size. Smaller screenshots are sent
unchanged. Responses requesting unsupported
commands or fields are rejected. App text and screenshots cannot redefine the
goal or instructions. The AI may adapt its plan, ask a question or conclude
passed, failed or inconclusive using only supplied evidence.

## Connection diagnostics

Provider failures retain only fixed technical codes in CLI output and history:
`connection_refused`, `dns_error`, `tls_error`, `connection_error`, `timeout`,
`invalid_json`, `invalid_request`, `worker_start_error`, `worker_protocol_error`
or `http_NNN` for supported HTTP errors. Raw exceptions, proxy addresses and
provider response bodies are excluded. An infrastructure error is not an AI
application verdict; an attempted request may still incur unknown remote usage.

The worker retains the launching process's proxy configuration and TLS checks.
A restricted agent session may have a disabled network path even when Appium
and the Android device are accessible locally. Check the same CLI invocation
from an ordinary host terminal to distinguish environments. Do not remove proxy
variables, disable TLS, change the endpoint or add blind retries to work around
an execution policy. Behind a TLS-inspecting proxy, give Visto the proxy's
certificate bundle as described in
[installation](local-development.md#behind-a-tls-inspecting-proxy). `visto doctor`
does not contact the provider; `visto settings verify-key` checks the key and the
connection without inference.

## Data sent and stored

A live invocation sends the original goal, constraints, expected result,
screenshots, recent AI decisions, entered text/technical action details, receipts
and user clarifications to `https://api.openai.com/v1/responses`. These may contain
private application data. Use a dedicated test account/device with suitable data.
The request sets `store: false`, and uses no remote conversation storage.
This does not mean zero provider retention: OpenAI documents separate abuse
monitoring retention and organization-specific controls. See the
[official data controls](https://developers.openai.com/api/docs/guides/your-data).

Dictation in the console sends the operator's recording (not screenshots) to
`https://api.openai.com/v1/audio/transcriptions` with model `gpt-transcribe`.
Only the returned text is kept, in the form field; the audio is not stored.
Transcription minutes are billed separately and are not counted in run
statistics or cost estimates.

Local evidence is retained for inspection until the operator removes the chosen
data directory. It is private filesystem data, not encrypted by this application
and not automatically uploaded or served through HTTP. Consult
[artifact storage](artifact-storage.md) and [first device test](first-device-test.md)
before a live invocation. No live call was needed for the adapter's fake tests.
