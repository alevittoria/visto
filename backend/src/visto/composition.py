"""Composition root: external adapters are wired here, never into inner layers."""

import logging
import re
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from visto.adapters.android.inventory import find_adb, list_devices, start_server
from visto.adapters.api.execution import LOOPBACK_HOSTS
from visto.adapters.api.execution import router as execution_router
from visto.adapters.api.health import router as health_router
from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.api.settings import SettingsRoutesConfig
from visto.adapters.api.settings import router as settings_router
from visto.adapters.ios.inventory import find_xcrun, list_physical, list_simulators
from visto.adapters.pricing import fetch_prices
from visto.adapters.settings.store import SettingsStore
from visto.application.ports import PortError
from visto.home import VistoHome, default_home
from visto.toolchain import Toolchain, ToolchainMissing, ToolPaths
from visto.toolchain.appium import installed_driver_version, wda_project

_LOG = logging.getLogger(__name__)


def default_settings(
    home: VistoHome,
    appium_url: str | None = None,
    ios_prepare: Callable[[str, float], object] | None = None,
) -> WebSettings:
    settings = WebSettings(home.data, SettingsStore(home), home.leases, ios_prepare=ios_prepare)
    return settings if appium_url is None else replace(settings, appium_url=appium_url)


def console_directory() -> Path | None:
    """The built console packaged with Visto; None in a checkout without a build."""
    console = Path(str(files("visto") / "console"))
    return console if (console / "index.html").is_file() else None


_CONSOLE_SEGMENT = re.compile(r"[A-Za-z0-9_@~+=-][A-Za-z0-9._@~+=-]*")


def _console_file(console: Path, path: str) -> Path:
    """The requested file inside the console, else index.html for client-side routes.

    The decoded request path is validated lexically before any filesystem call, so a
    drive, UNC or traversal path never reaches the disk (or the network).
    """
    index = console / "index.html"
    segments = path.removeprefix("/").split("/")
    if not all(_CONSOLE_SEGMENT.fullmatch(segment) for segment in segments):
        return index
    candidate = console.joinpath(*segments)
    try:
        return candidate if candidate.is_file() else index
    except (OSError, ValueError):
        return index


def managed_tools(home: VistoHome) -> ToolPaths | None:
    try:
        return Toolchain(home).paths()
    except (ToolchainMissing, ValueError):
        return None


def settings_host(tools: ToolPaths | None, ios: bool | None = None) -> SettingsRoutesConfig:
    ios = sys.platform == "darwin" if ios is None else ios
    appium = None if tools is None else tools.appium_dir
    if appium is None:
        return SettingsRoutesConfig(ios_supported=ios)
    return SettingsRoutesConfig(
        ios_supported=ios,
        wda_project=lambda: wda_project(appium),
        xcuitest_version=lambda: installed_driver_version(appium, "appium-xcuitest-driver"),
    )


def create_app(
    service: ExecutionService | None = None,
    *,
    home: VistoHome | None = None,
    appium_url: str | None = None,
    ios: bool | None = None,
    ios_prepare: Callable[[str, float], object] | None = None,
) -> FastAPI:
    """Create the local HTTP application without contacting device or provider.

    `appium_url` is the Appium the console's runs use (`visto start` passes the port
    it started Appium on), and `ios_prepare` what brings its iOS tunnel back before an
    iOS run. `ios` defaults to whether this host is a Mac; elsewhere no
    iOS device source is wired, so no iOS wording or platform reaches the console.
    """
    ios = sys.platform == "darwin" if ios is None else ios
    prepare = None
    # An injected service without a home (tests) never reads the user's toolchain.
    tools = None if home is None and service is not None else managed_tools(home or default_home())
    if service is None:
        execution = ExecutionService(
            default_settings(home or default_home(), appium_url, ios_prepare)
        )
        adb = tools.adb if tools is not None and tools.adb.is_file() else find_adb()

        async def prepare():
            # Own the adb server from startup so the first device listing finds it ready.
            if adb is not None and not await start_server(adb):
                _LOG.warning("The adb server could not be started")

        execution.device_lister = lambda: list_devices(adb)
        if ios:
            xcrun = find_xcrun()
            # Two independent iOS sources: one failing must not hide the other's devices.
            execution.ios_device_lister = lambda: list_simulators(xcrun)
            execution.ios_physical_device_lister = lambda: list_physical(xcrun)
        # Daily public price list for cost estimates; the stored switch is read per refresh.
        execution.price_fetcher = fetch_prices
    else:
        execution = service

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if prepare is not None:
            await prepare()
        await execution.open()
        app.state.execution = execution
        try:
            yield
        finally:
            await execution.close()

    app = FastAPI(title="Visto", version=version("visto"), lifespan=lifespan)

    @app.exception_handler(PortError)
    async def storage_unavailable(_: Request, __: PortError) -> JSONResponse:
        # Never echo boundary detail: it may contain local paths.
        return JSONResponse({"detail": "Local evidence storage is unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
        # Name field locations only; submitted values may contain secrets.
        fields = sorted(
            {
                ".".join(str(part) for part in item.get("loc", ())[1:]) or "body"
                for item in error.errors()
            }
        )
        detail = "Invalid request fields: " + ", ".join(fields)
        return JSONResponse({"detail": detail}, status_code=422)

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        # Reads expose private evidence too: a DNS-rebound page sends its own Host.
        if request.url.hostname not in LOOPBACK_HOSTS:
            response = JSONResponse({"detail": "Loopback host is required"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Another origin must not embed screenshots or responses (e.g. via <img>);
        # the same-origin console, navigation and downloads are unaffected.
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

    app.include_router(health_router)
    app.state.settings_host = settings_host(tools, ios)
    app.include_router(execution_router)
    app.include_router(settings_router)
    console = console_directory()
    if console is not None:

        @app.exception_handler(StarletteHTTPException)
        async def console_fallback(request: Request, error: StarletteHTTPException):
            path = request.url.path
            is_api = path == "/api" or path.startswith("/api/")
            if error.status_code == 404 and request.method in ("GET", "HEAD") and not is_api:
                return FileResponse(_console_file(console, path))
            return await http_exception_handler(request, error)

    return app
