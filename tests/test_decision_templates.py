from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ts_agent.workspace import init_workspace
from ts_agent.workspace.decision import INPUT_OPERATIONS, validate_decision
from ts_agent.workspace.operation_registry import (
    INPUT_OPERATION_CONTRACTS,
    input_operation_names,
    operation_catalog,
    validate_input_operation_keys,
)
from ts_agent.workspace.errors import ContractError
from tests.kernel_helpers import compile_change


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "skills" / "tspi-orchestration" / "assets" / "templates" / "decision"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
EXPECTED_FILES = {
    "README.md",
    "accept_claim.json",
    "complete_node.json",
    "create_phase.json",
    "create_claim.json",
    "evaluate_proof.json",
    "freeze_proof_spec.json",
    "record_finding.json",
    "record_observation.json",
    "record_observation_candidate.json",
    "relate_claims.json",
    "resolve_finding.json",
    "set_focus.json",
    "start_node.json",
    "update_claim.json",
}


def test_templates_are_composable_operation_snippets() -> None:
    assert {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()} == EXPECTED_FILES
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["op"] in INPUT_OPERATIONS
        assert "schema_version" not in value
        assert "decision_id" not in value
        assert "context_ref" not in value
        assert "base_revision" not in value
        assert not any(key.endswith("_id") for key in value if key != "conceptId")


def test_operation_registry_is_the_compiler_vocabulary() -> None:
    assert INPUT_OPERATIONS == input_operation_names()
    assert "record_observation_candidate" not in INPUT_OPERATIONS
    for name in INPUT_OPERATIONS:
        contract = INPUT_OPERATION_CONTRACTS[name]
        assert "op" in contract.required


def test_operation_catalog_groups_public_variants_and_exact_fields() -> None:
    catalog = operation_catalog("record_observation")

    assert catalog["schema_version"] == "ts-change-operation-catalog/1"
    assert catalog["selected_operation"] == "record_observation"
    constraints = catalog["operations"][0].pop("value_constraints")
    assert constraints["artifact_binding"] == {"required": ["artifactId"], "optional": ["sha256"]}
    assert constraints["direct_provenance"]["required"] == ["producer"]
    assert "json" in constraints["datatype"]
    assert catalog["operations"] == [{
        "op": "record_observation",
        "template_ref": "skills/tspi-orchestration/assets/templates/decision/record_observation.json",
        "variants": [
            {
                "variant": "direct",
                "template_ref": "skills/tspi-orchestration/assets/templates/decision/record_observation.json",
                "required_fields": sorted(INPUT_OPERATION_CONTRACTS["record_observation"].required),
                "optional_fields": sorted(INPUT_OPERATION_CONTRACTS["record_observation"].optional),
            },
            {
                "variant": "candidate",
                "template_ref": "skills/tspi-orchestration/assets/templates/decision/record_observation_candidate.json",
                "required_fields": sorted(INPUT_OPERATION_CONTRACTS["record_observation_candidate"].required),
                "optional_fields": sorted(INPUT_OPERATION_CONTRACTS["record_observation_candidate"].optional),
            },
        ],
    }]


def test_operation_catalog_rejects_unknown_operation() -> None:
    with pytest.raises(ContractError, match="unsupported change operation"):
        operation_catalog("guess_fields")


def test_operation_registry_rejects_non_object_and_selector_mismatch() -> None:
    with pytest.raises(ContractError, match="must be an object"):
        validate_input_operation_keys([])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="does not match value op"):
        validate_input_operation_keys(
            {"op": "create_claim"},
            operation="start_node",
        )


def test_operation_registry_accepts_public_name_for_named_variant() -> None:
    validate_input_operation_keys(
        {
            "op": "record_observation",
            "local_ref": "candidate",
            "nodeRef": "node_1",
            "candidate": {"artifactId": "art_" + "a" * 24, "candidateId": "candidate_1"},
            "conceptId": "test.confirmed",
            "subjectRef": "subject",
            "summary": "A parser candidate.",
        },
        operation="record_observation_candidate",
    )


