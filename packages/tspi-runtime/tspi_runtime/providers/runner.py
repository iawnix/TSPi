from __future__ import annotations
import json, sys, traceback
from typing import Callable, Any
from .protocol import ProviderRequest, ProviderError

def run_jsonl_provider(handler:Callable[[ProviderRequest],dict[str,Any]], *, stdin=None, stdout=None)->int:
    stdin=stdin or sys.stdin; stdout=stdout or sys.stdout
    for line in stdin:
        if not line.strip(): continue
        try:
            request=ProviderRequest.from_dict(json.loads(line)); result=handler(request)
            if not isinstance(result,dict) or result.get("status") not in {"succeeded","failed","cancelled","timed_out"}: raise ProviderError("malformed provider result")
        except Exception as exc:
            result={"status":"failed","result":None,"outputs":[],"provenance":{},"diagnostics":[{"code":"provider_error","message":str(exc)}]}
        stdout.write(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n"); stdout.flush()
    return 0
