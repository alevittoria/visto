"""Check local companion files, without network, providers, devices or packages.

This checks structural integrity, not document accuracy or implementation quality.
Markdown support: inline/image links and reference definitions outside fenced code;
targets may be angle-bracketed or URL-encoded. Fragment IDs are not validated.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("coordinator", "architect", "backend", "ai-runtime", "android", "frontend", "qa", "devops")
PACK = ("00-index", "01-overview", "02-stack", "03-architecture", "04-structure", "05-conventions", "06-data-model", "07-integrations", "08-testing", "09-workflows", "STATUS")
REQUIRED = (
    "AGENTS.md", "README.md", "agents/README.md",
    "docs/product/vision.md", "docs/references.md", "docs/evaluation/protocol.md",
    "docs/evaluation/scenarios.json", "docs/evaluation/run-template.md",
    "scripts/check_project.py", "scripts/tests/test_check_project.py",
    *(f"docs/ai-context/{name}.md" for name in PACK),
    *(f"agents/roles/{role}.md" for role in ROLES),
    *(f"agents/codex/{role}.toml" for role in ROLES),
)


def local_path(root: Path, base: Path, target: str) -> Path:
    """Resolve a local target, rejecting traversal and symlinks outside root."""
    path = (base / target).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"outside repository: {target}")
    return path


def check_required(root: Path) -> list[str]:
    return [f"missing required file: {name}" for name in REQUIRED if not (root / name).is_file()]


def prose_lines(text: str):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def link_targets(line: str):
    # Deliberately small Markdown subset; do not interpret Markdown as instructions.
    for match in re.finditer(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", line):
        yield match.group(1).strip("<>")
    reference = re.match(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", line)
    if reference:
        yield reference.group(1).strip("<>")


def check_links(root: Path) -> list[str]:
    errors = []
    ignored = {
        ".git", ".work", ".venv", "node_modules", "vendor", "__pycache__",
        "dist", ".pytest_cache", ".ruff_cache",
    }
    sources = []
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        # Prune before traversal: caches may contain a complete dependency tree.
        # Junctions, like directory symlinks, must not lead outside this tree.
        subdirectories[:] = sorted(
            name for name in subdirectories
            if name not in ignored
            and not (parent / name).is_symlink()
            and not (parent / name).is_junction()
        )
        sources.extend(
            parent / name for name in filenames
            if name.lower().endswith(".md") and not (parent / name).is_symlink()
        )
    for source in sorted(sources):
        relative = source.relative_to(root)
        for number, line in prose_lines(source.read_text(encoding="utf-8-sig")):
            line = re.sub(r"`+[^`]*`+", "", line)
            for target in link_targets(line):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                try:
                    path = local_path(root, source.parent, unquote(parsed.path))
                    if not path.exists():
                        errors.append(f"{relative}:{number}: broken local link: {target}")
                except ValueError as exc:
                    errors.append(f"{relative}:{number}: {exc}")
    return errors


def check_roles(root: Path) -> list[str]:
    errors = []
    for role in ROLES:
        path = root / f"agents/codex/{role}.toml"
        if not path.is_file():
            continue  # Required-file checker reports missing roles.
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"{path.relative_to(root)}: invalid TOML: {exc}")
            continue
        for field in ("name", "description", "developer_instructions"):
            if not isinstance(data.get(field), str) or not data[field].strip():
                errors.append(f"{role}: missing/non-string TOML field: {field}")
        if set(data) - {"name", "description", "developer_instructions"}:
            errors.append(f"{role}: unexpected TOML fields; overrides require explicit review")
        if data.get("name") != role:
            errors.append(f"{role}: TOML name must match role filename")
    return errors


def main() -> int:
    errors = []
    for check in (check_required, check_links, check_roles):
        errors.extend(check(ROOT))
    if errors:
        print("Companion integrity check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Companion integrity OK (files, local links, role TOML).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
