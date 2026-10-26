"""Install the pinned Appium tree with the portable Node's corepack and pnpm."""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Literal

from visto.toolchain.install import Toolchain, ToolPaths, _remove, child_env

INSTALL_TIMEOUT_SECONDS = 900
INSTALLED_MARKER = ".visto-installed"
_FILES = ("package.json", "pnpm-lock.yaml")
_REPOSITORY_TOOLS = Path(__file__).resolve().parents[4] / "tools" / "appium"


def appium_flavor(host: str) -> Literal["default", "macos"]:
    return "macos" if host.startswith("macos-") else "default"


def _has_files(directory: Path) -> bool:
    return all((directory / name).is_file() for name in _FILES)


def appium_resources(flavor: str) -> Path:
    """Directory with package.json and pnpm-lock.yaml: packaged copy, else the checkout."""
    if flavor not in ("default", "macos"):
        raise ValueError(f"unknown Appium flavor: {flavor!r}")
    packaged = Path(str(resources.files("visto.toolchain").joinpath("appium", flavor)))
    if _has_files(packaged):
        return packaged
    checkout = _REPOSITORY_TOOLS / "macos" if flavor == "macos" else _REPOSITORY_TOOLS
    if _has_files(checkout):
        return checkout
    raise FileNotFoundError(f"Appium package files for flavor {flavor!r} were not found")


def appium_version(flavor: str) -> str:
    lock = (appium_resources(flavor) / "pnpm-lock.yaml").read_bytes()
    return f"{flavor}-{hashlib.sha256(lock).hexdigest()[:12]}"


def _corepack(node: Path) -> Path:
    root = node.parent if os.name == "nt" else node.parent.parent / "lib"
    return root / "node_modules" / "corepack" / "dist" / "corepack.js"


def install_appium(
    toolchain: Toolchain,
    flavor: str,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Install the locked tree into toolchain/appium/<version>/ and activate it.

    Activation happens only after a complete install; on failure the directory is
    removed and the active version is unchanged. Raises ToolchainMissing (before
    touching disk) when the portable Node is not installed.
    """
    paths: ToolPaths = toolchain.paths()
    source = appium_resources(flavor)
    version = appium_version(flavor)
    final = toolchain.component_dir("appium", version)
    if (final / INSTALLED_MARKER).is_file():
        toolchain.activate("appium", version)
        return
    _remove(final)
    state = toolchain.state()
    env = child_env(paths, os.environ, state.ca_bundle)
    env["COREPACK_HOME"] = str(toolchain.root / "corepack")
    env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    try:
        final.mkdir(parents=True)
        for name in _FILES:
            (final / name).write_bytes((source / name).read_bytes())
        argv = [
            str(paths.node),
            str(_corepack(paths.node)),
            "pnpm",
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--node-linker=hoisted",
        ]
        run(
            argv,
            cwd=final,
            env=env,
            timeout=INSTALL_TIMEOUT_SECONDS,
            shell=False,
            check=True,
            capture_output=True,
        ).check_returncode()
        (final / INSTALLED_MARKER).write_text("", encoding="utf-8")
    except BaseException:
        _remove(final)
        raise
    toolchain.activate("appium", version)


def installed_driver_version(appium_dir: Path, package: str) -> str | None:
    try:
        data = json.loads(
            (appium_dir / "node_modules" / package / "package.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def wda_project(appium_dir: Path, max_depth: int = 4) -> Path | None:
    """Find WebDriverAgent.xcodeproj under node_modules, at most max_depth levels deep."""
    pending = [(appium_dir / "node_modules", 0)]
    while pending:
        directory, depth = pending.pop(0)
        try:
            children = sorted(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name == "WebDriverAgent.xcodeproj":
                return child
            if depth < max_depth and child.is_dir() and not child.is_symlink():
                pending.append((child, depth + 1))
    return None
