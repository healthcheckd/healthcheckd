"""Tests for command execution health check."""

import asyncio
import signal
from unittest import mock

import pytest

from healthcheckd.checks.run import (
    RunCheck,
    check_exit_code,
    parse_expected_result,
)


def _closing_timeout(coro, timeout=None):
    """Side effect that closes the coroutine then raises TimeoutError."""
    if hasattr(coro, "close"):
        coro.close()
    raise asyncio.TimeoutError()


class TestParseExpectedResult:
    def test_single_zero(self):
        negated, values = parse_expected_result("0")
        assert negated is False
        assert values == {0}

    def test_single_nonzero(self):
        negated, values = parse_expected_result("1")
        assert negated is False
        assert values == {1}

    def test_negation(self):
        negated, values = parse_expected_result("!0")
        assert negated is True
        assert values == {0}

    def test_csv_values(self):
        negated, values = parse_expected_result("0,1,2,3")
        assert negated is False
        assert values == {0, 1, 2, 3}

    def test_strips_whitespace(self):
        negated, values = parse_expected_result("  0 , 1  ")
        assert values == {0, 1}


class TestCheckExitCode:
    def test_match_exact(self):
        assert check_exit_code(0, False, {0}) is True

    def test_no_match_exact(self):
        assert check_exit_code(1, False, {0}) is False

    def test_match_set(self):
        assert check_exit_code(2, False, {0, 1, 2}) is True

    def test_negated_match(self):
        assert check_exit_code(1, True, {0}) is True

    def test_negated_no_match(self):
        assert check_exit_code(0, True, {0}) is False


def _make_subprocess(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    """Create a mock async subprocess."""
    proc = mock.Mock()
    proc.returncode = returncode
    proc.stdout = mock.Mock()
    proc.stdout.read = mock.AsyncMock(return_value=stdout)
    proc.stderr = mock.Mock()
    proc.stderr.read = mock.AsyncMock(return_value=stderr)
    proc.wait = mock.AsyncMock(return_value=None)
    proc.send_signal = mock.Mock()
    proc.kill = mock.Mock()
    return proc


class TestRunCheck:
    @pytest.fixture
    def check(self):
        return RunCheck(
            name="mycheck",
            command=["/bin/true"],
            expected_result="0",
        )

    async def test_healthy_when_exit_code_matches(self, check):
        proc = _make_subprocess(0)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True
        assert result.name == "mycheck"
        assert "Exit code: 0" in result.detail

    async def test_unhealthy_when_exit_code_mismatches(self):
        check = RunCheck(
            name="fail", command=["/bin/false"], expected_result="0"
        )
        proc = _make_subprocess(1)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is False

    async def test_negation_healthy(self):
        check = RunCheck(
            name="not-zero", command=["/bin/false"], expected_result="!0"
        )
        proc = _make_subprocess(1)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True

    async def test_negation_unhealthy(self):
        check = RunCheck(
            name="not-zero", command=["/bin/true"], expected_result="!0"
        )
        proc = _make_subprocess(0)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is False

    async def test_csv_expected_result(self):
        check = RunCheck(
            name="multi", command=["/usr/bin/test"], expected_result="0,1,2"
        )
        proc = _make_subprocess(2)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await check.execute()
        assert result.healthy is True

    async def test_timeout_kills_process(self):
        check = RunCheck(
            name="slow", command=["/bin/sleep", "100"], timeout=0.01
        )
        proc = _make_subprocess(0)

        with mock.patch("asyncio.create_subprocess_exec", return_value=proc):
            with mock.patch(
                "healthcheckd.checks.run.asyncio.wait_for",
                side_effect=_closing_timeout,
            ):
                result = await check.execute()

        assert result.healthy is False
        assert "timed out" in result.detail

    async def test_oserror_on_exec(self, check):
        with mock.patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("No such file"),
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "Failed to execute" in result.detail

    async def test_name_property(self, check):
        assert check.name == "mycheck"

    async def test_passes_empty_env(self, check):
        proc = _make_subprocess(0)
        with mock.patch("asyncio.create_subprocess_exec", return_value=proc) as m:
            await check.execute()
        _, kwargs = m.call_args
        assert kwargs["env"] == {}

    async def test_kill_process_sigterm_then_wait(self):
        check = RunCheck(name="test", command=["/bin/true"])
        proc = _make_subprocess(0)

        async def fake_wait_for(coro, timeout):
            return await coro

        with mock.patch(
            "healthcheckd.checks.run.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            await check._kill_process(proc)
        proc.send_signal.assert_called_once_with(signal.SIGTERM)

    async def test_kill_process_already_dead(self):
        check = RunCheck(name="test", command=["/bin/true"])
        proc = _make_subprocess(0)
        proc.send_signal = mock.Mock(side_effect=ProcessLookupError())
        await check._kill_process(proc)

    async def test_kill_process_sigkill_after_grace(self):
        check = RunCheck(name="test", command=["/bin/true"])
        proc = _make_subprocess(0)

        with mock.patch(
            "healthcheckd.checks.run.asyncio.wait_for",
            side_effect=_closing_timeout,
        ):
            await check._kill_process(proc)

        proc.kill.assert_called_once()
        proc.wait.assert_awaited()

    async def test_kill_process_sigkill_already_dead(self):
        check = RunCheck(name="test", command=["/bin/true"])
        proc = _make_subprocess(0)
        proc.kill = mock.Mock(side_effect=ProcessLookupError())

        with mock.patch(
            "healthcheckd.checks.run.asyncio.wait_for",
            side_effect=_closing_timeout,
        ):
            await check._kill_process(proc)
