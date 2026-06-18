"""Write ASE NEB main-path workspace nodes.

``write_input_check_node`` records the root input-check node (atom order,
mechanism preflight, endpoint readiness). ``write_neb_node_metadata`` records the
NEB candidate-generation node. Both translate a :class:`ProjectContext` plus a
config/summary into node.json, evidence, report.md, reflection, and tree state —
all via the workspace I/O layer.
"""

from __future__ import annotations

from typing import Any

from transition_state_workflow.base.ase_neb import ProjectContext, level_slug_from_calculator
from transition_state_workflow.chem.geometry import Atom
from transition_state_workflow.chem.mechanism import (
    endpoint_readiness_summary,
    infer_mechanism_preflight_from_geometry,
)
from transition_state_workflow.core.workspace import (
    append_evidence_record,
    finalize_node_report_and_tree,
    node_record,
    write_json,
)


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _atoms_from_structure(structure: Any) -> list[Atom]:
    symbols = structure.get_chemical_symbols()
    positions = structure.get_positions()
    if len(symbols) != len(positions):
        raise ValueError(f"symbol/position length mismatch: {len(symbols)} symbols, {len(positions)} positions")
    return [
        Atom(str(symbol), float(position[0]), float(position[1]), float(position[2]))
        for symbol, position in zip(symbols, positions)
    ]


def infer_ase_neb_mechanism_preflight(
    cfg: dict[str, Any],
    reactant: Any,
    product: Any,
) -> dict[str, Any]:
    """Infer mechanism preflight from ASE-like endpoint objects without importing ASE."""

    calc_cfg = _as_mapping(cfg.get("calculator"))
    refinement_cfg = _as_mapping(cfg.get("refinement"))
    gaussian_cfg = _as_mapping(refinement_cfg.get("gaussian"))
    calc_charge = calc_cfg.get("charge")
    calc_uhf = calc_cfg.get("uhf")
    gaussian_charge = gaussian_cfg.get("charge")
    gaussian_multiplicity = gaussian_cfg.get("multiplicity")
    charge = gaussian_charge if gaussian_charge is not None else calc_charge
    multiplicity = gaussian_multiplicity
    if multiplicity is None and calc_uhf is not None:
        multiplicity = int(calc_uhf) + 1

    return infer_mechanism_preflight_from_geometry(
        reactant=_atoms_from_structure(reactant),
        product=_atoms_from_structure(product),
        charge=charge,
        multiplicity=multiplicity,
        xtb_uhf=calc_uhf,
        calculator_type=calc_cfg.get("type"),
        calculator_charge=calc_charge,
        validation_charge=gaussian_charge,
        validation_multiplicity=gaussian_multiplicity,
    )


def endpoint_validation_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    return endpoint_readiness_summary(_as_mapping(cfg.get("endpoint_validation")))


