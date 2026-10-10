"""Load scientific execution declarations without a Pi or Node dependency.

The package declares catalogs explicitly. Each use validates their resource
bytes, so a prepared Job cannot silently inherit edited code or declarations.
Skills supply guidance only; executable resource identity belongs to this catalog.
"""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator

from research_agent.foundation.env import resolve_package_root
from research_agent.jobs.environment import validate_requirements

_SCHEMA = json.loads(files(__package__).joinpath('execution_schema.json').read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA)
_RESERVED = {'spec.json', 'receipt.json', 'status.json', 'input_manifest.json', 'logs', '.coragent'}


def _relative(value):
    path = PurePosixPath(value)
    if not value or '\\' in value or path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise ValueError('execution_resource_path_invalid')
    return path


def _owned_file(root, relative):
    path = root / _relative(relative)
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('execution_resource_symlink')
        current = current.parent
    if not path.is_file():
        raise ValueError('execution_resource_missing: ' + relative)
    return path


def _verify(root, relative, expected):
    content = _owned_file(root, relative).read_bytes()
    if expected != 'sha256:' + hashlib.sha256(content).hexdigest():
        raise ValueError('execution_resource_changed: ' + relative)


def _destination(value, destinations, *, reserved=_RESERVED):
    path = _relative(value)
    if path.parts[0] in reserved or any(path == other or path in other.parents or other in path.parents for other in destinations):
        raise ValueError('execution_destinations_overlap_or_reserved')
    destinations.add(path)


def _executor(root, entry):
    validate_requirements(entry.get('requirements', {}), entry['runtime'])
    resources = entry['resources']
    _module_paths(entry, resources)
    destinations = set()
    for relative, expected in resources.items():
        _destination(relative, destinations)
        _verify(root, relative, expected)
    for key in ('entry', 'cli'):
        if key in entry and entry[key] not in resources:
            raise ValueError('executor_entry_resource_required')
    if entry['runtime'] == 'python' and 'entry' not in entry:
        raise ValueError('executor_python_entry_required')
    if entry['runtime'] == 'native' and 'entry' in entry:
        raise ValueError('executor_native_entry_forbidden')
    for destination in entry['inputs'].values():
        _destination(destination, destinations)
    argv = entry['argv']
    placeholders = {'{entry}', '{args}', '{command}', '{executable}', *['{input:' + role + '}' for role in entry['inputs']]}
    if any((token.startswith('{') or token.endswith('}')) and token not in placeholders for token in argv):
        raise ValueError('executor_argv_placeholder_invalid')
    if argv[0] != ('{entry}' if entry['runtime'] == 'python' else '{command}') or argv.count('{args}') > 1:
        raise ValueError('executor_argv_invalid')
    outputs = set()
    for output in entry['outputs']:
        destination = _relative(output['path'])
        if destination in outputs:
            raise ValueError('executor_output_duplicate')
        outputs.add(destination)


def _validator(root, entry):
    validate_requirements(entry.get('requirements', {}), 'python')
    _verify(root, entry['entry'], entry['sha256'])
    _module_paths(entry, entry.get('resources', {}))
    destinations = set()
    reserved = _RESERVED | {'validator.py', 'validator_inputs.json', 'validator_result.json'}
    for destination, resource in entry.get('resources', {}).items():
        _destination(destination, destinations, reserved=reserved)
        if destination.startswith('input_'):
            raise ValueError('validator_resource_destination_invalid')
        _verify(root, resource['path'], resource['sha256'])
    roles = entry.get('input_contract', {}).get('roles', [])
    if len({role['name'] for role in roles}) != len(roles):
        raise ValueError('validator_input_role_duplicate')


def _module_paths(entry, resources):
    paths = entry.get('module_paths', [])
    if len(set(paths)) != len(paths) or paths and entry.get('runtime', 'python') != 'python':
        raise ValueError('execution_module_paths_invalid')
    for value in paths:
        path = _relative(value)
        if not any(path in PurePosixPath(resource).parents for resource in resources):
            raise ValueError('execution_module_path_unstaged')


def installed_catalogs(package_root=None):
    package = resolve_package_root(package_root)
    metadata = json.loads((package / 'package.json').read_text())
    declarations = metadata['coragent']['execution']
    if not isinstance(declarations, list) or any(not isinstance(path, str) for path in declarations) or len(set(declarations)) != len(declarations):
        raise ValueError('execution_catalog_declarations_invalid')
    catalogs, names = [], set()
    identities = {kind: set() for kind in ('executors', 'validators', 'acceptance_profiles')}
    for declaration in declarations:
        path = _owned_file(package, declaration)
        catalog = json.loads(path.read_text())
        _VALIDATOR.validate(catalog)
        if catalog['name'] in names:
            raise ValueError('execution_catalog_name_duplicate')
        names.add(catalog['name'])
        root = path.parent
        for kind, seen in identities.items():
            for entry in catalog[kind]:
                identity = (entry['id'], entry['version'])
                if identity in seen:
                    raise ValueError('execution_catalog_identity_duplicate')
                seen.add(identity)
                if kind == 'executors':
                    _executor(root, entry)
                elif kind == 'validators':
                    _validator(root, entry)
                else:
                    checks = entry['checks']
                    if len({check['id'] for check in checks}) != len(checks):
                        raise ValueError('acceptance_check_duplicate')
        catalogs.append({**catalog, 'root': str(root)})
    return catalogs


def registered_entry(collection, identifier, version):
    if not isinstance(version, str) or not version:
        raise ValueError(collection + '_version_required')
    matches = [(Path(catalog['root']), entry) for catalog in installed_catalogs()
               for entry in catalog[collection] if entry['id'] == identifier and entry['version'] == version]
    if len(matches) != 1:
        raise ValueError(collection + '_not_registered: use an installed id and version')
    return matches[0]
