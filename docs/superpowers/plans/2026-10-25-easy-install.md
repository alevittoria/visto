# Easy Installation and In-Console Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install Visto with uv plus `visto setup`, run it with `visto start`, and configure the provider key and iOS signing values in the console instead of `.env` and environment variables.

**Architecture:** A Visto home (`~/.visto/`) holds a pinned, checksum-verified portable toolchain, the run data and a settings/secrets store. Settings and secrets are adapters read at use time by the backend and the CLI. New outer-ring modules (`visto/home.py`, `visto/instances.py`, `visto/toolchain/`, `visto/commands/`) bootstrap and supervise Appium and the backend; domain and application are untouched. The wheel carries the compiled console and the Appium lockfiles and is released by a GitHub Action.

**Tech Stack:** Python 3.12 stdlib + FastAPI/uvicorn (no new runtime dependency), React/TypeScript, SQLite, hatchling, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-easy-install-design.md`

## Global Constraints

- Follow `AGENTS.md`: Clean Architecture (domain/application import nothing new), device and app anonymity in every fixture/doc/commit, no device contact or billable inference, docs describe current state only, run `python scripts/check_project.py` after doc edits.
- No `.env`, no environment variable for `OPENAI_API_KEY`, `VISTO_IOS_*` or `VISTO_PRICE_REFRESH`. The process environment is never consulted for them.
- Never write to system/user environment variables, `PATH`, shell profiles; never require admin rights; never require Android Studio.
- The provider key never appears in any API response, log line, error detail, report or CLI output (last four characters in key status only).
- Every download is pinned and checksum-verified before extraction.
- Supported hosts: `win-x64`, `macos-arm64`, `macos-x64`, `linux-x64`. Android is always installed, on macOS too. Windows/Linux never show iOS wording, options or checks.
- No update-check network call anywhere.
- Default Visto home `Path.home() / ".visto"`; the home is a CLI option (`--home`), never an environment variable.
- No new runtime Python dependency. Version-sensitive APIs (uv tool install, GitHub Actions, Node distribution, Android repository, Adoptium API, OpenAI models endpoint, corepack) are verified against official docs and recorded in `docs/references.md` by the task that relies on them.
- Backend checks: `cd backend && uv run pytest -q` and `uv run ruff check src tests && uv run ruff format --check src tests`. Frontend checks: `cd frontend && pnpm test && pnpm lint`. Final: `python scripts/verify.py`.
- Commits only when the user has asked for them; this plan's commit steps are executed because the user asked for the work on branch `feature/easy-install`.

## Review Focus

1. **Archive with `..`, absolute or symlink entries** → extraction refuses and writes nothing outside the target (Task 6, `test_extract_rejects_traversal_and_links`).
2. **Setup interrupted mid-download or mid-extract** (Ctrl+C, network drop) → previous active version untouched, temp files removed, next `setup` completes (Task 6, `test_interrupted_install_keeps_previous_active`).
3. **Hand-edited or corrupt `settings.json` / `secrets.json`** (invalid JSON, wrong types, newer format) → a `SettingsError` naming the file kind, never its content; the API returns 503 with a fixed message; the console shows it (Task 2, `test_corrupt_files_raise_sanitized_errors`; Task 4, `test_settings_read_reports_store_error`).
4. **Key pasted with trailing newline or internal whitespace** → trailing/leading whitespace stripped, internal whitespace rejected, the 422 detail names the field only (Task 2, `test_set_api_key_normalizes_and_rejects`; Task 4, `test_key_validation_error_never_echoes_value`).
5. **Port 4723/8000 already in use, or Appium dies** → clear message, no orphaned Appium child after Ctrl+C or backend failure (Task 9, `test_start_refuses_busy_port` and `test_appium_child_terminated_on_exit`).

## File Map

| Path | Responsibility | Task |
|---|---|---|
| `backend/src/visto/home.py` | `VistoHome` paths, `default_home()` | 1 |
| `backend/src/visto/adapters/ios/signing.py` | `IOSSigning` value + capability mapping | 2 |
| `backend/src/visto/adapters/settings/{__init__,store}.py` | settings + secrets files | 2 |
| `backend/src/visto/configuration.py`, `.env.example`, `tests/test_configuration.py` | removed | 3 |
| `backend/src/visto/adapters/api/settings.py` | settings routes | 4 |
| `backend/src/visto/adapters/ai/{transport,http_worker}.py` | key probe | 4 |
| `backend/src/visto/adapters/storage/{migrations,sqlite}.py` | schema migrations, backup | 5 |
| `backend/src/visto/toolchain/{__init__,manifest,fetch,install}.py`, `components.json` | pinned portable components | 6 |
| `backend/src/visto/toolchain/{appium,license}.py`, `android-sdk-license.txt` | Appium install, license | 7 |
| `backend/src/visto/instances.py` | process registry | 8 |
| `backend/src/visto/commands/{__init__,setup,start,appium_process}.py`, composition static console | `setup`, `start` | 9 |
| `backend/src/visto/commands/{doctor,settings}.py`, `cli.py` | `doctor`, `settings`, `run` reuse | 10 |
| `frontend/src/settings.ts`, `frontend/src/components/SettingsView.tsx`, `App.tsx`, `ReadinessPanel.tsx` | settings page | 11 |
| `backend/pyproject.toml`, `scripts/build_release.py`, `scripts/check_wheel.py`, `.github/workflows/release.yml` | wheel + release | 12 |
| `docs/**`, `README.md`, `.gitignore` | documentation | 13 |

Suggested roles (`agents/roles/`): Tasks 1–5, 8, 10 backend; 6, 7, 9, 12 devops; 11 frontend; 13 coordinator; reviews qa.

---

### Task 1: Visto home and path wiring

**Files:**
- Create: `backend/src/visto/home.py`, `backend/tests/test_home.py`
- Modify: `backend/src/visto/composition.py` (`REPOSITORY`, `default_settings`, `create_app` signature), `backend/src/visto/runner.py:30`, `backend/src/visto/cli.py` (`--data-dir` default → home)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class VistoHome: root: Path` with properties `data -> root/"data"`, `leases -> root/"data"/"device-leases"`, `settings_file -> root/"settings.json"`, `secrets_file -> root/"secrets.json"`, `toolchain -> root/"toolchain"`, `instances -> root/"instances"`, `logs -> root/"logs"`.
  - `default_home() -> VistoHome` (`Path.home() / ".visto"`).
  - `create_app(service: ExecutionService | None = None, *, home: VistoHome | None = None) -> FastAPI` (home defaults to `default_home()`).
  - `RunnerSettings.lease_directory` keeps its field, defaulting to `default_home().leases` (via `field(default_factory=...)`).
  - CLI: every subcommand accepts `--home PATH`; `--data-dir` defaults to `<home>/data`.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_layout(tmp_path):
    home = VistoHome(tmp_path)
    assert home.data == tmp_path / "data"
    assert home.leases == tmp_path / "data" / "device-leases"
    assert home.settings_file == tmp_path / "settings.json"
    assert home.secrets_file == tmp_path / "secrets.json"

def test_default_home_is_user_dot_visto(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_home().root == tmp_path / ".visto"

def test_cli_data_dir_follows_home(tmp_path):  # in test_cli.py
    args = parser().parse_args(["inspect", "--home", str(tmp_path), "--run-id", "r"])
    assert resolved_data_dir(args) == tmp_path / "data"
```

Also update existing tests in `test_cli.py`/`test_api.py` that assert `.work/...` defaults.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_home.py tests/test_cli.py -q` — expect FAIL (module missing).
- [ ] **Step 3: Implement** `home.py`; remove `REPOSITORY` from `composition.py`; `default_settings(home: VistoHome) -> WebSettings` uses `home.data` and `home.leases`; add `resolved_data_dir(args) -> Path` in `cli.py` (explicit `--data-dir` wins).
- [ ] **Step 4: Run** the full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: introduce the Visto home for data and lease paths`.

### Task 2: Settings and secrets store

**Files:**
- Create: `backend/src/visto/adapters/ios/signing.py`, `backend/src/visto/adapters/settings/__init__.py`, `backend/src/visto/adapters/settings/store.py`, `backend/tests/test_settings_store.py`

**Interfaces:**
- Consumes: `VistoHome` (Task 1).
- Produces:
  - `signing.py`: `@dataclass(frozen=True) class IOSSigning: team_id: str = ""; signing_id: str = ""; wda_bundle_id: str = ""; prebuilt_wda: bool = False; wda_derived_data: str = ""` and `def capabilities(self) -> dict[str, object]` producing exactly today's mapping (`appium:xcodeOrgId`, `appium:xcodeSigningId`, `appium:updatedWDABundleId`, `appium:usePrebuiltWDA: True` only when `prebuilt_wda`, `appium:derivedDataPath` with `~` expanded, empty values omitted).
  - `store.py`: `class SettingsError(ValueError)`; `@dataclass(frozen=True) class Settings: price_refresh: bool = True; ios: IOSSigning = IOSSigning(); ios_saved_for_xcuitest: str | None = None`; `@dataclass(frozen=True) class KeyStatus: configured: bool; last4: str | None`; `class SettingsStore(home: VistoHome)` with `load() -> Settings`, `save(settings: Settings) -> None`, `api_key() -> str` (`""` when absent), `set_api_key(key: str) -> KeyStatus`, `delete_api_key() -> KeyStatus`, `key_status() -> KeyStatus`.
  - File formats (format `1`): `settings.json` = `{"format": 1, "price_refresh": bool, "ios": {team_id, signing_id, wda_bundle_id, prebuilt_wda, wda_derived_data}, "ios_saved_for_xcuitest": str|null}`; `secrets.json` = `{"format": 1, "openai_api_key": str}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_files_give_defaults(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    assert store.load() == Settings()
    assert store.api_key() == "" and store.key_status() == KeyStatus(False, None)

def test_round_trip_and_key_status(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.save(Settings(price_refresh=False, ios=IOSSigning(team_id="TEAM123")))
    assert store.load().ios.team_id == "TEAM123" and store.load().price_refresh is False
    assert store.set_api_key("sk-test-abcd1234") == KeyStatus(True, "1234")
    assert store.api_key() == "sk-test-abcd1234"
    assert store.delete_api_key() == KeyStatus(False, None)

def test_set_api_key_normalizes_and_rejects(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.set_api_key("  sk-test-wxyz\n")
    assert store.api_key() == "sk-test-wxyz"
    for bad in ("", "   ", "sk test", "sk-\ttab", "x" * 8193):
        with pytest.raises(SettingsError) as error:
            store.set_api_key(bad)
        assert bad.strip() == "" or bad.strip() not in str(error.value)

def test_corrupt_files_raise_sanitized_errors(tmp_path):
    home = VistoHome(tmp_path)
    home.settings_file.write_text('{"format": 1, "price_refresh": "yes-SECRETISH"}')
    with pytest.raises(SettingsError) as error:
        SettingsStore(home).load()
    assert "SECRETISH" not in str(error.value) and "settings" in str(error.value).lower()
    home.secrets_file.write_text("not json sk-leak")
    with pytest.raises(SettingsError) as error:
        SettingsStore(home).api_key()
    assert "sk-leak" not in str(error.value)

def test_newer_format_is_refused(tmp_path):
    home = VistoHome(tmp_path)
    home.settings_file.write_text('{"format": 2}')
    with pytest.raises(SettingsError, match="newer"):
        SettingsStore(home).load()

@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_secrets_file_is_owner_only(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.set_api_key("sk-test-mode")
    assert stat.S_IMODE(VistoHome(tmp_path).secrets_file.stat().st_mode) == 0o600

def test_ios_capabilities_match_previous_mapping():
    signing = IOSSigning("T", "Apple Development", "com.example.wda", True, "~/dd")
    caps = signing.capabilities()
    assert caps["appium:xcodeOrgId"] == "T" and caps["appium:usePrebuiltWDA"] is True
    assert caps["appium:derivedDataPath"] == str(Path("~/dd").expanduser())
    assert IOSSigning().capabilities() == {}
```

- [ ] **Step 2: Run** `uv run pytest tests/test_settings_store.py -q` — expect FAIL.
- [ ] **Step 3: Implement.** Writes are atomic (write a sibling temp file, `os.chmod(0o600)` on POSIX before content, `os.replace`). Create the home directory on first write. Strict type checks on load; error messages say "settings file is invalid" / "secrets file is invalid" / "… was written by a newer Visto".
- [ ] **Step 4: Run** the full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: add the settings and secrets store`.

### Task 3: Read settings at use; remove `.env`

**Files:**
- Modify: `backend/src/visto/adapters/api/service.py` (`WebSettings.env_file` → `settings_store: SettingsStore`, `key_resolver` removed, readiness/transcribe/create, price loop), `backend/src/visto/adapters/api/execution.py` (`/prices` `refresh_enabled`), `backend/src/visto/composition.py` (always set `price_fetcher`; the switch is read per refresh), `backend/src/visto/adapters/ios/device.py` (drop `_setting`, `SIGNING`, `os.environ`; accept `signing: IOSSigning`), `backend/src/visto/runner.py` (`RunnerSettings.ios_signing: IOSSigning = IOSSigning()`, passed to `XCUITestDevice`), `backend/src/visto/cli.py` (`run`/`doctor` read key and signing from the store; remove `--env-file`)
- Delete: `backend/src/visto/configuration.py`, `backend/tests/test_configuration.py`, `.env.example`
- Test: `backend/tests/test_api.py`, `test_ios_device.py`, `test_cli.py`, `test_pricing.py`

**Interfaces:**
- Consumes: `SettingsStore`, `Settings`, `IOSSigning` (Task 2).
- Produces: `XCUITestDevice(server_url, lease_directory, *, signing: IOSSigning = IOSSigning(), request_timeout_ms=..., cleanup_timeout_ms=..., wire=None)`; `ExecutionService(settings: WebSettings, *, runtime_factory=..., ...)` with `settings.settings_store`; `ExecutionService.refresh_prices()` returns `False` without fetching when `store.load().price_refresh` is false.

- [ ] **Step 1: Write the failing tests**

```python
def test_environment_key_is_ignored(monkeypatch, tmp_path):   # test_api.py
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    service = make_service(tmp_path)              # store with no key
    assert service.readiness()["provider_key_configured"] is False

def test_key_change_applies_without_restart(tmp_path):
    service = make_service(tmp_path)
    service.settings.settings_store.set_api_key("sk-test-live")
    assert service.readiness()["provider_key_configured"] is True

def test_run_snapshots_signing_at_create(tmp_path):
    # create a run with a fake runtime_factory capturing RunnerSettings,
    # then change the stored signing; captured ios_signing keeps the old value

def test_ios_capabilities_ignore_environment(monkeypatch):    # test_ios_device.py
    monkeypatch.setenv("VISTO_IOS_TEAM_ID", "ENVTEAM")
    device = XCUITestDevice("http://127.0.0.1:4723", Path("leases"), signing=IOSSigning(team_id="T"))
    assert device.capabilities("udid")["appium:xcodeOrgId"] == "T"

async def test_price_refresh_switch_read_per_refresh(tmp_path):  # test_pricing.py / test_api.py
    # store price_refresh False -> refresh_prices() returns False and fetcher not called;
    # set True -> fetcher called once
```

- [ ] **Step 2: Run** the touched test files — expect FAIL.
- [ ] **Step 3: Implement.** The runtime factory receives `RunnerSettings` with `ios_signing` taken from `store.load().ios` at create time. CLI error for a missing key: `"Provider key is not configured; set it in the console Settings page or with 'visto settings set-key'"`. Store errors in readiness map to `configuration_error = "Local settings are invalid; open Settings or check the Visto home"`.
- [ ] **Step 4: Run** the full backend suite and `grep -rn "OPENAI_API_KEY\|VISTO_IOS_\|VISTO_PRICE_REFRESH\|env_file" backend/src` — expect PASS and only the `transport.py` child-environment scrub left (keep it: it protects against an inherited variable).
- [ ] **Step 5: Commit** `refactor: read provider key and iOS signing from the settings store`.

### Task 4: Settings API and key verification

**Files:**
- Create: `backend/src/visto/adapters/api/settings.py`, `backend/tests/test_api_settings.py`
- Modify: `backend/src/visto/adapters/ai/transport.py` (add `probe_model`), `backend/src/visto/adapters/ai/http_worker.py` (probe packet), `backend/src/visto/composition.py` (include router, inject `ios_supported`, `wda_project`, `xcuitest_version` callables), `backend/tests/test_ai_transport.py`, `docs/references.md` (OpenAI retrieve-model endpoint)

**Interfaces:**
- Consumes: `SettingsStore` (Task 2), `require_local_write` from `execution.py`.
- Produces (all under `/api`, writes guarded by `require_local_write`):
  - `GET /settings` → `{"price_refresh": bool, "ios_supported": bool, "ios": {team_id, signing_id, wda_bundle_id, prebuilt_wda, wda_derived_data} | null, "key": {"configured": bool, "last4": str|null, "storage": "file"}, "wda_project": str|null, "wda_rebuild_needed": bool}` (`ios`, `wda_project` are `null` and `wda_rebuild_needed` false when not supported).
  - `PUT /settings` body `{"price_refresh": bool, "ios": {...} | null}` (strict, `extra="forbid"`; non-null `ios` on a non-iOS host → 422 `"iOS settings are not available on this host"`). Saving `ios` records `ios_saved_for_xcuitest = xcuitest_version()`. Returns the GET shape.
  - `PUT /settings/key` body `{"api_key": str}` → `{"configured", "last4", "storage"}`; `DELETE /settings/key` → same.
  - `POST /settings/key/verify` → `{"result": "ok" | "missing" | "unauthorized" | "model_unavailable" | "unreachable"}`.
  - `transport.probe_model(api_key: str, model: str, timeout_ms: int) -> dict` — GET `https://api.openai.com/v1/models/{model}` through the same fixed child; the worker accepts packet `{"api_key", "probe_model", "timeout_ms"}` with `probe_model` matching `^[A-Za-z0-9._-]{1,128}$`. Verify the endpoint in the provider's official reference first.
  - `SettingsRoutesConfig` injected via `app.state.settings_host` with `ios_supported: bool`, `wda_project: Callable[[], Path | None]`, `xcuitest_version: Callable[[], str | None]` (defaults: `sys.platform == "darwin"`, `lambda: None`, `lambda: None`; Task 9 wires real ones).

- [ ] **Step 1: Write the failing tests**

```python
def test_key_is_write_only(client, store):
    r = client.put("/api/settings/key", json={"api_key": "sk-test-abcd9876"}, headers=LOCAL)
    assert r.json() == {"configured": True, "last4": "9876", "storage": "file"}
    for path in ("/api/settings", "/api/readiness"):
        assert "sk-test-abcd9876" not in client.get(path).text

def test_settings_writes_require_local_console(client):
    assert client.put("/api/settings/key", json={"api_key": "sk-x"}).status_code == 403
    assert client.put("/api/settings/key", json={"api_key": "sk-x"},
                      headers={**LOCAL, "Origin": "http://evil.example"}).status_code == 403

def test_key_validation_error_never_echoes_value(client):
    r = client.put("/api/settings/key", json={"api_key": "sk bad SPACE"}, headers=LOCAL)
    assert r.status_code == 422 and "SPACE" not in r.text

def test_ios_hidden_and_rejected_off_mac(client_non_ios):
    assert client_non_ios.get("/api/settings").json()["ios"] is None
    r = client_non_ios.put("/api/settings", json={"price_refresh": True, "ios": IOS_BODY}, headers=LOCAL)
    assert r.status_code == 422

def test_wda_rebuild_needed_after_driver_change(client_ios, host):
    client_ios.put("/api/settings", json={"price_refresh": True, "ios": IOS_BODY}, headers=LOCAL)
    host.version = "99.0.0"
    assert client_ios.get("/api/settings").json()["wda_rebuild_needed"] is True

def test_settings_read_reports_store_error(client, home):
    home.settings_file.write_text("{broken")
    r = client.get("/api/settings")
    assert r.status_code == 503 and "broken" not in r.text

@pytest.mark.parametrize("code,result", [(None, "ok"), ("provider: http_401", "unauthorized"),
    ("provider: http_404", "model_unavailable"), ("provider: timeout", "unreachable")])
def test_verify_maps_probe_outcomes(client_with_probe, code, result): ...

def test_worker_probe_uses_fixed_get(monkeypatch):  # test_ai_transport.py
    # handle_packet({"api_key": "k", "probe_model": "gpt-6-luna", "timeout_ms": 1000})
    # issues GET to https://api.openai.com/v1/models/gpt-6-luna; invalid model id -> invalid_request
```

- [ ] **Step 2: Run** `uv run pytest tests/test_api_settings.py tests/test_ai_transport.py -q` — expect FAIL.
- [ ] **Step 3: Implement.** Verification probes `WebSettings.model` (the default allowlisted vision model). Store errors map to 503 `"Local settings are invalid"`.
- [ ] **Step 4: Run** the full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: add settings API with write-only provider key`.

### Task 5: SQLite migrations with backup

**Files:**
- Create: `backend/src/visto/adapters/storage/migrations.py`, `backend/tests/test_storage_migrations.py`
- Modify: `backend/src/visto/adapters/storage/sqlite.py:36-62`

**Interfaces:**
- Produces: `CURRENT_VERSION = 1`; `MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]]` (key = target version; empty today besides the v0→v1 create); `class SchemaTooNew(ValueError)`; `def schema_version(database: Path) -> int` (0 when missing, read-only); `def migrate(database: Path, *, migrations=MIGRATIONS, current=CURRENT_VERSION, now: Callable[[], datetime]) -> Path | None` (returns backup path when it migrated an existing non-empty database). `SQLiteRunStore.__init__` calls `migrate` and raises `PortError("storage: database is newer than this Visto")` for `SchemaTooNew`.

- [ ] **Step 1: Write the failing tests**

```python
def test_fresh_database_created_at_current(tmp_path):
    db = tmp_path / "runs.sqlite3"
    assert migrate(db) is None and schema_version(db) == CURRENT_VERSION

def test_existing_database_backed_up_before_migration(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    steps = {2: lambda c: c.execute("CREATE TABLE extra (x)")}
    backup = migrate(db, migrations=steps, current=2, now=lambda: FIXED)
    assert backup.name == "runs.sqlite3.v1-20261025T120000Z.bak"
    assert schema_version(backup) == 1 and schema_version(db) == 2

def test_failed_migration_leaves_database_unchanged(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    with pytest.raises(sqlite3.Error):
        migrate(db, migrations={2: failing_step}, current=2, now=lambda: FIXED)
    assert schema_version(db) == 1 and run_count(db) == 1

def test_newer_database_refused(tmp_path):
    db = make_database_with_version(tmp_path, 7)
    with pytest.raises(SchemaTooNew):
        migrate(db)
```

- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** Backup with `sqlite3.Connection.backup` into the data directory; each migration step plus its `PRAGMA user_version` update runs in one `BEGIN IMMEDIATE` transaction.
- [ ] **Step 4: Run** full backend suite — expect PASS (existing storage tests unchanged).
- [ ] **Step 5: Commit** `feat: add numbered SQLite migrations with backup`.

### Task 6: Toolchain manifest, verified download, atomic install

**Files:**
- Create: `backend/src/visto/toolchain/__init__.py`, `manifest.py`, `fetch.py`, `install.py`, `components.json`, `backend/tests/test_toolchain.py`
- Modify: `docs/references.md` (Node distribution + SHASUMS256, Adoptium API, Android repository XML and checksums)

**Interfaces:**
- Consumes: `VistoHome` (Task 1).
- Produces:
  - `class UnsupportedHost(ValueError)`; `host_key(system: str | None = None, machine: str | None = None) -> str` returning one of the four keys (`AMD64`/`x86_64` → x64, `arm64`/`aarch64` → arm64 on Darwin only).
  - `@dataclass(frozen=True) class Archive: url: str; checksum: str  # "sha256:<hex>" or "sha1:<hex>"; kind: Literal["zip","tar.gz","tar.xz"]; strip: str | None; dest: str`; `@dataclass(frozen=True) class Component: name: str; version: str; archives: tuple[Archive, ...]`; `load_manifest() -> dict[str, dict[str, Component]]` (component → host → Component) from `components.json`.
  - Components and layout: `node` → `toolchain/node/<v>/`; `jdk` → `toolchain/jdk/<v>/`; `android-sdk` (two archives: platform-tools → `platform-tools/`, build-tools → `build-tools/<bt-version>/`) → `toolchain/android-sdk/<v>/` where `<v>` is `pt<ptver>-bt<btver>`.
  - `class ChecksumMismatch(ValueError)`, `class UnsafeArchive(ValueError)`; `download(url: str, target: Path, checksum: str, *, opener: Callable[[str], BinaryIO], ca_bundle: Path | None = None) -> Path`; `extract(archive: Path, kind: str, target: Path, strip: str | None) -> None`.
  - `@dataclass class ToolchainState: active: dict[str, str]; android_license_sha256: str | None; ca_bundle: str | None` stored in `toolchain/state.json` (format 1).
  - `class Toolchain(home: VistoHome)`: `state() -> ToolchainState`, `pending(components: Iterable[Component]) -> list[Component]`, `install(component: Component, *, opener, ca_bundle=None) -> None`, `activate(name: str, version: str) -> None`, `prune() -> None`, `paths() -> ToolPaths`.
  - `@dataclass(frozen=True) class ToolPaths: node: Path; java_home: Path; android_home: Path; adb: Path; appium_dir: Path | None` and `child_env(paths: ToolPaths, base: Mapping[str, str], ca_bundle: str | None) -> dict[str, str]` (sets `ANDROID_HOME`, `ANDROID_SDK_ROOT`, `JAVA_HOME`, prepends node, `java_home/bin`, `android_home/platform-tools` to `PATH`, adds `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE` when a CA bundle is set, removes `OPENAI_API_KEY`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("system,machine,key", [("Windows","AMD64","win-x64"), ("Darwin","arm64","macos-arm64"),
    ("Darwin","x86_64","macos-x64"), ("Linux","x86_64","linux-x64")])
def test_host_key(system, machine, key): assert host_key(system, machine) == key

def test_unsupported_hosts(): 
    for s, m in (("Windows","ARM64"), ("Linux","aarch64"), ("FreeBSD","amd64")):
        with pytest.raises(UnsupportedHost): host_key(s, m)

def test_manifest_covers_every_host_and_pins_checksums():
    manifest = load_manifest()
    for name in ("node", "jdk", "android-sdk"):
        assert set(manifest[name]) == {"win-x64", "macos-arm64", "macos-x64", "linux-x64"}
        for comp in manifest[name].values():
            assert all(re.fullmatch(r"(sha256:[0-9a-f]{64}|sha1:[0-9a-f]{40})", a.checksum) for a in comp.archives)
            assert all(a.url.startswith("https://") for a in comp.archives)

def test_download_rejects_checksum_mismatch(tmp_path):
    with pytest.raises(ChecksumMismatch):
        download("https://example.invalid/a.zip", tmp_path / "a.zip", "sha256:" + "0"*64, opener=fake_opener(b"data"))
    assert not (tmp_path / "a.zip").exists()

def test_extract_rejects_traversal_and_links(tmp_path):
    for archive in (zip_with("../evil", b"x"), zip_with("/abs", b"x"), tar_with_symlink("link", "/etc")):
        with pytest.raises(UnsafeArchive): extract(archive, kind_of(archive), tmp_path / "out", None)
    assert not (tmp_path / "evil").exists()

def test_install_is_idempotent_and_side_by_side(tmp_path):
    tc = Toolchain(VistoHome(tmp_path)); comp = fake_component("node", "1.0.0")
    tc.install(comp, opener=serving(comp)); tc.activate("node", "1.0.0")
    assert tc.pending([comp]) == []
    newer = fake_component("node", "2.0.0"); tc.install(newer, opener=serving(newer)); tc.activate("node", "2.0.0")
    assert (tmp_path / "toolchain/node/1.0.0").exists(); tc.prune()
    assert not (tmp_path / "toolchain/node/1.0.0").exists() and tc.state().active["node"] == "2.0.0"

def test_interrupted_install_keeps_previous_active(tmp_path):
    tc = Toolchain(VistoHome(tmp_path)); installed_and_active(tc, "node", "1.0.0")
    with pytest.raises(KeyboardInterrupt):
        tc.install(fake_component("node", "2.0.0"), opener=interrupting_opener())
    assert tc.state().active["node"] == "1.0.0"
    assert not (tmp_path / "toolchain/node/2.0.0").exists()
    assert list((tmp_path / "toolchain").glob("**/.tmp-*")) == []

