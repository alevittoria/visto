import asyncio
import base64
import hashlib
import json
import shutil
import struct
import threading
import zlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from visto.adapters.android import AppiumDevice
from visto.adapters.appium.wire import CommandError
from visto.application.ports import OperatorActionRequired, PortError
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import Action, ArtifactRef, Observation, ReceiptStatus


@pytest.fixture
def tmp_path():
    # Windows sandbox cannot reopen pytest's user-only (0o700) temp directories.
    root = Path(__file__).resolve().parents[2] / ".work" / "android-tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid4().hex
    target.mkdir()
    try:
        yield target
    finally:
        if target.resolve().parent != root.resolve():
            raise ValueError("Refusing cleanup outside Android test directory")
        shutil.rmtree(target)


def png(width=100, height=200):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\0\0" * width) * height))
        + chunk(b"IEND", b"")
    )


class FakeWire:
    def __init__(self):
        self.calls = []
        self.rotation = 0
        self.content = png()
        self.fail_mutation = False
        self.fail_delete = False
        self.fail_create = False
        self.focused = "field/1"

    def request(self, method, path, body, timeout_ms):
        self.calls.append((method, path, body, timeout_ms))
        assert 0 < timeout_ms <= 30000
        if path == "/session":
            if self.fail_create:
                raise TimeoutError("sensitive remote details")
            return {"value": {"sessionId": "session/with+reserved"}}
        if method == "DELETE":
            if self.fail_delete:
                raise PortError("deletion failed")
            return {"value": None}
        if path == "/session/session%2Fwith%2Breserved/appium/device/rotation":
            raise PortError("android: HTTP 405 unknown method; not implemented")
        if method == "GET" and path == "/session/session%2Fwith%2Breserved/rotation":
            return {"value": {"x": 0, "y": 0, "z": self.rotation}}
        if path.endswith("/screenshot"):
            return {"value": base64.b64encode(self.content).decode()}
        if method == "GET" and path.endswith("/element/active"):
            if self.focused is None:
                raise PortError("no such element")
            return {"value": {"element-6066-11e4-a52e-4f735466cecf": self.focused}}
        if self.fail_mutation:
            raise OSError("private text must never escape")
        return {"value": None}


async def prepared(tmp_path, wire=None):
    wire = wire or FakeWire()
    device = AppiumDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
    lease = await device.acquire("run", "serial", 3000)
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
        "serial",
        lease.session_id,
        lease.lease_id,
        artifact,
        image.width,
        image.height,
        image.rotation,
    )
    return device, wire, lease, source


def action(lease, command=None):
    return Action(
        "action",
        "run",
        "decision",
        "obs",
        lease.lease_id,
        command if command is not None else Tap(10, 20),
        2000,
    )


