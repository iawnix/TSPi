"""Public facade for ASE-managed NEB backend primitives.

The implementation is split by backend responsibility, but this package keeps
the historical ``transition_state_workflow.backends.ase_neb`` import surface
stable for CLI adapters and compatibility shims.
"""

from __future__ import annotations

from transition_state_workflow.backends.ase import (
    import_ase_bits,
    require_ase,
    require_gaussian_calculator,
    require_xtb,
)
from transition_state_workflow.backends.gaussian import (
    parse_gaussian_energy_hartree,
    parse_gaussian_forces_hartree_per_bohr,
)

from .contracts import (
    BOHR_TO_ANG,
    HARTREE_PER_BOHR_TO_EV_PER_ANG,
    HARTREE_TO_EV,
    AseNebCandidateArtifact,
    AseNebConfigError,
    AseNebPathArtifacts,
    AseNebPreparationResult,
    AseNebRuntimeRequest,
    ExternalGaussianCalculatorRequest,
    ExternalGaussianNebRuntimeRequest,
)
from .gaussian_external import (
    ExternalGaussianForceCalculator,
    extract_gaussian_tail_from_template,
    require_external_gaussian_force_route,
    write_external_gaussian_dry_run_input,
)
from .images import (
    build_images,
    build_images_from_endpoints,
    check_image_consistency,
    load_endpoint_images,
    natural_path_key,
    prepare_ase_neb_initial_path,
    read_image_set,
    read_xyz_images_from_dir,
    write_image_set,
)
from .results import (
    collect_path_data,
    evaluate_neb_candidate_quality,
    force_max,
    write_candidate_quality_artifacts,
    write_forces_table,
    write_json_artifact,
    write_path_summary,
)
from .runtime import (
    attach_calculators,
    create_calculator,
    make_neb_object,
    run_ase_neb_candidate_path,
    run_external_gaussian_neb_continuation,
    temporary_env,
)

__all__ = [
    "AseNebConfigError",
    "HARTREE_TO_EV",
    "BOHR_TO_ANG",
    "HARTREE_PER_BOHR_TO_EV_PER_ANG",
    "require_ase",
    "require_xtb",
    "require_gaussian_calculator",
    "import_ase_bits",
    "parse_gaussian_energy_hartree",
    "parse_gaussian_forces_hartree_per_bohr",
    "extract_gaussian_tail_from_template",
    "require_external_gaussian_force_route",
    "AseNebRuntimeRequest",
    "AseNebPreparationResult",
    "ExternalGaussianCalculatorRequest",
    "ExternalGaussianNebRuntimeRequest",
    "ExternalGaussianForceCalculator",
    "create_calculator",
    "temporary_env",
    "load_endpoint_images",
    "build_images_from_endpoints",
    "build_images",
    "write_image_set",
    "prepare_ase_neb_initial_path",
    "read_image_set",
    "natural_path_key",
    "check_image_consistency",
    "read_xyz_images_from_dir",
    "write_external_gaussian_dry_run_input",
    "AseNebCandidateArtifact",
    "AseNebPathArtifacts",
    "force_max",
    "collect_path_data",
    "write_json_artifact",
    "write_forces_table",
    "write_path_summary",
    "write_candidate_quality_artifacts",
    "make_neb_object",
    "attach_calculators",
    "evaluate_neb_candidate_quality",
    "run_ase_neb_candidate_path",
    "run_external_gaussian_neb_continuation",
]
