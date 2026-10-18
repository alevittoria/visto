import hashlib
import json

import pytest

from visto.adapters.command_codec import decode_command, encode_command
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText


@pytest.mark.parametrize(
    "command",
    [
        Tap(0, 2),
        LongPress(0, 2, 800),
        Swipe(1, 2, 3, 4, 100),
        TypeText("literal $text\n"),
        Back(),
        Home(),
        Enter(),
    ],
)
def test_command_wire_round_trip(command):
    assert decode_command(json.loads(json.dumps(encode_command(command)))) == command


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "shell", "command": "anything"},
        {"kind": "back", "extra": 1},
        {"kind": "tap", "x": True, "y": 0},
        {"kind": "tap", "x": float("nan"), "y": 0},
        {"kind": "tap", "x": 1.5, "y": 0},
        {"kind": "tap", "x": 0},
        {"kind": "type_text", "text": 3},
        [],
        None,
    ],
)
def test_command_wire_rejects_unknown_fields_kinds_and_malformed_values(payload):
    with pytest.raises(ValueError):
        decode_command(payload)


def test_presented_image_requires_exact_persisted_content():
    from datetime import UTC, datetime

    from visto.application.context import PresentedImage
    from visto.domain.models import ArtifactRef, Observation

    data = b"fixture image bytes"
    artifact = ArtifactRef(
        "a", "r", "image/png", len(data), hashlib.sha256(data).hexdigest(), "key"
    )
    observation = Observation(
        "o", "r", 1, datetime.now(UTC), "device", "session", "lease", artifact, 10, 10, 0
    )
    assert PresentedImage(observation, data).content == data
    with pytest.raises(ValueError):
        PresentedImage(observation, b"different content")
