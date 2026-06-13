"""Resolve and validate the on-disk layout of a TS-search workspace node.

A node lives at ``<workspace>/nodes/<node_id>/`` with ``inputs/``, ``outputs/``,
``parsed/``, and ``scratch/`` subdirectories. Several node-scoped helper commands
need the same resolution and validation, so it lives here once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


NODE_SUBDIRECTORIES = ("inputs", "outputs", "parsed", "scratch")


@dataclass(frozen=True)
class NodeLayout:
    """Resolved directories for a node-scoped helper command."""

    root: Path
    node_dir: Path
    inputs: Path
    outputs: Path
    parsed: Path
    scratch: Path


def resolve_node_layout(workspace: Path, node_id: str) -> NodeLayout:
    """Resolve a node layout, creating the standard subdirectories.

    Raises:
        FileNotFoundError: if ``workspace`` is not a TS-search workspace root, or
            the node directory or its ``node.json`` is missing.
    """

    root = workspace.expanduser().resolve()
    if not (root / "manifest.json").exists() or not (root / "tree.json").exists():
        raise FileNotFoundError(f"{root} is not a TS-search workspace root")
    node_dir = root / "nodes" / node_id
    if not node_dir.exists():
        raise FileNotFoundError(f"missing node directory: {node_dir}")
    if not (node_dir / "node.json").exists():
        raise FileNotFoundError(f"missing node metadata: {node_dir / 'node.json'}")
    for name in NODE_SUBDIRECTORIES:
        (node_dir / name).mkdir(exist_ok=True)
    return NodeLayout(
        root=root,
        node_dir=node_dir,
        inputs=node_dir / "inputs",
        outputs=node_dir / "outputs",
        parsed=node_dir / "parsed",
        scratch=node_dir / "scratch",
    )
