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
from visto.adapters.ios.signing import IOSSigning
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


async def prepared(tmp_path, wire=None, signing=None):
    wire = wire or FakeWire()
    device = XCUITestDevice(
        "http://127.0.0.1:4723", tmp_path, signing=signing or IOSSigning(), wire=wire
    )
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


def test_signing_capabilities_appear_only_when_configured(tmp_path):
    signing = IOSSigning(
        team_id="TEAM123456",
        signing_id="Apple Development",
        wda_bundle_id="test.visto.WebDriverAgentRunner",
        prebuilt_wda=True,
        wda_derived_data="~/DerivedData/WebDriverAgent-test",
    )

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

        configured, other, second_lease, _ = await prepared(tmp_path, signing=signing)
        caps = other.calls[0][2]["capabilities"]["alwaysMatch"]
        assert caps["appium:xcodeOrgId"] == signing.team_id
        assert caps["appium:xcodeSigningId"] == signing.signing_id
        assert caps["appium:updatedWDABundleId"] == signing.wda_bundle_id
        # A run never rebuilds WebDriverAgent; installing it is an operator pre-step.
        assert caps["appium:usePrebuiltWDA"] is True
        # The prebuilt runner is looked up where the operator built it, not where the
        # driver's resolved project path would place it.
        assert caps["appium:derivedDataPath"] == str(
            Path("~/DerivedData/WebDriverAgent-test").expanduser()
        )
        await configured.release(second_lease)

    asyncio.run(scenario())


def test_ios_capabilities_ignore_environment(monkeypatch):
    monkeypatch.setenv("VISTO_IOS_TEAM_ID", "ENVTEAM")
    monkeypatch.setenv("VISTO_IOS_PREBUILT_WDA", "1")
    device = XCUITestDevice(
        "http://127.0.0.1:4723", Path("leases"), signing=IOSSigning(team_id="T")
    )
    capabilities = device.capabilities("udid")
    assert capabilities["appium:xcodeOrgId"] == "T"
    assert "appium:usePrebuiltWDA" not in capabilities


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


def test_unknown_device_refusal_tells_the_operator_to_connect_the_phone_by_cable(tmp_path):
    device = XCUITestDevice("http://unused", tmp_path)
    hint = device.diagnose("Unknown device or simulator UDID: '00008000-000A000A00000000'")
    assert "USB cable" in hint and "tunnel" in hint
    assert "00008000" not in hint
    assert device.diagnose("Something else failed") is None


def test_webdriveragent_launch_failure_points_to_signing_and_the_build_result(tmp_path):
    device = XCUITestDevice("http://unused", tmp_path)
    hint = device.diagnose(
        "Unable to launch WebDriverAgent. Original error: xcodebuild failed with code 65."
        " /private/path/to/build"
    )
    assert "Signing identity" in hint and "Apple Development" in hint
    assert "xcodebuild" in hint and "iOS setup" in hint
    assert "/private/path" not in hint and "65" not in hint


def test_the_ios_tunnel_is_prepared_for_the_phone_before_its_session_is_requested(tmp_path):
    wire = FakeWire()
    seen = []

    def prepare(udid, timeout_s):
        seen.append((udid, timeout_s, len(wire.calls)))

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire, prepare=prepare)
        lease = await device.acquire("run", "device-A", 3000)
        await device.release(lease)

    asyncio.run(scenario())
    assert seen and seen[0][0] == "device-A" and seen[0][2] == 0
    assert seen[0][1] == 1.5  # Half of the 3000 ms startup budget.


def test_a_failing_preparation_does_not_stop_the_session_attempt(tmp_path):
    wire = FakeWire()

    def prepare(udid, timeout_s):
        raise RuntimeError("tunnel trouble")

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire, prepare=prepare)
        lease = await device.acquire("run", "device-A", 3000)
        await device.release(lease)

    asyncio.run(scenario())
    assert any(call[1] == "/session" for call in wire.calls)


from visto.adapters.appium.wire import CommandError  # noqa: E402
from visto.application.ports import OperatorActionRequired  # noqa: E402

