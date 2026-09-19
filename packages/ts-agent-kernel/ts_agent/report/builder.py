"""Build immutable Markdown packages from the canonical ResearchMap."""

from __future__ import annotations

import hashlib
import errno
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ts_agent.workspace.artifacts import resolve_workspace_artifact_ids
from ts_agent.path_safety import has_symlink_component, lexical_path, path_has_symlink
from ts_agent.io import write_json as write_json_atomic, write_text_atomic

from .context import collect_report_context


def build_final_report(root: str | Path) -> str:
    return render_final_report(collect_report_context(root))


def build_report_package(
    root: str | Path,
    output_dir: str | Path | None = None,
    *,
    exclude_activity_refs: Iterable[str] = (),
    asset_artifact_ids: Iterable[str] = (),
) -> dict[str, Any]:
    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ValueError(f"workspace root contains a symbolic link: {root_path}")
    package_dir = lexical_path(output_dir) if output_dir is not None else root_path / "reports" / "final-report"
    reports_root = root_path / "reports"
    if package_dir.parent != reports_root:
        raise ValueError("report package must be a direct child of workspace reports/")
    if path_has_symlink(reports_root) or path_has_symlink(package_dir):
        raise ValueError("report package path cannot contain a symbolic link")
    if reports_root.exists() and not reports_root.is_dir():
        raise ValueError("workspace reports path is not a directory")
    context = collect_report_context(root_path, exclude_activity_refs=exclude_activity_refs)
    research_map = context["research_map"]
    status = context["runtime_status"]
    if package_dir.exists():
        raise ValueError(f"report package already exists: {package_dir}")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.tmp-", dir=package_dir.parent))
    _assert_report_physical_path(staging, "report staging directory")
    try:
        (staging / "assets").mkdir()
        asset_records = _copy_report_assets(root_path, staging / "assets", asset_artifact_ids)
        _write_json(staging / "asset_index.json", {
            "schema_version": "ts-report-asset-index/1",
            "assets": asset_records,
        })
        _write_json(staging / "report_context.json", context)
        _write_json(staging / "research_map.json", research_map)
        _write_json(staging / "claim_graph.json", {
            "claims": research_map["claims"],
            "relations": research_map["claim_relations"],
        })
        _write_json(staging / "research_roadmap.json", _research_roadmap(context))
        _write_json(staging / "activities.json", {
            "activities": status["deterministic_activities"],
            "activity_summaries": status["activity_summaries"],
            "activity_integrity_findings": status["activity_integrity_findings"],
            "runtime_integrity_findings": status.get("runtime_integrity_findings", []),
            "calculation_attempt_integrity_findings": status.get(
                "calculation_attempt_integrity_findings", []
            ),
            "excluded_activity_refs": status["excluded_activity_refs"],
        })
        _write_json(staging / "analysis_results.json", context.get("analysis_results", {}))
        _write_json(staging / "findings.json", {"findings": research_map["findings"]})
        _write_json(staging / "gates.json", {"gates": research_map["gates"]})
        write_text_atomic(staging / "final_report.md", render_final_report(context))
        write_text_atomic(staging / "email_summary.md", render_email_summary(context))
        manifest = _package_manifest(
            staging,
            context["workspace_revision"],
            status["runtime_revision"],
        )
        _write_json(staging / "package_manifest.json", manifest)
        manifest_digest = _sha256_file(staging / "package_manifest.json")
        _assert_report_physical_path(staging, "report staging directory")
        if path_has_symlink(reports_root) or path_has_symlink(package_dir):
            raise ValueError("report package path changed to a symbolic link during build")
        os.rename(staging, package_dir)
    except Exception:
        if not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "package_dir": str(package_dir),
        "report": str(package_dir / "final_report.md"),
        "context": str(package_dir / "report_context.json"),
        "email_summary": str(package_dir / "email_summary.md"),
        "assets_dir": str(package_dir / "assets"),
        "manifest": str(package_dir / "package_manifest.json"),
        "manifest_digest": manifest_digest,
        "workspace_revision": str(context["workspace_revision"]),
        "runtime_revision": str(status["runtime_revision"]),
        "asset_artifact_ids": [record["artifact_id"] for record in asset_records],
        "asset_refs": [f"{package_dir.relative_to(root_path).as_posix()}/{record['ref']}" for record in asset_records],
    }


