"""Validate prepared environment evidence at the managed submission boundary."""
import os

from research_agent.jobs.config_contract import SUBMISSION_FIELDS, binding_digest, load_job_config, resolve_binding
from research_agent.jobs.environment import guarded_command, probe_binding


def check_configuration(params):
    """Cheap submission recheck; never invokes a target or extension subprocess."""
    metadata = params.get("metadata") or {}
    selected = metadata.get("execution_binding")
    evidence_fields = {"execution_environment", "execution_argv", "python_binding", "executor", "script"}
    if selected is None:
        if evidence_fields & metadata.keys():
            raise ValueError("execution_binding_required")
        return
    settings = load_job_config(os.environ["RESEARCH_AGENT_JOB_CONFIG"])
    expected = resolve_binding(settings, selected["environment"], selected["backend"], runtime=selected["runtime"])
    if selected != expected or metadata.get("configuration_sha256") != binding_digest(expected):
        raise ValueError("execution_binding_changed: prepare again with the current configuration")
    if params.get("platform") != selected["environment"]:
        raise ValueError("execution_binding_platform_mismatch")
    if (params.get("environment", {}) != selected["binding"].get("environment", {}) or "env" in params
            or metadata.get("python_binding") != selected["python"]):
        raise ValueError("execution_binding_override_forbidden")
    if {key: value for key, value in metadata.items() if key in SUBMISSION_FIELDS} != selected["submission"]:
        raise ValueError("execution_binding_submission_mismatch")
    return settings, selected


def check_binding(params, *, probe):
    configured = check_configuration(params)
    if configured is None:
        return
    settings, selected = configured
    metadata = params['metadata']
    if sum(bool(metadata.get(key)) for key in ('executor', 'validator', 'script')) != 1:
        raise ValueError('execution_entry_identity_required')
    argv = metadata.get("execution_argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise ValueError("execution_argv_invalid")
    requirements = {}
    module_paths = None
    if metadata.get("executor"):
        from .executors import registered_executor, validate_prepared_entry
        identity = metadata["executor"]
        _, descriptor = registered_executor(identity["id"], identity["version"])
        if descriptor["backend"] != selected["backend"] or descriptor["runtime"] != selected["runtime"]:
            raise ValueError("executor_binding_mismatch")
        requirements = descriptor.get("requirements", {})
        module_paths = descriptor.get('module_paths')
        validate_prepared_entry(params, descriptor)
    elif metadata.get("validator"):
        from research_agent.application.execution_catalog import registered_entry
        identity = metadata["validator"]
        _, descriptor = registered_entry("validators", identity["id"], identity["version"])
        if descriptor["backend"] != selected["backend"] or selected["runtime"] != "python":
            raise ValueError("validator_binding_mismatch")
        requirements = descriptor.get("requirements", {})
        module_paths = descriptor.get('module_paths')
    elif metadata.get('script'):
        script = metadata['script']
        if argv[0] != script.get('entry') or not any(row.get('destination') == script.get('entry') and
                'sha256:' + row.get('sha256', '') == script.get('sha256') for row in params.get('inputs', []) if isinstance(row, dict)):
            raise ValueError('execution_script_mismatch')
    snapshot = metadata.get("execution_environment")
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != "job-environment/1"
            or snapshot.get("requirements") != requirements
            or snapshot.get("sha256") != binding_digest(snapshot.get("observation"))):
        raise ValueError("execution_environment_evidence_invalid")
    if metadata.get('module_paths') != module_paths:
        raise ValueError('execution_module_paths_mismatch')
    command, guard_inputs = guarded_command(selected, argv, snapshot, module_paths=module_paths)
    if params.get("command") != command:
        raise ValueError("execution_guard_required: use the prepared command without edits")
    for required in guard_inputs:
        # CLI preparation may load the installed wheel while the Worker loads
        # the same release's source entrypoint. Guard identity is its staged
        # destination and bytes, not the host-side location of that copy.
        # Job staging checks the declared digest before executing the guard.
        if not any(isinstance(row, dict) and row.get("destination") == required["destination"]
                   and row.get("sha256") == required["sha256"] for row in params.get("inputs", [])):
            raise ValueError("execution_guard_input_missing")
    if probe:
        observed = probe_binding(settings, selected, requirements)
        if observed != snapshot:
            def differences(left, right, prefix=''):
                if isinstance(left, dict) and isinstance(right, dict):
                    return [path for key in sorted(left.keys() | right.keys())
                            for path in differences(left.get(key), right.get(key), prefix + '.' + key)]
                return [prefix.lstrip('.')] if left != right else []
            # Field names identify drift without exposing environment values.
            raise ValueError('execution_environment_changed: ' + ','.join(differences(snapshot, observed)))
