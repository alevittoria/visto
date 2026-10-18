"""Pure, portable evidence reports; no artifact reads or inference are performed."""

import json
import re
from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime, timedelta
from enum import Enum
from html import escape

from visto.application.ports import RunRecord
from visto.domain import models
from visto.domain.commands import COMMAND_TYPES
from visto.domain.run import (
    TERMINAL_TYPES,
    AIConclusion,
    BudgetExhausted,
    Cancelled,
    InfrastructureFailure,
    PendingQuestion,
    Run,
    RunUsage,
    UserAnswer,
)

_RECORD_TYPES = (
    models.Observation,
    models.AgentDecision,
    models.Action,
    models.TechnicalReceipt,
    PendingQuestion,
    UserAnswer,
)
_VALUE_TYPES = (
    *_RECORD_TYPES,
    *TERMINAL_TYPES,
    *COMMAND_TYPES,
    Run,
    RunUsage,
    models.Goal,
    models.RunConfiguration,
    models.RunLimits,
    models.ModelIdentity,
    models.ModelUsage,
    models.ArtifactRef,
    models.Assessment,
    models.EffectAssessment,
    models.Act,
    models.ObserveAfter,
    models.AskUser,
    models.Conclude,
)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
# Integer timedelta division avoids floating-point rounding for recorded times.
_MILLISECOND = timedelta(milliseconds=1)


