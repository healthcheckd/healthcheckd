"""Integration tests for SIGHUP config reload."""

from unittest import mock

import pytest

from healthcheckd.__main__ import _reload_checks, create_check
from healthcheckd.checks import CheckResult
from healthcheckd.config import CheckConfig
from healthcheckd.metrics import MetricsManager
from healthcheckd.scheduler import CheckScheduler


def _make_check(name, healthy=True):
    check = mock.AsyncMock()
    check.name = name

    async def execute():
        return CheckResult(name=name, healthy=healthy)

    check.execute = execute
    return check


class TestReloadChecks:
    async def test_reload_adds_new_check(self, tmp_path):
        metrics = MetricsManager()
        old = _make_check("old")
        scheduler = CheckScheduler([old], metrics, frequency=60)
        await scheduler._run_cycle()

        config_dir = tmp_path / "config.d"
        config_dir.mkdir()
        (config_dir / "new-tcp.yaml").write_text(
            "type: tcp\nhost: 127.0.0.1\nport: 22\n"
        )

        _reload_checks(scheduler, config_dir)
        assert len(scheduler.checks) == 1
        assert scheduler.checks[0].name == "new-tcp"

    async def test_reload_removes_check(self, tmp_path):
        metrics = MetricsManager()
        a = _make_check("a")
        b = _make_check("b")
        scheduler = CheckScheduler([a, b], metrics, frequency=60)
        await scheduler._run_cycle()

        config_dir = tmp_path / "config.d"
        config_dir.mkdir()
        (config_dir / "a.yaml").write_text(
            "type: tcp\nhost: 127.0.0.1\nport: 22\n"
        )

        _reload_checks(scheduler, config_dir)
        assert len(scheduler.checks) == 1
        assert scheduler.checks[0].name == "a"
        assert "b" not in scheduler.results

    async def test_reload_failure_keeps_old_config(self, tmp_path):
        metrics = MetricsManager()
        old = _make_check("old")
        scheduler = CheckScheduler([old], metrics, frequency=60)
        await scheduler._run_cycle()

        config_dir = tmp_path / "config.d"
        config_dir.mkdir()
        # Invalid config: not a mapping
        (config_dir / "bad.yaml").write_text("just a string\n")

        _reload_checks(scheduler, config_dir)
        # Old config preserved
        assert len(scheduler.checks) == 1
        assert scheduler.checks[0].name == "old"

    async def test_reload_empty_directory(self, tmp_path):
        metrics = MetricsManager()
        old = _make_check("old")
        scheduler = CheckScheduler([old], metrics, frequency=60)
        await scheduler._run_cycle()

        config_dir = tmp_path / "config.d"
        config_dir.mkdir()

        _reload_checks(scheduler, config_dir)
        assert len(scheduler.checks) == 0

    async def test_reload_nonexistent_directory(self):
        metrics = MetricsManager()
        old = _make_check("old")
        scheduler = CheckScheduler([old], metrics, frequency=60)
        await scheduler._run_cycle()

        from pathlib import Path

        _reload_checks(scheduler, Path("/nonexistent/path"))
        # Empty config returned for nonexistent dir
        assert len(scheduler.checks) == 0

    def test_reload_with_multiple_formats(self, tmp_path):
        metrics = MetricsManager()
        scheduler = CheckScheduler([], metrics, frequency=60)

        config_dir = tmp_path / "config.d"
        config_dir.mkdir()
        (config_dir / "tcp-check.yaml").write_text(
            "type: tcp\nhost: 127.0.0.1\nport: 22\n"
        )
        (config_dir / "disk-check.json").write_text(
            '{"type": "disk", "path": "/", "min_free_percent": 10}'
        )

        _reload_checks(scheduler, config_dir)
        assert len(scheduler.checks) == 2
        names = {c.name for c in scheduler.checks}
        assert names == {"tcp-check", "disk-check"}
