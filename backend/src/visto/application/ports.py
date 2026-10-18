"""Small async integration boundaries. Exceptions/details must be sanitized.

All I/O is finite and caller-bound. Cancellation/deadlines and semantic decision
validation are application responsibilities; adapters never silently retry an
uncertain mutation or invent an AI conclusion.
"""

from datetime import datetime
from typing import Protocol

from visto.domain.models import (
    Action,
    AgentDecision,
    ArtifactRef,
    CapturedImage,
    DeviceLease,
    Observation,
    TechnicalReceipt,
)
from visto.domain.run import PendingQuestion, Run, TerminalRecord, UserAnswer

from .context import AgentContext, AgentReply

type RunRecord = (
    Observation | Action | TechnicalReceipt | AgentDecision | PendingQuestion | UserAnswer
)


class PortError(Exception):
    """Technical boundary failure with safe component/code/detail, no raw secrets.

    Device execution after possible dispatch must return an UNCERTAIN receipt
    instead of raising an exception that could invite blind mutation retry.
    """


class Device(Protocol):
    async def acquire(self, run_id: str, device_id: str, timeout_ms: int) -> DeviceLease:
        """Acquire exclusive ownership or fail, without stealing another lease."""
        ...

    async def release(self, lease: DeviceLease) -> None:
        """Idempotently release only this owner; never another run's session."""
        ...

    async def observe(self, lease: DeviceLease, timeout_ms: int) -> CapturedImage:
        """Fresh capture or explicit failure, never an empty/previous screenshot."""
        ...

    async def execute(
        self, lease: DeviceLease, action: Action, source: Observation
    ) -> TechnicalReceipt:
        """Validate live ownership/frame/capability, dispatch once, report receipt.

        Coordinates refer to source image pixels, including its rotation. Reject
        stale/unsupported frames rather than guessing. No arbitrary shell.
        """
        ...


class Agent(Protocol):
    async def decide(self, context: AgentContext, timeout_ms: int) -> AgentReply:
        """One logical conversation; screenshots are data, original goal is authority.

        Timeout, refusal, rate-limit, malformed output and context overflow are
        explicit technical errors. Unknown usage stays None; no silent fallback.
        """
        ...


class RunStore(Protocol):
    async def create(self, run: Run) -> None: ...

    async def get(self, run_id: str) -> Run: ...

    async def history(self, run_id: str) -> tuple[RunRecord, ...]: ...

    async def append(self, record: RunRecord) -> None:
        """Run-scoped unique records; identical repeat idempotent, conflict rejected.

        Artifact must exist before observation append; source observations and
        decision must exist before action intent; intent precedes device dispatch.
        Do not overwrite evidence or previously supplied decision context.
        Append question/attributed answer before resume clears pending snapshot;
        application context retains those answers as user clarifications.
        """
        ...

    async def save(self, run: Run, expected_revision: int) -> Run:
        """Compare-and-swap lifecycle; reject changed goal/config or terminal rewrite."""
        ...

    async def finalize(self, run_id: str, terminal: TerminalRecord) -> Run:
        """Atomically persist first terminal; return actual winning terminal Run.

        A late cancellation/conclusion cannot replace the winner. Repeated calls
        return that winner. Validate scope and append terminal atomically. This
        database guarantee is required in addition to immutable Run.finish().
        """
        ...


class ArtifactStore(Protocol):
    async def put(self, run_id: str, content: bytes, media_type: str) -> ArtifactRef:
        """Durably store uniquely owned bytes/hash; no overwrite or public path."""
        ...

    async def read(self, reference: ArtifactRef) -> bytes:
        """Check run ownership/hash/length; missing or corrupt bytes are errors."""
        ...


class RunControl(Protocol):
    def cancel_requested(self) -> bool: ...

    def pause_requested(self) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    async def wait(self, delay_ms: int, control: RunControl) -> None:
        """Finite interruptible wait, returning early for cancellation or pause."""
        ...
