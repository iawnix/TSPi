"""Command-backed molecular rendering."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from .config import DEFAULT_RESOLUTION
from .curves import render_curve
from .environment import EnvironmentChecker
from .panels import compose_panels
from .results import RenderResult


class MolVisualizer:
    """Render molecular structures through the configured xyzrender command."""

    def __init__(
        self,
        engine: str = "xyzrender",
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
        return self._render_panel_set(
            "compare",
            files,
            output_file,
            labels=titles or [],
            layout=layout,
            show_arrows=False,
            styles=styles or [],
            resolution=resolution or self.resolution,
        )

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
        files = [str(path) for path in structure_files]
        return self._render_panel_set(
            "mechanism",
            files,
            output_file,
            labels=labels,
            layout=layout,
            show_arrows=show_arrow,
            styles=[],
            resolution=self.resolution,
        )

    def render_curve(
        self,
        data_file: str | Path,
        output_file: str | Path,
        *,
        kind: str = "curve",
        resolution: tuple[int, int] | None = None,
    ) -> RenderResult:
        return render_curve(
            data_file,
            output_file,
            kind=kind,
            resolution=resolution or self.resolution,
            background=self.background,
        )

    def _render_panel_set(
        self,
        operation: str,
        files: list[str],
        output_file: str | Path,
        *,
        labels: list[str],
        layout: str,
        show_arrows: bool,
        styles: list[str],
        resolution: tuple[int, int],
    ) -> RenderResult:
        prefix = self._xyzrender_command(operation)
        if not prefix:
            return RenderResult.missing_command("xyzrender", ["Set TS_RENDER_XYZRENDER or install the skill runtime env."])
        if not files:
            return RenderResult(
                ok=False,
                output_path=None,
                command=[],
                stderr=f"{operation} requires at least one structure file",
                diagnostics=["no input structures"],
                failure_stage="request",
            )
        if labels and len(labels) != len(files):
            return RenderResult(
                ok=False,
                output_path=None,
                command=[],
                stderr=f"{operation} labels must match the number of input structures",
                diagnostics=["label count does not match input count"],
                failure_stage="request",
            )
        if styles and len(styles) > len(files):
            return RenderResult(
                ok=False,
                output_path=None,
                command=[],
                stderr="compare styles cannot outnumber input structures",
                diagnostics=["style count exceeds input count"],
                failure_stage="request",
            )

        commands: list[list[str]] = []
        stdout: list[str] = []
        stderr: list[str] = []
        with tempfile.TemporaryDirectory(prefix="ts-render-panels-") as temporary:
            panel_files: list[Path] = []
            panel_size = max(256, min(2048, max(resolution)))
            for index, input_file in enumerate(files):
                panel_file = Path(temporary) / f"panel-{index + 1}.png"
                command = [*prefix, input_file, "-o", str(panel_file), "-S", str(panel_size), "-t"]
                if index < len(styles) and styles[index] == "space_fill":
                    command.append("--vdw")
                result = self._run(command, panel_file)
                commands.append(command)
                if result.stdout:
                    stdout.append(result.stdout)
                if result.stderr:
                    stderr.append(result.stderr)
                if not result.ok:
                    return RenderResult(
                        ok=False,
                        output_path=None,
                        command=command,
                        returncode=result.returncode,
                        stdout="\n".join(stdout),
                        stderr="\n".join(stderr),
                        diagnostics=[f"{operation} panel {index + 1} failed", *result.diagnostics],
                        commands=commands,
                        failure_stage=result.failure_stage or "xyzrender",
                    )
                panel_files.append(panel_file)
            try:
                compose_panels(
                    panel_files,
                    output_file,
                    resolution=resolution,
                    layout=layout,
                    labels=labels,
                    background=self.background,
                    show_arrows=show_arrows,
                )
            except Exception as exc:
                return RenderResult(
                    ok=False,
                    output_path=None,
                    command=commands[-1] if commands else [],
                    stdout="\n".join(stdout),
                    stderr=f"panel composition failed: {exc}",
                    diagnostics=[f"{operation} panel composition failed"],
                    commands=commands,
                    failure_stage="composition",
                )
        return RenderResult(
            ok=True,
            output_path=str(output_file),
            command=commands[-1] if commands else [],
            returncode=0,
            stdout="\n".join(stdout),
            stderr="\n".join(stderr),
            diagnostics=[],
            commands=commands,
            failure_stage=None,
        )

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
            commands=[command],
            failure_stage=None if ok else "xyzrender",
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
