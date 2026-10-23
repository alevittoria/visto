"""Screenshots sized to the provider's image limits and coordinates mapped back; fakes only."""

import asyncio
import base64
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from visto.adapters.ai import INSTRUCTION_VERSION, OpenAIAgent
from visto.adapters.ai.imaging import MAX_PATCHES, MAX_SIDE, PATCH, presented_size
from visto.application.context import AgentContext, PresentedImage
from visto.domain.commands import CommandKind, Swipe, Tap
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    ArtifactRef,
    Goal,
    ModelIdentity,
    Observation,
    ReceiptStatus,
    RunConfiguration,
    RunLimits,
    TechnicalReceipt,
)
from visto.domain.run import Run

# A phone screenshot larger than the provider's limits, and its presented size.
SOURCE = (1178, 2556)
PRESENTED = (944, 2048)


def patches(width, height):
    return -(-width // PATCH) * -(-height // PATCH)


@pytest.mark.parametrize(
    "size", [(1178, 2556), (1080, 2400), (2556, 1178), (2048, 2048), (1440, 3120), (800, 6000)]
)
def test_presented_size_fits_every_limit_and_keeps_the_aspect_ratio(size):
    width, height = presented_size(*size)
    assert max(width, height) <= MAX_SIDE
    assert patches(width, height) <= MAX_PATCHES
    assert abs(width / height - size[0] / size[1]) < 0.01


def test_small_screenshots_are_presented_unchanged():
    assert presented_size(100, 200) == (100, 200)
    assert presented_size(*SOURCE) == PRESENTED


def png(size):
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(buffer, "PNG")
    return buffer.getvalue()


def observation(observation_id, sequence, captured_at, content):
    artifact = ArtifactRef(
        f"a{sequence}",
        "r",
        "image/png",
        len(content),
        hashlib.sha256(content).hexdigest(),
        f"owned/{sequence}",
    )
    return Observation(
        observation_id, "r", sequence, captured_at, "udid", "session", "lease", artifact, *SOURCE, 0
    )


@pytest.fixture
def context():
    now = datetime.now(UTC)
    identity = ModelIdentity("openai", "gpt-6-sol", INSTRUCTION_VERSION)
    run = Run(
        "r",
        "udid",
        Goal("Add three and four", ()),
        RunConfiguration(RunLimits(30000, 4, 6, 1000, 500), tuple(CommandKind), identity, "v1"),
        now,
        now,
    ).start(now)
    content = png(SOURCE)
    first = observation("o1", 1, now, content)
    current = observation("o2", 2, now + timedelta(seconds=2), content)
    # The previous tap hit the centre of a key, in source pixels.
    tap = Tap(726, 1968)
    previous = Action("x1", "r", "d1", "o1", "lease", tap, 1000)
    receipt = TechnicalReceipt("r", "x1", ReceiptStatus.COMPLETED, now, now + timedelta(seconds=1))
    decision = AgentDecision("d1", "r", "o1", ("o1",), Act(tap, 1000), "Tap", "", identity)
    return AgentContext(
        run,
        (PresentedImage(first, content), PresentedImage(current, content)),
        "o2",
        previous,
        receipt,
        recent_decisions=(decision,),
    )


def respond(command):
    value = {
        "rationale": "Tap the key",
        "working_plan": "Add",
        "previous_effect": {
            "action_id": "x1",
            "verdict": "achieved",
            "explanation": "The key registered",
            "observation_ids": ["o2"],
        },
        "next": {"kind": "act", "command": command, "timeout_ms": 1000},
    }
    return {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}
        ],
        "usage": {"input_tokens": 30, "output_tokens": 20},
    }


def decide(context, command):
    sent = []

    def wire(key, body, timeout):
        sent.append(json.loads(body))
        return respond(command)

    reply = asyncio.run(OpenAIAgent("secret", transport=wire).decide(context, 1000))
    return reply.decision, sent[0]["input"][0]["content"]


def test_images_are_sent_at_the_presented_size_with_matching_metadata(context):
    _, content = decide(context, {"kind": "tap", "x": 0, "y": 0})
    images = [part for part in content if part["type"] == "input_image"]
    metadata = [json.loads(part["text"]) for part in content[1:] if part["type"] == "input_text"]
    assert len(images) == 2 and len(metadata) == 2
    for part, meta in zip(images, metadata, strict=True):
        assert part["image_url"].startswith("data:image/png;base64,")
        encoded = part["image_url"].split(",", 1)[1]
        assert Image.open(io.BytesIO(base64.b64decode(encoded))).size == PRESENTED
        assert (meta["width"], meta["height"]) == PRESENTED


def test_returned_coordinates_are_mapped_back_to_source_pixels(context):
    decision, _ = decide(context, {"kind": "tap", "x": 581, "y": 1577})
    assert decision.next.command == Tap(725, 1968)
    swipe = {
        "kind": "swipe",
        "start_x": 0,
        "start_y": 2047,
        "end_x": 943,
        "end_y": 0,
        "duration_ms": 300,
    }
    decision, _ = decide(context, swipe)
    # The presented image's last pixel stays inside the source screenshot.
    assert decision.next.command == Swipe(0, 2555, 1177, 0, 300)


def test_history_coordinates_are_presented_in_the_image_scale(context):
    _, content = decide(context, {"kind": "tap", "x": 0, "y": 0})
    history = json.loads(content[0]["text"])
    assert history["previous_action"]["command"] == {"record_type": "Tap", "x": 582, "y": 1577}
    command = history["recent_decisions"][0]["next"]["command"]
    assert command == {"record_type": "Tap", "x": 582, "y": 1577}
