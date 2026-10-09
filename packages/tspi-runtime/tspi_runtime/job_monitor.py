"""Durable, domain-neutral Job wake outbox. Never sends notifications."""
import hashlib
import json
import time
import uuid
from types import SimpleNamespace
from job_runtime import JobState
from datetime import datetime, timezone
from pathlib import Path
from research_state.transactions import TransactionCoordinator, state_transaction, write_json, read_json
from .execution import _runtime, _receipt


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return read_json(path)
def write(path,value):
    write_json(path, value)
def digest(value):return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def read_binding(path):
    value = read(path)
    if (value.get('schema_version') != 'ts-job-monitor/1'
            or {'intent_id', 'intent_digest'} & set(value)
            or any(not value.get(key) for key in ('job_id', 'attempt_id', 'job_digest'))):
        raise ValueError('monitor_binding_schema_invalid: current Job/Attempt binding required')
    return value


def read_delivery(path):
    value = read(path)
    if value.get('schema_version') != 'ts-job-monitor-delivery/1':
        raise ValueError('monitor_delivery_schema_invalid: current Job delivery required')
    return value


def bind(root, intent, session_id):
    if not session_id or not intent.get('node_id'):return
    job=intent['job_id'];mid='monitor_'+hashlib.sha256(job.encode()).hexdigest()[:24]
    path=root/'operations/monitors'/mid/'binding.json'
    if path.exists():
        read_binding(path)
        return
    manifest=read(root/'workspace_manifest.json')
    write(path,{'schema_version':'ts-job-monitor/1','monitor_id':mid,'workspace_id':manifest['workspace_id'],
        'node_id':intent['node_id'],'job_id':job,'attempt_id':intent['attempt_id'],
        'job_digest':digest(intent),'session_id':session_id,'wake_policy':'next_run','notify_policy':'none',
        'enabled':True,'created_at':now(),'sequence':0,'last_state':None})


def command(root, action, args):
    root=Path(root).resolve();base=root/'operations/monitors'
    if action == 'tick':
        return _tick(root, base, args)
    with TransactionCoordinator(root).locked():
        return _command(root,base,action,args)


def _command(root,base,action,args):
    manifest=read(root/'workspace_manifest.json');workspace_id=manifest['workspace_id']
    bindings=sorted(base.glob('*/binding.json'))
    if args.get('monitor_id'):bindings=[p for p in bindings if p.parent.name==args['monitor_id']]
    if action in {'list','status'}:
        result = {'workspace_id':workspace_id,'monitors':[read_binding(p) for p in bindings]}
        if action == 'status':
            # Observation must not claim, batch or retry the delivery outbox.
            result['pending_deliveries'] = [
                {key: row.get(key) for key in ('session_id', 'request_id', 'event_id', 'error', 'deferred_state')}
                for binding in bindings for path in sorted((binding.parent/'deliveries').glob('*.json'))
                if not (row := read_delivery(path)).get('delivered')]
        return result
    if action in {'enable','disable'}:
        for p in bindings:
            row=read_binding(p);row['enabled']=action=='enable';write(p,row)
        return {'workspace_id':workspace_id,'updated':len(bindings)}
    if action=='health':
        write(base/'health.json',{'checked_at':now(),'error':args.get('error')});return {'ok':True}
    if action=='tick':
        raise ValueError('tick must observe outside the workspace transaction')
    return _delivery_command(root,base,action,args)


def _tick(root, base, args):
    bindings=sorted(base.glob('*/binding.json'))
    if args.get('monitor_id'):bindings=[p for p in bindings if p.parent.name==args['monitor_id']]
    errors=[];observed=[]
    for p in bindings:
        try:
            row=read_binding(p)
            if not row.get('enabled'):continue
            receipt = None
            try:
                receipt=_receipt(root,{'job_id':row['job_id']})
                status=_runtime(root).job_status(receipt)
            except FileNotFoundError:
                status=SimpleNamespace(state=JobState.UNKNOWN,exit_code=None,error='dispatch intent has no receipt; reconcile required')
            status_value={key:getattr(status,key,None) for key in ('exit_code','started_at','finished_at','error','diagnostics')}
            status_value['state']=status.state.value
            observed.append(_commit_observation(root, {'monitor_id':row['monitor_id'],
                'status':status_value,'receipt':receipt.__dict__ if receipt else None}))
        except Exception as exc:errors.append(str(exc))
    return {'monitors':observed,'registration_errors':errors}



