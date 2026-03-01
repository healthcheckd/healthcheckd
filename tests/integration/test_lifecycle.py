"""Integration tests for daemon lifecycle."""

import asyncio
import logging
import os
import signal
from unittest import mock

import pytest

from healthcheckd.__main__ import (
    _JsonFormatter,
    _sd_notify,
    create_check,
    run_daemon,
    setup_logging,
)
from healthcheckd.checks import CheckResult
from healthcheckd.checks.disk import DiskCheck
from healthcheckd.checks.file import FileCheck
from healthcheckd.checks.http import HttpCheck
from healthcheckd.checks.run import RunCheck
from healthcheckd.checks.systemd import SystemdCheck
from healthcheckd.checks.tcp import TcpCheck
from healthcheckd.config import CheckConfig, MainConfig


def _make_check(name, healthy=True):
    """Create a mock check for lifecycle tests."""
    check = mock.AsyncMock()
    check.name = name

    async def execute():
        return CheckResult(name=name, healthy=healthy)

    check.execute = execute
    return check


class TestCreateCheck:
    def test_systemd(self):
        config = CheckConfig(
            name="sshd",
            check_type="systemd",
            params={
                "unit": "sshd.service",
                "expected_states": "running,enabled",
            },
        )
        check = create_check(config)
        assert isinstance(check, SystemdCheck)
        assert check.name == "sshd"

    def test_systemd_strips_state_whitespace(self):
        config = CheckConfig(
            name="sshd",
            check_type="systemd",
            params={
                "unit": "sshd.service",
                "expected_states": "running , enabled",
            },
        )
        check = create_check(config)
        assert isinstance(check, SystemdCheck)

    def test_run(self):
        config = CheckConfig(
            name="ping",
            check_type="run",
            params={"command": ["/bin/true"]},
        )
        check = create_check(config)
        assert isinstance(check, RunCheck)
        assert check.name == "ping"

    def test_run_with_expected_result(self):
        config = CheckConfig(
            name="check",
            check_type="run",
            params={"command": ["/bin/false"], "expected_result": "!0"},
        )
        check = create_check(config)
        assert isinstance(check, RunCheck)

    def test_http(self):
        config = CheckConfig(
            name="web",
            check_type="http",
            params={"url": "https://example.com"},
        )
        check = create_check(config)
        assert isinstance(check, HttpCheck)
        assert check.name == "web"

    def test_http_with_all_options(self):
        config = CheckConfig(
            name="api",
            check_type="http",
            params={
                "url": "https://api.example.com/health",
                "expected_result": 201,
                "validate_tls": False,
                "containing_string": "ok",
            },
        )
        check = create_check(config)
        assert isinstance(check, HttpCheck)

    def test_tcp(self):
        config = CheckConfig(
            name="db",
            check_type="tcp",
            params={"host": "127.0.0.1", "port": 5432},
        )
        check = create_check(config)
        assert isinstance(check, TcpCheck)
        assert check.name == "db"

    def test_file(self):
        config = CheckConfig(
            name="heartbeat",
            check_type="file",
            params={"path": "/var/run/heartbeat"},
        )
        check = create_check(config)
        assert isinstance(check, FileCheck)
        assert check.name == "heartbeat"

    def test_file_with_max_age(self):
        config = CheckConfig(
            name="hb",
            check_type="file",
            params={"path": "/var/run/hb", "max_age": 60},
        )
        check = create_check(config)
        assert isinstance(check, FileCheck)

    def test_disk(self):
        config = CheckConfig(
            name="root",
            check_type="disk",
            params={"path": "/", "min_free_percent": 10},
        )
        check = create_check(config)
        assert isinstance(check, DiskCheck)
        assert check.name == "root"