def test_explicit_serial_and_lifecycle(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        caps = wire.calls[0][2]["capabilities"]["alwaysMatch"]
        assert caps["appium:udid"] == "serial"
        assert caps["appium:noReset"] is True
        assert caps["appium:autoLaunch"] is False
        assert (source.width, source.height, source.rotation) == (100, 200, 0)
        assert any("session%2Fwith%2Breserved" in call[1] for call in wire.calls)
        await device.release(lease)
        await device.release(lease)
        assert not list(tmp_path.glob("*.lease"))
        assert len([c for c in wire.calls if c[0] == "DELETE"]) == 1

    asyncio.run(scenario())


def test_observe_uses_native_uiautomator2_rotation_route(tmp_path):
    async def scenario():
        wire = FakeWire()
        device = AppiumDevice("http://unused", tmp_path, wire=wire)
        lease = await device.acquire("run", "serial", 3000)
        try:
            capture = await device.observe(lease, 3000)
            assert (capture.width, capture.height, capture.rotation) == (100, 200, 0)
            assert capture.content == wire.content
            # The pinned native driver does not implement /appium/device/rotation.
            assert [(call[0], call[1]) for call in wire.calls[1:]] == [
                ("GET", "/session/session%2Fwith%2Breserved/rotation"),
                ("GET", "/session/session%2Fwith%2Breserved/screenshot"),
                ("GET", "/session/session%2Fwith%2Breserved/rotation"),
            ]
        finally:
            await device.release(lease)
        assert not list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


def test_two_adapters_cannot_own_same_serial(tmp_path):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        second_wire = FakeWire()
        second = AppiumDevice("http://unused", tmp_path, wire=second_wire)
        with pytest.raises(PortError, match="already leased"):
            await second.acquire("other", "serial", 1000)
        assert not second_wire.calls
        with pytest.raises(PortError):
            await device.release(replace(lease, run_id="other"))
        assert not any(c[0] == "DELETE" for c in wire.calls)
        await device.release(lease)
        await second.acquire("other", "serial", 1000)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command, suffix, expected",
    [
        (Tap(10, 20), "/actions", None),
        (Swipe(1, 2, 30, 40, 50), "/actions", None),
        (
            TypeText("è文字🙂"),
            "/element/field%2F1/value",
            {"text": "è文字🙂", "replace": True},
        ),
        (Back(), "/execute/sync", {"script": "mobile: pressKey", "args": [{"keycode": 4}]}),
        (Home(), "/execute/sync", {"script": "mobile: pressKey", "args": [{"keycode": 3}]}),
        (Enter(), "/execute/sync", {"script": "mobile: pressKey", "args": [{"keycode": 66}]}),
        (LongPress(10, 20, 900), "/actions", None),
    ],
)
def test_typed_commands_and_no_source_replay(tmp_path, command, suffix, expected):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, command), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        call = wire.calls[-1]
        assert call[0] == "POST" and call[1].endswith(suffix)
        if expected:
            assert call[2] == expected
        else:
            pointer = call[2]["actions"][0]
            assert pointer["parameters"] == {"pointerType": "touch"}
            assert pointer["actions"][-1] == {"type": "pointerUp", "button": 0}
            if isinstance(command, LongPress):
                assert pointer["actions"][2] == {"type": "pause", "duration": 900}
        count = len(wire.calls)
        duplicate = await device.execute(lease, action(lease, command), source)
        assert duplicate.status is ReceiptStatus.REJECTED
        assert len(wire.calls) == count
        await device.release(lease)

    asyncio.run(scenario())


def test_type_text_sets_whole_text_in_one_request_on_the_focused_field(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, TypeText("user@example.test")), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        mutations = [c for c in wire.calls if c[0] == "POST" and "/element/" in c[1]]
        assert len(mutations) == 1  # One request: no per-character typing.
        assert mutations[0][2] == {"text": "user@example.test", "replace": True}
        assert not any("mobile: type" in str(c[2]) for c in wire.calls)
        await device.release(lease)

    asyncio.run(scenario())


