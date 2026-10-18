from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from visto.domain.commands import (
    Back,
    CommandKind,
    Home,
    LongPress,
    Swipe,
    Tap,
    TypeText,
)
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    ArtifactRef,
    Assessment,
    CapturedImage,
    Conclude,
    DeviceLease,
    EffectAssessment,
    EffectVerdict,
    Goal,
    ModelIdentity,
    ModelUsage,
    Observation,
    ObserveAfter,
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
    RunState,
    RunUsage,
    UserAnswer,
)
from visto.domain.validation import validate_action, validate_decision

NOW = datetime(2026, 10, 15, tzinfo=UTC)


@pytest.fixture
def run():
    return Run(
        run_id="run-1",
        device_id="device-1",
        goal=Goal("  Keep original request  ", ("Do not buy",), "A visible receipt"),
        configuration=RunConfiguration(
            RunLimits(60000, 10, 20, 3000, 1000),
            tuple(CommandKind),
            ModelIdentity("provider", "model", "instructions-v1"),
            "android-v1",
        ),
        created_at=NOW,
        updated_at=NOW,
    ).start(NOW)


@pytest.fixture
def observation():
    return Observation(
        "obs-1",
        "run-1",
        1,
        NOW,
        "device-1",
        "session-1",
        "lease-1",
        ArtifactRef("artifact-1", "run-1", "image/png", 3, "0" * 64, "opaque-key"),
        100,
        200,
        0,
    )


def decision(observation, next_decision=None):
    return AgentDecision(
        "decision-1",
        "run-1",
        observation.observation_id,
        (observation.observation_id,),
        next_decision or Act(Tap(99, 199), 1000),
        "Inspect the next screen",
        "Adaptable plan",
        ModelIdentity("provider", "model", "instructions-v1"),
    )


def test_original_goal_config_and_expected_result_survive_lifecycle(run):
    paused = run.pause(NOW)
    resumed = paused.resume(NOW + timedelta(seconds=1))
    assert resumed.goal is run.goal
    assert resumed.configuration is run.configuration
    assert resumed.goal.text == "  Keep original request  "
    assert resumed.goal.expected_result == "A visible receipt"
    with pytest.raises(FrozenInstanceError):
        resumed.goal.text = "replacement"
    with pytest.raises(ValueError):
        Goal("goal", ["mutable constraint"])


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Tap(True, 1),
        lambda: Tap(float("nan"), 1),
        lambda: Tap(-1, 0),
        lambda: Swipe(0, 0, 1, 1, float("inf")),
        lambda: Swipe(0, 0, 1, 1, 0),
        lambda: LongPress(0, 0, 0),
        lambda: ObserveAfter(True),
        lambda: Act(Back(), float("nan")),
        lambda: TypeText(5),
        lambda: RunLimits(True, 1, 1, 1, 1),
    ],
)
def test_malformed_technical_commands_and_limits_are_rejected(factory):
    with pytest.raises(ValueError):
        factory()


def test_action_binds_exact_decision_observation_and_lease(run, observation):
    proposed = decision(observation)
    action = Action("action-1", "run-1", "decision-1", "obs-1", "lease-1", Tap(99, 199), 1000)
    lease = DeviceLease("lease-1", "run-1", "device-1", "session-1")
    validate_decision(proposed, run, (observation,), "obs-1")
    validate_action(action, proposed, observation, lease, run.configuration)
    for invalid in (
        replace(action, decision_id="other"),
        replace(action, observation_id="old"),
        replace(action, lease_id="old-lease"),
        replace(action, command=Home()),
    ):
        with pytest.raises(ValueError):
            validate_action(invalid, proposed, observation, lease, run.configuration)
    with pytest.raises(ValueError):
        validate_action(
            action, proposed, observation, replace(lease, session_id="new"), run.configuration
        )


def test_coordinate_bounds_and_capabilities_are_technical_only(run, observation):
    for command in (Tap(100, 0), Swipe(0, 0, 99, 200, 100), LongPress(100, 0, 500)):
        proposed = decision(observation, Act(command, 1000))
        with pytest.raises(ValueError):
            validate_decision(proposed, run, (observation,), "obs-1")
    for command in (LongPress(1, 1, 1001), Swipe(0, 0, 1, 1, 1001)):
        proposed = decision(observation, Act(command, 1000))
        with pytest.raises(ValueError):
            validate_decision(proposed, run, (observation,), "obs-1")
    disabled = replace(
        run, configuration=replace(run.configuration, capabilities=(CommandKind.BACK,))
    )
    with pytest.raises(ValueError):
        validate_decision(decision(observation), disabled, (observation,), "obs-1")