def test_child_env_is_scoped(tmp_path):
    env = child_env(paths_in(tmp_path), {"PATH": "/usr/bin", "OPENAI_API_KEY": "k"}, None)
    assert env["ANDROID_HOME"] == str(tmp_path / "sdk") and "OPENAI_API_KEY" not in env
    assert env["PATH"].split(os.pathsep)[-1] == "/usr/bin" and os.environ.get("ANDROID_HOME") != env["ANDROID_HOME"]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_toolchain.py -q` — expect FAIL.
- [ ] **Step 3: Fill `components.json`** with real pins: Node `24.19.0` (from `https://nodejs.org/dist/v24.19.0/SHASUMS256.txt`), Temurin JDK 17 LTS latest GA (Adoptium API checksum), Android platform-tools and build-tools versions from Google's `repository2-3.xml` (sha1). Record each source in `docs/references.md`. Network reads of these metadata files are allowed; no device, no provider.
- [ ] **Step 4: Implement.** Downloads stream into `toolchain/.tmp-<random>/`, verify, extract there, then `os.replace` into `toolchain/<name>/<version>/`; `try/finally` removes the temp dir. State writes are atomic. `strip` removes the archive's single top-level folder (e.g. `node-v24.19.0-win-x64`). `urllib` opener honours `ca_bundle` via `ssl.create_default_context(cafile=...)`.
- [ ] **Step 5: Run** full backend suite — expect PASS.
- [ ] **Step 6: Commit** `feat: add pinned portable toolchain installer`.

