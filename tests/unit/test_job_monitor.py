import json
import sys
import time
from pathlib import Path
from tspi_runtime.execution import dispatch
from tspi_runtime.job_monitor import command
from tests.unit.test_job_recovery import workspace


def test_terminal_job_wakes_once_and_reclaims_failed_delivery(tmp_path):
    workspace(tmp_path)
    job=dispatch('start',{'root':str(tmp_path),'job_id':'job_wake','node_id':'node_1',
        'session_id':'session_original','command':[sys.executable,'-c','pass']})
    for _ in range(100):
        command(tmp_path,'tick',{})
        rows=command(tmp_path,'pending',{})['deliveries']
        if rows:break
        time.sleep(.02)
    assert len(rows)==1
    event_id=rows[0]['event_id']
    first=command(tmp_path,'claim',{'event_id':event_id,'channel':'wake'})
    assert first['claimed'] and first['session_id']=='session_original'
    assert command(tmp_path,'claim',{'event_id':event_id,'channel':'notify'})['claimed'] is False
    command(tmp_path,'complete',{'event_id':event_id,'channel':'wake','claim_token':first['claim_token'],'error':'host offline'})
    second=command(tmp_path,'claim',{'event_id':event_id,'channel':'wake'})
    assert second['request_id']==first['request_id']
    command(tmp_path,'complete',{'event_id':event_id,'channel':'wake','claim_token':second['claim_token'],'delivered':True})
    command(tmp_path,'tick',{})
    assert command(tmp_path,'pending',{})['deliveries']==[]


def test_deferred_delivery_retries_only_after_canonical_state_changes(tmp_path):
    from research_state.agent_workspace import read_liveness, checkpoint
    workspace(tmp_path)
    folder=tmp_path/'operations/monitors/monitor_fixture/deliveries'
    folder.mkdir(parents=True)
    state=read_liveness(tmp_path)
    token=f"{state['revision']}:{state.get('checkpoint_id')}"
    (folder/'event_fixture.json').write_text(json.dumps({'schema_version':'ts-job-monitor-delivery/1',
        'event_id':'event_fixture','session_id':'s','request_id':'job-wake:event_fixture','delivered':False,'deferred_state':token}))
    assert command(tmp_path,'pending',{})['deliveries']==[]
    checkpoint(tmp_path,{'principal':'root_agent','authority':'kernel_write','id':'checkpoint_continue',
                        'disposition':'continue_required','claim_ids':['claim_1']})
    assert len(command(tmp_path,'pending',{})['deliveries'])==1


def test_long_queue_emits_one_diagnostic_event_without_poll_wakes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from job_runtime import JobState
    from tspi_runtime import job_monitor
    workspace(tmp_path)
    dispatch('start',{'root':str(tmp_path),'job_id':'job_queue','node_id':'node_1','session_id':'s',
        'metadata':{'queue_wait_seconds':60},'command':[sys.executable,'-c','pass']})
    status = SimpleNamespace(state=JobState.QUEUED,exit_code=None,error=None,diagnostics={'wait_seconds':10})
    monkeypatch.setattr(job_monitor,'_runtime',lambda root:SimpleNamespace(job_status=lambda receipt:status))
    command(tmp_path,'tick',{})
    assert command(tmp_path,'pending',{})['deliveries']==[]
    status.diagnostics={'wait_seconds':61,'queue_diagnosis':'feasible procs: 0'}
    for _ in range(3):command(tmp_path,'tick',{})
    rows=command(tmp_path,'pending',{})['deliveries'];assert len(rows)==1
    event=command(tmp_path,'event',{'event_id':rows[0]['event_id']})
    assert event['status']['reason']=='queue_wait_exceeded'
    assert event['status']['diagnostics']['queue_diagnosis']=='feasible procs: 0'


def test_batches_are_stable_across_retry_and_new_events(tmp_path):
    workspace(tmp_path)
    folder=tmp_path/'operations/monitors/monitor_fixture/deliveries';folder.mkdir(parents=True)
    def add(name, **extra):
        (folder/f'{name}.json').write_text(json.dumps({'schema_version':'ts-job-monitor-delivery/1','event_id':name,'session_id':'s',
            'request_id':'job-wake:'+name,'delivered':False,**extra}))
    add('event_1');add('event_2')
    rows=command(tmp_path,'pending',{})['deliveries']
    assert rows[0]['request_id']==rows[1]['request_id']
    assert rows[0]['batch_event_ids']==['event_1','event_2']
    add('event_3')
    again=command(tmp_path,'pending',{})['deliveries']
    assert again[:2]==rows
    assert again[2]['request_id']!=rows[0]['request_id']
    add('event_old',claim_token='uncertain-rpc',batch_event_ids=['event_old'])
    old=command(tmp_path,'pending',{})['deliveries'][-1]
    assert old['request_id']=='job-wake:event_old'


def test_monitor_status_observes_outbox_without_claiming_or_batching(tmp_path):
    workspace(tmp_path)
    folder = tmp_path/'operations/monitors/monitor_fixture'
    (folder/'deliveries').mkdir(parents=True)
    (folder/'binding.json').write_text(json.dumps({'schema_version':'ts-job-monitor/1','monitor_id':'monitor_fixture','session_id':'s', 'job_id':'job_fixture','attempt_id':'attempt_fixture','job_digest':'sha256:'+'a'*64}))
    pending = folder/'deliveries/event_pending.json'
    pending.write_text(json.dumps({'schema_version':'ts-job-monitor-delivery/1','event_id':'event_pending','session_id':'s','request_id':'wake_pending','delivered':False}))
    (folder/'deliveries/event_done.json').write_text(json.dumps({'schema_version':'ts-job-monitor-delivery/1','event_id':'event_done','session_id':'s','delivered':True}))
    before = pending.read_bytes()
    result = command(tmp_path,'status',{})
    assert [row['event_id'] for row in result['pending_deliveries']] == ['event_pending']
    assert result['pending_deliveries'][0]['session_id'] == 's'
    assert pending.read_bytes() == before


def test_old_monitor_records_are_rejected_without_conversion(tmp_path):
    import pytest
    workspace(tmp_path)
    folder = tmp_path/'operations/monitors/monitor_fixture'
    (folder/'deliveries').mkdir(parents=True)
    binding = folder/'binding.json'
    binding.write_text(json.dumps({'schema_version': 'ts-compute-monitor/1', 'intent_id': 'calc_1'}))
    original = binding.read_bytes()
    with pytest.raises(ValueError, match='monitor_binding_schema_invalid'):
        command(tmp_path, 'list', {})
    assert 'monitor_binding_schema_invalid' in command(tmp_path, 'tick', {})['registration_errors'][0]
    assert binding.read_bytes() == original
    delivery = folder/'deliveries/event_old.json'
    delivery.write_text(json.dumps({'schema_version': 'ts-monitor-delivery/1', 'event_id':'event_old'}))
    with pytest.raises(ValueError, match='monitor_delivery_schema_invalid'):
        command(tmp_path, 'pending', {})
