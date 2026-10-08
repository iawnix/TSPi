import json
import pytest
from research_state.monitor_wake import assess
from research_state.admission import tool_admission


def event_fixture(root, state='succeeded'):
    event = {'schema_version':'ts-job-monitor-event/1','monitor_id':'monitor_test',
             'event_id':'event_fixture','workspace_id':'ws_test','session_id':'session_test',
             'node_id':'node_test','attempt_id':'attempt_test','job_id':'job_test','state':state,'exit_status':0 if state=='succeeded' else 1}
    path=root/'operations/monitors/monitor_test/events/event_fixture.json'
    path.parent.mkdir(parents=True);path.write_text(json.dumps(event))
    context={'workspace_id':'ws_test','revision':7,'nodes':[{'id':'node_test','state':'closed'}],
             'attempts':[{'id':'attempt_test','state':state,'exit_code':event['exit_status'],
                          'metadata':{'job_id':'job_test','output_validation':{'complete':state=='succeeded'}}}]}
    return context


@pytest.mark.parametrize('state', ['succeeded','failed'])
def test_handled_monitor_event_is_obsolete_even_if_delivered_late(tmp_path,state):
    context=event_fixture(tmp_path,state)
    value=assess(tmp_path,context,{'disposition':'terminal'},'event_fixture','session_test')
    assert value['obsolete'] and not value['admitted']


def test_new_failure_is_not_silenced_by_terminal_workspace(tmp_path):
    context=event_fixture(tmp_path,'failed')
    context['attempts'][0]['state']='running'
    value=assess(tmp_path,context,{'disposition':'terminal'},'event_fixture','session_test')
    assert value['admitted'] and not value['obsolete']
    assert not assess(tmp_path,context,{'disposition':'user_input_required'},'event_fixture','session_test')['admitted']
    with pytest.raises(ValueError,match='another workspace or session'):
        assess(tmp_path,context,{},'event_fixture','other_session')


def test_exit_success_without_collection_still_needs_attention(tmp_path):
    context=event_fixture(tmp_path)
    context['attempts'][0]['metadata'].pop('output_validation')
    assert assess(tmp_path,context,{},'event_fixture','session_test')['admitted']


@pytest.mark.parametrize('name', ['bash','write','edit'])
def test_native_preparation_is_allowed_before_strategy_but_blocked_after_terminal(name):
    tool={'name':name,'effect':'execution_control','phase':'prepare'}
    assert tool_admission({}, {'lifecycle':'decision_needed'},tool)['accepted']
    assert not tool_admission({}, {'lifecycle':'terminal'},tool)['accepted']
    assert tool_admission({}, {'lifecycle':'terminal'},{'name':'read','effect':'read'})['accepted']


def test_current_interpretation_suppresses_wake_but_old_field_and_stale_review_do_not(tmp_path):
    context = event_fixture(tmp_path)
    context['nodes'][0]['state'] = 'active'
    context['attempt_interpretations'] = [{'attempt_ref': 'attempt_test', 'review_state': 'current'}]
    assert assess(tmp_path, context, {}, 'event_fixture', 'session_test')['obsolete']
    context['attempt_interpretations'][0]['review_state'] = 'needs_review'
    assert not assess(tmp_path, context, {}, 'event_fixture', 'session_test')['obsolete']
    context['attempt_interpretations'] = [{'attempt_id': 'attempt_test', 'review_state': 'current'}]
    assert not assess(tmp_path, context, {}, 'event_fixture', 'session_test')['obsolete']


def test_old_monitor_event_is_not_admitted(tmp_path):
    context = event_fixture(tmp_path)
    path = tmp_path / 'operations/monitors/monitor_test/events/event_fixture.json'
    event = json.loads(path.read_text())
    for patch in [{'schema_version': 'ts-compute-monitor-event/1'}, {'intent_id': 'calc_1'}, {'intent_digest': 'old'}]:
        path.write_text(json.dumps({**event, **patch}))
        with pytest.raises(ValueError, match='monitor_event_schema_invalid'):
            assess(tmp_path, context, {}, 'event_fixture', 'session_test')
