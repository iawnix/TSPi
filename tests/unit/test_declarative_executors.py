"""Installed external executors use generic preparation and ordinary Jobs."""
import hashlib
import json
from pathlib import Path
import time

import pytest

from research_agent.application.api import execute
from research_agent.application.executors import prepare, prepare_script
from research_agent.application.memory_context import read
from research_agent.artifacts.registry import manifests
from research_agent.application.job_state import execution
from tests.unit.test_job_recovery import workspace


def catalog(root, monkeypatch):
    root.mkdir()
    (root / "run.sh").write_text('cat "$1" > result.txt\n')
    resources = {"run.sh": "sha256:" + hashlib.sha256((root / "run.sh").read_bytes()).hexdigest()}
    declaration = {"schema_version": "research-agent-execution/1", "name": "external", "version": "1",
        "executors": [{"id": "external.copy", "version": "3", "backend": "shell",
            "runtime": "native", "argv": ["{command}", "run.sh", "{input:data}", "{args}"],
            "inputs": {"data": "input.txt"}, "outputs": [{"path": "result.txt", "required": True, "min_bytes": 1}],
            "resources": resources}], "validators": [], "acceptance_profiles": []}
    declaration_path = root / "execution.json"
    declaration_path.write_text(json.dumps(declaration))
    (root / "package.json").write_text(json.dumps({"researchAgent": {"execution": ["execution.json"]}}))
    monkeypatch.setenv("RESEARCH_AGENT_PACKAGE_ROOT", str(root))
    return declaration_path


def binding(path):
    text = '''default_environment="local"
[environments.local]
kind="local"
supervisor="process"
[environments.local.backends.shell]
command="/bin/sh"
'''
    path.write_text(text)
    return text


