"""Deterministic scientific curve rendering from validated JSON artifacts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .results import RenderResult


CURVE_SCHEMA = "ts-curve-data/1"
CURVE_KINDS = ("curve", "energy", "scan", "convergence")


def render_curve(
    data_file: str | Path,
    output_file: str | Path,
    *,
    kind: str = "curve",
    resolution: tuple[int, int] = (1024, 768),
    background: str = "white",
) -> RenderResult:
    """Render one validated curve artifact to a deterministic PNG."""

    if kind not in CURVE_KINDS:
        return _failure("request", f"unsupported curve kind: {kind}")
    try:
        document = json.loads(Path(data_file).read_text(encoding="utf-8"))
        series, title, x_label, y_label = _validate_document(document, kind)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _failure("request", str(exc))

    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - depends on optional render environment
        return _failure("environment", "matplotlib is required for curve rendering", exc)

    width, height = resolution
    if width < 128 or height < 128:
        return _failure("request", "curve resolution must be at least 128x128")
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure = None
    try:
        figure, axis = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        figure.patch.set_facecolor(background)
        axis.set_facecolor(background)
        for item in series:
            axis.plot(item["x"], item["y"], label=item["name"])
        axis.set_title(title)
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        axis.grid(True, alpha=0.25)
        if len(series) > 1:
            axis.legend()
        figure.tight_layout()
        # Metadata is fixed to avoid timestamps and backend-specific author data.
        figure.savefig(output, format="png", metadata={"Software": "TSPi ts-render"})
    except Exception as exc:
        return _failure("matplotlib", str(exc), exc)
    finally:
        if figure is not None:
            plt.close(figure)
    if not output.is_file() or output.stat().st_size == 0:
        return _failure("matplotlib", f"expected output was not created: {output}")
    return RenderResult(
        ok=True,
        output_path=str(output),
        command=["matplotlib", str(data_file), "-o", str(output_file)],
        returncode=0,
        diagnostics=[],
        commands=[],
        failure_stage=None,
    )


def _validate_document(document: Any, kind: str) -> tuple[list[dict[str, Any]], str, str, str]:
    if not isinstance(document, dict) or document.get("schema_version") != CURVE_SCHEMA:
        raise ValueError(f"curve input must use {CURVE_SCHEMA}")
    series = document.get("series")
    if not isinstance(series, list) or not series or len(series) > 16:
        raise ValueError("curve input must contain 1 to 16 series")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(series, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"series {index} must be an object")
        x = item.get("x")
        y = item.get("y")
        if not isinstance(x, list) or not isinstance(y, list) or len(x) != len(y) or not x:
            raise ValueError(f"series {index} must contain equal non-empty x and y arrays")
        if len(x) > 100_000:
            raise ValueError(f"series {index} exceeds the 100000 point limit")
        values = [*x, *y]
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in values):
            raise ValueError(f"series {index} contains a non-finite numeric value")
        normalized.append({"name": str(item.get("name") or f"Series {index}"), "x": x, "y": y})
    title = str(document.get("title") or {"energy": "Energy profile", "scan": "Parameter scan", "convergence": "Convergence"}.get(kind, "Curve"))
    x_label = str(document.get("x_label") or document.get("x_unit") or "x")
    y_label = str(document.get("y_label") or document.get("y_unit") or "y")
    return normalized, title, x_label, y_label


def _failure(stage: str, message: str, error: Exception | None = None) -> RenderResult:
    detail = f"{message}: {error}" if error is not None else message
    return RenderResult(
        ok=False,
        output_path=None,
        command=[],
        returncode=None,
        stderr=detail,
        diagnostics=[message],
        commands=[],
        failure_stage=stage,
    )
