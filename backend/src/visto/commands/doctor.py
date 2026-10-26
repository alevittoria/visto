"""`visto doctor`: read-only, bounded checks of the toolchain, Appium, adb and settings.

Nothing here mutates the toolchain, a device or the provider. Listing devices runs
`adb devices`, which starts the managed adb server when none is running; it is
skipped when a different adb server is already running, because the client would
restart that server.
"""

import asyncio
import json
import os
import re
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from visto.adapters.android.inventory import find_adb, list_devices
from visto.adapters.devices import AttachedDevice, InventoryUnavailable
from visto.adapters.ios.inventory import find_xcrun
from visto.adapters.settings.store import SettingsError, SettingsStore
from visto.commands.appium_process import appium_running
from visto.commands.setup import pending_names
from visto.home import VistoHome
from visto.toolchain import Toolchain, ToolchainMissing, ToolPaths, UnsupportedHost, host_key
from visto.toolchain.appium import installed_driver_version, wda_project
from visto.toolchain.license import license_accepted

OK, PROBLEMS = 0, 2
APPIUM_PORT = 4723
RECOVERY = "docs/android-setup.md, section 'Exclusive ownership and crash recovery'"
UNAUTHORIZED = "accept the USB debugging prompt on the phone"
_ADB_VERSION = re.compile(rb"Android Debug Bridge version \d+\.\d+\.(\d+)")
_MARKS = {True: "[ok]", False: "[!!]", None: "[--]"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None = warning/info
    detail: str


def adb_server_version(port: int = 5037, timeout_s: float = 2) -> int | None:
    """Ask a running adb server for its protocol version; None when nothing answers."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s) as connection:
            connection.settimeout(timeout_s)
            connection.sendall(b"000chost:version")
            reply = b""
            while len(reply) < 8:
                chunk = connection.recv(8 - len(reply))
                if not chunk:
                    return None
                reply += chunk
            if reply[:4] != b"OKAY":
                return None
            length = int(reply[4:8], 16)
            if not 1 <= length <= 8:
                return None
            body = b""
            while len(body) < length:
                chunk = connection.recv(length - len(body))
                if not chunk:
                    return None
                body += chunk
            return int(body, 16)
    except (OSError, ValueError):
        return None


def adb_client_version(adb: Path) -> int | None:
    """The protocol version of an adb executable (`adb version`, starts no server)."""
    try:
        done = subprocess.run(
            [str(adb), "version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _ADB_VERSION.search(done.stdout[:4096])
    return int(match.group(1)) if done.returncode == 0 and match else None


def xcrun_finds(xcrun: Path, name: str) -> bool:
    """Whether an Xcode command-line tool resolves; read-only, contacts no device."""
    try:
        done = subprocess.run(
            [str(xcrun), "--find", name], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _xcrun_tool(name: str) -> bool:
    xcrun = find_xcrun()
    return xcrun is not None and xcrun_finds(xcrun, name)


def _list_attached(adb: Path) -> Sequence[AttachedDevice]:
    return asyncio.run(list_devices(adb))


def default_probes(appium_port: int = APPIUM_PORT) -> dict[str, Callable]:
    return {
        "adb_server_version": adb_server_version,
        "adb_client_version": adb_client_version,
        "xcrun_tool": _xcrun_tool,
        "appium_up": lambda: appium_running(appium_port),
        "list_attached": _list_attached,
    }


def _text(value: object) -> str:
    """Lease content is untrusted: short printable text only."""
    text = str(value)
    return text if text.isprintable() and 0 < len(text) <= 128 else "?"


def _toolchain(toolchain: Toolchain, host: str) -> Check:
    try:
        pending = pending_names(toolchain, host)
    except (OSError, ValueError, LookupError) as error:
        return Check("Toolchain", False, f"cannot be checked: {error}; run 'visto setup'")
    if pending:
        return Check(
            "Toolchain", False, f"missing or outdated: {', '.join(pending)}; run 'visto setup'"
        )
    active = toolchain.state().active
    versions = ", ".join(f"{name} {active[name]}" for name in ("node", "jdk", "android-sdk"))
    return Check("Toolchain", True, f"{versions}, appium installed")


def _license(toolchain: Toolchain) -> Check:
    try:
        accepted = license_accepted(toolchain.state())
    except ValueError as error:
        return Check("Android SDK license", False, f"cannot be checked: {error}")
    if accepted:
        return Check("Android SDK license", True, "accepted")
    return Check("Android SDK license", False, "not accepted; run 'visto setup'")


def _devices(devices: Sequence[AttachedDevice]) -> Check:
    if not devices:
        return Check("Android devices", None, "none connected; enable USB debugging and plug in")
    parts = []
    for device in devices:
        if device.state == "device":
            parts.append(f"{device.serial} ready")
        elif device.state == "unauthorized":
            parts.append(f"{device.serial}: {UNAUTHORIZED}")
        else:
            parts.append(f"{device.serial}: {device.state}")
    ready = all(device.state == "device" for device in devices)
    return Check("Android devices", True if ready else None, "; ".join(parts))


def _adb(
    paths: ToolPaths | None,
    adb_server_version: Callable[[], int | None],
    adb_client_version: Callable[[Path], int | None],
    list_attached: Callable[[Path], Sequence[AttachedDevice]],
) -> list[Check]:
    adb = paths.adb if paths is not None else find_adb()
    if adb is None:
        return [Check("adb", False, "not found; run 'visto setup'")]
    client = adb_client_version(adb)
    if client is None:
        return [Check("adb", False, f"{adb} did not report a version; run 'visto setup'")]
    if paths is None:
        checks = [
            Check(
                "adb",
                None,
                f"version {client} at {adb}, not managed by Visto; run 'visto setup'",
            )
        ]
    else:
        checks = [Check("adb", True, f"version {client} at {adb}")]
    server = adb_server_version()
    if server is not None and server != client:
        checks.append(
            Check(
                "adb server",
                None,
                f"a running adb server uses version {server}, this adb {client}; quit the"
                " other tool that started it, otherwise its server will be restarted",
            )
        )
        checks.append(Check("Android devices", None, "not listed while that adb server runs"))
        return checks
    try:
        checks.append(_devices(list_attached(adb)))
    except InventoryUnavailable as error:
        checks.append(Check("Android devices", False, str(error)))
    return checks


def _key(store: SettingsStore) -> Check:
    try:
        configured = store.key_status().configured
    except SettingsError as error:
        return Check("Provider key", False, str(error))
    if configured:
        return Check("Provider key", True, "configured")
    return Check(
        "Provider key",
        False,
        "not configured; run 'visto settings set-key' or use the console Settings page",
    )


def _leases(home: VistoHome) -> Check:
    try:
        markers = sorted(home.leases.glob("*.lease")) if home.leases.is_dir() else []
    except OSError:
        return Check("Device leases", False, f"{home.leases} cannot be read")
    if not markers:
        return Check("Device leases", True, "none retained")
    parts = []
    for marker in markers:
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            parts.append(f"{marker} (unreadable)")
            continue
        parts.append(
            f"device {_text(data.get('device_id'))}, run {_text(data.get('run_id'))},"
            f" PID {_text(data.get('pid'))} ({marker})"
        )
    return Check(
        "Device leases", None, "retained: " + "; ".join(parts) + f"; recover as in {RECOVERY}"
    )


def _mac(home: VistoHome, paths: ToolPaths | None, xcrun_tool: Callable[[str], bool]) -> list:
    checks = []
    for tool in ("simctl", "devicectl"):
        found = xcrun_tool(tool)
        detail = "found" if found else "not found; install Xcode and its command-line tools"
        checks.append(Check(f"xcrun {tool}", True if found else None, detail))
    try:
        settings = SettingsStore(home).load()
    except SettingsError as error:
        checks.append(Check("iOS signing", False, str(error)))
        settings = None
    if settings is not None:
        ios = settings.ios
        signed = all(v.strip() for v in (ios.team_id, ios.signing_id, ios.wda_bundle_id))
        checks.append(
            Check(
                "iOS signing",
                True if signed else None,
                "configured" if signed else "not configured (needed for physical iPhones)",
            )
        )
    appium = None if paths is None else paths.appium_dir
    project = None if appium is None else wda_project(appium)
    checks.append(
        Check("WebDriverAgent project", True, str(project))
        if project is not None
        else Check("WebDriverAgent project", None, "not found; run 'visto setup'")
    )
    installed = (
        None if appium is None else installed_driver_version(appium, "appium-xcuitest-driver")
    )
    saved = None if settings is None else settings.ios_saved_for_xcuitest
    if installed is not None and saved is not None and installed != saved:
        checks.append(
            Check(
                "XCUITest driver",
                None,
                f"updated from {saved} to {installed}; rebuild and re-sign WebDriverAgent,"
                " then save the iOS settings again",
            )
        )
    elif installed is not None:
        checks.append(Check("XCUITest driver", True, f"version {installed}"))
    return checks


def collect_checks(
    home: VistoHome,
    *,
    host: str,
    adb_server_version: Callable[[], int | None],
    adb_client_version: Callable[[Path], int | None],
    xcrun_tool: Callable[[str], bool],
    appium_up: Callable[[], bool],
    list_attached: Callable[[Path], Sequence[AttachedDevice]] = _list_attached,
    appium_port: int = APPIUM_PORT,
) -> list[Check]:
    toolchain = Toolchain(home)
    try:
        paths = toolchain.paths()
    except (ToolchainMissing, ValueError):
        paths = None
    checks = [_toolchain(toolchain, host), _license(toolchain)]
    checks.append(
        Check("Appium", True, f"reachable at 127.0.0.1:{appium_port}")
        if appium_up()
        else Check("Appium", None, "not running; 'visto start' and 'visto run' start it")
    )
    checks += _adb(paths, adb_server_version, adb_client_version, list_attached)
    checks += [_key(SettingsStore(home)), _leases(home)]
    if host.startswith("macos-"):
        checks += _mac(home, paths, xcrun_tool)
    return checks


def _host() -> str:
    try:
        return host_key()
    except UnsupportedHost:
        return "unsupported"


def run_doctor(
    home: VistoHome,
    *,
    json_output: bool,
    output: Callable[[str], object] = print,
    fields: Mapping[str, object] | None = None,
    appium_port: int = APPIUM_PORT,
    **probes,
) -> int:
    """Exit codes: 0 when no check failed, 2 otherwise. `fields` extend the JSON output."""
    options = {"host": _host(), **default_probes(appium_port), **probes}
    listed = []
    list_attached = options.get("list_attached", _list_attached)

    def recorded(adb: Path) -> Sequence[AttachedDevice]:
        listed.append(adb)
        return list_attached(adb)

    options["list_attached"] = recorded
    checks = collect_checks(home, appium_port=appium_port, **options)
    code = PROBLEMS if any(check.ok is False for check in checks) else OK
    if json_output:
        data = {
            **(fields or {}),
            # `adb devices` asks the attached devices for their state; nothing else does.
            "device_contacted": bool(listed),
            "ok": code == OK,
            "checks": [asdict(check) for check in checks],
        }
        output(json.dumps(data, default=str, ensure_ascii=False))
    else:
        for check in checks:
            output(f"{_MARKS[check.ok]} {check.name}: {check.detail}")
    return code
