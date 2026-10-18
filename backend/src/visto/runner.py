"""Composition for the opt-in headless runner; construction never contacts a device."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from visto.adapters.ai import INSTRUCTION_VERSION, OpenAIAgent
from visto.adapters.android import AppiumDevice
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.loop import RunLoop
from visto.application.runtime import MutableRunControl, SystemClock
from visto.domain.commands import CommandKind
from visto.domain.models import Goal, ModelIdentity, RunConfiguration, RunLimits
from visto.domain.run import Run


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    device_id: str
    data_directory: Path
    appium_url: str = "http://127.0.0.1:4723"
    model: str = "gpt-6-luna"
    limits: RunLimits = RunLimits(1200000, 60, 90, 60000, 10000)
    lease_directory: Path = Path(".work/device-leases")
    capabilities: tuple[CommandKind, ...] = tuple(CommandKind)

    def __post_init__(self):
        if not self.device_id.strip() or not self.model.strip():
            raise ValueError("An explicit device serial and model are required")
        parsed = urlsplit(self.appium_url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Appium URL must be a credential-free loopback address")
        _ = parsed.port  # Reject malformed/out-of-range ports before side effects.


def build_runtime(settings: RunnerSettings, api_key: str, control: MutableRunControl) -> RunLoop:
    """Validate provider configuration before creating local evidence directories."""
    agent = OpenAIAgent(api_key, settings.model)
    root = settings.data_directory.resolve()
    artifacts = LocalArtifactStore(root / "artifacts")
    store = SQLiteRunStore(root / "runs.sqlite3", artifacts)
    device = AppiumDevice(
        settings.appium_url,
        settings.lease_directory.resolve(),
        request_timeout_ms=settings.limits.max_command_timeout_ms,
    )
    return RunLoop(device, agent, store, artifacts, SystemClock(), control)


def new_run(settings: RunnerSettings, goal: Goal, clock: SystemClock) -> Run:
    now = clock.now()
    return Run(
        uuid4().hex,
        settings.device_id,
        goal,
        RunConfiguration(
            settings.limits,
            settings.capabilities,
            ModelIdentity("openai", settings.model, INSTRUCTION_VERSION),
            "appium-wire-v1",
        ),
        now,
        now,
    )
