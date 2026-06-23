"""Command-backed molecular rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

from .config import DEFAULT_RESOLUTION
from .environment import EnvironmentChecker
from .results import RenderResult


class MolVisualizer:
    """Render molecular structures through the configured xyzrender command."""

    def __init__(
        self,
        engine: str = "blender",
        style: str = "ball_and_stick",
        color_scheme: str = "cpk",
        background: str = "white",
        resolution: tuple[int, int] = DEFAULT_RESOLUTION,
        xyzrender_path: str | None = None,
        timeout: int = 600,
    ):
        self.engine = engine
        self.style = style
        self.color_scheme = color_scheme
        self.background = background
        self.resolution = resolution
        self.timeout = timeout
        self.checker = EnvironmentChecker()
        self.xyzrender_path = xyzrender_path or self.checker.xyzrender_path()

    def render_molecule(
        self,
        structure_file: str | Path,
        output_file: str | Path,
        style: str | None = None,
        engine: str | None = None,
        resolution: tuple[int, int] | None = None,
        background: str | None = None,
        color_scheme: str | None = None,
    ) -> RenderResult:
        command = self._base_command("render", structure_file, output_file, style, engine, resolution, background, color_scheme)
        return self._run(command, output_file)

    def render(self, structure_file: str | Path, output: str | Path, **kwargs) -> RenderResult:
        return self.render_molecule(structure_file, output, **kwargs)

    def compare_structures(
        self,
        structure_files: Iterable[str | Path],
        output_file: str | Path,
        styles: list[str] | None = None,
        titles: list[str] | None = None,
        layout: str = "horizontal",
        engine: str | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> RenderResult:
        files = [str(path) for path in structure_files]
        prefix = self._xyzrender_command("compare")
        if not prefix:
            return RenderResult.missing_command("xyzrender", ["Set TS_RENDER_XYZRENDER or install the skill runtime env."])
        if not files:
            return RenderResult(
                ok=False,
                output_path=None,
                command=[],
                stderr="compare requires at least one structure file",
                diagnostics=["no input structures"],
            )
        command = [
            *prefix,
            files[0],
            "-o",
            str(output_file),
            "-S",
            _canvas_size(resolution or self.resolution),
        ]
        _add_background_args(command, self.background)
        for overlay in files[1:]:
            command.extend(["--overlay", overlay])
        for index, title in enumerate(titles or []):
            command.extend(["-l", f"{index}:{title}"])
        for index, style in enumerate(styles or []):
            if style == "space_fill":
                command.extend(["--vdw"])
        return self._run(command, output_file)

    def compare(self, structure_files: Iterable[str | Path], output: str | Path, **kwargs) -> RenderResult:
        return self.compare_structures(structure_files, output, **kwargs)

    def animate_trajectory(
        self,
        trajectory_file: str | Path,
        output_file: str | Path,
        frames: int = 100,
        fps: int = 24,
        camera_path: str = "orbit",
        style: str | None = None,
        engine: str | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> RenderResult:
        prefix = self._xyzrender_command("animate")
        if not prefix:
            return RenderResult.missing_command("xyzrender", ["Set TS_RENDER_XYZRENDER or install the skill runtime env."])
        command = [
            *prefix,
            str(trajectory_file),
            "--gif-trj",
            "-go",
            str(output_file),
            "--gif-fps",
            str(fps),
            "-S",
            _canvas_size(resolution or self.resolution),
        ]
        _add_background_args(command, self.background)
        return self._run(command, output_file)

    def render_reaction_mechanism(
        self,
        structure_files: Iterable[str | Path],
        labels: list[str],
        output_file: str | Path,
        layout: str = "horizontal",
        show_arrow: bool = True,
    ) -> RenderResult:
        prefix = self._xyzrender_command("mechanism")
        if not prefix:
            return RenderResult.missing_command("xyzrender", ["Set TS_RENDER_XYZRENDER or install the skill runtime env."])
        files = [str(path) for path in structure_files]
        if not files:
            return RenderResult(
                ok=False,
                output_path=None,
                command=[],
                stderr="mechanism requires at least one structure file",
                diagnostics=["no input structures"],
            )
        command = [
            *prefix,
            files[0],
            "-o",
            str(output_file),
            "-S",
            _canvas_size(self.resolution),
        ]
        _add_background_args(command, self.background)
        for overlay in files[1:]:
            command.extend(["--overlay", overlay])
        for index, label in enumerate(labels):
            command.extend(["-l", f"{index}:{label}"])
        return self._run(command, output_file)

    def _base_command(
        self,
        subcommand: str,
        input_file: str | Path,
        output_file: str | Path,
        style: str | None,
        engine: str | None,
        resolution: tuple[int, int] | None,
        background: str | None,
        color_scheme: str | None,
    ) -> list[str]:
        prefix = self._xyzrender_command(subcommand)
        if not prefix:
            return []
        command = [
            *prefix,
            str(input_file),
            "-o",
            str(output_file),
            "-S",
            _canvas_size(resolution or self.resolution),
        ]
        _add_background_args(command, background or self.background)
        if (style or self.style) == "space_fill":
            command.extend(["--vdw"])
        return command

    def _xyzrender_command(self, subcommand: str) -> list[str]:
        if not self.xyzrender_path:
            return []
        return [self.xyzrender_path]

    def _run(self, command: list[str], output_file: str | Path) -> RenderResult:
        if not command:
            return RenderResult.missing_command("xyzrender", ["Set TS_RENDER_XYZRENDER or install the skill runtime env."])
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
            check=False,
        )
        ok = completed.returncode == 0 and output.exists()
        diagnostics = [] if ok else [f"expected output was not created: {output}"]
        return RenderResult(
            ok=ok,
            output_path=str(output) if ok else None,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            diagnostics=diagnostics,
        )


def render_molecule(structure_file: str | Path, output_file: str | Path, **kwargs) -> RenderResult:
    return MolVisualizer(**{key: value for key, value in kwargs.items() if key in _INIT_KEYS}).render_molecule(
        structure_file,
        output_file,
        **{key: value for key, value in kwargs.items() if key not in _INIT_KEYS},
    )


def _resolution_text(resolution: tuple[int, int]) -> str:
    return f"{resolution[0]}x{resolution[1]}"


def _canvas_size(resolution: tuple[int, int]) -> str:
    return str(max(resolution))


def _add_background_args(command: list[str], background: str) -> None:
    if background == "transparent":
        command.append("-t")
    else:
        command.extend(["-B", background])


_INIT_KEYS = {"engine", "style", "color_scheme", "background", "resolution", "xyzrender_path", "timeout"}
