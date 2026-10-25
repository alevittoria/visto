"""`visto start`: managed Appium plus the local console and API on loopback."""

import os
import signal
import subprocess
import webbrowser
from collections.abc import Callable
from contextlib import contextmanager

from visto.commands import appium_process
from visto.commands.appium_process import AppiumFailed, AppiumProcess, PortBusy
from visto.commands.data import DataUnavailable, prepare_data
from visto.commands.setup import pending_names, run_setup
from visto.composition import create_app
from visto.home import VistoHome
from visto.instances import others, registered
from visto.toolchain import Toolchain, ToolchainMissing, child_env, host_key, trusted_ca_bundle

OK, FAILED, BUSY = 0, 3, 4


def uvicorn_serve(app, port: int, *, ready: Callable[[], None], stop: Callable[[], bool]) -> None:
    """Serve on 127.0.0.1:<port>; call `ready` once listening, return when `stop()` is true."""
    import uvicorn

    class Server(uvicorn.Server):
        announced = False

        async def on_tick(self, counter: int) -> bool:
            if not self.announced:
                self.announced = True
                ready()
            return await super().on_tick(counter) or stop()

    server = Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    try:
        server.run()
    except SystemExit:
        # uvicorn exits the process when it cannot bind or start the application.
        raise OSError(f"the server could not start on port {port}") from None


def run_start(
    home: VistoHome,
    *,
    port: int = 8000,
    appium_port: int = 4723,
    open_browser: bool = True,
    serve=uvicorn_serve,
    output: Callable[[str], object] = print,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    **setup_kwargs,
) -> int:
    """Exit codes: 0 stopped normally, setup's code when it fails, 3 failure, 4 busy."""
    with registered(home, "start"):
        if any(instance.kind == "start" for instance in others(home)):
            output("Visto is already running")
            return BUSY
        for number, option in ((port, "--port"), (appium_port, "--appium-port")):
            if appium_process.port_in_use(number):
                output(f"Port {number} is in use; pass {option}")
                return FAILED
        toolchain = Toolchain(home)
        try:
            pending = pending_names(toolchain, setup_kwargs.get("host") or host_key())
        except (OSError, ValueError) as error:
            output(f"The toolchain state cannot be read: {error}")
            return FAILED
        if pending:
            output("Updating components: " + ", ".join(pending))
            code = run_setup(home, **{"accept_license": None, "ca_bundle": None, **setup_kwargs})
            if code != OK:
                return code
        try:
            state = toolchain.state()
            paths = toolchain.paths()
        except (ValueError, ToolchainMissing) as error:
            output(f"The toolchain is not usable: {error}; run 'visto setup'")
            return FAILED
        try:
            prepare_data(home, home.data)
        except DataUnavailable as error:
            output(str(error))
            return error.code
        # The provider worker inherits this process's environment.
        with trusted_ca_bundle(state.ca_bundle):
            return _serve(home, paths, state, port, appium_port, open_browser, serve, output, popen)


def _interrupt(signum, frame):
    raise KeyboardInterrupt


@contextmanager
def _termination_interrupts():
    """Turn SIGTERM/SIGHUP/SIGBREAK into KeyboardInterrupt so cleanup `finally` runs.

    uvicorn restores the previous handler after serving and re-raises the signal it
    captured; with this handler that re-raise becomes an exception, not process death.
    """
    previous = {}
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous[number] = signal.signal(number, _interrupt)
        except (ValueError, OSError):  # Not the main thread.
            pass
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _serve(home, paths, state, port, appium_port, open_browser, serve, output, popen) -> int:
    log = home.logs / "appium.log"
    env = child_env(paths, os.environ, state.ca_bundle)
    url = f"http://127.0.0.1:{port}/"

    def ready() -> None:
        output(f"Visto is running at {url} (press Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)

    appium = None
    with _termination_interrupts():
        try:
            try:
                appium = AppiumProcess.start(paths, env, appium_port, log, popen=popen)
            except PortBusy:
                output(f"Port {appium_port} is in use; pass --appium-port")
                return FAILED
            except (AppiumFailed, OSError) as error:
                output(f"Appium could not start: {error}")
                return FAILED
            app = create_app(home=home, appium_url=f"http://127.0.0.1:{appium_port}")
            serve(app, port, ready=ready, stop=lambda: not appium.alive())
            if not appium.alive():
                output(f"Appium stopped unexpectedly; see {log}")
                return FAILED
            return OK
        except KeyboardInterrupt:
            return OK
        except Exception as error:
            output(f"The Visto server stopped: {error}")
            return FAILED
        finally:
            if appium is not None:
                appium.stop()
