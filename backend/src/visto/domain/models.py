"""Immutable request, screenshot evidence and conversational decision values."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ._validation import geometry, instance, integer, items, text, timestamp
from .commands import COMMAND_TYPES, CommandKind, DeviceCommand


@dataclass(frozen=True, slots=True)
class Goal:
    text: str = field(repr=False)
    constraints: tuple[str, ...] = field(default=(), repr=False)
    expected_result: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        text(self.text)
        items(self.constraints, str)
        if self.expected_result is not None:
            text(self.expected_result)


@dataclass(frozen=True, slots=True)
class RunLimits:
    wall_time_ms: int
    max_actions: int
    max_inferences: int
    max_command_timeout_ms: int
    max_observation_delay_ms: int

    def __post_init__(self) -> None:
        integer(
            self.wall_time_ms,
            self.max_actions,
            self.max_inferences,
            self.max_command_timeout_ms,
            self.max_observation_delay_ms,
            minimum=1,
        )


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider: str
    model: str
    instruction_version: str

    def __post_init__(self) -> None:
        text(self.provider, self.model, self.instruction_version)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (self.input_tokens, self.output_tokens):
            if value is not None:
                integer(value)


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    limits: RunLimits
    capabilities: tuple[CommandKind, ...]
    identity: ModelIdentity
    device_adapter_version: str

    def __post_init__(self) -> None:
        instance(self.limits, RunLimits)
        items(self.capabilities, CommandKind)
        instance(self.identity, ModelIdentity)
        text(self.device_adapter_version)
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Duplicate capability")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    run_id: str
    media_type: str
    byte_length: int
    sha256: str
    storage_key: str

    def __post_init__(self) -> None:
        text(self.artifact_id, self.run_id, self.storage_key, self.media_type, self.sha256)
        integer(self.byte_length, minimum=1)
        if self.media_type not in ("image/png", "image/jpeg"):
            raise ValueError("Unsupported screenshot media type")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Expected lowercase SHA256 digest")


@dataclass(frozen=True, slots=True)
class DeviceLease:
    lease_id: str
    run_id: str
    device_id: str
    session_id: str

    def __post_init__(self) -> None:
        text(self.lease_id, self.run_id, self.device_id, self.session_id)


@dataclass(frozen=True, slots=True)
class CapturedImage:
    """Unpersisted bytes captured under the supplied exclusive lease."""

    lease: DeviceLease
    captured_at: datetime
    content: bytes = field(repr=False)
    media_type: str
    width: int
    height: int
    rotation: int

    def __post_init__(self) -> None:
        instance(self.lease, DeviceLease)
        timestamp(self.captured_at)
        if type(self.content) is not bytes or not self.content:
            raise ValueError("Missing image bytes")
        if self.media_type not in ("image/png", "image/jpeg"):
            raise ValueError("Unsupported screenshot media type")
        geometry(self.width, self.height, self.rotation)


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    run_id: str
    sequence: int
    captured_at: datetime
    device_id: str
    session_id: str
    lease_id: str
    screenshot: ArtifactRef
    width: int
    height: int
    rotation: int

    def __post_init__(self) -> None:
        text(self.observation_id, self.run_id, self.device_id, self.session_id, self.lease_id)
        integer(self.sequence, minimum=1)
        timestamp(self.captured_at)
        instance(self.screenshot, ArtifactRef)
        geometry(self.width, self.height, self.rotation)
        if self.screenshot.run_id != self.run_id:
            raise ValueError("Artifact belongs to another run")


@dataclass(frozen=True, slots=True)
class Action:
    action_id: str
    run_id: str
    decision_id: str
    observation_id: str
    lease_id: str
    command: DeviceCommand
    timeout_ms: int

    def __post_init__(self) -> None:
        text(self.action_id, self.run_id, self.decision_id, self.observation_id, self.lease_id)
        instance(self.command, COMMAND_TYPES)
        integer(self.timeout_ms, minimum=1)


class ReceiptStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    ERROR = "error"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class TechnicalReceipt:
    """COMPLETED is transport execution, never an application verdict."""

    run_id: str
    action_id: str
    status: ReceiptStatus
    dispatched_at: datetime
    finished_at: datetime
    started_at: datetime | None = None
    detail: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        text(self.run_id, self.action_id)
        text(self.detail, allow_empty=True)
        instance(self.status, ReceiptStatus)
        timestamp(self.dispatched_at, self.finished_at)
        if self.finished_at < self.dispatched_at:
            raise ValueError("Receipt ends before dispatch")
        if self.started_at is not None:
            timestamp(self.started_at)
            if not self.dispatched_at <= self.started_at <= self.finished_at:
                raise ValueError("Invalid receipt start time")


class SemanticVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class EffectVerdict(StrEnum):
    ACHIEVED = "achieved"
    NOT_ACHIEVED = "not_achieved"
    UNCLEAR = "unclear"


@dataclass(frozen=True, slots=True)
class EffectAssessment:
    action_id: str
    verdict: EffectVerdict
    explanation: str = field(repr=False)
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        text(self.action_id, self.explanation)
        instance(self.verdict, EffectVerdict)
        items(self.observation_ids, str, nonempty=True)


@dataclass(frozen=True, slots=True)
class Assessment:
    run_id: str
    decision_id: str
    verdict: SemanticVerdict
    explanation: str = field(repr=False)
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        text(self.run_id, self.decision_id, self.explanation)
        instance(self.verdict, SemanticVerdict)
        items(self.observation_ids, str, nonempty=True)


@dataclass(frozen=True, slots=True)
class Act:
    command: DeviceCommand
    timeout_ms: int

    def __post_init__(self) -> None:
        instance(self.command, COMMAND_TYPES)
        integer(self.timeout_ms, minimum=1)


@dataclass(frozen=True, slots=True)
class ObserveAfter:
    delay_ms: int

    def __post_init__(self) -> None:
        integer(self.delay_ms, minimum=1)


@dataclass(frozen=True, slots=True)
class AskUser:
    question: str = field(repr=False)

    def __post_init__(self) -> None:
        text(self.question)


@dataclass(frozen=True, slots=True)
class Conclude:
    assessment: Assessment

    def __post_init__(self) -> None:
        instance(self.assessment, Assessment)


type NextDecision = Act | ObserveAfter | AskUser | Conclude


@dataclass(frozen=True, slots=True)
class AgentDecision:
    decision_id: str
    run_id: str
    source_observation_id: str
    presented_observation_ids: tuple[str, ...]
    next: NextDecision
    rationale: str = field(repr=False)
    working_plan: str = field(repr=False)
    identity: ModelIdentity
    usage: ModelUsage = ModelUsage()
    previous_effect: EffectAssessment | None = None

    def __post_init__(self) -> None:
        text(self.decision_id, self.run_id, self.source_observation_id, self.rationale)
        text(self.working_plan, allow_empty=True)
        items(self.presented_observation_ids, str, nonempty=True)
        if len(set(self.presented_observation_ids)) != len(self.presented_observation_ids):
            raise ValueError("Duplicate presented observation")
        instance(self.next, (Act, ObserveAfter, AskUser, Conclude))
        instance(self.identity, ModelIdentity)
        instance(self.usage, ModelUsage)
        if self.previous_effect is not None:
            instance(self.previous_effect, EffectAssessment)