### Task 7: Appium install and Android SDK license

**Files:**
- Create: `backend/src/visto/toolchain/appium.py`, `backend/src/visto/toolchain/license.py`, `backend/src/visto/toolchain/android-sdk-license.txt`, `backend/tests/test_toolchain_appium.py`
- Modify: `tools/appium/package.json`, `tools/appium/macos/package.json` (`packageManager` with `+sha512.<hash>` integrity, verified against corepack docs), `docs/references.md` (corepack, Android SDK terms)

**Interfaces:**
- Consumes: `Toolchain`, `ToolPaths`, `child_env` (Task 6).
- Produces:
  - `appium_flavor(host: str) -> Literal["default", "macos"]`.
  - `appium_resources(flavor: str) -> Path` — the directory holding `package.json` + `pnpm-lock.yaml`: package resource `visto/toolchain/appium/<flavor>/` when present (wheel), else repository `tools/appium` / `tools/appium/macos` (contributor checkout); `FileNotFoundError` otherwise.
  - `appium_version(flavor: str) -> str` = `"<flavor>-" + sha256(lockfile)[:12]`.
  - `install_appium(toolchain: Toolchain, flavor: str, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None` — copies both files into `toolchain/appium/<version>/`, runs `[node, <corepack.js>, "pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--node-linker=hoisted"]` with `child_env(...)` plus `COREPACK_HOME=<toolchain>/corepack` and `COREPACK_ENABLE_DOWNLOAD_PROMPT=0`, cwd = that directory, timeout 900 s; on failure removes the directory.
  - `installed_driver_version(appium_dir: Path, package: str) -> str | None` (reads `node_modules/<package>/package.json`).
  - `wda_project(appium_dir: Path) -> Path | None` (bounded search, depth ≤ 4, for `WebDriverAgent.xcodeproj` under `node_modules`).
  - `license.py`: `LICENSE_TEXT: str`, `LICENSE_SHA256: str`, `license_accepted(state: ToolchainState) -> bool`, `record_acceptance(toolchain: Toolchain) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_flavor_per_host():
    assert appium_flavor("macos-arm64") == "macos" and appium_flavor("win-x64") == "default"

def test_install_appium_runs_frozen_hoisted_install(tmp_path):
    calls = []
    install_appium(toolchain_with_node(tmp_path), "default", run=recording(calls, rc=0))
    argv, kwargs = calls[0]
    assert argv[-4:] == ["install", "--frozen-lockfile", "--ignore-scripts", "--node-linker=hoisted"]
    assert kwargs["env"]["COREPACK_ENABLE_DOWNLOAD_PROMPT"] == "0" and "OPENAI_API_KEY" not in kwargs["env"]
    assert kwargs.get("shell", False) is False and kwargs["cwd"].name.startswith("default-")

def test_failed_appium_install_leaves_nothing(tmp_path):
    tc = toolchain_with_node(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        install_appium(tc, "default", run=recording([], rc=1))
    assert not any((tmp_path / "toolchain/appium").glob("default-*"))

def test_license_acceptance_is_tied_to_text(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    assert not license_accepted(tc.state()); record_acceptance(tc)
    assert tc.state().android_license_sha256 == LICENSE_SHA256 and license_accepted(tc.state())

def test_wda_project_found(tmp_path):
    p = tmp_path / "node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj"; p.mkdir(parents=True)
    assert wda_project(tmp_path) == p
```

- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; copy the Android SDK license text from Google's repository XML `android-sdk-license` element into `android-sdk-license.txt` (cite in references).
- [ ] **Step 4: Run** full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: install pinned Appium and record SDK license acceptance`.

### Task 8: Visto process registry

**Files:**
- Create: `backend/src/visto/instances.py`, `backend/tests/test_instances.py`

**Interfaces:**
- Consumes: `VistoHome`.
- Produces: `@dataclass(frozen=True) class Instance: pid: int; kind: str; started_at: str`; `@contextmanager def registered(home: VistoHome, kind: Literal["start","run","inspect","setup"]) -> Iterator[Instance]` (writes `instances/<pid>.json` atomically, removes it on exit); `def others(home: VistoHome) -> list[Instance]` (excludes the current PID, drops and deletes entries whose PID is not alive); `class Busy(RuntimeError)`; `def exclusive(home, kind) -> ContextManager[Instance]` raising `Busy` when `others()` is non-empty (used by `setup` and migrations).
- Liveness: `os.kill(pid, 0)` on POSIX; on Windows `OpenProcess` via `ctypes` + `GetExitCodeProcess == STILL_ACTIVE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_registration_visible_to_others(tmp_path):
    home = VistoHome(tmp_path)
    with registered(home, "start"):
        write_entry(home, pid=os.getppid(), kind="run")        # a live foreign pid
        assert [i.kind for i in others(home)] == ["run"]
    assert not (home.instances / f"{os.getpid()}.json").exists()

