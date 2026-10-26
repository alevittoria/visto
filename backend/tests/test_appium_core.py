import asyncio
import hashlib
import http.client
import json
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from visto.adapters.appium import AppiumSession
from visto.adapters.appium.session import AppiumRefusal
from visto.adapters.appium.wire import CommandError, HttpWire
from visto.application.ports import OperatorActionRequired, PortError
from visto.application.runtime import utc_now
from visto.domain.commands import Tap
from visto.domain.models import (
    Action,
    ArtifactRef,
    CapturedImage,
    DeviceLease,
    Observation,
    ReceiptStatus,
)

# The core never parses pixels: framing checks belong to the capture hook.
IMAGE = b"stub image bytes"
WIDTH, HEIGHT = 40, 60


@pytest.fixture
def tmp_path():
    # Windows sandbox cannot reopen pytest's user-only (0o700) temp directories.
    root = Path(__file__).resolve().parents[2] / ".work" / "appium-core-tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid4().hex
    target.mkdir()
    try:
        yield target
    finally:
        if target.resolve().parent != root.resolve():
            raise ValueError("Refusing cleanup outside Appium core test directory")
        shutil.rmtree(target)


class FakeWire:
    def __init__(self):
        self.calls = []
        self.fail_create = False
        self.fail_mutation = False

    def request(self, method, path, body, timeout_ms):
        self.calls.append((method, path, body, timeout_ms))
        assert 0 < timeout_ms <= 30000
        if path == "/session":
            if self.fail_create:
                raise TimeoutError("sensitive remote details")
            return {"value": {"sessionId": "stub-session"}}
        if method == "DELETE":
            return {"value": None}
        if self.fail_mutation:
            raise OSError("private text must never escape")
        return {"value": None}


class StubDevice(AppiumSession):
    """Smallest subclass of the core: no platform routes beyond the mutation path."""

    def __init__(self, lease_directory, wire):
        super().__init__("stub", "stub-wire-v1", wire, lease_directory)

    def capabilities(self, device_id):
        return {"platformName": "Stub"}

    def capture(self, lease, deadline, stop):
        return CapturedImage(lease, utc_now(), IMAGE, "image/png", WIDTH, HEIGHT, 0)

    def translate(self, command, lease, deadline, stop):
        return "/actions", {}


async def prepared(tmp_path, wire=None):
    wire = wire or FakeWire()
    device = StubDevice(tmp_path, wire)
    lease = await device.acquire("run", "device-A", 3000)
    image = await device.observe(lease, 3000)
    artifact = ArtifactRef(
        "image",
        "run",
        "image/png",
        len(image.content),
        hashlib.sha256(image.content).hexdigest(),
        "private/image",
    )
    source = Observation(
        "obs",
        "run",
        1,
        image.captured_at,
        "device-A",
        lease.session_id,
        lease.lease_id,
        artifact,
        image.width,
        image.height,
        image.rotation,
    )
    return device, wire, lease, source


def action(lease):
    return Action("action", "run", "decision", "obs", lease.lease_id, Tap(10, 20), 2000)


def test_session_component_prefixes_sanitized_errors(tmp_path):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        assert wire.calls[0][2] == {"capabilities": {"alwaysMatch": {"platformName": "Stub"}}}
        with pytest.raises(PortError) as error:
            await device.observe(replace(lease, run_id="other"), 1000)
        message = str(error.value)
        assert message.startswith("stub: ") and "lease is not owned" in message
        assert str(tmp_path) not in message
        await device.release(lease)

    asyncio.run(scenario())


def test_second_session_on_same_device_is_refused(tmp_path):
    async def scenario():
        device, _, lease, _ = await prepared(tmp_path)
        other_wire = FakeWire()
        second = StubDevice(tmp_path, other_wire)
        with pytest.raises(PortError, match="stub: device already leased"):
            await second.acquire("other-run", "device-A", 1000)
        assert not other_wire.calls
        await device.release(lease)
        await second.acquire("other-run", "device-A", 1000)

    asyncio.run(scenario())


