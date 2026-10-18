"""Service liveness is separate from execution readiness."""

from importlib.metadata import version

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    product: str
    version: str
    runtime_ready: bool


@router.get("/api/health")
async def health() -> HealthResponse:
    return HealthResponse(
        product="Visto",
        version=version("visto"),
        runtime_ready=False,
    )
