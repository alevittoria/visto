"""`visto setup`: install the pinned toolchain into the Visto home."""

import subprocess
from collections.abc import Callable
from pathlib import Path

from visto.home import VistoHome
from visto.instances import Busy, exclusive
from visto.toolchain import Component, Toolchain, host_key, load_manifest
from visto.toolchain.appium import appium_flavor, appium_version, install_appium
from visto.toolchain.fetch import Opener, https_opener
from visto.toolchain.install import CORE
from visto.toolchain.license import LICENSE_TEXT, license_accepted, record_acceptance

LICENSE_PROMPT = "Accept the Android SDK license? [y/N]"
OK, DECLINED, FAILED, BUSY = 0, 2, 3, 4


def pending_core(toolchain: Toolchain, host: str) -> list[Component]:
    manifest = load_manifest()
    return toolchain.pending([manifest[name][host] for name in CORE])


def appium_pending(toolchain: Toolchain, host: str) -> bool:
    return toolchain.state().active.get("appium") != appium_version(appium_flavor(host))


def pending_names(toolchain: Toolchain, host: str) -> list[str]:
    """Names of the components `run_setup` would install or update."""
    names = [component.name for component in pending_core(toolchain, host)]
    return [*names, "appium"] if appium_pending(toolchain, host) else names


def _accepted(accept_license: bool | None, ask: Callable[[str], str], output) -> bool:
    if accept_license is not None:
        return accept_license
    output(LICENSE_TEXT)
    try:
        answer = ask(LICENSE_PROMPT)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def run_setup(
    home: VistoHome,
    *,
    accept_license: bool | None,
    ca_bundle: Path | None,
    host: str | None = None,
    opener: Opener | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ask: Callable[[str], str] = input,
    output: Callable[[str], object] = print,
) -> int:
    """Exit codes: 0 ok, 2 license declined, 3 failure, 4 another Visto uses the home."""
    try:
        with exclusive(home, "setup"):
            return _setup(home, accept_license, ca_bundle, host, opener, run, ask, output)
    except Busy as error:
        output(str(error))
        return BUSY


def _setup(home, accept_license, ca_bundle, host, opener, run, ask, output) -> int:
    toolchain = Toolchain(home)
    try:
        host = host or host_key()
        state = toolchain.state()
        if ca_bundle is not None:
            if not Path(ca_bundle).is_file():
                output(f"CA bundle not found: {ca_bundle}")
                return FAILED
            state.ca_bundle = str(Path(ca_bundle).resolve())
            toolchain.save_state(state)
        if accept_license is False or not license_accepted(state):
            if not _accepted(accept_license, ask, output):
                output("The Android SDK license was not accepted; nothing was installed.")
                return DECLINED
            record_acceptance(toolchain)
        if opener is None:
            opener = https_opener(None if state.ca_bundle is None else Path(state.ca_bundle))
        for component in pending_core(toolchain, host):
            output(f"Downloading {component.name} {component.version}")
            toolchain.install(component, opener=opener)
            toolchain.activate(component.name, component.version)
        if appium_pending(toolchain, host):
            flavor = appium_flavor(host)
            output(f"Installing Appium {appium_version(flavor)}")
            install_appium(toolchain, flavor, run=run)
        toolchain.prune()
    except (OSError, ValueError, LookupError, subprocess.SubprocessError) as error:
        # Unsupported host, checksum and archive errors are ValueErrors; URL errors OSErrors.
        output(f"Setup failed: {error}")
        return FAILED
    output("Setup complete.")
    return OK
