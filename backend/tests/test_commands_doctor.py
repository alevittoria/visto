"""`visto doctor`: read-only checks with injected probes; no device or provider contact."""

import json
import re
import socket
import threading
from contextlib import contextmanager
from pathlib import Path

from test_commands_start import installed_home

from visto.adapters.devices import AttachedDevice, InventoryUnavailable, Platform
from visto.adapters.settings.store import Settings, SettingsStore
from visto.commands.doctor import adb_server_version, collect_checks, run_doctor
from visto.home import VistoHome
from visto.toolchain import Toolchain, load_manifest
from visto.toolchain.appium import appium_flavor, appium_version
from visto.toolchain.license import record_acceptance

IOS_WORDS = re.compile(r"ios|xcode|xcuitest|webdriveragent", re.I)


def probes(*, server=None, client=41, simctl=True, devices=(), appium=False):
    def listing(adb):
        if isinstance(devices, Exception):
            raise devices
        return tuple(AttachedDevice(Platform.ANDROID, s, state) for s, state in devices)

    return {
        "adb_server_version": lambda: server,
        "adb_client_version": lambda adb: client,
        "xcrun_tool": lambda name: simctl,
        "appium_up": lambda: appium,
        "list_attached": listing,
    }


def installed(tmp_path: Path) -> VistoHome:
    return installed_home(tmp_path)


def mac_home(tmp_path: Path, *, saved_for: str, installed: str) -> VistoHome:
    home = VistoHome(tmp_path / "home")
    toolchain = Toolchain(home)
    manifest = load_manifest()
    versions = {n: manifest[n]["macos-arm64"].version for n in ("node", "jdk", "android-sdk")}
    versions["appium"] = appium_version(appium_flavor("macos-arm64"))
    for name, version in versions.items():
        toolchain.component_dir(name, version).mkdir(parents=True)
    driver = toolchain.component_dir("appium", versions["appium"]) / "node_modules"
    (driver / "appium-xcuitest-driver").mkdir(parents=True)
    (driver / "appium-xcuitest-driver" / "package.json").write_text(
        json.dumps({"version": installed}), encoding="utf-8"
    )
    state = toolchain.state()
    state.active.update(versions)
    toolchain.save_state(state)
    record_acceptance(toolchain)
    SettingsStore(home).save(Settings(ios_saved_for_xcuitest=saved_for))
    return home


def home_with_lease(tmp_path: Path, *, device_id: str, run_id: str, pid: int) -> VistoHome:
    home = VistoHome(tmp_path / "home")
    home.leases.mkdir(parents=True)
    (home.leases / "0123abcd.lease").write_text(
        json.dumps({"token": "t0k3n", "pid": pid, "run_id": run_id, "device_id": device_id}),
        encoding="utf-8",
    )
    return home


@contextmanager
def fake_adb_server(reply: bytes):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    received = []

    def serve():
        connection, _ = listener.accept()
        with connection:
            received.append(connection.recv(64))
            connection.sendall(reply)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield listener.getsockname()[1]
    finally:
        worker.join(timeout=5)
        listener.close()
    assert received == [b"000chost:version"]


def by_name(checks):
    return {check.name: check for check in checks}


def test_doctor_hides_ios_off_mac(tmp_path, capsys):
    names = [c.name for c in collect_checks(VistoHome(tmp_path), host="linux-x64", **probes())]
    assert not any(re.search(r"ios|xcode|webdriveragent", n, re.I) for n in names)
    for home in (VistoHome(tmp_path / "empty"), installed(tmp_path)):
        run_doctor(home, json_output=False, host="win-x64", **probes(devices=[("device-A", "x")]))
        run_doctor(home, json_output=True, host="linux-x64", **probes(server=40))
    # The pytest directory carries this test's name; only product wording is checked.
    out = capsys.readouterr().out
    out = out.replace(str(tmp_path), "<tmp>").replace(json.dumps(str(tmp_path))[1:-1], "<tmp>")
    assert not IOS_WORDS.search(out)


def test_doctor_warns_on_xcuitest_change(tmp_path):
    home = mac_home(tmp_path, saved_for="12.19.1", installed="13.0.0")
    assert any(
        c.ok is None and "WebDriverAgent" in c.detail
        for c in collect_checks(home, host="macos-arm64", **probes())
    )
    same = mac_home(tmp_path / "same", saved_for="13.0.0", installed="13.0.0")
    assert by_name(collect_checks(same, host="macos-arm64", **probes()))["XCUITest driver"].ok


def test_doctor_reports_mac_tooling(tmp_path):
    home = mac_home(tmp_path, saved_for="13.0.0", installed="13.0.0")
    checks = by_name(collect_checks(home, host="macos-arm64", **probes(simctl=False)))
    assert checks["xcrun simctl"].ok is None and checks["xcrun devicectl"].ok is None
    assert checks["iOS signing"].ok is None
    assert checks["WebDriverAgent project"].ok is None


def test_doctor_lists_retained_leases(tmp_path):
    home = home_with_lease(tmp_path, device_id="device-A", run_id="run-1", pid=4242)
    detail = next(
        c.detail
        for c in collect_checks(home, host="win-x64", **probes())
        if c.name == "Device leases"
    )
    assert "device-A" in detail and "run-1" in detail
    assert "4242" in detail and "docs/android-setup.md" in detail
    assert "t0k3n" not in detail


