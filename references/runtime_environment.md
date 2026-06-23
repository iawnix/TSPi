# Runtime Environment Contract

TSAgentSkill uses an isolated Conda runtime for Python dependencies.

The environment spec lives at:

```text
environment.yml
```

The installer writes a runtime manifest:

```text
.runtime/env.json
```

The Conda prefix is stored outside the skill source tree by default. If the
package is installed below a workspace `.agents` directory and that directory
is writable, the store is:

```text
<workspace>/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

If `.agents` is read-only or the package is not installed below `.agents`, the
fallback store is:

```text
<package-parent>/.envs/transition-state-workflow/<environment-spec-hash>/
```

Override points:

- `TS_AGENT_ENV_ROOT`: alternate hashed environment store.
- `TS_AGENT_CONDA_EXE`: explicit Conda or Mamba executable for installation.
- `TS_AGENT_CONDA_ROOT`: root directory of an existing Conda or Mamba
  installation, such as `/opt/miniforge3`.
- `TS_AGENT_PYTHON`: explicit interpreter override for runtime execution.
- `TS_AGENT_DISABLE_RUNTIME_REEXEC=1`: disable script self-reexec for tests.

Public scripts call `ts_runtime.ensure_runtime_python()` before importing
workflow modules. The Pi extension reads `.runtime/env.json` and executes the
recorded interpreter when present.

Runtime helpers must not mutate workspace ledgers, start or close nodes, or
interpret chemistry.

Package installation does not create a Conda environment automatically. Users
must provide or expose an existing Conda/Mamba installation and run the
environment installer explicitly:

```bash
python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json
```

For a core workflow-only environment, run:

```bash
python scripts/install_env.py --conda-root /path/to/miniforge3 --json
```

`--with-render` installs `xyzrender` into the isolated runtime. `ts_render
diagnostic` reports only `xyzrender` availability; Blender, FFmpeg, OpenBabel,
Mayavi, and PyVista are not TSAgentSkill render dependencies.
