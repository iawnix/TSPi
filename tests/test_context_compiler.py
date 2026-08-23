from __future__ import annotations

from pathlib import Path

import pytest

from tests.v4_helpers import accept_research_claim
from ts_workspace.context import ContextCompileError, build_review_snapshot, compile_context, validation_capabilities
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace
from ts_workspace.io import read_json


def _seed(root: Path) -> dict[str, str]:
    drafted = draft_decision(
        root,
        {
            "rationale": "Create competing Claims and one open frontier Act.",
            "basis_refs": [],
            "operations": [
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
                    "op": "start_act",
                    "local_ref": "search",
                    "title": "Bounded research act",
                    "deliverable": "One bounded research result.",
                    "objective": "Search for observations that distinguish the mechanisms.",
                    "claimRefs": ["$concerted", "$stepwise"],
                },
                {
                    "op": "record_finding",
                    "local_ref": "ambiguity",
                    "findingType": "mechanism_ambiguity",
                    "severity": "warning",
                    "statement": "No discriminating path evidence is available yet.",
                    "claimRefs": ["$concerted", "$stepwise"],
                    "actRefs": ["$search"],
                },
                {"op": "set_focus", "claimRefs": ["$concerted"], "actRefs": ["$search"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_frontier_projection_includes_competing_claim_and_open_finding(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    context = compile_context(root, mode="frontier")

    assert context["schema_version"] == "ts-context-projection/1"
    assert context["projection_id"].startswith("ctx_")
    assert {item["claim_id"] for item in context["claims"]} == {refs["concerted"], refs["stepwise"]}
    assert [item["relation_id"] for item in context["claim_relations"]] == [refs["alternatives"]]
    assert [item["act_id"] for item in context["research_acts"]] == [refs["search"]]
    assert [item["finding_id"] for item in context["open_findings"]] == [refs["ambiguity"]]
    assert context["retrieval"]["has_more"] is False


def test_context_derives_claim_act_link_from_creator_provenance(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    act_draft = draft_decision(
        root,
        {
            "rationale": "Start an exploratory Act before it discovers a Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "start_act", "local_ref": "exploration", "title": "Bounded research act", "deliverable": "One bounded research result.", "objective": "Look for an alternative mechanism."}
            ],
        },
    )
    apply_decision(root, act_draft["decision"])
    act_id = act_draft["allocated_refs"]["exploration"]
    claim_draft = draft_decision(
        root,
        {
            "rationale": "Record the alternative Claim discovered by the Act.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": "alternative",
                    "claimType": "mechanism",
                    "statement": "An alternative pathway may exist.",
                    "createdByAct": act_id,
                }
            ],
        },
    )
    apply_decision(root, claim_draft["decision"])
    claim_id = claim_draft["allocated_refs"]["alternative"]

    canonical_act = read_json(root / "research_acts.json")["acts"][0]
    assert canonical_act["claim_refs"] == []
    act_context = compile_context(root, mode="act", act_ref=act_id)
    assert [row["claim_id"] for row in act_context["claims"]] == [claim_id]
    assert act_context["research_acts"][0]["claim_refs"] == []
    assert act_context["research_acts"][0]["related_claim_refs"] == [claim_id]
    assert [row["act_id"] for row in compile_context(root, mode="claim", claim_ref=claim_id)["research_acts"]] == [act_id]
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

    assert snapshot["schema_version"] == "ts-review-snapshot/3"
    assert snapshot["target_claim_ref"] == refs["concerted"]
    assert snapshot["dependency_refs"]["claim_refs"] == [refs["concerted"], refs["stepwise"]]
    assert snapshot["dependency_refs"]["finding_refs"] == [refs["ambiguity"]]
    assert all("role" not in item and "layer" not in item for item in snapshot["findings"])


def test_validation_capabilities_are_data_driven() -> None:
    capabilities = validation_capabilities()

    assert capabilities["schema_version"] == "ts-validation-capabilities/2"
    assert capabilities["agent_supplied_executable_code"] is False
    assert "observation.equals" in {item["name"] for item in capabilities["predicates"]}
    assert "classical-ts" in {item["template_id"] for item in capabilities["templates"]}
    assert "accepted-ts" in {item["profile_id"] for item in capabilities["acceptance_profiles"]}

    focused = validation_capabilities(template_id="reaction-coordinate", template_version="1")
    template = focused["selected_template"]
    assert template["parameters"] == {"subject_ref": {"type": "string", "required": True}}
    assert template["definition"]["checks"][0]["parameters"]["selector"]["concept_id"] == (
        "vibration.mode_matches_reaction_coordinate"
    )
    assert template["digest"].startswith("sha256:")


def test_claim_projection_uses_numeric_id_order(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted = draft_decision(
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
    apply_decision(root, drafted["decision"])
    refs = [drafted["allocated_refs"][f"claim{index}"] for index in range(1, 11)]

    context = compile_context(root, mode="subgraph", claim_refs=list(reversed(refs)))

    assert [item["claim_id"] for item in context["claims"]] == refs


def test_focused_validation_capabilities_require_a_complete_registered_ref() -> None:
    with pytest.raises(ContextCompileError, match="template_id and template_version together"):
        validation_capabilities(template_id="reaction-coordinate")
    with pytest.raises(ContextCompileError, match="does not exist"):
        validation_capabilities(template_id="reaction-coordinate", template_version="999")


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
