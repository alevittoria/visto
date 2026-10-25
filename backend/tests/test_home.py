import os
import stat
from pathlib import Path

import pytest

from visto.home import VistoHome, default_home, make_private_dir


def test_home_layout(tmp_path):
    home = VistoHome(tmp_path)
    assert home.data == tmp_path / "data"
    assert home.leases == tmp_path / "data" / "device-leases"
    assert home.settings_file == tmp_path / "settings.json"
    assert home.secrets_file == tmp_path / "secrets.json"
    assert home.toolchain == tmp_path / "toolchain"
    assert home.instances == tmp_path / "instances"
    assert home.logs == tmp_path / "logs"


def test_default_home_is_user_dot_visto(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_home().root == tmp_path / ".visto"


def test_make_private_dir_creates_missing_parents_and_keeps_existing(tmp_path):
    target = tmp_path / "a" / "b"
    make_private_dir(target)
    make_private_dir(target)
    assert target.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_make_private_dir_is_owner_only_only_for_what_it_creates(tmp_path):
    tmp_path.chmod(0o755)
    make_private_dir(tmp_path / "a" / "b")
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "a").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "a" / "b").stat().st_mode) == 0o700
