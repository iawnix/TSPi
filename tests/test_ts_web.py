from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import threading
from importlib.resources import files
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "components" / "ts-web"))


def _provider_for(state: Path) -> ProviderClient:
    return ProviderClient(str(ROOT / "scripts" / "ts_web_provider.py"), state)

from tests.workspace_helpers import (
    accept_research_claim,
    calculation_prepared_fixture,
    calculation_result_fixture,
)
from ts_agent.projection.normalize import (
    normalize_workspace,
    workspace_snapshot,
    graph_payload_from_view,
    claim_payload,
    node_payload,
    research_files_payload,
    list_node_files,
)
from ts_agent.projection.registry import register_workspace, register_workspaces
from ts_agent.projection.file_preview import MAX_TEXT_BYTES
from ts_agent.projection.file_preview import preview_capability, read_text_preview
from ts_agent.projection.research_map import project_research_map
from ts_web import server as ts_web_server
from ts_web.provider import ProviderClient
from ts_web.registry import (
    list_workspaces,
    reconcile_workspace_registry,
    register_workspaces,
    workspace_discovery_roots,
)
from ts_web.server import create_server
from tests.kernel_helpers import compile_change
from ts_agent.workspace.engine import init_workspace
from tests.kernel_helpers import apply_compiled_change




def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _assert_public_payload(payload: object, private_root: Path) -> None:
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "source_root" not in rendered
    assert str(private_root) not in rendered


def _make_workspace(root: Path) -> dict[str, str]:
    init_workspace(root)
    drafted = compile_change(
        root,
        {
            "rationale": "Create a small Claim graph and ResearchNode DAG for the explorer.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "mechanism",
                    "title": "Mechanism search",
                    "objective": "Distinguish concerted and stepwise pathways.",
                },
                {
                    "op": "create_claim",
                    "local_ref": "concerted",
                    "claimType": "mechanism",
                    "statement": "The pathway is concerted.",
                    "falsifiers": ["A stable stepwise intermediate is observed."],
                },
                {
                    "op": "create_claim",
                    "local_ref": "stepwise",
                    "claimType": "mechanism",
                    "statement": "The pathway is stepwise.",
                },
                {
                    "op": "relate_claims",
                    "local_ref": "alternatives",
                    "sourceClaimRef": "$concerted",
                    "targetClaimRef": "$stepwise",
                    "relationType": "alternative_to",
                    "rationale": "The Claims are competing explanations.",
                },
                {
                    "op": "start_node",
                    "local_ref": "search",
                    "phaseRef": "$mechanism",
                    "title": "Bounded research node",
                    "deliverable": "One bounded research result.",
                    "objective": "Search for observations that distinguish the mechanisms.",
                    "primaryClaimRef": "$concerted",
                    "claimRefs": ["$concerted", "$stepwise"],
                    "tags": ["candidate-search"],
                },
                {
                    "op": "record_observation",
                    "local_ref": "normal",
                    "nodeRef": "$search",
                    "conceptId": "program.normal_termination",
                    "subjectRef": "calc_probe",
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The probe terminated normally.",
                    "provenance": {"producer": "test-parser"},
                },
                {
                    "op": "freeze_proof_spec",
                    "local_ref": "spec",
                    "nodeRef": "$search",
                    "targetClaimRef": "$concerted",
                    "dimension": "probe",
                    "title": "Program completion probe",
                    "definition": {
                        "checks": [
                            {
                                "check_id": "normal",
                                "predicate": "observation.equals",
                                "parameters": {
                                    "selector": {
                                        "concept_id": "program.normal_termination",
                                        "subject_ref": "calc_probe",
                                    },
                                    "expected": True,
                                },
                                "blocking": True,
                            }
                        ],
                        "success_policy": {"mode": "all_blocking"},
                    },
                },
                {
                    "op": "evaluate_proof",
                    "local_ref": "result",
                    "nodeRef": "$search",
                    "proofRef": "$spec",
                    "observationRefs": ["$normal"],
                },
                {
                    "op": "update_claim",
                    "claimRef": "$concerted",
                    "status": "supported",
                    "summary": "The bounded probe passed.",
                    "observationRefs": ["$normal"],
                    "validationResultRefs": ["$result"],
                },
                {
                    "op": "record_finding",
                    "local_ref": "ambiguity",
                    "findingType": "mechanism_ambiguity",
                    "severity": "warning",
                    "statement": "Connectivity evidence is still absent.",
                    "claimRefs": ["$concerted", "$stepwise"],
                    "nodeRefs": ["$search"],
                    "basisObservationRefs": ["$normal"],
                },
                {
                    "op": "complete_node",
                    "nodeRef": "$search",
                    "outcome": "inconclusive",
                    "summary": "The probe completed but did not resolve the mechanism.",
                    "openQuestions": ["Which endpoints are connected?"],
                },
                {"op": "set_focus", "claimRefs": ["$concerted"], "nodeRefs": ["$search"]},
            ],
        },
    )
    apply_compiled_change(root, drafted["decision"])
    refs = dict(drafted["allocated_refs"])
    connectivity = compile_change(
        root,
        {
            "rationale": "The candidate probe is complete but endpoint identity remains unresolved, so connectivity becomes the next research decision.",
            "basis_refs": [refs["search"]],
            "operations": [
                {
                    "op": "start_node",
                    "local_ref": "connectivity",
                    "phaseRef": refs["mechanism"],
                    "title": "Resolve bidirectional connectivity",
                    "deliverable": "One endpoint-connectivity conclusion.",
                    "objective": "Test bidirectional connectivity.",
                    "dependencyRefs": [refs["search"]],
                    "primaryClaimRef": refs["concerted"],
                    "claimRefs": [refs["concerted"]],
                    "tags": ["connectivity"],
                },
                {"op": "set_focus", "claimRefs": [refs["concerted"]], "nodeRefs": ["$connectivity"]},
            ],
        },
    )
    apply_compiled_change(root, connectivity["decision"])
    refs.update(connectivity["allocated_refs"])
    node_id = refs["connectivity"]
    artifact = root / "nodes" / node_id / "outputs" / "probe.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    workspace_identity = json.loads(
        (root / ".agents" / "workspace-identity.json").read_text(encoding="utf-8")
    )["workspace_id"]
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "intent.json",
        {
            "schema_version": "ts-calculation-intent/7",
            "intent_id": "calc_1",
            "node_id": node_id,
            "node_contract_digest": "sha256:" + "a" * 64,
            "scientific_intent_digest": "sha256:" + "b" * 64,
            "capability": "gaussian.irc",
            "capability_version": "1",
            "capability_descriptor_digest": "sha256:" + "c" * 64,
            "expected_output_roles": ["program_output", "reaction_path"],
            "backend": "gaussian",
            "task_type": "irc",
            "purpose": "Trace both directions from the selected transition-state candidate.",
            "attempt_kind": "primary",
            "lineage": None,
            "input_refs": {"gjf": f"nodes/{node_id}/inputs/candidate.gjf"},
            "input_bindings": [
                {
                    "input_role": "gjf",
                    "artifact_id": "art_" + "0" * 24,
                    "path": f"nodes/{node_id}/inputs/candidate.gjf",
                    "sha256": "sha256:" + "d" * 64,
                    "owner_node": node_id,
                    "source_intent_id": None,
                }
            ],
            "parameters": {
                "method": "M062X",
                "basis": "6-31+G(d,p)",
                "candidateStrategy": "bidirectional_irc",
            },
            "expected_artifacts": [f"nodes/{node_id}/attempts/calc_1/outputs/gaussian.out"],
            "execution_target": {
                "kind": "remote",
                "authority": "execution_mirror",
                "profile": "cluster_1w",
                "workspace_id": workspace_identity,
                "remote_dir": f"/remote/ts/workspaces/{workspace_identity}/runs/{node_id}/calc_1",
                "resources": {
                    "queue": "batch",
                    "nodes": 1,
                    "ncpus": 8,
                    "memory": "1gb",
                    "walltime": "01:00:00",
                    "ngpus": 0,
                    "mpiprocs": None,
                    "ompthreads": None,
                },
            },
            "dry_run": False,
        },
    )
    status = calculation_result_fixture(
        json.loads(
            (root / "nodes" / node_id / "attempts" / "calc_1" / "intent.json").read_text(
                encoding="utf-8"
            )
        ),
        state="completed",
        program_status="completed",
        job_id="123.cluster",
    )
    status["provenance"].update(
        {
            "observed_at": "2026-08-16T00:04:00+00:00",
            "program_record": {
                "started_at": "2026-08-16T00:02:00+00:00",
                "finished_at": "2026-08-16T00:03:30+00:00",
            },
        }
    )
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "prepared.json",
        calculation_prepared_fixture(
            json.loads(
                (root / "nodes" / node_id / "attempts" / "calc_1" / "intent.json").read_text(
                    encoding="utf-8"
                )
            )
        ),
    )
    _write(root / "nodes" / node_id / "attempts" / "calc_1" / "status.json", status)
    _write(
        root / "nodes" / node_id / "activities" / "op_1" / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": "op_1",
            "kind": "render",
            "operation": "molecule",
            "node_refs": [node_id],
            "request": {},
            "started_at": "2026-08-16T00:00:00+00:00",
        },
    )
    _write(
        root / "nodes" / node_id / "activities" / "op_1" / "status.json",
        {
            "schema_version": "ts-deterministic-activity-status/1",
            "activity_id": "op_1",
            "kind": "render",
            "operation": "molecule",
            "node_refs": [node_id],
            "status": "completed",
            "started_at": "2026-08-16T00:00:00+00:00",
            "completed_at": "2026-08-16T00:01:00+00:00",
            "error": None,
        },
    )
    _write(
        root / "nodes" / node_id / "activities" / "op_1" / "result.json",
        {"outcome": "success", "summary": "Molecule rendered."},
    )
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "runs" / "sub_1" / "task.json",
        {
            "task_id": "sub_1",
            "role": "compute",
            "authority": "operational",
            "operation": "finalize",
            "scope": {"node_refs": [node_id], "claim_refs": [refs["concerted"]]},
            "inputs": {"node_id": node_id, "intent_id": "calc_1", "backend": "gaussian"},
        },
    )
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "runs" / "sub_1" / "run.json",
        {
            "task_id": "sub_1",
            "status": "completed",
            "started_at": "2026-08-16T00:02:00+00:00",
            "finished_at": "2026-08-16T00:03:00+00:00",
            "error": None,
        },
    )
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "runs" / "sub_1" / "result.json",
        {"outcome": "success", "summary": "Calculation finalized."},
    )
    _write(
        root / "reviews" / refs["concerted"] / "runs" / "sub_2" / "task.json",
        {
            "task_id": "sub_2",
            "role": "review",
            "authority": "advisory",
            "operation": "claim_review",
            "scope": {"node_refs": [node_id], "claim_refs": [refs["concerted"]]},
        },
    )
    _write(
        root / "reviews" / refs["concerted"] / "runs" / "sub_2" / "run.json",
        {
            "task_id": "sub_2",
            "status": "completed",
            "started_at": "2026-08-16T00:02:00+00:00",
            "finished_at": "2026-08-16T00:03:00+00:00",
            "error": None,
        },
    )
    _write(
        root / "reviews" / refs["concerted"] / "runs" / "sub_2" / "result.json",
        {"outcome": "success", "summary": "Connectivity remains untested."},
    )
    return refs


