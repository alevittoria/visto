"""Local env-file resolution with dummy values and no provider/device contact."""

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from visto.configuration import resolve_api_key


@pytest.fixture
def env_file(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    base = Path(__file__).resolve().parents[2] / ".work" / "configuration-tests"
    target = base / uuid4().hex
    target.mkdir(parents=True)
    yield target / ".env"
    if target.resolve().parent != base.resolve():
        raise ValueError("Refusing test cleanup outside workspace")
    shutil.rmtree(target)


def test_missing_file_returns_empty_without_creating_it(env_file):
    assert resolve_api_key(env_file) == ""
    assert not env_file.exists()


def test_process_key_wins_without_reading_file(env_file, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-process-key")
    env_file.write_bytes(b"\xff invalid UTF-8")
    assert resolve_api_key(env_file) == "dummy-process-key"


@pytest.mark.parametrize("process_value", ["", " \t\n"])
def test_blank_process_key_falls_back_without_environment_mutation(
    env_file, monkeypatch, process_value
):
    monkeypatch.setenv("OPENAI_API_KEY", process_value)
    env_file.write_text("OPENAI_API_KEY=dummy-file-key", encoding="utf-8")
    before = dict(os.environ)
    assert resolve_api_key(env_file) == "dummy-file-key"
    assert dict(os.environ) == before


def test_file_key_does_not_create_process_variable(env_file):
    env_file.write_text("OPENAI_API_KEY=dummy-file-key", encoding="utf-8")
    assert resolve_api_key(env_file) == "dummy-file-key"
    assert "OPENAI_API_KEY" not in os.environ


def test_only_explicit_file_is_read(env_file, monkeypatch):
    env_file.write_text("OPENAI_API_KEY=dummy-cwd-key", encoding="utf-8")
    selected_file = env_file.parent / "selected.env"
    selected_file.write_text("OPENAI_API_KEY=dummy-selected-key", encoding="utf-8")
    with monkeypatch.context() as local_patch:
        local_patch.chdir(env_file.parent)
        assert resolve_api_key(selected_file) == "dummy-selected-key"
        assert resolve_api_key(env_file.parent / "absent.env") == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OPENAI_API_KEY=dummy-key\n", "dummy-key"),
        ("  export OPENAI_API_KEY = dummy-key  # explanation\n", "dummy-key"),
        ("\ufeffOPENAI_API_KEY='dummy-key' # explanation\r\n", "dummy-key"),
        ('OPENAI_API_KEY="dummy-key"# explanation', "dummy-key"),
        ("OPENAI_API_KEY=dummy#literal", "dummy#literal"),
        ("OPENAI_API_KEY='dummy # literal'", "dummy # literal"),
        ('OPENAI_API_KEY="${OTHER}\\literal"', "${OTHER}\\literal"),
        ("OPENAI_API_KEY=", ""),
        ("OPENAI_API_KEY= # empty", ""),
        ("OPENAI_API_KEY=''", ""),
        ("# comment\n\nOTHER=ignored\nexport OTHER='unclosed\n", ""),
        ("OPENAI_API_KEY_EXTRA=ignored\nOPENAI_API_KEYS=ignored", ""),
    ],
)
def test_supported_literal_subset(env_file, text, expected):
    env_file.write_text(text, encoding="utf-8")
    assert resolve_api_key(env_file) == expected


@pytest.mark.parametrize(
    "text",
    [
        "OPENAI_API_KEY=dummy-secret\nOPENAI_API_KEY=another-dummy",
        "OPENAI_API_KEY=\nexport OPENAI_API_KEY=dummy-secret",
        "OPENAI_API_KEY dummy-secret",
        "export OPENAI_API_KEY",
        "OPENAI_API_KEY: dummy-secret",
        "OPENAI_API_KEY += dummy-secret",
        "OPENAI_API_KEY='dummy-secret",
        'OPENAI_API_KEY="dummy-secret',
        "OPENAI_API_KEY='dummy-secret' unexpected",
        'OPENAI_API_KEY="dummy-secret" unexpected',
    ],
)
def test_target_duplicates_and_malformed_lines_have_fixed_error(env_file, text):
    env_file.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        resolve_api_key(env_file)
    assert str(error.value) == "Env file has invalid or duplicate OPENAI_API_KEY entries"


def test_invalid_utf8_has_fixed_error(env_file):
    env_file.write_bytes(b"OPENAI_API_KEY=dummy-secret\xff")
    with pytest.raises(ValueError) as error:
        resolve_api_key(env_file)
    assert str(error.value) == "Env file must contain valid UTF-8 text"


def test_unreadable_file_has_fixed_error(env_file, monkeypatch):
    def unreadable(*args, **kwargs):
        raise PermissionError("private-dummy-path-and-secret")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(ValueError) as error:
        resolve_api_key(env_file)
    assert str(error.value) == "Env file could not be read"


def test_directory_is_not_treated_as_missing(env_file):
    env_file.mkdir()
    with pytest.raises(ValueError, match="^Env file could not be read$"):
        resolve_api_key(env_file)
