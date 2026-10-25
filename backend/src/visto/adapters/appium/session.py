"""Platform-neutral Appium session: fail-closed ownership and bounded operations."""

import asyncio
import hashlib
import json
import math
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from visto.application.ports import OperatorActionRequired, PortError
from visto.application.runtime import utc_now
from visto.domain.commands import DeviceCommand, LongPress, Swipe, Tap
from visto.domain.models import (
    Action,
    CapturedImage,
    DeviceLease,
    Observation,
    ReceiptStatus,
    TechnicalReceipt,
)

from .wire import CommandError, Wire


class NoFocusedField(Exception):
    """TypeText was requested while no input element had focus."""


# https://w3c.github.io/webdriver/#elements
W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"


def _positive(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Expected positive integer milliseconds")
    return value


class AppiumSession:
    """Ownership, deadlines and receipt semantics; subclasses own the platform routes."""

    def __init__(
        self,
        component: str,
        version: str,
        wire: Wire,
        lease_directory: Path,
        *,
        request_timeout_ms: int = 30000,
        cleanup_timeout_ms: int = 5000,
    ):
        self.version = version
        self._component = component
        self._wire = wire
        self._directory = Path(lease_directory)
        self._request_timeout = _positive(request_timeout_ms)
        self._cleanup_timeout = _positive(cleanup_timeout_ms)
        self._lease: DeviceLease | None = None
        self._marker: Path | None = None
        self._token: str | None = None
        # Last observed frame; a subclass reads it to know when the core drops the geometry
        # its own capture derived, and translate only runs while it matches the source.
        self._capture: CapturedImage | None = None
        self._pending: asyncio.Task | None = None
        self._active = threading.Event()
        self._used_sources: set[str] = set()
        self._uncertain = threading.Event()

    def capabilities(self, device_id: str) -> dict:
        """Capabilities for one explicitly addressed device; no generic shell."""
        raise NotImplementedError

    def diagnose(self, message: str) -> str | None:
        """Fixed operator hint for a recognised Appium refusal; never echoes `message`."""
        return None

    def capture(self, lease: DeviceLease, deadline: float, stop: threading.Event) -> CapturedImage:
        """Fresh screenshot with the geometry it was taken in, never a previous frame."""
        raise NotImplementedError

    def translate(
        self, command: DeviceCommand, lease: DeviceLease, deadline: float, stop: threading.Event
    ) -> tuple[str, dict]:
        """Session-relative route and body for one command, called with a current capture.

        May perform read-only lookups, but must not dispatch the mutation itself.
        """
        raise NotImplementedError

    async def _run(self, operation: Callable, timeout_ms: int):
        """A late worker keeps its lease quarantined; it may never dispatch after timeout."""
        timeout_ms = _positive(timeout_ms)
        if self._active.is_set():
            raise PortError(f"{self._component}: operation still in flight; ownership retained")
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
            raise PortError(f"{self._component}: device operation failed") from None

    def _request(self, method, path, body, deadline, stop):
        remaining = math.floor((deadline - time.monotonic()) * 1000)
        if stop.is_set() or remaining < 1:
            raise PortError(f"{self._component}: operation deadline reached")
        try:
            response = self._wire.request(method, path, body, min(remaining, self._request_timeout))
            if not isinstance(response, dict) or "value" not in response:
                raise ValueError
            value = response["value"]
            if isinstance(value, dict) and "error" in value:
                raise ValueError
            return value
        except CommandError as error:
            hint = self.diagnose(error.message)
            if hint:
                raise OperatorActionRequired(f"{self._component}: {hint}") from None
            raise PortError(f"{self._component}: Appium request failed") from None
        except Exception:
            raise PortError(f"{self._component}: Appium request failed") from None

    def _owned(self, lease):
        if lease != self._lease or self._marker is None or self._token is None:
            raise PortError(f"{self._component}: lease is not owned by this adapter")
        try:
            data = json.loads(self._marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PortError(f"{self._component}: ownership marker unavailable") from None
        if data.get("token") != self._token:
            raise PortError(f"{self._component}: ownership marker changed")

    def _path(self, lease, suffix=""):
        return "/session/" + quote(lease.session_id, safe="") + suffix

    def _focused_element(self, lease, deadline, stop):
        """Read-only lookup of the focused input; no mutation has been dispatched yet.

        Shared, so both platforms reject a focus-less TypeText on the same evidence.
        """
        # https://w3c.github.io/webdriver/#get-active-element
        try:
            value = self._request("GET", self._path(lease, "/element/active"), None, deadline, stop)
        except PortError:
            raise NoFocusedField from None
        element = value.get(W3C_ELEMENT, value.get("ELEMENT")) if isinstance(value, dict) else None
        if not isinstance(element, str) or not element or len(element) > 256:
            raise NoFocusedField
        return element

    async def acquire(self, run_id: str, device_id: str, timeout_ms: int) -> DeviceLease:
        if not run_id.strip() or not device_id.strip():
            raise ValueError("Run and device identifiers are required")

        def acquire(deadline, stop):
            if self._marker is not None:
                raise PortError(f"{self._component}: adapter already owns or quarantines a device")
            # Before the marker: a platform hook that refuses the target leaves no
            # quarantine behind, since no remote session can exist for it.
            capabilities = self.capabilities(device_id)
            self._directory.mkdir(parents=True, exist_ok=True)
            marker = self._directory / (hashlib.sha256(device_id.encode()).hexdigest() + ".lease")
            token = uuid4().hex
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise PortError(
                    f"{self._component}: device already leased; manual recovery may be required"
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
            result = self._request(
                "POST", "/session", {"capabilities": {"alwaysMatch": capabilities}}, deadline, stop
            )
            if not isinstance(result, dict) or not isinstance(result.get("sessionId"), str):
                raise PortError(
                    f"{self._component}: malformed session response; ownership retained"
                )
            self._lease = DeviceLease(token, run_id, device_id, result["sessionId"])
            return self._lease

        try:
            return await self._run(acquire, timeout_ms)
        except TimeoutError:
            raise PortError(
                f"{self._component}: session startup timed out; ownership retained"
            ) from None

    async def release(self, lease: DeviceLease) -> None:
        if self._lease is None and self._marker is None:
            return

        def release(deadline, stop):
            self._owned(lease)
            self._request("DELETE", self._path(lease), None, deadline, stop)
            self._owned(lease)
            if self._uncertain.is_set():
                raise PortError(
                    f"{self._component}: uncertain mutation; ownership retained for manual recovery"
                )
            self._marker.unlink()
            self._lease = self._marker = self._token = self._capture = None
            self._used_sources.clear()

        try:
            await self._run(release, self._cleanup_timeout)
        except TimeoutError:
            raise PortError(
                f"{self._component}: session cleanup timed out; ownership retained"
            ) from None

    async def observe(self, lease: DeviceLease, timeout_ms: int) -> CapturedImage:
        def observe(deadline, stop):
            self._owned(lease)
            capture = self.capture(lease, deadline, stop)
            self._capture = capture
            return capture

        try:
            return await self._run(observe, timeout_ms)
        except TimeoutError:
            raise PortError(f"{self._component}: screenshot timed out") from None

    def _validate_source(self, lease, action, source):
        self._owned(lease)
        if self._uncertain.is_set():
            raise PortError(f"{self._component}: uncertain session cannot dispatch more mutations")
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
            raise PortError(f"{self._component}: stale or mismatched source frame")
        command = action.command
        points = []
        if isinstance(command, Tap):
            points = [(command.x, command.y)]
        elif isinstance(command, LongPress):
            points = [(command.x, command.y)]
            if command.duration_ms > action.timeout_ms:
                raise PortError(f"{self._component}: long press exceeds command timeout")
        elif isinstance(command, Swipe):
            points = [(command.start_x, command.start_y), (command.end_x, command.end_y)]
            if command.duration_ms > action.timeout_ms:
                raise PortError(f"{self._component}: swipe exceeds command timeout")
        if any(not (0 <= x < source.width and 0 <= y < source.height) for x, y in points):
            raise PortError(f"{self._component}: coordinates outside source frame")

    async def execute(
        self, lease: DeviceLease, action: Action, source: Observation
    ) -> TechnicalReceipt:
        dispatched = utc_now()
        mutation_started = threading.Event()

        def execute(deadline, stop):
            try:
                self._validate_source(lease, action, source)
                suffix, body = self.translate(action.command, lease, deadline, stop)
                current = self.capture(lease, deadline, stop)
                if (current.width, current.height, current.rotation) != (
                    source.width,
                    source.height,
                    source.rotation,
                ):
                    raise PortError(f"{self._component}: device coordinate frame changed")
                self._owned(lease)
                if stop.is_set() or time.monotonic() >= deadline:
                    raise PortError(f"{self._component}: command expired before dispatch")
                self._used_sources.add(source.observation_id)
                mutation_started.set()
                self._request("POST", self._path(lease, suffix), body, deadline, stop)
                return ReceiptStatus.COMPLETED, "Appium command completed technically"
            except NoFocusedField:
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
