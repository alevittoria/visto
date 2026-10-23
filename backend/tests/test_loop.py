import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from visto.application.context import AgentReply
from visto.application.loop import ContextLimits, RunLoop
from visto.application.ports import OperatorActionRequired, PortError
from visto.application.runtime import MutableRunControl
from visto.domain.commands import CommandKind, Tap
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    ArtifactRef,
    AskUser,
    Assessment,
    CapturedImage,
    Conclude,
    DeviceLease,
    EffectAssessment,
    EffectVerdict,
    Goal,
    ModelIdentity,
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
    Run,
    RunState,
    UserAnswer,
)


class FakeClock:
    def __init__(self):
        self.seconds = 0

    def now(self):
        return datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    async def wait(self, delay_ms, control):
        self.seconds += delay_ms / 1000


class MemoryStore:
    def __init__(self):
        self.runs = {}
        self.records = []

    async def create(self, run):
        assert run.run_id not in self.runs
        self.runs[run.run_id] = run

    async def get(self, run_id):
        return self.runs[run_id]

    async def history(self, run_id):
        return tuple(r for r in self.records if r.run_id == run_id)

    async def append(self, record):
        self.records.append(record)

    async def save(self, run, expected_revision):
        assert self.runs[run.run_id].revision == expected_revision
        self.runs[run.run_id] = run
        return run

    async def finalize(self, run_id, terminal):
        self.runs[run_id] = self.runs[run_id].finish(terminal)
        return self.runs[run_id]


class MemoryArtifacts:
    def __init__(self):
        self.data = {}

    async def put(self, run_id, content, media_type):
        key = str(len(self.data))
        self.data[key] = content
        return ArtifactRef(
            key, run_id, media_type, len(content), hashlib.sha256(content).hexdigest(), key
        )

    async def read(self, reference):
        return self.data[reference.storage_key]


class FakeDevice:
    def __init__(self, clock, store):
        self.clock, self.store = clock, store
        self.leases = 0
        self.active = None
        self.executions = []
        self.observations = 0
        self.status = ReceiptStatus.COMPLETED
        self.fail_capture_after = None
        self.raise_execute = False
        self.after_execute = lambda: None
        self.fail_release = False
        self.fail_acquire = None

    async def acquire(self, run_id, device_id, timeout_ms):
        if self.fail_acquire is not None:
            raise self.fail_acquire
        assert self.active is None
        self.leases += 1
        self.active = DeviceLease(f"lease-{self.leases}", run_id, device_id, "session")
        return self.active

    async def release(self, lease):
        assert lease == self.active
        self.active = None
        if self.fail_release:
            raise PortError("sensitive transport information")

    async def observe(self, lease, timeout_ms):
        if self.fail_capture_after == self.observations:
            raise PortError("sensitive transport information")
        self.observations += 1
        return CapturedImage(
            lease, self.clock.now(), f"frame {self.observations}".encode(), "image/png", 100, 200, 0
        )

    async def execute(self, lease, action, source):
        assert action in self.store.records  # durable intent before mutation
        self.executions.append(action)
        self.after_execute()
        if self.raise_execute:
            raise PortError("dispatch may have happened")
        return TechnicalReceipt(
            action.run_id, action.action_id, self.status, self.clock.now(), self.clock.now()
        )


class ScriptedAgent:
    def __init__(self, script):
        self.script = iter(script)
        self.contexts = []
        self.after_decide = lambda: None

    async def decide(self, context, timeout_ms):
        self.contexts.append(context)
        next_step = next(self.script)
        if isinstance(next_step, Exception):
            raise next_step
        decision_id = f"decision-{len(self.contexts)}"
        ids = tuple(image.observation.observation_id for image in context.images)
        if isinstance(next_step, SemanticVerdict):
            next_step = Conclude(
                Assessment(
                    context.run.run_id,
                    decision_id,
                    next_step,
                    "AI judgement",
                    (context.current_observation_id,),
                )
            )
        effect = None
        if context.previous_action:
            effect = EffectAssessment(
                context.previous_action.action_id,
                EffectVerdict.UNCLEAR,
                "AI assesses prior effect",
                ids,
            )
        decision = AgentDecision(
            decision_id,
            context.run.run_id,
            context.current_observation_id,
            ids,
            next_step,
            "AI rationale",
            "Revised plan",
            context.run.configuration.identity,
            previous_effect=effect,
        )
        self.after_decide()
        return AgentReply(decision)


