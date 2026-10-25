"""ADB inventory parsing and API exposure; no real adb or device is contacted."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import directory, make_service  # noqa: F401  (fixture reuse)

from visto.adapters.android.inventory import (
    InventoryUnavailable,
    find_adb,
    list_devices,
    parse_devices,
    start_server,
)
from visto.adapters.devices import AttachedDevice, Platform
from visto.composition import create_app

OUTPUT = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
SERIAL01               device usb:1-1 product:demo model:Demo_Phone device:demo transport_id:3
emulator-5554          unauthorized transport_id:4
192.168.1.20:5555      offline
bad<serial>            device
<script>alert(1)</script>

"""


def test_parse_keeps_states_and_details_and_skips_malformed_lines():
    assert parse_devices(OUTPUT) == (
        AttachedDevice(Platform.ANDROID, "SERIAL01", "device", "Demo Phone", "demo"),
        AttachedDevice(Platform.ANDROID, "emulator-5554", "unauthorized"),
        AttachedDevice(Platform.ANDROID, "192.168.1.20:5555", "offline"),
    )
    assert parse_devices("") == ()


def test_adb_parsing_tags_every_entry_as_android():
    assert {d.platform for d in parse_devices(OUTPUT)} == {Platform.ANDROID}


def test_selectability_is_platform_specific():
    assert AttachedDevice(Platform.ANDROID, "device-A", "device").selectable is True
    assert AttachedDevice(Platform.ANDROID, "device-A", "unauthorized").selectable is False
    assert AttachedDevice(Platform.IOS, "device-B", "booted").selectable is True
    assert AttachedDevice(Platform.IOS, "device-B", "shutdown").selectable is False
    assert AttachedDevice(Platform.IOS, "device-B", "connected").selectable is True
    assert AttachedDevice(Platform.IOS, "device-B", "device").selectable is False
    assert [Platform.ANDROID.value, Platform.IOS.value] == ["android", "ios"]


def test_find_adb_prefers_sdk_environment_then_path():
    import os
    import shutil
    from pathlib import Path
    from uuid import uuid4

    root = Path(__file__).resolve().parents[2] / ".work" / ("adb-test-" + uuid4().hex)
    name = "adb.exe" if os.name == "nt" else "adb"
    try:
        (root / "sdk" / "platform-tools").mkdir(parents=True)
        (root / "sdk" / "platform-tools" / name).write_bytes(b"")
        assert find_adb({"ANDROID_HOME": str(root / "sdk"), "PATH": ""}) == (
            root / "sdk" / "platform-tools" / name
        )
        assert find_adb({"ANDROID_HOME": str(root / "missing"), "PATH": ""}) is None
    finally:
        shutil.rmtree(root)


def test_unavailable_or_failing_adb_reports_safe_message():
    with pytest.raises(InventoryUnavailable, match="not found"):
        asyncio.run(list_devices(None))
    # A real executable that rejects these arguments exercises the error path.
    from pathlib import Path

    with pytest.raises(InventoryUnavailable, match="reported an error"):
        asyncio.run(list_devices(Path(sys.executable)))


def test_start_server_runs_one_fixed_command_without_pipes(monkeypatch):
    calls = []

    def fake_run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    adb = Path("/sdk/adb")
    assert asyncio.run(start_server(adb)) is True
    ((command, options),) = calls
    assert command == [str(adb), "start-server"]
    assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert "shell" not in options


def test_start_server_reports_failure_without_raising(monkeypatch):
    def failing(command, **options):
        raise subprocess.TimeoutExpired(command, 15)

    monkeypatch.setattr(subprocess, "run", failing)
    assert asyncio.run(start_server(Path("/sdk/adb"))) is False
    assert asyncio.run(start_server(None)) is False


def test_devices_route_lists_selectable_devices_and_hides_failure_detail(directory):  # noqa: F811
    service = make_service(directory)

    async def lister():
        return parse_devices(OUTPUT)

    service.device_lister = lister
    with TestClient(create_app(service), base_url="http://localhost") as client:
        body = client.get("/api/devices").json()
    assert body["available"] is True and body["error"] is None
    assert [(d["serial"], d["platform"], d["selectable"]) for d in body["devices"]] == [
        ("SERIAL01", "android", True),
        ("emulator-5554", "android", False),
        ("192.168.1.20:5555", "android", False),
    ]
    assert body["devices"][0]["model"] == "Demo Phone"

    async def failing():
        raise InventoryUnavailable("adb did not answer in time")

    service = make_service(directory)
    service.device_lister = failing
    with TestClient(create_app(service), base_url="http://localhost") as client:
        assert client.get("/api/devices").json() == {
            "available": False,
            "devices": [],
            "error": "adb did not answer in time",
            "notes": [],
        }
