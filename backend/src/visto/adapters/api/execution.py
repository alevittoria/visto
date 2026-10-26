"""HTTP transport for the bounded local execution service."""

import asyncio
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from visto.adapters.ai import MAX_AUDIO_BYTES
from visto.adapters.devices import Platform
from visto.adapters.pricing import ATTRIBUTION, SOURCE_NAME, SOURCE_URL
from visto.adapters.reports import render_html, render_json
from visto.domain.models import Observation

from .service import ExecutionService, kind, public
from .statistics import cost_view, summarize

router = APIRouter(prefix="/api")
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


class LimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    wall_time_ms: int = Field(default=1200000, ge=1, le=3600000)
    max_actions: int = Field(default=60, ge=1, le=300)
    max_inferences: int = Field(default=90, ge=1, le=300)
    max_command_timeout_ms: int = Field(default=60000, ge=1, le=60000)
    max_observation_delay_ms: int = Field(default=10000, ge=1, le=60000)


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    device_id: NonBlank = Field(max_length=256)
    goal: NonBlank = Field(max_length=16000)
    expected_result: NonBlank | None = Field(default=None, max_length=8000)
    constraints: list[Annotated[NonBlank, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=32
    )
    model: NonBlank | None = Field(default=None, max_length=128)
    observe_only: bool = False
    platform: Platform = Field(default=Platform.ANDROID, strict=False)
    limits: LimitsRequest = Field(default_factory=LimitsRequest)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question_id: NonBlank = Field(max_length=256)
    text: NonBlank = Field(max_length=8000)


def service(request: Request) -> ExecutionService:
    return request.app.state.execution


def require_local_write(request: Request):
    host = urlsplit(str(request.url)).hostname
    if request.headers.get("x-visto") != "local-console" or host not in LOOPBACK_HOSTS:
        raise HTTPException(403, "Local console request header and loopback host are required")
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin console writes are forbidden")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(403, "Cross-site console writes are forbidden")


@router.get("/readiness")
async def readiness(request: Request) -> dict:
    return service(request).readiness()


@router.get("/devices")
async def devices(request: Request) -> dict:
    return await service(request).devices()


@router.post("/transcriptions")
async def transcription(request: Request) -> dict:
    """Raw recorded audio in, transcript out; the operator reviews it before a run."""
    require_local_write(request)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long")
    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording is too long")
    return await service(request).transcribe(bytes(audio), request.headers.get("content-type"))


@router.post("/runs", status_code=202)
async def create_run(request: Request, body: CreateRequest) -> dict:
    require_local_write(request)
    return await service(request).create(body)


@router.get("/runs")
async def list_runs(
    request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> dict:
    execution = service(request)
    runs = await execution._rows(limit=limit, offset=offset)
    usage = await execution.usage()
    return {
        "runs": [execution.view(run, usage) for run in runs],
        "limit": limit,
        "offset": offset,
    }


@router.delete("/runs")
async def delete_runs(request: Request) -> dict:
    require_local_write(request)
    return await service(request).delete_all()


@router.get("/usage")
async def usage(request: Request) -> dict:
    """Token totals across all stored runs, from persisted decisions only."""
    execution = service(request)
    per_run = await execution.usage()
    total = tuple(sum(item[index] for item in per_run.values()) for index in range(4))
    return {**execution.usage_view(total), "runs_with_decisions": len(per_run)}


@router.get("/statistics")
async def statistics(request: Request) -> dict:
    """Outcome, duration, action and token aggregates over every stored run."""
    execution = service(request)
    runs = await execution._rows(limit=-1)
    usage = await execution.usage()
    actions = await execution.store.action_counts()
    prices = await asyncio.to_thread(execution.prices.history)
    return summarize(runs, usage, actions, prices)


@router.get("/prices")
async def prices(request: Request) -> dict:
    """Latest stored daily price snapshot and refresh state; never fetches."""
    execution = service(request)
    latest = await asyncio.to_thread(execution.prices.latest_snapshot)
    history = await asyncio.to_thread(execution.prices.history)
    return {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "attribution": ATTRIBUTION,
        "refresh_enabled": execution.price_fetcher is not None
        and execution.price_refresh_enabled(),
        "snapshot": latest,
        "last_attempt_at": execution.price_attempt_at,
        "error": execution.price_error,
        "models": {
            model: {
                "day": price.day.isoformat(),
                "input_per_m": price.input_per_m,
                "output_per_m": price.output_per_m,
            }
            for model, price in sorted(history.latest().items())
            if model in execution.settings.models
        },
    }


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> dict:
    execution = service(request)
    run = await execution.get(run_id)
    usage = await execution.usage(run_id)
    result = execution.view(run, usage)
    result["cost"] = cost_view(run, usage, await asyncio.to_thread(execution.prices.history))
    return result


@router.delete("/runs/{run_id}")
async def delete_run(request: Request, run_id: str) -> dict:
    require_local_write(request)
    return await service(request).delete(run_id)


@router.get("/runs/{run_id}/events")
async def events(
    request: Request,
    run_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> dict:
    execution = service(request)
    await execution.get(run_id)
    history = await execution.store.history(run_id)
    selected = history[after : after + limit]
    return {
        "events": [
            {"sequence": after + index + 1, "kind": kind(item), "data": public(item)}
            for index, item in enumerate(selected)
        ],
        "next_after": after + len(selected),
    }


@router.get("/runs/{run_id}/artifacts/{observation_id}")
async def artifact(request: Request, run_id: str, observation_id: str) -> Response:
    execution = service(request)
    await execution.get(run_id)
    history = await execution.store.history(run_id)
    observation = next(
        (
            item
            for item in history
            if isinstance(item, Observation) and item.observation_id == observation_id
        ),
        None,
    )
    if observation is None:
        raise HTTPException(404, "Observation artifact not found in this run")
    return Response(
        await execution.artifacts.read(observation.screenshot),
        media_type=observation.screenshot.media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )


async def report_response(request: Request, run_id: str, *, html: bool) -> Response:
    execution = service(request)
    run = await execution.get(run_id)
    history = await execution.store.history(run_id)
    # If lifecycle changed during the first read, include its durable final history.
    current = await execution.get(run_id)
    if current.revision != run.revision:
        history = await execution.store.history(run_id)
    try:
        content = (render_html if html else render_json)(current, history)
    except ValueError:
        raise HTTPException(409, "Stored run cannot be exported with this report format") from None
    return Response(
        content,
        media_type="text/html" if html else "application/json",
        headers={
            "Content-Disposition": (
                'inline; filename="visto-report.html"'
                if html
                else 'attachment; filename="visto-report.json"'
            ),
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
            ),
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/runs/{run_id}/report.json")
async def json_report(request: Request, run_id: str) -> Response:
    return await report_response(request, run_id, html=False)


@router.get("/runs/{run_id}/report.html")
async def html_report(request: Request, run_id: str) -> Response:
    return await report_response(request, run_id, html=True)


@router.post("/runs/{run_id}/pause", status_code=202)
async def pause(request: Request, run_id: str) -> dict:
    require_local_write(request)
    return await service(request).control(run_id, "pause")


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(request: Request, run_id: str) -> dict:
    require_local_write(request)
    return await service(request).control(run_id, "resume")


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel(request: Request, run_id: str) -> dict:
    require_local_write(request)
    return await service(request).control(run_id, "cancel")


@router.post("/runs/{run_id}/answers")
async def answer(request: Request, run_id: str, body: AnswerRequest) -> dict:
    require_local_write(request)
    return await service(request).answer(run_id, body)
