"""Target-side provisioner; this fixed stdlib bundle also runs over SSH."""
from __future__ import annotations
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import subprocess

try:
    from .install_job_environment import install
except ImportError:
    from install_job_environment import install


def private_file(path, content):
    if path.is_symlink():
        raise ValueError('target_file_symlink')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_file():
        if path.read_bytes() != content:
            raise ValueError('target_immutable_file_changed')
        return
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()))
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def provision(request):
    store = Path(request['store'])
    if not store.is_absolute() or store in (Path('/'), Path.home()) or '..' in store.parts:
        raise ValueError('target_store_must_be_dedicated')
    for parent in (store, *store.parents):
        if parent.is_symlink():
            raise ValueError('target_store_symlink')
    required = request['profile']['platform']
    libc, version = platform.libc_ver()
    if (platform.system() != required['system'] or platform.machine() not in required['machines']
            or libc != 'glibc' or tuple(map(int, version.split('.'))) < tuple(map(int, required['glibc'].split('.')))):
        raise ValueError('target_platform_unsupported')
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (store / '.provision.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        owner = store / 'installation-owner.json'
        content = (json.dumps({'installation_id': request['owner']}, sort_keys=True) + '\n').encode()
        if not owner.exists() and any(item.name not in {'.provision.lock'} and not item.name.startswith('.installer-')
                                      for item in store.iterdir()):
            raise ValueError('target_store_has_no_ownership_record')
        private_file(owner, content)
        binding = request['binding']
        prefix, lock = Path(binding['prefix']), Path(binding['lock_ref'])
        if prefix.parent != store or not lock.is_relative_to(store / 'locks'):
            raise ValueError('target_binding_escapes_store')
        if any(path.is_symlink() for path in (prefix, lock, *lock.parents)):
            raise ValueError('target_binding_symlink')
        for name, encoded in request['files'].items():
            if Path(name).name != name or name not in {request['profile']['lock'], Path(request['profile']['lock']).with_suffix('.requirements.txt').name}:
                raise ValueError('unexpected_target_file')
            private_file(lock.parent / name, base64.b64decode(encoded, validate=True))
        lock_bytes = lock.read_bytes()
        pip = lock.with_suffix('.requirements.txt')
        checksum = hashlib.sha256(lock_bytes + b'\0' + (pip.read_bytes() if pip.is_file() else b'')).hexdigest()
        if lock.parent.name != checksum or not prefix.name.endswith('-' + checksum[:16]):
            raise ValueError('target_lock_digest_mismatch')
        pending = store / ('.' + prefix.name + '.pending')
        # A prior interrupted attempt may leave a partial environment. Only
        # prefixes with our pending ownership record can be removed on retry.
        receipt = prefix / 'coragent-environment.json'
        if prefix.exists() and pending.exists() and not receipt.exists():
            if pending.read_bytes() != content or prefix.is_symlink():
                raise ValueError('target_incomplete_environment_not_owned')
            import shutil
            shutil.rmtree(prefix)
        if not prefix.exists():
            private_file(pending, content)
        cache = store / 'cache'
        cache.mkdir(exist_ok=True, mode=0o700)
        os.environ.setdefault('CONDA_PKGS_DIRS', str(cache / 'conda'))
        os.environ['PIP_CACHE_DIR'] = str(cache / 'pip')
        result = install(binding, package_cache=cache / 'pip-packages', offline=request.get('offline', False))
        pending.unlink(missing_ok=True)
        if request.get('resolver'):
            resolver = request['resolver']
            path = Path(resolver['path'])
            data = resolver['content'].encode()
            if path != store / 'resolver' / hashlib.sha256(data).hexdigest() / 'name-resolver.toml':
                raise ValueError('target_resolver_path_mismatch')
            private_file(path, data)
        return {'status': 'environment_verified', 'lock_sha256': result['lock_sha256'],
                'inventory_sha256': result['inventory_sha256']}


def main():
    request = json.load(sys.stdin)
    try:
        result = provision(request)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('CORAGENT_PROVISION=' + json.dumps({'status': 'failed', 'error': str(error)}))
        return 1
    print('CORAGENT_PROVISION=' + json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
