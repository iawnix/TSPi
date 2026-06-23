"""Trajectory animation wrapper for ts_render."""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_RESOLUTION
from .renderer import MolVisualizer
from .results import RenderResult


class TrajectoryVisualizer:
    def __init__(
        self,
        engine: str = "xyzrender",
        style: str = "ball_and_stick",
        color_scheme: str = "cpk",
        background: str = "white",
        resolution: tuple[int, int] = DEFAULT_RESOLUTION,
        xyzrender_path: str | None = None,
    ):
        self.renderer = MolVisualizer(
            engine=engine,
            style=style,
            color_scheme=color_scheme,
            background=background,
            resolution=resolution,
            xyzrender_path=xyzrender_path,
        )

    def animate_trajectory(
        self,
        trajectory_file: str | Path,
        output_file: str | Path,
        frames: int = 100,
        fps: int = 24,
        camera_path: str = "orbit",
    ) -> RenderResult:
        return self.renderer.animate_trajectory(
            trajectory_file,
            output_file,
            frames=frames,
            fps=fps,
            camera_path=camera_path,
        )

    def animate(self, trajectory_file: str | Path, output: str | Path, **kwargs) -> RenderResult:
        return self.animate_trajectory(trajectory_file, output, **kwargs)
