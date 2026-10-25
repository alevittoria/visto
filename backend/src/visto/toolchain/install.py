"""Side-by-side atomic installs under the Visto home and a scoped child environment."""

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from visto.home import VistoHome
from visto.toolchain.fetch import Opener, download, extract
from visto.toolchain.manifest import Component

STATE_FORMAT = 1
CORE = ("node", "jdk", "android-sdk")
# Inherited settings that would make the managed Node, npm/pnpm or Appium load code,
# packages or configuration from outside the managed toolchain.
_FOREIGN_NAMES = ("APPIUM_HOME", "NODE_OPTIONS", "NODE_PATH")
_FOREIGN_PREFIXES = ("NPM_CONFIG_", "COREPACK_")


class ToolchainMissing(LookupError):
    pass


@dataclass
class ToolchainState:
    active: dict[str, str] = field(default_factory=dict)
    android_license_sha256: str | None = None
    ca_bundle: str | None = None


@dataclass(frozen=True)
class ToolPaths:
    node: Path  # the node executable
    java_home: Path  # the directory containing bin/java
    android_home: Path
    adb: Path
    appium_dir: Path | None


def _segment(value: str) -> str:
    if not value or value in (".", "..") or any(c in value for c in "/\\:\x00"):
        raise ValueError(f"invalid toolchain path segment: {value!r}")
    return value


def _relative(dest: str) -> tuple[str, ...]:
    return tuple(_segment(part) for part in dest.split("/") if part != ".")


def _remove(path: Path) -> None:
    def writable_retry(function, name, _error):
        os.chmod(name, stat.S_IWRITE | stat.S_IREAD)
        function(name)

    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path, onexc=writable_retry)


def _optional_str(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("toolchain state file is invalid")
    return value


class Toolchain:
    def __init__(self, home: VistoHome):
        self.root = home.toolchain

    @property
    def _state_file(self) -> Path:
        return self.root / "state.json"

    def component_dir(self, name: str, version: str) -> Path:
        return self.root / _segment(name) / _segment(version)

    def state(self) -> ToolchainState:
        if not self._state_file.exists():
            return ToolchainState()
        try:
            data = json.loads(self._state_file.read_text("utf-8"))
        except (OSError, ValueError):
            raise ValueError("toolchain state file is invalid") from None
        version = data.get("format") if isinstance(data, dict) else None
        if type(version) is int and version > STATE_FORMAT:
            raise ValueError("toolchain state file was written by a newer Visto")
        active = data.get("active") if version == STATE_FORMAT else None
        if not isinstance(active, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in active.items()
        ):
            raise ValueError("toolchain state file is invalid")
        return ToolchainState(
            dict(active),
            _optional_str(data.get("android_license_sha256")),
            _optional_str(data.get("ca_bundle")),
        )

    def save_state(self, state: ToolchainState) -> None:
        """Atomic replace through a sibling temp file."""
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "format": STATE_FORMAT,
            "active": state.active,
            "android_license_sha256": state.android_license_sha256,
            "ca_bundle": state.ca_bundle,
        }
        descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".state.json.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(temporary, self._state_file)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def pending(self, components: Iterable[Component]) -> list[Component]:
        active = self.state().active
        return [
            component
            for component in components
            if active.get(component.name) != component.version
            or not self.component_dir(component.name, component.version).is_dir()
        ]

    def install(
        self, component: Component, *, opener: Opener | None, ca_bundle: Path | None = None
    ) -> None:
        """Download, verify and extract into a temp dir, then move it into place at once."""
        final = self.component_dir(component.name, component.version)
        if final.is_dir():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".tmp-", dir=self.root))
        try:
            tree = temporary / "t"
            tree.mkdir()
            for index, archive in enumerate(component.archives):
                file = download(
                    archive.url,
                    temporary / f"a{index}",
                    archive.checksum,
                    opener=opener,
                    ca_bundle=ca_bundle,
                )
                extract(file, archive.kind, tree.joinpath(*_relative(archive.dest)), archive.strip)
                file.unlink()
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tree, final)
        finally:
            _remove(temporary)

    def activate(self, name: str, version: str) -> None:
        if not self.component_dir(name, version).is_dir():
            raise FileNotFoundError(f"{name} {version} is not installed")
        state = self.state()
        state.active[name] = version
        self.save_state(state)

    def prune(self) -> None:
        """Remove inactive versions of tracked components and stale temp dirs."""
        if not self.root.is_dir():
            return
        for stale in self.root.glob(".tmp-*"):
            _remove(stale)
        for name, version in self.state().active.items():
            parent = self.root / _segment(name)
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.name != version:
                        _remove(child)

    def paths(self) -> ToolPaths:
        active = self.state().active
        missing = [
            name
            for name in CORE
            if name not in active or not self.component_dir(name, active[name]).is_dir()
        ]
        if missing:
            raise ToolchainMissing(f"toolchain components not installed: {', '.join(missing)}")
        windows = os.name == "nt"
        node = self.component_dir("node", active["node"])
        jdk = self.component_dir("jdk", active["jdk"])
        bundle = jdk / "Contents" / "Home"  # macOS JDK archives
        sdk = self.component_dir("android-sdk", active["android-sdk"])
        appium = active.get("appium")
        return ToolPaths(
            node=node / "node.exe" if windows else node / "bin" / "node",
            java_home=bundle if bundle.is_dir() else jdk,
            android_home=sdk,
            adb=sdk / "platform-tools" / ("adb.exe" if windows else "adb"),
            appium_dir=None if appium is None else self.component_dir("appium", appium),
        )


