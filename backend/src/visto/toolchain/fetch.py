"""Checksum-verified download and safe archive extraction (stdlib only)."""

import hashlib
import os
import posixpath
import re
import shutil
import ssl
import stat
import tarfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1 << 20
TIMEOUT_S = 60
_ALGORITHMS = {"sha256": 64, "sha1": 40}
_DRIVE = re.compile(r"^[A-Za-z]:")

Opener = Callable[[str], BinaryIO]


class ChecksumMismatch(ValueError):
    pass


class UnsafeArchive(ValueError):
    pass


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects (bounded by urllib) only while they stay on HTTPS.

    Release assets legitimately redirect to a CDN host; the checksum, not the host, is
    the integrity guarantee, but a downgrade to plain HTTP is refused outright.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            fp.close()
            message = f"refusing a non-HTTPS redirect to {newurl}"
            raise urllib.error.HTTPError(req.full_url, code, message, headers, None)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_opener(ca_bundle: Path | None = None) -> Opener:
    """A urllib opener that trusts `ca_bundle` (a PEM file) instead of the system store.

    The same TLS context verifies every redirect hop.
    """
    context = ssl.create_default_context(cafile=None if ca_bundle is None else str(ca_bundle))
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _HttpsOnlyRedirects()
    )
    return lambda url: opener.open(url, timeout=TIMEOUT_S)


def download(
    url: str,
    target: Path,
    checksum: str,
    *,
    opener: Opener | None = None,
    ca_bundle: Path | None = None,
) -> Path:
    """Stream `url` into `target`; on any failure, including a checksum mismatch, remove it."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS download: {url}")
    algorithm, _, expected = checksum.partition(":")
    if _ALGORITHMS.get(algorithm) != len(expected):
        raise ValueError(f"unsupported checksum: {checksum}")
    digest = hashlib.new(algorithm)
    opener = opener or https_opener(ca_bundle)
    try:
        with opener(url) as response, open(target, "wb") as out:
            while chunk := response.read(CHUNK):
                digest.update(chunk)
                out.write(chunk)
        actual = digest.hexdigest()
        if actual != expected.lower():
            raise ChecksumMismatch(f"{url}: expected {checksum}, got {algorithm}:{actual}")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


@dataclass(frozen=True)
class _Entry:
    name: str
    kind: str  # "dir", "file", "symlink", "hardlink"
    mode: int = 0
    link: str = ""
    read: Callable[[], BinaryIO] | None = None


def _parts(name: str, strip: tuple[str, ...]) -> tuple[str, ...]:
    """Validated relative path parts of an archive member after removing `strip`."""
    if not name or "\\" in name or "\x00" in name or name.startswith("/") or _DRIVE.match(name):
        raise UnsafeArchive(f"unsafe archive path: {name!r}")
    parts = tuple(part for part in name.split("/") if part not in ("", "."))
    if any(part == ".." or ":" in part for part in parts):
        raise UnsafeArchive(f"unsafe archive path: {name!r}")
    if not parts:
        return ()
    if parts[: len(strip)] != strip:
        raise UnsafeArchive(f"archive path outside {'/'.join(strip)!r}: {name!r}")
    return parts[len(strip) :]


def _check_link_target(location: tuple[str, ...], target: str) -> None:
    if not target or "\\" in target or "\x00" in target or target.startswith("/"):
        raise UnsafeArchive(f"unsafe link target: {target!r}")
    if _DRIVE.match(target):
        raise UnsafeArchive(f"unsafe link target: {target!r}")
    resolved = posixpath.normpath(posixpath.join(".", *location[:-1], target))
    if resolved == ".." or resolved.startswith("../"):
        raise UnsafeArchive(f"link escapes the archive: {target!r}")


def _zip_entries(archive: Path) -> Iterator[_Entry]:
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            mode = (info.external_attr >> 16) if info.create_system == 3 else 0
            kind = stat.S_IFMT(mode)
            if stat.S_ISLNK(mode):
                yield _Entry(info.filename, "symlink", link=zipped.read(info).decode("utf-8"))
            elif info.is_dir() or stat.S_ISDIR(mode):
                yield _Entry(info.filename, "dir")
            elif kind in (0, stat.S_IFREG):
                yield _Entry(info.filename, "file", mode, read=lambda i=info: zipped.open(i))
            else:
                raise UnsafeArchive(f"unsupported archive member: {info.filename!r}")


def _tar_entries(archive: Path, kind: str) -> Iterator[_Entry]:
    with tarfile.open(archive, {"tar.gz": "r:gz", "tar.xz": "r:xz"}[kind]) as tarred:
        for member in tarred:
            if member.isdir():
                yield _Entry(member.name, "dir")
            elif member.isreg():
                read = lambda m=member: tarred.extractfile(m)  # noqa: E731
                yield _Entry(member.name, "file", member.mode, read=read)
            elif member.issym():
                yield _Entry(member.name, "symlink", link=member.linkname)
            elif member.islnk():
                yield _Entry(member.name, "hardlink", link=member.linkname)
            else:
                raise UnsafeArchive(f"unsupported archive member: {member.name!r}")


def _set_mode(path: Path, mode: int) -> None:
    if os.name != "nt":
        os.chmod(path, 0o755 if mode & 0o111 else 0o644)


def _key(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Collision key that also matches case and Unicode-normalisation aliases."""
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)


