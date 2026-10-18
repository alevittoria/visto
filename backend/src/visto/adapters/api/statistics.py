"""Read-only aggregation of stored run outcomes for the console statistics view.

Counts only what was persisted: terminal records, action records and model usage
reported by recorded decisions. It never re-judges a run; the AI verdict is reused.
Costs use the price snapshot in effect on the run's UTC creation day, at base
input/output rates (cached-input and long-context tiers are not distinguished).
"""

import hashlib
from datetime import UTC
from statistics import mean, median

from visto.adapters.pricing import PriceHistory
from visto.domain.run import AIConclusion, Run

OUTCOMES = (
    "passed",
    "failed",
    "inconclusive",
    "infrastructure_failure",
    "cancelled",
    "budget_exhausted",
    "unfinished",
)
RECENT_RUNS = 20
TERMINAL_KINDS = {
    "InfrastructureFailure": "infrastructure_failure",
    "Cancelled": "cancelled",
    "BudgetExhausted": "budget_exhausted",
}


def outcome(run: Run) -> str:
    if run.terminal is None:
        return "unfinished"
    if isinstance(run.terminal, AIConclusion):
        return run.terminal.assessment.verdict.value
    return TERMINAL_KINDS[type(run.terminal).__name__]


def duration_ms(run: Run) -> int | None:
    """Creation to terminal record, including paused/waiting time; None while unfinished."""
    if run.terminal is None:
        return None
    return max(0, round((run.updated_at - run.created_at).total_seconds() * 1000))


def scenario_key(run: Run) -> str:
    goal = run.goal
    material = "\x1f".join((goal.text, goal.expected_result or "", *goal.constraints))
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def run_cost(run: Run, usage, prices: PriceHistory | None) -> tuple[float | None, bool]:
    """(USD or None when unpriced, approximate). A run without tokens costs 0."""
    input_tokens, output_tokens, _, _ = usage.get(run.run_id, (0, 0, 0, 0))
    if input_tokens == 0 and output_tokens == 0:
        return 0.0, False
    found = None
    if prices is not None:
        found = prices.at(run.configuration.identity.model, run.created_at.astimezone(UTC).date())
    if found is None:
        return None, False
    price, approximate = found
    usd = (input_tokens * price.input_per_m + output_tokens * price.output_per_m) / 1e6
    return usd, approximate


def cost_view(run: Run, usage, prices: PriceHistory | None) -> dict:
    """Single-run cost with the price list it used; usd is None when unpriced."""
    usd, approximate = run_cost(run, usage, prices)
    found = None
    if prices is not None:
        found = prices.at(run.configuration.identity.model, run.created_at.astimezone(UTC).date())
    price = found[0] if found else None
    return {
        "usd": usd,
        "approximate": approximate,
        "price_day": price.day.isoformat() if price else None,
        "input_per_m": price.input_per_m if price else None,
        "output_per_m": price.output_per_m if price else None,
    }


def _spread(values: list[int]) -> dict | None:
    if not values:
        return None
    return {
        "mean": round(mean(values)),
        "median": round(median(values)),
        "min": min(values),
        "max": max(values),
    }


def _group(key, label, runs, usage, actions, prices, *, recent=False) -> dict:
    outcomes = dict.fromkeys(OUTCOMES, 0)
    tokens_by_model: dict[str, dict[str, int]] = {}
    unknown = 0
    for run in runs:
        outcomes[outcome(run)] += 1
        input_tokens, output_tokens, _, missing = usage.get(run.run_id, (0, 0, 0, 0))
        unknown += missing
        model = tokens_by_model.setdefault(
            run.configuration.identity.model, {"input_tokens": 0, "output_tokens": 0}
        )
        model["input_tokens"] += input_tokens
        model["output_tokens"] += output_tokens
    finished = [run for run in runs if run.terminal is not None]
    costs = {run.run_id: run_cost(run, usage, prices) for run in runs}
    unpriced = [run for run in runs if costs[run.run_id][0] is None]
    result = {
        "key": key,
        "label": label,
        "runs": len(runs),
        "outcomes": outcomes,
        "ai_conclusions": sum(outcomes[name] for name in ("passed", "failed", "inconclusive")),
        "duration_ms": _spread([duration_ms(run) for run in finished]),
        "actions": _spread([actions.get(run.run_id, 0) for run in finished]),
        "input_tokens": sum(item["input_tokens"] for item in tokens_by_model.values()),
        "output_tokens": sum(item["output_tokens"] for item in tokens_by_model.values()),
        "unknown_usage_decisions": unknown,
        "tokens_by_model": tokens_by_model,
        "cost": {
            "usd": sum(value for value, _ in costs.values() if value is not None),
            "unpriced_runs": len(unpriced),
            "unpriced_models": sorted({run.configuration.identity.model for run in unpriced}),
            "approximate_runs": sum(approximate for _, approximate in costs.values()),
        },
    }
    if recent:
        first = runs[0].goal
        result["expected_result"] = first.expected_result
        result["constraints"] = list(first.constraints)
        result["recent"] = [
            {
                "run_id": run.run_id,
                "outcome": outcome(run),
                "model": run.configuration.identity.model,
                "created_at": run.created_at.isoformat(),
                "duration_ms": duration_ms(run),
                "actions": actions.get(run.run_id, 0),
                "cost_usd": costs[run.run_id][0],
                "cost_approximate": costs[run.run_id][1],
            }
            for run in runs[:RECENT_RUNS]
        ]
    return result


def summarize(
    runs: list[Run],
    usage: dict[str, tuple[int, int, int, int]],
    actions: dict[str, int],
    prices: PriceHistory | None = None,
) -> dict:
    """`runs` newest first. Groups keep that order; group lists are by size, then recency."""
    by_model: dict[str, list[Run]] = {}
    by_scenario: dict[str, list[Run]] = {}
    for run in runs:
        by_model.setdefault(run.configuration.identity.model, []).append(run)
        by_scenario.setdefault(scenario_key(run), []).append(run)

    def ordered(groups):
        return sorted(groups.items(), key=lambda item: -len(item[1]))

    return {
        "overall": _group("all", "All runs", runs, usage, actions, prices),
        "by_model": [
            _group(key, key, items, usage, actions, prices) for key, items in ordered(by_model)
        ],
        "by_scenario": [
            _group(key, items[0].goal.text, items, usage, actions, prices, recent=True)
            for key, items in ordered(by_scenario)
        ],
    }
