"""Pure-function unit tests for the ase_neb subpackage.

The subpackage was extracted from one 3400-line file; this module locks the
public behavior of the leaf modules (geometry, mechanism, config, workspace,
driver, validation) at the function level, independent of ASE or any
workspace-on-disk state. Anything that needs ASE installed is *not* tested
here — that belongs to integration tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.chem.geometry import (  # noqa: E402
    angle_degrees,
    dihedral_degrees,
    parse_angle_spec as parse_chem_angle_spec,
    parse_bond_spec as parse_chem_bond_spec,
    vector_norm,
)
from transition_state_workflow.tools.ase_neb.coerce import (  # noqa: E402
    as_mapping,
    as_positive_int,
)
from transition_state_workflow.tools.ase_neb.config import (  # noqa: E402
    input_node_id,
    level_slug_from_calculator,
    level_slug_from_gaussian_config,
    neb_node_id,
    normalize_config,
    safe_slug,
)
from transition_state_workflow.tools.ase_neb.errors import ConfigError  # noqa: E402
from transition_state_workflow.tool.ase_neb.driver import (  # noqa: E402
    AseNebPreparationResult,
    AseNebRuntimeRequest,
    evaluate_neb_candidate_quality,
    force_max,
)
from transition_state_workflow.tool.ase_neb.external_gaussian import (  # noqa: E402
    AseNebConfigError,
    ExternalGaussianCalculatorRequest,
    ExternalGaussianNebRuntimeRequest,
    ExternalGaussianRun,
    continue_node_id_from_images,
    external_gaussian_level_slug,
    require_external_gaussian_force_route,
)
from transition_state_workflow.tools.ase_neb.geometry import (  # noqa: E402
    Atom,
    angle_label,
    atom_indices_from_bonds_angles,
    bond_label,
    bonded_pairs,
    changed_bonds,
    covalent_cutoff,
    distance,
    fragment_labels,
    infer_angles,
    neighbor_map,
    parse_angle_spec,
    parse_bond_spec,
    read_xyz,
)
from transition_state_workflow.tools.ase_neb.mechanism import (  # noqa: E402
    ENDPOINT_READY_STATES,
    classify_validation_system,
    endpoint_validation_summary,
)
from transition_state_workflow.gate.neb_candidate import (  # noqa: E402
    build_validation_policy as build_gate_validation_policy,
)
from transition_state_workflow.tool.ase_neb.validation import (  # noqa: E402
    build_validation_policy,
    create_gaussian_refine_node as create_tool_gaussian_refine_node,
    default_validation_parent as tool_default_validation_parent,
    displacement_ladder,
    irc_policy,
    resolve_candidate as tool_resolve_candidate,
    threshold_policy,
    write_gaussian_input as write_ase_neb_gaussian_input,
)
from transition_state_workflow.core.ase_neb_validation import (  # noqa: E402
    create_validation_plan_node as create_core_validation_plan_node,
    latest_promotable_candidate as core_latest_promotable_candidate,
    resolve_candidate as core_resolve_candidate,
)
from transition_state_workflow.core.ase_neb_workspace import (  # noqa: E402
    next_node_id,
    node_record,
    read_tree,
    write_json,
)


# --- geometry ---------------------------------------------------------------

def test_distance_and_covalent_cutoff_are_symmetric() -> None:
    a = Atom("C", 0.0, 0.0, 0.0)
    b = Atom("H", 1.09, 0.0, 0.0)
    assert distance(a, b) == pytest.approx(1.09)
    assert covalent_cutoff(a, b) == pytest.approx(covalent_cutoff(b, a))


def test_core_geometry_reports_angles_dihedrals_and_vector_norms() -> None:
    a = Atom("C", 1.0, 0.0, 0.0)
    b = Atom("C", 0.0, 0.0, 0.0)
    c = Atom("C", 0.0, 1.0, 0.0)
    d = Atom("C", 0.0, 1.0, 1.0)

    assert vector_norm((0.0, 3.0, 4.0)) == pytest.approx(5.0)
    assert angle_degrees(a, b, c) == pytest.approx(90.0)
    assert dihedral_degrees(a, b, c, d) == pytest.approx(-90.0)


def test_bonded_pairs_finds_one_c_h_bond_at_typical_distance() -> None:
    atoms = [Atom("C", 0.0, 0.0, 0.0), Atom("H", 1.09, 0.0, 0.0)]
    assert bonded_pairs(atoms) == {(1, 2)}


def test_bonded_pairs_drops_far_atoms_outside_cutoff() -> None:
    atoms = [Atom("C", 0.0, 0.0, 0.0), Atom("C", 10.0, 0.0, 0.0)]
    assert bonded_pairs(atoms) == set()


def test_changed_bonds_identifies_formed_and_broken_pairs() -> None:
    # Reactant: H1-H2 bond. Product: H1 and H2 separated; no bond.
    reactant = [Atom("H", 0.0, 0.0, 0.0), Atom("H", 0.74, 0.0, 0.0)]
    product = [Atom("H", 0.0, 0.0, 0.0), Atom("H", 5.0, 0.0, 0.0)]
    out = changed_bonds(reactant, product)
    assert out["broken"] == [(1, 2)]
    assert out["formed"] == []


def test_changed_bonds_uses_user_bonds_verbatim_when_supplied() -> None:
    atoms = [Atom("C", 0.0, 0.0, 0.0), Atom("H", 1.09, 0.0, 0.0)]
    out = changed_bonds(atoms, atoms, user_bonds=[(2, 1)])
    assert out == {"user": [(2, 1)], "formed": [], "broken": []}


def test_parse_bond_and_angle_specs_accept_dash_colon_comma() -> None:
    assert parse_bond_spec("4-12") == (4, 12)
    assert parse_bond_spec("4:12") == (4, 12)
    assert parse_chem_bond_spec("4,12") == (4, 12)
    assert parse_angle_spec("4-12-7") == (4, 12, 7)
    assert parse_chem_angle_spec("4:12:7") == (4, 12, 7)
    with pytest.raises(ConfigError):
        parse_bond_spec("4-4")  # i == j


def test_atom_indices_from_bonds_angles_is_sorted_unique() -> None:
    bonds = [(3, 7), (1, 7)]
    angles = [(3, 7, 1)]
    assert atom_indices_from_bonds_angles(bonds, angles) == [1, 3, 7]


def test_bond_and_angle_labels_are_dash_joined() -> None:
    assert bond_label((1, 2)) == "1-2"
    assert angle_label((1, 2, 3)) == "1-2-3"


def test_neighbor_map_is_symmetric_and_covers_all_indices() -> None:
    atoms = [
        Atom("C", 0.0, 0.0, 0.0),
        Atom("H", 1.09, 0.0, 0.0),
        Atom("H", -1.09, 0.0, 0.0),
    ]
    neighbors = neighbor_map(atoms)
    assert neighbors == {1: {2, 3}, 2: {1}, 3: {1}}


def test_fragment_labels_group_connected_components() -> None:
    # Two H2 molecules, far apart.
    atoms = [
        Atom("H", 0.0, 0.0, 0.0),
        Atom("H", 0.74, 0.0, 0.0),
        Atom("H", 5.0, 0.0, 0.0),
        Atom("H", 5.74, 0.0, 0.0),
    ]
    labels = fragment_labels(atoms)
    assert len(labels) == 2
    assert all(label.startswith("H2:") for label in labels)


def test_infer_angles_returns_only_user_supplied_when_given() -> None:
    atoms = [Atom("C", 0.0, 0.0, 0.0), Atom("H", 1.0, 0.0, 0.0)]
    assert infer_angles(atoms, atoms, [], user_angles=[(1, 2, 3)]) == [(1, 2, 3)]


def test_read_xyz_round_trips_simple_two_atom_file(tmp_path: Path) -> None:
    path = tmp_path / "h2.xyz"
    path.write_text("2\nh2\nH 0.0 0.0 0.0\nH 0.74 0.0 0.0\n", encoding="utf-8")
    atoms, comment = read_xyz(path)
    assert comment == "h2"
    assert len(atoms) == 2
    assert atoms[1].x == pytest.approx(0.74)


def test_read_xyz_rejects_truncated_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.xyz"
    path.write_text("3\ntitle\nH 0 0 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_xyz(path)


# --- mechanism --------------------------------------------------------------

def test_classify_validation_system_detects_metal_h_transfer_and_default() -> None:
    h_atom = Atom("H", 0.0, 0.0, 0.0)
    metal_atom = Atom("Fe", 0.0, 0.0, 0.0)
    c_atom = Atom("C", 0.0, 0.0, 0.0)
    assert classify_validation_system([h_atom, metal_atom], [(1, 2)]) == "metal"
    assert classify_validation_system([h_atom, c_atom], [(1, 2)]) == "h_transfer"
    assert classify_validation_system([c_atom, c_atom], [(1, 2)]) == "small_rigid"


def test_classify_validation_system_override_short_circuits_inference() -> None:
    h_atom = Atom("H", 0.0, 0.0, 0.0)
    metal_atom = Atom("Fe", 0.0, 0.0, 0.0)
    assert classify_validation_system([h_atom, metal_atom], [(1, 2)], override="flexible") == "flexible"


def test_endpoint_validation_summary_defaults_to_reference_hypothesis() -> None:
    out = endpoint_validation_summary({})
    assert out["reactant_state"] == "reference_hypothesis"
    assert out["product_state"] == "reference_hypothesis"
    assert out["endpoint_minima_ready"] is False
    assert sorted(out["allowed_ready_states"]) == sorted(ENDPOINT_READY_STATES)


def test_endpoint_validation_summary_marks_ready_when_both_declared() -> None:
    cfg = {
        "endpoint_validation": {
            "reactant_state": "validated_minimum",
            "product_state": "lower_level_minimum",
        }
    }
    assert endpoint_validation_summary(cfg)["endpoint_minima_ready"] is True


# --- validation policy ------------------------------------------------------

def test_displacement_ladder_adds_small_step_for_low_frequency() -> None:
    base = displacement_ladder("flexible", None)
    extended = displacement_ladder("flexible", -50.0)
    assert 0.08 in extended
    assert 0.08 not in base


def test_threshold_policy_widens_for_metal_and_flexible_systems() -> None:
    metal = threshold_policy("metal")
    rigid = threshold_policy("small_rigid")
    assert metal["heavy_atom_rmsd_a"]["pass"] > rigid["heavy_atom_rmsd_a"]["pass"]


def test_irc_policy_is_required_when_publication_grade_or_flags() -> None:
    policy = irc_policy(
        system_class="small_rigid",
        bonds=[(1, 2)],
        imaginary_frequency=-500.0,
        publication_grade=True,
        force_irc=False,
        flags=[],
    )
    assert policy["policy"] == "required"


def test_irc_policy_is_optional_for_strong_endpoint_in_small_rigid() -> None:
    policy = irc_policy(
        system_class="small_rigid",
        bonds=[(1, 2)],
        imaginary_frequency=-500.0,
        publication_grade=False,
        force_irc=False,
        flags=[],
    )
    assert policy["policy"] == "optional_after_strong_endpoint_match"


def test_validation_policy_gate_matches_tool_adapter(tmp_path: Path) -> None:
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    reactant.write_text("2\nr\nH 0 0 0\nH 0.74 0 0\n", encoding="utf-8")
    product.write_text("2\np\nH 0 0 0\nH 2.00 0 0\n", encoding="utf-8")

    kwargs = {
        "user_bonds": [(1, 2)],
        "system_class_override": "h_transfer",
        "imaginary_frequency": -50.0,
        "publication_grade": False,
        "force_irc": False,
        "risk_flags": [],
    }
    gate_policy = build_gate_validation_policy(reactant, product, **kwargs)
    tool_policy = build_validation_policy(reactant, product, **kwargs)

    assert tool_policy == gate_policy
    assert gate_policy["system_class"] == "h_transfer"
    assert gate_policy["reaction_center"]["tracked_bonds"] == ["1-2"]
    assert 0.08 in gate_policy["imaginary_mode_follow"]["displacement_ladder_max_atom_a"]


def test_validation_policy_tool_adapter_preserves_config_error(tmp_path: Path) -> None:
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    reactant.write_text("2\nr\nH 0 0 0\nH 0.74 0 0\n", encoding="utf-8")
    product.write_text("1\np\nH 0 0 0\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        build_validation_policy(reactant, product)


def test_validation_gaussian_input_adapter_delegates_to_backend(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    output = tmp_path / "candidate.gjf"
    xyz.write_text("2\ncandidate\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")

    written = write_ase_neb_gaussian_input(
        xyz,
        output,
        {
            "route": "# M062X/6-31G(d) opt=(ts,calcfc) freq",
            "charge": 1,
            "multiplicity": 2,
        },
    )

    text = output.read_text(encoding="utf-8")
    assert written == output
    assert "# M062X/6-31G(d) opt=(ts,calcfc) freq\n\nTS candidate from ASE NEB\n\n1 2\n" in text


def test_validation_gaussian_input_adapter_preserves_config_error(tmp_path: Path) -> None:
    bad_xyz = tmp_path / "bad.xyz"
    bad_xyz.write_text("not xyz\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        write_ase_neb_gaussian_input(bad_xyz, tmp_path / "candidate.gjf", {})


def test_core_validation_resolves_promotable_candidate_and_tool_errors(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    candidate_dir = root / "nodes" / "n010_neb_xtb" / "candidates"
    candidate_dir.mkdir(parents=True)
    xyz = candidate_dir / "cand_001.xyz"
    xyz.write_text("2\ncandidate\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")
    write_json(
        candidate_dir / "cand_001.json",
        {
            "candidate_id": "cand_001",
            "xyz": "nodes/n010_neb_xtb/candidates/cand_001.xyz",
            "candidate_quality": {"accepted_for_promotion": True},
        },
    )

    assert core_latest_promotable_candidate(root) == ("n010_neb_xtb", "cand_001")
    assert core_resolve_candidate(root, source_node_id=None, candidate_id=None) == (
        "n010_neb_xtb",
        "cand_001",
        xyz,
    )
    assert tool_default_validation_parent(root) == "n010_neb_xtb"

    with pytest.raises(ConfigError):
        tool_resolve_candidate(tmp_path / "empty", source_node_id=None, candidate_id=None)


def test_tool_gaussian_refine_node_uses_core_state_writer(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    candidate = tmp_path / "candidate.xyz"
    candidate.write_text("2\ncandidate\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")

    node_id, gjf = create_tool_gaussian_refine_node(
        root,
        source_node_id="n010_neb_xtb",
        candidate_id="cand_001",
        candidate_xyz=candidate,
        gaussian_cfg={
            "route": "# M062X/6-31G(d) opt=(ts,calcfc) freq",
            "charge": 0,
            "multiplicity": 1,
        },
    )

    node_dir = root / "nodes" / node_id
    node = json.loads((node_dir / "node.json").read_text(encoding="utf-8"))
    assert gjf == node_dir / "inputs" / "ts_candidate_ts_freq.gjf"
    assert gjf.exists()
    assert (node_dir / "structures" / "source_candidate.xyz").exists()
    assert node["stage"] == "gaussian_tsfreq_input"
    assert node["parent_id"] == "n010_neb_xtb"
    assert node["inputs"]["ts_freq_gjf"] == str(gjf)
    assert "run_gaussian_tsfreq" in (node_dir / "reflection.md").read_text(encoding="utf-8")
    tree = read_tree(root)
    assert tree["nodes"][node_id]["parent_id"] == "n010_neb_xtb"
    assert node_id in tree["active_frontier"]


def test_core_validation_plan_node_writes_policy_state(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    reactant.write_text("2\nr\nH 0 0 0\nH 0.74 0 0\n", encoding="utf-8")
    product.write_text("2\np\nH 0 0 0\nH 2.00 0 0\n", encoding="utf-8")
    policy = build_gate_validation_policy(
        reactant,
        product,
        user_bonds=[(1, 2)],
        system_class_override="h_transfer",
    )

    node_id, policy_path = create_core_validation_plan_node(
        root,
        parent_node_id="n020_gaussian_tsfreq",
        policy=policy,
    )

    node_dir = root / "nodes" / node_id
    node = json.loads((node_dir / "node.json").read_text(encoding="utf-8"))
    assert policy_path == node_dir / "validation_policy.json"
    assert node["stage"] == "validation_plan"
    assert node["parent_id"] == "n020_gaussian_tsfreq"
    assert node["policy_file"] == str(policy_path)
    assert "run_mode_endpoint_validation" in (node_dir / "reflection.md").read_text(encoding="utf-8")
    assert read_tree(root)["nodes"][node_id]["stage"] == "validation_plan"


# --- config -----------------------------------------------------------------

def test_safe_slug_lowercases_and_strips_special_chars() -> None:
    assert safe_slug("M06-2X") == "m06_2x"
    assert safe_slug("def2-SVP+*") == "def2_svpp"
    assert safe_slug("") == "item"
    assert safe_slug("", default="fallback") == "fallback"


def test_as_mapping_returns_empty_dict_for_none() -> None:
    assert as_mapping(None, "x") == {}
    assert as_mapping({"a": 1}, "x") == {"a": 1}
    with pytest.raises(ConfigError):
        as_mapping(["not a dict"], "x")


def test_as_positive_int_rejects_zero_negatives_and_non_int() -> None:
    assert as_positive_int(5, "x") == 5
    with pytest.raises(ConfigError):
        as_positive_int(0, "x")
    with pytest.raises(ConfigError):
        as_positive_int(-1, "x")
    with pytest.raises(ConfigError):
        as_positive_int(1.5, "x")


def test_normalize_config_rejects_missing_reactant_product() -> None:
    with pytest.raises(ConfigError):
        normalize_config({"reactant": "", "product": "p.xyz", "output": "out"})


def test_normalize_config_demands_at_least_three_images() -> None:
    with pytest.raises(ConfigError):
        normalize_config({"reactant": "r.xyz", "product": "p.xyz", "output": "out", "images": 2})


def test_input_node_id_is_fixed() -> None:
    assert input_node_id() == "n000_input_check"


def test_neb_node_id_includes_calculator_type_and_climb_flag() -> None:
    cfg = {
        "calculator": {"type": "xtb", "method": "GFN2-xTB", "params": {}},
        "interpolation": "idpp",
        "neb": {"climb": True},
        "project": {},
    }
    node_id = neb_node_id(cfg)
    assert node_id.startswith("n010_neb_xtb_")
    assert "_ci" in node_id


def test_level_slug_from_calculator_handles_xtb_and_gaussian() -> None:
    xtb_cfg = {"type": "xtb", "method": "GFN2-xTB", "params": {}}
    assert level_slug_from_calculator(xtb_cfg) == "gfn2_xtb"
    gaussian_cfg = {"type": "gaussian", "params": {"method": "M062X", "basis": "def2SVP"}}
    assert "m062x" in level_slug_from_calculator(gaussian_cfg)


def test_level_slug_from_gaussian_config_extracts_method_basis_from_route() -> None:
    cfg = {"route": "# M062X/def2SVP opt=(ts,calcfc) freq"}
    assert "m062x" in level_slug_from_gaussian_config(cfg)


# --- workspace --------------------------------------------------------------

def test_node_record_succeeded_neb_stage_is_candidate_found() -> None:
    record = node_record(
        node_id="n010_neb_xtb_gfn2_xtb_idpp",
        parent_id=None,
        node_type="neb",
        hypothesis="test",
        changed_variables=None,
        status="succeeded",
        evidence=None,
        decision="test",
        stage="neb",
    )
    assert record["claim_status"] == "candidate_found"
    assert record["outcome"] == "candidate_generated"


def test_node_record_ambiguous_with_chemical_failure_code_routes_to_rejected() -> None:
    record = node_record(
        node_id="n010",
        parent_id=None,
        node_type="neb",
        hypothesis="test",
        changed_variables=None,
        status="ambiguous",
        evidence=None,
        decision="test",
        failure_type="neb_endpoint_candidate",
        stage="neb",
    )
    assert record["claim_status"] == "rejected"
    assert record["outcome"] == "chemical_failure"


def test_node_record_ambiguous_with_numerical_failure_code_stays_not_evaluated() -> None:
    record = node_record(
        node_id="n010",
        parent_id=None,
        node_type="neb",
        hypothesis="test",
        changed_variables=None,
        status="ambiguous",
        evidence=None,
        decision="test",
        failure_type="endpoint_minima_missing",
        stage="neb",
    )
    assert record["claim_status"] == "not_evaluated"
    assert record["outcome"] == "numerical_failure"


def test_next_node_id_increments_by_ten_from_max_existing(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes"
    (nodes / "n000_input_check").mkdir(parents=True)
    (nodes / "n010_neb").mkdir()
    (nodes / "n030_other").mkdir()
    out = next_node_id(tmp_path, "validation_plan")
    assert out == "n040_validation_plan"


def test_next_node_id_falls_back_to_start_when_directory_is_empty(tmp_path: Path) -> None:
    (tmp_path / "nodes").mkdir()
    assert next_node_id(tmp_path, "candidate", start=25) == "n025_candidate"


# --- driver -----------------------------------------------------------------

def test_force_max_returns_max_norm_over_atom_forces() -> None:
    forces = [(3.0, 4.0, 0.0), (1.0, 0.0, 0.0)]
    assert force_max(forces) == pytest.approx(5.0)


def test_force_max_returns_nan_when_forces_unavailable() -> None:
    import math

    assert math.isnan(force_max(None))


def test_evaluate_neb_candidate_quality_lists_codes_in_priority_order() -> None:
    # Endpoint not ready + not converged + zero barrier all true:
    # endpoint_minima_missing must be reported first (prerequisite check).
    summary = {"images": 5, "ts_candidate_index": 2, "barrier_ev_relative_to_reactant": 0.0}
    out = evaluate_neb_candidate_quality(summary, {}, optimizer_converged=False)
    assert out["accepted_for_promotion"] is False
    assert out["outcome_code"] == "endpoint_minima_missing"
    assert "endpoint_minima_missing" in out["failure_codes"]


def test_evaluate_neb_candidate_quality_passes_internal_max_at_steady_endpoints() -> None:
    cfg = {
        "endpoint_validation": {
            "reactant_state": "validated_minimum",
            "product_state": "validated_minimum",
        }
    }
    summary = {"images": 7, "ts_candidate_index": 3, "barrier_ev_relative_to_reactant": 0.5}
    out = evaluate_neb_candidate_quality(summary, cfg, optimizer_converged=True)
    assert out["accepted_for_promotion"] is True
    assert out["outcome_code"] is None


def test_ase_neb_runtime_request_exposes_optimizer_and_env() -> None:
    cfg = {
        "optimizer": {"name": "BFGS", "fmax": 0.05, "steps": 5},
        "calculator": {"type": "xtb", "env": {"OMP_NUM_THREADS": "2"}},
    }
    runtime = AseNebRuntimeRequest(cfg=cfg)
    assert runtime.optimizer_cfg == cfg["optimizer"]
    assert runtime.env == {"OMP_NUM_THREADS": "2"}
    assert runtime.trajectory_name == "neb.traj"
    assert runtime.logfile_name == "neb.log"


def test_ase_neb_preparation_result_reports_initial_image_count() -> None:
    result = AseNebPreparationResult(
        reactant="reactant",
        product="product",
        images=["reactant", "midpoint", "product"],
    )

    assert result.initial_image_count == 3
    assert result.reactant == "reactant"
    assert result.product == "product"


# --- external Gaussian (pure helpers) --------------------------------------

def test_external_gaussian_level_slug_extracts_method_basis_from_route() -> None:
    # Regression: this used re.search but external_gaussian.py once forgot to
    # ``import re``, so any external-Gaussian continuation crashed at call time.
    assert external_gaussian_level_slug("# wb97xd/def2tzvp force") == "wb97xd_def2tzvp"


def test_external_gaussian_level_slug_falls_back_without_method_basis() -> None:
    assert external_gaussian_level_slug("# force") == "gaussian_external"


def test_continue_node_id_from_images_builds_node_id(tmp_path: Path) -> None:
    (tmp_path / "nodes").mkdir()
    node_id = continue_node_id_from_images(tmp_path, "# wb97xd/def2tzvp force")
    assert node_id.startswith("n")
    assert "neb_gaussian_external_wb97xd_def2tzvp_from_images" in node_id


def test_external_gaussian_calculator_request_reads_tail_file(tmp_path: Path) -> None:
    tail_file = tmp_path / "tail.gjf"
    tail_file.write_text("H C 0\n6-31G\n****\n", encoding="utf-8")
    request = ExternalGaussianCalculatorRequest(
        route="# wb97xd/def2tzvp force",
        charge=0,
        multiplicity=1,
        template_gjf=None,
        tail_file=tail_file,
        command="g16",
        mem="8GB",
        nprocshared=4,
        require_normal_termination=True,
        output_suffix=".out",
    )

    assert request.tail() == "H C 0\n6-31G\n****\n"


def test_external_gaussian_force_route_validation_lives_in_backend() -> None:
    require_external_gaussian_force_route("# wb97xd/def2tzvp force")
    with pytest.raises(AseNebConfigError):
        require_external_gaussian_force_route("# wb97xd/def2tzvp opt")


def test_external_gaussian_run_delegates_runtime_request(tmp_path: Path) -> None:
    tail_file = tmp_path / "tail.gjf"
    tail_file.write_text("basis\n", encoding="utf-8")
    run = ExternalGaussianRun(
        project_root=tmp_path / "tssearch_ext",
        xyz_dir=tmp_path / "images",
        pattern="final_*.xyz",
        route="# wb97xd/def2tzvp force",
        charge=1,
        multiplicity=2,
        template_gjf=None,
        tail_file=tail_file,
        command="g16",
        mem="4GB",
        nprocshared=2,
        neb_cfg={"climb": True},
        optimizer_cfg={"name": "BFGS", "fmax": 0.05, "steps": 1},
        candidate_selection={"min_barrier_ev": 0.1},
        endpoint_validation={"reactant_state": "validated_minimum"},
        parent_node_id="n000_input_check",
        require_normal_termination=False,
        output_suffix="log",
    )

    runtime = run.calculator_request()
    assert isinstance(runtime, ExternalGaussianCalculatorRequest)
    assert runtime.route == run.route
    assert runtime.charge == 1
    assert runtime.multiplicity == 2
    assert runtime.tail() == "basis\n"
    assert run.tail() == runtime.tail()
    neb_runtime = run.runtime_request()
    assert isinstance(neb_runtime, ExternalGaussianNebRuntimeRequest)
    assert neb_runtime.calculator_request == runtime
    assert neb_runtime.quality_config() == {
        "candidate_selection": {"min_barrier_ev": 0.1},
        "endpoint_validation": {"reactant_state": "validated_minimum"},
    }
    assert run.cfg()["source_xyz_dir"] == str(run.xyz_dir)
    assert run.cfg()["output_suffix"] == "log"


def test_write_external_gaussian_neb_node_full_artifacts(tmp_path: Path) -> None:
    # Exercises the refactored candidate writer end-to-end (no ASE needed): it
    # builds node.json/config.json/validation.json + evidence + report +
    # reflection + tree state via finalize_node_report_and_tree.
    import json

    from transition_state_workflow.tool.ase_neb.external_gaussian import (
        write_external_gaussian_neb_node,
    )
    from transition_state_workflow.core.ase_neb_workspace import read_tree

    root = tmp_path / "tssearch_ext"
    cfg = {
        "source_xyz_dir": "/src",
        "xyz_pattern": "final_image_*.xyz",
        "route": "# wb97xd/def2tzvp force",
        "charge": 0,
        "multiplicity": 1,
        "command": "g16",
        "mem": None,
        "nprocshared": None,
        "neb": {"climb": True},
        "optimizer": {"name": "BFGS", "fmax": 0.05, "steps": 1},
        "candidate_selection": {},
        "require_normal_termination": True,
        "output_suffix": ".out",
    }
    summary = {
        "candidate_id": "cand_001",
        "ts_candidate_index": 3,
        "barrier_ev_relative_to_reactant": 0.4,
        "candidate_json": str(root / "nodes" / "n010_x" / "candidates" / "cand_001.json"),
        "candidate_quality": {"accepted_for_promotion": True, "reasons": ["ok"]},
    }
    node_dir = write_external_gaussian_neb_node(
        root,
        "n010_neb_gaussian_external",
        parent_node_id="n000_input_check",
        status="succeeded",
        cfg=cfg,
        source_files=[Path("/src/final_image_00.xyz"), Path("/src/final_image_01.xyz")],
        summary=summary,
    )
    for fname in ("node.json", "config.json", "validation.json", "report.md", "reflection.md"):
        assert (node_dir / fname).exists()
    # summary present + accepted -> full reflection, not template.
    assert "Computational Outcome" in (node_dir / "reflection.md").read_text(encoding="utf-8")
    node = json.loads((node_dir / "node.json").read_text(encoding="utf-8"))
    assert node["stage"] == "gaussian_external_neb"
    tree = read_tree(root)
    assert "n010_neb_gaussian_external" in tree["nodes"]


def test_ensure_external_gaussian_project_writes_skeleton_with_entry(tmp_path: Path) -> None:
    import json

    from transition_state_workflow.tool.ase_neb.external_gaussian import (
        ensure_external_gaussian_project,
    )

    root = tmp_path / "tssearch_ext"
    ensure_external_gaussian_project(root)
    # Shared skeleton: the four dirs + the three root files.
    for dirname in ("inputs", "nodes", "accepted", "rejected"):
        assert (root / dirname).is_dir()
    for fname in ("manifest.json", "evidence_registry.json", "tree.json", "README.md"):
        assert (root / fname).exists()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["node_schema"] == "ts-node-v2"
    # The external-Gaussian path layers its own manifest extra on the skeleton.
    assert manifest["entry"] == "external_gaussian_neb_from_existing_images"


def test_finalize_node_report_and_tree_writes_report_template_and_registers(tmp_path: Path) -> None:
    import json

    from transition_state_workflow.core.ase_neb_workspace import (
        finalize_node_report_and_tree,
        read_tree,
    )

    root = tmp_path / "ws"
    (root / "nodes" / "n010_x").mkdir(parents=True)
    node = {"node_id": "n010_x", "stage": "neb", "parent_id": "n000_root"}
    finalize_node_report_and_tree(
        root,
        root / "nodes" / "n010_x",
        "n010_x",
        node,
        parent="n000_root",
        stage="neb",
        status="pending",
        report_body="# Report\n\n- ok\n",
        reflection=None,
        reflection_decision="run_candidate",
    )
    report = (root / "nodes" / "n010_x" / "report.md").read_text(encoding="utf-8")
    assert "# Report" in report
    reflection = (root / "nodes" / "n010_x" / "reflection.md").read_text(encoding="utf-8")
    # No reflection texts supplied -> the template, carrying the decision.
    assert "run_candidate" in reflection
    tree = read_tree(root)
    assert "n010_x" in tree["nodes"]
    assert "n010_x" in tree["active_frontier"]  # pending -> frontier


def test_finalize_node_report_and_tree_writes_full_reflection_when_texts_given(tmp_path: Path) -> None:
    from transition_state_workflow.core.ase_neb_workspace import finalize_node_report_and_tree

    root = tmp_path / "ws"
    (root / "nodes" / "n020_y").mkdir(parents=True)
    finalize_node_report_and_tree(
        root,
        root / "nodes" / "n020_y",
        "n020_y",
        {"node_id": "n020_y"},
        parent="n010_x",
        stage="neb",
        status="succeeded",
        report_body="# R\n",
        reflection={
            "computational_outcome": "done",
            "mechanistic_implication": "implies",
            "knowledge_update": "learned",
            "next_branch": "next",
        },
    )
    reflection = (root / "nodes" / "n020_y" / "reflection.md").read_text(encoding="utf-8")
    # Full reflection sections, not the template.
    assert "Computational Outcome" in reflection
    assert "done" in reflection and "implies" in reflection


def test_ensure_tree_skeleton_is_idempotent_and_omits_entry_by_default(tmp_path: Path) -> None:
    import json

    from transition_state_workflow.core.ase_neb_workspace import ensure_tree_skeleton

    root = tmp_path / "ws"
    ensure_tree_skeleton(root, system_slug="sys", readme_body="# test\n")
    # Second call must not raise or overwrite (idempotent).
    (root / "manifest.json").write_text('{"sentinel": true}', encoding="utf-8")
    ensure_tree_skeleton(root, system_slug="sys", readme_body="# test\n")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"sentinel": True}  # preserved, not rewritten
    fresh = tmp_path / "ws2"
    ensure_tree_skeleton(fresh, system_slug="sys", readme_body="# test\n")
    base_manifest = json.loads((fresh / "manifest.json").read_text(encoding="utf-8"))
    assert "entry" not in base_manifest
