"""ASE runtime environment adapter and dependency loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput


ASE_SUPPORTED_WORKFLOWS = ("ase-neb",)
ASE_RUNTIME_DEPENDENCIES = ("ase", "xtb-python", "ase-gaussian-calculator")


class AseBackendAdapter(FilesystemBackendAdapter):
    """Registry adapter for ASE runtime capabilities.

    Actual ASE-NEB execution lives in ``backends/ase_neb/``. This adapter keeps
    the registry-level ``ase`` name explicit: it describes in-process ASE
    runtime requirements and accepted ASE workflow families rather than
    pretending that ASE has a standalone CLI parser.
    """

    name = "ase"

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Return ASE runtime metadata for an in-process workflow."""

        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")
        workflow = str(request.get("workflow", request.get("task", "ase-neb"))).strip().lower()
        if workflow not in ASE_SUPPORTED_WORKFLOWS:
            raise ValueError(f"unsupported ASE backend workflow: {workflow!r}")
        calculator = request.get("calculator", {})
        calculator_type = None
        if isinstance(calculator, Mapping):
            calculator_type = calculator.get("type")
        files = tuple(Path(item) for item in request.get("files", ()))
        return BackendInput(
            backend=self.name,
            files=files,
            command_argv=(),
            metadata={
                **dict(metadata),
                "adapter_role": "ase_runtime_environment",
                "workflow": workflow,
                "calculator_type": calculator_type,
                "execution_backend": "ase_neb" if workflow == "ase-neb" else workflow,
                "runtime_dependencies": ASE_RUNTIME_DEPENDENCIES,
            },
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Return ASE runtime artifact metadata without parsing NEB summaries."""

        existing = tuple(path for path in artifacts if path.exists())
        return BackendOutput(
            backend=self.name,
            artifacts=artifacts,
            properties={
                "adapter_role": "ase_runtime_environment",
                "supported_workflows": ASE_SUPPORTED_WORKFLOWS,
                "execution_backends": ("ase_neb",),
                "artifact_count": len(artifacts),
                "existing_artifacts": len(existing),
            },
        )


def require_ase() -> None:
    try:
        import ase  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("ASE is required for prepare/run; install ase first") from exc


def require_xtb() -> None:
    try:
        import xtb  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("xTB Python bindings are required for calculator.type=xtb") from exc


def require_gaussian_calculator() -> None:
    try:
        from ase.calculators.gaussian import Gaussian  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("ASE Gaussian calculator is required for calculator.type=gaussian") from exc


def import_ase_bits() -> dict[str, Any]:
    require_ase()
    from ase.io import read, write
    from ase.optimize import BFGS, FIRE, LBFGS, MDMin

    try:
        from ase.mep import DyNEB, NEB
    except ImportError:  # pragma: no cover - older ASE fallback
        from ase.neb import NEB  # type: ignore[no-redef]

        DyNEB = None

    return {
        "read": read,
        "write": write,
        "NEB": NEB,
        "DyNEB": DyNEB,
        "optimizers": {"FIRE": FIRE, "BFGS": BFGS, "LBFGS": LBFGS, "MDMin": MDMin},
    }


__all__ = [
    "ASE_RUNTIME_DEPENDENCIES",
    "ASE_SUPPORTED_WORKFLOWS",
    "AseBackendAdapter",
    "require_ase",
    "require_xtb",
    "require_gaussian_calculator",
    "import_ase_bits",
]
