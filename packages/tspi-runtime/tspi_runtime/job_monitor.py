"""Durable, domain-neutral Job wake outbox. Never sends notifications."""
import hashlib
import json
import time
import uuid
from types import SimpleNamespace
from job_runtime import JobState
from datetime import datetime, timezone
from pathlib import Path
from research_state.transactions import TransactionCoordinator
from .execution import _runtime, _receipt


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)
def digest(value):return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def bind(root, intent, session_id):
    if not session_id or not intent.get('node_id'):return
    job=intent['job_id'];mid='monitor_'+hashlib.sha256(job.encode()).hexdigest()[:24]
    path=root/'operations/monitors'/mid/'binding.json'
    if path.exists():return
    manifest=read(root/'workspace_manifest.json')
    write(path,{'schema_version':'ts-job-monitor/1','monitor_id':mid,'workspace_id':manifest['workspace_id'],
        'node_id':intent['node_id'],'intent_id':job,'job_id':job,'attempt_id':intent['attempt_id'],
        'intent_digest':digest(intent),'session_id':session_id,'wake_policy':'next_run','notify_policy':'none',
        'enabled':True,'created_at':now(),'sequence':0,'last_state':None})


def command(root, action, args):
    root=Path(root).resolve();base=root/'operations/monitors'
    with TransactionCoordinator(root).locked():
        return _command(root,base,action,args)


def _command(root,base,action,args):
    manifest=read(root/'workspace_manifest.json');workspace_id=manifest['workspace_id']
    bindings=sorted(base.glob('*/binding.json'))
    if args.get('monitor_id'):bindings=[p for p in bindings if p.parent.name==args['monitor_id']]
    if action in {'list','status'}:
        return {'workspace_id':workspace_id,'monitors':[read(p) for p in bindings]}
    if action in {'enable','disable'}:
        for p in bindings:
            row=read(p);row['enabled']=action=='enable';write(p,row)
        return {'workspace_id':workspace_id,'updated':len(bindings)}
    if action=='health':
        write(base/'health.json',{'checked_at':now(),'error':args.get('error')});return {'ok':True}
    if action=='tick':
        errors=[];observed=[]
        for p in bindings:
            row=read(p)
            if row.get('schema_version')!='ts-job-monitor/1' or not row.get('enabled'):continue
            try:
                try:
                    receipt=_receipt(root,{'jobId':row['job_id']})
                    status=_runtime(root).job_status(receipt)
                except FileNotFoundError:
                    status=SimpleNamespace(state=JobState.UNKNOWN,exit_code=None,error='dispatch intent has no receipt; reconcile required')
                state=status.state.value
                observed.append({'monitor_id':row['monitor_id'],'state':state})
                if state==row.get('last_state'):continue
                previous=row.get('last_state');row['last_state']=state
                # Queue/running transitions are retained without waking the Agent.
                if state not in {'succeeded','failed','timed_out','cancelled','unknown'}:
                    write(p,row);continue
                row['sequence']+=1
                eid='event_'+hashlib.sha256(f"{row['monitor_id']}:{row['sequence']}:{state}".encode()).hexdigest()[:32]
                event={**row,'schema_version':'ts-job-monitor-event/1','event_id':eid,'state':state,
                    'previous_state':previous,'status_digest':digest({'state':state,'exit_code':status.exit_code}),
                    'program_status':None,'exit_status':status.exit_code,'error_class':None,
                    'error':status.error,'observed_at':now(),'status':{'state':state,'exit_code':status.exit_code}}
                write(p.parent/'events'/f'{eid}.json',event)
                write(p.parent/'deliveries'/f'{eid}.json',{'event_id':eid,'session_id':row['session_id'],
                    'request_id':'job-wake:'+eid,'delivered':False})
                write(p,row)
            except Exception as exc:errors.append(str(exc))
        return {'monitors':observed,'registration_errors':errors}
    deliveries=sorted(base.glob('*/deliveries/*.json'))
    if action=='pending':
        from research_state.agent_workspace import read_liveness
        state=read_liveness(root)
        token=f"{state['revision']}:{state.get('checkpoint_id')}"
        return {'deliveries':[row for p in deliveries if not (row:=read(p)).get('delivered')
                              and row.get('deferred_state') != token]}
    eid=args.get('event_id')
    path=next((p for p in deliveries if p.stem==eid),None)
    if path is None:raise ValueError('unknown monitor event')
    if action=='event':return read(path.parent.parent/'events'/f'{eid}.json')
    row=read(path)
    if args.get('channel')!='wake':return {'claimed':False}
    if action=='claim':
        if row.get('delivered') or row.get('lease_until',0)>time.time():return {'claimed':False}
        row.update(claim_token=uuid.uuid4().hex,lease_until=time.time()+60)
        write(path,row);return {**row,'claimed':True}
    if action=='complete':
        if row.get('claim_token')!=args.get('claim_token'):raise ValueError('stale wake claim')
        row.update(delivered=bool(args.get('delivered')),error=args.get('error'),lease_until=0,
                   deferred_state=args.get('deferred_state'))
        write(path,row);return {'ok':True}
    raise ValueError('unknown monitor command')
