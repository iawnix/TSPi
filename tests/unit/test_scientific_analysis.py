from __future__ import annotations

import json
import math
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.analysis.engine import Inputs, evaluate, outcome
from ts_agent.analysis.catalog import DESCRIPTORS
from ts_agent.analysis.thermochemistry import R_KJ, HARTREE_KJ_MOL
from ts_agent.compute.analysis import run_analysis
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.workspace.candidates import load_finding_candidate, FindingCandidateError


def source(**roles):
    bindings, payloads = {}, {}
    for role, values in roles.items():
        values = values if isinstance(values, list) else [values]
        bindings[role] = []
        for value in values:
            identifier = f"art_{len(payloads):024x}"
            payloads[identifier] = (value if isinstance(value, str) else json.dumps(value)).encode()
            bindings[role].append({"artifact_id": identifier})
    return Inputs(bindings, payloads)


def reaction():
    return evaluate("reaction.parse", source(), {"reaction_smiles": "CCl.[OH-]>>CO.[Cl-]", "multiplicities": {"reactants": [1, 1], "products": [1, 1]}})


def request(node, capability, parameters, inputs=None):
    return {"schema_version": "ts-analysis-request/1", "node_id": node, "capability": capability, "capability_version": "1", "parameters": parameters, "input_artifacts": inputs or {}}


def gaussian_log(*, imaginary=False, temperature=298.15, method="HF/STO-3G", spacing=0.74, monatomic=False):
    geometry = [" 1 1 0 0.0 0.0 0.0"] if monatomic else [" 1 1 0 0.0 0.0 0.0", f" 2 1 0 {spacing} 0.0 0.0"]
    return "\n".join([
        " #P " + method + " Opt Freq", " ------------------", " Charge = 0 Multiplicity = " + ("2" if monatomic else "1"),
        " Standard orientation:", " -----", " Center Atomic Atomic Coordinates (Angstroms)", " Number Number Type X Y Z", " -----", *geometry, " -----",
        " SCF Done: E(RHF) = -1.100000000 A.U.",
        " Maximum Force 0.000001 0.000450 YES", " RMS Force 0.000001 0.000300 YES",
        " Maximum Displacement 0.000001 0.001800 YES", " RMS Displacement 0.000001 0.001200 YES",
        " Stationary point found.",
        *([] if monatomic else [f" Frequencies -- {'-1000.0' if imaginary else '4400.0'}", " Red. masses -- 1.0", " Atom AN X Y Z", " 1 1 -0.5 0.0 0.0", " 2 1 0.5 0.0 0.0"]),
        " Thermochemistry", f" Temperature {temperature:.3f} Kelvin. Pressure 1.00000 Atm.",
        " Zero-point correction= 0.010000", " Thermal correction to Enthalpy= 0.015000",
        " Thermal correction to Gibbs Free Energy= -0.005000", " Normal termination of Gaussian 16", "",
    ])


def thermo_parameters(**changes):
    return {"species_key": "H2", "quantity": "G", "conditions": {"temperature_k": 298.15, "phase": "gas",
            "source_standard_state": {"kind": "pressure", "value": 1, "unit": "atm"}, "standard_state": {"kind": "concentration", "value": 1, "unit": "mol/L"}},
            "methods": {"electronic": "HF/STO-3G"}, "electronic_state": {"charge": 0, "multiplicity": 1}, "stationary_kind": "minimum", **changes}


def thermal_record(key, value, elements, *, ts=False):
    params = thermo_parameters()
    return outcome("ts-thermochemical-result/1", {"species_key": key, "quantity": "G", "value": value, "unit": "kJ/mol",
        "conditions": params["conditions"], "methods": params["methods"], "model": {"kind": "parsed"}, "element_counts": elements,
        "electronic_state": {"charge": 0, "multiplicity": 1}, "stationary_kind": "transition_state" if ts else "minimum"})


def barrier(order=1, activation=50):
    reactants = [thermal_record("A", 0, {"H": 2})]
    if order == 2:
        reactants.append(thermal_record("B", 0, {"O": 1}))
    elements = {"H": 2, **({"O": 1} if order == 2 else {})}
    return evaluate("barrier.evaluate", source(reactants=reactants, products=thermal_record("P", -10, elements), transition_state=thermal_record("TS", activation, elements, ts=True)), {})