def _copy_report_assets(
    root: Path,
    assets_dir: Path,
    artifact_ids: Iterable[str],
) -> list[dict[str, Any]]:
    requested = list(artifact_ids)
    if len(requested) > 8 or len(set(requested)) != len(requested):
        raise ValueError("report asset_artifact_ids must contain at most 8 unique IDs")
    if not requested:
        return []
    resolved = resolve_workspace_artifact_ids(root, requested)
    records: list[dict[str, Any]] = []
    total_bytes = 0
    for index, artifact in enumerate(resolved, start=1):
        source = root.joinpath(*str(artifact["path"]).split("/"))
        suffix = source.suffix.lower()
        if suffix not in {".gif", ".png"}:
            raise ValueError(f"report asset must be a .png or .gif artifact: {artifact['artifact_id']}")
        if has_symlink_component(root, source) or source.is_symlink() or not source.is_file():
            raise ValueError(f"report asset is not a regular file: {artifact['artifact_id']}")
        source_size = _regular_file_size(source)
        if source_size < 1 or source_size > 16 * 1024 * 1024:
            raise ValueError(f"report asset size is outside the 1 byte to 16 MiB limit: {artifact['artifact_id']}")
        total_bytes += source_size
        if total_bytes > 64 * 1024 * 1024:
            raise ValueError("report assets exceed the 64 MiB package limit")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)[:120]
        if not safe_name or safe_name.startswith("."):
            safe_name = f"asset{suffix}"
        target_name = f"{index:02d}-{safe_name}"
        target = assets_dir / target_name
        _assert_report_physical_path(target, "report asset target")
        copied_size, copied_digest = _copy_regular_file(source, target)
        _assert_report_physical_path(target, "report asset target")
        if copied_digest != artifact["sha256"] or copied_size != source_size:
            raise ValueError(f"report asset changed while being copied: {artifact['artifact_id']}")
        records.append({
            "artifact_id": artifact["artifact_id"],
            "source_ref": artifact["path"],
            "ref": f"assets/{target_name}",
            "sha256": copied_digest,
            "size_bytes": copied_size,
        })
    return records



