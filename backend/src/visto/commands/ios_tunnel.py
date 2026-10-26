"""The RemoteXPC tunnel Appium needs to see physical iOS 17+ devices.

The driver's `tunnel-creation` script must run as root. Visto asks for the
administrator password once in its own terminal, keeps the credential fresh while
`visto start` runs, and stops the script with `sudo kill -TERM <sudo pid>` because
root processes cannot be signalled by the user. Only the sudo process Visto started
is signalled; sudo relays the signal to the script, however many processes sudo
itself uses (one was seen running sudo, a second sudo, then node).

The script only builds tunnels for phones on USB when it starts and exits when it
finds none, so `TunnelSupervisor` starts it again before an iOS run if it has ended.
"""

import os
import re
import stat
import subprocess
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from visto.commands.appium_process import port_in_use
from visto.home import make_private_dir
from visto.toolchain import ToolPaths

REGISTRY_PORT = 42314
REFRESH_S = 60
WATCH_S = 1
POLL_S = 0.25
READY_TIMEOUT_S = 30
# Margin for the registry to answer after its own long-poll ends.
ANSWER_MARGIN_S = 2
_UDID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
# Simulator UDIDs are UUIDs; a phone's UDID is not, and only a phone needs a tunnel.
_SIMULATOR = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$", re.I)
# Loopback only: never route the registry request through a configured proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SCRIPT = Path("node_modules", "appium-xcuitest-driver", "scripts", "tunnel-creation.mjs")


class TunnelUnavailable(RuntimeError):
    """The tunnel could not be started; the message says what the operator can do."""


