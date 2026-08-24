from __future__ import annotations

import http.client
import json
import threading
from importlib.resources import files
from pathlib import Path

import pytest

from tests.v5_helpers import accept_research_claim
from ts_web import normalize_workspace, register_workspace
from ts_web import server as ts_web_server
from ts_web.normalize import (
    claim_payload,
    graph_payload_from_view,
    node_payload,
    research_files_payload,
    workspace_snapshot,
)
from ts_web.registry import (
    list_workspaces,
    reconcile_workspace_registry,
    register_workspaces,
    workspace_discovery_roots,
)
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
                    "op": "freeze_validation_spec",
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
                    "op": "evaluate_validation",
                    "local_ref": "result",
                    "nodeRef": "$search",
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
                {
                    "op": "start_node",
                    "local_ref": "connectivity",
                    "phaseRef": "$mechanism",
                    "title": "Bounded research node",
                    "deliverable": "One bounded research result.",
                    "objective": "Test bidirectional connectivity.",
                    "dependencyRefs": ["$search"],
                    "primaryClaimRef": "$concerted",
                    "claimRefs": ["$concerted"],
                    "tags": ["connectivity"],
                },
                {"op": "set_focus", "claimRefs": ["$concerted"], "nodeRefs": ["$connectivity"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    refs = drafted["allocated_refs"]
    node_id = refs["connectivity"]
    artifact = root / "nodes" / node_id / "outputs" / "probe.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "intent.json",
        {
            "intent_id": "calc_1",
            "node_id": node_id,
            "backend": "gaussian",
            "task_type": "irc",
        },
    )
    _write(
        root / "nodes" / node_id / "attempts" / "calc_1" / "status.json",
        {
            "intent_id": "calc_1",
            "state": "completed",
            "program_status": "normal_termination",
        },
    )
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


def test_normalize_workspace_projects_v5_phase_node_and_operational_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    view = normalize_workspace(workspace)

    assert view["schema_version"] == "ts-web-workspace/5"
    assert view["workspace"]["kernel_protocol"] == "ts-research-kernel/5"
    assert view["research_phases"][0]["phase_id"] == refs["mechanism"]
    assert view["research_phases"][0]["node_refs"] == [refs["search"], refs["connectivity"]]
    assert view["focus"]["phase_refs"] == [refs["mechanism"]]
    assert view["focus"]["claim_refs"] == [refs["concerted"]]
    assert view["focus"]["node_refs"] == [refs["connectivity"]]
    active = next(row for row in view["research_nodes"] if row["node_id"] == refs["connectivity"])
    assert active["activities"][0]["activity_id"] == "op_1"
    assert active["attempts"][0]["runs"][0]["task_id"] == "sub_1"
    assert active["compute_run_count"] == 1
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
    original = ts_web_server.normalize_workspace

    def counted(source_root, *, label=None):
        nonlocal calls
        calls += 1
        return original(source_root, label=label)

    monkeypatch.setattr("ts_web.normalize.normalize_workspace", counted)
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


def test_web_ignores_legacy_attempt_ids_and_sorts_current_ordinals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)
    node_id = refs["connectivity"]
    for intent_id in ("calc_10", "calc_2", "calc_legacy"):
        _write(
            workspace / "nodes" / node_id / "attempts" / intent_id / "intent.json",
            {"intent_id": intent_id, "node_id": node_id, "backend": "gaussian", "task_type": "sp"},
        )
    legacy_activity = "op_019a338f-acaf-43e6-b498-4e3994971399"
    legacy_run = "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b"
    _write(workspace / "nodes" / node_id / "activities" / legacy_activity / "request.json", {})
    _write(workspace / "nodes" / node_id / "agent-runs" / "sub_old" / "task.json", {})
    _write(workspace / "nodes" / node_id / "attempts" / "calc_1" / "runs" / legacy_run / "task.json", {})

    view = normalize_workspace(workspace)
    detail = node_payload(workspace, node_id)

    active = next(row for row in view["research_nodes"] if row["node_id"] == node_id)
    assert [row["intent_id"] for row in active["attempts"]] == ["calc_1", "calc_2", "calc_10"]
    paths = {row["path"] for row in detail["files"]["files"]}
    assert f"nodes/{node_id}/attempts/calc_1/runs/sub_1/task.json" in paths
    assert not any(legacy_activity in path or legacy_run in path or "/agent-runs/" in path for path in paths)
    assert not any("/attempts/calc_legacy/" in path for path in paths)


