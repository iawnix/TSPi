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


def test_report_bash_preserves_source_digests_and_accepts_empty_output(tmp_path):
    import hashlib
    source = tmp_path/'result.json'
    source.write_text(json.dumps({'method':'fixture','validated':True,'steps':[{'task':'sp','energy_hartree':-1}]}))
    out = tmp_path/'results'; out.mkdir()
    run = subprocess.run(['bash', '-c', 'exec "$@"', 'report', sys.executable,
                          str(SKILLS/'report/scripts/build.py'), '--result', f'local={source}',
                          '--output-dir', str(out)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    report = json.loads((out/'report.json').read_text())
    assert report['results'][0]['energy_hartree'] == -1
    assert report['sources'][0]['path'] == str(source)
    assert report['sources'][0]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (out/'report.md').is_file()


def test_report_refuses_to_overwrite_existing_output(tmp_path):
    source = tmp_path/'input.json'; source.write_text('{"validated":false}')
    out = tmp_path/'out'; out.mkdir()
    previous = out/'report.md'; previous.write_text('keep me')
    run = subprocess.run([sys.executable, str(SKILLS/'report/scripts/build.py'), '--result', f'local={source}',
                          '--output-dir', str(out)], capture_output=True, text=True)
    assert run.returncode != 0
    assert 'refusing to overwrite' in run.stderr
    assert previous.read_text() == 'keep me'
    assert not (out/'report.json').exists()
