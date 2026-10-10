"""Durable, domain-neutral Job wake outbox. Never sends notifications."""
import hashlib
import json
import re
import time
import uuid
from types import SimpleNamespace
from research_agent.jobs import JobState
from datetime import datetime, timezone
from pathlib import Path
from research_agent.foundation.transactions import TransactionCoordinator, workspace_transaction, write_json, read_json
from .execution import _runtime, _receipt


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return read_json(path)
def write(path,value):
    write_json(path, value)
def digest(value):return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def valid_node_binding(value):
    if {'attempt_id', 'intent_id', 'intent_digest'} & set(value):
        return False
    return (value.get('node_id') is None and value.get('node_revision') is None
            and 'node_id' in value and 'node_revision' in value) or (
        isinstance(value.get('node_id'), str) and re.fullmatch(r'node_[A-Za-z0-9_-]+', value['node_id'])
        and type(value.get('node_revision')) is int and value['node_revision'] > 0)


def read_binding(path):
    value = read(path)
    if value.get('enabled') is False:
        raise ValueError('monitor_pause_migration_required: resolve the legacy Job pause explicitly before enabling Task Controller')
    if (value.get('schema_version') != 'coragent-job-monitor/2'
            or not valid_node_binding(value)
            or any(not value.get(key) for key in ('job_id', 'job_digest'))):
        raise ValueError('monitor_binding_schema_invalid: current Job binding required')
    return value


def read_delivery(path):
    value = read(path)
    if value.get('schema_version') != 'coragent-job-monitor-delivery/2':
        raise ValueError('monitor_delivery_schema_invalid: current Job delivery required')
    return value


def monitor_view(path):
    """Project existing observations and outbox facts for Host clients."""
    binding = read_binding(path)
    pending = [row for p in sorted((path.parent / 'deliveries').glob('*.json'))
               if not (row := read_delivery(p)).get('delivered')]
    events = [read(p) for p in (path.parent / 'events').glob('*.json')]
    latest = max(events, key=lambda event: event['sequence'], default={})
    errors = [row['error'] for row in pending if row.get('error')]
    return {**binding, 'pending_count': len(pending),
            'last_observed_at': latest.get('observed_at'),
            'last_error': errors[-1] if errors else latest.get('error')}


def bind(root, intent, session_id):
    if not session_id:return
    job=intent['job_id'];mid='monitor_'+hashlib.sha256(job.encode()).hexdigest()[:24]
    path=root/'operations/monitors'/mid/'binding.json'
    if path.exists():
        read_binding(path)
        return
    manifest=read(root/'workspace_manifest.json')
    write(path,{'schema_version':'coragent-job-monitor/2','monitor_id':mid,'workspace_id':manifest['workspace_id'],
        'job_id':job,'node_id':intent.get('node_id'),'node_revision':intent.get('node_revision'),
        'user_task_id':intent.get('user_task_id'),
        'job_digest':digest(intent),'session_id':session_id,'wake_policy':'next_run','notify_policy':'none',
        'created_at':now(),'sequence':0,'last_state':None})


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
        result = {'workspace_id':workspace_id,'monitors':[monitor_view(p) for p in bindings]}
        if action == 'status':
            # Observation must not claim, batch or retry the delivery outbox.
            result['pending_deliveries'] = [
                {key: row.get(key) for key in ('session_id', 'request_id', 'event_id', 'error')}
                for binding in bindings for path in sorted((binding.parent/'deliveries').glob('*.json'))
                if not (row := read_delivery(path)).get('delivered')]
        return result
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



