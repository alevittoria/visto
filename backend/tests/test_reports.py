"""Pure report fidelity, outcome distinctions and inert rendering contracts."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import pytest

from visto.adapters.reports import render_html, render_json
from visto.domain.commands import CommandKind, Tap
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    ArtifactRef,
    Assessment,
    Conclude,
    EffectAssessment,
    EffectVerdict,
    Goal,
    ModelIdentity,
    ModelUsage,
    Observation,
    ReceiptStatus,
    RunConfiguration,
    RunLimits,
    SemanticVerdict,
    TechnicalReceipt,
)
from visto.domain.run import (
    AIConclusion,
    BudgetExhausted,
    BudgetKind,
    Cancelled,
    InfrastructureFailure,
    PendingQuestion,
    Run,
    RunUsage,
    UserAnswer,
)

NOW = datetime(2026, 10, 16, tzinfo=UTC)
LATER = NOW + timedelta(seconds=2)


def fixture():
    configuration = RunConfiguration(
        RunLimits(60000, 10, 20, 5000, 2000),
        tuple(CommandKind),
        ModelIdentity("provider", "model-v1", "prompt-v2"),
        "android-v3",
    )
    run = Run(
        "run-1",
        "device-1",
        Goal("  Original goal  ", ("no buying",), "visible"),
        configuration,
        NOW,
        NOW,
    ).start(NOW)
    screenshot = ArtifactRef(
        "artifact-1",
        run.run_id,
        "image/png",
        123,
        "a" * 64,
        "C:/private/host/secrets/screenshot.png",
    )
    observation = Observation(
        "obs-1", run.run_id, 1, NOW, run.device_id, "session-1", "lease-1", screenshot, 100, 200, 0
    )
    decision = AgentDecision(
        "decision-1",
        run.run_id,
        "obs-1",
        ("obs-1",),
        Act(Tap(1, 2), 1000),
        "look closer",
        "a flexible plan",
        configuration.identity,
        ModelUsage(12, None),
    )
    action = Action(
        "action-1", run.run_id, decision.decision_id, "obs-1", "lease-1", Tap(1, 2), 1000
    )
    receipt = TechnicalReceipt(
        run.run_id,
        action.action_id,
        ReceiptStatus.COMPLETED,
        NOW,
        LATER,
        NOW,
        "command completed technically",
    )
    return run, (observation, decision, action, receipt)


@pytest.mark.parametrize("verdict", list(SemanticVerdict))
def test_ai_terminal_preserves_assessments_effects_evidence_and_versions(verdict):
    run, history = fixture()
    assessment = Assessment(run.run_id, "decision-2", verdict, "AI judgement", ("obs-1",))
    decision = AgentDecision(
        "decision-2",
        run.run_id,
        "obs-1",
        ("obs-1",),
        Conclude(assessment),
        "finish",
        "updated plan",
        run.configuration.identity,
        ModelUsage(4, 5),
        EffectAssessment("action-1", EffectVerdict.UNCLEAR, "uncertain effect", ("obs-1",)),
    )
    run = run.finish(AIConclusion(run.run_id, LATER, assessment))
    data = json.loads(render_json(run, (*history, decision)))
    assert data["outcome"] == verdict.value
    assert data["run"]["terminal"]["type"] == "AIConclusion"
    assert data["run"]["terminal"]["assessment"]["explanation"] == "AI judgement"
    assert data["history"][-1]["previous_effect"]["verdict"] == "unclear"
    assert data["history"][-1]["presented_observation_ids"] == ["obs-1"]
    assert data["history"][-1]["working_plan"] == "updated plan"
    assert data["run"]["configuration"]["identity"]["instruction_version"] == "prompt-v2"
    assert data["run"]["configuration"]["device_adapter_version"] == "android-v3"
    assert data["timing"]["terminal_elapsed_ms"] == 2000
    assert verdict.value in render_html(run, (*history, decision))


@pytest.mark.parametrize(
    "terminal, outcome",
    [
        (
            InfrastructureFailure("run-1", LATER, "provider", "unavailable", ("obs-1",)),
            "infrastructure_failure",
        ),
        (Cancelled("run-1", LATER, "operator"), "cancelled"),
        (
            BudgetExhausted("run-1", LATER, BudgetKind.ACTIONS, RunUsage(2000, 10, 3)),
            "budget_exhausted",
        ),
    ],
)
def test_technical_terminals_never_become_semantic_pass(terminal, outcome):
    run, history = fixture()
    run = run.finish(terminal)
    data = json.loads(render_json(run, history))
    assert data["outcome"] == outcome
    assert "assessment" not in data["run"]["terminal"]
    assert data["history"][-1]["status"] == "completed"
    assert outcome in render_html(run, history)


@pytest.mark.parametrize("state", ["created", "running", "paused", "waiting_for_user"])
def test_incomplete_and_suspended_states_are_explicit_without_invented_duration(state):
    run, history = fixture()
    if state == "created":
        run = replace(run, state=type(run.state).CREATED, revision=0)
    elif state == "paused":
        run = run.pause(LATER)
    elif state == "waiting_for_user":
        question = PendingQuestion("question-1", run.run_id, "decision-1", "Which item?", NOW)
        run = run.ask(question, NOW)
        history = (*history, question)
    data = json.loads(render_json(run, history))
    assert data["outcome"] == state
    assert data["run"]["terminal"] is None
    assert data["timing"]["terminal_elapsed_ms"] is None
    assert state in render_html(run, history)


def test_export_preserves_request_order_technical_receipts_and_scoped_links_without_host_paths():
    run, history = fixture()
    data = json.loads(render_json(run, history))
    assert data["schema_version"] == 1
    assert data["run"]["goal"]["text"] == "  Original goal  "
    assert data["run"]["goal"]["constraints"] == ["no buying"]
    assert data["run"]["goal"]["expected_result"] == "visible"
    assert [item["type"] for item in data["history"]] == [
        "Observation",
        "AgentDecision",
        "Action",
        "TechnicalReceipt",
    ]
    assert data["history"][2]["command"] == {"type": "Tap", "kind": "tap", "x": 1, "y": 2}
    assert data["history"][3]["finished_at"] == LATER.isoformat()
    ref = data["history"][0]["screenshot"]
    assert ref["url"] == "/api/runs/run-1/artifacts/obs-1"
    assert ref["sha256"] == "a" * 64
    for output in (render_json(run, history), render_html(run, history)):
        assert "storage_key" not in output
        assert "C:/private" not in output
        assert "/api/runs/run-1/artifacts/obs-1" in output


def test_unknown_usage_is_not_zero_or_a_complete_total_and_cost_is_unknown():
    run, history = fixture()
    usage = json.loads(render_json(run, history))["reported_usage"]
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] is None
    assert usage["known_output_tokens"] == 0
    assert usage["unknown_output_token_decisions"] == 1
    assert usage["cost"] is None
    assert "unrecorded" in usage["scope"]
    empty = json.loads(render_json(run, ()))["reported_usage"]
    assert empty["input_tokens"] is None
    assert empty["output_tokens"] is None
    assert "unknown" in render_html(run, history)


def test_question_and_attributed_answer_survive_resume():
    run, history = fixture()
    question = PendingQuestion("question-1", run.run_id, "decision-1", "Which item?", NOW)
    answer = UserAnswer(question.question_id, run.run_id, "The blue item", "operator", NOW)
    run = run.ask(question, NOW).answer(answer).resume(LATER)
    data = json.loads(render_json(run, (*history, question, answer)))
    assert data["run"]["pending_question"] is None
    assert data["history"][-2]["question"] == "Which item?"
    assert data["history"][-1]["answered_by"] == "operator"
    assert data["history"][-1]["text"] == "The blue item"


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            assert not name.lower().startswith("on")
            if name in ("href", "src"):
                self.links.append(value)


def test_html_is_inert_and_all_untrusted_text_is_escaped_without_external_urls():
    run, history = fixture()
    evil = '<script>alert(1)</script><img src="https://evil" onerror="x"> & "'
    run = replace(run, goal=Goal(evil, (evil,), evil))
    history = (*history[:-1], replace(history[-1], detail=evil))
    output = render_html(run, history)
    parser = Tags()
    parser.feed(output)
    assert "script" not in parser.tags
    assert "img" not in parser.tags
    assert parser.links and set(parser.links) == {"/api/runs/run-1/artifacts/obs-1"}
    assert "&lt;script&gt;" in output
    assert "Content-Security-Policy" in output
    assert json.loads(render_json(run, history))["run"]["goal"]["text"] == evil


@pytest.mark.parametrize(
    "identifier",
    ["..", "../other", "a/b", "a?x=y", "a#x", "a%2fb", 'a" onmouseover="x', "https://evil", "a\\b"],
)
def test_link_identifiers_cannot_escape_the_scoped_artifact_route(identifier):
    run, history = fixture()
    for candidate_run, candidate_history in [
        (replace(run, run_id=identifier), ()),
        (run, (replace(history[0], observation_id=identifier),)),
    ]:
        with pytest.raises(ValueError):
            render_json(candidate_run, candidate_history)
        with pytest.raises(ValueError):
            render_html(candidate_run, candidate_history)


def test_cross_run_records_and_unsupported_objects_fail_closed():
    run, history = fixture()
    with pytest.raises(ValueError):
        render_json(run, (replace(history[1], run_id="other-run"),))
    with pytest.raises(ValueError):
        render_json(run, (object(),))
