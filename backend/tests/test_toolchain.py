import email.message
import hashlib
import io
import json
import os
import re
import ssl
import stat
import tarfile
import urllib.error
import urllib.request
import urllib.response
import zipfile
from pathlib import Path

import pytest

from visto.home import VistoHome
from visto.toolchain import (
    Archive,
    ChecksumMismatch,
    Component,
    Toolchain,
    ToolchainMissing,
    ToolchainState,
    ToolPaths,
    UnsafeArchive,
    UnsupportedHost,
    child_env,
    download,
    extract,
    host_key,
    https_opener,
    load_manifest,
    stored_ca_bundle,
    trusted_ca_bundle,
)

HOSTS = {"win-x64", "macos-arm64", "macos-x64", "linux-x64"}
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


# --- helpers -----------------------------------------------------------------

_SERVED: dict[str, bytes] = {}


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def fake_opener(data: bytes):
    return lambda url: io.BytesIO(data)


def fake_component(name: str, version: str) -> Component:
    data = _zip_bytes({f"{name}-{version}/bin/tool": version.encode()})
    url = f"https://example.invalid/{name}-{version}.zip"
    _SERVED[url] = data
    archive = Archive(url, _sha256(data), "zip", f"{name}-{version}", ".")
    return Component(name, version, (archive,))


def serving(component: Component):
    urls = {archive.url for archive in component.archives}

    def opener(url):
        assert url in urls
        return io.BytesIO(_SERVED[url])

    return opener


class _Interrupting(io.RawIOBase):
    def __init__(self):
        self.calls = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        self.calls += 1
        if self.calls > 1:
            raise KeyboardInterrupt
        buffer[:4] = b"part"
        return 4


def interrupting_opener():
    return lambda url: _Interrupting()


def installed_and_active(toolchain: Toolchain, name: str, version: str) -> None:
    component = fake_component(name, version)
    toolchain.install(component, opener=serving(component))
    toolchain.activate(name, version)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def zip_with(path: Path, name: str, data: bytes) -> Path:
    return _write(path, _zip_bytes({name: data}))


def zip_with_symlink(path: Path, name: str, target: str) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, target)
    return _write(path, buffer.getvalue())


TarMember = tuple[tarfile.TarInfo, bytes | None]


def tar_with(path: Path, members: list[TarMember], mode: str = "w:gz") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, mode) as archive:
        for member, data in members:
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    return path


def tar_file(name: str, data: bytes, mode: int = 0o644) -> TarMember:
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(data), mode
    return info, data


def tar_link(name: str, target: str, kind=tarfile.SYMTYPE) -> TarMember:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, target
    return info, None


def tar_with_symlink(path: Path, name: str, target: str) -> Path:
    return tar_with(path, [tar_link(name, target)])


def kind_of(archive: Path) -> str:
    return "zip" if archive.suffix == ".zip" else "tar.gz"


def paths_in(root: Path) -> ToolPaths:
    return ToolPaths(
        node=root / "node" / "bin" / "node",
        java_home=root / "jdk",
        android_home=root / "sdk",
        adb=root / "sdk" / "platform-tools" / "adb",
        appium_dir=None,
    )


# --- host and manifest -------------------------------------------------------


@pytest.mark.parametrize(
    "system,machine,key",
    [
        ("Windows", "AMD64", "win-x64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x64"),
        ("Linux", "x86_64", "linux-x64"),
    ],
)
def test_host_key(system, machine, key):
    assert host_key(system, machine) == key


def test_unsupported_hosts():
    for system, machine in (("Windows", "ARM64"), ("Linux", "aarch64"), ("FreeBSD", "amd64")):
        with pytest.raises(UnsupportedHost):
            host_key(system, machine)


def test_manifest_covers_every_host_and_pins_checksums():
    manifest = load_manifest()
    for name in ("node", "jdk", "android-sdk"):
        assert set(manifest[name]) == HOSTS
        for comp in manifest[name].values():
            assert comp.name == name and comp.archives
            assert all(
                re.fullmatch(r"(sha256:[0-9a-f]{64}|sha1:[0-9a-f]{40})", a.checksum)
                for a in comp.archives
            )
            assert all(a.url.startswith("https://") for a in comp.archives)


def test_manifest_android_sdk_layout():
    for comp in load_manifest()["android-sdk"].values():
        match = re.fullmatch(r"pt([0-9.]+)-bt([0-9.]+)", comp.version)
        assert match
        assert [a.dest for a in comp.archives] == [
            "platform-tools",
            f"build-tools/{match.group(2)}",
        ]
        assert all(a.kind == "zip" and a.strip for a in comp.archives)


