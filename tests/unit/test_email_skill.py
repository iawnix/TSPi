import json
from pathlib import Path
from dataclasses import replace
import pytest
from notify_lib import delivery


def test_email_cli_starts_in_a_fresh_interpreter(tmp_path):
    import os
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / 'extensions/email/scripts/email_cli.py'
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run(
        [sys.executable, str(script), '--help'], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert 'prepare' in result.stdout and 'send' in result.stdout


def fixture(root,monkeypatch):
    (root/'workspace_manifest.json').write_text(json.dumps({'workspace_id':'ws_email','research_state':{'revision':1}}))
    report=root/'reports/result.md';report.parent.mkdir();report.write_text('Evidence report')
    cfg=delivery.EmailNotificationConfig(source=root/'notifications.toml',enabled=True,recipient='reader@example.test',digest='config1',provider='smtp',from_address='sender@example.test')
    monkeypatch.setattr(delivery,'load_notification_config',lambda *args:cfg)
    request={'schema_version':'ts-user-notification/2','notification_id':'study-complete-report-v1',
             'recipient':cfg.recipient,'event':'study_completed','subject':'Results','summary':'See report',
             'report_refs':['reports/result.md'],'attachments':[{'ref':'reports/result.md','sha256':delivery.sha256_path(report),'size_bytes':report.stat().st_size}]}
    path=root/'request.json';path.write_text(json.dumps(request))
    return path,cfg


def test_retry_across_revision_and_password_rotation_does_not_resend(tmp_path,monkeypatch):
    request,cfg=fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(delivery,'_run_transport',lambda *args, **kwargs:calls.append(kwargs) or 'accepted')
    assert delivery.notify_user(tmp_path,request)['state']=='sent'
    (tmp_path/'workspace_manifest.json').write_text(json.dumps({'workspace_id':'ws_email','research_state':{'revision':99}}))
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


@pytest.mark.parametrize('state', ['sent', 'unknown', 'sending'])
def test_historical_v2_digest_is_reconciled_without_rewrite_or_resend(tmp_path, monkeypatch, state):
    request, cfg = fixture(tmp_path, monkeypatch)
    value = json.loads(request.read_text())
    normalized = {'schema_version': 'ts-user-notification/1', 'event': value['event'],
                  'subject': value['subject'], 'summary': value['summary'] + '\n', 'workspace_id': 'ws_email',
                  'report_artifacts': value['attachments'], 'notification_id': value['notification_id'],
                  'recipient': cfg.recipient}
    digest = delivery.sha256_json(normalized)
    directory = tmp_path / delivery.DELIVERY_DIR_REF; directory.mkdir(parents=True)
    path = directory / (digest.removeprefix('sha256:') + '.json')
    receipt = {'schema_version': delivery.RECEIPT_SCHEMA, 'state': state,
               'notification_digest': digest, 'notification_id': value['notification_id']}
    path.write_text(json.dumps(receipt)); original = path.read_bytes()
    monkeypatch.setattr(delivery, '_run_transport', lambda *a, **kw: pytest.fail('historical transport restarted'))
    if state == 'sent':
        assert delivery.notify_user(tmp_path, request)['state'] == 'already_sent'
    elif state == 'sending':
        with pytest.raises(delivery.NotificationError) as caught:
            delivery.notify_user(tmp_path, request)
        assert caught.value.state == 'unknown'
        current = json.loads(path.read_text())
        assert current['notification_digest'] == digest
        assert current['state'] == 'unknown'
        return
    else:
        with pytest.raises(ValueError, match='unknown|sending'):
            delivery.notify_user(tmp_path, request)
    assert path.read_bytes() == original


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
