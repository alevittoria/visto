"""Pinned portable components per supported host, read from the packaged manifest."""

import json
import platform
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

HOSTS = ("win-x64", "macos-arm64", "macos-x64", "linux-x64")
KINDS = ("zip", "tar.gz", "tar.xz")
MANIFEST_FORMAT = 1
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}|sha1:[0-9a-f]{40}")
_X64 = {"amd64", "x86_64"}
_ARM64 = {"arm64", "aarch64"}


class UnsupportedHost(ValueError):
    pass


def host_key(system: str | None = None, machine: str | None = None) -> str:
    system = platform.system() if system is None else system
    machine = (platform.machine() if machine is None else machine).lower()
    if system == "Windows" and machine in _X64:
        return "win-x64"
    if system == "Linux" and machine in _X64:
        return "linux-x64"
    if system == "Darwin" and machine in _X64:
        return "macos-x64"
    if system == "Darwin" and machine in _ARM64:
        return "macos-arm64"
    raise UnsupportedHost(f"Unsupported host {system}/{machine}; supported: {', '.join(HOSTS)}")


@dataclass(frozen=True)
class Archive:
    url: str
    checksum: str  # "sha256:<hex>" or "sha1:<hex>"
    kind: Literal["zip", "tar.gz", "tar.xz"]
    strip: str | None
    dest: str


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    archives: tuple[Archive, ...]


def _archive(raw: dict) -> Archive:
    archive = Archive(raw["url"], raw["checksum"], raw["kind"], raw.get("strip"), raw["dest"])
    if not archive.url.startswith("https://"):
        raise ValueError(f"manifest URL is not HTTPS: {archive.url}")
    if not _CHECKSUM.fullmatch(archive.checksum):
        raise ValueError(f"manifest checksum is not pinned: {archive.url}")
    if archive.kind not in KINDS:
        raise ValueError(f"manifest archive kind is unknown: {archive.kind}")
    return archive


def load_manifest() -> dict[str, dict[str, Component]]:
    """Component name -> host key -> Component."""
    data = json.loads((files("visto.toolchain") / "components.json").read_text("utf-8"))
    if data.get("format") != MANIFEST_FORMAT:
        raise ValueError("components.json has an unsupported format")
    manifest: dict[str, dict[str, Component]] = {}
    for name, entry in data["components"].items():
        hosts = entry["hosts"]
        if set(hosts) != set(HOSTS):
            raise ValueError(f"components.json does not cover every host for {name}")
        manifest[name] = {
            host: Component(name, entry["version"], tuple(_archive(raw) for raw in archives))
            for host, archives in hosts.items()
        }
    return manifest
