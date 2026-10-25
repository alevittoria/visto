import asyncio
import base64
import hashlib
import shutil
import struct
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from visto.adapters.ios import XCUITestDevice
from visto.application.ports import PortError
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import Action, ArtifactRef, Observation, ReceiptStatus

# A 3x device: the screenshot is three times the reported window size in points.
PIXELS = (360, 780)
POINTS = (120, 260)


@pytest.fixture
def tmp_path():
    # Windows sandbox cannot reopen pytest's user-only (0o700) temp directories.
    root = Path(__file__).resolve().parents[2] / ".work" / "ios-device-tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid4().hex
    target.mkdir()
    try:
        yield target
    finally:
        if target.resolve().parent != root.resolve():
            raise ValueError("Refusing cleanup outside iOS device test directory")
        shutil.rmtree(target)


def png(width=PIXELS[0], height=PIXELS[1]):
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
        self.points = POINTS
        self.fail_create = False
        self.fail_startup = False
        self.fail_mutation = False
        self.fail_delete = False
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
        if self.fail_startup:
            # A session id was handed out, but the session answers nothing.
            raise PortError("session is not usable")
        if method == "GET" and path.endswith("/rotation"):
            return {"value": {"x": 0, "y": 0, "z": self.rotation}}
        if method == "GET" and path.endswith("/window/rect"):
            return {"value": {"x": 0, "y": 0, "width": self.points[0], "height": self.points[1]}}
        if method == "GET" and path.endswith("/screenshot"):
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
    device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
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


def action(lease, command=None):
    return Action(
        "action",
        "run",
        "decision",
        "obs",
        lease.lease_id,
        command if command is not None else Tap(300, 600),
        2000,
    )


def pointer(call):
    return call[2]["actions"][0]["actions"]


