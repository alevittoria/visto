"""Statistics reuse stored outcomes; they never re-judge a run."""

from datetime import UTC, datetime, timedelta

from visto.adapters.api.statistics import outcome, summarize
from visto.adapters.pricing import ModelPrice, PriceHistory
from visto.domain.commands import CommandKind
from visto.domain.models import (
    Assessment,
    Goal,
    ModelIdentity,
    RunConfiguration,
    RunLimits,
    SemanticVerdict,
)
from visto.domain.run import (
    AIConclusion,
    BudgetExhausted,
    BudgetKind,
    Cancelled,
    InfrastructureFailure,
    Run,
    RunUsage,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def run(run_id, model="model-a", goal="Open the fictional notes app", seconds=None, end=None):
    configuration = RunConfiguration(
        RunLimits(60000, 10, 20, 5000, 2000),
        tuple(CommandKind),
        ModelIdentity("provider", model, "prompt-v3"),
        "android-v3",
    )
    created = Run(run_id, "device-A", Goal(goal), configuration, NOW, NOW).start(NOW)
    if end is None:
        return created
    at = NOW + timedelta(seconds=seconds)
    match end:
        case "passed" | "failed" | "inconclusive":
            assessment = Assessment(run_id, "d-" + run_id, SemanticVerdict(end), "why", ("o",))
            terminal = AIConclusion(run_id, at, assessment)
        case "cancelled":
            terminal = Cancelled(run_id, at, "user")
        case "budget":
            terminal = BudgetExhausted(run_id, at, BudgetKind.ACTIONS, RunUsage(1, 2, 3))
        case _:
            terminal = InfrastructureFailure(run_id, at, "device.execute", "detail")
    return created.finish(terminal)


def test_outcomes_keep_ai_verdicts_and_technical_terminals_distinct():
    assert outcome(run("a", end="passed", seconds=1)) == "passed"
    assert outcome(run("b", end="infra", seconds=1)) == "infrastructure_failure"
    assert outcome(run("c", end="budget", seconds=1)) == "budget_exhausted"
    assert outcome(run("d")) == "unfinished"


def test_groups_by_model_and_scenario_with_spreads_and_tokens():
    runs = [  # Newest first, as the store lists them.
        run("r5"),
        run("r4", model="model-b", end="failed", seconds=40),
        run("r3", goal="Rename a fictional folder", end="cancelled", seconds=5),
        run("r2", end="passed", seconds=20),
        run("r1", end="passed", seconds=10),
    ]
    usage = {"r1": (100, 10, 2, 0), "r2": (300, 30, 3, 1), "r4": (50, 5, 1, 0)}
    actions = {"r1": 2, "r2": 4, "r4": 9}

    result = summarize(runs, usage, actions)

    overall = result["overall"]
    assert overall["runs"] == 5
    assert overall["outcomes"] == {
        "passed": 2,
        "failed": 1,
        "inconclusive": 0,
        "infrastructure_failure": 0,
        "cancelled": 1,
        "budget_exhausted": 0,
        "unfinished": 1,
    }
    assert overall["ai_conclusions"] == 3
    # Unfinished r5 is excluded from duration and action spreads.
    assert overall["duration_ms"] == {"mean": 18750, "median": 15000, "min": 5000, "max": 40000}
    assert overall["actions"] == {"mean": 4, "median": 3, "min": 0, "max": 9}
    assert (overall["input_tokens"], overall["output_tokens"]) == (450, 45)
    assert overall["unknown_usage_decisions"] == 1
    assert overall["tokens_by_model"] == {
        "model-a": {"input_tokens": 400, "output_tokens": 40},
        "model-b": {"input_tokens": 50, "output_tokens": 5},
    }

    assert [group["key"] for group in result["by_model"]] == ["model-a", "model-b"]
    assert result["by_model"][0]["runs"] == 4

    scenarios = result["by_scenario"]
    assert [group["label"] for group in scenarios] == [
        "Open the fictional notes app",
        "Rename a fictional folder",
    ]
    notes = scenarios[0]
    assert notes["runs"] == 4 and notes["outcomes"]["passed"] == 2
    assert [item["run_id"] for item in notes["recent"]] == ["r5", "r4", "r2", "r1"]
    assert notes["recent"][1] == {
        "run_id": "r4",
        "outcome": "failed",
        "model": "model-b",
        "created_at": NOW.isoformat(),
        "duration_ms": 40000,
        "actions": 9,
        "cost_usd": None,
        "cost_approximate": False,
    }
    assert notes["recent"][0]["duration_ms"] is None
    assert "recent" not in result["by_model"][0]


def test_same_goal_text_with_other_expectations_is_another_scenario():
    first = run("a", end="passed", seconds=1)
    other = run("b", end="passed", seconds=1)
    other = other.__class__(
        **{
            **{name: getattr(other, name) for name in other.__dataclass_fields__},
            "goal": Goal(other.goal.text, ("no network",)),
        }
    )
    assert len(summarize([other, first], {}, {})["by_scenario"]) == 2


def test_empty_history_has_no_spreads():
    result = summarize([], {}, {})
    assert result["overall"]["runs"] == 0
    assert result["overall"]["duration_ms"] is None
    assert result["by_model"] == [] and result["by_scenario"] == []


def test_each_run_is_priced_with_the_snapshot_of_its_creation_day():
    day = NOW.date()
    prices = PriceHistory(
        {
            "model-a": [
                ModelPrice(day + timedelta(days=1), 100, 1000),
                ModelPrice(day, 1, 10),
            ]
        }
    )
    old = run("old", end="passed", seconds=1)
    later = run("later", end="passed", seconds=1)
    later = later.__class__(
        **{
            **{name: getattr(later, name) for name in later.__dataclass_fields__},
            "created_at": NOW + timedelta(days=1),
            "updated_at": NOW + timedelta(days=1, seconds=1),
            "terminal": Cancelled("later", NOW + timedelta(days=1, seconds=1), "user"),
        }
    )
    early = run("early", end="passed", seconds=1)
    early = early.__class__(
        **{
            **{name: getattr(early, name) for name in early.__dataclass_fields__},
            "created_at": NOW - timedelta(days=3),
        }
    )
    other = run("other", model="model-z", end="failed", seconds=1)
    idle = run("idle", model="model-z", end="cancelled", seconds=1)
    usage = {name: (1_000_000, 100_000, 1, 0) for name in ("old", "later", "early", "other")}

    result = summarize([later, old, early, other, idle], usage, {}, prices)

    cost = result["overall"]["cost"]
    # old: 1 + 1 = 2; later: 100 + 100 = 200; early: earliest snapshot (approximate) = 2.
    assert cost == {
        "usd": 204,
        "unpriced_runs": 1,
        "unpriced_models": ["model-z"],
        "approximate_runs": 1,
    }
    recent = {item["run_id"]: item for item in result["by_scenario"][0]["recent"]}
    assert recent["old"]["cost_usd"] == 2 and recent["later"]["cost_usd"] == 200
    assert recent["early"]["cost_approximate"] is True
    assert recent["other"]["cost_usd"] is None
    assert recent["idle"]["cost_usd"] == 0  # No tokens, no price needed.
