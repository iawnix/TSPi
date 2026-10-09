"""User requirements survive plan changes and require matching execution evidence."""
import hashlib
import json
import sys
import time

import pytest

from research_state.agent_workspace import AgentWorkspaceError, checkpoint, read_context, read_liveness
from research_state.requirements import requirements_evaluation
from research_state.sources import record_source
from tspi_runtime.evidence import dispatch as artifact
from tspi_runtime.execution import dispatch
from tests.unit.test_job_recovery import workspace
from tests.unit.test_reliability_contract import change


@pytest.fixture
def profile(tmp_path, monkeypatch):
    package = tmp_path / "installed-package"
    extension = package / "extensions/fixture"
    extension.mkdir(parents=True)
    script = extension / "validate.py"
    script.write_text("""import json
from pathlib import Path
spec = json.loads(Path('input_0').read_text())
source = json.loads(Path('validator_inputs.json').read_text())['inputs'][0]
Path('validator_result.json').write_text(json.dumps({'schema_version':'validator-output/1','verdict':'pass',
 'bindings':{'spec_artifact_id':source['artifact_id'],'spec_sha256':source['sha256'],'method':spec['method']}}))
""")
    checks = [{"id": name, "kind": "validator_result", "validator_id": "fixture." + name, "validator_version": "1"}
              for name in ("mapping", "saddle", "path")]
    validators = []
    for check in checks:
        entry = extension / (check["id"] + ".py")
        entry.write_text(script.read_text() + "\n# Fixture criterion: " + check["id"] + "\n")
        validators.append({"id": check["validator_id"], "version": "1", "entry": entry.name, "backend": "validation",
            "sha256": "sha256:" + hashlib.sha256(entry.read_bytes()).hexdigest(),
            "input_contract": {"schema_version": "validator-input/1", "roles": [
                {"name": "spec", "source": "registered_artifact", "schema_version": "fixture-spec/1"}]}})
    (extension / "manifest.json").write_text(json.dumps({"schema_version": "tspi-extension/1", "name": "fixture", "version": "1.0.0", "skills": [], "validators": validators, "acceptance_profiles": [{
            "id": "fixture.path", "version": "1", "description": "Three independently executed fixture checks",
            "subject_binding": "spec_artifact_id", "binding_keys": ["spec_artifact_id", "spec_sha256", "method"],
            "constraint_keys": ["method"], "checks": checks}]}))
    monkeypatch.setenv("TSPI_EXTENSION_MANIFESTS", str(extension / "manifest.json"))
    return {"id": "fixture.path", "version": "1"}


def source(root, text="Study the selected path with M062X.", message_id="message_1"):
    return record_source(root, {"session_id": "session_fixture", "message_id": message_id, "text": text})["source_ref"]


def requirement(root, profile, **values):
    src = source(root)
    operation = {"type": "create_requirement", "id": "requirement_path", "source_ref": src,
                 "source_quote": "Study the selected path with M062X.", "statement": "Validate the selected reaction path",
                 "acceptance_profile": profile, "constraints": {"method": "M062X"}, "node_ids": ["node_1"], **values}
    change(root, [operation])
    return operation


def input_spec(root, method="M062X"):
    return artifact("create", {"root": str(root), "content": json.dumps({"schema_version": "fixture-spec/1", "method": method})})["artifact_id"]


def run_validator(root, validator_id, spec, suffix="", additional_inputs=()):
    job_id = "job_" + validator_id.replace(".", "_") + suffix
    dispatch("start", {"root": str(root), "job_id": job_id, "node_id": "node_1", "session_id": "session_fixture",
                       "validator_id": validator_id, "validator_version": "1", "input_artifact_ids": [spec, *additional_inputs]})
    for _ in range(200):
        if dispatch("status", {"root": str(root), "job_id": job_id})["state"] not in {"started", "running"}:
            break
        time.sleep(.01)
    result = dispatch("collect", {"root": str(root), "job_id": job_id})
    assert result["result_receipt"]["validator_result"]["verdict"] == "pass", (root / "runs/jobs" / job_id / "logs/stderr.log").read_text()
    return result["result_receipt"]["receipt_id"]


