"""Read-only iOS device inventory: two fixed xcrun commands, bounded, no generic shell."""

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from visto.adapters.devices import AttachedDevice, InventoryUnavailable, Platform

__all__ = [
    "AttachedDevice",
    "InventoryUnavailable",
    "find_xcrun",
    "list_devices",
    "list_physical",
    "list_simulators",
    "parse_physical",
    "parse_simulators",
]

_UDID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
_TEXT = re.compile(r"^[^\x00-\x1f]{1,128}$")
_IOS_RUNTIME = "SimRuntime.iOS-"
_MAX_OUTPUT = 1024 * 1024
_SIMULATORS = ("simctl", "list", "devices", "--json")
# devicectl has no --json flag: JSON goes to a file, here the process's stdout.
_PHYSICAL = ("devicectl", "list", "devices", "--quiet", "--json-output", "/dev/stdout")


def find_xcrun(environ: dict[str, str] | None = None) -> Path | None:
    """Locate xcrun on PATH; absent without Xcode or the command-line tools."""
    environ = dict(os.environ) if environ is None else environ
    found = shutil.which("xcrun", path=environ.get("PATH"))
    return Path(found) if found else None


def _load(payload: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except ValueError:
        document = None
    if not isinstance(document, dict):
        raise InventoryUnavailable("xcrun returned an unrecognised device list")
    return document


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and _TEXT.fullmatch(value) else None


def _section(entry: dict[str, Any], name: str, legacy: str) -> dict[str, Any]:
    """The `properties` entry, else the top-level key `devicectl --help` calls deprecated.

    The fallback is a precaution for toolchains that predate `properties`; no such
    toolchain has been observed.
    """
    properties = entry.get("properties")
    value = properties.get(name) if isinstance(properties, dict) else None
    value = value if isinstance(value, dict) else entry.get(legacy)
    return value if isinstance(value, dict) else {}


def parse_simulators(payload: str) -> tuple[AttachedDevice, ...]:
    """Parse `simctl list devices --json`; only available iOS simulators are listed."""
    runtimes = _load(payload).get("devices")
    if not isinstance(runtimes, dict):
        raise InventoryUnavailable("xcrun returned an unrecognised device list")
    devices = []
    for runtime, entries in runtimes.items():
        if _IOS_RUNTIME not in str(runtime) or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("isAvailable") is not True:
                continue
            udid = entry.get("udid")
            if not isinstance(udid, str) or not _UDID.fullmatch(udid):
                continue
            devices.append(
                AttachedDevice(
                    Platform.IOS,
                    udid,
                    "booted" if entry.get("state") == "Booted" else "shutdown",
                    _text(entry.get("name")),
                    _text(runtime),
                )
            )
    return tuple(devices)


def parse_physical(payload: str) -> tuple[AttachedDevice, ...]:
    """Parse `devicectl list devices` JSON; simulators it also reports are skipped."""
    result = _load(payload).get("result")
    entries = result.get("devices") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        raise InventoryUnavailable("xcrun returned an unrecognised device list")
    devices = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        hardware = _section(entry, "hardware", "hardwareProperties")
        connection = _section(entry, "connection", "connectionProperties")
        udid = hardware.get("udid")
        if hardware.get("reality") != "physical" or not isinstance(udid, str):
            continue
        if not _UDID.fullmatch(udid):
            continue
        link = connection.get("state", connection.get("tunnelState"))
        ready = connection.get("pairingState") == "paired" and link == "connected"
        devices.append(
            AttachedDevice(
                Platform.IOS,
                udid,
                "connected" if ready else "unavailable",
                _text(hardware.get("marketingName")),
                _text(hardware.get("productType")),
            )
        )
    return tuple(devices)


def _run(xcrun: Path, arguments: tuple[str, ...], timeout_s: float) -> str:
    tool = arguments[0]  # Notes name the failing tool: simctl or devicectl.
    try:
        result = subprocess.run(
            [str(xcrun), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise InventoryUnavailable(f"{tool} did not answer in time") from None
    except OSError:
        raise InventoryUnavailable(f"{tool} could not be started") from None
    if result.returncode != 0:
        raise InventoryUnavailable(f"{tool} reported an error; check the Xcode installation")
    if len(result.stdout) > _MAX_OUTPUT:
        raise InventoryUnavailable(f"{tool} returned more devices than can be listed")
    return result.stdout.decode("utf-8", "replace")


def _require(xcrun: Path | None) -> Path:
    if xcrun is None:
        raise InventoryUnavailable("xcrun was not found; install Xcode to list iOS devices")
    return xcrun


async def list_simulators(
    xcrun: Path | None, timeout_s: float = 10.0
) -> tuple[AttachedDevice, ...]:
    """Simulators only (`simctl`); run in a worker thread, like the Android inventory."""
    xcrun = _require(xcrun)
    output = await asyncio.to_thread(_run, xcrun, _SIMULATORS, timeout_s)
    return parse_simulators(output)


async def list_physical(xcrun: Path | None, timeout_s: float = 10.0) -> tuple[AttachedDevice, ...]:
    """Physical devices only (`devicectl`, which talks to the CoreDevice service)."""
    xcrun = _require(xcrun)
    output = await asyncio.to_thread(_run, xcrun, _PHYSICAL, timeout_s)
    return parse_physical(output)


async def list_devices(xcrun: Path | None, timeout_s: float = 10.0) -> tuple[AttachedDevice, ...]:
    """Both sources; raises only when neither can be listed (the first failure is kept)."""
    results = await asyncio.gather(
        list_simulators(xcrun, timeout_s), list_physical(xcrun, timeout_s), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, InventoryUnavailable)]
    if len(failures) == len(results):
        raise failures[0]
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, InventoryUnavailable):
            raise result
    return tuple(d for r in results if not isinstance(r, BaseException) for d in r)
