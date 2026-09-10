"""Hash-verified staging and collection over SCP."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from .client import SSHClient
from .errors import RemoteError
from .models import TransferRecord, validate_artifact_name, validate_remote_path


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def ensure_directory(client: SSHClient, remote_dir: str) -> None:
    validate_remote_path(remote_dir, label="remote_dir")
    client.run(["install", "-d", "-m", "700", "--", remote_dir])


def upload_verified(client: SSHClient, source: Path, remote_dir: str, name: str) -> TransferRecord:
    validate_remote_path(remote_dir, label="remote_dir")
    safe_name = validate_artifact_name(name)
    if not source.is_file() or source.is_symlink():
        raise RemoteError(f"staged input is not a regular file: {source}")
    digest = _sha256_file(source)
    size = source.stat().st_size
    destination = f"{remote_dir}/{safe_name}"
    existing = _remote_digest(client, destination, required=False)
    if existing is not None:
        if existing != digest:
            raise RemoteError(f"remote staging target already exists with a different digest: {safe_name}")
        return TransferRecord(destination, size, f"sha256:{digest}")

    temporary = f"{remote_dir}/.{safe_name}.upload-{uuid.uuid4().hex}"
    try:
        client.upload(source, temporary)
        uploaded = _remote_digest(client, temporary, required=True)
        if uploaded != digest:
            raise RemoteError(f"uploaded file digest mismatch: {safe_name}")
        linked = client.run(["ln", "--", temporary, destination], check=False)
        if linked.returncode != 0:
            existing = _remote_digest(client, destination, required=True)
            if existing != digest:
                raise RemoteError(f"remote staging target appeared with a different digest: {safe_name}")
    except Exception:
        client.run(["rm", "-f", "--", temporary], check=False)
        raise
    client.run(["rm", "-f", "--", temporary], check=False)
    return TransferRecord(destination, size, f"sha256:{digest}")


def download_verified(
    client: SSHClient,
    remote_dir: str,
    name: str,
    destination: Path,
) -> TransferRecord:
    validate_remote_path(remote_dir, label="remote_dir")
    safe_name = validate_artifact_name(name)
    remote_path = f"{remote_dir}/{safe_name}"
    if destination.exists() or destination.is_symlink():
        raise RemoteError(f"local collection target already exists: {destination}")
    digest = _remote_digest(client, remote_path, required=True)
    size_result = client.run(["wc", "-c", "--", remote_path])
    try:
        size = int(size_result.stdout.strip().split()[0])
    except (IndexError, ValueError) as exc:
        raise RemoteError(f"could not determine remote artifact size: {safe_name}") from exc
    temporary = destination.with_name(f".{destination.name}.download-{uuid.uuid4().hex}")
    try:
        client.download(remote_path, temporary)
        if temporary.is_symlink() or not temporary.is_file():
            raise RemoteError(f"downloaded artifact is not a regular file: {safe_name}")
        if _sha256_file(temporary) != digest or temporary.stat().st_size != size:
            raise RemoteError(f"downloaded artifact verification failed: {safe_name}")
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise RemoteError(f"local collection target already exists: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return TransferRecord(remote_path, size, f"sha256:{digest}")


def _remote_digest(client: SSHClient, path: str, *, required: bool) -> str | None:
    result = client.run(["sha256sum", "--", path], check=False)
    if result.returncode != 0:
        if required:
            raise RemoteError(f"remote file is missing or unreadable: {path}")
        return None
    digest = result.stdout.strip().split()[0] if result.stdout.strip() else ""
    if not _SHA256.fullmatch(digest):
        raise RemoteError(f"remote sha256sum returned invalid output for {path}")
    return digest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
