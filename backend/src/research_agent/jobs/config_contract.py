"""Public, standard-library-only contract for installation execution bindings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib

NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
QUEUE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}"
TIMEOUT_LIMITS = {"connect_timeout_seconds": 300, "command_timeout_seconds": 3600,
                  "transfer_timeout_seconds": 86400}
REMOTE_FIELDS = {"ssh_host", "ssh_config", "scheduler", "remote_root", "allowed_queues", "commands", *TIMEOUT_LIMITS}
TARGET_FIELDS = {"kind", "supervisor", "python", "backends", "submission", *REMOTE_FIELDS}
BACKEND_FIELDS = {"command", "python", "activation_script", "environment", "submission", "allowed_queues", "scratch_root"}


def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"{label} contains unsupported fields; use the current job.toml contract")


def _absolute(value, label):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or any(char in value for char in '\n\r\0') or '..' in Path(value).parts):
        raise ValueError(f"{label} must be an absolute target path without traversal")


def _queues(value, label):
    if (not isinstance(value, list) or len(value) != len(set(value))
            or any(not isinstance(q, str) or not re.fullmatch(QUEUE_PATTERN, q) for q in value)):
        raise ValueError(f"{label} must be an array of unique queue names")


def validate_remote(target, label):
    if target.get('scheduler', 'torque') not in {'torque', 'pbs'}:
        raise ValueError(f"{label}.scheduler must be torque or pbs")
    host = target.get('ssh_host')
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', host):
        raise ValueError(f"{label}.ssh_host is invalid")
    _absolute(target.get('remote_root'), label + '.remote_root')
    if 'ssh_config' in target:
        _absolute(target['ssh_config'], label + '.ssh_config')
    for key, maximum in TIMEOUT_LIMITS.items():
        if key in target and (type(target[key]) is not int or not 1 <= target[key] <= maximum):
            raise ValueError(f"{label}.{key} must be between 1 and {maximum}")
    commands = target.get('commands', {})
    _keys(commands, {'qsub', 'qstat', 'qdel', 'checkjob'}, label + '.commands')
    for name, command in commands.items():
        if not isinstance(command, str) or not command or any(c.isspace() or c == '\0' for c in command):
            raise ValueError(f"{label}.commands.{name} must name one executable")


def validate_python(binding, label="python"):
    if not isinstance(binding, dict) or set(binding) != {"manager", "conda_executable", "prefix", "lock_ref"}:
        raise ValueError(f"{label} requires manager, conda_executable, prefix and lock_ref; migrate legacy Python strings")
    if binding["manager"] != "conda":
        raise ValueError(f"{label}.manager must be conda")
    for field in ("conda_executable", "prefix", "lock_ref"):
        _absolute(binding[field], f"{label}.{field}")
    if not isinstance(binding["lock_ref"], str) or not binding["lock_ref"].strip():
        raise ValueError(f"{label}.lock_ref must identify the installed dependency lock")
    return binding


def validate_job_config(value):
    _keys(value, {"default_environment", "environments"}, "job config")
    environments = value.get("environments")
    if not isinstance(environments, dict) or not environments or value.get("default_environment") not in environments:
        raise ValueError("job config must define default_environment and at least one environment")
    for name, target in environments.items():
        if not re.fullmatch(NAME_PATTERN, name):
            raise ValueError(f"invalid job environment name: {name!r}")
        if not isinstance(target, dict) or target.get("kind") not in {"local", "remote"}:
            raise ValueError(f"job environment {name!r} must declare kind=local or kind=remote")
        _keys(target, TARGET_FIELDS, f"environments.{name}")
        if 'supervisor' in target and (target['kind'] != 'local' or target['supervisor'] not in {'process', 'systemd'}):
            raise ValueError('local supervisor must be process or systemd')
        if target['kind'] == 'remote':
            validate_remote(target, f"environments.{name}")
        elif set(target) & REMOTE_FIELDS:
            raise ValueError(f"environments.{name}: remote fields are invalid on a local target")
        if 'allowed_queues' in target:
            _queues(target['allowed_queues'], f"environments.{name}.allowed_queues")
        if "python" in target:
            validate_python(target["python"], f"environments.{name}.python")
        backends = target.get("backends", {})
        if not isinstance(backends, dict):
            raise ValueError(f"environments.{name}.backends must be a table")
        for backend, binding in backends.items():
            if not re.fullmatch(NAME_PATTERN, backend):
                raise ValueError(f"invalid backend name: {backend}")
            if not isinstance(binding, dict):
                raise ValueError(f"invalid backend binding: {backend}")
            _keys(binding, BACKEND_FIELDS, f"backend {backend}")
            if 'allowed_queues' in binding:
                _queues(binding['allowed_queues'], f"backend {backend}.allowed_queues")
                if target.get('allowed_queues') and set(binding['allowed_queues']) - set(target['allowed_queues']):
                    raise ValueError(f"backend {backend} queues exceed target allowed_queues")
            env = binding.get('environment', {})
            if not isinstance(env, dict) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
                    or not isinstance(item, str) or '\0' in item for key, item in env.items()):
                raise ValueError(f"backend {backend}.environment is invalid")
            if "python" in binding:
                validate_python(binding["python"], f"environments.{name}.backends.{backend}.python")
            command = binding.get("command")
            if command is not None:
                argv = [command] if isinstance(command, str) else command
                if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x.strip() for x in argv):
                    raise ValueError(f"backend {backend}.command must be a nonempty string or argv")
            elif "python" not in binding and "python" not in target:
                raise ValueError(f"backend {backend} requires command or an explicit python binding")
            for field in ('activation_script', 'scratch_root'):
                if field in binding:
                    _absolute(binding[field], f"backend {backend}.{field}")
        if "submission" in target:
            resolve_submission(value, name, require_queue=False)
        for backend, binding in backends.items():
            if "submission" in binding:
                resolve_submission(value, name, backend, require_queue=False)
    return value


def load_job_config(path):
    with Path(path).expanduser().open("rb") as handle:
        return validate_job_config(tomllib.load(handle))


def resolve_python(config, environment, backend):
    target = config["environments"][environment]
    binding = target.get("backends", {}).get(backend, {}).get("python", target.get("python"))
    if binding is None:
        raise ValueError(f"python_binding_missing: configure environments.{environment}.python or backends.{backend}.python as a Conda environment")
    return validate_python(binding)


def python_command(binding):
    validate_python(binding)
    # env -u applies before Conda itself; inherited host PYTHONPATH must not
    # contaminate either Conda or the selected target interpreter.
    return ["env", "-u", "PYTHONHOME", "-u", "PYTHONPATH", "PYTHONNOUSERSITE=1",
            binding["conda_executable"], "run", "--no-capture-output", "-p", binding["prefix"], "python"]


def binding_digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_binding(config, environment, backend, *, runtime):
    """Select only the configuration that can affect this execution."""
    if runtime not in {"python", "native"}:
        raise ValueError("execution_runtime_invalid")
    if environment not in config["environments"]:
        raise ValueError("execution_environment_not_configured")
    target = config["environments"][environment]
    binding = target.get("backends", {}).get(backend)
    if binding is None:
        raise ValueError("executor_binding_missing: configure the selected environment backend " + str(backend))
    python = resolve_python(config, environment, backend) if runtime == "python" else None
    return {"environment": environment, "kind": target["kind"], "backend": backend,
            "runtime": runtime, "binding": binding, "python": python,
            "submission": resolve_submission(config, environment, backend),
            **({"supervisor": target.get("supervisor", "systemd")} if target["kind"] == "local" else {}),
            **{key: target[key] for key in ("ssh_host", "remote_root") if key in target}}


SUBMISSION_FIELDS = {"queue", "resources", "queue_wait_seconds"}


def resolve_submission(config, environment, backend=None, *, require_queue=True, requested=None):
    """Merge installation resource defaults; queue allowlists are permissions, not defaults."""
    target = config["environments"][environment]
    binding = target.get("backends", {}).get(backend, {})
    base = target.get("submission", {})
    override = binding.get("submission", {})
    result = {"resources": {}}
    for settings in (base, override, {} if requested is None else requested):
        validate_submission(settings, kind=target['kind'], scheduler=target.get('scheduler', 'torque'), require_queue=False)
        result = {**result, **settings, "resources": {**result['resources'], **settings.get('resources', {})}}
    return validate_submission(result, kind=target['kind'], scheduler=target.get('scheduler', 'torque'),
                               require_queue=require_queue,
                               allowed_queues=(target.get('allowed_queues', []), binding.get('allowed_queues', [])))


def validate_submission(result, *, kind, scheduler='torque', require_queue=True, allowed_queues=()):
    """Validate resolved resources; platform adapters never merge defaults."""
    _keys(result, SUBMISSION_FIELDS, "submission")
    if "queue_wait_seconds" in result and (type(result["queue_wait_seconds"]) is not int or result["queue_wait_seconds"] < 1):
        raise ValueError("queue_wait_seconds must be positive")
    queue = result.get("queue")
    if require_queue and kind == "remote" and not queue:
        raise ValueError("queue_binding_missing: configure submission.queue; allowed_queues does not select a queue")
    if "queue" in result and (not isinstance(queue, str) or not re.fullmatch(QUEUE_PATTERN, queue)):
        raise ValueError("submission.queue is invalid")
    if kind == 'local' and {'queue', 'queue_wait_seconds'} & result.keys():
        raise ValueError('local submission does not support a scheduler queue')
    for allowed in allowed_queues:
        if queue and allowed and queue not in allowed:
            raise ValueError("submission queue is not allowed")
    resources = result.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("submission.resources must be a table")
    if set(resources) - {"cpus", "memory_mb", "walltime", "select"}:
        raise ValueError("unsupported submission resource")
    if "select" in resources and (not isinstance(resources['select'], str)
            or not re.fullmatch(r'[A-Za-z0-9_=:+.-]+', resources['select'])):
        raise ValueError("submission.resources.select is invalid")
    if 'select' in resources:
        if kind != 'remote' or scheduler != 'pbs':
            raise ValueError('submission.resources.select requires a PBS target')
        if {'cpus', 'memory_mb'} & resources.keys():
            raise ValueError('use PBS select or cpus/memory_mb, not both')
    for field in ("cpus", "memory_mb"):
        if field in resources and (type(resources[field]) is not int or resources[field] < 1):
            raise ValueError("submission.resources." + field + " must be positive")
    if "walltime" in resources:
        walltime_seconds(resources["walltime"])
    return result


def walltime_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+:[0-5][0-9]:[0-5][0-9]", value):
        raise ValueError("submission.resources.walltime must be HH:MM:SS")
    hours, minutes, seconds = map(int, value.split(':'))
    total = hours * 3600 + minutes * 60 + seconds
    if not total:
        raise ValueError("submission.resources.walltime must be positive")
    return total


def execution_timeout(timeout, resources):
    """One effective process limit, whether the target is local or remote."""
    if 'walltime' not in resources:
        return timeout
    walltime = walltime_seconds(resources['walltime'])
    return min(timeout, walltime) if timeout is not None else walltime


def job_config_schema():
    """Generate the public editor schema from the runtime's field vocabulary."""
    def record(properties, required=()):
        return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}
    def text(pattern=None):
        return {'type': 'string', 'minLength': 1, **({'pattern': pattern} if pattern else {})}
    def integer(maximum=None):
        return {'type': 'integer', 'minimum': 1, **({'maximum': maximum} if maximum else {})}
    absolute = text(r'^/(?!$)(?!.*(?:^|/)\.\.(?:/|$))[^\n\r\u0000]+$')
    queues = {'type': 'array', 'uniqueItems': True, 'items': text('^' + QUEUE_PATTERN + '$')}
    python = record({'manager': {'const': 'conda'}, **{key: absolute for key in ('conda_executable', 'prefix', 'lock_ref')}},
                    ('manager', 'conda_executable', 'prefix', 'lock_ref'))
    resources = record({'cpus': integer(), 'memory_mb': integer(),
                        'walltime': text(r'^(?!0+:00:00$)[0-9]+:[0-5][0-9]:[0-5][0-9]$'), 'select': text(r'^[A-Za-z0-9_=:+.-]+$')})
    resources['not'] = {'anyOf': [{'required': ['select', name]} for name in ('cpus', 'memory_mb')]}
    submission = record({'queue': text('^' + QUEUE_PATTERN + '$'), 'queue_wait_seconds': integer(), 'resources': resources})
    backend = record({'command': {'oneOf': [text(), {'type': 'array', 'minItems': 1, 'items': text()}]},
                      'python': python, 'activation_script': absolute, 'scratch_root': absolute,
                      'allowed_queues': queues, 'submission': submission,
                      'environment': {'type': 'object', 'propertyNames': {'pattern': r'^[A-Za-z_][A-Za-z0-9_]*$'},
                                      'additionalProperties': {'type': 'string', 'pattern': r'^[^\u0000]*$'}}})
    target = record({'kind': {'enum': ['local', 'remote']}, 'supervisor': {'enum': ['process', 'systemd']}, 'python': python, 'submission': submission,
                     'backends': {'type': 'object', 'propertyNames': text('^' + NAME_PATTERN + '$'), 'additionalProperties': backend},
                     'ssh_host': text(r'^[A-Za-z0-9][A-Za-z0-9_.@:-]*$'), 'ssh_config': absolute,
                     'scheduler': {'enum': ['torque', 'pbs']}, 'remote_root': absolute, 'allowed_queues': queues,
                     **{name: integer(limit) for name, limit in TIMEOUT_LIMITS.items()},
                     'commands': record({key: text(r'^\S+$') for key in ('qsub', 'qstat', 'qdel', 'checkjob')})}, ('kind',))
    assert set(target['properties']) == TARGET_FIELDS and set(backend['properties']) == BACKEND_FIELDS
    target['allOf'] = [
        {'if': {'properties': {'kind': {'const': 'remote'}}}, 'then': {'required': ['ssh_host', 'remote_root'], 'not': {'required': ['supervisor']}},
         'else': {'not': {'anyOf': [{'required': [key]} for key in sorted(REMOTE_FIELDS)]}}},
        {'if': {'not': {'required': ['python']}}, 'then': {'properties': {'backends': {
            'additionalProperties': {'anyOf': [{'required': ['command']}, {'required': ['python']}]}}}}},
    ]
    def submission_restriction(rule):
        return {'properties': {'submission': rule, 'backends': {'additionalProperties': {
            'properties': {'submission': rule}}}}}
    target['allOf'].extend([
        {'if': {'properties': {'kind': {'const': 'local'}}},
         'then': submission_restriction({'not': {'anyOf': [{'required': [key]} for key in ('queue', 'queue_wait_seconds')]}})},
        {'if': {'properties': {'kind': {'const': 'remote'}, 'scheduler': {'const': 'pbs'}}, 'required': ['scheduler']},
         'else': submission_restriction({'properties': {'resources': {'not': {'required': ['select']}}}})},
    ])
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'Job installation configuration',
            **record({'default_environment': text('^' + NAME_PATTERN + '$'),
                      'environments': {'type': 'object', 'minProperties': 1,
                                       'propertyNames': text('^' + NAME_PATTERN + '$'), 'additionalProperties': target}},
                     ('default_environment', 'environments'))}
