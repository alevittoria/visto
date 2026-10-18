"""Fixed one-request HTTPS child. Never print credentials or raw exception details."""

import base64
import json
import secrets
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .transport import (
    AUDIO_EXTENSIONS,
    MAX_AUDIO_BYTES,
    MAX_INPUT_BYTES,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    TRANSCRIPTION_MODEL,
    safe_error,
)

RESPONSES_URL = "https://api.openai.com/v1/responses"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(request, *, timeout):
    # A fixed endpoint cannot delegate credentials/images through a redirect.
    # build_opener retains standard ProxyHandler and TLS verification.
    return build_opener(RejectRedirects()).open(request, timeout=timeout)


def network_error(error: OSError) -> str:
    """Classify typed failures only; messages may contain credentials or proxy URLs.

    https://docs.python.org/3.12/library/urllib.error.html#urllib.error.URLError.reason
    """
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, TimeoutError):
        return "provider: timeout"
    if isinstance(reason, ssl.SSLError):
        return "provider: tls_error"
    if isinstance(reason, socket.gaierror):
        return "provider: dns_error"
    if isinstance(reason, ConnectionRefusedError):
        return "provider: connection_refused"
    return "provider: connection_error"


def transcription_body(audio: bytes, media_type: str) -> tuple[bytes, str]:
    """Fixed multipart form: only the audio bytes come from the caller.

    https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create
    """
    boundary = "visto-" + secrets.token_hex(16)
    head = "".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        for name, value in (("model", TRANSCRIPTION_MODEL), ("response_format", "json"))
    )
    head += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="speech.{AUDIO_EXTENSIONS[media_type]}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    )
    body = head.encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def handle_packet(raw: bytes) -> dict:
    try:
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Input limit")
        packet = json.loads(raw)
        base = {"api_key", "payload", "timeout_ms"}
        if type(packet) is not dict or set(packet) not in (base, base | {"media_type"}):
            raise ValueError("Invalid packet")
        key, encoded, timeout = packet["api_key"], packet["payload"], packet["timeout_ms"]
        if (
            type(key) is not str
            or not key.strip()
            or len(key) > 8192
            or type(encoded) is not str
            or type(timeout) is not int
            or timeout < 1
        ):
            raise ValueError("Invalid fields")
        payload = base64.b64decode(encoded, validate=True)
        if not payload or len(payload) > MAX_REQUEST_BYTES:
            raise ValueError("Invalid payload")
        if "media_type" in packet:
            # Speech transcription: the payload is audio; the form is fixed here.
            media_type = packet["media_type"]
            if media_type not in AUDIO_EXTENSIONS or len(payload) > MAX_AUDIO_BYTES:
                raise ValueError("Invalid audio")
            url = TRANSCRIPTIONS_URL
            payload, content_type = transcription_body(payload, media_type)
        else:
            # Validate before any request; endpoint/headers are never provided by AI.
            if type(json.loads(payload)) is not dict:
                raise ValueError("Invalid request JSON")
            url, content_type = RESPONSES_URL, "application/json"
    except (OSError, ValueError, TypeError):
        return {"error": "provider: invalid_request"}
    try:
        request = Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
            method="POST",
        )
        # urllib's normal TLS and proxy handling is retained. The parent owns the
        # total deadline and forcibly terminates this process if it expires.
        with urlopen(request, timeout=timeout / 1000) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            return {"error": "provider: response_size_limit"}
        value = json.loads(content)
        if type(value) is not dict:
            raise ValueError("Invalid provider response")
        return {"response": value}
    except HTTPError as error:
        code = f"provider: http_{error.code}"
        error.close()
        return {"error": code if safe_error(code) else "provider: transport_or_json_error"}
    except OSError as error:
        return {"error": network_error(error)}
    except (ValueError, TypeError):
        return {"error": "provider: invalid_json"}


def main() -> None:
    try:
        result = handle_packet(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
        output = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(output) > MAX_RESPONSE_BYTES:
            output = b'{"error":"provider: response_size_limit"}'
    except Exception:
        output = b'{"error":"provider: transport_or_json_error"}'
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
