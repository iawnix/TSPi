"""Installer access to the same dependency-free layout contract as bootstrap."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend/src'))
from research_agent.foundation.layout import AppLayout, SCHEMA, inspect_installation, paths