def test_manifest_versions_are_one_per_component():
    manifest = load_manifest()
    for hosts in manifest.values():
        assert len({comp.version for comp in hosts.values()}) == 1


# --- download ----------------------------------------------------------------


def test_download_rejects_checksum_mismatch(tmp_path):
    with pytest.raises(ChecksumMismatch):
        download(
            "https://example.invalid/a.zip",
            tmp_path / "a.zip",
            "sha256:" + "0" * 64,
            opener=fake_opener(b"data"),
        )
    assert not (tmp_path / "a.zip").exists()


def test_download_verifies_sha256_and_sha1(tmp_path):
    data = b"payload" * 10_000
    for checksum in (_sha256(data), "sha1:" + hashlib.sha1(data).hexdigest()):
        target = tmp_path / checksum[:4] / "a.zip"
        target.parent.mkdir()
        assert download("https://x.invalid/a", target, checksum, opener=fake_opener(data)) == target
        assert target.read_bytes() == data


def test_download_refuses_plain_http_and_unknown_algorithms(tmp_path):
    with pytest.raises(ValueError):
        download("http://x.invalid/a", tmp_path / "a", _sha256(b""), opener=fake_opener(b""))
    with pytest.raises(ValueError):
        download("https://x.invalid/a", tmp_path / "a", "md5:" + "0" * 32, opener=fake_opener(b""))
    assert not (tmp_path / "a").exists()


def _fake_https(monkeypatch, routes: dict[str, tuple[int, str]]) -> list[tuple[str, object]]:
    """Serve `routes` (url -> (status, Location or body)) instead of the network."""
    hops: list[tuple[str, object]] = []

    class FakeHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            hops.append((req.full_url, self._context))
            status, value = routes[req.full_url]
            headers = email.message.Message()
            if status in (301, 302, 303, 307, 308):
                headers["Location"] = value
                value = ""
            response = urllib.response.addinfourl(
                io.BytesIO(value.encode()), headers, req.full_url, status
            )
            response.msg = "fake"
            return response

    monkeypatch.setattr("visto.toolchain.fetch.urllib.request.HTTPSHandler", FakeHTTPSHandler)
    return hops


def test_https_opener_uses_ca_bundle(tmp_path, monkeypatch):
    seen = {}
    context = ssl.create_default_context()

    def fake_context(*, cafile=None):
        seen["cafile"] = cafile
        return context

    monkeypatch.setattr("visto.toolchain.fetch.ssl.create_default_context", fake_context)
    hops = _fake_https(monkeypatch, {"https://x.invalid/a": (200, "ok")})
    bundle = tmp_path / "corp.pem"
    assert https_opener(bundle)("https://x.invalid/a").read() == b"ok"
    assert seen["cafile"] == str(bundle)
    assert hops == [("https://x.invalid/a", context)]


def test_https_opener_follows_https_redirects_with_the_same_context(monkeypatch):
    context = ssl.create_default_context()
    monkeypatch.setattr(
        "visto.toolchain.fetch.ssl.create_default_context", lambda *, cafile=None: context
    )
    hops = _fake_https(
        monkeypatch,
        {
            "https://x.invalid/release": (302, "https://cdn.x.invalid/asset"),
            "https://cdn.x.invalid/asset": (200, "payload"),
        },
    )
    assert https_opener()("https://x.invalid/release").read() == b"payload"
    assert hops == [
        ("https://x.invalid/release", context),
        ("https://cdn.x.invalid/asset", context),
    ]


def test_https_opener_refuses_a_redirect_to_plain_http(monkeypatch, tmp_path):
    hops = _fake_https(monkeypatch, {"https://x.invalid/a": (302, "http://x.invalid/a")})
    with pytest.raises(urllib.error.HTTPError, match="non-HTTPS redirect"):
        download("https://x.invalid/a", tmp_path / "a", _sha256(b""), opener=https_opener())
    assert [url for url, _ in hops] == ["https://x.invalid/a"]
    assert not (tmp_path / "a").exists()


# --- extraction --------------------------------------------------------------


def test_extract_rejects_traversal_and_links(tmp_path):
    src = tmp_path / "src"
    for archive in (
        zip_with(src / "a.zip", "../evil", b"x"),
        zip_with(src / "b.zip", "/abs", b"x"),
        tar_with_symlink(src / "c.tar.gz", "link", "/etc"),
    ):
        with pytest.raises(UnsafeArchive):
            extract(archive, kind_of(archive), tmp_path / "out", None)
    assert not (tmp_path / "evil").exists()


