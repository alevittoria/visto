"""ADB device inventory: fixed, bounded commands only, no generic shell."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from visto.adapters.devices import AttachedDevice, InventoryUnavailable, Platform

__all__ = [
    "AttachedDevice",
    "InventoryUnavailable",
    "find_adb",
    "list_devices",
    "parse_devices",
    "start_server",
]

_SERIAL = re.compile(r"^[A-Za-z0-9._:\-]{1,256}$")
_DETAIL = re.compile(r"^([a-z_]+):(\S{1,128})$")


def find_adb(environ: dict[str, str] | None = None) -> Path | None:
    """Locate adb from the SDK environment, the default Windows SDK, or PATH."""
    environ = dict(os.environ) if environ is None else environ
    name = "adb.exe" if os.name == "nt" else "adb"
    roots = [environ.get("ANDROID_HOME"), environ.get("ANDROID_SDK_ROOT")]
    if environ.get("LOCALAPPDATA"):
        roots.append(str(Path(environ["LOCALAPPDATA"]) / "Android" / "Sdk"))
    for root in roots:
        if root:
            candidate = Path(root) / "platform-tools" / name
            if candidate.is_file():
                return candidate
    found = shutil.which("adb", path=environ.get("PATH"))
    return Path(found) if found else None


def parse_devices(output: str) -> tuple[AttachedDevice, ...]:
    """Parse `adb devices -l`; malformed lines are skipped, never echoed."""
    devices = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith(("List of devices", "*")):
            continue
        serial, state = parts[0], parts[1]
        if not _SERIAL.match(serial) or not re.fullmatch(r"[a-z ]{1,32}", state):
            continue
        details = dict(m.groups() for p in parts[2:] if (m := _DETAIL.match(p)))
        devices.append(
            AttachedDevice(
                Platform.ANDROID,
                serial,
                state,
                details.get("model", "").replace("_", " ") or None,
                details.get("product"),
            )
        )
    return tuple(devices)


def _run(adb: Path, timeout_s: float) -> bytes:
    try:
        result = subprocess.run(
            [str(adb), "devices", "-l"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
    except subprocess.TimeoutExpired:
        raise InventoryUnavailable("adb did not answer in time") from None
    except OSError:
        raise InventoryUnavailable("adb could not be started") from None
    if result.returncode != 0:
        raise InventoryUnavailable("adb reported an error")
    return result.stdout[:65536]


def _start(adb: Path, timeout_s: float) -> bool:
    # No pipes: the daemon this spawns would inherit them and keep the call waiting.
    try:
        result = subprocess.run(
            [str(adb), "start-server"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


async def start_server(adb: Path | None, timeout_s: float = 15.0) -> bool:
    """Start the adb server if it is not running; never raises."""
    if adb is None:
        return False
    return await asyncio.to_thread(_start, adb, timeout_s)


async def list_devices(adb: Path | None, timeout_s: float = 5.0) -> tuple[AttachedDevice, ...]:
    """Run in a worker thread: independent of the event loop type on Windows."""
    if adb is None:
        raise InventoryUnavailable("adb was not found; install Android platform-tools")
    output = await asyncio.to_thread(_run, adb, timeout_s)
    return parse_devices(output.decode("utf-8", "replace"))
