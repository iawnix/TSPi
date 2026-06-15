"""QBICS backend adapter and dMECP candidate-output parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput


QBICS_LOG_SUFFIXES = (".out", ".log", ".txt")
QBICS_ARTIFACT_SUFFIXES = (".mwfn", ".trj")


@dataclass(frozen=True)
class QbicsCommandRequest:
    """Typed request for one QBICS command-line run."""

    input_file: Path
    executable: str = "qbics-linux-cpu-mpi"
    task: str = "dmecp"
    method: str | None = None
    mpi_ranks: int | str | None = None
    threads: int | str | None = None
    memory_gb: int | str | None = None
    extra_args: tuple[str, ...] = ()


def positive_int_or_none(value: int | str | None, *, field: str) -> int | None:
    """Normalize optional positive integer command parameters."""

    if value is None or str(value).strip() == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"QBICS {field} must be positive")
    return parsed


def normalize_qbics_task(value: str | None) -> str:
    """Return the stable QBICS task name used by this workflow."""

    raw = (value or "dmecp").strip().lower()
    aliases = {
        "dmecp": "dmecp",
        "mecp": "dmecp",
        "d-mecp": "dmecp",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise ValueError(f"unsupported QBICS task: {value!r}") from exc


def qbics_method_label(value: str | None) -> str:
    """Return a stable method label for metadata."""

    return (value or "unknown").strip() or "unknown"


def build_qbics_cli_argv(request: QbicsCommandRequest) -> tuple[str, ...]:
    """Build an argv-only QBICS command, optionally wrapped by ``mpirun``."""

    task = normalize_qbics_task(request.task)
    mpi_ranks = positive_int_or_none(request.mpi_ranks, field="mpi_ranks")
    threads = positive_int_or_none(request.threads, field="threads")
    memory_gb = positive_int_or_none(request.memory_gb, field="memory_gb")
    argv: list[str] = []
    if mpi_ranks is not None and mpi_ranks > 1:
        argv.extend(("mpirun", "-np", str(mpi_ranks)))
    argv.extend((request.executable, str(request.input_file)))
    if threads is not None:
        argv.extend(("-n", str(threads)))
    if memory_gb is not None:
        argv.extend(("-m", str(memory_gb)))
    argv.extend(request.extra_args)
    if task != "dmecp":  # pragma: no cover - normalize_qbics_task guards this.
        raise ValueError(f"unsupported QBICS task: {task!r}")
    return tuple(argv)


def qbics_request_from_mapping(request: Mapping[str, Any]) -> QbicsCommandRequest:
    """Create a :class:`QbicsCommandRequest` from backend-neutral mapping fields."""

    input_value = request.get("input_file") or request.get("input_path") or request.get("inp")
    if input_value is None:
        files = tuple(request.get("files", ()))
        if files:
            input_value = files[0]
    if input_value is None:
        raise ValueError("QBICS backend request requires input_file, inp, or files[0]")
    return QbicsCommandRequest(
        input_file=Path(str(input_value)),
        executable=str(request.get("executable", "qbics-linux-cpu-mpi")),
        task=str(request.get("task", "dmecp")),
        method=request.get("method"),
        mpi_ranks=request.get("mpi_ranks", request.get("ranks")),
        threads=request.get("threads", request.get("omp_threads")),
        memory_gb=request.get("memory_gb", request.get("memory")),
        extra_args=tuple(str(item) for item in request.get("extra_args", ())),
    )


def discover_qbics_artifacts(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Return explicit and directory-discovered QBICS artifacts in stable order."""

    discovered: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if path not in seen:
            seen.add(path)
            discovered.append(path)

    for path in paths:
        if path.is_dir():
            for candidate in sorted(path.iterdir()):
                if not candidate.is_file():
                    continue
                lower_name = candidate.name.lower()
                suffix = candidate.suffix.lower()
                if (
                    "mecp" in lower_name
                    or lower_name.startswith("qbics")
                    or suffix in QBICS_ARTIFACT_SUFFIXES
                    or suffix in QBICS_LOG_SUFFIXES
                ):
                    add(candidate)
        else:
            add(path)
    return tuple(discovered)


