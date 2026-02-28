"""Compatibility shim for Python 3.9/3.10 (no stdlib tomllib)."""

import sys

if sys.version_info >= (3, 11):
    from tomllib import load as toml_load
else:  # pragma: no cover
    from tomli import load as toml_load

__all__ = ["toml_load"]