def test_conclusion_requires_same_run_presented_evidence(run, observation):
    assessment = Assessment(
        "run-1", "decision-1", SemanticVerdict.PASSED, "The AI judges success", ("obs-1",)
    )
    proposed = decision(observation, Conclude(assessment))
    validate_decision(proposed, run, (observation,), "obs-1")
    for invalid in (
        replace(proposed, run_id="other-run"),
        replace(proposed, presented_observation_ids=("unpresented",)),
        replace(proposed, next=Conclude(replace(assessment, observation_ids=("unpresented",)))),
        replace(proposed, next=Conclude(replace(assessment, decision_id="other-decision"))),
    ):
        with pytest.raises(ValueError):
            validate_decision(invalid, run, (observation,), "obs-1")
    with pytest.raises(ValueError):
        Assessment("run-1", "decision-1", SemanticVerdict.PASSED, "No evidence", ())
    with pytest.raises(ValueError):
        validate_decision(
            proposed,
            run,
            (
                replace(
                    observation,
                    run_id="other-run",
                    screenshot=replace(observation.screenshot, run_id="other-run"),
                ),
            ),
            "obs-1",
        )


def test_previous_effect_references_exact_previous_action(run, observation):
    previous = Action("previous", "run-1", "prior-decision", "obs-before", "lease-1", Back(), 1000)
    proposed = replace(
        decision(observation),
        previous_effect=EffectAssessment(
            "previous",
            EffectVerdict.UNCLEAR,
            "Need another view",
            ("obs-1",),
        ),
    )
    validate_decision(proposed, run, (observation,), "obs-1", previous)
    with pytest.raises(ValueError):
        validate_decision(proposed, run, (observation,), "obs-1")
    with pytest.raises(ValueError):
        validate_decision(decision(observation), run, (observation,), "obs-1", previous)


def test_question_answer_scope_idempotence_and_resume(run):
    question = PendingQuestion("question-1", "run-1", "decision-1", "Which account?", NOW)
    waiting = run.ask(question, NOW)
    assert waiting.state is RunState.WAITING_FOR_USER
    with pytest.raises(ValueError):
        waiting.resume(NOW)
    answer = UserAnswer("question-1", "run-1", "Synthetic account", "user", NOW)
    answered = waiting.answer(answer)
    assert answered.answer(answer) == answered
    for invalid in (
        replace(answer, run_id="other"),
        replace(answer, question_id="stale"),
        replace(answer, text="conflict"),
    ):
        with pytest.raises(ValueError):
            answered.answer(invalid)
    resumed = answered.resume(NOW)
    assert resumed.pending_question is None
    assert resumed.goal is run.goal
    with pytest.raises(ValueError):
        resumed.answer(answer)


def test_first_terminal_wins_and_never_becomes_another_verdict(run):
    cancelled = run.finish(Cancelled("run-1", NOW, "user"))
    ai = AIConclusion(
        "run-1",
        NOW,
        Assessment("run-1", "decision-1", SemanticVerdict.PASSED, "AI assessment", ("obs-1",)),
    )
    assert cancelled.finish(ai) is cancelled
    assert not hasattr(cancelled.terminal, "assessment")
    with pytest.raises(ValueError):
        cancelled.resume(NOW)
    with pytest.raises(ValueError):
        run.pause(NOW).finish(ai)


def test_unknown_usage_remains_unknown_and_timestamps_are_aware():
    assert ModelUsage().input_tokens is None
    assert ModelUsage(input_tokens=0).input_tokens == 0
    with pytest.raises(ValueError):
        PendingQuestion("q", "r", "d", "Question?", datetime(2026, 10, 15))


def test_raw_capture_is_distinct_from_persisted_observation_and_rejects_invalid_frames():
    lease = DeviceLease("lease", "run", "device", "session")
    image = CapturedImage(lease, NOW, b"fixture bytes", "image/png", 100, 200, 90)
    assert image.lease is lease
    assert not hasattr(image, "observation_id")
    for changes in (
        {"content": b""},
        {"width": True},
        {"rotation": 45},
        {"media_type": "text/html"},
    ):
        with pytest.raises(ValueError):
            replace(image, **changes)


def test_receipt_status_does_not_create_a_semantic_verdict_and_time_is_ordered():
    receipt = TechnicalReceipt("r", "action", ReceiptStatus.COMPLETED, NOW, NOW)
    assert not hasattr(receipt, "verdict")
    assert not hasattr(receipt, "assessment")
    assert replace(receipt, status=ReceiptStatus.UNCERTAIN).status is ReceiptStatus.UNCERTAIN
    for changes in (
        {"finished_at": NOW - timedelta(seconds=1)},
        {"started_at": NOW + timedelta(seconds=1)},
        {"status": "completed"},
    ):
        with pytest.raises(ValueError):
            replace(receipt, **changes)


def test_technical_stops_can_terminate_suspended_question_without_ai_verdict(run):
    waiting = run.ask(PendingQuestion("q", "run-1", "d", "Which account?", NOW), NOW)
    for terminal in (
        InfrastructureFailure("run-1", NOW, "device", "Unavailable", ("obs-1",)),
        BudgetExhausted("run-1", NOW, BudgetKind.WALL_TIME, RunUsage(60000, 1, 1)),
        Cancelled("run-1", NOW, "user"),
    ):
        stopped = waiting.finish(terminal)
        assert stopped.terminal is terminal
        assert stopped.pending_question.cancelled_at == NOW
        assert not hasattr(stopped.terminal, "assessment")
    with pytest.raises(ValueError):
        replace(run, state=RunState.TERMINAL)
