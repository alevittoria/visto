# Local web execution API

Local-only API. JSON field names use snake_case. Run/state data is
stored AI/runtime output, never a controller-derived semantic verdict.

All routes are under `/api`; outside it, the backend of an installed release
serves the built console at `/` (any other path falls back to its `index.html`).
Read routes return `Cache-Control: no-store`. Every response, including the served
console, carries `Cross-Origin-Resource-Policy: same-origin`, so another origin
cannot embed screenshots or other responses (for example through `<img>`).
Every request, reads included, requires a loopback Host (`localhost`, `127.0.0.1`
or `[::1]`, any port); any other Host gets 403, so a DNS-rebound page cannot read
run history or screenshots. Every POST, PUT and DELETE requires
`X-Visto: local-console` and a loopback Host, and is refused when
`Sec-Fetch-Site` is present and not `same-origin` or `none`.
When Origin is supplied it must equal the request origin. The Vite proxy is
configured with `changeOrigin: false` so it forwards the browser Host; Vite's
string shorthand would rewrite Host and every console POST would get 403.
No CORS permission is granted. Bind backend and frontend locally.
Errors are `{ "detail": "safe explanation" }`; validation errors are HTTP 422
with `detail` naming only invalid field locations, never submitted values.
409 means busy, stale control/question or run cannot safely resume after restart.

## Configuration and creation

- `GET /health`: existing product/version/runtime_ready liveness response.
- `GET /readiness`: `{configured, provider_key_configured, configuration_error,
  model, models, appium_url, device_selection:"manual", devices:[], active_run_id,
  cleanup_attention_run_ids, execution_available, default_limits, platforms}`.
  `platforms` lists the platforms (`"android"`, `"ios"`) whose device sources this
  process has configured (iOS sources only on macOS); it is derived from configuration,
  not from attached devices. Configuration-only: no device/provider
  network calls and no Appium session. Operator enters the exact authorized ADB
  serial (or picks one from `GET /devices`); physical connectivity is checked
  when a run starts. Readiness itself never runs adb. The provider key is read
  server-side from the settings store in the Visto home; `configuration_error` is
  set when the settings files cannot be used.
  `model` is the default; `models` is the operator-selectable allowlist
  (`gpt-6-luna` default, `gpt-5.6-terra`, `gpt-6-sol`).
- `GET /devices`: `{available, devices:[{serial,platform,state,model,product,selectable}],
  error, notes}`. `platform` is `"android"` or `"ios"`. Android entries come from one
  fixed, read-only `adb devices -l` (5 s timeout, one at a time) with the managed
  `adb` of the Visto home's toolchain, or, when the home has none, an adb found via
  ANDROID_HOME, ANDROID_SDK_ROOT, the default Windows SDK or PATH; iOS entries come
  from Xcode's command-line tools and are listed only on macOS. `selectable` is platform-specific: adb state
  `device` for Android, `booted` or `connected` for iOS; other states (unauthorized,
  offline, shutdown) are listed but not selectable. Failures return `available:false` and a safe
  `error` without process output. It may start the local adb server. The console
  calls it only on open and on explicit Refresh; a run still re-checks the device.
- `POST /runs` (202): `{device_id, model:null, goal, expected_result:null,
  constraints:[], observe_only:false, platform:"android", limits:{wall_time_ms:1200000,
  max_actions:60,max_inferences:90,max_command_timeout_ms:60000,
  max_observation_delay_ms:10000}}`. Optional fields use those defaults.
  `model` null means the default; a value outside `models` returns 422.
  `platform` is `"android"` (default, so existing callers are unchanged) or `"ios"`;
  any other value, or `"ios"` when `platforms` does not list it, returns 422. Creation lists no devices: a device that does not match
  the platform fails closed when the session starts. The stored run records the
  platform only through its adapter and instruction version strings.
  Returns a Run. Exactly one retained execution session; a paused or waiting run
  reserves that slot until completion/cancellation. There is no waiting queue.

- `POST /transcriptions`: dictated goal or expected-result text. Body is the raw
  recording; `Content-Type` must be `audio/webm`, `audio/mp4`, `audio/mpeg` or
  `audio/wav` (parameters such as `;codecs=opus` are ignored). Requires the local
  console guard. Returns `{text, model:"gpt-transcribe"}`; the console appends
  `text` to the field for the operator to review. Nothing is stored and no run is
  touched. Errors: 413 above 10 MiB, 415 other types, 422 empty body, 503 no
  provider key, 429 while another transcription is in flight, 502
  `Transcription failed (provider: <category>)` with a sanitized category only.
  One provider request through the same fixed HTTPS worker as runs (60 s timeout).

