"""iOS inventory parsing and command handling; no real xcrun or device is contacted."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from visto.adapters.devices import AttachedDevice, InventoryUnavailable, Platform
from visto.adapters.ios import inventory
from visto.adapters.ios.inventory import (
    find_xcrun,
    list_devices,
    list_physical,
    list_simulators,
    parse_physical,
    parse_simulators,
)

RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-18-0"
SIMULATORS = json.dumps(
    {
        "devices": {
            RUNTIME: [
                {
                    "udid": "00000000-0000-0000-0000-00000000000A",
                    "name": "Example Simulator 1",
                    "state": "Booted",
                    "isAvailable": True,
                },
                {
                    "udid": "00000000-0000-0000-0000-00000000000B",
                    "name": "Example Simulator 2",
                    "state": "Shutdown",
                    "isAvailable": True,
                },
                {
                    "udid": "00000000-0000-0000-0000-00000000000C",
                    "name": "Example Simulator 3",
                    "state": "Creating",
                    "isAvailable": True,
                },
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-17-0": [
                {
                    "udid": "00000000-0000-0000-0000-00000000000D",
                    "name": "Example Simulator 4",
                    "state": "Shutdown",
                    "isAvailable": False,
                }
            ],
            "com.apple.CoreSimulator.SimRuntime.watchOS-11-0": [
                {
                    "udid": "00000000-0000-0000-0000-00000000000E",
                    "name": "Example Watch 1",
                    "state": "Shutdown",
                    "isAvailable": True,
                }
            ],
        }
    }
)


def physical(udid, *, state="connected", pairing="paired", reality="physical", **extra):
    return {
        "identifier": "11111111-1111-1111-1111-111111111111",
        "visibilityClass": "default" if reality == "physical" else "simulators",
        "properties": {
            "connection": {"state": state, "pairingState": pairing},
            "hardware": {
                "udid": udid,
                "reality": reality,
                "platform": "iOS",
                "marketingName": "Example Phone 1",
                "productType": "ExamplePhone1,1",
            },
            **extra,
        },
    }


def payload(*devices):
    return json.dumps({"info": {"jsonVersion": 5}, "result": {"devices": list(devices)}})


def test_booted_simulator_is_selectable_and_shutdown_is_not():
    booted, shutdown, _creating = parse_simulators(SIMULATORS)
    assert booted == AttachedDevice(
        Platform.IOS,
        "00000000-0000-0000-0000-00000000000A",
        "booted",
        "Example Simulator 1",
        RUNTIME,
    )
    assert booted.selectable is True
    assert shutdown.state == "shutdown" and shutdown.selectable is False


def test_unavailable_simulator_runtimes_are_skipped():
    serials = [d.serial for d in parse_simulators(SIMULATORS)]
    # Unavailable simulator and non-iOS runtime are absent; "Creating" counts as shutdown.
    assert serials[-1].endswith("0C") and len(serials) == 3
    assert not any(s.endswith(("0D", "0E")) for s in serials)


def test_connected_physical_device_is_selectable():
    (device,) = parse_physical(payload(physical("00008000-000A000A00000000")))
    assert device == AttachedDevice(
        Platform.IOS, "00008000-000A000A00000000", "connected", "Example Phone 1", "ExamplePhone1,1"
    )
    assert device.selectable is True


def test_unpaired_physical_device_is_listed_as_unavailable():
    devices = parse_physical(
        payload(
            physical("00008000-000A000A00000001", pairing="unpaired"),
            physical("00008000-000A000A00000002", state="disconnected"),
            physical("00000000-0000-0000-0000-00000000000F", reality="simulated"),
        )
    )
    # Simulators reported by devicectl belong to simctl, not to this list.
    assert [(d.state, d.selectable) for d in devices] == [
        ("unavailable", False),
        ("unavailable", False),
    ]


@pytest.mark.parametrize(
    "text", ["", "not json", "[]", '{"devices": 3}', '{"result": {"devices": "x"}}', "SECRET"]
)
def test_malformed_payload_raises_inventory_unavailable_without_echoing_it(text):
    for parse in (parse_simulators, parse_physical):
        with pytest.raises(InventoryUnavailable) as error:
            parse(text)
        assert "SECRET" not in str(error.value) and "json" not in str(error.value).lower()


def test_missing_xcrun_explains_the_prerequisite():
    with pytest.raises(InventoryUnavailable, match="Xcode"):
        asyncio.run(list_devices(None))
    assert find_xcrun({"PATH": ""}) is None


def test_list_devices_runs_both_fixed_commands_without_a_shell(monkeypatch):
    calls = []

    def fake_run(command, **options):
        calls.append((command, options))
        text = SIMULATORS if "simctl" in command else payload(physical("00008000-000A000A00000000"))
        return subprocess.CompletedProcess(command, 0, stdout=text.encode())

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)
    devices = asyncio.run(list_devices(Path("/x/xcrun")))
    assert len(devices) == 4 and devices[-1].state == "connected"
    assert [c[0][:4] for c in calls] == [
        ["/x/xcrun", "simctl", "list", "devices"],
        ["/x/xcrun", "devicectl", "list", "devices"],
    ]
    assert all(o["stdin"] == subprocess.DEVNULL and "shell" not in o for _, o in calls)


@pytest.mark.parametrize(
    "outcome", [subprocess.TimeoutExpired("secret", 1), OSError("secret"), 1, "huge"]
)
def test_command_failures_are_sanitized(monkeypatch, outcome):
    def fake_run(command, **options):
        if isinstance(outcome, BaseException):
            raise outcome
        out = b"x" * (2**20 + 1) if outcome == "huge" else b"secret"
        return subprocess.CompletedProcess(command, 0 if outcome == "huge" else outcome, out)

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)
    with pytest.raises(InventoryUnavailable) as error:
        asyncio.run(list_devices(Path("/x/xcrun")))
    assert "secret" not in str(error.value) and "/x" not in str(error.value)


def test_one_failing_source_still_returns_the_other_and_names_the_failure(monkeypatch):
    def fake_run(command, **options):
        if "devicectl" in command:
            raise subprocess.TimeoutExpired("secret", 1)
        return subprocess.CompletedProcess(command, 0, stdout=SIMULATORS.encode())

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)
    xcrun = Path("/x/xcrun")
    assert len(asyncio.run(list_devices(xcrun))) == 3
    assert len(asyncio.run(list_simulators(xcrun))) == 3
    with pytest.raises(InventoryUnavailable, match="devicectl did not answer"):
        asyncio.run(list_physical(xcrun))
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda command, **o: subprocess.CompletedProcess(command, 1, stdout=b""),
    )
    with pytest.raises(InventoryUnavailable, match="simctl reported"):
        asyncio.run(list_devices(xcrun))
