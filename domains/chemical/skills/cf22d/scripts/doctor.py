"""Check CF22D implementation and optimizer dependencies without running SCF."""
import json
from pathlib import Path
import sys
from runner import _load_runtime


def main():
    try:
        _,pyscf,geometric,dispersion=_load_runtime()
        result={'ready':True,'python':sys.executable,'pyscf':pyscf,'geometric':geometric,'dispersion':dispersion}
        code=0
    except Exception as exc:
        result={'ready':False,'error':str(exc),'cause':str(exc.__cause__) if exc.__cause__ else None};code=1
    print(json.dumps(result));return code


if __name__=='__main__':raise SystemExit(main())
