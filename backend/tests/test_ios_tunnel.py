import os
import subprocess
from pathlib import Path

import pytest

from visto.commands import ios_tunnel
from visto.commands.ios_tunnel import REGISTRY_PORT, IosTunnel, TunnelUnavailable
from visto.toolchain import ToolPaths


def tool_paths(tmp_path: Path, *, with_script: bool = True) -> tuple[ToolPaths, Path]:
    appium = tmp_path / "appium"
    script = appium / "node_modules" / "appium-xcuitest-driver" / "scripts" / "tunnel-creation.mjs"
    if with_script:
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
    (tmp_path / "node").write_text("", encoding="utf-8")
    paths = ToolPaths(
        node=tmp_path / "node",
        java_home=tmp_path,
        android_home=tmp_path,
        adb=tmp_path / "adb",
        appium_dir=appium,
    )
    return paths, script


class FakeSudo:
    def __init__(self, *, authenticated=True, refreshed=True, terminates=True):
        self.authenticated = authenticated
        self.refreshed = refreshed
        self.terminates = terminates
        self.refreshes = 0
        self.terminated = []

    def authenticate(self) -> bool:
        return self.authenticated

    def refresh(self) -> bool:
        self.refreshes += 1
        return self.refreshed

    def terminate(self, pid: int) -> bool:
        self.terminated.append(pid)
        return self.terminates


class FakeProcess:
    pid = 4242

    def __init__(self, exit_code=None):
        self.returncode = exit_code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class StuckProcess(FakeProcess):
    """A sudo process that does not exit when its child is told to stop."""

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("sudo", timeout)


