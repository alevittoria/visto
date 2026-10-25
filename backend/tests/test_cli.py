"""Composed local checks across real adapters with fake network wires only."""

import asyncio
import json
import os
import shutil
import signal
from pathlib import Path
from uuid import uuid4

import pytest
from test_android import FakeWire
from test_commands_start import installed_home, old_database, write_entry

from visto.adapters.ai import OpenAIAgent
from visto.adapters.android import AppiumDevice
from visto.adapters.devices import Platform
from visto.adapters.ios.device import XCUITestDevice
from visto.adapters.ios.signing import IOSSigning
from visto.adapters.settings.store import Settings, SettingsStore
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.loop import RunLoop
from visto.application.ports import PortError
from visto.application.runtime import MutableRunControl, SystemClock
from visto.cli import main, parser, resolved_data_dir
from visto.domain.models import Action, AgentDecision, Goal, Observation, TechnicalReceipt
from visto.home import VistoHome
from visto.runner import RunnerSettings, build_runtime, new_run


@pytest.fixture
def root():
    base = Path(__file__).resolve().parents[2] / ".work" / "cli-tests"
    target = base / uuid4().hex
    target.mkdir(parents=True)
    yield target
    if target.resolve().parent != base.resolve():
        raise ValueError("Refusing test cleanup outside workspace")
    shutil.rmtree(target)


@pytest.fixture(autouse=True)
def appium_already_running(monkeypatch):
    """`run` reuses a running Appium; tests never spawn or probe a real one."""
    monkeypatch.setattr("visto.cli.appium_running", lambda port: True)


@pytest.fixture
def checks_pass(monkeypatch):
    """Doctor checks that touch the host (adb, Appium, toolchain) are replaced."""
    monkeypatch.setattr("visto.commands.doctor.collect_checks", lambda home, **probes: [])


def keyed(root, key="test-key"):
    SettingsStore(VistoHome(root / "home")).set_api_key(key)


def factory(root, steps):
    wire = FakeWire()
    loops = []
    calls = []

    def compose(settings, key, control):
        artifacts = LocalArtifactStore(root / "artifacts")
        store = SQLiteRunStore(root / "runs.sqlite3", artifacts)

        def provider(secret, body, timeout_ms):
            assert secret == "test-key"
            data = json.loads(body)
            meta = json.loads(data["input"][0]["content"][0]["text"])
            calls.append(meta)
            step = steps[len(calls) - 1]
            if isinstance(step, Exception):
                raise step
            if step in ("passed", "failed", "inconclusive"):
                nxt = {
                    "kind": "conclude",
                    "verdict": step,
                    "explanation": "Fake wire AI assessment",
                    "observation_ids": [meta["current_observation_id"]],
                }
            else:
                nxt = step
            previous = meta["previous_action"]
            effect = (
                None
                if previous is None
                else {
                    "action_id": previous["action_id"],
                    "verdict": "unclear",
                    "explanation": "Fake wire effect",
                    "observation_ids": [meta["current_observation_id"]],
                }
            )
            answer = {
                "rationale": "Fake provider decision",
                "working_plan": "Continue",
                "previous_effect": effect,
                "next": nxt,
            }
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(answer)}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

        device = AppiumDevice(settings.appium_url, root / "leases", wire=wire)
        loop = RunLoop(
            device,
            OpenAIAgent(key, settings.model, transport=provider),
            store,
            artifacts,
            SystemClock(),
            control,
        )
        loops.append(loop)
        return loop

    return compose, wire, calls, loops


def arguments(root):
    return [
        "run",
        "--device",
        "explicit-serial",
        "--goal",
        "  original goal  ",
        "--constraint",
        "Never buy",
        "--data-dir",
        str(root),
        "--home",
        str(root / "home"),
    ]


