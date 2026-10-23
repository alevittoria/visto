# Multimodal provider setup

The first runner uses the OpenAI Responses HTTPS API. `gpt-6-luna` is the default
model; it, `gpt-5.6-terra` and `gpt-6-sol` all list image
input and structured outputs in their official capability references. `--model` is explicit and configurable; account access and
judgement quality are unverified until a live run. There is no provider fallback.

Store `OPENAI_API_KEY` in the repository-root `.env` file, for example:

```dotenv
OPENAI_API_KEY=your_api_key_here
```

The local `.env` is ignored; `.env.example` contains no credential. The CLI reads
it on each `run`/`doctor` invocation. A nonblank existing process OPENAI_API_KEY
takes precedence. Use `--env-file PATH` in the CLI or `-EnvFile PATH` in the
PowerShell wrapper for another explicitly selected file. The loader reads only
OPENAI_API_KEY; it does not evaluate shell commands, expand variables or mutate
the process environment. Supported syntax: UTF-8/BOM, optional `export`, blank
lines/comments, plain/single-quoted/double-quoted values and trailing comments.
Duplicate or malformed provider-key assignments fail with a sanitized error.

The wrapper prompts with masked input only if both the process key and env file
are absent. A present empty file reports the missing key so it can be completed.
The application does not load personal Codex credentials, inspect other projects
or print the key. `inspect` does not read any credential file.
An API account/key with model access and billing is required. A ChatGPT session
is not automatically an API credential. Keep the local `.env` out of source control;
do not put a real key into example/source files,
goals, answers or screenshots.

The adapter uses the documented REST wire format directly, with standard-library
HTTPS and no provider SDK dependency. A fixed hidden Python child performs one
HTTPS request; the parent sends the key/request through stdin and removes
OPENAI_API_KEY from the inherited child environment, preserving proxy/TLS settings.
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
an execution policy. The configuration-only `doctor` does not check connectivity.

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