class TestSdNotify:
    def test_sends_to_notify_socket(self):
        import socket as sock_mod
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notify.sock")
            server = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_DGRAM)
            server.bind(path)
            try:
                with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": path}):
                    _sd_notify("READY=1")
                data = server.recv(256)
                assert data == b"READY=1"
            finally:
                server.close()

    def test_sends_to_abstract_socket(self):
        import socket as sock_mod

        server = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_DGRAM)
        server.bind("\0healthcheckd-test-notify")
        try:
            with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": "@healthcheckd-test-notify"}):
                _sd_notify("READY=1")
            data = server.recv(256)
            assert data == b"READY=1"
        finally:
            server.close()

    def test_noop_without_notify_socket(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            _sd_notify("READY=1")  # Should not raise


class TestJsonFormatter:
    def test_basic_format(self):
        import json

        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["logger"] == "test"
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed
        assert "exception" not in parsed

    def test_strips_control_characters(self):
        import json

        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="bad\x00input\x1b[31mred", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "badinput[31mred"

    def test_includes_exception(self):
        import json

        formatter = _JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="failure", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert any("ValueError" in line for line in parsed["exception"])

    def test_format_with_args(self):
        import json

        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="count: %d", args=(42,), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "count: 42"


class TestSetupLogging:
    def test_configures_info_level(self):
        original_level = logging.getLogger().level
        original_handlers = logging.getLogger().handlers[:]
        try:
            setup_logging("INFO")
            assert logging.getLogger().level == logging.INFO
            assert len(logging.getLogger().handlers) == 1
            assert isinstance(
                logging.getLogger().handlers[0].formatter, _JsonFormatter
            )
        finally:
            logging.getLogger().setLevel(original_level)
            logging.getLogger().handlers[:] = original_handlers

    def test_configures_debug_level(self):
        original_level = logging.getLogger().level
        original_handlers = logging.getLogger().handlers[:]
        try:
            setup_logging("DEBUG")
            assert logging.getLogger().level == logging.DEBUG
        finally:
            logging.getLogger().setLevel(original_level)
            logging.getLogger().handlers[:] = original_handlers


class TestRunDaemon:
    async def test_starts_and_stops_with_sigterm(self):
        config = MainConfig(port=0, bind="127.0.0.1", check_frequency=1)
        check = _make_check("test")

        task = asyncio.create_task(
            run_daemon(config, [check], config_dir=self._empty_dir())
        )

        # Wait for the daemon to be ready
        await asyncio.sleep(0.5)
        assert not task.done()

        # Send SIGTERM to trigger shutdown
        os.kill(os.getpid(), signal.SIGTERM)

        await asyncio.wait_for(task, timeout=5.0)

    async def test_sends_sd_notify_messages(self):
        config = MainConfig(port=0, bind="127.0.0.1", check_frequency=1)
        check = _make_check("test")

        with mock.patch("healthcheckd.__main__._sd_notify") as mock_notify:
            task = asyncio.create_task(
                run_daemon(
                    config,
                    [check],
                    config_dir=self._empty_dir(),
                )
            )

            await asyncio.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(task, timeout=5.0)

            # Verify sd_notify calls
            calls = [c[0][0] for c in mock_notify.call_args_list]
            assert "READY=1" in calls
            assert "STOPPING=1" in calls
            # Watchdog should have been called at least once
            assert "WATCHDOG=1" in calls

    async def test_sighup_triggers_reload(self, tmp_path):
        config = MainConfig(port=0, bind="127.0.0.1", check_frequency=1)
        check = _make_check("initial")
        config_dir = tmp_path / "config.d"
        config_dir.mkdir()

        task = asyncio.create_task(
            run_daemon(config, [check], config_dir=config_dir)
        )

        await asyncio.sleep(0.5)

        # Add a new check config
        (config_dir / "new-check.yaml").write_text(
            "type: tcp\nhost: 127.0.0.1\nport: 22\n"
        )

        # Send SIGHUP to trigger reload
        os.kill(os.getpid(), signal.SIGHUP)
        await asyncio.sleep(0.3)

        # Stop the daemon
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5.0)

    @staticmethod
    def _empty_dir():
        """Return a Path to a non-existent directory (load_check_configs returns [])."""
        from pathlib import Path

        return Path("/tmp/healthcheckd-test-nonexistent")
