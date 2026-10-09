"""Offline Flutter contracts and actual Host interop, owned by the test runner."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def capture_phone(args, root, run, record, replay):
    from tools.test.runner import source_files, digest_source
    if replay:
        metadata = json.loads((replay/'run.json').read_text())['phone']
        shutil.copytree(replay/'phone', run/'phone', ignore=shutil.ignore_patterns('.dart_tool', 'build'))
        record['phone'] = metadata
        return
    if not args.phone_source or not args.flutter_root or not args.pub_cache:
        raise ValueError('phone requires --phone-source, --flutter-root and --pub-cache')
    source=args.phone_source.resolve()
    flutter=args.flutter_root.resolve()
    pub=args.pub_cache.resolve()
    if not flutter.is_relative_to(root) or not pub.is_relative_to(root):
        raise ValueError('Flutter installation and pub cache must be in the private test root')
    if not (flutter/'bin/flutter').is_file() or not pub.is_dir():
        raise ValueError('Prepare the private Flutter SDK and offline pub cache before testing')
    files=source_files(source)
    digest=digest_source(source, files)
    for relative in files:
        original=source/relative
        if original.is_symlink() and not original.resolve().is_relative_to(source):
            raise ValueError('Phone source contains an external symlink')
        destination=run/'phone'/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original,destination)
    if digest_source(source,files)!=digest or digest_source(run/'phone',files)!=digest:
        raise ValueError('Phone source changed while capturing its snapshot')
    record['phone']={'source':str(source),'sha256':digest,'flutter':str(flutter),'pub_cache':str(pub)}


def main():
    run=Path(os.environ['RESEARCH_AGENT_TEST_RUN_ROOT'])
    mobile=run/'phone/apps/mobile'
    flutter=str(Path(os.environ['RESEARCH_AGENT_TEST_FLUTTER_ROOT'])/'bin/flutter')
    subprocess.run([flutter,'pub','get','--offline','--enforce-lockfile'],cwd=mobile,check=True)
    files=sys.argv[1:] or [
        'test/connection_settings_test.dart','test/tspi_link_pairing_test.dart',
        'test/settings_store_test.dart','test/host_gateway_test.dart',
        'test/monitor_page_test.dart','test/host_interop_test.dart',
    ]
    report=run/'report/phone.jsonl'
    with report.open('w') as output:
        result=subprocess.run([flutter,'test','--no-pub','--concurrency=2','--reporter=json',*files],
                              cwd=mobile,stdout=output,check=False)
    counts={'passed':0,'failed':0,'skipped':0}
    for line in report.read_text().splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        if event.get('type')=='testDone' and not event.get('hidden'):
            key='skipped' if event.get('skipped') else 'passed' if event.get('result')=='success' else 'failed'
            counts[key]+=1
    (run/'report/phone-counts.json').write_text(json.dumps(counts)+'\n')
    return int(result.returncode!=0 or counts['failed']!=0 or counts['skipped']!=0 or counts['passed']==0)


if __name__=='__main__': raise SystemExit(main())
