from pathlib import Path
import json
import sys
import time
import pytest
from research_agent.jobs import JobSpec, JobOutput, LocalProcessPlatform, JobState
from research_agent.application.execution import dispatch
from research_agent.research.workspace import admit_research_workspace
from research_agent.application.job_state import execution
from research_agent.artifacts.registry import manifests
from research_agent.research.workspace import initialize_workspace


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


def test_same_job_name_in_distinct_directories_does_not_reuse_a_terminal_observation(tmp_path):
    platform = LocalProcessPlatform()
    first = tmp_path / 'first'; first.mkdir()
    second = tmp_path / 'second'; second.mkdir()
    old = platform.start(JobSpec(command=(sys.executable, '-c', 'pass'), cwd=first, job_id='job_same'))
    wait_reaped(old)
    assert platform.status(old).state == JobState.SUCCEEDED
    new = platform.start(JobSpec(command=(sys.executable, '-c', 'import time; time.sleep(.3); raise SystemExit(23)'),
                                 cwd=second, job_id='job_same'))
    try:
        assert platform.status(new).state == JobState.RUNNING
    finally:
        wait_reaped(new)
    assert platform.status(new).state == JobState.FAILED
    assert platform.status(old).state == JobState.SUCCEEDED


def workspace(root):
    initialize_workspace(root, 'ws_jobs', 'research')
    admit_research_workspace(root)


def test_job_attempt_collection_and_repeated_request_are_durable(tmp_path):
    workspace(tmp_path)
    source=tmp_path/'in.txt';source.write_text('input')
    request={'root':str(tmp_path),'job_id':'job_test','command':[sys.executable,'-c',"from pathlib import Path;Path('result').write_text(Path('data/source').read_text())"],
        'inputs':[{'source':str(source),'destination':'data/source'}], 'outputs':[{'path':'result','required':True,'min_bytes':1}]}
    receipt=dispatch('start',request)
    assert dispatch('start',request)['job_id']==receipt['job_id']
    for _ in range(100):
        if dispatch('status',{'root':str(tmp_path),'job_id':'job_test'})['state']!='running':break
        time.sleep(.02)
    result=dispatch('collect',{'root':str(tmp_path),'job_id':'job_test'})
    materials=list(manifests(tmp_path))
    assert execution(tmp_path, receipt['job_id'])['state']=='succeeded'
    assert result['output_validation']['complete']
    assert len(materials)>=2
    assert all(a['provenance']['job_id']==receipt['job_id'] for a in materials)
    again=dispatch('collect',{'root':str(tmp_path),'job_id':'job_test'})
    assert len(list(manifests(tmp_path)))==len(materials)
    with pytest.raises(ValueError,match='different parameters'):
        dispatch('start',{**request,'command':[sys.executable,'-c','pass']})


def test_caller_request_id_replays_without_submitting_again(tmp_path):
    workspace(tmp_path)
    request = {
        'root': str(tmp_path), 'request_id': 'skill_stable_submission',
        'command': [sys.executable, '-c', "from pathlib import Path; p=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"],
    }
    first = dispatch('start', request)
    for _ in range(100):
        if dispatch('status', {'root': str(tmp_path), 'job_id': first['job_id']})['state'] != 'running':
            break
        time.sleep(.02)
    second = dispatch('start', request)
    assert second['job_id'] == first['job_id']
    assert (Path(first['cwd']) / 'count').read_text() == '1'
    assert len(list((tmp_path/'operations/executions').glob('*.json'))) == 1


def test_terminal_receipt_arrives_during_supervisor_liveness_check(tmp_path, monkeypatch):
    from research_agent.jobs import JobReceipt
    from research_agent.jobs import local
    receipt=JobReceipt('job_race','local','now',('true',),str(tmp_path),123,
                       {'supervised':True,'supervisor_start':'original'})
    def process_disappeared(pid):
        (tmp_path/'status.json').write_text(json.dumps({'job_id':'job_race','state':'succeeded','exit_code':0}))
        return None
    monkeypatch.setattr(local,'identity',process_disappeared)
    assert LocalProcessPlatform().status(receipt).state == JobState.SUCCEEDED
