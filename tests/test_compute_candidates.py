from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.workspace_helpers import apply_change, bootstrap_workspace_fixture, start_research_node
from ts_agent.compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    prepare_calculation,
)
from ts_agent.io import read_json, write_json
from ts_agent.report import build_report_package
from ts_agent.report.context import collect_report_context
from ts_agent.web.normalize import node_payload
from ts_agent.workspace import ContractError, validate_workspace


def _gaussian_log() -> str:
    return "\n".join(
        [
            " Entering Link 1 = synthetic",
            " #P B3LYP/6-31G(d) opt=(ts,calcfc) freq",
            " -------------------------------------------------------------------",
            " SCF Done:  E(RB3LYP) =  -40.123456     A.U. after 10 cycles",
            " Standard orientation:",
            " ---------------------------------------------------------------------",
            " Center     Atomic      Atomic             Coordinates (Angstroms)",
            " Number     Number       Type             X           Y           Z",
            " ---------------------------------------------------------------------",
            "      1          1           0        0.000000    0.000000    0.000000",
            " ---------------------------------------------------------------------",
            " Maximum Force            0.000010     0.000450     YES",
            " RMS     Force            0.000006     0.000300     YES",
            " Maximum Displacement     0.000020     0.001800     YES",
            " RMS     Displacement     0.000012     0.001200     YES",
            " Stationary point found.",
            " Frequencies --  -512.3000   47.1000   98.2000",
            " Normal termination of Gaussian 16",
        ]
    )


def _parsed_workspace(tmp_path: Path) -> tuple[Path, str, str, Path, dict]:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(workspace)["node_id"]
    gjf = workspace / "inputs" / "candidate.gjf"
    gjf.write_text(
        "%chk=candidate.chk\n#P B3LYP/6-31G(d) opt=(ts,calcfc) freq\n\nTS\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    artifact_id = next(
        item["artifact_id"]
        for item in list_calculation_artifacts(workspace)["artifacts"]
        if item["path"] == "inputs/candidate.gjf"
    )
    created = create_calculation_intent(
        workspace,
        {
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": "Parse one bounded Gaussian result into candidates.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "gaussian.opt_freq",
            "capability_version": "1",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
            "parameters": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])
    output_ref = f"nodes/{node_id}/attempts/{created['intent_id']}/outputs/gaussian.out"
    output_path = workspace / output_ref
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_gaussian_log(), encoding="utf-8")
    result = parse_calculation(workspace, created["intent_id"], output_ref)
    candidate_path = output_path.parent / "parsed" / "observation_candidates.json"
    return workspace, node_id, created["intent_id"], candidate_path, result


def _candidate_binding(workspace: Path, candidate_path: Path, field: str) -> tuple[dict, dict]:
    relative = candidate_path.relative_to(workspace).as_posix()
    artifact = next(
        item
        for item in list_calculation_artifacts(workspace)["artifacts"]
        if item["path"] == relative
    )
    document = read_json(candidate_path)
    candidate = next(
        item for item in document["candidates"]
        if item["qualifiers"]["parser_field"] == field
    )
    return {"artifactId": artifact["artifact_id"], "candidateId": candidate["candidate_id"]}, candidate


def test_parser_candidates_are_operational_until_root_promotes_one(tmp_path: Path) -> None:
    workspace, node_id, intent_id, candidate_path, result = _parsed_workspace(tmp_path)
    document = read_json(candidate_path)
    binding, candidate = _candidate_binding(workspace, candidate_path, "normal_termination")

    assert document["schema_version"] == "ts-observation-candidates/1"
    assert document["intent_id"] == intent_id
    assert [item["candidate_id"] for item in document["candidates"]] == [
        f"candidate_{index}" for index in range(1, len(document["candidates"]) + 1)
    ]
    assert candidate["value"] is True
    assert candidate["datatype"] == "boolean"
    assert candidate_path.relative_to(workspace).as_posix() in result["artifact_refs"]
    assert read_json(workspace / "observations.json")["observations"] == []

    changed = apply_change(
        workspace,
        {
            "rationale": "Interpret one deterministic parser candidate as a semantic observation.",
            "basis_refs": [binding["artifactId"]],
            "operations": [
                {
                    "op": "record_observation",
                    "local_ref": "normal",
                    "nodeRef": node_id,
                    "candidate": binding,
                    "conceptId": "program.normal_termination",
                    "subjectRef": intent_id,
                    "summary": "The selected Gaussian job section terminated normally.",
                    "qualifiers": {"selection": "final_job_section"},
                }
            ],
        },
    )
    observation = read_json(workspace / "observations.json")["observations"][0]
    assert changed["allocated_refs"]["normal"] == "obs_1"
    assert observation["concept_id"] == "program.normal_termination"
    assert observation["subject_ref"] == intent_id
    assert observation["value"] is True
    assert observation["qualifiers"]["parser_field"] == "normal_termination"
    assert observation["qualifiers"]["selection"] == "final_job_section"
    assert observation["candidate_ref"]["candidate_id"] == candidate["candidate_id"]
    assert set(observation["artifact_refs"]) == set(observation["provenance"]["source_digests"])
    assert validate_workspace(workspace)["valid"] is True


