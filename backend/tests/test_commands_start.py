import os
import socket
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from visto.adapters.storage.migrations import CURRENT_VERSION, schema_version
from visto.commands import appium_process
from visto.commands.appium_process import AppiumProcess, PortBusy
from visto.commands.start import run_start
from visto.home import VistoHome
from visto.toolchain import Toolchain, ToolPaths, host_key, load_manifest
from visto.toolchain.appium import appium_flavor, appium_version
from visto.toolchain.license import record_acceptance


def write_entry(home: VistoHome, *, pid: int, kind: str) -> None:
    home.instances.mkdir(parents=True, exist_ok=True)
    (home.instances / f"{pid}.json").write_text(
        f'{{"pid": {pid}, "kind": "{kind}", "started_at": "2026-01-01T00:00:00+00:00"}}',
        encoding="utf-8",
    )


def installed_home(tmp_path: Path) -> VistoHome:
    home = VistoHome(tmp_path / "home")
    toolchain = Toolchain(home)
    manifest = load_manifest()
    host = host_key()
    versions = {name: manifest[name][host].version for name in ("node", "jdk", "android-sdk")}
    versions["appium"] = appium_version(appium_flavor(host))
    for name, version in versions.items():
        toolchain.component_dir(name, version).mkdir(parents=True)
    state = toolchain.state()
    state.active.update(versions)
    toolchain.save_state(state)
    record_acceptance(toolchain)
    return home


class FakePopen:
    def __init__(self, exit_after_polls: int | None = None):
        self.pid = 999999
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.polls = 0
        self.exit_after_polls = exit_after_polls
        self.ignore_terminate = False

    def poll(self):
        self.polls += 1
        if self.exit_after_polls is not None and self.polls > self.exit_after_polls:
            self.returncode = 1
        return self.returncode

    def _terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15

    def terminate(self):
        self._terminate()

    def send_signal(self, _signal):
        self._terminate()

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("appium", timeout)
        return self.returncode


@contextmanager
def listening_socket():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


@pytest.fixture
def quiet(monkeypatch):
    """No real port probe, no readiness request and no browser."""
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: False)
    monkeypatch.setattr(appium_process, "appium_running", lambda port: True)
    opened = []
    monkeypatch.setattr("visto.commands.start.webbrowser.open", opened.append)
    return opened


def never(app, port, **kwargs):
    raise AssertionError("serve must not be called")


def immediate(app, port, **kwargs):
    return None


def raising(error):
    def serve(app, port, **kwargs):
        raise error("server failed")

    return serve


def capturing(captured):
    def popen(argv, **kwargs):
        captured.update(kwargs, argv=argv)
        return FakePopen()

    return popen


def test_start_refuses_busy_port(tmp_path):
    lines = []
    with listening_socket() as port:
        code = run_start(
            installed_home(tmp_path),
            port=port,
            open_browser=False,
            serve=never,
            output=lines.append,
        )
    assert code == 3 and lines == [f"Port {port} is in use; pass --port"]


def test_start_refuses_busy_appium_port(tmp_path, monkeypatch):
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: port == 4723)
    lines = []
    code = run_start(
        installed_home(tmp_path),
        open_browser=False,
        serve=never,
        output=lines.append,
        popen=capturing({}),
    )
    assert code == 3 and "4723" in lines[-1]


def test_appium_child_terminated_on_exit(tmp_path, quiet):
    proc = FakePopen()
    assert (
        run_start(
            installed_home(tmp_path),
            open_browser=False,
            serve=raising(RuntimeError),
            popen=lambda *a, **k: proc,
        )
        == 3
    )
    assert proc.terminated or proc.killed


def test_appium_env_is_child_only(tmp_path, monkeypatch, quiet):
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    captured = {}
    run_start(
        installed_home(tmp_path), open_browser=False, serve=immediate, popen=capturing(captured)
    )
    assert "ANDROID_HOME" in captured["env"] and "ANDROID_HOME" not in os.environ


def test_appium_command_line_and_log(tmp_path, quiet):
    home = installed_home(tmp_path)
    captured = {}
    assert run_start(home, open_browser=False, serve=immediate, popen=capturing(captured)) == 0
    paths = Toolchain(home).paths()
    assert captured["argv"] == [
        str(paths.node),
        str(paths.appium_dir / "node_modules" / "appium" / "index.js"),
        "--address",
        "127.0.0.1",
        "--port",
        "4723",
        "--log-level",
        "warn",
    ]
    assert captured["cwd"] == paths.appium_dir
    assert captured.get("shell", False) is False
    assert (home.logs / "appium.log").is_file()
    assert "OPENAI_API_KEY" not in captured["env"]


