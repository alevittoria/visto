"""Screenshots sized within the provider's image limits, and coordinates mapped across.

The provider resizes larger images before the model sees them, and the model then
answers in the resized image's pixels: https://developers.openai.com/api/docs/guides/images-vision .
Sending an image that already fits keeps the model's pixels equal to the stated size,
so the only conversion is the one done here, back to source-screenshot pixels.
"""

import io
import math
from dataclasses import fields, replace

from PIL import Image

from visto.domain.commands import COMMAND_TYPES
from visto.domain.models import Act, Action, AgentDecision

# The strictest documented `high` detail limits across current models.
MAX_SIDE = 2048
PATCH = 32
MAX_PATCHES = 2500
_X = ("x", "start_x", "end_x")
_Y = ("y", "start_y", "end_y")


def _patches(width: int, height: int) -> int:
    return math.ceil(width / PATCH) * math.ceil(height / PATCH)


def presented_size(width: int, height: int) -> tuple[int, int]:
    """Largest same-aspect size within the side and patch limits; never enlarged."""
    scale = min(
        1.0,
        MAX_SIDE / max(width, height),
        math.sqrt(MAX_PATCHES * PATCH * PATCH / (width * height)),
    )
    while True:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        if max(size) <= MAX_SIDE and _patches(*size) <= MAX_PATCHES:
            return size
        scale *= 0.99


def present(content: bytes, size: tuple[int, int]) -> bytes:
    """PNG of the screenshot at the presented size."""
    with Image.open(io.BytesIO(content)) as image:
        resized = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, "PNG")
    return buffer.getvalue()


class Scale:
    """Pixel mapping between one source screenshot and its presented image."""

    def __init__(self, source: tuple[int, int], presented: tuple[int, int]):
        self.source = source
        self.presented = presented

    def _map(self, command, frm, to):
        if type(command) not in COMMAND_TYPES:
            return command
        changes = {}
        for f in fields(command):
            axis = 0 if f.name in _X else 1 if f.name in _Y else None
            if axis is not None:
                # No clamping: an out-of-image coordinate must stay out of bounds so
                # that decision validation rejects it.
                changes[f.name] = round(getattr(command, f.name) * to[axis] / frm[axis])
        return replace(command, **changes)

    def to_source(self, command):
        return self._map(command, self.presented, self.source)

    def to_presented(self, command):
        return self._map(command, self.source, self.presented)


def presented_history(value, scales: dict[str, Scale], fallback: Scale):
    """An action or decision with its command in the scale its observation was shown at."""
    if isinstance(value, Action):
        scale = scales.get(value.observation_id, fallback)
        return replace(value, command=scale.to_presented(value.command))
    if isinstance(value, AgentDecision) and isinstance(value.next, Act):
        scale = scales.get(value.source_observation_id, fallback)
        command = scale.to_presented(value.next.command)
        return replace(value, next=replace(value.next, command=command))
    return value
