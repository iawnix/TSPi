from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace
from ts_workspace import (
    ensure_workspace_identity,
    read_workspace_identity,
    report_workspace,
    validate_workspace,
)
from ts_workspace.identity import IDENTITY_REF, WorkspaceIdentityError
from ts_workspace.validators.decision import ContractError


def test_initialized_workspace_has_stable_reported_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)

    first = read_workspace_identity(workspace)
    second = ensure_workspace_identity(workspace)
    report = report_workspace(workspace)

    assert first == second
    assert first["schema_version"] == "ts-workspace-identity/1"
    assert first["workspace_id"].startswith("ws_")
    assert report["workspace_id"] == first["workspace_id"]
    assert report["workspace_state_refs"]["workspace_identity"] == IDENTITY_REF


def test_concurrent_identity_creation_converges_on_one_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with ThreadPoolExecutor(max_workers=12) as executor:
        identities = list(executor.map(lambda _index: ensure_workspace_identity(workspace), range(48)))

    assert len({record["workspace_id"] for record in identities}) == 1
    identity_dir = workspace / ".agents"
    assert {path.name for path in identity_dir.iterdir()} == {"workspace-identity.json"}


def test_identity_creation_does_not_change_scientific_or_operational_revision(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    (workspace / IDENTITY_REF).unlink()
    before = report_workspace(workspace)

    created = ensure_workspace_identity(workspace)
    after = report_workspace(workspace)

    assert before["workspace_id"] is None
    assert after["workspace_id"] == created["workspace_id"]
    assert after["workspace_revision"] == before["workspace_revision"]
    assert after["operational_revision"] == before["operational_revision"]


def test_missing_identity_is_legacy_warning(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    (workspace / IDENTITY_REF).unlink()

    validation = validate_workspace(workspace)

    assert validation["valid"] is True
    assert "missing_workspace_identity" in {finding["code"] for finding in validation["findings"]}


def test_invalid_and_symlinked_identity_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    identity_path = workspace / IDENTITY_REF
    identity_path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

    with pytest.raises(WorkspaceIdentityError, match="invalid workspace identity"):
        read_workspace_identity(workspace)
    assert validate_workspace(workspace)["valid"] is False

    identity_path.unlink()
    target = workspace / "identity-target.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": "ts-workspace-identity/1",
                "workspace_id": "ws_0123456789abcdef01234567",
                "created_at": "2026-08-05T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    identity_path.symlink_to(target)

    with pytest.raises(WorkspaceIdentityError, match="symbolic link"):
        read_workspace_identity(workspace)
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert "invalid_workspace_identity" in {finding["code"] for finding in validation["findings"]}


def test_force_reinitialize_refuses_symlinked_identity_directory_before_clearing_state(
    tmp_path: Path,
) -> None:
    from ts_workspace import init_workspace

    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    identity_dir = workspace / ".agents"
    (identity_dir / "workspace-identity.json").unlink()
    identity_dir.rmdir()
    external = tmp_path / "external-agents"
    external.mkdir()
    identity_dir.symlink_to(external, target_is_directory=True)
    decision = {
        "schema_version": "ts-decision/2",
        "decision_id": "dec_force_symlink_guard",
        "action": "init_workspace",
        "rationale": "A force reinitialize must not follow an external identity directory.",
        "evidence_refs": [],
        "payload": {},
    }

    with pytest.raises(ContractError, match="workspace identity path cannot contain a symbolic link"):
        init_workspace(workspace, decision, force=True)

    assert (workspace / "research_state.json").is_file()
    assert not (external / "workspace-identity.json").exists()
