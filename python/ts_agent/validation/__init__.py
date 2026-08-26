"""Declarative, digest-bound scientific validation for TS research."""

from .compiler import GateSpecCompileError, compile_gate_spec
from .engine import ValidationEngineError, evaluate_gate_spec
from .registry import (
    PredicateRegistry,
    RegistryError,
    builtin_predicate_registry,
    load_acceptance_profile,
    load_gate_template,
)

__all__ = [
    "GateSpecCompileError",
    "PredicateRegistry",
    "RegistryError",
    "ValidationEngineError",
    "builtin_predicate_registry",
    "compile_gate_spec",
    "evaluate_gate_spec",
    "load_acceptance_profile",
    "load_gate_template",
]
