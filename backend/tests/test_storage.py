import asyncio
import shutil
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.ports import PortError
from visto.domain.commands import CommandKind, Tap
from visto.domain.models import (
    Act,
    Action,
    AgentDecision,
    AskUser,
    Assessment,
    Conclude,
    EffectAssessment,
    EffectVerdict,
    Goal,
    ModelIdentity,
    Observation,
    ReceiptStatus,
    RunConfiguration,
    RunLimits,
    SemanticVerdict,
    TechnicalReceipt,
)
from visto.domain.run import (
    AIConclusion,
    Cancelled,
    PendingQuestion,
    Run,
    RunState,
    UserAnswer,
)

NOW = datetime(2026, 10, 16, tzinfo=UTC)


@pytest.fixture
def tmp_path():
    # Pytest's mode=0700 temp directories are inaccessible in this managed Windows
    # sandbox. Ordinary workspace directories retain its inherited access rules.
    root = Path(__file__).resolve().parents[2] / ".work" / "storage-tests"
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ValueError("Refusing cleanup outside the storage test root")
    shutil.rmtree(resolved)


def initial():
    return Run(
        "run-1",
        "serial",
        Goal("  original  ", ("no purchases",), "visible"),
        RunConfiguration(
            RunLimits(60000, 10, 20, 5000, 2000),
            tuple(CommandKind),
            ModelIdentity("provider", "model", "prompt-v1"),
            "android-v1",
        ),
        NOW,
        NOW,
    )


async def setup(tmp_path):
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    store = SQLiteRunStore(tmp_path / "runs.sqlite", artifacts)
    run = initial()
    await store.create(run)
    run = await store.save(run.start(NOW), 0)
    ref = await artifacts.put(run.run_id, b"image", "image/png")
    obs = Observation("obs-1", run.run_id, 1, NOW, "serial", "session", "lease", ref, 100, 200, 0)
    await store.append(obs)
    decision = AgentDecision(
        "decision-1",
        run.run_id,
        obs.observation_id,
        (obs.observation_id,),
        Act(Tap(1, 2), 1000),
        "go",
        "plan",
        run.configuration.identity,
    )
    action = Action(
        "action-1", run.run_id, decision.decision_id, obs.observation_id, "lease", Tap(1, 2), 1000
    )
    return artifacts, store, run, obs, decision, action


def test_durable_ordered_history_idempotent_repeats_and_reload(tmp_path):
    async def scenario():
        artifacts, store, run, obs, decision, action = await setup(tmp_path)
        await store.append(decision)
        await store.append(action)
        receipt = TechnicalReceipt(run.run_id, action.action_id, ReceiptStatus.COMPLETED, NOW, NOW)
        await store.append(receipt)
        await store.append(decision)
        await store.append(action)
        reloaded = SQLiteRunStore(tmp_path / "runs.sqlite", artifacts)
        assert await reloaded.get(run.run_id) == run
        assert await reloaded.history(run.run_id) == (obs, decision, action, receipt)
        assert (await reloaded.get(run.run_id)).goal.text == "  original  "
        with pytest.raises(PortError):
            await store.append(replace(decision, rationale="overwrite"))

    asyncio.run(scenario())


def test_rejects_missing_dependencies_wrong_scope_and_missing_artifacts(tmp_path):
    async def scenario():
        _, store, run, obs, decision, action = await setup(tmp_path)
        receipt = TechnicalReceipt(run.run_id, action.action_id, ReceiptStatus.COMPLETED, NOW, NOW)
        for record in (
            action,
            receipt,
            replace(decision, source_observation_id="missing"),
            replace(obs, observation_id="obs-2", sequence=1),
            replace(obs, observation_id="obs-2", sequence=2, device_id="other"),
            replace(
                obs,
                observation_id="obs-2",
                sequence=2,
                screenshot=replace(obs.screenshot, storage_key="../../outside"),
            ),
        ):
            with pytest.raises(PortError):
                await store.append(record)
        assert await store.history(run.run_id) == (obs,)

    asyncio.run(scenario())


def test_compare_and_swap_and_original_goal_configuration_cannot_change(tmp_path):
    async def scenario():
        _, store, run, *_ = await setup(tmp_path)
        for candidate, revision in (
            (run.pause(NOW), 0),
            (replace(run.pause(NOW), goal=Goal("changed")), 1),
            (replace(run.pause(NOW), device_id="other"), 1),
            (replace(run, revision=2), 1),
        ):
            with pytest.raises(PortError):
                await store.save(candidate, revision)
        paused = await store.save(run.pause(NOW), 1)
        assert paused.state is RunState.PAUSED
        assert (await store.get(run.run_id)).goal == run.goal

    asyncio.run(scenario())


def test_atomic_terminal_race_and_no_later_append(tmp_path):
    async def scenario():
        artifacts, store, run, obs, _, _ = await setup(tmp_path)
        assessment = Assessment(
            run.run_id, "conclude", SemanticVerdict.PASSED, "AI judgement", (obs.observation_id,)
        )
        decision = AgentDecision(
            "conclude",
            run.run_id,
            obs.observation_id,
            (obs.observation_id,),
            Conclude(assessment),
            "done",
            "",
            run.configuration.identity,
        )
        await store.append(decision)
        second = SQLiteRunStore(tmp_path / "runs.sqlite", artifacts)
        winners = await asyncio.gather(
            store.finalize(run.run_id, AIConclusion(run.run_id, NOW, assessment)),
            second.finalize(run.run_id, Cancelled(run.run_id, NOW, "user")),
        )
        assert winners[0] == winners[1] == await store.get(run.run_id)
        assert winners[0].revision == run.revision + 1
        assert winners[0].state is RunState.TERMINAL
        with pytest.raises(PortError):
            await store.append(replace(obs, observation_id="obs-2", sequence=2))

    asyncio.run(scenario())


