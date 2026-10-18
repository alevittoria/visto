"""Local HTTP boundaries exercise no device or provider network operations."""

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from visto.adapters.api.service import ExecutionService, WebSettings
from visto.composition import create_app
from visto.domain.run import Cancelled


@pytest.fixture
def directory():
    root = Path(__file__).resolve().parents[2] / ".work" / ("api-test-" + uuid4().hex)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


class FakeLoop:
    def __init__(self, service, control):
        self.store = service.store
        self.control = control
        self.clock = service.clock

    async def start(self, run):
        await self.store.create(run)
        run = await self.store.save(run.start(self.clock.now()), run.revision)
        while not self.control.cancel_requested() and not self.control.pause_requested():
            await asyncio.sleep(0.001)
        if self.control.cancel_requested():
            return await self.store.finalize(
                run.run_id, Cancelled(run.run_id, self.clock.now(), "user")
            )
        return await self.store.save(run.pause(self.clock.now()), run.revision)

    async def resume(self, run_id):
        run = await self.store.get(run_id)
        if self.control.cancel_requested():
            return await self.store.finalize(run_id, Cancelled(run_id, self.clock.now(), "user"))
        run = await self.store.save(run.resume(self.clock.now()), run.revision)
        while not self.control.cancel_requested() and not self.control.pause_requested():
            await asyncio.sleep(0.001)
        if self.control.cancel_requested():
            return await self.store.finalize(run_id, Cancelled(run_id, self.clock.now(), "user"))
        return await self.store.save(run.pause(self.clock.now()), run.revision)


HEADERS = {"X-Visto": "local-console"}
BODY = {"device_id": "operator-selected-serial", "goal": "Preserve original goal"}


def make_service(directory):
    service = ExecutionService(
        WebSettings(directory, directory / ".env", directory / "leases"),
        key_resolver=lambda _: "dummy-key",
    )
    service.runtime_factory = lambda settings, key, control: FakeLoop(service, control)
    return service


def eventually(client, run_id, state):
    for _ in range(200):
        result = client.get("/api/runs/" + run_id).json()
        if result["state"] == state:
            return result
        import time

        time.sleep(0.005)
    raise AssertionError(result)


def test_readiness_is_configuration_only_and_writes_require_local_guard(directory):
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        assert client.get("/api/readiness").json()["configured"] is True
        assert client.post("/api/runs", json=BODY).status_code == 403
        assert (
            client.post(
                "/api/runs", headers={**HEADERS, "Origin": "https://evil.example"}, json=BODY
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/runs", headers={**HEADERS, "Host": "evil.example"}, json=BODY
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/runs", headers=HEADERS, json={**BODY, "limits": {"max_actions": True}}
            ).status_code
            == 422
        )
        assert client.get("/api/runs/absent").status_code == 404


def test_one_session_pause_resume_cancel_and_durable_restart(directory):
    service = make_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        response = client.post("/api/runs", headers=HEADERS, json=BODY)
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        eventually(client, run_id, "running")
        assert client.post("/api/runs", headers=HEADERS, json=BODY).status_code == 409
        assert client.post(f"/api/runs/{run_id}/pause", headers=HEADERS).status_code == 202
        paused = eventually(client, run_id, "paused")
        assert paused["can_resume"] is True
        assert client.post("/api/runs", headers=HEADERS, json=BODY).status_code == 409
        assert client.post(f"/api/runs/{run_id}/resume", headers=HEADERS).status_code == 202
        assert eventually(client, run_id, "running")["control_pending"] is None
        assert client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).status_code == 202
        terminal = eventually(client, run_id, "terminal")
        assert terminal["terminal"]["kind"] == "cancelled"
        assert terminal["goal"]["text"] == BODY["goal"]
        assert "dummy-key" not in str(terminal)
        assert client.get(f"/api/runs/{run_id}/events").json() == {"events": [], "next_after": 0}
        assert client.get(f"/api/runs/{run_id}/artifacts/missing").status_code == 404
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        assert client.get("/api/runs").json()["runs"][0]["run_id"] == run_id
        assert client.get("/api/runs/" + run_id).json()["terminal"]["kind"] == "cancelled"


