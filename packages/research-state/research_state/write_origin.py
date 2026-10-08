"""In-process runtime authority. JSON supplied by an agent cannot set it."""
from contextlib import contextmanager
from contextvars import ContextVar

_RUNTIME = ContextVar("research_runtime_write", default=False)


def is_runtime_write():
    return _RUNTIME.get()


@contextmanager
def runtime_write():
    token = _RUNTIME.set(True)
    try:
        yield
    finally:
        _RUNTIME.reset(token)