@pytest.mark.parametrize("verdict,exit_code", [("passed", 0), ("failed", 1), ("inconclusive", 2)])
def test_composed_run_action_wait_question_conclusion_and_durable_inspection(
    root, monkeypatch, verdict, exit_code
):
    keyed(root)
    compose, wire, calls, loops = factory(
        root,
        [
            {"kind": "act", "command": {"kind": "tap", "x": 1, "y": 2}, "timeout_ms": 1000},
            {"kind": "observe_after", "delay_ms": 1},
            {"kind": "ask_user", "question": "Which account?"},
            verdict,
        ],
    )
    output = []
    assert (
        main(
            arguments(root),
            factory=compose,
            output=output.append,
            prompt=lambda _: "Synthetic account",
        )
        == exit_code
    )
    result = json.loads(output[-1])
    run_id = result["run_id"]
    assert result["outcome"] == verdict
    assert result["reported_usage"]["input_tokens"] == 40
    history = asyncio.run(loops[0].store.history(run_id))
    assert len([r for r in history if isinstance(r, Observation)]) == 4
    assert len([r for r in history if isinstance(r, Action)]) == 1
    assert len([r for r in history if isinstance(r, TechnicalReceipt)]) == 1
    assert len([r for r in history if isinstance(r, AgentDecision)]) == 4
    assert calls[-1]["original_goal"]["text"] == "  original goal  "
    assert calls[-1]["attributed_user_answers"][0]["text"] == "Synthetic account"
    caps = [
        body["capabilities"]["alwaysMatch"]
        for method, path, body, _ in wire.calls
        if path == "/session"
    ]
    assert len(caps) == 2 and all(c["appium:udid"] == "explicit-serial" for c in caps)
    assert not list((root / "leases").glob("*.lease"))
    inspected = []
    assert (
        main(
            ["inspect", "--data-dir", str(root), "--home", str(root / "home"), "--run-id", run_id],
            output=inspected.append,
        )
        == 0
    )
    assert json.loads(inspected[0])["run"]["terminal"]["assessment"]["verdict"] == verdict
    assert "test-key" not in "".join(output + inspected)


@pytest.mark.parametrize("interrupt", [False, True])
def test_question_eof_or_sigint_persists_cancel_terminal(root, monkeypatch, interrupt):
    keyed(root)
    compose, _, _, loops = factory(root, [{"kind": "ask_user", "question": "Which?"}])

    def prompt(_):
        if interrupt:
            signal.raise_signal(signal.SIGINT)
        raise EOFError

    output = []
    assert main(arguments(root), factory=compose, output=output.append, prompt=prompt) == 130
    result = json.loads(output[-1])
    stored = asyncio.run(loops[0].store.get(result["run_id"]))
    assert stored.terminal.source == "user"
    assert result["outcome"] == "cancelled"


def test_provider_failure_is_technical_with_partial_evidence(root, monkeypatch):
    keyed(root)
    compose, _, _, loops = factory(
        root,
        [
            {"kind": "act", "command": {"kind": "back"}, "timeout_ms": 1000},
            PortError("provider: http_429"),
        ],
    )
    output = []
    assert main(arguments(root), factory=compose, output=output.append) == 3
    result = json.loads(output[-1])
    assert result["outcome"] == "infrastructure_failure"
    assert result["terminal"]["detail"] == "provider: http_429"
    assert len(result["terminal"]["observation_ids"]) == 2
    assert len(asyncio.run(loops[0].store.history(result["run_id"]))) == 5


def test_missing_key_and_invalid_url_fail_before_factory(root, monkeypatch):

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    output = []
    assert main(arguments(root), factory=forbidden, output=output.append) == 3
    assert "Provider key is not configured" in output[-1]
    keyed(root)
    assert (
        main(
            arguments(root) + ["--appium-url", "http://untrusted.example"],
            factory=forbidden,
            output=output.append,
        )
        == 3
    )