def test_shutdown_cancels_and_interrupted_run_refuses_resume(directory):
    service = make_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        eventually(client, run_id, "running")
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        assert client.get("/api/runs/" + run_id).json()["terminal"]["kind"] == "cancelled"
    # A persisted CLI-created/abandoned run has no process-local runtime.
    from visto.domain.models import Goal
    from visto.runner import RunnerSettings, new_run

    abandoned = new_run(
        RunnerSettings("other-serial", directory), Goal("Abandoned goal"), service.clock
    )
    asyncio.run(service.store.create(abandoned))
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        run = client.get("/api/runs/" + abandoned.run_id).json()
        assert run["interrupted"] and not run["can_resume"]
        assert (
            client.post(f"/api/runs/{abandoned.run_id}/resume", headers=HEADERS).status_code == 409
        )


class LocalDevice:
    def __init__(self, clock):
        self.clock = clock
        self.captures = 0
        self.acquisitions = 0
        self.releases = 0

    async def acquire(self, run_id, device_id, timeout_ms):
        from visto.domain.models import DeviceLease

        self.acquisitions += 1
        return DeviceLease(uuid4().hex, run_id, device_id, uuid4().hex)

    async def release(self, lease):
        self.releases += 1

    async def observe(self, lease, timeout_ms):
        from visto.domain.models import CapturedImage

        self.captures += 1
        return CapturedImage(
            lease,
            self.clock.now(),
            f"local-image-{self.captures}".encode(),
            "image/png",
            100,
            200,
            0,
        )

    async def execute(self, *args):
        raise AssertionError("No mutation is requested by this fixture")


class QuestionAgent:
    def __init__(self):
        self.calls = 0
        self.contexts = []

    async def decide(self, context, timeout_ms):
        from visto.application.context import AgentReply
        from visto.domain.models import (
            AgentDecision,
            AskUser,
            Assessment,
            Conclude,
            ModelUsage,
            SemanticVerdict,
        )

        self.contexts.append(context)
        self.calls += 1
        decision_id = uuid4().hex
        evidence = (context.current_observation_id,)
        next_decision = (
            AskUser("Which synthetic account should be used?")
            if self.calls == 1
            else Conclude(
                Assessment(
                    context.run.run_id,
                    decision_id,
                    SemanticVerdict.INCONCLUSIVE,
                    "Fixture conclusion based on fresh evidence",
                    evidence,
                )
            )
        )
        decision = AgentDecision(
            decision_id,
            context.run.run_id,
            context.current_observation_id,
            tuple(image.observation.observation_id for image in context.images),
            next_decision,
            "Concise fixture rationale",
            "Keep the immutable objective",
            context.run.configuration.identity,
            ModelUsage(1000 * self.calls, 40 * self.calls),
        )
        return AgentReply(decision, "local-conversation")


def real_local_service(directory):
    from visto.application.loop import RunLoop

    service = make_service(directory)
    device = LocalDevice(service.clock)
    agent = QuestionAgent()
    service.runtime_factory = lambda settings, key, control: RunLoop(
        device, agent, service.store, service.artifacts, service.clock, control
    )
    return service, device, agent


def test_real_loop_question_events_provenance_idempotent_answer_and_fresh_resume(directory):
    service, device, agent = real_local_service(directory)
    with TestClient(create_app(service), base_url="http://localhost:5173") as client:
        headers = {**HEADERS, "Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}
        run_id = client.post(
            "/api/runs",
            headers=headers,
            json={**BODY, "constraints": ["Never change objective"], "observe_only": True},
        ).json()["run_id"]
        run = eventually(client, run_id, "waiting_for_user")
        question_id = run["pending_question"]["question_id"]
        assert device.releases == 1
        assert client.post(f"/api/runs/{run_id}/resume", headers=headers).status_code == 409
        assert (
            client.post(
                f"/api/runs/{run_id}/answers",
                headers=headers,
                json={"question_id": "stale", "text": "synthetic fixture"},
            ).status_code
            == 409
        )
        answer = {"question_id": question_id, "text": "synthetic fixture"}
        assert (
            client.post(f"/api/runs/{run_id}/answers", headers=headers, json=answer).status_code
            == 200
        )
        assert (
            client.post(f"/api/runs/{run_id}/answers", headers=headers, json=answer).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/runs/{run_id}/answers",
                headers=headers,
                json={**answer, "text": "conflicting"},
            ).status_code
            == 409
        )
        page = client.get(f"/api/runs/{run_id}/events?limit=1").json()
        assert page["next_after"] == 1
        event = page["events"][0]
        assert event["kind"] == "observation"
        screenshot = event["data"]["screenshot"]
        assert "storage_key" not in screenshot
        assert screenshot["url"].endswith("/artifacts/" + event["data"]["observation_id"])
        assert client.get(screenshot["url"]).content == b"local-image-1"
        assert client.get(screenshot["url"]).headers["cache-control"] == "no-store"
        assert "working_plan" in str(client.get(f"/api/runs/{run_id}/events?after=1").json())
        assert client.post(f"/api/runs/{run_id}/resume", headers=headers).status_code == 202
        terminal = eventually(client, run_id, "terminal")
        assert terminal["terminal"]["kind"] == "ai_conclusion"
        assert terminal["terminal"]["assessment"]["verdict"] == "inconclusive"
        assert device.acquisitions == device.releases == 2
        assert agent.contexts[1].current_observation_id != agent.contexts[0].current_observation_id
        assert agent.contexts[1].run.goal.constraints == ("Never change objective",)
        assert agent.contexts[1].run.configuration.capabilities == ()
        assert len(agent.contexts[1].answers) == 1
        assert (
            client.post(f"/api/runs/{run_id}/answers", headers=headers, json=answer).status_code
            == 200
        )
        # No artifact may be fetched through a different persisted run.
        other_id = client.post("/api/runs", headers=headers, json=BODY).json()["run_id"]
        assert (
            client.get(
                f"/api/runs/{other_id}/artifacts/{event['data']['observation_id']}"
            ).status_code
            == 404
        )


