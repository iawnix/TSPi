# Runtime Environment Contract

TSPi uses an installation-managed Python runtime shared by workspaces: a
hash-addressed Conda environment for scientific dependencies and a venv for the
selected kernel wheel.

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

Research workspaces store state and artifacts. The installation runtime store
holds Python environments, and release directories hold versioned program files.

TSPi exports the manifest-selected interpreter as `TS_AGENT_PYTHON`, prepends
its `bin` to `PATH`, disables user site packages, and clears `PYTHONHOME` for
the Pi process tree. A missing or invalid runtime is repaired through the installer.

When diagnosing failure, check release, Python payload digest, manifest, spec
digest, interpreter, probe module origins, and optional renderer separately.
Reinstall the selected release into the hash-addressed environment rather than
modifying it ad hoc.
