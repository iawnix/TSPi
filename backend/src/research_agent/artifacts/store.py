"""Safe payload storage for registered Artifacts.

Callers provide an Artifact ID. The store persists the payload and returns
its verified location, digest, and size for the Artifact Store manifest.
Research notes only reference these materials; they do not own their metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import BinaryIO

from research_agent.foundation.path_safety import PathSafetyError, lexical_path, path_has_symlink


_ARTIFACT_ID = re.compile(r"^art_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CHUNK_SIZE = 1024 * 1024


class ArtifactPayloadError(ValueError):
    """Raised when a physical Artifact payload is unsafe or inconsistent."""


@dataclass(frozen=True)
class PayloadReceipt:
    """Verified physical metadata returned by a payload write/read."""

    artifact_id: str
    location: str
    sha256: str
    size_bytes: int
    media_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "location": self.location,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


class PayloadStore:
    """Store one immutable payload under ``root/<artifact_id>/payload``.

    The store does not write a manifest beside the payload.  Keeping metadata
    in two places would create a second Artifact registry; the caller commits
    the returned receipt through Research State instead.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = lexical_path(root)
        if path_has_symlink(self.root):
            raise ArtifactPayloadError(f"artifact payload root contains a symbolic link: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def put_file(
        self,
        artifact_id: str,
        source: str | os.PathLike[str],
        *,
        media_type: str | None = None,
        expected_sha256: str | None = None,
    ) -> PayloadReceipt:
        self._validate_id(artifact_id)
        source_path = lexical_path(source)
        if path_has_symlink(source_path):
            raise ArtifactPayloadError(f"payload source contains a symbolic link: {source_path}")
        try:
            source_stat = source_path.lstat()
        except FileNotFoundError as exc:
            raise ArtifactPayloadError(f"payload source does not exist: {source_path}") from exc
        if not stat.S_ISREG(source_stat.st_mode):
            raise ArtifactPayloadError(f"payload source must be a regular file: {source_path}")
        with source_path.open("rb") as handle:
            digest, size = _digest_stream(handle)
        self._check_expected_digest(expected_sha256, digest)
        destination = self._payload_path(artifact_id)
        if destination.exists() or destination.is_symlink():
            return self._verify_existing(artifact_id, destination, digest, size, media_type, source_path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._copy_atomic(source_path, destination)
        return self._receipt(artifact_id, destination, digest, size, media_type, source_path)

    def put_bytes(
        self,
        artifact_id: str,
        payload: bytes,
        *,
        media_type: str = "application/octet-stream",
        expected_sha256: str | None = None,
    ) -> PayloadReceipt:
        self._validate_id(artifact_id)
        if not isinstance(payload, bytes):
            raise ArtifactPayloadError("payload must be bytes")
        digest = _digest_bytes(payload)
        self._check_expected_digest(expected_sha256, digest)
        destination = self._payload_path(artifact_id)
        if destination.exists() or destination.is_symlink():
            return self._verify_existing(artifact_id, destination, digest, len(payload), media_type, None)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".payload.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_regular(temporary, destination)
            temporary = ""
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return self._receipt(artifact_id, destination, digest, len(payload), media_type, None)

    def read_bytes(self, artifact_id: str, *, max_bytes: int | None = None) -> bytes:
        self._validate_id(artifact_id)
        path = self._payload_path(artifact_id)
        self._validate_payload(path)
        with path.open("rb") as handle:
            if max_bytes is None:
                return handle.read()
            if not isinstance(max_bytes, int) or max_bytes < 0:
                raise ArtifactPayloadError("max_bytes must be a non-negative integer or null")
            return handle.read(max_bytes)

    def receipt(
        self,
        artifact_id: str,
        *,
        media_type: str | None = None,
        source_name: str | os.PathLike[str] | None = None,
    ) -> PayloadReceipt:
        self._validate_id(artifact_id)
        path = self._payload_path(artifact_id)
        self._validate_payload(path)
        digest, size = _digest_path(path)
        return self._receipt(artifact_id, path, digest, size, media_type, source_name)

    def _payload_path(self, artifact_id: str) -> Path:
        return self.root / artifact_id / "payload"

    def _receipt(
        self,
        artifact_id: str,
        path: Path,
        digest: str,
        size: int,
        media_type: str | None,
        source_name: str | os.PathLike[str] | None,
    ) -> PayloadReceipt:
        selected_type = media_type or (mimetypes.guess_type(str(source_name))[0] if source_name else None)
        return PayloadReceipt(
            artifact_id=artifact_id,
            location=str(path),
            sha256=digest,
            size_bytes=size,
            media_type=selected_type or "application/octet-stream",
        )

    def _verify_existing(
        self,
        artifact_id: str,
        path: Path,
        digest: str,
        size: int,
        media_type: str | None,
        source_name: str | os.PathLike[str] | None,
    ) -> PayloadReceipt:
        self._validate_payload(path)
        existing_digest, existing_size = _digest_path(path)
        if existing_digest != digest or existing_size != size:
            raise ArtifactPayloadError(f"artifact payload already exists with different content: {artifact_id}")
        return self._receipt(artifact_id, path, existing_digest, existing_size, media_type, source_name)

    def _validate_payload(self, path: Path) -> None:
        if path_has_symlink(path):
            raise ArtifactPayloadError(f"artifact payload contains a symbolic link: {path}")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ArtifactPayloadError(f"artifact payload does not exist: {path}") from exc
        if not stat.S_ISREG(mode):
            raise ArtifactPayloadError(f"artifact payload must be a regular file: {path}")

    @staticmethod
    def _validate_id(artifact_id: str) -> None:
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ArtifactPayloadError("artifact_id has an invalid format")

    @staticmethod
    def _check_expected_digest(expected: str | None, actual: str) -> None:
        if expected is not None and expected != actual:
            raise ArtifactPayloadError(f"artifact digest mismatch: expected {expected}, got {actual}")

    @staticmethod
    def _copy_atomic(source: Path, destination: Path) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".payload.", suffix=".tmp", dir=destination.parent)
        try:
            with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
                descriptor = -1
                shutil.copyfileobj(input_handle, output_handle, length=_CHUNK_SIZE)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            PayloadStore._replace_regular(temporary, destination)
            temporary = ""
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _replace_regular(temporary: str, destination: Path) -> None:
        if destination.is_symlink():
            raise ArtifactPayloadError(f"refusing to replace symbolic link: {destination}")
        if destination.exists() and not destination.is_file():
            raise ArtifactPayloadError(f"payload destination must be a regular file: {destination}")
        os.replace(temporary, destination)
        destination.chmod(0o600)


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_path(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        return _digest_stream(handle)


def _digest_stream(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := handle.read(_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    return "sha256:" + digest.hexdigest(), size


__all__ = ["ArtifactPayloadError", "PayloadReceipt", "PayloadStore"]