def test_suspended_deadline_expires_without_operator_resume(directory):
    service, device, agent = real_local_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post(
            "/api/runs", headers=HEADERS, json={**BODY, "limits": {"wall_time_ms": 150}}
        ).json()["run_id"]
        eventually(client, run_id, "waiting_for_user")
        terminal = eventually(client, run_id, "terminal")
        assert terminal["terminal"]["kind"] == "budget_exhausted"
        assert terminal["terminal"]["budget"] == "wall_time"
        assert device.captures == 1 and agent.calls == 1


def test_missing_configuration_and_runtime_failures_are_sanitized(directory):
    service = make_service(directory)
    service.key_resolver = lambda _: ""
    with TestClient(create_app(service), base_url="http://localhost") as client:
        assert not client.get("/api/readiness").json()["configured"]
        assert client.post("/api/runs", headers=HEADERS, json=BODY).status_code == 503
        invalid = client.post(
            "/api/runs", headers=HEADERS, json={**BODY, "api_key": "secret-must-not-echo"}
        )
        assert invalid.status_code == 422 and "secret-must-not-echo" not in invalid.text
    service = make_service(directory)

    class FailingLoop:
        async def start(self, run):
            raise RuntimeError("dummy-key private C:/path")

    service.runtime_factory = lambda *args: FailingLoop()
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        terminal = eventually(client, run_id, "terminal")
        assert terminal["terminal"]["kind"] == "infrastructure_failure"
        assert "dummy-key" not in str(terminal) and "C:/path" not in str(terminal)


def test_concurrent_creation_has_one_admission_without_waiting_queue(directory):
    from concurrent.futures import ThreadPoolExecutor

    service = make_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(
                pool.map(lambda _: client.post("/api/runs", headers=HEADERS, json=BODY), range(4))
            )
        assert sorted(response.status_code for response in responses) == [202, 409, 409, 409]
        assert len(client.get("/api/runs").json()["runs"]) == 1
        run_id = next(
            response.json()["run_id"] for response in responses if response.status_code == 202
        )
        client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS)
        eventually(client, run_id, "terminal")


def test_default_composition_paths_ignore_process_working_directory(directory, monkeypatch):
    import visto.composition as composition

    captured = []

    def capture(settings):
        captured.append(settings)
        return make_service(directory)

    monkeypatch.setattr(composition, "ExecutionService", capture)
    monkeypatch.chdir(directory)
    composition.create_app()
    settings = captured[0]
    repository = Path(__file__).resolve().parents[2]
    assert settings.env_file == repository / ".env"
    assert settings.data_directory == repository / ".work" / "runs"
    assert settings.lease_directory == repository / ".work" / "device-leases"


def test_proxied_console_origin_is_accepted_and_rewritten_host_is_rejected(directory):
    # Vite forwards the browser Host only with changeOrigin: false (see vite.config.ts).
    console = {**HEADERS, "Origin": "http://127.0.0.1:5173", "Sec-Fetch-Site": "same-origin"}
    with TestClient(
        create_app(make_service(directory)), base_url="http://127.0.0.1:5173"
    ) as client:
        created = client.post("/api/runs", headers=console, json=BODY)
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        assert client.post(f"/api/runs/{run_id}/cancel", headers=console).status_code == 202
        eventually(client, run_id, "terminal")
    with TestClient(
        create_app(make_service(directory)), base_url="http://127.0.0.1:8000"
    ) as client:
        assert client.post("/api/runs", headers=console, json=BODY).status_code == 403


