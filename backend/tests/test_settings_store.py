import os
import stat
from pathlib import Path

import pytest

from visto.adapters.ios.signing import IOSSigning
from visto.adapters.settings.store import KeyStatus, Settings, SettingsError, SettingsStore
from visto.home import VistoHome


def test_missing_files_give_defaults(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    assert store.load() == Settings()
    assert store.api_key() == "" and store.key_status() == KeyStatus(False, None)


def test_round_trip_and_key_status(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.save(Settings(price_refresh=False, ios=IOSSigning(team_id="TEAM123")))
    assert store.load().ios.team_id == "TEAM123" and store.load().price_refresh is False
    assert store.set_api_key("sk-test-abcd1234") == KeyStatus(True, "1234")
    assert store.api_key() == "sk-test-abcd1234"
    assert store.delete_api_key() == KeyStatus(False, None)


def test_home_is_created_on_first_write(tmp_path):
    store = SettingsStore(VistoHome(tmp_path / "new" / "home"))
    store.save(Settings(ios_saved_for_xcuitest="x"))
    assert store.load().ios_saved_for_xcuitest == "x"


def test_set_api_key_normalizes_and_rejects(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.set_api_key("  sk-test-wxyz\n")
    assert store.api_key() == "sk-test-wxyz"
    for bad in ("", "   ", "sk test", "sk-\ttab", "x" * 8193):
        with pytest.raises(SettingsError) as error:
            store.set_api_key(bad)
        assert bad.strip() == "" or bad.strip() not in str(error.value)
    assert store.api_key() == "sk-test-wxyz"


def test_corrupt_files_raise_sanitized_errors(tmp_path):
    home = VistoHome(tmp_path)
    home.settings_file.write_text('{"format": 1, "price_refresh": "yes-SECRETISH"}')
    with pytest.raises(SettingsError) as error:
        SettingsStore(home).load()
    assert "SECRETISH" not in str(error.value) and "settings" in str(error.value).lower()
    home.secrets_file.write_text("not json sk-leak")
    with pytest.raises(SettingsError) as error:
        SettingsStore(home).api_key()
    assert "sk-leak" not in str(error.value)


def test_newer_format_is_refused(tmp_path):
    home = VistoHome(tmp_path)
    home.settings_file.write_text('{"format": 2}')
    with pytest.raises(SettingsError, match="newer"):
        SettingsStore(home).load()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_secrets_file_is_owner_only(tmp_path):
    store = SettingsStore(VistoHome(tmp_path))
    store.set_api_key("sk-test-mode")
    assert stat.S_IMODE(VistoHome(tmp_path).secrets_file.stat().st_mode) == 0o600


def test_ios_capabilities_match_previous_mapping():
    signing = IOSSigning("T", "Apple Development", "com.example.wda", True, "~/dd")
    caps = signing.capabilities()
    assert caps["appium:xcodeOrgId"] == "T" and caps["appium:usePrebuiltWDA"] is True
    assert caps["appium:derivedDataPath"] == str(Path("~/dd").expanduser())
    assert caps["appium:xcodeSigningId"] == "Apple Development"
    assert caps["appium:updatedWDABundleId"] == "com.example.wda"
    assert IOSSigning().capabilities() == {}
