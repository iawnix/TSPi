#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'packages/tspi-runtime')); sys.path.insert(0,str(ROOT/'packages/research-state')); sys.path.insert(0,str(ROOT/'packages/research-memory')); sys.path.insert(0,str(ROOT/'packages/research-compute'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tspi_runtime.providers.runner import run_jsonl_provider
_seen=set()
def handle(req):
    key=req.parameters.get('idempotency_key') or req.request_id
    if key in _seen: return {'status':'succeeded','result':{'receipt_status':'already_sent','idempotency_key':key},'outputs':[],'provenance':{'provider_id':req.provider_id,'request_id':req.request_id},'diagnostics':[]}
    _seen.add(key)
    return {'status':'succeeded','result':{'receipt_status':'sent','idempotency_key':key},'outputs':[],'provenance':{'provider_id':req.provider_id,'request_id':req.request_id},'diagnostics':[]}
if __name__=='__main__': raise SystemExit(run_jsonl_provider(handle))
