import json
from pathlib import Path
from dataclasses import replace
import pytest
from notify_lib import delivery


def test_email_cli_starts_in_a_fresh_interpreter(tmp_path):
    import os
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / 'skills/email/scripts/email_cli.py'
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run(
        [sys.executable, str(script), '--help'], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert 'prepare' in result.stdout and 'send' in result.stdout


def fixture(root,monkeypatch):
    from research_agent.research.workspace import initialize_workspace, admit_research_workspace
    initialize_workspace(root, 'ws_email', 'research')
    admit_research_workspace(root)
    report=root/'reports/result.md';report.parent.mkdir(exist_ok=True);report.write_text('Evidence report')
    cfg=delivery.EmailNotificationConfig(source=root/'notifications.toml',enabled=True,recipient='reader@example.test',digest='config1',provider='smtp',from_address='sender@example.test')
    monkeypatch.setattr(delivery,'load_notification_config',lambda *args:cfg)
    request={'schema_version':'ts-user-notification/2','notification_id':'study-complete-report-v1',
             'recipient':cfg.recipient,'event':'study_completed','subject':'Results','summary':'See report',
             'report_refs':['reports/result.md'],'attachments':[{'ref':'reports/result.md','sha256':delivery.sha256_path(report),'size_bytes':report.stat().st_size}]}
    path=root/'request.json';path.write_text(json.dumps(request))
    return path,cfg


def test_retry_across_progress_and_password_rotation_does_not_resend(tmp_path,monkeypatch):
    request,cfg=fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(delivery,'_run_transport',lambda *args, **kwargs:calls.append(kwargs) or 'accepted')
    assert delivery.notify_user(tmp_path,request)['state']=='sent'
    from research_agent.research.nodes import create, update
    created = create(tmp_path, {"goal": "Track authorized report delivery"})
    update(tmp_path, {"node_id": created["node"]["id"], "note": "Progress changed",
        "progress": "Updated delivery explanation", "read_basis": created["read_basis"]})
    monkeypatch.setattr(delivery,'load_notification_config',lambda *args:replace(cfg,digest='rotated'))
    assert delivery.notify_user(tmp_path,request)['state']=='already_sent'
    assert len(calls)==1


def test_v1_requests_cannot_start_delivery(tmp_path, monkeypatch):
    request, _ = fixture(tmp_path, monkeypatch)
    value = json.loads(request.read_text()); value['schema_version'] = 'ts-user-notification/1'
    request.write_text(json.dumps(value))
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: pytest.fail('v1 transport started'))
    with pytest.raises(ValueError, match='schema_version'):
        delivery.notify_user(tmp_path, request)
    assert not (tmp_path / delivery.DELIVERY_DIR_REF).exists()



def test_unknown_delivery_and_changed_attachment_do_not_send(tmp_path,monkeypatch):
    request,_=fixture(tmp_path,monkeypatch);calls=[]
    def ambiguous(*args, **kwargs):
        calls.append(kwargs);raise delivery._DeliveryAmbiguous('connection lost after DATA')
    monkeypatch.setattr(delivery,'_run_transport',ambiguous)
    with pytest.raises(Exception,match='ambiguous'):delivery.notify_user(tmp_path,request)
    with pytest.raises(ValueError,match='unknown'):delivery.notify_user(tmp_path,request)
    assert len(calls)==1

    (tmp_path/'reports/result.md').write_text('changed')
    with pytest.raises(ValueError,match='attachment'):delivery.notify_user(tmp_path,request)
    assert len(calls)==1


@pytest.mark.parametrize('error', [OSError('after DATA'), ValueError('unexpected response'), RuntimeError('transport interrupted')])
def test_unclassified_transport_errors_never_become_retryable(tmp_path, monkeypatch, error):
    request, _ = fixture(tmp_path, monkeypatch); calls = []
    def fail(*args, **kwargs):
        calls.append(1); raise error
    monkeypatch.setattr(delivery, '_run_transport', fail)
    with pytest.raises(delivery.NotificationError) as caught:
        delivery.notify_user(tmp_path, request)
    assert caught.value.state == 'unknown'
    assert caught.value.retry_disposition == 'reconcile_only'
    with pytest.raises(ValueError, match='unknown'): delivery.notify_user(tmp_path, request)
    assert calls == [1]


def test_content_change_under_same_identity_is_rejected(tmp_path, monkeypatch):
    request, _ = fixture(tmp_path, monkeypatch); calls = []
    monkeypatch.setattr(delivery, '_run_transport', lambda *args, **kwargs: calls.append(1) or 'accepted')
    delivery.notify_user(tmp_path, request)
    value = json.loads(request.read_text()); value['summary'] = 'Changed report summary'
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='notification_id_reused'): delivery.notify_user(tmp_path, request)
    assert calls == [1]


def test_concurrent_delivery_and_crash_before_sent_receipt_do_not_resend(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    request, _ = fixture(tmp_path, monkeypatch); calls = []
    monkeypatch.setattr(delivery, '_run_transport', lambda *args, **kwargs: calls.append(1) or 'accepted')
    original = delivery._write_private_json
    def fail_sent(path, value, **kwargs):
        if value.get('state') == 'sent': raise OSError('crash before sent receipt')
        return original(path, value, **kwargs)
    monkeypatch.setattr(delivery, '_write_private_json', fail_sent)
    with pytest.raises(OSError): delivery.notify_user(tmp_path, request)
    monkeypatch.setattr(delivery, '_write_private_json', original)
    with pytest.raises(delivery.NotificationError) as caught:
        delivery.notify_user(tmp_path, request)
    assert caught.value.state == 'unknown' and calls == [1]
    # A separate authorized identity exercises concurrent first submission.
    value = json.loads(request.read_text()); value['notification_id'] = 'concurrent'
    request.write_text(json.dumps(value))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: delivery.notify_user(tmp_path, request), range(2)))
    assert {r['state'] for r in results} == {'sent', 'already_sent'}
    assert calls == [1, 1]