def write_input_check_node(
    ctx: ProjectContext,
    cfg: dict[str, Any],
    reactant: Any,
    product: Any,
) -> None:
    symbols = reactant.get_chemical_symbols()
    mechanism_preflight = infer_ase_neb_mechanism_preflight(cfg, reactant, product)
    endpoint_validation = endpoint_validation_summary(cfg)
    validation = {
        "atom_order_checked": True,
        "atom_count": len(symbols),
        "reactant_formula": reactant.get_chemical_formula(),
        "product_formula": product.get_chemical_formula(),
        "same_ordered_symbols": symbols == product.get_chemical_symbols(),
        "mechanism_preflight": mechanism_preflight,
        "endpoint_validation": endpoint_validation,
    }
    write_json(ctx.input_node / "mechanism_preflight.json", mechanism_preflight)
    write_json(ctx.input_node / "validation.json", validation)
    endpoint_ready = bool(endpoint_validation["endpoint_minima_ready"])
    input_node = node_record(
        node_id=ctx.input_node_id,
        parent_id=None,
        node_type="root",
        hypothesis="Reactant/product atom order, charge/spin state, and coarse mechanism define the root TS-search hypothesis.",
        changed_variables={},
        status="succeeded",
        claim_status="endpoint_minima_ready" if endpoint_ready else "not_evaluated",
        outcome="endpoint_minima_validated" if endpoint_ready else "none",
        evidence={
            "validation": str(ctx.input_node / "validation.json"),
            "mechanism_preflight": str(ctx.input_node / "mechanism_preflight.json"),
        },
        decision="split",
        stage="input_check",
        backend="ase",
        mechanism_preflight=mechanism_preflight,
        endpoint_validation=endpoint_validation,
        validation=validation,
        inputs={
            "reactant": cfg["reactant"],
            "product": cfg["product"],
        },
    )
    write_json(ctx.input_node / "node.json", input_node)
    append_evidence_record(
        ctx.root,
        node_id=ctx.input_node_id,
        kind="mechanism_preflight",
        path=ctx.input_node / "mechanism_preflight.json",
        claim="Mechanism preflight hypothesis was recorded before candidate generation.",
        evidence_state="prepared",
    )
    append_evidence_record(
        ctx.root,
        node_id=ctx.input_node_id,
        kind="input_validation",
        path=ctx.input_node / "validation.json",
        claim="Reactant/product atom order and root inputs were checked.",
        evidence_state="prepared",
    )
    append_evidence_record(
        ctx.root,
        node_id=ctx.input_node_id,
        kind="endpoint_minima_summary",
        path=ctx.input_node / "validation.json",
        claim=(
            "Endpoint minima/readiness evidence was declared for candidate generation."
            if endpoint_ready
            else "Endpoint inputs remain reference hypotheses; candidate generation cannot be promoted without endpoint readiness."
        ),
        evidence_state="supports" if endpoint_ready else "ambiguous",
    )
    finalize_node_report_and_tree(
        ctx.root,
        ctx.input_node,
        ctx.input_node_id,
        input_node,
        parent=None,
        stage="input_check",
        status="succeeded",
        report_body=f"""# Input Check

- Status: succeeded
- Atom count: {len(symbols)}
- Reactant formula: {reactant.get_chemical_formula()}
- Product formula: {product.get_chemical_formula()}
- Atom order: checked by ordered symbols
- Charge/multiplicity: {mechanism_preflight['total_charge']} / {mechanism_preflight['multiplicity']}
- Mechanism hypothesis: {mechanism_preflight['mechanism_hypothesis']}
- Mechanism confidence: {mechanism_preflight['mechanism_confidence']}
- Risk flags: {', '.join(mechanism_preflight['risk_flags']) if mechanism_preflight['risk_flags'] else 'none'}
""",
        reflection_decision="inputs_validated",
    )