Limits: wall time 1..3600000 ms, actions/inferences 1..300, command timeout
1..60000 ms, observation delay 1..60000 ms. Text goal max 16000 characters;
expected result max 8000; up to 32 constraints of max 2000 characters each.
Device serial max 256 characters. Strings must contain non-whitespace text.

## Settings

Settings are stored in the Visto home and read when used, so changes apply to the
next run without a restart. Every write uses the local-console guard above.
`503 Local settings are invalid` means a settings or secrets file cannot be used.

- `GET /settings`: `{price_refresh, ios_supported, ios, key:{configured, last4,
  storage:"file"}, wda_project, wda_rebuild_needed}`. `ios` is
  `{team_id, signing_id, wda_bundle_id, prebuilt_wda, wda_derived_data}` when the
  host supports iOS (macOS) and null otherwise; `wda_project` is the
  WebDriverAgent project path inside the managed Appium install or null;
  `wda_rebuild_needed` is true when the installed XCUITest driver differs from the
  one recorded when the iOS values were last saved. The key itself is never
  returned by any route.
- `PUT /settings`: `{price_refresh, ios?}` with the `ios` fields above (strings of
  at most 64/256/256/1024 characters, `prebuilt_wda` a boolean; unknown fields are
  rejected). Omitting `ios` keeps the stored values; sending it on a host without
  iOS support returns 422. Saving `ios` records the installed XCUITest driver
  version. Returns the `GET /settings` view.
- `PUT /settings/key`: `{api_key}` (at most 8192 characters). Stores the key and
  returns `{configured, last4, storage}`. An empty key or one containing
  whitespace or control characters returns 422 with a message that never contains
  the value.
- `DELETE /settings/key`: removes the stored key; returns `{configured:false,
  last4:null, storage}`.
- `POST /settings/key/verify`: `{result}` with `result` one of `ok`, `missing`,
  `unauthorized`, `model_unavailable` or `unreachable`. Retrieves the default
  model's metadata (`GET https://api.openai.com/v1/models/{model}`, 10 s timeout)
  with the stored key through the fixed HTTPS worker; no inference, not billed.
  401/403 map to `unauthorized`, 404 to `model_unavailable`, any other failure to
  `unreachable`.

## Inspection

- `GET /runs?limit=50&offset=0`: `{runs:[Run], limit, offset}` (max limit 100).
  Durable newest-first history, including runs created by the CLI.
- `GET /runs/{run_id}`: Run, plus `cost:{usd, approximate, price_day, input_per_m,
  output_per_m}` priced like `GET /statistics` (`usd` null when unpriced).
- `GET /usage`: `{input_tokens, output_tokens, recorded_decisions,
  unknown_usage_decisions, runs_with_decisions}` summed over all stored runs.
  Counts persisted AI decisions only; failed or unrecorded provider requests may
  have consumed tokens that are not counted. No cost is computed.
- `GET /statistics`: `{overall, by_model:[Group], by_scenario:[Group]}` over all
  stored runs. Group: `{key, label, runs, outcomes:{passed, failed, inconclusive,
  infrastructure_failure, cancelled, budget_exhausted, unfinished}, ai_conclusions,
  duration_ms, actions, input_tokens, output_tokens, unknown_usage_decisions,
  tokens_by_model:{model:{input_tokens,output_tokens}}}`; `duration_ms`/`actions`
  are `{mean, median, min, max}` over terminal runs or null. Duration runs from
  creation to the terminal record and includes paused time; actions count stored
  Action records. A scenario is one exact goal + expected result + constraints;
  scenario groups add `expected_result`, `constraints` and `recent` (up to 20
  newest `{run_id, outcome, model, created_at, duration_ms, actions, cost_usd,
  cost_approximate}`). Outcomes reuse the stored terminal; nothing is re-judged.
  Groups are ordered by size. Each group has `cost:{usd, unpriced_runs,
  unpriced_models, approximate_runs}`: each run is priced with the daily price
  snapshot in effect on its UTC creation day (base input/output rates; cached and
  long-context tiers not distinguished). Runs older than the first snapshot use
  the earliest one and count as approximate; models without a price are unpriced.
- `GET /prices`: `{source, source_url, attribution, refresh_enabled, snapshot:
  {day, fetched_at, source_updated_at}|null, last_attempt_at, error, models:
  {model:{day, input_per_m, output_per_m}}}` for the selectable models. Read-only;
  it never fetches. The backend fetches the public AI Pricing Guru list at start
  and checks hourly, storing at most one snapshot per UTC day in
  `<data dir>/prices.sqlite3`. The `price_refresh` setting (see Settings below)
  disables fetching when false; `refresh_enabled` reports it.
