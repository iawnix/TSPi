from pathlib import Path
import json
import sys
import time
import pytest
from job_runtime import JobSpec, JobOutput, LocalProcessPlatform, JobState
from tspi_runtime.execution import dispatch
from research_state.agent_workspace import admit_workspace, apply_change, read_context
from research_state.workspace import initialize_workspace


def wait_reaped(receipt):
    # Check the OS, without poll()/wait()/status() helping the owner reap.
    deadline = time.monotonic() + 5
    while Path(f"/proc/{receipt.pid}").exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert not Path(f"/proc/{receipt.pid}").exists(), "supervisor was not reaped"


@pytest.mark.parametrize('code', [0, 23])
def test_exit_receipt_survives_without_status_polling(tmp_path, code):
    first=LocalProcessPlatform()
    receipt=first.start(JobSpec(command=(sys.executable,'-c',f'raise SystemExit({code})'),cwd=tmp_path))
    wait_reaped(receipt)
    recovered=LocalProcessPlatform().status(receipt)
    assert recovered.state==(JobState.FAILED if code else JobState.SUCCEEDED)
    assert recovered.exit_code==code


def test_timeout_enforced_without_polling_and_restart_cancel(tmp_path):
    first=LocalProcessPlatform()
    receipt=first.start(JobSpec(command=(sys.executable,'-c','import time;time.sleep(30)'),cwd=tmp_path,timeout_seconds=.15))
    wait_reaped(receipt)
    assert LocalProcessPlatform().status(receipt).state==JobState.TIMED_OUT
    second=tmp_path/'cancel';second.mkdir()
    receipt=first.start(JobSpec(command=(sys.executable,'-c','import time;time.sleep(30)'),cwd=second))
    try:assert LocalProcessPlatform().cancel(receipt).state==JobState.CANCELLED
    finally:wait_reaped(receipt)


def test_missing_or_empty_outputs_do_not_rewrite_exit_code(tmp_path):
    runtime=LocalProcessPlatform()
    receipt=runtime.start(JobSpec(command=(sys.executable,'-c',"open('empty','w').close()"),cwd=tmp_path,
        outputs=(JobOutput('empty',required=True,min_bytes=1),JobOutput('missing',required=True))))
    wait_reaped(receipt)
    result=runtime.collect(receipt)
    assert result['status']['exit_code']==0
    assert result['output_validation']=={'complete':False,'errors':[{'path':'empty','error':'too_small'},{'path':'missing','error':'missing'}]}


def workspace(root):
    initialize_workspace(root,'ws_jobs','research');admit_workspace(root,{'authority':'host'})
    apply_change(root,{'principal':'root_agent','authority':'kernel_write','operations':[
        {'type':'create_claim','id':'claim_1','statement':'water energy'},
        {'type':'create_node','id':'node_1','title':'Calculation','objective':'water energy','completion_exemption':'Unit fixture checks execution only','claim_ids':['claim_1']},
        {'type':'set_focus','claim_ids':['claim_1'],'node_ids':['node_1']},
        {'type':'create_strategy_plan','id':'strategy_1','claim_id':'claim_1','node_id':'node_1','objective':'Run','rationale':'Need evidence'}]})


def test_job_attempt_collection_and_repeated_request_are_durable(tmp_path):
    workspace(tmp_path)
    source=tmp_path/'in.txt';source.write_text('input')
    request={'root':str(tmp_path),'job_id':'job_test','node_id':'node_1','command':[sys.executable,'-c',"from pathlib import Path;Path('result').write_text(Path('data/source').read_text())"],
        'inputs':[{'source':str(source),'destination':'data/source'}], 'outputs':[{'path':'result','required':True,'min_bytes':1}]}
    receipt=dispatch('start',request)
    assert receipt['attempt_id']
    assert dispatch('start',request)['job_id']==receipt['job_id']
    for _ in range(100):
        if dispatch('status',{'root':str(tmp_path),'job_id':'job_test'})['state']!='running':break
        time.sleep(.02)
    result=dispatch('collect',{'root':str(tmp_path),'job_id':'job_test'})
    ctx=read_context(tmp_path)
    assert len(ctx['attempts'])==1 and ctx['attempts'][0]['state']=='succeeded'
    assert result['output_validation']['complete']
    assert len(ctx['artifacts'])>=2
    assert all(a['producer_attempt_id']==receipt['attempt_id'] for a in ctx['artifacts'])
    again=dispatch('collect',{'root':str(tmp_path),'job_id':'job_test'})
    assert len(read_context(tmp_path)['artifacts'])==len(ctx['artifacts'])
    with pytest.raises(ValueError,match='different parameters'):
        dispatch('start',{**request,'command':[sys.executable,'-c','pass']})


def test_collected_artifact_link_is_persisted(tmp_path):
    workspace(tmp_path)
    from tspi_runtime.evidence import dispatch as artifact
    created=artifact('create',{'root':str(tmp_path),'content':'raw evidence','node_id':'node_1'})
    link=artifact('link',{'root':str(tmp_path),'artifact_id':created['artifact_id'],'subject_id':'claim_1','relation':'documents'})
    assert read_context(tmp_path)['evidence_links'][0]['id']==link['id']
    artifact('link',{'root':str(tmp_path),'artifact_id':created['artifact_id'],'subject_id':'claim_1','relation':'documents'})
    assert len(read_context(tmp_path)['evidence_links'])==1


def test_caller_request_id_replays_without_submitting_again(tmp_path):
    workspace(tmp_path)
    request = {
        'root': str(tmp_path), 'request_id': 'skill_stable_submission',
        'node_id': 'node_1',
        'command': [sys.executable, '-c', "from pathlib import Path; p=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"],
    }
    first = dispatch('start', request)
    for _ in range(100):
        if dispatch('status', {'root': str(tmp_path), 'job_id': first['job_id']})['state'] != 'running':
            break
        time.sleep(.02)
    second = dispatch('start', request)
    assert second['job_id'] == first['job_id']
    assert second['attempt_id'] == first['attempt_id']
    assert (Path(first['cwd']) / 'count').read_text() == '1'
    assert len(read_context(tmp_path)['attempts']) == 1


def test_terminal_receipt_arrives_during_supervisor_liveness_check(tmp_path, monkeypatch):
    from job_runtime import JobReceipt
    from job_runtime import local
    receipt=JobReceipt('job_race','local','now',('true',),str(tmp_path),123,
                       {'supervised':True,'supervisor_start':'original'})
    def process_disappeared(pid):
        (tmp_path/'status.json').write_text(json.dumps({'job_id':'job_race','state':'succeeded','exit_code':0}))
        return None
    monkeypatch.setattr(local,'identity',process_disappeared)
    assert LocalProcessPlatform().status(receipt).state == JobState.SUCCEEDED
