from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.workspace_helpers import start_research_node
from ts_compute.artifacts import list_calculation_artifacts
from ts_workspace.cli import main as workspace_cli
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace
from ts_workspace.errors import ContractError
from ts_workspace.locator import locate_research_files


def _write(path: Path, value: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, dict[str, str], dict[str, dict]]:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(
        root,
        objective="Verify a concerted Diels-Alder transition structure with Gaussian.",
        claim_type="mechanism",
        claim_statement="The Diels-Alder pathway is concerted.",
    )
    intent_id = "calc_1"
    attempt = root / "nodes" / refs["node_id"] / "attempts" / intent_id
    input_path = root / "nodes" / refs["node_id"] / "inputs" / "candidate.gjf"
    _write(input_path, "%chk=candidate.chk\n# opt freq hf/sto-3g\n\nCandidate\n\n0 1\nH 0 0 0\n\n")
    input_artifact = next(
        row
        for row in list_calculation_artifacts(root)["artifacts"]
        if row["path"] == input_path.relative_to(root).as_posix()
    )
    _write(
        attempt / "intent.json",
        {
            "intent_id": intent_id,
            "node_id": refs["node_id"],
            "backend": "gaussian",
            "task_type": "opt_freq",
            "input_bindings": [
                {
                    "artifact_id": input_artifact["artifact_id"],
                    "input_role": "gjf",
                    "owner_node": refs["node_id"],
                    "path": input_artifact["path"],
                    "sha256": input_artifact["sha256"],
                    "source_intent_id": None,
                }
            ],
        },
    )
    _write(
        attempt / "status.json",
        {
            "intent_id": intent_id,
            "state": "completed",
            "program_status": "normal_termination",
        },
    )
    _write(attempt / "outputs" / "remote" / "gaussian.out", "Normal termination\n")
    _write(attempt / "outputs" / "parsed" / "frequencies_cm-1.txt", "-503.1\n")
    _write(root / "nodes" / refs["node_id"] / "outputs" / "unrelated.xyz", "1\nunrelated\nH 0 0 0\n")
    catalog = list_calculation_artifacts(root)
    by_path = {row["path"]: row for row in catalog["artifacts"]}
    gaussian = by_path[
        f"nodes/{refs['node_id']}/attempts/{intent_id}/outputs/remote/gaussian.out"
    ]
    drafted = draft_decision(
        root,
        {
            "rationale": "Bind one parsed observation to the exact Gaussian output.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "record_observation",
                    "local_ref": "frequency",
                    "nodeRef": refs["node_id"],
                    "conceptId": "vibration.imaginary_frequency_count",
                    "subjectRef": intent_id,
                    "value": 1,
                    "datatype": "integer",
                    "summary": "Exactly one imaginary frequency was parsed.",
                    "artifacts": [
                        {"artifactId": gaussian["artifact_id"], "sha256": gaussian["sha256"]}
                    ],
                    "provenance": {"producer": "test-parser", "producerVersion": "1"},
                },
                {
                    "op": "record_observation",
                    "local_ref": "diagnostic",
                    "nodeRef": refs["node_id"],
                    "conceptId": "program.normal_termination",
                    "subjectRef": intent_id,
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The same output also records normal termination.",
                    "artifacts": [
                        {"artifactId": gaussian["artifact_id"], "sha256": gaussian["sha256"]}
                    ],
                    "provenance": {"producer": "test-parser", "producerVersion": "1"},
                },
                {
                    "op": "update_claim",
                    "claimRef": refs["claim_id"],
                    "status": "supported",
                    "summary": "The direct frequency observation supports the Claim.",
                    "observationRefs": ["$frequency"],
                },
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    refs = {
        **refs,
        "observation_id": drafted["allocated_refs"]["frequency"],
        "unclaimed_observation_id": drafted["allocated_refs"]["diagnostic"],
        "intent_id": intent_id,
        "artifact_id": gaussian["artifact_id"],
        "input_artifact_id": input_artifact["artifact_id"],
        "unrelated_artifact_id": by_path[f"nodes/{refs['node_id']}/outputs/unrelated.xyz"]["artifact_id"],
    }
    refreshed = list_calculation_artifacts(root)
    return root, refs, {row["artifact_id"]: row for row in refreshed["artifacts"]}


def _locate(root: Path, query: str, catalog: dict[str, dict]) -> dict:
    return locate_research_files(root, query, artifacts=catalog.values())


@pytest.mark.parametrize(
    ("ref_key", "kind"),
    [
        ("claim_id", "claim"),
        ("node_id", "node"),
        ("observation_id", "observation"),
        ("artifact_id", "artifact"),
        ("intent_id", "attempt"),
    ],
)
def test_locator_resolves_exact_research_and_execution_ids(
    tmp_path: Path,
    ref_key: str,
    kind: str,
) -> None:
    root, refs, catalog = _workspace(tmp_path)

    result = _locate(root, refs[ref_key], catalog)

    assert result["schema_version"] == "ts-workspace-locator/1"
    assert result["query_mode"] == "exact"
    assert result["match_count"] == 1
    assert result["matches"][0]["kind"] == kind
    assert result["matches"][0]["ref"] == refs[ref_key]
    assert result["matches"][0]["matched_fields"] == ["ref"]


def test_claim_locator_only_returns_direct_observation_artifacts(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)

    match = _locate(root, refs["claim_id"], catalog)["matches"][0]

    assert match["claim_refs"] == [refs["claim_id"]]
    assert match["node_refs"] == [refs["node_id"]]
    assert match["observation_refs"] == [refs["observation_id"]]
    assert [row["artifact_id"] for row in match["artifacts"]] == [refs["artifact_id"]]
    assert match["artifacts"][0]["relation"] == "direct_claim_evidence"
    assert match["artifacts"][0]["observation_refs"] == [refs["observation_id"]]
    assert match["artifacts"][0]["concept_ids"] == ["vibration.imaginary_frequency_count"]
    assert refs["unrelated_artifact_id"] not in {row["artifact_id"] for row in match["artifacts"]}
    assert match["directories"] == [
        {"path": f"nodes/{refs['node_id']}", "purpose": "node_root", "exists": True}
    ]


def test_node_locator_exposes_owned_files_attempts_and_semantic_bindings(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)

    match = _locate(root, refs["node_id"], catalog)["matches"][0]

    assert {row["artifact_id"] for row in match["artifacts"]} == set(catalog)
    assert match["attempts"][0]["intent_id"] == refs["intent_id"]
    assert match["attempts"][0]["task_type"] == "opt_freq"
    assert match["attempts"][0]["input_artifact_count"] == 1
    assert match["attempts"][0]["output_artifact_count"] == 2
    evidence = next(row for row in match["artifacts"] if row["artifact_id"] == refs["artifact_id"])
    assert evidence["relation"] == "node_observation_source"
    assert evidence["concept_ids"] == [
        "program.normal_termination",
        "vibration.imaginary_frequency_count",
    ]
    unrelated = next(
        row for row in match["artifacts"] if row["artifact_id"] == refs["unrelated_artifact_id"]
    )
    assert unrelated["relation"] == "node_owned"
    assert unrelated["observation_refs"] == []
    attempt_input = next(
        row for row in match["artifacts"] if row["artifact_id"] == refs["input_artifact_id"]
    )
    assert attempt_input["relation"] == "node_attempt_input"
    unparsed_output = next(
        row for row in match["artifacts"] if row["path"].endswith("frequencies_cm-1.txt")
    )
    assert unparsed_output["relation"] == "node_attempt_output"


def test_attempt_locator_distinguishes_frozen_inputs_from_outputs(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)

    match = _locate(root, refs["intent_id"], catalog)["matches"][0]
    relations = {row["artifact_id"]: row["relation"] for row in match["artifacts"]}

    assert relations[refs["input_artifact_id"]] == "attempt_input"
    assert relations[refs["artifact_id"]] == "attempt_output"
    assert match["attempts"][0]["input_artifact_count"] == 1
    assert match["attempts"][0]["output_artifact_count"] == 2

    input_match = _locate(root, refs["input_artifact_id"], catalog)["matches"][0]
    assert input_match["attempts"][0]["intent_id"] == refs["intent_id"]
    assert input_match["node_refs"] == [refs["node_id"]]


def test_locator_searches_scientific_terms_tasks_and_paths(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)

    scientific = _locate(root, "concerted", catalog)
    task = _locate(root, "gaussian opt_freq", catalog)
    path = _locate(root, "frequencies_cm-1", catalog)

    assert scientific["query_mode"] == "search"
    assert {row["kind"] for row in scientific["matches"]} >= {"claim", "node"}
    assert (task["matches"][0]["kind"], task["matches"][0]["ref"]) == (
        "attempt",
        refs["intent_id"],
    )
    assert path["matches"][0]["kind"] == "artifact"
    assert path["matches"][0]["artifacts"][0]["path"].endswith("frequencies_cm-1.txt")


def test_locator_index_and_results_are_bounded_and_read_only(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)
    before = {
        path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    result = _locate(root, "", catalog)
    after = {
        path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }

    assert result["query_mode"] == "index"
    assert [(row["kind"], row["ref"]) for row in result["matches"]] == [
        ("claim", refs["claim_id"]),
        ("node", refs["node_id"]),
    ]
    assert result["returned_match_count"] <= 8
    assert all(len(row["artifacts"]) <= 4 for row in result["matches"])
    assert after == before


def test_locator_rejects_oversized_query_and_duplicate_catalog_ids(tmp_path: Path) -> None:
    root, _refs, catalog = _workspace(tmp_path)
    rows = list(catalog.values())

    with pytest.raises(ContractError, match="exceeds 256"):
        locate_research_files(root, "x" * 257, artifacts=rows)
    with pytest.raises(ContractError, match="duplicate artifact_id"):
        locate_research_files(root, "claim_1", artifacts=[rows[0], rows[0]])


def test_locator_reports_total_and_returned_match_counts(tmp_path: Path) -> None:
    root, _refs, catalog = _workspace(tmp_path)
    rows = list(catalog.values())
    rows.extend(
        {
            "artifact_id": f"art_{index:024x}",
            "path": f"inputs/gaussian_candidate_{index}.log",
            "sha256": f"sha256:{index:064x}",
            "size_bytes": index,
            "owner_node": None,
            "source_intent_id": None,
            "input_roles": [],
        }
        for index in range(1, 21)
    )

    result = locate_research_files(root, "gaussian_candidate", artifacts=rows)

    assert result["match_count"] == 20
    assert result["returned_match_count"] == 8
    assert result["omitted_matches"] == 12
    assert len(result["matches"]) == 8


def test_locator_rejects_duplicate_canonical_ids(tmp_path: Path) -> None:
    root, refs, catalog = _workspace(tmp_path)
    path = root / "claims.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["claims"].append(dict(document["claims"][0]))
    _write(path, document)

    with pytest.raises(ContractError, match=f"duplicate claim_id: {refs['claim_id']}"):
        _locate(root, refs["claim_id"], catalog)


def test_workspace_cli_exposes_locator_and_requires_a_query(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, refs, _catalog = _workspace(tmp_path)

    assert workspace_cli(
        ["context", "--root", str(root), "--mode", "locate", "--query", refs["claim_id"]]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["query_mode"] == "exact"
    assert result["matches"][0]["ref"] == refs["claim_id"]

    assert workspace_cli(["context", "--root", str(root), "--mode", "locate"]) == 2
    assert "requires a non-empty --query" in capsys.readouterr().err
    assert workspace_cli(
        ["context", "--root", str(root), "--mode", "frontier", "--query", "claim_1"]
    ) == 2
    assert "only valid with mode=locate" in capsys.readouterr().err