def test_dead_entries_are_cleared(tmp_path):
    home = VistoHome(tmp_path); write_entry(home, pid=dead_pid(), kind="start")
    assert others(home) == [] and list(home.instances.glob("*.json")) == []

def test_exclusive_refuses_when_busy(tmp_path):
    home = VistoHome(tmp_path); write_entry(home, pid=os.getppid(), kind="start")
    with pytest.raises(Busy): 
        with exclusive(home, "setup"): pass

def test_stale_device_leases_do_not_block(tmp_path):
    home = VistoHome(tmp_path); (home.leases).mkdir(parents=True); (home.leases / "x.lease").write_text("{}")
    with exclusive(home, "setup"): pass
```

- [ ] **Step 2–4:** run (FAIL), implement, run full suite (PASS).
- [ ] **Step 5: Commit** `feat: register Visto processes in the home`.

### Task 9: `visto setup` and `visto start`

**Files:**
- Create: `backend/src/visto/commands/__init__.py`, `setup.py`, `start.py`, `appium_process.py`, `backend/tests/test_commands_setup.py`, `backend/tests/test_commands_start.py`
- Modify: `backend/src/visto/composition.py` (static console + SPA fallback, managed `adb`, real settings-host callables), `backend/src/visto/cli.py` (subcommands `setup`, `start`), `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Tasks 1–8.
- Produces:
  - `run_setup(home: VistoHome, *, accept_license: bool | None, ca_bundle: Path | None, host: str | None = None, opener=..., run=subprocess.run, ask: Callable[[str], str] = input, output=print) -> int` — under `exclusive(home, "setup")`; computes pending components (node, jdk, android-sdk, appium flavor); prompts for the license (text + `Accept the Android SDK license? [y/N]`) unless accepted for the current text or `accept_license is True`; `accept_license is False` or a "no" answer → exit 2 without downloading Android components; prints each component it fetches; activates, prunes; stores `ca_bundle` in state. Exit codes: 0 ok, 2 license declined, 3 failure, 4 busy.
  - `AppiumProcess` in `appium_process.py`: `start(paths: ToolPaths, env: dict, port: int, log_file: Path, *, popen=subprocess.Popen, ready_timeout_s: float = 60) -> AppiumProcess` (refuses with `PortBusy` if `127.0.0.1:<port>` accepts a TCP connection before launch; launches `node <appium_dir>/node_modules/appium/index.js --address 127.0.0.1 --port <port> --log-level warn`, cwd = `appium_dir`, stdout/stderr → log file; waits for `GET /status` 200), `stop(timeout_s: float = 10) -> None` (terminate, then kill; on Windows use `CREATE_NEW_PROCESS_GROUP` and `taskkill /T /F` as fallback so drivers die too), `alive() -> bool`; `appium_running(port: int) -> bool` (GET `/status`).
  - `run_start(home: VistoHome, *, port: int = 8000, appium_port: int = 4723, open_browser: bool = True, serve=uvicorn_serve, output=print, **setup_kwargs) -> int` — `registered(home, "start")`; if `others()` contains another `start` → exit 4 "Visto is already running"; if toolchain pending → `run_setup(...)` first (message "Updating components: …"); when the stored CA bundle is set, sets `SSL_CERT_FILE` in its own process environment so the provider worker inherits it; when `schema_version(db) < CURRENT_VERSION` and `others()` is non-empty → exit 4 "Stop other Visto processes before upgrading data"; migrations via `SQLiteRunStore` construction (SchemaTooNew → exit 3 with "This data was written by a newer Visto; install that version or restore a backup from <data dir>"); starts `AppiumProcess`; serves `create_app(home=home)` on `127.0.0.1:<port>` (port busy → exit 3 "Port <port> is in use; pass --port"); opens `http://127.0.0.1:<port>/` with `webbrowser.open` when `open_browser`; `finally` stops Appium; Appium dying while serving → message and exit 3.
  - `create_app(..., home=...)`: when `importlib.resources.files("visto") / "console" / "index.html"` exists, serve `/assets/*` and other files from it and `index.html` for any non-`/api` GET path not found; `/api/*` unknown paths stay 404 JSON. Composition uses `Toolchain(home).paths().adb` when the toolchain is installed, else `find_adb()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_setup_declined_license_downloads_no_android(tmp_path):
    opener = recording_opener()
    assert run_setup(VistoHome(tmp_path), accept_license=None, ca_bundle=None, host="win-x64",
                     opener=opener, ask=lambda _: "n", run=ok_run) == 2
    assert not any("android" in url or "platform-tools" in url for url in opener.urls)

def test_setup_on_windows_never_mentions_ios(tmp_path, capsys):
    run_setup(VistoHome(tmp_path), accept_license=True, ca_bundle=None, host="win-x64",
              opener=fake_all(), run=ok_run, output=print)
    out = capsys.readouterr().out
    assert not re.search(r"ios|xcode|xcuitest|webdriveragent", out, re.I)

def test_setup_refuses_when_busy(tmp_path):
    home = VistoHome(tmp_path); write_entry(home, pid=os.getppid(), kind="start")
    assert run_setup(home, accept_license=True, ca_bundle=None, host="linux-x64", opener=fake_all(), run=ok_run) == 4

def test_start_refuses_busy_port(tmp_path):
    with listening_socket() as port:
        assert run_start(installed_home(tmp_path), port=port, open_browser=False, serve=never) == 3

def test_appium_child_terminated_on_exit(tmp_path):
    proc = FakePopen()
    assert run_start(installed_home(tmp_path), open_browser=False, serve=raising(RuntimeError),
                     popen=lambda *a, **k: proc) == 3
    assert proc.terminated or proc.killed

def test_appium_env_is_child_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    captured = {}
    run_start(installed_home(tmp_path), open_browser=False, serve=immediate, popen=capturing(captured))
    assert "ANDROID_HOME" in captured["env"] and "ANDROID_HOME" not in os.environ

def test_console_served_with_spa_fallback(tmp_path, monkeypatch):   # test_api.py
    client = client_with_console(tmp_path, index="<div id=root>")
    assert client.get("/").text == "<div id=root>" and client.get("/settings").text == "<div id=root>"
    assert client.get("/api/nope").status_code == 404
```

- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; `uvicorn_serve(app, port)` wraps `uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))`. Appium log goes to `home.logs / "appium.log"` (private; Task 13 documents it).
- [ ] **Step 4: Run** full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: add visto setup and visto start`.

### Task 10: `visto doctor`, `visto settings`, `run` Appium reuse

**Files:**
- Create: `backend/src/visto/commands/doctor.py`, `backend/src/visto/commands/settings.py`, `backend/tests/test_commands_doctor.py`, `backend/tests/test_commands_settings.py`
- Modify: `backend/src/visto/cli.py` (dispatch; `run` reuses or spawns Appium; `run`/`inspect` registered; existing doctor JSON moved behind `--json`), `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2, 6–9.
- Produces:
  - `@dataclass(frozen=True) class Check: name: str; ok: bool | None  # None = warning/info; detail: str`.
  - `collect_checks(home: VistoHome, *, host: str, adb_server_version: Callable[[], int | None], adb_client_version: Callable[[Path], int | None], xcrun_tool: Callable[[str], bool], appium_up: Callable[[], bool]) -> list[Check]` — all hosts: toolchain matches manifest, Android license accepted, Appium reachable (info when not running), adb works + device states (`unauthorized` → "accept the USB debugging prompt on the phone"), provider key configured (presence only), retained leases listed with device id, run id, PID and the recovery doc pointer, a warning when a running adb server's version differs from the managed adb. macOS only: `xcrun simctl`, `xcrun devicectl`, iOS signing presence, `wda_project` path, warning when `installed_driver_version(appium_dir, "appium-xcuitest-driver") != settings.ios_saved_for_xcuitest`.
  - `adb_server_version(port: int = 5037, timeout_s: float = 2) -> int | None` — sends `000chost:version` over TCP, parses `OKAY` + 4-hex-length + hex version; `None` when nothing listens.
  - `run_doctor(home, *, json_output: bool, output=print, **probes) -> int` (0 when no check is `False`, else 2). Human output one line per check: `[ok]`, `[!!]`, `[--]`.
  - `run_settings(home, action: Literal["set-key","delete-key","verify-key","show"], *, stdin=sys.stdin, output=print, probe=probe_model) -> int` — `set-key` reads one line from stdin (never argv), prints only the key status; `verify-key` prints the verify result word.
  - `cli.main` subcommands: `setup [--accept-android-license] [--ca-bundle PATH]`, `start [--port] [--appium-port] [--no-browser]`, `doctor [--json]`, `settings {set-key,delete-key,verify-key,show}`, `run`, `inspect`; all take `--home`. `run`: if `appium_running(4723)` use it, else `AppiumProcess.start(...)` for the run's duration and stop it afterwards.
  - `pyproject` entry point target: `visto.cli:entry` (`def entry() -> None: sys.exit(main())`).

