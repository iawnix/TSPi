#!/usr/bin/env python3
"""First party render Provider using the extension's rendering library."""
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "packages" / "tspi-runtime"), str(Path(__file__).resolve().parent)]
from tspi_runtime.providers.runner import run_jsonl_provider
from render_lib import MolVisualizer
from render_lib.config import parse_resolution

def handle(request):
    inputs = request.inputs
    operation = str(inputs.get("operation", "render"))
    paths = [Path(item) for item in inputs.get("artifact_paths", inputs.get("inputs", []))]
    output = Path(inputs.get("output_path", ""))
    if not paths or not output.is_absolute(): raise ValueError("render provider requires absolute artifact_paths and output_path")
    resolution = parse_resolution(str(request.parameters.get("resolution", "1024x768")))
    visualizer = MolVisualizer(style=request.parameters.get("style", "ball_and_stick"), engine=request.parameters.get("engine", "xyzrender"), color_scheme=request.parameters.get("color_scheme", "cpk"), background=request.parameters.get("background", "white"), resolution=resolution)
    if operation == "render": result = visualizer.render_molecule(paths[0], output)
    elif operation == "compare": result = visualizer.compare_structures(paths, output, titles=request.parameters.get("titles"), layout=request.parameters.get("layout", "horizontal"))
    elif operation == "animate": result = visualizer.animate_trajectory(paths[0], output, frames=int(request.parameters.get("frames", 100)), fps=int(request.parameters.get("fps", 24)))
    elif operation == "mechanism": result = visualizer.render_reaction_mechanism(paths, request.parameters.get("labels", []), output, layout=request.parameters.get("layout", "horizontal"))
    else: result = visualizer.render_curve(paths[0], output, kind=operation, resolution=resolution)
    if not result.ok:
        return {"status": "failed", "result": result.to_dict(), "outputs": [], "provenance": {"provider_id": request.provider_id, "request_id": request.request_id}, "diagnostics": [{"code": "render_failed", "message": result.stderr or "; ".join(result.diagnostics)}]}
    return {"status": "succeeded", "result": result.to_dict(), "outputs": [{"role": "artifact", "path": str(output)}], "provenance": {"provider_id": request.provider_id, "request_id": request.request_id}, "diagnostics": result.diagnostics}

if __name__ == "__main__": raise SystemExit(run_jsonl_provider(handle))