def test_serve_gets_app_on_loopback_port_and_browser_opens(tmp_path, quiet):
    seen = {}

    def serve(app, port, *, ready, stop):
        seen.update(app=app, port=port)
        ready()
        assert stop() is False

    assert run_start(installed_home(tmp_path), port=8123, serve=serve, popen=capturing({})) == 0
    assert seen["port"] == 8123 and quiet == ["http://127.0.0.1:8123/"]


def test_console_runs_use_the_appium_port_start_launched(tmp_path, quiet, monkeypatch):
    import visto.commands.start as start

    captured, argv = [], {}
    monkeypatch.setattr(start, "create_app", lambda **kwargs: captured.append(kwargs))
    code = run_start(
        installed_home(tmp_path),
        appium_port=4801,
        open_browser=False,
        serve=immediate,
        popen=capturing(argv),
    )
    assert code == 0 and "4801" in argv["argv"]
    assert captured[0]["appium_url"] == "http://127.0.0.1:4801"


def test_no_browser_when_disabled(tmp_path, quiet):
    def serve(app, port, *, ready, stop):
        ready()

    run_start(installed_home(tmp_path), open_browser=False, serve=serve, popen=capturing({}))
    assert quiet == []


def test_appium_dying_while_serving_exits_3(tmp_path, quiet):
    proc, lines = FakePopen(), []

    def serve(app, port, *, ready, stop):
        proc.returncode = 1
        assert stop() is True

    code = run_start(
        installed_home(tmp_path),
        open_browser=False,
        serve=serve,
        popen=lambda *a, **k: proc,
        output=lines.append,
    )
    assert code == 3 and any("Appium" in line for line in lines)


def test_second_start_is_refused(tmp_path, quiet):
    home = installed_home(tmp_path)
    write_entry(home, pid=os.getppid(), kind="start")
    lines = []
    code = run_start(home, open_browser=False, serve=never, output=lines.append)
    assert code == 4 and lines == ["Visto is already running"]


def test_pending_toolchain_runs_setup_first(tmp_path, quiet, monkeypatch):
    home = VistoHome(tmp_path / "empty")
    calls, lines = [], []

    def fake_setup(setup_home, **kwargs):
        calls.append(kwargs)
        return 2

    monkeypatch.setattr("visto.commands.start.run_setup", fake_setup)
    code = run_start(
        home, open_browser=False, serve=never, output=lines.append, accept_license=True
    )
    assert code == 2 and calls[0]["accept_license"] is True
    assert lines[0].startswith("Updating components: ") and "android-sdk" in lines[0]


def test_ca_bundle_is_exported_for_the_server_process(tmp_path, quiet, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    home = installed_home(tmp_path)
    toolchain = Toolchain(home)
    state = toolchain.state()
    state.ca_bundle = str(tmp_path / "corporate.pem")
    toolchain.save_state(state)
    seen = {}

    def serve(app, port, **kwargs):
        seen["ssl"] = os.environ.get("SSL_CERT_FILE")

    captured = {}
    run_start(home, open_browser=False, serve=serve, popen=capturing(captured))
    assert seen["ssl"] == state.ca_bundle
    assert captured["env"]["NODE_EXTRA_CA_CERTS"] == state.ca_bundle


def test_newer_database_is_refused(tmp_path, quiet):
    home = installed_home(tmp_path)
    home.data.mkdir(parents=True)
    connection = sqlite3.connect(home.data / "runs.sqlite3")
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    lines = []
    code = run_start(home, open_browser=False, serve=never, output=lines.append)
    assert code == 3
    assert lines[-1] == (
        "This data was written by a newer Visto; install that version or restore a backup"
        f" from {home.data}"
    )


def old_database(data: Path) -> Path:
    """A database from before numbered migrations: tables present, user_version 0."""
    data.mkdir(parents=True, exist_ok=True)
    database = data / "runs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.close()
    return database


def test_upgrade_refused_while_other_processes_use_the_home(tmp_path, quiet):
    home = installed_home(tmp_path)
    database = old_database(home.data)
    write_entry(home, pid=os.getppid(), kind="run")
    lines = []
    code = run_start(home, open_browser=False, serve=never, output=lines.append)
    assert code == 4 and lines == ["Stop other Visto processes before upgrading data"]
    assert schema_version(database) == 0 and list(home.data.glob("*.bak")) == []


def test_new_database_is_created_while_other_processes_run(tmp_path, quiet):
    home = installed_home(tmp_path)
    write_entry(home, pid=os.getppid(), kind="inspect")
    assert run_start(home, open_browser=False, serve=immediate, popen=capturing({})) == 0
    assert schema_version(home.data / "runs.sqlite3") == CURRENT_VERSION


# --- AppiumProcess -------------------------------------------------------------


def tool_paths(tmp_path: Path) -> ToolPaths:
    appium = tmp_path / "appium"
    appium.mkdir()
    return ToolPaths(tmp_path / "node", tmp_path, tmp_path, tmp_path / "adb", appium)


def test_appium_process_refuses_listening_port(tmp_path):
    with listening_socket() as port:
        with pytest.raises(PortBusy):
            AppiumProcess.start(
                tool_paths(tmp_path), {}, port, tmp_path / "a.log", popen=capturing({})
            )


def test_appium_exiting_during_startup_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: False)
    monkeypatch.setattr(appium_process, "appium_running", lambda port: False)
    with pytest.raises(RuntimeError):
        AppiumProcess.start(
            tool_paths(tmp_path),
            {},
            4723,
            tmp_path / "a.log",
            popen=lambda *a, **k: FakePopen(exit_after_polls=1),
        )