def test_doctor_is_configuration_only_and_no_secret(root, monkeypatch, checks_pass):
    keyed(root)
    output = []
    assert (
        main(
            ["doctor", "--json", "--device", "serial", "--data-dir", str(root)]
            + ["--home", str(root / "home")],
            output=output.append,
        )
        == 0
    )
    result = json.loads(output[0])
    assert result["api_key_present"] and not result["device_contacted"]
    assert "test-key" not in output[0]
    assert not (root / "runs.sqlite3").exists()


def test_settings_reject_malformed_loopback_port(root):
    with pytest.raises(ValueError):
        RunnerSettings("serial", root, "http://127.0.0.1:99999")


def test_cleanup_failure_keeps_durable_ai_terminal_but_nonzero_exit(root, monkeypatch):
    keyed(root)
    compose, wire, _, loops = factory(root, ["passed"])
    wire.fail_delete = True
    output = []
    assert main(arguments(root), factory=compose, output=output.append) == 3
    result = json.loads(output[-1])
    assert result["outcome"] == "passed" and result["cleanup_failed"]
    assert asyncio.run(loops[0].store.get(result["run_id"])).terminal.assessment.verdict == "passed"
    assert list((root / "leases").glob("*.lease"))


def test_data_directory_selection_cannot_split_device_lease_domain(root):
    from visto.application.runtime import MutableRunControl

    first = build_runtime(RunnerSettings("serial", root / "one"), "test-key", MutableRunControl())
    second = build_runtime(RunnerSettings("serial", root / "two"), "test-key", MutableRunControl())
    assert first.device._directory == second.device._directory


@pytest.mark.parametrize(
    "step,code",
    [
        ("inconclusive", 2),
        ({"kind": "act", "command": {"kind": "tap", "x": 1, "y": 2}, "timeout_ms": 1000}, 3),
    ],
)
def test_observe_only_disables_mutation_capabilities(root, monkeypatch, step, code):
    keyed(root)
    compose, wire, calls, _ = factory(root, [step])
    assert (
        main(arguments(root) + ["--observe-only"], factory=compose, output=lambda _: None) == code
    )
    assert calls[0]["configuration"]["capabilities"] == []
    assert not any(path.endswith("/actions") for _, path, _, _ in wire.calls)


def test_request_file_preserves_quotes_unicode_and_constraints(root, monkeypatch):
    keyed(root)
    request = {
        "goal": '  Apri "Note di prova"\nè una prova  ',
        "constraints": ['Do not press "Buy"'],
        "expected_result": 'Versione "Demo"',
    }
    path = root / "request.json"
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    compose, _, calls, _ = factory(root, ["inconclusive"])
    assert (
        main(
            [
                "run",
                "--device",
                "serial",
                "--data-dir",
                str(root),
                "--home",
                str(root / "home"),
                "--request-file",
                str(path),
            ],
            factory=compose,
            output=lambda _: None,
        )
        == 2
    )
    assert calls[0]["original_goal"] == {
        "text": request["goal"],
        "constraints": request["constraints"],
        "expected_result": request["expected_result"],
    }


