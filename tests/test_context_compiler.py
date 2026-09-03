from __future__ import annotations

from pathlib import Path

import pytest

from tests.workspace_helpers import accept_research_claim
from ts_agent.workspace.context import ContextCompileError, build_review_snapshot, compile_context, proof_capabilities
from tests.kernel_helpers import compile_change
from ts_agent.workspace.engine import init_workspace
from tests.kernel_helpers import apply_compiled_change
from ts_agent.io import read_json


def _seed(root: Path) -> dict[str, str]:
    drafted = compile_change(
        root,
        {
            "rationale": "Create competing Claims and one open frontier Node.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "phase",
                    "title": "Mechanism discrimination",
                    "objective": "Distinguish competing mechanism Claims.",
                },
                {"op": "create_claim", "local_ref": "concerted", "claimType": "mechanism", "statement": "The pathway is concerted."},
                {"op": "create_claim", "local_ref": "stepwise", "claimType": "mechanism", "statement": "The pathway is stepwise."},
                {
                    "op": "relate_claims",
                    "local_ref": "alternatives",
                    "sourceClaimRef": "$concerted",
                    "targetClaimRef": "$stepwise",
                    "relationType": "alternative_to",
                    "rationale": "These Claims are competing explanations.",
                },
                {
                    "op": "start_node",
                    "local_ref": "search",
                    "phaseRef": "$phase",
                    "title": "Bounded research node",
                    "deliverable": "One bounded research result.",
                    "objective": "Search for observations that distinguish the mechanisms.",
                    "primaryClaimRef": "$concerted",
                    "claimRefs": ["$concerted", "$stepwise"],
                },
                {
                    "op": "record_finding",
                    "local_ref": "ambiguity",
                    "findingType": "mechanism_ambiguity",
                    "severity": "warning",
                    "statement": "No discriminating path evidence is available yet.",
                    "claimRefs": ["$concerted", "$stepwise"],
                    "nodeRefs": ["$search"],
                },
                {"op": "set_focus", "claimRefs": ["$concerted"], "nodeRefs": ["$search"]},
            ],
        },
    )
    apply_compiled_change(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_frontier_projection_includes_competing_claim_and_open_finding(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    context = compile_context(root, mode="frontier")

    assert context["schema_version"] == "ts-context-projection/3"
    assert context["projection_id"].startswith("ctx_")
    assert {item["claim_id"] for item in context["claims"]} == {refs["concerted"], refs["stepwise"]}
    assert [item["relation_id"] for item in context["claim_relations"]] == [refs["alternatives"]]
    assert [item["node_id"] for item in context["research_nodes"]] == [refs["search"]]
    assert [item["finding_id"] for item in context["open_findings"]] == [refs["ambiguity"]]
    assert context["retrieval"]["has_more"] is False


def test_context_derives_claim_node_link_from_creator_provenance(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_draft = compile_change(
        root,
        {
            "rationale": "Start an exploratory Node before it discovers a Claim.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "phase",
                    "title": "Exploration",
                    "objective": "Explore mechanisms without a pre-existing Claim.",
                },
                {"op": "start_node", "local_ref": "exploration", "phaseRef": "$phase", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Look for an alternative mechanism."}
            ],
        },
    )
    apply_compiled_change(root, node_draft["decision"])
    node_id = node_draft["allocated_refs"]["exploration"]
    claim_draft = compile_change(
        root,
        {
            "rationale": "Record the alternative Claim discovered by the Node.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": "alternative",
                    "claimType": "mechanism",
                    "statement": "An alternative pathway may exist.",
                    "createdByNode": node_id,
                }
            ],
        },
    )
    apply_compiled_change(root, claim_draft["decision"])
    claim_id = claim_draft["allocated_refs"]["alternative"]

    canonical_node = read_json(root / "research_nodes.json")["nodes"][0]
    assert canonical_node["claim_refs"] == []
    node_context = compile_context(root, mode="node", node_ref=node_id)
    assert [row["claim_id"] for row in node_context["claims"]] == [claim_id]
    assert node_context["research_nodes"][0]["claim_refs"] == []
    assert node_context["research_nodes"][0]["related_claim_refs"] == [claim_id]
    assert [row["node_id"] for row in compile_context(root, mode="claim", claim_ref=claim_id)["research_nodes"]] == [node_id]
    assert [row["claim_id"] for row in compile_context(root, mode="frontier")["claims"]] == [claim_id]


