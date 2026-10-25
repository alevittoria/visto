"""`visto settings`: the provider key through stdin, its non-billable check, and a summary.

The key is read from one line of stdin, never from argv or the environment, and is
never printed: output shows only whether it is configured and its last four
characters.
"""

import asyncio
import getpass
import sys
from collections.abc import Callable
from dataclasses import fields
from typing import Literal, TextIO

from visto.adapters.ai.transport import probe_model, verify_key
from visto.adapters.settings.store import KeyStatus, SettingsError, SettingsStore
from visto.home import VistoHome
from visto.runner import RunnerSettings
from visto.toolchain import (
    Toolchain,
    UnsupportedHost,
    host_key,
    stored_ca_bundle,
    trusted_ca_bundle,
)

Action = Literal["set-key", "delete-key", "verify-key", "show"]
ACTIONS: tuple[Action, ...] = ("set-key", "delete-key", "verify-key", "show")
OK, REJECTED, FAILED = 0, 2, 3
PROBE_TIMEOUT_MS = 10000
MODEL = next(f.default for f in fields(RunnerSettings) if f.name == "model")
PROMPT = "Paste the provider API key and press Enter: "


def key_line(status: KeyStatus) -> str:
    if status.configured:
        return f"Provider key: configured (ends with {status.last4})"
    return "Provider key: not configured"


def _read_key(stdin: TextIO) -> str:
    """One line: hidden input on an interactive terminal, else the next stdin line."""
    if stdin is sys.stdin and stdin.isatty():
        return getpass.getpass(PROMPT)
    return stdin.readline()


def _is_mac(host: str | None) -> bool:
    try:
        return (host or host_key()).startswith("macos-")
    except UnsupportedHost:
        return False


def _flag(value: str) -> str:
    return "set" if value.strip() else "not set"


def _show(store: SettingsStore, host: str | None, output) -> None:
    settings = store.load()
    output(key_line(store.key_status()))
    output(f"Price refresh: {'on' if settings.price_refresh else 'off'}")
    if _is_mac(host):
        # Presence only: signing identifiers are configuration and never echoed.
        ios = settings.ios
        output(f"iOS team ID: {_flag(ios.team_id)}")
        output(f"iOS signing ID: {_flag(ios.signing_id)}")
        output(f"WebDriverAgent bundle ID: {_flag(ios.wda_bundle_id)}")
        output(f"WebDriverAgent derived data: {_flag(ios.wda_derived_data)}")
        output(f"Prebuilt WebDriverAgent: {'yes' if ios.prebuilt_wda else 'no'}")


def run_settings(
    home: VistoHome,
    action: Action,
    *,
    stdin: TextIO = sys.stdin,
    output: Callable[[str], object] = print,
    probe=probe_model,
    host: str | None = None,
) -> int:
    """Exit codes: 0 ok, 2 rejected key or failed verification, 3 unusable settings files."""
    store = SettingsStore(home)
    try:
        if action == "set-key":
            try:
                status = store.set_api_key(_read_key(stdin))
            except SettingsError as error:
                # Key-validation messages never contain the value.
                if str(error).startswith("the API key"):
                    output(f"Not saved: {error}")
                    return REJECTED
                raise
            output(key_line(status))
            return OK
        if action == "delete-key":
            output(key_line(store.delete_api_key()))
            return OK
        if action == "verify-key":
            with trusted_ca_bundle(stored_ca_bundle(Toolchain(home))):
                result = asyncio.run(
                    verify_key(store.api_key(), MODEL, PROBE_TIMEOUT_MS, probe=probe)
                )
            output(result)
            return OK if result == "ok" else REJECTED
        if action == "show":
            _show(store, host, output)
            return OK
        raise ValueError(f"unknown settings action: {action}")
    except (SettingsError, OSError) as error:
        detail = str(error) if isinstance(error, SettingsError) else "settings files cannot be used"
        output(f"Settings are unusable: {detail}")
        return FAILED
    except (EOFError, KeyboardInterrupt):
        output("Cancelled; nothing was changed")
        return REJECTED
