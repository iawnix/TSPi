"""Finalizers that update read ledgers after node closure."""

from .node import finalize_closed_node

__all__ = ["finalize_closed_node"]
