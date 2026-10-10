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


ROOT = Path(__file__).resolve().parents[2]
COMPONENT_ROOT = ROOT / "components" / "coragent-web"


def test_web_cli_uses_explicit_provider_and_shared_catalog(tmp_path: Path, monkeypatch) -> None:
    from research_agent.research.workspace import initialize_workspace, admit_research_workspace
    from research_agent.research.workspace_catalog import WorkspaceCatalog

    monkeypatch.delenv("CORAGENT_WEB_PROVIDER", raising=False)
    external = tmp_path / "external"
    initialize_workspace(external, "study", "research")
    admit_research_workspace(external)
    workspace_root = tmp_path / "projects"
    state_dir = tmp_path / "web-state"
    entry = [sys.executable, str(COMPONENT_ROOT / "bin/coragent-web")]
    provider = str(ROOT / "apps/agent-cli/research_web_bridge.py")

    def invoke(command: str, *arguments: str) -> object:
        result = subprocess.run(
            [*entry, "--provider", provider, command, "--state-dir", str(state_dir),
             "--workspace-root", str(workspace_root), *arguments],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    invoke("register", "--source-root", str(external), "--label", "External study")
    catalog = WorkspaceCatalog(workspace_root)
    assert catalog.resolve("study")["source_root"] == str(external)
    assert invoke("list")["workspaces"][0]["workspace_id"] == "study"
    invoke("remove", "--workspace-id", "study")
    assert catalog.list() == []
    assert external.is_dir()
    missing_provider = subprocess.run(
        [*entry, "list", "--state-dir", str(state_dir)], capture_output=True, text=True,
    )
    assert missing_provider.returncode != 0
    assert "requires --provider or CORAGENT_WEB_PROVIDER" in missing_provider.stderr


def test_web_component_source_has_no_private_research_agent_runtime_imports() -> None:
    for path in COMPONENT_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "import research_agent.application" not in source
        assert "from research_agent.application" not in source


def test_web_component_archive_is_complete_and_validated(tmp_path: Path) -> None:
    result = build_web(tmp_path, allow_dirty=True)
    manifest_path = Path(result["manifest"])
    manifest = load_web_manifest(manifest_path)

    assert manifest["component"] == {"name": "coragent-web", "version": json.loads((ROOT / "package.json").read_text())["version"]}
    assert manifest["entrypoint"] == {"path": "bin/coragent-web"}
    with tarfile.open(Path(result["archive"]), "r:gz") as archive:
        files = {
            member.name.removeprefix("component/")
            for member in archive.getmembers()
            if member.isfile()
        }
    assert files == set(WEB_COMPONENT_FILES)


def test_web_component_protocol_schemas_validate_envelopes() -> None:
    contract_root = ROOT / "contracts" / "coragent-web"
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
        "schema_version": "research-memory-provider/1",
        "request_id": "schema-check",
        "operation": "catalog",
        "workspace_id": None,
        "route": None,
        "query": {},
    }
    Draft202012Validator(request_schema).validate(request)
    Draft202012Validator(response_schema).validate(
        {
            "schema_version": "research-memory-provider/1",
            "request_id": "schema-check",
            "ok": True,
            "payload": {"workspaces": []},
        }
    )
    Draft202012Validator(component_schema).validate(
        {
            "schema_version": "coragent-web-component-release/1",
            "release_id": "0.17.0-sha256-0123456789abcdef",
            "component": {"name": "coragent-web", "version": "0.18.0"},
            "protocols": {
                "provider": "research-memory-provider/1",
                "snapshot": "research-snapshot/3",
                "theme": "coragent-theme/1",
            },
            "entrypoint": {"path": "bin/coragent-web"},
            "archive": {
                "filename": "coragent-web-component-0.17.0-sha256-0123456789abcdef.tgz",
                "sha256": "0" * 64,
                "size_bytes": 1,
            },
            "source": {"git_commit": None, "dirty": False},
            "created_at_utc": "2026-09-11T00:00:00+00:00",
        }
    )


def test_provider_json_lines_does_not_reuse_a_previous_request_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    provider = ROOT / "apps" / "agent-cli" / "research_web_bridge.py"
    first = {
        "schema_version": "research-memory-provider/1",
        "request_id": "first",
        "operation": "catalog",
        "workspace_id": None,
        "route": None,
        "query": {},
    }
    completed = subprocess.run(
        [sys.executable, str(provider), "--state-dir", str(state_dir)],
        input=json.dumps(first) + "\n{not-json}\n" + "x" * (2 * 1024 * 1024 + 1) + "\n" + json.dumps({**first, "request_id": "after-errors"}) + "\n",
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["request_id"] for response in responses] == ["first", "unknown", "unknown", "after-errors"]
    assert responses[0]["ok"] is True
    assert responses[1]["ok"] is False
    assert responses[1]["error"]["schema_version"] == "research-memory-error/1"
    assert responses[2]["ok"] is False
    assert responses[2]["error"]["schema_version"] == "research-memory-error/1"
    assert responses[3]["ok"] is True