- [ ] **Step 1: Write the failing tests**

```python
def test_doctor_hides_ios_off_mac(tmp_path):
    names = [c.name for c in collect_checks(VistoHome(tmp_path), host="linux-x64", **probes())]
    assert not any(re.search(r"ios|xcode|webdriveragent", n, re.I) for n in names)

def test_doctor_warns_on_xcuitest_change(tmp_path):
    home = mac_home(tmp_path, saved_for="12.19.1", installed="13.0.0")
    assert any(c.ok is None and "WebDriverAgent" in c.detail for c in collect_checks(home, host="macos-arm64", **probes()))

def test_doctor_lists_retained_leases(tmp_path):
    home = home_with_lease(tmp_path, device_id="device-A", run_id="run-1", pid=4242)
    detail = next(c.detail for c in collect_checks(home, host="win-x64", **probes()) if c.name == "Device leases")
    assert "device-A" in detail and "run-1" in detail

def test_doctor_warns_on_adb_server_mismatch(tmp_path):
    checks = collect_checks(installed(tmp_path), host="win-x64", **probes(server=40, client=41))
    assert any(c.ok is None and "adb" in c.name.lower() for c in checks)

def test_doctor_never_prints_key(tmp_path, capsys):
    home = installed(tmp_path); SettingsStore(home).set_api_key("sk-test-secret77")
    run_doctor(home, json_output=False, **probes()); run_doctor(home, json_output=True, **probes())
    assert "sk-test-secret77" not in capsys.readouterr().out

def test_adb_server_version_parses_reply():
    with fake_adb_server(b"OKAY0004002a") as port: assert adb_server_version(port) == 42

def test_set_key_reads_stdin_only(tmp_path, capsys):
    assert run_settings(VistoHome(tmp_path), "set-key", stdin=io.StringIO("sk-test-stdin1\n")) == 0
    assert "sk-test-stdin1" not in capsys.readouterr().out
    with pytest.raises(SystemExit): parser().parse_args(["settings", "set-key", "sk-arg"])

def test_run_reuses_running_appium(tmp_path):  # test_cli.py: appium_running -> True => no AppiumProcess.start
def test_run_spawns_and_stops_appium(tmp_path):  # appium_running -> False => start then stop
```

- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full backend suite — expect PASS.
- [ ] **Step 5: Commit** `feat: add visto doctor and settings commands`.

### Task 11: Console settings page

**Files:**
- Create: `frontend/src/settings.ts`, `frontend/src/components/SettingsView.tsx`, `frontend/tests/settings.test.mjs`
- Modify: `frontend/src/App.tsx` (hash route `#settings`, first-load redirect when `provider_key_configured` is false and no run hash), `frontend/src/components/ReadinessPanel.tsx` ("Open settings" button when the key is missing; key fact text "Configured" / "Missing"), `frontend/src/style.css`

**Interfaces:**
- Consumes: Task 4 API shapes exactly.
- Produces (`settings.ts`):
  - `interface IosSettings { team_id: string; signing_id: string; wda_bundle_id: string; prebuilt_wda: boolean; wda_derived_data: string }`
  - `interface KeyStatus { configured: boolean; last4: string | null; storage: 'file' }`
  - `interface SettingsView { price_refresh: boolean; ios_supported: boolean; ios: IosSettings | null; key: KeyStatus; wda_project: string | null; wda_rebuild_needed: boolean }`
  - `type VerifyResult = 'ok' | 'missing' | 'unauthorized' | 'model_unavailable' | 'unreachable'`
  - `parseSettings(value: unknown): SettingsView | null`, `parseKeyStatus(value: unknown): KeyStatus | null`, `parseVerify(value: unknown): VerifyResult | null`, `settingsFromHash(hash: string): boolean`, `verifyMessage(result: VerifyResult): string`, and client calls `loadSettings()`, `saveSettings(body)`, `setKey(apiKey)`, `deleteKey()`, `verifyKey()` built on `apiRequest`.
- UI: key section shows "Configured, ending in ••••1234" or "Not configured", a password-type input (cleared after save), Save / Remove / Verify; the key input value is never stored in state beyond submit. iOS section rendered only when `ios_supported && ios !== null`, with the five fields, the read-only WebDriverAgent project path, and a warning when `wda_rebuild_needed`. Price refresh toggle. A plain note that the key is stored in plain text in the Visto folder, readable only by this user.

- [ ] **Step 1: Write the failing tests**