def recording_popen(seen, process=None):
    def popen(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return process or FakeProcess()

    return popen


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(ios_tunnel, "port_in_use", lambda port: port == REGISTRY_PORT)


def test_tunnel_runs_the_driver_script_as_root_and_waits_for_its_registry(tmp_path, ready):
    paths, script = tool_paths(tmp_path)
    seen = {}
    tunnel = IosTunnel.start(
        paths, tmp_path / "tunnel.log", home=tmp_path, sudo=FakeSudo(), popen=recording_popen(seen)
    )
    assert seen["argv"] == ["sudo", "-n", str(paths.node), str(script)]
    assert seen["cwd"] == script.parent.parent
    # sudo ties its cached credential to the terminal: the script must keep it.
    assert seen.get("start_new_session") is not True
    assert seen["shell"] is False
    assert (tmp_path / "tunnel.log").is_file()
    tunnel.stop()


def test_stop_terminates_only_the_children_of_the_sudo_it_started(tmp_path, ready):
    paths, _ = tool_paths(tmp_path)
    sudo = FakeSudo()
    tunnel = IosTunnel.start(
        paths, tmp_path / "tunnel.log", home=tmp_path, sudo=sudo, popen=recording_popen({})
    )
    tunnel.stop()
    assert sudo.terminated == [FakeProcess.pid]


def test_refresh_keeps_the_credential_alive_while_running(tmp_path, ready, monkeypatch):
    paths, _ = tool_paths(tmp_path)
    monkeypatch.setattr(ios_tunnel, "REFRESH_S", 0.01)
    sudo = FakeSudo()
    tunnel = IosTunnel.start(
        paths, tmp_path / "tunnel.log", home=tmp_path, sudo=sudo, popen=recording_popen({})
    )
    deadline = 200
    while sudo.refreshes < 2 and deadline:
        deadline -= 1
        ios_tunnel.time.sleep(0.01)
    tunnel.stop()
    assert sudo.refreshes >= 2


def test_missing_script_is_reported_before_anything_runs(tmp_path, ready):
    paths, _ = tool_paths(tmp_path, with_script=False)
    seen = {}
    with pytest.raises(TunnelUnavailable, match="visto setup"):
        IosTunnel.start(
            paths,
            tmp_path / "tunnel.log",
            home=tmp_path,
            sudo=FakeSudo(),
            popen=recording_popen(seen),
        )
    assert not seen


def test_script_that_exits_during_startup_is_reported(tmp_path, monkeypatch):
    paths, _ = tool_paths(tmp_path)
    monkeypatch.setattr(ios_tunnel, "port_in_use", lambda port: False)
    with pytest.raises(TunnelUnavailable, match="exited during startup"):
        IosTunnel.start(
            paths,
            tmp_path / "tunnel.log",
            home=tmp_path,
            sudo=FakeSudo(),
            popen=recording_popen({}, FakeProcess(exit_code=1)),
        )


def test_registry_that_never_answers_times_out_and_stops_the_script(tmp_path, monkeypatch):
    paths, script = tool_paths(tmp_path)
    monkeypatch.setattr(ios_tunnel, "port_in_use", lambda port: False)
    sudo = FakeSudo()
    with pytest.raises(TunnelUnavailable, match="not ready in time"):
        IosTunnel.start(
            paths,
            tmp_path / "tunnel.log",
            home=tmp_path,
            sudo=sudo,
            popen=recording_popen({}),
            ready_timeout_s=0.01,
        )
    assert sudo.terminated == [FakeProcess.pid]


class ExitingProcess(FakeProcess):
    def __init__(self):
        super().__init__()

    def poll(self):
        return self.returncode

    def finish(self, code=0):
        self.returncode = code


def wait_for(condition, attempts=300):
    while not condition() and attempts:
        attempts -= 1
        ios_tunnel.time.sleep(0.01)
    return condition()


def test_tunnel_that_stops_for_lack_of_usb_devices_says_so(tmp_path, ready, monkeypatch):
    monkeypatch.setattr(ios_tunnel, "WATCH_S", 0.01)
    paths, _ = tool_paths(tmp_path)
    log = tmp_path / "tunnel.log"
    process = ExitingProcess()
    notices = []
    IosTunnel.start(
        paths,
        log,
        home=tmp_path,
        sudo=FakeSudo(),
        popen=recording_popen({}, process),
        notify=notices.append,
    )
    log.write_text("WARN TunnelCreation No USB devices found.\n", encoding="utf-8")
    process.finish()
    assert wait_for(lambda: notices)
    assert "USB cable" in notices[0] and "next iOS run" in notices[0]


def test_tunnel_that_stops_for_another_reason_points_to_the_log(tmp_path, ready, monkeypatch):
    monkeypatch.setattr(ios_tunnel, "WATCH_S", 0.01)
    paths, _ = tool_paths(tmp_path)
    log = tmp_path / "tunnel.log"
    process = ExitingProcess()
    notices = []
    IosTunnel.start(
        paths,
        log,
        home=tmp_path,
        sudo=FakeSudo(),
        popen=recording_popen({}, process),
        notify=notices.append,
    )
    process.finish(1)
    assert wait_for(lambda: notices)
    assert str(log) in notices[0]


def test_stopping_the_tunnel_does_not_report_an_exit(tmp_path, ready, monkeypatch):
    monkeypatch.setattr(ios_tunnel, "WATCH_S", 0.01)
    paths, _ = tool_paths(tmp_path)
    process = ExitingProcess()
    notices = []
    tunnel = IosTunnel.start(
        paths,
        tmp_path / "tunnel.log",
        home=tmp_path,
        sudo=FakeSudo(),
        popen=recording_popen({}, process),
        notify=notices.append,
    )
    tunnel.stop()
    process.finish()
    ios_tunnel.time.sleep(0.1)
    assert notices == []


def started(tmp_path, *, sudo=None, process=None, notices=None):
    paths, _ = tool_paths(tmp_path)
    return IosTunnel.start(
        paths,
        tmp_path / "tunnel.log",
        home=tmp_path,
        sudo=sudo or FakeSudo(),
        popen=recording_popen({}, process),
        notify=(notices.append if notices is not None else lambda message: None),
    )


def test_begin_stop_silences_the_exit_notice_without_terminating(tmp_path, ready, monkeypatch):
    monkeypatch.setattr(ios_tunnel, "WATCH_S", 0.01)
    process, notices, sudo = ExitingProcess(), [], FakeSudo()
    tunnel = started(tmp_path, sudo=sudo, process=process, notices=notices)
    tunnel.begin_stop()
    # Ctrl+C reaches sudo too: the script may end while Appium is still stopping.
    process.finish()
    ios_tunnel.time.sleep(0.1)
    assert notices == [] and sudo.terminated == []
    tunnel.stop()


def test_failed_refresh_is_reported_once(tmp_path, ready, monkeypatch):
    monkeypatch.setattr(ios_tunnel, "REFRESH_S", 0.01)
    sudo, notices = FakeSudo(refreshed=False), []
    tunnel = started(tmp_path, sudo=sudo, notices=notices)
    assert wait_for(lambda: sudo.refreshes >= 3)
    tunnel.stop()
    assert len(notices) == 1
    assert "administrator credential expired" in notices[0]
    assert "may not be able to stop the iOS tunnel" in notices[0]


def test_failed_terminate_names_the_manual_command(tmp_path, ready):
    notices = []
    tunnel = started(
        tmp_path, sudo=FakeSudo(terminates=False), process=StuckProcess(), notices=notices
    )
    tunnel.stop(timeout_s=0.01)
    assert notices == [
        "The iOS tunnel may still be running as root; stop it with:"
        f" sudo kill -TERM {FakeProcess.pid}"
    ]


def test_tunnel_that_outlives_the_wait_names_the_manual_command(tmp_path, ready):
    notices = []
    tunnel = started(tmp_path, process=StuckProcess(), notices=notices)
    tunnel.stop(timeout_s=0.01)
    assert len(notices) == 1 and f"sudo kill -TERM {FakeProcess.pid}" in notices[0]


def test_tunnel_that_exits_after_a_failed_terminate_is_not_reported(tmp_path, ready):
    notices, process = [], ExitingProcess()
    tunnel = started(tmp_path, sudo=FakeSudo(terminates=False), process=process, notices=notices)
    process.finish()
    tunnel.stop(timeout_s=0.01)
    assert notices == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruption_while_waiting_for_readiness_stops_the_tunnel(
    tmp_path, monkeypatch, interruption
):
    paths, _ = tool_paths(tmp_path)

    def interrupted(port):
        raise interruption

    monkeypatch.setattr(ios_tunnel, "port_in_use", interrupted)
    sudo = FakeSudo()
    with pytest.raises(interruption):
        IosTunnel.start(
            paths, tmp_path / "tunnel.log", home=tmp_path, sudo=sudo, popen=recording_popen({})
        )
    assert sudo.terminated == [FakeProcess.pid]


posix = pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes")


@posix
@pytest.mark.parametrize("target", ["node", "script", "script directory", "appium directory"])
def test_writable_code_is_refused_before_anything_runs(tmp_path, ready, target):
    paths, script = tool_paths(tmp_path)
    path = {
        "node": paths.node,
        "script": script,
        "script directory": script.parent,
        "appium directory": paths.appium_dir,
    }[target]
    path.chmod(path.stat().st_mode | 0o020)
    seen = {}
    with pytest.raises(TunnelUnavailable, match="writable by other users") as error:
        IosTunnel.start(
            paths,
            tmp_path / "tunnel.log",
            home=tmp_path,
            sudo=FakeSudo(),
            popen=recording_popen(seen),
        )
    assert str(path) in str(error.value)
    assert not seen


@posix
def test_code_owned_by_another_user_is_refused(tmp_path, ready, monkeypatch):
    paths, _ = tool_paths(tmp_path)
    real = os.getuid()
    assert real != 0
    monkeypatch.setattr(ios_tunnel.os, "getuid", lambda: real + 1)
    seen = {}
    with pytest.raises(TunnelUnavailable, match="owned by another user"):
        ios_tunnel.check_trusted(paths, tmp_path)
    with pytest.raises(TunnelUnavailable):
        IosTunnel.start(
            paths,
            tmp_path / "tunnel.log",
            home=tmp_path,
            sudo=FakeSudo(),
            popen=recording_popen(seen),
        )
    assert not seen


def test_missing_node_is_refused(tmp_path):
    paths, _ = tool_paths(tmp_path)
    paths.node.unlink()
    with pytest.raises(TunnelUnavailable, match="visto setup"):
        ios_tunnel.check_trusted(paths, tmp_path)


def test_trusted_code_returns_the_script(tmp_path):
    paths, script = tool_paths(tmp_path)
    assert ios_tunnel.check_trusted(paths, tmp_path) == script


# --- The real Sudo, with subprocess.run replaced: real sudo is never called --------


@pytest.fixture
def runs(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, calls_result[0])

    calls_result = [0]
    monkeypatch.setattr(ios_tunnel.subprocess, "run", run)
    return calls, calls_result


def test_real_sudo_authenticates_in_the_terminal(runs):
    calls, _ = runs
    assert ios_tunnel.Sudo().authenticate() is True
    argv, kwargs = calls[0]
    assert argv == ["sudo", "-v"] and not kwargs.get("shell")


def test_real_sudo_refreshes_without_prompting(runs):
    calls, result = runs
    assert ios_tunnel.Sudo().refresh() is True
    result[0] = 1
    assert ios_tunnel.Sudo().refresh() is False
    argv, kwargs = calls[0]
    assert argv == ["sudo", "-n", "-v"] and not kwargs.get("shell") and kwargs["timeout"]


def test_real_sudo_signals_only_the_sudo_it_started_which_relays_to_the_script(runs):
    calls, result = runs
    assert ios_tunnel.Sudo().terminate(4242) is True
    argv, kwargs = calls[0]
    assert argv == ["sudo", "-n", "kill", "-TERM", "4242"]
    assert not kwargs.get("shell") and kwargs["timeout"]
    result[0] = 1
    assert ios_tunnel.Sudo().terminate(4242) is False


def test_real_sudo_terminate_reports_a_failure_to_run(monkeypatch):
    def failing(argv, **kwargs):
        raise OSError("no sudo")

    monkeypatch.setattr(ios_tunnel.subprocess, "run", failing)
    assert ios_tunnel.Sudo().terminate(4242) is False


# --- The supervisor: one tunnel per Visto, started again before an iOS run ---

UDID = "00008000-000A000A00000000"


class Launches:
    """A popen whose scripts the test can end, one process per launch."""

    def __init__(self):
        self.processes = []

    def __call__(self, argv, **kwargs):
        process = ExitingProcess()
        process.pid = 5000 + len(self.processes)
        self.processes.append(process)
        return process


def supervisor(tmp_path, launches, *, sudo=None, notices=None):
    paths, _ = tool_paths(tmp_path)
    return ios_tunnel.TunnelSupervisor(
        paths,
        tmp_path / "tunnel.log",
        home=tmp_path,
        sudo=sudo or FakeSudo(),
        popen=launches,
        notify=(notices.append if notices is not None else lambda message: None),
    )


@pytest.fixture
def registry(monkeypatch):
    """The registry port answers while one of our scripts runs; device waits are recorded."""
    state = {"alive": lambda: False, "waits": []}
    monkeypatch.setattr(
        ios_tunnel, "port_in_use", lambda port: port == REGISTRY_PORT and state["alive"]()
    )

    def ready(udid, timeout_s):
        state["waits"].append((udid, timeout_s))
        return True

    monkeypatch.setattr(ios_tunnel, "device_tunnel_ready", ready)
    return state


def test_an_ended_tunnel_is_started_again_before_an_ios_run(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: any(p.returncode is None for p in launches.processes)
    tunnels = supervisor(tmp_path, launches)
    tunnels.start()
    launches.processes[0].finish()  # No phone on USB when Visto started.
    assert tunnels.ensure(UDID, 20) is True
    assert len(launches.processes) == 2
    assert registry["waits"][-1][0] == UDID and 0 < registry["waits"][-1][1] <= 20
    tunnels.stop()


def test_a_running_tunnel_is_not_started_twice(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: any(p.returncode is None for p in launches.processes)
    tunnels = supervisor(tmp_path, launches)
    tunnels.start()
    assert tunnels.ensure(UDID, 20) is True
    assert len(launches.processes) == 1
    tunnels.stop()


def test_a_tunnel_started_by_someone_else_is_used_not_replaced(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: True  # The operator runs the script by hand.
    tunnels = supervisor(tmp_path, launches)
    tunnels.start()
    assert tunnels.ensure(UDID, 20) is True
    assert launches.processes == []
    tunnels.stop()


def test_a_failed_relaunch_is_reported_and_never_raises(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: any(p.returncode is None for p in launches.processes)
    notices = []
    tunnels = supervisor(tmp_path, launches, notices=notices)
    tunnels.start()
    launches.processes[0].finish()
    (tmp_path / "appium" / ios_tunnel.SCRIPT).unlink()
    assert tunnels.ensure(UDID, 20) is False
    assert any(line.startswith("The iOS tunnel was not started") for line in notices)
    tunnels.stop()


def test_nothing_is_started_once_visto_is_stopping(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: any(p.returncode is None for p in launches.processes)
    tunnels = supervisor(tmp_path, launches)
    tunnels.start()
    launches.processes[0].finish()
    tunnels.begin_stop()
    assert tunnels.ensure(UDID, 20) is False
    assert len(launches.processes) == 1
    tunnels.stop()


def test_stop_ends_the_current_script(tmp_path, registry):
    launches = Launches()
    registry["alive"] = lambda: any(p.returncode is None for p in launches.processes)
    sudo = FakeSudo()
    tunnels = supervisor(tmp_path, launches, sudo=sudo)
    tunnels.start()
    launches.processes[0].finish()
    tunnels.ensure(UDID, 20)
    tunnels.stop()
    assert sudo.terminated == [launches.processes[1].pid]


class Opener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, url, timeout):
        self.requests.append((url, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return Response(self.outcome)


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_device_tunnel_wait_long_polls_the_loopback_registry(monkeypatch):
    opener = Opener(200)
    monkeypatch.setattr(ios_tunnel, "_DIRECT", opener)
    assert ios_tunnel.device_tunnel_ready(UDID, 12) is True
    url, timeout = opener.requests[0]
    assert url == f"http://127.0.0.1:{REGISTRY_PORT}/remotexpc/tunnels/{UDID}?waitMs=10000"
    assert timeout == 12


@pytest.mark.parametrize("outcome", [OSError("refused"), 404])
def test_device_without_a_tunnel_is_not_ready(monkeypatch, outcome):
    monkeypatch.setattr(ios_tunnel, "_DIRECT", Opener(outcome))
    assert ios_tunnel.device_tunnel_ready(UDID, 5) is False


def test_malformed_device_id_is_never_sent(monkeypatch):
    opener = Opener(200)
    monkeypatch.setattr(ios_tunnel, "_DIRECT", opener)
    assert ios_tunnel.device_tunnel_ready("../../metadata", 5) is False
    assert opener.requests == []


def test_a_simulator_needs_no_tunnel(tmp_path, registry):
    launches = Launches()
    tunnels = supervisor(tmp_path, launches)
    assert tunnels.ensure("00000000-0000-0000-0000-00000000000A", 20) is False
    assert launches.processes == [] and registry["waits"] == []


def test_a_run_never_waits_longer_than_its_budget_for_another_launch(tmp_path, registry):
    launches = Launches()
    tunnels = supervisor(tmp_path, launches)
    tunnels._lock.acquire()  # Another run is starting the tunnel right now.
    try:
        started = ios_tunnel.time.monotonic()
        assert tunnels.ensure(UDID, 0.2) is False
        assert ios_tunnel.time.monotonic() - started < 1
    finally:
        tunnels._lock.release()
    assert launches.processes == []