def assess(root, receipts=(), identifier="requirement_assessment_1", **values):
    change(root, [{"type": "assess_requirement", "id": identifier, "requirement_id": "requirement_path",
                   "reason": "Inspect current checks against the user deliverable", "result_receipt_refs": list(receipts), **values}])
    return requirements_evaluation(read_context(root))


def finish(root):
    return checkpoint(root, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_final", "disposition": "terminal", "reason": "End this bounded run"}})


def test_sources_are_atomic_authentic_and_must_be_reviewed(tmp_path):
    workspace(tmp_path)
    ref = source(tmp_path, "What is the current status?")
    state = read_context(tmp_path)
    assert len(state["requirement_sources"]) == 1
    assert source(tmp_path, "What is the current status?") == ref
    assert len(read_context(tmp_path)["requirement_sources"]) == 1
    assert any(row["kind"] == "review_user_source" for row in read_liveness(tmp_path)["research_obligations"])
    with pytest.raises(AgentWorkspaceError, match="requirements_unsettled"):
        finish(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="requirement_source_host_only"):
        change(tmp_path, [{"type": "register_requirement_source", "source_ref": ref}])
    change(tmp_path, [{"type": "review_source", "source_ref": ref, "disposition": "no_new_requirements",
                       "reason": "This is a status question about the existing work."}])
    assert requirements_evaluation(read_context(tmp_path))["settled"]
    assert not requirements_evaluation(read_context(tmp_path))["satisfied"]


def test_requirement_registration_needs_no_profile_and_cannot_disappear(tmp_path):
    workspace(tmp_path)
    src = source(tmp_path, "Calculate a new biological observable with method X.")
    change(tmp_path, [{"type": "create_requirement", "id": "requirement_path", "source_ref": src,
                       "source_quote": "Calculate a new biological observable with method X.",
                       "statement": "Calculate the observable", "execution_required": True,
                       "constraints": {"new_observable": "X"}}])
    result = assess(tmp_path)
    assert not result["satisfied"] and not result["settled"]
    assert result["requirements"][0]["constraints"] == {"new_observable": "X"}
    assert any(row["id"] == "acceptance_criteria" and not row["satisfied"] for row in result["requirements"][0]["checks"])
    with pytest.raises(AgentWorkspaceError, match="requirement_source_has_requirements"):
        change(tmp_path, [{"type": "review_source", "source_ref": src, "disposition": "no_new_requirements",
                           "reason": "No installed method exists, so ignore the request"}])
    with pytest.raises(AgentWorkspaceError, match="requirements_unsettled"):
        finish(tmp_path)


def test_missing_template_preserves_obligation_and_cannot_be_replaced_by_material(tmp_path):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "biology.new_method", "version": "1"}, constraints={"temperature": 300})
    report = artifact("create", {"root": str(tmp_path), "content": "No installed template was found"})
    result = assess(tmp_path, evidence_refs=[report["artifact_id"]])
    assert not result["satisfied"]
    assert result["requirements"][0]["checks"][0]["id"] == "acceptance_profile"
    with pytest.raises(AgentWorkspaceError, match="requirement_minimum_cannot_be_weakened"):
        change(tmp_path, [{"type": "revise_requirement", "requirement_id": "requirement_path",
                           "acceptance_profile": {"id": "research.material", "version": "1"}, "reason": "Substitute a report"}])