class Sudo:
    """The privileged commands. Tests replace this object; nothing else calls sudo."""

    def authenticate(self) -> bool:
        """Ask for the password in this terminal."""
        try:
            return subprocess.run(["sudo", "-v"], check=False).returncode == 0
        except OSError:
            return False

    def refresh(self) -> bool:
        """Extend the cached credential without prompting."""
        try:
            result = subprocess.run(
                ["sudo", "-n", "-v"], capture_output=True, check=False, timeout=30
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def terminate(self, pid: int) -> bool:
        """Signal the sudo process `pid` without prompting; True if the signal was sent."""
        try:
            result = subprocess.run(
                stop_command(pid, prompt=False),
                capture_output=True,
                check=False,
                timeout=30,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def stop_command(pid: int, *, prompt: bool = True) -> list[str]:
    """Signal the sudo process Visto started: sudo relays it to the command it runs."""
    return ["sudo", *(() if prompt else ("-n",)), "kill", "-TERM", str(pid)]


def device_tunnel_ready(udid: str, timeout_s: float) -> bool:
    """Long-poll the driver's registry until it lists a tunnel for this phone."""
    if not _UDID.fullmatch(udid):
        return False
    wait_ms = int(max(timeout_s - ANSWER_MARGIN_S, 0) * 1000)
    url = f"http://127.0.0.1:{REGISTRY_PORT}/remotexpc/tunnels/{udid}?waitMs={wait_ms}"
    try:
        with _DIRECT.open(url, timeout=timeout_s) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def script_path(paths: ToolPaths) -> Path | None:
    if paths.appium_dir is None:
        return None
    script = paths.appium_dir / SCRIPT
    return script if script.is_file() else None


def _chain(path: Path, home: Path) -> list[Path]:
    """`path` and, when it lives under the Visto home, each parent up to the home."""
    if not path.is_relative_to(home):
        return [path]
    chain = [path]
    for parent in path.parents:
        chain.append(parent)
        if parent == home:
            break
    return chain


def _untrusted(path: Path) -> str | None:
    try:
        info = os.stat(path)
    except OSError:
        return f"{path} cannot be read; run 'visto setup'"
    if info.st_uid not in (os.getuid(), 0):
        return f"{path} is owned by another user"
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return f"{path} is writable by other users"
    return None


def check_trusted(paths: ToolPaths, home: Path) -> Path:
    """The script root will run, after checking nobody else can change what root runs.

    The node binary, the script and every directory between the script and the Visto
    home must belong to this user or root and be writable by nobody else. This does
    not stop another process of this same user from replacing them.
    """
    script = script_path(paths)
    if script is None:
        raise TunnelUnavailable("the XCUITest driver has no tunnel script; run 'visto setup'")
    if os.name != "posix":
        return script
    for path in (*_chain(paths.node, home), *_chain(script, home)):
        reason = _untrusted(path)
        if reason:
            raise TunnelUnavailable(f"it would run code as root that is not safe: {reason}")
    return script


class IosTunnel:
    def __init__(
        self,
        process: subprocess.Popen,
        sudo: Sudo,
        log_file: Path,
        log_offset: int,
        notify: Callable[[str], object],
    ):
        self._process = process
        self._sudo = sudo
        self._log_file = log_file
        self._log_offset = log_offset
        self._notify = notify
        self._stopping = threading.Event()
        self._refresher = threading.Thread(target=self._refresh_loop, daemon=True)
        self._watcher = threading.Thread(target=self._watch, daemon=True)

    @classmethod
    def start(
        cls,
        paths: ToolPaths,
        log_file: Path,
        *,
        home: Path,
        sudo: Sudo,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        ready_timeout_s: float = 30,
        notify: Callable[[str], object] = lambda message: None,
    ) -> "IosTunnel":
        """`notify` receives every notice the operator must see: exit, credential, stop."""
        script = check_trusted(paths, home)
        make_private_dir(log_file.parent)
        offset = log_file.stat().st_size if log_file.exists() else 0
        descriptor = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        # No new session: sudo ties its cached credential to this terminal.
        with os.fdopen(descriptor, "ab") as log:
            process = popen(
                ["sudo", "-n", str(paths.node), str(script)],
                cwd=script.parent.parent,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
            )
        tunnel = cls(process, sudo, log_file, offset, notify)
        try:
            tunnel._await_ready(ready_timeout_s)
        except BaseException:
            # Includes Ctrl+C and SIGTERM: nobody else holds this tunnel yet.
            tunnel.stop()
            raise
        tunnel._refresher.start()
        tunnel._watcher.start()
        return tunnel

    def _await_ready(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            if self._process.poll() is not None:
                raise TunnelUnavailable(
                    f"the iOS tunnel exited during startup; see {self._log_file}"
                )
            if port_in_use(REGISTRY_PORT):
                return
            if time.monotonic() >= deadline:
                raise TunnelUnavailable(
                    f"the iOS tunnel was not ready in time; see {self._log_file}"
                )
            time.sleep(POLL_S)

    def alive(self) -> bool:
        return self._process.poll() is None

    def _refresh_loop(self) -> None:
        reported = False
        while not self._stopping.wait(REFRESH_S):
            if not self._sudo.refresh() and not reported and not self._stopping.is_set():
                reported = True
                self._notify(
                    "The administrator credential expired; Visto may not be able to stop the"
                    f" iOS tunnel. {self._manual_stop()}"
                )

    def _watch(self) -> None:
        """Say so when the script ends on its own: the driver then finds no tunnel."""
        while not self._stopping.wait(WATCH_S):
            if self._process.poll() is not None:
                self._notify(self._exit_notice())
                return

    def _exit_notice(self) -> str:
        try:
            with self._log_file.open("rb") as stream:
                stream.seek(self._log_offset)
                tail = stream.read().decode("utf-8", "replace")
        except OSError:
            tail = ""
        if "No USB devices found" in tail:
            return (
                "The iOS tunnel stopped: no phone is connected by USB cable. Connect it and"
                " unlock it; Visto starts the tunnel again when the next iOS run starts."
            )
        return (
            "The iOS tunnel stopped; Visto starts it again when the next iOS run starts."
            f" See {self._log_file}"
        )

    def _manual_stop(self) -> str:
        command = " ".join(stop_command(self._process.pid))
        return f"If it keeps running after Visto stops, stop it with: {command}"

    def begin_stop(self) -> None:
        """From now on the script ending is expected: no exit notice, nothing terminated.

        Ctrl+C also reaches sudo, which shares this terminal's process group.
        """
        self._stopping.set()

    def stop(self, timeout_s: float = 10) -> None:
        """Stop the root script; if that cannot be confirmed, say how to stop it by hand."""
        self.begin_stop()
        if self._process.poll() is not None:
            return
        terminated = self._sudo.terminate(self._process.pid)
        try:
            # A failed kill may only mean the script already ended: check briefly.
            self._process.wait(timeout=timeout_s if terminated else min(timeout_s, 1))
        except subprocess.TimeoutExpired:
            command = " ".join(stop_command(self._process.pid))
            self._notify(f"The iOS tunnel may still be running as root; stop it with: {command}")


class TunnelSupervisor:
    """One tunnel for this Visto: started with it, started again before an iOS run.

    Every launch reuses the credential cached by the password prompt of `visto
    start`; the running tunnel keeps it fresh. Nothing here raises to a run: a phone
    without a tunnel then fails its session with an explicit hint.
    """

    def __init__(
        self,
        paths: ToolPaths,
        log_file: Path,
        *,
        home: Path,
        sudo: Sudo,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        notify: Callable[[str], object] = lambda message: None,
    ):
        self._paths = paths
        self._log_file = log_file
        self._home = home
        self._sudo = sudo
        self._popen = popen
        self._notify = notify
        # Serialises launches with each other and with stop: no root script is ever
        # started after Visto began stopping, and never two at once.
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._tunnel: IosTunnel | None = None

    def start(self) -> None:
        with self._lock:
            if not port_in_use(REGISTRY_PORT):
                self._launch(READY_TIMEOUT_S)

    def ensure(self, udid: str, timeout_s: float) -> bool:
        """Before an iOS session: True when the registry lists a tunnel for `udid` in time."""
        if _SIMULATOR.fullmatch(udid):
            return False
        deadline = time.monotonic() + timeout_s
        # Another run may be launching the tunnel: wait for it only within this budget.
        if not self._lock.acquire(timeout=max(timeout_s, 0)):
            return False
        try:
            if self._stopping.is_set():
                return False
            running = self._tunnel is not None and self._tunnel.alive()
            # A registry we did not start belongs to the operator: use it, never replace it.
            if not running and not port_in_use(REGISTRY_PORT):
                launch_s = min(READY_TIMEOUT_S, deadline - time.monotonic())
                if launch_s <= 0 or not self._launch(launch_s):
                    return False
        finally:
            self._lock.release()
        remaining = deadline - time.monotonic()
        return remaining > 0 and device_tunnel_ready(udid, remaining)

    def _launch(self, timeout_s: float) -> bool:
        try:
            tunnel = IosTunnel.start(
                self._paths,
                self._log_file,
                home=self._home,
                sudo=self._sudo,
                popen=self._popen,
                ready_timeout_s=timeout_s,
                notify=self._notify,
            )
        except TunnelUnavailable as error:
            self._notify(f"The iOS tunnel was not started: {error}")
            return False
        # Only now: the ended tunnel kept the credential fresh until a new one runs.
        previous, self._tunnel = self._tunnel, tunnel
        if previous is not None:
            previous.stop()
        return True

    def begin_stop(self) -> None:
        self._stopping.set()
        tunnel = self._tunnel
        if tunnel is not None:
            tunnel.begin_stop()

    def stop(self) -> None:
        self.begin_stop()
        with self._lock:
            if self._tunnel is not None:
                self._tunnel.stop()
