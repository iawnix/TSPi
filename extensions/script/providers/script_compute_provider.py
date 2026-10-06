"""Generic bash Compute Provider.

The provider stages an immutable script Artifact and executes it through the
same compute lifecycle as scientific backends.  It never receives a Research
State handle and therefore cannot write canonical claims or facts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_compute.capabilities import CapabilityDescriptor
from research_compute.provider import BackendTask, PreparedTask


def _output_manifest(settings: dict[str, str]) -> list[str]:
    raw = settings.get("output_manifest", "[\"script_result.json\"]")
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("script output_manifest must be a JSON string array") from exc
    if not isinstance(values, list) or not values:
        raise ValueError("script output_manifest must contain at least one file")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("script output_manifest entries must be simple basenames")
        if value in normalized:
            raise ValueError("script output_manifest entries must be unique")
        normalized.append(value)
    if "script_result.json" not in normalized:
        raise ValueError("script output_manifest must include script_result.json")
    return normalized


def _args(settings: dict[str, str]) -> list[str]:
    raw = settings.get("args", "[]")
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("script args must be a JSON string array") from exc
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("script args must be a string array")
    return values


class ScriptComputeProvider:
    provider_id = "script"
    domain_id = "script"
    backends = ("script",)

    def supports(self, backend: str) -> bool:
        return backend == "script"

    def environment_providers(self, descriptor: Any, environment_kind: str) -> tuple[str, ...]:
        del environment_kind
        return (descriptor.backend,)

    def readiness_probe(self, backend: str, binding: Any) -> None:
        del backend, binding
        return None

    def bridge_environment(self, backend: str, kind: str, environment: dict[str, str]) -> dict[str, str]:
        del backend, kind
        return environment

    def bridge_readiness(self, backend: str, command: list[str], environment: dict[str, str], base: dict[str, Any]) -> dict[str, Any]:
        del backend, command, environment
        return base

    @staticmethod
    def validate_parsed_task(backend: str, task_type: str, facts: dict[str, Any]) -> dict[str, Any]:
        del backend, task_type
        failures = []
        if facts.get("execution_completed") is not True:
            failures.append("program_did_not_complete")
        if facts.get("declared_outputs_present") is not True:
            failures.append("declared_outputs_missing")
        if facts.get("manifest_valid") is not True:
            failures.append("script_manifest_invalid")
        if facts.get("missing_artifacts"):
            failures.append("required_artifacts_missing")
        failures = list(dict.fromkeys(failures))
        return {"status": "completed" if not failures else "incomplete", "failures": failures}

    @staticmethod
    def parsed_program_outcome(backend: str, facts: dict[str, Any]) -> tuple[str, str | None]:
        del backend
        return ("completed", None) if facts.get("execution_completed") is True else ("failed", "script_error_termination")

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return (SCRIPT_BASH_DESCRIPTOR,)

    def validate_inputs(self, workspace: Path, intent: dict[str, Any], inputs: dict[str, str]) -> None:
        if set(inputs) != {"script"}:
            raise ValueError("script.bash requires exactly one script input")
        path = workspace / inputs["script"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("script input must be a regular immutable Artifact")
        _output_manifest({key: _json_value(value) for key, value in intent.get("parameters", {}).items()})
        _args({key: _json_value(value) for key, value in intent.get("parameters", {}).items()})
        if intent.get("execution_target", {}).get("kind") == "remote":
            raise ValueError("script.bash currently supports only local execution")

    def classify_task(self, workspace: Path, intent: dict[str, Any]) -> str:
        return "bash"

    def prepare(self, task: BackendTask) -> PreparedTask:
        if set(task.inputs) != {"script"}:
            raise ValueError("script.bash requires exactly one script input")
        outputs = _output_manifest(task.settings)
        command = ["/bin/bash", task.inputs["script"], *_args(task.settings)]
        return PreparedTask(
            backend="script",
            node_id=task.node_id,
            command=command,
            input_paths=[task.inputs["script"]],
            expected_artifacts=outputs,
        )

    def required_artifacts(self, backend: str, task_type: str) -> set[str]:
        return {"script_result.json"}

    def parse_artifact_name(self, backend: str, expected_names: list[str]) -> str | None:
        del self, backend
        return "script_result.json" if "script_result.json" in expected_names else None

    def validate_parse_source(self, backend: str, source: Path) -> None:
        del self
        if backend != "script" or source.name != "script_result.json":
            raise ValueError("script parser requires the bound script_result.json artifact")

    def remote_stdout_name(self, prepared_task: dict[str, Any]) -> str:
        return self.parse_artifact_name(str(prepared_task.get("backend")), [Path(str(ref)).name for ref in prepared_task.get("expected_artifacts", [])]) or "remote_job.stdout"

    def build_parse_context(
        self, workspace: Path, intent: dict[str, Any],
        parse_inputs: dict[str, tuple[str, Path]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        del workspace, parse_inputs
        return {"task_type": str(intent.get("task_type", "bash"))}, []

    def validate_parse_inputs(self, backend: str, intent: dict[str, Any], context: dict[str, Any]) -> None:
        del backend, intent, context

    def remote_job_options(self, config: Any) -> dict[str, Any]:
        del config
        return {}

    def remote_artifact_name(self, config: Any, name: str) -> str:
        del config
        return name

    def local_job_options(self, prepared_task: dict[str, Any], local_command: list[str],
                          input_names: set[str], run_dir: Path) -> dict[str, Any]:
        del prepared_task, local_command, input_names, run_dir
        return {}

    def artifact_import_formats(self) -> dict[str, frozenset[str]]:
        return {}

    def artifact_input_roles(self, path: str) -> list[str]:
        del path
        return []

    def validate_artifact_import(self, artifact_format: str, content: str,
                                 charge: int | None, multiplicity: int | None) -> dict[str, Any]:
        del content, charge, multiplicity
        raise ValueError(f"script provider does not support artifact format: {artifact_format}")

    def structure_operation(self, operation: str, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        del root, request
        raise ValueError(f"script provider does not support structure operation: {operation}")

    def run_analysis(self, root: Path, request: dict[str, Any]) -> dict[str, Any]:
        del root, request
        raise ValueError("script provider does not support analysis operations")

    def validate_candidate(self, root: Path, artifact: dict[str, Any], node_id: str, candidate_id: str) -> dict[str, Any]:
        del root, artifact, node_id, candidate_id
        raise ValueError("script provider does not support analysis candidates")

    def parse(
        self,
        workspace: Path,
        intent: dict[str, Any],
        source: Path,
        parse_inputs: dict[str, tuple[str, Path]],
        *,
        parse_context: dict[str, Any],
    ) -> dict[str, Any]:
        del parse_context
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("script_result.json must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("script_result.json must contain an object")
        return {
            "summary": {
                "backend": "script",
                "task_type": "bash",
                "execution_completed": True,
                "declared_outputs_present": all(path.is_file() for _, path in parse_inputs.values()),
                "manifest_valid": True,
                "output_count": len(parse_inputs),
                "parser_version": "script.bash.parser/1",
            },
            "result": payload,
        }

    def parser_name(self, backend: str, *, parse_context: dict[str, Any]) -> str:
        del backend, parse_context
        return "script.bash.parser/1"

    def write_parse_artifacts(
        self,
        parsed: dict[str, Any],
        parse_dir: Path,
        source: Path,
        *,
        backend: str,
        parse_context: dict[str, Any],
    ) -> None:
        del backend, parse_context
        parse_dir.mkdir(parents=True, exist_ok=True)
        payload = parsed.get("result")
        if not isinstance(payload, dict):
            payload = {}
        (parse_dir / "script_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def _json_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


SCRIPT_BASH_DESCRIPTOR = CapabilityDescriptor(
    capability="script.bash",
    version="1",
    backend="script",
    task_type="bash",
    input_roles=frozenset({"script"}),
    output_roles=("program_output", "script_result"),
    effects=("local_prepare", "local_compute", "local_parse"),
    parameter_schema={
        "type": "object",
        "properties": {
            "args": {"type": "array", "maxItems": 64, "items": {"type": "string", "maxLength": 4096}},
            "output_manifest": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"},
            },
        },
        "additionalProperties": False,
    },
    limits={"max_args": 64, "max_outputs": 64, "environment": "local"},
    parsers=("script.bash.parser/1",),
)


script_compute_provider = ScriptComputeProvider()
