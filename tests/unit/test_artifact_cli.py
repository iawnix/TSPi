from __future__ import annotations

import json
import stat
from pathlib import Path

from tspi_bootstrap import artifact_cli


def test_manifest_command_writes_owner_only_atomic_json(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("input\n", encoding="utf-8")
    output = tmp_path / "transfer.json"

    assert artifact_cli.main(
        [
            "manifest", "--root", str(source), "--path", "input.txt",
            "--chunk-size", "3", "--output", str(output),
        ]
    ) == 0

    result = json.loads(capsys.readouterr().out)
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["entries"] == 1
    assert manifest["entries"][0]["path"] == "input.txt"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_apply_command_resumes_and_is_idempotent(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "nested/data.bin").parent.mkdir()
    (source / "nested/data.bin").write_bytes(b"0123456789")
    manifest_path = tmp_path / "manifest.json"
    assert artifact_cli.main(
        [
            "manifest", "--root", str(source), "--path", "nested/data.bin",
            "--chunk-size", "4", "--output", str(manifest_path),
        ]
    ) == 0
    capsys.readouterr()

    partial = destination / "nested/data.bin"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"0123")
    assert artifact_cli.main(
        [
            "apply", "--source-root", str(source), "--destination-root", str(destination),
            "--manifest", str(manifest_path),
        ]
    ) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["copied"] == 1
    assert partial.read_bytes() == b"0123456789"

    assert artifact_cli.main(
        [
            "apply", "--source-root", str(source), "--destination-root", str(destination),
            "--manifest", str(manifest_path),
        ]
    ) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["skipped"] == 1

    partial.write_bytes(b"corrupt")
    assert artifact_cli.main(
        [
            "apply", "--source-root", str(source), "--destination-root", str(destination),
            "--manifest", str(manifest_path), "--no-resume",
        ]
    ) == 0
    third = json.loads(capsys.readouterr().out)
    assert third["copied"] == 1
    assert partial.read_bytes() == b"0123456789"


def test_cli_reports_malformed_manifest_and_protected_paths(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    protected = source / ".pi/app-server-host/state"
    protected.parent.mkdir(parents=True)
    protected.write_text("private", encoding="utf-8")

    assert artifact_cli.main(
        [
            "manifest", "--root", str(source), "--path", ".pi/app-server-host/state",
            "--output", str(tmp_path / "manifest.json"),
        ]
    ) == 2
    assert "protected" in capsys.readouterr().err

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}\n", encoding="utf-8")
    assert artifact_cli.main(
        [
            "apply", "--source-root", str(source), "--destination-root", str(tmp_path / "destination"),
            "--manifest", str(malformed),
        ]
    ) == 2
    assert "invalid shape" in capsys.readouterr().err


def test_cli_rejects_symlinked_manifest(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("input", encoding="utf-8")
    actual = tmp_path / "actual.json"
    actual.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "manifest.json"
    link.symlink_to(actual)

    assert artifact_cli.main(
        [
            "apply", "--source-root", str(source), "--destination-root", str(tmp_path / "destination"),
            "--manifest", str(link),
        ]
    ) == 2
    assert "regular file" in capsys.readouterr().err