def test_unbacked_conclusion_rejected_and_history_preserved(tmp_path):
    async def scenario():
        _, store, run, obs, decision, action = await setup(tmp_path)
        await store.append(decision)
        await store.append(action)
        terminal = AIConclusion(
            run.run_id,
            NOW,
            Assessment(
                run.run_id, "missing", SemanticVerdict.PASSED, "unsupported", (obs.observation_id,)
            ),
        )
        with pytest.raises(PortError):
            await store.finalize(run.run_id, terminal)
        assert await store.history(run.run_id) == (obs, decision, action)
        assert (await store.get(run.run_id)).terminal is None

    asyncio.run(scenario())


def test_artifacts_are_immutable_scoped_hashed_and_do_not_expose_input_paths(tmp_path):
    async def scenario():
        store = LocalArtifactStore(tmp_path / "artifacts")
        first = await store.put("../../run", b"private", "image/png")
        second = await store.put("../../run", b"private", "image/png")
        assert first.storage_key != second.storage_key
        assert ".." not in first.storage_key
        assert await store.read(first) == b"private"
        for forged in (replace(first, run_id="other"), replace(first, storage_key="../outside")):
            with pytest.raises(PortError):
                await store.read(forged)
        (tmp_path / "artifacts" / first.storage_key).write_bytes(b"corrupt")
        with pytest.raises(PortError, match="corrupt"):
            await store.read(first)
        assert await store.read(second) == b"private"

    asyncio.run(scenario())


def test_question_answer_survive_resume_and_reopen(tmp_path):
    async def scenario():
        artifacts, store, run, obs, decision, _ = await setup(tmp_path)
        decision = replace(decision, next=AskUser("Which item?"))
        question = PendingQuestion(
            "question-1", run.run_id, decision.decision_id, "Which item?", NOW
        )
        await store.append(decision)
        with pytest.raises(PortError):
            await store.save(run.ask(question, NOW), run.revision)
        await store.append(question)
        waiting = await store.save(run.ask(question, NOW), run.revision)
        answer = UserAnswer(question.question_id, run.run_id, "The blue item", "operator", NOW)
        await store.append(answer)
        answered = await store.save(waiting.answer(answer), waiting.revision)
        resumed = await store.save(answered.resume(NOW), answered.revision)
        reopened = SQLiteRunStore(tmp_path / "runs.sqlite", artifacts)
        assert await reopened.history(run.run_id) == (obs, decision, question, answer)
        assert (await reopened.get(run.run_id)).pending_question is None
        assert resumed.goal == run.goal
        with pytest.raises(PortError):
            await store.append(replace(answer, text="Replacement answer"))

    asyncio.run(scenario())


def test_action_dispatch_intent_rejected_after_pause(tmp_path):
    async def scenario():
        _, store, run, _, decision, action = await setup(tmp_path)
        await store.append(decision)
        await store.save(run.pause(NOW), run.revision)
        with pytest.raises(PortError):
            await store.append(action)

    asyncio.run(scenario())


def test_codec_rejects_unknown_tags_duplicate_keys_and_extra_fields():
    from visto.adapters.storage.codec import dumps, loads

    assert loads(dumps(initial())) == initial()
    for payload in (
        '{"version":1,"value":{"tag":"eval","fields":{}}}',
        '{"version":1,"version":1,"value":null}',
        '{"version":true,"value":null}',
        '{"version":1,"value":{"tag":"tuple","value":[],"extra":1}}',
    ):
        with pytest.raises(ValueError):
            loads(payload)


@pytest.mark.parametrize("mode", ["missing_receipt", "stale_capture", "source_frame", "fresh"])
def test_post_action_decision_requires_receipt_and_fresh_capture(tmp_path, mode):
    async def scenario():
        _, store, run, source, decision, action = await setup(tmp_path)
        await store.append(decision)
        await store.append(action)
        finished_at = NOW + timedelta(seconds=1)
        if mode != "missing_receipt":
            await store.append(
                TechnicalReceipt(
                    run.run_id, action.action_id, ReceiptStatus.COMPLETED, NOW, finished_at
                )
            )
        current = source
        if mode != "source_frame":
            current = replace(
                source,
                observation_id="obs-2",
                sequence=2,
                captured_at=NOW if mode == "stale_capture" else finished_at,
            )
            await store.append(current)
        ids = (
            (source.observation_id,)
            if current is source
            else (source.observation_id, current.observation_id)
        )
        assessment = Assessment(
            run.run_id,
            "decision-2",
            SemanticVerdict.PASSED,
            "Model assessment",
            (current.observation_id,),
        )
        conclusion = AgentDecision(
            "decision-2",
            run.run_id,
            current.observation_id,
            ids,
            Conclude(assessment),
            "Observed effect",
            "",
            run.configuration.identity,
            previous_effect=EffectAssessment(
                action.action_id, EffectVerdict.ACHIEVED, "Observed effect", ids
            ),
        )
        if mode == "fresh":
            await store.append(conclusion)
            terminal = await store.finalize(
                run.run_id, AIConclusion(run.run_id, finished_at, assessment)
            )
            assert terminal.terminal.assessment == assessment
        else:
            with pytest.raises(PortError):
                await store.append(conclusion)
            with pytest.raises(PortError):
                await store.finalize(run.run_id, AIConclusion(run.run_id, finished_at, assessment))
            assert (await store.get(run.run_id)).terminal is None

    asyncio.run(scenario())
