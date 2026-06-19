"""ASE-NEB remote job adapter.

This module keeps ASE/xTB NEB engine behavior out of the generic SSH/job
lifecycle layer. It builds a node-scoped :class:`RemoteJobSpec` that stages a
small skill runtime copy inside the remote TS-search workspace and then runs
``scripts/ase_neb_framework.py run <config>`` on the compute host.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
from pathlib import Path
import posixpath
import re
import shlex
import tarfile
from typing import Any

from transition_state_workflow.remote.job_runner import RemoteJobSpec, RemoteUpload, validate_node_id
from transition_state_workflow.util.cli import CliError


DEFAULT_REMOTE_PYTHON = "/home/iaw/soft/conda/envs/AresTSTools_Computer_30/bin/python"
DEFAULT_XTB_BIN_DIR = "/home/iaw/soft/xtb/6.7.1/bin"
DEFAULT_GAUSSIAN_LIB_DIR = "/home/iaw/soft/Gaussian/g16"
DEFAULT_OPENMPI_LIB_DIR = "/home/iaw/soft/Openmpi/4.1.6/lib"
DEFAULT_REMOTE_TOOL_SUBDIR = "tools/transition-state-workflow"
RUNTIME_ARCHIVE_NAME = "transition-state-workflow.runtime.tar.gz"


@dataclass(frozen=True)
class AseNebRemoteLayout:
    """Resolved local/remote paths for one ASE-NEB remote job."""

    remote_root: str
    node_id: str
    remote_node_dir: str
    remote_input_dir: str
    remote_run_dir: str
    remote_tool_root: str
    remote_archive_path: str
    remote_config_path: str
    output_name: str
    local_download_dir: Path

    @property
    def remote_output_root(self) -> str:
        return posixpath.join(self.remote_run_dir, self.output_name)


def default_skill_root() -> Path:
    """Return the skill checkout/install root for local runtime packaging."""

    return Path(__file__).resolve().parents[3]


def safe_remote_root(raw: str) -> str:
    """Normalize a remote root without allowing an empty root."""

    root = str(raw).strip().rstrip("/")
    if not root:
        raise CliError("--root must not be empty")
    return root


def safe_name(raw: str, *, default: str) -> str:
    """Return a conservative file/directory name for generated artifacts."""

    name = Path(str(raw).strip()).name
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or default


def job_stem_from_config(config_path: Path) -> str:
    """Infer a readable job stem from a config filename."""

    stem = safe_name(config_path.stem, default="ase_neb")
    for suffix in ("_config", "-config"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem or "ase_neb"


def default_local_download_dir(config_path: Path, node_id: str, explicit: Path | None) -> Path:
    """Return the local node outputs dir when config lives under nodes/*/inputs."""

    if explicit is not None:
        return explicit.expanduser().resolve()
    resolved = config_path.resolve()
    if resolved.parent.name == "inputs" and resolved.parent.parent.name == node_id:
        return resolved.parent.parent / "outputs"
    return resolved.parent / f"{node_id}_remote_outputs"


def build_layout(args: Any, config_path: Path) -> AseNebRemoteLayout:
    """Resolve remote node paths for an ASE-NEB job."""

    node_id = validate_node_id(args.node)
    remote_root = safe_remote_root(args.root)
    remote_node_dir = posixpath.join(remote_root, "nodes", node_id)
    remote_input_dir = posixpath.join(remote_node_dir, "inputs")
    remote_run_dir = posixpath.join(remote_node_dir, "outputs")
    remote_tool_root = (
        str(args.tool_root).rstrip("/")
        if getattr(args, "tool_root", None)
        else posixpath.join(remote_root, DEFAULT_REMOTE_TOOL_SUBDIR)
    )
    if not remote_tool_root or remote_tool_root == "/":
        raise CliError("--tool-root must not be empty or /")
    output_name = safe_name(
        getattr(args, "output_name", "") or inferred_output_name(config_path),
        default="ase_neb",
    )
    remote_config_name = f"{safe_name(config_path.stem, default='ase_neb_config')}.remote.json"
    return AseNebRemoteLayout(
        remote_root=remote_root,
        node_id=node_id,
        remote_node_dir=remote_node_dir,
        remote_input_dir=remote_input_dir,
        remote_run_dir=remote_run_dir,
        remote_tool_root=remote_tool_root,
        remote_archive_path=posixpath.join(remote_root, "tools", RUNTIME_ARCHIVE_NAME),
        remote_config_path=posixpath.join(remote_input_dir, remote_config_name),
        output_name=output_name,
        local_download_dir=default_local_download_dir(config_path, node_id, getattr(args, "output_dir", None)),
    )


def inferred_output_name(config_path: Path) -> str:
    """Infer the nested ASE-NEB output directory name from a local config."""

    try:
        cfg = read_config_mapping(config_path)
    except CliError:
        return job_stem_from_config(config_path)
    return safe_name(Path(str(cfg.get("output", ""))).name, default=job_stem_from_config(config_path))


def read_config_mapping(path: Path) -> dict[str, Any]:
    """Read a JSON/TOML/YAML config without importing the ASE tool layer."""

    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            try:
                import tomllib
            except ModuleNotFoundError as exc:  # pragma: no cover - Python < 3.11
                raise CliError("TOML config needs Python 3.11+ tomllib") from exc
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-untyped]
            except ModuleNotFoundError as exc:
                raise CliError("YAML config needs PyYAML; use JSON or TOML otherwise") from exc
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            raise CliError(f"unsupported config suffix: {path.suffix}")
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON config: {exc}") from exc

    if not isinstance(data, dict):
        raise CliError("config root must be a mapping")
    return data


def resolve_config_file_value(cfg: dict[str, Any], config_path: Path, key_path: tuple[str, ...]) -> None:
    """Resolve one local file path in a config mapping if present."""

    parent: dict[str, Any] = cfg
    for key in key_path[:-1]:
        value = parent.get(key)
        if not isinstance(value, dict):
            return
        parent = value
    key = key_path[-1]
    value = parent.get(key)
    if not value:
        return
    path = Path(str(value))
    resolved = path if path.is_absolute() else config_path.resolve().parent / path
    parent[key] = str(resolved)


def load_local_config(config_path: Path) -> dict[str, Any]:
    """Load an ASE-NEB config and resolve local input-file paths."""

    cfg = copy.deepcopy(read_config_mapping(config_path))
    for key in ("reactant", "product"):
        if not isinstance(cfg.get(key), str) or not str(cfg[key]).strip():
            raise CliError(f"{key} must be a non-empty path string")
    for key_path in (
        ("reactant",),
        ("product",),
        ("calculator", "template_gjf"),
        ("calculator", "tail_file"),
    ):
        resolve_config_file_value(cfg, config_path, key_path)
    return cfg


def unique_remote_input_name(label: str, local_path: Path, used: dict[str, Path]) -> str:
    """Return a basename that will not collide inside remote inputs/."""

    base = safe_name(local_path.name, default=f"{label}.dat")
    if base not in used or used[base] == local_path:
        used[base] = local_path
        return base
    candidate = safe_name(f"{label}_{base}", default=f"{label}.dat")
    index = 2
    while candidate in used and used[candidate] != local_path:
        candidate = safe_name(f"{label}_{index}_{base}", default=f"{label}_{index}.dat")
        index += 1
    used[candidate] = local_path
    return candidate


def add_config_file_upload(
    *,
    cfg: dict[str, Any],
    uploads: list[RemoteUpload],
    used_names: dict[str, Path],
    label: str,
    key_path: tuple[str, ...],
    remote_input_dir: str,
) -> None:
    """Replace one local config file path with a remote input path and upload it."""

    parent: dict[str, Any] = cfg
    for key in key_path[:-1]:
        value = parent.get(key)
        if not isinstance(value, dict):
            return
        parent = value
    key = key_path[-1]
    raw = parent.get(key)
    if not raw:
        return
    local_path = Path(str(raw)).resolve()
    if not local_path.is_file():
        raise CliError(f"{'.'.join(key_path)} does not exist: {local_path}")
    name = unique_remote_input_name(label, local_path, used_names)
    remote_path = posixpath.join(remote_input_dir, name)
    parent[key] = remote_path
    uploads.append(RemoteUpload(local_path, remote_path))


def write_remote_config(
    *,
    local_cfg: dict[str, Any],
    layout: AseNebRemoteLayout,
    staging_dir: Path,
) -> tuple[Path, list[RemoteUpload]]:
    """Write the remote JSON config and return all config/input uploads."""

    remote_cfg = copy.deepcopy(local_cfg)
    remote_cfg["output"] = layout.remote_output_root
    uploads: list[RemoteUpload] = []
    used_names: dict[str, Path] = {}
    for label, key_path in (
        ("reactant", ("reactant",)),
        ("product", ("product",)),
        ("template_gjf", ("calculator", "template_gjf")),
        ("tail_file", ("calculator", "tail_file")),
    ):
        add_config_file_upload(
            cfg=remote_cfg,
            uploads=uploads,
            used_names=used_names,
            label=label,
            key_path=key_path,
            remote_input_dir=layout.remote_input_dir,
        )
    remote_config = staging_dir / Path(layout.remote_config_path).name
    remote_config.write_text(json.dumps(remote_cfg, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    uploads.insert(0, RemoteUpload(remote_config, layout.remote_config_path))
    return remote_config, uploads


def iter_runtime_files(skill_root: Path) -> list[Path]:
    """Return files needed by the remote ASE-NEB runtime package."""

    files: list[Path] = []
    ignored_parts = {".git", ".pytest_cache", "__pycache__"}
    for dirname in ("src", "scripts", "templates"):
        base = skill_root / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix == ".pyc" or any(part in ignored_parts for part in path.parts):
                continue
            files.append(path)
    if not files:
        raise CliError(f"no runtime files found under {skill_root}")
    return files


def build_runtime_archive(skill_root: Path, archive_path: Path) -> Path:
    """Create a tar.gz runtime package containing src/, scripts/, and templates/."""

    root = skill_root.expanduser().resolve()
    if not (root / "src" / "transition_state_workflow").is_dir():
        raise CliError(f"runtime root does not look like transition-state-workflow: {root}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in iter_runtime_files(root):
            archive.add(path, arcname=str(path.relative_to(root)))
    return archive_path


def parse_env_assignments(assignments: list[str]) -> dict[str, str]:
    """Parse KEY=VALUE runner environment overrides."""

    env: dict[str, str] = {}
    for item in assignments:
        if "=" not in item:
            raise CliError(f"--env must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise CliError(f"invalid environment variable name: {key}")
        env[key] = value
    return env


def remote_runner_text(args: Any, layout: AseNebRemoteLayout) -> str:
    """Build the compute-host runner script for ASE-NEB."""

    job_stem = safe_name(getattr(args, "job_stem", "") or job_stem_from_config(Path(args.config)), default="ase_neb")
    run_dir = shlex.quote(layout.remote_run_dir)
    tool_root = shlex.quote(layout.remote_tool_root)
    archive_path = shlex.quote(layout.remote_archive_path)
    config_path = shlex.quote(layout.remote_config_path)
    output_name = shlex.quote(layout.output_name)
    python = shlex.quote(str(getattr(args, "python", DEFAULT_REMOTE_PYTHON)))
    xtb_bin_dir = shlex.quote(str(getattr(args, "xtb_bin_dir", DEFAULT_XTB_BIN_DIR) or ""))
    gaussian_lib_dir = shlex.quote(str(getattr(args, "gaussian_lib_dir", DEFAULT_GAUSSIAN_LIB_DIR) or ""))
    openmpi_lib_dir = shlex.quote(str(getattr(args, "openmpi_lib_dir", DEFAULT_OPENMPI_LIB_DIR) or ""))
    preserve_ld_library_path = "true" if bool(getattr(args, "preserve_ld_library_path", False)) else "false"
    allow_gaussian_neb = "true" if bool(getattr(args, "allow_gaussian_neb", False)) else "false"
    metadata = shlex.quote(f"{job_stem}.run_metadata.txt")
    validate_out = shlex.quote(f"{job_stem}.validate.out")
    validate_err = shlex.quote(f"{job_stem}.validate.err")
    prepare_out = shlex.quote(f"{job_stem}.prepare.out")
    prepare_err = shlex.quote(f"{job_stem}.prepare.err")
    run_out = shlex.quote(f"{job_stem}.run.out")
    run_err = shlex.quote(f"{job_stem}.run.err")
    extract_out = shlex.quote(f"{job_stem}.extract.out")
    extract_err = shlex.quote(f"{job_stem}.extract.err")
    results_archive = shlex.quote(f"{job_stem}.results.tar.gz")
    extra_exports = "\n".join(
        f"export {key}={shlex.quote(value)}" for key, value in parse_env_assignments(getattr(args, "env", []) or []).items()
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
TOOL_ROOT={tool_root}
ARCHIVE={archive_path}
CONFIG={config_path}
OUTPUT_NAME={output_name}
PYTHON={python}
XTB_BIN_DIR={xtb_bin_dir}
GAUSSIAN_LIB_DIR={gaussian_lib_dir}
OPENMPI_LIB_DIR={openmpi_lib_dir}
PRESERVE_LD_LIBRARY_PATH={preserve_ld_library_path}
ALLOW_GAUSSIAN_NEB={allow_gaussian_neb}

META={metadata}
VALIDATE_OUT={validate_out}
VALIDATE_ERR={validate_err}
PREPARE_OUT={prepare_out}
PREPARE_ERR={prepare_err}
RUN_OUT={run_out}
RUN_ERR={run_err}
EXTRACT_OUT={extract_out}
EXTRACT_ERR={extract_err}
RESULTS_ARCHIVE={results_archive}

cd "$RUN_DIR"

finish() {{
    local final_status="$1"
    if [[ -d "$OUTPUT_NAME" ]]; then
        set +e
        tar -czf "$RESULTS_ARCHIVE" "$OUTPUT_NAME" >> "$META" 2>/dev/null
        tar_status=$?
        set -e
        echo "results_archive=$RUN_DIR/$RESULTS_ARCHIVE" >> "$META"
        echo "results_archive_status=$tar_status" >> "$META"
    fi
    echo "end=$(date -Is)" >> "$META"
    echo "status=$final_status" >> "$META"
    exit "$final_status"
}}

if [[ -n "$XTB_BIN_DIR" ]]; then
    export PATH="$XTB_BIN_DIR:$PATH"
fi
export PATH="$(dirname "$PYTHON"):$PATH"
PYTHON_PREFIX="$(dirname "$(dirname "$PYTHON")")"
if [[ -n "$GAUSSIAN_LIB_DIR" || -n "$OPENMPI_LIB_DIR" ]]; then
    export LD_LIBRARY_PATH="$PYTHON_PREFIX/lib:${{GAUSSIAN_LIB_DIR:+$GAUSSIAN_LIB_DIR:}}${{OPENMPI_LIB_DIR:+$OPENMPI_LIB_DIR:}}${{LD_LIBRARY_PATH:-}}"
else
    export LD_LIBRARY_PATH="$PYTHON_PREFIX/lib:${{LD_LIBRARY_PATH:-}}"
fi
if [[ "$PRESERVE_LD_LIBRARY_PATH" != "true" && -n "${{LD_LIBRARY_PATH:-}}" ]]; then
    export LD_LIBRARY_PATH="$(printf '%s' "$LD_LIBRARY_PATH" | tr ':' '\\n' | awk '$0 !~ /gcc\\/11\\.3\\.0/' | paste -sd: -)"
fi
{extra_exports}

xtb_path="$(command -v xtb || true)"
{{
    echo "host=$(hostname)"
    echo "start=$(date -Is)"
    echo "run_dir=$RUN_DIR"
    echo "tool_root=$TOOL_ROOT"
    echo "archive=$ARCHIVE"
    echo "config=$CONFIG"
    echo "output_root=$RUN_DIR/$OUTPUT_NAME"
    echo "python=$PYTHON"
    echo "xtb=$xtb_path"
    echo "allow_gaussian_neb=$ALLOW_GAUSSIAN_NEB"
    echo "OMP_NUM_THREADS=${{OMP_NUM_THREADS:-}}"
    echo "MKL_NUM_THREADS=${{MKL_NUM_THREADS:-}}"
    echo "OPENBLAS_NUM_THREADS=${{OPENBLAS_NUM_THREADS:-}}"
}} > "$META"

if [[ ! -r "$CONFIG" ]]; then
    echo "error: remote ASE-NEB config is not readable: $CONFIG" >&2
    finish 66
fi
if [[ ! -r "$ARCHIVE" ]]; then
    echo "error: runtime archive is not readable: $ARCHIVE" >&2
    finish 67
fi

mkdir -p "$TOOL_ROOT"
set +e
tar -xzf "$ARCHIVE" -C "$TOOL_ROOT" > "$EXTRACT_OUT" 2> "$EXTRACT_ERR"
extract_status=$?
set -e
echo "extract_status=$extract_status" >> "$META"
if [[ "$extract_status" -ne 0 ]]; then
    finish "$extract_status"
fi

ASE_NEB="$TOOL_ROOT/scripts/ase_neb_framework.py"
if [[ ! -r "$ASE_NEB" ]]; then
    echo "error: missing remote ASE-NEB entry point: $ASE_NEB" >&2
    finish 68
fi
chmod +x "$ASE_NEB" || true
export PYTHONPATH="$TOOL_ROOT/src${{PYTHONPATH:+:$PYTHONPATH}}"

set +e
"$PYTHON" "$ASE_NEB" validate-config "$CONFIG" --strict-files --require-deps > "$VALIDATE_OUT" 2> "$VALIDATE_ERR"
validate_status=$?
if [[ "$validate_status" -eq 0 ]]; then
    "$PYTHON" "$ASE_NEB" prepare "$CONFIG" > "$PREPARE_OUT" 2> "$PREPARE_ERR"
    prepare_status=$?
else
    prepare_status=99
fi
if [[ "$validate_status" -eq 0 && "$prepare_status" -eq 0 ]]; then
    if [[ "$ALLOW_GAUSSIAN_NEB" == "true" ]]; then
        "$PYTHON" "$ASE_NEB" run "$CONFIG" --allow-gaussian-neb > "$RUN_OUT" 2> "$RUN_ERR"
    else
        "$PYTHON" "$ASE_NEB" run "$CONFIG" > "$RUN_OUT" 2> "$RUN_ERR"
    fi
    run_status=$?
else
    run_status=99
fi
set -e

{{
    echo "validate_status=$validate_status"
    echo "prepare_status=$prepare_status"
    echo "run_status=$run_status"
}} >> "$META"

if [[ "$validate_status" -ne 0 || "$prepare_status" -ne 0 || "$run_status" -ne 0 ]]; then
    finish 1
fi
finish 0
"""


def build_remote_job_spec(
    args: Any,
    config_path: Path,
    layout: AseNebRemoteLayout,
    *,
    staging_dir: Path,
    runtime_archive: Path,
) -> RemoteJobSpec:
    """Build the generic remote job spec for an ASE-NEB config."""

    local_cfg = load_local_config(config_path)
    _, config_uploads = write_remote_config(local_cfg=local_cfg, layout=layout, staging_dir=staging_dir)
    job_stem = safe_name(getattr(args, "job_stem", "") or job_stem_from_config(config_path), default="ase_neb")
    uploads = [
        *config_uploads,
        RemoteUpload(config_path.resolve(), posixpath.join(layout.remote_input_dir, config_path.name)),
        RemoteUpload(runtime_archive, layout.remote_archive_path),
        *(
            RemoteUpload(path.resolve(), posixpath.join(layout.remote_input_dir, path.resolve().name))
            for path in getattr(args, "extra_file", []) or []
        ),
    ]
    return RemoteJobSpec(
        engine="ase-neb",
        job_stem=job_stem,
        remote_run_dir=layout.remote_run_dir,
        runner_name=f"{job_stem}.run_ase_neb_on_compute.sh",
        runner_text=remote_runner_text(args, layout),
        local_download_dir=layout.local_download_dir,
        uploads=tuple(dict((upload.remote_path, upload) for upload in uploads).values()),
        remote_prepare_dirs=(
            layout.remote_input_dir,
            layout.remote_tool_root,
            posixpath.dirname(layout.remote_archive_path),
            posixpath.join(layout.remote_node_dir, "scratch", "ase_neb"),
        ),
        metadata_name=f"{job_stem}.run_metadata.txt",
        receipt_name=f"{job_stem}.submit_receipt.txt",
        nohup_name=f"{job_stem}.runner.nohup",
        download_groups=(
            (f"{job_stem}.run_metadata.txt",),
            (f"{job_stem}.validate.out",),
            (f"{job_stem}.validate.err",),
            (f"{job_stem}.prepare.out",),
            (f"{job_stem}.prepare.err",),
            (f"{job_stem}.run.out",),
            (f"{job_stem}.run.err",),
        ),
        optional_download_groups=(
            (f"{job_stem}.extract.out",),
            (f"{job_stem}.extract.err",),
            (f"{job_stem}.results.tar.gz",),
            (f"{job_stem}.submit_receipt.txt", "submit_receipt.txt"),
            (f"{job_stem}.runner.nohup", "runner.nohup"),
            (f"{job_stem}.run_ase_neb_on_compute.sh",),
        ),
    )


__all__ = [
    "AseNebRemoteLayout",
    "DEFAULT_REMOTE_PYTHON",
    "DEFAULT_XTB_BIN_DIR",
    "build_layout",
    "build_remote_job_spec",
    "build_runtime_archive",
    "default_skill_root",
    "inferred_output_name",
    "job_stem_from_config",
    "remote_runner_text",
]
