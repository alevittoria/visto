"""Small strict constructor checks: type hints alone do not validate values."""

from datetime import datetime


def text(*values: object, allow_empty: bool = False) -> None:
    if any(not isinstance(v, str) or (not allow_empty and not v.strip()) for v in values):
        raise ValueError("Expected text" if allow_empty else "Expected nonempty text")


def integer(*values: object, minimum: int = 0) -> None:
    if any(type(v) is not int or v < minimum for v in values):
        raise ValueError(f"Expected integer >= {minimum}; booleans are not numbers")


def instance(value: object, classes: type | tuple[type, ...]) -> None:
    if not isinstance(value, classes):
        raise ValueError("Unexpected value type")


def items(value: object, classes: type | tuple[type, ...], *, nonempty: bool = False) -> None:
    if type(value) is not tuple or (nonempty and not value):
        raise ValueError("Expected immutable tuple" + (" with values" if nonempty else ""))
    for item in value:
        instance(item, classes)
        if isinstance(item, str):
            text(item)


def timestamp(*values: object) -> None:
    for value in values:
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("Expected timezone-aware timestamp")


def geometry(width: int, height: int, rotation: int) -> None:
    integer(width, height, minimum=1)
    integer(rotation)
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Unsupported image rotation")
