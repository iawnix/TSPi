"""Content-addressed artifact storage for research capabilities."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any


_ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{64}$")
_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactError(ValueError):
    """Raised when an artifact is invalid, missing, or fails verification."""


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    content_digest: str
    artifact_type: str
    byte_count: int
    artifact_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "research-agent-artifact-ref/1"

    def __post_init__(self) -> None:
        if self.schema_version != "research-agent-artifact-ref/1":
            raise ArtifactError("unsupported artifact reference schema_version")
        if not isinstance(self.artifact_id, str) or not _ARTIFACT_ID.fullmatch(self.artifact_id):
            raise ArtifactError("artifact_id is invalid")
        if not isinstance(self.content_digest, str) or not _CONTENT_DIGEST.fullmatch(self.content_digest):
            raise ArtifactError("content_digest is invalid")
        if self.artifact_id.removeprefix("art_") != self.content_digest.removeprefix("sha256:"):
            raise ArtifactError("artifact_id does not match content_digest")
        if not isinstance(self.artifact_type, str) or not self.artifact_type:
            raise ArtifactError("artifact_type must be non-empty")
        if not isinstance(self.byte_count, int) or self.byte_count < 0:
            raise ArtifactError("byte_count must be a non-negative integer")
        if not isinstance(self.artifact_path, str) or Path(self.artifact_path).is_absolute():
            raise ArtifactError("artifact_path must be relative")
        expected_path = f"content/{self.content_digest.removeprefix('sha256:')}.bin"
        if self.artifact_path != expected_path:
            raise ArtifactError("artifact_path does not match content_digest")
        if not isinstance(self.metadata, dict):
            raise ArtifactError("metadata must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "artifact_type": self.artifact_type,
            "byte_count": self.byte_count,
            "artifact_path": self.artifact_path,
            "metadata": dict(self.metadata),
        }


class ArtifactStore:
    """Store immutable bytes under a digest-derived, relative artifact path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise ArtifactError("artifact store root must be a physical directory")
        self.root.mkdir(parents=True, exist_ok=True)
        self._content_root = self.root / "content"
        self._metadata_root = self.root / "metadata"
        self._content_root.mkdir(exist_ok=True)
        self._metadata_root.mkdir(exist_ok=True)
        if any(path.is_symlink() or not path.is_dir() for path in (self._content_root, self._metadata_root)):
            raise ArtifactError("artifact store directories must be physical directories")

    def put_bytes(
        self,
        content: bytes,
        *,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        if not isinstance(content, bytes):
            raise ArtifactError("artifact content must be bytes")
        if not isinstance(artifact_type, str) or not artifact_type:
            raise ArtifactError("artifact_type must be non-empty")
        metadata = dict(metadata or {})
        digest = "sha256:" + sha256(content).hexdigest()
        digest_hex = digest.removeprefix("sha256:")
        artifact_id = "art_" + digest_hex
        content_path = self._content_root / f"{digest_hex}.bin"
        metadata_path = self._metadata_root / f"{digest_hex}.json"
        if content_path.is_symlink() or metadata_path.is_symlink():
            raise ArtifactError("artifact store paths must not be symbolic links")
        if content_path.exists() and content_path.read_bytes() != content:
            raise ArtifactError("content digest collision detected")
        if not content_path.exists():
            self._atomic_write(content_path, content)
        ref = ArtifactRef(
            artifact_id=artifact_id,
            content_digest=digest,
            artifact_type=artifact_type,
            byte_count=len(content),
            artifact_path=content_path.relative_to(self.root).as_posix(),
            metadata=metadata,
        )
        if metadata_path.exists():
            try:
                existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ArtifactError("artifact metadata is invalid") from exc
            if existing != ref.to_dict():
                raise ArtifactError("artifact metadata is already bound to different metadata")
        else:
            self._atomic_write(metadata_path, (json.dumps(ref.to_dict(), sort_keys=True) + "\n").encode())
        return ref

    def get(self, artifact_id: str) -> ArtifactRef:
        digest_hex = self._digest_hex(artifact_id)
        metadata_path = self._metadata_root / f"{digest_hex}.json"
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise ArtifactError(f"artifact is not present: {artifact_id}")
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            return ArtifactRef(**value)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ArtifactError(f"artifact metadata is invalid: {artifact_id}") from exc

    def read_bytes(self, artifact: ArtifactRef | str) -> bytes:
        ref = self.get(artifact) if isinstance(artifact, str) else artifact
        digest_hex = self._digest_hex(ref.artifact_id)
        if ref.content_digest != f"sha256:{digest_hex}" or ref.artifact_path != f"content/{digest_hex}.bin":
            raise ArtifactError(f"artifact reference does not match its digest: {ref.artifact_id}")
        path = self.root / ref.artifact_path
        try:
            path.resolve().relative_to(self._content_root.resolve())
        except ValueError as exc:
            raise ArtifactError("artifact content path escapes the content store") from exc
        if path.is_symlink() or not path.is_file():
            raise ArtifactError(f"artifact content is not present: {ref.artifact_id}")
        content = path.read_bytes()
        if len(content) != ref.byte_count or "sha256:" + sha256(content).hexdigest() != ref.content_digest:
            raise ArtifactError(f"artifact content digest mismatch: {ref.artifact_id}")
        return content

    def _digest_hex(self, artifact_id: str) -> str:
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ArtifactError("artifact_id is invalid")
        return artifact_id.removeprefix("art_")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
