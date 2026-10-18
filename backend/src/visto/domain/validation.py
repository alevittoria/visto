"""Cross-reference and technical checks; never inspect application pixels/text."""

from ._validation import items
from .commands import DeviceCommand, LongPress, Swipe, Tap
from .models import (
    Act,
    Action,
    AgentDecision,
    Conclude,
    DeviceLease,
    Observation,
    ObserveAfter,
    RunConfiguration,
)
from .run import Run, RunState


def validate_observations(
    run: Run,
    observations: tuple[Observation, ...],
    current_observation_id: str,
) -> Observation:
    """Validate actual presented evidence and fresh current frame, without pixels."""
    if run.state is not RunState.RUNNING:
        raise ValueError("Agent context requires a running run")
    items(observations, Observation, nonempty=True)
    ids = tuple(o.observation_id for o in observations)
    if len(set(ids)) != len(ids) or current_observation_id not in ids:
        raise ValueError("Missing current or duplicate observation")
    if len({o.sequence for o in observations}) != len(observations):
        raise ValueError("Duplicate observation sequence")
    if any(o.run_id != run.run_id or o.device_id != run.device_id for o in observations):
        raise ValueError("Observation belongs to another run/device")
    current = observations[ids.index(current_observation_id)]
    if any(
        o.sequence > current.sequence or o.captured_at > current.captured_at for o in observations
    ):
        raise ValueError("Current observation is stale relative to presented evidence")
    if current.captured_at < run.updated_at:
        raise ValueError("Current observation predates latest run transition")
    return current


def _command_bounds(
    command: DeviceCommand,
    observation: Observation,
    timeout_ms: int,
    configuration: RunConfiguration,
) -> None:
    if command.kind not in configuration.capabilities:
        raise ValueError("Unsupported command capability")
    if timeout_ms > configuration.limits.max_command_timeout_ms:
        raise ValueError("Command timeout exceeds run limit")
    points = []
    if isinstance(command, Tap):
        points = [(command.x, command.y)]
    elif isinstance(command, LongPress):
        points = [(command.x, command.y)]
        if command.duration_ms > timeout_ms:
            raise ValueError("Long press duration exceeds command timeout")
    elif isinstance(command, Swipe):
        points = [(command.start_x, command.start_y), (command.end_x, command.end_y)]
        if command.duration_ms > timeout_ms:
            raise ValueError("Swipe duration exceeds command timeout")
    if any(x >= observation.width or y >= observation.height for x, y in points):
        raise ValueError("Coordinates outside source screenshot frame")


def validate_decision(
    decision: AgentDecision,
    run: Run,
    presented_observations: tuple[Observation, ...],
    current_observation_id: str,
    previous_action: Action | None = None,
) -> None:
    """Caller supplies persisted observations actually delivered to the model."""
    if run.state is not RunState.RUNNING or decision.run_id != run.run_id:
        raise ValueError("Decision is not for this running run")
    if decision.identity != run.configuration.identity:
        raise ValueError("Decision model/instruction identity differs from run snapshot")
    current = validate_observations(run, presented_observations, current_observation_id)
    ids = tuple(o.observation_id for o in presented_observations)
    if len(set(ids)) != len(ids) or decision.presented_observation_ids != ids:
        raise ValueError("Decision must record the exact presented evidence")
    if (
        current_observation_id not in ids
        or decision.source_observation_id != current_observation_id
    ):
        raise ValueError("Decision does not reference current observation")
    effect = decision.previous_effect
    if previous_action is None:
        if effect is not None:
            raise ValueError("Initial decision has no previous action")
    elif (
        previous_action.run_id != run.run_id
        or previous_action.observation_id == current_observation_id
        or effect is None
        or effect.action_id != previous_action.action_id
    ):
        raise ValueError("Effect must assess the exact previous action")
    if effect is not None and not set(effect.observation_ids) <= set(ids):
        raise ValueError("Effect cites unpresented evidence")
    if isinstance(decision.next, Act):
        _command_bounds(decision.next.command, current, decision.next.timeout_ms, run.configuration)
    elif isinstance(decision.next, ObserveAfter):
        if decision.next.delay_ms > run.configuration.limits.max_observation_delay_ms:
            raise ValueError("Observation delay exceeds run limit")
    elif isinstance(decision.next, Conclude):
        assessment = decision.next.assessment
        if (
            assessment.run_id != run.run_id
            or assessment.decision_id != decision.decision_id
            or not set(assessment.observation_ids) <= set(ids)
        ):
            raise ValueError("Conclusion scope/evidence mismatch")


def validate_action(
    action: Action,
    decision: AgentDecision,
    observation: Observation,
    lease: DeviceLease,
    configuration: RunConfiguration,
) -> None:
    """Adapter also checks live lease ownership and actual device frame at dispatch."""
    if not isinstance(decision.next, Act):
        raise ValueError("Decision is not an action")
    if (
        action.run_id != decision.run_id
        or action.run_id != observation.run_id
        or action.run_id != lease.run_id
        or action.decision_id != decision.decision_id
        or action.observation_id != decision.source_observation_id
        or action.observation_id != observation.observation_id
        or action.lease_id != lease.lease_id
        or action.lease_id != observation.lease_id
        or observation.device_id != lease.device_id
        or observation.session_id != lease.session_id
        or action.command != decision.next.command
        or action.timeout_ms != decision.next.timeout_ms
    ):
        raise ValueError("Action/decision/source observation/device lease mismatch")
    _command_bounds(action.command, observation, action.timeout_ms, configuration)