def make_runner(script, *, limits=None, context_limits=None):
    clock = FakeClock()
    store = MemoryStore()
    control = MutableRunControl()
    device = FakeDevice(clock, store)
    agent = ScriptedAgent(script)
    run = Run(
        "run",
        "device",
        Goal(" Keep original ", ("Do not buy",), "Receipt visible"),
        RunConfiguration(
            limits or RunLimits(60000, 10, 20, 3000, 1000),
            tuple(CommandKind),
            ModelIdentity("fake", "model", "v1"),
            "v1",
        ),
        clock.now(),
        clock.now(),
    )
    loop = RunLoop(
        device,
        agent,
        store,
        MemoryArtifacts(),
        clock,
        control,
        context_limits=context_limits or ContextLimits(),
    )
    return loop, run, device, agent, store, clock, control


@pytest.mark.parametrize("verdict", list(SemanticVerdict))
def test_ai_conclusions_preserve_semantics_and_evidence(verdict):
    loop, run, device, agent, store, _, _ = make_runner(
        [Act(Tap(1, 2), 1000), ObserveAfter(100), verdict]
    )
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, AIConclusion)
    assert result.terminal.assessment.verdict is verdict
    assert result.goal is run.goal
    assert device.active is None
    assert device.observations == 3
    assert len(device.executions) == 1
    assert len([r for r in store.records if isinstance(r, Observation)]) == 3
    assert agent.contexts[-1].previous_receipt.status is ReceiptStatus.COMPLETED


def test_question_answer_resume_reacquires_and_supplies_fresh_image_and_attribution():
    loop, run, device, agent, store, clock, _ = make_runner(
        [AskUser("Which account?"), SemanticVerdict.INCONCLUSIVE]
    )

    async def scenario():
        waiting = await loop.start(run)
        assert waiting.state is RunState.WAITING_FOR_USER
        assert device.active is None
        answer = UserAnswer(
            waiting.pending_question.question_id,
            run.run_id,
            "Synthetic account",
            "user",
            clock.now(),
        )
        answered = await loop.answer(answer)
        assert (await loop.answer(answer)) == answered
        result = await loop.resume(run.run_id)
        assert (await loop.answer(answer)) == result
        with pytest.raises(ValueError):
            await loop.answer(replace(answer, text="conflicting"))
        return result

    result = asyncio.run(scenario())
    assert isinstance(result.terminal, AIConclusion)
    assert device.leases == 2
    assert agent.contexts[0].current_observation_id != agent.contexts[1].current_observation_id
    assert agent.contexts[1].answers[0].text == "Synthetic account"
    assert len([r for r in store.records if isinstance(r, UserAnswer)]) == 1


def test_pause_after_decision_does_not_dispatch_stale_action_on_resume():
    loop, run, device, agent, _, _, control = make_runner(
        [Act(Tap(1, 2), 1000), SemanticVerdict.PASSED]
    )
    agent.after_decide = control.pause

    async def scenario():
        paused = await loop.start(run)
        assert paused.state is RunState.PAUSED
        assert device.active is None
        assert not device.executions
        control.resume()
        agent.after_decide = lambda: None
        return await loop.resume(run.run_id)

    assert isinstance(asyncio.run(scenario()).terminal, AIConclusion)
    assert device.leases == 2
    assert device.observations == 2
    assert not device.executions


@pytest.mark.parametrize("raises", [False, True])
def test_uncertain_mutation_is_never_replayed_and_reaches_ai_as_receipt(raises):
    loop, run, device, agent, store, _, _ = make_runner(
        [Act(Tap(1, 2), 1000), SemanticVerdict.INCONCLUSIVE]
    )
    device.status = ReceiptStatus.UNCERTAIN
    device.raise_execute = raises
    assert isinstance(asyncio.run(loop.start(run)).terminal, AIConclusion)
    assert len(device.executions) == 1
    assert agent.contexts[1].previous_receipt.status is ReceiptStatus.UNCERTAIN
    assert len([r for r in store.records if isinstance(r, TechnicalReceipt)]) == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_provider_failure_and_cancel_are_distinct_and_preserve_capture(cancel):
    loop, run, device, agent, store, _, control = make_runner([PortError("secret")])
    if cancel:
        control.cancel()
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, Cancelled if cancel else InfrastructureFailure)
    assert device.active is None
    if not cancel:
        assert len([r for r in store.records if isinstance(r, Observation)]) == 1
        assert "secret" not in result.terminal.detail
        assert result.terminal.component == "agent"
    else:
        assert not agent.contexts


