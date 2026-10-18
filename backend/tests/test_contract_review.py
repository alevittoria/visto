"""Independent review probes for technical boundaries, never UI success rules."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from visto.adapters.command_codec import decode_command
from visto.application.context import AgentContext, PresentedImage
from visto.domain.commands import CommandKind, Tap
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    ArtifactRef,
    EffectAssessment,
    EffectVerdict,
    Goal,
    ModelIdentity,
    Observation,
    ReceiptStatus,
    RunConfiguration,
    RunLimits,
    TechnicalReceipt,
)
from visto.domain.run import PendingQuestion, Run, UserAnswer
from visto.domain.validation import validate_decision

NOW = datetime(2026, 10, 15, tzinfo=UTC)


@pytest.fixture
def decision_case():
    identity = ModelIdentity("provider", "selected-model", "instructions-v1")
    run = Run(
        run_id="r",
        device_id="selected-device",
        goal=Goal("Preserve this exact goal", ("Never submit payment",)),
        configuration=RunConfiguration(
            RunLimits(60_000, 10, 20, 3_000, 1_000),
            tuple(CommandKind),
            identity,
            "device-adapter-v1",
        ),
        created_at=NOW,
        updated_at=NOW,
    ).start(NOW)
    current = Observation(
        "current",
        "r",
        2,
        NOW,
        "selected-device",
        "session",
        "lease",
        ArtifactRef("image", "r", "image/png", 3, "0" * 64, "opaque"),
        100,
        200,
        0,
    )
    decision = AgentDecision(
        "d",
        "r",
        "current",
        ("current",),
        Act(Tap(5, 5), 1_000),
        "Observe after this tap",
        "Flexible plan",
        identity,
    )
    return run, current, decision


def test_current_observation_must_belong_to_selected_device(decision_case):
    run, current, decision = decision_case
    foreign = replace(current, device_id="another-device")
    with pytest.raises(ValueError):
        validate_decision(decision, run, (foreign,), "current")


def test_decision_must_match_fresh_current_frame(decision_case):
    run, current, decision = decision_case
    newer = replace(current, observation_id="newer", sequence=3)
    with pytest.raises(ValueError):
        validate_decision(decision, run, (current, newer), "newer")


def test_decision_may_not_claim_another_model_identity(decision_case):
    run, current, decision = decision_case
    wrong_identity = replace(
        decision,
        identity=ModelIdentity("provider", "unconfigured-model", "instructions-v1"),
    )
    with pytest.raises(ValueError):
        validate_decision(wrong_identity, run, (current,), "current")


def test_current_frame_must_have_been_presented_to_agent(decision_case):
    run, current, decision = decision_case
    older = replace(current, observation_id="older", sequence=1)
    concealed_current = replace(decision, presented_observation_ids=("older",))
    with pytest.raises(ValueError):
        validate_decision(concealed_current, run, (older, current), "current")


def test_previous_action_cannot_be_assessed_using_its_own_source_frame(decision_case):
    run, current, decision = decision_case
    previous = Action("previous", "r", "prior-decision", "current", "lease", Tap(1, 1), 1_000)
    repeated_frame = replace(
        decision,
        previous_effect=EffectAssessment(
            "previous",
            EffectVerdict.UNCLEAR,
            "Need fresh evidence",
            ("current",),
        ),
    )
    with pytest.raises(ValueError):
        validate_decision(repeated_frame, run, (current,), "current", previous)


def image_for(observation):
    content = b"abc"
    artifact = replace(observation.screenshot, sha256=hashlib.sha256(content).hexdigest())
    return PresentedImage(replace(observation, screenshot=artifact), content)


def test_agent_context_rejects_capture_before_previous_command_finished(decision_case):
    run, current, _ = decision_case
    previous = Action("previous", "r", "prior", "older", "lease", Tap(1, 1), 1_000)
    receipt = TechnicalReceipt(
        "r",
        "previous",
        ReceiptStatus.COMPLETED,
        NOW,
        NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError):
        AgentContext(run, (image_for(current),), "current", previous, receipt)


def test_agent_context_does_not_mark_older_frame_as_current(decision_case):
    run, current, _ = decision_case
    newer = replace(current, observation_id="newer", sequence=3)
    with pytest.raises(ValueError):
        AgentContext(run, (image_for(current), image_for(newer)), "current")


@pytest.mark.parametrize("other_sequence", [1, 2])
def test_presented_evidence_rejects_tied_or_time_reversed_sequences(
    decision_case,
    other_sequence,
):
    run, current, decision = decision_case
    # A later capture cannot share an earlier sequence or precede sequence 2.
    conflicting = replace(
        current,
        observation_id="conflicting",
        sequence=other_sequence,
        captured_at=NOW + timedelta(seconds=1),
    )
    proposed = replace(decision, presented_observation_ids=("current", "conflicting"))
    with pytest.raises(ValueError):
        validate_decision(proposed, run, (current, conflicting), "current")
    with pytest.raises(ValueError):
        AgentContext(run, (image_for(current), image_for(conflicting)), "current")


def test_original_goal_and_attributed_clarification_reach_resumed_context(decision_case):
    run, current, _ = decision_case
    question = PendingQuestion("q", "r", "d", "Which synthetic account?", NOW)
    answer = UserAnswer("q", "r", "The seeded account", "requesting-user", NOW)
    resumed = run.ask(question, NOW).answer(answer).resume(NOW)
    context = AgentContext(resumed, (image_for(current),), "current", answers=(answer,))
    assert context.run.goal is run.goal
    assert context.run.configuration is run.configuration
    assert context.answers == (answer,)
    assert context.answers[0].answered_by == "requesting-user"
    with pytest.raises(ValueError):
        replace(context, answers=(replace(answer, run_id="foreign-run"),))


@pytest.mark.parametrize("kind", [[], {}, ["tap"], None, 7, True])
def test_non_string_command_discriminator_is_a_protocol_error(kind):
    with pytest.raises(ValueError):
        decode_command({"kind": kind})
