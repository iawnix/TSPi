"""Synthetic Gaussian records test evidence selection, not computed chemistry."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

SKILLS = Path(__file__).resolve().parents[2] / 'domains/chemical/skills'
sys.path[:0] = [str(SKILLS / 'gaussian/scripts'), str(SKILLS / '_shared')]
from gaussian_io import parse_log

spec = importlib.util.spec_from_file_location('frequency_regression_validator',
    SKILLS / 'validation/scripts/gaussian_frequency.py')
frequency_validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frequency_validator)

CONVERGED = ''' Maximum Force 0.00001 0.00045 YES
 RMS     Force 0.00001 0.00030 YES
 Maximum Displacement 0.00001 0.00180 YES
 RMS     Displacement 0.00001 0.00120 YES
 Stationary point found.
'''


def parse(tmp_path, text):
    path = tmp_path / 'gaussian.out'
    path.write_text(text)
    return parse_log(path)


def test_repaired_calculation_does_not_inherit_previous_process_failure(tmp_path):
    failed = (' Entering Link 1 = /fixture/l1.exe\n #p HF/STO-3G Opt\n ----\n'
              ' Convergence failure -- run terminated.\n Error termination via Lnk1e\n')
    repaired = (' Entering Link 1 = /fixture/l1.exe\n #p HF/STO-3G Opt\n ----\n'
                ' SCF Done: E(RHF) = -75.1 A.U.\n' + CONVERGED + ' Normal termination of Gaussian\n')
    result = parse(tmp_path, failed + repaired)
    assert result['summary']['section_count'] == 2
    assert result['summary']['selected_section_index'] == 1
    assert result['summary']['normal_termination']
    assert not result['summary']['error_termination']
    assert result['summary']['primary_failure'] is None
    assert result['summary']['final_convergence_satisfied']
    old = parse_log(tmp_path / 'gaussian.out', section_index=0)
    assert old['summary']['primary_failure']['kind'] == 'scf_convergence'


@pytest.mark.parametrize('later', [
    ' Maximum Force 0.1 0.00045 NO\n',
    ' Maximum Force 0.00001 0.00045 YES\n',
    CONVERGED.replace(' Stationary point found.\n', '').replace('0.00001 0.00045 YES', '0.1 0.00045 NO'),
])
def test_later_incomplete_or_failed_convergence_cannot_reuse_old_stationary_point(tmp_path, later):
    result = parse(tmp_path, CONVERGED + ' Step number 2 out of a maximum of 20\n' + later)
    assert not result['summary']['final_convergence_satisfied']
    assert result['summary']['force_convergence_source'] == 'last_section_rows'
    assert not result['summary']['stationary_point_found']


@pytest.mark.parametrize('later', [' Step number 2 out of a maximum of 20\n', ' Maximum Force\n'])
def test_truncated_new_optimization_evidence_clears_previous_convergence(tmp_path, later):
    result = parse(tmp_path, CONVERGED + later)
    assert not result['summary']['final_convergence_evidence_present']
    assert not result['summary']['stationary_point_found']


def test_empty_final_harmonic_section_does_not_reuse_previous_negative_mode(tmp_path):
    result = parse(tmp_path, ' Harmonic frequencies\n Frequencies -- -200.0 100.0 150.0\n'
        ' Thermochemistry\n Harmonic frequencies\n Normal termination of Gaussian\n')
    assert result['summary']['raw_imaginary_frequency_count'] == 1
    assert result['frequencies'] == []
    assert result['summary']['frequency_count'] == 0
    assert result['normal_modes'] == []


def test_fortran_exponents_in_frequency_records_are_read_without_losing_sign(tmp_path):
    result = parse(tmp_path, ' Harmonic frequencies\n Frequencies -- -2.0D+02 1.0d+02 1.5E+02\n')
    assert result['frequencies'] == [-200.0, 100.0, 150.0]
    assert result['summary']['imaginary_frequency_count'] == 1


def test_final_geometry_follows_record_order_across_orientation_types(tmp_path):
    def orientation(kind, x):
        return (f' {kind} orientation:\n ----\n Center Atomic Atomic Coordinates (Angstroms)\n'
                ' Number Number Type X Y Z\n ----\n'
                f' 1 8 0 {x} 0.0 0.0\n ----\n')
    result = parse(tmp_path, orientation('Standard', 0.0) + orientation('Input', 1.0))
    assert result['atoms'] == [('O', 1.0, 0.0, 0.0)]


@pytest.mark.parametrize('frequencies,error_termination', [
    ([-200.0, float('nan'), 100.0], False),
    ([-200.0, float('inf'), 100.0], False),
    ([-200.0, 'unparsed', 100.0], False),
    ([-200.0, True, 100.0], False),
    ([-200.0, 100.0, 150.0], True),
])
def test_unusable_frequency_evidence_is_inconclusive_not_a_scientific_pass(tmp_path, frequencies, error_termination):
    path = tmp_path / 'parsed.json'
    path.write_text(json.dumps({'summary': {'normal_termination': True, 'error_termination': error_termination},
                               'frequencies': frequencies}))
    assert frequency_validator.validate([path])['verdict'] == 'inconclusive'


@pytest.mark.parametrize('frequencies,verdict', [
    ([-200.0, 100.0, 150.0], 'pass'), ([20.0, 100.0, 150.0], 'fail'),
    ([-200.0, -100.0, 150.0], 'fail'),
])
def test_finite_frequency_table_reports_only_its_declared_scope(tmp_path, frequencies, verdict):
    path = tmp_path / 'parsed.json'
    path.write_text(json.dumps({'summary': {'normal_termination': True, 'error_termination': False},
                               'frequencies': frequencies}))
    result = frequency_validator.validate([path])
    assert result['verdict'] == verdict
    assert 'excludes IRC and mode character' in result['scope']


@pytest.mark.parametrize('evidence,passes', [
    (CONVERGED + ' Harmonic frequencies\n Frequencies -- -200.0 100.0 150.0\n', True),
    (CONVERGED + ' Harmonic frequencies\n Frequencies -- -200.0 100.0 150.0\n'
        ' Thermochemistry\n Harmonic frequencies\n', False),
    (CONVERGED + ' Maximum Force 0.00001 0.00045 YES\n'
        ' Harmonic frequencies\n Frequencies -- -200.0 100.0 150.0\n', False),
])
def test_actual_runner_keeps_program_success_separate_from_final_evidence(tmp_path, evidence, passes):
    from tests.unit.test_gaussian_explicit_input import gjf
    source = gjf(tmp_path / 'input.gjf')
    log = tmp_path / 'synthetic.out'
    log.write_text(' #p M062X/6-31G** Opt=(TS,CalcFC) Freq\n ----------------\n'
                   ' SCF Done: E(RM062X) = -76.0 A.U.\n' + evidence + ' Normal termination of Gaussian\n')
    program = tmp_path / 'fixture-gaussian'
    program.write_text('#!/bin/sh\ncat >/dev/null\ncat ' + shlex.quote(str(log)) + '\n')
    program.chmod(0o755)
    out = tmp_path / 'out'
    run = subprocess.run([sys.executable, str(SKILLS / 'gaussian/scripts/run.py'),
        '--input-gjf', str(source), '--executable', str(program), '--output-dir', str(out),
        '--threads', '12', '--memory-mb', '4000', '--validation', 'saddle'],
        capture_output=True, text=True, timeout=30)
    result = json.loads((out / 'result.json').read_text())
    assert run.returncode == (0 if passes else 1)
    assert result['program_returncode'] == 0
    assert result['execution_status'] == 'succeeded'
    assert result['parsing']['status'] == 'completed'
    assert result['check_status'] == ('satisfied' if passes else 'not_satisfied')
    assert result['checks_passed'] is passes
    assert result['scientific_validation'] == 'not_assessed'
