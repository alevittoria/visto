"""Public AI Pricing Guru dataset: one fixed unauthenticated GET, no redirects.

Terms allow internal use with attribution (see docs/references.md). Rates are USD
per one million tokens, scraped daily by the source from provider price pages.
"""

import json
import math
import urllib.request
from dataclasses import dataclass

SOURCE_NAME = "AI Pricing Guru"
SOURCE_URL = "https://www.aipricing.guru/api/pricing.json"
ATTRIBUTION = "Prices: AI Pricing Guru (aipricing.guru), verify with the provider before budgeting."
PROVIDER = "openai"
MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PriceSheet:
    source_updated_at: str | None
    # model id -> (input USD per 1M tokens, output USD per 1M tokens)
    prices: dict[str, tuple[float, float]]


def _rate(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 100_000 else None


def parse_prices(content: bytes) -> PriceSheet:
    """Keeps base input/output rates of the provider adapter's models only."""
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Unexpected pricing document")
    prices = {}
    for model in data["models"]:
        if not isinstance(model, dict) or model.get("provider") != PROVIDER:
            continue
        identifier, pricing = model.get("id"), model.get("pricing")
        if not isinstance(identifier, str) or not identifier or not isinstance(pricing, dict):
            continue
        rates = _rate(pricing.get("inputPerM")), _rate(pricing.get("outputPerM"))
        if None not in rates:
            prices[identifier[:128]] = rates
    if not prices:
        raise ValueError("Pricing document lists no usable models")
    updated = data.get("lastUpdated")
    return PriceSheet(updated[:64] if isinstance(updated, str) else None, prices)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_prices(timeout_s: float = 20) -> PriceSheet:
    """Blocking; run it in a worker thread. Raises OSError/ValueError on any failure."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        SOURCE_URL, headers={"Accept": "application/json", "User-Agent": "visto"}
    )
    with opener.open(request, timeout=timeout_s) as response:
        if response.status != 200:
            raise ValueError("Unexpected pricing response status")
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Pricing document too large")
    return parse_prices(content)
