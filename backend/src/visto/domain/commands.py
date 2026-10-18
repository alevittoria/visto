"""Allowlisted device operations in integer source-screenshot pixels."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

from ._validation import integer, text


class CommandKind(StrEnum):
    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    TYPE_TEXT = "type_text"
    BACK = "back"
    HOME = "home"
    ENTER = "enter"


@dataclass(frozen=True, slots=True)
class Tap:
    x: int
    y: int
    kind: ClassVar[CommandKind] = CommandKind.TAP

    def __post_init__(self) -> None:
        integer(self.x, self.y)


@dataclass(frozen=True, slots=True)
class LongPress:
    x: int
    y: int
    duration_ms: int
    kind: ClassVar[CommandKind] = CommandKind.LONG_PRESS

    def __post_init__(self) -> None:
        integer(self.x, self.y)
        integer(self.duration_ms, minimum=1)


@dataclass(frozen=True, slots=True)
class Swipe:
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int
    kind: ClassVar[CommandKind] = CommandKind.SWIPE

    def __post_init__(self) -> None:
        integer(self.start_x, self.start_y, self.end_x, self.end_y)
        integer(self.duration_ms, minimum=1)


@dataclass(frozen=True, slots=True)
class TypeText:
    text: str = field(repr=False)
    kind: ClassVar[CommandKind] = CommandKind.TYPE_TEXT

    def __post_init__(self) -> None:
        text(self.text, allow_empty=True)


@dataclass(frozen=True, slots=True)
class Back:
    kind: ClassVar[CommandKind] = CommandKind.BACK


@dataclass(frozen=True, slots=True)
class Home:
    kind: ClassVar[CommandKind] = CommandKind.HOME


@dataclass(frozen=True, slots=True)
class Enter:
    """Enter key on the focused input, e.g. to submit a search field."""

    kind: ClassVar[CommandKind] = CommandKind.ENTER


type DeviceCommand = Tap | LongPress | Swipe | TypeText | Back | Home | Enter
COMMAND_TYPES = (Tap, LongPress, Swipe, TypeText, Back, Home, Enter)
