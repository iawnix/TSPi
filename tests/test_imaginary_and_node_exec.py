"""Imaginary-mode follow-up and node-exec engine wrapper tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import (
    IMAGINARY_MODE_CLI,
    NODE_EXEC_CLI,
    initialize_workspace,
    run_cli,
    start_node,
    validate_workspace,
)
from transition_state_workflow.backends.gaussian import prepare_gaussian_imaginary_mode_follow_data
from transition_state_workflow.gate.connectivity import endpoint_connection_screen
from transition_state_workflow.tools.contracts import ToolCapability, ToolRequest
from transition_state_workflow.tools.node_exec import NodeExecutionTool


def minimal_gaussian_freq_log() -> str:
    return """ Charge = 0 Multiplicity = 1
 Maximum Force            0.000001     0.000450     YES
 RMS     Force            0.000001     0.000300     YES
 Maximum Displacement     0.000001     0.001800     YES
 RMS     Displacement     0.000001     0.001200     YES
 Stationary point found.
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          1           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    0.740000
 ---------------------------------------------------------------------
 Frequencies --   -100.0000
 Red. masses --      1.0000
 Frc consts  --      0.1000
 IR Inten    --      0.0000
  Atom  AN      X      Y      Z
    1    1    0.1000  0.0000  0.0000
    2    1   -0.1000  0.0000  0.0000
 Normal termination of Gaussian 16
"""


def minimal_gaussian_geometry_log(distance: float) -> str:
    return f""" Charge = 0 Multiplicity = 1
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          1           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    {distance:.6f}
 ---------------------------------------------------------------------
 Normal termination of Gaussian 16
