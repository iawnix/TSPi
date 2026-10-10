"""Check configured software bindings or a selected recipe's prerequisites."""
import argparse
import json

from research_agent.jobs.config_contract import binding_digest, load_job_config, resolve_binding, validate_job_config
from research_agent.jobs.environment import probe_binding, validate_requirements
from research_agent.application.execution_catalog import installed_catalogs


def check_target(settings, environment, *, backend=None, executor=None, version=None,
                 runtime=None, probe=True, details=False):
    """Observe one target without requiring a recipe for every scientific method."""
    if bool(backend) == bool(executor) or bool(executor) != bool(version) or runtime and not backend:
        raise ValueError('select_backend_or_executor_and_version')
    validate_job_config(settings)
    result = {'environment': environment, 'scope': 'recipe_requirements' if executor else 'binding'}
    entry = None
    if executor:
        result['executor'] = {'id': executor, 'version': version}
        entries = [entry for catalog in installed_catalogs() for entry in catalog['executors']
                   if entry['id'] == executor and entry['version'] == version]
        if not entries:
            return {**result, 'status': 'recipe_not_found', 'software_availability': 'not_checked'}
        entry = entries[0]
        backend, runtime = entry['backend'], entry['runtime']
    result['backend'] = backend
    target = settings['environments'].get(environment)
    if target is None:
        return {**result, 'status': 'not_configured', 'error': 'execution_environment_not_configured'}
    binding = target.get('backends', {}).get(backend)
    if binding is None:
        return {**result, 'status': 'not_configured', 'error': 'executor_binding_missing'}
    # A binding may include both a wrapper Python and a native executable.
    # Check both by default; callers of native commands can explicitly narrow it.
    runtime = runtime or ('python' if binding.get('python') or target.get('python') else 'native')
    result['runtime'] = runtime
    requirements = entry.get('requirements', {}) if entry else {}
    try:
        selected = resolve_binding(settings, environment, backend, runtime=runtime)
        if entry:
            needs_command = any(token in entry.get('argv', []) for token in ('{command}', '{executable}'))
            if bool(binding.get('command')) != needs_command:
                raise ValueError('execution_binding_command_mismatch')
        validate_requirements(requirements, runtime)
        evidence = probe_binding(settings, selected, requirements) if probe else None
    except (ValueError, OSError) as exc:
        return {**result, 'status': 'check_failed', 'error': str(exc)}
    return {**result, 'status': 'verified' if probe else 'configuration_validated',
            **({'environment_evidence': evidence} if details else {})}


def check_environments(settings, *, catalogs=None, probe=True):
    validate_job_config(settings)
    catalogs = installed_catalogs() if catalogs is None else catalogs
    entries = [(kind, entry) for catalog in catalogs for kind in ('executors', 'validators')
               for entry in catalog.get(kind, [])]
    results = {}
    for name, target in settings['environments'].items():
        results[name] = {}
        covered = set()
        cache = {}
        for kind, entry in entries:
            backend = entry['backend']
            key = kind + ':' + entry['id'] + '@' + entry['version']
            if backend not in target.get('backends', {}):
                results[name][key] = {'status': 'not_configured', 'backend': backend}
                continue
            covered.add(backend)
            runtime = 'python' if kind == 'validators' else entry['runtime']
            selected = resolve_binding(settings, name, backend, runtime=runtime)
            command = selected['binding'].get('command')
            needs_command = any(token in entry.get('argv', []) for token in ('{command}', '{executable}'))
            if bool(command) != needs_command:
                raise ValueError('execution_binding_command_mismatch: ' + name + '/' + key)
            requirements = entry.get('requirements', {})
            if probe:
                validate_requirements(requirements, runtime)
            identity = binding_digest([selected, requirements])
            if identity not in cache:
                cache[identity] = probe_binding(settings, selected, requirements) if probe else None
            results[name][key] = {'status': 'verified' if probe else 'configuration_validated',
                                  'backend': backend, 'environment_evidence': cache[identity]}
        # A configured binding can also serve a task-specific script or native
        # command without inventing a registered scientific capability.
        for backend, binding in target.get('backends', {}).items():
            if backend in covered:
                continue
            runtime = 'native' if binding.get('command') else 'python'
            selected = resolve_binding(settings, name, backend, runtime=runtime)
            evidence = probe_binding(settings, selected, {}) if probe else None
            results[name]['binding:' + backend] = {'status': 'verified' if probe else 'configuration_validated',
                'backend': backend, 'environment_evidence': evidence}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--environment', help='Check only this named environment and selected backend or recipe')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--backend', help='Check a binding even when no predefined recipe exists')
    selection.add_argument('--executor', help='Check prerequisites of one predefined recipe')
    parser.add_argument('--version')
    parser.add_argument('--runtime', choices=['native', 'python'], help='Optional runtime for --backend')
    parser.add_argument('--details', action='store_true', help='Include full evidence in a targeted check')
    args = parser.parse_args()
    if bool(args.environment) != bool(args.backend or args.executor):
        parser.error('--environment requires --backend or --executor (and vice versa)')
    if bool(args.executor) != bool(args.version) or args.runtime and not args.backend:
        parser.error('--executor requires --version; --runtime is only for --backend')
    if args.details and not args.environment:
        parser.error('--details requires a targeted check; the full installation check already includes evidence')
    try:
        settings = load_job_config(args.config)
        result = (check_target(settings, args.environment, backend=args.backend, executor=args.executor,
                              version=args.version, runtime=args.runtime, details=args.details)
                  if args.environment else check_environments(settings))
    except (ValueError, OSError) as exc:
        # Probe errors are structured, sanitized codes; avoid tracebacks with argv.
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, indent=2))
    if args.environment and result['status'] != 'verified':
        parser.exit(1)


if __name__ == '__main__':
    main()