def test_capture_failure_after_dispatch_preserves_intent_receipt_and_prior_evidence():
    loop, run, device, _, store, _, _ = make_runner([Act(Tap(1, 2), 1000)])
    device.fail_capture_after = 1
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, InfrastructureFailure)
    assert len(result.terminal.observation_ids) == 1
    assert any(isinstance(r, Action) for r in store.records)
    assert any(isinstance(r, TechnicalReceipt) for r in store.records)
    assert device.active is None


def test_infrastructure_failure_logs_component_and_cause_for_the_operator(caplog):
    loop, run, device, _, _, _, _ = make_runner([Act(Tap(1, 2), 1000)])
    device.fail_capture_after = 1
    with caplog.at_level("ERROR", logger="visto.application.loop"):
        result = asyncio.run(loop.start(run))
    assert result.terminal.detail == "Technical operation failed; inspect recorded evidence"
    (record,) = caplog.records
    assert record.getMessage() == "Infrastructure failure in device.observe"
    assert record.exc_info is not None


@pytest.mark.parametrize("budget", [BudgetKind.ACTIONS, BudgetKind.INFERENCES])
def test_count_budget_exhaustion_is_technical(budget):
    limits = RunLimits(
        60000,
        1 if budget is BudgetKind.ACTIONS else 10,
        1 if budget is BudgetKind.INFERENCES else 20,
        3000,
        1000,
    )
    loop, run, device, _, _, _, _ = make_runner(
        [Act(Tap(1, 2), 1000), Act(Tap(1, 2), 1000)], limits=limits
    )
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, BudgetExhausted)
    assert result.terminal.budget is budget
    assert len(device.executions) == 1


def test_wall_budget_continues_during_suspension():
    loop, run, device, _, _, clock, control = make_runner([Act(Tap(1, 2), 1000)])
    control.pause()

    async def scenario():
        assert (await loop.start(run)).state is RunState.PAUSED
        clock.seconds += 61
        control.resume()
        return await loop.resume(run.run_id)

    result = asyncio.run(scenario())
    assert isinstance(result.terminal, BudgetExhausted)
    assert result.terminal.budget is BudgetKind.WALL_TIME
    assert not device.executions


def test_context_is_bounded_without_losing_original_goal_or_action_source():
    loop, run, _, agent, store, _, _ = make_runner(
        [Act(Tap(1, 2), 1000)] + [ObserveAfter(1)] * 8 + [SemanticVerdict.PASSED],
        context_limits=ContextLimits(max_images=2, max_recent_decisions=2),
    )
    assert isinstance(asyncio.run(loop.start(run)).terminal, AIConclusion)
    assert all(len(c.images) <= 2 and len(c.recent_decisions) <= 2 for c in agent.contexts)
    assert all(c.run.goal == run.goal for c in agent.contexts)
    source = agent.contexts[1].previous_action.observation_id
    assert source in [i.observation.observation_id for i in agent.contexts[-1].images]
    assert len([r for r in store.records if isinstance(r, Observation)]) == 10


def test_release_failure_is_surfaced_without_overwriting_terminal():
    loop, run, device, _, store, _, _ = make_runner([SemanticVerdict.PASSED])
    device.fail_release = True
    with pytest.raises(PortError, match="release"):
        asyncio.run(loop.start(run))
    assert isinstance(store.runs[run.run_id].terminal, AIConclusion)


def test_context_overflow_is_explicit_and_preserves_goal_and_evidence():
    loop, run, device, agent, store, _, _ = make_runner(
        [ObserveAfter(1), SemanticVerdict.PASSED],
        context_limits=ContextLimits(max_history_text_chars=1),
    )
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, InfrastructureFailure)
    assert result.terminal.component == "context"
    assert len(agent.contexts) == 1
    assert result.goal is run.goal
    assert len([r for r in store.records if isinstance(r, Observation)]) == 2
    assert device.active is None