# What a WebDriverAgent left running by an earlier Appium answers once its test
# session is gone; app and device names are not part of these answers.
STALE_RECT = (
    "The previously found element \"Application 'local.pid.0'\" is not present in the"
    " current view anymore. Original error: Application local.pid.0 is not running"
)
UNAUTHORISED = (
    'Error Domain=XCTDaemonErrorDomain Code=41 "Not authorized for performing UI testing actions."'
)


class StaleRunnerWire(FakeWire):
    """Appium reuses a stale runner until a session asks for a new one, which stays."""

    def __init__(self, message=STALE_RECT, *, always=False):
        super().__init__()
        self.message = message
        self.always = always
        self.replaced = False

    def request(self, method, path, body, timeout_ms):
        if path == "/session" and body["capabilities"]["alwaysMatch"].get("appium:useNewWDA"):
            self.replaced = True
        if method == "GET" and path.endswith("/window/rect") and (self.always or not self.replaced):
            self.calls.append((method, path, body, timeout_ms))
            raise CommandError("appium: command failure", self.message)
        return super().request(method, path, body, timeout_ms)


def created_with(wire):
    return [
        call[2]["capabilities"]["alwaysMatch"].get("appium:useNewWDA")
        for call in wire.calls
        if call[1] == "/session"
    ]


@pytest.mark.parametrize("message", [STALE_RECT, UNAUTHORISED])
def test_a_stale_webdriveragent_is_replaced_once_and_the_new_session_is_used(tmp_path, message):
    wire = StaleRunnerWire(message)

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
        lease = await device.acquire("run", "device-A", 3000)
        assert len(list(tmp_path.glob("*.lease"))) == 1
        await device.release(lease)
        # The next run starts normally again: a new runner is not forced every time.
        await device.release(await device.acquire("run-2", "device-A", 3000))

    asyncio.run(scenario())
    assert created_with(wire) == [None, True, None]
    assert [c[0] for c in wire.calls].count("DELETE") == 3


def test_a_runner_that_stays_unauthorised_ends_with_an_explicit_hint(tmp_path):
    wire = StaleRunnerWire(UNAUTHORISED, always=True)

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
        with pytest.raises(OperatorActionRequired) as error:
            await device.acquire("run", "device-A", 3000)
        return str(error.value)

    message = asyncio.run(scenario())
    assert message.startswith("ios: ") and "UI Automation" in message
    assert "XCTDaemonErrorDomain" not in message
    assert created_with(wire) == [None, True]
    assert not list(tmp_path.glob("*.lease"))


def test_an_otherwise_unusable_session_is_not_retried(tmp_path):
    wire = FakeWire()
    wire.fail_startup = True

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
        with pytest.raises(PortError, match="session started but is unusable"):
            await device.acquire("run", "device-A", 3000)

    asyncio.run(scenario())
    assert created_with(wire) == [None]


@pytest.mark.parametrize("message", [STALE_RECT, UNAUTHORISED])
def test_stale_runner_answers_get_no_hint_once_the_session_is_in_use(tmp_path, message):
    # Mid-run, "is not running" may be the app under test that crashed: no runner hint.
    assert XCUITestDevice("http://unused", tmp_path).diagnose(message) is None


def test_a_stale_session_that_cannot_be_deleted_is_not_retried_and_stays_leased(tmp_path):
    wire = StaleRunnerWire(UNAUTHORISED)
    wire.fail_delete = True

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
        with pytest.raises(PortError, match="manual recovery may be required"):
            await device.acquire("run", "device-A", 3000)

    asyncio.run(scenario())
    assert created_with(wire) == [None]
    assert len(list(tmp_path.glob("*.lease"))) == 1


def test_no_retry_is_attempted_without_time_left(tmp_path, monkeypatch):
    wire = StaleRunnerWire(UNAUTHORISED)
    budgets = iter([3000, 3000])
    monkeypatch.setattr(XCUITestDevice, "_ms_left", staticmethod(lambda d: next(budgets, 0)))

    async def scenario():
        device = XCUITestDevice("http://127.0.0.1:4723", tmp_path, wire=wire)
        with pytest.raises(OperatorActionRequired) as error:
            await device.acquire("run", "device-A", 3000)
        return str(error.value)

    message = asyncio.run(scenario())
    assert created_with(wire) == [None] and "UI Automation" in message