def test_normalize_workspace_projects_phase_node_and_operational_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    view = normalize_workspace(workspace)

    assert view["schema_version"] == "ts-web-workspace/6"
    assert view["workspace"]["kernel_protocol"] == "ts-research-kernel/6"
    assert view["research_phases"][0]["phase_id"] == refs["mechanism"]
    assert view["research_phases"][0]["node_refs"] == [refs["search"], refs["connectivity"]]
    assert view["focus"]["phase_refs"] == [refs["mechanism"]]
    assert view["focus"]["claim_refs"] == [refs["concerted"]]
    assert view["focus"]["node_refs"] == [refs["connectivity"]]
    active = next(row for row in view["research_nodes"] if row["node_id"] == refs["connectivity"])
    completed = next(row for row in view["research_nodes"] if row["node_id"] == refs["search"])
    assert active["activities"][0]["activity_id"] == "op_1"
    assert "runs" not in active["attempts"][0]
    assert active["attempts"][0]["run_count"] == 1
    assert next(row for row in view["agent_runs"] if row["task_id"] == "sub_1")["intent_id"] == "calc_1"
    assert active["compute_run_count"] == 1
    assert "endpoint identity remains unresolved" in active["opening_decision"]["rationale"]
    assert completed["dependent_refs"] == [refs["connectivity"]]
    assert completed["completion_decision"]["decision_id"] == completed["result"]["decision_id"]
    assert "research_trajectory" not in view
    assert all(row["phase_ref"] == refs["mechanism"] for row in view["research_nodes"])


def test_workspace_snapshot_is_small_when_unchanged_and_coherent_when_changed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    row = {
        "workspace_id": "ws_test",
        "source_root": str(workspace),
        "label": "test workspace",
    }

    initial = workspace_snapshot(row)
    assert initial["changed"] is True
    assert initial["scientific_changed"] is True
    assert initial["operational_changed"] is True
    assert initial["view"]["workspace_revision"] == initial["workspace_revision"]
    assert initial["view"]["operational_revision"] == initial["operational_revision"]
    assert initial["graph"]["workspace_revision"] == initial["workspace_revision"]
    assert initial["graph"]["operational_revision"] == initial["operational_revision"]

    unchanged = workspace_snapshot(
        row,
        since_workspace_revision=initial["workspace_revision"],
        since_operational_revision=initial["operational_revision"],
    )
    assert unchanged == {
        "schema_version": "ts-explorer-workspace-snapshot/1",
        "workspace_id": "ws_test",
        "changed": False,
        "scientific_changed": False,
        "operational_changed": False,
        "workspace_revision": initial["workspace_revision"],
        "operational_revision": initial["operational_revision"],
    }

    status_path = workspace / "nodes" / refs["connectivity"] / "attempts" / "calc_1" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["program_status"] = "error_termination"
    _write(status_path, status)
    changed = workspace_snapshot(
        row,
        since_workspace_revision=initial["workspace_revision"],
        since_operational_revision=initial["operational_revision"],
    )
    assert changed["changed"] is True
    assert changed["scientific_changed"] is False
    assert changed["operational_changed"] is True
    assert changed["workspace_revision"] == initial["workspace_revision"]
    assert changed["operational_revision"] != initial["operational_revision"]
    active = next(
        row
        for row in changed["view"]["research_nodes"]
        if row["node_id"] == refs["connectivity"]
    )
    assert active["attempts"][0]["program_status"] == "error_termination"


def test_workspace_snapshot_normalizes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    _make_workspace(workspace)
    row = {"workspace_id": "ws_test", "source_root": str(workspace), "label": "test"}
    calls = 0
    from ts_agent.projection import normalize as projection

    original = projection.normalize_workspace

    def counted(source_root, *, label=None):
        nonlocal calls
        calls += 1
        return original(source_root, label=label)

    monkeypatch.setattr(projection, "normalize_workspace", counted)
    workspace_snapshot(row)
    assert calls == 1


