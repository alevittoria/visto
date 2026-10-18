"""Operator speech-to-text for goal authoring; never part of a run's conversation."""

from visto.application.ports import PortError

from .transport import request_transcription

MAX_TRANSCRIPT_CHARS = 16000


async def transcribe(api_key: str, audio: bytes, media_type: str, timeout_ms: int = 60000) -> str:
    """Return the provider transcript; only a bounded text field is accepted."""
    response = await request_transcription(api_key, audio, media_type, timeout_ms)
    text = response.get("text")
    if type(text) is not str or len(text) > MAX_TRANSCRIPT_CHARS:
        raise PortError("provider: invalid_json")
    return text.strip()
