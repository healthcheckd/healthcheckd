"""Tests for file existence and age health check."""

import os
import time
from unittest import mock

import pytest

from healthcheckd.checks.file import FileCheck


class TestFileCheck:
    async def test_healthy_when_file_exists(self, tmp_path):
        f = tmp_path / "heartbeat"
        f.write_text("alive")
        check = FileCheck(name="hb", path=str(f))
        result = await check.execute()
        assert result.healthy is True
        assert "exists" in result.detail

    async def test_unhealthy_when_file_missing(self):
        check = FileCheck(name="hb", path="/nonexistent/heartbeat")
        result = await check.execute()
        assert result.healthy is False
        assert "not accessible" in result.detail

    async def test_healthy_when_file_within_max_age(self, tmp_path):
        f = tmp_path / "heartbeat"
        f.write_text("alive")
        check = FileCheck(name="hb", path=str(f), max_age=60)
        result = await check.execute()
        assert result.healthy is True

    async def test_unhealthy_when_file_too_old(self, tmp_path):
        f = tmp_path / "heartbeat"
        f.write_text("alive")
        check = FileCheck(name="hb", path=str(f), max_age=60)

        # Mock time to make file appear old
        with mock.patch("healthcheckd.checks.file.time.time", return_value=time.time() + 120):
            result = await check.execute()

        assert result.healthy is False
        assert "old" in result.detail

    async def test_no_age_check_when_max_age_zero(self, tmp_path):
        f = tmp_path / "heartbeat"
        f.write_text("alive")
        check = FileCheck(name="hb", path=str(f), max_age=0)
        result = await check.execute()
        assert result.healthy is True

    async def test_unhealthy_on_permission_error(self):
        check = FileCheck(name="hb", path="/root/secret")
        with mock.patch(
            "healthcheckd.checks.file.os.stat",
            side_effect=PermissionError("Permission denied"),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "not accessible" in result.detail

    async def test_name_property(self):
        check = FileCheck(name="hb", path="/tmp/test")
        assert check.name == "hb"