def test_reads_reject_non_loopback_host_against_dns_rebinding(directory):
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        for host in ("rebound.example.test", "rebound.example.test:8080", "192.0.2.10:8000"):
            for path in ("/api/health", "/api/runs", f"/api/runs/{run_id}/report.json"):
                response = client.get(path, headers={"Host": host})
                assert response.status_code == 403
                assert response.json() == {"detail": "Loopback host is required"}
                assert response.headers["cache-control"] == "no-store"
        for host in ("localhost:8080", "127.0.0.1:8000", "[::1]:5173"):
            assert client.get("/api/runs", headers={"Host": host}).status_code == 200
        assert client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).status_code == 202
        eventually(client, run_id, "terminal")


def test_validation_errors_are_a_single_safe_detail_string(directory):
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        invalid = client.post(
            "/api/runs",
            headers=HEADERS,
            json={**BODY, "goal": " ", "limits": {"wall_time_ms": "secret-value"}},
        )
    assert invalid.status_code == 422
    detail = invalid.json()["detail"]
    assert isinstance(detail, str) and "goal" in detail and "limits.wall_time_ms" in detail
    assert "secret-value" not in invalid.text


def test_pause_while_resume_is_pending_is_a_conflict(directory):
    service = make_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        assert client.post(f"/api/runs/{run_id}/pause", headers=HEADERS).status_code == 202
        eventually(client, run_id, "paused")
        service.active.pending = "resume"  # Freeze the window before the loop saves running.
        response = client.post(f"/api/runs/{run_id}/pause", headers=HEADERS)
        assert response.status_code == 409 and "Resume is pending" in response.json()["detail"]
        service.active.pending = None
        client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS)
        eventually(client, run_id, "terminal")


def test_cleanup_failure_after_terminal_is_flagged_without_changing_outcome(directory):
    service = make_service(directory)

    class CleanupFailingLoop:
        async def start(self, run):
            await service.store.create(run)
            await service.store.finalize(
                run.run_id, Cancelled(run.run_id, service.clock.now(), "user")
            )
            raise RuntimeError("lease release failed dummy-key")

    service.runtime_factory = lambda *args: CleanupFailingLoop()
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        terminal = eventually(client, run_id, "terminal")
        for _ in range(200):
            terminal = client.get("/api/runs/" + run_id).json()
            if terminal["cleanup_failed"]:
                break
            import time

            time.sleep(0.005)
        assert terminal["cleanup_failed"] is True
        assert terminal["terminal"]["kind"] == "cancelled"
        assert "dummy-key" not in str(terminal)
        assert client.get("/api/readiness").json()["cleanup_attention_run_ids"] == [run_id]


def test_model_selection_is_restricted_to_the_configured_allowlist(directory):
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        readiness = client.get("/api/readiness").json()
        assert readiness["model"] == "gpt-6-luna"
        assert readiness["models"] == ["gpt-6-luna", "gpt-5.6-terra", "gpt-6-sol"]
        assert readiness["default_limits"]["max_actions"] == 60
        rejected = client.post("/api/runs", headers=HEADERS, json={**BODY, "model": "gpt-other"})
        assert rejected.status_code == 422
        assert client.get("/api/runs").json()["runs"] == []
        run = client.post("/api/runs", headers=HEADERS, json={**BODY, "model": "gpt-6-sol"})
        assert run.status_code == 202
        assert run.json()["configuration"]["identity"]["model"] == "gpt-6-sol"
        client.post(f"/api/runs/{run.json()['run_id']}/cancel", headers=HEADERS)
        eventually(client, run.json()["run_id"], "terminal")


