"""Composed local checks across real adapters with fake network wires only."""

import asyncio
import json
import shutil
import signal
from pathlib import Path
from uuid import uuid4

import pytest
from test_android import FakeWire

from visto.adapters.ai import OpenAIAgent
from visto.adapters.android import AppiumDevice
from visto.adapters.devices import Platform
from visto.adapters.ios.device import XCUITestDevice
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.loop import RunLoop
from visto.application.ports import PortError
from visto.application.runtime import MutableRunControl, SystemClock
from visto.cli import main
from visto.domain.models import Action, AgentDecision, Goal, Observation, TechnicalReceipt
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
        "--env-file",
        str(root / ".env"),
    ]


@pytest.mark.parametrize("verdict,exit_code", [("passed", 0), ("failed", 1), ("inconclusive", 2)])
def test_composed_run_action_wait_question_conclusion_and_durable_inspection(
    root, monkeypatch, verdict, exit_code
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
    monkeypatch.delenv("OPENAI_API_KEY")
    inspected = []
    assert (
        main(["inspect", "--data-dir", str(root), "--run-id", run_id], output=inspected.append) == 0
    )
    assert json.loads(inspected[0])["run"]["terminal"]["assessment"]["verdict"] == verdict
    assert "test-key" not in "".join(output + inspected)


@pytest.mark.parametrize("interrupt", [False, True])
def test_question_eof_or_sigint_persists_cancel_terminal(root, monkeypatch, interrupt):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args):
        pytest.fail("Factory must not be called")

    output = []
    assert main(arguments(root), factory=forbidden, output=output.append) == 3
    assert "OPENAI_API_KEY" in output[-1]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert (
        main(
            arguments(root) + ["--appium-url", "http://untrusted.example"],
            factory=forbidden,
            output=output.append,
        )
        == 3
    )


def test_doctor_is_configuration_only_and_no_secret(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    output = []
    assert (
        main(["doctor", "--device", "serial", "--data-dir", str(root)], output=output.append) == 0
    )
    result = json.loads(output[0])
    assert result["api_key_present"] and not result["device_contacted"]
    assert "test-key" not in output[0]
    assert not (root / "runs.sqlite3").exists()


def test_settings_reject_malformed_loopback_port(root):
    with pytest.raises(ValueError):
        RunnerSettings("serial", root, "http://127.0.0.1:99999")


def test_cleanup_failure_keeps_durable_ai_terminal_but_nonzero_exit(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    compose, wire, calls, _ = factory(root, [step])
    assert (
        main(arguments(root) + ["--observe-only"], factory=compose, output=lambda _: None) == code
    )
    assert calls[0]["configuration"]["capabilities"] == []
    assert not any(path.endswith("/actions") for _, path, _, _ in wire.calls)


def test_request_file_preserves_quotes_unicode_and_constraints(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
            ["run", "--device", "serial", "--data-dir", str(root), "--request-file", str(path)],
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


def test_env_file_runs_without_exporting_or_printing_credential(root, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (root / ".env").write_text('OPENAI_API_KEY="test-key"\n', encoding="utf-8")
    compose, _, _, _ = factory(root, ["inconclusive"])
    output = []
    assert main(arguments(root), factory=compose, output=output.append) == 2
    import os

    assert "OPENAI_API_KEY" not in os.environ
    assert "test-key" not in "".join(output)


def test_doctor_reports_env_key_presence_without_revealing_it(root, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (root / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    output = []
    assert (
        main(
            ["doctor", "--device", "serial", "--env-file", str(root / ".env")], output=output.append
        )
        == 0
    )
    assert json.loads(output[0])["api_key_present"] is True
    assert "test-key" not in "".join(output)


def test_doctor_reports_ios_prerequisites_without_contacting_a_device(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISTO_IOS_TEAM_ID", "TEAM-SECRET-1")
    monkeypatch.setenv("VISTO_IOS_SIGNING_ID", "Signing Identity Secret")
    monkeypatch.setenv("VISTO_IOS_WDA_BUNDLE_ID", "example.bundle.secret")

    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name in ("simctl", "devicectl"))
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: Path("/usr/bin/xcrun"))
    output = []
    arguments_ = ["doctor", "--platform", "ios", "--device", "device-B", "--data-dir", str(root)]
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

    monkeypatch.delenv("VISTO_IOS_TEAM_ID")
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: None)
    output.clear()
    assert main(arguments_, output=output.append) == 2
    result = json.loads(output[0])
    assert result["xcrun_present"] is False and result["wda_signing_configured"] is False


def test_doctor_exit_for_ios_needs_only_the_simulator_toolchain(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for name in ("VISTO_IOS_TEAM_ID", "VISTO_IOS_SIGNING_ID", "VISTO_IOS_WDA_BUNDLE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("visto.cli.find_xcrun", lambda: Path("/usr/bin/xcrun"))
    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name == "simctl")
    output = []
    arguments_ = ["doctor", "--platform", "ios", "--device", "device-B", "--data-dir", str(root)]
    assert main(arguments_, output=output.append) == 0
    result = json.loads(output[0])
    assert result["simulator_tooling_present"] is True
    assert result["device_tooling_present"] is False
    assert result["wda_signing_configured"] is False

    monkeypatch.setattr("visto.cli.xcrun_tool", lambda xcrun, name: name == "devicectl")
    output.clear()
    assert main(arguments_, output=output.append) == 2


def test_run_rejects_an_unknown_platform(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

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