def test_environment_key_is_ignored(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    output = []
    assert main(arguments(root), factory=forbidden, output=output.append) == 3
    assert "Provider key is not configured" in output[-1]
    assert "sk-from-env" not in "".join(output)


def test_stored_key_runs_without_printing_credential(root):
    keyed(root)
    compose, _, _, _ = factory(root, ["inconclusive"])
    output = []
    assert main(arguments(root), factory=compose, output=output.append) == 2
    assert "test-key" not in "".join(output)


def test_run_passes_stored_ios_signing_to_the_runtime(root):
    keyed(root)
    store = SettingsStore(VistoHome(root / "home"))
    signing = IOSSigning(team_id="TEAM-X", prebuilt_wda=True)
    store.save(Settings(ios=signing))
    seen = []

    def capture(settings, key, control):
        seen.append(settings.ios_signing)
        raise ValueError("stop")

    assert main(arguments(root), factory=capture, output=lambda _: None) == 3
    assert seen == [signing]


def test_doctor_reports_stored_key_presence_without_revealing_it(root, monkeypatch, checks_pass):
    keyed(root)
    output = []
    assert (
        main(
            ["doctor", "--json", "--device", "serial", "--home", str(root / "home")]
            + ["--data-dir", str(root)],
            output=output.append,
        )
        == 0
    )
    assert json.loads(output[0])["api_key_present"] is True
    assert "test-key" not in "".join(output)


def test_doctor_reports_ios_prerequisites_without_contacting_a_device(
    root, monkeypatch, checks_pass
):
    monkeypatch.setattr("visto.cli.ios_host", lambda: True)
    keyed(root)
    store = SettingsStore(VistoHome(root / "home"))
    store.save(
        Settings(
            ios=IOSSigning(
                team_id="TEAM-SECRET-1",
                signing_id="Signing Identity Secret",
                wda_bundle_id="example.bundle.secret",
            )
        )
    )

    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name in ("simctl", "devicectl"))
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: Path("/usr/bin/xcrun"))
    output = []
    arguments_ = ["doctor", "--json", "--platform", "ios", "--device", "device-B"]
    arguments_ += ["--data-dir", str(root)]
    arguments_ += ["--home", str(root / "home")]
    assert main(arguments_, output=output.append) == 0
    result = json.loads(output[0])
    assert result["platform"] == "ios"
    assert result["xcrun_present"] is True
    assert result["simulator_tooling_present"] is True
    assert result["device_tooling_present"] is True
    assert result["wda_signing_configured"] is True
    assert result["device_contacted"] is False and result["provider_contacted"] is False
    for secret in ("TEAM-SECRET-1", "Signing Identity Secret", "example.bundle.secret", "/usr/bin"):
        assert secret not in output[0]

    store.save(Settings(ios=IOSSigning(signing_id="x", wda_bundle_id="y")))
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: None)
    output.clear()
    assert main(arguments_, output=output.append) == 2
    result = json.loads(output[0])
    assert result["xcrun_present"] is False and result["wda_signing_configured"] is False


def test_doctor_exit_for_ios_needs_only_the_simulator_toolchain(root, monkeypatch, checks_pass):
    monkeypatch.setattr("visto.cli.ios_host", lambda: True)
    keyed(root)
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: Path("/usr/bin/xcrun"))
    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name == "simctl")
    output = []
    arguments_ = ["doctor", "--json", "--platform", "ios", "--device", "device-B"]
    arguments_ += ["--data-dir", str(root)]
    arguments_ += ["--home", str(root / "home")]
    assert main(arguments_, output=output.append) == 0
    result = json.loads(output[0])
    assert result["simulator_tooling_present"] is True
    assert result["device_tooling_present"] is False
    assert result["wda_signing_configured"] is False

    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name == "devicectl")
    output.clear()
    assert main(arguments_, output=output.append) == 2


def test_run_rejects_an_unknown_platform(root, monkeypatch):
    keyed(root)

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    with pytest.raises(SystemExit) as stopped:
        main(arguments(root) + ["--platform", "symbian"], factory=forbidden, output=print)
    assert stopped.value.code == 2


@pytest.mark.parametrize(
    "platform,device_class,adapter,instructions",
    [
        (Platform.ANDROID, AppiumDevice, "appium-wire-v1", "android-agent-v3"),
        (Platform.IOS, XCUITestDevice, "appium-xcuitest-v1", "ios-agent-v1"),
    ],
)
def test_runtime_selects_the_adapter_and_versions_from_the_platform(
    root, platform, device_class, adapter, instructions
):
    settings = RunnerSettings("device-B", root, platform=platform)
    loop = build_runtime(settings, "test-key", MutableRunControl())
    assert type(loop.device) is device_class
    configuration = new_run(settings, Goal("Example goal"), SystemClock()).configuration
    assert configuration.device_adapter_version == adapter == device_class.version
    assert configuration.identity.instruction_version == instructions


