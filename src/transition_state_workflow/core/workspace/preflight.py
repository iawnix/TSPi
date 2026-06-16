"""Mechanism-preflight root node writers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import relative_path_or_absolute

from .branch import write_prepared_branch_state
from .evidence import append_portable_evidence_record
from .io import write_text_file_if_allowed
from .naming import utc_timestamp
from .scaffold import ensure_workspace_root_has_manifest_and_tree


DEFAULT_PREFLIGHT_NODE_ID = "n000_mechanism_preflight"


def write_mechanism_preflight_node(
    *,
    root: Path,
    node_id: str = DEFAULT_PREFLIGHT_NODE_ID,
    force: bool = False,
) -> str:
    """Create a real mechanism-preflight node from workspace mechanism metadata."""

    source = root.resolve()
    ensure_workspace_root_has_manifest_and_tree(source)
    node_dir = source / "nodes" / node_id
    if (node_dir / "node.json").exists() and not force:
        return node_id

    mechanism = read_json_object_required(source / "mechanism_model.json")
    manifest_path = source / "manifest.json"
    manifest = read_json_object_required(manifest_path)
    now = utc_timestamp()
    charge = mechanism.get("charge", manifest.get("charge", "unknown"))
    multiplicity = mechanism.get("multiplicity", manifest.get("multiplicity", "unknown"))
    reaction_class = str(mechanism.get("reaction_class") or "unknown")
    key_atoms = [str(item) for item in mechanism.get("key_atoms") or []]
    expected_bond_changes = mechanism.get("expected_bond_changes") or []
    hypothesis = (
        "Mechanism preflight records the initial charge, multiplicity, "
        "reaction-class hypothesis, and reaction-center expectations before compute branches."
    )
    branch_write = write_prepared_branch_state(
        root=source,
        node_id=node_id,
        parent_id=None,
        stage="mechanism_preflight",
        operation="mechanism-preflight",
        hypothesis=hypothesis,
        input_refs=[],
        pathway_id="",
        step_id="",
        timestamp=now,
        overwrite_existing=force,
    )
    node_dir = branch_write.node_dir
    summary_path = node_dir / "parsed" / "mechanism_preflight_summary.json"
    summary_payload = {
        "schema": "tssearch-mechanism-preflight-summary-v1",
        "node_id": node_id,
        "charge": charge,
        "multiplicity": multiplicity,
        "reaction_class": reaction_class,
        "reaction_class_confidence": mechanism.get("reaction_class_confidence", ""),
        "key_atoms": key_atoms,
        "expected_bond_changes": expected_bond_changes,
        "analysis_plan": mechanism.get("analysis_plan", {}),
        "open_questions": mechanism.get("open_questions", []),
        "created_at": now,
    }
    write_json_object(summary_path, summary_payload, overwrite_existing=True)

    summary_rel = relative_path_or_absolute(source, summary_path)
    node_path = node_dir / "node.json"
    node_payload = read_json_object_required(node_path)
    evidence = dict(node_payload.get("evidence") or {})
    evidence["preflight_summary"] = summary_rel
    node_payload["evidence"] = evidence
    node_payload["display"] = {
        **dict(node_payload.get("display") or {}),
        "title": node_id,
        "subtitle": "mechanism preflight",
        "primary_file": summary_rel,
        "summary": f"Preflight: charge {charge}, multiplicity {multiplicity}, reaction class {reaction_class}.",
    }
    write_json_object(node_path, node_payload, overwrite_existing=True)

    write_text_file_if_allowed(
        node_dir / "hypothesis.md",
        mechanism_preflight_hypothesis_markdown(
            node_id=node_id,
            charge=charge,
            multiplicity=multiplicity,
            reaction_class=reaction_class,
            key_atoms=key_atoms,
            expected_bond_changes=expected_bond_changes,
        ),
        overwrite_existing=force,
    )
    write_text_file_if_allowed(
        node_dir / "decision_card.md",
        mechanism_preflight_decision_card_markdown(node_id=node_id, summary_rel=summary_rel, created_at=now),
        overwrite_existing=force,
    )
    write_text_file_if_allowed(
        node_dir / "reflection.md",
        """# Reflection

## Computational Outcome

Not run yet.

## Mechanistic Implication

Pending.

