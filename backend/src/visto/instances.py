"""Registry of running Visto processes sharing one home.

Each process writes ``instances/<pid>.json`` while it runs. Setup and migrations
use :func:`exclusive` to refuse while another process uses the same home. Device
leases are a separate mechanism and never consulted here.
"""

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from visto.home import VistoHome, make_private_dir

Kind = Literal["start", "run", "inspect", "setup"]


@dataclass(frozen=True)
class Instance:
    pid: int
    kind: str
    started_at: str


class Busy(RuntimeError):
    """Another Visto process is using the same home."""


_MAX_PID = 2**31 - 1


def _pid_alive(pid: int) -> bool:
    if not 1 <= pid <= _MAX_PID:
        return False
    try:
        if sys.platform == "win32":
            return _pid_alive_windows(pid)
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _write(home: VistoHome, instance: Instance) -> None:
    make_private_dir(home.instances)
    target = home.instances / f"{instance.pid}.json"
    tmp = home.instances / f"{instance.pid}.json.tmp"
    payload = {"pid": instance.pid, "kind": instance.kind, "started_at": instance.started_at}
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, target)


_held: dict[Path, tuple[Instance, int]] = {}


@contextmanager
def registered(home: VistoHome, kind: Kind) -> Iterator[Instance]:
    """Register this process; nested use keeps the outermost entry until it exits."""
    key = home.root
    outer = _held.get(key)
    if outer is not None:
        _held[key] = (outer[0], outer[1] + 1)
        try:
            yield outer[0]
        finally:
            instance, depth = _held[key]
            _held[key] = (instance, depth - 1)
        return
    instance = Instance(os.getpid(), kind, datetime.now(UTC).isoformat())
    _write(home, instance)
    _held[key] = (instance, 1)
    try:
        yield instance
    finally:
        del _held[key]
        (home.instances / f"{instance.pid}.json").unlink(missing_ok=True)


def _read(path: Path) -> Instance | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Instance(int(data["pid"]), str(data["kind"]), str(data["started_at"]))
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def others(home: VistoHome) -> list[Instance]:
    if not home.instances.is_dir():
        return []
    found: list[Instance] = []
    for path in sorted(home.instances.glob("*.json")):
        instance = _read(path)
        if instance is None or not _pid_alive(instance.pid):
            _discard(path)
            continue
        if instance.pid != os.getpid():
            found.append(instance)
    return found


@contextmanager
def exclusive(home: VistoHome, kind: Kind) -> Iterator[Instance]:
    """Register first, then refuse if another live process is registered."""
    with registered(home, kind) as instance:
        busy = others(home)
        if busy:
            kinds = ", ".join(sorted({i.kind for i in busy}))
            raise Busy(f"Another Visto process ({kinds}) is using this home; stop it and retry.")
        yield instance