@pytest.mark.parametrize(
    "name", ["C:/evil", "c:evil", "dir\\..\\evil", "a/../../evil", "a/b:stream"]
)
def test_extract_rejects_unsafe_zip_names(tmp_path, name):
    with pytest.raises(UnsafeArchive):
        extract(zip_with(tmp_path / "a.zip", name, b"x"), "zip", tmp_path / "out", None)


def test_extract_rejects_escaping_links(tmp_path):
    archives = [
        zip_with_symlink(tmp_path / "a.zip", "top/link", "../../outside"),
        zip_with_symlink(tmp_path / "b.zip", "top/link", "/etc/passwd"),
        tar_with(tmp_path / "c.tar.gz", [tar_link("top/link", "../../outside")]),
        tar_with(tmp_path / "d.tar.gz", [tar_link("top/hard", "/etc/passwd", tarfile.LNKTYPE)]),
        tar_with(tmp_path / "e.tar.gz", [tar_link("top/hard", "top/missing", tarfile.LNKTYPE)]),
    ]
    for index, archive in enumerate(archives):
        kind = "zip" if archive.suffix == ".zip" else "tar.gz"
        with pytest.raises(UnsafeArchive):
            extract(archive, kind, tmp_path / f"out{index}", "top")


def test_extract_rejects_special_members(tmp_path):
    fifo = tarfile.TarInfo("top/pipe")
    fifo.type = tarfile.FIFOTYPE
    with pytest.raises(UnsafeArchive):
        extract(tar_with(tmp_path / "a.tar.gz", [(fifo, None)]), "tar.gz", tmp_path / "out", "top")


def test_extract_strips_the_named_top_folder(tmp_path):
    archive = _write(
        tmp_path / "a.zip",
        _zip_bytes({"pkg-1/": b"", "pkg-1/bin/tool": b"t", "pkg-1/README": b"r"}),
    )
    extract(archive, "zip", tmp_path / "out", "pkg-1")
    assert (tmp_path / "out/bin/tool").read_bytes() == b"t"
    assert (tmp_path / "out/README").read_bytes() == b"r"
    assert not (tmp_path / "out/pkg-1").exists()


def test_extract_rejects_members_outside_the_strip_folder(tmp_path):
    archive = _write(tmp_path / "a.zip", _zip_bytes({"pkg-1/a": b"", "other/b": b""}))
    with pytest.raises(UnsafeArchive):
        extract(archive, "zip", tmp_path / "out", "pkg-1")


@pytest.mark.parametrize("kind,mode", [("tar.gz", "w:gz"), ("tar.xz", "w:xz")])
def test_extract_tar_with_strip_and_hardlink_copy(tmp_path, kind, mode):
    archive = tar_with(
        tmp_path / f"a.{kind}",
        [
            tar_file("./jdk-1/bin/java", b"java", 0o755),
            tar_link("./jdk-1/bin/java2", "./jdk-1/bin/java", tarfile.LNKTYPE),
        ],
        mode,
    )
    extract(archive, kind, tmp_path / "out", "jdk-1")
    assert (tmp_path / "out/bin/java").read_bytes() == b"java"
    assert (tmp_path / "out/bin/java2").read_bytes() == b"java"


@POSIX_ONLY
def test_extract_preserves_executable_bits(tmp_path):
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [tar_file("n/bin/node", b"n", 0o4755), tar_file("n/README", b"r", 0o666)],
    )
    extract(archive, "tar.gz", tmp_path / "t", "n")
    assert stat.S_IMODE((tmp_path / "t/bin/node").stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "t/README").stat().st_mode) == 0o644

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        info = zipfile.ZipInfo("pt/adb")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        zipped.writestr(info, b"adb")
    extract(_write(tmp_path / "a.zip", buffer.getvalue()), "zip", tmp_path / "z", "pt")
    assert stat.S_IMODE((tmp_path / "z/adb").stat().st_mode) == 0o755


@POSIX_ONLY
def test_extract_keeps_internal_relative_symlinks(tmp_path):
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [
            tar_file("n/lib/cli.js", b"js"),
            tar_link("n/bin/npm", "../lib/cli.js"),
        ],
    )
    extract(archive, "tar.gz", tmp_path / "out", "n")
    assert os.readlink(tmp_path / "out/bin/npm") == "../lib/cli.js"
    assert (tmp_path / "out/bin/npm").read_bytes() == b"js"