def test_delta_avoids_repeating_unchanged_context(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    context = compile_context(root, mode="frontier")

    delta = compile_context(
        root,
        mode="delta",
        since_revision=context["workspace_revision"],
        since_operational_revision=context["operational_revision"],
    )

    assert delta["changed"] is False
    assert "claims" not in delta


def test_claim_review_snapshot_uses_graph_dependencies_not_evidence_roles(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    snapshot = build_review_snapshot(root, target_claim_ref=refs["concerted"])

    assert snapshot["schema_version"] == "ts-review-snapshot/4"
    assert snapshot["target_claim_ref"] == refs["concerted"]
    assert snapshot["dependency_refs"]["claim_refs"] == [refs["concerted"], refs["stepwise"]]
    assert snapshot["dependency_refs"]["finding_refs"] == [refs["ambiguity"]]
    assert all("role" not in item and "layer" not in item for item in snapshot["findings"])


def test_validation_capabilities_are_data_driven() -> None:
    capabilities = proof_capabilities()

    assert capabilities["schema_version"] == "ts-proof-capabilities/1"
    assert capabilities["agent_supplied_executable_code"] is False
    assert "observation.equals" in {item["name"] for item in capabilities["predicates"]}
    assert "classical-ts" in {item["template_id"] for item in capabilities["templates"]}
    assert "accepted-ts" in {item["profile_id"] for item in capabilities["acceptance_profiles"]}

    focused = proof_capabilities(template_id="reaction-coordinate", template_version="1")
    template = focused["selected_template"]
    assert template["parameters"] == {"subject_ref": {"type": "string", "required": True}}
    assert template["definition"]["checks"][0]["parameters"]["selector"]["concept_id"] == (
        "vibration.mode_matches_reaction_coordinate"
    )
    assert template["digest"].startswith("sha256:")


def test_claim_projection_uses_numeric_id_order(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted = compile_change(
        root,
        {
            "rationale": "Create enough Claims to exercise numeric ordering.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": f"claim{index}",
                    "claimType": "ordering_probe",
                    "statement": f"Claim number {index}.",
                }
                for index in range(1, 11)
            ],
        },
    )
    apply_compiled_change(root, drafted["decision"])
    refs = [drafted["allocated_refs"][f"claim{index}"] for index in range(1, 11)]

    context = compile_context(root, mode="subgraph", claim_refs=list(reversed(refs)))

    assert [item["claim_id"] for item in context["claims"]] == refs


def test_focused_validation_capabilities_require_a_complete_registered_ref() -> None:
    with pytest.raises(ContextCompileError, match="template_id and template_version together"):
        proof_capabilities(template_id="reaction-coordinate")
    with pytest.raises(ContextCompileError, match="does not exist"):
        proof_capabilities(template_id="reaction-coordinate", template_version="999")


def test_context_and_review_snapshot_expose_derived_acceptance_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = accept_research_claim(root)

    context = compile_context(root, mode="claim", claim_ref=refs["claim"])
    snapshot = build_review_snapshot(root, target_claim_ref=refs["claim"])

    assert context["acceptance_summary"]["current_refs"] == [f"acceptances/{refs['acceptance']}.json"]
    assert context["acceptances"][0]["current"] is True
    assert snapshot["acceptances"][0]["acceptance_id"] == refs["acceptance"]
    assert snapshot["dependency_refs"]["acceptance_refs"] == [refs["acceptance"]]
