"""Content-addressed test dependencies, exclusively in the private test root."""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TEST_IMPORTS = "import ase,jsonschema,packaging,numpy,pytest,rdkit,scipy; from PIL import Image"
ROOT = Path(__file__).resolve().parents[2]


def configure_paths(env_root: Path) -> None:
    import tempfile
    root = env_root.expanduser().resolve()
    if not root.is_relative_to(Path('/home/iaw/project/TSPi/local_debug')) and os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Local testing must use repository local_debug')
    os.umask(0o077)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    for name in ('tmp', 'registry', 'runs', 'evidence', 'builds', 'toolchains'):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ['CORAGENT_TEST_ENV_ROOT'] = str(root)
    os.environ['CORAGENT_TEST_ROOT'] = str(root / 'tmp')
    os.environ['TMPDIR'] = str(root / 'tmp')
    tempfile.tempdir = str(root / 'tmp')
    for variable, directory in (('npm_config_cache','npm'),('PIP_CACHE_DIR','pip'),('CONDA_PKGS_DIRS','conda'),('XDG_CACHE_HOME','xdg')):
        path = root / 'cache' / directory
        path.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(path)


def lock_path(package_root: Path) -> Path:
    return package_root / 'tools/test/environment.lock.txt'


def key(package_root: Path, paths: list[str], extra: str = '') -> str:
    digest = hashlib.sha256((platform.system() + platform.machine() + extra).encode())
    for pattern in paths:
        for path in sorted(package_root.glob(pattern)):
            if path.is_file():
                digest.update(str(path.relative_to(package_root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def spec_sha256(package_root: Path) -> str:
    return hashlib.sha256(lock_path(package_root).read_bytes()).hexdigest()


def default_prefix(package_root: Path, env_root: Path) -> Path:
    return env_root / 'deps/python' / key(package_root, ['tools/test/environment.lock.txt','tools/test/environment.py'])


def probe(python: Path, imports: str = TEST_IMPORTS) -> bool:
    if not python.is_file() or not os.access(python, os.X_OK):
        return False
    env = dict(os.environ)
    for name in ('PYTHONPATH','PYTHONHOME'): env.pop(name, None)
    env['PYTHONNOUSERSITE'] = '1'
    return subprocess.run([str(python), '-c', imports], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


@contextlib.contextmanager
def locked(root: Path, identity: str):
    with (root / 'registry' / f'{identity}.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def dependency_paths(package_root: Path, root: Path) -> dict[str, Path]:
    node_version = subprocess.check_output(['node','--version'], text=True).strip()
    package=json.loads((package_root/'package.json').read_text())
    lock=json.loads((package_root/'package-lock.json').read_text())
    install_fields=('dependencies','devDependencies','optionalDependencies','peerDependencies','peerDependenciesMeta','overrides','workspaces','engines','os','cpu')
    requested={name:package[name] for name in install_fields if name in package}
    # Release names, version numbers, files and resource declarations do not
    # change installed third-party dependencies.
    lock.pop('name',None);lock.pop('version',None)
    if '' in lock.get('packages',{}):
        lock['packages']['']={name:value for name,value in lock['packages'][''].items() if name not in ('name','version','license')}
    node_input=json.dumps({'requested':requested,'lock':lock},sort_keys=True,separators=(',',':'))
    return {
        'python': default_prefix(package_root, root),
        'host': root / 'deps/host' / key(package_root,['environment.lock.txt','tools/test/environment.py']),
        'node': root / 'deps/node' / key(package_root, ['tools/test/environment.py'], node_version+node_input),
        'pi': root / 'deps/pi' / key(package_root, ['config/pi-source.json','config/pi-patches/*.patch','scripts/prepare_pi_source.py','tools/test/environment.py'], node_version),
    }


def prepare(package_root: Path, root: Path, components: list[str] | None = None) -> dict[str, Path]:
    configure_paths(root)
    dependencies = dependency_paths(package_root, root)
    for component in components or list(dependencies):
        target = dependencies[component]
        with locked(root, component + '-' + target.name):
            receipt = target / '.prepared.json'
            if receipt.is_file():
                if component in ('python','host') and not probe(target / 'bin/python',TEST_IMPORTS if component=='python' else 'import jsonschema,packaging'):
                    raise RuntimeError('Prepared Python dependency probe failed; use gc to remove the invalid environment')
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            log_path = root / 'registry' / f'prepare-{component}-{target.name}.log'
            with log_path.open('w') as log:
                def run(command, cwd=package_root):
                    subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)
                if component in ('python','host'):
                    conda = os.environ.get('CORAGENT_TEST_CONDA') or shutil.which('conda')
                    if not conda:
                        raise RuntimeError('Set CORAGENT_TEST_CONDA to the explicit conda executable')
                    # Conda embeds its prefix; build at the final path under a lock.
                    # Only the atomic receipt publishes the completed environment.
                    run([conda,'create','--yes','--prefix',str(target),'--file',str(lock_path(package_root) if component=='python' else package_root/'environment.lock.txt')])
                    if not probe(target / 'bin/python',TEST_IMPORTS if component=='python' else 'import jsonschema,packaging'): raise RuntimeError('Locked Python probe failed')
                elif component == 'node':
                    target.mkdir()
                    for name in ('package.json','package-lock.json'): shutil.copy2(package_root / name, target / name)
                    run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'], target)
                else:
                    # Keep clone/build diagnostics exclusively in the private log.
                    code = ('import sys;sys.path.insert(0,sys.argv[1]);import prepare_pi_source as p;'
                            'from pathlib import Path;s=Path(sys.argv[2]);p.clone(s);p.install_deps(s);'
                            'p.hydrate_model_data(s);p.prepare_build(s);p.verify(s)')
                    run([sys.executable,'-c',code,str(package_root / 'scripts'),str(target)])
                pending=receipt.with_suffix('.pending')
                pending.write_text(json.dumps({'component':component,'key':target.name}) + '\n')
                pending.replace(receipt)
    return dependencies