def test_graph_uses_claim_relations_and_research_node_dependencies(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    graph = graph_payload_from_view(normalize_workspace(workspace))

    assert graph["schema_version"] == "ts-explorer-graph/5"
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
    assert graph["deterministic_activities"][0]["kind"] == "render"
    assert {row["role"] for row in graph["agent_runs"]} == {"compute", "review"}


def test_claim_and_node_details_follow_graph_references(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    refs = _make_workspace(workspace)

    claim = claim_payload(workspace, refs["concerted"])
    active = node_payload(workspace, refs["connectivity"])
    completed = node_payload(workspace, refs["search"])

    assert {row["node_id"] for row in claim["research_nodes"]} == {refs["search"], refs["connectivity"]}
    assert claim["validation_results"][0]["verdict"] == "pass"
    assert active["dependencies"][0]["node_id"] == refs["search"]
    assert active["research_node"]["activities"][0]["activity_id"] == "op_1"
    assert claim["review_runs"][0]["task_id"] == "sub_2"
    attempt = active["research_node"]["attempts"][0]
    assert {key: value for key, value in attempt.items() if key != "runs"} == {
        "intent_id": "calc_1",
        "ref": f"nodes/{refs['connectivity']}/attempts/calc_1",
        "backend": "gaussian",
        "task_type": "irc",
        "state": "completed",
        "program_status": "normal_termination",
        "error_class": None,
        "run_count": 1,
    }
    assert attempt["runs"][0]["task_id"] == "sub_1"
    assert completed["dependents"][0]["node_id"] == refs["connectivity"]
    assert completed["phase"]["phase_id"] == refs["mechanism"]
    assert completed["history"][0]["decision_id"] == completed["research_node"]["created_by_decision"]
    assert {row["claim_id"] for row in completed["claims"]} == {refs["concerted"], refs["stepwise"]}
    assert completed["validation_specs"][0]["title"] == "Program completion probe"
    assert f"nodes/{refs['connectivity']}/outputs/probe.json" in {
        row["path"] for row in active["files"]["files"]
    }


def test_web_derives_claim_node_link_from_creator_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    node_draft = draft_decision(
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
    apply_decision(workspace, node_draft["decision"])
    node_id = node_draft["allocated_refs"]["exploration"]
    claim_draft = draft_decision(
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
    apply_decision(workspace, claim_draft["decision"])
    claim_id = claim_draft["allocated_refs"]["alternative"]

    view = normalize_workspace(workspace)
    node = next(row for row in view["research_nodes"] if row["node_id"] == node_id)
    graph = graph_payload_from_view(view)
    assert node["claim_refs"] == []
    assert node["related_claim_refs"] == [claim_id]
    assert graph["claim_node_links"] == [{"claim_ref": claim_id, "node_ref": node_id}]
    assert [row["node_id"] for row in claim_payload(workspace, claim_id)["research_nodes"]] == [node_id]
    assert [row["claim_id"] for row in node_payload(workspace, node_id)["claims"]] == [claim_id]


def test_static_ui_exposes_v5_phase_roadmap_and_on_demand_node_details() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ts_web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "TS Research Explorer" in html
    assert "Research Roadmap" in html
    assert "Scientific Conclusions" in html
    assert "Research Files" in html
    assert "Advanced Graphs" in html
    assert "app.css" in html
    assert "app.js" in html
    assert "renderPhaseBand" in script
    assert "renderNodeDetail" in script
    assert 'const tabs = ["overview", "conclusions", "evidence", "runs", "files", "history"]' in script
    assert 'control: [state.view.unresolved_controls, "control_id"]' in script
    assert "function renderActDetail" not in script
    assert "/api/node" not in html + script
    assert "/api/gates" not in html + script
    assert "/api/evidence" not in html + script


def test_static_ui_refreshes_registry_and_persists_theme() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "ts_web" / "static" / "app.css").read_text(encoding="utf-8")
    script = (ROOT / "ts_web" / "static" / "app.js").read_text(encoding="utf-8")

    assert ':root[data-theme="dark"]' in css
    assert "body.inspector-open { overflow: hidden; }" in css
    assert 'id="theme-button"' in html
    assert 'const themeStorageKey = "ts-explorer-theme"' in script
    assert 'themeButton.addEventListener("click", toggleTheme)' in script
    assert "async function loadWorkspaceCatalog()" in script
    assert 'const payload = await api("/api/workspaces")' in script
    assert 'refreshButton.addEventListener("click", refreshExplorer)' in script
    assert 'refreshStatus.textContent = "Refreshing workspace"' in script
    assert 'showToast("Workspace refreshed")' in script
    assert "const liveRefreshIntervalMs = 5000" in script
    assert "async function pollLiveRefresh()" in script
    assert 'document.addEventListener("visibilitychange"' in script
    assert 'setHealth("stale", "Stale")' in script
    assert "/snapshot?${query}" in script
    assert "renderUnavailableWorkspace(catalogRow)" in script
    assert 'row.available === false ? " (incompatible)" : ""' in script


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
    for name in ("index.html", "app.css", "app.js"):
        expected = files("ts_web").joinpath("static", name).read_bytes()
        assert ts_web_server._static_asset(name).read_bytes() == expected


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
                    "nodeRefs": [refs["node"]],
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


def test_workspace_discovery_roots_use_installation_layout_or_explicit_roots(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    state = installation / ".pi" / "ts-web"
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert workspace_discovery_roots(state) == [installation / "workspaces"]
    assert workspace_discovery_roots(tmp_path / "custom-state") == []
    assert workspace_discovery_roots(state, [first, first, second]) == [first, second]


def test_reconcile_workspace_registry_discovers_v5_and_prunes_only_stale_managed_rows(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    managed = installation / "workspaces"
    current = managed / "ts_001"
    init_workspace(current)
    stale = managed / "ts_004"
    legacy = managed / "legacy"
    legacy.mkdir()
    _write(legacy / "workspace.json", {"schema_version": "ts-workspace/4"})
    external = tmp_path / "external"
    init_workspace(external)
    state = installation / ".pi" / "ts-web"
    register_workspaces(
        [stale, legacy, external],
        state,
        ["stale managed", "registered legacy", "external label"],
    )

    rows = reconcile_workspace_registry(state, [managed])
    by_source = {row["source_root"]: row for row in rows}

    assert str(stale.resolve()) not in by_source
    assert by_source[str(current.resolve())]["label"] == "ts_001"
    assert by_source[str(legacy.resolve())]["label"] == "registered legacy"
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
    server = create_server("127.0.0.1", 0, state)
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
    incompatible = tmp_path / "v4-workspace"
    incompatible.mkdir()
    _write(incompatible / "workspace.json", {"schema_version": "ts-workspace/4"})
    compatible = tmp_path / "v5-workspace"
    _make_workspace(compatible)
    state = tmp_path / "web-state"
    old_row, new_row = register_workspaces(
        [incompatible, compatible],
        state,
        ["old workspace", "current workspace"],
    )
    server = create_server("127.0.0.1", 0, state)
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
        assert "cannot read v5 workspace file" in summaries[old_row["workspace_id"]]["load_error"]
        assert _get_text(host, port, f"/api/workspace/{old_row['workspace_id']}")[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_server_is_read_only_v5_and_has_no_legacy_routes(tmp_path: Path) -> None:
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
        assert health == {"ok": True, "protocol": "ts-research-kernel/5", "read_only": True}
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
        assert _get_json(host, port, f"{base}/graph")["schema_version"] == "ts-explorer-graph/5"
        assert _get_json(host, port, f"{base}/phases")["research_phases"][0]["phase_id"] == refs["mechanism"]
        assert _get_json(host, port, f"{base}/claims")["claims"][0]["schema_version"] == "ts-claim/3"
        assert _get_json(host, port, f"{base}/nodes")["research_nodes"][0]["schema_version"] == "ts-research-node/1"
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
        preview = _get_json(host, port, f"{base}/file?path=nodes/{refs['connectivity']}/outputs/probe.json")
        assert preview["text"] == "{}\n"
        assert _get_text(host, port, f"{base}/file?path=workspace.json")[0] == 400
        html = _get_text(host, port, "/")[1]
        assert "TS Research Explorer" in html
        assert _get_text(host, port, "/app.css")[0] == 200
        assert _get_text(host, port, "/app.js")[0] == 200
        for legacy in (f"{base}/tree", f"{base}/gates", f"{base}/evidence", "/api/node/n000"):
            assert _get_text(host, port, legacy)[0] == 404
        assert _get_text(host, port, f"{base}/node/n000")[0] == 400
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
