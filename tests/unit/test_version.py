"""Tests for healthcheckd version and package structure."""

import re


def test_version_is_importable():
    from healthcheckd import __version__

    assert __version__ is not None


def test_version_is_semver():
    from healthcheckd import __version__

    assert re.match(r"^\d+\.\d+\.\d+(-.*)?$", __version__)
