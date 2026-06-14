"""Static dependency guards for the target refactor architecture."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "transition_state_workflow"

FORBIDDEN_INTERNAL_IMPORTS = {
    "base": {"backends", "cli", "core", "gate", "remote", "tool", "tools", "web"},
    "backends": {"cli", "core", "gate", "remote", "tool", "tools", "web"},
    "core": {"backends", "cli", "gate", "remote", "tool", "tools", "web"},
    "gate": {"cli", "core", "remote", "tools", "web"},
    "remote": {"backends", "cli", "core", "gate", "tool", "tools", "web"},
    "tools": {"cli", "core", "gate", "tool", "web"},
    "web": {"cli", "remote", "tools"},
}

FORBIDDEN_WEB_TOOL_MODULES = {
    "transition_state_workflow.tool.ase_neb",
    "transition_state_workflow.tool.ase_neb_framework",
    "transition_state_workflow.tool.gaussian_gen_preflight",
    "transition_state_workflow.tool.imaginary_mode_follow",
    "transition_state_workflow.tool.node_exec",
    "transition_state_workflow.tool.prepare_gaussian_ts_input",
    "transition_state_workflow.tool.remote_gaussian_monitor",
    "transition_state_workflow.tool.rmsd_connectivity_check",
    "transition_state_workflow.tool.run_remote_gaussian",
    "transition_state_workflow.tool.ts_descriptor_extract",
    "transition_state_workflow.tool.validate_workspace",
    "transition_state_workflow.tool.finalize_node",
    "transition_state_workflow.tool.plan_next",
    "transition_state_workflow.tool.record_backtrack",
    "transition_state_workflow.tool.start_node",
}


def internal_imports(source_file: Path) -> set[str]:
    """Return imported top-level transition_state_workflow package names."""

    imported: set[str] = set()
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            prefix = "transition_state_workflow."
            if name.startswith(prefix):
                imported.add(name.removeprefix(prefix).split(".", 1)[0])
    return imported


def full_internal_imports(source_file: Path) -> set[str]:
    """Return full transition_state_workflow import module names."""

    imported: set[str] = set()
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.startswith("transition_state_workflow."):
                imported.add(name)
    return imported


def raw_cli_output_violations(source_file: Path) -> list[str]:
    """Return direct stdout/stderr writes that bypass util.cli."""

    violations: list[str] = []
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            violations.append(f"{source_file.relative_to(ROOT)}:{node.lineno} uses print()")
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"write", "flush"}:
            continue
        value = node.func.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr in {"stdout", "stderr"}
            and isinstance(value.value, ast.Name)
            and value.value.id == "sys"
        ):
            violations.append(
                f"{source_file.relative_to(ROOT)}:{node.lineno} writes sys.{value.attr}.{node.func.attr}()"
            )
    return violations


def test_target_architecture_has_no_reverse_dependencies() -> None:
    violations: list[str] = []
    for layer, forbidden in FORBIDDEN_INTERNAL_IMPORTS.items():
        layer_root = PACKAGE / layer
        if not layer_root.exists():
            continue
        for source_file in sorted(layer_root.rglob("*.py")):
            bad = sorted(internal_imports(source_file) & forbidden)
            if bad:
                violations.append(f"{source_file.relative_to(ROOT)} imports forbidden layers: {', '.join(bad)}")
    assert not violations, "reverse architecture dependencies:\n" + "\n".join(violations)


def test_chem_layer_has_no_tool_or_runtime_boundary_dependencies() -> None:
    forbidden = {"backends", "cli", "core", "gate", "remote", "tool", "tools", "web"}
    offenders: list[str] = []
    for source_file in sorted((PACKAGE / "chem").rglob("*.py")):
        bad = sorted(internal_imports(source_file) & forbidden)
        if bad:
            offenders.append(f"{source_file.relative_to(ROOT)} imports forbidden layers: {', '.join(bad)}")
    assert not offenders, "chem layer imports non-chem boundaries:\n" + "\n".join(offenders)


def test_legacy_tool_package_is_not_imported_by_non_web_new_architecture_layers() -> None:
    offenders: list[str] = []
    for layer in ("backends", "cli", "core", "gate", "remote", "tools"):
        layer_root = PACKAGE / layer
        if not layer_root.exists():
            continue
        for source_file in sorted(layer_root.rglob("*.py")):
            if "tool" in internal_imports(source_file):
                offenders.append(str(source_file.relative_to(ROOT)))
    assert not offenders, "new architecture layers import legacy tool package:\n" + "\n".join(offenders)


def test_web_boundary_does_not_import_job_execution_modules() -> None:
    offenders: list[str] = []
    web_root = PACKAGE / "web"
    for source_file in sorted(web_root.rglob("*.py")):
        bad = sorted(full_internal_imports(source_file) & FORBIDDEN_WEB_TOOL_MODULES)
        if bad:
            offenders.append(f"{source_file.relative_to(ROOT)} imports job modules: {', '.join(bad)}")
    assert not offenders, "web boundary imports job execution modules:\n" + "\n".join(offenders)


def test_remote_and_web_cli_output_goes_through_util_cli() -> None:
    offenders: list[str] = []
    for layer in ("remote", "web"):
        for source_file in sorted((PACKAGE / layer).rglob("*.py")):
            offenders.extend(raw_cli_output_violations(source_file))
    assert not offenders, "remote/web bypass util.cli output helpers:\n" + "\n".join(offenders)


def test_connectivity_checker_lives_in_gate_with_tool_compatibility() -> None:
    from transition_state_workflow.gate import connectivity
    from transition_state_workflow.tool import rmsd_connectivity_check

    assert rmsd_connectivity_check.main is connectivity.main
    assert rmsd_connectivity_check.build_parser is connectivity.build_parser
    compat_source = PACKAGE / "tool" / "rmsd_connectivity_check.py"
    assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 6


def test_descriptor_extractor_lives_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.tool import ts_descriptor_extract
    from transition_state_workflow.tools import descriptors

    assert ts_descriptor_extract.main is descriptors.main
    assert descriptors.parse_freq_metadata is gaussian.parse_freq_metadata
    assert descriptors.parse_imaginary_vectors is gaussian.parse_imaginary_vectors
    assert descriptors.parse_charge_table is gaussian.parse_charge_table
    assert ts_descriptor_extract.parse_freq_metadata is gaussian.parse_freq_metadata
    assert ts_descriptor_extract.parse_imaginary_vectors is gaussian.parse_imaginary_vectors
    compat_source = PACKAGE / "tool" / "ts_descriptor_extract.py"
    assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 6


def test_gaussian_gen_preflight_helpers_live_in_backend_with_tool_compatibility() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.tool import gaussian_gen_preflight

    assert gaussian_gen_preflight.route_indices is gaussian.route_indices
    assert gaussian_gen_preflight.split_tail is gaussian.split_tail
    assert gaussian_gen_preflight.link0_end is gaussian.link0_end
    assert gaussian_gen_preflight.warnings_for is gaussian.warnings_for
    assert gaussian_gen_preflight.fix_lines is gaussian.fix_lines


def test_ase_neb_leaf_helpers_live_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.tool.ase_neb import coerce as old_coerce
    from transition_state_workflow.tool.ase_neb import constants as old_constants
    from transition_state_workflow.tool.ase_neb import errors as old_errors
    from transition_state_workflow.tools.ase_neb import coerce, constants, errors

    assert old_errors.ConfigError is errors.ConfigError
    assert old_coerce.as_mapping is coerce.as_mapping
    assert old_coerce.as_positive_int is coerce.as_positive_int
    assert old_constants.CONFIG_VERSION is constants.CONFIG_VERSION
    for name in ("constants.py", "errors.py", "coerce.py"):
        compat_source = PACKAGE / "tool" / "ase_neb" / name
        assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_neb_geometry_mechanism_live_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.chem import geometry as chem_geometry
    from transition_state_workflow.chem import mechanism as chem_mechanism
    from transition_state_workflow.tool.ase_neb import geometry as old_geometry
    from transition_state_workflow.tool.ase_neb import mechanism as old_mechanism
    from transition_state_workflow.tools.ase_neb import geometry, mechanism

    assert geometry.changed_bonds is chem_geometry.changed_bonds
    assert geometry.bonded_pairs is chem_geometry.bonded_pairs
    assert geometry.infer_angles is chem_geometry.infer_angles
    assert geometry.fragment_labels is chem_geometry.fragment_labels
    assert mechanism.classify_validation_system is chem_mechanism.classify_validation_system
    assert mechanism.ENDPOINT_READY_STATES is chem_mechanism.ENDPOINT_READY_STATES
    assert old_geometry.read_xyz is geometry.read_xyz
    assert old_geometry.changed_bonds is geometry.changed_bonds
    assert old_geometry.infer_angles is geometry.infer_angles
    assert old_mechanism.classify_validation_system is mechanism.classify_validation_system
    assert old_mechanism.endpoint_validation_summary is mechanism.endpoint_validation_summary
    assert old_mechanism.infer_mechanism_preflight is mechanism.infer_mechanism_preflight
    for name in ("geometry.py", "mechanism.py"):
        compat_source = PACKAGE / "tool" / "ase_neb" / name
        assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_runtime_loader_lives_in_backend_with_tool_compatibility() -> None:
    from transition_state_workflow.backends import ase
    from transition_state_workflow.tool.ase_neb import gaussian_calc

    assert gaussian_calc.require_ase is ase.require_ase
    assert gaussian_calc.require_xtb is ase.require_xtb
    assert gaussian_calc.require_gaussian_calculator is ase.require_gaussian_calculator
    assert gaussian_calc.import_ase_bits is ase.import_ase_bits


def test_ase_neb_images_live_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.tool.ase_neb import images as old_images
    from transition_state_workflow.tools.ase_neb import images

    assert old_images.load_endpoint_images is images.load_endpoint_images
    assert old_images.build_images_from_endpoints is images.build_images_from_endpoints
    assert old_images.write_image_set is images.write_image_set
    assert old_images.read_xyz_images_from_dir is images.read_xyz_images_from_dir
    compat_source = PACKAGE / "tool" / "ase_neb" / "images.py"
    assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_neb_config_lives_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.tool.ase_neb import config as old_config
    from transition_state_workflow.tools.ase_neb import config

    assert old_config.ProjectContext is config.ProjectContext
    assert old_config.safe_slug is config.safe_slug
    assert old_config.normalize_config is config.normalize_config
    assert old_config.resolve_config_paths is config.resolve_config_paths
    assert old_config.validate_config is config.validate_config
    assert old_config.neb_node_id is config.neb_node_id
    compat_source = PACKAGE / "tool" / "ase_neb" / "config.py"
    assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_neb_workspace_lives_in_tools_with_tool_compatibility() -> None:
    from transition_state_workflow.tool.ase_neb import workspace as old_workspace
    from transition_state_workflow.tools.ase_neb import workspace

    assert old_workspace.write_json is workspace.write_json
    assert old_workspace.node_record is workspace.node_record
    assert old_workspace.read_tree is workspace.read_tree
    assert old_workspace.append_evidence_record is workspace.append_evidence_record
    assert old_workspace.ensure_project_scaffold is workspace.ensure_project_scaffold
    assert old_workspace.finalize_node_report_and_tree is workspace.finalize_node_report_and_tree
    compat_source = PACKAGE / "tool" / "ase_neb" / "workspace.py"
    assert len(compat_source.read_text(encoding="utf-8").splitlines()) <= 4
