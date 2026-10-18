"""One bounded conversation; technical receipts never determine semantic success."""

import asyncio
import logging
from dataclasses import dataclass, fields, is_dataclass
from uuid import uuid4

from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    AskUser,
    Conclude,
    DeviceLease,
    Observation,
    ObserveAfter,
    ReceiptStatus,
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

from .context import AgentContext, AgentReply, PresentedImage
from .ports import Agent, ArtifactStore, Clock, Device, PortError, RunControl, RunStore

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_images: int = 3
    max_recent_decisions: int = 8
    max_image_bytes: int = 24_000_000
    max_history_text_chars: int = 64_000

    def __post_init__(self) -> None:
        for value in (
            self.max_images,
            self.max_recent_decisions,
            self.max_image_bytes,
            self.max_history_text_chars,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("Context limits must be positive integers")
        if self.max_images < 2:
            raise ValueError("Context requires room for pre/post action evidence")


@dataclass(slots=True)
class _Session:
    started: float
    initial_elapsed_ms: int
    actions: int = 0
    inferences: int = 0
    conversation_id: str | None = None


def _text_size(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, tuple):
        return sum(_text_size(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return sum(_text_size(getattr(value, item.name)) for item in fields(value))
    return 0


_SAFE_PROVIDER_ERRORS = {
    "provider: " + code
    for code in (
        "response_size_limit",
        "transport_or_json_error",
        "connection_refused",
        "dns_error",
        "tls_error",
        "connection_error",
        "invalid_json",
        "invalid_request",
        "worker_start_error",
        "worker_protocol_error",
        "identity_mismatch",
        "context_limit",
        "incomplete_or_failed_response",
        "refusal",
        "missing_or_multiple_decisions",
        "timeout",
        "malformed_response",
        "http_400",
        "http_401",
        "http_403",
        "http_404",
        "http_408",
        "http_409",
        "http_413",
        "http_422",
        "http_429",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
    )
}
_DEFAULT_CONTEXT_LIMITS = ContextLimits()
# Screens often animate after a mutation; capturing at once can show a transition.
DEFAULT_SETTLE_MS = 1500


class RunLoop:
    def __init__(
        self,
        device: Device,
        agent: Agent,
        store: RunStore,
        artifacts: ArtifactStore,
        clock: Clock,
        control: RunControl,
        *,
        context_limits: ContextLimits = _DEFAULT_CONTEXT_LIMITS,
        settle_ms: int = DEFAULT_SETTLE_MS,
    ) -> None:
        if type(settle_ms) is not int or settle_ms < 0:
            raise ValueError("Settle delay must be a non-negative integer")
        self.device = device
        self.agent = agent
        self.store = store
        self.artifacts = artifacts
        self.clock = clock
        self.control = control
        self.context_limits = context_limits
        self.settle_ms = settle_ms
        self._sessions: dict[str, _Session] = {}
        self._busy = False

    async def start(self, run: Run) -> Run:
        if self._busy or run.state is not RunState.CREATED:
            raise ValueError("A new idle run is required")
        self._busy = True
        try:
            await self.store.create(run)
            self._sessions[run.run_id] = _Session(
                self.clock.monotonic(),
                max(0, int((self.clock.now() - run.created_at).total_seconds() * 1000)),
            )
            started = run.start(self.clock.now())
            run = await self.store.save(started, run.revision)
            return await self._drive(run)
        finally:
            self._busy = False

    async def resume(self, run_id: str) -> Run:
        if self._busy:
            raise ValueError("Another execution is active")
        self._busy = True
        try:
            run = await self.store.get(run_id)
            if run.state is RunState.TERMINAL:
                return run
            if run_id not in self._sessions:
                raise ValueError("Interrupted process cannot automatically resume a run")
            stopped = await self._stop(run)
            if stopped is not None:
                return stopped
            resumed = run.resume(self.clock.now())
            run = await self.store.save(resumed, run.revision)
            return await self._drive(run)
        finally:
            self._busy = False

    async def answer(self, answer: UserAnswer) -> Run:
        run = await self.store.get(answer.run_id)
        history = await self.store.history(answer.run_id)
        existing = next(
            (
                r
                for r in history
                if isinstance(r, UserAnswer) and r.question_id == answer.question_id
            ),
            None,
        )
        if existing is not None:
            if existing != answer:
                raise ValueError("Conflicting answer to settled question")
            return run
        answered = run.answer(answer)
        await self.store.append(answer)
        return await self.store.save(answered, run.revision)

    def _usage(self, run: Run) -> RunUsage:
        session = self._sessions[run.run_id]
        elapsed = max(
            session.initial_elapsed_ms + int((self.clock.monotonic() - session.started) * 1000),
            int((self.clock.now() - run.created_at).total_seconds() * 1000),
        )
        return RunUsage(max(0, elapsed), session.actions, session.inferences)

    def _remaining(self, run: Run) -> int:
        return max(1, run.configuration.limits.wall_time_ms - self._usage(run).elapsed_ms)

    def _operation_timeout(self, run: Run) -> int:
        return min(self._remaining(run), run.configuration.limits.max_command_timeout_ms)

    async def _stop(self, run: Run, *, inference: bool = False) -> Run | None:
        if self.control.cancel_requested():
            return await self.store.finalize(
                run.run_id, Cancelled(run.run_id, self.clock.now(), "user")
            )
        usage = self._usage(run)
        budget = None
        if usage.elapsed_ms >= run.configuration.limits.wall_time_ms:
            budget = BudgetKind.WALL_TIME
        elif inference and usage.inferences >= run.configuration.limits.max_inferences:
            budget = BudgetKind.INFERENCES
        if budget:
            return await self._budget(run, budget)
        if self.control.pause_requested() and run.state is RunState.RUNNING:
            return await self.store.save(run.pause(self.clock.now()), run.revision)
        return None

    async def _budget(self, run: Run, kind: BudgetKind) -> Run:
        return await self.store.finalize(
            run.run_id, BudgetExhausted(run.run_id, self.clock.now(), kind, self._usage(run))
        )

    async def _capture(self, run: Run, lease: DeviceLease) -> Observation:
        timeout = self._operation_timeout(run)
        captured = await asyncio.wait_for(self.device.observe(lease, timeout), timeout / 1000)
        if captured.lease != lease:
            raise ValueError("Capture has different ownership")
        reference = await self.artifacts.put(run.run_id, captured.content, captured.media_type)
        history = await self.store.history(run.run_id)
        sequence = 1 + max((r.sequence for r in history if isinstance(r, Observation)), default=0)
        observation = Observation(
            uuid4().hex,
            run.run_id,
            sequence,
            captured.captured_at,
            lease.device_id,
            lease.session_id,
            lease.lease_id,
            reference,
            captured.width,
            captured.height,
            captured.rotation,
        )
        # Hash verification precedes the durable observation record.
        PresentedImage(observation, captured.content)
        await self.store.append(observation)
        return observation

    async def _context(self, run: Run, current: Observation) -> AgentContext:
        history = await self.store.history(run.run_id)
        observations = [r for r in history if isinstance(r, Observation)]
        receipts = [r for r in history if isinstance(r, TechnicalReceipt)]
        previous_receipt = receipts[-1] if receipts else None
        previous_action = next(
            (
                r
                for r in history
                if isinstance(r, Action)
                and previous_receipt is not None
                and r.action_id == previous_receipt.action_id
            ),
            None,
        )
        required = {current.observation_id}
        if previous_action:
            required.add(previous_action.observation_id)
        selected = [o for o in observations if o.observation_id in required]
        for observation in reversed(observations):
            if len(selected) >= self.context_limits.max_images:
                break
            if observation not in selected:
                selected.append(observation)
        selected.sort(key=lambda o: o.sequence)
        if sum(o.screenshot.byte_length for o in selected) > self.context_limits.max_image_bytes:
            raise ValueError("Evidence exceeds context byte limit")
        decisions = tuple(r for r in history if isinstance(r, AgentDecision))
        recent = decisions[-self.context_limits.max_recent_decisions :]
        answers = tuple(r for r in history if isinstance(r, UserAnswer))
        plan = decisions[-1].working_plan if decisions else ""
        text_size = _text_size((plan, recent, answers, previous_action, previous_receipt))
        if text_size > self.context_limits.max_history_text_chars:
            raise ValueError("Attributed history exceeds context text limit")
        images = tuple(
            [PresentedImage(o, await self.artifacts.read(o.screenshot)) for o in selected]
        )
        return AgentContext(
            run,
            images,
            current.observation_id,
            previous_action,
            previous_receipt,
            plan,
            recent,
            answers,
            self._sessions[run.run_id].conversation_id,
        )

    async def _decide(self, context: AgentContext, timeout: int) -> AgentReply | None:
        task = asyncio.create_task(self.agent.decide(context, timeout))
        try:
            async with asyncio.timeout(timeout / 1000):
                while True:
                    done, _ = await asyncio.wait({task}, timeout=0.05)
                    if done:
                        return task.result()
                    if self.control.cancel_requested() or self.control.pause_requested():
                        return None
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _execute(
        self, run: Run, lease: DeviceLease, decision: AgentDecision, source: Observation
    ) -> ReceiptStatus:
        assert isinstance(decision.next, Act)
        action = Action(
            uuid4().hex,
            run.run_id,
            decision.decision_id,
            source.observation_id,
            lease.lease_id,
            decision.next.command,
            decision.next.timeout_ms,
        )
        validate_action(action, decision, source, lease, run.configuration)
        await self.store.append(action)
        self._sessions[run.run_id].actions += 1
        dispatched_at = self.clock.now()
        if (
            self.control.cancel_requested()
            or self.control.pause_requested()
            or self._usage(run).elapsed_ms >= run.configuration.limits.wall_time_ms
        ):
            await self.store.append(
                TechnicalReceipt(
                    run.run_id,
                    action.action_id,
                    ReceiptStatus.REJECTED,
                    dispatched_at,
                    self.clock.now(),
                    detail="Command blocked before dispatch",
                )
            )
            return ReceiptStatus.REJECTED
        cancelled = False
        try:
            receipt = await asyncio.wait_for(
                self.device.execute(lease, action, source),
                min(action.timeout_ms, self._remaining(run)) / 1000,
            )
            if (receipt.run_id, receipt.action_id) != (run.run_id, action.action_id):
                raise ValueError("Execution receipt has different scope")
            if receipt.dispatched_at < dispatched_at or receipt.finished_at > self.clock.now():
                raise ValueError("Execution receipt has invalid timing")
        except (Exception, asyncio.CancelledError) as error:
            cancelled = isinstance(error, asyncio.CancelledError)
            receipt = TechnicalReceipt(
                run.run_id,
                action.action_id,
                ReceiptStatus.UNCERTAIN,
                dispatched_at,
                self.clock.now(),
                detail="Execution outcome is uncertain; observe again",
            )
        await self.store.append(receipt)
        if cancelled:
            raise asyncio.CancelledError
        return receipt.status

    async def _drive(self, run: Run) -> Run:
        lease = None
        component = "device.acquire"
        try:
            stopped = await self._stop(run)
            if stopped:
                return stopped
            timeout = self._operation_timeout(run)
            lease = await asyncio.wait_for(
                self.device.acquire(run.run_id, run.device_id, timeout), timeout / 1000
            )
            if (lease.run_id, lease.device_id) != (run.run_id, run.device_id):
                raise ValueError("Acquired lease has different scope")
            while True:
                stopped = await self._stop(run)
                if stopped:
                    return stopped
                component = "device.observe"
                current = await self._capture(run, lease)
                stopped = await self._stop(run, inference=True)
                if stopped:
                    return stopped
                component = "context"
                context = await self._context(run, current)
                component = "agent"
                self._sessions[run.run_id].inferences += 1
                timeout = self._remaining(run)
                reply = await self._decide(context, timeout)
                if reply is None:
                    stopped = await self._stop(run)
                    if stopped:
                        return stopped
                    continue
                decision = reply.decision
                validate_decision(
                    decision,
                    run,
                    tuple(i.observation for i in context.images),
                    current.observation_id,
                    context.previous_action,
                )
                component = "storage"
                await self.store.append(decision)
                self._sessions[run.run_id].conversation_id = reply.conversation_id
                stopped = await self._stop(run)
                if stopped:
                    return stopped
                if isinstance(decision.next, Conclude):
                    return await self.store.finalize(
                        run.run_id,
                        AIConclusion(run.run_id, self.clock.now(), decision.next.assessment),
                    )
                if isinstance(decision.next, AskUser):
                    question = PendingQuestion(
                        uuid4().hex,
                        run.run_id,
                        decision.decision_id,
                        decision.next.question,
                        self.clock.now(),
                    )
                    await self.store.append(question)
                    return await self.store.save(run.ask(question, self.clock.now()), run.revision)
                if isinstance(decision.next, Act):
                    if self._usage(run).actions >= run.configuration.limits.max_actions:
                        return await self._budget(run, BudgetKind.ACTIONS)
                    component = "device.execute"
                    status = await self._execute(run, lease, decision, current)
                    delay = min(self.settle_ms, self._remaining(run))
                    if status is not ReceiptStatus.REJECTED and delay > 0:
                        component = "clock"
                        await asyncio.wait_for(
                            self.clock.wait(delay, self.control), delay / 1000 + 0.1
                        )
                elif isinstance(decision.next, ObserveAfter):
                    component = "clock"
                    delay = min(decision.next.delay_ms, self._remaining(run))
                    await asyncio.wait_for(self.clock.wait(delay, self.control), delay / 1000 + 0.1)
        except asyncio.CancelledError:
            return await self.store.finalize(
                run.run_id, Cancelled(run.run_id, self.clock.now(), "task")
            )
        except Exception as error:
            # Operator diagnostics only: the terminal detail stays generic and sanitized.
            _LOG.error("Infrastructure failure in %s", component, exc_info=error)
            stopped = await self._stop(run)
            if stopped:
                return stopped
            history = await self.store.history(run.run_id)
            ids = tuple(r.observation_id for r in history if isinstance(r, Observation))
            detail = "Technical operation failed; inspect recorded evidence"
            if component == "agent" and isinstance(error, PortError):
                if str(error) in _SAFE_PROVIDER_ERRORS:
                    detail = str(error)
            return await self.store.finalize(
                run.run_id,
                InfrastructureFailure(
                    run.run_id,
                    self.clock.now(),
                    component,
                    detail,
                    ids,
                ),
            )
        finally:
            if lease is not None:
                try:
                    await asyncio.wait_for(
                        self.device.release(lease),
                        run.configuration.limits.max_command_timeout_ms / 1000,
                    )
                except Exception:
                    raise PortError("Device lease release failed") from None
