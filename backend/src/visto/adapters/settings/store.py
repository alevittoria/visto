"""User settings and the provider key, stored as JSON files in the Visto home."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from visto.adapters.ios.signing import IOSSigning
from visto.home import VistoHome, make_private_dir

FORMAT = 1
MAX_KEY_LENGTH = 8192
_IOS_TEXT = ("team_id", "signing_id", "wda_bundle_id", "wda_derived_data")


class SettingsError(ValueError):
    """A settings or secrets problem; messages never contain file or key content."""


@dataclass(frozen=True)
class Settings:
    price_refresh: bool = True
    ios: IOSSigning = IOSSigning()
    ios_saved_for_xcuitest: str | None = None


@dataclass(frozen=True)
class KeyStatus:
    configured: bool
    last4: str | None


def _read(path: Path, label: str) -> dict | None:
    """The parsed object of a format-1 file, or None when the file is absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise SettingsError(f"{label} file is invalid") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise SettingsError(f"{label} file is invalid") from None
    version = data.get("format") if isinstance(data, dict) else None
    if type(version) is not int:
        raise SettingsError(f"{label} file is invalid")
    if version > FORMAT:
        raise SettingsError(f"{label} file was written by a newer Visto")
    if version != FORMAT:
        raise SettingsError(f"{label} file is invalid")
    return data


def _write(path: Path, data: dict) -> None:
    """Atomic replace through an owner-only sibling temp file."""
    make_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if os.name != "nt":
                os.chmod(handle.fileno(), 0o600)  # Before any content is written.
            json.dump(data, handle, indent=2)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class SettingsStore:
    def __init__(self, home: VistoHome):
        self._home = home

    def load(self) -> Settings:
        data = _read(self._home.settings_file, "settings")
        if data is None:
            return Settings()
        price_refresh = data.get("price_refresh", True)
        saved = data.get("ios_saved_for_xcuitest")
        ios = data.get("ios", {})
        if (
            type(price_refresh) is not bool
            or not (saved is None or isinstance(saved, str))
            or not isinstance(ios, dict)
        ):
            raise SettingsError("settings file is invalid")
        values: dict[str, object] = {name: ios.get(name, "") for name in _IOS_TEXT}
        values["prebuilt_wda"] = ios.get("prebuilt_wda", False)
        if type(values["prebuilt_wda"]) is not bool or not all(
            isinstance(values[name], str) for name in _IOS_TEXT
        ):
            raise SettingsError("settings file is invalid")
        return Settings(price_refresh, IOSSigning(**values), saved)

    def save(self, settings: Settings) -> None:
        ios = settings.ios
        _write(
            self._home.settings_file,
            {
                "format": FORMAT,
                "price_refresh": settings.price_refresh,
                "ios": {
                    "team_id": ios.team_id,
                    "signing_id": ios.signing_id,
                    "wda_bundle_id": ios.wda_bundle_id,
                    "prebuilt_wda": ios.prebuilt_wda,
                    "wda_derived_data": ios.wda_derived_data,
                },
                "ios_saved_for_xcuitest": settings.ios_saved_for_xcuitest,
            },
        )

    def api_key(self) -> str:
        data = _read(self._home.secrets_file, "secrets")
        if data is None:
            return ""
        key = data.get("openai_api_key", "")
        if not isinstance(key, str):
            raise SettingsError("secrets file is invalid")
        return key

    def set_api_key(self, key: str) -> KeyStatus:
        key = key.strip() if isinstance(key, str) else ""
        if not key:
            raise SettingsError("the API key is empty")
        if len(key) > MAX_KEY_LENGTH:
            raise SettingsError("the API key is too long")
        if not key.isprintable() or any(character.isspace() for character in key):
            raise SettingsError("the API key contains whitespace or control characters")
        _write(self._home.secrets_file, {"format": FORMAT, "openai_api_key": key})
        return self.key_status()

    def delete_api_key(self) -> KeyStatus:
        self._home.secrets_file.unlink(missing_ok=True)
        return self.key_status()

    def key_status(self) -> KeyStatus:
        key = self.api_key()
        return KeyStatus(True, key[-4:]) if key else KeyStatus(False, None)
