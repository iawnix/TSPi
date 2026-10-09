import json
import pytest
from pathlib import Path
from jsonschema import Draft202012Validator
from research_agent.research.workspace import initialize_workspace, admit_research_workspace
from research_agent.research.web import handle_request, register_sources, PROVIDER_PROTOCOL, ResearchWebError
from research_agent.research.records import record_source
from research_agent.research.nodes import create


def test_web_exposes_snapshot_search_and_full_original(tmp_path):
    root=tmp_path/'workspace'; state=tmp_path/'catalog'
    initialize_workspace(root,'web_one','research');admit_research_workspace(root)
    register_sources(state,[root])
    source=record_source(root,{'session_id':'s','message_id':'u','text':'计算路径并比较不确定性'})
    node=create(root,{'goal':'Planned comparison'})['node']
    def request(route,query=None):
        return handle_request(state,{'schema_version':PROVIDER_PROTOCOL,'request_id':'r','operation':'route','workspace_id':'web_one','route':route,'query':query or {}})
    payload=request('snapshot')
    contracts = Path(__file__).resolve().parents[2] / 'contracts/ts-web'
    validator = Draft202012Validator(json.loads((contracts / 'research-memory-response.schema.json').read_text()))
    validator.validate(payload)
    validator.validate(json.loads((contracts / 'research-memory-response.fixture.json').read_text()))
    assert payload['schema_version']=='research-memory-response/1'
    assert payload['snapshot']['tasks'][0]['content']=='计算路径并比较不确定性'
    assert request('records',{'query':'路径'})['total']==1
    record=request('record/'+source['source_ref'])
    assert json.loads(record['text'])['content']=='计算路径并比较不确定性'
    assert request('nodes')['records'][0]['ref']==node['id']
    assert request('record/'+node['id'])['node']['goal']=='Planned comparison'
    with pytest.raises((ResearchWebError,ValueError)):request('record/../../secret')