def _identifier(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("Unsafe report route identifier")
    return value


def _value(value: object, run_id: str) -> object:
    if isinstance(value, Enum):
        return value.value
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is tuple:
        return [_value(item, run_id) for item in value]
    if type(value) not in _VALUE_TYPES:
        raise ValueError("Unsupported report value")
    if hasattr(value, "run_id") and value.run_id != run_id:
        raise ValueError("Report value belongs to another run")
    result = {
        "type": type(value).__name__,
        **{
            field.name: _value(getattr(value, field.name), run_id)
            for field in fields(value)
            if not (type(value) is models.ArtifactRef and field.name == "storage_key")
        },
    }
    if type(value) in COMMAND_TYPES:
        result["kind"] = value.kind.value
    if type(value) is models.Observation:
        observation_id = _identifier(value.observation_id)
        result["screenshot"]["url"] = f"/api/runs/{run_id}/artifacts/{observation_id}"
    return result


def _outcome(run: Run) -> str:
    match run.terminal:
        case AIConclusion(assessment=assessment):
            return assessment.verdict.value
        case InfrastructureFailure():
            return "infrastructure_failure"
        case Cancelled():
            return "cancelled"
        case BudgetExhausted():
            return "budget_exhausted"
        case _:
            return run.state.value


def _usage(history: Sequence[RunRecord]) -> dict[str, object]:
    decisions = [item for item in history if type(item) is models.AgentDecision]
    usage: dict[str, object] = {
        "scope": (
            "persisted_decisions_only; unrecorded or failed requests may incur unknown usage"
        ),
        "recorded_decisions": len(decisions),
        "cost": None,
        "cost_status": "unknown; costs are not recorded by the runtime",
    }
    for name in ("input_tokens", "output_tokens"):
        values = [getattr(item.usage, name) for item in decisions]
        known = sum(value for value in values if value is not None)
        usage[name] = known if values and all(value is not None for value in values) else None
        usage[f"known_{name}"] = known
        usage[f"unknown_{name.removesuffix('s')}_decisions"] = sum(
            value is None for value in values
        )
    return usage


def report_data(run: Run, history: Sequence[RunRecord]) -> dict[str, object]:
    """Return a versioned JSON-compatible snapshot without filesystem storage keys.

    Input is a trusted Run plus ordered stored records. Wrong-run values and
    unsupported records fail closed. Text is preserved exactly as recorded;
    screenshot links are derived exclusively from validated run/observation IDs.
    No completion, model correctness, artifact availability or cost is inferred.
    """
    if type(run) is not Run:
        raise ValueError("Expected a Run")
    run_id = _identifier(run.run_id)
    records = tuple(history)
    if any(type(record) not in _RECORD_TYPES for record in records):
        raise ValueError("Unsupported report record")
    return {
        "schema_version": 1,
        "outcome": _outcome(run),
        "notice": (
            "AI assessments are model judgements, not independently verified ground truth. "
            "Completed technical commands do not establish semantic test success. "
            "Nonterminal reports are snapshots; screenshot links require the local service."
        ),
        "run": _value(run, run_id),
        "timing": {
            "created_at": run.created_at.isoformat(),
            "snapshot_updated_at": run.updated_at.isoformat(),
            "snapshot_elapsed_ms": (run.updated_at - run.created_at) // _MILLISECOND,
            "terminal_elapsed_ms": (
                (run.terminal.recorded_at - run.created_at) // _MILLISECOND
                if run.terminal is not None
                else None
            ),
            "scope": "stored timestamps only; no live duration or inference latency is inferred",
        },
        "reported_usage": _usage(records),
        "history": [_value(record, run_id) for record in records],
    }


def render_json(run: Run, history: Sequence[RunRecord]) -> str:
    """Render UTF-8 JSON text; missing usage/timing/cost remains JSON null."""
    return json.dumps(report_data(run, history), ensure_ascii=False, indent=2) + "\n"


def _html(value: object, key: str = "") -> str:
    if isinstance(value, dict):
        return (
            "<dl>"
            + "".join(
                f"<dt><strong>{escape(name.replace('_', ' '))}</strong></dt>"
                f"<dd>{_html(item, name)}</dd>"
                for name, item in value.items()
            )
            + "</dl>"
        )
    if isinstance(value, list):
        if not value:
            return "<p>None recorded</p>"
        return "<ol>" + "".join(f"<li>{_html(item)}</li>" for item in value) + "</ol>"
    if value is None:
        return "<span>unknown / not recorded</span>"
    if key == "url":
        # This key is generated only for a validated Observation, never copied
        # from user text or storage_key. All values still receive HTML escaping.
        return f'<a href="{escape(str(value), quote=True)}">Open screenshot</a>'
    return f"<pre>{escape(str(value), quote=True)}</pre>"


def render_html(run: Run, history: Sequence[RunRecord]) -> str:
    """Render escaped inert HTML with no scripts, remote assets or image loading."""
    data = report_data(run, history)
    run_data = data["run"]
    header = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'\">"
        '<meta name="referrer" content="no-referrer">'
        "<title>Visto evidence report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:70rem;margin:2rem auto;"
        "padding:0 1rem;line-height:1.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;"
        "margin:.2rem 0}dd{margin-bottom:.7rem}details{border-top:1px solid #aaa;"
        "padding:.8rem 0}summary{cursor:pointer;font-weight:bold}dt{color:#444}</style>"
        "</head><body>"
        "<h1>Visto evidence report</h1>"
    )
    sections = (
        ("Outcome", data["outcome"]),
        ("Interpretation and snapshot limits", data["notice"]),
        ("Original request", run_data["goal"]),
        (
            "Run and terminal record",
            {key: value for key, value in run_data.items() if key != "goal"},
        ),
        ("Timing", data["timing"]),
        ("Reported usage", data["reported_usage"]),
    )
    body = "".join(f"<section><h2>{name}</h2>{_html(value)}</section>" for name, value in sections)
    body += "<section><h2>Ordered evidence history</h2>"
    if not data["history"]:
        body += "<p>No history recorded in this snapshot.</p>"
    for index, record in enumerate(data["history"], 1):
        body += (
            f"<details open><summary>{index}. {escape(record['type'])}</summary>"
            f"{_html(record)}</details>"
        )
    return header + body + "</section></body></html>\n"


__all__ = ["render_html", "render_json", "report_data"]