def test_web_control_projection_distinguishes_submit_and_cancel_for_one_attempt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    attempt = workspace / "nodes" / node_id / "attempts" / "calc_1"
    for operation, error_class in (
        ("submit", "submission_ambiguous"),
        ("cancel", "cancellation_ambiguous"),
    ):
        _write(attempt / f"{operation}_guard.json", {"operation": operation})
        _write(
            attempt / f"{operation}_result.json",
            {
                "state": "unknown",
                "error_class": error_class,
                "job_id": None,
                "control": {"effect_outcome": "unknown", "retry_disposition": "reconcile_only"},
            },
        )

    view = normalize_workspace(workspace)
    detail = node_payload(workspace, node_id)

    expected = {"calc_1:submit:1", "calc_1:cancel:1"}
    assert {row["control_id"] for row in view["unresolved_controls"]} == expected
    assert {row["control_id"] for row in detail["research_node"]["unresolved_controls"]} == expected


def test_web_projects_safe_pre_submit_retry_separately_from_reconciliation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    attempt = workspace / "nodes" / node_id / "attempts" / "calc_2"
    _write(attempt / "intent.json", {
        "intent_id": "calc_2",
        "node_id": node_id,
        "backend": "crest",
        "task_type": "conformer_search",
    })
    _write(attempt / "submit_guard.json", {"operation": "submit"})
    _write(attempt / "submit_result.json", {
        "state": "failed",
        "error_class": "remote_staging_failed",
        "job_id": None,
        "control": {
            "effect_outcome": "failed",
            "effect_attempted": False,
            "retry_disposition": "retry_same_submission",
            "reconciliation_required": False,
        },
    })

    view = normalize_workspace(workspace)
    detail = node_payload(workspace, node_id)
    graph = graph_payload_from_view(view)

    assert view["unresolved_controls"] == []
    assert view["retryable_controls"][0]["control_id"] == "calc_2:submit:1"
    assert detail["research_node"]["unresolved_controls"] == []
    assert detail["research_node"]["retryable_controls"][0]["error_class"] == "remote_staging_failed"
    assert graph["unresolved_controls"] == []
    assert graph["retryable_controls"][0]["retry_disposition"] == "retry_same_submission"


def test_web_ignores_noncanonical_attempt_ids_and_sorts_current_ordinals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    for intent_id in ("calc_10", "calc_2", "calc_removed"):
        _write(
            workspace / "nodes" / node_id / "attempts" / intent_id / "intent.json",
            {"intent_id": intent_id, "node_id": node_id, "backend": "gaussian", "task_type": "sp"},
        )
    unsupported_activity = "op_019a338f-acaf-43e6-b498-4e3994971399"
    unsupported_run = "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b"
    _write(workspace / "nodes" / node_id / "activities" / unsupported_activity / "request.json", {})
    _write(workspace / "nodes" / node_id / "agent-runs" / "sub_old" / "task.json", {})
    _write(workspace / "nodes" / node_id / "attempts" / "calc_1" / "runs" / unsupported_run / "task.json", {})

    view = normalize_workspace(workspace)
    detail = node_payload(workspace, node_id)

    active = next(row for row in view["research_nodes"] if row["node_id"] == node_id)
    assert [row["intent_id"] for row in active["attempts"]] == ["calc_1", "calc_2", "calc_10"]
    paths = {row["path"] for row in detail["files"]["files"]}
    assert f"nodes/{node_id}/attempts/calc_1/runs/sub_1/task.json" in paths
    assert not any(unsupported_activity in path or unsupported_run in path or "/agent-runs/" in path for path in paths)
    assert not any("/attempts/calc_removed/" in path for path in paths)


def test_web_projects_current_attempt_family_and_lineage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    primary_intent = json.loads(
        (
            workspace
            / "nodes"
            / node_id
            / "attempts"
            / "calc_1"
            / "intent.json"
        ).read_text(encoding="utf-8")
    )
    primary_intent.update(
        {
            "intent_id": "calc_2",
            "purpose": "Repeat the IRC with a smaller integration step after calc_1 stalled.",
            "attempt_kind": "recalculation",
            "lineage": {
                "source_node": node_id,
                "source_intent_id": "calc_1",
                "relation": "recalculation",
                "reason": "Resolve an integration-step sensitivity.",
                "changed_fields": ["parameters.stepSize"],
            },
            "scientific_intent_digest": "sha256:" + "e" * 64,
            "parameters": {
                "method": "M062X",
                "basis": "6-31+G(d,p)",
                "candidateStrategy": "bidirectional_irc",
                "stepSize": 5,
            },
            "expected_artifacts": [
                f"nodes/{node_id}/attempts/calc_2/outputs/gaussian.out"
            ],
        }
    )
    _write(
        workspace / "nodes" / node_id / "attempts" / "calc_2" / "intent.json",
        primary_intent,
    )

    attempts = node_payload(workspace, node_id)["research_node"]["attempts"]
    recalculation = next(row for row in attempts if row["intent_id"] == "calc_2")

    assert recalculation["purpose"].startswith("Repeat the IRC")
    assert recalculation["attempt_kind"] == "recalculation"
    assert recalculation["lineage"] == {
        "source_node": node_id,
        "source_intent_id": "calc_1",
        "relation": "recalculation",
        "reason": "Resolve an integration-step sensitivity.",
        "changed_fields": ["parameters.stepSize"],
    }
    assert recalculation["family_root_id"] == "calc_1"
    assert recalculation["family_index"] == 1
    assert recalculation["lineage_depth"] == 1
    assert recalculation["parameters"]["candidateStrategy"] == "bidirectional_irc"


def test_web_marks_retired_or_incomplete_intents_without_aliasing_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    attempts_root = workspace / "nodes" / node_id / "attempts"

    _write(
        attempts_root / "calc_3" / "intent.json",
        {
            "schema_version": "ts-calculation-intent/6",
            "intent_id": "calc_3",
            "node_id": node_id,
            "backend": "gaussian",
            "task_type": "irc",
            "settings": {"method": "retired-method"},
            "recalculation_ref": {
                "source_node": node_id,
                "source_intent_id": "calc_1",
                "purpose": "retired lineage",
                "changed_settings": ["settings.stepSize"],
            },
        },
    )
    _write(
        attempts_root / "calc_3" / "status.json",
        {"state": "completed", "program_status": "normal_termination"},
    )

    incomplete = json.loads(
        (
            attempts_root / "calc_1" / "intent.json"
        ).read_text(encoding="utf-8")
    )
    incomplete.pop("parameters")
    _write(attempts_root / "calc_4" / "intent.json", incomplete)

    attempts = node_payload(workspace, node_id)["research_node"]["attempts"]
    retired = next(row for row in attempts if row["intent_id"] == "calc_3")
    malformed = next(row for row in attempts if row["intent_id"] == "calc_4")

    assert retired["intent_status"] == "unsupported"
    assert retired["display_state"] == "unsupported"
    assert retired["parameters"] == {}
    assert retired["lineage"] is None
    assert "ts-calculation-intent/7" in retired["intent_error"]
    assert malformed["intent_status"] == "invalid"
    assert malformed["display_state"] == "invalid"
    assert malformed["parameters"] == {}
    assert "parameters" in malformed["intent_error"]


def test_web_attempt_projection_reuses_fail_closed_index_for_symlinked_outputs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    attempt = workspace / "nodes" / node_id / "attempts" / "calc_1"
    outside = tmp_path / "outside-outputs"
    intent = json.loads((attempt / "intent.json").read_text(encoding="utf-8"))
    _write(
        outside / "calculation_result.json",
        calculation_result_fixture(
            intent,
            state="parsed",
            program_status="completed",
            job_id="outside.job",
        ),
    )
    (attempt / "outputs").symlink_to(outside, target_is_directory=True)

    projected = next(
        row
        for row in node_payload(workspace, node_id)["research_node"]["attempts"]
        if row["intent_id"] == "calc_1"
    )

    assert projected["integrity_error"] == "symbolic link is not allowed"
    assert projected["display_state"] == "invalid"
    assert projected["job_id"] == "123.cluster"
    assert projected.get("observation_candidates") is None


