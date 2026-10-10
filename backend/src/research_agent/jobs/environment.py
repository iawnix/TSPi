"""Observe configured targets and bind an execution guard to that evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile

from .config_contract import binding_digest, python_command
from .worker import supervisor_environment

PROBE_FILE = Path(__file__).with_name("environment_probe.py")
PROBE_DESTINATION = ".coragent/environment_probe.py"


def validate_requirements(value, runtime):
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    if not isinstance(value, dict) or set(value) - {"python", "packages", "imports"}:
        raise ValueError("execution_requirements_invalid")
    if runtime == "native" and value:
        raise ValueError("native_execution_cannot_require_python")
    packages, imports = value.get("packages", {}), value.get("imports", [])
    if (not isinstance(packages, dict) or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key) for key in packages)
            or not isinstance(imports, list) or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", name) for name in imports)
            or len(imports) != len(set(imports))):
        raise ValueError("execution_requirements_invalid")
    for spec in [*packages.values(), *([value["python"]] if "python" in value else [])]:
        if not isinstance(spec, str) or not spec:
            raise ValueError("execution_requirements_invalid")
        try:
            SpecifierSet(spec)
        except InvalidSpecifier:
            raise ValueError("execution_requirements_invalid") from None
    return value


def _python_request(selected, requirements):
    command = selected["binding"].get("command", [])
    return {"python": selected["python"], "requirements": requirements,
            "command": [command] if isinstance(command, str) else command}


def _file_check(expression, role, expected=None):
    missing = "execution_environment_changed" if expected is not None else "environment_" + role + "_missing"
    reject = '{ echo CORAGENT_ENVIRONMENT_ERROR=' + missing + ' >&2; exit 125; }'
    script = [f"research_agent_path=$(readlink -f -- {expression}) || " + reject,
              'test -f "$research_agent_path" || ' + reject,
              'research_agent_hash=$(sha256sum < "$research_agent_path")', 'research_agent_hash="sha256:${research_agent_hash%% *}"']
    if expected is not None:
        script.append(f'[ "$research_agent_path" = {shlex.quote(expected["path"])} ] && '
                      f'[ "$research_agent_hash" = {shlex.quote(expected["sha256"])} ] || '
                      '{ echo CORAGENT_ENVIRONMENT_ERROR=execution_environment_changed >&2; exit 125; }')
    else:
        script.append(f"printf 'CORAGENT_FILE=%s\\t%s\\t%s\\n' {shlex.quote(role)} \"$research_agent_path\" \"$research_agent_hash\"")
    return "\n".join(script)


def _activation(selected, expected=None):
    activation = selected["binding"].get("activation_script")
    if not activation:
        return ""
    check = _file_check(shlex.quote(activation), "activation", expected)
    # Verify before sourcing. Activation output can contain credentials.
    return check + "\nsource " + shlex.quote(activation) + " >/dev/null 2>&1\n"


def _native_check(selected, expected=None):
    command = selected["binding"]["command"]
    executable = command if isinstance(command, str) else command[0]
    missing = "execution_environment_changed" if expected is not None else "environment_executable_missing"
    reject = '{ echo CORAGENT_ENVIRONMENT_ERROR=' + missing + ' >&2; exit 125; }'
    return ('research_agent_executable=$(type -P -- ' + shlex.quote(executable) + ') || ' + reject
            + '\ntest -x "$research_agent_executable" || ' + reject + '\n'
            + _file_check('"$research_agent_executable"', "executable", expected))


def _capture(command, *, env=None, timeout):
    with subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_target(settings, selected, script):
    target = settings["environments"][selected["environment"]]
    env = selected["binding"].get("environment", {})
    timeout = target.get("command_timeout_seconds", 120)
    if selected["kind"] == "local":
        with tempfile.TemporaryDirectory(prefix="coragent-environment-") as scratch:
            variables = {**supervisor_environment(), "TMPDIR": scratch,
                         **{key: value.replace("{scratch}", scratch) for key, value in env.items()}}
            return _capture(["bash", "-c", script], env=variables, timeout=timeout)
    command = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={target.get('connect_timeout_seconds', 15)}"]
    if target.get("ssh_config"):
        command.extend(["-F", target["ssh_config"]])
    command.append(target["ssh_host"])
    # The remote shell supplies its own HOME. No Host environment is forwarded.
    exports = "\n".join("export " + key + "=" + shlex.quote(value).replace("{scratch}", "'\"$research_agent_scratch\"'") for key, value in env.items())
    remote = ("set -eu\numask 077\nmkdir -p -- " + shlex.quote(target["remote_root"]) + "\n"
              "research_agent_scratch=$(mktemp -d " + shlex.quote(target["remote_root"].rstrip("/") + "/.environment-XXXXXX") + ")\n"
              "trap 'rm -rf -- \"$research_agent_scratch\"' EXIT\nexport TMPDIR=\"$research_agent_scratch\"\n" + exports + "\n" + script)
    command.append('env -i PATH=/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 '
                   + f'timeout --kill-after=5 {timeout} bash -c ' + shlex.quote(remote))
    return _capture(command, timeout=timeout + 10)


def probe_binding(settings, selected, requirements):
    """Probe both local and SSH targets; a scheduler-only check is insufficient."""
    validate_requirements(requirements, selected["runtime"])
    script = "set -eu\n" + _activation(selected)
    if selected["runtime"] == "python":
        script += shlex.join(python_command(selected["python"]) + ["-c", PROBE_FILE.read_text(),
                            json.dumps(_python_request(selected, requirements))])
    else:
        script += _native_check(selected)
    try:
        result = _run_target(settings, selected, script)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("environment_probe_unavailable: verify the selected target connection and binding") from None
    if result.returncode:
        codes = re.findall(r"^CORAGENT_ENVIRONMENT_ERROR=([a-z_]+)$", result.stderr, re.MULTILINE)
        raise ValueError(codes[-1] if codes else "environment_probe_failed")
    files, python = {}, None
    try:
        for line in result.stdout.splitlines():
            if line.startswith("CORAGENT_FILE="):
                role, path, digest = line.removeprefix("CORAGENT_FILE=").split("\t")
                if role in files or role not in {"activation", "executable"} or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                    raise ValueError()
                files[role] = {"path": path, "sha256": digest}
            elif line.startswith("CORAGENT_ENVIRONMENT="):
                if python is not None:
                    raise ValueError()
                python = json.loads(line.removeprefix("CORAGENT_ENVIRONMENT="))
        if bool(selected["python"]) != (python is not None) or bool(selected["binding"].get("activation_script")) != ("activation" in files):
            raise ValueError()
        if selected["runtime"] == "native" and "executable" not in files:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("environment_probe_response_invalid") from None
    if python:
        from packaging.specifiers import SpecifierSet
        if "python" in requirements and python["python_version"] not in SpecifierSet(requirements["python"]):
            raise ValueError("environment_python_version_mismatch")
        for name, spec in requirements.get("packages", {}).items():
            if python["packages"].get(name, "0") not in SpecifierSet(spec):
                raise ValueError("environment_dependency_version_mismatch: " + name)
    observation = {"files": files, "python": python}
    return {"schema_version": "job-environment/1", "requirements": requirements,
            "observation": observation, "sha256": binding_digest(observation)}


def guarded_command(selected, argv, snapshot, *, module_paths=None):
    """Build the command deterministically so Runtime can reject forged metadata."""
    observation = snapshot["observation"]
    script = "set -eu\n" + _activation(selected, observation["files"].get("activation"))
    inputs = []
    if selected["runtime"] == "python":
        import hashlib
        digest = hashlib.sha256(PROBE_FILE.read_bytes()).hexdigest()
        inputs = [{"source": str(PROBE_FILE), "destination": PROBE_DESTINATION, "sha256": digest}]
        script += 'research_agent_hash=$(sha256sum < ' + shlex.quote(PROBE_DESTINATION) + ')\n'
        script += '[ "${research_agent_hash%% *}" = ' + shlex.quote(digest) + ' ] || exit 125\n'
        if module_paths is not None:
            launcher = Path(__file__).with_name('python_entrypoint.py')
            target = '.coragent/python_entrypoint.py'
            launcher_digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
            inputs.append({'source': str(launcher), 'destination': target, 'sha256': launcher_digest})
            script += 'research_agent_hash=$(sha256sum < ' + shlex.quote(target) + ')\n'
            script += '[ "${research_agent_hash%% *}" = ' + shlex.quote(launcher_digest) + ' ] || exit 125\n'
            argv = [target, json.dumps(module_paths), *argv]
        command = python_command(selected["python"]) + [PROBE_DESTINATION,
            json.dumps(_python_request(selected, snapshot["requirements"]), sort_keys=True),
            json.dumps(observation["python"], sort_keys=True), "--", *argv]
    else:
        script += _native_check(selected, observation["files"]["executable"]) + "\n"
        command = list(argv)
    return ["bash", "-c", script + '\nexec "$@"', "execution-guard", *command], inputs
