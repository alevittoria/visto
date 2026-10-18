"""Immutable run lifecycle; orchestration and atomic storage belong outside it."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from ._validation import instance, integer, items, text, timestamp
from .models import Assessment, Goal, RunConfiguration


@dataclass(frozen=True, slots=True)
class UserAnswer:
    question_id: str
    run_id: str
    text: str = field(repr=False)
    answered_by: str
    answered_at: datetime

    def __post_init__(self) -> None:
        text(self.question_id, self.run_id, self.text, self.answered_by)
        timestamp(self.answered_at)


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    question_id: str
    run_id: str
    decision_id: str
    question: str = field(repr=False)
    created_at: datetime
    answer: UserAnswer | None = None
    cancelled_at: datetime | None = None

    def __post_init__(self) -> None:
        text(self.question_id, self.run_id, self.decision_id, self.question)
        timestamp(self.created_at)
        if self.answer is not None:
            instance(self.answer, UserAnswer)
            if (self.answer.question_id, self.answer.run_id) != (self.question_id, self.run_id):
                raise ValueError("Wrong-run or stale question answer")
            if self.answer.answered_at < self.created_at or self.cancelled_at is not None:
                raise ValueError("Invalid question answer state/time")
        if self.cancelled_at is not None:
            timestamp(self.cancelled_at)
            if self.cancelled_at < self.created_at:
                raise ValueError("Question cancelled before creation")

    def with_answer(self, answer: UserAnswer) -> PendingQuestion:
        instance(answer, UserAnswer)
        if self.answer == answer:
            return self
        if self.answer is not None or self.cancelled_at is not None:
            raise ValueError("Question is already settled")
        return replace(self, answer=answer)


class RunState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_USER = "waiting_for_user"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class AIConclusion:
    run_id: str
    recorded_at: datetime
    assessment: Assessment

    def __post_init__(self) -> None:
        text(self.run_id)
        timestamp(self.recorded_at)
        instance(self.assessment, Assessment)
        if self.assessment.run_id != self.run_id:
            raise ValueError("Assessment belongs to another run")


@dataclass(frozen=True, slots=True)
class InfrastructureFailure:
    run_id: str
    recorded_at: datetime
    component: str
    detail: str = field(repr=False)
    observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text(self.run_id, self.component, self.detail)
        timestamp(self.recorded_at)
        items(self.observation_ids, str)


@dataclass(frozen=True, slots=True)
class Cancelled:
    run_id: str
    recorded_at: datetime
    source: str

    def __post_init__(self) -> None:
        text(self.run_id, self.source)
        timestamp(self.recorded_at)


class BudgetKind(StrEnum):
    WALL_TIME = "wall_time"
    ACTIONS = "actions"
    INFERENCES = "inferences"


@dataclass(frozen=True, slots=True)
class RunUsage:
    elapsed_ms: int
    actions: int
    inferences: int

    def __post_init__(self) -> None:
        integer(self.elapsed_ms, self.actions, self.inferences)


@dataclass(frozen=True, slots=True)
class BudgetExhausted:
    run_id: str
    recorded_at: datetime
    budget: BudgetKind
    usage: RunUsage

    def __post_init__(self) -> None:
        text(self.run_id)
        timestamp(self.recorded_at)
        instance(self.budget, BudgetKind)
        instance(self.usage, RunUsage)


type TerminalRecord = AIConclusion | InfrastructureFailure | Cancelled | BudgetExhausted
TERMINAL_TYPES = (AIConclusion, InfrastructureFailure, Cancelled, BudgetExhausted)


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    device_id: str
    goal: Goal
    configuration: RunConfiguration
    created_at: datetime
    updated_at: datetime
    state: RunState = RunState.CREATED
    revision: int = 0
    pending_question: PendingQuestion | None = None
    terminal: TerminalRecord | None = None

    def __post_init__(self) -> None:
        text(self.run_id, self.device_id)
        instance(self.goal, Goal)
        instance(self.configuration, RunConfiguration)
        instance(self.state, RunState)
        timestamp(self.created_at, self.updated_at)
        integer(self.revision)
        if self.updated_at < self.created_at:
            raise ValueError("Run update precedes creation")
        if (self.state is RunState.TERMINAL) != (self.terminal is not None):
            raise ValueError("Terminal state must have exactly one terminal record")
        if self.terminal is not None:
            instance(self.terminal, TERMINAL_TYPES)
            if self.terminal.run_id != self.run_id or self.terminal.recorded_at != self.updated_at:
                raise ValueError("Terminal scope/time mismatch")
        if self.pending_question is not None:
            instance(self.pending_question, PendingQuestion)
            if self.pending_question.run_id != self.run_id:
                raise ValueError("Question belongs to another run")
            if self.state not in (RunState.WAITING_FOR_USER, RunState.TERMINAL):
                raise ValueError("Pending question requires suspension")
        if self.state is RunState.WAITING_FOR_USER and self.pending_question is None:
            raise ValueError("Missing pending question")

    def _transition(self, state: RunState, at: datetime, **changes: object) -> Run:
        timestamp(at)
        if at < self.updated_at:
            raise ValueError("Transition time moved backwards")
        return replace(self, state=state, updated_at=at, revision=self.revision + 1, **changes)

    def start(self, at: datetime) -> Run:
        if self.state is not RunState.CREATED:
            raise ValueError("Only a created run can start")
        return self._transition(RunState.RUNNING, at)

    def pause(self, at: datetime) -> Run:
        if self.state is RunState.PAUSED:
            return self
        if self.state is not RunState.RUNNING:
            raise ValueError("Only a running run can pause")
        return self._transition(RunState.PAUSED, at)

    def ask(self, question: PendingQuestion, at: datetime) -> Run:
        instance(question, PendingQuestion)
        if self.state is not RunState.RUNNING or question.answer or question.cancelled_at:
            raise ValueError("Cannot ask a settled question or suspend this state")
        timestamp(at)
        if question.created_at > at or question.created_at < self.updated_at:
            raise ValueError("Invalid question creation time")
        return self._transition(RunState.WAITING_FOR_USER, at, pending_question=question)

    def answer(self, answer: UserAnswer) -> Run:
        if self.state is not RunState.WAITING_FOR_USER or self.pending_question is None:
            raise ValueError("No active question for this run")
        settled = self.pending_question.with_answer(answer)
        if settled is self.pending_question:
            return self
        return self._transition(self.state, answer.answered_at, pending_question=settled)

    def resume(self, at: datetime) -> Run:
        """Application must reacquire ownership and freshly observe before dispatch."""
        if self.state is RunState.WAITING_FOR_USER:
            if self.pending_question is None or self.pending_question.answer is None:
                raise ValueError("Question must be answered before resume")
        elif self.state is not RunState.PAUSED:
            raise ValueError("Run is not suspended")
        return self._transition(RunState.RUNNING, at, pending_question=None)

    def finish(self, terminal: TerminalRecord) -> Run:
        """First terminal wins. The store enforces this atomically across writers."""
        instance(terminal, TERMINAL_TYPES)
        if terminal.run_id != self.run_id:
            raise ValueError("Terminal belongs to another run")
        if self.terminal is not None:
            return self
        if isinstance(terminal, AIConclusion) and self.state is not RunState.RUNNING:
            raise ValueError("Only a running agent can conclude")
        question = self.pending_question
        if question and question.answer is None:
            question = replace(question, cancelled_at=terminal.recorded_at)
        return self._transition(
            RunState.TERMINAL, terminal.recorded_at, terminal=terminal, pending_question=question
        )
