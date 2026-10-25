import os
import subprocess
from pathlib import Path

import pytest

from visto.home import VistoHome
from visto.toolchain import Toolchain, ToolchainMissing
from visto.toolchain.appium import (
    appium_flavor,
    appium_resources,
    appium_version,
    install_appium,
    installed_driver_version,
    wda_project,
)
from visto.toolchain.license import (
    LICENSE_SHA256,
    LICENSE_TEXT,
    license_accepted,
    record_acceptance,
)


def toolchain_with_node(tmp_path: Path) -> Toolchain:
    tc = Toolchain(VistoHome(tmp_path))
    for name in ("node", "jdk", "android-sdk"):
        tc.component_dir(name, "1").mkdir(parents=True)
    state = tc.state()
    state.active.update({"node": "1", "jdk": "1", "android-sdk": "1"})
    tc.save_state(state)
    return tc


def recording(calls: list, rc: int):
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, rc)

    return run


def test_flavor_per_host():
    assert appium_flavor("macos-arm64") == "macos" and appium_flavor("win-x64") == "default"
    assert appium_flavor("macos-x64") == "macos" and appium_flavor("linux-x64") == "default"


def test_version_is_flavor_and_lockfile_hash():
    assert appium_version("default").startswith("default-")
    assert len(appium_version("macos")) == len("macos-") + 12
    assert (appium_resources("macos") / "pnpm-lock.yaml").is_file()


def test_install_appium_runs_frozen_hoisted_install(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    calls = []
    tc = toolchain_with_node(tmp_path)
    install_appium(tc, "default", run=recording(calls, rc=0))
    argv, kwargs = calls[0]
    assert argv[-4:] == [
        "install",
        "--frozen-lockfile",
        "--ignore-scripts",
        "--node-linker=hoisted",
    ]
    assert argv[2] == "pnpm" and argv[1].endswith("corepack.js")
    assert kwargs["env"]["COREPACK_ENABLE_DOWNLOAD_PROMPT"] == "0"
    assert kwargs["env"]["COREPACK_HOME"] == str(tc.root / "corepack")
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert kwargs.get("shell", False) is False and kwargs["cwd"].name.startswith("default-")
    assert kwargs["timeout"] == 900
    assert (kwargs["cwd"] / "pnpm-lock.yaml").is_file()
    version = appium_version("default")
    assert tc.state().active["appium"] == version
    assert tc.paths().appium_dir == tc.component_dir("appium", version)
    tc.prune()
    assert tc.component_dir("appium", version).is_dir()


def test_second_install_is_a_no_op(tmp_path):
    calls = []
    tc = toolchain_with_node(tmp_path)
    install_appium(tc, "default", run=recording(calls, rc=0))
    install_appium(tc, "default", run=recording(calls, rc=0))
    assert len(calls) == 1


def test_failed_appium_install_leaves_nothing(tmp_path):
    tc = toolchain_with_node(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        install_appium(tc, "default", run=recording([], rc=1))
    assert not any((tmp_path / "toolchain/appium").glob("default-*"))
    assert "appium" not in tc.state().active


def test_install_without_node_touches_nothing(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    calls = []
    with pytest.raises(ToolchainMissing):
        install_appium(tc, "default", run=recording(calls, rc=0))
    assert not calls and not (tmp_path / "toolchain/appium").exists()


def test_corepack_located_inside_portable_node(tmp_path):
    calls = []
    tc = toolchain_with_node(tmp_path)
    install_appium(tc, "default", run=recording(calls, rc=0))
    node = tc.paths().node
    root = node.parent if os.name == "nt" else node.parent.parent / "lib"
    assert Path(calls[0][0][1]) == root / "node_modules/corepack/dist/corepack.js"


def test_license_acceptance_is_tied_to_text(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    assert not license_accepted(tc.state())
    record_acceptance(tc)
    assert tc.state().android_license_sha256 == LICENSE_SHA256 and license_accepted(tc.state())
    state = tc.state()
    state.android_license_sha256 = "0" * 64
    assert not license_accepted(state)


def test_license_text_is_the_sdk_agreement():
    assert LICENSE_TEXT.startswith("Terms and Conditions")
    assert "Android Software Development Kit License Agreement" in LICENSE_TEXT


def test_wda_project_found(tmp_path):
    p = tmp_path / "node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj"
    p.mkdir(parents=True)
    assert wda_project(tmp_path) == p


def test_wda_project_absent_or_too_deep(tmp_path):
    assert wda_project(tmp_path) is None
    deep = tmp_path / "node_modules/a/b/c/d/e/WebDriverAgent.xcodeproj"
    deep.mkdir(parents=True)
    assert wda_project(tmp_path) is None


def test_installed_driver_version(tmp_path):
    package = tmp_path / "node_modules/some-driver"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version": "1.2.3"}')
    assert installed_driver_version(tmp_path, "some-driver") == "1.2.3"
    assert installed_driver_version(tmp_path, "missing") is None
