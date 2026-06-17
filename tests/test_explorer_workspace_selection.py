"""Explorer workspace-selection contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import initialize_empty_workspace
from transition_state_workflow.base.workspace import ExplorerServerConfig, ExplorerWorkspaceConfig
from transition_state_workflow.web.server import (
    ExplorerWorkspaceDirectory,
    HTTPError,
    build_workspaces_api_payload,
)


def workspace_config(root: Path, workspace_id: str) -> ExplorerWorkspaceConfig:
    """Build one validated-enough workspace config for directory-level tests."""

    return ExplorerWorkspaceConfig(
        workspace_id=workspace_id,
        display_name=workspace_id,
        source_directory=root,
        explorer_state_directory=root.parent / f"{workspace_id}_state",
        metadata={"origin": "unit-test"},
    )


def test_multi_workspace_api_does_not_force_server_default(tmp_path: Path) -> None:
    ws1 = tmp_path / "tssearch_one"
    ws2 = tmp_path / "tssearch_two"
    initialize_empty_workspace(ws1)
    initialize_empty_workspace(ws2)
    directory = ExplorerWorkspaceDirectory(
        ExplorerServerConfig(
            workspaces=(workspace_config(ws1, "ws-one"), workspace_config(ws2, "ws-two")),
            default_workspace_id="ws-one",
            bind_host="127.0.0.1",
            bind_port=8765,
        )
    )

    payload = build_workspaces_api_payload(directory)

    assert payload["default_workspace"] == ""
    assert [item["id"] for item in payload["workspaces"]] == ["ws-one", "ws-two"]
    with pytest.raises(HTTPError) as exc_info:
        directory.get_default()
    assert exc_info.value.code == "workspace_required"
    assert exc_info.value.http_status.value == 400


def test_single_workspace_keeps_legacy_default_routes(tmp_path: Path) -> None:
    ws1 = tmp_path / "tssearch_one"
    initialize_empty_workspace(ws1)
    directory = ExplorerWorkspaceDirectory(
        ExplorerServerConfig(
            workspaces=(workspace_config(ws1, "ws-one"),),
            default_workspace_id="",
            bind_host="127.0.0.1",
            bind_port=8765,
        )
    )

    payload = build_workspaces_api_payload(directory)

    assert payload["default_workspace"] == "ws-one"
    assert directory.get_default().workspace_id == "ws-one"

    stale_default_directory = ExplorerWorkspaceDirectory(
        ExplorerServerConfig(
            workspaces=(workspace_config(ws1, "ws-one"),),
            default_workspace_id="old-workspace",
            bind_host="127.0.0.1",
            bind_port=8765,
        )
    )
    assert stale_default_directory.default_workspace_id() == "ws-one"


def test_frontend_selection_uses_url_and_localstorage() -> None:
    html = (Path(__file__).resolve().parents[1] / "src" / "transition_state_workflow" / "web" / "static" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "workspaceIdFromUrl" in html
    assert 'localStorage.getItem("ts-workspace-id")' in html
    assert 'localStorage.setItem("ts-workspace-id", id)' in html
    assert "payload.default_workspace || state.workspaces[0]" not in html
