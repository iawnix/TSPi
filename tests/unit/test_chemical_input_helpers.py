import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT/'extensions/chemical/skills/chemical-input/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('chemical_input_helper', SCRIPTS/'prepare.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def test_water_identity_and_reproducible_seed_need_no_reaction_mapping(tmp_path):
    resolved = helper.resolve_name('水分子')
    assert resolved['data']['status'] == 'resolved'
    assert resolved['data']['resolver_provenance']['rule'] == 'neutral-water'
    first = helper.seeds('O', 0, 1, tmp_path/'first')
    second = helper.seeds('O', 0, 1, tmp_path/'second')
    assert first['formula'] == 'H2O'
    assert first['seeds'][0]['sha256'] == second['seeds'][0]['sha256']
    assert (tmp_path/'first/seed-1.xyz').read_text().splitlines()[0] == '3'
    with pytest.raises(ValueError, match='multiplicity'):
        helper.seeds('O', 0, 2, tmp_path/'bad')


def test_stereo_is_explicitly_enumerated_without_selecting_one_identity(tmp_path):
    with pytest.raises(ValueError, match='unspecified stereochemistry'):
        helper.seeds('CC(O)F', 0, 1, tmp_path/'blocked')
    result = helper.seeds('CC(O)F', 0, 1, tmp_path/'ensemble', True)
    assert len(result['seeds']) == 2
    assert len({seed['smiles'] for seed in result['seeds']}) == 2
    assert result['geometry_status'] == 'initial_seed'


def test_reaction_checks_conservation_and_chosen_mapping():
    result = helper.reaction('[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]>>[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]')
    assert result['checks']['element_charge_balance']['verdict']=='pass'
    assert result['checks']['declared_transformation']['verdict']=='not_assessed'
    assert [change['atoms'] for change in result['bond_changes'] if change['before'] == 0] == [[1, 6], [4, 5]]
    with pytest.raises(ValueError, match='unique'):
        helper.reaction('[CH4:1]>>[CH3:1][CH3:1]')
    assert helper.reaction('[CH4:1]>>[OH2:1]')['checks']['map_identity']['verdict']=='fail'
    assert helper.reaction('[13CH4:1]>>[CH4:1]')['checks']['map_identity']['verdict']=='fail'


def test_opsin_configuration_calls_real_resolver_implementation(tmp_path, monkeypatch):
    import name_resolution
    config = tmp_path/'name-resolver.toml'
    config.write_text('default_resolver="opsin"\n[backends.opsin]\nenabled=true\ncache=false\n')
    monkeypatch.setenv('TSPI_NAME_RESOLVER_CONFIG', str(config))
    calls = []
    def reply(url, **kwargs):
        calls.append(url)
        return {'status': 'SUCCESS', 'smiles': 'C=CC=C'}, 'sha256:fixture'
    monkeypatch.setattr(name_resolution, '_http_json', reply)
    result = helper.resolve_name('丁二烯', 'buta-1,3-diene')
    assert result['data']['status'] == 'resolved'
    assert result['data']['name'] == '丁二烯'
    assert result['data']['candidates'][0]['formula'] == 'C4H6'
    assert calls and 'buta-1%2C3-diene' in calls[0]