def test_web_projects_parser_candidates_separately_from_canonical_observations(tmp_path: Path) -> None:
    workspace, node_id, intent_id, _candidate_path, _result = _parsed_workspace(tmp_path)

    payload = node_payload(workspace, node_id)
    attempt = next(row for row in payload["research_node"]["attempts"] if row["intent_id"] == intent_id)
    projection = attempt["observation_candidates"]

    assert projection["status"] == "pending_interpretation"
    assert projection["pending_interpretation"] is True
    assert projection["candidate_count"] > 0
    assert projection["promoted_count"] == 0
    assert projection["pending_count"] == projection["candidate_count"]
    assert all(row["state"] == "pending_interpretation" for row in projection["candidates"])
    assert payload["observations"] == []


def test_parser_candidates_and_artifact_catalog_do_not_enter_scientific_report(tmp_path: Path) -> None:
    workspace, _node_id, _intent_id, candidate_path, _result = _parsed_workspace(tmp_path)

    context = collect_report_context(workspace)
    assert context["observations"] == []
    serialized_context = json.dumps(context, ensure_ascii=False, sort_keys=True)
    assert "observation_candidates" not in serialized_context
    assert "candidate_1" not in serialized_context

    package = build_report_package(workspace, workspace / "reports" / "candidate-separation")
    manifest = read_json(Path(package["manifest"]))
    assert all("observation_candidates" not in row["ref"] for row in manifest["files"])
    assert "candidate_1" not in (workspace / "reports" / "candidate-separation" / "final_report.md").read_text(encoding="utf-8")
    assert candidate_path.is_file()


def test_web_marks_selected_candidate_promoted_after_explicit_promotion(tmp_path: Path) -> None:
    workspace, node_id, intent_id, candidate_path, _result = _parsed_workspace(tmp_path)
    binding, _candidate = _candidate_binding(workspace, candidate_path, "normal_termination")
    _promote(workspace, node_id, binding)

    payload = node_payload(workspace, node_id)
    attempt = next(row for row in payload["research_node"]["attempts"] if row["intent_id"] == intent_id)
    projection = attempt["observation_candidates"]

    assert projection["status"] == "pending_interpretation"
    assert projection["promoted_count"] == 1
    assert projection["pending_count"] == projection["candidate_count"] - 1
    selected = next(row for row in projection["candidates"] if row["candidate_id"] == binding["candidateId"])
    assert selected["state"] == "promoted"
    assert selected["observation_refs"]
    assert all(row["observation_id"] in selected["observation_refs"] for row in payload["observations"])


def test_web_reports_candidate_digest_drift_without_ingesting_invalid_output(tmp_path: Path) -> None:
    workspace, node_id, intent_id, candidate_path, _result = _parsed_workspace(tmp_path)
    document = read_json(candidate_path)
    document["candidates"][0]["summary"] = "Changed after parser completion."
    write_json(candidate_path, document)

    payload = node_payload(workspace, node_id)
    attempt = next(row for row in payload["research_node"]["attempts"] if row["intent_id"] == intent_id)
    projection = attempt["observation_candidates"]

    assert projection["status"] == "invalid"
    assert "digest" in projection["error"] or "bound" in projection["error"]
    assert payload["observations"] == []


def test_candidate_promotion_rejects_candidate_or_source_digest_drift(tmp_path: Path) -> None:
    workspace, node_id, _intent_id, candidate_path, _result = _parsed_workspace(tmp_path)
    binding, _candidate = _candidate_binding(workspace, candidate_path, "normal_termination")
    document = read_json(candidate_path)
    document["candidates"][0]["summary"] = "Tampered parser summary."
    write_json(candidate_path, document)
    tampered_binding, _ = _candidate_binding(
        workspace,
        candidate_path,
        document["candidates"][0]["qualifiers"]["parser_field"],
    )
    with pytest.raises(ContractError, match="parser binding changed"):
        _promote(workspace, node_id, tampered_binding)
    assert read_json(workspace / "observations.json")["observations"] == []

    workspace2, node_id2, _intent_id2, candidate_path2, _result2 = _parsed_workspace(tmp_path / "source")
    binding2, _ = _candidate_binding(workspace2, candidate_path2, "normal_termination")
    source = candidate_path2.parent.parent / "gaussian.out"
    source.write_text(source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(ContractError, match="source artifact changed"):
        _promote(workspace2, node_id2, binding2)


def test_candidate_promotion_rejects_cross_node_unknown_candidate_and_owned_overrides(tmp_path: Path) -> None:
    workspace, node_id, _intent_id, candidate_path, _result = _parsed_workspace(tmp_path)
    binding, _candidate = _candidate_binding(workspace, candidate_path, "normal_termination")
    other_node = start_research_node(workspace, title="Unrelated Node")["node_id"]
    with pytest.raises(ContractError, match="outside an Attempt parsed output"):
        _promote(workspace, other_node, binding)

    unknown = {**binding, "candidateId": "candidate_999"}
    with pytest.raises(ContractError, match="unknown ObservationCandidate"):
        _promote(workspace, node_id, unknown)

    request = _promotion_request(node_id, binding)
    request["operations"][0]["value"] = False
    with pytest.raises(ContractError, match="unsupported fields: value"):
        apply_change(workspace, request)


def _promote(workspace: Path, node_id: str, binding: dict) -> dict:
    return apply_change(workspace, _promotion_request(node_id, binding))


def _promotion_request(node_id: str, binding: dict) -> dict:
    return {
        "rationale": "Attempt one bounded candidate promotion.",
        "basis_refs": [binding["artifactId"]],
        "operations": [
            {
                "op": "record_observation",
                "local_ref": "candidate",
                "nodeRef": node_id,
                "candidate": binding,
                "conceptId": "program.normal_termination",
                "subjectRef": "selected-calculation",
                "summary": "Promote the selected deterministic parser value.",
            }
        ],
    }