def test_web_attempt_projection_does_not_traverse_symlinked_attempt_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    attempts = workspace / "nodes" / node_id / "attempts"
    outside = tmp_path / "outside-attempts"
    intent = json.loads(
        (attempts / "calc_1" / "intent.json").read_text(encoding="utf-8")
    )
    _write(outside / "calc_2" / "intent.json", {**intent, "intent_id": "calc_2"})
    attempts.rename(workspace / "nodes" / node_id / "attempts-real")
    attempts.symlink_to(outside, target_is_directory=True)

    payload = node_payload(workspace, node_id)
    projected = [
        row
        for row in payload["research_node"]["attempts"]
        if row["intent_id"] == "calc_2"
    ]

    # A symlinked parent is never enumerated, so an outside calc directory
    # cannot be mistaken for a workspace Attempt.  The parent-level finding is
    # still visible in the Node detail projection.
    assert projected == []
    assert payload["calculation_attempt_integrity_findings"] == [{
        "code": "calculation_attempt_integrity",
        "scope": "attempt_parent",
        "path": f"nodes/{node_id}/attempts",
        "node_refs": [node_id],
        "message": "Attempt parent path contains a symbolic-link component",
    }]
    assert payload["research_node"]["attempt_integrity_findings"] == payload[
        "calculation_attempt_integrity_findings"
    ]


