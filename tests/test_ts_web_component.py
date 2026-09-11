from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts._suite import WEB_COMPONENT_FILES, load_web_manifest
from scripts.build_web import build_web


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "components" / "ts-web"


def test_web_component_source_has_no_private_ts_agent_imports() -> None:
    for path in COMPONENT_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "import ts_agent" not in source
        assert "from ts_agent" not in source


def test_web_component_archive_is_complete_and_validated(tmp_path: Path) -> None:
    result = build_web(tmp_path, allow_dirty=True)
    manifest_path = Path(result["manifest"])
    manifest = load_web_manifest(manifest_path)

    assert manifest["component"] == {"name": "ts-web", "version": "0.17.0"}
    assert manifest["entrypoint"] == {"path": "bin/ts-web"}
    with tarfile.open(Path(result["archive"]), "r:gz") as archive:
        files = {
            member.name.removeprefix("component/")
            for member in archive.getmembers()
            if member.isfile()
        }
    assert files == set(WEB_COMPONENT_FILES)


def test_web_component_protocol_schemas_validate_envelopes() -> None:
    contract_root = ROOT / "contracts" / "ts-web"
    request_schema = json.loads(
        (contract_root / "provider-request.schema.json").read_text(encoding="utf-8")
    )
    response_schema = json.loads(
        (contract_root / "provider-response.schema.json").read_text(encoding="utf-8")
    )
    component_schema = json.loads(
        (contract_root / "component-manifest.schema.json").read_text(encoding="utf-8")
    )

    request = {
        "schema_version": "ts-web-provider-request/1",
        "request_id": "schema-check",
        "operation": "catalog",
        "workspace_id": None,
        "route": None,
        "query": {},
    }
    Draft202012Validator(request_schema).validate(request)
    Draft202012Validator(response_schema).validate(
        {
            "schema_version": "ts-web-provider/1",
            "request_id": "schema-check",
            "ok": True,
            "payload": {"workspaces": []},
        }
    )
    Draft202012Validator(component_schema).validate(
        {
            "schema_version": "ts-web-component-release/1",
            "release_id": "0.17.0-sha256-0123456789abcdef",
            "component": {"name": "ts-web", "version": "0.17.0"},
            "protocols": {
                "provider": "ts-web-provider/1",
                "projection": "ts-web-workspace/6",
                "graph": "ts-explorer-graph/6",
                "theme": "ts-theme/1",
            },
            "entrypoint": {"path": "bin/ts-web"},
            "archive": {
                "filename": "ts-web-component-0.17.0-sha256-0123456789abcdef.tgz",
                "sha256": "0" * 64,
                "size_bytes": 1,
            },
            "source": {"git_commit": None, "dirty": False},
            "created_at_utc": "2026-09-11T00:00:00+00:00",
        }
    )


def test_provider_json_lines_does_not_reuse_a_previous_request_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    provider = ROOT / "scripts" / "ts_web_provider.py"
    first = {
        "schema_version": "ts-web-provider-request/1",
        "request_id": "first",
        "operation": "catalog",
        "workspace_id": None,
        "route": None,
        "query": {},
    }
    completed = subprocess.run(
        [sys.executable, str(provider), "--state-dir", str(state_dir)],
        input=json.dumps(first) + "\n{not-json}\n",
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["request_id"] for response in responses] == ["first", "unknown"]
    assert responses[0]["ok"] is True
    assert responses[1]["ok"] is False