def test_cli_data_dir_follows_home(tmp_path):
    args = parser().parse_args(["inspect", "--home", str(tmp_path), "--run-id", "r"])
    assert resolved_data_dir(args) == tmp_path / "data"


def test_explicit_data_dir_wins_over_home(tmp_path):
    args = parser().parse_args(
        ["inspect", "--home", str(tmp_path), "--data-dir", str(tmp_path / "x"), "--run-id", "r"]
    )
    assert resolved_data_dir(args) == tmp_path / "x"


def test_setup_and_start_dispatch_with_their_options(tmp_path, monkeypatch):
    import visto.cli as cli

    calls = []
    monkeypatch.setattr(cli, "run_setup", lambda home, **kw: calls.append((home, kw)) or 0)
    monkeypatch.setattr(cli, "run_start", lambda home, **kw: calls.append((home, kw)) or 0)
    bundle = tmp_path / "ca.pem"
    assert (
        cli.main(
            [
                "setup",
                "--home",
                str(tmp_path),
                "--accept-android-license",
                "--ca-bundle",
                str(bundle),
            ]
        )
        == 0
    )
    assert cli.main(["setup", "--home", str(tmp_path)]) == 0
    assert (
        cli.main(
            [
                "start",
                "--home",
                str(tmp_path),
                "--port",
                "8100",
                "--appium-port",
                "4800",
                "--no-browser",
            ]
        )
        == 0
    )
    assert calls[0][0].root == tmp_path
    assert calls[0][1] == {"accept_license": True, "ca_bundle": bundle}
    assert calls[1][1] == {"accept_license": None, "ca_bundle": None}
    assert calls[2][1] == {"port": 8100, "appium_port": 4800, "open_browser": False}


def test_setup_keeps_the_short_license_flag(tmp_path):
    args = parser().parse_args(["setup", "--home", str(tmp_path), "--accept-license"])
    assert args.accept_license is True


def test_doctor_and_settings_dispatch(tmp_path, monkeypatch):
    import visto.cli as cli

    calls = []
    monkeypatch.setattr(cli, "run_doctor", lambda home, **kw: calls.append((home, kw)) or 0)
    monkeypatch.setattr(cli, "run_settings", lambda home, action: calls.append((home, action)) or 0)
    assert cli.main(["doctor", "--home", str(tmp_path)]) == 0
    assert calls[0][1]["json_output"] is False and calls[0][1]["fields"] is None
    for action in ("set-key", "delete-key", "verify-key", "show"):
        assert cli.main(["settings", action, "--home", str(tmp_path)]) == 0
    assert [c[1] for c in calls[1:]] == ["set-key", "delete-key", "verify-key", "show"]
    assert all(c[0].root == tmp_path for c in calls)
    with pytest.raises(SystemExit):
        parser().parse_args(["settings", "--home", str(tmp_path)])


def test_entry_exits_with_main_code(monkeypatch):
    import visto.cli as cli

    monkeypatch.setattr(cli, "main", lambda: 7)
    with pytest.raises(SystemExit) as stopped:
        cli.entry()
    assert stopped.value.code == 7


class FakeAppium:
    def __init__(self, events):
        self.events = events

    def stop(self):
        self.events.append("stop")


def test_run_reuses_running_appium(root, monkeypatch):
    keyed(root)
    probed = []
    monkeypatch.setattr("visto.cli.appium_running", lambda port: probed.append(port) or True)

    def forbidden(*args, **kwargs):
        pytest.fail("A running Appium must be reused")

    monkeypatch.setattr("visto.cli.AppiumProcess.start", forbidden)
    compose, _, _, _ = factory(root, ["inconclusive"])
    assert main(arguments(root), factory=compose, output=lambda _: None) == 2
    assert probed == [4723]


