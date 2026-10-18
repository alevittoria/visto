"""Multimodal provider boundary."""

from .openai import INSTRUCTION_VERSION, OpenAIAgent
from .transcription import transcribe
from .transport import AUDIO_EXTENSIONS, MAX_AUDIO_BYTES, TRANSCRIPTION_MODEL

__all__ = [
    "AUDIO_EXTENSIONS",
    "INSTRUCTION_VERSION",
    "MAX_AUDIO_BYTES",
    "OpenAIAgent",
    "TRANSCRIPTION_MODEL",
    "transcribe",
]
