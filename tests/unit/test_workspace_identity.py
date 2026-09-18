from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ts_agent.workspace import ensure_workspace_identity, init_workspace, read_workspace_identity, validate_workspace
from ts_agent.workspace.identity import IDENTITY_REF, WorkspaceIdentityError
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.research import ResearchKernel


def test_initialized_workspace_has_stable_bound_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    initialized = init_workspace(workspace)

    first = read_workspace_identity(workspace)
    second = ensure_workspace_identity(workspace)
    workspace_doc = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))

    assert first == second
    assert first["schema_version"] == "ts-workspace-identity/1"
    assert first["workspace_id"] == initialized["workspace_id"] == workspace_doc["workspace_id"]
    assert first["workspace_id"].startswith("ws_")


def test_concurrent_identity_creation_converges_on_one_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with ThreadPoolExecutor(max_workers=12) as executor:
        identities = list(executor.map(lambda _index: ensure_workspace_identity(workspace), range(48)))
    assert len({record["workspace_id"] for record in identities}) == 1
    assert {path.name for path in (workspace / ".agents").iterdir()} == {"workspace-identity.json"}


def test_identity_recreation_does_not_change_scientific_or_operational_revision(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    scientific_before = ResearchKernel(workspace).load().revision
    operational_before = operational_snapshot(workspace)["operational_revision"]
    (workspace / IDENTITY_REF).unlink()

    ensure_workspace_identity(workspace)

    assert ResearchKernel(workspace).load().revision == scientific_before
    assert operational_snapshot(workspace)["operational_revision"] == operational_before


def test_missing_identity_invalidates_runtime_without_changing_scientific_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / IDENTITY_REF).unlink()
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert "invalid_workspace_identity" in {finding["code"] for finding in validation["findings"]}


def test_invalid_and_symlinked_identity_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    identity_path = workspace / IDENTITY_REF
    identity_path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

    with pytest.raises(WorkspaceIdentityError, match="invalid workspace identity"):
        read_workspace_identity(workspace)
    assert validate_workspace(workspace)["valid"] is False

    identity_path.unlink()
    target = workspace / "identity-target.json"
    target.write_text(
        json.dumps({
            "schema_version": "ts-workspace-identity/1",
            "workspace_id": "ws_0123456789abcdef01234567",
            "created_at": "2026-08-05T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    identity_path.symlink_to(target)
    with pytest.raises(WorkspaceIdentityError, match="symbolic link"):
        read_workspace_identity(workspace)
    assert "invalid_workspace_identity" in {
        finding["code"] for finding in validate_workspace(workspace)["findings"]
    }


def test_identity_creation_refuses_symlinked_identity_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external-agents"
    external.mkdir()
    (workspace / ".agents").symlink_to(external, target_is_directory=True)

    with pytest.raises(WorkspaceIdentityError, match="symbolic link"):
        ensure_workspace_identity(workspace)

    assert not (external / "workspace-identity.json").exists()
