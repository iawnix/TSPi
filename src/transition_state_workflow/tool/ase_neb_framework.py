#!/usr/bin/env python3
"""Compatibility re-export for the ASE NEB framework CLI."""
from transition_state_workflow.cli.ase_neb_framework import *  # noqa: F401,F403
if __name__ == "__main__":
    raise SystemExit(main())
