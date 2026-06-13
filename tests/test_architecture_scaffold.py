"""Unit tests for the refactor architecture scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from transition_state_workflow.backends import default_backend_registry
from transition_state_workflow.backends.contracts import BackendOutput
from transition_state_workflow.remote.contracts import RemoteCommandResult, RemoteWorkspace
from transition_state_workflow.remote.openssh import OpenSSHTransport
from transition_state_workflow.remote.sync import build_metadata_sync_plan, execute_sync_plan, verify_sync_plan
from transition_state_workflow.tools.contracts import ChemTool, ToolCapability, ToolRequest, ToolResult
from transition_state_workflow.tools.registry import ChemToolRegistry


@dataclass(frozen=True)
class DummyTool:
    """Small ChemTool implementation for registry tests."""

    name: str
    capabilities: frozenset[ToolCapability]

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            capability=request.capability,
            ok=True,
            properties={"node_id": request.node_id},
        )


class RecordingTransport:
    """Fake transport that records sync downloads without touching a remote."""

    def __init__(self) -> None:
        self.downloads: list[tuple[str, Path]] = []

    def run(self, argv: list[str], *, cwd: str | None = None) -> RemoteCommandResult:
        return RemoteCommandResult(returncode=0, stdout=" ".join(argv), stderr=cwd or "")

    def upload(self, local_path: Path, remote_path: str) -> None:
        raise AssertionError("upload should not be used in metadata sync")

    def download(self, remote_path: str, local_path: Path) -> None:
        self.downloads.append((remote_path, local_path))
        local_path.write_text(f"downloaded {remote_path}\n", encoding="utf-8")


def test_tool_registry_indexes_by_capability() -> None:
    registry = ChemToolRegistry()
    candidate_tool: ChemTool = DummyTool(
        name="xtb-neb",
        capabilities=frozenset({ToolCapability.CANDIDATE_GENERATION}),
    )
    descriptor_tool: ChemTool = DummyTool(
        name="descriptor",
        capabilities=frozenset({ToolCapability.DESCRIPTOR_ANALYSIS}),
    )
    registry.register(descriptor_tool)
    registry.register(candidate_tool)

    assert registry.names() == ("descriptor", "xtb-neb")
    assert registry.get("xtb-neb") is candidate_tool
    assert registry.by_capability(ToolCapability.CANDIDATE_GENERATION) == (candidate_tool,)
    assert registry.by_capability(ToolCapability.CONNECTIVITY_CHECK) == ()


def test_tool_registry_rejects_invalid_tools() -> None:
    registry = ChemToolRegistry()
    with pytest.raises(ValueError, match="tool name"):
        registry.register(DummyTool(name="", capabilities=frozenset({ToolCapability.OPTIMIZATION})))
    with pytest.raises(ValueError, match="at least one capability"):
        registry.register(DummyTool(name="empty", capabilities=frozenset()))


def test_default_backend_registry_exposes_named_adapters(tmp_path: Path) -> None:
    registry = default_backend_registry()
    assert registry.names() == ("ase", "gaussian", "qbics", "xtb")

    input_file = tmp_path / "input.gjf"
    input_file.write_text("%chk=test.chk\n", encoding="utf-8")
    gaussian = registry.get("gaussian")
    prepared = gaussian.prepare({"files": [str(input_file)], "command_argv": ["g16", "input.gjf"]})
    assert prepared.backend == "gaussian"
    assert prepared.files == (input_file,)
    assert prepared.command_argv == ("g16", "input.gjf")

    parsed = gaussian.parse((input_file, tmp_path / "missing.out"))
    assert isinstance(parsed, BackendOutput)
    assert parsed.backend == "gaussian"
    assert parsed.properties["artifact_count"] == 2
    assert parsed.properties["existing_artifacts"] == 1


def test_backend_adapter_rejects_non_mapping_metadata() -> None:
    adapter = default_backend_registry().get("xtb")
    with pytest.raises(ValueError, match="metadata"):
        adapter.prepare({"metadata": ["bad"]})


def test_metadata_sync_plan_downloads_to_local_mirror(tmp_path: Path) -> None:
    workspace = RemoteWorkspace(
        workspace_id="demo",
        remote_root="/remote/tssearch_demo/",
        local_mirror=tmp_path / "mirror",
    )
    plan = build_metadata_sync_plan(workspace, patterns=("manifest.json", "nodes/n001/node.json"))
    transport = RecordingTransport()

    attempted = execute_sync_plan(plan, transport)

    assert attempted == plan.entries
    assert transport.downloads == [
        ("/remote/tssearch_demo/manifest.json", tmp_path / "mirror" / "manifest.json"),
        ("/remote/tssearch_demo/nodes/n001/node.json", tmp_path / "mirror" / "nodes/n001/node.json"),
    ]
    assert verify_sync_plan(plan) == ()


def test_verify_sync_plan_reports_missing_required_files(tmp_path: Path) -> None:
    workspace = RemoteWorkspace("demo", "/remote/demo", tmp_path / "mirror")
    plan = build_metadata_sync_plan(workspace, patterns=("manifest.json",))
    required_entry = plan.entries[0].__class__(
        remote_path=plan.entries[0].remote_path,
        local_path=plan.entries[0].local_path,
        required=True,
    )
    required_plan = plan.__class__(workspace=workspace, entries=(required_entry,))

    assert verify_sync_plan(required_plan) == (str(tmp_path / "mirror" / "manifest.json"),)


def test_openssh_transport_dry_run_returns_command_result() -> None:
    transport = OpenSSHTransport.from_target("login.example", compute_host="compute.example", dry_run=True)

    result = transport.run(["echo", "ready"], cwd="/tmp/work")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
