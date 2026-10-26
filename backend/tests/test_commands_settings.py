"""`visto settings`: the key travels through stdin only and is never printed."""

import io

import pytest

from visto.adapters.ios.signing import IOSSigning
from visto.adapters.settings.store import Settings, SettingsStore
from visto.application.ports import PortError
from visto.cli import parser
from visto.commands.settings import run_settings
from visto.home import VistoHome


def test_set_key_reads_stdin_only(tmp_path, capsys):
    assert run_settings(VistoHome(tmp_path), "set-key", stdin=io.StringIO("sk-test-stdin1\n")) == 0
    assert "sk-test-stdin1" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        parser().parse_args(["settings", "set-key", "sk-arg"])
    assert SettingsStore(VistoHome(tmp_path)).api_key() == "sk-test-stdin1"


def test_set_key_reads_exactly_one_line(tmp_path):
    stdin = io.StringIO("sk-test-first1\nsecond-line\n")
    assert run_settings(VistoHome(tmp_path), "set-key", stdin=stdin, output=lambda _: None) == 0
    assert SettingsStore(VistoHome(tmp_path)).api_key() == "sk-test-first1"
    assert stdin.read() == "second-line\n"


def test_set_key_rejects_empty_input(tmp_path):
    lines = []
    assert run_settings(VistoHome(tmp_path), "set-key", stdin=io.StringIO(""), output=lines.append)
    assert not SettingsStore(VistoHome(tmp_path)).key_status().configured


def test_set_key_status_shows_last_four_only(tmp_path):
    lines = []
    run_settings(
        VistoHome(tmp_path), "set-key", stdin=io.StringIO("sk-x-abcd\n"), output=lines.append
    )
    assert "abcd" in "".join(lines) and "sk-x" not in "".join(lines)


def test_delete_key(tmp_path):
    home = VistoHome(tmp_path)
    SettingsStore(home).set_api_key("sk-test-gone99")
    lines = []
    assert run_settings(home, "delete-key", output=lines.append) == 0
    assert not SettingsStore(home).key_status().configured
    assert "not configured" in "".join(lines)


@pytest.mark.parametrize(
    "outcome,word,code",
    [
        (None, "ok", 0),
        ("provider: http_401", "unauthorized", 2),
        ("provider: http_404", "model_unavailable", 2),
        ("provider: timeout", "unreachable", 2),
    ],
)
def test_verify_key_prints_result_word(tmp_path, outcome, word, code):
    home = VistoHome(tmp_path)
    SettingsStore(home).set_api_key("sk-test-verify1")
    seen = []

    async def probe(key, model, timeout_ms):
        seen.append((key, model, timeout_ms))
        if outcome is not None:
            raise PortError(outcome)
        return {"id": model}

    lines = []
    assert run_settings(home, "verify-key", output=lines.append, probe=probe) == code
    assert lines == [word]
    assert seen == [("sk-test-verify1", "gpt-6-luna", 10000)]


def test_verify_without_key_makes_no_probe(tmp_path):
    async def probe(*args):
        pytest.fail("no probe without a key")

    lines = []
    assert run_settings(VistoHome(tmp_path), "verify-key", output=lines.append, probe=probe) == 2
    assert lines == ["missing"]


def test_show_off_mac_has_no_ios(tmp_path):
    home = VistoHome(tmp_path)
    SettingsStore(home).set_api_key("sk-test-show1234")
    lines = []
    assert run_settings(home, "show", output=lines.append, host="win-x64") == 0
    text = "\n".join(lines)
    assert "1234" in text and "sk-test" not in text
    assert "Price refresh: on" in text
    assert "ios" not in text.lower()


def test_show_on_mac_prints_presence_flags_only(tmp_path):
    home = VistoHome(tmp_path)
    SettingsStore(home).save(
        Settings(ios=IOSSigning(team_id="TEAM-SECRET-1", wda_bundle_id="example.bundle.secret"))
    )
    lines = []
    assert run_settings(home, "show", output=lines.append, host="macos-arm64") == 0
    text = "\n".join(lines)
    assert "Provider key: not configured" in text
    assert "iOS team ID: set" in text and "iOS signing ID: not set" in text
    assert "TEAM-SECRET-1" not in text and "example.bundle.secret" not in text


def test_invalid_settings_file_fails_without_content(tmp_path):
    home = VistoHome(tmp_path)
    home.secrets_file.write_text("{not json sk-test-leak", encoding="utf-8")
    lines = []
    assert run_settings(home, "show", output=lines.append, host="win-x64") == 3
    assert "sk-test-leak" not in "".join(lines)


def test_verify_key_trusts_the_remembered_ca_bundle(tmp_path, monkeypatch):
    import os

    from visto.toolchain import Toolchain, ToolchainState

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    home = VistoHome(tmp_path)
    SettingsStore(home).set_api_key("sk-test-verify1")
    Toolchain(home).save_state(ToolchainState(ca_bundle=str(tmp_path / "corp.pem")))
    seen = []

    async def probe(key, model, timeout_ms):
        seen.append(os.environ.get("SSL_CERT_FILE"))
        return {"id": model}

    assert run_settings(home, "verify-key", output=lambda _: None, probe=probe) == 0
    assert seen == [str(tmp_path / "corp.pem")] and "SSL_CERT_FILE" not in os.environ
