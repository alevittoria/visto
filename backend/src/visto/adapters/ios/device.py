"""XCUITest capabilities, screenshot capture in points and W3C command translation."""

import asyncio
import base64
import logging
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from visto.adapters.appium.png import png_size
from visto.adapters.appium.session import AppiumSession
from visto.adapters.appium.wire import MAX_RESPONSE, HttpWire, Wire
from visto.adapters.ios.geometry import Frame, frame, to_points
from visto.adapters.ios.signing import IOSSigning
from visto.application.ports import OperatorActionRequired, PortError
from visto.application.runtime import utc_now
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import CapturedImage, DeviceLease

_LOG = logging.getLogger(__name__)

# WebDriverAgent reports the interface orientation in the same vocabulary as Android.
ROTATIONS = (0, 90, 180, 270)
# Duration of the left-edge back gesture; long enough for iOS to recognise a drag.
BACK_SWIPE_MS = 300

# Immutable default: no signing values, no prebuilt-WDA claim.
UNSIGNED = IOSSigning()

# Answers of a WebDriverAgent that an earlier Appium left running on the phone after
# its test session ended (for example when `visto start` stopped): the driver reuses it
# and it can no longer drive the UI. Recognised only while a new session is confirmed:
# later, "is not running" may be the app under test that stopped.
STALE_RUNNER_MARKS = (
    ("Not authorized for performing UI testing actions",),
    ("previously found element", "is not running"),
)
STALE_RUNNER_HINT = (
    "WebDriverAgent on the phone is not authorised for UI testing; close the"
    " WebDriverAgent app on the phone, check that UI Automation is enabled in the"
    " phone's Developer settings, and start the run again"
)


class StaleRunner(OperatorActionRequired):
    """The session reached a WebDriverAgent that cannot drive the UI any more."""


