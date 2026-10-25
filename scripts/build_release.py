"""Build the release wheel: frontend console and Appium locks packaged with the backend.

Requires the documented locked setup first (backend `uv sync`, frontend dependencies
installed). Never contacts a device or an AI provider. Prints the wheel path.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PACKAGE = BACKEND / "src" / "visto"
APPIUM_FILES = ("package.json", "pnpm-lock.yaml")
TIMEOUT = 600


def executable(value: str) -> str:
    """Accept an installed tool name or an explicit executable path."""
    found = shutil.which(value)
    if found is None:
        raise FileNotFoundError(f"Executable unavailable: {value}")
    return str(Path(found).resolve())


def run(command: list[str], *, cwd: Path) -> None:
    print(f"[{cwd.name}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True, timeout=TIMEOUT, shell=False)


def copy_tree(source: Path, target: Path) -> None:
    """Replace target with a copy of source, so no stale file survives."""
    if not source.is_dir():
        raise FileNotFoundError(f"Missing build output: {source}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def copy_files(source: Path, names: Iterable[str], target: Path) -> None:
    """Replace target with a directory holding only the named files from source."""
    names = tuple(names)
    for name in names:
        if not (source / name).is_file():
            raise FileNotFoundError(f"Missing file: {source / name}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in names:
        shutil.copy2(source / name, target / name)


def build_frontend(node: str) -> None:
    tsc = FRONTEND / "node_modules/typescript/bin/tsc"
    vite = FRONTEND / "node_modules/vite/bin/vite.js"
    if not tsc.is_file() or not vite.is_file():
        raise FileNotFoundError(
            "Frontend dependencies missing; run the documented pnpm install first"
        )
    run([node, str(tsc), "--noEmit"], cwd=FRONTEND)
    run([node, str(vite), "build", "--configLoader", "native"], cwd=FRONTEND)


def stage_package_data() -> None:
    copy_tree(FRONTEND / "dist", PACKAGE / "console")
    appium = PACKAGE / "toolchain" / "appium"
    if appium.exists():
        shutil.rmtree(appium)
    copy_files(ROOT / "tools/appium", APPIUM_FILES, appium / "default")
    copy_files(ROOT / "tools/appium/macos", APPIUM_FILES, appium / "macos")


def build_wheel(uv: str) -> Path:
    python = BACKEND / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        raise FileNotFoundError("Backend environment missing; run the documented uv sync first")
    version = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    wheel = BACKEND / "dist" / f"visto-{version}-py3-none-any.whl"
    wheel.unlink(missing_ok=True)
    # The build group in uv.lock supplies hatchling; reuse that environment.
    run(
        [uv, "build", "--wheel", "--no-build-isolation", "--python", str(python)],
        cwd=BACKEND,
    )
    if not wheel.is_file():
        raise FileNotFoundError(f"Expected wheel not produced: {wheel}")
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="node", help="Node executable name or absolute path")
    parser.add_argument("--uv", default="uv", help="uv executable name or absolute path")
    args = parser.parse_args(argv)
    try:
        build_frontend(executable(args.node))
        stage_package_data()
        wheel = build_wheel(executable(args.uv))
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Release build failed: {error}", file=sys.stderr)
        return 1
    print(wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