def test_task_composed_checks_require_execution_and_cannot_be_weakened(tmp_path):
    from research_state.workspace import initialize_workspace
    from research_state.agent_workspace import admit_workspace
    initialize_workspace(tmp_path, "simple_computation", "research")
    admit_workspace(tmp_path, {"authority": "host"})
    src = source(tmp_path, "Compute the requested observable.")
    change(tmp_path, [{"type": "create_node", "id": "node_1", "title": "Compute", "objective": "Produce an observable"},
                     {"type": "create_requirement", "id": "requirement_path", "source_ref": src,
                      "source_quote": "Compute the requested observable.", "statement": "Compute the observable",
                      "node_ids": ["node_1"], "execution_required": True}])
    input_id = artifact("create", {"root": str(tmp_path), "content": "bounded input data"})["artifact_id"]
    input_path = next(row["location"] for row in read_context(tmp_path)["artifacts"] if row["id"] == input_id)
    change(tmp_path, [{"type": "bind_requirement", "requirement_id": "requirement_path",
                       "input_artifact_ids": [input_id], "reason": "Bind the actual data used by this computation"}])
    with pytest.raises(ValueError, match="job_input_not_staged"):
        dispatch("start", {"root": str(tmp_path), "job_id": "job_fake_input", "node_id": "node_1",
                           "command": [sys.executable, "-c", "pass"], "input_artifact_ids": [input_id]})
    criterion = {"id": "meaning", "source_type": "agent_assessment", "description": "Inspect the reported observable and its units"}
    change(tmp_path, [{"type": "revise_requirement", "requirement_id": "requirement_path",
                       "criteria": [criterion], "reason": "Define how to interpret the output"}])
    for extra in ({"execution_required": False}, {"criteria": [{**criterion, "description": "A report exists"}]}):
        with pytest.raises(AgentWorkspaceError, match="requirement_minimum_cannot_be_weakened"):
            change(tmp_path, [{"type": "revise_requirement", "requirement_id": "requirement_path",
                               "reason": "Weaken the task", **extra}])
    judgment = [{"criterion_id": "meaning", "verdict": "pass", "reason": "Inspected the output and units"}]
    assert not assess(tmp_path, assessments=judgment)["satisfied"]

    def run(job_id, code):
        dispatch("start", {"root": str(tmp_path), "job_id": job_id, "node_id": "node_1",
                           "command": [sys.executable, "-c", "from pathlib import Path; Path('value.txt').write_text('1 Hartree'); raise SystemExit(" + str(code) + ")"],
                           "input_artifact_ids": [input_id], "inputs": [{"source": input_path, "destination": "data.txt"}],
                           "outputs": [{"path": "value.txt", "required": True}]})
        for _ in range(200):
            if dispatch("status", {"root": str(tmp_path), "job_id": job_id})["state"] in {"succeeded", "failed"}:
                break
            time.sleep(.01)
        return dispatch("collect", {"root": str(tmp_path), "job_id": job_id})["result_receipt"]["receipt_id"]

    failed = run("job_failed", 1)
    assert not assess(tmp_path, [failed], identifier="failed_assessment", assessments=judgment)["satisfied"]
    with pytest.raises(AgentWorkspaceError, match="requirement_machine_verdict_mismatch"):
        assess(tmp_path, [failed], identifier="override_failed", assessments=[*judgment,
            {"criterion_id": "requirement.execution_succeeded", "verdict": "pass", "result_receipt_ref": failed}])
    succeeded = run("job_succeeded", 0)
    assert assess(tmp_path, [succeeded], identifier="success_assessment", assessments=judgment)["satisfied"]
    state = read_context(tmp_path)
    assert state["claims"] == [] and state["gates"] == [] and state["strategy_plans"] == []
    (tmp_path / "runs/jobs/job_succeeded/value.txt").write_text("2 Hartree")
    dispatch("collect", {"root": str(tmp_path), "job_id": "job_succeeded"})
    assert not requirements_evaluation(read_context(tmp_path))["satisfied"]


def test_requirement_cannot_invent_user_quote_or_downgrade_profile(tmp_path, profile):
    workspace(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="requirement_source_quote_mismatch"):
        requirement(tmp_path, profile, source_quote="Skip all calculations")
    operation = requirement(tmp_path, profile)
    with pytest.raises(AgentWorkspaceError, match="requirement_source_has_requirements"):
        change(tmp_path, [{"type": "review_source", "source_ref": operation["source_ref"], "disposition": "no_new_requirements", "reason": "Pretend there was no task"}])
    with pytest.raises(AgentWorkspaceError, match="requirement_minimum_cannot_be_weakened"):
        change(tmp_path, [{"type": "revise_requirement", "requirement_id": "requirement_path", "constraints": {"method": "cheap method"}, "reason": "Reduce scope without a user change"}])
    with pytest.raises(AgentWorkspaceError, match="requirement_minimum_cannot_be_weakened"):
        change(tmp_path, [{"type": "revise_requirement", "requirement_id": "requirement_path", "constraints": {}, "acceptance_profile": {"id": "research.material", "version": "1"}, "reason": "Replace science with a report"}])


