from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.config.state_contract import (  # noqa: E402
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
)
from transition_state_workflow.tool.ase_neb.workspace import (  # noqa: E402
    append_evidence_record,
    node_record,
    update_tree_node_metadata,
    upsert_tree_node,
    write_json,
)
from transition_state_workflow.gate.validate import validate_ts_workspace_contract  # noqa: E402


ASE_NEB_CLI = SKILL_ROOT / "scripts" / "ase_neb_framework.py"
GAUSSIAN_PREFLIGHT_CLI = SKILL_ROOT / "scripts" / "gaussian_gen_preflight.py"
PREPARE_GAUSSIAN_CLI = SKILL_ROOT / "scripts" / "prepare_gaussian_ts_input.py"
DESCRIPTOR_CLI = SKILL_ROOT / "scripts" / "ts_descriptor_extract.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        check=True,
        text=True,
        capture_output=True,
    )


def initialize_minimal_workspace(root: Path) -> None:
    write_json(
        root / "manifest.json",
        {
            "system": "unit",
            "created_at": "now",
            "root": str(root),
            "node_schema": WORKSPACE_NODE_SCHEMA,
            "current_accepted_ts": None,
        },
    )
    write_json(
        root / "tree.json",
        {
            "schema": TREE_SCHEMA,
            "nodes": {},
            "active_frontier": [],
            "closed_nodes": [],
            "accepted_nodes": [],
            "events": [],
            "backtrack_events": [],
        },
    )
    write_json(
        root / "evidence_registry.json",
        {
            "schema": EVIDENCE_REGISTRY_SCHEMA,
            "system": "unit",
            "records": [],
            "updated_at": "now",
        },
    )


