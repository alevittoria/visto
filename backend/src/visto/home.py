"""Per-user Visto home: the single root for data, settings, toolchain and logs."""

from dataclasses import dataclass
from pathlib import Path

PRIVATE_DIR_MODE = 0o700


@dataclass(frozen=True, slots=True)
class VistoHome:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def leases(self) -> Path:
        return self.data / "device-leases"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def secrets_file(self) -> Path:
        return self.root / "secrets.json"

    @property
    def toolchain(self) -> Path:
        return self.root / "toolchain"

    @property
    def instances(self) -> Path:
        return self.root / "instances"

    @property
    def logs(self) -> Path:
        return self.root / "logs"


def default_home() -> VistoHome:
    return VistoHome(Path.home() / ".visto")


def make_private_dir(path: Path) -> None:
    """Create `path` and missing parents owner-only on POSIX; existing directories are kept.

    Windows ignores the mode and relies on the profile ACL.
    """
    path = Path(path)
    missing = []
    while not path.exists() and path.parent != path:
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        directory.mkdir(mode=PRIVATE_DIR_MODE, exist_ok=True)
