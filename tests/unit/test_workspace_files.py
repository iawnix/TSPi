import base64
import hashlib
import os
from pathlib import Path
import pytest
from research_agent.application.workspace_files import dispatch, FileAccessError

@pytest.fixture
def workspace(tmp_path):
    for name in ('inputs','runs','operations'):
        (tmp_path/name).mkdir()
    (tmp_path/'inputs/ethanol.xyz').write_text('2\nfixture\nC 0 0 0\nC 1.5 0 0\n')
    return tmp_path

def stat_file(root,path='inputs/ethanol.xyz'):
    return dispatch(root,{'operation':'stat','path':path})['file']

def test_only_materials_and_bounded_versioned_reads(workspace):
    (workspace/'inputs/.credentials.txt').write_text('private')
    (workspace/'inputs/state.sqlite').write_text('private')
    listing=dispatch(workspace,{'operation':'list','path':'inputs'})
    assert [x['name'] for x in listing['items']]==['ethanol.xyz']
    file=stat_file(workspace)
    part=dispatch(workspace,{'operation':'read','path':file['path'],'expected_version':file['version'],'offset':2,'length':7})
    assert base64.b64decode(part['data_base64'])==b'fixture'
    assert part['next_offset']==9
    for path in ('../secret.txt','inputs/../secret.txt','/etc/passwd','operations/state.txt','inputs/.credentials.txt'):
        with pytest.raises(FileAccessError):
            dispatch(workspace,{'operation':'stat','path':path})
    with pytest.raises(FileAccessError,match='range'):
        dispatch(workspace,{'operation':'read','path':file['path'],'expected_version':file['version'],'length':65537})

def test_links_and_same_size_replacement_are_rejected(workspace,tmp_path):
    source=workspace/'inputs/ethanol.xyz'
    os.symlink(source,workspace/'inputs/link.xyz')
    with pytest.raises(FileAccessError): stat_file(workspace,'inputs/link.xyz')
    os.symlink(workspace/'inputs',workspace/'runs/linked')
    with pytest.raises(FileAccessError): stat_file(workspace,'runs/linked/ethanol.xyz')
    file=stat_file(workspace)
    source.write_text('X'*file['size'])
    with pytest.raises(FileAccessError,match='changed'):
        dispatch(workspace,{'operation':'read','path':file['path'],'expected_version':file['version']})
    os.link(source,workspace/'inputs/hard.xyz')
    with pytest.raises(FileAccessError): stat_file(workspace,'inputs/hard.xyz')
    assert dispatch(workspace,{'operation':'list','path':'inputs'})['items']==[]

def test_pagination_detects_changed_directory(workspace):
    (workspace/'inputs/b.txt').write_text('b')
    first=dispatch(workspace,{'operation':'list','path':'inputs','limit':1})
    second=dispatch(workspace,{'operation':'list','path':'inputs','limit':1,'cursor':first['next_cursor']})
    assert first['items'][0]['path']!=second['items'][0]['path']
    (workspace/'inputs/c.txt').write_text('c')
    with pytest.raises(FileAccessError,match='changed'):
        dispatch(workspace,{'operation':'list','path':'inputs','cursor':first['next_cursor']})

def test_explicit_snapshot_is_stable_and_source_is_not_modified(workspace):
    original=(workspace/'inputs/ethanol.xyz').read_bytes()
    file=stat_file(workspace)
    request={'operation':'pin','path':file['path'],'expected_version':file['version']}
    first=dispatch(workspace,request)
    assert dispatch(workspace,request)==first
    assert first['sha256']==hashlib.sha256(original).hexdigest()
    assert (workspace/first['path']).read_bytes()==original
    (workspace/'inputs/ethanol.xyz').write_text('modified')
    assert (workspace/first['path']).read_bytes()==original
    with pytest.raises(FileAccessError,match='changed'):dispatch(workspace,request)