@POSIX_ONLY
def test_extract_rejects_symlink_chains_that_escape(tmp_path):
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [
            tar_file("n/d1/d2/keep", b""),
            tar_link("n/d1/d2/s", "."),
            tar_link("n/d1/d2/l", "s/../../../x"),  # lexically inside, escapes through s
        ],
    )
    with pytest.raises(UnsafeArchive):
        extract(archive, "tar.gz", tmp_path / "out", "n")


@POSIX_ONLY
def test_extract_rejects_writes_through_a_link(tmp_path):
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [tar_link("n/dir", "."), tar_file("n/dir/file", b"x")],
    )
    with pytest.raises(UnsafeArchive):
        extract(archive, "tar.gz", tmp_path / "out", "n")


def _outside(base: Path) -> list[str]:
    return sorted(p.name for p in base.iterdir() if p.name not in ("a.tar.gz", "out"))


@pytest.mark.parametrize("alias", ["L", "é"])  # case variant, decomposed "é"
def test_extract_rejects_case_and_normalisation_aliases_of_links(tmp_path, alias):
    link = "l" if alias == "L" else "é"
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [
            tar_file("n/d1/keep", b""),
            tar_link(f"n/d1/{link}", ".."),
            tar_file(f"n/d1/{alias}/escaped", b"x"),
        ],
    )
    with pytest.raises(UnsafeArchive):
        extract(archive, "tar.gz", tmp_path / "out", "n")
    assert _outside(tmp_path) == []
    assert not os.path.lexists(tmp_path / "out" / "d1" / link)


@POSIX_ONLY
@pytest.mark.parametrize("member", [tar_file("n/d/escaped", b"x"), tar_link("n/d/escaped", "x")])
def test_extract_never_creates_through_an_unknown_link(tmp_path, member):
    # A link the archive bookkeeping does not know, standing in for a filesystem alias.
    (tmp_path / "outside").mkdir()
    (tmp_path / "out").mkdir()
    os.symlink(tmp_path / "outside", tmp_path / "out" / "d")
    archive = tar_with(tmp_path / "a.tar.gz", [member])
    with pytest.raises(UnsafeArchive):
        extract(archive, "tar.gz", tmp_path / "out", "n")
    assert list((tmp_path / "outside").iterdir()) == []


@POSIX_ONLY
def test_extract_removes_a_refused_link_chain(tmp_path):
    archive = tar_with(
        tmp_path / "a.tar.gz",
        [
            tar_file("n/d1/d2/keep", b""),
            tar_link("n/d1/d2/s", "."),
            tar_link("n/d1/d2/l", "s/s/s/" + "../" * 5),  # lexically ".", really 3 levels up
            tar_file("n/d1/d2/other", b""),
        ],
    )
    with pytest.raises(UnsafeArchive):
        extract(archive, "tar.gz", tmp_path / "out", "n")
    links = [p for p in (tmp_path / "out").rglob("*") if p.is_symlink()]
    assert links == [] and _outside(tmp_path) == []


# --- install, state and paths ------------------------------------------------


