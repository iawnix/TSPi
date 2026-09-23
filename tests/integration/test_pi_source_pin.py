from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_pi_source_pin_is_explicit_and_valid() -> None:
    pin = json.loads((ROOT / "config" / "pi-source.json").read_text(encoding="utf-8"))
    assert pin["repository"] == "https://github.com/earendil-works/pi.git"
    assert pin["tag"] == "v0.85.1"
    assert len(pin["commit"]) == 40
    assert pin["commit"] == "d981de1229ef899957bbe968bc8dcda02a21f477"
    assert pin["protocolVersion"] == 8
    patch = (ROOT / "config" / "pi-worker-entry.patch").read_text(encoding="utf-8")
    assert "PI_SESSION_WORKER_ENTRY" in patch
    assert "packages/coding-agent/src/experimental/process.ts" in patch
    create_patch = (ROOT / "config" / "pi-multi-workspace-create.patch").read_text(encoding="utf-8")
    assert "createWorkspace(workspaceId" in create_patch
    assert "WorkspaceDirectory" in create_patch
    session_list_patch = (ROOT / "config" / "pi-workspace-session-list.patch").read_text(encoding="utf-8")
    assert ".filter(sessionMatchesCwd)" in session_list_patch
    workspace_patch = (ROOT / "config" / "pi-research-workspace.patch").read_text(encoding="utf-8")
    assert "research-workspace/1" in workspace_patch
    assert "service_invalid_value" in workspace_patch
    resolver_patch = (ROOT / "config" / "pi-source-resolver.patch").read_text(encoding="utf-8")
    assert "source-resolver.ts" in resolver_patch
    assert "resolveTypeboxPath" in resolver_patch
    system_prompt_patch = (ROOT / "config" / "pi-system-prompt.patch").read_text(encoding="utf-8")
    assert "slash-commands-provider.ts" in system_prompt_patch
    assert "tspi.system-prompt" in system_prompt_patch
    model_data_patch = (ROOT / "config" / "pi-model-data.patch").read_text(encoding="utf-8")
    assert "kimi-code-plan-global" in model_data_patch
    renderer_patch = (ROOT / "config" / "pi-tool-renderers.patch").read_text(encoding="utf-8")
    assert "setToolRenderers" in renderer_patch
    assert "PresentationToolRenderers" in renderer_patch
    assert "#builtInRenderers" in renderer_patch
    assert "#toolRendererRegistration !== registration" in renderer_patch
    transcript_patch = (ROOT / "config" / "pi-transcript-json.patch").read_text(encoding="utf-8")
    assert "function toStrictJson" in transcript_patch
    assert "reduceLaneSnapshot(snapshot, forwarded)" in transcript_patch
    assert "details: undefined" in transcript_patch