def test_node_files_publish_the_same_bounded_text_preview_capability(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    output = workspace / "nodes" / refs["connectivity"] / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    text_file = output / "readable.txt"
    binary_file = output / "image.png"
    large_file = output / "large.out"
    boundary_file = output / "utf8-boundary.txt"
    text_file.write_text("readable\n", encoding="utf-8")
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    large_file.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    boundary_file.write_text("a" * 8191 + "é" + "tail", encoding="utf-8")

    rows = {row["name"]: row for row in list_node_files(workspace, refs["connectivity"])["files"]}

    assert rows["readable.txt"]["preview"] == {"available": True, "reason": None}
    assert rows["image.png"]["preview"]["available"] is False
    assert "binary" in rows["image.png"]["preview"]["reason"].lower()
    assert rows["large.out"]["preview"]["available"] is False
    assert "1 MB" in rows["large.out"]["preview"]["reason"]
    assert rows["utf8-boundary.txt"]["preview"]["available"] is True
    assert preview_capability(text_file)["available"] is True
    assert read_text_preview(text_file) == "readable\n"
    with pytest.raises(ValueError, match="binary"):
        read_text_preview(binary_file)
    with pytest.raises(ValueError, match="1 MB"):
        read_text_preview(large_file)


def test_graph_uses_claim_relations_and_research_node_dependencies(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    graph = graph_payload_from_view(normalize_workspace(workspace))

    assert graph["schema_version"] == "ts-explorer-graph/6"
    assert graph["claim_graph"]["edges"] == [
        {
            "id": refs["alternatives"],
            "source": refs["concerted"],
            "target": refs["stepwise"],
            "kind": "alternative_to",
            "rationale": "The Claims are competing explanations.",
        }
    ]
    assert graph["research_node_dag"]["edges"] == [
        {
            "id": f"dependency:{refs['search']}:{refs['connectivity']}",
            "source": refs["search"],
            "target": refs["connectivity"],
            "kind": "depends_on",
        }
    ]
    assert "research_trajectory" not in graph
    assert graph["deterministic_activities"][0]["kind"] == "render"
    assert {row["role"] for row in graph["agent_runs"]} == {"compute", "review"}


def test_research_map_separates_shared_work_hypotheses_and_connectivity() -> None:
    phases = [{"phase_id": "phase_1", "title": "Mechanism", "objective": "Compare pathways."}]
    claims = [
        {"claim_id": "claim_1", "claim_type": "mechanism", "statement": "Concerted.", "status": "proposed"},
        {"claim_id": "claim_2", "claim_type": "mechanism", "statement": "Stepwise.", "status": "supported"},
    ]
    nodes = [
        {
            "node_id": "node_1", "phase_ref": "phase_1", "title": "Endpoints", "objective": "Prepare shared endpoints.",
            "status": "completed", "dependency_refs": [], "primary_claim_ref": "claim_1", "claim_refs": ["claim_1", "claim_2"],
            "observation_refs": ["obs_7"], "attempts": [],
        },
        {
            "node_id": "node_2", "phase_ref": "phase_1", "title": "Concerted TS", "objective": "Test one step.",
            "status": "open", "dependency_refs": ["node_1"], "primary_claim_ref": "claim_1", "claim_refs": ["claim_1"],
            "observation_refs": ["obs_3", "obs_4"], "attempts": [{"intent_id": "calc_1", "backend": "gaussian", "task_type": "irc", "display_state": "completed", "program_status": "normal_termination"}],
        },
        {
            "node_id": "node_3", "phase_ref": "phase_1", "title": "Stepwise TS", "objective": "Test two steps.",
            "status": "open", "dependency_refs": ["node_1"], "primary_claim_ref": "claim_2", "claim_refs": ["claim_2"],
            "observation_refs": ["obs_1", "obs_2"], "attempts": [],
        },
    ]
    observations = [
        {"observation_id": "obs_1", "concept_id": "reaction_path.endpoint_assignment", "created_by_node": "node_3", "subject_ref": "closure TS", "value": {"forward": "product", "reverse": "intermediate"}, "qualifiers": {}, "summary": "Connectivity."},
        {"observation_id": "obs_2", "concept_id": "reaction_path.endpoint_assignment", "created_by_node": "node_3", "subject_ref": "closure TS", "value": {"forward": "product", "reverse": "intermediate"}, "qualifiers": {}, "summary": "Duplicate connectivity."},
        {"observation_id": "obs_3", "concept_id": "reaction_path.endpoint_assignment", "created_by_node": "node_2", "subject_ref": "concerted TS", "value": "reactants", "qualifiers": {"direction": "reverse"}, "summary": "Reverse endpoint."},
        {"observation_id": "obs_4", "concept_id": "reaction_path.endpoint_assignment", "created_by_node": "node_2", "subject_ref": "concerted TS", "value": "product", "qualifiers": {"direction": "forward"}, "summary": "Forward endpoint."},
    ]
    relations = [{
        "relation_id": "rel_1", "source_claim_ref": "claim_1", "target_claim_ref": "claim_2",
        "relation_type": "competing_alternative", "rationale": "Competing mechanisms.",
    }]

    result = project_research_map(phases, nodes, claims, relations, observations)

    assert result["schema_version"] == "ts-research-map/1"
    phase = result["phases"][0]
    assert phase["shared_node_refs"] == ["node_1"]
    assert phase["claim_relations"][0]["relation_type"] == "competing_alternative"
    lanes = {row["claim_ref"]: row for row in phase["lanes"]}
    assert lanes["claim_1"]["node_refs"] == ["node_2"]
    assert lanes["claim_2"]["node_refs"] == ["node_3"]
    assert set((lanes["claim_1"]["connectivity_segments"][0]["endpoint_a"], lanes["claim_1"]["connectivity_segments"][0]["endpoint_b"])) == {"reactants", "product"}
    stepwise = lanes["claim_2"]["connectivity_segments"]
    assert len(stepwise) == 1
    assert stepwise[0]["observation_refs"] == ["obs_1", "obs_2"]
    assert stepwise[0]["direction"] == "undirected"
    node = next(row for row in result["nodes"] if row["node_ref"] == "node_2")
    assert node["latest_calculation"]["intent_id"] == "calc_1"
    assert node["upstream_dependencies"][0]["observation_count"] == 1


def test_research_map_uses_only_explicit_connectivity_direction() -> None:
    result = project_research_map(
        [{"phase_id": "phase_1", "title": "Path", "objective": "Trace endpoints."}],
        [{
            "node_id": "node_1",
            "phase_ref": "phase_1",
            "title": "IRC",
            "objective": "Trace both directions.",
            "status": "completed",
            "dependency_refs": [],
            "primary_claim_ref": "claim_1",
            "claim_refs": ["claim_1"],
            "observation_refs": ["obs_1"],
            "attempts": [],
        }],
        [{
            "claim_id": "claim_1",
            "claim_type": "mechanism",
            "statement": "One pathway.",
            "status": "supported",
        }],
        [],
        [{
            "observation_id": "obs_1",
            "concept_id": "reaction_path.endpoint_assignment",
            "created_by_node": "node_1",
            "subject_ref": "TS",
            "value": {"forward": "product", "reverse": "reactants"},
            "qualifiers": {"connectivity_direction": "reverse_to_forward"},
            "summary": "Directed connectivity.",
        }],
    )

    segment = result["connectivity_segments"][0]
    assert segment["endpoint_a"] == "reactants"
    assert segment["endpoint_b"] == "product"
    assert segment["direction"] == "reverse_to_forward"


def test_claim_and_node_details_follow_graph_references(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    summary = normalize_workspace(workspace)
    claim = claim_payload(workspace, refs["concerted"])
    active = node_payload(workspace, refs["connectivity"])
    completed = node_payload(workspace, refs["search"])

    assert {row["node_id"] for row in claim["research_nodes"]} == {refs["search"], refs["connectivity"]}
    assert claim["validation_results"][0]["verdict"] == "pass"
    assert active["dependencies"][0]["node_id"] == refs["search"]
    assert active["research_node"]["activities"][0]["activity_id"] == "op_1"
    assert claim["review_runs"][0]["task_id"] == "sub_2"
    summary_node = next(
        row for row in summary["research_nodes"] if row["node_id"] == refs["connectivity"]
    )
    assert "settings" not in summary_node["attempts"][0]
    assert "runs" not in summary_node["attempts"][0]
    attempt = active["research_node"]["attempts"][0]
    assert attempt["intent_id"] == "calc_1"
    assert attempt["node_id"] == refs["connectivity"]
    assert attempt["lineage"] is None
    assert attempt["family_root_id"] == "calc_1"
    assert attempt["family_index"] == 1
    assert attempt["lineage_depth"] == 0
    assert attempt["display_state"] == "completed"
    assert attempt["job_id"] == "123.cluster"
    assert attempt["duration_seconds"] == 90
    assert attempt["run_count"] == 1
    assert attempt["parameters"]["candidateStrategy"] == "bidirectional_irc"
    assert attempt["execution_target"]["profile"] == "cluster_1w"
    assert attempt["runs"][0]["task_id"] == "sub_1"
    assert completed["dependents"][0]["node_id"] == refs["connectivity"]
    assert completed["phase"]["phase_id"] == refs["mechanism"]
    assert completed["history"][0]["decision_id"] == completed["research_node"]["created_by_decision"]
    assert {row["claim_id"] for row in completed["claims"]} == {refs["concerted"], refs["stepwise"]}
    assert completed["proof_specs"][0]["title"] == "Program completion probe"
    assert f"nodes/{refs['connectivity']}/outputs/probe.json" in {
        row["path"] for row in active["files"]["files"]
    }


def test_web_derives_claim_node_link_from_creator_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    node_draft = compile_change(
        workspace,
        {
            "rationale": "Start an exploratory Node before it discovers a Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "create_phase", "local_ref": "exploration_phase", "title": "Exploration", "objective": "Look for an alternative mechanism."},
                {"op": "start_node", "local_ref": "exploration", "phaseRef": "$exploration_phase", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Look for an alternative mechanism."}
            ],
        },
    )
    apply_compiled_change(workspace, node_draft["decision"])
    node_id = node_draft["allocated_refs"]["exploration"]
    claim_draft = compile_change(
        workspace,
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
    apply_compiled_change(workspace, claim_draft["decision"])
    claim_id = claim_draft["allocated_refs"]["alternative"]

    view = normalize_workspace(workspace)
    node = next(row for row in view["research_nodes"] if row["node_id"] == node_id)
    graph = graph_payload_from_view(view)
    assert node["claim_refs"] == []
    assert node["related_claim_refs"] == [claim_id]
    assert graph["claim_node_links"] == [{"claim_ref": claim_id, "node_ref": node_id}]
    assert [row["node_id"] for row in claim_payload(workspace, claim_id)["research_nodes"]] == [node_id]
    assert [row["claim_id"] for row in node_payload(workspace, node_id)["claims"]] == [claim_id]


def test_static_ui_exposes_research_map_dependency_dag_and_node_details() -> None:
    static = ROOT / "components" / "ts-web" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    claim_map = (static / "claim-map.js").read_text(encoding="utf-8")
    tree = (static / "research-tree.js").read_text(encoding="utf-8")
    research_map = (static / "research-map.js").read_text(encoding="utf-8")
    attempt_timeline = (static / "attempt-timeline.js").read_text(encoding="utf-8")
    css = (static / "app.css").read_text(encoding="utf-8")

    assert "TS Research Explorer" in html
    assert "Research Map" in html
    assert "Scientific Conclusions" in html
    assert "Research Files" in html
    assert "Advanced Graphs" not in html + script
    assert "app.css" in html
    assert "i18n.js" in html
    assert "/logo.svg" in html
    assert "/favicon.svg" in html
    assert "app.js" in html
    assert "claim-map.js" in html
    assert "research-tree.js" in html
    assert "research-map.js" in html
    assert "attempt-timeline.js" in html
    assert "renderNodeDetail" in script
    assert "window.TSResearchTree.mount" in script
    assert "window.TSResearchMap.mount" in script
    assert "window.TSClaimMap.mount" in script
    assert "state.graph.research_node_dag.edges" in script
    assert 'data-conclusions-mode="table"' in script
    assert 'data-conclusions-mode="map"' in script
    assert 'data-roadmap-mode="map"' in script
    assert 'data-roadmap-mode="dag"' in script
    assert 'onSelectRelation: relationId => openDetail("relation", relationId)' in script
    assert "renderPhaseBand" not in script
    assert "Cross-Phase ResearchNode DAG" not in script
    assert "computeLayout" in tree
    assert "computeLineage" in tree
    assert 'root.classList.add("research-tree")' in tree
    assert "research-tree-outline" in tree
    assert "ResizeObserver" in tree
    assert 'global.TSResearchMap = { mount }' in research_map
    assert "Connectivity evidence" in research_map
    assert "Shared foundation" in research_map
    assert "computeLayout" in claim_map
    assert "computeLineage" in claim_map
    assert "filterNodes" in claim_map
    assert 'root.classList.add("claim-map")' in claim_map
    assert "claim-map-outline" in claim_map
    assert "claim-map-arrow" in claim_map
    assert 'const tabs = ["overview", "conclusions", "evidence", "runs", "files", "history"]' in script
    assert "renderAttemptOverview(node)" in script
    assert "renderAttemptTimeline(node.attempts)" in script
    assert "TSAttemptTimeline.project" in script
    assert "pageForAttempt" in attempt_timeline
    assert 'details[data-attempt-id]' in script
    assert 'data-attempt-node="${escapeHtml(sourceNode)}"' in script
    assert "async function openAttemptSource(sourceNodeId, attemptId)" in script
    assert 'const opened = await openDetail("node", sourceNodeId)' in script
    assert 'preview?.available' in script
    assert 'icon("eye")' in script
    assert 'icon("external")' not in script
    assert 'id="icon-eye"' in html
    assert ".attempt-filter { grid-column: 2; }" in css
    assert "${latest.intent_id} ${trStatus(attemptState(latest))}" in tree
    assert "...array(state.view.retryable_controls)" in script
    assert "intentIds[0]" in script
    assert "Fix remote configuration, then retry" in script
    assert "function renderActDetail" not in script
    assert "/api/node" not in html + script
    assert "/api/gates" not in html + script
    assert "/api/evidence" not in html + script


def test_static_i18n_catalogs_match_and_cover_literal_ui_references() -> None:
    static = ROOT / "components" / "ts-web" / "static"
    catalog = (static / "i18n.js").read_text(encoding="utf-8")
    english, chinese = catalog.split("    zh: {", maxsplit=1)
    key_pattern = re.compile(r'^      "([^"]+)":', re.MULTILINE)
    english_keys = set(key_pattern.findall(english))
    chinese_keys = set(key_pattern.findall(chinese))

    sources = "\n".join(path.read_text(encoding="utf-8") for path in static.glob("*.js"))
    sources += "\n" + (static / "index.html").read_text(encoding="utf-8")
    literal_references = set(re.findall(r'\btr\(\s*"([^"]+)"', sources))
    literal_references.update(re.findall(r'data-i18n(?:-aria-label|-title)?="([^"]+)"', sources))

    assert english_keys == chinese_keys
    assert literal_references <= english_keys
    assert len(english_keys) >= 400


def test_attempt_timeline_filters_and_paginates_families() -> None:
    timeline_path = (ROOT / "components" / "ts-web" / "static" / "attempt-timeline.js").as_uri()
    probe = f"""
globalThis.window = globalThis;
(async () => {{
  await import({json.dumps(timeline_path)});
  const attempts = Array.from({{length: 8}}, (_, index) => {{
    const ordinal = index + 1;
    return {{
      intent_id: `calc_${{ordinal}}`,
      family_root_id: ordinal < 8 ? "calc_1" : "calc_8",
      family_index: ordinal < 8 ? 1 : 2,
      attempt_kind: ordinal === 1 || ordinal === 8 ? "primary" : (ordinal % 2 ? "retry" : "recalculation"),
      display_state: ordinal === 6 ? "failed" : "completed",
    }};
  }});
  const first = TSAttemptTimeline.project(attempts, {{page: 1}});
  const second = TSAttemptTimeline.project(attempts, {{page: 2}});
  const retries = TSAttemptTimeline.project(attempts, {{kind: "retry"}});
  process.stdout.write(JSON.stringify({{
    pageCount: first.pageCount,
    first: first.rows.map(row => row.intent_id),
    second: second.rows.map(row => row.intent_id),
    retries: retries.rows.map(row => row.intent_id),
    pageForSeven: TSAttemptTimeline.pageForAttempt(attempts, {{}}, "calc_7"),
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(["node", "-e", probe], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result == {
        "pageCount": 2,
        "first": ["calc_1", "calc_2", "calc_3", "calc_4", "calc_5", "calc_6"],
        "second": ["calc_7", "calc_8"],
        "retries": ["calc_3", "calc_5", "calc_7"],
        "pageForSeven": 2,
    }


def test_research_tree_layout_handles_branch_merge_and_lineage() -> None:
    tree_path = (ROOT / "components" / "ts-web" / "static" / "research-tree.js").as_uri()
    probe = f"""
globalThis.window = globalThis;
(async () => {{
  await import({json.dumps(tree_path)});
  const nodes = [
    {{node_id: "node_1", phase_ref: "phase_1"}},
    {{node_id: "node_2", phase_ref: "phase_1"}},
    {{node_id: "node_3", phase_ref: "phase_1"}},
    {{node_id: "node_4", phase_ref: "phase_2"}},
  ];
  const edges = [
    {{source: "node_1", target: "node_2"}},
    {{source: "node_1", target: "node_3"}},
    {{source: "node_2", target: "node_4"}},
    {{source: "node_3", target: "node_4"}},
  ];
  const layout = TSResearchTree.computeLayout(nodes, edges, new Map([["phase_1", 0], ["phase_2", 1]]));
  const lineage = TSResearchTree.computeLineage(nodes, edges, "node_2");
  process.stdout.write(JSON.stringify({{
    depths: Object.fromEntries(Object.entries(layout.positions).map(([id, row]) => [id, row.depth])),
    branchRowsDiffer: layout.positions.node_2.y !== layout.positions.node_3.y,
    ancestors: [...lineage.ancestors].sort(),
    descendants: [...lineage.descendants].sort(),
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["depths"] == {"node_1": 0, "node_2": 1, "node_3": 1, "node_4": 2}
    assert result["branchRowsDiffer"] is True
    assert result["ancestors"] == ["node_1"]
    assert result["descendants"] == ["node_4"]


def test_claim_map_layout_filters_and_lineage() -> None:
    map_path = (ROOT / "components" / "ts-web" / "static" / "claim-map.js").as_uri()
    probe = f"""
globalThis.window = globalThis;
(async () => {{
  await import({json.dumps(map_path)});
  const nodes = [
    {{claim_id: "claim_1", status: "proposed", claim_type: "mechanism", acceptance_state: "none"}},
    {{claim_id: "claim_2", status: "supported", claim_type: "mechanism", acceptance_state: "current"}},
    {{claim_id: "claim_3", status: "proposed", claim_type: "alternative", acceptance_state: "none"}},
    {{claim_id: "claim_4", status: "supported", claim_type: "connectivity", acceptance_state: "current"}},
  ];
  const edges = [
    {{id: "rel_1", source: "claim_1", target: "claim_2"}},
    {{id: "rel_2", source: "claim_1", target: "claim_3"}},
    {{id: "rel_3", source: "claim_2", target: "claim_4"}},
    {{id: "rel_4", source: "claim_3", target: "claim_4"}},
    {{id: "rel_5", source: "claim_1", target: "claim_4"}},
  ];
  const layout = TSClaimMap.computeLayout(nodes, edges);
  const lineage = TSClaimMap.computeLineage(nodes, edges, "claim_2");
  const filtered = TSClaimMap.filterNodes(nodes, {{status: "supported", acceptance: "current"}});
  const route = TSClaimMap.computeEdgeRoute(layout.positions.claim_1, layout.positions.claim_4, 0);
  const relationLabel = TSClaimMap.wrapRelationLabel("candidate_step_for_pathway", 12);
  process.stdout.write(JSON.stringify({{
    depths: Object.fromEntries(Object.entries(layout.positions).map(([id, row]) => [id, row.depth])),
    branchRowsDiffer: layout.positions.claim_2.y !== layout.positions.claim_3.y,
    ancestors: [...lineage.ancestors].sort(),
    descendants: [...lineage.descendants].sort(),
    filtered: filtered.map(row => row.claim_id),
    sourceY: layout.positions.claim_1.y,
    route,
    relationLabel,
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["depths"] == {"claim_1": 0, "claim_2": 1, "claim_3": 1, "claim_4": 2}
    assert result["branchRowsDiffer"] is True
    assert result["ancestors"] == ["claim_1"]
    assert result["descendants"] == ["claim_4"]
    assert result["filtered"] == ["claim_2", "claim_4"]
    assert result["route"]["long"] is True
    assert result["route"]["labelY"] < result["sourceY"]
    assert " L " in result["route"]["pathData"]
    assert "".join(result["relationLabel"]) == "candidate_step_for_pathway"


def test_static_ui_refreshes_registry_and_persists_theme() -> None:
    static = ROOT / "components" / "ts-web" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    css = (static / "app.css").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")

    assert ':root[data-theme="dark"]' in css
    assert "body.inspector-open { overflow: hidden; }" in css
    assert 'id="theme-button"' in html
    assert 'const themeStorageKey = "ts-explorer-theme"' in script
    assert 'themeButton.addEventListener("click", toggleTheme)' in script
    assert "async function loadWorkspaceCatalog()" in script
    assert 'const payload = await api("/api/workspaces")' in script
    assert 'refreshButton.addEventListener("click", refreshExplorer)' in script
    assert 'tr("action.refreshing", "Refreshing workspace")' in script
    assert 'showToast(tr("action.refreshed", "Workspace refreshed"))' in script
    assert "const liveRefreshIntervalMs = 5000" in script
    assert "async function pollLiveRefresh()" in script
    assert 'document.addEventListener("visibilitychange"' in script
    assert 'setHealth("stale", tr("health.stale", "Stale"))' in script
    assert "/snapshot?${query}" in script
    assert "renderUnavailableWorkspace(catalogRow)" in script
    assert 'tr("workspace.incompatibleSuffix", "incompatible")' in script
    assert 'textContent = view.workspace.kernel_protocol || tr("workspace.fallback", "Research workspace")' in script
    assert "escapeHtml(view.workspace.workspace_id)" not in script
    assert "shortDigest(view.workspace_revision)" not in script


def test_research_files_payload_is_a_read_only_locator_projection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    before = _relative_files(workspace)

    result = research_files_payload(workspace, refs["connectivity"])

    assert result["schema_version"] == "ts-workspace-locator/1"
    assert result["query_mode"] == "exact"
    assert result["matches"][0]["kind"] == "node"
    assert result["matches"][0]["directories"][0]["path"] == f"nodes/{refs['connectivity']}"
    assert _relative_files(workspace) == before


def test_static_asset_resolves_from_current_package() -> None:
    for name in ("index.html", "app.css", "app.js", "i18n.js", "logo.svg", "favicon.svg", "attempt-timeline.js", "claim-map.js", "research-map.js", "research-tree.js"):
        expected = (ROOT / "components" / "ts-web" / "static" / name).read_bytes()
        assert (ts_web_server.STATIC_ROOT / name).read_bytes() == expected


def test_web_distinguishes_current_from_historical_acceptance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    refs = accept_research_claim(workspace)

    current = normalize_workspace(workspace)
    assert current["current_acceptances"][0]["acceptance_id"] == refs["acceptance"]
    assert graph_payload_from_view(current)["claim_graph"]["nodes"][0]["acceptance_state"] == "current"

    drafted = compile_change(
        workspace,
        {
            "rationale": "Add a later limitation that requires reassessment.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "record_finding",
                    "local_ref": "limitation",
                    "findingType": "later_limitation",
                    "severity": "warning",
                    "statement": "The earlier assessment does not include this limitation.",
                    "claimRefs": [refs["claim"]],
                    "nodeRefs": [refs["node"]],
                }
            ],
        },
    )
    apply_compiled_change(workspace, drafted["decision"])

    historical = normalize_workspace(workspace)
    assert historical["valid"] is True
    assert historical["current_acceptances"] == []
    assert historical["acceptances"][0]["current"] is False
    claim = graph_payload_from_view(historical)["claim_graph"]["nodes"][0]
    assert claim["accepted"] is False
    assert claim["acceptance_state"] == "historical"


def test_register_workspace_deduplicates_and_rejects_source_pollution(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    _make_workspace(source)
    state = tmp_path / "web-state"
    first = register_workspace(source, state, "single")
    second = register_workspace(source, state, "single updated")

    assert first["workspace_id"] == second["workspace_id"]
    assert [row["label"] for row in list_workspaces(state)] == ["single updated"]
    with pytest.raises(ValueError, match="state_dir"):
        register_workspace(source, source / ".web")


def test_register_workspaces_validates_all_sources_before_writing(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_workspace(first)
    _make_workspace(second)
    state = second / ".web-state"

    with pytest.raises(ValueError, match="state_dir"):
        register_workspaces([first, second], state, ["A", "B"])
    assert not state.exists()


def test_workspace_discovery_roots_use_installation_layout_or_explicit_roots(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    state = installation / ".pi" / "ts-web"
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert workspace_discovery_roots(state) == [installation / "workspaces"]
    assert workspace_discovery_roots(tmp_path / "custom-state") == []
    assert workspace_discovery_roots(state, [first, first, second]) == [first, second]


def test_reconcile_workspace_registry_discovers_supported_and_prunes_only_stale_managed_rows(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    managed = installation / "workspaces"
    current = managed / "ts_001"
    init_workspace(current)
    stale = managed / "ts_004"
    unsupported = managed / "unsupported"
    unsupported.mkdir()
    _write(unsupported / "workspace.json", {"schema_version": "ts-workspace/unsupported"})
    external = tmp_path / "external"
    init_workspace(external)
    state = installation / ".pi" / "ts-web"
    register_workspaces(
        [stale, unsupported, external],
        state,
        ["stale managed", "registered unsupported", "external label"],
    )

    rows = reconcile_workspace_registry(state, [managed])
    by_source = {row["source_root"]: row for row in rows}

    assert str(stale.resolve()) not in by_source
    assert by_source[str(current.resolve())]["label"] == "ts_001"
    assert by_source[str(unsupported.resolve())]["label"] == "registered unsupported"
    assert by_source[str(external.resolve())]["label"] == "external label"


def test_reconcile_workspace_registry_does_not_prune_an_unreachable_root(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    managed = installation / "workspaces"
    stale = managed / "ts_004"
    state = installation / ".pi" / "ts-web"
    registered = register_workspace(stale, state, "temporarily unavailable")

    rows = reconcile_workspace_registry(state, [managed])

    assert rows == [registered]


def test_web_catalog_reconciles_managed_workspaces_on_start_and_refresh(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    managed = installation / "workspaces"
    first = managed / "ts_001"
    init_workspace(first)
    state = installation / ".pi" / "ts-web"
    register_workspace(managed / "ts_004", state, "stale")
    server = create_server("127.0.0.1", 0, state, provider=_provider_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        initial = _get_json(host, port, "/api/workspaces")
        assert [row["label"] for row in initial["workspaces"]] == ["ts_001"]
        assert initial["workspaces"][0]["available"] is True

        second = managed / "ts_002"
        init_workspace(second)
        refreshed = _get_json(host, port, "/api/workspaces")
        assert [row["label"] for row in refreshed["workspaces"]] == ["ts_001", "ts_002"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_catalog_isolates_incompatible_registered_workspace(tmp_path: Path) -> None:
    incompatible = tmp_path / "unsupported-workspace"
    incompatible.mkdir()
    _write(incompatible / "workspace.json", {"schema_version": "ts-workspace/unsupported"})
    compatible = tmp_path / "supported-workspace"
    _make_workspace(compatible)
    state = tmp_path / "web-state"
    old_row, new_row = register_workspaces(
        [incompatible, compatible],
        state,
        ["old workspace", "current workspace"],
    )
    server = create_server("127.0.0.1", 0, state, provider=_provider_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = _get_json(host, port, "/api/workspaces")
        assert payload["default_workspace"] == new_row["workspace_id"]
        summaries = {row["workspace_id"]: row for row in payload["workspaces"]}
        assert summaries[new_row["workspace_id"]]["available"] is True
        assert summaries[new_row["workspace_id"]]["load_error"] is None
        assert summaries[old_row["workspace_id"]]["available"] is False
        assert summaries[old_row["workspace_id"]]["valid"] is False
        assert "cannot read workspace file" in summaries[old_row["workspace_id"]]["load_error"]
        _assert_public_payload(payload, incompatible)
        assert _get_text(host, port, f"/api/workspace/{old_row['workspace_id']}")[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_response_ignores_client_disconnect(tmp_path: Path) -> None:
    server = create_server("127.0.0.1", 0, tmp_path / "web-state", provider=_provider_for(tmp_path / "web-state"))
    handler = object.__new__(server.RequestHandlerClass)

    def disconnected(*_args: object, **_kwargs: object) -> None:
        raise BrokenPipeError

    handler.send_response = disconnected
    try:
        handler._send_json({"ok": True})
    finally:
        server.server_close()


def test_web_server_is_read_only_and_has_no_removed_routes(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    refs = _make_workspace(source)
    output = source / "nodes" / refs["connectivity"] / "outputs"
    binary_path = output / "image.png"
    large_path = output / "large.out"
    binary_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    large_path.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "workspace")
    server = create_server("127.0.0.1", 0, state, provider=_provider_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        health = _get_json(host, port, "/api/health")
        assert health["ok"] is True
        assert health["protocol"] == "ts-research-kernel/6"
        assert health["read_only"] is True
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["default_workspace"] == row["workspace_id"]
        base = f"/api/workspace/{row['workspace_id']}"
        snapshot = _get_json(host, port, f"{base}/snapshot")
        assert snapshot["schema_version"] == "ts-explorer-workspace-snapshot/1"
        assert snapshot["changed"] is True
        unchanged_query = (
            f"workspace_revision={snapshot['workspace_revision']}"
            f"&operational_revision={snapshot['operational_revision']}"
        )
        unchanged = _get_json(host, port, f"{base}/snapshot?{unchanged_query}")
        assert unchanged["changed"] is False
        assert "view" not in unchanged
        assert "graph" not in unchanged
        assert _get_json(host, port, f"{base}/graph")["schema_version"] == "ts-explorer-graph/6"
        assert _get_json(host, port, f"{base}/phases")["research_phases"][0]["phase_id"] == refs["mechanism"]
        assert _get_json(host, port, f"{base}/claims")["claims"][0]["schema_version"] == "ts-claim/4"
        assert _get_json(host, port, f"{base}/nodes")["research_nodes"][0]["schema_version"] == "ts-research-node/2"
        assert _get_json(host, port, f"{base}/observations")["observations"][0]["schema_version"] == "ts-observation/2"
        assert _get_json(host, port, f"{base}/validation")["validation_results"][0]["verdict"] == "pass"
        assert _get_json(host, port, f"{base}/findings")["findings"][0]["status"] == "open"
        files = _get_json(host, port, f"{base}/files?query={refs['connectivity']}")
        assert files["matches"][0]["ref"] == refs["connectivity"]
        assert _get_json(host, port, f"{base}/files")["query_mode"] == "index"
        agent_runs = _get_json(host, port, f"{base}/activity")["agent_runs"]
        assert {(row["task_id"], row["role"]) for row in agent_runs} == {
            ("sub_1", "compute"),
            ("sub_2", "review"),
        }
        assert _get_json(host, port, f"{base}/claim/{refs['concerted']}")["claim"]["status"] == "supported"
        node = _get_json(host, port, f"{base}/node/{refs['connectivity']}")
        assert node["research_node"]["status"] == "open"
        projected_files = {item["name"]: item for item in node["files"]["files"]}
        assert projected_files["probe.json"]["preview"]["available"] is True
        assert projected_files["image.png"]["preview"]["available"] is False
        assert projected_files["large.out"]["preview"]["available"] is False
        preview = _get_json(host, port, f"{base}/file?path=nodes/{refs['connectivity']}/outputs/probe.json")
        assert preview["text"] == "{}\n"
        binary_status, binary_body = _get_text(
            host,
            port,
            f"{base}/file?path=nodes/{refs['connectivity']}/outputs/image.png",
        )
        assert binary_status == 400
        assert "binary" in binary_body.lower()
        large_status, large_body = _get_text(
            host,
            port,
            f"{base}/file?path=nodes/{refs['connectivity']}/outputs/large.out",
        )
        assert large_status == 400
        assert "1 mb" in large_body.lower()
        assert "source_root" not in binary_body + large_body
        assert str(source) not in binary_body + large_body
        assert _get_text(host, port, f"{base}/file?path=workspace.json")[0] == 400
        html = _get_text(host, port, "/")[1]
        assert "TS Research Explorer" in html
        assert _get_text(host, port, "/app.css")[0] == 200
        assert _get_text(host, port, "/app.js")[0] == 200
        assert _get_text(host, port, "/i18n.js")[0] == 200
        assert _get_text(host, port, "/logo.svg")[0] == 200
        assert _get_text(host, port, "/favicon.svg")[0] == 200
        assert _get_text(host, port, "/attempt-timeline.js")[0] == 200
        assert _get_text(host, port, "/claim-map.js")[0] == 200
        assert _get_text(host, port, "/research-map.js")[0] == 200
        assert _get_text(host, port, "/research-tree.js")[0] == 200
        for removed_route in (f"{base}/tree", f"{base}/gates", f"{base}/evidence", "/api/node/n000"):
            assert _get_text(host, port, removed_route)[0] in {400, 404}
        assert _get_text(host, port, f"{base}/node/n000")[0] == 400
        for route in (
            "/api/workspaces",
            f"{base}/snapshot",
            f"{base}/graph",
            f"{base}/phases",
            f"{base}/claims",
            f"{base}/nodes",
            f"{base}/observations",
            f"{base}/validation",
            f"{base}/findings",
            f"{base}/files",
            f"{base}/activity",
            f"{base}/claim/{refs['concerted']}",
            f"{base}/node/{refs['connectivity']}",
            f"{base}/file?path=nodes/{refs['connectivity']}/outputs/probe.json",
        ):
            _assert_public_payload(_get_json(host, port, route), source)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert _relative_files(source) == before


def test_web_api_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    class StubProvider:
        def request(self, operation, **kwargs):
            return {"operation": operation}

    server = create_server("127.0.0.1", 0, tmp_path / "state", provider=StubProvider(), auth_token="secret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        connection.close()

        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", "/api/health", headers={"Authorization": "Bearer secret"})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["ok"] is True
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_web_file_preview_never_follows_external_symlink_paths(tmp_path: Path) -> None:
    """The HTTP file endpoint must share the same physical boundary as the index."""

    source = tmp_path / "workspace"
    refs = _make_workspace(source)
    output = source / "nodes" / refs["connectivity"] / "outputs"
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("this must stay outside the workspace\n", encoding="utf-8")

    linked_file = output / "linked.txt"
    linked_file.symlink_to(secret)
    linked_dir = output / "linked-dir"
    linked_dir.symlink_to(outside, target_is_directory=True)

    state = tmp_path / "web-state"
    row = register_workspace(source, state, "workspace")
    server = create_server("127.0.0.1", 0, state, provider=_provider_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        base = f"/api/workspace/{row['workspace_id']}/file"
        status, body = _get_text(
            host,
            port,
            f"{base}?path=nodes/{refs['connectivity']}/outputs/linked.txt",
        )
        assert status == 400
        assert "symbolic link" in body.lower()
        assert "this must stay outside" not in body

        status, body = _get_text(
            host,
            port,
            f"{base}?path=nodes/{refs['connectivity']}/outputs/linked-dir/secret.txt",
        )
        assert status == 400
        assert "symbolic link" in body.lower()
        assert "this must stay outside" not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_registry_rejects_symlinked_source_and_state_roots(tmp_path: Path) -> None:
    physical = tmp_path / "workspace"
    _make_workspace(physical)
    source_link = tmp_path / "workspace-link"
    source_link.symlink_to(physical, target_is_directory=True)
    state = tmp_path / "web-state"

    with pytest.raises(ValueError, match="symbolic link"):
        register_workspace(source_link, state)

    real_state = tmp_path / "real-state"
    real_state.mkdir()
    state_link = tmp_path / "state-link"
    state_link.symlink_to(real_state, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        register_workspace(physical, state_link)


def test_web_normalizer_does_not_ingest_symlinked_canonical_documents(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _make_workspace(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    # This is deliberately shaped like a canonical document so a plain
    # ``read_json`` would silently import it into the Web projection.
    (outside / "claims.json").write_text(
        json.dumps({
            "schema_version": "ts-claim-registry/4",
            "claims": [{"claim_id": "claim_external", "statement": "secret"}],
        }),
        encoding="utf-8",
    )
    (workspace / "claims.json").unlink()
    (workspace / "claims.json").symlink_to(outside / "claims.json")

    with pytest.raises(ValueError, match="symbolic link"):
        normalize_workspace(workspace)


def _relative_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def _get_json(host: str, port: int, path: str) -> dict:
    status, body = _get_text(host, port, path)
    assert status == 200, body
    return json.loads(body)


def _get_text(host: str, port: int, path: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        connection.close()
