# Runtime Environment Contract

TSPi uses one installation-owned, hash-addressed Python environment shared by
workspaces. It does not use the shell's current Conda environment or install
dependencies into shared `base`.

`scripts/install_env.py` binds package root, environment specification digest,
interpreter, optional render dependencies, runtime manifest, and environment
prefix. `ts_runtime/launcher.py` resolves and verifies that manifest before
workflow imports.

Research workspaces contain state and artifacts only; they do not contain the
Python environment. Immutable releases contain source but no `node_modules`,
credentials, sessions, or generated env.

When diagnosing runtime failure, check the selected release, runtime manifest,
environment spec digest, interpreter existence, package import root, and
optional renderer separately. Reinstall the hash-addressed environment through
the installer rather than modifying it ad hoc.
