"""OpenAI Responses REST adapter. No SDK retries, hidden fallback or remote state.

Wire contract: https://developers.openai.com/api/docs/guides/structured-outputs
and https://developers.openai.com/api/docs/guides/images-vision .
"""

import asyncio
import base64
import json
from dataclasses import asdict, fields, is_dataclass
from importlib.resources import files
from pathlib import Path

from visto.application.context import AgentContext, AgentReply
from visto.application.ports import PortError
from visto.domain.models import ModelUsage

from .schema import SCHEMA, decode_decision
from .transport import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, request_response

INSTRUCTION_VERSION = "android-agent-v3"


def history_data(value):
    """Retain record/command variants which dataclasses.asdict alone would erase."""
    if is_dataclass(value):
        return {
            "record_type": type(value).__name__,
            **{f.name: history_data(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, tuple):
        return [history_data(v) for v in value]
    return value


def load_instructions() -> str:
    packaged = files("visto").joinpath("prompts/android-agent-v3.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    # Source-tree execution; wheels contain the resource at the path above.
    return (Path(__file__).resolve().parents[4] / "prompts/android-agent-v3.md").read_text(
        encoding="utf-8"
    )


class OpenAIAgent:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-6-sol",
        *,
        transport=None,
        max_output_tokens: int = 4096,
    ):
        if not api_key.strip() or not model.strip():
            raise ValueError("Provider key and model are required")
        if type(max_output_tokens) is not int or not 512 <= max_output_tokens <= 16384:
            raise ValueError("Invalid output token bound")
        self._key = api_key
        self.model = model
        self._transport = transport
        self.max_output_tokens = max_output_tokens
        self._instructions = load_instructions()

    async def decide(self, context: AgentContext, timeout_ms: int) -> AgentReply:
        identity = context.run.configuration.identity
        if (identity.provider, identity.model, identity.instruction_version) != (
            "openai",
            self.model,
            INSTRUCTION_VERSION,
        ):
            raise PortError("provider: identity_mismatch")
        if type(timeout_ms) is not int or timeout_ms < 1:
            raise ValueError("Invalid inference timeout")
        if len(context.images) > 8 or len(context.recent_decisions) > 20:
            raise PortError("provider: context_limit")
        metadata = {
            "original_goal": asdict(context.run.goal),
            "configuration": asdict(context.run.configuration),
            "current_observation_id": context.current_observation_id,
            "working_plan": context.working_plan,
            "previous_action": history_data(context.previous_action),
            "previous_receipt": (
                asdict(context.previous_receipt) if context.previous_receipt else None
            ),
            "recent_decisions": [history_data(d) for d in context.recent_decisions],
            "attributed_user_answers": [asdict(a) for a in context.answers],
        }
        metadata_text = json.dumps(metadata, default=str, ensure_ascii=False)
        if len(metadata_text) > 100000:
            raise PortError("provider: context_limit")
        content = [{"type": "input_text", "text": metadata_text}]
        for image in context.images:
            o = image.observation
            content.extend(
                [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "observation_id": o.observation_id,
                                "width": o.width,
                                "height": o.height,
                                "rotation": o.rotation,
                                "captured_at": o.captured_at.isoformat(),
                            }
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            f"data:{o.screenshot.media_type};base64,"
                            + base64.b64encode(image.content).decode("ascii")
                        ),
                        "detail": "high",
                    },
                ]
            )
        request = {
            "model": self.model,
            "store": False,
            "instructions": self._instructions,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": INSTRUCTION_VERSION.replace("-", "_"),
                    "strict": True,
                    "schema": SCHEMA,
                }
            },
        }
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise PortError("provider: context_limit")
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                if self._transport is None:
                    response = await request_response(self._key, payload, timeout_ms)
                else:
                    # Explicit synchronous fakes only. Production owns a killable
                    # subprocess, never an uninterruptible default-executor job.
                    response = self._transport(self._key, payload, timeout_ms)
            if type(response) is not dict or response.get("status") != "completed":
                raise PortError("provider: incomplete_or_failed_response")
            texts = []
            for item in response["output"]:
                if item.get("type") != "message":
                    continue
                for part in item["content"]:
                    if part.get("type") == "refusal":
                        raise PortError("provider: refusal")
                    if part.get("type") == "output_text":
                        texts.append(part["text"])
            if len(texts) != 1 or len(texts[0]) > MAX_RESPONSE_BYTES:
                raise PortError("provider: missing_or_multiple_decisions")
            usage = response.get("usage") or {}
            decision = decode_decision(
                json.loads(texts[0]),
                context,
                ModelUsage(usage.get("input_tokens"), usage.get("output_tokens")),
            )
            return AgentReply(decision)
        except PortError:
            raise
        except TimeoutError:
            raise PortError("provider: timeout") from None
        except Exception:
            raise PortError("provider: malformed_response") from None
