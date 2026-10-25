"""Transactional run metadata; no device commands or semantic interpretation."""

import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from visto.application.ports import ArtifactStore, PortError, RunRecord
from visto.domain.models import (
    Action,
    AgentDecision,
    AskUser,
    Conclude,
    DeviceLease,
    Observation,
    TechnicalReceipt,
)
from visto.domain.run import (
    AIConclusion,
    InfrastructureFailure,
    PendingQuestion,
    Run,
    RunState,
    TerminalRecord,
    UserAnswer,
)
from visto.domain.validation import validate_action, validate_decision
from visto.home import make_private_dir

from .codec import dumps, loads
from .migrations import SchemaTooNew, migrate


class SQLiteRunStore:
    def __init__(self, database: Path, artifacts: ArtifactStore) -> None:
        self.database = Path(database).resolve()
        self.artifacts = artifacts
        try:
            make_private_dir(self.database.parent)
            migrate(self.database)
        except SchemaTooNew:
            raise PortError("storage: database is newer than this Visto") from None
        except (OSError, sqlite3.Error, ValueError):
            raise PortError("storage: initialization failed") from None

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.database, timeout=5, autocommit=True)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    async def _call[T](self, operation: Callable[[], T]) -> T:
        try:
            return await asyncio.to_thread(operation)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RecursionError):
            raise PortError("storage: operation rejected or persistence unavailable") from None

    @staticmethod
    def _get(connection: sqlite3.Connection, run_id: str) -> Run:
        row = connection.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        result = loads(row[0])
        if not isinstance(result, Run) or result.run_id != run_id:
            raise ValueError("Invalid stored run")
        return result

    @staticmethod
    def _history(connection: sqlite3.Connection, run_id: str) -> tuple[RunRecord, ...]:
        rows = connection.execute(
            "SELECT payload FROM records WHERE run_id=? ORDER BY position", (run_id,)
        ).fetchall()
        records = tuple(loads(row[0]) for row in rows)
        if any(
            not isinstance(
                record,
                (Observation, AgentDecision, Action, TechnicalReceipt, PendingQuestion, UserAnswer),
            )
            or record.run_id != run_id
            for record in records
        ):
            raise ValueError("Invalid stored history")
        return records

    async def create(self, run: Run) -> None:
        def operation():
            if run.state is not RunState.CREATED or run.revision != 0:
                raise ValueError("Initial run required")
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT payload FROM runs WHERE run_id=?", (run.run_id,)
                ).fetchone()
                if existing is not None:
                    if loads(existing[0]) != run:
                        raise ValueError("Run ID conflict")
                    return
                connection.execute("INSERT INTO runs VALUES (?, ?)", (run.run_id, dumps(run)))

        await self._call(operation)

    async def get(self, run_id: str) -> Run:
        def operation():
            with self._transaction() as connection:
                return self._get(connection, run_id)

        return await self._call(operation)

    async def history(self, run_id: str) -> tuple[RunRecord, ...]:
        def operation():
            with self._transaction() as connection:
                self._get(connection, run_id)
                return self._history(connection, run_id)

        return await self._call(operation)

    @staticmethod
    def _key(record: RunRecord) -> tuple[str, str]:
        match record:
            case Observation():
                key = record.observation_id
            case AgentDecision():
                key = record.decision_id
            case Action():
                key = record.action_id
            case TechnicalReceipt():
                key = record.action_id
            case PendingQuestion() | UserAnswer():
                key = record.question_id
            case _:
                raise ValueError("Unsupported record")
        return type(record).__name__, key

    @staticmethod
    def _validate_record(record: RunRecord, run: Run, history: tuple[RunRecord, ...]) -> None:
        if run.state is RunState.TERMINAL:
            raise ValueError("Run already terminal")
        if isinstance(record, (Observation, AgentDecision, Action, PendingQuestion)):
            if run.state is not RunState.RUNNING:
                raise ValueError("Active execution record requires a running run")
        observations = {
            item.observation_id: item for item in history if isinstance(item, Observation)
        }
        decisions = {item.decision_id: item for item in history if isinstance(item, AgentDecision)}
        actions = {item.action_id: item for item in history if isinstance(item, Action)}
        match record:
            case Observation():
                previous = tuple(observations.values())
                if (
                    record.device_id != run.device_id
                    or record.sequence != len(previous) + 1
                    or record.captured_at < run.updated_at
                    or any(item.captured_at > record.captured_at for item in previous)
                ):
                    raise ValueError("Observation sequence/device/time mismatch")
            case AgentDecision():
                if record.source_observation_id != next(reversed(observations), None):
                    raise ValueError("Decision must use the latest frame")
                presented = tuple(observations[key] for key in record.presented_observation_ids)
                previous_action = next(reversed(actions.values()), None)
                if previous_action is not None:
                    receipt = next(
                        (
                            item
                            for item in history
                            if isinstance(item, TechnicalReceipt)
                            and item.action_id == previous_action.action_id
                        ),
                        None,
                    )
                    current = observations[record.source_observation_id]
                    if (
                        receipt is None
                        or receipt.run_id != run.run_id
                        or current.observation_id == previous_action.observation_id
                        or current.captured_at < receipt.finished_at
                    ):
                        raise ValueError("Decision requires settled action and fresh evidence")
                validate_decision(
                    record, run, presented, record.source_observation_id, previous_action
                )
            case Action():
                observation = observations[record.observation_id]
                decision = decisions[record.decision_id]
                if record.decision_id != next(
                    reversed(decisions), None
                ) or record.observation_id != next(reversed(observations), None):
                    raise ValueError("Action intent must use the latest decision/frame")
                if any(item.decision_id == decision.decision_id for item in actions.values()):
                    raise ValueError("Decision already has an action")
                receipts = {
                    item.action_id for item in history if isinstance(item, TechnicalReceipt)
                }
                if set(actions) - receipts:
                    raise ValueError("Previous command outcome unresolved")
                validate_action(
                    record,
                    decision,
                    observation,
                    DeviceLease(
                        observation.lease_id, run.run_id, run.device_id, observation.session_id
                    ),
                    run.configuration,
                )
            case TechnicalReceipt():
                action = actions[record.action_id]
                if record.dispatched_at < observations[action.observation_id].captured_at:
                    raise ValueError("Receipt precedes source frame")
            case PendingQuestion():
                decision = decisions[record.decision_id]
                if (
                    not isinstance(decision.next, AskUser)
                    or record.question != decision.next.question
                    or record.answer is not None
                    or record.cancelled_at is not None
                    or record.created_at < run.updated_at
                ):
                    raise ValueError("Question mismatch")
            case UserAnswer():
                question = next(
                    (
                        item
                        for item in history
                        if isinstance(item, PendingQuestion)
                        and item.question_id == record.question_id
                    ),
                    None,
                )
                if (
                    run.pending_question is None
                    or run.pending_question.question_id != record.question_id
                    or question is None
                ):
                    raise ValueError("No active question")
                question.with_answer(record)

    @classmethod
    def _append(cls, connection: sqlite3.Connection, record: RunRecord) -> None:
        kind, key = cls._key(record)
        run = cls._get(connection, record.run_id)
        payload = dumps(record)
        existing = connection.execute(
            "SELECT payload FROM records WHERE run_id=? AND kind=? AND record_id=?",
            (record.run_id, kind, key),
        ).fetchone()
        if existing is not None:
            if existing[0] != payload:
                raise ValueError("Conflicting history record")
            return
        cls._validate_record(record, run, cls._history(connection, run.run_id))
        connection.execute(
            "INSERT INTO records(run_id,kind,record_id,payload) VALUES (?,?,?,?)",
            (record.run_id, kind, key, payload),
        )

    async def append(self, record: RunRecord) -> None:
        if isinstance(record, Observation):
            await self.artifacts.read(record.screenshot)

        def operation():
            with self._transaction() as connection:
                self._append(connection, record)

        await self._call(operation)

    async def save(self, run: Run, expected_revision: int) -> Run:
        def operation():
            with self._transaction() as connection:
                current = self._get(connection, run.run_id)
                if (
                    type(expected_revision) is not int
                    or current.revision != expected_revision
                    or current.terminal is not None
                    or run.terminal is not None
                    or (current.goal, current.configuration, current.device_id, current.created_at)
                    != (run.goal, run.configuration, run.device_id, run.created_at)
                    or run.revision != current.revision + 1
                ):
                    raise ValueError("Lifecycle CAS conflict")
                history = self._history(connection, run.run_id)
                match current.state, run.state:
                    case RunState.CREATED, RunState.RUNNING:
                        expected = current.start(run.updated_at)
                    case RunState.RUNNING, RunState.PAUSED:
                        expected = current.pause(run.updated_at)
                    case RunState.RUNNING, RunState.WAITING_FOR_USER:
                        if run.pending_question not in history:
                            raise ValueError("Question not durable")
                        expected = current.ask(run.pending_question, run.updated_at)
                    case RunState.WAITING_FOR_USER, RunState.WAITING_FOR_USER:
                        answer = run.pending_question.answer if run.pending_question else None
                        if answer not in history:
                            raise ValueError("Answer not durable")
                        expected = current.answer(answer)
                    case ((RunState.PAUSED | RunState.WAITING_FOR_USER), RunState.RUNNING):
                        expected = current.resume(run.updated_at)
                    case _:
                        raise ValueError("Unsupported transition")
                if expected != run:
                    raise ValueError("Lifecycle mismatch")
                connection.execute(
                    "UPDATE runs SET payload=? WHERE run_id=?", (dumps(run), run.run_id)
                )
                return run

        return await self._call(operation)

    @classmethod
    def _finalize(
        cls, connection: sqlite3.Connection, run_id: str, terminal: TerminalRecord
    ) -> Run:
        run = cls._get(connection, run_id)
        if terminal.run_id != run_id:
            raise ValueError("Wrong-run terminal")
        if run.terminal is not None:
            return run
        history = cls._history(connection, run_id)
        observations = {item.observation_id for item in history if isinstance(item, Observation)}
        if isinstance(terminal, AIConclusion):
            assessment = terminal.assessment
            decision = next(
                (
                    item
                    for item in history
                    if isinstance(item, AgentDecision)
                    and item.decision_id == assessment.decision_id
                ),
                None,
            )
            if (
                decision is None
                or not isinstance(decision.next, Conclude)
                or decision.next.assessment != assessment
                or decision
                != next(
                    (item for item in reversed(history) if isinstance(item, AgentDecision)), None
                )
                or not set(assessment.observation_ids) <= observations
            ):
                raise ValueError("Conclusion lacks persisted decision/evidence")
        if isinstance(terminal, InfrastructureFailure):
            if not set(terminal.observation_ids) <= observations:
                raise ValueError("Failure cites missing observations")
        finished = run.finish(terminal)
        connection.execute("INSERT INTO terminals VALUES (?, ?)", (run_id, dumps(terminal)))
        connection.execute("UPDATE runs SET payload=? WHERE run_id=?", (dumps(finished), run_id))
        return finished

    async def finalize(self, run_id: str, terminal: TerminalRecord) -> Run:
        def operation():
            with self._transaction() as connection:
                return self._finalize(connection, run_id, terminal)

        return await self._call(operation)

    async def delete(self, run_id: str) -> bool:
        """Remove one run with its history and terminal; caller ensures no active owner."""

        def operation():
            with self._transaction() as connection:
                connection.execute("DELETE FROM records WHERE run_id=?", (run_id,))
                connection.execute("DELETE FROM terminals WHERE run_id=?", (run_id,))
                return connection.execute("DELETE FROM runs WHERE run_id=?", (run_id,)).rowcount > 0

        return await self._call(operation)

    async def token_usage(self, run_id: str | None = None) -> dict[str, tuple[int, int, int, int]]:
        """Per run: (input tokens, output tokens, decisions, decisions with unknown usage)."""

        def operation():
            usage = "$.value.fields.usage.fields."
            with self._transaction() as connection:
                rows = connection.execute(
                    "SELECT run_id, "
                    f"COALESCE(SUM(json_extract(payload, '{usage}input_tokens')), 0), "
                    f"COALESCE(SUM(json_extract(payload, '{usage}output_tokens')), 0), "
                    "COUNT(*), "
                    f"SUM(json_extract(payload, '{usage}input_tokens') IS NULL "
                    f"OR json_extract(payload, '{usage}output_tokens') IS NULL) "
                    "FROM records WHERE kind='AgentDecision' AND (?1 IS NULL OR run_id=?1) "
                    "GROUP BY run_id",
                    (run_id,),
                ).fetchall()
            return {row[0]: (int(row[1]), int(row[2]), int(row[3]), int(row[4])) for row in rows}

        return await self._call(operation)

    async def action_counts(self) -> dict[str, int]:
        """Per run: persisted device actions (dispatched or attempted), any receipt status."""

        def operation():
            with self._transaction() as connection:
                rows = connection.execute(
                    "SELECT run_id, COUNT(*) FROM records WHERE kind='Action' GROUP BY run_id"
                ).fetchall()
            return {row[0]: int(row[1]) for row in rows}

        return await self._call(operation)
