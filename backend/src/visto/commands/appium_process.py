"""The managed Appium server: a child process bound to loopback, stopped with Visto."""

import os
import signal
import socket
import subprocess
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from visto.home import make_private_dir
from visto.toolchain import ToolPaths

LOOPBACK = "127.0.0.1"
POLL_S = 0.25
_WINDOWS = os.name == "nt"


class PortBusy(RuntimeError):
    """Something already accepts connections on the port."""


class AppiumFailed(RuntimeError):
    """Appium exited or did not become ready."""


def port_in_use(port: int) -> bool:
    """True when 127.0.0.1:<port> accepts a TCP connection. Binds nothing."""
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.5):
            return True
    except OSError:
        return False


# Loopback only: never route the readiness probe through a configured proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def appium_running(port: int) -> bool:
    """True when GET http://127.0.0.1:<port>/status answers 200."""
    try:
        with _DIRECT.open(f"http://{LOOPBACK}:{port}/status", timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _kill_group(pid: int) -> None:
    """POSIX: SIGKILL Appium's own session group (it leads it), drivers included."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def _kill_tree(pid: int) -> None:
    """Windows: force-stop the process and every descendant (drivers included)."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    taskkill = str(Path(root) / "System32" / "taskkill.exe")
    try:
        subprocess.run(
            [taskkill, "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


class AppiumProcess:
    def __init__(self, process: subprocess.Popen, log_file: Path):
        self._process = process
        self.log_file = log_file

    @classmethod
    def start(
        cls,
        paths: ToolPaths,
        env: dict,
        port: int,
        log_file: Path,
        *,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        ready_timeout_s: float = 60,
    ) -> "AppiumProcess":
        if paths.appium_dir is None:
            raise AppiumFailed("Appium is not installed; run 'visto setup'")
        if port_in_use(port):
            raise PortBusy(f"Port {port} is in use")
        argv = [
            str(paths.node),
            str(paths.appium_dir / "node_modules" / "appium" / "index.js"),
            "--address",
            LOOPBACK,
            "--port",
            str(port),
            "--log-level",
            "warn",
        ]
        # Appium leads its own process group: terminal Ctrl+C reaches only Visto, which
        # stops Appium itself, and the forced stop reaches the whole group or tree
        # (CTRL_BREAK and taskkill /T on Windows, killpg on POSIX), drivers included.
        group = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if _WINDOWS
            else {"start_new_session": True}
        )
        make_private_dir(log_file.parent)
        descriptor = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab") as log:
            process = popen(
                argv,
                cwd=paths.appium_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                **group,
            )
        appium = cls(process, log_file)
        try:
            appium._wait_ready(port, time.monotonic() + ready_timeout_s)
        except BaseException:
            appium.stop()
            raise
        return appium

    def _wait_ready(self, port: int, deadline: float) -> None:
        while True:
            if not self.alive():
                raise AppiumFailed(f"Appium exited during startup; see {self.log_file}")
            if appium_running(port):
                return
            if time.monotonic() >= deadline:
                raise AppiumFailed(f"Appium was not ready in time; see {self.log_file}")
            time.sleep(POLL_S)

    def alive(self) -> bool:
        return self._process.poll() is None

    def stop(self, timeout_s: float = 10) -> None:
        """Ask Appium to stop, then force it with its process group or tree.

        The forced step runs in a `finally`, so an interrupt while waiting for the
        graceful exit still ends in a kill.
        """
        process = self._process
        if process.poll() is not None:
            return
        try:
            try:
                if _WINDOWS:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
            except OSError:
                pass
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if process.poll() is None:
                self._force(timeout_s)

    def _force(self, timeout_s: float) -> None:
        process = self._process
        if _WINDOWS:
            _kill_tree(process.pid)
        else:
            _kill_group(process.pid)
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            pass