def test_reaction_conservation_mapping_and_changes():
    spec = reaction()
    assert spec["verdict"] == "valid"
    maps = evaluate("reaction.mapping.generate", source(reaction=spec), {"max_states": 10000})
    assert len(maps["data"]["candidates"]) >= 1
    assert maps["data"]["ambiguity"]  # equivalent methyl hydrogens
    with pytest.raises(ValueError, match="candidate_index"):
        evaluate("reaction.bond_changes", source(reaction=spec, mapping=maps), {})
    changes = evaluate("reaction.bond_changes", source(reaction=spec, mapping=maps), {"candidate_index": 0})
    assert len(changes["data"]["broken"]) == len(changes["data"]["formed"]) == 1
    limited = evaluate("reaction.mapping.generate", source(reaction=spec), {"max_states": 1})
    assert limited["data"]["truncated"] and limited["verdict"] == "inconclusive"


@pytest.mark.parametrize("smiles,spins,verdict", [
    ("[2H]O>>O", [1], "invalid"), ("[Na+]>>[Na]", [2], "invalid"),
    ("[H+].[OH-]>>O", [1], "valid"),
])
def test_reaction_isotope_charge_proton_conservation(smiles, spins, verdict):
    result = evaluate("reaction.parse", source(), {"reaction_smiles": smiles, "multiplicities": {"reactants": [1] * len(smiles.split('>>')[0].split('.')), "products": spins}})
    assert result["verdict"] == verdict


def test_spin_parity_and_reindex_assembly():
    with pytest.raises(ValueError, match="multiplicity"):
        evaluate("reaction.parse", source(), {"reaction_smiles": "[H]>>[H]", "multiplicities": {"reactants": [1], "products": [1]}})
    xyz = "2\nx\nH 0 0 0\nH 1 0 0\n"
    mapping = [{"reactant": {"species": 0, "atom": a}, "product": {"species": 0, "atom": 1-a}} for a in range(2)]
    result = evaluate("structure.reindex", source(reactants=xyz, products=xyz), {"mapping": mapping})
    assert result["files"]["product.xyz"].splitlines()[2].startswith("H 1.000")
    assembly = evaluate("structure.assemble_fragments", source(fragments=[xyz, xyz]), {"placement_candidates": [
        [{"translation": [0, 0, 0]}, {"translation": [0, 0, 0]}], [{"translation": [0, 0, 0]}, {"translation": [5, 0, 0]}]]})
    assert [c["clash"] for c in assembly["data"]["candidates"]] == [True, False]
    with pytest.raises(ValueError, match="reflections"):
        evaluate("structure.assemble_fragments", source(fragments=xyz), {"placements": [{"translation": [0, 0, 0], "rotation": [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]}]})


def test_species_identity_keeps_stereo_isotope_and_spin_distinct():
    from ts_agent.analysis.reaction import species_record

    for left, right in [(species_record("a", "[CH2]", 1), species_record("b", "[CH2]", 3)),
                        (species_record("a", "F[C@H](Cl)Br", 1), species_record("b", "F[C@@H](Cl)Br", 1)),
                        (species_record("a", "O", 1), species_record("b", "[2H]O", 1))]:
        result = evaluate("species.identity", source(reference={"schema_version": "ts-species-record/1", "data": left},
            target={"schema_version": "ts-species-record/1", "data": right}), {})
        assert not result["data"]["same_species"] and result["data"]["same_conformer"] is None


