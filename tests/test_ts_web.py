from __future__ import annotations

import http.client
import json
import threading
from importlib.resources import files
from pathlib import Path

import pytest

from tests.v4_helpers import accept_research_claim
from ts_web import normalize_workspace, register_workspace
from ts_web import server as ts_web_server
from ts_web.normalize import (
    act_payload,
    claim_payload,
    graph_payload_from_view,
    research_files_payload,
)
from ts_web.registry import list_workspaces, register_workspaces
from ts_web.server import create_server
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_workspace(root: Path) -> dict[str, str]:
    init_workspace(root)
    drafted = draft_decision(
        root,
        {
            "rationale": "Create a small Claim graph and ResearchAct DAG for the explorer.",
            "basis_refs": [],
            "operations": [
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
                    "op": "start_act",
                    "local_ref": "search",
                    "title": "Bounded research act",
                    "deliverable": "One bounded research result.",
                    "objective": "Search for observations that distinguish the mechanisms.",
                    "claimRefs": ["$concerted", "$stepwise"],
                    "tags": ["candidate-search"],
                    "hypothesis": {
                        "statement": "A bounded probe can discriminate between the competing mechanisms.",
                        "assumptions": ["The probe is representative of the elementary step."],
                        "predictions": ["One mechanism will remain consistent with the observations."],
                        "falsifiers": ["The probe is compatible with both mechanisms."],
                    },
                },
                {
                    "op": "record_observation",
                    "local_ref": "normal",
                    "actRef": "$search",
                    "conceptId": "program.normal_termination",
                    "subjectRef": "calc_probe",
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The probe terminated normally.",
                    "provenance": {"producer": "test-parser"},
                },
                {
                    "op": "freeze_validation_spec",
                    "local_ref": "spec",
                    "actRef": "$search",
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
                    "op": "evaluate_validation",
                    "local_ref": "result",
                    "actRef": "$search",
                    "specRef": "$spec",
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
                    "actRefs": ["$search"],
                    "basisObservationRefs": ["$normal"],
                },
                {
                    "op": "complete_act",
                    "actRef": "$search",
                    "outcome": "inconclusive",
                    "summary": "The probe completed but did not resolve the mechanism.",
                    "openQuestions": ["Which endpoints are connected?"],
                },
                {
                    "op": "start_act",
                    "local_ref": "connectivity",
                    "title": "Bounded research act",
                    "deliverable": "One bounded research result.",
                    "objective": "Test bidirectional connectivity.",
                    "dependencyRefs": ["$search"],
                    "claimRefs": ["$concerted"],
                    "tags": ["connectivity"],
                },
                {"op": "set_focus", "claimRefs": ["$concerted"], "actRefs": ["$connectivity"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    refs = drafted["allocated_refs"]
    act_id = refs["connectivity"]
    artifact = root / "acts" / act_id / "outputs" / "probe.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    _write(
        root / "acts" / act_id / "attempts" / "calc_1" / "intent.json",
        {
            "intent_id": "calc_1",
            "act_id": act_id,
            "backend": "gaussian",
            "task_type": "irc",
        },
    )
    _write(
        root / "acts" / act_id / "attempts" / "calc_1" / "status.json",
        {
            "intent_id": "calc_1",
            "state": "completed",
            "program_status": "normal_termination",
        },
    )
    _write(
        root / "acts" / act_id / "activities" / "op_1" / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": "op_1",
            "kind": "render",
            "operation": "molecule",
            "act_refs": [act_id],
            "request": {},
            "started_at": "2026-08-16T00:00:00+00:00",
        },
    )
    _write(
        root / "acts" / act_id / "activities" / "op_1" / "status.json",
        {
            "schema_version": "ts-deterministic-activity-status/1",
            "activity_id": "op_1",
            "kind": "render",
            "operation": "molecule",
            "act_refs": [act_id],
            "status": "completed",
            "started_at": "2026-08-16T00:00:00+00:00",
            "completed_at": "2026-08-16T00:01:00+00:00",
            "error": None,
        },
    )
    _write(
        root / "acts" / act_id / "activities" / "op_1" / "result.json",
        {"outcome": "success", "summary": "Molecule rendered."},
    )
    _write(
        root / "acts" / act_id / "attempts" / "calc_1" / "runs" / "sub_1" / "task.json",
        {
            "task_id": "sub_1",
            "role": "compute",
            "authority": "operational",
            "operation": "finalize",
            "scope": {"act_refs": [act_id], "claim_refs": [refs["concerted"]]},
            "inputs": {"act_id": act_id, "intent_id": "calc_1", "backend": "gaussian"},
        },
    )
    _write(
        root / "acts" / act_id / "attempts" / "calc_1" / "runs" / "sub_1" / "run.json",
        {
            "task_id": "sub_1",
            "status": "completed",
            "started_at": "2026-08-16T00:02:00+00:00",
            "finished_at": "2026-08-16T00:03:00+00:00",
            "error": None,
        },
    )
    _write(
        root / "acts" / act_id / "attempts" / "calc_1" / "runs" / "sub_1" / "result.json",
        {"outcome": "success", "summary": "Calculation finalized."},
    )
    _write(
        root / "reviews" / refs["concerted"] / "runs" / "sub_2" / "task.json",
        {
            "task_id": "sub_2",
            "role": "review",
            "authority": "advisory",
            "operation": "claim_review",
            "scope": {"act_refs": [act_id], "claim_refs": [refs["concerted"]]},
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


def test_normalize_workspace_projects_v4_scientific_and_operational_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    view = normalize_workspace(workspace)

    assert view["schema_version"] == "ts-web-workspace/4"
    assert view["workspace"]["kernel_protocol"] == "ts-research-kernel/4"
    assert view["focus"]["claim_refs"] == [refs["concerted"]]
    assert view["focus"]["act_refs"] == [refs["connectivity"]]
    active = next(row for row in view["research_acts"] if row["act_id"] == refs["connectivity"])
    assert active["activities"][0]["activity_id"] == "op_1"
    assert active["attempts"][0]["runs"][0]["task_id"] == "sub_1"
    assert active["compute_run_count"] == 1
    assert all("node_id" not in row for row in view["research_acts"])


def test_web_ignores_legacy_attempt_ids_and_sorts_current_ordinals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    act_id = refs["connectivity"]
    for intent_id in ("calc_10", "calc_2", "calc_legacy"):
        _write(
            workspace / "acts" / act_id / "attempts" / intent_id / "intent.json",
            {"intent_id": intent_id, "act_id": act_id, "backend": "gaussian", "task_type": "sp"},
        )
    legacy_activity = "op_019a338f-acaf-43e6-b498-4e3994971399"
    legacy_run = "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b"
    _write(workspace / "acts" / act_id / "activities" / legacy_activity / "request.json", {})
    _write(workspace / "acts" / act_id / "agent-runs" / "sub_old" / "task.json", {})
    _write(workspace / "acts" / act_id / "attempts" / "calc_1" / "runs" / legacy_run / "task.json", {})

    view = normalize_workspace(workspace)
    detail = act_payload(workspace, act_id)

    active = next(row for row in view["research_acts"] if row["act_id"] == act_id)
    assert [row["intent_id"] for row in active["attempts"]] == ["calc_1", "calc_2", "calc_10"]
    paths = {row["path"] for row in detail["files"]["files"]}
    assert f"acts/{act_id}/attempts/calc_1/runs/sub_1/task.json" in paths
    assert not any(legacy_activity in path or legacy_run in path or "/agent-runs/" in path for path in paths)
    assert not any("/attempts/calc_legacy/" in path for path in paths)


def test_graph_uses_claim_relations_and_research_act_dependencies(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    graph = graph_payload_from_view(normalize_workspace(workspace))

    assert graph["schema_version"] == "ts-explorer-graph/4"
    assert graph["claim_graph"]["edges"] == [
        {
            "id": refs["alternatives"],
            "source": refs["concerted"],
            "target": refs["stepwise"],
            "kind": "alternative_to",
            "rationale": "The Claims are competing explanations.",
        }
    ]
    assert graph["research_act_dag"]["edges"] == [
        {
            "id": f"dependency:{refs['search']}:{refs['connectivity']}",
            "source": refs["search"],
            "target": refs["connectivity"],
            "kind": "depends_on",
        }
    ]
    assert graph["deterministic_activities"][0]["kind"] == "render"
    assert {row["role"] for row in graph["agent_runs"]} == {"compute", "review"}


def test_claim_and_act_details_follow_graph_references(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    claim = claim_payload(workspace, refs["concerted"])
    active = act_payload(workspace, refs["connectivity"])
    completed = act_payload(workspace, refs["search"])

    assert {row["act_id"] for row in claim["research_acts"]} == {refs["search"], refs["connectivity"]}
    assert claim["validation_results"][0]["verdict"] == "pass"
    assert active["dependencies"][0]["act_id"] == refs["search"]
    assert active["research_act"]["activities"][0]["activity_id"] == "op_1"
    assert claim["review_runs"][0]["task_id"] == "sub_2"
    attempt = active["research_act"]["attempts"][0]
    assert {key: value for key, value in attempt.items() if key != "runs"} == {
        "intent_id": "calc_1",
        "ref": f"acts/{refs['connectivity']}/attempts/calc_1",
        "backend": "gaussian",
        "task_type": "irc",
        "state": "completed",
        "program_status": "normal_termination",
        "error_class": None,
        "run_count": 1,
    }
    assert attempt["runs"][0]["task_id"] == "sub_1"
    assert completed["dependents"][0]["act_id"] == refs["connectivity"]
    assert completed["research_act"]["hypothesis"]["falsifiers"] == [
        "The probe is compatible with both mechanisms."
    ]
    assert {row["claim_id"] for row in completed["claims"]} == {refs["concerted"], refs["stepwise"]}
    assert completed["validation_specs"][0]["title"] == "Program completion probe"
    assert f"acts/{refs['connectivity']}/outputs/probe.json" in {
        row["path"] for row in active["files"]["files"]
    }


def test_web_derives_claim_act_link_from_creator_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    act_draft = draft_decision(
        workspace,
        {
            "rationale": "Start an exploratory Act before it discovers a Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "start_act", "local_ref": "exploration", "title": "Bounded research act", "deliverable": "One bounded research result.", "objective": "Look for an alternative mechanism."}
            ],
        },
    )
    apply_decision(workspace, act_draft["decision"])
    act_id = act_draft["allocated_refs"]["exploration"]
    claim_draft = draft_decision(
        workspace,
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
    apply_decision(workspace, claim_draft["decision"])
    claim_id = claim_draft["allocated_refs"]["alternative"]

    view = normalize_workspace(workspace)
    act = next(row for row in view["research_acts"] if row["act_id"] == act_id)
    graph = graph_payload_from_view(view)
    assert act["claim_refs"] == []
    assert act["related_claim_refs"] == [claim_id]
    assert graph["claim_act_links"] == [{"claim_ref": claim_id, "act_ref": act_id}]
    assert [row["act_id"] for row in claim_payload(workspace, claim_id)["research_acts"]] == [act_id]
    assert [row["claim_id"] for row in act_payload(workspace, act_id)["claims"]] == [claim_id]


def test_static_ui_exposes_v4_dual_graph_without_legacy_routes() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert "TS Research Explorer" in html
    assert "Claim graph" in html
    assert "ResearchAct DAG" in html
    assert "Lineage and Claims" in html
    assert "Calculation attempts" in html
    assert "Compute runs" in html
    assert "Review runs" in html
    assert "Research contract" in html
    assert "Research Files" in html
    assert "renderResearchFiles" in html
    assert "/files?query=" in html
    assert "Scientific record" in html
    assert "Audit references" in html
    assert "renderActHypothesis" in html
    assert "/graph" in html
    assert "/api/node" not in html
    assert "/api/gates" not in html
    assert "/api/evidence" not in html


def test_research_files_payload_is_a_read_only_locator_projection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    before = _relative_files(workspace)

    result = research_files_payload(workspace, refs["connectivity"])

    assert result["schema_version"] == "ts-workspace-locator/1"
    assert result["query_mode"] == "exact"
    assert result["matches"][0]["kind"] == "act"
    assert result["matches"][0]["directories"][0]["path"] == f"acts/{refs['connectivity']}"
    assert _relative_files(workspace) == before


def test_static_asset_resolves_from_current_package() -> None:
    expected = files("ts_web").joinpath("static", "index.html").read_bytes()
    assert ts_web_server._static_asset("index.html").read_bytes() == expected


def test_web_distinguishes_current_from_historical_acceptance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    refs = accept_research_claim(workspace)

    current = normalize_workspace(workspace)
    assert current["current_acceptances"][0]["acceptance_id"] == refs["acceptance"]
    assert graph_payload_from_view(current)["claim_graph"]["nodes"][0]["acceptance_state"] == "current"

    drafted = draft_decision(
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
                    "actRefs": [refs["act"]],
                }
            ],
        },
    )
    apply_decision(workspace, drafted["decision"])

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


def test_web_server_is_read_only_v4_and_has_no_legacy_routes(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    refs = _make_workspace(source)
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "workspace")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        health = _get_json(host, port, "/api/health")
        assert health == {"ok": True, "protocol": "ts-research-kernel/4", "read_only": True}
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["default_workspace"] == row["workspace_id"]
        base = f"/api/workspace/{row['workspace_id']}"
        assert _get_json(host, port, f"{base}/graph")["schema_version"] == "ts-explorer-graph/4"
        assert _get_json(host, port, f"{base}/claims")["claims"][0]["schema_version"] == "ts-claim/2"
        assert _get_json(host, port, f"{base}/acts")["research_acts"][0]["schema_version"] == "ts-research-act/3"
        assert _get_json(host, port, f"{base}/observations")["observations"][0]["schema_version"] == "ts-observation/1"
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
        act = _get_json(host, port, f"{base}/act/{refs['connectivity']}")
        assert act["research_act"]["status"] == "open"
        preview = _get_json(host, port, f"{base}/file?path=acts/{refs['connectivity']}/outputs/probe.json")
        assert preview["text"] == "{}\n"
        html = _get_text(host, port, "/")[1]
        assert "TS Research Explorer" in html
        assert "act-table" in html
        for legacy in (f"{base}/tree", f"{base}/gates", f"{base}/evidence", f"{base}/node/n000", "/api/node/n000"):
            assert _get_text(host, port, legacy)[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert _relative_files(source) == before


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