def test_external_native_executor_runs_without_core_changes_or_python_binding(tmp_path, monkeypatch):
    catalog(tmp_path / "catalog", monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace(root)
    config = tmp_path / "job.toml"
    binding(config)
    source = root / "data.txt"
    source.write_text("externally declared result\n")
    request = prepare(config, "local", "external.copy", "3", {"data": source})
    assert request["metadata"]["execution_argv"] == ["/bin/sh", "run.sh", "input.txt"]
    assert "python_binding" not in request["metadata"]
    assert not list((root/"operations/executions").glob("*.json"))
    path = root / "request.json"
    path.write_text(json.dumps(request))
    receipt = execute("job.start", root, {"request_file": str(path),
        "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for _ in range(200):
        status = execute("job.status", root, {"job_id": receipt["job_id"]})
        if status["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.01)
    assert status["state"] == "succeeded"
    collected = execute("job.collect", root, {"job_id": receipt["job_id"]})
    assert collected["output_validation"]["complete"]
    assert (Path(receipt["cwd"]) / "result.txt").read_text() == source.read_text()
    assert execution(root, receipt["job_id"])["metadata"]["executor"] == {"id": "external.copy", "version": "3"}


def test_only_selected_binding_and_actual_input_content_change_work_identity(tmp_path, monkeypatch):
    catalog(tmp_path / "catalog", monkeypatch)
    config = tmp_path / "job.toml"
    original = binding(config)
    source = tmp_path / "data.txt"
    source.write_text("one")
    def request():
        return prepare(config, "local", "external.copy", "3", {"data": source})
    first = request()
    config.write_text(original + '\n[environments.other]\nkind="local"\n[environments.other.backends.other]\ncommand="/unrelated"\n')
    assert request() == first
    config.write_text(original.replace('/bin/sh', '/bin/bash'))
    assert request()["work_id"] != first["work_id"]
    config.write_text(original)
    source.write_text("two")
    assert request()["work_id"] != first["work_id"]


def test_previously_loaded_catalog_does_not_authorize_changed_executor_resources(tmp_path, monkeypatch):
    catalog(tmp_path / "catalog", monkeypatch)
    from research_agent.application.execution_catalog import installed_catalogs
    installed_catalogs()
    config = tmp_path / "job.toml"
    binding(config)
    source = tmp_path / "data.txt"
    source.write_text("input")
    (tmp_path / "catalog/run.sh").write_text("exit 23\n")
    with pytest.raises(ValueError, match="execution_resource_changed"):
        prepare(config, "local", "external.copy", "3", {"data": source})


def test_unregistered_version_or_undeclared_input_cannot_prepare(tmp_path, monkeypatch):
    catalog(tmp_path / "catalog", monkeypatch)
    config = tmp_path / "job.toml"
    binding(config)
    with pytest.raises(ValueError, match="executors_not_registered"):
        prepare(config, "local", "external.copy", "4", {})
    with pytest.raises(ValueError, match="executor_inputs_invalid"):
        prepare(config, "local", "external.copy", "3", {})


def test_prepared_native_entry_cannot_replace_its_bound_executable(tmp_path, monkeypatch):
    from research_agent.jobs.environment import guarded_command
    from research_agent.application.execution_environment import check_binding
    catalog(tmp_path / 'catalog', monkeypatch)
    config = tmp_path / 'job.toml'
    binding(config)
    source = tmp_path / 'input.txt'; source.write_text('input')
    request = prepare(config, 'local', 'external.copy', '3', {'data': source})
    metadata = request['metadata']
    metadata['execution_argv'][0] = '/bin/false'
    request['command'], _ = guarded_command(metadata['execution_binding'], metadata['execution_argv'], metadata['execution_environment'])
    with pytest.raises(ValueError, match='executor_command_mismatch'):
        check_binding(request, probe=False)


def test_task_specific_script_uses_explicit_binding_and_pinned_dependencies(tmp_path, monkeypatch):
    import os
    script = tmp_path / "analysis.py"
    script.write_text("from pathlib import Path\nPath('output.txt').write_text(Path('input.txt').read_text().upper())\n")
    source = tmp_path / "data.txt"
    source.write_text("new research method")
    request = prepare_script(os.environ["RESEARCH_AGENT_JOB_CONFIG"], "local", "validation", script,
                             dependencies=[str(source) + "=input.txt"], collect=["output.txt"])
    assert request["metadata"]["execution_binding"]["backend"] == "validation"
    assert "executor" not in request["metadata"]
    assert request["metadata"]["script"]["sha256"] == "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()
    root = tmp_path / "workspace"
    root.mkdir()
    workspace(root)
    path = root / "request.json"
    path.write_text(json.dumps(request))
    receipt = execute("job.start", root, {"request_file": str(path),
        "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for _ in range(200):
        status = execute("job.status", root, {"job_id": receipt["job_id"]})
        if status["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.01)
    assert status["state"] == "succeeded"
    assert (Path(receipt["cwd"]) / "output.txt").read_text() == "NEW RESEARCH METHOD"
    assert execute("job.collect", root, {"job_id": receipt["job_id"]})["output_validation"]["complete"]


def test_validator_on_remote_default_uses_remote_python_and_selected_resources(tmp_path, monkeypatch, mock_environment_probe):
    from research_agent.application.validators import prepare as prepare_validator
    from research_agent.application.evidence import dispatch as evidence
    workspace(tmp_path)
    root = tmp_path / "catalog"
    root.mkdir()
    script = root / "validator.py"
    script.write_text("raise RuntimeError('preparation never executes validators')\n")
    manifest = root / "execution.json"
    manifest.write_text(json.dumps({"schema_version": "research-agent-execution/1", "name": "external", "version": "1", "executors": [], "acceptance_profiles": [],
        "validators": [{"id": "external.validator", "version": "1", "backend": "validation", "entry": "validator.py",
            "sha256": "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest(),
            "input_contract": {"schema_version": "validator-input/1", "roles": [{"name": "input", "source": "registered_artifact"}]}}]}))
    (root / "package.json").write_text(json.dumps({"researchAgent": {"execution": ["execution.json"]}}))
    monkeypatch.setenv("RESEARCH_AGENT_PACKAGE_ROOT", str(root))
    config = tmp_path / "job.toml"
    config.write_text('''default_environment="cluster"
[environments.cluster]
kind="remote"
ssh_host="fixture"
remote_root="/scratch/jobs"
[environments.cluster.submission]
queue="science"
[environments.cluster.submission.resources]
cpus=3
[environments.cluster.backends.validation]
[environments.cluster.backends.validation.python]
manager="conda"
conda_executable="/cluster/conda/bin/conda"
prefix="/cluster/validation"
lock_ref="/cluster/validation.lock"
[environments.local]
kind="local"
supervisor="process"
''')
    artifact = evidence("create", {"root": str(tmp_path), "content": "registered input"})
    params = {"validator_id": "external.validator", "validator_version": "1", "input_artifact_ids": [artifact["artifact_id"]]}
    request = prepare_validator(tmp_path, params)
    assert request["platform"] == "cluster"
    assert "/cluster/conda/bin/conda" in request["command"]
    assert "/cluster/validation" in request["command"]
    assert request["metadata"]["resources"] == {"cpus": 3}
    assert request["metadata"]["queue"] == "science"
    with pytest.raises(ValueError, match="executor_binding_missing"):
        prepare_validator(tmp_path, {**params, "platform": "local"})


@pytest.mark.parametrize("kind", ["seed", "path-candidates"])
def test_structure_generation_collects_every_output_with_binding_and_attempt(tmp_path, kind):
    import os
    from tests.unit.test_chemical_path_execution import SPEC
    from research_agent.application.evidence import dispatch as evidence
    workspace(tmp_path)
    inputs, refs = {}, []
    if kind == "seed":
        arguments = ["--smiles", "O", "--charge", "0", "--multiplicity", "1"]
        expected = "results/seeds/seed-1.xyz"
    else:
        spec = tmp_path / "input.json"
        spec.write_text(json.dumps(SPEC))
        registered = evidence("register", {"root": str(tmp_path), "path": str(spec)})
        inputs, refs = {"spec": spec}, [registered["artifact_id"]]
        arguments = ["--enumerate-stereo", "--conformers", "1"]
        expected = "results/candidate-1-1/ts.gjf"
    request = prepare(os.environ["RESEARCH_AGENT_JOB_CONFIG"], "local", "chemical." + kind, "1", inputs, arguments, input_artifact_ids=refs)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    receipt = execute("job.start", tmp_path, {"request_file": str(path),
        "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for _ in range(400):
        status = execute("job.status", tmp_path, {"job_id": receipt["job_id"]})
        if status["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.01)
    assert status["state"] == "succeeded", (Path(receipt["cwd"]) / "logs/stderr.log").read_text()
    collected = execute("job.collect", tmp_path, {"job_id": receipt["job_id"]})
    assert collected["output_validation"]["complete"]
    artifact = next(row for row in collected["artifacts"] if row["provenance"]["source_path"].endswith(expected))
    assert artifact["provenance"]["job_id"] == receipt["job_id"]
    state = {"artifacts": list(manifests(tmp_path))}
    row = next(row for row in state["artifacts"] if row["artifact_id"] == artifact["artifact_id"])
    assert row["input_artifact_ids"] == refs
    assert execution(tmp_path, receipt["job_id"])["metadata"]["execution_binding"]["backend"] == "structure"


def test_recursive_collection_rejects_escape_and_empty_required_directory(tmp_path):
    from research_agent.jobs.outputs import collect_outputs
    root = tmp_path / "job"
    (root / "results").mkdir(parents=True)
    declaration = [{"path": "results", "recursive": True, "required": True}]
    _, validation = collect_outputs(root, declaration)
    assert not validation["complete"]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (root / "results/link.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="output escapes job cwd"):
        collect_outputs(root, declaration)


def test_one_executor_resolves_explicit_local_and_remote_targets(tmp_path, monkeypatch):
    from research_agent.jobs.config_contract import binding_digest
    def probe(settings, selected, requirements):
        command = selected['binding']['command']
        observation = {'files': {'executable': {'path': command if isinstance(command, str) else command[0], 'sha256': 'sha256:' + 'a' * 64}}}
        return {'schema_version': 'job-environment/1', 'requirements': requirements,
                'observation': observation, 'sha256': binding_digest(observation)}
    monkeypatch.setattr('research_agent.application.executors.probe_binding', probe)
    catalog(tmp_path / 'catalog', monkeypatch)
    config = tmp_path / 'job.toml'
    config.write_text('''default_environment="local"
[environments.local]
kind="local"
supervisor="process"
[environments.local.backends.shell]
command="/bin/sh"
[environments.cluster]
kind="remote"
ssh_host="fixture"
remote_root="/scratch/jobs"
[environments.cluster.submission]
queue="science"
[environments.cluster.backends.shell]
command="/cluster/bin/sh"
[environments.empty]
kind="local"
supervisor="process"
''')
    source = tmp_path / 'input.txt'
    source.write_text('same scientific input')
    local = prepare(config, 'local', 'external.copy', '3', {'data': source})
    remote = prepare(config, 'cluster', 'external.copy', '3', {'data': source})
    assert local['metadata']['executor'] == remote['metadata']['executor']
    assert local['metadata']['resources_sha256'] == remote['metadata']['resources_sha256']
    assert local['metadata']['execution_argv'][0] == '/bin/sh'
    assert remote['metadata']['execution_argv'][0] == '/cluster/bin/sh'
    assert remote['metadata']['queue'] == 'science'
    assert remote['platform'] == 'cluster' and local['platform'] == 'local'
    assert remote['work_id'] != local['work_id']
    with pytest.raises(ValueError, match='executor_binding_missing'):
        prepare(config, 'empty', 'external.copy', '3', {'data': source})


def test_readiness_distinguishes_shared_backend_configuration_from_verification(tmp_path, monkeypatch):
    from research_agent.application.execution_catalog import installed_catalogs
    from research_agent.application.environment_check import check_environments
    from research_agent.jobs.config_contract import load_job_config
    import copy
    path = catalog(tmp_path / 'catalog', monkeypatch)
    declaration = json.loads(path.read_text())
    second = copy.deepcopy(declaration['executors'][0])
    second['id'] = 'external.other'
    declaration['executors'].append(second)
    path.write_text(json.dumps(declaration))
    config = tmp_path / 'job.toml'
    config.write_text(binding(config) + '\n[environments.empty]\nkind="local"\n')
    monkeypatch.setattr('research_agent.application.environment_check.probe_binding',
                        lambda *args: pytest.fail('configuration-only check must not contact a target'))
    result = check_environments(load_job_config(config), catalogs=installed_catalogs(), probe=False)
    assert len(result['local']) == 2
    assert all(row['status'] == 'configuration_validated' for row in result['local'].values())
    assert all(row['environment_evidence'] is None for row in result['local'].values())
    assert all(row['status'] == 'not_configured' for row in result['empty'].values())
