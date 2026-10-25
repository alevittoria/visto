"""Settings routes: console-editable options and the write-only provider key."""

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from visto.adapters.ai.transport import probe_model
from visto.adapters.ai.transport import verify_key as key_verdict
from visto.adapters.ios.signing import IOSSigning
from visto.adapters.settings.store import KeyStatus, Settings, SettingsError, SettingsStore

from .execution import require_local_write, service

router = APIRouter(prefix="/api")
PROBE_TIMEOUT_MS = 10000
KEY_STORAGE = "file"


@dataclass
class SettingsRoutesConfig:
    """Host facts and the key probe; defaults describe a host without iOS support."""

    ios_supported: bool = sys.platform == "darwin"
    wda_project: Callable[[], Path | None] = lambda: None
    xcuitest_version: Callable[[], str | None] = lambda: None
    prober: Callable[[str, str, int], Awaitable[dict]] = field(default=probe_model)


class IOSBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    team_id: str = Field(default="", max_length=64)
    signing_id: str = Field(default="", max_length=256)
    wda_bundle_id: str = Field(default="", max_length=256)
    prebuilt_wda: bool = False
    wda_derived_data: str = Field(default="", max_length=1024)


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    price_refresh: bool
    ios: IOSBody | None = None


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    api_key: str = Field(max_length=8192)


def _config(request: Request) -> SettingsRoutesConfig:
    config = getattr(request.app.state, "settings_host", None)
    if config is None:
        config = request.app.state.settings_host = SettingsRoutesConfig()
    return config


def _store(request: Request) -> SettingsStore:
    return service(request).settings.settings_store


def _invalid() -> HTTPException:
    return HTTPException(503, "Local settings are invalid")


def _key_view(status: KeyStatus) -> dict:
    return {"configured": status.configured, "last4": status.last4, "storage": KEY_STORAGE}


def _view(request: Request) -> dict:
    config = _config(request)
    try:
        store = _store(request)
        settings = store.load()
        key = store.key_status()
    except SettingsError:
        raise _invalid() from None
    supported = config.ios_supported
    current = config.xcuitest_version() if supported else None
    project = config.wda_project() if supported else None
    ios = settings.ios
    return {
        "price_refresh": settings.price_refresh,
        "ios_supported": supported,
        "ios": {
            "team_id": ios.team_id,
            "signing_id": ios.signing_id,
            "wda_bundle_id": ios.wda_bundle_id,
            "prebuilt_wda": ios.prebuilt_wda,
            "wda_derived_data": ios.wda_derived_data,
        }
        if supported
        else None,
        "key": _key_view(key),
        "wda_project": str(project) if project is not None else None,
        "wda_rebuild_needed": bool(
            supported
            and settings.ios_saved_for_xcuitest is not None
            and current is not None
            and settings.ios_saved_for_xcuitest != current
        ),
    }


@router.get("/settings")
async def read_settings(request: Request) -> dict:
    return _view(request)


@router.put("/settings")
async def write_settings(request: Request, body: SettingsBody) -> dict:
    require_local_write(request)
    config = _config(request)
    if body.ios is not None and not config.ios_supported:
        raise HTTPException(422, "iOS settings are not available on this host")
    store = _store(request)
    try:
        current = store.load()
        if body.ios is None:
            settings = Settings(body.price_refresh, current.ios, current.ios_saved_for_xcuitest)
        else:
            settings = Settings(
                body.price_refresh,
                IOSSigning(**body.ios.model_dump()),
                config.xcuitest_version(),
            )
        store.save(settings)
    except (SettingsError, OSError):
        raise _invalid() from None
    return _view(request)


@router.put("/settings/key")
async def write_key(request: Request, body: KeyBody) -> dict:
    require_local_write(request)
    try:
        return _key_view(_store(request).set_api_key(body.api_key))
    except SettingsError as error:
        # Key-validation messages never contain the value; file errors are generic.
        if str(error).startswith("the API key"):
            raise HTTPException(422, str(error)) from None
        raise _invalid() from None
    except OSError:
        raise _invalid() from None


@router.delete("/settings/key")
async def delete_key(request: Request) -> dict:
    require_local_write(request)
    try:
        return _key_view(_store(request).delete_api_key())
    except (SettingsError, OSError):
        raise _invalid() from None


@router.post("/settings/key/verify")
async def verify_key(request: Request) -> dict:
    """Non-billable check: retrieve the default model's metadata with the stored key."""
    require_local_write(request)
    execution = service(request)
    try:
        key = _store(request).api_key()
    except SettingsError:
        raise _invalid() from None
    result = await key_verdict(
        key, execution.settings.model, PROBE_TIMEOUT_MS, probe=_config(request).prober
    )
    return {"result": result}