def test_migrated_ase_neb_candidate_node_is_strict_v2(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    endpoint_dir = root / "nodes" / "n005_endpoint_gate"
    node_dir = root / "nodes" / "n010_neb_xtb"
    endpoint_dir.mkdir(parents=True)
    node_dir.mkdir(parents=True)
    initialize_minimal_workspace(root)
    endpoint_summary = endpoint_dir / "endpoint_summary.json"
    write_json(endpoint_summary, {"endpoint_minima_ready": True})
    endpoint_node = node_record(
        node_id="n005_endpoint_gate",
        parent_id=None,
        node_type="endpoint_minima_validation",
        hypothesis="Unit-test endpoint minima are ready for candidate generation.",
        changed_variables={"endpoint_gate": True},
        status="succeeded",
        claim_status="endpoint_minima_ready",
        outcome="endpoint_minima_validated",
        evidence={"summary": "nodes/n005_endpoint_gate/endpoint_summary.json"},
        decision="prepare_candidate_generation",
        stage="endpoint_minima_validation",
        operation="unit-test-endpoint-minima",
    )
    write_json(endpoint_dir / "node.json", endpoint_node)
    (endpoint_dir / "reflection.md").write_text(
        "## Computational Outcome\nEndpoint minima checks passed.\n\n"
        "## Mechanistic Implication\nCandidate generation has validated endpoint prerequisites.\n\n"
        "## Next Branch\nRun NEB candidate generation.\n",
        encoding="utf-8",
    )
    upsert_tree_node(root, "n005_endpoint_gate", parent=None, stage="endpoint_minima_validation", status="succeeded")
    update_tree_node_metadata(root, "n005_endpoint_gate", endpoint_node)
    append_evidence_record(
        root,
        node_id="n005_endpoint_gate",
        kind="endpoint_minima_summary",
        path=endpoint_summary,
        claim="Endpoint minima are ready for candidate generation.",
        evidence_state="supports",
    )
    summary = node_dir / "summary.json"
    write_json(summary, {"candidate": True})
    node = node_record(
        node_id="n010_neb_xtb",
        parent_id="n005_endpoint_gate",
        node_type="candidate_generation",
        hypothesis="Unit-test NEB branch produced a candidate.",
        changed_variables={"calculator": "xtb"},
        status="succeeded",
        evidence={"summary": "nodes/n010_neb_xtb/summary.json"},
        decision="promote",
        stage="neb",
        operation="ase-neb",
    )
    write_json(node_dir / "node.json", node)
    (node_dir / "reflection.md").write_text(
        "## Computational Outcome\nNEB produced a candidate geometry.\n\n"
        "## Mechanistic Implication\nThe branch remains candidate-only pending TS/Freq and connectivity validation.\n\n"
        "## Next Branch\nPrepare Gaussian TS/Freq validation.\n",
        encoding="utf-8",
    )
    upsert_tree_node(root, "n010_neb_xtb", parent="n005_endpoint_gate", stage="neb", status="succeeded")
    update_tree_node_metadata(root, "n010_neb_xtb", node)
    append_evidence_record(
        root,
        node_id="n010_neb_xtb",
        kind="neb_candidate_summary",
        path=summary,
        claim="NEB candidate summary exists.",
        evidence_state="candidate_found",
    )

    saved_node = json.loads((node_dir / "node.json").read_text(encoding="utf-8"))
    assert saved_node["schema"] == "ts-node-v2"
    assert saved_node["claim_status"] == "candidate_found"
    assert saved_node["outcome"] == "candidate_generated"
    for legacy_key in ("status", "failure_type", "children", "parent", "node_type", "backtrack_target"):
        assert legacy_key not in saved_node

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert tree["schema"] == "tssearch-branching-tree-v2"
    assert tree["nodes"]["n010_neb_xtb"] == {
        "parent_id": "n005_endpoint_gate",
        "stage": "neb",
        "operation": "ase-neb",
        "hypothesis": "Unit-test NEB branch produced a candidate.",
    }

    validation = validate_ts_workspace_contract(root)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_migrated_ase_neb_example_config_validates_without_ase_runtime() -> None:
    result = run_cli(
        str(ASE_NEB_CLI),
        "validate-config",
        str(SKILL_ROOT / "examples" / "neb_xtb_config.json"),
        "--strict-files",
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["config"]["project"]["schema"] == "tssearch-branching-tree-v2"


def test_ase_neb_reflect_command_writes_template(tmp_path: Path) -> None:
    # Regression: ``command_reflect`` calls write_reflection_template, which the
    # main module once failed to import after the workspace split — the command
    # crashed at call time even though import/compile passed. This exercises the
    # path end-to-end (no ASE needed).
    project = tmp_path / "tssearch_reflect"
    node_dir = project / "nodes" / "n010_candidate"
    node_dir.mkdir(parents=True)
    result = run_cli(
        str(ASE_NEB_CLI),
        "reflect",
        str(project),
        "n010_candidate",
        "--decision",
        "run_gaussian_validation",
    )
    assert result.returncode == 0
    assert (node_dir / "reflection.md").exists()
    assert "run_gaussian_validation" in (node_dir / "reflection.md").read_text(encoding="utf-8")


def _ase_available() -> bool:
    try:
        import ase  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _ase_available(), reason="ASE not installed")
def test_ase_neb_continue_gaussian_neb_dry_run_writes_first_input(tmp_path: Path) -> None:
    # Regression guard for the external-Gaussian path: the dry-run branch reads
    # the image directory (needs ASE), builds node metadata, and writes the first
    # Gaussian input — touching external_gaussian.* helpers including
    # continue_node_id_from_images -> external_gaussian_level_slug (the re.search
    # path that once crashed for lack of ``import re``).
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for i in range(3):
        (images_dir / f"final_image_{i:02d}.xyz").write_text(
            f"2\nimg{i}\nH 0.0 0.0 {0.1 * i}\nH 0.0 0.0 {0.74 + 0.1 * i}\n",
            encoding="utf-8",
        )
    project = tmp_path / "tssearch_ext_gaussian"
    result = run_cli(
        str(ASE_NEB_CLI),
        "continue-gaussian-neb-from-images",
        str(project),
        "--xyz-dir",
        str(images_dir),
        "--pattern",
        "final_image_*.xyz",
        "--route",
        "# wb97xd/def2tzvp force",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--dry-run-inputs",
    )
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["image_count"] == 3
    assert Path(payload["first_input"]).exists()
    # The node id is derived via external_gaussian_level_slug (the re.search path).
    assert "wb97xd_def2tzvp" in payload["node_id"]


def test_migrated_gaussian_preflight_fix(tmp_path: Path) -> None:
    source = tmp_path / "legacy_genecp.gjf"
    fixed = tmp_path / "fixed.gjf"
    source.write_text(
        "# RM062X/genecp opt\n\n"
        "legacy\n\n"
        "0 1\n"
        "H 0 0 0\n\n"
        "-H -C 0\n"
        "Def2SVP\n"
        "****\n",
        encoding="utf-8",
    )

    run_cli(str(GAUSSIAN_PREFLIGHT_CLI), str(source), "--fix", "--output", str(fixed), "--chk", "fixed.chk")
    text = fixed.read_text(encoding="utf-8")
    assert "%chk=fixed.chk" in text
    assert "/gen " in text.lower()
    assert "-H -C 0" not in text
    assert "H C 0" in text


def test_migrated_gaussian_preflight_keeps_pretty_json(tmp_path: Path) -> None:
    source = tmp_path / "ok.gjf"
    source.write_text(
        "%chk=ok.chk\n"
        "# M062X/6-31G(d) opt\n\n"
        "ok\n\n"
        "0 1\n"
        "H 0 0 0\n\n\n",
        encoding="utf-8",
    )

    result = run_cli(str(GAUSSIAN_PREFLIGHT_CLI), str(source))
    assert result.stdout.count("\n") > 1
    assert json.loads(result.stdout) == {"fixed": False, "output": None, "warnings": []}


def test_migrated_prepare_gaussian_uses_backend_and_keeps_cli_contract(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    output = tmp_path / "candidate.gjf"
    xyz.write_text(
        "2\n"
        "candidate title\n"
        "H 0 0 0\n"
        "H 0 0 0.74\n",
        encoding="utf-8",
    )

    result = run_cli(
        str(PREPARE_GAUSSIAN_CLI),
        str(xyz),
        str(output),
        "--route",
        "M062X/6-31G(d) opt=(ts,calcfc) freq",
        "--nproc",
        "4",
        "--mem",
        "8GB",
        "--chk",
        "candidate.chk",
    )

    payload = json.loads(result.stdout)
    text = output.read_text(encoding="utf-8")
    assert result.stdout.count("\n") > 1
    assert payload == {"atoms": 2, "chk": "candidate.chk", "frame": 0, "output": str(output)}
    assert text.startswith("%chk=candidate.chk\n%nprocshared=4\n%mem=8GB\n#P M062X/6-31G(d)")
    assert "candidate title\n\n0 1\n" in text
    assert "H         0.00000000       0.00000000       0.74000000" in text


def test_migrated_descriptor_extract_smoke(tmp_path: Path) -> None:
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

    result = run_cli(
        str(DESCRIPTOR_CLI),
        "--ts-out",
        str(ts_out),
        "--ts-xyz",
        str(ts_xyz),
        "--minus-xyz",
        str(minus_xyz),
        "--plus-xyz",
        str(plus_xyz),
        "-o",
        str(output),
        "--pairs",
        "1-2",
    )
    payload = json.loads(result.stdout)
    assert payload["validation"]["imaginary_frequency_count"] == 1
    assert (output / "ts_descriptors.json").exists()
    assert (output / "reaction_center_distances.csv").exists()
