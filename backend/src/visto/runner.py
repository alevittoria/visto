"""Composition for the opt-in headless runner; construction never contacts a device."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from visto.adapters.ai import INSTRUCTION_VERSIONS, OpenAIAgent
from visto.adapters.android import AppiumDevice
from visto.adapters.devices import Platform
from visto.adapters.ios.device import XCUITestDevice
from visto.adapters.ios.signing import IOSSigning
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.loop import RunLoop
from visto.application.runtime import MutableRunControl, SystemClock
from visto.domain.commands import CommandKind
from visto.domain.models import Goal, ModelIdentity, RunConfiguration, RunLimits
from visto.domain.run import Run
from visto.home import default_home

# The one place a platform selects its device adapter.
DEVICE_ADAPTERS = {Platform.ANDROID: AppiumDevice, Platform.IOS: XCUITestDevice}


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    device_id: str
    data_directory: Path
    appium_url: str = "http://127.0.0.1:4723"
    model: str = "gpt-6-luna"
    limits: RunLimits = RunLimits(1200000, 60, 90, 60000, 10000)
    lease_directory: Path = field(default_factory=lambda: default_home().leases)
    capabilities: tuple[CommandKind, ...] = tuple(CommandKind)
    platform: Platform = Platform.ANDROID
    ios_signing: IOSSigning = IOSSigning()
    # Before an iOS session: brings the tunnel back for a phone (see XCUITestDevice).
    ios_prepare: Callable[[str, float], object] | None = field(
        default=None, compare=False, repr=False
    )

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
    agent = OpenAIAgent(api_key, settings.model, platform=settings.platform)
    root = settings.data_directory.resolve()
    artifacts = LocalArtifactStore(root / "artifacts")
    store = SQLiteRunStore(root / "runs.sqlite3", artifacts)
    options = (
        {"signing": settings.ios_signing, "prepare": settings.ios_prepare}
        if settings.platform is Platform.IOS
        else {}
    )
    device = DEVICE_ADAPTERS[settings.platform](
        settings.appium_url,
        settings.lease_directory.resolve(),
        request_timeout_ms=settings.limits.max_command_timeout_ms,
        **options,
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
            ModelIdentity("openai", settings.model, INSTRUCTION_VERSIONS[settings.platform]),
            DEVICE_ADAPTERS[settings.platform].version,
        ),
        now,
        now,
    )
