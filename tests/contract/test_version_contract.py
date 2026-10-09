"""Release versions must stay coherent without rewriting dependency identities."""
import json
import shutil

import pytest

from tools import version


def test_rc_release_maps_to_python_and_preserves_dependency_locks(tmp_path):
    for relative in (*version.MANIFESTS, *version.LOCKS, "backend/src/research_agent/_version.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(version.ROOT / relative, target)
    lock_before = json.loads((tmp_path / "package-lock.json").read_text())
    for path, content in version.generated(tmp_path, "0.19.0-rc.2").items():
        path.write_text(content)
    version.check(tmp_path)
    assert '__version__ = "0.19.0rc2"' in (tmp_path / "backend/src/research_agent/_version.py").read_text()
    lock_after = json.loads((tmp_path / "package-lock.json").read_text())
    assert {key: value for key, value in lock_after["packages"].items() if key} == {
        key: value for key, value in lock_before["packages"].items() if key
    }
    relay = tmp_path / "services/relay/package.json"
    value = json.loads(relay.read_text())
    value["version"] = "0.18.0"
    relay.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="services/relay/package.json"):
        version.check(tmp_path)


@pytest.mark.parametrize("value", ["01.2.3", "1.2", "1.2.3-beta.1", "1.2.3-rc.01", "1.2.3+local"])
def test_unsupported_release_versions_are_rejected(value):
    with pytest.raises(ValueError):
        version.python_version(value)
