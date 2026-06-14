#!/usr/bin/env python3
"""Compatibility re-export for the TS hypothesis workspace CLI."""
from transition_state_workflow.cli.hypothesis_workspace import *  # noqa: F401,F403
if __name__ == "__main__":
    raise SystemExit(main())