def test_unpresented_evidence_cannot_be_persisted_as_ai_conclusion():
    loop, run, device, agent, store, _, _ = make_runner([SemanticVerdict.PASSED])
    original = agent.decide

    async def invalid_decision(context, timeout_ms):
        reply = await original(context, timeout_ms)
        assessment = replace(reply.decision.next.assessment, observation_ids=("invented",))
        return AgentReply(replace(reply.decision, next=Conclude(assessment)))

    agent.decide = invalid_decision
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, InfrastructureFailure)
    assert result.terminal.component == "agent"
    assert not any(isinstance(r, AgentDecision) for r in store.records)
    assert device.active is None


def test_no_device_mutation_after_wall_time_expires_during_inference():
    loop, run, device, agent, _, clock, _ = make_runner([Act(Tap(1, 2), 1000)])
    agent.after_decide = lambda: setattr(clock, "seconds", 61)
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, BudgetExhausted)
    assert result.terminal.budget is BudgetKind.WALL_TIME
    assert not device.executions


def test_action_timeout_records_uncertainty_before_fresh_observation():
    loop, run, device, agent, store, _, _ = make_runner(
        [Act(Tap(1, 2), 1), SemanticVerdict.INCONCLUSIVE]
    )

    async def slow_execute(lease, action, source):
        device.executions.append(action)
        await asyncio.sleep(10)

    device.execute = slow_execute
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, AIConclusion)
    assert len(device.executions) == 1
    assert agent.contexts[1].previous_receipt.status is ReceiptStatus.UNCERTAIN
    assert len([r for r in store.records if isinstance(r, TechnicalReceipt)]) == 1


def test_external_task_cancellation_records_uncertain_receipt_then_terminal():
    loop, run, device, _, store, _, _ = make_runner([Act(Tap(1, 2), 1000)])

    async def scenario():
        dispatched = asyncio.Event()

        async def pending_execute(lease, action, source):
            dispatched.set()
            await asyncio.sleep(10)

        device.execute = pending_execute
        task = asyncio.create_task(loop.start(run))
        await dispatched.wait()
        task.cancel()
        return await task

    result = asyncio.run(scenario())
    assert isinstance(result.terminal, Cancelled)
    receipts = [r for r in store.records if isinstance(r, TechnicalReceipt)]
    assert len(receipts) == 1 and receipts[0].status is ReceiptStatus.UNCERTAIN
    assert device.active is None


def test_resume_in_a_new_process_is_refused_before_acquiring_device():
    loop, run, device, _, _, _, control = make_runner([])
    control.pause()

    async def scenario():
        await loop.start(run)
        loop._sessions.clear()  # emulate loss of live counters/ownership on process restart
        control.resume()
        with pytest.raises(ValueError, match="Interrupted process"):
            await loop.resume(run.run_id)

    asyncio.run(scenario())
    assert not device.leases


def test_system_clock_wait_returns_early_for_control_request():
    from visto.application.runtime import SystemClock

    clock = SystemClock()
    control = MutableRunControl()

    async def scenario():
        task = asyncio.create_task(clock.wait(10_000, control))
        await asyncio.sleep(0)
        control.cancel()
        await asyncio.wait_for(task, 0.5)

    asyncio.run(scenario())


