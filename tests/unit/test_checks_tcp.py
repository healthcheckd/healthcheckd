"""Tests for TCP port connectivity health check."""

import asyncio
from unittest import mock

import pytest

from healthcheckd.checks.tcp import TcpCheck


def _closing_timeout(coro, timeout=None):
    """Side effect that closes the coroutine then raises TimeoutError."""
    if hasattr(coro, "close"):
        coro.close()
    raise asyncio.TimeoutError()


def _closing_oserror(coro, timeout=None):
    """Side effect that closes the coroutine then raises OSError."""
    if hasattr(coro, "close"):
        coro.close()
    raise OSError("Connection refused")


class TestTcpCheck:
    @pytest.fixture
    def check(self):
        return TcpCheck(name="postgres", host="127.0.0.1", port=5432)

    async def test_healthy_when_connection_succeeds(self, check):
        writer = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock(return_value=None)
        reader = mock.Mock()

        async def fake_wait_for(coro, timeout):
            # Close the real coroutine, return our mock
            if hasattr(coro, "close"):
                coro.close()
            return reader, writer

        with mock.patch(
            "healthcheckd.checks.tcp.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            result = await check.execute()

        assert result.healthy is True
        assert result.name == "postgres"
        assert "connected" in result.detail
        writer.close.assert_called_once()

    async def test_unhealthy_on_timeout(self, check):
        with mock.patch(
            "healthcheckd.checks.tcp.asyncio.wait_for",
            side_effect=_closing_timeout,
        ):
            result = await check.execute()

        assert result.healthy is False
        assert "timed out" in result.detail

    async def test_unhealthy_on_connection_refused(self, check):
        with mock.patch(
            "healthcheckd.checks.tcp.asyncio.wait_for",
            side_effect=_closing_oserror,
        ):
            result = await check.execute()

        assert result.healthy is False
        assert "failed" in result.detail

    async def test_name_property(self, check):
        assert check.name == "postgres"