@state_transaction('job.monitor_observation')
def _commit_observation(root, request):
    p=root/'operations/monitors'/request['monitor_id']/'binding.json'
    row=read_binding(p)
    if not row.get('enabled'):return {'monitor_id':row['monitor_id'],'state':'disabled'}
    status=SimpleNamespace(**request['status'])
    receipt=SimpleNamespace(**request['receipt']) if request['receipt'] else SimpleNamespace(
        job_id=row['job_id'], attempt_id=row['attempt_id'], node_id=row['node_id'], workspace_id=row['workspace_id'], metadata={})
    if receipt:
        if receipt.job_id!=row['job_id'] or receipt.attempt_id!=row['attempt_id']:
            raise ValueError('monitor_binding_mismatch')
        from .job_state import observe_attempt
        conflict = observe_attempt(root,receipt,request['status'])
        if conflict:
            status.state = "unknown"
            status.error = "job_terminal_conflict: explicit reconciliation required"
    state=status.state
    result={'monitor_id':row['monitor_id'],'state':state}
    diagnostics = getattr(status, 'diagnostics', {}) or {}
    threshold = receipt.metadata.get('queue_wait_seconds') if receipt is not None else None
    queue_wait = (state in {'queued','held'} and threshold and
                  (diagnostics.get('wait_seconds') or 0) >= threshold and not row.get('queue_wait_reported'))
    if state==row.get('last_state') and not queue_wait:return result
    if queue_wait: row['queue_wait_reported'] = True
    previous=row.get('last_state');row['last_state']=state
    # Queue/running transitions are retained without waking the Agent.
    if state not in {'succeeded','failed','timed_out','cancelled','unknown'} and not queue_wait:
        write(p,row);return result
    row['sequence']+=1
    eid='event_'+hashlib.sha256(f"{row['monitor_id']}:{row['sequence']}:{state}".encode()).hexdigest()[:32]
    event={**row,'schema_version':'ts-job-monitor-event/1','event_id':eid,'state':state,
        'previous_state':previous,'status_digest':digest({'state':state,'exit_code':status.exit_code}),
        'program_status':None,'exit_status':status.exit_code,'error_class':None,
        'error':status.error,'observed_at':now(),'status':{'state':state,'exit_code':status.exit_code,'diagnostics':diagnostics, 'reason':'queue_wait_exceeded' if queue_wait else 'state_changed'}}
    write(p.parent/'events'/f'{eid}.json',event)
    write(p.parent/'deliveries'/f'{eid}.json',{'schema_version':'ts-job-monitor-delivery/1','event_id':eid,'session_id':row['session_id'],
        'request_id':'job-wake:'+eid,'delivered':False})
    write(p,row)
    return result



def _delivery_command(root,base,action,args):
    deliveries=sorted(base.glob('*/deliveries/*.json'))
    if action=='pending':
        from research_state.agent_workspace import read_liveness
        state=read_liveness(root)
        token=f"{state['revision']}:{state.get('checkpoint_id')}"
        pending = [(p, row) for p in deliveries if not (row := read_delivery(p)).get('delivered')
                   and row.get('deferred_state') != token]
        for path, row in pending:
            if row.get('superseded_input'):
                # Only a Worker-proven pre-consumption rejection permits a new
                # input. Preserve prior business identities; lost replies and
                # provider failures never rotate an admitted input identity.
                previous = row['request_id']
                row.setdefault('superseded_requests', []).append(previous)
                row.update(request_id='job-wake-batch:' + hashlib.sha256(f'{previous}:{token}'.encode()).hexdigest(),
                           superseded_input=False)
                write(path, row)
        # Persist immutable batch membership before Host admission. Retries and
        # uncertain RPC outcomes must reuse both identity and message payload.
        sessions = {}
        for path, row in pending:
            if not row.get('batch_event_ids'):
                sessions.setdefault(row.get('session_id'), []).append((path, row))
        for rows in sessions.values():
            ids = sorted(row['event_id'] for _, row in rows)
            request_id = 'job-wake-batch:' + hashlib.sha256(':'.join(ids).encode()).hexdigest()
            for path, row in rows:
                row.update(request_id=request_id, batch_event_ids=ids)
                write(path, row)
        return {'deliveries': [row for _, row in pending]}
    eid=args.get('event_id')
    path=next((p for p in deliveries if p.stem==eid),None)
    if path is None:raise ValueError('unknown monitor event')
    if action=='event':
        from research_state.monitor_wake import validate_event
        return validate_event(read(path.parent.parent/'events'/f'{eid}.json'))
    row=read_delivery(path)
    if args.get('channel')!='wake':return {'claimed':False}
    if action=='claim':
        if row.get('delivered') or row.get('lease_until',0)>time.time():return {'claimed':False}
        row.update(claim_token=uuid.uuid4().hex,lease_until=time.time()+60)
        write(path,row);return {**row,'claimed':True}
    if action=='complete':
        if row.get('claim_token')!=args.get('claim_token'):raise ValueError('stale wake claim')
        row.update(delivered=bool(args.get('delivered')),error=args.get('error'),lease_until=0,
                   deferred_state=args.get('deferred_state'))
        if args.get('superseded_input'):
            row['superseded_input'] = True
        write(path,row);return {'ok':True}
    raise ValueError('unknown monitor command')
