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
workspace `.agents` directory is writable, the store is:

```text
/home/iaw/TS/.agents/envs/transition-state-workflow/<environment-spec-hash>/
```

If `.agents` is read-only, the fallback store is:

```text
/home/iaw/TS/.envs/transition-state-workflow/<environment-spec-hash>/
```

Override points:

- `TS_AGENT_ENV_ROOT`: alternate hashed environment store.
- `TS_AGENT_CONDA_EXE`: explicit Conda or Mamba executable for installation.
- `TS_AGENT_PYTHON`: explicit interpreter override for runtime execution.
- `TS_AGENT_DISABLE_RUNTIME_REEXEC=1`: disable script self-reexec for tests.

Public scripts call `ts_runtime.ensure_runtime_python()` before importing
workflow modules. The Pi extension reads `.runtime/env.json` and executes the
recorded interpreter when present.

Runtime helpers must not mutate workspace ledgers, start or close nodes, or
interpret chemistry.

The package `postinstall` script requests render backend packages as well:

```bash
python scripts/install_env.py --with-render --json
```

For a core workflow-only environment, run:

```bash
python scripts/install_env.py --json
```

`ts_render diagnostic` remains the source of truth for whether `xyzrender`,
Blender, FFmpeg, and OpenBabel are available on the active machine.