- `GET /runs/{run_id}/events?after=0&limit=100`: `{events:[{sequence,kind,data}],
  next_after}`. Sequence is 1-based position in durable run history; after is the
  last consumed sequence. Event kinds are `observation`, `agent_decision`,
  `action`, `technical_receipt`, `pending_question`, `user_answer`.
  Terminal/lifecycle changes are in the separately-polled Run.
- `GET /runs/{run_id}/artifacts/{observation_id}`: integrity-checked image bytes.
  Only references in this run's persisted observation history are accepted.
- `GET /runs/{run_id}/report.json` and `/report.html`: downloadable reports;
  screenshots use the scoped artifact routes above.

Run is the domain record rendered as ordinary JSON: `run_id`, `device_id`,
`goal:{text,constraints,expected_result}`, `configuration:{limits,capabilities,
identity:{provider,model,instruction_version},device_adapter_version}`,
`created_at`, `updated_at`, `state`, `revision`, `pending_question`, `terminal`.
It additionally includes `can_resume`, `interrupted`, `control_pending`
(`pause`, `cancel`, `resume` or null) and `cleanup_failed`. `cleanup_failed`
is true (this process only) when device/lease cleanup failed after the run was
already terminal: the stored outcome stays authoritative, but the operator must
reconcile that serial's lease/Appium session before another run on it. Run views from
`GET /runs` and `GET /runs/{run_id}` include `usage:{input_tokens,output_tokens,
recorded_decisions,unknown_usage_decisions}` with the same scope as `GET /usage`. Timestamps are ISO 8601 with timezone.
States: `created`, `running`, `paused`, `waiting_for_user`, `terminal`.
Terminal has `kind`: `ai_conclusion`, `infrastructure_failure`, `cancelled` or
`budget_exhausted`. AI verdict is only `terminal.assessment.verdict` for
`ai_conclusion`: `passed`, `failed`, `inconclusive`.

Dataclasses nested in responses include `kind` in snake_case alongside their
domain fields. Commands have kinds `tap`, `long_press`, `swipe`, `type_text`, `back`, `home`,
`enter`;
next-decision kinds are `act`, `observe_after`, `ask_user`, `conclude`.
Observation screenshot contains `artifact_id`, `run_id`, `media_type`,
`byte_length`, `sha256`, `url`; private storage keys/paths are omitted.
Usage token values may be null (unknown). Decisions include concise `rationale`,
`working_plan`, `presented_observation_ids` and `source_observation_id`, effect assessment and `next`.

## Controls

- `POST /runs/{run_id}/pause` (202): cooperative stop after in-flight work settles.
  Returns 409 while a resume request is still pending.
- `POST /runs/{run_id}/resume` (202): paused run or answered waiting run only;
  returns current Run immediately; fresh observation precedes new dispatch.
- `POST /runs/{run_id}/cancel` (202): cooperative cancellation; paused/waiting
  runs settle immediately. Repeated terminal cancellation returns the terminal.
- `POST /runs/{run_id}/answers` (200): `{question_id,text}`. Records attributed
  operator clarification. Same question+text retry is idempotent; conflicting or
  stale answers return 409. Then call resume explicitly.
- `DELETE /runs/{run_id}` (200): `{deleted:[run_id]}`. Permanently removes the
  run, its history, terminal record and screenshots. 409 for the run this process
  is executing; 404 if absent. An `interrupted` run may still be live in a CLI
  process: deleting it makes that process fail on storage.
- `DELETE /runs` (200): `{deleted:[run_id...], kept_active_run_id}`. Deletes every
  stored run except the one this process is executing.

Deletes require the same local-console header/loopback/same-origin guard as POST.
History is removed before screenshot files; a 503 after a storage failure may
leave unreachable screenshot files on disk.

Controls return Run and may show `control_pending` while work settles. Poll
until lifecycle confirms the request. A nonterminal run not executing in this
web process is marked `interrupted:true`: it may be live in a CLI process or
abandoned by a prior process; the API cannot distinguish these. It cannot resume and cannot claim ownership of a device; create
a new run only after operator reconciliation of any surviving Appium lease.
Shutdown requests cancellation and waits finitely for command/provider cleanup.
The local console exposes screenshots and test text to local readers. During
execution screenshots/text are sent to the configured provider; no local-only
inference or retention guarantee is implied. See artifact/provider documentation.

