"""Private local immutable screenshot files with bound, checked references."""

import asyncio
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

from visto.application.ports import PortError
from visto.domain.models import ArtifactRef
from visto.home import make_private_dir

from .codec import dumps, loads


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        make_private_dir(self.root)

    async def put(self, run_id: str, content: bytes, media_type: str) -> ArtifactRef:
        if not isinstance(run_id, str) or not run_id.strip() or type(content) is not bytes:
            raise PortError("artifact: invalid input")
        if not content or media_type not in ("image/png", "image/jpeg"):
            raise PortError("artifact: unsupported or empty screenshot")
        return await asyncio.to_thread(self._put, run_id, content, media_type)

    def _put(self, run_id: str, content: bytes, media_type: str) -> ArtifactRef:
        artifact_id = uuid.uuid4().hex
        directory = hashlib.sha256(run_id.encode()).hexdigest()
        reference = ArtifactRef(
            artifact_id,
            run_id,
            media_type,
            len(content),
            hashlib.sha256(content).hexdigest(),
            f"{directory}/{artifact_id}",
        )
        try:
            path = self._path(reference)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Resolve again after mkdir: an existing symlink cannot escape root.
            path = self._path(reference)
            self._write(path, content)
            self._write(path.with_suffix(".json"), dumps(reference).encode())
            return reference
        except (OSError, ValueError):
            raise PortError("artifact: write failed") from None

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        # Exclusive creation prevents overwriting a previous evidence file.
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _path(self, reference: ArtifactRef) -> Path:
        if not isinstance(reference, ArtifactRef) or not re.fullmatch(
            r"[0-9a-f]{32}", reference.artifact_id
        ):
            raise ValueError("Invalid artifact ID")
        directory = hashlib.sha256(reference.run_id.encode()).hexdigest()
        expected = f"{directory}/{reference.artifact_id}"
        if reference.storage_key != expected:
            raise ValueError("Artifact scope mismatch")
        path = self.root / directory / reference.artifact_id
        for candidate in (path, path.with_suffix(".json")):
            if not candidate.resolve().is_relative_to(self.root):
                raise ValueError("Artifact escaped storage root")
            if candidate.is_symlink() or candidate.parent.is_symlink():
                raise ValueError("Artifact symlinks are forbidden")
        return path

    async def read(self, reference: ArtifactRef) -> bytes:
        return await asyncio.to_thread(self._read, reference)

    def _read(self, reference: ArtifactRef) -> bytes:
        try:
            path = self._path(reference)
            stored = loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            if stored != reference or path.stat().st_size != reference.byte_length:
                raise ValueError("Artifact metadata mismatch")
            content = path.read_bytes()
            if (
                len(content) != reference.byte_length
                or hashlib.sha256(content).hexdigest() != reference.sha256
            ):
                raise ValueError("Artifact content mismatch")
            return content
        except (OSError, ValueError, TypeError, RecursionError):
            raise PortError("artifact: missing, corrupt or out-of-scope evidence") from None

    async def delete_run(self, run_id: str) -> None:
        """Remove every screenshot owned by one run; links are never followed."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise PortError("artifact: invalid input")
        await asyncio.to_thread(self._delete_run, run_id)

    def _delete_run(self, run_id: str) -> None:
        directory = self.root / hashlib.sha256(run_id.encode()).hexdigest()
        try:
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise ValueError("Artifact directory escaped storage root")
            if directory.exists():
                shutil.rmtree(directory)
        except (OSError, ValueError):
            raise PortError("artifact: delete failed") from None