def test_gaussian_modes_and_input_construction():
    evidence = evaluate("gaussian.output.analyze", source(log=gaussian_log(imaginary=True)), {})
    assert evidence["data"]["imaginary_frequency_count"] == 1
    assert evidence["data"]["converged"]
    mode = evaluate("vibration.analyze_mode", source(evidence=evidence), {"mode_index": 0, "bonds": [{"atoms": [0, 1], "sign": -1}]})
    assert mode["data"]["reaction_coordinate_overlap"] == pytest.approx(1)
    evidence["data"]["modes"][0]["displacements"] = []
    assert evaluate("vibration.analyze_mode", source(evidence=evidence), {"mode_index": 0, "bonds": [{"atoms": [0, 1], "sign": 1}]})["verdict"] == "inconclusive"
    xyz = "2\nx\nH 0 0 0\nH 1 0 0\n"
    params = {"task": "qst2", "charge": 0, "multiplicity": 1, "method": "HF", "basis": "STO-3G"}
    assert "QST2" in evaluate("gaussian.input.build", source(structures=[xyz, xyz]), params)["files"]["calculation.gjf"]
    with pytest.raises(ValueError, match="number"):
        evaluate("gaussian.input.build", source(structures=xyz), params)
    with pytest.raises(ValueError, match="single method"):
        evaluate("gaussian.input.build", source(structures=[xyz, xyz]), {**params, "method": "HF\n--Link1--"})


def test_standard_state_analytic_correction_and_missing_data():
    params = thermo_parameters()
    result = evaluate("thermochemistry.evaluate", source(electronic=gaussian_log()), params)
    assert result["verdict"] == "valid"
    correction = R_KJ * 298.15 * math.log(0.0831446261815324 * 298.15 / 1.01325)
    assert result["data"]["standard_state_correction_kj_mol"] == pytest.approx(correction)
    assert result["data"]["value"] == pytest.approx(-1.105 * HARTREE_KJ_MOL + correction)
    electronic = evaluate("thermochemistry.evaluate", source(electronic=gaussian_log()), {**params, "quantity": "E"})
    assert electronic["data"]["standard_state_correction_kj_mol"] == 0
    correlated = evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(method="MP2/STO-3G")),
                          {**params, "methods": {"electronic": "MP2/STO-3G"}})
    assert correlated["verdict"] == "inconclusive" and correlated["data"]["value"] is None
    with pytest.raises(ValueError, match="temperature"):
        evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(temperature=300)), params)
    assert evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(method="UHF/STO-3G")), params)["verdict"] == "inconclusive"
    composite = {**params, "methods": {"electronic": "HF/STO-3G", "thermal": "HF/STO-3G", "composite": True}}
    assert evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(), thermal=gaussian_log(spacing=1)), composite)["verdict"] == "inconclusive"


def test_rrho_monatomic_enthalpy_and_geometry_guard():
    params = thermo_parameters(quantity="H", electronic_state={"charge": 0, "multiplicity": 2}, model={"kind": "rrho", "geometry": "monatomic", "symmetry_number": 1})
    result = evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(monatomic=True)), params)
    assert result["data"]["thermal_correction_kj_mol"] == pytest.approx(2.5 * R_KJ * 298.15, rel=1e-6)
    with pytest.raises(ValueError, match="classification"):
        evaluate("thermochemistry.evaluate", source(electronic=gaussian_log()), thermo_parameters(model={"kind": "rrho", "geometry": "nonlinear", "symmetry_number": 1}))


def test_rrho_ts_excludes_unstable_mode_and_parsed_requires_full_spectrum():
    params = thermo_parameters(quantity="H", stationary_kind="transition_state", model={"kind": "rrho", "geometry": "linear", "symmetry_number": 1})
    result = evaluate("thermochemistry.evaluate", source(electronic=gaussian_log(imaginary=True)), params)
    assert result["verdict"] == "valid"
    assert result["data"]["thermal_correction_kj_mol"] == pytest.approx(3.5 * R_KJ * 298.15, rel=1e-6)
    incomplete = gaussian_log().replace(" 2 1 0 0.74 0.0 0.0", " 2 1 0 0.74 0.0 0.0\n 3 1 0 0.0 0.74 0.0")
    result = evaluate("thermochemistry.evaluate", source(electronic=incomplete), thermo_parameters())
    assert result["verdict"] == "inconclusive" and result["data"]["value"] is None


