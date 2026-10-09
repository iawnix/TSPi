"""Standalone launcher for staged Python tools; no control-plane dependencies."""
import json
from pathlib import Path
import runpy
import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        paths = json.loads(args.pop(0))
        entry = Path(args[0]).resolve(strict=True)
        root = Path.cwd().resolve()
        if not entry.is_relative_to(root) or not isinstance(paths, list):
            raise ValueError('entrypoint_path_invalid')
        imports = [str(entry.parent)]
        for value in paths:
            relative = Path(value)
            path = (root / relative).resolve(strict=True)
            if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root) or not path.is_dir():
                raise ValueError('entrypoint_import_path_invalid')
            imports.append(str(path))
        sys.path[:0] = imports
        sys.argv = [str(entry), *args[1:]]
        runpy.run_path(str(entry), run_name='__main__')
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    except Exception as exc:
        print(json.dumps({'schema_version': 'entrypoint-error/1', 'stage': 'python_entrypoint',
                          'code': 'module_unavailable' if isinstance(exc, ModuleNotFoundError) else 'entrypoint_failed',
                          'exception_type': type(exc).__name__,
                          **({'module': exc.name} if isinstance(exc, ModuleNotFoundError) else {})}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
