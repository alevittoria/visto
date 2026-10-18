"""Versioned, closed tagged JSON codec; no imports or execution from stored tags."""

import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum

from visto.domain import commands, models, run

# Deliberately explicit: adding a domain value requires a persistence decision.
_TYPES = (
    commands.Tap,
    commands.LongPress,
    commands.Swipe,
    commands.TypeText,
    commands.Back,
    commands.Home,
    commands.Enter,
    models.Goal,
    models.RunLimits,
    models.ModelIdentity,
    models.ModelUsage,
    models.RunConfiguration,
    models.ArtifactRef,
    models.Observation,
    models.Action,
    models.TechnicalReceipt,
    models.EffectAssessment,
    models.Assessment,
    models.Act,
    models.ObserveAfter,
    models.AskUser,
    models.Conclude,
    models.AgentDecision,
    run.UserAnswer,
    run.PendingQuestion,
    run.AIConclusion,
    run.InfrastructureFailure,
    run.Cancelled,
    run.RunUsage,
    run.BudgetExhausted,
    run.Run,
)
_ENUMS = (
    commands.CommandKind,
    models.ReceiptStatus,
    models.SemanticVerdict,
    models.EffectVerdict,
    run.RunState,
    run.BudgetKind,
)
_REGISTRY = {cls.__name__: cls for cls in (*_TYPES, *_ENUMS)}


def _encode(value: object) -> object:
    if isinstance(value, Enum) and type(value) in _ENUMS:
        return {"tag": type(value).__name__, "value": value.value}
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, datetime):
        return {"tag": "datetime", "value": value.isoformat()}
    if type(value) is tuple:
        return {"tag": "tuple", "value": [_encode(item) for item in value]}
    if type(value) in _TYPES:
        return {
            "tag": type(value).__name__,
            "fields": {field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    raise ValueError("Unsupported stored value")


def _decode(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is not dict or type(value.get("tag")) is not str:
        raise ValueError("Invalid stored tag")
    tag = value["tag"]
    if tag in ("datetime", "tuple") or _REGISTRY.get(tag) in _ENUMS:
        if set(value) != {"tag", "value"}:
            raise ValueError("Invalid stored fields")
        if tag == "datetime":
            if type(value["value"]) is not str:
                raise ValueError("Invalid timestamp")
            result = datetime.fromisoformat(value["value"])
            if result.utcoffset() is None:
                raise ValueError("Naive timestamp")
            return result
        if tag == "tuple":
            if type(value["value"]) is not list:
                raise ValueError("Invalid tuple")
            return tuple(_decode(item) for item in value["value"])
        return _REGISTRY[tag](value["value"])
    cls = _REGISTRY.get(tag)
    if cls is None or not is_dataclass(cls) or set(value) != {"tag", "fields"}:
        raise ValueError("Unknown stored type")
    data = value["fields"]
    if type(data) is not dict or set(data) != {field.name for field in fields(cls)}:
        raise ValueError("Unexpected stored dataclass fields")
    return cls(**{key: _decode(item) for key, item in data.items()})


def dumps(value: object) -> str:
    return json.dumps(
        {"version": 1, "value": _encode(value)}, sort_keys=True, separators=(",", ":")
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate stored JSON key")
        result[key] = value
    return result


def loads(payload: str) -> object:
    data = json.loads(payload, object_pairs_hook=_unique)
    if (
        type(data) is not dict
        or set(data) != {"version", "value"}
        or type(data["version"]) is not int
        or data["version"] != 1
    ):
        raise ValueError("Unsupported storage version")
    return _decode(data["value"])
