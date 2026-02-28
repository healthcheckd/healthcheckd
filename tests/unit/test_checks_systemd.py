"""Tests for systemd unit health check."""

import asyncio
from unittest import mock

import pytest

from healthcheckd.checks.systemd import SystemdCheck


def _make_subprocess_result(stdout: str, returncode: int = 0, stderr: str = ""):
    """Create a mock subprocess result."""
    proc = mock.AsyncMock()
    proc.communicate = mock.AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    proc.returncode = returncode
    return proc


def _closing_timeout(coro, timeout=None):
    """Side effect that closes the coroutine then raises TimeoutError."""
    if hasattr(coro, "close"):
        coro.close()
    raise asyncio.TimeoutError()


class TestSystemdCheck:
    @pytest.fixture
    def check(self):
        return SystemdCheck(
            name="sshd",
            unit="sshd.service",
            expected_states=["running", "enabled"],
        )

    async def test_healthy_when_all_states_present(self, check):
        stdout = (
            "ActiveState=active\n"
            "SubState=running\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True
        assert result.name == "sshd"

    async def test_unhealthy_when_state_missing(self, check):
        stdout = (
            "ActiveState=inactive\n"
            "SubState=dead\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is False
        assert "missing states" in result.detail

    async def test_unhealthy_on_systemctl_error(self, check):
        proc = _make_subprocess_result("", returncode=4, stderr="Unit not found")
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is False
        assert "Error querying unit" in result.detail

    async def test_unhealthy_on_timeout(self):
        check = SystemdCheck(
            name="slow",
            unit="slow.service",
            expected_states=["running"],
            timeout=0.01,
        )
        with mock.patch(
            "healthcheckd.checks.systemd.asyncio.wait_for",
            side_effect=_closing_timeout,
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "Timeout" in result.detail

    async def test_unhealthy_on_oserror(self, check):
        with mock.patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("exec failed"),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "Error querying unit" in result.detail

    async def test_name_property(self, check):
        assert check.name == "sshd"

    async def test_timer_controlled_unit(self):
        """Timer-controlled services only need 'enabled' state."""
        check = SystemdCheck(
            name="backup",
            unit="backup.service",
            expected_states=["enabled"],
        )
        stdout = (
            "ActiveState=inactive\n"
            "SubState=dead\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True

    async def test_handles_empty_values(self, check):
        stdout = (
            "ActiveState=\n"
            "SubState=running\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True

    async def test_passes_correct_args_to_systemctl(self, check):
        stdout = (
            "ActiveState=active\n"
            "SubState=running\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc) as m:
            await check.execute()
        m.assert_called_once_with(
            "/usr/bin/systemctl", "show",
            "--property=ActiveState,SubState,UnitFileState",
            "sshd.service",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={},
        )

    async def test_handles_lines_without_equals(self, check):
        """systemctl output may contain lines without = sign."""
        stdout = (
            "ActiveState=active\n"
            "some garbage line\n"
            "SubState=running\n"
            "\n"
            "UnitFileState=enabled\n"
        )
        proc = _make_subprocess_result(stdout)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True
