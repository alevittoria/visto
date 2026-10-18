"""One immutable price snapshot per UTC day, so old runs keep their day's prices."""

import sqlite3
from bisect import bisect_right
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .aipricing import PriceSheet


@dataclass(frozen=True, slots=True)
class ModelPrice:
    day: date
    input_per_m: float
    output_per_m: float


class PriceHistory:
    def __init__(self, rows: dict[str, list[ModelPrice]]):
        self.rows = {
            model: sorted(items, key=lambda item: item.day) for model, items in rows.items()
        }

    def at(self, model: str, day: date) -> tuple[ModelPrice, bool] | None:
        """Snapshot in effect on `day`; else the earliest one, flagged as approximate."""
        items = self.rows.get(model)
        if not items:
            return None
        index = bisect_right([item.day for item in items], day)
        return (items[index - 1], False) if index else (items[0], True)

    def latest(self) -> dict[str, ModelPrice]:
        return {model: items[-1] for model, items in self.rows.items()}


class SQLitePriceStore:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS snapshots (day TEXT PRIMARY KEY, "
                "fetched_at TEXT NOT NULL, source_updated_at TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS prices (day TEXT NOT NULL REFERENCES snapshots(day), "
                "model TEXT NOT NULL, input_per_m REAL NOT NULL, output_per_m REAL NOT NULL, "
                "PRIMARY KEY (day, model))"
            )

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=5)
        return _Transaction(connection)

    def has(self, day: date) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM snapshots WHERE day=?", (day.isoformat(),))
            return row.fetchone() is not None

    def save(self, day: date, fetched_at: str, sheet: PriceSheet) -> bool:
        """First snapshot of a day wins; returns False when the day already exists."""
        with self._connect() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?)",
                (day.isoformat(), fetched_at, sheet.source_updated_at),
            ).rowcount
            if inserted:
                connection.executemany(
                    "INSERT INTO prices VALUES (?, ?, ?, ?)",
                    [(day.isoformat(), model, *rates) for model, rates in sheet.prices.items()],
                )
            return bool(inserted)

    def latest_snapshot(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT day, fetched_at, source_updated_at FROM snapshots ORDER BY day DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {"day": row[0], "fetched_at": row[1], "source_updated_at": row[2]}

    def history(self) -> PriceHistory:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT model, day, input_per_m, output_per_m FROM prices"
            ).fetchall()
        result: dict[str, list[ModelPrice]] = {}
        for model, day, input_per_m, output_per_m in rows:
            result.setdefault(model, []).append(
                ModelPrice(date.fromisoformat(day), input_per_m, output_per_m)
            )
        return PriceHistory(result)


class _Transaction:
    """Commit on success, roll back on error, always close."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, kind, *_):
        with closing(self.connection):
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
