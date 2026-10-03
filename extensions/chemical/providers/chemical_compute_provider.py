"""Chemistry extension implementation of the generic compute provider.

This is the only module that binds the generic compute lifecycle to Gaussian,
xTB, CREST, PySCF and ASE.  The research-compute package sees only the
protocol in ``research_compute.provider``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_compute.provider import BackendTask, PreparedTask


class ChemicalComputeProvider:
    provider_id = "chemical"
    domain_id = "chemical"
    backends = ("gaussian", "xtb", "crest", "ase_neb", "pyscf")

    def supports(self, backend: str) -> bool:
        return backend in self.backends

    def descriptors(self):
        from chemical_runtime.analysis.catalog import DESCRIPTORS
        return tuple(DESCRIPTORS)

    def run_analysis(self, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        from chemical_runtime.analysis.engine import run_scientific_analysis
        return run_scientific_analysis(str(root), request)

    def validate_candidate(self, root: Path, artifact: dict[str, Any], node_id: str, candidate_id: str) -> dict[str, Any]:
        from chemical_analysis_candidates import load_analysis_candidate
        return load_analysis_candidate(root, artifact, node_id, candidate_id)

    def structure_operation(self, operation: str, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        from chemical_artifacts import (
            import_calculation_artifact, create_structure_seed_artifact,
            create_structure_comparison_artifact, create_reaction_mapping_validation_artifact,
        )
        handlers = {
            "import_artifact": import_calculation_artifact,
            "structure_seed": create_structure_seed_artifact,
            "structure_compare": create_structure_comparison_artifact,
            "mapping_validate": create_reaction_mapping_validation_artifact,
        }
        try:
            return handlers[operation](root, request)
        except KeyError as exc:
            raise ValueError(f"unsupported chemical operation: {operation}") from exc

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
        return handlers[backend](task)

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

    def parse(self, workspace: Path, intent: dict[str, Any], source: Path,
              parse_inputs: dict[str, tuple[str, Path]], *, gaussian_task: str | None,
              xtb_control: Path | None, ase_neb_endpoints: dict[str, Path]) -> dict[str, Any]:
        from chemical_runtime.backends.ase_neb import parse_ase_neb_artifacts
        from chemical_runtime.backends.crest import parse_crest_artifacts
        from chemical_runtime.backends.gaussian import parse_irc_log, parse_log, parse_scan_log, read_gjf_route
        from chemical_runtime.backends.pyscf import parse_pyscf_artifacts
        from chemical_runtime.backends.xtb import parse_xtb_artifacts
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

    def parser_name(self, backend: str, *, is_irc: bool, is_scan: bool) -> str:
        suffix = "parse_irc_log" if is_irc and backend == "gaussian" else "parse_scan_log" if is_scan and backend == "gaussian" else {
            "gaussian": "parse_log", "xtb": "parse_xtb_artifacts", "crest": "parse_crest_artifacts",
            "pyscf": "parse_pyscf_artifacts", "ase_neb": "parse_ase_neb_artifacts",
        }[backend]
        return f"chemical.{backend}.{suffix}"

    def write_parse_artifacts(self, parsed: dict[str, Any], parse_dir: Path, source: Path,
                              *, backend: str, gaussian_task: str | None) -> None:
        from chemical_runtime.backends.ase_neb import write_ase_neb_parse_artifacts
        from chemical_runtime.backends.crest import write_crest_parse_artifacts
        from chemical_runtime.backends.gaussian import write_irc_parse_artifacts, write_parse_artifacts, write_scan_parse_artifacts
        from chemical_runtime.backends.pyscf import write_pyscf_parse_artifacts
        from chemical_runtime.backends.xtb import write_xtb_parse_artifacts
        if backend == "gaussian" and gaussian_task == "irc":
            return write_irc_parse_artifacts(parsed, parse_dir, source.stem, source.name)
        if backend == "gaussian" and gaussian_task == "scan":
            return write_scan_parse_artifacts(parsed, parse_dir)
        if backend == "gaussian":
            return write_parse_artifacts(parsed, parse_dir, source.stem, source.name)
        return {"xtb": write_xtb_parse_artifacts, "crest": write_crest_parse_artifacts,
                "pyscf": write_pyscf_parse_artifacts, "ase_neb": write_ase_neb_parse_artifacts}[backend](parsed, parse_dir)


chemical_compute_provider = ChemicalComputeProvider()
