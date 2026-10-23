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

from visto.adapters.devices import Platform
from visto.application.context import AgentContext, AgentReply
from visto.application.ports import PortError
from visto.domain.models import ModelUsage

from .imaging import Scale, present, presented_history, presented_size
from .schema import SCHEMA, decode_decision
from .transport import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, request_response

INSTRUCTION_VERSIONS = {
    Platform.ANDROID: "android-agent-v3",
    Platform.IOS: "ios-agent-v1",
}
PLATFORM_NOTES_MARKER = "\n<!-- platform notes -->\n"
PLATFORM_NAMES = {Platform.ANDROID: "Android", Platform.IOS: "iOS"}
INSTRUCTION_VERSION = INSTRUCTION_VERSIONS[Platform.ANDROID]


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


def _prompt(name: str) -> str:
    packaged = files("visto").joinpath(f"prompts/{name}")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    # Source-tree execution; wheels contain the resource at the path above.
    return (Path(__file__).resolve().parents[4] / "prompts" / name).read_text(encoding="utf-8")


def load_instructions(platform: Platform = Platform.ANDROID) -> str:
    """Render the shared core with one platform's notes; unknown platforms fail loudly."""
    version = INSTRUCTION_VERSIONS[platform]
    # A platform file holds the type_text semantics, the marker line, then the notes.
    type_text, marker, notes = _prompt(f"{version}.md").partition(PLATFORM_NOTES_MARKER)
    if not marker:
        raise ValueError(f"{version}.md is missing the platform notes marker")
    return (
        _prompt("agent-core.md")
        .replace("{{PLATFORM}}", PLATFORM_NAMES[platform])
        .replace("{{TYPE_TEXT_SEMANTICS}}", type_text)
        .replace("{{PLATFORM_NOTES}}", notes)
    )


class OpenAIAgent:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-6-sol",
        *,
        platform: Platform = Platform.ANDROID,
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
        self.platform = platform
        self._instructions = load_instructions(platform)

    async def decide(self, context: AgentContext, timeout_ms: int) -> AgentReply:
        identity = context.run.configuration.identity
        if (identity.provider, identity.model, identity.instruction_version) != (
            "openai",
            self.model,
            INSTRUCTION_VERSIONS[self.platform],
        ):
            raise PortError("provider: identity_mismatch")
        if type(timeout_ms) is not int or timeout_ms < 1:
            raise ValueError("Invalid inference timeout")
        if len(context.images) > 8 or len(context.recent_decisions) > 20:
            raise PortError("provider: context_limit")
        scales = {}
        for image in context.images:
            o = image.observation
            source = (o.width, o.height)
            scales[o.observation_id] = Scale(source, presented_size(*source))
        current = scales[context.current_observation_id]
        metadata = {
            "original_goal": asdict(context.run.goal),
            "configuration": asdict(context.run.configuration),
            "current_observation_id": context.current_observation_id,
            "working_plan": context.working_plan,
            "previous_action": history_data(
                presented_history(context.previous_action, scales, current)
            ),
            "previous_receipt": (
                asdict(context.previous_receipt) if context.previous_receipt else None
            ),
            "recent_decisions": [
                history_data(presented_history(d, scales, current))
                for d in context.recent_decisions
            ],
            "attributed_user_answers": [asdict(a) for a in context.answers],
        }
        metadata_text = json.dumps(metadata, default=str, ensure_ascii=False)
        if len(metadata_text) > 100000:
            raise PortError("provider: context_limit")
        content = [{"type": "input_text", "text": metadata_text}]
        for image in context.images:
            o = image.observation
            scale = scales[o.observation_id]
            media_type, data = o.screenshot.media_type, image.content
            if scale.presented != scale.source:
                try:
                    media_type, data = "image/png", present(data, scale.presented)
                except Exception:
                    raise PortError("provider: unreadable_screenshot") from None
            width, height = scale.presented
            content.extend(
                [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "observation_id": o.observation_id,
                                "width": width,
                                "height": height,
                                "rotation": o.rotation,
                                "captured_at": o.captured_at.isoformat(),
                            }
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            f"data:{media_type};base64," + base64.b64encode(data).decode("ascii")
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
                    "name": INSTRUCTION_VERSIONS[self.platform].replace("-", "_"),
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
                current.to_source,
            )
            return AgentReply(decision)
        except PortError:
            raise
        except TimeoutError:
            raise PortError("provider: timeout") from None
        except Exception:
            raise PortError("provider: malformed_response") from None