def _unaliased(path: Path) -> bool:
    """True when resolving `path` traverses no link (it is its own real path)."""
    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(path)


def _make_dirs(root: Path, parts: tuple[str, ...], verified: set[Path] | None = None) -> Path:
    """Create root/parts one level at a time, refusing any level that is or passes a link."""
    current = root
    for part in parts:
        current = current / part
        if verified is not None and current in verified:
            continue
        if os.path.islink(current) or (os.path.lexists(current) and not current.is_dir()):
            raise UnsafeArchive(f"archive path passes through a link or file: {current.name!r}")
        current.mkdir(exist_ok=True)
        if not _unaliased(current):
            raise UnsafeArchive(f"archive path passes through a link: {current.name!r}")
        if verified is not None:
            verified.add(current)
    return current


def _escapes(root: Path, location: Path) -> bool:
    return not Path(os.path.realpath(location)).is_relative_to(root)


def extract(archive: Path, kind: str, target: Path, strip: str | None) -> None:
    """Extract into `target`, refusing absolute, traversing, special or escaping members.

    Regular files and directories are written first; symbolic links (relative, inside the
    archive) are created last. Every directory level is created separately and must not be
    or pass through a link, including a case or normalisation alias of one; each link is
    resolved right after it is created and again once all exist, and a refused link is
    removed. Hard links become copies of earlier files.
    """
    if kind == "zip":
        entries = _zip_entries(archive)
    elif kind in ("tar.gz", "tar.xz"):
        entries = _tar_entries(archive, kind)
    else:
        raise ValueError(f"unknown archive kind: {kind}")
    prefix = tuple(strip.split("/")) if strip else ()
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    written: set[tuple[str, ...]] = set()  # collision keys of files and directories
    files: dict[tuple[str, ...], Path] = {}
    links: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {}  # key -> (parts, target)
    verified: set[Path] = set()  # directories checked while no link exists yet

    for entry in entries:
        parts = _parts(entry.name, prefix)
        if not parts:
            continue
        key = _key(parts)
        if any(key[:i] in links for i in range(1, len(key) + 1)):
            raise UnsafeArchive(f"archive member collides with a link: {entry.name!r}")
        if entry.kind == "symlink":
            _check_link_target(parts, entry.link)
            links[key] = (parts, entry.link)
            continue
        written.update(key[:i] for i in range(1, len(key) + 1))
        if entry.kind == "dir":
            _make_dirs(root, parts, verified)
            continue
        path = _make_dirs(root, parts[:-1], verified) / parts[-1]
        if os.path.islink(path):
            raise UnsafeArchive(f"archive member collides with a link: {entry.name!r}")
        if entry.kind == "hardlink":
            source = files.get(_parts(entry.link, prefix))
            if source is None:
                raise UnsafeArchive(f"hard link to an unknown member: {entry.link!r}")
            shutil.copy2(source, path)
        else:
            assert entry.read is not None
            with entry.read() as data, open(path, "wb") as out:
                shutil.copyfileobj(data, out, CHUNK)
            _set_mode(path, entry.mode)
        files[parts] = path

    created: list[Path] = []
    try:
        for key, (parts, link) in links.items():
            if key in written or any(key[:i] in links for i in range(1, len(key))):
                raise UnsafeArchive(f"archive member collides with a link: {'/'.join(parts)!r}")
            location = _make_dirs(root, parts[:-1]) / parts[-1]
            if os.path.lexists(location):
                raise UnsafeArchive(f"archive member collides with a link: {'/'.join(parts)!r}")
            os.symlink(link, location)
            created.append(location)
            if _escapes(root, location):
                raise UnsafeArchive(f"link escapes the archive: {'/'.join(parts)!r}")
        for location in created:
            if _escapes(root, location):
                raise UnsafeArchive(f"link escapes the archive: {location.name!r}")
    except BaseException:
        for location in created:
            location.unlink(missing_ok=True)
        raise