def test_weak_gate_and_exemption_cannot_finish_an_unperformed_requirement(tmp_path, profile):
    workspace(tmp_path)
    requirement(tmp_path, profile)
    report = artifact("create", {"root": str(tmp_path), "content": "The report explains why the work was not performed."})
    change(tmp_path, [
        {"type": "create_gate", "id": "gate_report", "scope": "node", "target_id": "node_1", "criteria": [{"id": "limits", "source_type": "agent_assessment"}]},
        {"type": "evaluate_gate", "gate_id": "gate_report", "verdict": "pass", "assessments": [{"criterion_id": "limits", "verdict": "pass", "reason": "Limitations described"}]},
        {"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "completed"},
    ])
    evaluation = assess(tmp_path, evidence_refs=[report["artifact_id"]])
    assert not evaluation["satisfied"] and not evaluation["settled"]
    assert read_liveness(tmp_path)["lifecycle"] == "decision_needed"
    with pytest.raises(AgentWorkspaceError, match="requirements_unsettled"):
        finish(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid"):
        change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_unstarted", "requirement_id": "requirement_path", "category": "execution_failed", "reason": "No candidate was prepared"}])


def test_stage_node_can_complete_but_success_delivery_cannot_consume_unmet_work(tmp_path, profile):
    workspace(tmp_path)
    requirement(tmp_path, profile)
    change(tmp_path, [{"type": "create_node", "id": "node_delivery", "title": "Success report", "objective": "Deliver the study",
                       "consumes": {"requirement_ids": ["requirement_path"]}},
                      {"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "completed"}])
    with pytest.raises(AgentWorkspaceError, match="node_requirements_unmet"):
        change(tmp_path, [{"type": "set_node_state", "node_id": "node_delivery", "state": "closed", "outcome": "completed"}])


def test_real_matching_validators_satisfy_requirement_and_receipt_changes_expire_it(tmp_path, profile):
    workspace(tmp_path)
    spec = input_spec(tmp_path)
    requirement(tmp_path, profile, input_artifact_ids=[spec])
    receipts = [run_validator(tmp_path, "fixture." + name, spec) for name in ("mapping", "saddle", "path")]
    result = assess(tmp_path, receipts)
    assert result["satisfied"] and result["settled"]
    # Existing current results can be reassessed without launching more Jobs.
    assess(tmp_path, receipts, identifier="assessment_reuse")
    assert len(read_context(tmp_path)["attempts"]) == 3
    change(tmp_path, [{"type": "create_node", "id": "node_delivered", "title": "Delivered result", "objective": "Deliver accepted research",
                       "consumes": {"requirement_ids": ["requirement_path"]}},
                      {"type": "set_node_state", "node_id": "node_delivered", "state": "closed", "outcome": "completed"}])
    delivered = next(row for row in read_context(tmp_path)["nodes"] if row["id"] == "node_delivered")
    assert delivered["requirement_consumption"]["requirements"][0]["assessment_id"] == "assessment_reuse"
    output = tmp_path / "runs/jobs/job_fixture_path/validator_result.json"
    value = json.loads(output.read_text())
    value["verdict"] = "fail"
    output.write_text(json.dumps(value))
    dispatch("collect", {"root": str(tmp_path), "job_id": "job_fixture_path"})
    changed = requirements_evaluation(read_context(tmp_path))
    assert changed["requirements"][0]["state"] == "needs_review"
    assert not changed["satisfied"]
    assert next(row for row in read_context(tmp_path)["nodes"] if row["id"] == "node_delivered") == delivered
    with pytest.raises(AgentWorkspaceError, match="requirements_unsettled"):
        finish(tmp_path)


@pytest.mark.parametrize("mismatch", ["method", "subject"])
def test_unrelated_input_or_wrong_method_does_not_satisfy_the_requirement(tmp_path, profile, mismatch):
    workspace(tmp_path)
    spec = input_spec(tmp_path)
    requirement(tmp_path, profile, input_artifact_ids=[spec],
                constraints={"method": "OtherMethod" if mismatch == "method" else "M062X"})
    wrong = spec if mismatch == "method" else input_spec(tmp_path, "OtherMethod")
    receipt = run_validator(tmp_path, "fixture.mapping", wrong)
    result = assess(tmp_path, [receipt])
    assert not result["satisfied"]
    assert all(not check["satisfied"] for check in result["requirements"][0]["checks"])


def test_unrelated_successful_true_job_is_not_validator_evidence(tmp_path, profile):
    workspace(tmp_path)
    requirement(tmp_path, profile, input_artifact_ids=[input_spec(tmp_path)])
    dispatch("start", {"root": str(tmp_path), "job_id": "job_true", "node_id": "node_1", "command": [sys.executable, "-c", "pass"]})
    for _ in range(100):
        if dispatch("status", {"root": str(tmp_path), "job_id": "job_true"})["state"] == "succeeded":
            break
        time.sleep(.01)
    receipt = dispatch("collect", {"root": str(tmp_path), "job_id": "job_true"})["result_receipt"]
    assert not assess(tmp_path, [receipt["receipt_id"]])["satisfied"]


def test_user_cancellation_preserves_unmet_work_and_independent_requirements(tmp_path, profile):
    workspace(tmp_path)
    original = requirement(tmp_path, profile)
    change(tmp_path, [{**original, "id": "requirement_other", "statement": "An independent path"}])
    cancelled = source(tmp_path, "Stop the selected first path; keep working on the other path.", "message_cancel")
    change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_1", "requirement_id": "requirement_path", "category": "user_cancel",
                       "source_ref": cancelled, "source_quote": "Stop the selected first path", "reason": "User cancellation applies to the first path."},
                      {"type": "review_source", "source_ref": cancelled, "disposition": "no_new_requirements", "reason": "Cancellation of existing scope, no added deliverable."}])
    result = requirements_evaluation(read_context(tmp_path))
    assert result["requirements"][0]["state"] == "stopped"
    assert not result["requirements"][0]["satisfied"]
    assert not result["settled"]
    assert any(row.get("requirement_id") == "requirement_other" for row in read_liveness(tmp_path)["research_obligations"])
    change(tmp_path, [{"type": "resume_requirement", "requirement_id": "requirement_path", "reason": "Resume the preserved work after the scoped interruption."}])
    assert requirements_evaluation(read_context(tmp_path))["requirements"][0]["state"] == "unmet"


def test_material_review_accepts_external_literature_without_jobs(tmp_path):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={}, statement="Preserve the supplied literature")
    material = artifact("create", {"root": str(tmp_path), "content": "A user-supplied literature excerpt with a citation."})
    assert assess(tmp_path, evidence_refs=[material["artifact_id"]])["satisfied"]
    assert read_context(tmp_path)["attempts"] == []


def test_actual_failed_execution_can_end_a_run_without_claiming_success(tmp_path, profile):
    workspace(tmp_path)
    requirement(tmp_path, profile)
    dispatch("start", {"root": str(tmp_path), "job_id": "job_failure", "node_id": "node_1",
                       "command": [sys.executable, "-c", "raise SystemExit(23)"]})
    for _ in range(100):
        if dispatch("status", {"root": str(tmp_path), "job_id": "job_failure"})["state"] == "failed":
            break
        time.sleep(.01)
    receipt = dispatch("collect", {"root": str(tmp_path), "job_id": "job_failure"})["result_receipt"]
    with pytest.raises(AgentWorkspaceError, match="requirement_stop_capability_not_proven"):
        change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_capability", "requirement_id": "requirement_path",
                           "category": "capability_unavailable", "result_receipt_refs": [receipt["receipt_id"]],
                           "reason": "An arbitrary command failure does not establish solver unavailability"}])
    change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_failed", "requirement_id": "requirement_path",
                       "category": "execution_failed", "result_receipt_refs": [receipt["receipt_id"]],
                       "reason": "The attempted path failed; retain unmet work for later diagnosis"},
                      {"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "stopped", "summary": "Execution failed"}])
    status = requirements_evaluation(read_context(tmp_path))
    assert status["settled"] and not status["satisfied"]
    finish(tmp_path)
    assert read_liveness(tmp_path)["unmet_requirement_ids"] == ["requirement_path"]


def test_host_can_record_new_input_while_blocked_without_resuming_effects(tmp_path):
    workspace(tmp_path)
    checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_blocked", "disposition": "blocked", "reason": "Wait for missing experimental material"}})
    ref = source(tmp_path, "Here is an update about the missing input.")
    state = read_context(tmp_path)
    assert state["requirement_sources"][0]["source_ref"] == ref
    assert read_liveness(tmp_path)["lifecycle"] == "blocked"


def test_adding_an_input_scope_expires_prior_acceptance_but_preserves_history(tmp_path):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={})
    first = artifact("create", {"root": str(tmp_path), "content": "First reference"})
    assert assess(tmp_path, evidence_refs=[first["artifact_id"]])["satisfied"]
    change(tmp_path, [{"type": "create_node", "id": "node_delivered", "title": "Delivered materials", "objective": "Share accepted materials",
                       "consumes": {"requirement_ids": ["requirement_path"]}},
                      {"type": "set_node_state", "node_id": "node_delivered", "state": "closed", "outcome": "completed"}])
    delivered = next(row for row in read_context(tmp_path)["nodes"] if row["id"] == "node_delivered")
    previous = read_context(tmp_path)["requirements"][0]["assessments"][0]
    second = artifact("create", {"root": str(tmp_path), "content": "Additional reference"})
    change(tmp_path, [{"type": "bind_requirement", "requirement_id": "requirement_path", "input_artifact_ids": [second["artifact_id"]],
                       "reason": "Include an additional supplied source in the scope"}])
    state = read_context(tmp_path)
    assert requirements_evaluation(state)["requirements"][0]["state"] == "needs_review"
    assert state["requirements"][0]["assessments"][0] == previous
    assert next(row for row in state["nodes"] if row["id"] == "node_delivered") == delivered
    assert delivered["requirement_consumption"]["requirements"][0]["version"] == 1
    from research_state.invariants import validate_context
    assert validate_context(state)["valid"]
    change(tmp_path, [{"type": "create_node", "id": "node_next_delivery", "title": "Additional materials", "objective": "Deliver the expanded scope",
                       "consumes": {"requirement_ids": ["requirement_path"]}}])
    with pytest.raises(AgentWorkspaceError, match="node_requirements_unmet"):
        change(tmp_path, [{"type": "set_node_state", "node_id": "node_next_delivery", "state": "closed", "outcome": "completed"}])
    assert assess(tmp_path, identifier="assessment_expanded", evidence_refs=[first["artifact_id"], second["artifact_id"]])["satisfied"]
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_next_delivery", "state": "closed", "outcome": "completed"}])
    current = next(row for row in read_context(tmp_path)["nodes"] if row["id"] == "node_next_delivery")
    assert current["requirement_consumption"]["requirements"][0]["version"] == 2


