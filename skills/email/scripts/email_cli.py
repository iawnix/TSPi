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
            result=request
        else:
            result=delivery.notify_user(root,Path(a.request_file))
        code=0
    except Exception as exc:
        result=notification_error_payload(exc);code=2
    prepared_request = result if a.command == 'prepare' and code == 0 else None
    if a.command in {'prepare', 'send'} and (root / 'research/journal.json').is_file():
        try:
            from research_agent.foundation.transactions import TransactionCoordinator
            from research_agent.application.job_state import persist_event, project_events
            fact = result
            receipt_ref = result.get('receipt_ref')
            if receipt_ref:
                _, receipt_path = workspace_path(root, receipt_ref, must_exist=True)
                fact = json.loads(receipt_path.read_text())
            # A sent receipt has the same identity on retry (already_sent).
            # Persist before projection so a later context read can recover
            # without repeating any email command or external effect.
            identity = ['email', receipt_ref, fact.get('state')] if receipt_ref else ['email', a.command, fact]
            with TransactionCoordinator(root).locked():
                event_id = persist_event(root, kind='delivery', title='Email ' + a.command,
                    content=json.dumps(fact, ensure_ascii=False), data=fact,
                    references=[receipt_ref] if receipt_ref else [], identity=identity)
                failures = project_events(root)
            pending = next((item for item in failures if item['event_id'] == event_id), None)
            if pending:
                result = {**result, 'journal_error': pending['error']}
        except Exception as error:
            # Delivery receipts remain authoritative even when journaling fails.
            result = {**result, 'journal_error': str(error)}
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    # A projection diagnostic is not part of the canonical send request.
    output.write_text(json.dumps(prepared_request if prepared_request is not None else result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return code


if __name__=='__main__':raise SystemExit(main())
