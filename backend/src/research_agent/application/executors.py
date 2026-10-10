"""Prepare installed execution descriptors without running science or writing State.

The manifest owns method-specific argv, inputs, outputs and the pure CLI parser.
The Job configuration owns target commands and interpreters. Only job.start may
turn the resulting reviewed file into a prepared reference and an Attempt.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

from research_agent.jobs.config_contract import binding_digest, load_job_config, resolve_binding
from research_agent.jobs.environment import probe_binding, guarded_command
from research_agent.jobs.inputs import content_digest
from research_agent.application.execution_catalog import installed_catalogs


def registered_executor(identifier, version):
    from .execution_catalog import registered_entry
    return registered_entry("executors", identifier, version)


def list_recipes(*, executor=None, version=None, backend=None, skill=None, details=False,
                 config=None, environment=None):
    """Index preparation shortcuts, independently of scientific capability."""
    settings = load_job_config(config) if config else None
    if bool(config) != bool(environment):
        raise ValueError("recipe_list_requires_config_and_environment_together")
    if settings and environment not in settings['environments']:
        raise ValueError("execution_environment_not_configured")
    recipes = []
    for catalog in installed_catalogs():
        for entry in catalog['executors']:
            if any(value is not None and entry.get(key) != value for key, value in
                   [('id', executor), ('version', version), ('backend', backend), ('skill', skill)]):
                continue
            row = copy.deepcopy(entry) if details else {
                key: entry[key] for key in ('id', 'version', 'skill', 'backend', 'runtime', 'inputs') if key in entry}
            if settings:
                row['binding_status'] = ('configured' if entry['backend'] in
                    settings['environments'][environment].get('backends', {}) else 'not_configured')
            recipes.append(row)
    return {'scope': 'predefined_recipes', 'software_availability': 'not_checked',
            **({'environment': environment} if environment else {}), 'recipes': recipes}


def _load_cli(base, descriptor):
    # Catalog verification pins this standard-library-only contract; never
    # import the scientific entrypoint in the control interpreter.
    spec = importlib.util.spec_from_file_location("research_agent_executor_cli", base / descriptor['cli'])
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def print_runner_help(executor, version):
    base, descriptor = registered_executor(executor, version)
    print(f"Recipe: {executor}@{version}; backend: {descriptor['backend']}")
    print('Managed argv template: ' + json.dumps(descriptor['argv']))
    print('Provide input roles with preparer --input role=file: ' + json.dumps(descriptor['inputs']))
    print('Pass other runner arguments after --. The preparer supplies fixed input/output/executable flags.')
    if not descriptor.get('cli'):
        print('No bundled CLI help; consult the method Skill or native program documentation.')
        return
    try:
        _load_cli(base, descriptor).parse_arguments(['--help'])
    except SystemExit as exc:
        if exc.code != 0:
            raise


def _relative(value):
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError("executor_destination_invalid: use a relative Job path")
    if path.parts[0] in {"spec.json", "receipt.json", "status.json", "input_manifest.json", "logs", ".research-agent"}:
        raise ValueError("executor_destination_reserved")
    return path


def _validate_forwarded_arguments(template, arguments):
    reserved = {token.split("=", 1)[0] for token in template if token.startswith("-")} | {"--help", "-h"}
    if any(arg.startswith("-") and any(flag.startswith(arg.split("=", 1)[0]) for flag in reserved) for arg in arguments):
        raise ValueError("executor_argument_reserved: fixed arguments are owned by the execution descriptor")


def validate_prepared_entry(params, descriptor):
    """An environment observation cannot authorize a different method or binary."""
    metadata = params['metadata']
    selected = metadata['execution_binding']
    argv = metadata['execution_argv']
    command = selected['binding'].get('command', [])
    command = [command] if isinstance(command, str) else command
    replacements = {'{entry}': [descriptor.get('entry', '')], '{command}': command, '{executable}': command,
                    **{f'{{input:{role}}}': [path] for role, path in descriptor['inputs'].items()}}
    template = descriptor['argv']
    index = template.index('{args}') if '{args}' in template else len(template)
    def expand(tokens):
        return [part for token in tokens for part in replacements.get(token, [token])]
    before, after = expand(template[:index]), expand(template[index + 1:])
    end = len(argv) - len(after)
    if (len(argv) < len(before) + len(after) or argv[:len(before)] != before or argv[end:] != after
            or index == len(template) and len(argv) != len(before)):
        raise ValueError('executor_command_mismatch')
    _validate_forwarded_arguments(template, argv[len(before):end])
    resources = descriptor['resources']
    if metadata.get('resources_sha256') != resources:
        raise ValueError('executor_resources_mismatch')
    inputs = {row['destination']: row for row in params.get('inputs', []) if isinstance(row, dict)}
    for path, digest in resources.items():
        if inputs.get(path, {}).get('sha256') != digest.removeprefix('sha256:'):
            raise ValueError('executor_resource_input_missing')
    if any(path not in inputs for path in descriptor['inputs'].values()):
        raise ValueError('executor_role_input_missing')
    expected_roles = {role: {'destination': path, 'sha256': 'sha256:' + inputs[path]['sha256']}
                      for role, path in descriptor['inputs'].items()}
    if metadata.get('input_roles', expected_roles) != expected_roles:
        raise ValueError('executor_input_roles_mismatch')
    if any(output not in params.get('outputs', []) for output in descriptor['outputs']):
        raise ValueError('executor_output_contract_changed')


def prepare(config, environment, executor, version, inputs, arguments=(), *, dependencies=(), collect=(), work_id=None, input_artifact_ids=()):
    base, descriptor = registered_executor(executor, version)
    return _prepare(config, environment, base, descriptor, descriptor["resources"], inputs, arguments,
                    dependencies=dependencies, collect=collect, work_id=work_id, input_artifact_ids=input_artifact_ids)


def prepare_script(config, environment, backend, script, arguments=(), *, dependencies=(), collect=(), work_id=None, input_artifact_ids=()):
    """Pin a task-specific Python script without inventing an installed method."""
    script = Path(script).expanduser().resolve()
    if not script.is_file() or script.suffix != ".py":
        raise ValueError("execution_script_invalid: provide an existing Python script")
    descriptor = {"backend": backend, "runtime": "python", "entry": script.name,
                  "argv": ["{entry}", "{args}"], "inputs": {}, "outputs": []}
    return _prepare(config, environment, script.parent, descriptor, {script.name: "sha256:" + content_digest(script)},
                    {}, arguments, dependencies=dependencies, collect=collect, work_id=work_id, input_artifact_ids=input_artifact_ids)


def _prepare(config, environment, base, descriptor, resources, inputs, arguments, *, dependencies, collect, work_id, input_artifact_ids):
    settings = load_job_config(config)
    selected = resolve_binding(settings, environment, descriptor["backend"], runtime=descriptor["runtime"])
    binding, python, submission = selected["binding"], selected["python"], selected["submission"]
    if not isinstance(inputs, dict) or set(inputs) != set(descriptor["inputs"]):
        raise ValueError("executor_inputs_invalid: provide exactly the declared input roles")
    if not isinstance(arguments, (list, tuple)) or any(not isinstance(arg, str) or "\0" in arg for arg in arguments):
        raise ValueError("executor_arguments_invalid: arguments must be argv strings")
    if (not isinstance(input_artifact_ids, (list, tuple)) or any(not isinstance(ref, str) or not ref for ref in input_artifact_ids)
            or len(set(input_artifact_ids)) != len(input_artifact_ids)):
        raise ValueError("executor_input_artifacts_invalid")
    command = binding.get("command", [])
    command = [command] if isinstance(command, str) else command
    template = descriptor["argv"]
    if arguments and "{args}" not in template:
        raise ValueError("executor_arguments_invalid: this entry has no forwarded arguments")
    uses_command = "{command}" in template or "{executable}" in template
    if uses_command and not command:
        raise ValueError("executor_command_missing")
    if "{executable}" in template and len(command) != 1:
        raise ValueError("executor_command_invalid: this wrapper requires one executable")
    if not uses_command and command:
        raise ValueError("executor_binding_unused_command: the selected Python binding is the sole interpreter")
    staged = []
    destinations = set()

    def stage(source, destination, expected=None):
        destination_path = _relative(destination)
        if any(destination_path == item or destination_path in item.parents or item in destination_path.parents for item in destinations):
            raise ValueError("executor_input_destinations_overlap")
        source = Path(source).expanduser().resolve()
        if not source.exists():
            raise ValueError("executor_input_missing: " + str(source))
        digest = content_digest(source)
        if expected is not None and expected != "sha256:" + digest:
            raise ValueError("executor_resource_changed: installed resource differs from the verified catalog")
        destinations.add(destination_path)
        staged.append({"source": str(source), "destination": destination, "sha256": digest})

    for path, expected in sorted(resources.items()):
        source = (base / path).resolve()
        if not source.is_relative_to(base) or not source.is_file():
            raise ValueError("executor_resource_invalid")
        stage(source, path, expected)
    for role, destination in descriptor["inputs"].items():
        stage(inputs[role], destination)
    for dependency in dependencies:
        source, separator, destination = dependency.partition("=")
        if not separator:
            raise ValueError("executor_dependency_invalid: use source=destination")
        stage(source, destination)
    outputs = copy.deepcopy(descriptor["outputs"])
    for path in collect:
        _relative(path)
        if any(row["path"] == path for row in outputs):
            raise ValueError("executor_output_duplicate")
        outputs.append({"path": path, "required": True, "min_bytes": 1})
    # Fixed flags are part of the descriptor. Arguments cannot replace its
    # input, output or executable after those were reviewed and pinned.
    _validate_forwarded_arguments(template, arguments)
    argv = []
    substitutions = {"{args}": list(arguments), "{command}": command, "{executable}": command,
                     "{entry}": [descriptor.get("entry", "")],
                     **{f"{{input:{role}}}": [path] for role, path in descriptor["inputs"].items()}}
    for token in template:
        argv.extend(substitutions.get(token, [token]))
    if descriptor.get("cli"):
        cli = _load_cli(base, descriptor)
        diagnostic = io.StringIO()
        try:
            with contextlib.redirect_stderr(diagnostic):
                cli.parse_arguments(argv[1:] if descriptor["runtime"] == "python" else argv[len(command):])
        except SystemExit as exc:
            raise ValueError("runner_arguments_invalid: " + diagnostic.getvalue().strip()) from exc
    execution_argv = list(argv)
    environment_evidence = probe_binding(settings, selected, descriptor.get("requirements", {}))
    module_paths = descriptor.get('module_paths')
    argv, guard_inputs = guarded_command(selected, execution_argv, environment_evidence, module_paths=module_paths)
    staged.extend(guard_inputs)
    configuration = binding_digest(selected)
    identity = binding_digest({"executor": descriptor, "configuration": configuration, "environment": environment_evidence,
        "resources": resources, "arguments": arguments, "outputs": outputs, "input_artifact_ids": input_artifact_ids,
        "inputs": {row["destination"]: row["sha256"] for row in staged}})[7:]
    work_id = work_id or "work_" + identity[:48]
    if not isinstance(work_id, str) or not work_id:
        raise ValueError("work_id_invalid")
    return {"request_id": "executor_" + hashlib.sha256(work_id.encode()).hexdigest()[:48],
            "work_id": work_id, "command": argv, "platform": environment,
            "inputs": staged, "outputs": outputs, "environment": binding.get("environment", {}),
            **({"input_artifact_ids": list(input_artifact_ids)} if input_artifact_ids else {}),
            "metadata": {**submission,
                         **({"executor": {"id": descriptor["id"], "version": descriptor["version"]}, **({"skill": descriptor["skill"]} if "skill" in descriptor else {})}
                            if descriptor.get("id") else {"script": {"entry": descriptor["entry"], "sha256": resources[descriptor["entry"]]}}),
                         "resources_sha256": resources, "configuration_sha256": configuration,
                         "execution_binding": selected, "execution_environment": environment_evidence, "execution_argv": execution_argv,
                         **({'module_paths': module_paths} if module_paths is not None else {}),
                         'input_roles': {role: {'destination': destination,
                             'sha256': 'sha256:' + next(row['sha256'] for row in staged if row['destination'] == destination)}
                             for role, destination in descriptor['inputs'].items()},
                         **({"python_binding": python} if python else {})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False, add_help=False)
    parser.add_argument("-h", "--help", action="store_true", help="Show preparer help, or the selected executor's runner help")
    parser.add_argument("--list", action="store_true", help="List predefined recipes; this is not a software availability check")
    parser.add_argument("--details", action="store_true", help="Include full descriptors with --list")
    parser.add_argument("--skill", help="Filter --list by associated Skill")
    parser.add_argument("--config")
    parser.add_argument("--environment")
    parser.add_argument("--executor")
    parser.add_argument("--version")
    parser.add_argument("--script", help="Pin a task-specific Python script instead of an installed executor")
    parser.add_argument("--backend", help="Named Python backend for --script, or backend filter for --list")
    parser.add_argument("--input", action="append", default=[], help="role=source path")
    parser.add_argument("--input-artifact", action="append", default=[], help="Registered input Artifact id or reference, whose bytes must be staged")
    parser.add_argument("--dependency", action="append", default=[], help="source=relative Job destination")
    parser.add_argument("--collect", action="append", default=[], help="Additional required relative Job output")
    parser.add_argument("--work-id", help="New identity for an intentional recalculation")
    parser.add_argument("--output", help="Save a request and print its file/digest for job_start")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.help:
        if args.executor:
            if not args.version:
                parser.error("selected runner help requires --executor and --version")
            print_runner_help(args.executor, args.version)
        else:
            parser.print_help()
        return
    if args.list:
        print(json.dumps(list_recipes(executor=args.executor, version=args.version, backend=args.backend,
            skill=args.skill, details=args.details, config=args.config, environment=args.environment), indent=2))
        return
    if args.details or args.skill:
        parser.error("--details and --skill require --list")
    if not args.config or not args.environment:
        parser.error("--config and --environment are required")
    if args.script:
        if not args.backend or args.executor or args.version or args.input:
            parser.error("--script requires --backend; do not combine it with executor/version/input")
    elif not args.executor or not args.version or args.backend:
        parser.error("--executor and --version are required; --backend is only for task-specific scripts")
    inputs = {}
    for item in args.input:
        role, separator, source = item.partition("=")
        if not separator or role in inputs or not source:
            parser.error("--input must be a unique role=source path")
        inputs[role] = source
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    options = {"dependencies": args.dependency, "collect": args.collect, "work_id": args.work_id, "input_artifact_ids": args.input_artifact}
    request = (prepare_script(args.config, args.environment, args.backend, args.script, arguments, **options)
               if args.script else prepare(args.config, args.environment, args.executor, args.version, inputs, arguments, **options))
    encoded = (json.dumps(request, indent=2) + "\n").encode()
    if args.output:
        path = Path(args.output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        print(json.dumps({"request_file": str(path), "request_sha256": hashlib.sha256(encoded).hexdigest()}))
    else:
        print(encoded.decode(), end="")


if __name__ == "__main__":
    main()
