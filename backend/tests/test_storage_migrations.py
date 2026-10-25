import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visto.adapters.storage.migrations import (
    CURRENT_VERSION,
    MigrationMissing,
    SchemaTooNew,
    migrate,
    schema_version,
)

FIXED = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)


def make_v1_database_with_one_run(tmp_path: Path) -> Path:
    db = tmp_path / "runs.sqlite3"
    migrate(db)
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO runs VALUES ('r1', '{}')")
    return db


def run_count(db: Path) -> int:
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def failing_step(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE half (x)")
    connection.execute("INSERT INTO missing_table VALUES (1)")


def test_fresh_database_created_at_current(tmp_path):
    db = tmp_path / "runs.sqlite3"
    assert migrate(db) is None
    assert schema_version(db) == CURRENT_VERSION
    assert list(tmp_path.glob("*.bak")) == []


def test_missing_database_has_version_zero_and_is_not_created(tmp_path):
    assert schema_version(tmp_path / "runs.sqlite3") == 0
    assert not (tmp_path / "runs.sqlite3").exists()


def test_current_database_is_not_backed_up(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    assert migrate(db) is None
    assert list(tmp_path.glob("*.bak")) == []


def test_existing_database_backed_up_before_migration(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    steps = {2: lambda c: c.execute("CREATE TABLE extra (x)")}
    backup = migrate(db, migrations=steps, current=2, now=lambda: FIXED)
    assert backup is not None
    assert backup.name == "runs.sqlite3.v1-20261025T120000Z.bak"
    assert schema_version(backup) == 1 and schema_version(db) == 2
    assert run_count(backup) == 1


def test_existing_backup_is_never_overwritten(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    existing = tmp_path / "runs.sqlite3.v1-20261025T120000Z.bak"
    existing.write_bytes(b"earlier backup")
    steps = {2: lambda c: c.execute("CREATE TABLE extra (x)")}
    with pytest.raises(FileExistsError):
        migrate(db, migrations=steps, current=2, now=lambda: FIXED)
    assert existing.read_bytes() == b"earlier backup" and schema_version(db) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_new_database_directory_and_backup_are_owner_only(tmp_path):
    db = tmp_path / "data" / "runs.sqlite3"
    migrate(db)
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    steps = {2: lambda c: c.execute("CREATE TABLE extra (x)")}
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO runs VALUES ('r1', '{}')")
    backup = migrate(db, migrations=steps, current=2, now=lambda: FIXED)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_existing_database_keeps_its_mode(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    db.chmod(0o640)
    migrate(db, migrations={2: lambda c: None}, current=2, now=lambda: FIXED)
    assert stat.S_IMODE(db.stat().st_mode) == 0o640


def test_failed_migration_leaves_database_unchanged(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    with pytest.raises(sqlite3.Error):
        migrate(db, migrations={2: failing_step}, current=2, now=lambda: FIXED)
    assert schema_version(db) == 1 and run_count(db) == 1
    with sqlite3.connect(db) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}
    assert "half" not in tables


def test_newer_database_refused(tmp_path):
    db = tmp_path / "runs.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA user_version=7")
    with pytest.raises(SchemaTooNew):
        migrate(db)
    assert schema_version(db) == 7 and list(tmp_path.glob("*.bak")) == []


def test_missing_step_is_refused_without_bumping_the_version(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    with pytest.raises(MigrationMissing):
        migrate(db, migrations={3: lambda c: None}, current=3, now=lambda: FIXED)
    assert schema_version(db) == 1 and list(tmp_path.glob("*.bak")) == []


def test_version_is_read_again_inside_the_migration_transaction(tmp_path):
    db = make_v1_database_with_one_run(tmp_path)
    applied = []

    def other_process_migrates_first():
        # Runs after the first version read: another process applies step 2 meanwhile.
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE extra (x)")
            connection.execute("PRAGMA user_version=2")
        return FIXED

    steps = {2: lambda c: applied.append(2) or c.execute("CREATE TABLE extra (x)")}
    migrate(db, migrations=steps, current=2, now=other_process_migrates_first)
    assert applied == [] and schema_version(db) == 2