def test_run_spawns_and_stops_appium(root, monkeypatch):
    home = installed_home(root)
    keyed(root)
    events = []
    monkeypatch.setattr("visto.cli.appium_running", lambda port: False)

    def start(paths, env, port, log_file, **kwargs):
        events.append(("start", port, log_file, env["ANDROID_HOME"]))
        return FakeAppium(events)

    monkeypatch.setattr("visto.cli.AppiumProcess.start", start)
    compose, _, _, _ = factory(root, ["inconclusive"])

    def composed(settings, key, control):
        events.append("run")
        return compose(settings, key, control)

    assert main(arguments(root), factory=composed, output=lambda _: None) == 2
    assert events[0][:3] == ("start", 4723, home.logs / "appium.log")
    assert events[1:] == ["run", "stop"]


def test_run_stops_spawned_appium_when_the_run_fails(root, monkeypatch):
    installed_home(root)
    keyed(root)
    events = []
    monkeypatch.setattr("visto.cli.appium_running", lambda port: False)

    def start(*args, **kwargs):
        events.append("start")
        return FakeAppium(events)

    def broken(settings, key, control):
        raise OSError("boom")

    monkeypatch.setattr("visto.cli.AppiumProcess.start", start)
    assert main(arguments(root), factory=broken, output=lambda _: None) == 3
    assert events == ["start", "stop"]


def test_run_without_appium_or_toolchain_asks_for_setup(root, monkeypatch):
    keyed(root)
    monkeypatch.setattr("visto.cli.appium_running", lambda port: False)

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    output = []
    assert main(arguments(root), factory=forbidden, output=output.append) == 3
    assert "visto setup" in json.loads(output[-1])["detail"]


def test_run_reports_appium_start_failure(root, monkeypatch):
    from visto.commands.appium_process import AppiumFailed

    installed_home(root)
    keyed(root)
    monkeypatch.setattr("visto.cli.appium_running", lambda port: False)

    def failing(*args, **kwargs):
        raise AppiumFailed("Appium exited during startup; see appium.log")

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    monkeypatch.setattr("visto.cli.AppiumProcess.start", failing)
    output = []
    assert main(arguments(root), factory=forbidden, output=output.append) == 3
    assert "Appium" in json.loads(output[-1])["detail"]


def test_run_and_inspect_register_in_the_home(root, monkeypatch):
    import visto.cli as cli

    keyed(root)
    entry = VistoHome(root / "home").instances / f"{os.getpid()}.json"
    seen = []
    compose, _, _, _ = factory(root, ["inconclusive"])

    def composed(settings, key, control):
        seen.append(json.loads(entry.read_text(encoding="utf-8"))["kind"])
        return compose(settings, key, control)

    output = []
    main(arguments(root), factory=composed, output=output.append)
    assert seen == ["run"] and not entry.exists()

    kinds = []
    original = cli.registered

    def recording(home, kind):
        kinds.append(kind)
        return original(home, kind)

    monkeypatch.setattr(cli, "registered", recording)
    run_id = json.loads(output[-1])["run_id"]
    inspect = ["inspect", "--home", str(root / "home"), "--data-dir", str(root), "--run-id", run_id]
    assert main(inspect, output=lambda _: None) == 0
    assert kinds == ["inspect"] and not entry.exists()


@pytest.mark.parametrize("command", ["doctor", "run"])
def test_platform_ios_is_not_offered_off_mac(monkeypatch, capsys, command):
    monkeypatch.setattr("visto.cli.ios_host", lambda: False)
    with pytest.raises(SystemExit):
        parser().parse_args([command, "--platform", "ios", "--device", "d", "--goal", "g"])
    with pytest.raises(SystemExit):
        parser().parse_args([command, "--help"])
    assert "ios" not in capsys.readouterr().out.lower()


