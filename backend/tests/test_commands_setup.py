import hashlib
import io
import os
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from visto.commands.setup import run_setup
from visto.home import VistoHome
from visto.toolchain import Archive, Component, Toolchain
from visto.toolchain.appium import appium_flavor, appium_version
from visto.toolchain.license import LICENSE_SHA256

SERVED: dict[str, bytes] = {}


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _component(name: str, path: str) -> Component:
    data = _zip({f"{name}/{path}": b"tool"})
    url = f"https://example.invalid/{name}/{name}-1.zip"
    SERVED[url] = data
    checksum = "sha256:" + hashlib.sha256(data).hexdigest()
    return Component(name, "1", (Archive(url, checksum, "zip", name, "."),))


def fake_manifest():
    components = {
        "node": _component("node", "bin/node"),
        "jdk": _component("jdk", "bin/java"),
        "android-sdk": _component("android-sdk", "platform-tools/adb"),
    }
    hosts = ("win-x64", "macos-arm64", "macos-x64", "linux-x64")
    return {name: dict.fromkeys(hosts, component) for name, component in components.items()}


@pytest.fixture(autouse=True)
def manifest(monkeypatch):
    monkeypatch.setattr("visto.commands.setup.load_manifest", fake_manifest)


class recording_opener:
    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        return io.BytesIO(SERVED[url])


def fake_all():
    return recording_opener()


def ok_run(argv, **kwargs):
    return subprocess.CompletedProcess(argv, 0)


def write_entry(home: VistoHome, *, pid: int, kind: str) -> None:
    home.instances.mkdir(parents=True, exist_ok=True)
    (home.instances / f"{pid}.json").write_text(
        f'{{"pid": {pid}, "kind": "{kind}", "started_at": "2026-01-01T00:00:00+00:00"}}',
        encoding="utf-8",
    )


def test_setup_declined_license_downloads_no_android(tmp_path):
    opener = recording_opener()
    assert (
        run_setup(
            VistoHome(tmp_path),
            accept_license=None,
            ca_bundle=None,
            host="win-x64",
            opener=opener,
            ask=lambda _: "n",
            run=ok_run,
        )
        == 2
    )
    assert not any("android" in url or "platform-tools" in url for url in opener.urls)
    assert Toolchain(VistoHome(tmp_path)).state().android_license_sha256 is None


def test_setup_explicitly_declined_license_exits_2_without_prompt(tmp_path):
    opener = recording_opener()

    def ask(_):
        raise AssertionError("no prompt expected")

    code = run_setup(
        VistoHome(tmp_path),
        accept_license=False,
        ca_bundle=None,
        host="linux-x64",
        opener=opener,
        ask=ask,
        run=ok_run,
    )
    assert code == 2 and opener.urls == []


def test_setup_on_windows_never_mentions_ios(tmp_path, capsys):
    run_setup(
        VistoHome(tmp_path),
        accept_license=True,
        ca_bundle=None,
        host="win-x64",
        opener=fake_all(),
        run=ok_run,
        output=print,
    )
    out = capsys.readouterr().out
    assert out
    assert not re.search(r"ios|xcode|xcuitest|webdriveragent", out, re.I)


def test_setup_refuses_when_busy(tmp_path):
    home = VistoHome(tmp_path)
    write_entry(home, pid=os.getppid(), kind="start")
    assert (
        run_setup(
            home,
            accept_license=True,
            ca_bundle=None,
            host="linux-x64",
            opener=fake_all(),
            run=ok_run,
        )
        == 4
    )


def test_prompted_acceptance_installs_everything_and_records_it(tmp_path):
    home = VistoHome(tmp_path)
    opener, prompts, lines = recording_opener(), [], []
    code = run_setup(
        home,
        accept_license=None,
        ca_bundle=None,
        host="win-x64",
        opener=opener,
        ask=lambda prompt: prompts.append(prompt) or "y",
        run=ok_run,
        output=lines.append,
    )
    assert code == 0
    assert prompts == ["Accept the Android SDK license? [y/N]"]
    assert sorted(url.split("/")[3] for url in opener.urls) == ["android-sdk", "jdk", "node"]
    state = Toolchain(home).state()
    assert state.android_license_sha256 == LICENSE_SHA256
    assert state.active["appium"] == appium_version(appium_flavor("win-x64"))
    assert {"node", "jdk", "android-sdk"} <= set(state.active)
    assert any("node" in line for line in lines) and any("android-sdk" in line for line in lines)


def test_second_setup_downloads_nothing_and_does_not_prompt(tmp_path):
    home = VistoHome(tmp_path)
    run_setup(
        home, accept_license=True, ca_bundle=None, host="linux-x64", opener=fake_all(), run=ok_run
    )
    opener, calls = recording_opener(), []

    def run(argv, **kwargs):
        calls.append(argv)
        return ok_run(argv)

    def ask(_):
        raise AssertionError("no prompt expected")

    code = run_setup(
        home, accept_license=None, ca_bundle=None, host="linux-x64", opener=opener, ask=ask, run=run
    )
    assert code == 0 and opener.urls == [] and calls == []


def test_android_is_installed_on_macos_too(tmp_path):
    opener = recording_opener()
    code = run_setup(
        VistoHome(tmp_path),
        accept_license=True,
        ca_bundle=None,
        host="macos-arm64",
        opener=opener,
        run=ok_run,
    )
    assert code == 0 and any("android-sdk" in url for url in opener.urls)
    active = Toolchain(VistoHome(tmp_path)).state().active
    assert active["appium"] == appium_version("macos")


def test_ca_bundle_is_stored_in_state(tmp_path):
    bundle = tmp_path / "corporate.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    home = VistoHome(tmp_path / "home")
    code = run_setup(
        home, accept_license=True, ca_bundle=bundle, host="linux-x64", opener=fake_all(), run=ok_run
    )
    assert code == 0
    assert Path(Toolchain(home).state().ca_bundle) == bundle.resolve()


def test_missing_ca_bundle_is_a_failure(tmp_path):
    code = run_setup(
        VistoHome(tmp_path),
        accept_license=True,
        ca_bundle=tmp_path / "none.pem",
        host="linux-x64",
        opener=fake_all(),
        run=ok_run,
    )
    assert code == 3


def test_download_failure_exits_3_and_leaves_nothing_active(tmp_path):
    home = VistoHome(tmp_path)
    lines = []
    code = run_setup(
        home,
        accept_license=True,
        ca_bundle=None,
        host="linux-x64",
        opener=lambda url: io.BytesIO(b"tampered"),
        run=ok_run,
        output=lines.append,
    )
    assert code == 3
    assert Toolchain(home).state().active == {}
    assert any("failed" in line.lower() for line in lines)


def test_appium_install_failure_exits_3(tmp_path):
    def failing(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv)

    code = run_setup(
        VistoHome(tmp_path),
        accept_license=True,
        ca_bundle=None,
        host="linux-x64",
        opener=fake_all(),
        run=failing,
    )
    assert code == 3
    assert "appium" not in Toolchain(VistoHome(tmp_path)).state().active