def write_neb_node_metadata(
    ctx: ProjectContext,
    cfg: dict[str, Any],
    *,
    status: str,
    summary: dict[str, Any] | None = None,
) -> None:
    calc_cfg = cfg["calculator"]
    quality = summary.get("candidate_quality", {}) if summary else {}
    accepted_for_promotion = bool(quality.get("accepted_for_promotion", False))
    failure_type = None
    if summary and not accepted_for_promotion:
        failure_type = str(quality.get("outcome_code") or "neb_candidate_rejected")
    decision = "run_neb" if summary is None else ("promote" if accepted_for_promotion else "backtrack")
    evidence = {
        "config": str(ctx.neb_node / "config.json"),
        "validation": str(ctx.neb_node / "validation.json"),
    }
    if summary:
        evidence["summary"] = str(ctx.neb_node / "summary.json")
        evidence["candidate_json"] = str(summary.get("candidate_json"))
    data = node_record(
        node_id=ctx.neb_node_id,
        parent_id=ctx.input_node_id,
        node_type="candidate_generation",
        hypothesis="ASE NEB candidate-generation branch using the configured interpolation, optimizer, and calculator.",
        changed_variables={
            "images": cfg["images"],
            "interpolation": cfg["interpolation"],
            "neb": cfg["neb"],
            "optimizer": cfg["optimizer"],
            "calculator": cfg["calculator"],
            "endpoint_validation": cfg.get("endpoint_validation", {}),
        },
        status=status,
        evidence=evidence,
        decision=decision,
        outcome_code=failure_type,
        stage="neb",
        backend=calc_cfg["type"],
        level=level_slug_from_calculator(calc_cfg),
        config={
            "images": cfg["images"],
            "interpolation": cfg["interpolation"],
            "neb": cfg["neb"],
            "optimizer": cfg["optimizer"],
            "calculator": cfg["calculator"],
            "endpoint_validation": cfg.get("endpoint_validation", {}),
        },
        outputs={
            "images": "images/",
            "trajectories": "trajectories/",
            "tables": "tables/",
            "candidates": "candidates/",
        },
        validation={
            "is_validated_transition_state": False,
            "claim": "NEB maximum is a transition-state candidate only.",
        },
    )
    if summary:
        data["summary"] = summary
        append_evidence_record(
            ctx.root,
            node_id=ctx.neb_node_id,
            kind="neb_candidate_summary",
            path=ctx.neb_node / "summary.json",
            claim=(
                "ASE NEB produced a promotable candidate geometry."
                if accepted_for_promotion
                else "ASE NEB did not pass candidate-promotion gates."
            ),
            evidence_state="candidate_found" if accepted_for_promotion else "ambiguous",
        )
        if summary.get("candidate_json"):
            append_evidence_record(
                ctx.root,
                node_id=ctx.neb_node_id,
                kind="neb_candidate_geometry",
                path=str(summary["candidate_json"]),
                claim="NEB maximum geometry is candidate-only evidence.",
                evidence_state="candidate_found" if accepted_for_promotion else "ambiguous",
            )
    write_json(ctx.neb_node / "node.json", data)
    write_json(ctx.neb_node / "config.json", data["config"])
    write_json(ctx.neb_node / "validation.json", data["validation"])
    append_evidence_record(
        ctx.root,
        node_id=ctx.neb_node_id,
        kind="neb_config",
        path=ctx.neb_node / "config.json",
        claim="ASE NEB candidate-generation configuration was recorded.",
        evidence_state="prepared",
    )
    append_evidence_record(
        ctx.root,
        node_id=ctx.neb_node_id,
        kind="neb_validation_policy",
        path=ctx.neb_node / "validation.json",
        claim="NEB output is candidate-only until Gaussian TS/Freq and connectivity validation pass.",
        evidence_state="prepared",
    )
    report_lines = [
        "# NEB Node",
        "",
        f"- Status: {status}",
        f"- Backend: {calc_cfg['type']}",
        f"- Level: {level_slug_from_calculator(calc_cfg)}",
        f"- Images: {cfg['images']}",
        f"- Interpolation: {cfg['interpolation']}",
        f"- Climbing image: {bool(cfg['neb'].get('climb', False))}",
        "",
        "NEB outputs are candidates only. Promote a candidate to Gaussian TS/Freq and connectivity validation before accepting a transition state.",
    ]
    if summary:
        report_lines.extend(
            [
                "",
                "## Candidate",
                f"- Candidate: {summary['candidate_id']}",
                f"- Source image: {summary['ts_candidate_index']}",
                f"- Barrier vs reactant: {summary['barrier_ev_relative_to_reactant']} eV",
                f"- Reaction energy: {summary['reaction_energy_ev']} eV",
                f"- Promotion gate: {'passed' if accepted_for_promotion else 'failed'}",
                f"- Gate reasons: {'; '.join(quality.get('reasons', [])) if quality else 'not evaluated'}",
            ]
        )
    reflection = None
    if summary:
        reflection = {
            "computational_outcome": (
                "NEB candidate-generation completed and passed promotion gates."
                if accepted_for_promotion
                else "NEB candidate-generation completed but failed promotion gates."
            ),
            "mechanistic_implication": (
                "The branch remains candidate-only; Gaussian TS/Freq and connectivity validation are still required."
                if accepted_for_promotion
                else "The branch should not be promoted until endpoint readiness, convergence, endpoint-image, and barrier issues are resolved."
            ),
            "knowledge_update": (
                "NEB produced a promotable candidate geometry."
                if accepted_for_promotion
                else "NEB did not produce a promotable candidate geometry."
            ),
            "next_branch": (
                "Prepare Gaussian TS/Freq validation."
                if accepted_for_promotion
                else "Backtrack to endpoint discovery or branch-variable adjustment."
            ),
        }
    finalize_node_report_and_tree(
        ctx.root,
        ctx.neb_node,
        ctx.neb_node_id,
        data,
        parent=ctx.input_node_id,
        stage="neb",
        status=status,
        report_body="\n".join(report_lines),
        reflection=reflection,
        reflection_decision=decision,
    )


__all__ = [
    "endpoint_validation_summary",
    "infer_ase_neb_mechanism_preflight",
    "write_input_check_node",
    "write_neb_node_metadata",
]
