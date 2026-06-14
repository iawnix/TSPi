from __future__ import annotations

from transition_state_workflow.gate.validate.common import (
    clean_string_list,
    clean_string_set,
    evidence_ids_from_records,
    iter_object_records,
    register_unique_id,
    require_list_field,
    validate_evidence_refs,
    validate_known_node_ref,
)
from transition_state_workflow.gate.validate.contracts import Finding


def finding_codes(findings: list[Finding]) -> list[str]:
    return [finding.code for finding in findings]


def test_common_clean_string_helpers_drop_empty_values() -> None:
    values = [" a ", "", None, "b", " a "]

    assert clean_string_list(values) == ["a", "b", "a"]
    assert clean_string_set(values) == {"a", "b"}


def test_common_list_and_object_record_helpers_emit_contract_findings() -> None:
    findings: list[Finding] = []

    assert require_list_field({"records": "bad"}, "records", findings, code="not_list", message="records bad", path="x.json") == []
    records = list(
        iter_object_records(
            [{"id": "ok"}, "bad"],
            findings,
            code="not_object",
            message_template="records[{index}] bad",
            path="x.json",
        )
    )

    assert records == [(0, {"id": "ok"})]
    assert finding_codes(findings) == ["not_list", "not_object"]
    assert findings[1].message == "records[1] bad"


def test_common_unique_and_node_reference_helpers_preserve_finding_context() -> None:
    findings: list[Finding] = []
    seen: set[str] = set()

    assert register_unique_id(" n001 ", seen, findings, duplicate_code="duplicate", duplicate_message_template="duplicate {value}", path="tree.json") == "n001"
    assert register_unique_id("n001", seen, findings, duplicate_code="duplicate", duplicate_message_template="duplicate {value}", path="tree.json", node_id="n001") == "n001"
    assert register_unique_id("", seen, findings, missing_code="missing", missing_message="missing id", duplicate_code="duplicate", duplicate_message_template="duplicate {value}", path="tree.json") == ""
    assert validate_known_node_ref("missing", {"n001"}, findings, code="missing_node", message="missing node", path="tree.json") == "missing"

    assert finding_codes(findings) == ["duplicate", "missing", "missing_node"]
    assert findings[0].node_id == "n001"
    assert findings[2].node_id == "missing"


def test_common_evidence_reference_helpers_validate_registry_like_payloads() -> None:
    findings: list[Finding] = []
    evidence_ids = evidence_ids_from_records(
        {
            "records": [
                {"evidence_id": "e001"},
                {"evidence_id": ""},
                "bad",
            ]
        }
    )

    validate_evidence_refs(
        {"evidence_refs": ["e001", "missing", ""]},
        evidence_ids,
        findings,
        code="missing_evidence",
        message_template="missing evidence {ref_id}",
        path="tree.json",
        node_id="n001",
    )

    assert evidence_ids == {"e001"}
    assert finding_codes(findings) == ["missing_evidence"]
    assert findings[0].message == "missing evidence missing"
    assert findings[0].node_id == "n001"
