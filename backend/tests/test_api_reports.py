"""Report HTTP integration uses the same persisted fake runs, never a real device."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_api import BODY, HEADERS, eventually, make_service, real_local_service

from visto.composition import create_app


@pytest.fixture
def directory():
    root = Path(__file__).resolve().parents[2] / ".work" / ("api-report-test-" + uuid4().hex)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def test_report_downloads_preserve_outcome_and_escape_text(directory):
    with TestClient(create_app(make_service(directory)), base_url="http://localhost") as client:
        goal = '<script>alert("private text")</script>'
        run_id = client.post("/api/runs", headers=HEADERS, json={**BODY, "goal": goal}).json()[
            "run_id"
        ]
        eventually(client, run_id, "running")
        partial = client.get(f"/api/runs/{run_id}/report.json")
        assert partial.json()["outcome"] == "running"
        assert partial.json()["reported_usage"]["input_tokens"] is None
        client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS)
        eventually(client, run_id, "terminal")
        report = client.get(f"/api/runs/{run_id}/report.json")
        assert report.status_code == 200
        assert report.json()["outcome"] == "cancelled"
        assert report.json()["run"]["goal"]["text"] == goal
        assert report.headers["content-disposition"].startswith("attachment;")
        assert report.headers["cache-control"] == "no-store"
        html = client.get(f"/api/runs/{run_id}/report.html")
        assert html.status_code == 200
        assert html.headers["content-type"].startswith("text/html")
        assert html.headers["content-disposition"].startswith("inline;")
        assert "default-src 'none'" in html.headers["content-security-policy"]
        assert "<script>" not in html.text and "&lt;script&gt;" in html.text
        assert "dummy-key" not in html.text and "storage_key" not in html.text
        assert client.get("/api/runs/missing/report.html").status_code == 404


def test_report_screenshot_links_use_integrity_checked_scoped_api(directory):
    service, _, _ = real_local_service(directory)
    with TestClient(create_app(service), base_url="http://localhost") as client:
        run_id = client.post("/api/runs", headers=HEADERS, json=BODY).json()["run_id"]
        eventually(client, run_id, "waiting_for_user")
        report = client.get(f"/api/runs/{run_id}/report.json").json()
        screenshot = report["history"][0]["screenshot"]
        assert "storage_key" not in screenshot
        assert client.get(screenshot["url"]).content == b"local-image-1"
        html = client.get(f"/api/runs/{run_id}/report.html").text
        assert f'href="{screenshot["url"]}"' in html
        assert "<img" not in html
