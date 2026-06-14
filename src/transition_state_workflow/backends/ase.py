"""ASE backend adapter boundary."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.backends.base import FilesystemBackendAdapter


class AseBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for ASE-managed calculation setup and parsing."""

    name = "ase"


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
    "AseBackendAdapter",
    "require_ase",
    "require_xtb",
    "require_gaussian_calculator",
    "import_ase_bits",
]
