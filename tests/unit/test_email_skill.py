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
