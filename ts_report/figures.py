"""Report asset generation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from ts_render import MolVisualizer


def write_report_assets(root: Path, context: dict[str, Any], assets_dir: Path) -> dict[str, Any]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Any] = {}
    assets["structure_panel_svg"] = _write_structure_panel_svg(context, assets_dir / "r_ts_p_structure_panel.svg")
    assets["distance_profile_svg"] = _write_distance_profile_svg(context, assets_dir / "irc_key_distance_profile.svg")
    assets["energy_profile_svg"] = _write_energy_profile_svg(context, assets_dir / "energy_profile.svg")
    render_asset = _try_render_mechanism(root, context, assets_dir / "r_ts_p_render.png")
    if render_asset:
        assets["structure_render"] = render_asset
    return assets


def _write_structure_panel_svg(context: dict[str, Any], path: Path) -> dict[str, Any]:
    structures = context.get("structures", {}) if isinstance(context.get("structures"), dict) else {}
    labels = ["reactant", "ts", "product"]
    lines = []
    for label in labels:
        item = structures.get(label, {})
        lines.append(f"{label.upper()}: {item.get('path', 'missing')}")
    return _write_text_svg(path, "R-TS-P Structure Panel", lines)


def _write_distance_profile_svg(context: dict[str, Any], path: Path) -> dict[str, Any]:
    profile = context.get("distance_profile", {}) if isinstance(context.get("distance_profile"), dict) else {}
    rows = [row for row in profile.get("rows", []) if isinstance(row, dict)]
    keys = [str(key) for key in profile.get("keys", [])[:6]]
    if not rows or not keys:
        return _write_text_svg(path, "IRC Key Distance Profile", ["No key-distance rows were available."])
    series: dict[str, list[float | None]] = {}
    for key in keys:
        values = []
        for row in rows:
            distances = row.get("distances") if isinstance(row.get("distances"), dict) else {}
            value = distances.get(key)
            values.append(float(value) if isinstance(value, int | float) else None)
        series[key] = values
    labels = [str(row.get("label", index)) for index, row in enumerate(rows)]
    return _write_line_svg(path, "IRC Key Distance Profile", labels, series, "Angstrom")


def _write_energy_profile_svg(context: dict[str, Any], path: Path) -> dict[str, Any]:
    profile = context.get("energy_profile", {}) if isinstance(context.get("energy_profile"), dict) else {}
    rows = [row for row in profile.get("rows", []) if isinstance(row, dict)]
    labels = [str(row.get("species", "")) for row in rows]
    series: dict[str, list[float | None]] = {}
    for key, label in [
        ("relative_zpe_corrected_energy_kcal_mol", "E+ZPE"),
        ("relative_free_energy_kcal_mol", "G"),
        ("relative_electronic_energy_kcal_mol", "electronic"),
    ]:
        values = [float(row[key]) if isinstance(row.get(key), int | float) else None for row in rows]
        if sum(value is not None for value in values) >= 2:
            series[label] = values
    if not series:
        notes = profile.get("notes", []) if isinstance(profile.get("notes"), list) else []
        return _write_text_svg(path, "Energy Profile", notes or ["Comparable R/TS/P energies were not available."])
    return _write_line_svg(path, "Energy Profile", labels, series, "kcal mol-1")


def _try_render_mechanism(root: Path, context: dict[str, Any], path: Path) -> dict[str, Any] | None:
    structures = context.get("structures", {}) if isinstance(context.get("structures"), dict) else {}
    selected = [structures.get(key, {}) for key in ["reactant", "ts", "product"]]
    files = []
    for item in selected:
        raw = item.get("path") if isinstance(item, dict) else None
        if not raw:
            return None
        full = root / str(raw)
        if not full.exists():
            return None
        files.append(full)
    result = MolVisualizer(resolution=(2048, 1024)).render_reaction_mechanism(files, ["R", "TS", "P"], path)
    return result.to_dict()


def _write_line_svg(
    path: Path,
    title: str,
    labels: list[str],
    series: dict[str, list[float | None]],
    unit: str,
) -> dict[str, Any]:
    width, height = 960, 520
    left, right, top, bottom = 90, 40, 60, 110
    values = [value for rows in series.values() for value in rows if value is not None]
    if not values:
        return _write_text_svg(path, title, ["No numeric values were available."])
    y_min, y_max = min(values), max(values)
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0
    x_step = (width - left - right) / max(1, len(labels) - 1)

    def x_at(index: int) -> float:
        return left + index * x_step

    def y_at(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * (height - top - bottom)

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="30" text-anchor="middle" font-family="Arial" font-size="24">{html.escape(title)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#333"/>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#333"/>',
        f'<text x="20" y="{top}" font-family="Arial" font-size="12">{html.escape(f"{y_max:.2f}")}</text>',
        f'<text x="20" y="{height - bottom}" font-family="Arial" font-size="12">{html.escape(f"{y_min:.2f}")}</text>',
        f'<text x="{left}" y="{height - 30}" font-family="Arial" font-size="13">{html.escape(unit)}</text>',
    ]
    for index, label in enumerate(labels):
        x = x_at(index)
        svg.append(f'<text x="{x}" y="{height - bottom + 28}" text-anchor="middle" font-family="Arial" font-size="12">{html.escape(label)}</text>')
    for series_index, (name, rows) in enumerate(series.items()):
        color = colors[series_index % len(colors)]
        points = [(x_at(index), y_at(value)) for index, value in enumerate(rows) if value is not None]
        if len(points) >= 2:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            svg.append(f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="3"/>')
        for x, y in points:
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        legend_y = 62 + series_index * 20
        svg.append(f'<rect x="{width - 210}" y="{legend_y - 10}" width="12" height="12" fill="{color}"/>')
        svg.append(f'<text x="{width - 190}" y="{legend_y}" font-family="Arial" font-size="13">{html.escape(name)}</text>')
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return {"path": str(path), "kind": "svg", "created": True}


def _write_text_svg(path: Path, title: str, lines: list[str]) -> dict[str, Any]:
    width, height = 960, 260 + 26 * max(0, len(lines) - 1)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="40" y="44" font-family="Arial" font-size="24" font-weight="700">{html.escape(title)}</text>',
    ]
    for index, line in enumerate(lines):
        svg.append(f'<text x="40" y="{88 + index * 26}" font-family="Arial" font-size="16">{html.escape(str(line))}</text>')
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return {"path": str(path), "kind": "svg", "created": True}
