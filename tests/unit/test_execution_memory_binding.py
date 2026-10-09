"""Runtime ownership survives research edits and unavailable Memory projections."""
import json
import sys
import time
import pytest
from research_agent.research.nodes import create, update
from research_agent.research.records import journal
from research_agent.application.execution import dispatch
from research_agent.application.evidence import dispatch as material
from research_agent.application.job_state import execution, project_events
from research_agent.application.job_monitor import command
from tests.unit.test_job_recovery import workspace


def finish(root, job):
    for _ in range(100):
        value = dispatch('status', {'root':str(root), 'job_id':job})
        if value['state'] in {'succeeded','failed','cancelled','timed_out'}:
            return dispatch('collect', {'root':str(root), 'job_id':job})
        time.sleep(.02)
    pytest.fail('fixture job did not finish')


def test_job_binds_one_node_revision_and_retries_do_not_rebind(tmp_path):
    workspace(tmp_path)
    created = create(tmp_path, {'goal':'Validate candidate', 'proposal':'First proposal'})
    node = created['node']
    request = {'root':str(tmp_path), 'job_id':'job_bound', 'node_id':node['id'], 'session_id':'original',
        'command':[sys.executable,'-c',"print('evidence')"]}
    first = dispatch('start', request)
    update(tmp_path, {'node_id':node['id'], 'note':'Revise after new information',
        'proposal':'Second proposal', 'status':'closed', 'read_basis':created['read_basis']})
    second = dispatch('start', request)
    assert first['job_id'] == second['job_id']
    assert second['metadata']['research_binding'] == {'node_id':node['id'], 'node_revision':1}
    result = finish(tmp_path, first['job_id'])
    assert result['result_receipt']['node_revision'] == 1
    assert execution(tmp_path, first['job_id'])['node_id'] == node['id']
    command(tmp_path, 'tick', {})
    delivery = command(tmp_path, 'pending', {})['deliveries'][0]
    event = command(tmp_path, 'event', {'event_id':delivery['event_id']})
    assert event['node_id'] == node['id'] and event['node_revision'] == 1
    assert event['session_id'] == 'original'
    import jsonschema
    from pathlib import Path
    contract = Path(__file__).resolve().parents[2]/'contracts/monitor/2'
    binding = json.loads((tmp_path/'operations/monitors'/event['monitor_id']/'binding.json').read_text())
    for name, value in [('monitor', binding), ('event', event), ('delivery', delivery)]:
        jsonschema.validate(value, json.loads((contract/(name+'.schema.json')).read_text()))
    other = create(tmp_path, {'goal':'A different question'})['node']
    with pytest.raises(ValueError, match='reused with different parameters'):
        dispatch('start', {**request, 'node_id':other['id']})
    assert not project_events(tmp_path)
    records = [json.loads(p.read_text()) for p in (tmp_path/'research/records').glob('*.json')]
    assert any(r['origin']=='runtime' and r['node_id']==node['id'] and r['node_revision']==1 for r in records)


def test_projection_failure_does_not_prevent_execution_collection_or_monitor(tmp_path, monkeypatch):
    from research_agent.research import records
    workspace(tmp_path)
    def unavailable(*args, **kwargs):
        raise OSError('Memory temporarily unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(records, 'record_event', unavailable)
        job = dispatch('start', {'root':str(tmp_path), 'job_id':'job_no_projection', 'session_id':'s',
            'command':[sys.executable,'-c',"print('retained output')"]})
        result = finish(tmp_path, job['job_id'])
        assert result['result_receipt']['collection_state']=='complete'
        assert result['result_receipt']['node_id'] is None
        assert project_events(tmp_path)
        command(tmp_path, 'tick', {})
        assert len(command(tmp_path, 'pending', {})['deliveries']) == 1
    assert not project_events(tmp_path)
    before = journal(tmp_path)['sequence']
    assert not project_events(tmp_path)
    assert journal(tmp_path)['sequence'] == before
    events = list((tmp_path/'operations/events').glob('*.json'))
    receipts = list((tmp_path/'operations/event-projections').glob('*.json'))
    assert len(events) == len(receipts) > 0


def test_equal_bytes_from_another_material_do_not_prove_input_origin(tmp_path):
    workspace(tmp_path)
    first = material('create', {'root':str(tmp_path), 'name':'first', 'content':'identical'})
    second = material('create', {'root':str(tmp_path), 'name':'second', 'content':'identical'})
    assert first['artifact_id'] != second['artifact_id']
    with pytest.raises(ValueError, match='job_input_not_staged'):
        dispatch('start', {'root':str(tmp_path), 'job_id':'job_false_origin',
            'command':[sys.executable,'-c','pass'],
            'inputs':[{'source':first['location'], 'destination':'input'}],
            'input_artifact_ids':[second['artifact_id']]})
    assert not (tmp_path/'operations/jobs/job_false_origin.json').exists()
    node = create(tmp_path, {'goal':'Use an exact input'})['node']
    job = dispatch('start', {'root':str(tmp_path), 'job_id':'job_exact_origin', 'node_id':node['id'],
        'command':[sys.executable,'-c','pass'],
        'inputs':[{'source':first['location'], 'destination':'input'}],
        'input_artifact_ids':[first['artifact_id']]})
    finish(tmp_path, job['job_id'])
    assert not project_events(tmp_path)
    from research_agent.research.relations import graph
    links = list(graph(tmp_path)['relations'].values())
    assert any(link['source']==node['id'] and link['kind']=='uses' and link['target']==first['artifact_id'] for link in links)
    assert all(link['target'] != second['artifact_id'] for link in links)