def test_tst_molecularity_rates_branching_and_energy_guard():
    a = evaluate("kinetics.tst", source(barrier=barrier()), {})
    b = evaluate("kinetics.tst", source(barrier=barrier(2)), {"concentrations_molar": {"A": 0.1, "B": 0.2}})
    assert a["data"]["rate_constant_unit"] == "s^-1"
    assert b["data"]["rate_constant_unit"] == "(mol/L)^-1 s^-1"
    assert b["data"]["rate_molar_s"] == pytest.approx(b["data"]["rate_constant"] * 0.02)
    assert a["data"]["rate_constant"] == pytest.approx(b["data"]["rate_constant"])
    rev = evaluate("kinetics.tst", source(barrier=barrier()), {"direction": "reverse"})
    assert a["data"]["log_rate_constant"] - rev["data"]["log_rate_constant"] == pytest.approx(10 / (R_KJ * 298.15))
    faster = evaluate("kinetics.tst", source(barrier=barrier(activation=45)), {})
    params = {"assumptions": {"shared_equilibrated_precursor": True, "irreversible_products": True, "no_product_interconversion": True}}
    branches = evaluate("kinetics.branching", source(rates=[a, faster]), params)
    assert sum(branches["data"]["fractions"]) == pytest.approx(1)
    assert branches["data"]["fractions"][1] > 0.8
    params["assumptions"]["irreversible_products"] = False
    assert evaluate("kinetics.branching", source(rates=[a, faster]), params)["verdict"] == "unsupported"
    wrong = barrier()
    wrong["data"]["quantity"] = "E"
    with pytest.raises(ValueError, match="Gibbs"):
        evaluate("kinetics.tst", source(barrier=wrong), {})


def test_public_analysis_artifact_replay_and_tamper(tmp_path):
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node = start_research_node(workspace)["node_id"]
    params = {"reaction_smiles": "CCl.[OH-]>>CO.[Cl-]", "multiplicities": {"reactants": [1, 1], "products": [1, 1]}}
    result = run_analysis(workspace, request(node, "reaction.parse", params))
    artifact = result["analysis_artifact"]
    assert not run_analysis(workspace, request(node, "reaction.parse", params))["created"]
    loaded = load_finding_candidate(workspace, artifact_id=artifact["artifact_id"], artifact_sha256=None, candidate_id="candidate_1", node_id=node)
    assert loaded["candidate"]["value"] is True
    mapping = run_analysis(workspace, request(node, "reaction.mapping.generate", {}, {"reaction": [artifact["artifact_id"]]}))
    assert mapping["verdict"] == "inconclusive"
    path = workspace / artifact["path"]
    document = json.loads(path.read_text())
    document["finding_candidates"]["candidates"][0]["value"] = False
    path.write_text(json.dumps(document))
    changed = next(row for row in list_calculation_artifacts(workspace)["artifacts"] if row["path"] == artifact["path"])
    with pytest.raises(FindingCandidateError, match="recomputed"):
        load_finding_candidate(workspace, artifact_id=changed["artifact_id"], artifact_sha256=None, candidate_id="candidate_1", node_id=node)


def test_catalog_schemas_closed_and_invalid_parameters_rejected(tmp_path):
    for descriptor in DESCRIPTORS:
        Draft202012Validator.check_schema(descriptor["parameter_schema"])
        Draft202012Validator.check_schema(descriptor["input_schema"])
    with pytest.raises(ValueError, match="max_states"):
        run_analysis(tmp_path, request("node_1", "reaction.mapping.generate", {"max_states": 100001}, {"reaction": ["art_" + "0" * 24]}))