def test_marker_is_retained_when_session_creation_fails(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_create = True
        device = StubDevice(tmp_path, wire)
        with pytest.raises(PortError) as error:
            await device.acquire("run", "device-A", 1000)
        assert str(error.value).startswith("stub: ") and "sensitive" not in str(error.value)
        assert len(list(tmp_path.glob("*.lease"))) == 1

    asyncio.run(scenario())


def test_explicit_session_refusal_releases_marker(tmp_path):
    async def scenario():
        device = StubDevice(tmp_path, RefusingWire("unknown device"))
        with pytest.raises(PortError, match="stub: Appium request failed"):
            await device.acquire("run", "device-A", 1000)
        assert not list(tmp_path.glob("*.lease"))
        assert device._marker is None and device._token is None

    asyncio.run(scenario())


def test_refusal_with_operator_hint_releases_marker_and_keeps_the_hint(tmp_path):
    async def scenario():
        device = DiagnosingDevice(tmp_path, RefusingWire("a known refusal"))
        with pytest.raises(OperatorActionRequired, match="fix the stub server"):
            await device.acquire("run", "device-A", 1000)
        assert not list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


def test_refusal_whose_marker_cannot_be_removed_keeps_ownership(tmp_path, monkeypatch):
    def failing_unlink(self, missing_ok=False):
        raise OSError("read-only lease directory")

    async def scenario():
        device = StubDevice(tmp_path, RefusingWire("unknown device"))
        monkeypatch.setattr(Path, "unlink", failing_unlink)
        with pytest.raises(PortError, match="stub: session refused; ownership retained") as error:
            await device.acquire("run", "device-A", 1000)
        monkeypatch.undo()
        assert not isinstance(error.value, AppiumRefusal)
        assert len(list(tmp_path.glob("*.lease"))) == 1
        assert device._marker is not None and device._token is not None

    asyncio.run(scenario())


def test_explicit_refusal_is_an_appium_refusal(tmp_path):
    async def scenario():
        device = StubDevice(tmp_path, RefusingWire("unknown device"))
        with pytest.raises(AppiumRefusal):
            await device.acquire("run", "device-A", 1000)

    asyncio.run(scenario())


class LateRefusingWire(FakeWire):
    """Answers the session request with a W3C error only once the test allows it."""

    def __init__(self):
        super().__init__()
        self.answer = threading.Event()

    def request(self, method, path, body, timeout_ms):
        self.calls.append((method, path, body, timeout_ms))
        self.answer.wait(5)
        raise CommandError("appium: command failure", "unknown device")


def test_refusal_after_the_startup_deadline_keeps_the_marker_it_reported(tmp_path):
    async def scenario():
        wire = LateRefusingWire()
        device = StubDevice(tmp_path, wire)
        with pytest.raises(PortError, match="session startup timed out; ownership retained"):
            await device.acquire("run", "device-A", 50)
        wire.answer.set()
        with pytest.raises(PortError):
            await device._pending
        # The caller was told ownership is retained: the late refusal keeps it so.
        assert len(list(tmp_path.glob("*.lease"))) == 1
        assert device._marker is not None

    asyncio.run(scenario())


def test_deadline_that_fires_just_after_a_released_refusal_says_so(tmp_path, monkeypatch):
    from visto.adapters.appium import session

    async def late_deadline(awaitable, timeout):
        # The worker finished first, then the deadline still fired.
        try:
            await awaitable
        except PortError:
            pass
        raise TimeoutError

    async def scenario():
        device = StubDevice(tmp_path, RefusingWire("unknown device"))
        monkeypatch.setattr(session.asyncio, "wait_for", late_deadline)
        with pytest.raises(PortError) as error:
            await device.acquire("run", "device-A", 1000)
        monkeypatch.undo()
        assert "ownership released" in str(error.value)
        assert "retained" not in str(error.value)
        assert not list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


class RefusingWire(FakeWire):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def request(self, method, path, body, timeout_ms):
        self.calls.append((method, path, body, timeout_ms))
        raise CommandError("appium: command failure", self.message)


class DiagnosingDevice(StubDevice):
    def diagnose(self, message):
        return "fix the stub server" if "known refusal" in message else None


def test_known_appium_refusal_becomes_a_fixed_operator_hint(tmp_path):
    async def scenario():
        device = DiagnosingDevice(tmp_path, RefusingWire("a known refusal: /private/path"))
        with pytest.raises(OperatorActionRequired) as error:
            await device.acquire("run", "device-A", 1000)
        # The hint is the adapter's own text; the server's message never escapes.
        assert str(error.value) == "stub: fix the stub server"

    asyncio.run(scenario())


def test_unknown_appium_refusal_stays_generic(tmp_path):
    async def scenario():
        device = DiagnosingDevice(tmp_path, RefusingWire("something else: /private/path"))
        with pytest.raises(PortError) as error:
            await device.acquire("run", "device-A", 1000)
        assert not isinstance(error.value, OperatorActionRequired)
        assert str(error.value) == "stub: Appium request failed"

    asyncio.run(scenario())


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self, limit):
        return self._body[:limit]


def fake_connection(status, body):
    class Connection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, path, body=None, headers=None):
            pass

        def getresponse(self):
            return FakeResponse(status, body)

        def close(self):
            pass

    return Connection


def test_wire_keeps_the_w3c_error_message_of_a_failed_command(monkeypatch):
    body = json.dumps(
        {"value": {"error": "session not created", "message": "server explanation"}}
    ).encode()
    monkeypatch.setattr(http.client, "HTTPConnection", fake_connection(500, body))
    with pytest.raises(CommandError) as error:
        HttpWire("http://127.0.0.1:4723").request("POST", "/session", {}, 1000)
    assert error.value.message == "server explanation"
    assert str(error.value) == "appium: command failure"


def test_wire_reports_a_non_w3c_http_failure_without_a_message(monkeypatch):
    monkeypatch.setattr(http.client, "HTTPConnection", fake_connection(502, b"<html>"))
    with pytest.raises(PortError) as error:
        HttpWire("http://127.0.0.1:4723").request("GET", "/status", None, 1000)
    assert not isinstance(error.value, CommandError)


def test_dispatch_failure_after_mutation_returns_uncertain(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        wire.fail_mutation = True
        receipt = await device.execute(lease, action(lease), source)
        assert receipt.status is ReceiptStatus.UNCERTAIN
        assert "private" not in receipt.detail
        assert device._uncertain.is_set()
        assert (await device.execute(lease, action(lease), source)).status is ReceiptStatus.REJECTED
        assert len([c for c in wire.calls if c[1].endswith("/actions")]) == 1
        with pytest.raises(PortError, match="manual recovery"):
            await device.release(lease)
        assert list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


def test_release_without_acquire_is_a_noop(tmp_path):
    async def scenario():
        wire = FakeWire()
        device = StubDevice(tmp_path, wire)
        assert await device.release(DeviceLease("lease", "run", "device-A", "session")) is None
        assert not wire.calls
        assert not list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())
