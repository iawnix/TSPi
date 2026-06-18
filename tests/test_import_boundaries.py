"""Static dependency guards for the target refactor architecture."""

from __future__ import annotations

import ast
import importlib
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

TOOLS_CORE_COMPATIBILITY_SHIMS = {
    PACKAGE / "tools" / "ase_neb" / "node_writers.py",
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
            if layer == "tools" and source_file in TOOLS_CORE_COMPATIBILITY_SHIMS:
                bad = [item for item in bad if item != "core"]
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


def test_legacy_tool_package_is_removed_and_unimported() -> None:
    assert not (PACKAGE / "tool").exists()
    offenders: list[str] = []
    for root in (PACKAGE, ROOT / "tests", ROOT / "scripts"):
        for source_file in sorted(root.rglob("*.py")):
            bad = sorted(
                name
                for name in full_internal_imports(source_file)
                if name == "transition_state_workflow.tool" or name.startswith("transition_state_workflow.tool.")
            )
            if bad:
                offenders.append(f"{source_file.relative_to(ROOT)} imports {', '.join(bad)}")
    assert not offenders, "legacy tool package imports remain:\n" + "\n".join(offenders)


def test_public_scripts_do_not_import_legacy_tool_package() -> None:
    offenders: list[str] = []
    for source_file in sorted((ROOT / "scripts").glob("*.py")):
        bad = sorted(
            name
            for name in full_internal_imports(source_file)
            if name == "transition_state_workflow.tool" or name.startswith("transition_state_workflow.tool.")
        )
        if bad:
            offenders.append(f"{source_file.relative_to(ROOT)} imports {', '.join(bad)}")
    assert not offenders, "public scripts import legacy tool package:\n" + "\n".join(offenders)


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


def test_no_runtime_pep585_builtin_type_aliases_for_compute_python38() -> None:
    offenders: list[str] = []
    builtin_aliases = {"tuple", "list", "dict", "set"}
    for source_file in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name) and value.value.id in builtin_aliases:
                offenders.append(
                    f"{source_file.relative_to(ROOT)}:{node.lineno} uses runtime PEP585 alias {value.value.id}[...]"
                )
    assert not offenders, "runtime type aliases must stay Python 3.8-compatible:\n" + "\n".join(offenders)


