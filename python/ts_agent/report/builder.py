"""Build immutable Markdown packages from the report projection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ts_agent.workspace.associations import derive_claim_node_links
from ts_agent.workspace.refs import node_sort_key, claim_sort_key
from ts_agent.workspace.artifacts import resolve_workspace_artifact_ids

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
    root_path = Path(root).expanduser().resolve()
    package_dir = Path(output_dir).expanduser().resolve() if output_dir is not None else root_path / "reports" / "final-report"
    if package_dir.parent != (root_path / "reports").resolve():
        raise ValueError("report package must be a direct child of workspace reports/")
    context = collect_report_context(root_path, exclude_activity_refs=exclude_activity_refs)
    if package_dir.exists():
        raise ValueError(f"report package already exists: {package_dir}")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.tmp-", dir=package_dir.parent))
    try:
        (staging / "assets").mkdir()
        asset_records = _copy_report_assets(root_path, staging / "assets", asset_artifact_ids)
        _write_json(staging / "asset_index.json", {
            "schema_version": "ts-report-asset-index/1",
            "assets": asset_records,
        })
        _write_json(staging / "report_context.json", context)
        _write_json(staging / "claim_graph.json", {
            "claims": context["claims"],
            "relations": context["claim_relations"],
        })
        _write_json(staging / "research_roadmap.json", context["research_trajectory"])
        _write_json(staging / "activities.json", {
            "activities": context["deterministic_activities"],
            "activity_summaries": context["activity_summaries"],
            "activity_integrity_findings": context["activity_integrity_findings"],
            "excluded_activity_refs": context["excluded_activity_refs"],
        })
        _write_json(staging / "observation_index.json", {"observations": context["observations"]})
        _write_json(staging / "validation.json", {
            "specs": context["proof_specs"],
            "results": context["validation_results"],
        })
        _write_json(staging / "findings.json", {"findings": context["findings"]})
        _write_json(staging / "acceptances.json", {
            "acceptances": context["acceptances"],
            "current_acceptance_refs": context["acceptance_summary"]["current_refs"],
        })
        (staging / "final_report.md").write_text(render_final_report(context), encoding="utf-8")
        (staging / "email_summary.md").write_text(render_email_summary(context), encoding="utf-8")
        manifest = _package_manifest(
            staging,
            context["workspace_revision"],
            context["operational_revision"],
        )
        _write_json(staging / "package_manifest.json", manifest)
        manifest_digest = _sha256_file(staging / "package_manifest.json")
        os.rename(staging, package_dir)
    except Exception:
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
        "operational_revision": str(context["operational_revision"]),
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
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"report asset is not a regular file: {artifact['artifact_id']}")
        size = source.stat().st_size
        if size < 1 or size > 16 * 1024 * 1024:
            raise ValueError(f"report asset size is outside the 1 byte to 16 MiB limit: {artifact['artifact_id']}")
        total_bytes += size
        if total_bytes > 64 * 1024 * 1024:
            raise ValueError("report assets exceed the 64 MiB package limit")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)[:120]
        if not safe_name or safe_name.startswith("."):
            safe_name = f"asset{suffix}"
        target_name = f"{index:02d}-{safe_name}"
        target = assets_dir / target_name
        shutil.copyfile(source, target)
        copied_digest = _sha256_file(target)
        if copied_digest != artifact["sha256"] or target.stat().st_size != size:
            raise ValueError(f"report asset changed while being copied: {artifact['artifact_id']}")
        records.append({
            "artifact_id": artifact["artifact_id"],
            "source_ref": artifact["path"],
            "ref": f"assets/{target_name}",
            "sha256": copied_digest,
            "size_bytes": size,
        })
    return records


def render_final_report(context: dict[str, Any]) -> str:
    focus_claims = set(context["focus"]["claim_refs"])
    focus_nodes = set(context["focus"]["node_refs"])
    accepted_claims = {item["claim_ref"] for item in context["current_acceptances"]}
    phase_by_id = {item["phase_id"]: item for item in context["research_phases"]}
    focus_phase_refs = {
        node["phase_ref"]
        for node in context["research_nodes"]
        if node["node_id"] in focus_nodes
    }
    activity_summaries = {
        item["node_id"]: item
        for item in context["activity_summaries"]
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    claim_node_links = derive_claim_node_links(context["claims"], context["research_nodes"])
    trajectory_nodes = {
        item["node_id"]: item
        for item in context["research_trajectory"]["nodes"]
    }
    related_claim_refs = {
        node["node_id"]: [
            claim_id
            for claim_id, node_id in claim_node_links
            if node_id == node["node_id"]
        ]
        for node in context["research_nodes"]
    }
    lines = [
        "# Transition-State Research Report",
        "",
        "## Executive Status",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Workspace | `{context['workspace_id']}` |",
        f"| Revision | `{context['workspace_revision']}` |",
        f"| Operational revision | `{context['operational_revision']}` |",
        f"| Report | `{context['report_id']}` |",
        f"| Focus Claims | `{', '.join(sorted(focus_claims, key=claim_sort_key)) or 'none'}` |",
        f"| Focus Phases | `{', '.join(sorted(focus_phase_refs)) or 'none'}` |",
        f"| Focus ResearchNodes | `{', '.join(sorted(focus_nodes, key=node_sort_key)) or 'none'}` |",
        f"| Phases / Nodes / Claims / Observations / Findings | {len(context['research_phases'])} / {len(context['research_nodes'])} / {len(context['claims'])} / {len(context['observations'])} / {len(context['findings'])} |",
        "",
        _executive_sentence(context["claims"], focus_claims, accepted_claims),
        "",
        "## Research Roadmap",
    ]
    for phase in context["research_phases"]:
        marker = " (focus)" if phase["phase_id"] in focus_phase_refs else ""
        lines.extend([
            "",
            f"### `{phase['phase_id']}` - {_escape(phase['title'])}{marker}",
            "",
            _escape(phase["objective"]),
            "",
            "| ResearchNode | Research decision | Status / outcome | Dependencies |",
            "| --- | --- | --- | --- |",
        ])
        phase_nodes = [node for node in context["research_nodes"] if node["phase_ref"] == phase["phase_id"]]
        for node in phase_nodes:
            node_marker = " (focus)" if node["node_id"] in focus_nodes else ""
            trajectory_node = trajectory_nodes[node["node_id"]]
            opening = trajectory_node.get("opening_decision") or {}
            result = node.get("result") or {}
            lines.append(
                f"| `{node['node_id']}`{node_marker} - {_escape(node['title'])} | "
                f"{_escape(opening.get('rationale') or node['objective'])} | "
                f"`{node['status']}`{': ' + _escape(result['summary']) if result.get('summary') else ''} | "
                f"`{', '.join(node['dependency_refs']) or 'none'}` |"
            )
        if not phase_nodes:
            lines.append("| _none_ |  |  |  |")

    lines.extend([
        "",
        "## Scientific Conclusions",
        "",
        "| Claim | Type | Status | Statement | Assumptions | Falsifiers |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for claim in context["claims"]:
        marker = " (focus)" if claim["claim_id"] in focus_claims else ""
        lines.append(
            f"| `{claim['claim_id']}`{marker} | `{claim['claim_type']}` | `{claim['status']}` | {_escape(claim['statement'])} | "
            f"{_markdown_items(claim['assumptions'])} | {_markdown_items(claim['falsifiers'])} |"
        )
    lines.extend(["", "### Claim Relations", "", "| Relation | Source | Type | Target | Rationale |", "| --- | --- | --- | --- | --- |"])
    for relation in context["claim_relations"]:
        lines.append(
            f"| `{relation['relation_id']}` | `{relation['source_claim_ref']}` | `{relation['relation_type']}` | "
            f"`{relation['target_claim_ref']}` | {_escape(relation['rationale'])} |"
        )
    if not context["claim_relations"]:
        lines.append("| _none_ |  |  |  |  |")

    lines.extend(["", "## ResearchNode Records", ""])
    for node in context["research_nodes"]:
        result = node.get("result") if isinstance(node.get("result"), dict) else None
        activity = activity_summaries.get(node["node_id"], {})
        claim_refs = related_claim_refs[node["node_id"]]
        phase = phase_by_id[node["phase_ref"]]
        opening = trajectory_nodes[node["node_id"]].get("opening_decision") or {}
        lines.extend([
            f"### `{node['node_id']}` - {_escape(node['title'])}",
            "",
            f"- Phase: `{phase['phase_id']}` ({_escape(phase['title'])}).",
            f"- Status: `{node['status']}`; dependencies: `{', '.join(node['dependency_refs']) or 'none'}`.",
            f"- Research decision: {_escape(opening.get('rationale') or node['title'])}",
            f"- Objective: {_escape(node['objective'])}",
            f"- Deliverable: {_escape(node['deliverable'])}",
            f"- Primary Claim: `{node.get('primary_claim_ref') or 'none'}`; Claim scope: `{', '.join(claim_refs) or 'none'}`.",
            f"- Outcome: {_escape(result['summary']) if result else '_pending_'}",
            f"- Open questions: {_markdown_items(result.get('open_questions', [])) if result else '_not yet recorded_'}",
            f"- Deterministic activities: {activity.get('activity_count', 0)} total, "
            f"{activity.get('completed_count', 0)} completed, {activity.get('failed_count', 0)} failed, "
            f"{activity.get('running_count', 0)} running, {activity.get('pending_count', 0)} pending.",
            f"- Scientific records: {len(node['observation_refs'])} Observations, "
            f"{len(node['finding_refs'])} Findings, {len(node['proof_spec_refs'])} ProofSpecs, "
            f"{len(node['validation_result_refs'])} ValidationResults.",
            "",
        ])

    lines.extend(["", "## Semantic Observations", "", "| Observation | Concept | Subject | Value | Unit | ResearchNode | Artifacts |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for observation in context["observations"]:
        value = json.dumps(observation["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(
            f"| `{observation['observation_id']}` | `{observation['concept_id']}` | `{observation['subject_ref']}` | "
            f"`{_escape(value)}` | `{observation['unit'] or ''}` | `{observation['created_by_node']}` | "
            f"`{', '.join(observation['artifact_refs']) or 'none'}` |"
        )

    lines.extend(["", "## Frozen Validation", "", "| ProofSpec | Dimension | Target Claim | Checks | Latest Verdict |", "| --- | --- | --- | --- | --- |"])
    results_by_spec: dict[str, list[dict[str, Any]]] = {}
    for result in context["validation_results"]:
        results_by_spec.setdefault(result["proof_ref"], []).append(result)
    for spec in context["proof_specs"]:
        rows = results_by_spec.get(spec["proof_id"], [])
        latest = rows[-1]["verdict"] if rows else "not evaluated"
        lines.append(
            f"| `{spec['proof_id']}` | `{spec['dimension']}` | `{spec['target_claim_ref']}` | "
            f"{len(spec['checks'])} | `{latest}` |"
        )

    lines.extend(["", "## Findings", "", "| Finding | Severity | Status | Claims | Statement |", "| --- | --- | --- | --- | --- |"])
    for finding in context["findings"]:
        lines.append(
            f"| `{finding['finding_id']}` | `{finding['severity']}` | `{finding['status']}` | "
            f"`{', '.join(finding['claim_refs']) or 'none'}` | {_escape(finding['statement'])} |"
        )
    if not context["findings"]:
        lines.append("| _none_ |  |  |  |  |")

    lines.extend(["", "## Claim Acceptance", ""])
    if context["acceptances"]:
        for acceptance in context["acceptances"]:
            profile = acceptance["profile_ref"]
            state = "current" if acceptance["current"] else "historical"
            stale = "" if acceptance["current"] else f"; stale because `{', '.join(acceptance['stale_reasons'])}`"
            lines.append(
                f"- `{acceptance['acceptance_id']}` is `{state}` for `{acceptance['claim_ref']}` under "
                f"`{profile['profile_id']}@{profile['version']}` with ValidationResults "
                f"`{', '.join(acceptance['validation_result_refs'])}`{stale}."
            )
    else:
        lines.append("- No acceptance assessment has been recorded.")
    if context["acceptances"] and not context["current_acceptances"]:
        lines.append("- No historical acceptance remains current at this workspace revision.")

    lines.extend(["", "## Operational Follow-up", ""])
    if context["unresolved_controls"]:
        lines.append(f"- {len(context['unresolved_controls'])} unresolved compute control record(s) remain.")
    if context["pending_review_dispositions"]:
        lines.append(f"- {len(context['pending_review_dispositions'])} advisory Review response(s) remain pending.")
    if context["activity_integrity_findings"]:
        lines.append(f"- {len(context['activity_integrity_findings'])} deterministic activity integrity error(s) remain.")
    open_findings = [item for item in context["findings"] if item["status"] == "open"]
    lines.extend(f"- Open Finding `{item['finding_id']}`: {_escape(item['statement'])}" for item in open_findings)
    if not context["unresolved_controls"] and not context["pending_review_dispositions"] and not context["activity_integrity_findings"] and not open_findings:
        lines.append("- No unresolved operational control, Review response, or open Finding is recorded.")
    lines.extend([
        "",
        "The Root Agent owns research strategy. The Research Kernel owns canonical mutation, provenance, frozen validation, and acceptance.",
    ])
    return "\n".join(lines) + "\n"


def render_email_summary(context: dict[str, Any]) -> str:
    focus = set(context["focus"]["claim_refs"])
    focus_rows = [item for item in context["claims"] if item["claim_id"] in focus]
    accepted = {item["claim_ref"] for item in context["current_acceptances"]}
    return "\n".join([
        "Subject: TS research workspace update",
        "",
        _executive_sentence(context["claims"], focus, accepted),
        "",
        f"Workspace: {context['workspace_id']}",
        f"Revision: {context['workspace_revision']}",
        "Focus Claims:",
        *(f"- {item['claim_id']}: {item['status']} - {item['statement']}" for item in focus_rows),
        "",
        f"Open Findings: {sum(item['status'] == 'open' for item in context['findings'])}",
        "Main report: final_report.md",
        "",
    ])


def _executive_sentence(claims: list[dict[str, Any]], focus: set[str], accepted: set[str]) -> str:
    rows = [item for item in claims if item["claim_id"] in focus]
    if rows and all(item["claim_id"] in accepted for item in rows):
        return "All focus Claims have current, immutable acceptance snapshots under versioned profiles."
    if rows:
        states = ", ".join(f"{item['claim_id']}={item['status']}" for item in rows)
        return f"Focus Claim status: {states}. No current acceptance covers every focus Claim."
    return "No focus Claim is selected; this report records the current graph without selecting a path."


def _package_manifest(package_dir: Path, revision: str, operational_revision: str) -> dict[str, Any]:
    files = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == "package_manifest.json":
            continue
        files.append({
            "ref": path.relative_to(package_dir).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    return {
        "schema_version": "ts-report-package/4",
        "workspace_revision": revision,
        "operational_revision": operational_revision,
        "files": files,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_items(values: list[Any]) -> str:
    return "; ".join(_escape(str(value)) for value in values) or "_none_"