def test_system_clock_ignores_backward_wall_clock_steps(monkeypatch):
    from visto.application import runtime

    first = runtime.SystemClock().now()

    class SteppedBack(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(minutes=1)

    monkeypatch.setattr(runtime, "datetime", SteppedBack)
    second = runtime.SystemClock().now()
    assert first <= second <= runtime.utc_now()
    assert second.tzinfo is UTC
    assert abs((second - datetime.now(UTC)).total_seconds()) < 60


def test_control_cancel_interrupts_pending_inference_and_releases_lease_promptly():
    loop, run, device, agent, _, _, control = make_runner([])

    async def scenario():
        entered = asyncio.Event()

        async def pending_decision(context, timeout_ms):
            entered.set()
            await asyncio.sleep(10)

        agent.decide = pending_decision
        task = asyncio.create_task(loop.start(run))
        await entered.wait()
        control.cancel()
        return await asyncio.wait_for(asyncio.shield(task), 0.5)

    result = asyncio.run(scenario())
    assert isinstance(result.terminal, Cancelled)
    assert result.terminal.source == "user"
    assert device.active is None


def test_context_bound_counts_embedded_question_text():
    loop, run, _, _, _, clock, _ = make_runner(
        [AskUser("x" * 1000), SemanticVerdict.INCONCLUSIVE],
        context_limits=ContextLimits(max_history_text_chars=100),
    )

    async def scenario():
        waiting = await loop.start(run)
        await loop.answer(
            UserAnswer(waiting.pending_question.question_id, run.run_id, "A", "user", clock.now())
        )
        return await loop.resume(run.run_id)

    assert isinstance(asyncio.run(scenario()).terminal, InfrastructureFailure)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("provider: http_401", "provider: http_401"),
        ("provider: refusal", "provider: refusal"),
        *[
            (f"provider: {code}", f"provider: {code}")
            for code in (
                "connection_refused",
                "dns_error",
                "tls_error",
                "connection_error",
                "invalid_json",
                "invalid_request",
                "worker_start_error",
                "worker_protocol_error",
            )
        ],
        (
            "provider: connection_refused proxy=secret",
            "Technical operation failed; inspect recorded evidence",
        ),
        (
            "provider: http_401 token=secret",
            "Technical operation failed; inspect recorded evidence",
        ),
    ],
)
def test_provider_diagnostics_only_expose_exact_safe_codes(message, expected):
    loop, run, _, _, _, _, _ = make_runner([PortError(message)])
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, InfrastructureFailure)
    assert result.terminal.detail == expected


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            OperatorActionRequired("android: export ANDROID_HOME for Appium"),
            "android: export ANDROID_HOME for Appium",
        ),
        (
            PortError("android: remote text"),
            "Technical operation failed; inspect recorded evidence",
        ),
    ],
)
def test_only_operator_action_errors_reach_the_terminal_detail(error, expected):
    loop, run, device, _, _, _, _ = make_runner([])
    device.fail_acquire = error
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, InfrastructureFailure)
    assert result.terminal.component == "device.acquire"
    assert result.terminal.detail == expected


def test_last_allowed_inference_action_still_gets_post_action_evidence():
    loop, run, device, _, store, _, _ = make_runner(
        [Act(Tap(1, 2), 1000)], limits=RunLimits(60000, 10, 1, 3000, 1000)
    )
    result = asyncio.run(loop.start(run))
    assert isinstance(result.terminal, BudgetExhausted)
    assert result.terminal.budget is BudgetKind.INFERENCES
    assert len(device.executions) == 1
    assert len([r for r in store.records if isinstance(r, Observation)]) == 2


@pytest.mark.parametrize("stop", ["cancel", "pause", "deadline"])
def test_stop_after_durable_intent_prevents_dispatch_and_records_rejection(stop):
    loop, run, device, _, store, clock, control = make_runner([Act(Tap(1, 2), 1000)])
    original_append = store.append

    async def interrupt_after_intent(record):
        await original_append(record)
        if isinstance(record, Action):
            if stop == "deadline":
                clock.seconds = 61
            else:
                getattr(control, stop)()

    store.append = interrupt_after_intent
    result = asyncio.run(loop.start(run))
    assert not device.executions
    receipts = [r for r in store.records if isinstance(r, TechnicalReceipt)]
    assert len(receipts) == 1 and receipts[0].status is ReceiptStatus.REJECTED
    if stop == "pause":
        assert result.state is RunState.PAUSED
    elif stop == "cancel":
        assert isinstance(result.terminal, Cancelled)
    else:
        assert isinstance(result.terminal, BudgetExhausted)
        assert result.terminal.budget is BudgetKind.WALL_TIME
    assert device.active is None


@pytest.mark.parametrize(
    ("status", "waited"), [(ReceiptStatus.COMPLETED, 1.5), (ReceiptStatus.REJECTED, 0)]
)
def test_screen_settles_after_dispatched_action_before_next_capture(status, waited):
    loop, run, device, _, _, clock, _ = make_runner([Act(Tap(1, 2), 1000), SemanticVerdict.PASSED])
    device.status = status
    assert isinstance(asyncio.run(loop.start(run)).terminal, AIConclusion)
    assert device.observations == 2
    assert clock.seconds == waited
