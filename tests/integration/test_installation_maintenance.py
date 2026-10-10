"""Installation failure boundaries preserve the matching code and State."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socketserver
from threading import Thread
from types import SimpleNamespace

import pytest

from scripts import install_wizard as wizard
from research_agent.foundation.installation_maintenance import InstallationMaintenance, assert_installation_available

CONFIG = 'default_environment = "local"\n[environments.local]\nkind = "local"\n'


def test_exclusive_installation_and_durable_activation_window(tmp_path):
    maintenance = InstallationMaintenance(tmp_path).acquire()
    try:
        with pytest.raises(RuntimeError, match='maintenance_busy'):
            InstallationMaintenance(tmp_path).acquire()
        with pytest.raises(RuntimeError, match='maintenance_required'):
            assert_installation_available(tmp_path)
        assert maintenance.rollback_allowed
        maintenance.transition('starting')
        assert not maintenance.rollback_allowed
        with pytest.raises(RuntimeError, match='forward repair'):
            maintenance.transition('rolled_back')
        assert_installation_available(tmp_path)
    finally:
        maintenance.close()
    # A crash is represented by releasing the process lock without completion.
    with pytest.raises(RuntimeError, match='maintenance_required'):
        assert_installation_available(tmp_path)
    repair = InstallationMaintenance(tmp_path).acquire()
    try:
        assert repair.repairing and not repair.rollback_allowed
        repair.transition('starting')
        repair.transition('completed')
    finally:
        repair.close()
    assert_installation_available(tmp_path)


def test_interrupted_preparation_also_requires_forward_repair(tmp_path):
    first = InstallationMaintenance(tmp_path).acquire()
    first.close()
    repair = InstallationMaintenance(tmp_path).acquire()
    try:
        # The new process has no original in-memory configuration snapshot.
        assert repair.repairing and not repair.rollback_allowed
        with pytest.raises(RuntimeError, match='maintenance_required'):
            assert_installation_available(tmp_path)
    finally:
        repair.close()


def test_maintenance_rejects_a_symlink_record(tmp_path):
    outside = tmp_path/'outside.json'
    outside.write_text('{}')
    control = tmp_path/'var/state/installation'
    control.mkdir(parents=True)
    (control/'maintenance.json').symlink_to(outside)
    with pytest.raises(OSError, match='symbolic'):
        InstallationMaintenance(tmp_path).acquire()
    assert outside.read_text() == '{}'


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path/'install'
    workspace = tmp_path/'research/t001'
    (root/'releases/old').mkdir(parents=True)
    (root/'current').symlink_to('releases/old')
    control = root/'var/state/installation'
    control.mkdir(parents=True)
    (control/'install-state.json').write_text(json.dumps({'current_release_id':'old'}))
    credentials = root/'etc/pi/auth.json'
    credentials.parent.mkdir(parents=True)
    credentials.write_text('{"fixture":"private, never print"}\n')
    job_config = root/'etc/job.toml'
    job_config.write_text('# original fixture configuration\n'+CONFIG)
    (workspace/'research_map').mkdir(parents=True)
    original = {'workspace_id':'t001', 'nodes':[{'id':'n1','dependencies':[]}],
                'requirements':[{'id':'r1','status':'unmet'}]}
    context = workspace/'research_map/context.json'
    context.write_text(json.dumps(original))
    events = []
    state = {'failure':None}
    options = ['--install-root',str(root),'--workspace-root',str(workspace.parent),
               '--without-web','--service-scope','none','--non-interactive','--json']

    def prepare(args, _checks):
        wizard.validate_options(args)
        return {'operation':'update','release_id':(root/'current').resolve().name}
    def install(_args):
        assert_installation_available(root) if not (control/'maintenance.json').exists() else None
        events.append('install')
        (root/'releases/new').mkdir(exist_ok=True)
        return {'release_id':'new','package_root':str(root/'releases/new'),'runtime':{'python_executable': 'fixture-python'}}
    def publish(_root, result, **kwargs):
        assert events[-1] == 'stop'
        (root/'current').unlink()
        (root/'current').symlink_to('releases/new')
        (control/'install-state.json').write_text(json.dumps({'current_release_id':'new'}))
        job_config.write_text('# new fixture configuration\n'+CONFIG)
        return result
    def prepare_jobs(value, *_args):
        events.append('prepare-jobs')
        if state['failure'] == 'preparation':
            raise RuntimeError('fixture environment preparation failed')
        return value
    def verify(*_args):
        events.append('verify')
        if state['failure'] == 'configuration':
            raise RuntimeError('fixture configuration failure')
    def configure(_args, *, start=None):
        assert start is False
        with pytest.raises(RuntimeError, match='maintenance_required'):
            assert_installation_available(root)
        events.append('configure-units')
        return []
    def activate(*_args):
        assert events[-1] == 'inspect'
        assert_installation_available(root)
        events.append('activate')
        # A started runtime could accept new input before a later service fails.
        (workspace/'runtime-evidence.txt').write_text('new evidence')
        if state['failure'] == 'activation':
            raise RuntimeError('fixture second service failed')
        return []
    def inspect(_root):
        events.append('inspect')
        return {'operation':'update','release_id':(root/'current').resolve().name}
    monkeypatch.setattr(wizard,'collect_preflight',lambda:[])
    monkeypatch.setattr(wizard,'require_preflight',lambda *_a,**_k:None)
    monkeypatch.setattr(wizard,'_prepare_installation',prepare)
    monkeypatch.setattr(wizard,'stop_installation_services',lambda _args:events.append('stop'))
    monkeypatch.setattr(wizard,'run_install',install)
    from scripts import install_package
    monkeypatch.setattr(install_package, 'activate_prepared_package', publish)
    monkeypatch.setattr(wizard._job_install, 'plan', lambda *_a: {'inputs': {}})
    monkeypatch.setattr(wizard._job_install, 'prepare', prepare_jobs)
    monkeypatch.setattr(wizard._job_install, 'publish', lambda *_a: {'job': {'path': str(job_config), 'status':'configured'}})
    monkeypatch.setattr(wizard,'install_uninstaller',lambda *_a:None)
    for name in ('provision_pi_agent_configuration','configure_model_icons','configure_workspace_root',
                 'configure_service_runtime','configure_remote_host','configure_phone_connection',
                 'provision_service_credentials','configure_notification_config','configure_backend_configs'):
        monkeypatch.setattr(wizard,name,lambda *_a,**_k:{})
    monkeypatch.setattr(wizard,'prepare_app_server_runtime',lambda _root, **_k:root/'runtimes/pi')
    monkeypatch.setattr(wizard,'bind_pi_runtime_node_modules',lambda *_a:None)
    monkeypatch.setattr(wizard,'ensure_host_identity',lambda _root:None)
    monkeypatch.setattr(wizard,'verify_job_bindings',verify)
    monkeypatch.setattr(wizard,'configure_services',configure)
    monkeypatch.setattr(wizard,'activate_installed_services',activate)
    monkeypatch.setattr(wizard,'inspect_installation',inspect)
    return root, workspace, options, events, state, credentials.read_bytes()


def test_preparation_failure_keeps_old_runtime_available_without_stopping_services(installation):
    root, workspace, options, events, state, auth = installation
    state['failure'] = 'preparation'
    assert wizard.main(options) == 1
    assert 'stop' not in events
    assert (root/'current').resolve().name == 'old'
    assert (root/'etc/pi/auth.json').read_bytes() == auth
    assert_installation_available(root)


def test_deferred_maintenance_serializes_preparation_without_fencing_runtime(tmp_path):
    operation = InstallationMaintenance(tmp_path).acquire(defer=True)
    try:
        assert_installation_available(tmp_path)
        with pytest.raises(RuntimeError, match='busy'):
            InstallationMaintenance(tmp_path).acquire(defer=True)
        operation.transition('preparing')
        with pytest.raises(RuntimeError, match='maintenance_required'):
            assert_installation_available(tmp_path)
    finally:
        operation.close()


def test_failure_before_activation_restores_configuration_and_old_release(installation):
    root, workspace, options, events, state, auth = installation
    original = (workspace/'research_map/context.json').read_bytes()
    state['failure'] = 'configuration'
    assert wizard.main(options) == 1
    assert (root/'current').resolve().name == 'old'
    assert (root/'etc/job.toml').read_text() == '# original fixture configuration\n'+CONFIG
    assert (root/'etc/pi/auth.json').read_bytes() == auth
    assert (workspace/'research_map/context.json').read_bytes() == original
    assert 'activate' not in events
    assert_installation_available(root)


def test_failure_after_activation_retains_new_release_and_resumes(installation):
    root, workspace, options, events, state, auth = installation
    state['failure'] = 'activation'
    assert wizard.main(options) == 1
    assert (root/'current').resolve().name == 'new'
    assert (root/'etc/pi/auth.json').read_bytes() == auth
    context = json.loads((workspace/'research_map/context.json').read_text())
    assert context['requirements'] == [{'id':'r1','status':'unmet'}]
    assert context['nodes'] == [{'id':'n1','dependencies':[]}]
    assert events[-1] == 'stop'
    with pytest.raises(RuntimeError, match='maintenance_required'):
        assert_installation_available(root)
    assert (workspace/'runtime-evidence.txt').read_text() == 'new evidence'
    state['failure'] = None
    assert wizard.main(options) == 0
    assert (root/'current').resolve().name == 'new'
    assert (root/'etc/pi/auth.json').read_bytes() == auth
    assert_installation_available(root)


def test_stop_waits_for_all_installation_writers_but_never_stops_jobs(tmp_path, monkeypatch):
    units = tmp_path/'units'
    units.mkdir()
    for name in ('ts-web-research-agent.service','ts-app-server-research-agent.service','ts-app-server-research-agent@.service'):
        (units/name).touch()
    args = wizard.parse_args(['--install-root',str(tmp_path/'install'),'--service-scope','user'])
    monkeypatch.setattr(wizard,'validate_service_ownership',lambda _a:None)
    monkeypatch.setattr(wizard,'_service_unit_directory',lambda _s:units)
    monkeypatch.setattr(wizard,'app_server_service_instances',lambda _s:['ts-app-server-research-agent@old.service'])
    calls = []
    monkeypatch.setattr(wizard,'_run_systemctl',lambda _s,*args:calls.append(args))
    monkeypatch.setattr(wizard,'_service_status',lambda *_a:{'active':'inactive'})
    wizard.stop_installation_services(args)
    assert calls == [('stop','ts-web-research-agent.service'),('stop','ts-app-server-research-agent.service'),('stop','ts-app-server-research-agent@old.service')]
    monkeypatch.setattr(wizard,'_service_status',lambda *_a:{'active':'deactivating'})
    with pytest.raises(RuntimeError,match='did not stop'):
        wizard.stop_installation_services(args)


def test_service_readiness_checks_live_release_and_web_bridge(tmp_path, monkeypatch):
    from research_agent.bootstrap import launcher
    state = {'release':'old','web':{'error':'bridge unavailable'}}
    socket_path = tmp_path/'host.sock'
    token = tmp_path/'web.token'
    token.write_text('fixture-token')
    class Host(socketserver.StreamRequestHandler):
        def handle(self):
            request = json.loads(self.rfile.readline())
            assert request['method'] == 'initialize'
            self.wfile.write((json.dumps({'id':request['id'],'result':{'release_id':state['release']}})+'\n').encode())
    class Web(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            assert self.path == '/api/workspaces'
            assert self.headers.get('Authorization') == 'Bearer fixture-token'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(state['web']).encode())
    host = socketserver.UnixStreamServer(str(socket_path), Host)
    web = ThreadingHTTPServer(('127.0.0.1',0), Web)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (host,web)]
    for thread in threads:
        thread.start()
    try:
        installation = SimpleNamespace(package_root=tmp_path/'releases/new/agent')
        monkeypatch.setattr(launcher,'resolve_installation',lambda *_a:installation)
        monkeypatch.setattr(launcher,'resolve_host_socket',lambda *_a:socket_path)
        args = SimpleNamespace(install_root=str(tmp_path), service_scope='user',start_services=True,
                               with_web=True,web_host='127.0.0.1',web_port=web.server_port,
                               web_auth_token_file=str(token))
        installed = {'package_root':str(tmp_path/'releases/new'),'release_id':'new'}
        with pytest.raises(RuntimeError,match='release mismatch'):
            wizard.verify_running_services(args,installed,timeout_seconds=0)
        state['release'] = 'new'
        with pytest.raises(RuntimeError,match='invalid workspace catalog'):
            wizard.verify_running_services(args,installed,timeout_seconds=0)
        state['web'] = {'workspaces':[]}
        assert wizard.verify_running_services(args,installed,timeout_seconds=0)['status'] == 'verified'
    finally:
        for server, thread in zip((host,web),threads):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
        socket_path.unlink()
