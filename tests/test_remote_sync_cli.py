"""Tests for the explicit remote workspace sync CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from transition_state_workflow.remote.sync_cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_sync_cli_plan_outputs_json(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "plan",
            "--workspace-id",
            "demo",
            "--remote-root",
            "/remote/demo",
            "--local-mirror",
            str(tmp_path / "mirror"),
            "--pattern",
            "manifest.json",
            "--pretty",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workspace"]["id"] == "demo"
    assert payload["entries"] == [
        {
            "remote_path": "/remote/demo/manifest.json",
            "local_path": str((tmp_path / "mirror" / "manifest.json").resolve()),
            "required": False,
        }
    ]


def test_sync_cli_verify_reports_missing_required_file(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "verify",
            "--workspace-id",
            "demo",
            "--remote-root",
            "/remote/demo",
            "--local-mirror",
            str(tmp_path / "mirror"),
            "--pattern",
            "manifest.json",
            "--require",
            "manifest.json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["missing_required"] == [str((tmp_path / "mirror" / "manifest.json").resolve())]


def test_sync_cli_register_writes_explorer_registry(tmp_path: Path, capsys) -> None:
    mirror = tmp_path / "mirror"
    registry = tmp_path / "workspaces.json"
    exit_code = main(
        [
            "register",
            "--workspace-id",
            "demo",
            "--remote-root",
            "/remote/demo",
            "--local-mirror",
            str(mirror),
            "--registry",
            str(registry),
            "--name",
            "Demo Workspace",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workspace_id"] == "demo"
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    assert registry_payload["workspaces"][0]["source"] == str(mirror.resolve())
    assert registry_payload["workspaces"][0]["name"] == "Demo Workspace"


def test_ts_remote_sync_wrapper_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ts_remote_sync.py"), "--help"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "plan" in result.stdout
    assert "register" in result.stdout
