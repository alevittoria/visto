"""Bridge host USB devices into the container adb server over adb-over-TCP.

Docker Desktop (Windows/macOS) cannot pass USB to containers, but it forwards
`host.docker.internal` to the host's loopback, where the host adb server already
owns the phone. On an explicit operator refresh this module asks the host server,
with fixed commands only, for each authorized USB device's Wi-Fi address, switches
it to TCP when needed and connects it from the container server. The phone then
prompts to authorize the container's adb key if it does not know it yet.
"""

import asyncio
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from visto.adapters.android.inventory import parse_devices

_HOST = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")
_ADDRESS = re.compile(r"\binet (\d{1,3}(?:\.\d{1,3}){3})/")
ATTACHED = ("device", "unauthorized")

# (arguments after the adb executable, timeout seconds) -> (exit code, stdout)
Runner = Callable[[list[str], float], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class HostAdb:
    host: str
    port: int = 5037

    @classmethod
    def parse(cls, value: str | None) -> "HostAdb | None":
        """`host[:port]`; empty or unset disables the bridge."""
        value = (value or "").strip()
        if not value:
            return None
        host, _, port = value.partition(":")
        if not _HOST.match(host) or (port and not port.isdigit()):
            raise ValueError("VISTO_HOST_ADB must be host[:port]")
        number = int(port) if port else 5037
        if not 1 <= number <= 65535:
            raise ValueError("VISTO_HOST_ADB port is out of range")
        return cls(host, number)


def subprocess_runner(adb: Path) -> Runner:
    def run(arguments: list[str], timeout_s: float) -> tuple[int, str]:
        try:
            result = subprocess.run(
                [str(adb), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
            )
        except (subprocess.TimeoutExpired, OSError):
            return -1, ""
        return result.returncode, result.stdout[:65536].decode("utf-8", "replace")

    return run


def _states(run: Runner, prefix: list[str]) -> dict[str, str] | None:
    code, output = run([*prefix, "devices", "-l"], 5.0)
    if code != 0:
        return None
    return {device.serial: device.state for device in parse_devices(output)}


def bridge(
    run: Runner,
    host: HostAdb,
    *,
    tcp_port: int = 5555,
    settle_s: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, ...]:
    """Return safe operator notes; never raises and never echoes process output.

    `adb tcpip` restarts adbd on the phone, so it runs at most once per device per
    call and only when a plain `adb connect` to its Wi-Fi address did not attach.
    """
    remote = ["-H", host.host, "-P", str(host.port)]
    host_states = _states(run, remote)
    if host_states is None:
        return (
            f"Host adb is not reachable at {host.host}:{host.port}; "
            "start it on the host (adb start-server) with the phone attached by USB.",
        )
    local = _states(run, []) or {}
    notes = []
    for serial, state in host_states.items():
        if ":" in serial or serial.startswith("emulator-"):
            continue  # Only USB devices need bridging.
        if state != "device":
            notes.append(f"{serial}: accept the USB debugging prompt for this computer first.")
            continue
        code, output = run(
            [*remote, "-s", serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"], 5.0
        )
        match = _ADDRESS.search(output) if code == 0 else None
        if match is None:
            notes.append(
                f"{serial}: no Wi-Fi address; connect the phone to the computer's network."
            )
            continue
        target = f"{match.group(1)}:{tcp_port}"
        if local.get(target) in ATTACHED:
            continue
        if _connect(run, target):
            continue
        if run([*remote, "-s", serial, "tcpip", str(tcp_port)], 10.0)[0] != 0:
            notes.append(f"{serial}: switching to adb over TCP failed.")
            continue
        deadline = clock() + settle_s
        while clock() < deadline:  # adbd restarts before it accepts TCP connections.
            sleep(1.0)
            if _connect(run, target):
                break
        else:
            notes.append(
                f"{serial}: {target} did not accept the connection; check Wi-Fi and firewall."
            )
    return tuple(notes)


def _connect(run: Runner, target: str) -> bool:
    run(["disconnect", target], 5.0)  # Drop a stale offline entry, if any.
    run(["connect", target], 5.0)
    return (_states(run, []) or {}).get(target) in ATTACHED


async def bridge_host_devices(adb: Path | None, host: HostAdb) -> tuple[str, ...]:
    if adb is None:
        return ("adb was not found; install Android platform-tools",)
    return await asyncio.to_thread(bridge, subprocess_runner(adb), host)