def _put(env: dict[str, str], key: str, value: str) -> None:
    """Set `key`, dropping case variants on Windows where names are case-insensitive."""
    if os.name == "nt":
        for existing in [k for k in env if k.upper() == key]:
            del env[existing]
    env[key] = value


def child_env(paths: ToolPaths, base: Mapping[str, str], ca_bundle: str | None) -> dict[str, str]:
    """Environment for managed child processes; the caller's own environment is untouched."""
    env = {
        key: value
        for key, value in base.items()
        if key.upper() != "OPENAI_API_KEY"
        and key.upper() not in _FOREIGN_NAMES
        and not key.upper().startswith(_FOREIGN_PREFIXES)
    }
    names = [k for k in env if k.upper() == "PATH"] if os.name == "nt" else ["PATH"]
    inherited = next((env[k] for k in names if env.get(k)), "")
    prefix = [
        str(paths.node.parent),
        str(paths.java_home / "bin"),
        str(paths.android_home / "platform-tools"),
    ]
    _put(env, "PATH", os.pathsep.join([*prefix, inherited] if inherited else prefix))
    _put(env, "ANDROID_HOME", str(paths.android_home))
    _put(env, "ANDROID_SDK_ROOT", str(paths.android_home))
    _put(env, "JAVA_HOME", str(paths.java_home))
    if ca_bundle:
        _put(env, "NODE_EXTRA_CA_CERTS", str(ca_bundle))
        _put(env, "SSL_CERT_FILE", str(ca_bundle))
    return env


def stored_ca_bundle(toolchain: Toolchain) -> str | None:
    """The CA bundle remembered by `visto setup`; None when none, or the state is unreadable."""
    try:
        return toolchain.state().ca_bundle
    except ValueError:
        return None


@contextmanager
def trusted_ca_bundle(
    ca_bundle: str | None, environ: MutableMapping[str, str] = os.environ
) -> Iterator[None]:
    """While active, this process's TLS (and the provider worker it spawns) trusts `ca_bundle`.

    `SSL_CERT_FILE` replaces Python's default roots; the previous value is restored on exit.
    """
    if not ca_bundle:
        yield
        return
    previous = environ.get("SSL_CERT_FILE")
    environ["SSL_CERT_FILE"] = ca_bundle
    try:
        yield
    finally:
        if previous is None:
            environ.pop("SSL_CERT_FILE", None)
        else:
            environ["SSL_CERT_FILE"] = previous
