"""Versioned strict technical decision schema and decoder; no UI verdict rules."""

from uuid import uuid4

from visto.adapters.command_codec import decode_command
from visto.application.context import AgentContext
from visto.domain.models import (
    Act,
    AgentDecision,
    AskUser,
    Assessment,
    Conclude,
    EffectAssessment,
    EffectVerdict,
    ModelUsage,
    ObserveAfter,
    SemanticVerdict,
)
from visto.domain.validation import validate_decision


def obj(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STRING = {"type": "string", "maxLength": 8000}
INTEGER = {"type": "integer", "minimum": 0, "maximum": 3600000}
EVIDENCE = {"type": "array", "items": STRING, "minItems": 1, "maxItems": 8}


def enum(*values):
    return {"type": "string", "enum": list(values)}


COMMAND = {
    "anyOf": [
        obj(kind=enum("tap"), x=INTEGER, y=INTEGER),
        obj(kind=enum("long_press"), x=INTEGER, y=INTEGER, duration_ms=INTEGER),
        obj(
            kind=enum("swipe"),
            start_x=INTEGER,
            start_y=INTEGER,
            end_x=INTEGER,
            end_y=INTEGER,
            duration_ms=INTEGER,
        ),
        obj(kind=enum("type_text"), text=STRING),
        obj(kind=enum("back")),
        obj(kind=enum("home")),
        obj(kind=enum("enter")),
    ]
}
SCHEMA = obj(
    rationale=STRING,
    working_plan=STRING,
    previous_effect={
        "anyOf": [
            {"type": "null"},
            obj(
                action_id=STRING,
                verdict=enum("achieved", "not_achieved", "unclear"),
                explanation=STRING,
                observation_ids=EVIDENCE,
            ),
        ]
    },
    next={
        "anyOf": [
            obj(kind=enum("act"), command=COMMAND, timeout_ms=INTEGER),
            obj(kind=enum("observe_after"), delay_ms=INTEGER),
            obj(kind=enum("ask_user"), question=STRING),
            obj(
                kind=enum("conclude"),
                verdict=enum("passed", "failed", "inconclusive"),
                explanation=STRING,
                observation_ids=EVIDENCE,
            ),
        ]
    },
)


def check_schema(value, schema):
    """Validate our deliberately small JSON-schema subset before constructing values."""
    if "anyOf" in schema:
        for variant in schema["anyOf"]:
            try:
                check_schema(value, variant)
                return
            except ValueError:
                pass
        raise ValueError("No supported decision variant")
    kind = schema["type"]
    if kind == "null":
        valid = value is None
    elif kind == "object":
        valid = type(value) is dict and set(value) == set(schema["properties"])
        if valid:
            for key, child in schema["properties"].items():
                check_schema(value[key], child)
    elif kind == "string":
        valid = type(value) is str and len(value) <= schema.get("maxLength", 8000)
    elif kind == "integer":
        valid = type(value) is int and schema["minimum"] <= value <= schema["maximum"]
    elif kind == "array":
        valid = type(value) is list and schema["minItems"] <= len(value) <= schema["maxItems"]
        if valid:
            for item in value:
                check_schema(item, schema["items"])
    else:
        raise ValueError("Unsupported schema")
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise ValueError("Malformed decision field")


def decode_decision(payload, context: AgentContext, usage: ModelUsage) -> AgentDecision:
    check_schema(payload, SCHEMA)
    decision_id = uuid4().hex
    run_id = context.run.run_id
    nxt = payload["next"]
    match nxt["kind"]:
        case "act":
            choice = Act(decode_command(nxt["command"]), nxt["timeout_ms"])
        case "observe_after":
            choice = ObserveAfter(nxt["delay_ms"])
        case "ask_user":
            choice = AskUser(nxt["question"])
        case "conclude":
            choice = Conclude(
                Assessment(
                    run_id,
                    decision_id,
                    SemanticVerdict(nxt["verdict"]),
                    nxt["explanation"],
                    tuple(nxt["observation_ids"]),
                )
            )
    effect = payload["previous_effect"]
    if effect is not None:
        effect = EffectAssessment(
            effect["action_id"],
            EffectVerdict(effect["verdict"]),
            effect["explanation"],
            tuple(effect["observation_ids"]),
        )
    decision = AgentDecision(
        decision_id,
        run_id,
        context.current_observation_id,
        tuple(i.observation.observation_id for i in context.images),
        choice,
        payload["rationale"],
        payload["working_plan"],
        context.run.configuration.identity,
        usage,
        effect,
    )
    validate_decision(
        decision,
        context.run,
        tuple(i.observation for i in context.images),
        context.current_observation_id,
        context.previous_action,
    )
    return decision
