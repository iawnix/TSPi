"""Behavioral regression coverage for the executable scientific Skills."""
from pathlib import Path
import json
import subprocess
import sys
import os
import pytest

SKILLS=Path(__file__).resolve().parents[2]/'extensions/chemical/skills'


def test_xtb_failure_does_not_start_single_point(tmp_path):
    xyz=tmp_path/'water.xyz';xyz.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    fake=tmp_path/'xtb'
    fake.write_text('#!/bin/sh\nprintf "Hamiltonian GFN2-xTB\\nconvergence criteria satisfied after 3 iterations\\n| TOTAL ENERGY -5.0 Eh\\n* finished run on today\\n"\ncp input.xyz xtbopt.xyz\n')
    fake.chmod(0o755)
    out=tmp_path/'out'
    run=subprocess.run([sys.executable,str(SKILLS/'xtb/scripts/run.py'),'--xyz',str(xyz),'--executable',str(fake),'--task','opt-sp','--output-dir',str(out)],capture_output=True,text=True)
    assert run.returncode==1
    assert 'optimization did not converge' in run.stderr
    assert not (out/'sp').exists()
    assert json.loads((out/'result.json').read_text())['validated'] is False


@pytest.mark.parametrize('skill',['cf22d','xtb','gaussian'])
def test_installed_skill_entrypoint_does_not_import_host_or_provider(skill,tmp_path):
    import shutil
    installed=tmp_path/'skills'
    shutil.copytree(SKILLS/skill,installed/skill)
    shutil.copytree(SKILLS/'_shared',installed/'_shared')
    run=subprocess.run([sys.executable,str(installed/skill/'scripts/run.py'),'--help'],cwd=tmp_path,env={**os.environ,'PYTHONPATH':''},capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert '--task' in run.stdout


def test_cf22d_rejects_method_substitution_before_calculation(tmp_path):
    xyz=tmp_path/'water.xyz';xyz.write_text('1\natom\nH 0 0 0\n')
    run=subprocess.run([sys.executable,str(SKILLS/'cf22d/scripts/run.py'),'--xyz',str(xyz),'--xc','RHF','--task','sp','--output-dir',str(tmp_path/'out')],capture_output=True,text=True)
    assert run.returncode==1
    assert 'only permits xc=CF22D' in run.stderr
