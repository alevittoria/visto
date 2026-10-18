"""Strict JSON-compatible technical-command codec, not a future run/API schema."""

from dataclasses import asdict, fields

from visto.domain.commands import COMMAND_TYPES, DeviceCommand

_COMMANDS = {command.kind.value: command for command in COMMAND_TYPES}


def encode_command(command: DeviceCommand) -> dict[str, object]:
    if type(command) not in COMMAND_TYPES:
        raise ValueError("Unsupported technical command")
    return {"kind": command.kind.value, **asdict(command)}


def decode_command(payload: object) -> DeviceCommand:
    if type(payload) is not dict or type(payload.get("kind")) is not str:
        raise ValueError("Expected command object with kind")
    command_type = _COMMANDS.get(payload["kind"])
    if command_type is None:
        raise ValueError("Unsupported command kind")
    expected = {"kind", *(field.name for field in fields(command_type))}
    if set(payload) != expected:
        raise ValueError("Unknown or missing command fields")
    return command_type(**{key: value for key, value in payload.items() if key != "kind"})
