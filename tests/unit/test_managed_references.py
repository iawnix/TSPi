"""Exact workspace references survive mutation, concurrency and process restart."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
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


def test_preparation_cli_emits_only_a_file_and_digest_in_workspace(tmp_path):
    workspace(tmp_path)
    config = tmp_path / "job.toml"
    from job_runtime.config_contract import load_job_config
    python = load_job_config(config)['environments']['local']['backends']['validation']['python']
    config.write_text('''default_environment = "local"
[environments.local]
kind = "local"
[environments.local.python]
manager = "conda"
conda_executable = CONDA_PATH
prefix = PREFIX_PATH
lock_ref = LOCK_PATH
[environments.local.backends.xtb]
command = ["/bin/true"]
'''.replace('CONDA_PATH', json.dumps(python['conda_executable']))
       .replace('PREFIX_PATH', json.dumps(python['prefix'])).replace('LOCK_PATH', json.dumps(python['lock_ref'])))
    xyz = tmp_path / "water.xyz"
    xyz.write_text("1\nH\nH 0 0 0\n")
    output = tmp_path / "prepared" / "request.json"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join(sys.path)}
    before = read_context(tmp_path)
    result = subprocess.run([sys.executable, "-m", "tspi_runtime.executors", "--config", str(config), "--environment", "local",
                             "--executor", "chemical.xtb", "--version", "1", "--input", "geometry=" + str(xyz), "--output", str(output),
                             "--", "--task", "sp"], env=env, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value == {"request_file": str(output), "request_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    assert any(row['source'] == str(xyz) for row in json.loads(output.read_text())["inputs"])
    assert read_context(tmp_path) == before
    assert not (tmp_path / "operations/references/index.json").exists()


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


@pytest.mark.parametrize("change, error", [
    ({"request_sha256": "0" * 64}, "prepared_request_changed"),
    ({"request_sha256": None}, "prepared_request_digest_required"),
    ({"command": ["false"]}, "prepared_override_forbidden"),
    ({"request_id": "replacement"}, "prepared_override_forbidden: remove top-level request_id"),
    ({"node_id": "node_missing"}, "research_node_required"),
])
def test_file_submission_rejection_does_not_register_or_stage(tmp_path, change, error):
    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    path = prepared(tmp_path)
    params = {"request_file": str(path), "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "node_id": "node_1", **change}
    before = read_context(tmp_path)
    with pytest.raises(ValueError, match=error):
        execute("job.start", tmp_path, params)
    assert read_context(tmp_path) == before
    assert not (tmp_path / "operations/references/index.json").exists()
    assert not list((tmp_path / "operations/jobs").glob("*.json"))
    assert not list((tmp_path / "runs/jobs").glob("*"))


def test_file_submission_freezes_one_read_and_replays_without_execution(tmp_path, monkeypatch):
    from research_state import references
    import time

    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    marker = tmp_path / "launches.txt"
    path = prepared(tmp_path, command=[sys.executable, "-c",
        f"from pathlib import Path; Path({str(marker)!r}).open('a').write('run\\n')"])
    encoded = path.read_bytes()
    params = {"request_file": str(path), "request_sha256": hashlib.sha256(encoded).hexdigest(), "node_id": "node_1"}
    original = references.read_prepared_file
    reads = []

    def read_and_replace(root, request):
        value = original(root, request)
        reads.append(value)
        # Mutation after resolution must neither change the staged command
        # nor be silently incorporated by a second parser in another layer.
        path.write_text(json.dumps({"command": ["false"]}))
        return value

    monkeypatch.setattr(references, "read_prepared_file", read_and_replace)
    first = execute("job.start", tmp_path, params)
    assert len(reads) == 1
    assert first["prepared_ref"] == "p1"
    frozen = resolve_prepared_job(tmp_path, {"prepared_ref": "p1"})
    assert frozen["command"] == json.loads(encoded)["command"]
    path.write_bytes(encoded)
    replay = execute("job.start", tmp_path, params)
    assert replay["prepared_ref"] == "p1"
    assert replay["job_id"] == first["job_id"]
    assert execute("job.start", tmp_path, {"prepared_ref": "p1", "node_id": "node_1"})["job_id"] == first["job_id"]
    for _ in range(200):
        status = execute_job("status", {"root": str(tmp_path), "job_id": first["job_id"]})
        if status["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.01)
    assert status["state"] == "succeeded"
    assert marker.read_text() == "run\n"
    assert len(read_context(tmp_path)["attempts"]) == 1
    assert len(list((tmp_path / "operations/references/records").glob("p*.json"))) == 1


def test_file_reference_and_attempt_recover_in_the_same_dispatch_transaction(tmp_path, monkeypatch):
    from research_state import transactions

    workspace(tmp_path)
    (tmp_path / "input.xyz").write_text("geometry")
    marker = tmp_path / "launches.txt"
    path = prepared(tmp_path, command=[sys.executable, "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()"])
    params = {"request_file": str(path), "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "node_id": "node_1"}
    original = transactions._atomic_json

    def fail_index(target, value):
        if target == tmp_path / "operations/references/index.json":
            raise OSError("simulated index failure before dispatch")
        return original(target, value)

    monkeypatch.setattr(transactions, "_atomic_json", fail_index)
    with pytest.raises(OSError, match="index failure"):
        execute("job.start", tmp_path, params)
    monkeypatch.setattr(transactions, "_atomic_json", original)
    replay = execute("job.start", tmp_path, params)
    assert replay["state"] == "unknown"
    assert not marker.exists()
    assert resolve_prepared_job(tmp_path, {"prepared_ref": "p1"})["work_id"] == "work_one"
    attempts = read_context(tmp_path)["attempts"]
    assert len(attempts) == 1
    intent = json.loads((tmp_path / f"operations/jobs/{replay['job_id']}.json").read_text())
    assert intent["prepared_ref"] == "p1"
    assert intent["attempt_id"] == attempts[0]["id"]