@workspace_transaction('job.monitor_observation')
def _commit_observation(root, request):
    p=root/'operations/monitors'/request['monitor_id']/'binding.json'
    row=read_binding(p)
    status=SimpleNamespace(**request['status'])
    receipt=SimpleNamespace(**request['receipt']) if request['receipt'] else SimpleNamespace(
        job_id=row['job_id'], workspace_id=row['workspace_id'], metadata={})
    if receipt:
        if receipt.job_id!=row['job_id']:
            raise ValueError('monitor_binding_mismatch')
        from .job_state import observe_execution
        conflict = observe_execution(root,receipt,request['status'])
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
    event={**row,'schema_version':'coragent-job-monitor-event/2','event_id':eid,'state':state,
        'previous_state':previous,'status_digest':digest({'state':state,'exit_code':status.exit_code}),
        'program_status':None,'exit_status':status.exit_code,'error_class':None,
        'error':status.error,'observed_at':now(),'status':{'state':state,'exit_code':status.exit_code,'diagnostics':diagnostics, 'reason':'queue_wait_exceeded' if queue_wait else 'state_changed'}}
    write(p.parent/'events'/f'{eid}.json',event)
    write(p.parent/'deliveries'/f'{eid}.json',{'schema_version':'coragent-job-monitor-delivery/2','event_id':eid,'session_id':row['session_id'],
        'request_id':'job-wake:'+eid,'delivered':False})
    write(p,row)
    return result



def _delivery_command(root,base,action,args):
    deliveries=sorted(base.glob('*/deliveries/*.json'))
    if action=='pending':
        pending = [(p, row) for p in deliveries if not (row := read_delivery(p)).get('delivered')]
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
        # Task Controller owns admission policy; the outbox retains facts only.
        for path, _ in pending:
            read_binding(path.parent.parent / 'binding.json')
        return {'deliveries': [row for _, row in pending]}
    eid=args.get('event_id')
    path=next((p for p in deliveries if p.stem==eid),None)
    if path is None:raise ValueError('unknown monitor event')
    if action=='event':
        return validate_event(read(path.parent.parent/'events'/f'{eid}.json'))
    row=read_delivery(path)
    if args.get('channel')!='wake':return {'claimed':False}
    if action=='claim':
        read_binding(path.parent.parent / 'binding.json')
        if row.get('delivered') or row.get('lease_until',0)>time.time():return {'claimed':False}
        row.update(claim_token=uuid.uuid4().hex,lease_until=time.time()+60)
        write(path,row);return {**row,'claimed':True}
    if action=='complete':
        if row.get('claim_token')!=args.get('claim_token'):raise ValueError('stale wake claim')
        row.update(delivered=bool(args.get('delivered')),error=args.get('error'),lease_until=0)
        write(path,row);return {'ok':True}
    raise ValueError('unknown monitor command')


def validate_event(event):
    if (event.get("schema_version") != "coragent-job-monitor-event/2" or not valid_node_binding(event) or
            any(not isinstance(event.get(key), str) or not event[key]
                for key in ("event_id", "monitor_id", "job_id", "workspace_id", "session_id"))):
        raise ValueError("monitor_event_schema_invalid")
    return event


def assess(root, event_id, session_id):
    if not isinstance(event_id, str) or not re.fullmatch(r"event_[A-Za-z0-9_-]+", event_id):
        raise ValueError("invalid monitor event identity")
    root = Path(root)
    with TransactionCoordinator(root).locked():
        paths = list((root / "operations/monitors").glob(f"*/events/{event_id}.json"))
        if len(paths) != 1:
            raise ValueError("unknown monitor event")
        event = validate_event(read(paths[0]))
        if event["workspace_id"] != read(root / "workspace_manifest.json")["workspace_id"] or event["session_id"] != session_id:
            raise ValueError("monitor event belongs to another workspace or session")
        delivery = read_delivery(paths[0].parent.parent / "deliveries" / paths[0].name)
        if delivery['event_id'] != event_id or delivery['session_id'] != session_id:
            raise ValueError("monitor_delivery_binding_mismatch")
        obsolete = bool(delivery.get("delivered"))
        read_binding(paths[0].parent.parent / "binding.json")
        return {"event_id": event_id, "event": event, "obsolete": obsolete,
                "admitted": not obsolete, "reason": "already_delivered" if obsolete else "attention_required",
                "delivery_token": digest({"event_id": event_id, "request_id": delivery["request_id"], "delivered": obsolete})}
