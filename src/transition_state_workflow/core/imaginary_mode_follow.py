"""Core artifact writers for imaginary-mode endpoint follow-up."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from transition_state_workflow.chem.geometry import Atom, append_xyz_frame, write_xyz
from transition_state_workflow.util.json_io import write_json_object
from transition_state_workflow.util.node_layout import NodeLayout, resolve_node_layout


def write_json(path: Path, payload: dict[str, object]) -> None:
    """Write stable JSON through the shared utility."""

    write_json_object(path, payload)


def resolve_output_layout(
    *,
    workspace: Path | None,
    node_id: str | None,
    output_dir: Path | None,
) -> NodeLayout:
    """Resolve either a first-class node layout or a legacy output directory."""

    has_node_scope = bool(workspace or node_id)
    if has_node_scope:
        if not workspace or not node_id:
            raise ValueError("--workspace and --node-id must be provided together")
        if output_dir:
            raise ValueError("use either --workspace/--node-id or --output-dir, not both")
        return resolve_node_layout(workspace, node_id)
    if output_dir is None:
        raise ValueError("provide --workspace/--node-id for node-scoped output or legacy --output-dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    return NodeLayout(
        root=output_dir,
        node_dir=output_dir,
        inputs=output_dir,
        outputs=output_dir,
        parsed=output_dir,
        scratch=output_dir,
    )


def artifact_layout_summary(layout: NodeLayout) -> dict[str, object]:
    return {
        "inputs": str(layout.inputs),
        "outputs": str(layout.outputs),
        "parsed": str(layout.parsed),
    }


def write_endpoint_run_script(layout: NodeLayout) -> Path:
    run_script = layout.outputs / "run_endpoint_opts.sh"
    run_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'g16_bin="${G16_BIN:-g16}"',
                '"$g16_bin" < ../inputs/imaginary_minus_opt.gjf > imaginary_minus_opt.out 2> imaginary_minus_opt.g16_driver.out',
                '"$g16_bin" < ../inputs/imaginary_plus_opt.gjf > imaginary_plus_opt.out 2> imaginary_plus_opt.g16_driver.out',
                "",
            ]
        ),
        encoding="utf-8",
    )
    run_script.chmod(0o755)
    return run_script


def write_prepare_artifacts(
    layout: NodeLayout,
    *,
    freq_output: Path,
    summary: dict[str, object],
    ts_atoms: list[Atom] | None = None,
    minus_atoms: list[Atom] | None = None,
    plus_atoms: list[Atom] | None = None,
    scan_frames: Iterable[tuple[float, list[Atom], str]] = (),
    endpoint_opt_inputs: list[Path] | None = None,
    template_qst_tail_stripped: bool | None = None,
) -> dict[str, object]:
    """Write imaginary-mode follow-up geometry and summary artifacts."""

    payload = dict(summary)
    payload["artifact_layout"] = artifact_layout_summary(layout)

    if ts_atoms is not None and minus_atoms is not None and plus_atoms is not None:
        mode_index = payload.get("imaginary_mode_index", "")
        write_xyz(layout.outputs / "ts_final.xyz", ts_atoms, f"Final TS geometry from {freq_output.name}")
        write_xyz(layout.outputs / "imaginary_minus.xyz", minus_atoms, f"Displaced - along mode {mode_index}")
        write_xyz(layout.outputs / "imaginary_plus.xyz", plus_atoms, f"Displaced + along mode {mode_index}")
        frames: list[str] = []
        for _, frame_atoms, comment in scan_frames:
            append_xyz_frame(frames, frame_atoms, comment)
        if frames:
            (layout.outputs / "imaginary_mode_scan.xyz").write_text(
                "\n".join(frames) + "\n",
                encoding="utf-8",
            )

    if endpoint_opt_inputs:
        run_script = write_endpoint_run_script(layout)
        payload["endpoint_opt_inputs"] = [str(path) for path in endpoint_opt_inputs]
        payload["endpoint_run_script"] = str(run_script)
        payload["template_qst_tail_stripped"] = bool(template_qst_tail_stripped)

    write_json(layout.parsed / "imaginary_mode_summary.json", payload)
    return payload


def write_endpoint_connectivity_summary(layout: NodeLayout, summary: dict[str, object]) -> Path:
    path = layout.parsed / "endpoint_connectivity_summary.json"
    write_json(path, summary)
    return path


def write_irc_connectivity_artifacts(
    layout: NodeLayout,
    *,
    summary: dict[str, object],
    forward_atoms: list[Atom],
    reverse_atoms: list[Atom],
    forward_log: Path,
    reverse_log: Path,
) -> Path:
    write_xyz(layout.outputs / "forward_endpoint.xyz", forward_atoms, f"Final geometry from {forward_log.name}")
    write_xyz(layout.outputs / "reverse_endpoint.xyz", reverse_atoms, f"Final geometry from {reverse_log.name}")
    path = layout.parsed / "irc_connectivity_summary.json"
    write_json(path, summary)
    return path


def resolve_make_opt_output_path(
    *,
    workspace: Path | None,
    node_id: str | None,
    output_gjf: Path,
) -> Path:
    if workspace or node_id:
        if not workspace or not node_id:
            raise ValueError("--workspace and --node-id must be provided together")
        layout = resolve_node_layout(workspace, node_id)
        return layout.inputs / output_gjf.name
    output_gjf.parent.mkdir(parents=True, exist_ok=True)
    return output_gjf


__all__ = [
    "artifact_layout_summary",
    "resolve_make_opt_output_path",
    "resolve_output_layout",
    "write_endpoint_connectivity_summary",
    "write_endpoint_run_script",
    "write_irc_connectivity_artifacts",
    "write_json",
    "write_prepare_artifacts",
]
