"""Daily price snapshots: parsing, one snapshot per day and offline-safe refresh."""

import asyncio
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from visto.adapters.api.service import ExecutionService, WebSettings
from visto.adapters.pricing import PriceSheet, SQLitePriceStore, parse_prices
from visto.adapters.settings.store import Settings, SettingsStore
from visto.composition import create_app
from visto.home import VistoHome

DOCUMENT = {
    "lastUpdated": "2026-10-16T00:10:09.511Z",
    "models": [
        {
            "id": "fictional-1",
            "provider": "openai",
            "pricing": {"inputPerM": 0.1, "outputPerM": 0.5},
        },
        {
            "id": "fictional-2",
            "provider": "openai",
            "pricing": {"inputPerM": None, "outputPerM": 1},
        },
        {
            "id": "fictional-3",
            "provider": "openai",
            "pricing": {"inputPerM": True, "outputPerM": 1},
        },
        {"id": "other-1", "provider": "someone-else", "pricing": {"inputPerM": 1, "outputPerM": 2}},
        "not a model",
    ],
}


@pytest.fixture
def directory():
    root = Path(__file__).resolve().parents[2] / ".work" / ("pricing-test-" + uuid4().hex)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def test_parse_keeps_provider_models_with_numeric_base_rates():
    sheet = parse_prices(json.dumps(DOCUMENT).encode())
    assert sheet == PriceSheet("2026-10-16T00:10:09.511Z", {"fictional-1": (0.1, 0.5)})
    with pytest.raises(ValueError):
        parse_prices(b'{"models": []}')
    with pytest.raises(ValueError):
        parse_prices(b"[]")


def test_store_keeps_the_first_snapshot_of_each_day(directory):
    store = SQLitePriceStore(directory / "prices.sqlite3")
    day = date(2026, 10, 16)
    assert store.save(day, "t1", PriceSheet(None, {"m": (1, 2)}))
    assert not store.save(day, "t2", PriceSheet(None, {"m": (9, 9)}))
    assert store.save(date(2026, 10, 18), "t3", PriceSheet("u", {"m": (3, 4)}))
    history = store.history()
    assert history.at("m", date(2026, 10, 17))[0].input_per_m == 1
    assert history.at("m", date(2026, 10, 18)) == (history.latest()["m"], False)
    assert history.at("m", date(2026, 10, 1))[1] is True
    assert history.at("unknown", day) is None
    assert store.latest_snapshot() == {
        "day": "2026-10-18",
        "fetched_at": "t3",
        "source_updated_at": "u",
    }


class FixedClock:
    def __init__(self, now):
        self.value = now

    def now(self):
        return self.value

    def monotonic(self):
        return 0.0


def test_refresh_fetches_once_per_utc_day_and_reports_failures(directory):
    store = SettingsStore(VistoHome(directory / "home"))
    store.set_api_key("dummy-key")
    service = ExecutionService(
        WebSettings(directory, store, directory / "leases", models=("fictional-1",)),
    )
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 2:
            raise OSError("network down")
        return PriceSheet(None, {"fictional-1": (0.1, 0.5), "fictional-9": (1, 1)})

    async def scenario():
        await service.open()  # No fetcher yet: no background task.
        service.price_fetcher = fetch
        service.clock = FixedClock(datetime(2026, 10, 16, 23, tzinfo=UTC))
        assert await service.refresh_prices() is True
        assert await service.refresh_prices() is False  # Same day: no request.
        service.clock = FixedClock(datetime(2026, 10, 17, 1, tzinfo=UTC))
        assert await service.refresh_prices() is False
        assert service.price_error is not None
        assert await service.refresh_prices() is True
        assert service.price_error is None

    asyncio.run(scenario())
    assert len(calls) == 3

    with TestClient(create_app(service), base_url="http://localhost") as client:
        body = client.get("/api/prices").json()
    assert body["source"] == "AI Pricing Guru"
    assert body["snapshot"]["day"] == "2026-10-17"
    # Only operator-selectable models are listed.
    assert body["models"] == {
        "fictional-1": {"day": "2026-10-17", "input_per_m": 0.1, "output_per_m": 0.5}
    }


def test_price_refresh_switch_is_read_per_refresh(directory):
    store = SettingsStore(VistoHome(directory / "home"))
    store.save(Settings(price_refresh=False))
    service = ExecutionService(WebSettings(directory, store, directory / "leases"))
    calls = []

    def fetch():
        calls.append(1)
        return PriceSheet(None, {"fictional-1": (0.1, 0.5)})

    async def scenario():
        await service.open()
        service.price_fetcher = fetch
        service.clock = FixedClock(datetime(2026, 10, 16, 23, tzinfo=UTC))
        assert await service.refresh_prices() is False
        assert calls == []
        store.save(Settings(price_refresh=True))
        assert await service.refresh_prices() is True
        assert len(calls) == 1

    asyncio.run(scenario())
