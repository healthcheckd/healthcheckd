"""Tests for Python compatibility shims."""

import io
import sys


def test_toml_load_parses_valid_toml():
    from healthcheckd.compat import toml_load

    data = b'[section]\nkey = "value"\nnumber = 42\n'
    result = toml_load(io.BytesIO(data))
    assert result == {"section": {"key": "value", "number": 42}}


def test_toml_load_handles_nested_tables():
    from healthcheckd.compat import toml_load

    data = b'[server]\nport = 9990\nbind = "0.0.0.0"\n'
    result = toml_load(io.BytesIO(data))
    assert result["server"]["port"] == 9990
    assert result["server"]["bind"] == "0.0.0.0"


def test_toml_load_uses_stdlib_on_311_plus():
    """Verify that on Python 3.11+, we use stdlib tomllib."""
    if sys.version_info >= (3, 11):
        from healthcheckd.compat import toml_load
        import tomllib

        assert toml_load is tomllib.load


def test_compat_module_exports():
    """Verify __all__ is defined and contains expected exports."""
    from healthcheckd import compat

    assert "toml_load" in compat.__all__