@pytest.mark.parametrize("legacy_order", [False, True])
def test_multiple_input_roles_replay_independent_of_json_key_order(tmp_path, legacy_order):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    node = start_research_node(root)["node_id"]
    parsed = run_analysis(root, request(node, "reaction.parse", {"reaction_smiles": "CCl.[OH-]>>CO.[Cl-]", "multiplicities": {"reactants": [1, 1], "products": [1, 1]}}))
    reaction_id = parsed["analysis_artifact"]["artifact_id"]
    mapping = run_analysis(root, request(node, "reaction.mapping.generate", {}, {"reaction": [reaction_id]}))
    roles = {"reaction": [reaction_id], "mapping": [mapping["analysis_artifact"]["artifact_id"]]}
    result = run_analysis(root, request(node, "reaction.bond_changes", {"candidate_index": 0}, roles))
    artifact = result["analysis_artifact"]
    again = run_analysis(root, request(node, "reaction.bond_changes", {"candidate_index": 0}, dict(reversed(list(roles.items())))))
    assert again["analysis_artifact"] == artifact and not again["created"]
    path = root / artifact["path"]
    document = json.loads(path.read_text())
    if legacy_order:
        document["source_artifacts"].reverse()
        document["finding_candidates"]["source_artifacts"].reverse()
        for row in document["finding_candidates"]["candidates"]:
            row["source_artifact_ids"].reverse()
        path.write_text(json.dumps(document, sort_keys=True))
        artifact = next(a for a in list_calculation_artifacts(root)["artifacts"] if a["path"] == artifact["path"])
    loaded = load_finding_candidate(root, artifact_id=artifact["artifact_id"], artifact_sha256=None, candidate_id="candidate_1", node_id=node)
    assert len(loaded["source_artifacts"]) == 2
    document["source_artifacts"].append(document["source_artifacts"][0])
    path.write_text(json.dumps(document))
    changed = next(a for a in list_calculation_artifacts(root)["artifacts"] if a["path"] == artifact["path"])
    with pytest.raises(FindingCandidateError, match="source artifact binding"):
        load_finding_candidate(root, artifact_id=changed["artifact_id"], artifact_sha256=None, candidate_id="candidate_1", node_id=node)


def test_network_parallel_hyperedges_cycles_and_bounded_reachability():
    spec = reaction()
    forward = evaluate("mechanism.step.define", source(reaction=spec), {"step_key": "s1", "reversible": True})
    parallel = evaluate("mechanism.step.define", source(reaction=spec), {"step_key": "s2", "reversible": False})
    network = evaluate("mechanism.network.assemble", source(steps=[forward, parallel]), {"scope": "SN2 alternatives", "initial_species": ["r0", "r1"], "target_species": ["p0"], "max_paths": 1})
    assert len(network["data"]["steps"]) == 2
    assert len(network["data"]["steps"][0]["reactants"]) == 2
    assert network["data"]["audit"]["cycle_species"]
    assert network["verdict"] == "inconclusive"
    assert network["data"]["paths"]["truncated"]
    missing = evaluate("mechanism.network.assemble", source(steps=forward), {"scope": "missing co-reactant", "initial_species": ["r0"], "target_species": ["p0"]})
    assert missing["data"]["paths"]["paths"] == []
    assert evaluate("mechanism.network.audit", source(network=network), {})["data"]["chemistry_balanced"]


def test_energy_profile_keeps_stoichiometric_pool_and_renderer_contract():
    reaction_spec = evaluate("reaction.parse", source(), {"species": [
        {"key": "A", "smiles": "CCO", "multiplicity": 1}, {"key": "P", "smiles": "COC", "multiplicity": 1}],
        "reactants": [{"species": "A", "coefficient": 1}], "products": [{"species": "P", "coefficient": 1}]})
    energies = evaluate("barrier.evaluate", source(reactants=thermal_record("A", 0, {"C": 2, "H": 6, "O": 1}),
        products=thermal_record("P", -10, {"C": 2, "H": 6, "O": 1}), transition_state=thermal_record("TS", 50, {"C": 2, "H": 6, "O": 1}, ts=True)), {})
    step = evaluate("mechanism.step.define", source(reaction=reaction_spec, barrier=energies), {"step_key": "isomerization", "reversible": True})
    network = evaluate("mechanism.network.assemble", source(steps=step), {"scope": "synthetic energy reference check"})
    profile = evaluate("mechanism.energy_profile", source(network=network), {"path": [{"step": "isomerization"}, {"step": "isomerization", "direction": "reverse"}], "initial_composition": {"A": 1}})
    assert [p["energy"] for p in profile["data"]["points"]] == [0, 50, -10, 50, 0]
    assert profile["data"]["final_composition"] == {"A": 1, "P": 0}
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/ts-render/curve-data.schema.json").read_text())
    Draft202012Validator(schema).validate(json.loads(profile["files"]["energy_profile.json"]))
    with pytest.raises(ValueError, match="unavailable"):
        evaluate("mechanism.energy_profile", source(network=network), {"path": [{"step": "isomerization"}], "initial_composition": {"P": 1}})


