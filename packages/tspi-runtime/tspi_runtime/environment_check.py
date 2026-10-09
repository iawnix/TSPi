"""Installation readiness from installed execution descriptors and Job bindings."""
import argparse
import json

from job_runtime.config_contract import binding_digest, load_job_config, resolve_binding, validate_job_config
from job_runtime.environment import probe_binding, validate_requirements
from tspi_foundation.extension_catalog import installed_extensions


def check_environments(settings, *, extensions=None, probe=True):
    validate_job_config(settings)
    extensions = installed_extensions() if extensions is None else extensions
    entries = [(kind, entry) for extension in extensions for kind in ('executors', 'validators')
               for entry in extension.get(kind, [])]
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
    args = parser.parse_args()
    try:
        result = check_environments(load_job_config(args.config))
    except (ValueError, OSError) as exc:
        # Probe errors are structured, sanitized codes; avoid tracebacks with argv.
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
