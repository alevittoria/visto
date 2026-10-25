"""Bounded local control-plane service; retains one runtime conversation."""

import asyncio
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from fastapi import HTTPException

from visto.adapters.ai import AUDIO_EXTENSIONS, TRANSCRIPTION_MODEL, transcribe
from visto.adapters.devices import AttachedDevice, InventoryUnavailable, Platform
from visto.adapters.pricing import PriceSheet, SQLitePriceStore
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.adapters.storage.codec import loads
from visto.application.loop import RunLoop
from visto.application.ports import PortError
from visto.application.runtime import MutableRunControl, SystemClock
from visto.configuration import resolve_api_key
from visto.domain.models import ArtifactRef, Goal, Observation, RunLimits
from visto.domain.run import InfrastructureFailure, Run, RunState, UserAnswer
from visto.runner import RunnerSettings, build_runtime, new_run

_LOG = logging.getLogger(__name__)
PRICE_CHECK_INTERVAL_S = 3600


def kind(value: object) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type(value).__name__).lower().replace("a_i_", "ai_")


def public(value: object, *, observation_id: str | None = None) -> object:
    """Explicit artifact translation keeps private storage keys off the wire."""
    if isinstance(value, ArtifactRef):
        return {
            **{
                f.name: public(getattr(value, f.name))
                for f in fields(value)
                if f.name != "storage_key"
            },
            "url": f"/api/runs/{value.run_id}/artifacts/{observation_id}",
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        oid = value.observation_id if isinstance(value, Observation) else observation_id
        return {
            "kind": kind(value),
            **{f.name: public(getattr(value, f.name), observation_id=oid) for f in fields(value)},
        }
    if isinstance(value, tuple):
        return [public(item) for item in value]
    return value


@dataclass(frozen=True)
class WebSettings:
    data_directory: Path
    env_file: Path
    lease_directory: Path
    appium_url: str = "http://127.0.0.1:4723"
    model: str = "gpt-6-luna"
    # Operator-selectable models (OpenAI docs, see docs/references.md); default first.
    models: tuple[str, ...] = ("gpt-6-luna", "gpt-5.6-terra", "gpt-6-sol")
    limits: RunLimits = RunLimits(1200000, 60, 90, 60000, 10000)


@dataclass
class _Execution:
    run_id: str
    runtime: RunLoop
    control: MutableRunControl
    wake: asyncio.Event
    task: asyncio.Task | None = None
    pending: str | None = None


class ExecutionService:
    def __init__(
        self,
        settings: WebSettings,
        *,
        runtime_factory: Callable = build_runtime,
        key_resolver: Callable = resolve_api_key,
        device_lister: Callable[[], Awaitable[tuple[AttachedDevice, ...]]] | None = None,
        ios_device_lister: Callable[[], Awaitable[tuple[AttachedDevice, ...]]] | None = None,
        ios_physical_device_lister: Callable[[], Awaitable[tuple[AttachedDevice, ...]]]
        | None = None,
        transcriber: Callable[[str, bytes, str], Awaitable[str]] = transcribe,
    ):
        self.settings = settings
        self.runtime_factory = runtime_factory
        self.key_resolver = key_resolver
        self.device_lister = device_lister
        self.ios_device_lister = ios_device_lister
        self.ios_physical_device_lister = ios_physical_device_lister
        self.transcriber = transcriber
        self.transcribing = False
        self.inventory_lock = asyncio.Lock()
        self.clock = SystemClock()
        self.active: _Execution | None = None
        self.lock = asyncio.Lock()
        self.closing = False
        # Runs whose cleanup failed after a terminal record already existed. The
        # stored verdict stays authoritative; the operator must reconcile the device.
        self.cleanup_failures: set[str] = set()
        # Optional blocking fetch of today's price list; None keeps pricing offline.
        self.price_fetcher: Callable[[], PriceSheet] | None = None
        self.price_error: str | None = None
        self.price_attempt_at: str | None = None
        self.price_task: asyncio.Task | None = None

    async def open(self):
        self.artifacts = LocalArtifactStore(self.settings.data_directory / "artifacts")
        self.store = SQLiteRunStore(self.settings.data_directory / "runs.sqlite3", self.artifacts)
        try:
            self.prices = SQLitePriceStore(self.settings.data_directory / "prices.sqlite3")
        except (OSError, sqlite3.Error):
            raise PortError("storage: price history unavailable") from None
        if self.price_fetcher is not None:
            self.price_task = asyncio.create_task(self._price_loop())

    async def refresh_prices(self) -> bool:
        """Stores one snapshot per UTC day; True when a new day's prices were saved."""
        now = self.clock.now()
        if self.price_fetcher is None or await asyncio.to_thread(self.prices.has, now.date()):
            return False
        self.price_attempt_at = now.isoformat()
        try:
            sheet = await asyncio.to_thread(self.price_fetcher)
            saved = await asyncio.to_thread(self.prices.save, now.date(), now.isoformat(), sheet)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.price_error = "Price list could not be refreshed; retrying within an hour"
            _LOG.warning("Price refresh failed: %s", type(error).__name__)
            return False
        self.price_error = None
        return saved

    async def _price_loop(self):
        while True:
            await self.refresh_prices()
            await asyncio.sleep(PRICE_CHECK_INTERVAL_S)

    def platforms(self) -> list[str]:
        """Platforms whose device sources are configured in this process."""
        ios = self.ios_device_lister or self.ios_physical_device_lister
        return [
            p.value for p, on in ((Platform.ANDROID, self.device_lister), (Platform.IOS, ios)) if on
        ]

    def readiness(self):
        error = None
        key = ""
        try:
            key = self.key_resolver(self.settings.env_file)
            RunnerSettings(
                "configuration-check",
                self.settings.data_directory,
                appium_url=self.settings.appium_url,
                model=self.settings.model,
            )
        except (ValueError, OSError):
            error = "Server configuration is invalid; check local operator settings"
        configured = bool(key.strip()) and error is None
        return {
            "configured": configured,
            "provider_key_configured": bool(key.strip()),
            "configuration_error": error,
            "model": self.settings.model,
            "models": list(self.settings.models),
            "appium_url": self.settings.appium_url,
            "device_selection": "manual",
            "devices": [],
            "platforms": self.platforms(),
            "active_run_id": self.active.run_id if self.active else None,
            "cleanup_attention_run_ids": sorted(self.cleanup_failures),
            "execution_available": configured and self.active is None and not self.closing,
            "default_limits": {
                f.name: getattr(self.settings.limits, f.name) for f in fields(self.settings.limits)
            },
        }

    async def transcribe(self, audio: bytes, content_type: str | None) -> dict:
        """Dictated goal text: one bounded provider request, never stored or run."""
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        if media_type not in AUDIO_EXTENSIONS:
            raise HTTPException(415, "Unsupported audio format")
        if not audio:
            raise HTTPException(422, "No audio was recorded")
        try:
            key = self.key_resolver(self.settings.env_file)
        except (ValueError, OSError):
            key = ""
        if not key.strip():
            raise HTTPException(503, "Provider configuration is missing or invalid on the server")
        if self.transcribing:
            raise HTTPException(429, "Another recording is being transcribed")
        self.transcribing = True
        try:
            text = await self.transcriber(key, audio, media_type)
        except PortError as error:
            # Transport codes are sanitized categories such as "provider: http_401".
            raise HTTPException(502, f"Transcription failed ({error})") from None
        finally:
            self.transcribing = False
        return {"text": text, "model": TRANSCRIPTION_MODEL}

    async def devices(self):
        """Inventory for selection; a run still re-checks the device."""
        listers = [
            lister
            for lister in (
                self.device_lister,
                self.ios_device_lister,
                self.ios_physical_device_lister,
            )
            if lister
        ]
        if not listers:
            return {"available": False, "devices": [], "error": "Device listing is not configured"}

        async def adb_source():
            async with self.inventory_lock:  # One adb client process at a time.
                return await self.device_lister()

        async def listed(source):
            try:
                return await source()
            except InventoryUnavailable as error:
                return error

        # Sources run concurrently so the worst case is the slowest one, not their sum.
        sources = [
            source
            for source, lister in (
                (adb_source, self.device_lister),
                (self.ios_device_lister, self.ios_device_lister),
                (self.ios_physical_device_lister, self.ios_physical_device_lister),
            )
            if lister
        ]
        results = await asyncio.gather(*(listed(source) for source in sources))
        attached: list[AttachedDevice] = []
        problems: list[str] = []
        for result in results:
            if isinstance(result, InventoryUnavailable):
                problems.append(str(result))
            else:
                attached.extend(result)
        if len(problems) == len(sources):
            return {
                "available": False,
                "devices": [],
                "error": "; ".join(dict.fromkeys(problems)),
                "notes": [],
            }
        notes = tuple(dict.fromkeys(problems))  # A shared cause is noted once.
        return {
            "available": True,
            "devices": [
                {
                    "serial": item.serial,
                    "platform": item.platform.value,
                    "state": item.state,
                    "model": item.model,
                    "product": item.product,
                    "selectable": item.selectable,
                }
                for item in attached
            ],
            "error": None,
            "notes": list(notes),
        }

    async def _rows(self, run_id=None, limit=50, offset=0):
        def read():
            try:
                with closing(
                    sqlite3.connect(self.store.database.as_uri() + "?mode=ro", uri=True, timeout=5)
                ) as db:
                    if run_id is None:
                        rows = db.execute(
                            "SELECT payload FROM runs ORDER BY rowid DESC LIMIT ? OFFSET ?",
                            (limit, offset),
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT payload FROM runs WHERE run_id=?", (run_id,)
                        ).fetchall()
                    result = [loads(row[0]) for row in rows]
                    if any(not isinstance(run, Run) for run in result):
                        raise ValueError("Invalid stored run")
                    return result
            except (sqlite3.Error, ValueError, OSError, TypeError, KeyError, RecursionError):
                raise PortError("storage: read unavailable") from None

        return await asyncio.to_thread(read)

    async def get(self, run_id):
        rows = await self._rows(run_id)
        if not rows:
            raise HTTPException(404, "Run not found")
        return rows[0]

    async def usage(self, run_id=None):
        return await self.store.token_usage(run_id)

    @staticmethod
    def usage_view(totals):
        input_tokens, output_tokens, decisions, unknown = totals or (0, 0, 0, 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "recorded_decisions": decisions,
            "unknown_usage_decisions": unknown,
        }

    def view(self, run, usage=None):
        own = self.active is not None and self.active.run_id == run.run_id
        pending = self.active.pending if own else None
        if pending == "resume" and run.state in (RunState.RUNNING, RunState.TERMINAL):
            pending = None
        result = public(run)
        result.pop("kind")
        suspended = run.state in (RunState.PAUSED, RunState.WAITING_FOR_USER)
        answered = run.pending_question is None or run.pending_question.answer is not None
        result.update(
            can_resume=own and suspended and answered and pending is None,
            interrupted=not own and run.state is not RunState.TERMINAL,
            control_pending=pending,
            cleanup_failed=run.run_id in self.cleanup_failures,
        )
        if usage is not None:
            result["usage"] = self.usage_view(usage.get(run.run_id))
        return result

    async def create(self, request):
        async with self.lock:
            if self.closing or self.active is not None:
                raise HTTPException(
                    409, "One execution is already retained; finish or cancel it first"
                )
            model = self.settings.model if request.model is None else request.model
            if model not in self.settings.models:
                raise HTTPException(422, "Unsupported AI model")
            readiness = self.readiness()
            if not readiness["configured"]:
                raise HTTPException(
                    503, "Provider configuration is missing or invalid on the server"
                )
            try:
                key = self.key_resolver(self.settings.env_file)
                settings = RunnerSettings(
                    request.device_id,
                    self.settings.data_directory,
                    appium_url=self.settings.appium_url,
                    model=model,
                    limits=RunLimits(**request.limits.model_dump()),
                    lease_directory=self.settings.lease_directory,
                    platform=request.platform,
                    **({"capabilities": ()} if request.observe_only else {}),
                )
                control = MutableRunControl()
                runtime = self.runtime_factory(settings, key, control)
                run = new_run(
                    settings,
                    Goal(request.goal, tuple(request.constraints), request.expected_result),
                    self.clock,
                )
            except (ValueError, OSError):
                raise HTTPException(503, "Runtime configuration could not be initialized") from None
            await self.store.create(run)
            entry = _Execution(run.run_id, runtime, control, asyncio.Event())
            self.active = entry
            entry.task = asyncio.create_task(self._worker(entry, run))
            return self.view(run)

    async def _worker(self, entry, run):
        try:
            run = await entry.runtime.start(run)
            while run.state is not RunState.TERMINAL:
                entry.pending = None
                while not entry.wake.is_set():
                    remaining = (
                        run.configuration.limits.wall_time_ms / 1000
                        - (self.clock.now() - run.created_at).total_seconds()
                    )
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(entry.wake.wait(), remaining)
                    except TimeoutError:
                        # Some platform timers wake early. Recheck the actual deadline;
                        # never try to resume an unanswered question before expiry.
                        continue
                entry.wake.clear()
                run = await entry.runtime.resume(run.run_id)
        except Exception:
            # Never include exception text: it may contain credentials or private paths.
            try:
                if (await self.store.get(run.run_id)).state is RunState.TERMINAL:
                    # Finalize would be a no-op: surface cleanup separately from the verdict.
                    self.cleanup_failures.add(run.run_id)
                    return
                await self.store.finalize(
                    run.run_id,
                    InfrastructureFailure(
                        run.run_id,
                        self.clock.now(),
                        "web.execution",
                        "Execution or cleanup failed; inspect local evidence and device ownership",
                    ),
                )
            except Exception:
                pass  # Preserve durable partial history; subsequent reads expose storage failure.
        finally:
            if self.active is entry:
                self.active = None

    async def control(self, run_id, operation):
        async with self.lock:
            run = await self.get(run_id)
            if run.state is RunState.TERMINAL:
                if operation == "cancel":
                    return self.view(run)
                raise HTTPException(409, "Run is already terminal")
            entry = self.active
            if entry is None or entry.run_id != run_id:
                raise HTTPException(
                    409, "Prior-process run cannot safely resume or claim device ownership"
                )
            if operation == "pause":
                if entry.pending == "resume":
                    raise HTTPException(409, "Resume is pending; retry once the run is running")
                if run.state is RunState.PAUSED:
                    return self.view(run)
                if run.state not in (RunState.CREATED, RunState.RUNNING):
                    raise HTTPException(409, "Run is not running")
                if entry.pending == "cancel":
                    raise HTTPException(409, "Cancellation is pending")
                entry.control.pause()
                entry.pending = "pause"
            elif operation == "cancel":
                entry.control.cancel()
                entry.pending = "cancel"
                entry.wake.set()
            else:
                if entry.pending is not None or run.state not in (
                    RunState.PAUSED,
                    RunState.WAITING_FOR_USER,
                ):
                    raise HTTPException(409, "Run is not ready to resume")
                if run.pending_question is not None and run.pending_question.answer is None:
                    raise HTTPException(409, "Answer the pending question first")
                entry.control.resume()
                entry.pending = "resume"
                entry.wake.set()
            return self.view(run)

    async def delete(self, run_id):
        async with self.lock:
            await self.get(run_id)
            if self.active is not None and self.active.run_id == run_id:
                raise HTTPException(409, "Finish or cancel this run before deleting it")
            await self._delete(run_id)
            return {"deleted": [run_id]}

    async def delete_all(self):
        """Delete every stored run except the one this process still owns."""
        async with self.lock:
            active = self.active.run_id if self.active is not None else None
            deleted = []
            while True:
                runs = [run for run in await self._rows(limit=100) if run.run_id != active]
                if not runs:
                    break
                for run in runs:
                    await self._delete(run.run_id)
                    deleted.append(run.run_id)
            return {"deleted": deleted, "kept_active_run_id": active}

    async def _delete(self, run_id):
        # History first: leftover files are unreachable, a dangling record would not be.
        await self.store.delete(run_id)
        self.cleanup_failures.discard(run_id)
        await self.artifacts.delete_run(run_id)

    async def answer(self, run_id, request):
        async with self.lock:
            run = await self.get(run_id)
            entry = self.active
            history = await self.store.history(run_id)
            old = next(
                (
                    item
                    for item in history
                    if isinstance(item, UserAnswer) and item.question_id == request.question_id
                ),
                None,
            )
            if old is not None:
                if old.text == request.text:
                    return self.view(run)
                raise HTTPException(409, "Conflicting answer to a settled question")
            if entry is None or entry.run_id != run_id or entry.pending is not None:
                raise HTTPException(409, "No available retained question for this run")
            if (
                run.pending_question is None
                or run.pending_question.question_id != request.question_id
            ):
                raise HTTPException(409, "Question is stale or belongs to another run")
            try:
                answered = await entry.runtime.answer(
                    UserAnswer(
                        request.question_id, run_id, request.text, "web-operator", self.clock.now()
                    )
                )
            except ValueError:
                raise HTTPException(
                    409, "Question cannot be answered in the current state"
                ) from None
            return self.view(answered)

    async def close(self):
        self.closing = True
        if self.price_task is not None:
            self.price_task.cancel()
        entry = self.active
        if entry is None:
            return
        entry.control.cancel()
        entry.pending = "cancel"
        entry.wake.set()
        timeout = self.settings.limits.max_command_timeout_ms / 1000 + 5
        try:
            await asyncio.wait_for(asyncio.shield(entry.task), timeout)
        except TimeoutError:
            entry.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(entry.task), 2)
            except (TimeoutError, asyncio.CancelledError):
                pass