def test_type_text_without_focused_field_is_rejected_before_any_mutation(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.focused = None
        device, wire, lease, source = await prepared(tmp_path, wire)
        receipt = await device.execute(lease, action(lease, TypeText("secret text")), source)
        assert receipt.status is ReceiptStatus.REJECTED
        assert "tap the field first" in receipt.detail and "secret" not in receipt.detail
        assert not any(c[0] == "POST" and "/element/" in c[1] for c in wire.calls)
        # Not uncertain: a later command from a fresh observation can still dispatch.
        assert not device._uncertain.is_set()
        await device.release(lease)

    asyncio.run(scenario())


def test_type_text_failure_after_dispatch_is_uncertain(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_mutation = True
        device, wire, lease, source = await prepared(tmp_path, wire)
        receipt = await device.execute(lease, action(lease, TypeText("abc")), source)
        assert receipt.status is ReceiptStatus.UNCERTAIN
        assert device._uncertain.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["bounds", "rotation", "size", "scope", "hash", "stale"])
def test_frame_and_scope_mismatch_never_mutates(tmp_path, change):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        intent = action(lease)
        if change == "bounds":
            intent = action(lease, Tap(100, 20))
        elif change == "rotation":
            wire.rotation = 90
        elif change == "size":
            wire.content = png(200, 100)
        elif change == "scope":
            source = replace(source, session_id="other")
        elif change == "hash":
            source = replace(source, screenshot=replace(source.screenshot, sha256="0" * 64))
        elif change == "stale":
            fresh = await device.observe(lease, 1000)
            # Consecutive fake captures can share Windows' wall-clock tick.
            source = replace(source, captured_at=fresh.captured_at - timedelta(microseconds=1))
        receipt = await device.execute(lease, intent, source)
        assert receipt.status is ReceiptStatus.REJECTED
        assert not any(c[0] == "POST" and c[1] != "/session" for c in wire.calls)
        await device.release(lease)

    asyncio.run(scenario())


def test_uncertain_dispatch_is_not_retried_and_error_is_sanitized(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        wire.fail_mutation = True
        receipt = await device.execute(lease, action(lease), source)
        assert receipt.status is ReceiptStatus.UNCERTAIN
        assert "private" not in receipt.detail
        assert len([c for c in wire.calls if c[1].endswith("/actions")]) == 1
        assert (await device.execute(lease, action(lease), source)).status is ReceiptStatus.REJECTED
        with pytest.raises(PortError, match="manual recovery"):
            await device.release(lease)
        assert list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


def test_cleanup_failure_retains_marker(tmp_path):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        wire.fail_delete = True
        with pytest.raises(PortError):
            await device.release(lease)
        assert len(list(tmp_path.glob("*.lease"))) == 1
        wire.fail_delete = False
        await device.release(lease)

    asyncio.run(scenario())


def test_startup_failure_keeps_crash_marker(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_create = True
        device = AppiumDevice("http://unused", tmp_path, wire=wire)
        with pytest.raises(PortError):
            await device.acquire("run", "serial", 1000)
        marker = list(tmp_path.glob("*.lease"))
        assert len(marker) == 1
        assert json.loads(marker[0].read_text())["device_id"] == "serial"

    asyncio.run(scenario())


@pytest.mark.parametrize("content", [b"", b"not PNG", png()[:-1], png()[:30] + b"bad"])
def test_invalid_screenshots_raise_without_empty_evidence(tmp_path, content):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        wire.content = content
        with pytest.raises(PortError):
            await device.observe(lease, 1000)
        await device.release(lease)

    asyncio.run(scenario())


def test_timeout_during_preflight_cannot_dispatch_later_or_release_owner(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        entered, unblock = threading.Event(), threading.Event()
        original = wire.request

        def blocked(method, path, body, timeout_ms):
            if path.endswith("/screenshot"):
                entered.set()
                unblock.wait(2)
            return original(method, path, body, timeout_ms)

        wire.request = blocked
        try:
            receipt = await device.execute(lease, replace(action(lease), timeout_ms=30), source)
            assert entered.is_set()
            assert receipt.status is ReceiptStatus.REJECTED
            with pytest.raises(PortError, match="in flight"):
                await device.release(lease)
            assert list(tmp_path.glob("*.lease"))
        finally:
            unblock.set()
        await asyncio.sleep(0.05)
        assert not any(c[1].endswith("/actions") for c in wire.calls)
        await device.release(lease)

    asyncio.run(scenario())


def test_canceled_mutation_keeps_exclusive_owner_until_worker_and_manual_recovery(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        entered, unblock = threading.Event(), threading.Event()
        original = wire.request

        def blocked(method, path, body, timeout_ms):
            if path.endswith("/actions"):
                entered.set()
                unblock.wait(2)
            return original(method, path, body, timeout_ms)

        wire.request = blocked
        task = asyncio.create_task(device.execute(lease, action(lease), source))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(PortError, match="in flight"):
                await device.release(lease)
            second = AppiumDevice("http://unused", tmp_path, wire=FakeWire())
            with pytest.raises(PortError, match="already leased"):
                await second.acquire("other", "serial", 1000)
        finally:
            unblock.set()
        await asyncio.sleep(0.05)
        with pytest.raises(PortError, match="manual recovery"):
            await device.release(lease)
        assert list(tmp_path.glob("*.lease"))

    asyncio.run(scenario())


def test_rotation_during_capture_is_failure(tmp_path):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        original = wire.request

        def rotates(method, path, body, timeout_ms):
            value = original(method, path, body, timeout_ms)
            if path.endswith("/screenshot"):
                wire.rotation = 90
            return value

        wire.request = rotates
        with pytest.raises(PortError, match="rotation changed"):
            await device.observe(lease, 1000)
        await device.release(lease)

    asyncio.run(scenario())


def test_appium_without_the_android_sdk_tells_the_operator_what_to_fix(tmp_path):
    class Wire(FakeWire):
        def request(self, method, path, body, timeout_ms):
            # Wording of appium-adb when the Appium process has no SDK path.
            raise CommandError(
                "appium: command failure",
                "An unknown server-side error occurred while processing the command. "
                "Original error: Neither ANDROID_HOME nor ANDROID_SDK_ROOT environment "
                "variable was exported.",
            )

    async def scenario():
        device = AppiumDevice("http://unused", tmp_path, wire=Wire())
        with pytest.raises(OperatorActionRequired) as error:
            await device.acquire("run", "device-A", 1000)
        message = str(error.value)
        assert message.startswith("android: ") and "ANDROID_HOME" in message
        assert "unknown server-side error" not in message

    asyncio.run(scenario())
