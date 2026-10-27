"""The bootstrap API must not imply that Android execution is ready."""

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.settings.store import SettingsStore
from visto.composition import create_app
from visto.home import VistoHome


def test_health_reports_service_identity_without_claiming_runtime_readiness() -> None:
    # Isolated workspace: health never reads personal credentials or real history.
    root = Path(__file__).resolve().parents[2] / ".work" / ("health-test-" + uuid4().hex)
    root.mkdir(parents=True)
    service = ExecutionService(
        WebSettings(root, SettingsStore(VistoHome(root / "home")), root / "leases")
    )
    try:
        with TestClient(create_app(service), base_url="http://localhost") as client:
            response = client.get("/api/health")
    finally:
        shutil.rmtree(root)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "product": "Visto",
        "version": "0.3.0",
        "runtime_ready": False,
    }
