"""Opening the run database: a schema upgrade runs only while no other process uses the home.

Call :func:`prepare_data` after this process registered itself in the home, so two
processes starting together both see each other and neither upgrades.
"""

import sqlite3
from pathlib import Path

from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.adapters.storage.migrations import CURRENT_VERSION, schema_version
from visto.application.ports import PortError
from visto.home import VistoHome
from visto.instances import others

FAILED, BUSY = 3, 4


class DataUnavailable(ValueError):
    """The run database cannot be opened now; `code` is the exit code `visto start` uses."""

    def __init__(self, message: str, code: int = FAILED):
        super().__init__(message)
        self.code = code


def prepare_data(home: VistoHome, data_dir: Path) -> None:
    """Create or migrate `<data_dir>/runs.sqlite3`; raise DataUnavailable when it cannot."""
    database = data_dir / "runs.sqlite3"
    newer = (
        "This data was written by a newer Visto; install that version or restore a backup"
        f" from {data_dir}"
    )
    try:
        version = schema_version(database)
    except (OSError, sqlite3.Error):
        raise DataUnavailable("The local run database cannot be read") from None
    if version > CURRENT_VERSION:
        raise DataUnavailable(newer)
    # Creating a missing database is not an upgrade: migrate() serializes creation itself.
    if version < CURRENT_VERSION and database.exists() and others(home):
        raise DataUnavailable("Stop other Visto processes before upgrading data", BUSY)
    try:
        SQLiteRunStore(database, LocalArtifactStore(data_dir / "artifacts"))
    except PortError:
        try:
            too_new = schema_version(database) > CURRENT_VERSION
        except (OSError, sqlite3.Error):
            too_new = False
        raise DataUnavailable(newer if too_new else "Local data is unavailable") from None
