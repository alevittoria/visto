import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from visto.home import VistoHome
from visto.instances import Busy, exclusive, others, registered


def write_entry(home: VistoHome, *, pid: int, kind: str) -> None:
    home.instances.mkdir(parents=True, exist_ok=True)
    (home.instances / f"{pid}.json").write_text(
        json.dumps({"pid": pid, "kind": kind, "started_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_registration_visible_to_others(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    with registered(home, "start"):
        write_entry(home, pid=os.getppid(), kind="run")
        assert [i.kind for i in others(home)] == ["run"]
    assert not (home.instances / f"{os.getpid()}.json").exists()


def test_dead_entries_are_cleared(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    write_entry(home, pid=dead_pid(), kind="start")
    assert others(home) == []
    assert list(home.instances.glob("*.json")) == []


def test_corrupt_entries_are_cleared(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    home.instances.mkdir(parents=True)
    (home.instances / "123.json").write_text("{not json", encoding="utf-8")
    (home.instances / "456.json").write_bytes(b"\xff\xfe\x00")
    assert others(home) == []
    assert list(home.instances.glob("*.json")) == []


def test_others_without_directory(tmp_path: Path) -> None:
    assert others(VistoHome(tmp_path)) == []


def test_exclusive_refuses_when_busy(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    write_entry(home, pid=os.getppid(), kind="start")
    with pytest.raises(Busy), exclusive(home, "setup"):
        pass


def test_exclusive_registers_while_held(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    with exclusive(home, "setup"):
        assert (home.instances / f"{os.getpid()}.json").exists()
    assert not (home.instances / f"{os.getpid()}.json").exists()


def test_stale_device_leases_do_not_block(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    home.leases.mkdir(parents=True)
    (home.leases / "x.lease").write_text("{}")
    with exclusive(home, "setup"):
        pass


@pytest.mark.parametrize("raw_pid", ["Infinity", str(10**30), "0", "-5"])
def test_out_of_range_pids_are_stale(tmp_path: Path, raw_pid: str) -> None:
    home = VistoHome(tmp_path)
    home.instances.mkdir(parents=True)
    (home.instances / "9.json").write_text(
        '{"pid": ' + raw_pid + ', "kind": "start", "started_at": "x"}', encoding="utf-8"
    )
    assert others(home) == []
    assert list(home.instances.glob("*.json")) == []


def test_undeletable_entry_does_not_crash(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    (home.instances / "dir.json").mkdir(parents=True)
    assert others(home) == []


def test_exclusive_unregisters_when_busy(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    write_entry(home, pid=os.getppid(), kind="start")
    with pytest.raises(Busy), exclusive(home, "setup"):
        pass
    assert not (home.instances / f"{os.getpid()}.json").exists()


def test_nested_exclusive_keeps_outer_registration(tmp_path: Path) -> None:
    home = VistoHome(tmp_path)
    entry = home.instances / f"{os.getpid()}.json"
    with registered(home, "start"):
        with exclusive(home, "setup"):
            assert json.loads(entry.read_text(encoding="utf-8"))["kind"] == "start"
        assert entry.exists()
    assert not entry.exists()
