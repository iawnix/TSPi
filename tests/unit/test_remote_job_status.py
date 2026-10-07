from pathlib import Path
import subprocess
import pytest
from job_runtime import TorqueSSHPlatform, JobReceipt, JobState


def platform():return TorqueSSHPlatform({'ssh_host':'fixture','remote_root':'/scratch'})
def receipt(root):return JobReceipt('job_remote','remote','now',('true',),str(root),metadata={'scheduler_id':'123.cluster','remote_dir':'/scratch/job_remote'})


@pytest.mark.parametrize('scheduler,expected',[('Q',JobState.QUEUED),('R',JobState.RUNNING),('H',JobState.HELD),('unrecognized',JobState.UNKNOWN)])
def test_scheduler_states_are_not_all_running(tmp_path,monkeypatch,scheduler,expected):
    remote=platform()
    def run(command,**kwargs):
        if 'status.exit' in command:return subprocess.CompletedProcess([],1,'','')
        return subprocess.CompletedProcess([],0,'Job Id: 123.cluster\n job_state = '+scheduler,'')
    monkeypatch.setattr(remote,'_run_ssh',run)
    assert remote.status(receipt(tmp_path)).state==expected


def test_exit_receipt_wins_over_scheduler_listing(tmp_path,monkeypatch):
    remote=platform()
    def run(command,**kwargs):
        assert 'status.exit' in command
        return subprocess.CompletedProcess([],0,'17\n','')
    monkeypatch.setattr(remote,'_run_ssh',run)
    status=remote.status(receipt(tmp_path))
    assert status.state==JobState.FAILED and status.exit_code==17


def test_failed_qdel_does_not_claim_cancellation(tmp_path,monkeypatch):
    remote=platform()
    def run(command,**kwargs):
        if 'status.exit' in command:return subprocess.CompletedProcess([],1,'','')
        if 'qdel' in command:return subprocess.CompletedProcess([],1,'','scheduler unavailable')
        return subprocess.CompletedProcess([],0,' job_state = R','')
    monkeypatch.setattr(remote,'_run_ssh',run)
    assert remote.cancel(receipt(tmp_path)).state==JobState.UNKNOWN


def test_reconcile_recovers_submission_without_calling_qsub(tmp_path,monkeypatch):
    import json
    remote=platform()
    (tmp_path/'spec.json').write_text(json.dumps({'command':['true'],'attempt_id':'attempt_1','node_id':'node_1'}))
    def run(command,**kwargs):
        assert 'qsub' not in command and 'scheduler.id' in command
        return subprocess.CompletedProcess([],0,'123.cluster\n','')
    monkeypatch.setattr(remote,'_run_ssh',run)
    recovered=remote.recover_receipt('job_remote',tmp_path)
    assert recovered.metadata['scheduler_id']=='123.cluster'
    assert recovered.attempt_id=='attempt_1'


@pytest.mark.parametrize('code,expected', [(125, JobState.FAILED), (0, JobState.SUCCEEDED)])
def test_scheduler_exit_recovers_job_that_could_not_write_receipt(tmp_path, monkeypatch, code, expected):
    remote = platform()
    def run(command, **kwargs):
        if 'status.exit' in command:
            return subprocess.CompletedProcess([], 1, '', '')
        return subprocess.CompletedProcess([], 0, f'Job Id: 123.cluster\n job_state = C\n exit_status = {code}\n', '')
    monkeypatch.setattr(remote, '_run_ssh', run)
    status = remote.status(receipt(tmp_path))
    assert status.state == expected and status.exit_code == code
    assert 'scheduler' in status.error
    # Durable terminal state survives a new platform instance without SSH.
    recovered = platform()
    monkeypatch.setattr(recovered, '_run_ssh', lambda *a, **k: pytest.fail('must reuse receipt'))
    assert recovered.status(receipt(tmp_path)).exit_code == code


def test_queue_diagnosis_preserves_normal_wait_and_explains_resources(tmp_path, monkeypatch):
    remote = TorqueSSHPlatform({'ssh_host':'fixture','remote_root':'/scratch','commands':{'checkjob':'checkjob'}})
    def run(command, **kwargs):
        if 'status.exit' in command: return subprocess.CompletedProcess([],1,'','')
        if command.startswith('checkjob'): return subprocess.CompletedProcess([],0,'idle procs: 224 feasible procs: 0\nRejection Reasons: Features','')
        return subprocess.CompletedProcess([],0,'Job Id: 123.cluster\n job_state = Q\n queue = batch\n','')
    monkeypatch.setattr(remote,'_run_ssh',run)
    status = remote.status(receipt(tmp_path))
    assert status.state == JobState.QUEUED and status.error is None
    assert status.diagnostics['queue'] == 'batch'
    assert 'feasible procs: 0' in status.diagnostics['queue_diagnosis']


def test_optional_diagnostic_timeout_does_not_erase_queue_state(tmp_path, monkeypatch):
    remote = TorqueSSHPlatform({'ssh_host':'fixture','remote_root':'/scratch','commands':{'checkjob':'checkjob'}})
    def run(command, **kwargs):
        if 'status.exit' in command:return subprocess.CompletedProcess([],1,'','')
        if command.startswith('checkjob'):raise subprocess.TimeoutExpired(command,1)
        return subprocess.CompletedProcess([],0,'job_state = Q\nqueue = test\n','')
    monkeypatch.setattr(remote,'_run_ssh',run)
    status=remote.status(receipt(tmp_path))
    assert status.state==JobState.QUEUED and status.error is None
    assert 'diagnosis_error' in status.diagnostics