def test_session_capabilities_target_xcuitest_and_do_not_launch_an_app(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        caps = wire.calls[0][2]["capabilities"]["alwaysMatch"]
        assert caps["platformName"] == "iOS"
        assert caps["appium:automationName"] == "XCUITest"
        assert caps["appium:udid"] == "device-A"
        assert caps["appium:noReset"] is True
        assert caps["appium:fullReset"] is False
        assert caps["appium:autoLaunch"] is False
        assert caps["appium:shouldTerminateApp"] is False
        assert caps["appium:newCommandTimeout"] == 120
        # No app is installed, launched or terminated by a run.
        assert not any(key in caps for key in ("appium:app", "appium:bundleId"))
        assert (source.width, source.height, source.rotation) == (*PIXELS, 0)
        assert device.version == "appium-xcuitest-v1"
        await device.release(lease)
        assert not list(tmp_path.glob("*.lease"))
        # The released session keeps neither a capture nor its point geometry.
        assert device._frame is None

    asyncio.run(scenario())


def test_signing_capabilities_appear_only_when_configured(tmp_path, monkeypatch):
    signing = {
        "VISTO_IOS_TEAM_ID": "TEAM123456",
        "VISTO_IOS_SIGNING_ID": "Apple Development",
        "VISTO_IOS_WDA_BUNDLE_ID": "test.visto.WebDriverAgentRunner",
        "VISTO_IOS_PREBUILT_WDA": "1",
        "VISTO_IOS_WDA_DERIVED_DATA": "~/DerivedData/WebDriverAgent-test",
    }
    for name in signing:
        monkeypatch.delenv(name, raising=False)

    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        bare = wire.calls[0][2]["capabilities"]["alwaysMatch"]
        assert not any(
            key in bare
            for key in (
                "appium:xcodeOrgId",
                "appium:xcodeSigningId",
                "appium:updatedWDABundleId",
                "appium:usePrebuiltWDA",
                "appium:derivedDataPath",
            )
        )
        await device.release(lease)

        for name, value in signing.items():
            monkeypatch.setenv(name, value)
        configured, other, second_lease, _ = await prepared(tmp_path)
        caps = other.calls[0][2]["capabilities"]["alwaysMatch"]
        assert caps["appium:xcodeOrgId"] == signing["VISTO_IOS_TEAM_ID"]
        assert caps["appium:xcodeSigningId"] == signing["VISTO_IOS_SIGNING_ID"]
        assert caps["appium:updatedWDABundleId"] == signing["VISTO_IOS_WDA_BUNDLE_ID"]
        # A run never rebuilds WebDriverAgent; installing it is an operator pre-step.
        assert caps["appium:usePrebuiltWDA"] is True
        # The prebuilt runner is looked up where the operator built it, not where the
        # driver's resolved project path would place it.
        assert caps["appium:derivedDataPath"] == str(
            Path("~/DerivedData/WebDriverAgent-test").expanduser()
        )
        await configured.release(second_lease)

    asyncio.run(scenario())


def test_tap_is_dispatched_in_points_not_pixels(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, Tap(300, 600)), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        call = wire.calls[-1]
        assert call[0] == "POST" and call[1].endswith("/actions")
        assert call[2]["actions"][0]["parameters"] == {"pointerType": "touch"}
        assert pointer(call)[0] == {
            "type": "pointerMove",
            "duration": 0,
            "origin": "viewport",
            "x": 100,
            "y": 200,
        }
        assert pointer(call)[-1] == {"type": "pointerUp", "button": 0}
        # No screenshot pixel reaches the wire.
        assert "300" not in str(call[2]) and "600" not in str(call[2])
        await device.release(lease)

    asyncio.run(scenario())


def test_back_is_dispatched_as_a_swipe_from_the_left_edge(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, Back()), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        call = wire.calls[-1]
        assert call[0] == "POST" and call[1].endswith("/actions")
        middle = POINTS[1] // 2
        assert pointer(call) == [
            {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": 0, "y": middle},
            {"type": "pointerDown", "button": 0},
            {
                "type": "pointerMove",
                "duration": 300,
                "origin": "viewport",
                "x": POINTS[0] // 2,
                "y": middle,
            },
            {"type": "pointerUp", "button": 0},
        ]
        await device.release(lease)

    asyncio.run(scenario())


def test_a_swipe_converts_both_of_its_ends_to_points(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, Swipe(300, 600, 30, 60, 500)), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        assert pointer(wire.calls[-1]) == [
            {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": 100, "y": 200},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": 500, "origin": "viewport", "x": 10, "y": 20},
            {"type": "pointerUp", "button": 0},
        ]
        await device.release(lease)

    asyncio.run(scenario())


def test_a_long_press_holds_at_the_converted_point(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, LongPress(300, 600, 900)), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        assert pointer(wire.calls[-1]) == [
            {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": 100, "y": 200},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": 900},
            {"type": "pointerUp", "button": 0},
        ]
        await device.release(lease)

    asyncio.run(scenario())


def test_without_a_stored_frame_nothing_can_be_converted(tmp_path):
    async def scenario():
        device = XCUITestDevice("http://unused", tmp_path, wire=FakeWire())
        lease = await device.acquire("run", "device-A", 2000)
        with pytest.raises(PortError, match="no screen geometry"):
            device._geometry()  # Nothing has been observed yet.
        await device.release(lease)

    asyncio.run(scenario())


def test_a_frame_of_another_capture_cannot_convert_coordinates(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        assert (await device.execute(lease, action(lease), source)).status is (
            ReceiptStatus.COMPLETED
        )
        # The pre-dispatch capture replaced the frame, so it no longer belongs to the
        # core's current capture and cannot serve a later command.
        assert device._frame is not None and device._frame[0] is not device._capture
        with pytest.raises(PortError, match="no screen geometry"):
            device._geometry()
        await device.release(lease)
        assert device._frame is None

    asyncio.run(scenario())


def test_home_uses_the_press_button_script(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, Home()), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        call = wire.calls[-1]
        assert call[0] == "POST" and call[1].endswith("/execute/sync")
        assert call[2] == {"script": "mobile: pressButton", "args": [{"name": "home"}]}
        await device.release(lease)

    asyncio.run(scenario())


def test_enter_sends_a_newline_to_the_focused_element(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        receipt = await device.execute(lease, action(lease, Enter()), source)
        assert receipt.status is ReceiptStatus.COMPLETED
        call = wire.calls[-1]
        assert call[0] == "POST" and call[1].endswith("/element/field%2F1/value")
        assert call[2] == {"text": "\n"}
        await device.release(lease)

    asyncio.run(scenario())


def test_type_text_without_focus_is_rejected_and_types_nothing(tmp_path):
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


def test_orientation_change_during_capture_is_an_error(tmp_path):
    async def scenario():
        device, wire, lease, _ = await prepared(tmp_path)
        original = wire.request

        def rotates(method, path, body, timeout_ms):
            value = original(method, path, body, timeout_ms)
            if path.endswith("/screenshot"):
                wire.rotation = 90
            return value

        wire.request = rotates
        with pytest.raises(PortError, match="orientation changed"):
            await device.observe(lease, 1000)
        await device.release(lease)

    asyncio.run(scenario())


def test_inconsistent_scale_refuses_the_device(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.points = (POINTS[0], 200)  # The window size disagrees with the screenshot.
        device = XCUITestDevice("http://unused", tmp_path, wire=wire)
        lease = await device.acquire("run", "device-A", 3000)
        with pytest.raises(PortError, match="inconsistent screen scale"):
            await device.observe(lease, 1000)
        assert not any(c[0] == "POST" and c[1] != "/session" for c in wire.calls)
        await device.release(lease)

    asyncio.run(scenario())


def test_android_serial_fails_closed_and_keeps_its_marker_so_the_device_stays_leased(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_create = True  # An Android serial is unknown to the XCUITest driver.
        device = XCUITestDevice("http://unused", tmp_path, wire=wire)
        with pytest.raises(PortError) as error:
            await device.acquire("run", "android-serial-A", 1000)
        assert "sensitive" not in str(error.value)
        assert len(list(tmp_path.glob("*.lease"))) == 1
        second = XCUITestDevice("http://unused", tmp_path, wire=FakeWire())
        with pytest.raises(PortError, match="already leased"):
            await second.acquire("other", "android-serial-A", 1000)

    asyncio.run(scenario())


def test_mutation_failure_after_dispatch_returns_uncertain(tmp_path):
    async def scenario():
        device, wire, lease, source = await prepared(tmp_path)
        wire.fail_mutation = True
        receipt = await device.execute(lease, action(lease), source)
        assert receipt.status is ReceiptStatus.UNCERTAIN
        assert "private" not in receipt.detail
        assert device._uncertain.is_set()
        assert len([c for c in wire.calls if c[1].endswith("/actions")]) == 1
        with pytest.raises(PortError, match="manual recovery"):
            await device.release(lease)
        assert list(tmp_path.glob("*.lease"))
        # A retained lease holds no screenshot bytes: pixels are private data.
        assert device._frame is None

    asyncio.run(scenario())


def test_a_session_created_despite_a_failed_startup_is_reconciled(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_startup = True
        device = XCUITestDevice("http://unused", tmp_path, wire=wire)
        with pytest.raises(PortError) as error:
            await device.acquire("run", "device-A", 2000)
        assert "manual recovery" not in str(error.value)
        deletes = [c for c in wire.calls if c[0] == "DELETE"]
        assert len(deletes) == 1 and "session%2Fwith%2Breserved" in deletes[0][1]
        assert not list(tmp_path.glob("*.lease"))
        # The device is free again: a later run can take it.
        second = XCUITestDevice("http://unused", tmp_path, wire=FakeWire())
        lease = await second.acquire("other", "device-A", 2000)
        await second.release(lease)

    asyncio.run(scenario())


def test_a_reconciliation_that_itself_fails_retains_the_marker(tmp_path):
    async def scenario():
        wire = FakeWire()
        wire.fail_startup = True
        wire.fail_delete = True
        device = XCUITestDevice("http://unused", tmp_path, wire=wire)
        with pytest.raises(PortError, match="manual recovery"):
            await device.acquire("run", "device-A", 2000)
        assert len([c for c in wire.calls if c[0] == "DELETE"]) == 1
        assert len(list(tmp_path.glob("*.lease"))) == 1
        second = XCUITestDevice("http://unused", tmp_path, wire=FakeWire())
        with pytest.raises(PortError, match="already leased"):
            await second.acquire("other", "device-A", 2000)

    asyncio.run(scenario())
