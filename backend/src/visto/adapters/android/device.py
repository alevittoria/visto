"""UiAutomator2 capabilities, screenshot capture and W3C command translation."""

import base64
from pathlib import Path
from urllib.parse import quote

from visto.adapters.appium.png import png_size
from visto.adapters.appium.session import AppiumSession
from visto.adapters.appium.wire import MAX_RESPONSE, HttpWire, Wire
from visto.application.ports import PortError
from visto.application.runtime import utc_now
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import CapturedImage


class AppiumDevice(AppiumSession):
    version = "appium-wire-v1"

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
            "android",
            self.version,
            wire if wire is not None else HttpWire(server_url),
            lease_directory,
            request_timeout_ms=request_timeout_ms,
            cleanup_timeout_ms=cleanup_timeout_ms,
        )

    def capabilities(self, device_id):
        # https://github.com/appium/appium-uiautomator2-driver#capabilities
        return {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:udid": device_id,
            "appium:noReset": True,
            "appium:fullReset": False,
            "appium:autoLaunch": False,
            "appium:shouldTerminateApp": False,
            "appium:skipLogcatCapture": True,
            "appium:adbExecTimeout": self._request_timeout,
            "appium:uiautomator2ServerReadTimeout": self._request_timeout,
            "appium:newCommandTimeout": 120,
        }

    def diagnose(self, message):
        # appium-adb refuses every session when the Appium process has no SDK path.
        if "Neither ANDROID_HOME nor ANDROID_SDK_ROOT" in message:
            return (
                "Appium cannot find the Android SDK; export ANDROID_HOME for the Appium "
                "process, restart Appium and recover the retained device lease"
            )
        return None

    def _rotation(self, lease, deadline, stop):
        # AndroidDriver 14.2.0 proxies this native UiAutomator2 route; the generic
        # Appium /appium/device/rotation route is unsupported by our pinned stack.
        # Versioned source and compatibility evidence: docs/references.md.
        result = self._request("GET", self._path(lease, "/rotation"), None, deadline, stop)
        if not isinstance(result, dict) or type(result.get("z")) is not int:
            raise PortError(f"{self._component}: invalid rotation response")
        rotation = result["z"]
        if rotation not in (0, 90, 180, 270):
            raise PortError(f"{self._component}: unsupported rotation")
        return rotation

    def capture(self, lease, deadline, stop):
        before = self._rotation(lease, deadline, stop)
        encoded = self._request("GET", self._path(lease, "/screenshot"), None, deadline, stop)
        try:
            if not isinstance(encoded, str) or len(encoded) > MAX_RESPONSE:
                raise ValueError
            content = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise PortError(f"{self._component}: malformed screenshot encoding") from None
        width, height = png_size(content, self._component)
        after = self._rotation(lease, deadline, stop)
        if before != after:
            raise PortError(f"{self._component}: rotation changed during screenshot")
        return CapturedImage(lease, utc_now(), content, "image/png", width, height, after)

    def translate(self, command, lease, deadline, stop):
        # https://www.w3.org/TR/webdriver2/#perform-actions
        if isinstance(command, (Tap, LongPress, Swipe)):
            x, y = (
                (command.start_x, command.start_y)
                if isinstance(command, Swipe)
                else (command.x, command.y)
            )
            actions = [
                {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
            ]
            if isinstance(command, LongPress):
                actions.append({"type": "pause", "duration": command.duration_ms})
            if isinstance(command, Swipe):
                actions.append(
                    {
                        "type": "pointerMove",
                        "duration": command.duration_ms,
                        "origin": "viewport",
                        "x": command.end_x,
                        "y": command.end_y,
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
        # TypeText targets the focused element, resolved read-only before dispatch.
        # https://w3c.github.io/webdriver/#element-send-keys (UiAutomator2 adds `replace`).
        if isinstance(command, TypeText):
            element = self._focused_element(lease, deadline, stop)
            return f"/element/{quote(element, safe='')}/value", {
                "text": command.text,
                "replace": True,
            }
        # https://github.com/appium/appium-uiautomator2-driver#mobile-presskey
        # Android KeyEvent: KEYCODE_HOME 3, KEYCODE_BACK 4, KEYCODE_ENTER 66.
        if isinstance(command, (Back, Home, Enter)):
            keycode = {Back: 4, Home: 3, Enter: 66}[type(command)]
            return "/execute/sync", {"script": "mobile: pressKey", "args": [{"keycode": keycode}]}
        raise PortError(f"{self._component}: unsupported command")
