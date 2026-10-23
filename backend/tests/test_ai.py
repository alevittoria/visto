"""Provider wire checks use fakes only; these do not evaluate model judgement."""

import asyncio
import hashlib
import json
import tomllib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visto.adapters.ai import (
    INSTRUCTION_VERSION,
    INSTRUCTION_VERSIONS,
    OpenAIAgent,
    load_instructions,
)
from visto.adapters.ai.openai import history_data
from visto.adapters.devices import Platform
from visto.application.context import AgentContext, PresentedImage
from visto.application.ports import PortError
from visto.domain.commands import Back, CommandKind, Enter, Home, LongPress
from visto.domain.models import (
    ArtifactRef,
    Conclude,
    Goal,
    ModelIdentity,
    Observation,
    RunConfiguration,
    RunLimits,
)
from visto.domain.run import Run

ANDROID_INSTRUCTIONS_SHA256 = "903f4338c1e8bdaeb099d0b95e2ba4273371e8b1c0e30fd77f3669acb0cdec21"


@pytest.fixture
def context():
    now = datetime.now(UTC)
    run = Run(
        "r",
        "serial",
        Goal("  Preserve exact goal  ", ("Never purchase",)),
        RunConfiguration(
            RunLimits(30000, 4, 6, 1000, 500),
            tuple(CommandKind),
            ModelIdentity("openai", "gpt-6-sol", INSTRUCTION_VERSION),
            "appium-v1",
        ),
        now,
        now,
    ).start(now)
    content = b"fake screenshot"
    artifact = ArtifactRef(
        "a", "r", "image/png", len(content), hashlib.sha256(content).hexdigest(), "owned/key"
    )
    o = Observation("o", "r", 1, now, "serial", "session", "lease", artifact, 100, 200, 0)
    return AgentContext(run, (PresentedImage(o, content),), "o")


def payload():
    return {
        "rationale": "Visible evidence",
        "working_plan": "Inspect",
        "previous_effect": None,
        "next": {
            "kind": "conclude",
            "verdict": "inconclusive",
            "explanation": "Insufficient evidence",
            "observation_ids": ["o"],
        },
    }


def response(value=None):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(value or payload())}],
            }
        ],
        "usage": {"input_tokens": 30, "output_tokens": 20},
    }


def test_wire_has_original_goal_images_strict_schema_and_no_remote_state(context):
    calls = []

    def wire(key, body, timeout):
        calls.append((key, json.loads(body), timeout))
        return response()

    reply = asyncio.run(OpenAIAgent("secret", transport=wire).decide(context, 1000))
    assert isinstance(reply.decision.next, Conclude)
    assert reply.decision.usage.input_tokens == 30
    assert reply.conversation_id is None
    key, sent, timeout = calls[0]
    assert key == "secret" and timeout == 1000
    assert sent["store"] is False and "previous_response_id" not in sent
    assert sent["text"]["format"]["strict"] is True
    content = sent["input"][0]["content"]
    assert json.loads(content[0]["text"])["original_goal"]["text"] == context.run.goal.text
    assert content[-1]["image_url"].startswith("data:image/png;base64,")
    assert "Never purchase" in content[0]["text"]
    assert "secret" not in json.dumps(sent)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(status="incomplete"),
        lambda r: r.update(output=[]),
        lambda r: r["output"][0].update(content=[{"type": "refusal", "refusal": "private"}]),
        lambda r: r["output"][0]["content"][0].update(text="not JSON"),
        lambda r: r.update(usage={"input_tokens": True}),
    ],
)
def test_errors_are_explicit_sanitized_and_never_retry(context, change):
    r = response()
    change(r)
    calls = []

    def wire(*args):
        calls.append(args)
        return r

    with pytest.raises(PortError) as error:
        asyncio.run(OpenAIAgent("secret", transport=wire).decide(context, 1000))
    assert len(calls) == 1
    assert "private" not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.parametrize(
    "next_value",
    [
        {"kind": "act", "command": {"kind": "shell", "command": "bad"}, "timeout_ms": 10},
        {"kind": "act", "command": {"kind": "tap", "x": True, "y": 0}, "timeout_ms": 10},
        {"kind": "act", "command": {"kind": "tap", "x": 100, "y": 0}, "timeout_ms": 10},
        {"kind": "observe_after", "delay_ms": 10000},
        {
            "kind": "conclude",
            "verdict": "passed",
            "explanation": "bad",
            "observation_ids": ["alien"],
        },
        {"kind": "ask_user", "question": "q", "extra": 1},
    ],
)
def test_invalid_commands_and_unpresented_evidence_rejected(context, next_value):
    value = payload()
    value["next"] = next_value
    with pytest.raises(PortError, match="malformed"):
        asyncio.run(
            OpenAIAgent("secret", transport=lambda *a: response(value)).decide(context, 1000)
        )


def test_usage_missing_remains_unknown(context):
    r = response()
    del r["usage"]
    reply = asyncio.run(OpenAIAgent("secret", transport=lambda *a: r).decide(context, 1000))
    assert reply.decision.usage.input_tokens is None


def test_identity_context_and_transport_failures(context):
    agent = OpenAIAgent(
        "secret", transport=lambda *a: (_ for _ in ()).throw(RuntimeError("secret"))
    )
    with pytest.raises(PortError, match="malformed"):
        asyncio.run(agent.decide(context, 1000))
    with pytest.raises(PortError, match="identity"):
        asyncio.run(OpenAIAgent("secret", "other").decide(context, 1000))
    with pytest.raises(PortError, match="context_limit"):
        asyncio.run(agent.decide(replace(context, working_plan="x" * 100001), 1000))


def test_command_variant_is_retained_in_provider_history():
    assert history_data(Back()) != history_data(Home())


@pytest.mark.parametrize(
    "command, expected",
    [
        ({"kind": "long_press", "x": 10, "y": 20, "duration_ms": 900}, LongPress(10, 20, 900)),
        ({"kind": "enter"}, Enter()),
    ],
)
def test_long_press_and_enter_decode_from_provider(context, command, expected):
    value = payload()
    value["next"] = {"kind": "act", "command": command, "timeout_ms": 1000}
    reply = asyncio.run(
        OpenAIAgent("secret", transport=lambda *a: response(value)).decide(context, 1000)
    )
    assert reply.decision.next.command == expected


def test_android_instructions_are_byte_identical_after_refactoring():
    rendered = load_instructions(Platform.ANDROID)
    assert hashlib.sha256(rendered.encode()).hexdigest() == ANDROID_INSTRUCTIONS_SHA256


def test_ios_instructions_name_the_platform_and_its_navigation_reality():
    text = load_instructions(Platform.IOS)
    assert "iOS test agent" in text and "Android" not in text
    assert "may not navigate" in text and "home screen" in text
    assert "does not clear what the field already held, so clear any existing" in text
    assert "replacing what it held" not in text
    assert "{{" not in text and "<!--" not in text


def test_identity_mismatch_rejects_the_other_platform_version(context):
    agent = OpenAIAgent("secret", platform=Platform.IOS, transport=lambda *a: None)
    with pytest.raises(PortError, match="identity"):
        asyncio.run(agent.decide(context, 1000))


def test_every_prompt_resource_the_loader_reads_is_packaged_in_the_wheel():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    needed = ["agent-core.md", *(f"{INSTRUCTION_VERSIONS[p]}.md" for p in Platform)]
    for name in needed:
        assert included.get(f"prompts/{name}") == f"visto/prompts/{name}"
