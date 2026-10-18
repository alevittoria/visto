"""Composition root: external adapters are wired here, never into inner layers."""

import os
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from visto.adapters.android.host_bridge import HostAdb, bridge_host_devices
from visto.adapters.android.inventory import find_adb, list_devices
from visto.adapters.api.execution import LOOPBACK_HOSTS
from visto.adapters.api.execution import router as execution_router
from visto.adapters.api.health import router as health_router
from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.pricing import fetch_prices
from visto.application.ports import PortError

# Repository-root defaults do not depend on the process working directory.
REPOSITORY = Path(__file__).resolve().parents[3]


def default_settings() -> WebSettings:
    work = REPOSITORY / ".work"
    return WebSettings(work / "runs", REPOSITORY / ".env", work / "device-leases")


def create_app(service: ExecutionService | None = None) -> FastAPI:
    """Create the local HTTP application without contacting device or provider."""
    if service is None:
        execution = ExecutionService(default_settings())
        adb = find_adb()
        execution.device_lister = lambda: list_devices(adb)
        # Docker Desktop: the host adb server owns USB phones (docs/docker.md).
        host = HostAdb.parse(os.environ.get("VISTO_HOST_ADB"))
        if host is not None:
            execution.device_connector = lambda: bridge_host_devices(adb, host)
        # Daily public price list for cost estimates; "off" keeps the backend offline.
        if os.environ.get("VISTO_PRICE_REFRESH", "on").strip().lower() != "off":
            execution.price_fetcher = fetch_prices
    else:
        execution = service

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
        return response

    app.include_router(health_router)
    app.include_router(execution_router)
    return app
