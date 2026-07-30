# Runtime Environment Contract

TSAgentSkill uses an isolated Conda or Mamba runtime for Python dependencies.
Package installation only registers or fetches the skill package; it does not
create the Python environment automatically.

Keep three roots separate:

- `package_root`: the skill code checkout or installed copy. This may be a
  Codex `.agents/skills` tree, a Pi `.pi/git` checkout, or a development tree.
- `workspace_root`: the TS research workspace that owns state and runtime
  metadata.
- `runtime_home`: the directory that stores the runtime manifest.

The environment spec lives in the package:

```text
<package_root>/environment.yml
```

With `--workspace-root` or `TS_WORKSPACE_ROOT`, the default runtime locations
are workspace-owned:

```text
<workspace_root>/.agents/runtime/transition-state-workflow/env.json
<workspace_root>/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

This is the preferred Codex and Pi contract. It keeps runtime state out of Pi
Git package checkouts, which may be reset or cleaned during package updates,
and it keeps local Pi path installs from reusing a development-tree runtime.

When no workspace root or runtime override is supplied, installed Codex copies
under `.agents/skills` use:

```text
<workspace_root>/.agents/runtime/transition-state-workflow/env.json
<workspace_root>/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

Other source checkouts fall back to package-parent stores:

```text
<package_parent>/.runtime/transition-state-workflow/env.json
<package_parent>/.envs/transition-state-workflow/<environment-spec-hash>/
```

Legacy manifests at `<package_root>/.runtime/env.json` are read only when no
explicit `workspace_root`, `runtime_home`, or manifest override is supplied.
They are compatibility input, not the target for new installs.

Override points:

- `TS_WORKSPACE_ROOT`: workspace root that owns `.agents/runtime` and
  `.agents/envs`.
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
export TS_AGENT_SKILL_ROOT=/path/to/transition-state-workflow
export TS_WORKSPACE_ROOT=/path/to/ts-workspace
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
