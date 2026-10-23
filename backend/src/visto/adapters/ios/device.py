"""XCUITest capabilities, screenshot capture in points and W3C command translation."""

import asyncio
import base64
import os
import time
from pathlib import Path
from urllib.parse import quote

from visto.adapters.appium.png import png_size
from visto.adapters.appium.session import AppiumSession
from visto.adapters.appium.wire import MAX_RESPONSE, HttpWire, Wire
from visto.adapters.ios.geometry import Frame, frame, to_points
from visto.application.ports import PortError
from visto.application.runtime import utc_now
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import CapturedImage, DeviceLease

# WebDriverAgent reports the interface orientation in the same vocabulary as Android.
ROTATIONS = (0, 90, 180, 270)
# Duration of the left-edge back gesture; long enough for iOS to recognise a drag.
BACK_SWIPE_MS = 300
# WebDriverAgent signing values; secrets, so they are read here and never logged.
SIGNING = (
    ("appium:xcodeOrgId", "VISTO_IOS_TEAM_ID"),
    ("appium:xcodeSigningId", "VISTO_IOS_SIGNING_ID"),
    ("appium:updatedWDABundleId", "VISTO_IOS_WDA_BUNDLE_ID"),
)
_DISABLED = ("", "0", "false", "no")


def _setting(name: str) -> str:
    return os.environ.get(name, "").strip()


class XCUITestDevice(AppiumSession):
    version = "appium-xcuitest-v1"

    def __init__(
        self,
        server_url: str,
        lease_directory: Path,
        *,
        request_timeout_ms: int = 30000,
        cleanup_timeout_ms: int = 5000,
        wire: Wire | None = None,
    ):
        super().__init__(
            "ios",
            self.version,
            wire if wire is not None else HttpWire(server_url),
            lease_directory,
            request_timeout_ms=request_timeout_ms,
            cleanup_timeout_ms=cleanup_timeout_ms,
        )
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
        # A run never builds WebDriverAgent; building and installing it is an operator
        # pre-step, and the operator declares it by setting this variable.
        if _setting("VISTO_IOS_PREBUILT_WDA").lower() not in _DISABLED:
            capabilities["appium:usePrebuiltWDA"] = True
        # The driver opens WebDriverAgent by its resolved path, so Xcode's default
        # derived data for a build made through a symlinked path is not found.
        derived_data = _setting("VISTO_IOS_WDA_DERIVED_DATA")
        if derived_data:
            capabilities["appium:derivedDataPath"] = str(Path(derived_data).expanduser())
        for capability, variable in SIGNING:
            value = _setting(variable)
            if value:
                capabilities[capability] = value
        return capabilities

    async def acquire(self, run_id: str, device_id: str, timeout_ms: int) -> DeviceLease:
        """Confirm the created session answers before handing the lease out."""
        started = time.monotonic()
        lease = await super().acquire(run_id, device_id, timeout_ms)
        remaining = timeout_ms - int((time.monotonic() - started) * 1000)

        def confirm(deadline, stop):
            self._owned(lease)
            self._window(lease, deadline, stop)

        try:
            if remaining < 1:
                raise PortError(f"{self._component}: session startup budget exhausted")
            await self._run(confirm, remaining)
        except asyncio.CancelledError:
            raise  # Cancellation keeps the marker: the remote session may exist.
        except Exception:
            await self._reconcile(lease)  # Always raises.
        return lease

    async def _reconcile(self, lease) -> None:
        """At most one bounded delete of a session that was created but is not usable.

        Always raises: the marker only goes when that delete is certain. A confirmation
        worker still in flight blocks the delete before it is sent, which is the same
        fail-closed outcome as a delete that failed: the marker is retained.
        """
        try:
            await self.release(lease)
        except Exception:
            raise PortError(
                f"{self._component}: session started but is unusable;"
                " manual recovery may be required"
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