## Knowledge Update

- No knowledge-base update requested.

## Next Branch

- Optimize or validate endpoint references before candidate generation.
""",
        overwrite_existing=force,
    )
    append_portable_evidence_record(
        root=source,
        kind="mechanism_preflight",
        path=summary_rel,
        node_id=node_id,
        claim="Initial mechanism preflight was recorded before compute branches.",
        evidence_state="prepared",
    )
    manifest["mechanism_preflight_storage"] = "node"
    manifest["mechanism_preflight_node_id"] = node_id
    write_json_object(manifest_path, manifest, overwrite_existing=True)
    return node_id


def mechanism_preflight_hypothesis_markdown(
    *,
    node_id: str,
    charge: object,
    multiplicity: object,
    reaction_class: str,
    key_atoms: list[str],
    expected_bond_changes: object,
) -> str:
    """Render the preflight hypothesis text for the canonical root node."""

    key_atom_text = ", ".join(key_atoms) if key_atoms else "not specified"
    bond_text = format_expected_bond_changes(expected_bond_changes)
    return f"""# Hypothesis: {node_id}

## Chemical Hypothesis

The TS search starts from a mechanism preflight with charge {charge},
multiplicity {multiplicity}, reaction class `{reaction_class}`, and reaction-center
expectations recorded before compute branches.

## Reaction-Center Expectations

- Key atoms: {key_atom_text}
- Expected bond changes: {bond_text}

## Mechanism Analysis Plan / Required Diagnostics

- Reaction type: compare endpoint and candidate branches against the preflight
  reaction-class hypothesis.
- Reaction center: track the expected forming and breaking bonds.
- Electronic / spin / charge: preserve the recorded charge and multiplicity.
- Orbital / population: record unavailable unless a later output provides
  descriptors.
- Energy / barrier expectation: report only after validated method-level
  evidence exists.

## Evidence That Would Support This Hypothesis

- Endpoint validation preserves the intended charge, multiplicity, and mapped
  reaction-center identity.
- Candidate-generation branches test a chemically meaningful coordinate from
  this preflight rather than arbitrary pose changes.

## Evidence That Would Refute This Hypothesis

- Endpoint optimization collapses the intended reactant/product identity.
- The chosen reaction-center atoms or bond changes do not match parsed endpoint
  connectivity.
"""


def mechanism_preflight_decision_card_markdown(*, node_id: str, summary_rel: str, created_at: str) -> str:
    """Render the decision card for the canonical preflight root node."""

    return f"""# TS Decision Card: {node_id}

## Chemical Hypothesis

Record the initial mechanism preflight as the root scientific branch record.

## Why This Tool

Chosen operation/route: mechanism-preflight

This node anchors later endpoint validation and candidate-generation branches to
the charge, multiplicity, reaction-class hypothesis, and reaction-center
expectations recorded in `{summary_rel}`.

## Input / Dependency Nodes

- None recorded.

## Expected Supporting Evidence

- Endpoint references remain chemically distinct at the intended charge and
  multiplicity.
- Later branches name how they test or revise this preflight.

## Refutation Criteria

- Endpoint identity checks or parsed connectivity refute the expected
  reaction-center changes.
- A later branch requires a different elementary-step hypothesis.

## Cost And Risk

- Compute cost: none for the preflight record itself.
- Scientific risk: this node is not a TS claim; it only records the initial
  mechanism hypothesis and required diagnostics.

## Next If Supported

- Create endpoint validation branches as children of this node.

## Next If Refuted

- Create an alternative mechanism-preflight branch and make downstream compute
  nodes children of the revised hypothesis.

## Created

{created_at}
"""


def format_expected_bond_changes(value: object) -> str:
    """Return a compact Markdown-safe summary of expected bond changes."""

    if not value:
        return "not specified"
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                role = str(item.get("role") or "change")
                bond = item.get("bond") or item.get("atoms") or item.get("atom_pair") or ""
                parts.append(f"{role}:{bond}")
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else "not specified"
    return str(value)


__all__ = [
    "DEFAULT_PREFLIGHT_NODE_ID",
    "format_expected_bond_changes",
    "mechanism_preflight_decision_card_markdown",
    "mechanism_preflight_hypothesis_markdown",
    "write_mechanism_preflight_node",
]
