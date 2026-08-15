# Runtime Environment Contract

TSAgentSkill uses an isolated Conda or Mamba runtime for Python dependencies.
Installing a validated package release does not create the Python environment
automatically.

Keep three roots separate:

- `package_root`: the active versioned release under
  `<installation>/.pi/packages/ts-agent/current`.
- `workspace_root`: the TS research workspace that owns state and runtime
  metadata.
- `runtime_home`: the directory that stores the runtime manifest.

The environment spec lives in the package:

```text
<package_root>/environment.yml
```

With `--workspace-root` or `TS_WORKSPACE_ROOT`, the resolver's default runtime
locations are workspace-owned:

```text
<workspace_root>/.agents/runtime/transition-state-workflow/env.json
<workspace_root>/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

This keeps runtime state out of immutable release directories.

The installation-level `TSPi` launcher deliberately supplies all three runtime
overrides through its Python host so concurrent research workspaces reuse one
validated environment:

```text
<installation>/.agents/runtime/transition-state-workflow/env.json
<installation>/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

`TS_WORKSPACE_ROOT` still points to the selected research directory. Runtime
sharing does not merge sessions, canonical workspace files, workspace identity,
compute control records, or reports. The installation manifest and environment
are immutable dependencies from the research workspace's perspective.

When no workspace root or runtime override is supplied, source checkouts fall
back to package-parent stores:

```text
<package_parent>/.runtime/transition-state-workflow/env.json
<package_parent>/.envs/transition-state-workflow/<environment-spec-hash>/
```

Legacy manifests at `<package_root>/.runtime/env.json` are read only when no
explicit `workspace_root`, `runtime_home`, or manifest override is supplied.
They are compatibility input, not the target for new installs.

Override points:

- `TS_WORKSPACE_ROOT`: selected research workspace; it owns runtime files only
  when the runtime-specific overrides below are absent.
- `TS_AGENT_RUNTIME_HOME`: alternate directory for `env.json`.
- `TS_AGENT_RUNTIME_MANIFEST`: exact manifest path.
- `TS_AGENT_ENV_ROOT`: alternate hashed environment store.
- `TS_AGENT_CONDA_EXE`: explicit Conda or Mamba executable for installation.
- `TS_AGENT_CONDA_ROOT`: root directory of an existing Conda or Mamba
  installation, such as `/opt/miniforge3`.
- `TS_AGENT_PYTHON`: absolute executable path used as an explicit interpreter
  override for runtime execution.
- `TS_AGENT_DISABLE_RUNTIME_REEXEC=1`: disable script self-reexec for tests.

Install or refresh the runtime with explicit package and workspace roots:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/TSPi-installation/.pi/packages/ts-agent/current
export TS_WORKSPACE_ROOT=/path/to/TSPi-installation/workspaces/reaction-a
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --workspace-root "$TS_WORKSPACE_ROOT" \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

For a core workflow-only environment, omit `--with-render`.

Public scripts call `ts_runtime.ensure_runtime_python()` before importing
workflow modules. The Pi extension calls
`scripts/ts_runtime.py resolve --workspace-root <workspace> --json` and uses
the interpreter reported by the same Python resolver.

Runtime helpers must not mutate workspace state files, start or close nodes, or
interpret chemistry.

`--with-render` installs `xyzrender` into the isolated runtime. `ts_render
diagnostic` reports only `xyzrender` availability; Blender, FFmpeg, OpenBabel,
Mayavi, and PyVista are not TSAgentSkill render dependencies.
