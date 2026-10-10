"""Public failure summaries must not disclose private diagnostic content."""
import json
from pathlib import Path

from tools.test.runner import inspect_case_results


def layout(tmp_path):
    source = tmp_path / 'source'
    (source / 'tools/test').mkdir(parents=True)
    (source / 'tools/test/manifest.toml').write_text('''schema_version = "coragent-test-manifest/1"
[suites.integration]
globs = ["tests/test_*.py"]
[suites.native-pi]
globs = ["tests/*.test.mjs"]
''')
    (source / 'tests').mkdir()
    (source / 'tests/test_public.py').write_text('')
    (source / 'tests/public.test.mjs').write_text('')
    (tmp_path / 'report').mkdir()
    (tmp_path / 'logs').mkdir()
    return tmp_path


def test_python_summary_uses_inventory_not_private_case_names(tmp_path):
    run = layout(tmp_path)
    (run / 'report/integration.xml').write_text('''<testsuites><testsuite>
<testcase classname="tests.test_public.Example" name="test_case[private-marker]">
  <failure message="private-marker">private-marker</failure>
  <system-out>private-marker</system-out>
</testcase>
<testcase classname="private-marker" name="private-marker"><error>private-marker</error></testcase>
<testcase classname="tests.test_public" name="test_skip"><skipped>private-marker</skipped></testcase>
</testsuite></testsuites>''')
    result = {'suite': 'integration', 'status': 'failed'}
    inspect_case_results(run, result)
    assert result['failed_files'] == ['tests/test_public.py']
    assert (result['cases'], result['failures'], result['errors'], result['skipped']) == (3, 1, 1, 1)
    assert 'private-marker' not in json.dumps(result)


def test_node_summary_rejects_locations_outside_inventory(tmp_path):
    run = layout(tmp_path)
    public = run / 'source/tests/public.test.mjs'
    (run / 'logs/native-pi.log').write_text(f'''not ok 1 - private-marker
  ---
  location: '{public}:12:1'
  error: 'private-marker'
  ...
not ok 2 - private-marker
  ---
  location: '/private-marker:1:1'
  error: 'private-marker'
  ...
# tests 2
# pass 0
# fail 2
# skipped 0
''')
    result = {'suite': 'native-pi', 'status': 'failed'}
    inspect_case_results(run, result)
    assert result['failed_files'] == ['tests/public.test.mjs']
    assert (result['tests'], result['fail']) == (2, 2)
    assert 'private-marker' not in json.dumps(result)
