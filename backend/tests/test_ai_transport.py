"""Real local subprocess checks; no OpenAI or device calls."""

import asyncio
import base64
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import pytest

from visto.adapters.ai import http_worker
from visto.adapters.ai.transport import MAX_RESPONSE_BYTES, probe_model, request_response
from visto.application.ports import PortError


def local_worker(script):
    processes = []
    requested = []
    started = asyncio.Event()

    def spawn(args, **kwargs):
        requested.append((args, kwargs.copy()))
        process = subprocess.Popen([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        started.set()
        return process

    return spawn, processes, requested, started


def test_local_worker_receives_secret_only_on_stdin_with_fixed_hidden_invocation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    script = (
        "import base64,json,sys; packet=json.load(sys.stdin); "
        "assert packet['api_key']=='private-key'; "
        "assert base64.b64decode(packet['payload'])==b'{\"model\":\"fake\"}'; "
        "print(json.dumps({'response':{'status':'completed','output':[]}}))"
    )

    async def scenario():
        spawn, processes, requested, _ = local_worker(script)
        result = await request_response("private-key", b'{"model":"fake"}', 3000, _spawn=spawn)
        assert result == {"status": "completed", "output": []}
        args, kwargs = requested[0]
        assert args == [sys.executable, "-m", "visto.adapters.ai.http_worker"]
        assert "private-key" not in repr((args, kwargs))
        assert "shell" not in kwargs
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["HTTPS_PROXY"] == "http://proxy.example:8080"
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert processes[0].returncode == 0

    asyncio.run(scenario())


def test_timeout_kills_reaps_worker_and_prevents_late_response():
    script = "import sys,time; sys.stdin.buffer.read(); time.sleep(10); print('{\"response\":{}}')"

    async def scenario():
        spawn, processes, _, _ = local_worker(script)
        with pytest.raises(PortError, match="^provider: timeout$"):
            await request_response("private-key", b"{}", 200, _spawn=spawn)
        assert len(processes) == 1 and processes[0].returncode is not None
        assert processes[0].returncode != 0

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 3  # Includes asyncio executor shutdown.


def test_cancellation_kills_reaps_worker_and_propagates_cancelled_error():
    script = "import sys,time; sys.stdin.buffer.read(); time.sleep(10)"

    async def scenario():
        spawn, processes, _, entered = local_worker(script)
        task = asyncio.create_task(request_response("private-key", b"{}", 10000, _spawn=spawn))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert len(processes) == 1 and processes[0].returncode is not None
        assert processes[0].returncode != 0

    asyncio.run(scenario())


def test_oversized_worker_output_is_bounded_and_worker_reaped():
    script = (
        "import sys; sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write(b'x'*{MAX_RESPONSE_BYTES + 1}); sys.stdout.flush(); "
    )

    async def scenario():
        spawn, processes, _, _ = local_worker(script)
        with pytest.raises(PortError, match="^provider: response_size_limit$"):
            await request_response("private-key", b"{}", 3000, _spawn=spawn)
        assert processes[0].returncode is not None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "envelope",
    [
        "not JSON private-key",
        '{"error":"secret private-key"}',
        '{"response":{},"error":"provider: http_401"}',
        '{"response":[]}',
    ],
)
def test_malformed_or_unknown_worker_error_is_sanitized(envelope):
    script = f"import sys; sys.stdin.buffer.read(); print({envelope!r})"

    async def scenario():
        spawn, processes, _, _ = local_worker(script)
        with pytest.raises(PortError) as error:
            await request_response("private-key", b"{}", 3000, _spawn=spawn)
        assert "private-key" not in str(error.value)
        assert processes[0].returncode is not None

    asyncio.run(scenario())


def test_known_worker_http_error_surfaces_only_code():
    async def scenario():
        spawn, processes, _, _ = local_worker(
            'import sys; sys.stdin.buffer.read(); print(\'{"error":"provider: http_401"}\')'
        )
        with pytest.raises(PortError, match="^provider: http_401$"):
            await request_response("private-key", b"{}", 3000, _spawn=spawn)
        assert processes[0].returncode == 0

    asyncio.run(scenario())


def test_worker_http_failure_does_not_return_secret_response_body(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError("https://api.openai.com/v1/responses", 401, "private-key", {}, None)

    monkeypatch.setattr(http_worker, "urlopen", fail)
    packet = {
        "api_key": "private-key",
        "payload": base64.b64encode(b"{}").decode(),
        "timeout_ms": 1000,
    }
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {"error": "provider: http_401"}


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (URLError(ConnectionRefusedError(10061, "private proxy/key")), "connection_refused"),
        (URLError(socket.gaierror(-2, "private hostname/key")), "dns_error"),
        (URLError(ssl.SSLCertVerificationError("private certificate/key")), "tls_error"),
        (URLError(TimeoutError("private proxy/key")), "timeout"),
        (TimeoutError("private proxy/key"), "timeout"),
        (URLError("private proxy/key"), "connection_error"),
        (OSError("private hostname/key"), "connection_error"),
    ],
)
def test_worker_classifies_network_failure_without_disclosing_details(monkeypatch, failure, code):
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise failure

    monkeypatch.setattr(http_worker, "urlopen", fail)
    packet = {
        "api_key": "private-key",
        "payload": base64.b64encode(b"{}").decode(),
        "timeout_ms": 1000,
    }
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {"error": f"provider: {code}"}
    assert len(calls) == 1