def test_delete_single_and_all_runs_keeps_the_active_run(directory):
    service, _, agent = real_local_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        first = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        question = eventually(client, first, "waiting_for_user")["pending_question"]
        assert client.delete(f"/api/runs/{first}").status_code == 403
        assert client.delete(f"/api/runs/{first}", headers=HEADERS).status_code == 409
        answer = {"question_id": question["question_id"], "text": "synthetic fixture"}
        client.post(f"/api/runs/{first}/answers", headers=HEADERS, json=answer)
        client.post(f"/api/runs/{first}/resume", headers=HEADERS)
        eventually(client, first, "terminal")
        artifacts = directory / "artifacts"
        assert any(artifacts.iterdir())

        usage = client.get(f"/api/runs/{first}").json()["usage"]
        assert usage == {
            "input_tokens": 3000,
            "output_tokens": 120,
            "recorded_decisions": 2,
            "unknown_usage_decisions": 0,
        }
        assert client.get("/api/runs").json()["runs"][0]["usage"]["input_tokens"] == 3000
        assert client.get("/api/usage").json()["output_tokens"] == 120

        deleted = client.delete(f"/api/runs/{first}", headers=HEADERS)
        assert deleted.json() == {"deleted": [first]}
        assert client.get(f"/api/runs/{first}").status_code == 404
        assert client.delete(f"/api/runs/{first}", headers=HEADERS).status_code == 404
        assert not any(artifacts.iterdir())
        assert client.get("/api/usage").json()["input_tokens"] == 0

        agent.calls = 0  # Each run starts with a question again.
        second = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        question = eventually(client, second, "waiting_for_user")["pending_question"]
        client.post(
            f"/api/runs/{second}/answers",
            headers=HEADERS,
            json={"question_id": question["question_id"], "text": "synthetic fixture"},
        )
        client.post(f"/api/runs/{second}/resume", headers=HEADERS)
        eventually(client, second, "terminal")
        agent.calls = 0
        third = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        eventually(client, third, "waiting_for_user")
        result = client.delete("/api/runs", headers=HEADERS).json()
        assert result == {"deleted": [second], "kept_active_run_id": third}
        assert [run["run_id"] for run in client.get("/api/runs").json()["runs"]] == [third]
        client.post(f"/api/runs/{third}/cancel", headers=HEADERS)
        eventually(client, third, "terminal")
        assert client.delete("/api/runs", headers=HEADERS).json()["deleted"] == [third]
        assert client.get("/api/runs").json()["runs"] == []


def test_statistics_aggregate_stored_outcomes_tokens_and_scenarios(directory):
    service, _, _ = real_local_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        assert client.get("/api/statistics").json()["overall"]["runs"] == 0
        first = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        question = eventually(client, first, "waiting_for_user")["pending_question"]
        answer = {"question_id": question["question_id"], "text": "synthetic fixture"}
        client.post(f"/api/runs/{first}/answers", headers=HEADERS, json=answer)
        client.post(f"/api/runs/{first}/resume", headers=HEADERS)
        eventually(client, first, "terminal")

        service.runtime_factory = lambda settings, key, control: FakeLoop(service, control)
        other = {**BODY, "goal": "Another fictional goal"}
        second = client.post("/api/runs", headers=HEADERS, json=other).json()["run_id"]
        eventually(client, second, "running")
        client.post(f"/api/runs/{second}/cancel", headers=HEADERS)
        eventually(client, second, "terminal")

        result = client.get("/api/statistics").json()
        overall = result["overall"]
        assert overall["runs"] == 2
        assert overall["outcomes"]["inconclusive"] == 1
        assert overall["outcomes"]["cancelled"] == 1
        assert overall["ai_conclusions"] == 1
        assert (overall["input_tokens"], overall["output_tokens"]) == (3000, 120)
        assert overall["duration_ms"]["min"] >= 0
        assert [group["runs"] for group in result["by_model"]] == [2]
        labels = [group["label"] for group in result["by_scenario"]]
        assert labels == ["Another fictional goal", "Preserve original goal"]
        assert result["by_scenario"][1]["recent"][0]["run_id"] == first

        # Single-run cost: unpriced without a list, then the list of the run's day.
        from datetime import date

        from visto.adapters.pricing import PriceSheet

        view = client.get(f"/api/runs/{first}").json()
        assert view["cost"] == {
            "usd": None,
            "approximate": False,
            "price_day": None,
            "input_per_m": None,
            "output_per_m": None,
        }
        day = date.fromisoformat(view["created_at"][:10])
        model = view["configuration"]["identity"]["model"]
        service.prices.save(day, "fixture", PriceSheet(None, {model: (1.0, 10.0)}))
        assert client.get(f"/api/runs/{first}").json()["cost"] == {
            "usd": (3000 * 1 + 120 * 10) / 1e6,
            "approximate": False,
            "price_day": day.isoformat(),
            "input_per_m": 1.0,
            "output_per_m": 10.0,
        }