def test_connectivity_checker_lives_in_gate_without_tool_compatibility() -> None:
    from transition_state_workflow.gate import connectivity

    assert connectivity.main is not None
    assert connectivity.build_parser is not None
    script_source = (ROOT / "scripts" / "rmsd_connectivity_check.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.gate.connectivity import main" in script_source
    assert "transition_state_workflow.tool." not in script_source


def test_descriptor_extractor_lives_in_tools_without_tool_compatibility() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.tools import descriptors

    assert descriptors.main is not None
    assert descriptors.parse_freq_metadata is gaussian.parse_freq_metadata
    assert descriptors.parse_imaginary_vectors is gaussian.parse_imaginary_vectors
    assert descriptors.parse_charge_table is gaussian.parse_charge_table
    script_source = (ROOT / "scripts" / "ts_descriptor_extract.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.tools.descriptors import main" in script_source
    assert "transition_state_workflow.tool." not in script_source


def test_node_exec_cli_lives_in_cli_without_tool_compatibility() -> None:
    from transition_state_workflow.cli import node_exec
    from transition_state_workflow.tools import node_exec as tool_node_exec

    assert node_exec.NodeExecutionRequest is tool_node_exec.NodeExecutionRequest
    assert node_exec.dry_run_payload is tool_node_exec.dry_run_payload
    assert node_exec.render_command is tool_node_exec.render_command
    assert node_exec.run_node_command is tool_node_exec.run_node_command

    assert not (PACKAGE / "tool" / "node_exec.py").exists()
    try:
        importlib.import_module("transition_state_workflow.tool.node_exec")
    except ModuleNotFoundError:
        pass
    else:  # pragma: no cover - assertion message is the point of this branch.
        raise AssertionError("legacy tool.node_exec import path should be removed")

    script_source = (ROOT / "scripts" / "ts_node_exec.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.cli.node_exec import main" in script_source
    assert "transition_state_workflow.tool.node_exec" not in script_source


def test_workspace_validator_lives_in_gate_package_without_tool_compatibility() -> None:
    from transition_state_workflow.gate import validate

    assert validate.validate_ts_workspace_contract is not None
    assert validate.main is not None

    validate_package = PACKAGE / "gate" / "validate"
    assert validate_package.is_dir()
    assert not (PACKAGE / "gate" / "validate.py").exists()
    for expected_module in (
        "__init__.py",
        "__main__.py",
        "artifacts.py",
        "cli.py",
        "common.py",
        "contracts.py",
        "evidence.py",
        "events.py",
        "finalization.py",
        "io.py",
        "mechanism.py",
        "nodes.py",
        "pathway.py",
        "tree.py",
        "workspace.py",
    ):
        assert (validate_package / expected_module).is_file()

    forbidden = {
        "transition_state_workflow.backends",
        "transition_state_workflow.cli",
        "transition_state_workflow.core",
        "transition_state_workflow.remote",
        "transition_state_workflow.tool",
        "transition_state_workflow.tools",
        "transition_state_workflow.web",
    }
    offenders: list[str] = []
    for source_file in sorted(validate_package.rglob("*.py")):
        bad = sorted(
            name
            for name in full_internal_imports(source_file)
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
        )
        if bad:
            offenders.append(f"{source_file.relative_to(ROOT)} imports {', '.join(bad)}")
    assert not offenders, "validator package reverse imports:\n" + "\n".join(offenders)

    script_source = (ROOT / "scripts" / "ts_validate_workspace.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.gate.validate import main" in script_source


def test_hypothesis_workspace_cli_lives_in_cli_without_tool_compatibility() -> None:
    from transition_state_workflow.cli import hypothesis_workspace
    from transition_state_workflow.cli import workspace_control

    assert hypothesis_workspace.main is not None
    assert hypothesis_workspace.build_parser is not None
    assert hypothesis_workspace.initialize_ts_hypothesis_workspace_from_cli_args is not None
    assert workspace_control.build_workspace_report_payload is not None
    assert workspace_control.validate_decision_payload is not None
    assert not (PACKAGE / "core" / "workspace_control.py").exists()

    parser = hypothesis_workspace.build_parser()
    assert set(parser._subparsers._actions[-1].choices) == {
        "init_workspace",
        "start_node",
        "end_node",
        "report_workspace",
        "validate_decision",
    }
    script_source = (ROOT / "scripts" / "ts_workspace.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.cli.hypothesis_workspace import main" in script_source

    plan_next_package = PACKAGE / "core" / "plan_next"
    assert plan_next_package.is_dir()
    assert not (PACKAGE / "core" / "plan_next.py").exists()
    for expected_module in (
        "__init__.py",
        "contracts.py",
        "loader.py",
        "packet.py",
        "pathway.py",
        "phase.py",
        "snapshot.py",
        "suggestions.py",
        "context.py",
        "ids.py",
    ):
        assert (plan_next_package / expected_module).is_file()

    cli_imports = full_internal_imports(PACKAGE / "cli" / "hypothesis_workspace.py")
    assert "transition_state_workflow.tool" not in {
        name.split(".", 2)[0] + "." + name.split(".", 2)[1]
        for name in cli_imports
        if name.startswith("transition_state_workflow.")
    }

    script_source = (ROOT / "scripts" / "ts_hypothesis_workspace.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.cli.hypothesis_workspace import main" in script_source
    assert "transition_state_workflow.tool.hypothesis_workspace import main" not in script_source


def test_gaussian_cli_helpers_live_in_cli_and_backend_without_tool_compatibility() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.cli import gaussian_gen_preflight
    from transition_state_workflow.cli import parse_gaussian_ts_result
    from transition_state_workflow.cli import prepare_gaussian_ts_input

    assert gaussian_gen_preflight.route_indices is gaussian.route_indices
    assert gaussian_gen_preflight.split_tail is gaussian.split_tail
    assert gaussian_gen_preflight.link0_end is gaussian.link0_end
    assert gaussian_gen_preflight.warnings_for is gaussian.warnings_for
    assert gaussian_gen_preflight.fix_lines is gaussian.fix_lines
    assert parse_gaussian_ts_result.parse_log is not gaussian.parse_gaussian_tsfreq_log
    assert parse_gaussian_ts_result.parse_frequencies is gaussian.parse_gaussian_frequencies
    assert prepare_gaussian_ts_input.read_xyz_frame is gaussian.read_xyz_frame
    assert prepare_gaussian_ts_input.write_gaussian_input is gaussian.write_gaussian_input

    removed_modules = (
        "transition_state_workflow.tool.gaussian_gen_preflight",
        "transition_state_workflow.tool.parse_gaussian_ts_result",
        "transition_state_workflow.tool.prepare_gaussian_ts_input",
    )
    for module_name in removed_modules:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            pass
        else:  # pragma: no cover - assertion message is the point of this branch.
            raise AssertionError(f"legacy {module_name} import path should be removed")

    for module_path in (
        PACKAGE / "tool" / "gaussian_gen_preflight.py",
        PACKAGE / "tool" / "parse_gaussian_ts_result.py",
        PACKAGE / "tool" / "prepare_gaussian_ts_input.py",
    ):
        assert not module_path.exists()

    expected_script_imports = {
        "scripts/gaussian_gen_preflight.py": "transition_state_workflow.cli.gaussian_gen_preflight import main",
        "scripts/parse_gaussian_ts_result.py": "transition_state_workflow.cli.parse_gaussian_ts_result import main",
        "scripts/prepare_gaussian_ts_input.py": "transition_state_workflow.cli.prepare_gaussian_ts_input import main",
    }
    for script, expected_import in expected_script_imports.items():
        script_source = (ROOT / script).read_text(encoding="utf-8")
        assert expected_import in script_source
        assert "transition_state_workflow.tool." not in script_source


def test_ase_neb_legacy_tool_import_paths_are_removed() -> None:
    removed_paths = (
        PACKAGE / "tool" / "ase_neb" / "__init__.py",
        PACKAGE / "tool" / "ase_neb" / "coerce.py",
        PACKAGE / "tool" / "ase_neb" / "config.py",
        PACKAGE / "tool" / "ase_neb" / "constants.py",
        PACKAGE / "tool" / "ase_neb" / "driver.py",
        PACKAGE / "tool" / "ase_neb" / "errors.py",
        PACKAGE / "tool" / "ase_neb" / "external_gaussian.py",
        PACKAGE / "tool" / "ase_neb" / "gaussian_calc.py",
        PACKAGE / "tool" / "ase_neb" / "geometry.py",
        PACKAGE / "tool" / "ase_neb" / "images.py",
        PACKAGE / "tool" / "ase_neb" / "mechanism.py",
        PACKAGE / "tool" / "ase_neb" / "node_writers.py",
        PACKAGE / "tool" / "ase_neb" / "validation.py",
        PACKAGE / "tool" / "ase_neb" / "workflow.py",
        PACKAGE / "tool" / "ase_neb_framework.py",
    )
    for path in removed_paths:
        assert not path.exists()

    old_prefixes = (
        "transition_state_workflow.tool.ase_neb",
        "transition_state_workflow.tool.ase_neb_framework",
    )
    offenders: list[str] = []
    for source_file in sorted(list(PACKAGE.rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))):
        imports = full_internal_imports(source_file)
        bad = [
            name
            for name in imports
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in old_prefixes)
        ]
        if bad:
            offenders.append(f"{source_file.relative_to(ROOT)} imports {', '.join(sorted(bad))}")
    assert not offenders, "removed ASE NEB tool paths are still imported:\n" + "\n".join(offenders)


def test_ase_neb_leaf_helpers_live_in_tools() -> None:
    from transition_state_workflow.tools.ase_neb import coerce, constants, errors

    assert errors.ConfigError is not None
    assert coerce.as_mapping is not None
    assert coerce.as_positive_int is not None
    assert constants.CONFIG_VERSION is not None


def test_ase_neb_geometry_mechanism_live_in_tools() -> None:
    from transition_state_workflow.chem import geometry as chem_geometry
    from transition_state_workflow.chem import mechanism as chem_mechanism
    from transition_state_workflow.tools.ase_neb import geometry, mechanism

    assert geometry.changed_bonds is chem_geometry.changed_bonds
    assert geometry.bonded_pairs is chem_geometry.bonded_pairs
    assert geometry.infer_angles is chem_geometry.infer_angles
    assert geometry.fragment_labels is chem_geometry.fragment_labels
    assert mechanism.classify_validation_system is chem_mechanism.classify_validation_system
    assert mechanism.ENDPOINT_READY_STATES is chem_mechanism.ENDPOINT_READY_STATES


def test_ase_runtime_loader_lives_in_backend() -> None:
    from transition_state_workflow.backends import ase

    assert ase.require_ase is not None
    assert ase.require_xtb is not None
    assert ase.require_gaussian_calculator is not None
    assert ase.import_ase_bits is not None


def test_ase_neb_images_live_in_backend() -> None:
    from transition_state_workflow.backends import ase_neb
    from transition_state_workflow.tools.ase_neb import images

    assert images.load_endpoint_images is ase_neb.load_endpoint_images
    assert images.build_images_from_endpoints is ase_neb.build_images_from_endpoints
    assert images.write_image_set is ase_neb.write_image_set
    assert images.read_xyz_images_from_dir is ase_neb.read_xyz_images_from_dir
    assert len((PACKAGE / "tools" / "ase_neb" / "images.py").read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_neb_config_lives_in_tools() -> None:
    from transition_state_workflow.tools.ase_neb import config

    assert config.ProjectContext is not None
    assert config.safe_slug is not None
    assert config.normalize_config is not None
    assert config.resolve_config_paths is not None
    assert config.validate_config is not None
    assert config.neb_node_id is not None


def test_workspace_primitives_live_in_core_workspace_without_ase_neb_compatibility() -> None:
    from transition_state_workflow.core import workspace

    assert workspace.BranchReferenceError is not None
    assert workspace.clean_optional_node_ref is not None
    assert workspace.normalize_branch_input_refs is not None
    assert workspace.parent_graph_would_cycle is not None
    assert workspace.validate_branch_references is not None
    assert workspace.write_prepared_branch_state is not None
    assert workspace.prepared_branch_node_payload is not None
    assert workspace.prepared_branch_tree_entry is not None
    assert workspace.prepared_branch_event is not None
    assert workspace.next_branch_event_id is not None
    assert workspace.write_json is not None
    assert workspace.node_record is not None
    assert workspace.read_tree is not None
    assert workspace.append_evidence_record is not None
    assert workspace.append_portable_evidence_record is not None
    assert workspace.write_text_file_if_allowed is not None
    assert workspace.ensure_workspace_directories is not None
    assert workspace.ensure_tree_skeleton is not None
    assert workspace.ensure_workspace_root_has_manifest_and_tree is not None
    assert workspace.finalize_node_report_and_tree is not None
    assert workspace.initial_evidence_registry is not None
    assert workspace.initial_workspace_manifest is not None
    assert workspace.initial_workspace_tree is not None
    assert workspace.write_initial_workspace_files is not None

    workspace_package = PACKAGE / "core" / "workspace"
    assert workspace_package.is_dir()
    for expected_module in (
        "__init__.py",
        "branch.py",
        "evidence.py",
        "io.py",
        "naming.py",
        "nodes.py",
        "references.py",
        "scaffold.py",
        "tree.py",
    ):
        assert (workspace_package / expected_module).is_file()

    removed_modules = (
        PACKAGE / "core" / "ase_neb_workspace.py",
        PACKAGE / "tools" / "ase_neb" / "workspace.py",
        PACKAGE / "tool" / "ase_neb" / "workspace.py",
    )
    for path in removed_modules:
        assert not path.exists()

    old_import = "transition_state_workflow.core.ase_neb_workspace"
    offenders = [
        str(path.relative_to(ROOT))
        for path in PACKAGE.rglob("*.py")
        if old_import in path.read_text(encoding="utf-8")
    ]
    assert not offenders


def test_ase_neb_node_writers_live_in_core_with_tools_adapter() -> None:
    from transition_state_workflow.core import ase_neb_nodes as core_nodes
    from transition_state_workflow.tools.ase_neb import node_writers

    assert node_writers.write_input_check_node is core_nodes.write_input_check_node
    assert node_writers.write_neb_node_metadata is core_nodes.write_neb_node_metadata
    adapter_source = PACKAGE / "tools" / "ase_neb" / "node_writers.py"
    assert len(adapter_source.read_text(encoding="utf-8").splitlines()) <= 4


def test_neb_candidate_policy_lives_in_gate_with_cli_adapter() -> None:
    from transition_state_workflow.cli import ase_neb_validation
    from transition_state_workflow.gate import neb_candidate

    assert ase_neb_validation.displacement_ladder is neb_candidate.displacement_ladder
    assert ase_neb_validation.threshold_policy is neb_candidate.threshold_policy
    assert ase_neb_validation.irc_policy is neb_candidate.irc_policy

    gate_imports = full_internal_imports(PACKAGE / "gate" / "neb_candidate.py")
    forbidden = {
        "transition_state_workflow.backends",
        "transition_state_workflow.core",
        "transition_state_workflow.remote",
        "transition_state_workflow.tool",
        "transition_state_workflow.tools",
        "transition_state_workflow.web",
    }
    assert not [
        name
        for name in gate_imports
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    ]


def test_ase_neb_refinement_input_rendering_lives_in_gaussian_backend() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.cli import ase_neb_validation

    assert ase_neb_validation.gaussian_refinement_defaults() == gaussian.gaussian_refinement_defaults()

    validation_imports = full_internal_imports(PACKAGE / "cli" / "ase_neb_validation.py")
    assert "transition_state_workflow.tools.ase_neb.geometry" not in validation_imports
    assert "transition_state_workflow.backends.gaussian" in validation_imports


def test_ase_neb_validation_state_writers_live_in_core_with_cli_adapter() -> None:
    from transition_state_workflow.cli import ase_neb_validation
    from transition_state_workflow.core import ase_neb_validation as core_validation

    assert ase_neb_validation.find_project_input is core_validation.find_project_input
    assert ase_neb_validation.latest_promotable_candidate is core_validation.latest_promotable_candidate
    assert ase_neb_validation.latest_node_with_stage is core_validation.latest_node_with_stage
    assert ase_neb_validation.create_validation_plan_node is core_validation.create_validation_plan_node

    core_imports = full_internal_imports(PACKAGE / "core" / "ase_neb_validation.py")
    forbidden = {
        "transition_state_workflow.backends",
        "transition_state_workflow.gate",
        "transition_state_workflow.remote",
        "transition_state_workflow.tool",
        "transition_state_workflow.tools",
        "transition_state_workflow.web",
    }
    assert not [
        name
        for name in core_imports
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    ]

    validation_source = (PACKAGE / "cli" / "ase_neb_validation.py").read_text(encoding="utf-8")
    for moved_detail in (
        "json.loads",
        "shutil.copyfile",
        "read_tree(",
        "node_record(",
        "upsert_tree_node(",
        "write_markdown(",
        "write_reflection_template(",
    ):
        assert moved_detail not in validation_source


def test_imaginary_mode_follow_split_across_backend_gate_core() -> None:
    from transition_state_workflow.backends import gaussian
    from transition_state_workflow.cli import imaginary_mode_follow
    from transition_state_workflow.core import imaginary_mode_follow as core_follow
    from transition_state_workflow.gate import connectivity

    assert imaginary_mode_follow.endpoint_template_from_gjf is gaussian.endpoint_template_from_gjf
    assert imaginary_mode_follow.resolve_output_layout is core_follow.resolve_output_layout
    assert imaginary_mode_follow.write_prepare_artifacts is core_follow.write_prepare_artifacts
    assert imaginary_mode_follow.endpoint_connection_screen is connectivity.endpoint_connection_screen
    assert imaginary_mode_follow.irc_connection_screen is connectivity.irc_connection_screen

    for source_file, forbidden in (
        (
            PACKAGE / "backends" / "gaussian.py",
            {
                "transition_state_workflow.core",
                "transition_state_workflow.gate",
                "transition_state_workflow.tool",
                "transition_state_workflow.tools",
            },
        ),
        (
            PACKAGE / "gate" / "connectivity.py",
            {
                "transition_state_workflow.backends",
                "transition_state_workflow.core",
                "transition_state_workflow.tool",
                "transition_state_workflow.tools",
            },
        ),
        (
            PACKAGE / "core" / "imaginary_mode_follow.py",
            {
                "transition_state_workflow.backends",
                "transition_state_workflow.gate",
                "transition_state_workflow.remote",
                "transition_state_workflow.tool",
                "transition_state_workflow.tools",
                "transition_state_workflow.web",
            },
        ),
    ):
        imports = full_internal_imports(source_file)
        assert not [
            name
            for name in imports
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
        ]

    assert not (PACKAGE / "tool" / "imaginary_mode_follow.py").exists()
    try:
        importlib.import_module("transition_state_workflow.tool.imaginary_mode_follow")
    except ModuleNotFoundError:
        pass
    else:  # pragma: no cover - assertion message is the point of this branch.
        raise AssertionError("legacy tool.imaginary_mode_follow import path should be removed")

    script_source = (ROOT / "scripts" / "ts_imaginary_mode_follow.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.cli.imaginary_mode_follow import main" in script_source
    assert "transition_state_workflow.tool.imaginary_mode_follow" not in script_source


def test_ase_neb_external_state_writers_live_in_core_with_cli_adapter() -> None:
    from transition_state_workflow.cli import ase_neb_external
    from transition_state_workflow.core import ase_neb_external as core_external

    assert ase_neb_external.external_gaussian_level_slug is core_external.external_gaussian_level_slug
    assert ase_neb_external.continue_node_id_from_images is core_external.continue_node_id_from_images
    assert ase_neb_external.ensure_external_gaussian_project is core_external.ensure_external_gaussian_project
    assert ase_neb_external.write_external_image_input_node is core_external.write_external_image_input_node
    assert ase_neb_external.write_external_gaussian_neb_node is core_external.write_external_gaussian_neb_node

    core_imports = full_internal_imports(PACKAGE / "core" / "ase_neb_external.py")
    forbidden = {
        "transition_state_workflow.backends",
        "transition_state_workflow.gate",
        "transition_state_workflow.remote",
        "transition_state_workflow.tool",
        "transition_state_workflow.tools",
        "transition_state_workflow.web",
    }
    assert not [
        name
        for name in core_imports
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    ]
    cli_imports = full_internal_imports(PACKAGE / "cli" / "ase_neb_external.py")
    assert "transition_state_workflow.core.ase_neb_workspace" not in cli_imports


def test_ase_neb_execution_lives_in_backend_with_tools_adapters() -> None:
    from transition_state_workflow.backends import ase_neb
    from transition_state_workflow.tools.ase_neb import results

    assert ase_neb.AseNebPreparationResult is not None
    assert ase_neb.prepare_ase_neb_initial_path is not None
    assert ase_neb.AseNebRuntimeRequest is not None
    assert ase_neb.run_ase_neb_candidate_path is not None
    assert ase_neb.ExternalGaussianCalculatorRequest is not None
    assert ase_neb.ExternalGaussianNebRuntimeRequest is not None
    assert ase_neb.create_calculator is not None
    assert ase_neb.ExternalGaussianForceCalculator is not None
    assert ase_neb.make_neb_object is not None
    assert ase_neb.attach_calculators is not None
    assert ase_neb.evaluate_neb_candidate_quality is not None
    assert ase_neb.force_max is not None
    assert results.collect_path_data is ase_neb.collect_path_data
    assert results.write_forces_table is ase_neb.write_forces_table
    assert results.write_path_summary is ase_neb.write_path_summary
    assert results.write_candidate_quality_artifacts is ase_neb.write_candidate_quality_artifacts

    forbidden = {
        "transition_state_workflow.cli",
        "transition_state_workflow.core",
        "transition_state_workflow.gate",
        "transition_state_workflow.remote",
        "transition_state_workflow.tool",
        "transition_state_workflow.tools",
        "transition_state_workflow.web",
    }
    backend_package = PACKAGE / "backends" / "ase_neb"
    assert backend_package.is_dir()
    for expected_module in (
        "__init__.py",
        "contracts.py",
        "images.py",
        "gaussian_external.py",
        "results.py",
        "runtime.py",
    ):
        assert (backend_package / expected_module).is_file()
    backend_offenders: list[str] = []
    for source_file in sorted(backend_package.rglob("*.py")):
        backend_imports = full_internal_imports(source_file)
        bad = sorted(
            name
            for name in backend_imports
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
        )
        if bad:
            backend_offenders.append(f"{source_file.relative_to(ROOT)} imports {', '.join(bad)}")
    assert not backend_offenders, "ASE NEB backend package reverse imports:\n" + "\n".join(backend_offenders)

    result_imports = full_internal_imports(PACKAGE / "tools" / "ase_neb" / "results.py")
    assert "transition_state_workflow.tools.ase_neb.workspace" not in result_imports
    assert "transition_state_workflow.tools.ase_neb.node_writers" not in result_imports

    workflow_source = (PACKAGE / "cli" / "ase_neb_workflow.py").read_text(encoding="utf-8")
    for runtime_detail in (
        "import_ase_bits",
        "attach_calculators",
        "make_neb_object",
        "temporary_env",
        "load_endpoint_images",
        "build_images_from_endpoints",
        "write_image_set",
        "write_path_summary",
        "write_candidate_quality_artifacts",
    ):
        assert runtime_detail not in workflow_source

    assert len((PACKAGE / "tools" / "ase_neb" / "results.py").read_text(encoding="utf-8").splitlines()) <= 4


def test_ase_neb_framework_cli_lives_in_cli_without_tool_compatibility() -> None:
    from transition_state_workflow.cli import ase_neb_framework as cli_framework
    from transition_state_workflow.cli import ase_neb_workflow

    assert cli_framework.prepare is ase_neb_workflow.prepare
    assert cli_framework.run_neb is ase_neb_workflow.run_neb
    assert cli_framework.load_config_for_cli is ase_neb_workflow.load_config_for_cli
    assert cli_framework.make_gaussian_refine_from_cli is ase_neb_workflow.make_gaussian_refine_from_cli
    assert cli_framework.evaluate_neb_candidate_quality is ase_neb_workflow.evaluate_neb_candidate_quality

    cli_source = PACKAGE / "cli" / "ase_neb_framework.py"
    cli_imports = full_internal_imports(cli_source)
    assert "transition_state_workflow.cli.ase_neb_workflow" in cli_imports
    assert not any(
        name == "transition_state_workflow.tool" or name.startswith("transition_state_workflow.tool.")
        for name in cli_imports
    )

    script_source = (ROOT / "scripts" / "ase_neb_framework.py").read_text(encoding="utf-8")
    assert "transition_state_workflow.cli.ase_neb_framework import main" in script_source
    assert "transition_state_workflow.tool.ase_neb_framework import main" not in script_source

    assert not (PACKAGE / "tool" / "ase_neb_framework.py").exists()