def test_worker_classifies_invalid_response_json_without_disclosing_body(monkeypatch):
    monkeypatch.setattr(http_worker, "urlopen", lambda *a, **kw: BytesIO(b"private body/key"))
    packet = {
        "api_key": "private-key",
        "payload": base64.b64encode(b"{}").decode(),
        "timeout_ms": 1000,
    }
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {
        "error": "provider: invalid_json"
    }


@pytest.mark.parametrize(
    "code",
    [
        "connection_refused",
        "dns_error",
        "tls_error",
        "connection_error",
        "invalid_json",
        "invalid_request",
        "worker_start_error",
        "worker_protocol_error",
        "timeout",
    ],
)
def test_parent_preserves_only_known_sanitized_diagnostic_codes(code):
    async def scenario():
        envelope = json.dumps({"error": f"provider: {code}"})
        spawn, processes, _, _ = local_worker(
            f"import sys; sys.stdin.buffer.read(); print({envelope!r})"
        )
        with pytest.raises(PortError) as error:
            await request_response("private-key", b"{}", 3000, _spawn=spawn)
        assert str(error.value) == f"provider: {code}"
        assert processes[0].returncode == 0

    asyncio.run(scenario())


def test_fixed_worker_rejects_malformed_stdin_without_network():
    async def scenario():
        processes = []

        def production_spawn(args, **kwargs):
            process = subprocess.Popen(args, **kwargs)
            processes.append(process)
            return process

        # Exercise default Popen/module/STDIN production path. Malformed request
        # JSON is rejected inside the child before HTTPS can be performed.
        with pytest.raises(PortError, match="^provider: invalid_request$"):
            await request_response(
                "private-key", b"invalid private-key", 3000, _spawn=production_spawn
            )
        assert len(processes) == 1 and processes[0].returncode == 0

    asyncio.run(scenario())


def test_launch_failure_is_sanitized():
    def fail(*args, **kwargs):
        raise OSError("private-key failed to launch")

    with pytest.raises(PortError, match="^provider: worker_start_error$"):
        asyncio.run(request_response("private-key", b"{}", 1000, _spawn=fail))


def test_expired_startup_kills_child_without_sending_request_packet():
    processes = []

    def slow_spawn(args, **kwargs):
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(10)"],
            **kwargs,
        )
        processes.append(process)
        time.sleep(0.03)
        return process

    with pytest.raises(PortError, match="^provider: timeout$"):
        asyncio.run(request_response("private-key", b"{}", 1, _spawn=slow_spawn))
    assert processes[0].returncode is not None and processes[0].returncode != 0


def test_redirect_response_cannot_forward_credentials_or_images(monkeypatch):
    opener = build_opener(http_worker.RejectRedirects())
    monkeypatch.setattr(
        opener, "open", lambda *args, **kwargs: pytest.fail("Redirect was followed")
    )
    headers = Message()
    headers["Location"] = "https://untrusted.invalid/collect"
    request = Request(
        "https://api.openai.com/v1/responses",
        data=b"private screenshot",
        headers={"Authorization": "Bearer private-key"},
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        opener.error("https", request, BytesIO(), 302, "Found", headers)
    assert error.value.code == 302
    error.value.close()


def test_worker_probe_uses_fixed_get(monkeypatch):
    seen = []

    def fake(request, *, timeout):
        seen.append(request)
        return BytesIO(b'{"id":"gpt-6-luna"}')

    monkeypatch.setattr(http_worker, "urlopen", fake)
    packet = {"api_key": "k", "probe_model": "gpt-6-luna", "timeout_ms": 1000}
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {
        "response": {"id": "gpt-6-luna"}
    }
    request = seen[0]
    assert request.full_url == "https://api.openai.com/v1/models/gpt-6-luna"
    assert request.get_method() == "GET" and request.data is None
    assert request.get_header("Authorization") == "Bearer k"


@pytest.mark.parametrize("model", ["../v1/responses", "a/b", "a b", "", "x" * 129, 5, "m?x=1"])
def test_worker_probe_rejects_invalid_model_before_request(monkeypatch, model):
    calls = []
    monkeypatch.setattr(http_worker, "urlopen", lambda *a, **kw: calls.append(a))
    packet = {"api_key": "k", "probe_model": model, "timeout_ms": 1000}
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {
        "error": "provider: invalid_request"
    }
    assert calls == []


def test_worker_probe_packet_rejects_extra_fields(monkeypatch):
    monkeypatch.setattr(http_worker, "urlopen", lambda *a, **kw: pytest.fail("request"))
    packet = {"api_key": "k", "probe_model": "m", "timeout_ms": 1000, "payload": "e30="}
    assert http_worker.handle_packet(json.dumps(packet).encode()) == {
        "error": "provider: invalid_request"
    }


def test_parent_probe_sends_no_payload_and_validates_model():
    script = (
        "import json,sys; p=json.load(sys.stdin); "
        "assert set(p)=={'api_key','probe_model','timeout_ms'} and p['probe_model']=='gpt-6-luna'; "
        "print(json.dumps({'response':{'id':'gpt-6-luna'}}))"
    )

    async def scenario():
        spawn, _, _, _ = local_worker(script)
        assert await probe_model("k", "gpt-6-luna", 3000, _spawn=spawn) == {"id": "gpt-6-luna"}
        with pytest.raises(PortError, match="^provider: invalid_request$"):
            await probe_model("k", "../bad", 3000, _spawn=spawn)

    asyncio.run(scenario())
