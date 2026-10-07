"""Persist operational Job facts through the canonical Research State writer."""
import hashlib
import json
from research_state import agent_workspace as state


def context(root):
    return json.loads((root/'research_map/context.json').read_text())


def change(root, key, operations):
    return state.apply_change(root, {'request_id':key,'principal':'root_agent','authority':'kernel_write',
                                     'operations':operations})


def register_attempt(root, spec, platform):
    if spec.node_id is None:
        if spec.attempt_id: raise ValueError('attempt binding requires a node')
        return None
    if not state.has_state_files(root): raise ValueError('research Job requires an initialized research workspace')
    attempt_id=spec.attempt_id or 'attempt_'+hashlib.sha256(spec.job_id.encode()).hexdigest()[:32]
    old=next((a for a in context(root)['attempts'] if a['id']==attempt_id),None)
    if old:
        if old['node_id']!=spec.node_id or old.get('metadata',{}).get('job_id')!=spec.job_id:
            raise ValueError('attempt already belongs to another node or job')
        return attempt_id
    change(root,'job-attempt:'+spec.job_id,[{'type':'register_attempt','id':attempt_id,'node_id':spec.node_id,
        'execution_kind':'command','state':'started','environment':platform or 'local',
        'metadata':{'job_id':spec.job_id,'command':list(spec.command),'job_metadata':dict(spec.metadata)}}])
    return attempt_id


def observe_attempt(root, receipt, value):
    if not receipt.attempt_id or not state.has_state_files(root):return
    status=value.get('status',value)
    execution=status.get('state')
    mapped={'submitted':'started','queued':'started','held':'started','running':'running',
            'succeeded':'succeeded','failed':'failed','timed_out':'timed_out','cancelled':'cancelled'}.get(execution)
    if not mapped:return
    old=next((a for a in context(root)['attempts'] if a['id']==receipt.attempt_id),None)
    if not old:raise ValueError('job receipt refers to an unregistered Attempt')
    validation = value.get('output_validation')
    if old['state'] in state.ATTEMPT_TERMINAL_STATES and old['state'] != mapped:return
    if old['state']=='running' and mapped=='started':return
    if old['state']==mapped and (validation is None or old.get('metadata',{}).get('output_validation')==validation):return
    operation={'type':'transition_attempt','attempt_id':receipt.attempt_id,'state':mapped,
               'exit_code':status.get('exit_code'),'metadata':{**old.get('metadata',{}),'job_id':receipt.job_id}}
    if validation is not None: operation['metadata']['output_validation']=validation
    if status.get('error'):operation['error']=status['error']
    suffix=hashlib.sha256(json.dumps(validation,sort_keys=True).encode()).hexdigest()[:16] if validation is not None else 'execution'
    change(root,f'job-state:{receipt.job_id}:{mapped}:{suffix}',[operation])
