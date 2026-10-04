---
name: script
description: Run bounded shell scripts through the auditable Compute lifecycle with declared inputs and outputs.
---

# Script Compute

Use this Skill with `script.bash@1` through `compute_run` when a validated shell script needs
the durable Attempt, Artifact and provenance lifecycle. The script is an
immutable input Artifact. Pass arguments as an array and declare output
basenames in `output_manifest`; `script_result.json` is required for parsing.

The script runs in the local compute environment and cannot write Research
State directly. Read its output, then submit scientific facts through the
normal Research State operation.