def test_doctor_without_leases_is_ok(tmp_path):
    checks = by_name(collect_checks(VistoHome(tmp_path), host="win-x64", **probes()))
    assert checks["Device leases"].ok is True


def test_doctor_warns_on_adb_server_mismatch(tmp_path):
    listed = []
    found = probes(server=40, client=41)
    found["list_attached"] = lambda adb: listed.append(adb) or ()
    checks = collect_checks(installed(tmp_path), host="win-x64", **found)
    assert any(c.ok is None and "adb" in c.name.lower() for c in checks)
    # Listing devices with a different adb would restart the other server.
    assert listed == []


def test_doctor_device_states(tmp_path):
    home = installed(tmp_path)

    def devices_check(listed):
        checks = collect_checks(home, host="win-x64", **probes(devices=listed))
        return by_name(checks)["Android devices"]

    mixed = devices_check([("device-A", "device"), ("device-B", "unauthorized")])
    assert mixed.ok is None
    assert "device-A ready" in mixed.detail
    assert "device-B: accept the USB debugging prompt on the phone" in mixed.detail
    assert devices_check([("device-A", "device")]).ok is True
    assert devices_check([]).ok is None
    assert devices_check(InventoryUnavailable("adb reported an error")).ok is False


def test_doctor_toolchain_license_and_key(tmp_path):
    empty = by_name(collect_checks(VistoHome(tmp_path / "empty"), host="win-x64", **probes()))
    assert empty["Toolchain"].ok is False and "visto setup" in empty["Toolchain"].detail
    assert empty["Android SDK license"].ok is False
    assert empty["Provider key"].ok is False
    assert empty["Appium"].ok is None
    home = installed(tmp_path)
    SettingsStore(home).set_api_key("sk-test-secret77")
    ready = by_name(collect_checks(home, host="win-x64", **probes(appium=True)))
    assert ready["Toolchain"].ok and ready["Android SDK license"].ok
    assert ready["Provider key"].ok and ready["Appium"].ok


def test_run_doctor_exit_code_and_lines(tmp_path):
    lines = []
    home = installed(tmp_path)
    assert run_doctor(home, json_output=False, output=lines.append, host="win-x64", **probes()) == 2
    assert all(re.match(r"\[(ok|!!|--)\] [^:]+: ", line) for line in lines)
    assert any(line.startswith("[!!] Provider key: ") for line in lines)
    SettingsStore(home).set_api_key("sk-test-secret77")
    lines.clear()
    ready = probes(devices=[("device-A", "device")])
    assert run_doctor(home, json_output=True, output=lines.append, host="win-x64", **ready) == 0
    data = json.loads(lines[0])
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["Provider key"]["ok"] is True and data["ok"] is True


def test_doctor_never_prints_key(tmp_path, capsys):
    home = installed(tmp_path)
    SettingsStore(home).set_api_key("sk-test-secret77")
    run_doctor(home, json_output=False, **probes())
    run_doctor(home, json_output=True, **probes())
    assert "sk-test-secret77" not in capsys.readouterr().out


def test_adb_server_version_parses_reply():
    with fake_adb_server(b"OKAY0004002a") as port:
        assert adb_server_version(port) == 42


def test_adb_server_version_none_without_server_or_on_failure():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert adb_server_version(port) is None
    with fake_adb_server(b"FAIL0004oops") as port:
        assert adb_server_version(port) is None


def test_doctor_fallback_adb_is_reported_as_unmanaged(tmp_path, monkeypatch):
    monkeypatch.setattr("visto.commands.doctor.find_adb", lambda: Path("/contrib/sdk/adb"))
    adb = by_name(collect_checks(VistoHome(tmp_path), host="win-x64", **probes()))["adb"]
    assert adb.ok is None
    assert "not managed by Visto" in adb.detail and "visto setup" in adb.detail
    managed = by_name(collect_checks(installed(tmp_path), host="win-x64", **probes()))["adb"]
    assert managed.ok is True and "not managed" not in managed.detail


def test_doctor_checks_appium_on_the_given_port(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(
        "visto.commands.doctor.appium_running", lambda port: asked.append(port) or True
    )
    found = probes()
    del found["appium_up"]
    lines = []
    run_doctor(
        installed(tmp_path),
        json_output=False,
        output=lines.append,
        host="win-x64",
        appium_port=4801,
        **found,
    )
    assert asked == [4801]
    assert "[ok] Appium: reachable at 127.0.0.1:4801" in lines


def test_doctor_json_reports_whether_devices_were_listed(tmp_path):
    home = installed(tmp_path)
    lines = []
    run_doctor(home, json_output=True, output=lines.append, host="win-x64", **probes())
    assert json.loads(lines[-1])["device_contacted"] is True
    # A different adb server is left alone, so no device is listed.
    run_doctor(home, json_output=True, output=lines.append, host="win-x64", **probes(server=40))
    assert json.loads(lines[-1])["device_contacted"] is False