class XCUITestDevice(AppiumSession):
    version = "appium-xcuitest-v1"

    def __init__(
        self,
        server_url: str,
        lease_directory: Path,
        *,
        signing: IOSSigning = UNSIGNED,
        request_timeout_ms: int = 30000,
        cleanup_timeout_ms: int = 5000,
        wire: Wire | None = None,
        prepare: Callable[[str, float], object] | None = None,
    ):
        super().__init__(
            "ios",
            self.version,
            wire if wire is not None else HttpWire(server_url),
            lease_directory,
            request_timeout_ms=request_timeout_ms,
            cleanup_timeout_ms=cleanup_timeout_ms,
        )
        self._signing = signing
        # Called with (device id, seconds) before a session is requested: `visto start`
        # passes one that brings the iOS tunnel back for a phone plugged in later.
        self._prepare = prepare
        # Set for one retry only: asks the driver to replace the runner on the phone.
        self._new_runner = False
        # True while a new session's first request runs: the only time a stale runner
        # can be told apart from the app under test.
        self._confirming = False
        # Point geometry of the last capture, paired with the image it was derived from:
        # a frame can never convert coordinates for a different screenshot.
        self._frame: tuple[CapturedImage, Frame] | None = None

    def capabilities(self, device_id):
        # https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/
        capabilities = {
            "platformName": "iOS",
            "appium:automationName": "XCUITest",
            "appium:udid": device_id,
            "appium:noReset": True,
            "appium:fullReset": False,
            "appium:autoLaunch": False,
            "appium:shouldTerminateApp": False,
            "appium:newCommandTimeout": 120,
        }
        # Signing and the prebuilt-WDA flag come from the stored settings; a run never
        # builds WebDriverAgent.
        capabilities.update(self._signing.capabilities())
        if self._new_runner:
            # The driver quits and uninstalls the runner it would otherwise reuse, then
            # builds and starts a new one (driver source; see docs/references.md).
            capabilities["appium:useNewWDA"] = True
        return capabilities

    def diagnose(self, message):
        # The driver lists no such device: the phone is not on USB, or no tunnel runs.
        if "Unknown device or simulator UDID" in message:
            return (
                "Appium cannot see the phone; connect it with a USB cable, unlock it and"
                " accept the trust prompt, then start the run again (from the console,"
                " Visto starts the iOS tunnel for it unless it runs with --no-ios-tunnel)"
            )
        # The driver only reports xcodebuild's exit code; the reason is in its result.
        if "Unable to launch WebDriverAgent" in message:
            return (
                "WebDriverAgent could not be built or installed on the phone; check the"
                " signing values in Settings (Signing identity is the type, such as"
                " 'Apple Development', not the full certificate name) and the trust prompt"
                " on the phone, then read the xcodebuild result described in the iOS setup"
                " guide"
            )
        if self._confirming and any(
            all(part in message for part in mark) for mark in STALE_RUNNER_MARKS
        ):
            return STALE_RUNNER_HINT
        return None

    async def acquire(self, run_id: str, device_id: str, timeout_ms: int) -> DeviceLease:
        """Confirm the created session answers before handing the lease out."""
        started = time.monotonic()
        if self._prepare is not None:
            # At most half the startup budget: the session needs the rest.
            try:
                await asyncio.to_thread(self._prepare, device_id, timeout_ms / 2000)
            except Exception:
                # Best effort: without a tunnel the session fails with its own hint.
                _LOG.warning("The iOS tunnel could not be prepared", exc_info=True)
        deadline = started + timeout_ms / 1000
        try:
            return await self._open(run_id, device_id, deadline)
        except StaleRunner:
            # Once per run, and only after the stale session was deleted and its lease
            # released: session creation drives no app, so this repeats no app action.
            if self._ms_left(deadline) < 1:
                raise
            self._new_runner = True
            try:
                return await self._open(run_id, device_id, deadline)
            finally:
                self._new_runner = False

    @staticmethod
    def _ms_left(deadline: float) -> int:
        return int((deadline - time.monotonic()) * 1000)

    async def _open(self, run_id: str, device_id: str, deadline: float) -> DeviceLease:
        lease = await super().acquire(run_id, device_id, max(1, self._ms_left(deadline)))
        remaining = self._ms_left(deadline)

        def confirm(deadline, stop):
            self._owned(lease)
            self._confirming = True
            try:
                self._window(lease, deadline, stop)
            finally:
                self._confirming = False

        try:
            if remaining < 1:
                raise PortError(f"{self._component}: session startup budget exhausted")
            await self._run(confirm, remaining)
        except asyncio.CancelledError:
            raise  # Cancellation keeps the marker: the remote session may exist.
        except Exception as error:
            await self._reconcile(lease, error)  # Always raises.
        return lease

    async def _reconcile(self, lease, error: Exception) -> None:
        """At most one bounded delete of a session that was created but is not usable.

        Always raises: the marker only goes when that delete is certain. A confirmation
        worker still in flight blocks the delete before it is sent, which is the same
        fail-closed outcome as a delete that failed: the marker is retained. Once the
        device is released, a recognised cause keeps its fixed operator hint.
        """
        try:
            await self.release(lease)
        except Exception:
            raise PortError(
                f"{self._component}: session started but is unusable;"
                " manual recovery may be required"
            ) from None
        if isinstance(error, OperatorActionRequired):
            hint = str(error)
            raise (StaleRunner if hint.endswith(STALE_RUNNER_HINT) else OperatorActionRequired)(
                hint
            ) from None
        raise PortError(f"{self._component}: session started but is unusable; device released")

    async def release(self, lease) -> None:
        """Holds no screenshot bytes past a release, successful or not.

        Screenshot pixels are private data, and a retained lease awaiting manual
        recovery has no use for the geometry of a screen nobody will act on.
        """
        try:
            await super().release(lease)
        finally:
            self._frame = None

    def _number(self, value, label):
        """Accept WebDriverAgent's integral sizes, which may arrive as JSON floats."""
        if type(value) is int:
            return value
        if type(value) is float and value.is_integer():
            return int(value)
        raise PortError(f"{self._component}: invalid {label} response")

    def _rotation(self, lease, deadline, stop):
        # WDA's /rotation keeps all four interface orientations apart, while its
        # /orientation collapses them to PORTRAIT/LANDSCAPE; neither route is in the
        # XCUITest driver's no-proxy list, so both reach WDA unchanged.
        # Versioned source and evidence: docs/references.md.
        result = self._request("GET", self._path(lease, "/rotation"), None, deadline, stop)
        rotation = self._number(
            result.get("z") if isinstance(result, dict) else None, "orientation"
        )
        if rotation not in ROTATIONS:
            raise PortError(f"{self._component}: unsupported orientation")
        return rotation

    def _window(self, lease, deadline, stop):
        """Window size in points: the gesture coordinate space, not screenshot pixels."""
        # https://www.w3.org/TR/webdriver2/#get-window-rect
        result = self._request("GET", self._path(lease, "/window/rect"), None, deadline, stop)
        result = result if isinstance(result, dict) else {}
        width = self._number(result.get("width"), "window size")
        height = self._number(result.get("height"), "window size")
        # A session that reports no window cannot be driven; `frame` owns the scale.
        if min(width, height) < 1:
            raise PortError(f"{self._component}: invalid window size response")
        return width, height

    def capture(self, lease, deadline, stop):
        self._frame = None  # No partial geometry survives a failed capture.
        before = self._rotation(lease, deadline, stop)
        encoded = self._request("GET", self._path(lease, "/screenshot"), None, deadline, stop)
        try:
            if not isinstance(encoded, str) or len(encoded) > MAX_RESPONSE:
                raise ValueError
            content = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise PortError(f"{self._component}: malformed screenshot encoding") from None
        width, height = png_size(content, self._component)
        point_width, point_height = self._window(lease, deadline, stop)
        after = self._rotation(lease, deadline, stop)
        # Refuse before deriving any geometry: pixels and points read in two different
        # orientations would place every converted coordinate on the wrong axis.
        if before != after:
            raise PortError(f"{self._component}: orientation changed during screenshot")
        image = CapturedImage(lease, utc_now(), content, "image/png", width, height, after)
        self._frame = (image, frame(width, height, point_width, point_height))
        return image

    def _geometry(self) -> Frame:
        """The frame of the core's current capture; any other pairing is refused."""
        stored = self._frame
        if stored is None or stored[0] is not self._capture:
            raise PortError(f"{self._component}: no screen geometry for the current capture")
        return stored[1]

    def _gesture(self, command, geometry):
        """Start, optional move `(x, y, duration)` and hold, all in points."""
        if isinstance(command, Back):
            # iOS has no back button: the system gesture is a drag from the left edge.
            # It does not navigate on every screen, and the executor claims only that
            # the gesture was dispatched.
            middle = geometry.point_height // 2
            return (0, middle), (geometry.point_width // 2, middle, BACK_SWIPE_MS), 0
        if isinstance(command, Swipe):
            start = to_points(geometry, command.start_x, command.start_y)
            end = to_points(geometry, command.end_x, command.end_y)
            return start, (*end, command.duration_ms), 0
        start = to_points(geometry, command.x, command.y)
        return start, None, command.duration_ms if isinstance(command, LongPress) else 0

    def translate(self, command, lease, deadline, stop):
        # https://www.w3.org/TR/webdriver2/#perform-actions; the XCUITest driver passes
        # /actions to WebDriverAgent, which works in points, so every screenshot pixel
        # goes through to_points first.
        if isinstance(command, (Tap, LongPress, Swipe, Back)):
            start, move, hold = self._gesture(command, self._geometry())
            actions = [
                {
                    "type": "pointerMove",
                    "duration": 0,
                    "origin": "viewport",
                    "x": start[0],
                    "y": start[1],
                },
                {"type": "pointerDown", "button": 0},
            ]
            if hold:
                actions.append({"type": "pause", "duration": hold})
            if move is not None:
                actions.append(
                    {
                        "type": "pointerMove",
                        "duration": move[2],
                        "origin": "viewport",
                        "x": move[0],
                        "y": move[1],
                    }
                )
            actions.append({"type": "pointerUp", "button": 0})
            return "/actions", {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "finger",
                        "parameters": {"pointerType": "touch"},
                        "actions": actions,
                    }
                ]
            }
        # Both target the focused element, resolved read-only before dispatch; Enter is
        # a newline, which the iOS keyboard turns into its return key.
        # https://www.w3.org/TR/webdriver2/#element-send-keys (XCUITest sets the value).
        if isinstance(command, (TypeText, Enter)):
            element = self._focused_element(lease, deadline, stop)
            text = command.text if isinstance(command, TypeText) else "\n"
            return f"/element/{quote(element, safe='')}/value", {"text": text}
        # https://appium.github.io/appium-xcuitest-driver/latest/reference/execute-methods/
        if isinstance(command, Home):
            return "/execute/sync", {"script": "mobile: pressButton", "args": [{"name": "home"}]}
        raise PortError(f"{self._component}: unsupported command")
