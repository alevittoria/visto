"""Shared Appium session core; platform specifics live in the platform adapters."""

from .session import AppiumSession, NoFocusedField
from .wire import HttpWire, Wire

__all__ = ["AppiumSession", "HttpWire", "NoFocusedField", "Wire"]
