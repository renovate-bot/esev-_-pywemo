"""Atheris stub for platforms were it is unsupported."""
# flake8: noqa
import contextlib

try:
    from atheris import *
except ImportError:

    @contextlib.contextmanager
    def instrument_imports():
        yield
