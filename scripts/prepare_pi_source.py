"""Resolve and verify the pinned Pi source tree used by the native app server."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "config" / "pi-source.json"
PATCH_PATH = ROOT / "config" / "pi-worker-entry.patch"
MULTI_WORKSPACE_PATCH_PATH = ROOT / "config" / "pi-multi-workspace.patch"
MULTI_WORKSPACE_CREATE_PATCH_PATH = ROOT / "config" / "pi-multi-workspace-create.patch"
WORKSPACE_SESSION_LIST_PATCH_PATH = ROOT / "config" / "pi-workspace-session-list.patch"
RESEARCH_WORKSPACE_PATCH_PATH = ROOT / "config" / "pi-research-workspace.patch"
SYSTEM_PROMPT_PATCH_PATH = ROOT / "config" / "pi-system-prompt.patch"
SOURCE_RESOLVER_PATCH_PATH = ROOT / "config" / "pi-source-resolver.patch"
MODEL_DATA_PATCH_PATH = ROOT / "config" / "pi-model-data.patch"
PRESENTATION_LAYOUT_PATCH_PATH = ROOT / "config" / "pi-presentation-layout.patch"
TOOL_RENDERERS_PATCH_PATH = ROOT / "config" / "pi-tool-renderers.patch"
HARNESS_ADMISSION_PATCH_PATH = ROOT / "config" / "pi-harness-admission.patch"
HARNESS_ADMISSION_QUEUE_PATCH_PATH = ROOT / "config" / "pi-harness-admission-queue.patch"
HARNESS_OPERATION_REQUEST_PATCH_PATH = ROOT / "config" / "pi-harness-operation-request.patch"
HARNESS_OPERATION_FORWARD_PATCH_PATH = ROOT / "config" / "pi-harness-operation-forward.patch"
TRANSCRIPT_JSON_PATCH_PATH = ROOT / "config" / "pi-transcript-json.patch"


class PiSourceError(RuntimeError):
    pass


def _pin() -> dict[str, object]:
    value = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("commit"), str):
        raise PiSourceError(f"invalid Pi source pin: {PIN_PATH}")
    return value


def _git(source: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise PiSourceError(f"cannot inspect Pi source {source}: {detail.strip()}") from exc
    return result.stdout.strip()


def verify(source: Path) -> str:
    expected = str(_pin()["commit"])
    if not source.is_dir() or not (source / ".git").exists():
        raise PiSourceError(f"Pi source is not a Git checkout: {source}")
    commit = _git(source, "rev-parse", "HEAD")
    if commit != expected:
        raise PiSourceError(f"Pi source commit mismatch: expected {expected}, found {commit}")
    if not (source / "packages" / "coding-agent" / "src" / "experimental" / "cli.ts").is_file():
        raise PiSourceError(f"Pi source does not contain the experimental CLI: {source}")
    marker = "PI_SESSION_WORKER_ENTRY"
    process_path = source / "packages" / "coding-agent" / "src" / "experimental" / "process.ts"
    if marker not in process_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi Worker entrypoint patch: {source}")
    sessions_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "sessions.ts"
    sessions = sessions_path.read_text(encoding="utf-8")
    server_path = source / "packages" / "coding-agent" / "src" / "experimental" / "server.ts"
    server = server_path.read_text(encoding="utf-8")
    services_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "server.ts"
    services = services_path.read_text(encoding="utf-8")
    client_path = source / "packages" / "coding-agent" / "src" / "experimental" / "client.ts"
    client = client_path.read_text(encoding="utf-8") if client_path.is_file() else ""
    multi_workspace_markers = {
        "workspace service": "tspi.workspace-directory" in sessions,
        "workspaceId session binding": "workspaceId?: string" in sessions and "createOptions.workspaceId" in server,
        "workspace creation": "createWorkspace: createWorkspaceRoot" in server,
        "workspace create service": "createWorkspace(workspaceId: string" in services and "create: (workspaceId, context)" in services,
        "ResearchMap workspace schema": (
            "isSupportedWorkspaceIdentity" in server
            or 'identity?.schema_version !== "research-workspace/1"' in server
        ),
        "workspace validation diagnostic": 'new RoutedServerError("service_invalid_value", `Session cwd is not a supported TSPi workspace:' in server,
        "workspace-scoped session listing": ".filter(sessionMatchesCwd)" in client,
    }
    missing = [label for label, present in multi_workspace_markers.items() if not present]
    if missing:
        raise PiSourceError(f"Pi source is missing the complete TSPi multi-workspace patch ({', '.join(missing)}): {source}")
    slash_commands_path = (
        source
        / "packages"
        / "coding-agent"
        / "src"
        / "experimental"
        / "services"
        / "slash-commands-provider.ts"
    )
    if "tspi.system-prompt" not in slash_commands_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi system prompt patch: {source}")
    resolver_path = source / "packages" / "coding-agent" / "src" / "experimental" / "source-resolver.ts"
    if 'pattern === "typebox"' not in resolver_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi source resolver patch: {source}")
    model_generator = source / "packages" / "ai" / "scripts" / "generate-models.ts"
    if 'data["kimi-code-plan-global"]' not in model_generator.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the Kimi model catalog compatibility patch: {source}")
    layout_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "presentation-layout.ts"
    if "pi.local.presentation-layout" not in layout_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi presentation layout patch: {source}")
    renderer_layout = layout_path.read_text(encoding="utf-8")
    renderer_client = (source / "packages" / "coding-agent" / "src" / "experimental" / "client-tui.ts").read_text(encoding="utf-8")
    renderer_chat = (source / "packages" / "coding-agent" / "src" / "experimental" / "client-tui-chat.ts").read_text(encoding="utf-8")
    if "setToolRenderers" not in renderer_layout or "PresentationToolRenderers" not in renderer_client or "#builtInRenderers" not in renderer_chat:
        raise PiSourceError(f"Pi source is missing the TSPi native tool renderer patch: {source}")
    transcript_provider_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "transcript-provider.ts"
    if "function toStrictJson" not in transcript_provider_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi Transcript JSON patch: {source}")
    controller_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "agent-controller.ts"
    provider_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "agent-controller-provider.ts"
    provider = provider_path.read_text(encoding="utf-8")
    if (
        "startPrompt(request" not in controller_path.read_text(encoding="utf-8")
        or "operationId?: string" not in controller_path.read_text(encoding="utf-8")
        or "const admitAndDrive" not in provider
        or "nothing_queued" not in provider
        or "const watch = await lane.watch(context)" not in provider
    ):
        raise PiSourceError(f"Pi source is missing the non-blocking TSPi Harness admission patch: {source}")
    return commit


def apply_worker_patch(source: Path) -> None:
    process_path = source / "packages" / "coding-agent" / "src" / "experimental" / "process.ts"
    if "PI_SESSION_WORKER_ENTRY" in process_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi Worker entrypoint patch: {exc}") from exc


def apply_multi_workspace_patch(source: Path) -> None:
    sessions_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "sessions.ts"
    server_path = source / "packages" / "coding-agent" / "src" / "experimental" / "server.ts"
    services_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "server.ts"
    sessions = sessions_path.read_text(encoding="utf-8")
    server = server_path.read_text(encoding="utf-8")
    services = services_path.read_text(encoding="utf-8")
    if (
        "tspi.workspace-directory" in sessions
        and "workspaceId?: string" in sessions
        and "createWorkspace: createWorkspaceRoot" in server
        and "createWorkspace(workspaceId: string" in services
        and "create: (workspaceId, context)" in services
    ):
        return
    patch_path = MULTI_WORKSPACE_CREATE_PATCH_PATH if "tspi.workspace-directory" in sessions else MULTI_WORKSPACE_PATCH_PATH
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(patch_path)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        # An older release may already carry the list-only workspace patch in
        # its working tree. A three-way apply uses the pinned Pi commit as the
        # merge base and upgrades that partial patch without requiring a clean
        # checkout.
        try:
            subprocess.run(
                ["git", "-C", str(source), "apply", "--3way", str(patch_path)],
                check=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as fallback:
            raise PiSourceError(
                f"failed to upgrade TSPi multi-workspace patch ({patch_path.name}): {fallback}"
            ) from exc


def apply_workspace_session_list_patch(source: Path) -> None:
    """Keep non-interactive session discovery within the selected workspace."""
    client_path = source / "packages" / "coding-agent" / "src" / "experimental" / "client.ts"
    if ".filter(sessionMatchesCwd)" in client_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(
            ["git", "-C", str(source), "apply", str(WORKSPACE_SESSION_LIST_PATCH_PATH)],
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply workspace-scoped session list patch: {exc}") from exc


def apply_research_workspace_patch(source: Path) -> None:
    """Upgrade already-patched Pi trees to the canonical ResearchMap identity."""
    server_path = source / "packages" / "coding-agent" / "src" / "experimental" / "server.ts"
    server = server_path.read_text(encoding="utf-8")
    if "isSupportedWorkspaceIdentity" in server or (
        'identity?.schema_version !== "research-workspace/1"' in server
        and 'new RoutedServerError("service_invalid_value", `Session cwd is not a supported TSPi workspace:' in server
    ):
        return
    try:
        subprocess.run(
            ["git", "-C", str(source), "apply", str(RESEARCH_WORKSPACE_PATCH_PATH)],
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi ResearchMap workspace patch: {exc}") from exc


def apply_system_prompt_patch(source: Path) -> None:
    slash_commands_path = (
        source
        / "packages"
        / "coding-agent"
        / "src"
        / "experimental"
        / "services"
        / "slash-commands-provider.ts"
    )
    if "tspi.system-prompt" in slash_commands_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(
            ["git", "-C", str(source), "apply", "--ignore-whitespace", str(SYSTEM_PROMPT_PATCH_PATH)],
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi system prompt patch: {exc}") from exc


def apply_source_resolver_patch(source: Path) -> None:
    resolver_path = source / "packages" / "coding-agent" / "src" / "experimental" / "source-resolver.ts"
    if 'pattern === "typebox"' in resolver_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(SOURCE_RESOLVER_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi source resolver patch: {exc}") from exc


def apply_model_data_patch(source: Path) -> None:
    model_generator = source / "packages" / "ai" / "scripts" / "generate-models.ts"
    if 'data["kimi-code-plan-global"]' in model_generator.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(MODEL_DATA_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply Pi model catalog compatibility patch: {exc}") from exc


def apply_presentation_layout_patch(source: Path) -> None:
    marker = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "presentation-layout.ts"
    if marker.is_file() and "pi.local.presentation-layout" in marker.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(PRESENTATION_LAYOUT_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply Pi presentation layout patch: {exc}") from exc


def apply_tool_renderers_patch(source: Path) -> None:
    """Upgrade a prepared Pi tree with process-local native tool renderers."""
    layout_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "presentation-layout.ts"
    chat_path = source / "packages" / "coding-agent" / "src" / "experimental" / "client-tui-chat.ts"
    if layout_path.is_file() and chat_path.is_file():
        layout = layout_path.read_text(encoding="utf-8")
        chat = chat_path.read_text(encoding="utf-8")
        if "setToolRenderers" in layout and "#builtInRenderers" in chat:
            return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(TOOL_RENDERERS_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply Pi native tool renderer patch: {exc}") from exc


def apply_transcript_json_patch(source: Path) -> None:
    """Keep replicated Transcript updates within Chord's strict JSON contract."""
    provider_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "transcript-provider.ts"
    if "function toStrictJson" in provider_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(TRANSCRIPT_JSON_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply Pi Transcript JSON patch: {exc}") from exc


def apply_harness_admission_patch(source: Path) -> None:
    """Expose durable accept-then-drive methods to Host clients.

    The patch is deliberately kept in the TSPi repository and applied only to
    the pinned checkout. This prevents an arbitrary local Pi tree from being
    loaded as the Harness runtime.
    """
    controller_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "agent-controller.ts"
    provider_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "agent-controller-provider.ts"
    provider = provider_path.read_text(encoding="utf-8")
    controller = controller_path.read_text(encoding="utf-8")
    has_admission = "const admitAndDrive" in provider and "startQueued" in provider
    has_queue_upgrade = "nothing_queued" in provider and "const watch = await lane.watch(context)" in provider
    if not has_admission:
        try:
            subprocess.run(["git", "-C", str(source), "apply", str(HARNESS_ADMISSION_PATCH_PATH)], check=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PiSourceError(f"failed to apply TSPi Harness admission patch: {exc}") from exc
        provider = provider_path.read_text(encoding="utf-8")
        controller = controller_path.read_text(encoding="utf-8")
        has_admission = True
        has_queue_upgrade = "nothing_queued" in provider and "const watch = await lane.watch(context)" in provider
    if has_admission and not has_queue_upgrade:
        try:
            subprocess.run(
                ["git", "-C", str(source), "apply", str(HARNESS_ADMISSION_QUEUE_PATCH_PATH)],
                check=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PiSourceError(f"failed to upgrade TSPi Harness queue admission patch: {exc}") from exc

    # The first Harness patch already carries the operation-id field. Keep the
    # operation hint as two small upgrades so a checkout prepared by an older
    # release (including one that already has the queue patch) can be repaired
    # without reapplying the whole multi-file patch.
    controller = controller_path.read_text(encoding="utf-8")
    if "operationId?: string" not in controller:
        try:
            subprocess.run(
                ["git", "-C", str(source), "apply", str(HARNESS_OPERATION_REQUEST_PATCH_PATH)],
                check=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PiSourceError(f"failed to apply TSPi Harness operation request patch: {exc}") from exc
    provider = provider_path.read_text(encoding="utf-8")
    if "request.operationId === undefined" not in provider:
        try:
            subprocess.run(
                ["git", "-C", str(source), "apply", str(HARNESS_OPERATION_FORWARD_PATCH_PATH)],
                check=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PiSourceError(f"failed to apply TSPi Harness operation forwarding patch: {exc}") from exc


def clone(destination: Path) -> Path:
    pin = _pin()
    if destination.exists():
        raise PiSourceError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", "--no-checkout", str(pin["repository"]), str(destination)], check=True)
        _git(destination, "fetch", "--depth", "1", "origin", str(pin["commit"]))
        _git(destination, "checkout", "--detach", str(pin["commit"]))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to clone pinned Pi source: {exc}") from exc
    apply_worker_patch(destination)
    apply_multi_workspace_patch(destination)
    apply_workspace_session_list_patch(destination)
    apply_research_workspace_patch(destination)
    apply_system_prompt_patch(destination)
    apply_source_resolver_patch(destination)
    apply_model_data_patch(destination)
    apply_presentation_layout_patch(destination)
    apply_tool_renderers_patch(destination)
    apply_transcript_json_patch(destination)
    apply_harness_admission_patch(destination)
    verify(destination)
    return destination


def install(install_root: Path) -> Path:
    """Install the pinned, patched Pi tree used by App Server processes."""
    commit = str(_pin()["commit"])
    destination = install_root.resolve() / ".pi" / "runtime-cache" / "pi" / commit
    if destination.exists():
        apply_worker_patch(destination)
        apply_multi_workspace_patch(destination)
        apply_workspace_session_list_patch(destination)
        apply_research_workspace_patch(destination)
        apply_system_prompt_patch(destination)
        apply_source_resolver_patch(destination)
        apply_model_data_patch(destination)
        apply_presentation_layout_patch(destination)
        apply_tool_renderers_patch(destination)
        apply_transcript_json_patch(destination)
        apply_harness_admission_patch(destination)
        verify(destination)
        if not (destination / "node_modules").is_dir():
            _install_dependencies(destination)
        _prepare_runtime_build(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".pi-source-", dir=destination.parent) as temporary:
        staged = Path(temporary) / commit
        clone(staged)
        _install_dependencies(staged)
        _prepare_runtime_build(staged)
        os.replace(staged, destination)
    return destination


def _install_dependencies(source: Path) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise PiSourceError("npm is required to install the managed Pi App Server runtime")
    try:
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=source, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to install pinned Pi dependencies: {exc}") from exc


def _prepare_runtime_build(source: Path) -> None:
    """The source entrypoint still imports generated model data and package dist files."""
    npm = shutil.which("npm")
    if npm is None:
        raise PiSourceError("npm is required to prepare the pinned Pi runtime")
    try:
        if not (source / "packages/ai/src/providers/data/amazon-bedrock.json").is_file():
            subprocess.run([npm, "run", "hydrate:model-data"], cwd=source, check=True)
        required = ("packages/chord/dist/index.js", "packages/coding-agent/dist/bundle")
        if any(not (source / path).exists() for path in required):
            subprocess.run([npm, "run", "build:offline"], cwd=source, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to build pinned Pi runtime: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", type=Path, metavar="SOURCE_ROOT")
    group.add_argument("--clone", type=Path, metavar="DESTINATION")
    group.add_argument("--install", type=Path, metavar="INSTALL_ROOT")
    parser.add_argument("--apply-worker-patch", action="store_true", help="apply the native Worker entrypoint patch before verification")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            if args.apply_worker_patch:
                apply_worker_patch(args.verify)
            source = verify(args.verify)
        elif args.clone is not None:
            if args.apply_worker_patch:
                parser.error("--apply-worker-patch is only valid with --verify")
            source = clone(args.clone)
        else:
            if args.apply_worker_patch:
                parser.error("--apply-worker-patch is only valid with --verify")
            source = install(args.install)
    except PiSourceError as exc:
        parser.error(str(exc))
    print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