```js
test('settings view parsing hides iOS when unsupported', () => {
  const base = { price_refresh: true, ios_supported: false, ios: null,
    key: { configured: false, last4: null, storage: 'file' }, wda_project: null, wda_rebuild_needed: false };
  assert.deepEqual(parseSettings(base), base);
  assert.equal(parseSettings({ ...base, ios_supported: false, ios: { team_id: 'x' } }), null);
  assert.equal(parseSettings({ ...base, key: { configured: true, last4: 'toolong', storage: 'file' } }), null);
});
test('settings hash route', () => {
  assert.equal(settingsFromHash('#settings'), true);
  assert.equal(settingsFromHash('#run/abc'), false);
});
test('verify results have operator messages', () => {
  for (const r of ['ok', 'missing', 'unauthorized', 'model_unavailable', 'unreachable']) assert.ok(verifyMessage(r).length > 0);
  assert.equal(parseVerify({ result: 'maybe' }), null);
});
test('setKey sends the key only in the body of a local write', async () => {
  const calls = []; await setKey('sk-test-1', fakeFetch(calls, { configured: true, last4: 'st-1', storage: 'file' }));
  assert.equal(calls[0].init.method, 'PUT'); assert.equal(calls[0].init.headers['X-Visto'], 'local-console');
  assert.ok(!calls[0].url.includes('sk-test-1'));
});
```

- [ ] **Step 2: Run** `cd frontend && pnpm test` — expect FAIL.
- [ ] **Step 3: Implement** (client functions accept an optional `fetcher` like `apiRequest` for tests).
- [ ] **Step 4: Run** `pnpm test && pnpm lint && pnpm build` — expect PASS.
- [ ] **Step 5: Commit** `feat: add console settings page`.

### Task 12: Wheel contents and release workflow

**Files:**
- Create: `scripts/build_release.py`, `scripts/check_wheel.py`, `scripts/tests/test_release_scripts.py`, `.github/workflows/release.yml`
- Modify: `backend/pyproject.toml` (`[project.scripts] visto = "visto.cli:entry"`; `[tool.hatch.build.targets.wheel] artifacts = ["src/visto/console/**", "src/visto/toolchain/appium/**"]`; include `components.json`, `android-sdk-license.txt`), `.gitignore` (`backend/src/visto/console/`, `backend/src/visto/toolchain/appium/`), `scripts/verify.py` only if needed for the new script tests, `docs/references.md` (hatch artifacts, GitHub Actions used, `uv tool install` from a URL)

**Interfaces:**
- Produces:
  - `build_release.py`: `main(argv) -> int` — requires installed frontend deps; runs the frontend production build; copies `frontend/dist/` → `backend/src/visto/console/`, `tools/appium/{package.json,pnpm-lock.yaml}` → `backend/src/visto/toolchain/appium/default/`, `tools/appium/macos/{…}` → `…/appium/macos/`; runs `uv build --wheel` in `backend`; prints the wheel path.
  - `check_wheel.py`: `missing_entries(wheel: Path) -> list[str]` requiring `visto/console/index.html`, `visto/toolchain/components.json`, `visto/toolchain/android-sdk-license.txt`, `visto/toolchain/appium/default/pnpm-lock.yaml`, `visto/toolchain/appium/macos/pnpm-lock.yaml`, `visto/prompts/agent-core.md`, and an `entry_points.txt` containing `visto = visto.cli:entry`; `main(argv) -> int`.
  - `release.yml`: on `push` tags `v*`; `permissions: contents: write`; steps: checkout, setup uv (pinned), setup Node `24.19.0`, `corepack enable`, `uv sync --project backend --locked --all-groups`, `pnpm install --frozen-lockfile` in `frontend`, fail if tag ≠ `v` + `pyproject` version, `python scripts/verify.py`, `python scripts/build_release.py`, `python scripts/check_wheel.py <wheel>`, write `<wheel>.sha256`, create the release with `gh release create "$TAG" <wheel> <wheel>.sha256 --generate-notes`. Actions pinned by commit SHA with the version in a comment.

- [ ] **Step 1: Write the failing tests**

```python
def test_check_wheel_reports_missing(tmp_path):
    wheel = make_zip(tmp_path / "visto-0.1.0-py3-none-any.whl", {"visto/__init__.py": ""})
    assert "visto/console/index.html" in missing_entries(wheel)

def test_check_wheel_accepts_complete(tmp_path):
    assert missing_entries(make_complete_wheel(tmp_path)) == []
```

- [ ] **Step 2: Run** `python -m pytest scripts/tests/test_release_scripts.py -q` — expect FAIL.
- [ ] **Step 3: Implement**; then locally `python scripts/build_release.py` and `python scripts/check_wheel.py backend/dist/visto-0.1.0-py3-none-any.whl` — expect exit 0. Confirm `uv build` in `verify.py` still passes when the console directory is absent (artifacts are optional).
- [ ] **Step 4: Run** `python scripts/verify.py` — expect PASS.
- [ ] **Step 5: Commit** `build: ship console and Appium locks in the wheel; add release workflow`.

### Task 13: Documentation

**Files:**
- Modify: `docs/local-development.md` (becomes "Installation": uv, `uv tool install <release wheel URL>`, `visto setup`, `visto start`, `visto doctor`, `visto settings`, proxy CA bundle, upgrade with `uv tool install --force <new URL>` after stopping Visto, uninstall `uv tool uninstall visto` + removing `~/.visto`; a "Contributing" section with `uv sync`, pnpm, `uv run visto start --home .work/home --no-browser` and the Vite dev server), `docs/ios-setup.md` (signing table → Settings page fields; WebDriverAgent path from doctor/settings; rebuild after driver change; Appium package location in the home), `docs/android-setup.md` (lease directory `~/.visto/data/device-leases`, recovery steps), `docs/provider-setup.md`, `docs/web-console.md` (Settings page, price refresh switch), `docs/artifact-storage.md` (home layout, key in plain text in `secrets.json`, owner-only on POSIX, user-profile ACL on Windows, `logs/appium.log` private), `docs/first-device-test.md`, `docs/api-contract.md` (settings endpoints), `docs/ai-context/{02-stack,04-structure,07-integrations,STATUS}.md`, `README.md`, `CONTRIBUTING.md`, `docs/references.md` (consolidate)

- [ ] **Step 1:** Rewrite the docs above; remove every mention of `.env`, `OPENAI_API_KEY` as a variable, `VISTO_IOS_*`, `VISTO_PRICE_REFRESH`, `setx`, Android Studio as a requirement.
- [ ] **Step 2: Run** `python scripts/check_project.py` — expect `Companion integrity OK`; `grep -rn "\.env\b\|VISTO_IOS_\|VISTO_PRICE_REFRESH\|setx" docs README.md CONTRIBUTING.md` — expect no hits outside historical spec/plan files.
- [ ] **Step 3:** STATUS: current state (installation via wheel + `visto` commands, settings store), verification state (local checks only; clean-host live installs on Windows and macOS not yet performed), known issues, next work (live clean-host install checks on Windows and macOS, first tagged release).
- [ ] **Step 4: Run** `python scripts/verify.py` — expect PASS.
- [ ] **Step 5: Commit** `docs: describe installation with visto setup and the settings page`.

---

## Live checks (user-run, labelled, not part of this plan's execution)

1. Clean Windows host: install uv, install the wheel from a test release, `visto setup`, `visto start`, set the key in Settings, `visto doctor`, run against a USB-connected phone.
2. Clean Mac host: same, plus iOS settings and the WebDriverAgent steps.
3. Upgrade path: install release N, create a run, install release N+1, confirm data and settings survive.
