"""Exact workspace references survive mutation, concurrency and process restart."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from research_state.references import (ReferenceError, annotate_artifact_references, artifact_reference,
                                       prepare_job, resolve_artifact_reference, resolve_operation_references,
                                       resolve_prepared_job)
from research_state.agent_workspace import apply_change, read_context
from tspi_runtime.api import execute
from tspi_runtime.evidence import dispatch as evidence
from tspi_runtime.execution import JobSubmissionError, dispatch as execute_job
from tests.unit.test_job_recovery import workspace


def prepared(root, *, command=None, work_id="work_one"):
    path = root / "request.json"
    path.write_text(json.dumps({"request_id": "request_one", "work_id": work_id,
                               "command": command or [sys.executable, "-c", "pass"],
                               "inputs": [{"source": "input.xyz", "destination": "input.xyz"}]}))
    return path


def test_prepared_ref_is_immutable_and_input_versions_are_checked(tmp_path):
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("original geometry")
    path = prepared(tmp_path)
    first = prepare_job(tmp_path, {"request_file": str(path)})
    assert first["prepared_ref"] == "p1"
    assert prepare_job(tmp_path, {"request_file": str(path)}) == first
    original = resolve_prepared_job(tmp_path, {"prepared_ref": "p1", "node_id": "node_1"})
    assert original["work_id"] == "work_one"
    assert original["inputs"][0]["sha256"]
    path.write_text(path.read_text().replace('"pass"', '"print(2)"'))
    second = prepare_job(tmp_path, {"request_file": str(path)})
    assert second["prepared_ref"] != first["prepared_ref"]
    assert resolve_prepared_job(tmp_path, {"prepared_ref": "p1", "node_id": "node_1"}) == original
    with pytest.raises(ReferenceError, match="prepared_override_forbidden"):
        resolve_prepared_job(tmp_path, {"prepared_ref": "p1", "work_id": "replace"})
    (tmp_path / "input.xyz").write_text("changed geometry")
    with pytest.raises(ReferenceError, match="prepared_input_changed"):
        resolve_prepared_job(tmp_path, {"prepared_ref": "p1"})
    third = prepare_job(tmp_path, {"request_file": str(path)})
    assert third["prepared_ref"] not in {first["prepared_ref"], second["prepared_ref"]}


def test_concurrent_preparation_and_restart_reuse_one_reference(tmp_path):
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    path = prepared(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: prepare_job(tmp_path, {"request_file": str(path)}), range(8)))
    assert {value["prepared_ref"] for value in values} == {"p1"}
    script = "from research_state.references import prepare_job; import json,sys; print(json.dumps(prepare_job(sys.argv[1], {'request_file':sys.argv[2]})))"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(path)], env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["prepared_ref"] == "p1"
    assert len(list((tmp_path / "operations/references/records").glob("*.json"))) == 1


def test_artifact_refs_are_exact_typed_and_preserve_canonical_provenance(tmp_path):
    workspace(tmp_path)
    item = evidence("create", {"root": str(tmp_path), "node_id": "node_1", "name": "note", "content": "result"})
    assert item["artifact_ref"] == "a1"
    assert artifact_reference(tmp_path, item["artifact_id"]) == "a1"
    assert evidence("read", {"root": str(tmp_path), "artifact_id": "a1"})["content"] == "result"
    assert resolve_artifact_reference(tmp_path, "a1") == item["artifact_id"]
    op = {"type": "create_finding", "statement": "a1 is written literally here", "source_refs": ["a1"]}
    resolved = resolve_operation_references(tmp_path, [op])[0]
    assert resolved["source_refs"] == [item["artifact_id"]]
    assert resolved["statement"] == op["statement"]
    assert op["source_refs"] == ["a1"]
    with pytest.raises(ReferenceError, match="reference_not_found.*available references: a1"):
        resolve_artifact_reference(tmp_path, "a99")
    with pytest.raises(ReferenceError, match="reference_type_mismatch"):
        resolve_artifact_reference(tmp_path, "p1")
    canonical = read_context(tmp_path)["artifacts"][0]
    assert annotate_artifact_references(tmp_path, {"records": [canonical]})["records"][0]["artifact_ref"] == "a1"


def test_artifact_refs_do_not_escape_the_bound_workspace(tmp_path):
    first, other = tmp_path / "first", tmp_path / "other"
    first.mkdir(); other.mkdir()
    workspace(first); workspace(other)
    evidence("create", {"root": str(first), "name": "note", "content": "result"})
    with pytest.raises(ReferenceError, match="reference_not_found"):
        resolve_artifact_reference(other, "a1")


def test_public_commands_and_changes_resolve_artifact_selectors(tmp_path):
    workspace(tmp_path)
    item = execute("artifact.create", tmp_path, {"node_id": "node_1", "content": "result"})
    other = execute("artifact.create", tmp_path, {"node_id": "node_1", "content": "other result"})
    ref = item["artifact_ref"]
    assert execute("artifact.read", tmp_path, {"artifact_ref": ref})["content"] == "result"
    assert execute("research.detail", tmp_path, {"kind": "artifact", "id": ref})["item"]["id"] == item["artifact_id"]
    with pytest.raises(ValueError, match="artifact_selector_conflict"):
        execute("artifact.read", tmp_path, {"artifact_ref": ref, "artifact_id": other["artifact_id"]})
    with pytest.raises(ValueError, match="artifact_selector_required"):
        execute("artifact.read", tmp_path, {})
    linked = execute("artifact.link", tmp_path, {"artifact_ref": ref, "subject_id": "claim_1"})
    assert linked["artifact_id"] == item["artifact_id"]
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "operations": [{
        "type": "link_evidence", "id": "evidence_via_change", "artifact_ref": other["artifact_ref"],
        "subject_type": "claim", "subject_id": "claim_1", "relation": "documents",
    }]})
    assert next(row for row in read_context(tmp_path)["evidence_links"] if row["id"] == "evidence_via_change")["artifact_id"] == other["artifact_id"]


def test_preparation_cli_emits_a_managed_reference_in_workspace(tmp_path):
    workspace(tmp_path)
    config = tmp_path / "job.toml"
    config.write_text('''default_environment = "local"
[environments.local]
kind = "local"
[environments.local.python]
manager = "conda"
conda_executable = "/opt/conda/bin/conda"
prefix = "/opt/runner"
lock_ref = "/opt/locks/runner.lock"
[environments.local.backends.xtb]
command = ["/opt/xtb"]
''')
    xyz = tmp_path / "water.xyz"
    xyz.write_text("1\nH\nH 0 0 0\n")
    output = tmp_path / "prepared" / "request.json"
    helper = Path(__file__).resolve().parents[2] / "extensions/chemical/skills/method-selection/scripts/prepare_job.py"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run([sys.executable, str(helper), "--config", str(config), "--environment", "local",
                             "--backend", "xtb", "--skill", "xtb", "--xyz", str(xyz), "--output", str(output),
                             "--", "--task", "sp"], env=env, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value["prepared_ref"] == "p1"
    assert execute("job.prepare", tmp_path, {"request_file": str(output)}) == value
    resolved = execute("job.resolve_prepared", tmp_path, {"prepared_ref": value["prepared_ref"], "node_id": "node_1"})
    assert resolved["node_id"] == "node_1"
    assert resolved["work_id"] == value["work_id"]
    assert resolved["inputs"][-1]["source"] == str(xyz)
    assert not read_context(tmp_path)["attempts"]


def test_tampered_prepared_snapshot_is_rejected(tmp_path):
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    path = prepared(tmp_path)
    prepare_job(tmp_path, {"request_file": str(path)})
    snapshot = tmp_path / "operations/references/records/p1.json"
    value = json.loads(snapshot.read_text())
    value["payload"]["request"]["command"] = ["false"]
    snapshot.write_text(json.dumps(value))
    with pytest.raises(ReferenceError, match="prepared_snapshot_changed"):
        resolve_prepared_job(tmp_path, {"prepared_ref": "p1"})


def test_repeated_reference_submissions_reuse_the_same_real_job(tmp_path):
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    marker = tmp_path / "launches.txt"
    path = prepared(tmp_path, command=[sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).open('a').write('run\\n')"])
    ref = prepare_job(tmp_path, {"request_file": str(path)})["prepared_ref"]
    params = {"prepared_ref": ref, "node_id": "node_1"}
    def launch(_):
        try:
            return execute("job.start", tmp_path, params)
        except JobSubmissionError:
            # A competing dispatcher may not yet have committed its receipt.
            # The caller must reconcile that identity, never submit new work.
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(launch, range(2)))
    first = next(result for result in outcomes if result is not None)
    assert execute("job.start", tmp_path, params)["job_id"] == first["job_id"]
    # Collect waits for this very small fixture Job to finish; no solver or
    # long-lived service is involved.
    import time
    for _ in range(200):
        if execute_job("status", {"root": str(tmp_path), "job_id": first["job_id"]})["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.01)
    assert marker.read_text() == "run\n"
    assert len(read_context(tmp_path)["attempts"]) == 1
    assert execute_job("collect", {"root": str(tmp_path), "job_id": first["job_id"]})["status"]["state"] == "succeeded"


def test_registry_index_and_snapshot_recover_as_one_transaction(tmp_path, monkeypatch):
    from research_state import transactions
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    path = prepared(tmp_path)
    original = transactions._atomic_json
    def fail_index(target, value):
        if target == tmp_path / "operations/references/index.json":
            raise OSError("simulated reference index write failure")
        return original(target, value)
    monkeypatch.setattr(transactions, "_atomic_json", fail_index)
    with pytest.raises(OSError, match="index write failure"):
        prepare_job(tmp_path, {"request_file": str(path)})
    monkeypatch.setattr(transactions, "_atomic_json", original)
    value = prepare_job(tmp_path, {"request_file": str(path)})
    assert value["prepared_ref"] == "p1"
    assert resolve_prepared_job(tmp_path, {"prepared_ref": "p1"})["work_id"] == "work_one"
    assert len(list((tmp_path / "operations/references/records").glob("*.json"))) == 1
