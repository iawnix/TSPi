#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'packages/tspi-runtime')); sys.path.insert(0,str(ROOT/'packages/research-state')); sys.path.insert(0,str(ROOT/'packages/research-memory')); sys.path.insert(0,str(ROOT/'packages/research-compute'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tspi_runtime.providers.runner import run_jsonl_provider
def handle(req):
    return {'status':'succeeded','result':{'operation':req.operation,'provider':'tspi-render'},'outputs':[],'provenance':{'provider_id':req.provider_id,'request_id':req.request_id},'diagnostics':[]}
if __name__=='__main__': raise SystemExit(run_jsonl_provider(handle))