def test_prepare_pi_source_verifies_a_matching_checkout() -> None:
    configured = os.environ.get("TSPI_PI_SOURCE")
    if not configured:
        return
    source = Path(configured)
    if not source.is_dir():
        return
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "prepare_pi_source.py"), "--verify", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_prepare_runtime_build_is_idempotent(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    monkeypatch.setattr(prepare_pi_source.shutil, "which", lambda name: "/bin/npm")
    calls = []

    def run(command, **kwargs):
        calls.append(command[2])
        outputs = ["packages/ai/src/providers/data/amazon-bedrock.json"] if command[2] == "hydrate:model-data" else ["packages/chord/dist/index.js", "packages/coding-agent/dist/bundle"]
        for output in outputs:
            path = tmp_path / output
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    monkeypatch.setattr(prepare_pi_source.subprocess, "run", run)
    prepare_pi_source._prepare_runtime_build(tmp_path)
    prepare_pi_source._prepare_runtime_build(tmp_path)
    assert calls == ["hydrate:model-data", "build:offline"]


def test_multi_workspace_patch_upgrades_a_list_only_checkout(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    services = source / "packages/coding-agent/src/experimental/services"
    services.mkdir(parents=True)
    (services / "sessions.ts").write_text(
        'export const WorkspaceDirectory = defineService<WorkspaceDirectory>("tspi.workspace-directory");\n',
        encoding="utf-8",
    )
    (services / "server.ts").write_text(
        "listWorkspaces(context: Context): Promise<WorkspaceSummary[]>;\n"
        "provider.provide(WorkspaceDirectory, { list: (context) => options.listWorkspaces(context) });\n",
        encoding="utf-8",
    )
    (source / "packages/coding-agent/src/experimental/server.ts").write_text(
        "listWorkspaces: listWorkspaceRoots,\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)

    monkeypatch.setattr(prepare_pi_source.subprocess, "run", run)

    prepare_pi_source.apply_multi_workspace_patch(source)

    assert calls == [["git", "-C", str(source), "apply", str(prepare_pi_source.MULTI_WORKSPACE_CREATE_PATCH_PATH)]]


def test_research_workspace_patch_upgrades_an_existing_patched_checkout(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    server = source / "packages/coding-agent/src/experimental/server.ts"
    server.parent.mkdir(parents=True)
    server.write_text(
        'if (identity?.schema_version !== "ts-workspace/6") continue;\n'
        'throw new Error(`Session cwd is not a supported TSPi workspace: ${candidate}`);\n',
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        prepare_pi_source.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    prepare_pi_source.apply_research_workspace_patch(source)

    assert calls == [[
        "git",
        "-C",
        str(source),
        "apply",
        str(prepare_pi_source.RESEARCH_WORKSPACE_PATCH_PATH),
    ]]


def test_workspace_session_list_patch_is_idempotent(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    client = source / "packages/coding-agent/src/experimental/client.ts"
    client.parent.mkdir(parents=True)
    client.write_text(".filter(sessionMatchesCwd)\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(prepare_pi_source.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    prepare_pi_source.apply_workspace_session_list_patch(source)

    assert calls == []


def test_tool_renderer_patch_is_idempotent_for_an_upgraded_checkout(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    layout = source / "packages/coding-agent/src/experimental/services"
    chat = source / "packages/coding-agent/src/experimental"
    layout.mkdir(parents=True)
    (layout / "presentation-layout.ts").write_text("setToolRenderers\n", encoding="utf-8")
    (chat / "client-tui-chat.ts").write_text("#builtInRenderers\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(prepare_pi_source.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    prepare_pi_source.apply_tool_renderers_patch(source)

    assert calls == []


def test_transcript_json_patch_is_idempotent_for_an_upgraded_checkout(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    provider = source / "packages/coding-agent/src/experimental/services/transcript-provider.ts"
    provider.parent.mkdir(parents=True)
    provider.write_text("function toStrictJson() {}\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(prepare_pi_source.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    prepare_pi_source.apply_transcript_json_patch(source)

    assert calls == []


def test_pi_source_verify_rejects_a_list_only_workspace_patch(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    source = tmp_path / "pi"
    experimental = source / "packages/coding-agent/src/experimental"
    services = experimental / "services"
    services.mkdir(parents=True)
    (source / ".git").mkdir()
    (experimental / "cli.ts").write_text("", encoding="utf-8")
    (experimental / "process.ts").write_text("PI_SESSION_WORKER_ENTRY", encoding="utf-8")
    (services / "sessions.ts").write_text(
        'export const WorkspaceDirectory = defineService<WorkspaceDirectory>("tspi.workspace-directory");\n',
        encoding="utf-8",
    )
    (experimental / "server.ts").write_text("listWorkspaces: listWorkspaceRoots,\n", encoding="utf-8")
    (services / "server.ts").write_text(
        "listWorkspaces(context: Context): Promise<WorkspaceSummary[]>;\n",
        encoding="utf-8",
    )
    (services / "slash-commands-provider.ts").write_text("tspi.system-prompt", encoding="utf-8")
    (experimental / "source-resolver.ts").write_text('pattern === "typebox"', encoding="utf-8")
    monkeypatch.setattr(prepare_pi_source, "_git", lambda *_args: prepare_pi_source._pin()["commit"])

    with pytest.raises(prepare_pi_source.PiSourceError, match="complete TSPi multi-workspace patch"):
        prepare_pi_source.verify(source)
