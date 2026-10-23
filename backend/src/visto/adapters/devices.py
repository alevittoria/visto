"""Platform-neutral device inventory types shared by the platform inventories."""

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    ANDROID = "android"
    IOS = "ios"


# Per-platform states in which a run may start; the single source of selectability.
_SELECTABLE = {
    Platform.ANDROID: frozenset({"device"}),
    Platform.IOS: frozenset({"booted", "connected"}),
}


@dataclass(frozen=True, slots=True)
class AttachedDevice:
    platform: Platform
    serial: str
    state: str  # platform state, e.g. adb device/unauthorized/offline, iOS booted/shutdown
    model: str | None = None
    product: str | None = None

    @property
    def selectable(self) -> bool:
        return self.state in _SELECTABLE[self.platform]


class InventoryUnavailable(Exception):
    """Safe message only; never includes process output or local paths."""
