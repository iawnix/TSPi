import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT/'domains/chemical/skills/gaussian/scripts'
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS.parents[1]/'_shared')]
spec = importlib.util.spec_from_file_location('gaussian_input_job', SCRIPTS/'input_job.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def gjf(path, route='Opt=(TS,CalcFC) Freq'):
    path.write_text('%nprocshared=12\n%mem=4000MB\n%chk=ts.chk\n#p M062X/6-31G** '+route+'\n\nfixture\n\n0 1\nO 0 0 0\nH 0 0 1\nH 0 1 0\n\n')
    return path


def test_explicit_gaussian_input_preserves_ts_and_irc_routes(tmp_path):
    for route in ['Opt=(TS,CalcFC) Freq', 'IRC=(Forward,CalcFC,MaxPoints=10)', 'Opt=QST2', 'Opt=ModRedundant']:
        path = gjf(tmp_path/'input.gjf', route)
        value = helper.inspect_input(path, 'M062X', '6-31G**', 0, 1, 12, 4000)
        assert route in value['routes'][0]
    with pytest.raises(ValueError, match='method/basis'):
        helper.inspect_input(path, 'HF', '6-31G**', 0, 1, 12, 4000)
    with pytest.raises(ValueError, match='nprocshared'):
        helper.inspect_input(path, 'M062X', '6-31G**', 0, 1, 24, 4000)
    path.write_text(path.read_text().replace('%chk=ts.chk', '%chk=../escape.chk'))
    with pytest.raises(ValueError, match='relative staged'):
        helper.inspect_input(path, 'M062X', '6-31G**', 0, 1, 12, 4000)


def test_normal_exit_without_frequency_does_not_validate_a_saddle(tmp_path):
    path = gjf(tmp_path/'input.gjf')
    program = tmp_path/'gaussian'
    program.write_text("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' ' #p M062X/6-31G** Opt=(TS,CalcFC) Freq' ' ----------------' ' SCF Done: E(RM062X) = -76.0 A.U.' ' Normal termination of Gaussian'\n")
    program.chmod(0o755)
    output = tmp_path/'out'
    result = subprocess.run([sys.executable, str(SCRIPTS/'run.py'), '--input-gjf', str(path),
        '--executable', str(program), '--output-dir', str(output), '--threads', '12', '--memory-mb', '4000',
        '--validation', 'saddle'], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    record = json.loads((output/'result.json').read_text())
    assert record['program_returncode'] == 0
    assert record['scientific_validation'] == 'not_assessed'
    assert record['checks_passed'] is False
    assert 'stationary point' in record['error']['message']
    assert (output/'input.gjf').read_bytes() == path.read_bytes()


def test_input_validation_never_starts_gaussian_with_missing_dependency(tmp_path):
    path = gjf(tmp_path/'input.gjf', 'IRC=(Forward,ReadFC)')
    path.write_text('%oldchk=missing.chk\n'+path.read_text())
    marker = tmp_path/'executed'
    program = tmp_path/'g16'; program.write_text(f'#!/bin/sh\ntouch "{marker}"\n'); program.chmod(0o755)
    from argparse import Namespace
    with pytest.raises(ValueError, match='missing staged'):
        helper.run_input(Namespace(input_gjf=str(path),method='M062X',basis='6-31G**',charge=0,multiplicity=1,
            threads=12,memory_mb=4000,output_dir=str(tmp_path/'out'),executable=str(program),validation='irc'))
    assert not marker.exists()


def test_xyz_shortcut_rejects_ignored_scientific_validation(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPTS/'run.py'), '--xyz', str(tmp_path/'input.xyz'),
        '--task', 'opt', '--validation', 'saddle', '--executable', 'unused',
        '--output-dir', str(tmp_path/'out')], capture_output=True, text=True)
    assert result.returncode == 2
    assert '--validation requires --input-gjf' in result.stderr


def test_prepared_gaussian_request_tracks_checkpoint_and_collection(tmp_path, mock_environment_probe):
    from research_agent.application.executors import prepare
    config = tmp_path/'job.toml'
    config.write_text('''default_environment = "local"
[environments.local]
kind = "local"
[environments.local.python]
manager = "conda"
conda_executable = "/opt/conda/bin/conda"
prefix = "/opt/runner"
lock_ref = "/opt/locks/runner.lock"
[environments.local.backends.gaussian]
command = ["/opt/g16"]
''')
    source = gjf(tmp_path/'input.gjf', 'IRC=(Forward,ReadFC)')
    checkpoint = tmp_path/'previous.chk'; checkpoint.write_bytes(b'checkpoint version 1')
    def request(collect=()):
        return prepare(config, 'local', 'chemical.gaussian-input', '1', {'input': source}, ['--validation', 'irc'],
            dependencies=[str(checkpoint)+'=previous.chk'], collect=['results/' + name for name in collect])
    first = request(['irc.chk'])
    assert first == request(['irc.chk'])
    assert any(item['source'] == str(checkpoint) and item['destination'] == 'previous.chk' and len(item['sha256']) == 64 for item in first['inputs'])
    assert any(item['path'] == 'results/irc.chk' and item['required'] for item in first['outputs'])
    assert request()['request_id'] != first['request_id']
    checkpoint.write_bytes(b'checkpoint version 2')
    assert request(['irc.chk'])['request_id'] != first['request_id']


def test_fixed_width_tight_wrap_and_primary_failure(tmp_path):
    from gaussian_io import parse_log, compact_route
    expected = '#p M062X/6-31G** Opt=(TS,CalcFC,NoEigenTest,MaxCycles=200) Freq SCF=Tight Int=UltraFine'
    log = tmp_path/'gaussian.out'
    log.write_text(expected.replace('SCF=Tight', 'SCF=Ti\n ght') + '\n ----------------\n'
                   ' Optimization stopped.\n -- Number of steps exceeded, NStep=114\n'
                   ' Error termination via Lnk1e\n Error: segmentation violation\n')
    summary = parse_log(log, expected_route=expected)['summary']
    assert summary['route_expectation']['matched']
    assert summary['primary_failure']['kind'] == 'optimization_limit'
    assert any(d['kind']=='signal' for d in summary['diagnostics'])
    assert compact_route(expected) != compact_route(expected.replace('SCF=Tight','SCF=Loose'))


@pytest.mark.parametrize('target', ['route', 'title'])
def test_reject_coordinate_in_route_or_title_before_dispatch(tmp_path, target):
    path = gjf(tmp_path/'input.gjf')
    old = ' Freq\n\n' if target == 'route' else 'fixture\n\n'
    path.write_text(path.read_text().replace(old, old[:-1] + 'H 2.45 2.00 -0.64\n\n'))
    with pytest.raises(ValueError, match='coordinate record in route/title'):
        helper.inspect_input(path, 'M062X','6-31G**',0,1,12,4000)
