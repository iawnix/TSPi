"""Declarative, digest-bound scientific validation for TS research."""

from .compiler import ProofSpecCompileError, compile_proof_spec
from .engine import ValidationEngineError, evaluate_proof_spec
from .registry import (
    PredicateRegistry,
    RegistryError,
    builtin_predicate_registry,
    load_acceptance_profile,
    load_proof_template,
)

__all__ = [
    "ProofSpecCompileError",
    "PredicateRegistry",
    "RegistryError",
    "ValidationEngineError",
    "builtin_predicate_registry",
    "compile_proof_spec",
    "evaluate_proof_spec",
    "load_acceptance_profile",
    "load_proof_template",
]
