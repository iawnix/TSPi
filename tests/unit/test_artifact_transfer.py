from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from artifact_store.transfer import TransferManifestError, apply_manifest, build_manifest, validate_manifest


def test_manifest_is_explicit_sorted_chunked_and_digest_verified(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "b.txt").write_bytes(b"b")
    (source / "a.bin").write_bytes(bytes(range(10)))

    manifest = build_manifest(source, ["b.txt", "a.bin"], chunk_size=4)

    assert [entry["path"] for entry in manifest["entries"]] == ["a.bin", "b.txt"]
    assert len(manifest["entries"][0]["chunks"]) == 3
    assert manifest["manifest_sha256"].startswith("sha256:")
    assert validate_manifest(json.loads(json.dumps(manifest))) == manifest


def test_apply_manifest_resumes_and_skips_verified_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    payload = b"0123456789abcdef"
    (source / "nested/data.bin").parent.mkdir()
    (source / "nested/data.bin").write_bytes(payload)
    manifest = build_manifest(source, ["nested/data.bin"], chunk_size=4)

    target = destination / "nested/data.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload[:4])
    result = apply_manifest(source, destination, manifest)
    assert result["copied"] == 1
    assert target.read_bytes() == payload

    result = apply_manifest(source, destination, manifest)
    assert result["skipped"] == 1


def test_transfer_rejects_protected_paths_and_tampered_manifests(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    protected = source / ".pi/app-server-host/sessions.sqlite"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"secret")
    with pytest.raises(TransferManifestError, match="protected"):
        build_manifest(source, [".pi/app-server-host/sessions.sqlite"])

    (source / "safe.txt").write_text("safe", encoding="utf-8")
    manifest = build_manifest(source, ["safe.txt"])
    manifest["entries"][0]["sha256"] = "sha256:" + hashlib.sha256(b"tampered").hexdigest()
    with pytest.raises(TransferManifestError, match="digest mismatch"):
        validate_manifest(manifest)
