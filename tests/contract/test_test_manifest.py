from pathlib import Path
from tools.test.manifest import ROOT,audit,load_manifest,suite_paths


def test_manifest_discovers_each_test_in_exactly_one_primary_suite():
    result=audit()
    assert result['files']>0
    assert {'fast','node-fast','integration','native-pi','source','package'} <= set(load_manifest()['suites'])


def test_native_and_fast_node_suites_do_not_overlap():
    native={Path(path) for path in suite_paths('native-pi')}
    fast={Path(path) for path in suite_paths('node-fast')}
    assert native.isdisjoint(fast)
    assert native|fast==set((ROOT/'tests/node').rglob('*.test.mjs'))
    assert all('native' in path.parts for path in native)


def test_test_root_contains_only_configuration_files():
    assert {path.name for path in (ROOT/'tests').iterdir() if path.is_file()} <= {'__init__.py','conftest.py'}
