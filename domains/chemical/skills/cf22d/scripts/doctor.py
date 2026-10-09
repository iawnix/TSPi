"""Check CF22D implementation and optimizer dependencies without running SCF."""
import json
from pathlib import Path
import sys


def main():
    try:
        # Direct invocation uses the same import roots as the managed launcher.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
        from runner import _load_runtime
        _,pyscf,geometric,dispersion=_load_runtime()
        result={'ready':True,'python':sys.executable,'pyscf':pyscf,'geometric':geometric,'dispersion':dispersion}
        code=0
    except Exception as exc:
        cause = exc.__cause__ or exc
        result={'ready':False,'code':'dependency_missing' if isinstance(cause, ModuleNotFoundError) else 'method_initialization_failed',
                'exception_type':type(cause).__name__, 'module':getattr(cause,'name',None),
                'error':str(exc),'cause':str(exc.__cause__) if exc.__cause__ else None};code=1
    print(json.dumps(result));return code


if __name__=='__main__':raise SystemExit(main())
