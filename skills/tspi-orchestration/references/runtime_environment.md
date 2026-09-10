# Runtime Environment Contract

TSPi uses one installation-owned, hash-addressed Python environment shared by
workspaces. It does not use the shell's current Conda environment or install
dependencies into shared `base`.

`scripts/install_env.py` binds package root, environment-spec digest,
interpreter, optional render dependencies, runtime manifest, and environment
prefix. A formal release contains one manifest-bound `ts-agent-kernel` wheel;
the installer revalidates and installs that wheel without building in the
read-only release. An authored checkout instead builds the wheel in a temporary
copy. Both paths record a digest of all installed modules and package data.
RDKit and a compatible NumPy range are core dependencies. Before writing the
runtime manifest, the installer proves NumPy/RDKit imports, SMILES parsing,
fixed-seed ETKDG embedding, and UFF optimization, recording versions and module
origins. `packages/ts-agent-kernel/ts_agent/runtime/launcher.py` accepts the manifest only when
the source and installed distribution digests still match.

Research workspaces contain state and artifacts only; they do not contain the
Python environment. Immutable releases contain source but no `node_modules`,
credentials, sessions, or generated env.

TSPi exports the manifest-selected interpreter as `TS_AGENT_PYTHON`, prepends
its `bin` to `PATH`, disables user site packages, and clears `PYTHONHOME` for
the Pi process tree. It never falls back to system Python.

When diagnosing failure, check release, Python payload digest, manifest, spec
digest, interpreter, probe module origins, and optional renderer separately.
Reinstall the selected release into the hash-addressed environment rather than
modifying it ad hoc.
