"""Check that a built Visto wheel carries the files an installed tool needs.

Usage: python scripts/check_wheel.py backend/dist/visto-<version>-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REQUIRED = (
    "visto/console/index.html",
    "visto/toolchain/components.json",
    "visto/toolchain/android-sdk-license.txt",
    "visto/toolchain/appium/default/package.json",
    "visto/toolchain/appium/default/pnpm-lock.yaml",
    "visto/toolchain/appium/macos/package.json",
    "visto/toolchain/appium/macos/pnpm-lock.yaml",
    "visto/prompts/agent-core.md",
)
# The built console references hashed bundles here; their names change every build.
ASSETS = "visto/console/assets/"
ENTRY_POINT = "visto = visto.cli:entry"


def missing_entries(wheel: Path) -> list[str]:
    """Required entries absent from the wheel; empty when it is complete."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = [name for name in REQUIRED if name not in names]
        if not any(name.startswith(ASSETS) and name != ASSETS for name in names):
            missing.append(f"a file under {ASSETS}")
        entry_points = [
            name
            for name in names
            if name.count("/") == 1
            and name.split("/")[0].endswith(".dist-info")
            and name.endswith("/entry_points.txt")
        ]
        declared = any(
            ENTRY_POINT in (line.strip() for line in archive.read(name).decode().splitlines())
            for name in entry_points
        )
    if not declared:
        missing.append(f"entry_points.txt containing {ENTRY_POINT}")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    try:
        missing = missing_entries(args.wheel)
    except (OSError, zipfile.BadZipFile) as error:
        print(f"Cannot read wheel {args.wheel}: {error}", file=sys.stderr)
        return 1
    for entry in missing:
        print(f"missing: {entry}", file=sys.stderr)
    if missing:
        return 1
    print(f"Wheel contents complete: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
