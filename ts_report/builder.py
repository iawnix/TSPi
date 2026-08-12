"""Build Markdown reports from validated workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .context import (
    collect_report_context,
    node_audit_status,
    node_hypothesis_status,
    node_label,
    node_program_outcome,
    node_scientific_status,
    pathway_audit_outcome_for_node,
)
from .figures import write_report_assets


def build_final_report(root: str | Path) -> str:
    context = collect_report_context(root)
    return render_final_report(context)


def build_report_package(root: str | Path, output_dir: str | Path | None = None) -> dict[str, str]:
    root_path = Path(root)
    package_dir = Path(output_dir) if output_dir is not None else root_path / "reports" / "final_report_package"
    context = collect_report_context(root_path)
    if package_dir.exists():
        raise ValueError(f"report package already exists: {package_dir}")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.tmp-", dir=package_dir.parent))
    try:
        context["assets"] = write_report_assets(root_path, context, staging_dir / "assets")
        context["assets"] = _rebase_paths(context["assets"], staging_dir, package_dir)

        context_path = staging_dir / "report_context.json"
        report_path = staging_dir / "final_report.md"
        email_path = staging_dir / "email_summary.md"
        context_path.write_text(json.dumps(_json_safe(context), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report_path.write_text(render_final_report(context), encoding="utf-8")
        email_path.write_text(render_email_summary(context), encoding="utf-8")
        manifest_path = staging_dir / "package_manifest.json"
        manifest = _package_manifest(staging_dir, context["workspace_revision"])
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_digest = _sha256_file(manifest_path)
        if package_dir.exists():
            raise ValueError(f"report package already exists: {package_dir}")
        os.rename(staging_dir, package_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    context_path = package_dir / "report_context.json"
    report_path = package_dir / "final_report.md"
    email_path = package_dir / "email_summary.md"
    manifest_path = package_dir / "package_manifest.json"
    return {
        "package_dir": str(package_dir),
        "report": str(report_path),
        "context": str(context_path),
        "email_summary": str(email_path),
        "assets_dir": str(package_dir / "assets"),
        "manifest": str(manifest_path),
        "manifest_digest": manifest_digest,
        "workspace_revision": str(context["workspace_revision"]),
    }


def _package_manifest(package_dir: Path, workspace_revision: str) -> dict[str, Any]:
    files = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == "package_manifest.json":
            continue
        files.append(
            {
                "ref": path.relative_to(package_dir).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": "ts-report-package/1",
        "workspace_revision": workspace_revision,
        "files": files,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _rebase_paths(value: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _rebase_paths(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase_paths(item, old_root, new_root) for item in value]
    if isinstance(value, str):
        old = str(old_root)
        if value == old or value.startswith(f"{old}{os.sep}"):
            return str(new_root) + value[len(old) :]
    return value


def render_final_report(context: dict[str, Any]) -> str:
    lines = [
        "# Transition-State Search Report",
        "",
        "## 1. Executive Verdict",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Workspace | `{context['workspace_root']}` |",
        f"| Highest validated layer | `{context['highest_validated_layer']}` |",
        f"| Validation scopes reached | `{', '.join(context.get('validation_scopes_reached', [])) or 'none'}` |",
        f"| Final claim | `{context['final_claim']}` |",
        f"| Accepted TS refs | `{', '.join(context.get('accepted_ts_refs', [])) or 'none'}` |",
        f"| Nodes | {len(context.get('nodes', []))} |",
        f"| Evidence entries | {len(context.get('evidence_records', []))} |",
        "",
        _conclusion_sentence(context),
        "",
        "## 2. Reaction Overview",
        "",
        *_reaction_overview_lines(context),
        "",
        "## 3. R-TS-P Structural Panel",
        "",
        *_structure_panel_lines(context),
        "",
        "## 4. Imaginary Mode / Vibration Analysis",
        "",
        *_mode_lines(context),
        "",
        "## 5. IRC / Connectivity Evidence",
        "",
        *_connectivity_lines(context),
        "",
        "## 6. Energy Profile",
        "",
        *_energy_lines(context),
        "",
        "## 7. Mechanistic Interpretation",
        "",
        *_mechanism_lines(context),
        "",
        "## 8. Evidence Audit",
        "",
        *_evidence_layer_lines(context.get("evidence_records", []), context.get("accepted_ts_refs", [])),
        "",
        "## 9. Search Tree Summary",
        "",
        "| Node | Type / scope | Lifecycle | Program outcome | Hypothesis status | Audit status / outcome |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    records = context.get("evidence_records", [])
    for node in context.get("nodes", []):
        audit_note = _pathway_audit_note(node, records)
        audit_outcome = audit_note.removeprefix(" (audit_outcome=").removesuffix(")") if audit_note else ""
        lines.append(
            f"| `{node['node_id']}` | {node_label(node)} | {node['lifecycle']} | "
            f"{node_program_outcome(node)} | {node_hypothesis_status(node)} | "
            f"{node_audit_status(node) or audit_outcome} |"
        )

    lines.extend(["", "Node index:", ""])
    for node in context.get("nodes", []):
        audit_note = _pathway_audit_note(node, records)
        lines.append(
            f"- {node['node_id']}: {node_label(node)} / {node['lifecycle']} / "
            f"{node_scientific_status(node)}{audit_note}"
        )

    lines.extend(
        [
            "",
            "## 10. Limitations And Follow-up",
            "",
            *_limitation_lines(context),
            "",
            "## 11. Artifact And Evidence Appendix",
            "",
            "| Evidence ID | Role | Kind | Node | Path | Summary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for record in context.get("evidence_records", []):
        lines.append(
            f"| `{record.get('evidence_id', '')}` | {record.get('role', '')} | {record.get('kind', '')} | "
            f"`{record.get('node_id', '')}` | `{record.get('path', '')}` | {_escape_table(str(record.get('summary', '')))} |"
        )
    return "\n".join(lines) + "\n"


def render_email_summary(context: dict[str, Any]) -> str:
    active = context.get("active_hypothesis", {}) if isinstance(context.get("active_hypothesis"), dict) else {}
    lines = [
        f"Subject: TS report - {context.get('final_claim')} at {context.get('highest_validated_layer')} layer",
        "",
        _conclusion_sentence(context).replace("**Conclusion.** ", ""),
        "",
        f"Workspace: {context.get('workspace_root')}",
        f"Hypothesis: {active.get('hypothesis_id', '')} {active.get('summary', '')}",
        f"Accepted TS refs: {', '.join(context.get('accepted_ts_refs', [])) or 'none'}",
        "",
        "Main report: final_report.md",
    ]
    return "\n".join(lines) + "\n"


def _conclusion_sentence(context: dict[str, Any]) -> str:
    highest = context.get("highest_validated_layer")
    final_claim = context.get("final_claim")
    accepted_refs = context.get("accepted_ts_refs", [])
    if highest == "pathway" and final_claim in {"accepted", "pathway_accepted"}:
        return (
            "**Conclusion.** The workspace evidence supports the audited pathway. "
            f"Accepted TS artifacts: `{', '.join(accepted_refs)}`."
        )
    if highest == "pathway" and final_claim == "not_accepted":
        return "**Conclusion.** The pathway audit supports a negative conclusion; the audited pathway is not accepted."
    if highest == "accepted_ts":
        return (
            "**Conclusion.** The transition state is accepted by TS/Freq and connectivity gates, "
            "but no accepted pathway audit is present."
        )
    return f"**Conclusion.** Highest evidence layer reached is `{highest}`; no higher scientific conclusion is accepted."


def _reaction_overview_lines(context: dict[str, Any]) -> list[str]:
    active = context.get("active_hypothesis", {}) if isinstance(context.get("active_hypothesis"), dict) else {}
    derived = active.get("derived_from") if isinstance(active.get("derived_from"), dict) else {}
    claim = active.get("structured_claim") if isinstance(active.get("structured_claim"), dict) else {}
    electronic = claim.get("electronic_model") if isinstance(claim.get("electronic_model"), dict) else {}
    center = context.get("reaction_center", {}) if isinstance(context.get("reaction_center"), dict) else {}
    forming = ", ".join(item.get("label", str(item.get("atoms", ""))) for item in center.get("forming_bonds", []))
    breaking = ", ".join(item.get("label", str(item.get("atoms", ""))) for item in center.get("breaking_bonds", []))
    transferred = ", ".join(str(item.get("label") or item.get("atom")) for item in center.get("transferred_atoms", []))
    return [
        "| Item | Value |",
        "| --- | --- |",
        f"| Hypothesis | `{active.get('hypothesis_id', '')}` |",
        f"| Summary | {_escape_table(str(active.get('summary', '')))} |",
        f"| Reactant | `{derived.get('reactant_ref') or derived.get('reactants', '')}` |",
        f"| Product | `{derived.get('product_ref') or derived.get('product', '')}` |",
        f"| Charge / multiplicity | `{derived.get('charge', electronic.get('charge', ''))} / {derived.get('multiplicity', electronic.get('multiplicity', ''))}` |",
        f"| Forming bonds | {forming or 'not declared'} |",
        f"| Breaking bonds | {breaking or 'not declared'} |",
        f"| Transferred atoms | {transferred or 'not declared'} |",
    ]


def _structure_panel_lines(context: dict[str, Any]) -> list[str]:
    assets = context.get("assets", {}) if isinstance(context.get("assets"), dict) else {}
    structures = context.get("structures", {}) if isinstance(context.get("structures"), dict) else {}
    lines = []
    if assets.get("structure_render", {}).get("ok"):
        lines.append(f"![R-TS-P render]({assets['structure_render']['output_path']})")
        lines.append("")
    elif assets.get("structure_panel_svg"):
        lines.append(f"![R-TS-P structure panel]({assets['structure_panel_svg']['path']})")
        lines.append("")
    lines.extend(["| Role | Structure | Exists |", "| --- | --- | --- |"])
    for key in ["reactant", "ts", "product", "mode_minus", "mode_plus", "irc_forward", "irc_reverse"]:
        item = structures.get(key, {})
        if not item:
            continue
        lines.append(f"| {key} | `{item.get('path', '')}` | {item.get('exists', False)} |")
    profile = context.get("distance_profile", {}) if isinstance(context.get("distance_profile"), dict) else {}
    keys = [str(key) for key in profile.get("keys", [])[:6]]
    rows = [row for row in profile.get("rows", []) if isinstance(row, dict)]
    if keys and rows:
        lines.extend(["", "Key reaction-center distances:", "", _distance_table(keys, rows)])
    return lines or ["- No R/TS/P structure references were available in the report context."]


def _mode_lines(context: dict[str, Any]) -> list[str]:
    tsfreq = context.get("tsfreq", {}) if isinstance(context.get("tsfreq"), dict) else {}
    mode = tsfreq.get("mode_assignment") if isinstance(tsfreq.get("mode_assignment"), dict) else {}
    selected = tsfreq.get("selected_record") if isinstance(tsfreq.get("selected_record"), dict) else {}
    assets = context.get("assets", {}) if isinstance(context.get("assets"), dict) else {}
    lines = []
    if assets.get("distance_profile_svg"):
        lines.append(f"![Mode and IRC key distances]({assets['distance_profile_svg']['path']})")
        lines.append("")
    lines.extend(
        [
            "| Field | Value |",
            "| --- | --- |",
            f"| TS/Freq evidence | `{selected.get('evidence_id', '')}` |",
            f"| Imaginary frequency | `{mode.get('imaginary_frequency_cm-1', _key_facts(selected).get('imaginary_frequencies_cm-1', ''))}` |",
            f"| Mode verdict | {_escape_table(str(mode.get('mode_verdict', mode.get('verdict_against_prediction', ''))))} |",
            f"| Product-like displacement | {_escape_table(str(mode.get('product_like_displacement', '')))} |",
            f"| Reactant-like displacement | {_escape_table(str(mode.get('reactant_like_displacement', '')))} |",
        ]
    )
    return lines


def _connectivity_lines(context: dict[str, Any]) -> list[str]:
    conn = context.get("connectivity", {}) if isinstance(context.get("connectivity"), dict) else {}
    verdict = conn.get("verdict") if isinstance(conn.get("verdict"), dict) else {}
    directions = conn.get("directions") if isinstance(conn.get("directions"), dict) else {}
    lines = [
        "| Field | Value |",
        "| --- | --- |",
        f"| Connectivity verdict | {_escape_table(str(verdict.get('verdict', verdict.get('r_to_p_connected_via_ts', verdict.get('verdict_against_prediction', '')))))} |",
        f"| Forward assignment | `{verdict.get('forward_assignment', '')}` |",
        f"| Reverse assignment | `{verdict.get('reverse_assignment', '')}` |",
        f"| Strict IRC without program failure | `{verdict.get('strict_irc_complete_without_program_failure', verdict.get('strict_irc_complete', ''))}` |",
        f"| Stationary endpoint IRC complete | `{verdict.get('stationary_endpoint_irc_complete', '')}` |",
    ]
    if directions:
        lines.extend(["", "| Direction | Assignment | Termination | Final geometry |", "| --- | --- | --- | --- |"])
        for name, direction in directions.items():
            if not isinstance(direction, dict):
                continue
            lines.append(
                f"| {name} | {direction.get('assignment', '')} | {direction.get('termination', '')} | "
                f"`{direction.get('final_geometry', '')}` |"
            )
    if verdict.get("caveat"):
        lines.extend(["", f"Connectivity caveat: {_escape_table(str(verdict['caveat']))}"])
    return lines


def _energy_lines(context: dict[str, Any]) -> list[str]:
    profile = context.get("energy_profile", {}) if isinstance(context.get("energy_profile"), dict) else {}
    assets = context.get("assets", {}) if isinstance(context.get("assets"), dict) else {}
    lines = []
    if assets.get("energy_profile_svg"):
        lines.append(f"![Energy profile]({assets['energy_profile_svg']['path']})")
        lines.append("")
    lines.extend(
        [
            "| Species | Role | E_elec / hartree | E+ZPE / hartree | G / hartree | Rel E_elec / kcal mol-1 | Rel E+ZPE / kcal mol-1 | Rel G / kcal mol-1 | Source |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in profile.get("rows", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('species', '')} | {row.get('role', '')} | {_fmt(row.get('electronic_energy_hartree'))} | "
            f"{_fmt(row.get('electronic_plus_zpe_hartree'))} | "
            f"{_fmt(row.get('electronic_plus_thermal_free_energy_hartree'))} | "
            f"{_fmt(row.get('relative_electronic_energy_kcal_mol'))} | "
            f"{_fmt(row.get('relative_zpe_corrected_energy_kcal_mol'))} | "
            f"{_fmt(row.get('relative_free_energy_kcal_mol'))} | "
            f"`{row.get('source', '')}` |"
        )
    for note in profile.get("notes", []):
        lines.append(f"- {note}")
    return lines


def _mechanism_lines(context: dict[str, Any]) -> list[str]:
    interp = context.get("mechanism_interpretation", {}) if isinstance(context.get("mechanism_interpretation"), dict) else {}
    lines = [str(interp.get("summary", "No mechanism interpretation was generated."))]
    progress = interp.get("reaction_progress", []) if isinstance(interp.get("reaction_progress"), list) else []
    if progress:
        lines.extend(["", "| Coordinate | Type | R | TS | P | Progress |", "| --- | --- | --- | --- | --- | --- |"])
        for item in progress:
            if not isinstance(item, dict):
                continue
            progress_value = item.get("progress")
            lines.append(
                f"| {item.get('label', '')} | {item.get('type', '')} | {_fmt(item.get('reactant'))} | "
                f"{_fmt(item.get('ts'))} | {_fmt(item.get('product'))} | {_fmt(progress_value)} |"
            )
    for title, key in [
        ("Supporting observations", "supporting_observations"),
        ("Interpretation boundaries", "boundaries"),
    ]:
        values = interp.get(key, []) if isinstance(interp.get(key), list) else []
        if values:
            lines.extend(["", f"{title}:"])
            lines.extend(f"- {value}" for value in values)
    alternatives = interp.get("alternative_hypotheses", []) if isinstance(interp.get("alternative_hypotheses"), list) else []
    if alternatives:
        lines.extend(["", "Alternative hypotheses retained for audit:"])
        for item in alternatives:
            if isinstance(item, dict):
                lines.append(f"- {item.get('summary', '')} ({item.get('changed_variable', 'changed variable not specified')})")
    return lines


def _evidence_layer_lines(records: list[dict[str, Any]], accepted_refs: list[str]) -> list[str]:
    return [
        "### TS/Freq",
        "",
        *_role_table(records, {"tsfreq_gate", "mode_assignment", "electronic_structure_gate"}),
        "",
        "### Connectivity / IRC",
        "",
        *_role_table(records, {"connectivity_gate", "irc_endpoint_assignment", "stereochemical_connectivity_gate"}),
        "",
        "### Accepted TS",
        "",
        f"- Accepted artifacts: `{', '.join(accepted_refs) or 'none'}`",
        "",
        "### Pathway Audit",
        "",
        *_role_table(records, {"pathway_audit", "pathway_audit_summary"}),
    ]


def _role_table(records: list[dict[str, Any]], roles: set[str]) -> list[str]:
    rows = [record for record in records if record.get("role") in roles]
    if not rows:
        return ["- none"]
    lines = ["| Evidence | Role | Key facts | Path |", "| --- | --- | --- | --- |"]
    for record in rows:
        lines.append(
            f"| `{record.get('evidence_id', '')}` | {record.get('role', '')} | "
            f"{_escape_table('; '.join(f'{key}={value}' for key, value in _key_facts(record).items()))} | `{record.get('path', '')}` |"
        )
    return lines


def _key_facts(record: dict[str, Any]) -> dict[str, Any]:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
    merged = {**quality, **facts}
    preferred = [
        "method",
        "basis",
        "electronic_energy_hartree",
        "imaginary_frequency_count",
        "imaginary_frequencies_cm-1",
        "verdict_against_prediction",
        "reverse_assignment",
        "forward_assignment",
        "stereochemical_verdict",
        "stereochemistry_matched",
        "strict_pathway_decision",
        "strict_pathway_supported",
        "whole_R_to_P_pathway_accepted",
    ]
    return {key: merged[key] for key in preferred if key in merged}


def _pathway_audit_note(node: dict[str, Any], records: list[Any]) -> str:
    if node.get("node_type") != "audit" or node.get("audit_scope") != "pathway":
        return ""
    outcome = pathway_audit_outcome_for_node(node.get("node_id"), records)
    if outcome:
        return f" (audit_outcome={outcome})"
    reason = str(node.get("reason_code") or "").lower()
    if "not_accepted" in reason or "missing" in reason:
        return " (audit_outcome=pathway_not_accepted)"
    return ""


def _limitation_lines(context: dict[str, Any]) -> list[str]:
    limitations = context.get("limitations", []) if isinstance(context.get("limitations"), list) else []
    if limitations:
        return [f"- {item}" for item in limitations]
    return ["- No additional limitations were extracted beyond the evidence-layer boundaries above."]


def _distance_table(keys: list[str], rows: list[dict[str, Any]]) -> str:
    lines = ["| Structure | " + " | ".join(keys) + " |", "| --- | " + " | ".join("---" for _ in keys) + " |"]
    for row in rows:
        distances = row.get("distances") if isinstance(row.get("distances"), dict) else {}
        values = [_fmt(distances.get(key)) for key in keys]
        lines.append(f"| {row.get('label', '')} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return ""
    return str(value)


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