"""


def test_gaussian_backend_prepares_imaginary_mode_follow_data(tmp_path: Path) -> None:
    freq_output = tmp_path / "candidate_tsfreq.out"
    freq_output.write_text(minimal_gaussian_freq_log(), encoding="utf-8")

    follow = prepare_gaussian_imaginary_mode_follow_data(freq_output, scale=0.20)

    assert follow.summary["is_ts_frequency_validated"] is True
    assert follow.summary["claim_status_suggestion"] == "tsfreq_validated"
    assert follow.mode is not None
    assert follow.mode.frequency == -100.0
    assert follow.minus_atoms is not None
    assert follow.plus_atoms is not None
    assert len(follow.scan_frames) == 5


def test_connectivity_gate_endpoint_screen_detects_bond_change(tmp_path: Path) -> None:
    minus_log = tmp_path / "minus.out"
    plus_log = tmp_path / "plus.out"
    minus_log.write_text(minimal_gaussian_geometry_log(0.74), encoding="utf-8")
    plus_log.write_text(minimal_gaussian_geometry_log(2.00), encoding="utf-8")

    screen = endpoint_connection_screen(minus_log, plus_log, bond_scale=1.25)

    assert screen.summary["simple_connection_screen_supported"] is True
    assert screen.summary["connectivity_diff_count"] == 1
    assert screen.summary["broken_from_minus_to_plus"] == ["1:H-2:H"]


def test_imaginary_mode_follow_prepare_writes_node_scoped_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    start_node(
        root,
        node_id="n020_imaginary_follow",
        phase="connectivity_validation",
        parent_id="n010_candidate",
        hypothesis="Unit-test imaginary-mode follow-up prepares endpoint opt inputs.",
        operation="imaginary-mode-follow",
    )
    parent_outputs = root / "nodes" / "n010_candidate" / "outputs"
    parent_outputs.mkdir(exist_ok=True)
    freq_output = parent_outputs / "candidate_tsfreq.out"
    freq_output.write_text(minimal_gaussian_freq_log(), encoding="utf-8")
    template = root / "nodes" / "n020_imaginary_follow" / "inputs" / "template_tsfreq.gjf"
    template.write_text(
        "%chk=template.chk\n%nprocshared=8\n%mem=8GB\n"
        "#P M062X/def2SVP Opt=(TS,CalcFC) Freq NoSymm\n\n"
        "template\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
        encoding="utf-8",
    )

    result = run_cli(
        str(IMAGINARY_MODE_CLI),
        "prepare",
        str(freq_output),
        "--workspace",
        str(root),
        "--node-id",
        "n020_imaginary_follow",
        "--template-gjf",
        str(template),
        "--scale",
        "0.20",
        "--nproc",
        "2",
        "--mem",
        "1GB",
    )

    assert "validated_ts_freq" in result.stdout
    node_dir = root / "nodes" / "n020_imaginary_follow"
    summary = json.loads((node_dir / "parsed" / "imaginary_mode_summary.json").read_text(encoding="utf-8"))
    assert summary["is_ts_frequency_validated"] is True
    assert summary["claim_status_suggestion"] == "tsfreq_validated"
    assert summary["imaginary_frequency_count"] == 1
    assert (node_dir / "outputs" / "ts_final.xyz").exists()
    assert (node_dir / "outputs" / "imaginary_minus.xyz").exists()
    assert (node_dir / "outputs" / "imaginary_plus.xyz").exists()
    assert (node_dir / "inputs" / "imaginary_minus_opt.gjf").exists()
    assert (node_dir / "inputs" / "imaginary_plus_opt.gjf").exists()
    run_script = (node_dir / "outputs" / "run_endpoint_opts.sh").read_text(encoding="utf-8")
    assert '< ../inputs/imaginary_minus_opt.gjf > imaginary_minus_opt.out' in run_script
    assert "imaginary_minus_opt.gjf imaginary_minus_opt.out" not in run_script
    assert not (node_dir / "imaginary_mode_summary.json").exists()
def test_imaginary_mode_follow_prepare_strips_qst_template_extra_geometry(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    start_node(
        root,
        node_id="n020_imaginary_follow",
        phase="connectivity_validation",
        parent_id="n010_candidate",
        hypothesis="Unit-test imaginary-mode follow-up prepares endpoint opt inputs from a QST2 template.",
        operation="imaginary-mode-follow",
    )
    freq_output = root / "nodes" / "n010_candidate" / "outputs" / "candidate_tsfreq.out"
    freq_output.write_text(minimal_gaussian_freq_log(), encoding="utf-8")
    template = root / "nodes" / "n020_imaginary_follow" / "inputs" / "template_qst2.gjf"
    template.write_text(
        "%chk=template.chk\n%nprocshared=8\n%mem=8GB\n"
        "#P M062X/def2SVP Opt=(QST2,CalcFC) Freq NoSymm\n\n"
        "reactant title\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n"
        "product title\n\n0 1\nH 0 0 0\nH 0 0 1.00\n\n",
        encoding="utf-8",
    )

    run_cli(
        str(IMAGINARY_MODE_CLI),
        "prepare",
        str(freq_output),
        "--workspace",
        str(root),
        "--node-id",
        "n020_imaginary_follow",
        "--template-gjf",
        str(template),
        "--scale",
        "0.20",
    )

    node_dir = root / "nodes" / "n020_imaginary_follow"
    summary = json.loads((node_dir / "parsed" / "imaginary_mode_summary.json").read_text(encoding="utf-8"))
    minus_input = (node_dir / "inputs" / "imaginary_minus_opt.gjf").read_text(encoding="utf-8")
    assert summary["template_qst_tail_stripped"] is True
    assert "QST2" not in minus_input.upper()
    assert "product title" not in minus_input
    assert "H 0 0 1.00" not in minus_input
    assert minus_input.count("\n0 1\n") == 1
def test_node_exec_runs_fixed_name_engine_outputs_inside_node_outputs(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    code = (
        "from pathlib import Path\n"
        "import os\n"
        "Path('xtbopt.xyz').write_text(os.getcwd() + '\\n', encoding='utf-8')\n"
    )

    run_cli(
        str(NODE_EXEC_CLI),
        "--workspace",
        str(root),
        "--node-id",
        "n010_candidate",
        "--",
        sys.executable,
        "-c",
        code,
    )

    output_path = root / "nodes" / "n010_candidate" / "outputs" / "xtbopt.xyz"
    assert output_path.exists()
    assert not (root / "xtbopt.xyz").exists()
    assert str(root / "nodes" / "n010_candidate" / "outputs") in output_path.read_text(encoding="utf-8")
    metadata = (root / "nodes" / "n010_candidate" / "outputs" / "run_metadata.txt").read_text(encoding="utf-8")
    assert "node_id=n010_candidate" in metadata

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_node_exec_dry_run_keeps_legacy_json_contract(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    result = run_cli(
        str(NODE_EXEC_CLI),
        "--workspace",
        str(root),
        "--node-id",
        "n010_candidate",
        "--dry-run",
        "--",
        "xtb",
        "input.xyz",
    )

    payload = json.loads(result.stdout)
    assert result.stdout.count("\n") > 1
    assert payload["cwd"] == str(root / "nodes" / "n010_candidate" / "outputs")
    assert payload["command"] == "xtb input.xyz"
    assert payload["env"]["TS_NODE_INPUTS"] == str(root / "nodes" / "n010_candidate" / "inputs")
    assert payload["env"]["TS_NODE_OUTPUTS"] == str(root / "nodes" / "n010_candidate" / "outputs")
    assert payload["env"]["TS_NODE_SCRATCH"] == str(root / "nodes" / "n010_candidate" / "scratch")


def test_node_execution_tool_runs_as_chemtool_boundary(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    code = "from pathlib import Path; Path('tool.out').write_text('ok\\n', encoding='utf-8')"

    result = NodeExecutionTool().run(
        ToolRequest(
            root_directory=root,
            node_id="n010_candidate",
            capability=ToolCapability.CANDIDATE_GENERATION,
            parameters={"command": [sys.executable, "-c", code]},
        )
    )

    outputs = root / "nodes" / "n010_candidate" / "outputs"
    assert result.ok is True
    assert result.tool_name == "node-exec"
    assert result.capability == ToolCapability.CANDIDATE_GENERATION
    assert result.properties["returncode"] == 0
    assert result.properties["cwd"] == str(outputs)
    assert result.artifacts == (outputs / "run_metadata.txt",)
    assert (outputs / "tool.out").read_text(encoding="utf-8") == "ok\n"