def test_clawemail_cleanup_failure_after_process_is_ambiguous(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    @contextmanager
    def temporary(**kwargs):
        yield str(tmp_path)
        raise OSError('cleanup interrupted after send')
    monkeypatch.setattr(delivery.tempfile, 'TemporaryDirectory', temporary)
    monkeypatch.setattr(delivery.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='accepted'))
    with pytest.raises(delivery._DeliveryAmbiguous):
        delivery._run_clawemail(tmp_path/'manager', recipient='reader@example.test', subject='Report', body='Result', attachments=[])


def load_cli():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / 'skills/email/scripts/email_cli.py'
    spec = importlib.util.spec_from_file_location('email_cli_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_journal_failure_after_send_never_resends(tmp_path, monkeypatch):
    import sys
    from research_agent.research import records as memory_records
    from research_agent.research.retrieval import search
    request, _ = fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: calls.append(1) or 'accepted')
    cli = load_cli()
    output = tmp_path / 'email-output.json'
    monkeypatch.setattr(sys, 'argv', ['email_cli', 'send', '--root', str(tmp_path),
        '--request-file', str(request), '--output', str(output)])
    original = memory_records.record_event
    def unavailable(*args, **kwargs):
        raise OSError('journal temporarily unavailable')
    monkeypatch.setattr(memory_records, 'record_event', unavailable)
    assert cli.main() == 0
    sent = json.loads(output.read_text())
    assert sent['state'] == 'sent' and 'journal_error' in sent
    assert len(list((tmp_path / 'operations/events').glob('*.json'))) == 1
    monkeypatch.setattr(memory_records, 'record_event', original)
    from research_agent.application.memory_context import read
    assert read(tmp_path)['projection']['pending'] == 0
    records = search(tmp_path, origin='runtime')['records']
    assert [row['kind'] for row in records] == ['delivery']
    assert calls == [1]  # Context recovery never calls the email transport.
    assert cli.main() == 0
    assert json.loads(output.read_text())['state'] == 'already_sent'
    assert calls == [1]
    assert search(tmp_path, origin='runtime')['total'] == 1


def test_rejected_email_is_recorded_without_transport(tmp_path, monkeypatch):
    import sys
    from research_agent.research.retrieval import search
    request, _ = fixture(tmp_path, monkeypatch)
    value = json.loads(request.read_text()); value['event'] = 'invalid'
    request.write_text(json.dumps(value))
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: pytest.fail('transport started'))
    output = tmp_path / 'rejected.json'
    monkeypatch.setattr(sys, 'argv', ['email_cli', 'prepare', '--root', str(tmp_path),
        '--request-file', str(request), '--output', str(output)])
    assert load_cli().main() == 2
    assert json.loads(output.read_text())['state'] == 'rejected'
    assert search(tmp_path, origin='runtime', query='rejected')['total'] == 1


def test_prepare_projection_failure_does_not_corrupt_send_request(tmp_path, monkeypatch, capsys):
    import sys
    from research_agent.research import records
    request, _ = fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: calls.append(1) or 'accepted')
    def unavailable(*args, **kwargs):
        raise OSError('journal unavailable')
    monkeypatch.setattr(records, 'record_event', unavailable)
    prepared = tmp_path / 'prepared.json'
    monkeypatch.setattr(sys, 'argv', ['email_cli', 'prepare', '--root', str(tmp_path),
        '--request-file', str(request), '--output', str(prepared)])
    assert load_cli().main() == 0
    assert 'journal_error' in json.loads(capsys.readouterr().out)
    assert 'journal_error' not in json.loads(prepared.read_text())
    assert delivery.notify_user(tmp_path, prepared)['state'] == 'sent'
    assert delivery.notify_user(tmp_path, prepared)['state'] == 'already_sent'
    assert calls == [1]


def test_event_persistence_failure_keeps_send_receipt_and_safe_retry(tmp_path, monkeypatch):
    import sys
    from research_agent.application import job_state
    from research_agent.research.retrieval import search
    request, _ = fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: calls.append(1) or 'accepted')
    persist = job_state.persist_event
    def unavailable(*args, **kwargs):
        raise OSError('event store unavailable')
    monkeypatch.setattr(job_state, 'persist_event', unavailable)
    output = tmp_path / 'send.json'
    monkeypatch.setattr(sys, 'argv', ['email_cli', 'send', '--root', str(tmp_path),
        '--request-file', str(request), '--output', str(output)])
    cli = load_cli()
    assert cli.main() == 0
    sent = json.loads(output.read_text())
    assert sent['state'] == 'sent' and sent['journal_error'] == 'event store unavailable'
    assert json.loads((tmp_path / sent['receipt_ref']).read_text())['state'] == 'sent'
    monkeypatch.setattr(job_state, 'persist_event', persist)
    assert cli.main() == 0
    assert json.loads(output.read_text())['state'] == 'already_sent'
    assert calls == [1]
    assert search(tmp_path, origin='runtime')['total'] == 1
