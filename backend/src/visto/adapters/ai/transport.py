"""Deadline-bound fixed HTTPS child; credentials travel only through its stdin."""

import asyncio
import base64
import json
import os
import re
import subprocess
import sys

from visto.application.ports import PortError

MAX_REQUEST_BYTES = 24 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_INPUT_BYTES = MAX_REQUEST_BYTES * 2 + 65536
# Speech-to-text for operator-dictated goals (docs/references.md). The provider
# accepts up to 25 MB; the console's short recordings stay far below this bound.
TRANSCRIPTION_MODEL = "gpt-transcribe"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
AUDIO_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}
SAFE_ERRORS = frozenset(
    "provider: " + code
    for code in (
        "response_size_limit",
        "transport_or_json_error",
        "timeout",
        "connection_refused",
        "dns_error",
        "tls_error",
        "connection_error",
        "invalid_json",
        "invalid_request",
        "worker_start_error",
        "worker_protocol_error",
    )
)


def safe_error(value: object) -> bool:
    return type(value) is str and (
        value in SAFE_ERRORS or re.fullmatch(r"provider: http_[45][0-9]{2}", value) is not None
    )


async def _reap(process: subprocess.Popen, communication: asyncio.Task | None) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    if communication is None:
        communication = asyncio.create_task(asyncio.to_thread(process.communicate))
    try:
        await communication
    except (OSError, ValueError):
        pass  # A pipe error must not prevent reaping the already killed child.
    await asyncio.to_thread(process.wait)


async def _finish_cleanup(process: subprocess.Popen, communication: asyncio.Task | None) -> None:
    cleanup = asyncio.create_task(_reap(process, communication))
    interrupted = False
    while True:
        try:
            await asyncio.shield(cleanup)
            break
        except asyncio.CancelledError:
            interrupted = True
    if interrupted:
        raise asyncio.CancelledError


async def request_response(
    api_key: str, payload: bytes, timeout_ms: int, *, _spawn=subprocess.Popen
) -> dict:
    """Run only the fixed worker; _spawn is a private local-test boundary."""
    return await _exchange(api_key, payload, timeout_ms, {}, _spawn)


async def request_transcription(
    api_key: str, audio: bytes, media_type: str, timeout_ms: int, *, _spawn=subprocess.Popen
) -> dict:
    """Send one recording to the fixed transcription endpoint through the same worker."""
    if (
        media_type not in AUDIO_EXTENSIONS
        or type(audio) is not bytes
        or len(audio) > MAX_AUDIO_BYTES
    ):
        raise PortError("provider: invalid_request")
    return await _exchange(api_key, audio, timeout_ms, {"media_type": media_type}, _spawn)


async def _exchange(api_key, payload, timeout_ms, extra: dict, _spawn) -> dict:
    if (
        type(api_key) is not str
        or not api_key.strip()
        or len(api_key) > 8192
        or type(payload) is not bytes
        or not payload
        or len(payload) > MAX_REQUEST_BYTES
        or type(timeout_ms) is not int
        or timeout_ms < 1
    ):
        raise PortError("provider: invalid_request")
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    packet = json.dumps(
        {
            "api_key": api_key,
            "payload": base64.b64encode(payload).decode("ascii"),
            "timeout_ms": timeout_ms,
            **extra,
        },
        separators=(",", ":"),
    ).encode()
    process = None
    communication = None
    try:
        # Synchronous OS creation gives us the handle before cancellation can
        # occur. Startup counts against the deadline; no stdin is sent if it has
        # already expired. Remove the inherited provider key while preserving
        # normal proxy/TLS settings. This request's key travels only over stdin.
        process = _spawn(
            [sys.executable, "-m", "visto.adapters.ai.http_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                key: value for key, value in os.environ.items() if key.upper() != "OPENAI_API_KEY"
            },
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError
        # Only local child-pipe I/O runs in this thread. Killing our fixed child
        # closes the pipes; cleanup joins this task before returning. Network I/O
        # runs exclusively in the child. The trusted worker bounds stdout before
        # writing it; the parent also verifies the resulting envelope size.
        communication = asyncio.create_task(asyncio.to_thread(process.communicate, packet))
        async with asyncio.timeout_at(deadline):
            output, _ = await asyncio.shield(communication)
            if len(output) > MAX_RESPONSE_BYTES:
                raise PortError("provider: response_size_limit")
            if process.returncode != 0:
                raise PortError("provider: worker_protocol_error")
            envelope = json.loads(output)
            if type(envelope) is not dict:
                raise ValueError("Invalid worker response")
            if set(envelope) == {"error"} and safe_error(envelope["error"]):
                raise PortError(envelope["error"])
            if set(envelope) != {"response"} or type(envelope["response"]) is not dict:
                raise ValueError("Invalid worker response")
            return envelope["response"]
    except TimeoutError:
        raise PortError("provider: timeout") from None
    except PortError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        code = "worker_start_error" if process is None else "worker_protocol_error"
        raise PortError(f"provider: {code}") from None
    finally:
        if process is not None:
            await _finish_cleanup(process, communication)
