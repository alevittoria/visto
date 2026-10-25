"""Dictated-goal transcription boundaries; no provider network operations."""

import asyncio
import base64
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from visto.adapters.ai import http_worker, transcription
from visto.adapters.ai.transport import MAX_AUDIO_BYTES, request_transcription
from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.settings.store import SettingsStore
from visto.application.ports import PortError
from visto.composition import create_app
from visto.home import VistoHome

HEADERS = {"X-Visto": "local-console", "Content-Type": "audio/webm;codecs=opus"}


@pytest.fixture
def directory():
    root = Path(__file__).resolve().parents[2] / ".work" / ("transcription-test-" + uuid4().hex)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def client_for(directory, transcriber, key="dummy-key"):
    store = SettingsStore(VistoHome(directory / "home"))
    if key:
        store.set_api_key(key)
    service = ExecutionService(
        WebSettings(directory, store, directory / "leases"),
        transcriber=transcriber,
    )
    return TestClient(create_app(service), base_url="http://localhost")


def test_endpoint_returns_transcript_for_normalized_media_type(directory):
    calls = []

    async def fake(key, audio, media_type):
        calls.append((key, audio, media_type))
        return "Open the fictional notes app and create a note"

    with client_for(directory, fake) as client:
        response = client.post("/api/transcriptions", headers=HEADERS, content=b"fake-audio")
    assert response.status_code == 200
    assert response.json() == {
        "text": "Open the fictional notes app and create a note",
        "model": "gpt-transcribe",
    }
    assert calls == [("dummy-key", b"fake-audio", "audio/webm")]


def test_endpoint_requires_local_write_guard(directory):
    async def fake(*_):
        pytest.fail("Provider must not be called")

    with client_for(directory, fake) as client:
        no_header = {"Content-Type": "audio/webm"}
        assert (
            client.post("/api/transcriptions", headers=no_header, content=b"x").status_code == 403
        )
        cross = {**HEADERS, "Origin": "https://evil.example"}
        assert client.post("/api/transcriptions", headers=cross, content=b"x").status_code == 403


@pytest.mark.parametrize(
    ("headers", "content", "key", "status"),
    [
        ({**HEADERS, "Content-Type": "audio/ogg"}, b"x", "dummy-key", 415),
        ({**HEADERS, "Content-Type": "application/json"}, b"{}", "dummy-key", 415),
        (HEADERS, b"", "dummy-key", 422),
        (HEADERS, b"x", "", 503),
        (HEADERS, b"x" * (MAX_AUDIO_BYTES + 1), "dummy-key", 413),
    ],
    ids=["ogg", "json", "empty", "no-key", "too-large"],
)
def test_endpoint_rejects_invalid_input_before_provider(directory, headers, content, key, status):
    async def fake(*_):
        pytest.fail("Provider must not be called")

    with client_for(directory, fake, key) as client:
        response = client.post("/api/transcriptions", headers=headers, content=content)
    assert response.status_code == status
    assert "dummy-key" not in response.text


def test_provider_failure_surfaces_only_sanitized_category(directory):
    async def fail(*_):
        raise PortError("provider: http_401")

    with client_for(directory, fail) as client:
        response = client.post("/api/transcriptions", headers=HEADERS, content=b"x")
    assert response.status_code == 502
    assert response.json() == {"detail": "Transcription failed (provider: http_401)"}


def test_concurrent_transcription_is_rejected(directory):
    store = SettingsStore(VistoHome(directory / "home"))
    store.set_api_key("dummy-key")
    service = ExecutionService(WebSettings(directory, store, directory / "leases"))
    release = asyncio.Event()

    async def slow(*_):
        await release.wait()
        return "done"

    service.transcriber = slow

    async def scenario():
        first = asyncio.create_task(service.transcribe(b"x", "audio/webm"))
        await asyncio.sleep(0)
        with pytest.raises(Exception) as error:
            await service.transcribe(b"x", "audio/webm")
        assert error.value.status_code == 429
        release.set()
        assert (await first)["text"] == "done"
        assert service.transcribing is False

    asyncio.run(scenario())


def test_adapter_accepts_only_bounded_text(monkeypatch):
    async def respond(value):
        async def fake(*_):
            return value

        monkeypatch.setattr(transcription, "request_transcription", fake)
        return await transcription.transcribe("dummy-key", b"x", "audio/webm")

    assert (
        asyncio.run(respond({"text": "  Tap the fictional button  "})) == "Tap the fictional button"
    )
    for value in ({}, {"text": 3}, {"text": "x" * 16001}):
        with pytest.raises(PortError, match="^provider: invalid_json$"):
            asyncio.run(respond(value))


def test_parent_rejects_unsupported_audio_without_spawning():
    def spawn(*_, **__):
        pytest.fail("Worker must not start")

    for audio, media_type in ((b"x", "audio/ogg"), (b"x" * (MAX_AUDIO_BYTES + 1), "audio/webm")):
        with pytest.raises(PortError, match="^provider: invalid_request$"):
            asyncio.run(request_transcription("dummy-key", audio, media_type, 1000, _spawn=spawn))


def packet(**extra):
    return json.dumps(
        {
            "api_key": "private-key",
            "payload": base64.b64encode(b"\x1a\x45\xdf\xa3fake-webm").decode(),
            "timeout_ms": 1000,
            **extra,
        }
    ).encode()


def test_worker_posts_fixed_multipart_form_to_transcription_endpoint(monkeypatch):
    sent = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _):
            return b'{"text":"Fictional transcript"}'

    def fake_urlopen(request, *, timeout):
        sent.append(request)
        return Reply()

    monkeypatch.setattr(http_worker, "urlopen", fake_urlopen)
    result = http_worker.handle_packet(packet(media_type="audio/webm"))
    assert result == {"response": {"text": "Fictional transcript"}}
    request = sent[0]
    assert request.full_url == "https://api.openai.com/v1/audio/transcriptions"
    assert request.get_header("Authorization") == "Bearer private-key"
    content_type = request.get_header("Content-type")
    assert content_type.startswith("multipart/form-data; boundary=visto-")
    body = request.data
    assert b'name="model"\r\n\r\ngpt-transcribe\r\n' in body
    assert b'name="response_format"\r\n\r\njson\r\n' in body
    assert (
        b'filename="speech.webm"\r\nContent-Type: audio/webm\r\n\r\n\x1a\x45\xdf\xa3fake-webm'
        in body
    )
    assert body.endswith(f"--{content_type.split('boundary=')[1]}--\r\n".encode())


@pytest.mark.parametrize("extra", [{"media_type": "audio/ogg"}, {"media_type": 1}, {"url": "x"}])
def test_worker_rejects_unknown_media_or_fields_without_network(monkeypatch, extra):
    monkeypatch.setattr(http_worker, "urlopen", lambda *_, **__: pytest.fail("No network"))
    assert http_worker.handle_packet(packet(**extra)) == {"error": "provider: invalid_request"}
