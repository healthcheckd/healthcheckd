"""Tests for disk space health check."""

import os
from unittest import mock

import pytest

from healthcheckd.checks.disk import DiskCheck


def _make_statvfs(f_blocks: int, f_bavail: int):
    """Create a mock statvfs result."""
    result = mock.Mock()
    result.f_blocks = f_blocks
    result.f_bavail = f_bavail
    return result


class TestDiskCheck:
    async def test_healthy_when_enough_space(self):
        check = DiskCheck(name="root", path="/", min_free_percent=10)
        # 50% free
        with mock.patch(
            "healthcheckd.checks.disk.os.statvfs",
            return_value=_make_statvfs(1000, 500),
        ):
            result = await check.execute()
        assert result.healthy is True
        assert "50.0% free" in result.detail

    async def test_unhealthy_when_low_space(self):
        check = DiskCheck(name="root", path="/", min_free_percent=20)
        # 5% free
        with mock.patch(
            "healthcheckd.checks.disk.os.statvfs",
            return_value=_make_statvfs(1000, 50),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "5.0% free" in result.detail
        assert "minimum 20.0%" in result.detail

    async def test_exactly_at_threshold(self):
        check = DiskCheck(name="root", path="/", min_free_percent=10)
        # Exactly 10% free
        with mock.patch(
            "healthcheckd.checks.disk.os.statvfs",
            return_value=_make_statvfs(1000, 100),
        ):
            result = await check.execute()
        assert result.healthy is True

    async def test_unhealthy_on_oserror(self):
        check = DiskCheck(name="root", path="/nonexistent", min_free_percent=10)
        with mock.patch(
            "healthcheckd.checks.disk.os.statvfs",
            side_effect=OSError("No such file or directory"),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "Cannot stat filesystem" in result.detail

    async def test_unhealthy_on_zero_blocks(self):
        check = DiskCheck(name="root", path="/", min_free_percent=10)
        with mock.patch(
            "healthcheckd.checks.disk.os.statvfs",
            return_value=_make_statvfs(0, 0),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "0 total blocks" in result.detail

    async def test_name_property(self):
        check = DiskCheck(name="root", path="/", min_free_percent=10)
        assert check.name == "root"
