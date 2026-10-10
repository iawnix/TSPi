"""Standard-library installation planning and provisioning for execution targets.

Runtime bindings remain in job.toml. Profiles are immutable domain resources;
receipts record ownership and never supply implicit runtime configuration.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RECORD = 'var/state/installation/job-environments.json'
STORES = 'var/state/installation/job-environment-stores.json'


def contract(root=ROOT):
    spec = importlib.util.spec_from_file_location('installation_job_contract',
        root / 'backend/src/research_agent/jobs/config_contract.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_private(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('installation file cannot be a symlink: ' + str(path))
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def toml_bytes(document):
    lines = []
    def table(path, values):
        if path:
            lines.append('[' + '.'.join(json.dumps(key, ensure_ascii=False) for key in path) + ']')
        for key, value in values.items():
            if not isinstance(value, dict):
                lines.append(json.dumps(key, ensure_ascii=False) + ' = ' + json.dumps(value, ensure_ascii=False))
        lines.append('')
        for key, value in values.items():
            if isinstance(value, dict):
                table((*path, key), value)
    table((), document)
    return ('\n'.join(lines) + '\n').encode()


def resource(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or str(path) != relative:
        raise ValueError('invalid environment resource path')
    source = root / relative
    if not source.resolve().is_relative_to(root.resolve()) or source.is_symlink() or not source.is_file():
        raise ValueError('missing environment resource: ' + relative)
    return source


def profiles(package):
    metadata = json.loads((package / 'package.json').read_text())
    result = {}
    for relative in metadata.get('coragent', {}).get('environments', []):
        path = resource(package, relative)
        document = json.loads(path.read_text())
        if document.get('schema_version') != 'coragent-environments/1':
            raise ValueError('unsupported environment profile schema')
        for identifier, profile in document['profiles'].items():
            if identifier in result or not re.fullmatch(r'[A-Za-z0-9_.-]+', identifier):
                raise ValueError('duplicate or invalid environment profile')
            if not isinstance(profile.get('backends'), list) or not profile['backends'] or any(
                    not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) for name in profile['backends']):
                raise ValueError('environment profile needs named backends')
            platform = profile.get('platform', {})
            if (platform.get('system') != 'Linux' or not isinstance(platform.get('machines'), list)
                    or not platform['machines'] or not re.fullmatch(r'\d+\.\d+', str(platform.get('glibc', '')))):
                raise ValueError('environment profile needs a supported platform declaration')
            for name, checksum in profile['resources'].items():
                if 'sha256:' + digest(resource(path.parent, name).read_bytes()) != checksum:
                    raise ValueError('environment profile resource changed: ' + name)
            if profile['lock'] not in profile['resources']:
                raise ValueError('environment lock must be a pinned resource')
            requirements = Path(profile['lock']).with_suffix('.requirements.txt').as_posix()
            if (path.parent / requirements).exists() and requirements not in profile['resources']:
                raise ValueError('environment pip requirements must be a pinned resource')
            for check in profile.get('checks', []):
                if (check.get('backend') not in profile['backends'] or bool(check.get('script')) == bool(check.get('executor'))
                        or (check.get('script') and check['script'] not in profile['resources'])):
                    raise ValueError('invalid or unpinned environment acceptance check')
            result[identifier] = {**profile, 'root': str(path.parent)}
    return result


def assignments(values, label):
    result = {}
    for value in values or []:
        name, separator, path = value.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name in result:
            raise ValueError(label + ' requires unique TARGET=/absolute/path values')
        contract()._absolute(path, label)
        result[name] = path
    return result


def read_input(path, inputs, *, required=False):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError('configuration must be a regular file: ' + str(path))
    raw = path.read_bytes() if path.exists() else None
    if required and raw is None:
        raise ValueError('configuration file does not exist: ' + str(path))
    inputs[str(path)] = digest(raw) if raw is not None else None
    return raw


def plan(args, package=ROOT):
    root = Path(args.install_root or Path.home() / '.local/share/coragent').expanduser().resolve()
    inputs = {}
    installed_job = read_input(root / 'etc/job.toml', inputs)
    raw = read_input(args.job_config, inputs, required=True) if args.job_config else installed_job
    settings = tomllib.loads(raw.decode()) if raw is not None else {'default_environment': 'local',
        'environments': {'local': {'kind': 'local', 'backends': {}}}}
    if (not isinstance(settings, dict) or not isinstance(settings.get('environments'), dict)
            or any(not isinstance(target, dict) or target.get('kind') not in {'local', 'remote'}
                   for target in settings['environments'].values())):
        raise ValueError('job configuration needs named local or remote environments')
    settings = copy.deepcopy(settings)
    previous_raw = read_input(root / RECORD, inputs)
    previous = json.loads(previous_raw) if previous_raw else {'environments': []}
    if previous_raw and (not isinstance(previous, dict) or previous.get('schema_version') != 'coragent-job-install/1'
                        or not isinstance(previous.get('environments'), list)):
        raise ValueError('invalid managed environment record: ' + str(root / RECORD))
    for row in previous['environments']:
        if not isinstance(row, dict) or not {'target', 'kind', 'profile', 'backends', 'binding', 'managed', 'store'} <= row.keys():
            raise ValueError('incomplete managed environment record: ' + str(root / RECORD))
        contract().validate_python(row['binding'])
    available = profiles(package)
    selections = list(getattr(args, 'job_profile', None) or [])
    if raw is None and not getattr(args, 'without_default_job_environment', False):
        selections.extend('local:' + key for key, value in available.items() if value.get('default'))
    # A managed selection persists across upgrades, provided its bindings have
    # not been edited by the operator since the last publication.
    for row in previous['environments']:
        target = settings['environments'].get(row['target'], {})
        if row.get('managed') and all(target.get('backends', {}).get(backend, {}).get('python') == row['binding']
                                     for backend in row['backends']):
            if target.get('kind') == 'local':
                selections.append(row['target'] + ':' + row['profile'])
    roots = assignments(getattr(args, 'job_software_root', None), '--job-software-root')
    condas = assignments(getattr(args, 'job_conda', None), '--job-conda')
    if (roots.keys() | condas.keys()) - settings['environments'].keys():
        raise ValueError('software root or Conda target is not configured')
    identity = digest(os.fsencode(root))[:16]
    default_store = str(Path.home() / 'soft/coragent/job-envs' / identity)
    rows, selected_targets = [], set(getattr(args, 'verify_job_target', None) or [])
    for selection in dict.fromkeys(selections):
        target_name, separator, identifier = selection.partition(':')
        if not separator or target_name not in settings['environments'] or identifier not in available:
            raise ValueError('--job-profile requires a configured TARGET:PROFILE: ' + selection)
        target, profile = settings['environments'][target_name], available[identifier]
        selected_targets.add(target_name)
        backends = target.setdefault('backends', {})
        names = [name for name in profile['backends'] if profile.get('auto_bind', True) or name in backends]
        if not names:
            raise ValueError('profile needs an existing native software binding: ' + selection)
        prior = next((row for row in previous['environments'] if row['target'] == target_name
                      and row['profile'] == identifier and row.get('managed')), None)
        explicit = next((backends[name]['python'] for name in names if 'python' in backends.get(name, {})
                         and (not prior or backends[name]['python'] != prior['binding'])), None)
        content = resource(Path(profile['root']), profile['lock']).read_bytes()
        requirements = Path(profile['root']) / Path(profile['lock']).with_suffix('.requirements.txt')
        lock_digest = digest(content + b'\0' + (requirements.read_bytes() if requirements.is_file() else b''))
        if explicit:
            binding, managed, store = explicit, False, None
        else:
            store = roots.get(target_name) or (prior or {}).get('store')
            if not store and target['kind'] == 'local':
                store = default_store
            conda = condas.get(target_name) or ((prior or {}).get('binding') or {}).get('conda_executable')
            if not conda:
                conda = target.get('python', {}).get('conda_executable')
            if not conda and target['kind'] == 'local':
                conda = (str(Path(args.conda_root) / 'bin/conda') if args.conda_root else
                         shutil.which('conda') or shutil.which('mamba'))
            if not store or not conda:
                raise ValueError(selection + ' needs --job-software-root and --job-conda for its target')
            binding = {'manager': 'conda', 'conda_executable': conda,
                       'prefix': str(PurePosixPath(store) / (identifier + '-' + lock_digest[:16])),
                       'lock_ref': str(PurePosixPath(store) / 'locks' / lock_digest / Path(profile['lock']).name)}
            managed = True
        bound = []
        for name in names:
            current = backends.setdefault(name, {})
            if 'python' in current and current['python'] != binding and (not prior or current['python'] != prior['binding']):
                continue
            current['python'] = dict(binding)
            bound.append(name)
        rows.append({'target': target_name, 'kind': target['kind'], 'profile': identifier, 'backends': bound,
                     'binding': binding, 'managed': managed, 'store': store, 'lock_sha256': lock_digest, 'prepare': True})
    identities = {(row['target'], row['profile']) for row in rows}
    rows.extend({**row, 'prepare': False} for row in previous['environments']
                if (row['target'], row['profile']) not in identities)
    selected_targets.update(name for name, target in settings['environments'].items() if target['kind'] == 'local')
    if selected_targets - settings['environments'].keys():
        raise ValueError('verification target is not configured')
    resolver_path = root / 'etc/name-resolver.toml'
    existing_resolver = read_input(resolver_path, inputs)
    resolver = (read_input(args.name_resolver_config, inputs, required=True) if args.name_resolver_config else existing_resolver)
    if resolver is None:
        resolver = (package / 'config/name-resolver.example.toml').read_bytes()
    resolver_bindings, remote_resolvers = [], {}
    for name, target in settings['environments'].items():
        structure = target.get('backends', {}).get('structure')
        if structure is None:
            continue
        variables = structure.setdefault('environment', {})
        if {'CORAGENT_NAME_RESOLVER_CONFIG', 'CORAGENT_INSTALL_ROOT'} & variables.keys():
            continue
        row = next((item for item in rows if item['target'] == name and item['store'] and item.get('prepare')), None)
        if target['kind'] == 'local':
            variables['CORAGENT_NAME_RESOLVER_CONFIG'] = str(resolver_path)
            resolver_bindings.append(name)
        elif row:
            remote_configuration = tomllib.loads(resolver.decode())
            for backend, backend_settings in remote_configuration.get('backends', {}).items():
                backend_settings['cache_dir'] = str(PurePosixPath(row['store']) / 'cache/name-resolver' / backend)
            remote_content = toml_bytes(remote_configuration)
            variables['CORAGENT_NAME_RESOLVER_CONFIG'] = str(PurePosixPath(row['store']) / 'resolver' /
                digest(remote_content) / 'name-resolver.toml')
            remote_resolvers[name] = {'path': variables['CORAGENT_NAME_RESOLVER_CONFIG'], 'content': remote_content.decode()}
            resolver_bindings.append(name)
    contract().validate_job_config(settings)
    return {'schema_version': 'coragent-job-install/1', 'settings': settings,
            'environments': rows, 'targets': sorted(selected_targets), 'inputs': inputs,
            'resolver': resolver.decode(), 'resolver_bindings': resolver_bindings, 'remote_resolvers': remote_resolvers,
            'configuration_source': 'supplied' if args.job_config else 'preserved' if raw else 'generated',
            'profiles': available, 'install_root': str(root)}


def preview(value):
    return {'configuration_source': value['configuration_source'], 'verify_targets': value['targets'],
            'environments': [{**{k: row[k] for k in ('target', 'profile', 'managed')},
                              'prefix': row['binding']['prefix'], 'action': 'prepare_or_reuse' if row['managed'] and row.get('prepare') else 'preserve_existing'}
                             for row in value['environments']],
            'remote_contact': 'deferred_until_install', 'dependency_validation': 'in_managed_runtime'}


def assert_inputs_unchanged(value):
    for filename, expected in value['inputs'].items():
        path = Path(filename)
        actual = digest(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
        if actual != expected or path.is_symlink():
            raise ValueError('installation input changed during preparation: ' + filename)


def invoke_target(target, request, package, *, timeout=3600, log_path=None):
    helper = package / 'scripts/_job_target.py'
    if target['kind'] == 'local':
        command = [sys.executable, '-B', str(helper)]
        payload = request
    else:
        files = ['scripts/_job_target.py', 'scripts/install_job_environment.py',
                 'backend/src/research_agent/jobs/config_contract.py', 'backend/src/research_agent/jobs/environment_probe.py']
        bundle = {name: base64.b64encode((package / name).read_bytes()).decode() for name in files}
        # The bootstrap only materializes the fixed helper bundle in the target's
        # owned store. No Host environment or complete job.toml is transferred.
        bootstrap = ('import sys,json,base64,pathlib,subprocess,tempfile; '
                     'p=json.load(sys.stdin); '
                     'd=tempfile.TemporaryDirectory(prefix=".installer-",dir=p["request"]["store"]); '
                     'r=pathlib.Path(d.name); '
                     '[( (r/n).parent.mkdir(parents=True,exist_ok=True), (r/n).write_bytes(base64.b64decode(v))) for n,v in p["bundle"].items()]; '
                     's=subprocess.run([sys.executable,"-B",str(r/"scripts/_job_target.py")],input=json.dumps(p["request"]).encode()); '
                     'd.cleanup(); sys.exit(s.returncode)')
        store = request['store']
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=' + str(target.get('connect_timeout_seconds', 15))]
        if target.get('ssh_config'):
            command += ['-F', target['ssh_config']]
        shell = 'umask 077; mkdir -p -- ' + shlex.quote(store) + ' && timeout --kill-after=5 ' + str(timeout) + ' python3 -B -c ' + shlex.quote(bootstrap)
        command += [target['ssh_host'], shell]
        payload = {'request': request, 'bundle': bundle}
    environment = dict(os.environ) if target['kind'] == 'local' else {
        key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'USER', 'SSH_AUTH_SOCK') if key in os.environ}
    completed = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True,
                               timeout=timeout + 30, env=environment)
    if log_path:
        write_private(log_path, (completed.stdout + '\n' + completed.stderr).encode())
    lines = [line.removeprefix('CORAGENT_PROVISION=') for line in completed.stdout.splitlines()
             if line.startswith('CORAGENT_PROVISION=')]
    if len(lines) == 1 and completed.returncode:
        result = json.loads(lines[0])
        raise RuntimeError('target environment preparation failed: ' + result.get('error', 'unknown'))
    if completed.returncode or len(lines) != 1:
        raise RuntimeError('target environment preparation failed; check target access, platform, lock and cache')
    return json.loads(lines[0])


def prepare(value, args, package, python):
    root = Path(value['install_root'])
    stage_root = root / 'var/cache/job-install'
    stage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix='candidate-', dir=stage_root)).resolve()
    # Keep ownership even when acceptance or release activation later fails.
    # Old stores remain discoverable after selecting a different store on retry.
    registry = root / STORES
    if registry.is_symlink():
        raise ValueError('managed store registry cannot be a symlink')
    stores = json.loads(registry.read_text()) if registry.is_file() else []
    for row in value['environments']:
        if row['managed']:
            item = {key: row[key] for key in ('store', 'kind')}
            if item not in stores:
                stores.append(item)
    write_private(registry, (json.dumps(stores, indent=2) + '\n').encode())
    for row in value['environments']:
        if not row['managed'] or not row.get('prepare'):
            continue
        profile = value['profiles'][row['profile']]
        files = {name: base64.b64encode(resource(Path(profile['root']), name).read_bytes()).decode()
                 for name in profile['resources'] if name == profile['lock'] or name.endswith('.requirements.txt')}
        target = value['settings']['environments'][row['target']]
        request = {'store': row['store'], 'binding': row['binding'], 'files': files,
                   'profile': {key: profile[key] for key in ('lock', 'platform')},
                   'owner': digest(os.fsencode(root))[:16], 'offline': bool(getattr(args, 'job_offline', False))}
        if row['target'] in value['remote_resolvers']:
            request['resolver'] = value['remote_resolvers'][row['target']]
        log_path = stage / (row['target'] + '-' + row['profile'] + '-provision.log')
        try:
            row['receipt'] = invoke_target(target, request, package, log_path=log_path)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            raise RuntimeError(str(error) + '; target preparation log: ' + str(log_path)) from error
    candidate = copy.deepcopy(value['settings'])
    resolver = stage / 'name-resolver.toml'
    write_private(resolver, value['resolver'].encode())
    # Candidate Jobs read the candidate resolver; publication uses the final
    # installation path and is checked again before any service activation.
    for name in value['resolver_bindings']:
        target = candidate['environments'][name]
        if target['kind'] == 'local':
            target['backends']['structure']['environment']['CORAGENT_NAME_RESOLVER_CONFIG'] = str(resolver)
    config = stage / 'job.toml'
    write_private(config, toml_bytes(candidate))
    report = stage / 'readiness.json'
    command = [python, '-B', str(package / 'scripts/_job_acceptance.py'), '--config', str(config),
               '--package-root', str(package), '--directory', str(stage / 'jobs'), '--report', str(report),
               '--targets', json.dumps(value['targets']), '--timeout', str(getattr(args, 'job_check_timeout', 180))]
    completed = subprocess.run(command, text=True, capture_output=True, env=acceptance_environment(package, python))
    write_private(stage / 'acceptance.log', (completed.stdout + '\n' + completed.stderr).encode())
    if report.is_file():
        value['readiness'] = json.loads(report.read_text())
    if completed.returncode:
        raise RuntimeError('Job acceptance failed; report/log directory: ' + str(stage))
    value['stage'] = str(stage)
    value['package_root'] = str(package)
    return value


def publish(value):
    assert_inputs_unchanged(value)
    root = Path(value['install_root'])
    write_private(root / 'etc/name-resolver.toml', value['resolver'].encode())
    write_private(root / 'etc/job.toml', toml_bytes(value['settings']))
    record = {key: value[key] for key in ('schema_version', 'environments', 'readiness', 'configuration_source')}
    write_private(root / RECORD, (json.dumps(record, indent=2) + '\n').encode())
    current_digest = digest(toml_bytes(value['settings']))
    previous_digest = value['inputs'].get(str(root / 'etc/job.toml'))
    return {'job': {'status': 'configured', 'path': str(root / 'etc/job.toml'), 'readiness': value['readiness'],
                    'sha256': current_digest, 'previous_sha256': previous_digest,
                    'configuration_changed': previous_digest is not None and previous_digest != current_digest},
            'name_resolver': {'status': 'configured', 'path': str(root / 'etc/name-resolver.toml')}}


def verify_publication(value, python):
    root = Path(value['install_root'])
    if (root / 'etc/job.toml').read_bytes() != toml_bytes(value['settings']):
        raise RuntimeError('published Job configuration changed')
    if (root / 'etc/name-resolver.toml').read_text() != value['resolver']:
        raise RuntimeError('published resolver configuration changed')
    stage, package = Path(value['stage']), Path(value['package_root'])
    targets = [name for name in value['targets'] if value['settings']['environments'][name]['kind'] == 'local']
    report = stage / 'published-readiness.json'
    command = [python, '-B', str(package / 'scripts/_job_acceptance.py'), '--config', str(root / 'etc/job.toml'),
               '--package-root', str(package), '--directory', str(stage / 'published-jobs'), '--report', str(report),
               '--targets', json.dumps(targets), '--bindings-only']
    result = subprocess.run(command, text=True, capture_output=True, env=acceptance_environment(package, python))
    write_private(stage / 'published-acceptance.log', (result.stdout + '\n' + result.stderr).encode())
    if result.returncode:
        raise RuntimeError('published Job binding verification failed; local report: ' + str(report))
    record_path = root / RECORD
    record = json.loads(record_path.read_text())
    record['published_configuration_sha256'] = digest((root / 'etc/job.toml').read_bytes())
    record['publication'] = json.loads(report.read_text())
    write_private(record_path, (json.dumps(record, indent=2) + '\n').encode())


def acceptance_environment(package, python):
    environment = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'CORAGENT_INSTALL_ROOT', 'CORAGENT_RUNTIME_MANIFEST',
                'CORAGENT_WORKSPACE_ROOT'):
        environment.pop(key, None)
    environment.update(CORAGENT_PACKAGE_ROOT=str(package), CORAGENT_PYTHON=python,
                       PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    return environment


def cleanup_stores(root, workspace, guards):
    """Select unreferenced local stores owned by this installation for purge."""
    import fcntl
    record = root / RECORD
    registry = root / STORES
    if record.is_symlink() or registry.is_symlink():
        raise ValueError('managed environment records cannot be symlinks')
    rows = json.loads(record.read_text()).get('environments', []) if record.is_file() else []
    rows.extend({**row, 'managed': True} for row in (json.loads(registry.read_text()) if registry.is_file() else []))
    stores = {row['store'] for row in rows if row.get('managed') and row.get('store')}
    active = False
    for directory in (workspace, root / 'var/cache/job-install'):
        for path in directory.rglob('operations/executions/*.json') if directory.is_dir() else []:
            try:
                active |= json.loads(path.read_text()).get('state') not in {'succeeded', 'failed', 'cancelled', 'timed_out', 'collected'}
            except (OSError, ValueError):
                active = True
    removed, retained = [], []
    for value in sorted(stores):
        path = Path(value)
        try:
            if active or any(row.get('kind') != 'local' for row in rows if row.get('store') == value):
                raise ValueError('store is remote or referenced by unfinished jobs')
            if not path.is_absolute() or path in (Path('/'), Path.home(), root) or any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('invalid store path')
            owner = json.loads((path / 'installation-owner.json').read_text())
            if owner != {'installation_id': digest(os.fsencode(root))[:16]}:
                raise ValueError('foreign environment store')
            guard = guards.enter_context((path / '.provision.lock').open('a'))
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for process in Path('/proc').iterdir():
                if not process.name.isdecimal():
                    continue
                try:
                    if (os.fsencode(path) + b'/') in (process / 'cmdline').read_bytes():
                        raise ValueError('environment has a live process')
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
            removed.append(path)
        except (OSError, ValueError):
            retained.append(value)
    return removed, retained