def test_every_public_operation_variant_has_a_matching_template_shape() -> None:
    """Keep the on-demand catalog, registry, and snippets from drifting."""

    templates = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in TEMPLATE_DIR.glob("*.json")
    }
    contracts_by_template = {
        contract.template_ref(registry_name).rsplit("/", 1)[-1]: (registry_name, contract)
        for registry_name, contract in INPUT_OPERATION_CONTRACTS.items()
    }
    assert set(templates) == set(contracts_by_template)
    for filename, template in templates.items():
        registry_name, contract = contracts_by_template[filename]
        assert template["op"] == contract.exposed_name(registry_name)
        keys = set(template)
        assert contract.required <= keys
        assert keys <= contract.required | contract.optional

    catalog = operation_catalog()
    catalog_variants = {
        variant["template_ref"].rsplit("/", 1)[-1]
        for operation in catalog["operations"]
        for variant in operation["variants"]
    }
    assert catalog_variants == set(templates)


def test_create_claim_template_cannot_hide_required_preregistration_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="missing fields: .*question"):
        # Use the production compiler directly; test-only helpers intentionally
        # add fixture defaults and would conceal a public template regression.
        from ts_agent.workspace.decision import _compile_change

        _compile_change(
            workspace,
            {
                "schema_version": "ts-change-request/1",
                "rationale": "Reject an under-specified Claim.",
                "basis_refs": [],
                "operations": [{
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": "mechanism",
                    "statement": "The pathway is concerted.",
                }],
            },
        )


def test_representative_templates_compose_through_draft_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    operations = [
        _render("create_phase.json", PHASE_TITLE="Mechanism study", PHASE_OBJECTIVE="Test the candidate mechanism."),
        _render(
            "create_claim.json",
            CLAIM_QUESTION="Does the pathway follow a concerted mechanism?",
            CLAIM_TYPE="mechanism",
            CLAIM_STATEMENT="The pathway is concerted.",
            CLAIM_SCOPE="The declared reactants and the selected computational method.",
            CLAIM_UNCERTAINTY="The mechanism remains uncertain before validation.",
            CLAIM_PREDICTION="A validated transition state connects both declared endpoints.",
            CLAIM_FALSIFIER="No valid transition state connects the declared endpoints.",
        ),
        _render(
            "start_node.json",
            PHASE_REF="$phase",
            TITLE="Concerted pathway test",
            OBJECTIVE="Test the concerted pathway.",
            DELIVERABLE="A bounded result for the concerted-pathway hypothesis.",
            CLAIM_REF="$claim",
        ),
        _render(
            "record_finding.json",
            FINDING_TYPE="missing_connectivity",
            FINDING_STATEMENT="Connectivity is not yet established.",
            CLAIM_REF="$claim",
            NODE_REF="$node",
        ),
        _render("complete_node.json", NODE_REF="$node", RESULT_SUMMARY="The bounded search completed."),
    ]
    drafted = compile_change(
        workspace,
        {"rationale": "Compose one atomic research Decision.", "basis_refs": [], "operations": operations},
    )
    decision = validate_decision(drafted["decision"])
    assert decision["schema_version"] == "ts-research-decision/3"
    assert set(drafted["allocated_refs"]) == {"phase", "claim", "node", "finding"}
    assert [operation["op"] for operation in decision["operations"]] == [
        "append_research_phase",
        "append_claim",
        "append_research_node",
        "append_finding",
        "complete_research_node",
    ]


def test_templates_are_strategy_neutral_and_have_no_removed_taxonomy() -> None:
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.glob("*.json"))
    for forbidden in (
        '"phase_type"',
        '"phase_status"',
        '"node_type"',
        '"evidence_role"',
        '"evidence_layer"',
        '"required_gates"',
        '"gate_type"',
        '"branch_context"',
    ):
        assert forbidden not in rendered


def _render(name: str, **values: str) -> dict:
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    required = set(PLACEHOLDER_RE.findall(text))
    assert required == set(values), (name, required, set(values))
    return json.loads(PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], text))