def _research_roadmap(context: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical map grouped for report navigation."""

    research_map = context["research_map"]
    nodes_by_phase: dict[str, list[dict[str, Any]]] = {}
    for node in research_map["nodes"]:
        nodes_by_phase.setdefault(str(node.get("phase_id") or "unassigned"), []).append(node)
    return {
        "schema_version": "research-roadmap/1",
        "map_id": research_map["map_id"],
        "revision": research_map["revision"],
        "phases": [
            {**phase, "nodes": nodes_by_phase.get(str(phase["id"]), [])}
            for phase in research_map["phases"]
        ],
        "unassigned_nodes": nodes_by_phase.get("unassigned", []),
    }


def render_final_report(context: dict[str, Any]) -> str:
    """Render the current ResearchMap without introducing report state."""

    research_map = context["research_map"]
    status = context["runtime_status"]
    focus_claims = set(research_map["focus_claim_ids"])
    focus_nodes = set(research_map["focus_node_ids"])
    phase_by_id = {item["id"]: item for item in research_map["phases"]}
    activity_summaries = {
        item["node_id"]: item
        for item in status.get("activity_summaries", [])
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    lines = [
        "# Research Report",
        "",
        "## Status",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Map | `{research_map['map_id']}` - {_escape(research_map['title'])} |",
        f"| Revision | `{context['workspace_revision']}` |",
        f"| Runtime revision | `{status['runtime_revision']}` |",
        f"| Focus Claims | `{', '.join(sorted(focus_claims)) or 'none'}` |",
        f"| Focus Nodes | `{', '.join(sorted(focus_nodes)) or 'none'}` |",
        f"| Phases / Claims / Nodes / Findings / Gates | {len(research_map['phases'])} / {len(research_map['claims'])} / {len(research_map['nodes'])} / {len(research_map['findings'])} / {len(research_map['gates'])} |",
        "",
        _executive_sentence(research_map["claims"], focus_claims),
        "",
        "## Research Roadmap",
    ]
    for phase in research_map["phases"]:
        phase_id = phase["id"]
        marker = " (focus)" if any(
            node.get("phase_id") == phase_id and node.get("id") in focus_nodes
            for node in research_map["nodes"]
        ) else ""
        lines.extend([
            "",
            f"### `{phase_id}` - {_escape(phase['title'])}{marker}",
            "",
            _escape(phase.get("objective", "")),
            "",
            "| ResearchNode | State | Objective | Dependencies | Outcome |",
            "| --- | --- | --- | --- | --- |",
        ])
        phase_nodes = [node for node in research_map["nodes"] if node.get("phase_id") == phase_id]
        for node in phase_nodes:
            activity = activity_summaries.get(node["id"], {})
            outcome = node.get("outcome_summary") or node.get("outcome") or "pending"
            activity_hint = (
                f"; {activity.get('activity_count', 0)} activities"
                if activity else ""
            )
            lines.append(
                f"| `{node['id']}`{' (focus)' if node['id'] in focus_nodes else ''} - {_escape(node['title'])} | "
                f"`{node['state']}`{activity_hint} | {_escape(node['objective'])} | "
                f"`{', '.join(node.get('dependency_ids', [])) or 'none'}` | {_escape(str(outcome))} |"
            )
        if not phase_nodes:
            lines.append("| _none_ |  |  |  |  |")

    unassigned = [node for node in research_map["nodes"] if node.get("phase_id") is None]
    if unassigned:
        lines.extend(["", "### Unassigned Nodes", "", "| Node | State | Objective |", "| --- | --- | --- |"])
        lines.extend(
            f"| `{node['id']}` | `{node['state']}` | {_escape(node['objective'])} |"
            for node in unassigned
        )

    lines.extend(["", "## Claims", "", "| Claim | Status | Statement | Predictions | Falsifiers |", "| --- | --- | --- | --- | --- |"])
    for claim in research_map["claims"]:
        lines.append(
            f"| `{claim['id']}`{' (focus)' if claim['id'] in focus_claims else ''} | `{claim['status']}` | "
            f"{_escape(claim['statement'])} | {_markdown_items(claim.get('predictions', []))} | "
            f"{_markdown_items(claim.get('falsifiers', []))} |"
        )
    lines.extend(["", "### Claim Relations", "", "| Source | Relation | Target |", "| --- | --- | --- |"])
    for relation in research_map["claim_relations"]:
        lines.append(
            f"| `{relation.get('source_id')}` | `{relation.get('relation')}` | `{relation.get('target_id')}` |"
        )
    if not research_map["claim_relations"]:
        lines.append("| _none_ |  |  |")

    lines.extend(["", "## ResearchNode Records", ""])
    for node in research_map["nodes"]:
        phase = phase_by_id.get(node.get("phase_id"))
        node_findings = [item for item in research_map["findings"] if item.get("node_id") == node["id"]]
        node_gates = [item for item in research_map["gates"] if item.get("target_id") == node["id"]]
        lines.extend([
            f"### `{node['id']}` - {_escape(node['title'])}",
            "",
            f"- Phase: `{phase['id']}` ({_escape(phase['title'])})." if phase else "- Phase: unassigned.",
            f"- State: `{node['state']}`; dependencies: `{', '.join(node.get('dependency_ids', [])) or 'none'}`.",
            f"- Objective: {_escape(node['objective'])}",
            f"- Claims: `{', '.join(node.get('claim_ids', [])) or 'none'}`.",
            f"- Findings: `{', '.join(item['id'] for item in node_findings) or 'none'}`.",
            f"- Gates: `{', '.join(item['id'] for item in node_gates) or 'none'}`.",
            f"- Attempts: `{', '.join(node.get('attempt_refs', [])) or 'none'}`; Artifacts: `{', '.join(node.get('artifact_refs', [])) or 'none'}`.",
            f"- Outcome: {_escape(node.get('outcome_summary') or node.get('outcome') or 'pending')}.",
            "",
        ])

    lines.extend(["## Findings", "", "| Finding | Kind | Status | Node | Claims | Statement |", "| --- | --- | --- | --- | --- | --- |"])
    for finding in research_map["findings"]:
        lines.append(
            f"| `{finding['id']}` | `{finding['kind']}` | `{finding['status']}` | `{finding['node_id']}` | "
            f"`{', '.join(finding.get('claim_ids', [])) or 'none'}` | {_escape(finding['statement'])} |"
        )
    if not research_map["findings"]:
        lines.append("| _none_ |  |  |  |  |  |")

    lines.extend(["", "## Gates", "", "| Gate | Scope | Target | Criteria | Latest verdict |", "| --- | --- | --- | --- | --- |"])
    for gate in research_map["gates"]:
        latest = gate.get("evaluations", [])[-1] if gate.get("evaluations") else None
        lines.append(
            f"| `{gate['id']}` | `{gate['scope']}` | `{gate['target_id']}` | "
            f"{len(gate.get('criteria', []))} | `{latest.get('verdict') if latest else 'not evaluated'}` |"
        )
    if not research_map["gates"]:
        lines.append("| _none_ |  |  |  |  |")

    lines.extend(["", "## Operational Follow-up", ""])
    for row in status.get("node_dispatch", []):
        lines.append(f"- Node `{row.get('node_id')}` dispatch: {'paused' if row.get('paused') else 'resumed'}.")
    for key, label in (
        ("unresolved_controls", "unresolved compute controls"),
        ("pending_review_dispositions", "pending Review responses"),
        ("activity_integrity_findings", "activity integrity errors"),
        ("runtime_integrity_findings", "operational integrity errors"),
        ("calculation_attempt_integrity_findings", "Attempt integrity errors"),
    ):
        if status.get(key):
            lines.append(f"- {len(status[key])} {label} remain.")
    for finding in research_map["findings"]:
        if finding.get("status") == "open":
            lines.append(f"- Open Finding `{finding['id']}`: {_escape(finding['statement'])}")
    if len(lines) and lines[-1] == "":
        lines.append("- No unresolved operational record or open Finding is recorded.")
    lines.extend(["", "The Root Agent chooses research strategy; the ResearchKernel owns canonical map mutation and Gate evaluation."])

    analyses = context.get("analysis_results", {})
    if analyses.get("analyses"):
        lines.extend(["", "## Scientific Analysis Artifacts", "", "| Node | Capability | Verdict | Source Artifact |", "| --- | --- | --- | --- |"])
        lines.extend(
            f"| `{row['node_id']}` | `{row['capability']}@{row['version']}` | `{row['verdict']}` | `{row['artifact_id']}` |"
            for row in analyses["analyses"]
        )
    return "\n".join(lines) + "\n"


def render_email_summary(context: dict[str, Any]) -> str:
    research_map = context["research_map"]
    focus = set(research_map["focus_claim_ids"])
    focus_rows = [item for item in research_map["claims"] if item["id"] in focus]
    states = ", ".join(f"{item['id']}={item['status']}" for item in focus_rows) or "no focus Claim"
    return "\n".join([
        "Subject: TS research workspace update",
        "",
        f"ResearchMap status: {states}.",
        "",
        f"Map: {research_map['map_id']}",
        f"Revision: {context['workspace_revision']}",
        "Focus Claims:",
        *(f"- {item['id']}: {item['status']} - {item['statement']}" for item in focus_rows),
        "",
        f"Open Findings: {sum(item.get('status') == 'open' for item in research_map['findings'])}",
        "Main report: final_report.md",
        "",
    ])


def _executive_sentence(claims: list[dict[str, Any]], focus: set[str]) -> str:
    rows = [item for item in claims if item.get("id") in focus]
    if rows:
        return "Focus Claim status: " + ", ".join(f"{item['id']}={item['status']}" for item in rows) + "."
    return "No focus Claim is selected; this report records the current ResearchMap."


def _package_manifest(package_dir: Path, revision: str, runtime_revision: str) -> dict[str, Any]:
    files = []
    for path in sorted(package_dir.rglob("*")):
        if has_symlink_component(package_dir, path) or path.is_symlink():
            raise ValueError(f"report package contains a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"report package contains a non-file entry: {path}")
        if path.name == "package_manifest.json":
            continue
        files.append({
            "ref": path.relative_to(package_dir).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    return {
        "schema_version": "ts-report-package/5",
        "workspace_revision": revision,
        "runtime_revision": runtime_revision,
        "files": files,
    }


def _write_json(path: Path, value: Any) -> None:
    _assert_report_physical_path(path, "report package file")
    write_json_atomic(path, value)


def _assert_report_physical_path(path: Path, label: str) -> None:
    """Reject symlinked staging paths before report writes or reads."""

    if path_has_symlink(path) or path.is_symlink():
        raise ValueError(f"{label} contains a symbolic link: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EISDIR, "path must be a regular file", os.fspath(path))
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _regular_file_size(path: Path) -> int:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(errno.EISDIR, "path must be a regular file", os.fspath(path))
        return metadata.st_size
    finally:
        os.close(descriptor)


def _copy_regular_file(source: Path, target: Path) -> tuple[int, str]:
    """Copy one report asset through no-follow descriptors."""

    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    target_fd = -1
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise OSError(errno.EISDIR, "report asset source must be a regular file", os.fspath(source))
        target_fd = os.open(
            target,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                view = view[written:]
        os.fsync(target_fd)
        return size, "sha256:" + digest.hexdigest()
    finally:
        os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_items(values: list[Any]) -> str:
    return "; ".join(_escape(str(value)) for value in values) or "_none_"
