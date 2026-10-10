"""Single installation layout contract; standard library only, no runtime startup."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 'coragent-installation/2'

class AppLayout:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise ValueError('installation root must be a physical directory')
    @property
    def config(self): return self.root / 'etc'
    @property
    def marker(self): return self.config / 'installation.json'
    @property
    def releases(self): return self.root / 'releases'
    @property
    def current(self): return self.root / 'current'
    @property
    def state(self): return self.root / 'var/state'
    @property
    def install_state(self): return self.state / 'installation/install-state.json'
    @property
    def runtime_home(self): return self.state / 'installation/python'
    @property
    def host_state(self): return self.state / 'host'
    @property
    def sessions(self): return self.state / 'pi/sessions'
    @property
    def log(self): return self.root / 'var/log'
    @property
    def cache(self): return self.root / 'var/cache'
    @property
    def pi_runtime(self): return self.root / 'runtimes/pi'
    @property
    def pi_config(self): return self.config / 'pi'
    @property
    def job_config(self): return self.config / 'job.toml'
    @property
    def email_config(self): return self.config / 'email.toml'
    @property
    def guards(self):
        service = self.read_config().get('service') or {}
        base = service.get('runtime_dir') or str(Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'coragent')
        return Path(base) / self.identity / 'guards'
    @property
    def identity(self): return hashlib.sha256(os.fsencode(self.root)).hexdigest()[:16]
    def read_config(self):
        if not self.marker.exists(): return {}
        if self.marker.is_symlink(): raise ValueError('installation configuration cannot be a symbolic link')
        value = json.loads(self.marker.read_text())
        if not isinstance(value, dict) or value.get('schema_version') != SCHEMA or value.get('install_root') != str(self.root):
            raise ValueError('unsupported or mismatched installation layout; a fresh installation is required')
        return value
    def update_config(self, **fields):
        self.initialize()
        value = self.read_config()
        value.update(fields)
        temporary = self.marker.with_name(f'.installation.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(value, indent=2)+'\n')
        temporary.chmod(0o600); temporary.replace(self.marker)
        return self.marker
    @property
    def env_root(self):
        configured = self.read_config().get('env_root')
        value = Path(configured or os.environ.get('CORAGENT_HOST_ENV_ROOT', str(Path.home() / 'soft/coragent/host-envs' / self.identity))).expanduser()
        if not value.is_absolute() or value.is_symlink():
            raise ValueError('Host environment store must be an absolute physical path')
        resolved = value.resolve()
        if resolved in (Path('/'), Path.home().resolve(), self.root) or resolved in self.root.parents:
            raise ValueError('Host environment store must be a dedicated directory')
        return resolved
    def initialize(self):
        if any((self.root / name).exists() or (self.root / name).is_symlink() for name in ('.pi', '.agents')):
            raise ValueError('old installation layout is unsupported; uninstall before a fresh installation')
        for directory in (self.config, self.state/'installation', self.runtime_home, self.host_state,
                          self.sessions, self.log, self.cache, self.pi_runtime, self.pi_config, self.config/'secrets'):
            current = self.root
            for part in directory.relative_to(self.root).parts:
                current /= part
                if current.is_symlink(): raise ValueError(f'installation directory cannot be a symlink: {current}')
                current.mkdir(mode=0o700, parents=True, exist_ok=True)
                current.chmod(0o700)
        value=self.read_config()
        if not value:
            value={'schema_version':SCHEMA,'install_root':str(self.root),'installation_id':self.identity,'env_root':str(self.env_root)}
            temporary=self.marker.with_suffix('.tmp')
            temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(self.marker)
        return self


def paths(root): return AppLayout(root)


def inspect_installation(root):
    layout=paths(root); findings=[];release=None
    try:
        if not layout.read_config(): raise ValueError('installation configuration is missing')
        selected=layout.current.resolve(strict=True)
        if selected.parent != layout.releases: raise ValueError('current must select one direct release')
        release=selected.name
        state=json.loads(layout.install_state.read_text())
        if not isinstance(state, dict) or state.get('current_release_id')!=release or state.get('package_root')!=str(selected):
            raise ValueError('current and installation receipt disagree')
        if (layout.root/'.pi').exists() or (layout.root/'.agents').exists():raise ValueError('old installation directories are unsupported')
    except (OSError,ValueError,RuntimeError) as error: findings.append({'code':'invalid_layout','message':str(error)})
    return {'schema_version':SCHEMA,'root':str(layout.root),'layout':'standalone','ok':not findings,'release_id':release,'findings':findings}
