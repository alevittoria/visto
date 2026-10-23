"""ADB inventory parsing and API exposure; no real adb or device is contacted."""

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient
from test_api import directory, make_service  # noqa: F401  (fixture reuse)

from visto.adapters.android.host_bridge import HostAdb, bridge
from visto.adapters.android.inventory import (
    InventoryUnavailable,
    find_adb,
    list_devices,
    parse_devices,
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


HOST = HostAdb("host.docker.internal")
REMOTE = ["-H", "host.docker.internal", "-P", "5037"]
WLAN = "    inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0\n"
LOCAL_CONSOLE = {"X-Visto": "local-console"}


class FakeAdb:
    """Scripted adb: the host lists USB devices; the local server attaches targets."""

    def __init__(self, host_devices, *, tcp_mode=False, accepts=True, reachable=True):
        self.host_devices = host_devices
        self.tcp_mode = tcp_mode  # adbd already listens on TCP
        self.accepts = accepts  # the target accepts connections once in TCP mode
        self.reachable = reachable
        self.local = {}
        self.calls = []

    def __call__(self, arguments, timeout_s):
        self.calls.append(arguments)
        if arguments[:4] == REMOTE:
            rest = arguments[4:]
            if not self.reachable:
                return 1, ""
            if rest == ["devices", "-l"]:
                return 0, "List of devices attached\n" + self.host_devices
            if rest[2:4] == ["shell", "ip"]:
                return 0, WLAN
            if rest[2] == "tcpip":
                self.tcp_mode = True
                return 0, "restarting in TCP mode port: 5555\n"
            raise AssertionError(arguments)
        if arguments == ["devices", "-l"]:
            lines = "".join(f"{target}\t{state}\n" for target, state in self.local.items())
            return 0, "List of devices attached\n" + lines
        if arguments[0] == "disconnect":
            self.local.pop(arguments[1], None)
            return 0, ""
        if arguments[0] == "connect":
            if self.tcp_mode and self.accepts:
                self.local[arguments[1]] = "unauthorized"  # The phone now prompts.
            return 0, ""
        raise AssertionError(arguments)

    def tcpip_calls(self):
        return [call for call in self.calls if "tcpip" in call]


def run_bridge(adb):
    ticks = iter(range(1000))
    return bridge(adb, HOST, sleep=lambda _: None, clock=lambda: float(next(ticks)))


def test_bridge_switches_usb_device_to_tcp_and_connects_it():
    adb = FakeAdb("SERIAL01\tdevice usb:1-1 model:Demo\n")
    assert run_bridge(adb) == ()
    assert adb.local == {"192.168.1.20:5555": "unauthorized"}
    assert adb.tcpip_calls() == [[*REMOTE, "-s", "SERIAL01", "tcpip", "5555"]]


def test_bridge_connects_without_restarting_adbd_when_already_in_tcp_mode():
    adb = FakeAdb("SERIAL01\tdevice\n", tcp_mode=True)
    assert run_bridge(adb) == ()
    assert adb.tcpip_calls() == []
    # Already attached: neither connect nor tcpip.
    adb.calls.clear()
    assert run_bridge(adb) == ()
    assert not any(call[0] in ("connect", "disconnect") for call in adb.calls)


def test_bridge_reports_safe_notes_and_restarts_adbd_at_most_once():
    adb = FakeAdb("SERIAL01\tdevice\n", accepts=False)
    (note,) = run_bridge(adb)
    assert "did not accept" in note and len(adb.tcpip_calls()) == 1

    unauthorized = FakeAdb("SERIAL01\tunauthorized\n192.168.1.9:5555\tdevice\n")
    (note,) = run_bridge(unauthorized)
    assert "accept the USB debugging prompt" in note and unauthorized.tcpip_calls() == []

    (note,) = run_bridge(FakeAdb("", reachable=False))
    assert "not reachable at host.docker.internal:5037" in note


def test_host_adb_setting_parsing():
    assert HostAdb.parse(None) is None and HostAdb.parse(" ") is None
    assert HostAdb.parse("host.docker.internal") == HostAdb("host.docker.internal", 5037)
    assert HostAdb.parse("10.0.0.2:5038") == HostAdb("10.0.0.2", 5038)
    for bad in ("bad host:1", "h:x", "h:70000"):
        with pytest.raises(ValueError):
            HostAdb.parse(bad)


def test_refresh_route_connects_first_and_requires_local_console(directory):  # noqa: F811
    service = make_service(directory)
    events = []

    async def connector():
        events.append("connect")
        return ("SERIAL01: no Wi-Fi address; connect the phone to the computer's network.",)

    async def lister():
        events.append("list")
        return parse_devices(OUTPUT)

    service.device_lister, service.device_connector = lister, connector
    with TestClient(create_app(service), base_url="http://localhost") as client:
        assert client.post("/api/devices/refresh").status_code == 403
        assert client.get("/api/devices").json()["notes"] == []
        body = client.post("/api/devices/refresh", headers=LOCAL_CONSOLE).json()
    assert events == ["list", "connect", "list"]
    assert body["available"] is True and body["notes"][0].startswith("SERIAL01: no Wi-Fi")


def test_refresh_does_not_bridge_while_a_run_is_active(directory):  # noqa: F811
    service = make_service(directory)
    called = []

    async def connector():
        called.append(True)
        return ()

    async def lister():
        return ()

    service.device_lister, service.device_connector = lister, connector
    service.active = object()
    body = asyncio.run(service.devices(connect=True))
    assert called == [] and "not connected while a run is active" in body["notes"][0]
