"""Already-resolved evidence for one bounded logical agent conversation."""

import hashlib
from dataclasses import dataclass, field

from visto.domain._validation import instance, items, text
from visto.domain.models import Action, AgentDecision, Observation, TechnicalReceipt
from visto.domain.run import Run, UserAnswer
from visto.domain.validation import validate_observations


@dataclass(frozen=True, slots=True)
class PresentedImage:
    observation: Observation
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        instance(self.observation, Observation)
        artifact = self.observation.screenshot
        if (
            type(self.content) is not bytes
            or len(self.content) != artifact.byte_length
            or hashlib.sha256(self.content).hexdigest() != artifact.sha256
        ):
            raise ValueError("Presented image differs from stored artifact")


@dataclass(frozen=True, slots=True)
class AgentContext:
    run: Run
    images: tuple[PresentedImage, ...]
    current_observation_id: str
    previous_action: Action | None = None
    previous_receipt: TechnicalReceipt | None = None
    working_plan: str = field(default="", repr=False)
    recent_decisions: tuple[AgentDecision, ...] = ()
    answers: tuple[UserAnswer, ...] = ()
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        instance(self.run, Run)
        items(self.images, PresentedImage, nonempty=True)
        text(self.current_observation_id)
        text(self.working_plan, allow_empty=True)
        items(self.recent_decisions, AgentDecision)
        items(self.answers, UserAnswer)
        if self.conversation_id is not None:
            text(self.conversation_id)
        observations = tuple(image.observation for image in self.images)
        current = validate_observations(self.run, observations, self.current_observation_id)
        if (self.previous_action is None) != (self.previous_receipt is None):
            raise ValueError("Previous action and receipt must be supplied together")
        if self.previous_action is not None:
            instance(self.previous_action, Action)
            instance(self.previous_receipt, TechnicalReceipt)
            if (
                self.previous_action.run_id != self.run.run_id
                or self.previous_receipt.run_id != self.run.run_id
                or self.previous_action.action_id != self.previous_receipt.action_id
                or self.previous_action.observation_id == current.observation_id
                or current.captured_at < self.previous_receipt.finished_at
            ):
                raise ValueError("Previous action/receipt scope mismatch")
        if any(
            value.run_id != self.run.run_id for value in (*self.recent_decisions, *self.answers)
        ):
            raise ValueError("Context history belongs to another run")


@dataclass(frozen=True, slots=True)
class AgentReply:
    decision: AgentDecision
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        instance(self.decision, AgentDecision)
        if self.conversation_id is not None:
            text(self.conversation_id)
