"""Settings routes: local files and fakes only; no provider or device contact."""

import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.api.settings import SettingsRoutesConfig
from visto.adapters.settings.store import SettingsStore
from visto.application.ports import PortError
from visto.composition import create_app
from visto.home import VistoHome

LOCAL = {"X-Visto": "local-console"}
IOS_BODY = {
    "team_id": "TEAM000000",
    "signing_id": "Example Signing",
    "wda_bundle_id": "example.wda.runner",
    "prebuilt_wda": False,
    "wda_derived_data": "",
}


@pytest.fixture
def home():
    root = Path(__file__).resolve().parents[2] / ".work" / ("settings-api-" + uuid4().hex)
    root.mkdir(parents=True)
    yield VistoHome(root)
    shutil.rmtree(root)


@pytest.fixture
def host():
    return SimpleNamespace(version="1.0.0", probes=[], outcome=None)


def make_client(home, host, *, ios):
    service = ExecutionService(WebSettings(home.data, SettingsStore(home), home.leases))

    async def prober(key, model, timeout_ms):
        host.probes.append((key, model, timeout_ms))
        if host.outcome is not None:
            raise PortError(host.outcome)
        return {"id": model}

    app = create_app(service)
    app.state.settings_host = SettingsRoutesConfig(
        ios_supported=ios,
        wda_project=lambda: home.root / "wda-project",
        xcuitest_version=lambda: host.version,
        prober=prober,
    )
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def client(home, host):
    with make_client(home, host, ios=False) as c:
        yield c


@pytest.fixture
def client_non_ios(client):
    return client


@pytest.fixture
def client_ios(home, host):
    with make_client(home, host, ios=True) as c:
        yield c


def test_key_is_write_only(client):
    r = client.put("/api/settings/key", json={"api_key": "sk-test-abcd9876"}, headers=LOCAL)
    assert r.json() == {"configured": True, "last4": "9876", "storage": "file"}
    for path in ("/api/settings", "/api/readiness"):
        assert "sk-test-abcd9876" not in client.get(path).text
    assert client.get("/api/settings").json()["key"]["last4"] == "9876"
    deleted = client.delete("/api/settings/key", headers=LOCAL)
    assert deleted.json() == {"configured": False, "last4": None, "storage": "file"}


def test_settings_writes_require_local_console(client):
    for call in (
        lambda **kw: client.put("/api/settings/key", json={"api_key": "sk-x"}, **kw),
        lambda **kw: client.delete("/api/settings/key", **kw),
        lambda **kw: client.put("/api/settings", json={"price_refresh": True}, **kw),
        lambda **kw: client.post("/api/settings/key/verify", **kw),
    ):
        assert call().status_code == 403
        assert call(headers={**LOCAL, "Origin": "http://evil.example"}).status_code == 403


def test_key_validation_error_never_echoes_value(client):
    r = client.put("/api/settings/key", json={"api_key": "sk bad SPACE"}, headers=LOCAL)
    assert r.status_code == 422 and "SPACE" not in r.text
    r = client.put("/api/settings/key", json={"api_key": 5, "extra": "SECRET"}, headers=LOCAL)
    assert r.status_code == 422 and "SECRET" not in r.text


def test_ios_hidden_and_rejected_off_mac(client_non_ios):
    body = client_non_ios.get("/api/settings").json()
    assert body["ios"] is None and body["ios_supported"] is False
    assert body["wda_project"] is None and body["wda_rebuild_needed"] is False
    r = client_non_ios.put(
        "/api/settings", json={"price_refresh": True, "ios": IOS_BODY}, headers=LOCAL
    )
    assert r.status_code == 422 and "not available" in r.json()["detail"]


def test_settings_roundtrip_and_strict_body(client_ios):
    r = client_ios.put(
        "/api/settings", json={"price_refresh": False, "ios": IOS_BODY}, headers=LOCAL
    )
    assert r.status_code == 200
    body = client_ios.get("/api/settings").json()
    assert body["price_refresh"] is False and body["ios"] == IOS_BODY
    assert body["wda_project"].endswith("wda-project")
    bad = client_ios.put("/api/settings", json={"price_refresh": True, "x": 1}, headers=LOCAL)
    assert bad.status_code == 422
    kept = client_ios.put("/api/settings", json={"price_refresh": True}, headers=LOCAL).json()
    assert kept["ios"] == IOS_BODY


def test_wda_rebuild_needed_after_driver_change(client_ios, host):
    client_ios.put("/api/settings", json={"price_refresh": True, "ios": IOS_BODY}, headers=LOCAL)
    assert client_ios.get("/api/settings").json()["wda_rebuild_needed"] is False
    host.version = "99.0.0"
    assert client_ios.get("/api/settings").json()["wda_rebuild_needed"] is True


def test_settings_read_reports_store_error(client, home):
    home.root.mkdir(parents=True, exist_ok=True)
    home.settings_file.write_text("{broken")
    r = client.get("/api/settings")
    assert r.status_code == 503 and "broken" not in r.text
    put = client.put("/api/settings", json={"price_refresh": True}, headers=LOCAL)
    assert put.status_code == 503


def test_verify_without_key_makes_no_probe(client, host):
    assert client.post("/api/settings/key/verify", headers=LOCAL).json() == {"result": "missing"}
    assert host.probes == []


@pytest.mark.parametrize(
    ("code", "result"),
    [
        (None, "ok"),
        ("provider: http_401", "unauthorized"),
        ("provider: http_404", "model_unavailable"),
        ("provider: timeout", "unreachable"),
        ("provider: http_500", "unreachable"),
    ],
)
def test_verify_maps_probe_outcomes(client, host, code, result):
    client.put("/api/settings/key", json={"api_key": "sk-test-abcd9876"}, headers=LOCAL)
    host.outcome = code
    r = client.post("/api/settings/key/verify", headers=LOCAL)
    assert r.json() == {"result": result}
    assert host.probes == [("sk-test-abcd9876", "gpt-6-luna", 10000)]
