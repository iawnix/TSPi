"""Behavioral regression coverage for the executable scientific Skills."""
from pathlib import Path
import json
import subprocess
import sys
import os
import pytest

SKILLS=Path(__file__).resolve().parents[2]/'domains/chemical/skills'


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
    assert json.loads((out/'result.json').read_text())['checks_passed'] is False


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
    assert run.returncode==2
    assert 'only permits xc=CF22D' in run.stderr
    assert not (tmp_path/'out').exists()


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


def test_report_reads_environment_from_job_identity_instead_of_method_label(tmp_path):
    job = tmp_path/'runs/jobs/job_test'; (job/'results').mkdir(parents=True)
    (tmp_path/'operations/jobs').mkdir(parents=True)
    (tmp_path/'operations/jobs/job_test.json').write_text(json.dumps({'job_id': 'job_test', 'platform': 'local'}))
    (job/'receipt.json').write_text(json.dumps({'job_id': 'job_test', 'cwd': str(job)}))
    (job/'results/result.json').write_text(json.dumps({'method': 'GFN2-xTB', 'validated': True, 'steps': [{'task': 'sp', 'energy_hartree': -5}]}))
    out = tmp_path/'report'
    run = subprocess.run([sys.executable, str(SKILLS/'report/scripts/build.py'), '--job', str(job), '--output-dir', str(out)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads((out/'report.json').read_text())['results'][0]
    assert result['environment'] == 'local' and result['method'] == 'GFN2-xTB'
    assert result['checks_passed'] is None
    assert result['scientific_validation'] == 'not_assessed'


@pytest.mark.parametrize('skill', ['cf22d', 'xtb', 'gaussian'])
@pytest.mark.parametrize('atom,multiplicity', [('H 0 0 0', '1'), ('H NaN 0 0', '2'), ('Qq 0 0 0', '2')])
def test_runners_reject_bad_geometry_or_electronic_state_before_execution(tmp_path, skill, atom, multiplicity):
    source = tmp_path/'input.xyz'; source.write_text('1\ninvalid input\n'+atom+'\n')
    marker = tmp_path/'executed'
    executable = tmp_path/'solver'
    executable.write_text(f'#!/bin/sh\ntouch "{marker}"\n'); executable.chmod(0o755)
    command = [sys.executable, str(SKILLS/skill/'scripts/run.py'), '--xyz', str(source),
               '--task', 'sp', '--multiplicity', multiplicity, '--output-dir', str(tmp_path/'out')]
    if skill != 'cf22d': command += ['--executable', str(executable)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert not marker.exists() and not (tmp_path/'out').exists()
    assert any(message in result.stderr for message in ('electron count', 'non-finite', 'element symbol'))


@pytest.mark.parametrize('skill', ['xtb', 'gaussian'])
def test_doublet_runner_and_report_separate_numeric_checks_from_scientific_acceptance(tmp_path, skill):
    source = tmp_path/'hydrogen.xyz'; source.write_text('1\nH atom\nH 0D0 0 0\n')
    program = tmp_path/'solver'
    if skill == 'xtb':
        body = 'printf "%s\\n" "$@" > args.txt\n'
        output = 'Hamiltonian GFN2-xTB\nconvergence criteria satisfied after 3 iterations\n| TOTAL ENERGY -0.4 Eh\n* finished run on today\n'
    else:
        body = 'cat > supplied.gjf\n'
        output = ' #p M062X/6-31G** SP SCF=Tight Int=UltraFine\n ----------------\n SCF Done: E(UM062X) = -0.4 A.U.\n Normal termination of Gaussian\n'
    program.write_text('#!/bin/sh\n'+body+"cat <<'RESULT'\n"+output+'RESULT\n'); program.chmod(0o755)
    out = tmp_path/'out'
    run = subprocess.run([sys.executable, str(SKILLS/skill/'scripts/run.py'), '--xyz', str(source),
                          '--task', 'sp', '--multiplicity', '2', '--executable', str(program),
                          '--output-dir', str(out)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    if skill == 'xtb':
        args = (out/'sp/args.txt').read_text().splitlines()
        assert args[args.index('--uhf')+1] == '1'
    else:
        assert '\n0 2\n' in (out/'sp/supplied.gjf').read_text()
    record = json.loads((out/'result.json').read_text())
    assert record['schema_version'] == 'science-result/2' and record['multiplicity'] == 2
    assert record['checks_passed'] is True and record['scientific_validation'] == 'not_assessed'
    assert 'validated' not in record and 'spin' not in record
    report = tmp_path/'report'
    made = subprocess.run([sys.executable, str(SKILLS/'report/scripts/build.py'), '--result',
                           'local='+str(out/'result.json'), '--output-dir', str(report)], capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    rows = json.loads((report/'report.json').read_text())['results']
    assert len(rows) == 1 and rows[0]['checks_passed'] is True
    assert rows[0]['scientific_validation'] == 'not_assessed'


def test_shared_xyz_reader_requires_explicit_frame_and_preserves_trajectory_identity(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('science_xyz', SKILLS/'_shared/xyz.py')
    xyz = importlib.util.module_from_spec(spec); spec.loader.exec_module(xyz)
    path = tmp_path/'trajectory.xyz'
    path.write_text('1\nenergy: -1.0\nH 0 0 0\n1\nenergy: -0.9\nH 1D0 0 0\n')
    with pytest.raises(ValueError, match='exactly one'):
        xyz.read_xyz(path)
    assert xyz.read_xyz(path, 'last') == [('H', 1.0, 0.0, 0.0)]
    assert xyz.xyz_frame_metadata(path)['frames'][1]['energy_hartree'] == -0.9
    path.write_text(path.read_text().replace('H 1D0', 'He 1D0'))
    with pytest.raises(ValueError, match='element order'):
        xyz.read_xyz_frames(path)
