"""Runtime identity, provenance and crash recovery do not depend on notes."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.unit.test_job_recovery import workspace
from research_agent.application.api import execute
from research_agent.application.execution import dispatch, _receipt
from research_agent.application.job_state import execution, observe_execution
from research_agent.application.job_monitor import command, assess
from research_agent.application.memory_context import read
from research_agent.research.nodes import create, update
from research_agent.foundation.transactions import TransactionCoordinator


def finished(root, *, code=0, session_id='session', job_id='job_one'):
    receipt=dispatch('start', {'root':str(root), 'job_id':job_id, 'session_id':session_id,
        'command':[sys.executable, '-c', f"from pathlib import Path;Path('result').write_text('observed');raise SystemExit({code})"],
        'outputs':[{'path':'result','required':True}]})
    for _ in range(200):
        status=dispatch('status', {'root':str(root),'job_id':receipt['job_id']})
        if status['state'] not in {'running','started','queued'}:break
        time.sleep(.02)
    assert status['state'] in {'succeeded','failed'}
    return receipt


def test_monitor_records_failure_without_note_and_cannot_cross_sessions(tmp_path):
    workspace(tmp_path)
    receipt=finished(tmp_path,code=23)
    command(tmp_path,'tick',{})
    row=execution(tmp_path,receipt['job_id'])
    assert row['state']=='failed' and row['exit_code']==23
    delivery=command(tmp_path,'pending',{})['deliveries'][0]
    assert assess(tmp_path,delivery['event_id'],'session')['admitted']
    with pytest.raises(ValueError, match='another workspace or session'):
        assess(tmp_path,delivery['event_id'],'wrong')
    node = create(tmp_path, {'goal':'Understand the failed calculation'})['node']
    update(tmp_path,{'node_id':node['id'],'note':'Waiting for user clarification.'})
    assert assess(tmp_path,delivery['event_id'],'session')['admitted']
    assert read(tmp_path)['uncollected_jobs'][0]['state']=='failed'


def test_collection_versions_and_material_provenance(tmp_path):
    workspace(tmp_path)
    job=finished(tmp_path)
    first=dispatch('collect',{'root':str(tmp_path),'job_id':job['job_id']})
    assert first['result_receipt']['collection_state']=='complete'
    assert all(a['provenance']['job_id']==job['job_id'] for a in first['artifacts'])
    assert dispatch('collect',{'root':str(tmp_path),'job_id':job['job_id']})['result_receipt']==first['result_receipt']
    Path(job['cwd'],'result').write_text('changed output')
    newer=dispatch('collect',{'root':str(tmp_path),'job_id':job['job_id']})
    assert newer['result_receipt']['receipt_id']!=first['result_receipt']['receipt_id']
    assert execution(tmp_path,job['job_id'])['latest_result_receipt_ref']==newer['result_receipt']['receipt_id']
    with pytest.raises(ValueError):
        execute('artifact.create',tmp_path,{'content':'fake','name':'result','job_id':job['job_id']})


def test_terminal_conflict_is_preserved_until_reconciled(tmp_path):
    workspace(tmp_path)
    job=finished(tmp_path)
    receipt=_receipt(tmp_path,{'job_id':job['job_id']})
    conflict=observe_execution(tmp_path,receipt,{'state':'failed','exit_code':23})
    assert conflict['code']=='job_terminal_conflict'
    assert execution(tmp_path,job['job_id'])['state']=='succeeded'
    snapshot = read(tmp_path)
    assert any(row.get('execution_conflict') == conflict for row in snapshot['running_jobs'] + snapshot['uncollected_jobs'])
    dispatch('reconcile',{'root':str(tmp_path),'job_id':job['job_id']})
    assert execution(tmp_path,job['job_id'])['execution_conflict'] is None


def test_lost_submission_receipt_never_resubmits(tmp_path, monkeypatch):
    from research_agent.jobs import LocalProcessPlatform
    workspace(tmp_path)
    calls=[]
    def lost(self,spec): calls.append(spec.job_id); raise RuntimeError('lost')
    monkeypatch.setattr(LocalProcessPlatform,'start',lost)
    request={'root':str(tmp_path),'job_id':'job_uncertain','command':['true']}
    with pytest.raises(RuntimeError): dispatch('start',request)
    assert dispatch('start',request)['state']=='unknown'
    assert len(calls)==1
    assert dispatch('status',{'root':str(tmp_path),'job_id':'job_uncertain'})['state']=='unknown'
    assert read(tmp_path)['running_jobs'][0]['state']=='unknown'


def test_collection_commit_recovers_as_one_transaction(tmp_path,monkeypatch):
    from research_agent.foundation import transactions
    workspace(tmp_path); job=finished(tmp_path)
    original=transactions._atomic_json
    armed=[True]
    def crash(path,value):
        if armed[0] and '/operations/results/' in str(path):
            armed[0]=False; raise OSError('crash during result publish')
        return original(path,value)
    monkeypatch.setattr(transactions,'_atomic_json',crash)
    with pytest.raises(OSError): dispatch('collect',{'root':str(tmp_path),'job_id':job['job_id']})
    TransactionCoordinator(tmp_path).recover()
    current=execution(tmp_path,job['job_id'])
    receipt=json.loads((tmp_path/'operations/results'/(current['latest_result_receipt_ref']+'.json')).read_text())
    assert current['collection_state']=='complete'
    assert receipt['artifact_refs']==current['artifact_refs']
    assert not read(tmp_path)['uncollected_jobs']


@pytest.mark.parametrize('command,params',[('research.change',{}),('job.start',{'attempt_id':'attempt_1'}),('job.status',{'attempt_id':'attempt_1'}),('artifact.link',{})])
def test_retired_interfaces_rejected(tmp_path,command,params):
    with pytest.raises(ValueError):execute(command,tmp_path,params)
