from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.artifacts import ArtifactPayloadError, PayloadStore


def test_put_bytes_is_idempotent_and_returns_verified_receipt(tmp_path: Path) -> None:
    store = PayloadStore(tmp_path / "artifacts")

    first = store.put_bytes("art_result", b"result\n", media_type="text/plain")
    second = store.put_bytes("art_result", b"result\n", media_type="text/plain")

    assert first == second
    assert first.sha256.startswith("sha256:")
    assert first.size_bytes == 7
    assert store.read_bytes("art_result") == b"result\n"


def test_existing_artifact_cannot_be_overwritten_with_different_payload(tmp_path: Path) -> None:
    store = PayloadStore(tmp_path / "artifacts")
    store.put_bytes("art_result", b"first")

    with pytest.raises(ArtifactPayloadError, match="different content"):
        store.put_bytes("art_result", b"second")


def test_file_registration_verifies_expected_digest_and_rejects_symlink(tmp_path: Path) -> None:
    store = PayloadStore(tmp_path / "artifacts")
    source = tmp_path / "result.txt"
    source.write_text("hello", encoding="utf-8")
    receipt = store.put_file("art_result", source, media_type="text/plain")

    assert receipt.size_bytes == 5
    assert store.read_bytes("art_result") == b"hello"

    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(ArtifactPayloadError, match="symbolic link"):
        store.put_file("art_link", link)


def test_invalid_id_and_bounded_read_are_rejected_or_enforced(tmp_path: Path) -> None:
    store = PayloadStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactPayloadError, match="invalid format"):
        store.put_bytes("bad-id", b"x")
    store.put_bytes("art_result", b"abcdef")
    assert store.read_bytes("art_result", max_bytes=3) == b"abc"
    with pytest.raises(ArtifactPayloadError, match="max_bytes"):
        store.read_bytes("art_result", max_bytes=-1)
