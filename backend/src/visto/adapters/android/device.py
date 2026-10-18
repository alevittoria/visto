"""Bounded W3C/Appium wire operations and fail-closed local device ownership."""

import asyncio
import base64
import hashlib
import http.client
import json
import math
import os
import struct
import threading
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlsplit
from uuid import uuid4

from visto.application.ports import PortError
from visto.application.runtime import utc_now
from visto.domain.commands import Back, Enter, Home, LongPress, Swipe, Tap, TypeText
from visto.domain.models import (
    Action,
    CapturedImage,
    DeviceLease,
    Observation,
    ReceiptStatus,
    TechnicalReceipt,
)

MAX_RESPONSE = 32 * 1024 * 1024


# https://w3c.github.io/webdriver/#elements
W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"


class _NoFocusedField(Exception):
    """TypeText was requested while no input element had focus."""


class Wire(Protocol):
    def request(self, method: str, path: str, body: dict | None, timeout_ms: int) -> dict: ...


class HttpWire:
    """No redirects, proxy discovery, raw error logging or automatic retries."""

    def __init__(self, server_url: str):
        parsed = urlsplit(server_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Expected an Appium HTTP(S) URL without credentials/query")
        self._url = parsed

    def request(self, method: str, path: str, body: dict | None, timeout_ms: int) -> dict:
        connection_class = (
            http.client.HTTPSConnection
            if self._url.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_class(self._url.hostname, self._url.port, timeout=timeout_ms / 1000)
        try:
            connection.request(
                method,
                self._url.path.rstrip("/") + path,
                body=None if body is None else json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE or response.status < 200 or response.status >= 300:
                raise PortError("android: Appium HTTP failure")
            result = json.loads(data)
            if not isinstance(result, dict) or "value" not in result:
                raise PortError("android: malformed Appium response")
            if isinstance(result["value"], dict) and "error" in result["value"]:
                raise PortError("android: Appium command failure")
            return result
        except (OSError, ValueError, http.client.HTTPException):
            raise PortError("android: Appium transport failure") from None
        finally:
            connection.close()


def _positive(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Expected positive integer milliseconds")
    return value


def _png_size(content: bytes) -> tuple[int, int]:
    """Check chunk framing/CRC; image interpretation belongs to the model."""
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        raise PortError("android: screenshot is not PNG")
    offset, dimensions, ended, image_data = 8, None, False, False
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        kind = content[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(content):
            break
        payload = content[offset + 8 : end - 4]
        checksum = struct.unpack(">I", content[end - 4 : end])[0]
        if zlib.crc32(kind + payload) != checksum:
            raise PortError("android: corrupt screenshot")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                raise PortError("android: invalid PNG header")
            dimensions = struct.unpack(">II", payload[:8])
        if kind == b"IDAT":
            image_data = True
        if kind == b"IEND":
            ended = length == 0 and end == len(content)
            break
        offset = end
    if not ended or not image_data or not dimensions or min(dimensions) < 1:
        raise PortError("android: incomplete screenshot")
    return dimensions


class AppiumDevice:
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
        self._wire = wire if wire is not None else HttpWire(server_url)
        self._directory = Path(lease_directory)
        self._request_timeout = _positive(request_timeout_ms)
        self._cleanup_timeout = _positive(cleanup_timeout_ms)
        self._lease: DeviceLease | None = None
        self._marker: Path | None = None
        self._token: str | None = None
        self._capture: CapturedImage | None = None
        self._pending: asyncio.Task | None = None
        self._active = threading.Event()
        self._used_sources: set[str] = set()
        self._uncertain = threading.Event()

    async def _run(self, operation: Callable, timeout_ms: int):
        """A late worker keeps its lease quarantined; it may never dispatch after timeout."""
        timeout_ms = _positive(timeout_ms)
        if self._active.is_set():
            raise PortError("android: operation still in flight; ownership retained")
        stop = threading.Event()
        deadline = time.monotonic() + timeout_ms / 1000
        self._active.set()

        def worker():
            try:
                return operation(deadline, stop)
            finally:
                # A canceled asyncio task is not proof its OS thread has stopped.
                self._active.clear()

        task = asyncio.create_task(asyncio.to_thread(worker))
        # Retrieve late exceptions without losing the in-flight ownership guard.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self._pending = task
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout_ms / 1000)
        except (TimeoutError, asyncio.CancelledError):
            stop.set()
            raise
        except PortError:
            raise
        except Exception:
            raise PortError("android: device operation failed") from None

    def _request(self, method, path, body, deadline, stop):
        remaining = math.floor((deadline - time.monotonic()) * 1000)
        if stop.is_set() or remaining < 1:
            raise PortError("android: operation deadline reached")
        try:
            response = self._wire.request(method, path, body, min(remaining, self._request_timeout))
            if not isinstance(response, dict) or "value" not in response:
                raise ValueError
            value = response["value"]
            if isinstance(value, dict) and "error" in value:
                raise ValueError
            return value
        except Exception:
            raise PortError("android: Appium request failed") from None

    def _owned(self, lease):
        if lease != self._lease or self._marker is None or self._token is None:
            raise PortError("android: lease is not owned by this adapter")
        try:
            data = json.loads(self._marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PortError("android: ownership marker unavailable") from None
        if data.get("token") != self._token:
            raise PortError("android: ownership marker changed")

    def _path(self, lease, suffix=""):
        return "/session/" + quote(lease.session_id, safe="") + suffix

    async def acquire(self, run_id: str, device_id: str, timeout_ms: int) -> DeviceLease:
        if not run_id.strip() or not device_id.strip():
            raise ValueError("Run and device identifiers are required")

        def acquire(deadline, stop):
            if self._marker is not None:
                raise PortError("android: adapter already owns or quarantines a device")
            self._directory.mkdir(parents=True, exist_ok=True)
            marker = self._directory / (hashlib.sha256(device_id.encode()).hexdigest() + ".lease")
            token = uuid4().hex
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise PortError(
                    "android: device already leased; manual recovery may be required"
                ) from None
            self._marker, self._token = marker, token
            # Retain this marker if startup fails: the remote session may already exist.
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {"token": token, "pid": os.getpid(), "run_id": run_id, "device_id": device_id},
                    stream,
                )
                stream.flush()
                os.fsync(stream.fileno())
            # https://github.com/appium/appium-uiautomator2-driver#capabilities
            capabilities = {
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
            result = self._request(
                "POST", "/session", {"capabilities": {"alwaysMatch": capabilities}}, deadline, stop
            )
            if not isinstance(result, dict) or not isinstance(result.get("sessionId"), str):
                raise PortError("android: malformed session response; ownership retained")
            self._lease = DeviceLease(token, run_id, device_id, result["sessionId"])
            return self._lease

        try:
            return await self._run(acquire, timeout_ms)
        except TimeoutError:
            raise PortError("android: session startup timed out; ownership retained") from None

    async def release(self, lease: DeviceLease) -> None:
        if self._lease is None and self._marker is None:
            return

        def release(deadline, stop):
            self._owned(lease)
            self._request("DELETE", self._path(lease), None, deadline, stop)
            self._owned(lease)
            if self._uncertain.is_set():
                raise PortError(
                    "android: uncertain mutation; ownership retained for manual recovery"
                )
            self._marker.unlink()
            self._lease = self._marker = self._token = self._capture = None
            self._used_sources.clear()

        try:
            await self._run(release, self._cleanup_timeout)
        except TimeoutError:
            raise PortError("android: session cleanup timed out; ownership retained") from None

    def _rotation(self, lease, deadline, stop):
        # AndroidDriver 14.2.0 proxies this native UiAutomator2 route; the generic
        # Appium /appium/device/rotation route is unsupported by our pinned stack.
        # Versioned source and compatibility evidence: docs/references.md.
        result = self._request("GET", self._path(lease, "/rotation"), None, deadline, stop)
        if not isinstance(result, dict) or type(result.get("z")) is not int:
            raise PortError("android: invalid rotation response")
        rotation = result["z"]
        if rotation not in (0, 90, 180, 270):
            raise PortError("android: unsupported rotation")
        return rotation

    def _image(self, lease, deadline, stop):
        before = self._rotation(lease, deadline, stop)
        encoded = self._request("GET", self._path(lease, "/screenshot"), None, deadline, stop)
        try:
            if not isinstance(encoded, str) or len(encoded) > MAX_RESPONSE:
                raise ValueError
            content = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise PortError("android: malformed screenshot encoding") from None
        width, height = _png_size(content)
        after = self._rotation(lease, deadline, stop)
        if before != after:
            raise PortError("android: rotation changed during screenshot")
        return CapturedImage(lease, utc_now(), content, "image/png", width, height, after)

    async def observe(self, lease: DeviceLease, timeout_ms: int) -> CapturedImage:
        def observe(deadline, stop):
            self._owned(lease)
            capture = self._image(lease, deadline, stop)
            self._capture = capture
            return capture

        try:
            return await self._run(observe, timeout_ms)
        except TimeoutError:
            raise PortError("android: screenshot timed out") from None

    def _validate_source(self, lease, action, source):
        self._owned(lease)
        if self._uncertain.is_set():
            raise PortError("android: uncertain session cannot dispatch more mutations")
        capture = self._capture
        if (
            capture is None
            or action.run_id != lease.run_id
            or source.run_id != lease.run_id
            or source.device_id != lease.device_id
            or source.session_id != lease.session_id
            or action.lease_id != lease.lease_id
            or source.lease_id != lease.lease_id
            or action.observation_id != source.observation_id
            or source.observation_id in self._used_sources
            or source.captured_at != capture.captured_at
            or (source.width, source.height, source.rotation)
            != (capture.width, capture.height, capture.rotation)
            or source.screenshot.sha256 != hashlib.sha256(capture.content).hexdigest()
            or source.screenshot.byte_length != len(capture.content)
        ):
            raise PortError("android: stale or mismatched source frame")
        command = action.command
        points = []
        if isinstance(command, Tap):
            points = [(command.x, command.y)]
        elif isinstance(command, LongPress):
            points = [(command.x, command.y)]
            if command.duration_ms > action.timeout_ms:
                raise PortError("android: long press exceeds command timeout")
        elif isinstance(command, Swipe):
            points = [(command.start_x, command.start_y), (command.end_x, command.end_y)]
            if command.duration_ms > action.timeout_ms:
                raise PortError("android: swipe exceeds command timeout")
        if any(not (0 <= x < source.width and 0 <= y < source.height) for x, y in points):
            raise PortError("android: coordinates outside source frame")

    def _focused_element(self, lease, deadline, stop):
        """Read-only lookup of the focused input; no mutation has been dispatched yet."""
        # https://github.com/appium/appium-uiautomator2-driver (GET /element/active)
        try:
            value = self._request("GET", self._path(lease, "/element/active"), None, deadline, stop)
        except PortError:
            raise _NoFocusedField from None
        element = value.get(W3C_ELEMENT, value.get("ELEMENT")) if isinstance(value, dict) else None
        if not isinstance(element, str) or not element or len(element) > 256:
            raise _NoFocusedField
        return element

    def _command(self, command):
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
        # TypeText targets the focused element; see _focused_element and execute().
        # https://w3c.github.io/webdriver/#element-send-keys (UiAutomator2 adds `replace`).
        if isinstance(command, TypeText):
            return "/element/{element}/value", {"text": command.text, "replace": True}
        # https://github.com/appium/appium-uiautomator2-driver#mobile-presskey
        # Android KeyEvent: KEYCODE_HOME 3, KEYCODE_BACK 4, KEYCODE_ENTER 66.
        if isinstance(command, (Back, Home, Enter)):
            keycode = {Back: 4, Home: 3, Enter: 66}[type(command)]
            return "/execute/sync", {"script": "mobile: pressKey", "args": [{"keycode": keycode}]}
        raise PortError("android: unsupported command")

    async def execute(
        self, lease: DeviceLease, action: Action, source: Observation
    ) -> TechnicalReceipt:
        dispatched = utc_now()
        mutation_started = threading.Event()

        def execute(deadline, stop):
            try:
                self._validate_source(lease, action, source)
                suffix, body = self._command(action.command)
                if isinstance(action.command, TypeText):
                    element = self._focused_element(lease, deadline, stop)
                    suffix = suffix.replace("{element}", quote(element, safe=""))
                current = self._image(lease, deadline, stop)
                if (current.width, current.height, current.rotation) != (
                    source.width,
                    source.height,
                    source.rotation,
                ):
                    raise PortError("android: device coordinate frame changed")
                self._owned(lease)
                if stop.is_set() or time.monotonic() >= deadline:
                    raise PortError("android: command expired before dispatch")
                self._used_sources.add(source.observation_id)
                mutation_started.set()
                self._request("POST", self._path(lease, suffix), body, deadline, stop)
                return ReceiptStatus.COMPLETED, "Appium command completed technically"
            except _NoFocusedField:
                return (
                    ReceiptStatus.REJECTED,
                    "No focused text field; tap the field first. Nothing was typed",
                )
            except Exception:
                if mutation_started.is_set():
                    self._uncertain.set()
                return (
                    (ReceiptStatus.UNCERTAIN, "Command may have executed; observe before deciding")
                    if mutation_started.is_set()
                    else (ReceiptStatus.REJECTED, "Command rejected before mutation dispatch")
                )

        try:
            status, detail = await self._run(execute, action.timeout_ms)
        except (TimeoutError, PortError):
            if mutation_started.is_set():
                self._uncertain.set()
            status = (
                ReceiptStatus.UNCERTAIN if mutation_started.is_set() else ReceiptStatus.REJECTED
            )
            detail = "Operation did not settle in time; never retry automatically"
        except asyncio.CancelledError:
            if mutation_started.is_set():
                self._uncertain.set()
            raise
        return TechnicalReceipt(
            action.run_id, action.action_id, status, dispatched, utc_now(), detail=detail
        )