@pytest.mark.parametrize("new_work", ["attempt", "node"])
def test_stop_expires_when_its_execution_scope_changes(tmp_path, profile, new_work):
    workspace(tmp_path)
    requirement(tmp_path, profile)
    cancelled = source(tmp_path, "Cancel this path for now.", message_id="message_cancel")
    change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_path", "requirement_id": "requirement_path",
                       "category": "user_cancel", "source_ref": cancelled, "source_quote": "Cancel this path for now.",
                       "reason": "The user stopped this bounded path"},
                      {"type": "review_source", "source_ref": cancelled, "disposition": "no_new_requirements",
                       "reason": "The cancellation is applied to the existing requirement"}])
    before = read_context(tmp_path)["requirements"][0]["stops"][0]
    assert requirements_evaluation(read_context(tmp_path))["settled"]
    if new_work == "attempt":
        dispatch("start", {"root": str(tmp_path), "job_id": "job_retry", "node_id": "node_1", "command": ["true"]})
        for _ in range(100):
            if dispatch("status", {"root": str(tmp_path), "job_id": "job_retry"})["state"] == "succeeded":
                break
            time.sleep(.01)
        dispatch("collect", {"root": str(tmp_path), "job_id": "job_retry"})
    else:
        change(tmp_path, [{"type": "create_node", "id": "node_retry", "title": "Another path", "objective": "Continue research"},
                          {"type": "bind_requirement", "requirement_id": "requirement_path", "node_ids": ["node_retry"], "reason": "Add a new attempt route"}])
    state = read_context(tmp_path)
    status = requirements_evaluation(state)
    assert status["requirements"][0]["state"] == "needs_review"
    assert not status["settled"]
    assert state["requirements"][0]["stops"][0] == before
    with pytest.raises(AgentWorkspaceError, match="requirements_unsettled"):
        finish(tmp_path)