def test_install_is_idempotent_and_side_by_side(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    comp = fake_component("node", "1.0.0")
    tc.install(comp, opener=serving(comp))
    tc.activate("node", "1.0.0")
    assert tc.pending([comp]) == []
    tc.install(comp, opener=lambda url: pytest.fail("already installed"))
    newer = fake_component("node", "2.0.0")
    assert tc.pending([newer]) == [newer]
    tc.install(newer, opener=serving(newer))
    tc.activate("node", "2.0.0")
    assert (tmp_path / "toolchain/node/1.0.0").exists()
    assert (tmp_path / "toolchain/node/2.0.0/bin/tool").read_bytes() == b"2.0.0"
    tc.prune()
    assert not (tmp_path / "toolchain/node/1.0.0").exists()
    assert tc.state().active["node"] == "2.0.0"


def test_interrupted_install_keeps_previous_active(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    installed_and_active(tc, "node", "1.0.0")
    with pytest.raises(KeyboardInterrupt):
        tc.install(fake_component("node", "2.0.0"), opener=interrupting_opener())
    assert tc.state().active["node"] == "1.0.0"
    assert not (tmp_path / "toolchain/node/2.0.0").exists()
    assert list((tmp_path / "toolchain").glob("**/.tmp-*")) == []


def test_failed_checksum_leaves_nothing_behind(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    comp = fake_component("jdk", "1")
    with pytest.raises(ChecksumMismatch):
        tc.install(comp, opener=fake_opener(b"tampered"))
    assert not (tmp_path / "toolchain/jdk").exists()
    assert list((tmp_path / "toolchain").glob(".tmp-*")) == []


def test_install_lays_out_multiple_archives(tmp_path):
    pt = _zip_bytes({"platform-tools/adb": b"adb"})
    bt = _zip_bytes({"android-99.0/apksigner": b"sign"})
    _SERVED.update({"https://x.invalid/pt.zip": pt, "https://x.invalid/bt.zip": bt})
    comp = Component(
        "android-sdk",
        "pt1-bt99.0.0",
        (
            Archive(
                "https://x.invalid/pt.zip", _sha256(pt), "zip", "platform-tools", "platform-tools"
            ),
            Archive(
                "https://x.invalid/bt.zip", _sha256(bt), "zip", "android-99.0", "build-tools/99.0.0"
            ),
        ),
    )
    Toolchain(VistoHome(tmp_path)).install(comp, opener=serving(comp))
    root = tmp_path / "toolchain/android-sdk/pt1-bt99.0.0"
    assert (root / "platform-tools/adb").read_bytes() == b"adb"
    assert (root / "build-tools/99.0.0/apksigner").read_bytes() == b"sign"


def test_activate_requires_an_installed_version(tmp_path):
    with pytest.raises(FileNotFoundError):
        Toolchain(VistoHome(tmp_path)).activate("node", "9.9.9")


def test_prune_keeps_unmanaged_directories_and_removes_stale_temp(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    installed_and_active(tc, "node", "1.0.0")
    (tmp_path / "toolchain/corepack/cache").mkdir(parents=True)
    (tmp_path / "toolchain/.tmp-stale/x").mkdir(parents=True)
    tc.prune()
    assert (tmp_path / "toolchain/corepack/cache").exists()
    assert (tmp_path / "toolchain/node/1.0.0").exists()
    assert not (tmp_path / "toolchain/.tmp-stale").exists()


def test_state_round_trip_and_format(tmp_path):
    tc = Toolchain(VistoHome(tmp_path))
    assert tc.state() == ToolchainState(active={}, android_license_sha256=None, ca_bundle=None)
    tc.save_state(ToolchainState({"node": "1"}, "ab" * 32, "/corp.pem"))
    data = json.loads((tmp_path / "toolchain/state.json").read_text("utf-8"))
    assert data == {
        "format": 1,
        "active": {"node": "1"},
        "android_license_sha256": "ab" * 32,
        "ca_bundle": "/corp.pem",
    }
    assert tc.state().ca_bundle == "/corp.pem"
    assert list((tmp_path / "toolchain").glob(".state.json*")) == []


@pytest.mark.parametrize("text", ["{", '{"format": 2, "active": {}}', '{"active": {}}', "[]"])
def test_state_rejects_invalid_or_newer_files(tmp_path, text):
    _write(tmp_path / "toolchain/state.json", text.encode())
    with pytest.raises(ValueError):
        Toolchain(VistoHome(tmp_path)).state()


def _activate_dirs(tmp_path: Path, active: dict[str, str], *, mac: bool) -> Toolchain:
    tc = Toolchain(VistoHome(tmp_path))
    for name, version in active.items():
        (tmp_path / "toolchain" / name / version).mkdir(parents=True)
    if mac:
        (tmp_path / "toolchain/jdk" / active["jdk"] / "Contents/Home/bin").mkdir(parents=True)
    tc.save_state(ToolchainState(dict(active), None, None))
    return tc


@pytest.mark.parametrize("mac", [False, True])
def test_paths_point_at_active_versions(tmp_path, mac):
    active = {"node": "24.0.0", "jdk": "17.0.1+1", "android-sdk": "pt1-bt2"}
    paths = _activate_dirs(tmp_path, active, mac=mac).paths()
    root = tmp_path / "toolchain"
    exe = ".exe" if os.name == "nt" else ""
    node = root / "node/24.0.0" / ("node.exe" if os.name == "nt" else "bin/node")
    assert paths.node == node
    jdk = root / "jdk/17.0.1+1"
    assert paths.java_home == (jdk / "Contents/Home" if mac else jdk)
    assert paths.android_home == root / "android-sdk/pt1-bt2"
    assert paths.adb == root / f"android-sdk/pt1-bt2/platform-tools/adb{exe}"
    assert paths.appium_dir is None


def test_paths_resolve_appium_when_active(tmp_path):
    active = {"node": "1", "jdk": "2", "android-sdk": "pt3-bt4", "appium": "3.8.0"}
    paths = _activate_dirs(tmp_path, active, mac=False).paths()
    assert paths.appium_dir == tmp_path / "toolchain/appium/3.8.0"


def test_paths_require_the_core_components(tmp_path):
    tc = _activate_dirs(tmp_path, {"node": "1"}, mac=False)
    with pytest.raises(ToolchainMissing, match="jdk"):
        tc.paths()


# --- child environment -------------------------------------------------------


def test_child_env_is_scoped(tmp_path):
    env = child_env(paths_in(tmp_path), {"PATH": "/usr/bin", "OPENAI_API_KEY": "k"}, None)
    assert env["ANDROID_HOME"] == str(tmp_path / "sdk") and "OPENAI_API_KEY" not in env
    assert env["ANDROID_SDK_ROOT"] == env["ANDROID_HOME"]
    assert env["JAVA_HOME"] == str(tmp_path / "jdk")
    assert env["PATH"].split(os.pathsep) == [
        str(tmp_path / "node" / "bin"),
        str(tmp_path / "jdk" / "bin"),
        str(tmp_path / "sdk" / "platform-tools"),
        "/usr/bin",
    ]
    assert os.environ.get("ANDROID_HOME") != env["ANDROID_HOME"]
    assert "NODE_EXTRA_CA_CERTS" not in env and "SSL_CERT_FILE" not in env


def test_child_env_adds_ca_bundle_and_does_not_mutate_base(tmp_path):
    base = {"Path": "/usr/bin", "openai_api_key": "k"} if os.name == "nt" else {}
    original = dict(base)
    env = child_env(paths_in(tmp_path), base, "/corp.pem")
    assert env["NODE_EXTRA_CA_CERTS"] == env["SSL_CERT_FILE"] == "/corp.pem"
    assert base == original
    assert not any(key.upper() == "OPENAI_API_KEY" for key in env)
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "node" / "bin")
    assert len([key for key in env if key.upper() == "PATH"]) == 1


def test_child_env_drops_node_and_package_manager_overrides(tmp_path):
    base = {
        "PATH": "/usr/bin",
        "APPIUM_HOME": "/elsewhere/appium",
        "NODE_OPTIONS": "--require /elsewhere/hook.js",
        "NODE_PATH": "/elsewhere/node_modules",
        "npm_config_registry": "https://registry.example.invalid",
        "NPM_CONFIG_PREFIX": "/elsewhere",
        "COREPACK_HOME": "/elsewhere/corepack",
        "COREPACK_NPM_REGISTRY": "https://registry.example.invalid",
        "KEEP_ME": "1",
    }
    env = child_env(paths_in(tmp_path), base, None)
    assert env["KEEP_ME"] == "1"
    dropped = ("APPIUM_HOME", "NODE_OPTIONS", "NODE_PATH", "NPM_CONFIG_", "COREPACK_")
    assert not [key for key in env if key.upper().startswith(dropped)]


def test_trusted_ca_bundle_sets_and_restores_ssl_cert_file(tmp_path):
    environ = {"SSL_CERT_FILE": "/previous.pem"}
    with trusted_ca_bundle("/corp.pem", environ):
        assert environ["SSL_CERT_FILE"] == "/corp.pem"
    assert environ == {"SSL_CERT_FILE": "/previous.pem"}
    environ = {}
    with pytest.raises(RuntimeError), trusted_ca_bundle("/corp.pem", environ):
        assert environ["SSL_CERT_FILE"] == "/corp.pem"
        raise RuntimeError
    assert environ == {}
    environ = {"SSL_CERT_FILE": "/kept.pem"}
    with trusted_ca_bundle(None, environ):
        assert environ == {"SSL_CERT_FILE": "/kept.pem"}


def test_stored_ca_bundle_reads_the_toolchain_state(tmp_path):
    toolchain = Toolchain(VistoHome(tmp_path))
    assert stored_ca_bundle(toolchain) is None
    toolchain.save_state(ToolchainState(ca_bundle="/corp.pem"))
    assert stored_ca_bundle(toolchain) == "/corp.pem"
    toolchain.root.joinpath("state.json").write_text("{", encoding="utf-8")
    assert stored_ca_bundle(toolchain) is None
