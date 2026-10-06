"""Chemistry extension implementation of the generic compute provider.

This is the only module that binds the generic compute lifecycle to Gaussian,
xTB, CREST, PySCF and ASE.  The research-compute package sees only the
protocol in ``research_compute.provider``.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from research_compute.provider import BackendTask, PreparedTask
from research_compute.artifact_registry import ArtifactOperationDescriptor
from tspi_foundation.path_safety import has_symlink_component
from chemical_capabilities import CAPABILITY_DESCRIPTORS


class ChemicalComputeProvider:
    provider_id = "chemical"
    domain_id = "chemical"
    backends = ("gaussian", "xtb", "crest", "ase_neb", "pyscf")
    structure_operations = ("create_mol_structure", "structure_compare", "mapping_validate")
    provider_version = "1"

    def supports(self, backend: str) -> bool:
        return backend in self.backends

    def readiness_probe(self, backend: str, binding: Any) -> dict[str, Any] | None:
        from chemical_readiness import readiness_probe
        return readiness_probe(backend, binding)

    def bridge_environment(self, backend: str, kind: str, environment: dict[str, str]) -> dict[str, str]:
        from chemical_readiness import bridge_environment
        return bridge_environment(backend, kind, environment)

    def bridge_readiness(self, backend: str, command: list[str], environment: dict[str, str], base: dict[str, Any]) -> dict[str, Any]:
        from chemical_readiness import bridge_readiness
        return bridge_readiness(backend, command, environment, base)

    def descriptors(self):
        return CAPABILITY_DESCRIPTORS

    def operations(self):
        """Return the extension's artifact capabilities through one registry."""
        broad_input = {"type": "object", "required": ["node_id"], "additionalProperties": True}
        broad_result = {"type": "object", "additionalProperties": True}
        return tuple(
            ArtifactOperationDescriptor(
                operation=name,
                version="1",
                input_schema=broad_input,
                parameter_schema={"type": "object", "additionalProperties": True},
                result_schema=broad_result,
                output_roles=("artifact",),
                provenance_schema={"type": "object", "additionalProperties": True},
            )
            for name in self.structure_operations
        )

    def artifact_import_formats(self) -> dict[str, frozenset[str]]:
        from chemical_import import IMPORT_FORMAT_SUFFIXES
        return dict(IMPORT_FORMAT_SUFFIXES)

    def artifact_input_roles(self, path: str) -> list[str]:
        from chemical_import import ROLE_SUFFIXES
        suffix = Path(path).suffix.lower()
        return sorted(role for role, suffixes in ROLE_SUFFIXES.items() if suffix in suffixes)

    def validate_artifact_import(self, artifact_format: str, content: str,
                                 charge: int | None, multiplicity: int | None) -> dict[str, Any]:
        from chemical_import import validate_import_content
        return validate_import_content(artifact_format, content, charge, multiplicity)

    def environment_providers(self, descriptor: Any, environment_kind: str) -> tuple[str, ...]:
        if descriptor.backend == "ase_neb" and environment_kind == "local":
            return ("ase_neb_xtb", "ase_neb")
        return (descriptor.backend,)

    def analysis_descriptors(self):
        from chemical_runtime.analysis.catalog import DESCRIPTORS
        return tuple(DESCRIPTORS)

    def validate_parsed_task(self, backend: str, task_type: str, facts: dict[str, Any]) -> dict[str, Any]:
        from chemical_validation import validate_parsed_task
        return validate_parsed_task(backend, task_type, facts)

    def parsed_program_outcome(self, backend: str, facts: dict[str, Any]) -> tuple[str, str | None]:
        from chemical_validation import parsed_program_outcome
        return parsed_program_outcome(backend, facts)

    def run_analysis(self, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        # Mapping validation has an artifact-backed result contract of its
        # own.  Adapt the generic analysis request into that contract at the
        # extension boundary; the generic research-compute package remains
        # unaware of chemistry-specific request shapes.
        if request.get("capability") == "reaction.mapping.validate":
            from chemical_artifacts import create_reaction_mapping_validation_artifact

            inputs = request["input_artifacts"]
            parameters = request["parameters"]
            return create_reaction_mapping_validation_artifact(root, {
                "schema_version": "ts-reaction-mapping-validate-request/1",
                "node_id": request["node_id"],
                "reactants": [{"artifact_id": artifact_id} for artifact_id in inputs["reactants"]],
                "products": [{"artifact_id": artifact_id} for artifact_id in inputs["products"]],
                "mapping": parameters["mapping"],
            })
        from chemical_runtime.analysis.engine import run_scientific_analysis
        return run_scientific_analysis(str(root), request)

    def validate_candidate(self, root: Path, artifact: dict[str, Any], node_id: str, candidate_id: str) -> dict[str, Any]:
        from chemical_analysis_candidates import load_analysis_candidate
        return load_analysis_candidate(root, artifact, node_id, candidate_id)

    def structure_operation(self, operation: str, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        from chemical_artifacts import (
            create_mol_structure_artifact,
            create_structure_comparison_artifact, create_reaction_mapping_validation_artifact,
        )
        handlers = {
            "create_mol_structure": create_mol_structure_artifact,
            "structure_compare": create_structure_comparison_artifact,
            "mapping_validate": create_reaction_mapping_validation_artifact,
        }
        try:
            return handlers[operation](root, request)
        except KeyError as exc:
            raise ValueError(f"unsupported chemical operation: {operation}") from exc

    def execute_operation(self, operation: str, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        """Canonical artifact registry execution hook."""
        return self.structure_operation(operation, root, request)

    def classify_task(self, workspace: Path, intent: dict[str, Any]) -> str:
        from chemical_runtime.backends.gaussian import read_gjf_route, route_settings
        import re
        backend = str(intent["backend"])
        if backend != "gaussian":
            return str(intent["task_type"])
        ref = intent.get("input_refs", {}).get("gjf")
        if not isinstance(ref, str):
            raise ValueError("Gaussian intent requires a gjf input")
        input_path = workspace / ref
        flags = route_settings(read_gjf_route(input_path))
        if flags.get("has_irc"):
            return "irc"
        if flags.get("has_scan"):
            return "scan"
        text = input_path.read_text(encoding="utf-8", errors="replace")
        if flags.get("has_opt") and re.search(r"(?im)^\s*[dabla]\s+(?:\d+\s+){2,4}s\s+\d+(?:\s|$)", text):
            return "scan"
        if flags.get("has_opt") and flags.get("has_freq"):
            return "opt_freq"
        if flags.get("has_opt"):
            return "ts" if flags.get("has_ts") or flags.get("has_qst2") or flags.get("has_qst3") else "opt"
        if flags.get("has_freq"):
            return "freq"
        return "sp"

    def validate_inputs(self, workspace: Path, intent: dict[str, Any], inputs: dict[str, str]) -> None:
        from chemical_runtime.backends.ase_neb import validate_ase_neb_endpoints
        from chemical_runtime.backends.gaussian import read_gjf_route, route_settings
        from chemical_runtime.backends.xyz import xyz_frame_metadata
        from chemical_runtime.backends.xtb_scan import parse_xtb_scan_control
        backend = str(intent["backend"])
        task_type = self.classify_task(workspace, intent)
        if backend == "xtb" and task_type == "scan":
            geometry = xyz_frame_metadata(workspace / inputs["xyz"])
            parse_xtb_scan_control(workspace / inputs["control"], atom_count=int(geometry["atom_count"]))
            return
        if backend == "ase_neb":
            validate_ase_neb_endpoints(workspace / inputs["reactant"], workspace / inputs["product"])
            return
        if backend != "gaussian":
            return
        gjf = workspace / inputs["gjf"]
        if gjf.suffix.lower() not in {".gjf", ".com"}:
            raise ValueError("Gaussian input must use .gjf or .com")
        flags = route_settings(read_gjf_route(gjf))
        required_flags = {"opt": {"has_opt"}, "ts": {"has_ts"}, "freq": {"has_freq"},
                          "opt_freq": {"has_opt", "has_freq"}, "irc": {"has_irc"}, "scan": set(), "sp": set()}
        missing = sorted(flag for flag in required_flags.get(task_type, set()) if not flags.get(flag))
        if missing:
            raise ValueError(f"Gaussian route does not satisfy the detected operation {task_type}: missing {missing}")

    def prepare(self, task: BackendTask) -> PreparedTask:
        from chemical_runtime.backends.ase_neb import prepare_ase_neb
        from chemical_runtime.backends.crest import prepare_crest
        from chemical_runtime.backends.gaussian import prepare_gaussian
        from chemical_runtime.backends.pyscf import prepare_pyscf
        from chemical_runtime.backends.xtb import prepare_xtb
        handlers = {"xtb": prepare_xtb, "crest": prepare_crest, "gaussian": prepare_gaussian,
                    "pyscf": prepare_pyscf, "ase_neb": prepare_ase_neb}
        backend = task.backend or task.task_type
        prepared = handlers[backend](task)
        # The generic local lifecycle consumes provider-owned import paths
        # through PreparedTask.environment; it must not know this extension's
        # filesystem layout.
        extension_root = str(Path(__file__).resolve().parent)
        inherited = prepared.environment.get("PYTHONPATH", "")
        pythonpath = os.pathsep.join(item for item in (extension_root, inherited) if item)
        return replace(prepared, environment={**prepared.environment, "PYTHONPATH": pythonpath})

    def required_artifacts(self, backend: str, task_type: str) -> set[str]:
        from chemical_runtime.backends.ase_neb import ASE_NEB_REQUIRED_ARTIFACTS
        from chemical_runtime.backends.crest import CREST_REQUIRED_ARTIFACTS
        from chemical_runtime.backends.pyscf import PYSCF_REQUIRED_ARTIFACTS
        from chemical_runtime.backends.xtb import XTB_REQUIRED_ARTIFACTS
        if backend == "xtb":
            return set(XTB_REQUIRED_ARTIFACTS[task_type])
        if backend == "crest":
            return set(CREST_REQUIRED_ARTIFACTS)
        if backend == "ase_neb":
            return set(ASE_NEB_REQUIRED_ARTIFACTS)
        if backend == "pyscf":
            return set(PYSCF_REQUIRED_ARTIFACTS[task_type])
        return set()

    def parse_artifact_name(self, backend: str, expected_names: list[str]) -> str | None:
        if backend == "gaussian":
            candidates = [name for name in expected_names if Path(name).suffix.lower() in {".log", ".out"}]
        else:
            candidates = [name for name in expected_names if name == {
                "xtb": "xtb.out", "crest": "crest.out",
                "ase_neb": "neb_summary.json", "pyscf": "pyscf_result.json",
            }.get(backend)]
        return candidates[0] if len(candidates) == 1 else None

    def validate_parse_source(self, backend: str, source: Path) -> None:
        expected = self.parse_artifact_name(backend, [source.name])
        if backend == "gaussian":
            if source.suffix.lower() not in {".log", ".out"}:
                raise ValueError("Gaussian parser accepts only .log or .out artifacts")
        elif expected is None:
            raise ValueError(f"{backend} parser requires its bound primary artifact")

    def remote_stdout_name(self, prepared_task: dict[str, Any]) -> str:
        expected = [Path(str(ref)).name for ref in prepared_task.get("expected_artifacts", [])]
        if prepared_task.get("backend") == "gaussian":
            captures = [name for name in expected if Path(name).suffix.lower() in {".log", ".out"}]
            if len(captures) != 1:
                raise ValueError("Gaussian remote execution requires exactly one .log or .out artifact")
            return captures[0]
        return self.parse_artifact_name(str(prepared_task.get("backend")), expected) or "remote_job.stdout"

    def apply_environment(self, intent: dict[str, Any], prepared: PreparedTask, binding: Any, resolve_binding: Any) -> PreparedTask:
        """Bind chemistry calculators while keeping aliases inside the extension."""
        if binding is None or not binding.command:
            return prepared
        command = list(prepared.command)
        environment = {**prepared.environment, **binding.environment}
        gaussian_binding = None
        calculator = str(intent.get("parameters", {}).get("calculator", "xtb_cli"))
        if prepared.backend == "ase_neb":
            if calculator == "gaussian_cli":
                gaussian_binding = resolve_binding("gaussian")
                if gaussian_binding is not None:
                    environment.update(gaussian_binding.environment)
            remote = intent.get("execution_target", {}).get("kind") == "remote"
            required = "TS_ASE_NEB_GAUSSIAN" if calculator == "gaussian_cli" else "TS_ASE_NEB_XTB"
            if remote and not environment.get(required, "").strip():
                raise ValueError(f"remote ASE NEB binding requires environment.{required}")
            if remote:
                command = list(binding.command) + command[1:]
            elif calculator == "xtb_cli":
                environment.setdefault("TS_ASE_NEB_XTB", binding.command[0])
        else:
            command = list(binding.command) + command[1:]
        activation = (
            gaussian_binding.activation_script if calculator == "gaussian_cli" and gaussian_binding is not None
            and gaussian_binding.activation_script else binding.activation_script
        ) if intent.get("execution_target", {}).get("kind") == "local" else prepared.activation_script
        return replace(prepared, command=command, environment=environment, activation_script=activation)

    def remote_job_options(self, config: Any) -> dict[str, Any]:
        """Describe scheduler wrapper details for chemistry backends."""
        backend = str(config.backend)
        options: dict[str, Any] = {}
        if backend == "gaussian":
            options.update({"scratch": True, "scratch_exports": ("GAUSS_SCRDIR",), "stdin": True})
        if backend == "ase_neb" and config.environment.get("TS_ASE_NEB_GAUSSIAN"):
            gaussian = config.platform.backends.get("gaussian")
            if gaussian is not None and gaussian.activation_script:
                options["activation_scripts"] = (gaussian.activation_script,)
        if backend == "crest":
            options["artifact_aliases"] = {"crest.out": config.stdout_name}
        return options

    def remote_artifact_name(self, config: Any, name: str) -> str:
        return self.remote_job_options(config).get("artifact_aliases", {}).get(name, name)

    def local_job_options(self, prepared_task: dict[str, Any], local_command: list[str],
                          input_names: set[str], run_dir: Path) -> dict[str, Any]:
        if prepared_task.get("backend") != "gaussian":
            return {}
        if len(local_command) != 2 or local_command[1] not in input_names:
            raise ValueError("Gaussian local calculation must bind exactly one staged input")
        scratch = run_dir / "scratch"
        return {
            "command": [local_command[0]],
            "stdin_name": local_command[1],
            "scratch_dir": scratch,
            "environment": {"GAUSS_SCRDIR": str(scratch), "TMPDIR": str(scratch)},
        }

    def validate_parse_inputs(self, backend: str, intent: dict[str, Any], context: dict[str, Any]) -> None:
        if backend == "ase_neb":
            from chemical_runtime.backends.ase_neb import validate_ase_neb_endpoints
            endpoints = context.get("ase_neb_endpoints") or {}
            validate_ase_neb_endpoints(endpoints["reactant"], endpoints["product"])

    def build_parse_context(
        self, workspace: Path, intent: dict[str, Any],
        parse_inputs: dict[str, tuple[str, Path]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        backend = str(intent["backend"])
        context: dict[str, Any] = {"task_type": str(intent["task_type"])}
        extra: list[dict[str, str]] = []
        if backend == "gaussian":
            task_type = self.classify_task(workspace, intent)
            context.update({"gaussian_task": task_type, "is_irc": task_type == "irc", "is_scan": task_type == "scan", "task_type": task_type})
        if backend == "xtb" and intent.get("task_type") == "scan":
            ref, path = self._bound_input_path(workspace, str(intent["input_refs"]["control"]))
            context["xtb_control"] = path
            extra.append({"ref": ref, "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()})
        if backend == "ase_neb":
            endpoints = {}
            for role in ("reactant", "product"):
                ref, path = self._bound_input_path(workspace, str(intent["input_refs"][role]))
                endpoints[role] = path
                extra.append({"ref": ref, "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()})
            context["ase_neb_endpoints"] = endpoints
        return context, extra

    @staticmethod
    def _bound_input_path(workspace: Path, value: str) -> tuple[str, Path]:
        text = str(value).replace("\\", "/").lstrip("@")
        if PurePosixPath(text).is_absolute():
            raise ValueError("workspace input path must be relative")
        normalized = posixpath.normpath(text)
        if normalized in {"", ".", ".."} or normalized.startswith("../"):
            raise ValueError("workspace input path escapes workspace")
        path = workspace / normalized
        if has_symlink_component(workspace, path) or path.is_symlink() or not path.is_file():
            raise ValueError("workspace input path is not a physical file")
        return normalized, path

    def parse(self, workspace: Path, intent: dict[str, Any], source: Path,
              parse_inputs: dict[str, tuple[str, Path]], *, parse_context: dict[str, Any]) -> dict[str, Any]:
        from chemical_runtime.backends.ase_neb import parse_ase_neb_artifacts
        from chemical_runtime.backends.crest import parse_crest_artifacts
        from chemical_runtime.backends.gaussian import parse_irc_log, parse_log, parse_scan_log, read_gjf_route
        from chemical_runtime.backends.pyscf import parse_pyscf_artifacts
        from chemical_runtime.backends.xtb import parse_xtb_artifacts
        gaussian_task = parse_context.get("gaussian_task")
        xtb_control = parse_context.get("xtb_control")
        ase_neb_endpoints = parse_context.get("ase_neb_endpoints", {})
        backend = str(intent["backend"])
        paths = {name: path for name, (_, path) in parse_inputs.items()}
        if backend == "gaussian":
            expected_route = None
            gjf_ref = intent["input_refs"].get("gjf")
            if gjf_ref:
                expected_route = read_gjf_route(workspace / gjf_ref)
            if gaussian_task == "irc":
                return parse_irc_log(source)
            if gaussian_task == "scan":
                return parse_scan_log(source, expected_route=expected_route)
            return parse_log(source, expected_route=expected_route)
        if backend == "xtb":
            return parse_xtb_artifacts(str(intent["task_type"]), paths, control=xtb_control)
        if backend == "crest":
            return parse_crest_artifacts(paths, input_xyz=workspace / intent["input_refs"]["xyz"])
        if backend == "pyscf":
            from research_compute.capabilities import adapter_settings
            return parse_pyscf_artifacts(str(intent["task_type"]), paths, expected_settings=adapter_settings(intent["parameters"]))
        from research_compute.capabilities import adapter_settings
        return parse_ase_neb_artifacts(paths, reactant=ase_neb_endpoints["reactant"], product=ase_neb_endpoints["product"], expected_settings=adapter_settings(intent["parameters"]))

    def parser_name(self, backend: str, *, parse_context: dict[str, Any]) -> str:
        is_irc = parse_context.get("is_irc") is True
        is_scan = parse_context.get("is_scan") is True
        suffix = "parse_irc_log" if is_irc and backend == "gaussian" else "parse_scan_log" if is_scan and backend == "gaussian" else {
            "gaussian": "parse_log", "xtb": "parse_xtb_artifacts", "crest": "parse_crest_artifacts",
            "pyscf": "parse_pyscf_artifacts", "ase_neb": "parse_ase_neb_artifacts",
        }[backend]
        return f"chemical.{backend}.{suffix}"

    def write_parse_artifacts(self, parsed: dict[str, Any], parse_dir: Path, source: Path,
                              *, backend: str, parse_context: dict[str, Any]) -> None:
        from chemical_runtime.backends.ase_neb import write_ase_neb_parse_artifacts
        from chemical_runtime.backends.crest import write_crest_parse_artifacts
        from chemical_runtime.backends.gaussian import write_irc_parse_artifacts, write_parse_artifacts, write_scan_parse_artifacts
        from chemical_runtime.backends.pyscf import write_pyscf_parse_artifacts
        from chemical_runtime.backends.xtb import write_xtb_parse_artifacts
        gaussian_task = parse_context.get("gaussian_task")
        if backend == "gaussian" and gaussian_task == "irc":
            return write_irc_parse_artifacts(parsed, parse_dir, source.stem, source.name)
        if backend == "gaussian" and gaussian_task == "scan":
            return write_scan_parse_artifacts(parsed, parse_dir)
        if backend == "gaussian":
            return write_parse_artifacts(parsed, parse_dir, source.stem, source.name)
        return {"xtb": write_xtb_parse_artifacts, "crest": write_crest_parse_artifacts,
                "pyscf": write_pyscf_parse_artifacts, "ase_neb": write_ase_neb_parse_artifacts}[backend](parsed, parse_dir)


chemical_compute_provider = ChemicalComputeProvider()
