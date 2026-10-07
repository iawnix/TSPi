import json
from pathlib import Path
import pytest
from tspi_foundation.layout import paths, inspect_installation


def test_layout_initialization_and_configuration_are_shared(tmp_path):
    layout = paths(tmp_path / 'install').initialize()
    layout.update_config(workspace_root=str(tmp_path / 'research'))
    assert paths(layout.root).read_config()['workspace_root'] == str(tmp_path / 'research')
    assert layout.marker.stat().st_mode & 0o077 == 0
    assert not (layout.root / '.pi').exists()
    assert not (layout.root / '.agents').exists()
    assert not (layout.root / 'bin').exists()
    assert layout.pi_runtime != layout.cache


@pytest.mark.parametrize('old', ['.pi', '.agents'])
def test_old_installation_requires_fresh_install(tmp_path, old):
    (tmp_path / old).mkdir()
    with pytest.raises(ValueError, match='old installation'):
        paths(tmp_path).initialize()
    assert not (tmp_path / 'etc').exists()


def test_layout_rejects_symlinked_state_parent(tmp_path):
    (tmp_path / 'outside').mkdir()
    root = tmp_path / 'install'; root.mkdir()
    (root / 'var').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='symlink'):
        paths(root).initialize()
    assert not list((tmp_path / 'outside').iterdir())


def test_doctor_requires_matching_release_receipt(tmp_path):
    layout=paths(tmp_path).initialize()
    release=layout.releases/'release-a';release.mkdir(parents=True)
    layout.current.symlink_to('releases/release-a')
    layout.install_state.write_text(json.dumps({'current_release_id':'release-a','package_root':str(release)}))
    assert inspect_installation(tmp_path)['ok']
    layout.install_state.write_text(json.dumps({'current_release_id':'release-b','package_root':str(release)}))
    assert not inspect_installation(tmp_path)['ok']


@pytest.mark.parametrize('store', ['/', 'relative'])
def test_environment_store_cannot_be_a_broad_or_relative_path(tmp_path, monkeypatch, store):
    monkeypatch.setenv('TSPI_HOST_ENV_ROOT', store)
    with pytest.raises(ValueError, match='Host environment store'):
        paths(tmp_path/'install').initialize()
