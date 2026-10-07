import hashlib
import json
from pathlib import Path
import runpy

import pytest
from job_runtime import config_contract as contract
from tests.unit.test_job_python_config import binding

ROOT = Path(__file__).resolve().parents[2]
module = runpy.run_path(str(ROOT / "extensions/chemical/skills/_shared/execution_bindings.py"))
check = module["check_environments"]


def config():
    return {"default_environment": "local", "environments": {"local": {"kind": "local", "backends": {
        "pyscf": {"command": "/old/python"}, "xtb": {"command": "/opt/xtb"}}}}}


def test_old_install_source_rejected_before_any_probe():
    old = config()
    assert contract.validate_job_config(old)
    with pytest.raises(ValueError, match="science_binding_not_ready.*python_binding_missing"):
        check(old, contract=contract)
    old["environments"]["local"]["python"] = binding("/opt/runner")
    with pytest.raises(ValueError, match="sole Python binding"):
        check(old, contract=contract)


def test_inherited_python_matches_helper_and_remote_gaps_are_visible():
    c = config(); local = c["environments"]["local"]
    local["python"] = binding("/opt/runner")
    local["backends"]["pyscf"] = {}
    c["environments"]["remote"] = {"kind": "remote", "backends": {"xtb": {"command": "xtb"}}}
    report = check(c, contract=contract)
    assert report["local"]["pyscf"]["status"] == "static_valid"
    assert report["remote"]["xtb"]["status"] == "invalid"
    c["default_environment"] = "remote"
    with pytest.raises(ValueError, match="science_binding_not_ready"):
        check(c, contract=contract)


def test_local_environment_receipt_and_lock_drift_are_detected(tmp_path, monkeypatch):
    prefix = tmp_path / "env"; prefix.mkdir()
    conda = tmp_path / "conda"; conda.touch()
    lock = tmp_path / "runner.lock"; lock.write_text("@EXPLICIT\nhttps://example.test/python.conda\n")
    b = {**binding(str(prefix)), "conda_executable": str(conda), "lock_ref": str(lock)}
    c = {"default_environment": "local", "environments": {"local": {
        "kind": "local", "python": b, "backends": {"xtb": {"command": "xtb"}}}}}
    with pytest.raises(ValueError, match="no verified receipt"):
        check(c, contract=contract, probe_local=True)
    (prefix / "tspi-environment.json").write_text(json.dumps({
        "lock_sha256": "sha256:" + hashlib.sha256(lock.read_bytes() + b"\0").hexdigest(),
        "binding_sha256": contract.binding_digest(b)}))
    probe = module["_probe_local"]
    monkeypatch.setitem(probe.__globals__, "_run", lambda argv: lock.read_text() if "list" in argv else '{}')
    assert check(c, contract=contract, probe_local=True)["local"]["xtb"]["status"] == "local_ready"
    monkeypatch.setitem(probe.__globals__, "_run", lambda argv: '@EXPLICIT\nhttps://example.test/wrong.conda\n')
    with pytest.raises(ValueError, match="does not match its explicit"):
        check(c, contract=contract, probe_local=True)
    lock.write_text('@EXPLICIT\nhttps://example.test/new.conda\n')
    with pytest.raises(ValueError, match="receipt does not match"):
        check(c, contract=contract, probe_local=True)
