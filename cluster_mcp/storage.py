"""Chunked, restart-tolerant file transfers inside the configured workspace."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import stat
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import WorkspaceSettings
from .errors import SecurityError, TransferError
from .security import WorkspacePolicy, sha256_regular_file


class StorageService:
    def __init__(self, settings: WorkspaceSettings, policy: WorkspacePolicy) -> None:
        self.settings = settings
        self.policy = policy
        self.internal_root = settings.root / ".cluster_mcp"
        self.upload_root = self.internal_root / "uploads"
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.policy.initialize()
        self.upload_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.internal_root, 0o700)
        os.chmod(self.upload_root, 0o700)
        self.cleanup_expired_uploads()

    def _metadata_path(self, upload_id: str) -> Path:
        if not upload_id or not all(character in "0123456789abcdef" for character in upload_id):
            raise TransferError("Invalid upload identifier")
        return self.upload_root / f"{upload_id}.json"

    def _part_path(self, upload_id: str) -> Path:
        return self.upload_root / f"{upload_id}.part"

    def _write_metadata(self, upload_id: str, metadata: dict[str, Any]) -> None:
        target = self._metadata_path(upload_id)
        temporary = self.upload_root / f".{upload_id}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, json.dumps(metadata, separators=(",", ":")).encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)

    def _load_metadata(self, upload_id: str) -> dict[str, Any]:
        path = self._metadata_path(upload_id)
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError as exc:
            raise TransferError("Unknown or expired upload identifier") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise TransferError("Upload metadata is unreadable") from exc
        if not isinstance(value, dict):
            raise TransferError("Upload metadata is invalid")
        return value

    def cleanup_expired_uploads(self) -> int:
        cutoff = time.time() - self.settings.upload_expiry_hours * 3600
        removed = 0
        if not self.upload_root.exists():
            return removed
        with self._lock:
            for metadata_path in self.upload_root.glob("*.json"):
                try:
                    if metadata_path.stat().st_mtime >= cutoff:
                        continue
                    upload_id = metadata_path.stem
                    self._part_path(upload_id).unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue
            for part_path in self.upload_root.glob("*.part"):
                try:
                    metadata_path = self._metadata_path(part_path.stem)
                    if part_path.stat().st_mtime < cutoff and not metadata_path.exists():
                        part_path.unlink(missing_ok=True)
                except OSError:
                    continue
        return removed

    def list_files(self, relative_path: str = ".") -> dict[str, Any]:
        directory = self.policy.require_directory(relative_path)
        entries: list[dict[str, Any]] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if entry.name == ".cluster_mcp":
                    continue
                if len(entries) >= self.settings.max_listing_entries:
                    raise TransferError(
                        "Directory contains more than "
                        f"{self.settings.max_listing_entries} visible entries"
                    )
                metadata = entry.stat(follow_symlinks=False)
                if entry.is_symlink():
                    kind = "symlink"
                elif stat.S_ISDIR(metadata.st_mode):
                    kind = "directory"
                elif stat.S_ISREG(metadata.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries.append(
                    {
                        "name": entry.name,
                        "path": self.policy.relative_name(Path(entry.path)),
                        "type": kind,
                        "size": metadata.st_size,
                        "modified_at": datetime.fromtimestamp(
                            metadata.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )
        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        return {"path": self.policy.relative_name(directory) or ".", "entries": entries}

    def file_info(self, relative_path: str, *, include_sha256: bool = False) -> dict[str, Any]:
        path = self.policy.resolve(relative_path, must_exist=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
        else:
            kind = "other"
        result: dict[str, Any] = {
            "path": self.policy.relative_name(path),
            "type": kind,
            "size": metadata.st_size,
            "mode": oct(stat.S_IMODE(metadata.st_mode)),
            "modified_at": datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat(),
        }
        if include_sha256:
            if kind != "file":
                raise TransferError("SHA-256 can only be computed for a regular file")
            stable_metadata, digest = sha256_regular_file(path)
            result["size"] = stable_metadata.st_size
            result["modified_at"] = datetime.fromtimestamp(
                stable_metadata.st_mtime, timezone.utc
            ).isoformat()
            result["sha256"] = digest
        return result

    def create_directory(self, relative_path: str, *, parents: bool = False) -> dict[str, Any]:
        path = self.policy.resolve(relative_path, must_exist=False)
        if path == self.policy.root:
            return {"path": ".", "created": False}
        try:
            path.mkdir(mode=0o700, parents=parents, exist_ok=False)
        except FileExistsError as exc:
            raise TransferError("Destination already exists") from exc
        except FileNotFoundError as exc:
            raise TransferError(
                "Parent directory does not exist; set parents=true if intended"
            ) from exc
        return {"path": self.policy.relative_name(path), "created": True}

    def ensure_directory(self, relative_path: str) -> dict[str, Any]:
        path = self.policy.resolve(relative_path, must_exist=False)
        existed = path.exists()
        if existed:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise TransferError("Destination exists and is not a regular directory")
        else:
            path.mkdir(mode=0o700, parents=True, exist_ok=False)
        return {"path": self.policy.relative_name(path) or ".", "created": not existed}

    def prepare_upload(
        self,
        relative_path: str,
        *,
        size: int,
        sha256: str,
    ) -> dict[str, Any]:
        destination = self.policy.resolve(relative_path, must_exist=False)
        if destination.exists() or destination.is_symlink():
            info = self.file_info(relative_path, include_sha256=True)
            if info["type"] == "file" and info["size"] == size and info["sha256"] == sha256:
                return {
                    "path": relative_path,
                    "size": size,
                    "sha256": sha256,
                    "replayed": True,
                }
            raise TransferError("Upload destination already exists with different content")
        result = self.start_upload(relative_path, size=size, sha256=sha256, overwrite=False)
        return {**result, "replayed": False}

    def start_upload(
        self,
        relative_path: str,
        *,
        size: int,
        sha256: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if isinstance(size, bool) or not 0 <= size <= self.settings.max_upload_bytes:
            raise TransferError(
                f"Upload size must be between 0 and {self.settings.max_upload_bytes} bytes"
            )
        if sha256 is not None:
            sha256 = sha256.lower()
            if len(sha256) != 64 or any(
                character not in "0123456789abcdef" for character in sha256
            ):
                raise TransferError("sha256 must be a 64-character hexadecimal digest")
        destination = self.policy.resolve(relative_path, must_exist=False)
        if destination == self.policy.root:
            raise TransferError("Upload destination must name a file")
        if not destination.parent.is_dir():
            raise TransferError("Upload destination parent directory does not exist")
        if destination.exists() and not overwrite:
            raise TransferError("Destination already exists; set overwrite=true to replace it")
        free_bytes = shutil.disk_usage(destination.parent).free
        if free_bytes - size < self.settings.min_free_bytes:
            raise TransferError(
                f"Upload would leave less than {self.settings.min_free_bytes} bytes free "
                "in the workspace"
            )

        upload_id = uuid.uuid4().hex
        part_path = self._part_path(upload_id)
        with self._lock:
            descriptor = os.open(part_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            metadata = {
                "version": 1,
                "destination": self.policy.relative_name(destination),
                "expected_size": size,
                "expected_sha256": sha256,
                "received": 0,
                "overwrite": overwrite,
                "created_at": time.time(),
            }
            self._write_metadata(upload_id, metadata)
        return {
            "upload_id": upload_id,
            "path": metadata["destination"],
            "expected_size": size,
            "max_chunk_bytes": self.settings.max_chunk_bytes,
        }

    def upload_chunk(self, upload_id: str, *, offset: int, data_base64: str) -> dict[str, Any]:
        if isinstance(offset, bool) or offset < 0:
            raise TransferError("offset must be a non-negative integer")
        try:
            payload = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TransferError("data_base64 is not valid base64") from exc
        if len(payload) > self.settings.max_chunk_bytes:
            raise TransferError(f"Chunk exceeds the {self.settings.max_chunk_bytes}-byte limit")
        with self._lock:
            metadata = self._load_metadata(upload_id)
            received = int(metadata["received"])
            expected_size = int(metadata["expected_size"])
            if offset != received:
                raise TransferError(f"Expected chunk offset {received}, received {offset}")
            if received + len(payload) > expected_size:
                raise TransferError("Chunk exceeds the declared upload size")
            part_path = self._part_path(upload_id)
            flags = os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(part_path, flags)
            try:
                os.lseek(descriptor, offset, os.SEEK_SET)
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            metadata["received"] = received + len(payload)
            self._write_metadata(upload_id, metadata)
        return {
            "upload_id": upload_id,
            "received": metadata["received"],
            "expected_size": expected_size,
            "complete": metadata["received"] == expected_size,
        }

    def finish_upload(self, upload_id: str) -> dict[str, Any]:
        with self._lock:
            metadata = self._load_metadata(upload_id)
            expected_size = int(metadata["expected_size"])
            if int(metadata["received"]) != expected_size:
                raise TransferError(
                    f"Upload is incomplete: {metadata['received']} of {expected_size} "
                    "bytes received"
                )
            part_path = self._part_path(upload_id)
            actual_digest = self._sha256(part_path)
            expected_digest = metadata.get("expected_sha256")
            if expected_digest and actual_digest != expected_digest:
                raise TransferError(
                    f"SHA-256 mismatch: expected {expected_digest}, received {actual_digest}"
                )
            destination = self.policy.resolve(str(metadata["destination"]), must_exist=False)
            if destination.parent.resolve(strict=True) != destination.parent:
                raise SecurityError("Upload destination parent changed during transfer")
            if bool(metadata["overwrite"]):
                os.replace(part_path, destination)
            else:
                try:
                    os.link(part_path, destination, follow_symlinks=False)
                except FileExistsError as exc:
                    raise TransferError(
                        "Destination was created during upload; refusing to overwrite it"
                    ) from exc
                part_path.unlink()
            self._metadata_path(upload_id).unlink(missing_ok=True)
        return {
            "path": self.policy.relative_name(destination),
            "size": expected_size,
            "sha256": actual_digest,
        }

    def abort_upload(self, upload_id: str) -> dict[str, Any]:
        with self._lock:
            self._load_metadata(upload_id)
            self._part_path(upload_id).unlink(missing_ok=True)
            self._metadata_path(upload_id).unlink(missing_ok=True)
        return {"upload_id": upload_id, "aborted": True}

    def download_chunk(
        self, relative_path: str, *, offset: int = 0, max_bytes: int | None = None
    ) -> dict[str, Any]:
        if isinstance(offset, bool) or offset < 0:
            raise TransferError("offset must be a non-negative integer")
        chunk_size = self.settings.max_chunk_bytes if max_bytes is None else max_bytes
        if isinstance(chunk_size, bool) or not 1 <= chunk_size <= self.settings.max_chunk_bytes:
            raise TransferError(f"max_bytes must be between 1 and {self.settings.max_chunk_bytes}")
        path = self.policy.require_file(relative_path)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if offset > metadata.st_size:
                raise TransferError("offset is beyond the end of the file")
            os.lseek(descriptor, offset, os.SEEK_SET)
            payload = os.read(descriptor, chunk_size)
        finally:
            os.close(descriptor)
        next_offset = offset + len(payload)
        return {
            "path": self.policy.relative_name(path),
            "offset": offset,
            "next_offset": next_offset,
            "size": metadata.st_size,
            "eof": next_offset >= metadata.st_size,
            "data_base64": base64.b64encode(payload).decode("ascii"),
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
