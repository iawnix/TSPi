"""Node-scoped local command execution as a ChemTool boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
import subprocess

from transition_state_workflow.tools.contracts import ToolCapability, ToolRequest, ToolResult
from transition_state_workflow.util.node_layout import NodeLayout, resolve_node_layout


@dataclass(frozen=True)
class NodeExecutionRequest:
    """Resolved request for a node-scoped local engine command."""

    workspace: Path
    node_id: str
    command: tuple[str, ...]
    metadata_name: str = "run_metadata.txt"


@dataclass(frozen=True)
class NodeExecutionResult:
    """Result of a node-scoped local command execution."""

    returncode: int
    cwd: Path
    command_text: str
    metadata_path: Path | None = None


def timestamp() -> str:
    """Return a UTC ISO timestamp."""

    return datetime.now(timezone.utc).isoformat()


def render_command(argv: tuple[str, ...] | list[str]) -> str:
    """Render argv as copy-pasteable shell text for metadata and dry-run JSON."""

    return " ".join(shlex.quote(part) for part in argv)


def environment_for_node(layout: NodeLayout) -> dict[str, str]:
    """Return child-process environment with node-scoped path hints."""

    env = os.environ.copy()
    env.update(
        {
            "TS_WORKSPACE": str(layout.root),
            "TS_NODE_ID": layout.node_dir.name,
            "TS_NODE_DIR": str(layout.node_dir),
            "TS_NODE_INPUTS": str(layout.inputs),
            "TS_NODE_OUTPUTS": str(layout.outputs),
            "TS_NODE_PARSED": str(layout.parsed),
            "TS_NODE_SCRATCH": str(layout.scratch),
        }
    )
    return env


def write_metadata(path: Path, lines: list[str], *, append: bool = False) -> None:
    """Write simple key-value execution metadata."""

    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for line in lines:
            handle.write(line.rstrip() + "\n")


def dry_run_payload(layout: NodeLayout, command: tuple[str, ...]) -> dict[str, object]:
    """Return the legacy dry-run JSON payload for a node-scoped command."""

    return {
        "cwd": str(layout.outputs),
        "command": render_command(command),
        "env": {
            "TS_NODE_INPUTS": str(layout.inputs),
            "TS_NODE_OUTPUTS": str(layout.outputs),
            "TS_NODE_SCRATCH": str(layout.scratch),
        },
    }


def run_node_command(request: NodeExecutionRequest) -> NodeExecutionResult:
    """Run a local engine command from ``nodes/<node_id>/outputs``."""

    layout = resolve_node_layout(request.workspace, request.node_id)
    env = environment_for_node(layout)
    metadata_path = layout.outputs / request.metadata_name
    command_text = render_command(request.command)
    metadata_lines = [
        f"start={timestamp()}",
        f"workspace={layout.root}",
        f"node_id={layout.node_dir.name}",
        f"cwd={layout.outputs}",
        f"command={command_text}",
    ]
    write_metadata(metadata_path, metadata_lines)
    result = subprocess.run(request.command, cwd=layout.outputs, env=env, check=False)
    write_metadata(
        metadata_path,
        [f"end={timestamp()}", f"status={result.returncode}"],
        append=True,
    )
    return NodeExecutionResult(
        returncode=result.returncode,
        cwd=layout.outputs,
        command_text=command_text,
        metadata_path=metadata_path,
    )


class NodeExecutionTool:
    """ChemTool adapter for node-scoped local command execution."""

    name = "node-exec"
    capabilities = frozenset(
        {
            ToolCapability.CANDIDATE_GENERATION,
            ToolCapability.OPTIMIZATION,
            ToolCapability.TSFREQ_VALIDATION,
            ToolCapability.CONNECTIVITY_CHECK,
            ToolCapability.DESCRIPTOR_ANALYSIS,
        }
    )

    def run(self, request: ToolRequest) -> ToolResult:
        """Run a command from a :class:`ToolRequest` parameter mapping."""

        command = tuple(str(item) for item in request.parameters.get("command", ()))
        if not command:
            raise ValueError("node-exec request requires a nonempty command")
        metadata_name = str(request.parameters.get("metadata_name", "run_metadata.txt"))
        result = run_node_command(
            NodeExecutionRequest(
                workspace=request.root_directory,
                node_id=request.node_id,
                command=command,
                metadata_name=metadata_name,
            )
        )
        return ToolResult(
            tool_name=self.name,
            capability=request.capability,
            ok=result.returncode == 0,
            artifacts=(result.metadata_path,) if result.metadata_path is not None else (),
            properties={
                "returncode": result.returncode,
                "cwd": str(result.cwd),
                "command": result.command_text,
            },
        )


__all__ = [
    "NodeExecutionRequest",
    "NodeExecutionResult",
    "NodeExecutionTool",
    "dry_run_payload",
    "environment_for_node",
    "render_command",
    "run_node_command",
    "timestamp",
    "write_metadata",
]