def test_platform_ios_is_offered_on_mac(monkeypatch):
    monkeypatch.setattr("visto.cli.ios_host", lambda: True)
    assert parser().parse_args(["doctor", "--platform", "ios"]).platform == "ios"
    run = ["run", "--platform", "ios", "--device", "device-B", "--goal", "g"]
    assert parser().parse_args(run).platform == "ios"


def test_ios_host_follows_the_host_key(monkeypatch):
    import visto.cli as cli

    for host, expected in (("macos-arm64", True), ("win-x64", False), ("linux-x64", False)):
        monkeypatch.setattr(cli, "host_key", lambda host=host: host)
        assert cli.ios_host() is expected


def test_doctor_json_off_mac_has_no_ios_fields(root, monkeypatch, checks_pass):
    monkeypatch.setattr("visto.cli.ios_host", lambda: False)
    keyed(root)
    output = []
    arguments_ = ["doctor", "--json", "--home", str(root / "home"), "--data-dir", str(root)]
    assert main(arguments_, output=output.append) == 0
    assert not any("xcrun" in name or "wda" in name for name in json.loads(output[0]))


def test_doctor_uses_the_port_of_the_appium_url(tmp_path, monkeypatch):
    import visto.cli as cli

    calls = []
    monkeypatch.setattr(cli, "run_doctor", lambda home, **kw: calls.append(kw) or 0)
    arguments_ = ["doctor", "--home", str(tmp_path), "--appium-url", "http://127.0.0.1:4801"]
    assert cli.main(arguments_) == 0
    assert cli.main([*arguments_, "--json"]) == 0
    assert [call["appium_port"] for call in calls] == [4801, 4801]


def test_run_and_inspect_refuse_to_upgrade_data_while_another_process_runs(root):
    from visto.adapters.storage.migrations import schema_version

    keyed(root)
    home = VistoHome(root / "home")
    database = old_database(root)
    write_entry(home, pid=os.getppid(), kind="start")

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    inspect = ["inspect", "--home", str(home.root), "--data-dir", str(root), "--run-id", "r"]
    for argv in (arguments(root), inspect):
        output = []
        assert main(argv, factory=forbidden, output=output.append) == 3
        assert json.loads(output[-1])["detail"] == (
            "Stop other Visto processes before upgrading data"
        )
    assert schema_version(database) == 0 and list(root.glob("*.bak")) == []
    assert not (home.instances / f"{os.getpid()}.json").exists()


def test_run_upgrades_data_after_registering_when_alone(root, monkeypatch):
    import visto.cli as cli
    from visto.adapters.storage.migrations import CURRENT_VERSION, schema_version

    keyed(root)
    database = old_database(root)
    entry = VistoHome(root / "home").instances / f"{os.getpid()}.json"
    registered_during_upgrade = []
    original = cli.prepare_data

    def recording(home, data_dir):
        registered_during_upgrade.append(entry.exists())
        return original(home, data_dir)

    monkeypatch.setattr(cli, "prepare_data", recording)
    compose, _, _, _ = factory(root, ["inconclusive"])
    assert main(arguments(root), factory=compose, output=lambda _: None) == 2
    assert registered_during_upgrade == [True]
    assert schema_version(database) == CURRENT_VERSION


def test_run_provider_requests_trust_the_remembered_ca_bundle(root, monkeypatch):
    from visto.toolchain import Toolchain, ToolchainState

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    keyed(root)
    bundle = str(root / "corp.pem")
    Toolchain(VistoHome(root / "home")).save_state(ToolchainState(ca_bundle=bundle))
    compose, _, _, _ = factory(root, ["inconclusive"])
    seen = []

    def composed(settings, key, control):
        seen.append(os.environ.get("SSL_CERT_FILE"))
        return compose(settings, key, control)

    assert main(arguments(root), factory=composed, output=lambda _: None) == 2
    assert seen == [bundle] and "SSL_CERT_FILE" not in os.environ
