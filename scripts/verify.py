"""Run installed local checks from any cwd; never contact Android or an AI provider.

Install dependencies with the documented locked setup commands first. This script
does not bootstrap global tools or install dependencies implicitly.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def executable(value: str) -> str:
    """Accept an installed tool name or an explicit executable path."""
    found = shutil.which(value)
    if found is None:
        raise FileNotFoundError(f"Executable unavailable: {value}")
    return str(Path(found).resolve())


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"[{cwd.name}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True, timeout=180, shell=False)


def backend_checks(uv: str) -> None:
    backend = ROOT / "backend"
    python = (
        backend
        / ".venv"
        / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    if not python.is_file():
        raise FileNotFoundError(
            "Backend environment missing; run the documented uv sync first"
        )
    uv_options = [uv, "--cache-dir", str(ROOT / ".work/uv-cache"), "--offline"]
    run([*uv_options, "lock", "--check"], cwd=backend)
    run([str(python), "-m", "pytest", "-p", "no:cacheprovider"], cwd=backend)
    run([str(python), "-m", "ruff", "check", "src", "tests"], cwd=backend)
    run([str(python), "-m", "ruff", "format", "--check", "src", "tests"], cwd=backend)
    # The build group in uv.lock supplies the backend and its exact transitive
    # dependencies. Reuse that environment instead of re-resolving build tools.
    run(
        [*uv_options, "build", "--no-build-isolation", "--python", str(python)],
        cwd=backend,
    )


def frontend_checks(node: str) -> None:
    frontend = ROOT / "frontend"
    tsc = frontend / "node_modules/typescript/bin/tsc"
    vite = frontend / "node_modules/vite/bin/vite.js"
    if not tsc.is_file() or not vite.is_file():
        raise FileNotFoundError(
            "Frontend dependencies missing; run the documented pnpm install first"
        )
    run(
        [
            node,
            str(tsc),
            "--noEmit",
            "--noUnusedLocals",
            "--noUnusedParameters",
            "--allowUnreachableCode",
            "false",
            "--allowUnusedLabels",
            "false",
        ],
        cwd=frontend,
    )
    tests = sorted(frontend.glob("tests/*.test.mjs"))
    if not tests:
        raise FileNotFoundError("Frontend test files missing")
    run([node, "--test", "--test-isolation=none", *map(str, tests)], cwd=frontend)
    run([node, str(vite), "build", "--configLoader", "native"], cwd=frontend)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--node", default="node", help="Node executable name or absolute path"
    )
    parser.add_argument(
        "--uv", default="uv", help="uv executable name or absolute path"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--backend-only", action="store_true")
    selection.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    try:
        run([sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-v"])
        run([sys.executable, "scripts/check_project.py"])
        if not args.frontend_only:
            backend_checks(executable(args.uv))
        if not args.backend_only:
            frontend_checks(executable(args.node))
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    print("All selected local checks passed. Device/model quality remains unevaluated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
