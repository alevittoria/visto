"""The Android SDK License Agreement text and the user's acceptance of exactly that text."""

import hashlib
from importlib import resources

from visto.toolchain.install import Toolchain, ToolchainState

LICENSE_TEXT = (
    resources.files("visto.toolchain")
    .joinpath("android-sdk-license.txt")
    .read_text(encoding="utf-8")
    .strip()
)
LICENSE_SHA256 = hashlib.sha256(LICENSE_TEXT.encode("utf-8")).hexdigest()


def license_accepted(state: ToolchainState) -> bool:
    """True only when the recorded acceptance matches the current license text."""
    return state.android_license_sha256 == LICENSE_SHA256


def record_acceptance(toolchain: Toolchain) -> None:
    state = toolchain.state()
    state.android_license_sha256 = LICENSE_SHA256
    toolchain.save_state(state)
