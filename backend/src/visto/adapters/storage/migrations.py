"""Numbered forward SQLite migrations with a backup before changing existing data."""

import os
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from visto.home import make_private_dir

Migration = Callable[[sqlite3.Connection], None]


class SchemaTooNew(ValueError):
    """The database was written by a newer Visto than this one."""


class MigrationMissing(ValueError):
    """No migration step leads to a required schema version."""


def _create_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS records ("
        "position INTEGER PRIMARY KEY, run_id TEXT NOT NULL "
        "REFERENCES runs(run_id), kind TEXT NOT NULL, "
        "record_id TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(run_id, kind, record_id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS terminals ("
        "run_id TEXT PRIMARY KEY REFERENCES runs(run_id), "
        "payload TEXT NOT NULL)"
    )


CURRENT_VERSION = 1
MIGRATIONS: dict[int, Migration] = {1: _create_v1}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def schema_version(database: Path) -> int:
    """Return the stored schema version; 0 when the file is missing. Read-only."""
    path = Path(database)
    if not path.exists():
        return 0
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _has_tables(database: Path) -> bool:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        return connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None
    finally:
        connection.close()


def _create_private(path: Path) -> None:
    """Create an empty owner-only file; raise FileExistsError when it already exists."""
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))


def _backup(database: Path, version: int, moment: datetime) -> Path:
    stamp = moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = database.with_name(f"{database.name}.v{version}-{stamp}.bak")
    # Owner-only before SQLite writes; never reuse or overwrite an existing backup.
    _create_private(target)
    source = destination = None
    try:
        source = sqlite3.connect(database, timeout=5)
        destination = sqlite3.connect(target)
        source.backup(destination)
    except BaseException:
        if destination is not None:
            destination.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        for connection in (source, destination):
            if connection is not None:
                connection.close()
    return target


def migrate(
    database: Path,
    *,
    migrations: Mapping[int, Migration] = MIGRATIONS,
    current: int = CURRENT_VERSION,
    now: Callable[[], datetime] = _utc_now,
) -> Path | None:
    """Bring the database to `current`; return the backup path when one was made."""
    database = Path(database)
    make_private_dir(database.parent)
    version = schema_version(database)
    if version > current:
        raise SchemaTooNew("database is newer than this Visto")
    missing = [target for target in range(version + 1, current + 1) if target not in migrations]
    if missing:
        raise MigrationMissing(f"no migration to schema version {missing[0]}")
    backup: Path | None = None
    if version < current and database.exists() and (version > 0 or _has_tables(database)):
        backup = _backup(database, version, now())
    if not database.exists():
        # A new database starts owner-only; existing files keep the user's mode.
        try:
            _create_private(database)
        except FileExistsError:
            pass  # Another process created it first.
    connection = sqlite3.connect(database, timeout=5, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        while True:
            connection.execute("BEGIN IMMEDIATE")
            try:
                # Read again under the write lock: another process may have migrated.
                found = connection.execute("PRAGMA user_version").fetchone()[0]
                if found > current:
                    raise SchemaTooNew("database is newer than this Visto")
                if found == current:
                    connection.execute("COMMIT")
                    break
                step = migrations.get(found + 1)
                if step is None:
                    raise MigrationMissing(f"no migration to schema version {found + 1}")
                step(connection)
                connection.execute(f"PRAGMA user_version={int(found + 1)}")
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
    finally:
        connection.close()
    return backup