@pytest.mark.parametrize("platforms", [["local", "local"], ["local", "remote"]])
def test_platform_constraint_checks_every_scientific_producer(tmp_path, profile, platforms):
    workspace(tmp_path)
    manifest = tmp_path / "installed-package/extensions/fixture/manifest.json"
    descriptor = json.loads(manifest.read_text())
    pair = {**descriptor["validators"][0], "id": "fixture.pair", "input_contract": {
        "schema_version": "validator-input/1", "roles": [
            {"name": "spec", "source": "registered_artifact", "schema_version": "fixture-spec/1"},
            {"name": "first", "source": "collected_output"},
            {"name": "second", "source": "collected_output"}]}}
    descriptor["validators"].append(pair)
    descriptor["acceptance_profiles"][0]["checks"] = [{"id": "pair", "kind": "validator_result", "validator_id": "fixture.pair", "validator_version": "1"}]
    manifest.write_text(json.dumps(descriptor))
    spec = input_spec(tmp_path)
    requirement(tmp_path, profile, input_artifact_ids=[spec], constraints={"method": "M062X", "platform": "local"})
    outputs, attempts = [], []
    for index in range(2):
        job_id = "job_producer_" + str(index)
        started = dispatch("start", {"root": str(tmp_path), "job_id": job_id, "node_id": "node_1",
            "command": [sys.executable, "-c", "from pathlib import Path; Path('output.txt').write_text('observation " + str(index) + "')"],
            "outputs": [{"path": "output.txt", "required": True}]})
        for _ in range(100):
            if dispatch("status", {"root": str(tmp_path), "job_id": job_id})["state"] == "succeeded":
                break
            time.sleep(.01)
        result = dispatch("collect", {"root": str(tmp_path), "job_id": job_id})
        outputs.append(result["artifacts"][0]["artifact_id"])
        attempts.append(started["attempt_id"])
    # Simulate platform observations in State; no remote process is launched.
    path = tmp_path / "research_map/context.json"
    state = json.loads(path.read_text())
    for ref, platform in zip(attempts, platforms):
        next(row for row in state["attempts"] if row["id"] == ref)["environment"] = platform
    path.write_text(json.dumps(state))
    receipt = run_validator(tmp_path, "fixture.pair", spec, additional_inputs=outputs)
    evaluation = assess(tmp_path, [receipt])
    assert evaluation["satisfied"] == all(platform == "local" for platform in platforms)


def test_platform_constraint_cannot_be_proved_by_imported_material_alone(tmp_path):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={"platform": "local"})
    material = artifact("create", {"root": str(tmp_path), "content": "A report saying local was used"})
    result = assess(tmp_path, evidence_refs=[material["artifact_id"]])
    assert not result["satisfied"]
    assert result["requirements"][0]["checks"][-1]["id"] == "execution_platform"
