"""Installation-configured email Skill: prepare without sending, send, inspect."""
import argparse
import json
from pathlib import Path
import sys
from notify_lib import delivery
from notify_lib.artifacts import workspace_path, sha256_path
from notify_lib.errors import notification_error_payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['check','prepare','send','status'])
    p.add_argument('--root',required=True)
    p.add_argument('--request-file')
    p.add_argument('--output',required=True,help='request (prepare) or local receipt output')
    p.add_argument('--receipt-ref')
    a=p.parse_args();root=Path(a.root).resolve()
    try:
        if a.command=='status':
            _,path=workspace_path(root,a.receipt_ref,must_exist=True)
            result=json.loads(path.read_text())
        elif a.command=='check':
            config=delivery.load_notification_config()
            result={'enabled':config.enabled,'recipient':config.recipient,'transport':config.provider}
        elif a.command=='prepare':
            config=delivery.load_notification_config()
            request=json.loads(Path(a.request_file).read_text())
            request.update(schema_version='ts-user-notification/2',recipient=config.recipient)
            delivery.bounded_text(request.get('notification_id'),'notification_id',256)
            records=[]
            for ref in request.get('report_refs',[]):
                ref,path=workspace_path(root,ref,must_exist=True)
                records.append({'ref':ref,'sha256':sha256_path(path),'size_bytes':path.stat().st_size})
            request['attachments']=records
            # Use the same shape and bounded-content validation as sending.
            delivery._event(request.get('event'))
            delivery.bounded_text(request.get('subject'),'subject',300)
            delivery.bounded_content(request.get('summary'),'summary',20000)
            if (root / 'research_map/context.json').exists():
                from research_state.agent_workspace import read_context
                from research_state.delivery import delivery_snapshot
                request['state_binding'] = delivery_snapshot(read_context(root), request.get('node_id'), request['event'], root=root)
            result=request
        else:
            result=delivery.notify_user(root,Path(a.request_file))
        code=0
    except Exception as exc:
        result=notification_error_payload(exc);code=2
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return code


if __name__=='__main__':raise SystemExit(main())
