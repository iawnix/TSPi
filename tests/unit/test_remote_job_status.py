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
