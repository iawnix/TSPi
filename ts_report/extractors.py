"""Evidence extractors for final reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.io import read_json

HARTREE_TO_KCAL_MOL = 627.509474
ENERGY_FIELDS = (
    "electronic_energy_hartree",
    "zero_point_correction_hartree",
    "thermal_gibbs_correction_hartree",
    "electronic_plus_zpe_hartree",
    "electronic_plus_thermal_free_energy_hartree",
)


def active_hypothesis(mechanism: dict[str, Any]) -> dict[str, Any]:
    focus_id = mechanism.get("focus_hypothesis_id")
    hypotheses = [item for item in mechanism.get("hypotheses", []) if isinstance(item, dict)]
    return next((item for item in hypotheses if item.get("hypothesis_id") == focus_id), hypotheses[-1] if hypotheses else {})


def evidence_artifacts(root: Path, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for record in records:
        path = _record_path(root, record)
        if path is None or path.suffix.lower() != ".json" or not path.exists():
            continue
        try:
            artifacts[str(record.get("evidence_id", ""))] = read_json(path)
        except Exception:  # noqa: BLE001
            continue
    return artifacts


def reaction_center(active: dict[str, Any]) -> dict[str, Any]:
    claim = active.get("structured_claim") if isinstance(active.get("structured_claim"), dict) else {}
    center = claim.get("reaction_center") if isinstance(claim.get("reaction_center"), dict) else {}
    return {
        "forming_bonds": [item for item in center.get("forming_bonds", []) if isinstance(item, dict)],
        "breaking_bonds": [item for item in center.get("breaking_bonds", []) if isinstance(item, dict)],
        "transferred_atoms": [item for item in center.get("transferred_atoms", []) if isinstance(item, dict)],
        "spectator_regions": [item for item in center.get("spectator_regions", []) if isinstance(item, dict)],
    }


def collect_structures(
    root: Path,
    active: dict[str, Any],
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    derived = active.get("derived_from") if isinstance(active.get("derived_from"), dict) else {}
    structures: dict[str, dict[str, Any]] = {
        "reactant": _structure_ref(root, derived.get("reactant_ref"), "Reactant endpoint"),
        "product": _structure_ref(root, derived.get("product_ref"), "Product endpoint"),
    }

    tsfreq_record = _latest_record(records, {"tsfreq_gate"})
    tsfreq_artifact = artifacts.get(str(tsfreq_record.get("evidence_id", ""))) if tsfreq_record else None
    ts_path = _ts_structure_from_artifact(root, tsfreq_record, tsfreq_artifact)
    if ts_path is not None:
        structures["ts"] = _structure_ref(root, ts_path, "Accepted or selected TS")

    mode_minus, mode_plus = _mode_structures_from_tsfreq(root, tsfreq_record, tsfreq_artifact)
    if mode_minus is not None:
        structures["mode_minus"] = _structure_ref(root, mode_minus, "Negative imaginary-mode displacement")
    if mode_plus is not None:
        structures["mode_plus"] = _structure_ref(root, mode_plus, "Positive imaginary-mode displacement")

    conn_record = _latest_record(records, {"connectivity_gate", "irc_endpoint_assignment"})
    conn_artifact = artifacts.get(str(conn_record.get("evidence_id", ""))) if conn_record else None
    for key, ref in _irc_structures_from_connectivity(root, conn_artifact).items():
        structures[key] = ref

    return {key: value for key, value in structures.items() if value.get("path")}


def collect_tsfreq(
    root: Path,
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gate_records = [record for record in records if record.get("role") == "tsfreq_gate"]
    mode_records = [record for record in records if record.get("role") == "mode_assignment"]
    selected = _latest_supported(gate_records) or (gate_records[-1] if gate_records else {})
    artifact = artifacts.get(str(selected.get("evidence_id", "")), {})
    mode_record = mode_records[-1] if mode_records else {}
    mode_artifact = artifacts.get(str(mode_record.get("evidence_id", "")), artifact)
    mode_assignment = _first_dict(mode_artifact, "mode_assignment") or _merged_quality_facts(mode_record)
    electronic_gate = _first_dict(artifact, "electronic_structure_gate")
    return {
        "records": gate_records,
        "mode_records": mode_records,
        "selected_record": selected,
        "selected_artifact": artifact,
        "mode_assignment": mode_assignment,
        "electronic_structure_gate": electronic_gate or {},
        "energy": _energy_from_tsfreq(root, selected, artifact),
    }


def collect_connectivity(
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gate_records = [record for record in records if record.get("role") == "connectivity_gate"]
    endpoint_records = [record for record in records if record.get("role") == "irc_endpoint_assignment"]
    selected = _latest_supported(gate_records) or (gate_records[-1] if gate_records else {})
    artifact = artifacts.get(str(selected.get("evidence_id", "")), {})
    if not artifact and endpoint_records:
        artifact = artifacts.get(str(endpoint_records[-1].get("evidence_id", "")), {})
    return {
        "records": gate_records,
        "endpoint_records": endpoint_records,
        "selected_record": selected,
        "summary": artifact,
        "verdict": _first_dict(artifact, "connectivity_verdict") or _merged_quality_facts(selected),
        "directions": _first_dict(artifact, "direct_irc_endpoint_assignments")
        or _first_dict(artifact, "directions")
        or {},
    }


def collect_distance_profile(active: dict[str, Any], tsfreq: dict[str, Any], connectivity: dict[str, Any]) -> dict[str, Any]:
    keys = _reaction_center_labels(reaction_center(active))
    rows: list[dict[str, Any]] = []
    ts_artifact = tsfreq.get("selected_artifact") if isinstance(tsfreq.get("selected_artifact"), dict) else {}
    conn_artifact = connectivity.get("summary") if isinstance(connectivity.get("summary"), dict) else {}

    distance_sets = _first_dict(ts_artifact, "reaction_center_distances_angstrom") or {}
    mode_assignment = _first_dict(ts_artifact, "mode_assignment") or {}
    selected_job = str(mode_assignment.get("selected_job") or "").strip()
    primary_labels = ["reactant_endpoint", "product_endpoint"]
    if selected_job:
        primary_labels = [
            "reactant_endpoint",
            f"{selected_job}_mode_minus_0.20",
            f"{selected_job}_final",
            f"{selected_job}_mode_plus_0.20",
            "product_endpoint",
        ]
    else:
        primary_labels = ["reactant_endpoint", "p39_mode_minus_0.20", "p39_final", "p39_mode_plus_0.20", "product_endpoint"]
    for label in primary_labels:
        if label in distance_sets and isinstance(distance_sets[label], dict):
            rows.append({"label": _distance_label(label), "distances": distance_sets[label]})
    for label, value in distance_sets.items():
        if isinstance(value, dict) and label not in set(primary_labels) and label.endswith("_final") and not selected_job:
            rows.append({"label": _distance_label(label), "distances": value})

    endpoint_refs = _first_dict(conn_artifact, "endpoint_reference_distances_angstrom") or _first_dict(
        conn_artifact, "endpoint_key_distances_angstrom"
    )
    if isinstance(endpoint_refs, dict):
        if not any(row["label"] == "Reactant" for row in rows) and isinstance(endpoint_refs.get("reactant"), dict):
            rows.insert(0, {"label": "Reactant", "distances": endpoint_refs["reactant"]})
        if not any(row["label"] == "Product" for row in rows) and isinstance(endpoint_refs.get("product"), dict):
            rows.append({"label": "Product", "distances": endpoint_refs["product"]})

    for direction_label, direction in _direction_items(connectivity.get("directions", {})):
        distances = direction.get("distances") if isinstance(direction, dict) else None
        if isinstance(distances, dict):
            rows.append({"label": direction_label, "distances": distances})

    if not keys:
        keys = sorted({key for row in rows for key in row.get("distances", {})})
    else:
        extras = sorted({key for row in rows for key in row.get("distances", {}) if key not in keys})
        keys.extend(extras[:4])
    return {"keys": keys, "rows": rows}


def collect_energy_profile(
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    tsfreq: dict[str, Any],
) -> dict[str, Any]:
    rows_by_species: dict[str, dict[str, Any]] = {
        "R": {"species": "R", "role": "reactant", "source": "", "electronic_energy_hartree": None},
        "TS": {"species": "TS", "role": "transition_state", **_complete_energy_fields(tsfreq.get("energy") or {})},
        "P": {"species": "P", "role": "product", "source": "", "electronic_energy_hartree": None},
    }

    for species, row in _iter_energy_rows(records, artifacts):
        current = rows_by_species.get(species, {})
        if _energy_field_count(row) >= _energy_field_count(current):
            rows_by_species[species] = {**current, **row, "species": species}

    rows = [rows_by_species["R"], rows_by_species["TS"], rows_by_species["P"]]
    notes = _relative_energy_notes(rows)
    _add_relative_energies(rows, notes)
    return {"rows": rows, "notes": notes}


def _iter_energy_rows(
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for record in records:
        artifact = artifacts.get(str(record.get("evidence_id", "")), {})
        rows.extend(_energy_rows_from_container(record, artifact, _energy_source(record)))
    return rows


def _energy_rows_from_container(record: dict[str, Any], artifact: Any, source: str) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for data in _energy_payloads(record, artifact):
        species = _energy_species(record, data)
        if species is None or not _has_energy_data(data):
            continue
        rows.append((species, _energy_row(species, record, data, source)))
    return rows


def _energy_payloads(record: dict[str, Any], artifact: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    merged = {**_merged_quality_facts(record)}
    if isinstance(artifact, dict):
        merged.update(artifact)
    payloads.append(merged)
    if isinstance(artifact, dict):
        rows = artifact.get("rows") or _first_dict(artifact, "energy_profile")
        if isinstance(rows, dict):
            rows = rows.get("rows")
        if isinstance(rows, list):
            payloads.extend(item for item in rows if isinstance(item, dict))
        for key in ("reactant", "r", "product", "p", "ts", "transition_state"):
            value = artifact.get(key)
            if isinstance(value, dict):
                payloads.append({"species": key, **value})
        energies = artifact.get("energies")
        if isinstance(energies, dict):
            for key, value in energies.items():
                if isinstance(value, dict):
                    payloads.append({"species": str(key), **value})
    return payloads


def _energy_species(record: dict[str, Any], data: dict[str, Any]) -> str | None:
    for key in ("species", "structure_role", "stationary_point_role", "endpoint_role"):
        value = str(data.get(key, "")).strip().lower()
        if value in {"r", "reactant", "reactant_endpoint"}:
            return "R"
        if value in {"p", "product", "product_endpoint"}:
            return "P"
        if value in {"ts", "transition_state", "transition state"}:
            return "TS"
    tokens = [
        data.get("species"),
        data.get("structure_role"),
        data.get("stationary_point_role"),
        data.get("endpoint_role"),
        data.get("role"),
        record.get("role"),
        record.get("kind"),
        record.get("summary"),
        record.get("path"),
    ]
    text = " ".join(str(token).lower() for token in tokens if token)
    if any(token in text for token in ("transition_state", "transition state", "tsfreq", "ts_freq")):
        return "TS"
    if any(token in text for token in ("reactant", "reagent", " r ", "species=r", "endpoint_r")):
        return "R"
    if any(token in text for token in ("product", " p ", "species=p", "endpoint_p")):
        return "P"
    return None


def _energy_source(record: dict[str, Any]) -> str:
    if record.get("path"):
        return str(record["path"])
    source_files = record.get("source_files") if isinstance(record.get("source_files"), list) else []
    return str(source_files[0]) if source_files else ""


def _has_energy_data(data: dict[str, Any]) -> bool:
    return any(_numeric(data.get(field)) is not None for field in ENERGY_FIELDS)


def _energy_field_count(data: dict[str, Any]) -> int:
    return sum(1 for field in ENERGY_FIELDS if _numeric(data.get(field)) is not None)


def _energy_row(species: str, record: dict[str, Any], data: dict[str, Any], source: str) -> dict[str, Any]:
    completed = _complete_energy_fields(data)
    role = {"R": "reactant", "TS": "transition_state", "P": "product"}[species]
    row: dict[str, Any] = {
        "species": species,
        "role": str(data.get("role") or role),
        "source": source or str(record.get("path", "")),
    }
    for field in ENERGY_FIELDS:
        row[field] = completed.get(field)
    return row


def _complete_energy_fields(data: dict[str, Any]) -> dict[str, Any]:
    completed = dict(data)
    electronic = _numeric(completed.get("electronic_energy_hartree"))
    zpe = _numeric(completed.get("zero_point_correction_hartree"))
    gibbs = _numeric(completed.get("thermal_gibbs_correction_hartree"))
    if _numeric(completed.get("electronic_plus_zpe_hartree")) is None and electronic is not None and zpe is not None:
        completed["electronic_plus_zpe_hartree"] = electronic + zpe
    if (
        _numeric(completed.get("electronic_plus_thermal_free_energy_hartree")) is None
        and electronic is not None
        and gibbs is not None
    ):
        completed["electronic_plus_thermal_free_energy_hartree"] = electronic + gibbs
    for field in ENERGY_FIELDS:
        value = _numeric(completed.get(field))
        if value is not None:
            completed[field] = value
    return completed


def _add_relative_energies(rows: list[dict[str, Any]], notes: list[str]) -> None:
    for absolute_key, relative_key, label in [
        ("electronic_energy_hartree", "relative_electronic_energy_kcal_mol", "electronic energies"),
        ("electronic_plus_zpe_hartree", "relative_zpe_corrected_energy_kcal_mol", "E+ZPE energies"),
        (
            "electronic_plus_thermal_free_energy_hartree",
            "relative_free_energy_kcal_mol",
            "thermal free energies",
        ),
    ]:
        reference = _relative_reference(rows, absolute_key)
        if reference is None:
            notes.append(f"Comparable R/TS/P {label} are not complete in the current report context.")
            continue
        for row in rows:
            energy = _numeric(row.get(absolute_key))
            if energy is not None:
                row[relative_key] = round((energy - reference) * HARTREE_TO_KCAL_MOL, 3)


def _relative_reference(rows: list[dict[str, Any]], absolute_key: str) -> float | None:
    reactant = next((row for row in rows if row.get("species") == "R"), {})
    reactant_energy = _numeric(reactant.get(absolute_key))
    if reactant_energy is not None:
        return reactant_energy
    known = [_numeric(row.get(absolute_key)) for row in rows]
    known_values = [value for value in known if value is not None]
    if len(known_values) >= 2:
        return min(known_values)
    return None


def _relative_energy_notes(rows: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for row in rows:
        if _numeric(row.get("electronic_energy_hartree")) is None:
            notes.append(f"{row.get('species')} electronic energy is missing.")
        if _numeric(row.get("electronic_plus_zpe_hartree")) is None:
            notes.append(f"{row.get('species')} E+ZPE is missing.")
    return notes


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def collect_limitations(records: list[dict[str, Any]], connectivity: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    verdict = connectivity.get("verdict") if isinstance(connectivity.get("verdict"), dict) else {}
    caveat = verdict.get("caveat")
    if caveat:
        limitations.append(str(caveat))
    for record in records:
        text = str(record.get("summary", ""))
        if "caveat" in text.lower() and text not in limitations:
            limitations.append(text)
    return limitations


def _record_path(root: Path, record: dict[str, Any]) -> Path | None:
    raw = record.get("path")
    if not raw:
        source_files = record.get("source_files") if isinstance(record.get("source_files"), list) else []
        raw = source_files[0] if source_files else None
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else root / path


def _structure_ref(root: Path, value: Any, label: str) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(str(value))
    full = path if path.is_absolute() else root / path
    rel = str(full.relative_to(root)) if full.exists() and full.is_relative_to(root) else str(value)
    return {"label": label, "path": rel, "exists": full.exists()}


def _latest_record(records: list[dict[str, Any]], roles: set[str]) -> dict[str, Any]:
    matches = [record for record in records if record.get("role") in roles]
    return matches[-1] if matches else {}


def _latest_supported(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for record in reversed(records):
        merged = _merged_quality_facts(record)
        if str(merged.get("verdict_against_prediction", "")).lower() == "supported":
            return record
        if record.get("summary") and "support" in str(record.get("summary")).lower():
            return record
    return None


def _merged_quality_facts(record: dict[str, Any]) -> dict[str, Any]:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
    return {**quality, **facts}


def _first_dict(data: Any, key: str) -> dict[str, Any] | None:
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, dict):
            return value
        for child in data.values():
            found = _first_dict(child, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for child in data:
            found = _first_dict(child, key)
            if found is not None:
                return found
    return None


def _ts_structure_from_artifact(root: Path, record: dict[str, Any], artifact: dict[str, Any] | None) -> Path | None:
    merged = _merged_quality_facts(record)
    for key in ["ts_structure", "ts_xyz", "final_geometry", "structure", "xyz"]:
        if merged.get(key):
            return Path(str(merged[key]))
    artifact = artifact or {}
    for key in ["ts_structure", "ts_xyz", "final_geometry", "structure", "xyz"]:
        if artifact.get(key):
            return Path(str(artifact[key]))
    selected_job = None
    mode_assignment = _first_dict(artifact, "mode_assignment") or {}
    if mode_assignment.get("selected_job"):
        selected_job = str(mode_assignment["selected_job"])
    selected_job = selected_job or str(merged.get("selected_job") or "")
    record_path = _record_path(root, record)
    search_roots: list[Path] = []
    if record_path is not None:
        search_roots.append(record_path.parent)
    if selected_job and record_path is not None:
        search_roots.insert(0, record_path.parent / selected_job)
    for search_root in search_roots:
        if not search_root.exists():
            continue
        matches = sorted(search_root.glob("*final.xyz"))
        if matches:
            return matches[-1].relative_to(root)
    return None


def _mode_structures_from_tsfreq(
    root: Path,
    record: dict[str, Any],
    artifact: dict[str, Any] | None,
) -> tuple[Path | None, Path | None]:
    record_path = _record_path(root, record)
    if record_path is None:
        return None, None
    roots = [record_path.parent]
    selected_job = str((_first_dict(artifact or {}, "mode_assignment") or {}).get("selected_job") or "")
    if selected_job:
        roots.insert(0, record_path.parent / selected_job)
    minus = plus = None
    for search_root in roots:
        if not search_root.exists():
            continue
        minus_matches = sorted(search_root.glob("*mode_minus*.xyz"))
        plus_matches = sorted(search_root.glob("*mode_plus*.xyz"))
        minus = minus or (minus_matches[-1].relative_to(root) if minus_matches else None)
        plus = plus or (plus_matches[-1].relative_to(root) if plus_matches else None)
    return minus, plus


def _irc_structures_from_connectivity(root: Path, artifact: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(artifact, dict):
        return out
    for label, direction in _direction_items(
        _first_dict(artifact, "direct_irc_endpoint_assignments") or _first_dict(artifact, "directions") or {}
    ):
        if isinstance(direction, dict) and direction.get("final_geometry"):
            key = "irc_forward" if "forward" in label.lower() else "irc_reverse"
            out[key] = _structure_ref(root, direction["final_geometry"], f"IRC {label}")
    return out


def _energy_from_tsfreq(root: Path, record: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    merged = _merged_quality_facts(record)
    data = dict(merged)
    mode_assignment = _first_dict(artifact, "mode_assignment") or {}
    selected_job = str(mode_assignment.get("selected_job") or merged.get("selected_job") or "")
    job_summaries = artifact.get("job_summaries") if isinstance(artifact.get("job_summaries"), dict) else {}
    if selected_job and isinstance(job_summaries.get(selected_job), dict):
        data.update(job_summaries[selected_job])
    if not data.get("electronic_energy_hartree"):
        ts_path = _ts_structure_from_artifact(root, record, artifact)
        if ts_path is not None:
            validation = root / ts_path
            if validation.is_file():
                validation = validation.parent / "validation_summary.json"
            if validation.exists():
                try:
                    data.update(read_json(validation))
                except Exception:  # noqa: BLE001
                    pass
    return {
        "species": "TS",
        "role": "transition_state",
        "source": str(record.get("path", "")),
        "electronic_energy_hartree": data.get("electronic_energy_hartree"),
        "electronic_plus_zpe_hartree": data.get("electronic_plus_zpe_hartree"),
        "electronic_plus_thermal_free_energy_hartree": data.get("electronic_plus_thermal_free_energy_hartree"),
        "zero_point_correction_hartree": data.get("zero_point_correction_hartree"),
    }


def _reaction_center_labels(center: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for group in ["forming_bonds", "breaking_bonds"]:
        for item in center.get(group, []):
            label = item.get("label") if isinstance(item, dict) else None
            if label and label not in labels:
                labels.append(str(label))
    return labels


def _direction_items(directions: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(directions, dict):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for key, value in directions.items():
        if isinstance(value, dict):
            out.append((_distance_label(str(key)), value))
    return out


def _distance_label(label: str) -> str:
    replacements = {
        "reactant_endpoint": "Reactant",
        "product_endpoint": "Product",
        "p39_final": "TS",
        "p39_mode_minus_0.20": "Mode -",
        "p39_mode_plus_0.20": "Mode +",
    }
    if label in replacements:
        return replacements[label]
    if label.endswith("_final"):
        return "TS"
    if "mode_minus" in label:
        return "Mode -"
    if "mode_plus" in label:
        return "Mode +"
    return label.replace("_", " ")