def test_appium_not_ready_in_time_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: False)
    monkeypatch.setattr(appium_process, "appium_running", lambda port: False)
    proc = FakePopen()
    with pytest.raises(RuntimeError):
        AppiumProcess.start(
            tool_paths(tmp_path),
            {},
            4723,
            tmp_path / "a.log",
            popen=lambda *a, **k: proc,
            ready_timeout_s=0.05,
        )
    assert proc.terminated


@pytest.fixture(autouse=True)
def forced(monkeypatch):
    """Record forced group/tree kills instead of signalling real (fake) PIDs."""
    calls = []
    monkeypatch.setattr(appium_process, "_kill_tree", lambda pid: calls.append(("tree", pid)))
    monkeypatch.setattr(appium_process, "_kill_group", lambda pid: calls.append(("group", pid)))
    return calls


def started(tmp_path, monkeypatch, proc):
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: False)
    monkeypatch.setattr(appium_process, "appium_running", lambda port: True)
    return AppiumProcess.start(
        tool_paths(tmp_path), {}, 4723, tmp_path / "a.log", popen=lambda *a, **k: proc
    )


def test_stop_kills_when_terminate_is_ignored(tmp_path, monkeypatch, forced):
    proc = FakePopen()
    proc.ignore_terminate = True
    process = started(tmp_path, monkeypatch, proc)
    assert process.alive()
    process.stop(timeout_s=0.01)
    assert proc.terminated and proc.killed and not process.alive()
    assert forced == [("tree" if os.name == "nt" else "group", proc.pid)]


def test_interrupt_during_graceful_wait_still_kills(tmp_path, monkeypatch, forced):
    proc = FakePopen()
    proc.ignore_terminate = True
    process = started(tmp_path, monkeypatch, proc)
    real_wait = proc.wait
    waits = []

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) == 1:
            raise KeyboardInterrupt
        return real_wait(timeout)

    proc.wait = wait
    with pytest.raises(KeyboardInterrupt):
        process.stop()
    assert proc.killed and len(forced) == 1


def test_graceful_stop_does_not_force(tmp_path, monkeypatch, forced):
    proc = FakePopen()
    started(tmp_path, monkeypatch, proc).stop()
    assert proc.terminated and not proc.killed and forced == []


def test_termination_signal_while_serving_stops_appium(tmp_path, quiet):
    import signal

    proc = FakePopen()
    before = signal.getsignal(signal.SIGTERM)

    def serve(app, port, **kwargs):
        signal.raise_signal(signal.SIGTERM)
        for _ in range(1000):  # The Python-level handler runs between bytecodes.
            pass
        raise AssertionError("SIGTERM did not interrupt serving")

    code = run_start(
        installed_home(tmp_path), open_browser=False, serve=serve, popen=lambda *a, **k: proc
    )
    assert code == 0 and proc.terminated
    assert signal.getsignal(signal.SIGTERM) is before


def test_windows_child_gets_its_own_process_group(tmp_path, monkeypatch):
    monkeypatch.setattr(appium_process, "port_in_use", lambda port: False)
    monkeypatch.setattr(appium_process, "appium_running", lambda port: True)
    captured = {}
    AppiumProcess.start(
        tool_paths(tmp_path), {}, 4723, tmp_path / "a.log", popen=capturing(captured)
    )
    if os.name == "nt":
        assert captured["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert captured["start_new_session"] is True


def test_appium_running_is_false_when_nothing_listens():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert appium_process.appium_running(port) is False


def test_uvicorn_serve_announces_readiness_and_honours_stop():
    from fastapi import FastAPI

    from visto.commands.start import uvicorn_serve

    announced = []
    uvicorn_serve(FastAPI(), 0, ready=lambda: announced.append(True), stop=lambda: True)
    assert announced == [True]