def test_ts_audit_rejects_bad_stationary_point_and_missing_connectivity():
    evidence = evaluate("gaussian.output.analyze", source(log=gaussian_log(imaginary=True)), {})
    partial = evaluate("mechanism.step.audit", source(stationary=evidence), {"step_key": "step1"})
    assert partial["verdict"] == "inconclusive"
    evidence["data"]["imaginary_frequency_count"] = 2
    assert evaluate("mechanism.step.audit", source(stationary=evidence), {"step_key": "step1"})["verdict"] == "invalid"


def test_ts_audit_requires_bound_mode_origin_and_expected_endpoint():
    stationary = evaluate("gaussian.output.analyze", source(log=gaussian_log(imaginary=True)), {})
    mode = evaluate("vibration.analyze_mode", source(evidence=stationary), {"mode_index": 0, "bonds": [{"atoms": [0, 1], "sign": 1}]})
    paths = {direction: outcome("ts-path-endpoint-summary/1", {"normal_termination": True, "path_complete_marker": True,
        "direction": direction, "initial_geometry": stationary["data"]["geometry"]}) for direction in ("forward", "reverse")}
    inputs = source(stationary=stationary, mode=mode, **paths,
                    forward_match={"schema_version": "ts-structure-comparison/1", "verdict": "matched", "inputs": {"reference": {"artifact_id": "forward_endpoint"}, "target": {"artifact_id": "reactant"}}},
                    reverse_match={"schema_version": "ts-structure-comparison/1", "verdict": "matched", "inputs": {"reference": {"artifact_id": "reverse_endpoint"}, "target": {"artifact_id": "product"}}})

    def bind(role, result, **metadata):
        inputs.payloads[inputs.bindings[role][0]["artifact_id"]] = json.dumps({"schema_version": "ts-scientific-analysis/1", "result": result, **metadata}).encode()

    bind("mode", mode, input_artifacts={"evidence": [inputs.bindings["stationary"][0]["artifact_id"]]})
    for direction in paths:
        bind(direction, paths[direction], output_artifacts={"endpoint.xyz": {"artifact_id": direction + "_endpoint"}})
    p = {"step_key": "s", "forward_species_artifact_id": "reactant", "reverse_species_artifact_id": "product"}
    assert evaluate("mechanism.step.audit", inputs, p)["verdict"] == "valid"
    assert evaluate("mechanism.step.audit", inputs, {**p, "forward_species_artifact_id": "other_basin"})["verdict"] == "invalid"
    bind("mode", mode, input_artifacts={"evidence": ["another_ts"]})
    assert evaluate("mechanism.step.audit", inputs, p)["data"]["checks"]["mode_source"] is False


def test_network_preserves_invalid_step_evidence():
    audit = outcome("ts-elementary-step-audit/1", {"step_key": "s", "checks": {"one_imaginary_frequency": False}}, verdict="invalid")
    step = evaluate("mechanism.step.define", source(reaction=reaction(), audit=audit), {"step_key": "s"})
    assert step["verdict"] == "invalid"
    result = evaluate("mechanism.network.assemble", source(steps=step), {"scope": "contradicted TS candidate"})
    assert result["verdict"] == "invalid" and result["data"]["audit"]["chemistry_balanced"]


def test_irc_endpoint_summary_distinguishes_termination_and_completion():
    text = "\n".join([" #P HF/STO-3G IRC=(Forward,CalcFC,MaxPoints=2)", " -----", " SCF Done: E(RHF) = -1.0 A.U.",
        " Point Number 1 in FORWARD path direction.", " Point Number: 1 Path Number: 1", " CURRENT STRUCTURE", " 1 1 0.0 0.0 0.0", " 2 1 0.8 0.0 0.0",
        " NET REACTION COORDINATE UP TO THIS POINT = 0.1", " Calculation of FORWARD path complete.", " Normal termination of Gaussian 16", ""])
    complete = evaluate("path.endpoint_summary", source(log=text), {})
    assert complete["verdict"] == "valid" and complete["data"]["direction"] == "forward"
    assert "endpoint.xyz" in complete["files"]
    assert evaluate("path.endpoint_summary", source(log=text.replace("Calculation of FORWARD path complete.", "")), {})["verdict"] == "inconclusive"