def parse_qbics_output_text(text: str) -> dict[str, Any]:
    """Parse stable QBICS dMECP convergence and diagnostic signals."""

    lower_text = text.lower()
    scf_converged = None
    if "scf does not converge" in lower_text or "scf does not converged" in lower_text:
        scf_converged = False
    elif "scf converged" in lower_text or "scf convergence achieved" in lower_text:
        scf_converged = True
    dmecp_converged = None
    if "dmecp" in lower_text or "mecp" in lower_text:
        if "mecp optimization converged" in lower_text or "dmecp converged" in lower_text:
            dmecp_converged = True
        elif "dmecp does not converge" in lower_text or "mecp does not converge" in lower_text:
            dmecp_converged = False
    normal_termination = "normal termination" in lower_text or "job finished" in lower_text
    thresholds: dict[str, float] = {}
    for key in ("energy_cov", "grad_cov", "dr_cov"):
        match = re.search(rf"\b{key}\s+([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)", text, flags=re.IGNORECASE)
        if match:
            thresholds[key] = float(match.group(1).replace("D", "E").replace("d", "E"))
    final_energy = None
    for pattern in (
        r"\bfinal\s+energy\s*[=:]\s*([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
        r"\btotal\s+energy\s*[=:]?\s*([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
        r"\bmecp\s+energy\s*[=:]\s*([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            final_energy = float(match.group(1).replace("D", "E").replace("d", "E"))
    spin_squared = None
    match = re.search(r"<S\*\*2>|<S\^2>", text, flags=re.IGNORECASE)
    if match:
        tail = text[match.end() : match.end() + 80]
        value_match = re.search(r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)", tail)
        if value_match:
            spin_squared = float(value_match.group(1).replace("D", "E").replace("d", "E"))
    return {
        "scf_converged": scf_converged,
        "dmecp_converged": dmecp_converged,
        "normal_termination": normal_termination,
        "thresholds": thresholds,
        "final_energy_hartree": final_energy,
        "spin_squared": spin_squared,
    }


def parse_qbics_artifacts(artifacts: Sequence[Path]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Collect QBICS dMECP artifact metadata plus lightweight parsed evidence."""

    artifact_list = tuple(artifacts)
    existing = tuple(path for path in artifact_list if path.exists())
    candidate_geometries = tuple(str(path) for path in existing if path.name.lower().endswith("-mecp.xyz"))
    trajectories = tuple(str(path) for path in existing if "mecp-traj" in path.name.lower())
    mwfn_files = tuple(str(path) for path in existing if path.suffix.lower() == ".mwfn")
    log_paths = tuple(
        path
        for path in existing
        if path.is_file() and (path.name.lower().startswith("qbics") or path.suffix.lower() in QBICS_LOG_SUFFIXES)
    )
    parsed_logs: dict[str, Any] = {}
    diagnostics: list[str] = []
    for log_path in log_paths:
        parsed = parse_qbics_output_text(log_path.read_text(encoding="utf-8", errors="replace"))
        parsed_logs[str(log_path)] = parsed
        if parsed.get("scf_converged") is False:
            if candidate_geometries:
                diagnostics.append("qbics_scf_nonconverged_but_candidate_written")
            else:
                diagnostics.append("qbics_scf_nonconverged")
        if parsed.get("dmecp_converged") is False:
            diagnostics.append("qbics_dmecp_not_converged")
    properties = {
        "artifact_count": len(artifact_list),
        "existing_artifacts": len(existing),
        "candidate_only": True,
        "candidate_geometries": candidate_geometries,
        "trajectory": trajectories[0] if trajectories else None,
        "trajectories": trajectories,
        "mwfn_files": mwfn_files,
        "logs": tuple(str(path) for path in log_paths),
        "parsed_logs": parsed_logs,
    }
    return properties, tuple(dict.fromkeys(diagnostics))


class QbicsBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for QBICS candidate-generation setup and parsing."""

    name = "qbics"

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Prepare a QBICS dMECP command from backend-neutral fields."""

        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")
        command_request = qbics_request_from_mapping(request)
        task = normalize_qbics_task(command_request.task)
        return BackendInput(
            backend=self.name,
            files=(command_request.input_file,),
            command_argv=build_qbics_cli_argv(command_request),
            metadata={
                **dict(metadata),
                "task": task,
                "method": qbics_method_label(command_request.method),
                "candidate_only": True,
                "mpi_ranks": positive_int_or_none(command_request.mpi_ranks, field="mpi_ranks"),
                "threads": positive_int_or_none(command_request.threads, field="threads"),
                "memory_gb": positive_int_or_none(command_request.memory_gb, field="memory_gb"),
            },
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Parse QBICS dMECP artifacts without making TS-validation claims."""

        discovered = discover_qbics_artifacts(artifacts)
        properties, diagnostics = parse_qbics_artifacts(discovered)
        return BackendOutput(
            backend=self.name,
            artifacts=discovered,
            properties=properties,
            diagnostics=diagnostics,
        )


__all__ = [
    "QBICS_ARTIFACT_SUFFIXES",
    "QBICS_LOG_SUFFIXES",
    "QbicsBackendAdapter",
    "QbicsCommandRequest",
    "build_qbics_cli_argv",
    "discover_qbics_artifacts",
    "normalize_qbics_task",
    "parse_qbics_artifacts",
    "parse_qbics_output_text",
    "positive_int_or_none",
    "qbics_method_label",
    "qbics_request_from_mapping",
]
