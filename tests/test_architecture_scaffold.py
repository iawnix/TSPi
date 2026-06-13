"""Unit tests for the refactor architecture scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from transition_state_workflow.backends import default_backend_registry
from transition_state_workflow.backends.contracts import BackendOutput
from transition_state_workflow.remote.contracts import RemoteCommandResult, RemoteWorkspace
from transition_state_workflow.remote.mcp import MCPTransport
from transition_state_workflow.remote.openssh import OpenSSHTransport
from transition_state_workflow.remote.sftp import ParamikoSFTPTransport
from transition_state_workflow.remote.sync import build_metadata_sync_plan, execute_sync_plan, verify_sync_plan
from transition_state_workflow.tools import NodeExecutionTool, TSDescriptorExtractionTool
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


class FakeChannel:
    def recv_exit_status(self) -> int:
        return 7


class FakeStream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.channel = FakeChannel()

    def read(self) -> bytes:
        return self.payload


class FakeSFTP:
    def __init__(self, calls: list[tuple[str, str, str]]) -> None:
        self.calls = calls

    def put(self, local_path: str, remote_path: str) -> None:
        self.calls.append(("put", local_path, remote_path))

    def get(self, remote_path: str, local_path: str) -> None:
        self.calls.append(("get", remote_path, local_path))

    def close(self) -> None:
        self.calls.append(("close", "", ""))


class FakeParamikoClient:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.sftp_calls: list[tuple[str, str, str]] = []
        self.closed = False

    def exec_command(self, command: str):
        self.commands.append(command)
        return None, FakeStream(b"stdout"), FakeStream(b"stderr")

    def open_sftp(self) -> FakeSFTP:
        return FakeSFTP(self.sftp_calls)

    def close(self) -> None:
        self.closed = True


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


def test_node_execution_tool_registers_for_execution_capabilities() -> None:
    registry = ChemToolRegistry()
    node_exec = NodeExecutionTool()

    registry.register(node_exec)

    assert registry.get("node-exec") is node_exec
    assert node_exec in registry.by_capability(ToolCapability.CANDIDATE_GENERATION)
    assert node_exec in registry.by_capability(ToolCapability.OPTIMIZATION)
    assert node_exec in registry.by_capability(ToolCapability.TSFREQ_VALIDATION)


def test_descriptor_extraction_tool_registers_for_descriptor_analysis(tmp_path: Path) -> None:
    ts_out = tmp_path / "ts.out"
    ts_xyz = tmp_path / "ts.xyz"
    minus_xyz = tmp_path / "minus.xyz"
    plus_xyz = tmp_path / "plus.xyz"
    output = tmp_path / "descriptors"
    ts_out.write_text(
        " Charge = 0 Multiplicity = 1\n"
        " SCF Done:  E(RM062X) =  -1.000000 A.U. after 1 cycles\n"
        " Stationary point found.\n"
        " Frequencies --   -100.0000\n"
        " Red. masses --      1.0000\n"
        " Frc consts  --      0.1000\n"
        " IR Inten    --      0.0000\n"
        "  Atom  AN      X      Y      Z\n"
        "    1    1    0.1000  0.0000  0.0000\n"
        "    2    1   -0.1000  0.0000  0.0000\n"
        " Mulliken charges:\n"
        "    1  H   0.100\n"
        "    2  H  -0.100\n"
        " Sum of Mulliken charges = 0.000\n"
        " Normal termination of Gaussian 16\n",
        encoding="utf-8",
    )
    ts_xyz.write_text("2\nts\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")
    minus_xyz.write_text("2\nminus\nH -0.1 0 0\nH 0.1 0 0.74\n", encoding="utf-8")
    plus_xyz.write_text("2\nplus\nH 0.1 0 0\nH -0.1 0 0.74\n", encoding="utf-8")

    tool = TSDescriptorExtractionTool()
    registry = ChemToolRegistry()
    registry.register(tool)
    result = tool.run(
        ToolRequest(
            root_directory=tmp_path,
            node_id="n010_descriptor",
            capability=ToolCapability.DESCRIPTOR_ANALYSIS,
            parameters={
                "ts_out": ts_out,
                "ts_xyz": ts_xyz,
                "minus_xyz": minus_xyz,
                "plus_xyz": plus_xyz,
                "output_dir": output,
                "pairs": ("1-2",),
            },
        )
    )

    assert registry.by_capability(ToolCapability.DESCRIPTOR_ANALYSIS) == (tool,)
    assert result.ok is True
    assert result.tool_name == "ts-descriptor-extract"
    assert result.capability == ToolCapability.DESCRIPTOR_ANALYSIS
    assert output / "ts_descriptors.json" in result.artifacts
    assert result.properties["validation"]["imaginary_frequency_count"] == 1


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


def test_paramiko_sftp_transport_uses_injected_client(tmp_path: Path) -> None:
    client = FakeParamikoClient()
    transport = ParamikoSFTPTransport(client)
    local_file = tmp_path / "local.txt"
    local_file.write_text("x", encoding="utf-8")

    result = transport.run(["echo", "ready"], cwd="/remote/work dir")
    transport.upload(local_file, "/remote/in.txt")
    transport.download("/remote/out.txt", tmp_path / "downloads" / "out.txt")
    transport.close()

    assert result == RemoteCommandResult(returncode=7, stdout="stdout", stderr="stderr")
    assert client.commands == ["cd '/remote/work dir' && echo ready"]
    assert ("put", str(local_file), "/remote/in.txt") in client.sftp_calls
    assert ("get", "/remote/out.txt", str(tmp_path / "downloads" / "out.txt")) in client.sftp_calls
    assert client.closed is True


def test_mcp_transport_normalizes_command_and_file_tools(tmp_path: Path) -> None:
    calls: list[tuple[str, object, object]] = []

    def run_command(argv, cwd):
        calls.append(("run", tuple(argv), cwd))
        return {"returncode": 3, "stdout": "out", "stderr": "err"}

    def upload_file(local_path: Path, remote_path: str) -> None:
        calls.append(("upload", local_path.name, remote_path))

    def download_file(remote_path: str, local_path: Path) -> None:
        calls.append(("download", remote_path, local_path.name))

    transport = MCPTransport(
        run_command=run_command,
        upload_file=upload_file,
        download_file=download_file,
    )

    result = transport.run(["hostname"], cwd="/remote")
    transport.upload(tmp_path / "input.txt", "/remote/input.txt")
    transport.download("/remote/output.txt", tmp_path / "out" / "output.txt")

    assert result == RemoteCommandResult(returncode=3, stdout="out", stderr="err")
    assert calls == [
        ("run", ("hostname",), "/remote"),
        ("upload", "input.txt", "/remote/input.txt"),
        ("download", "/remote/output.txt", "output.txt"),
    ]
