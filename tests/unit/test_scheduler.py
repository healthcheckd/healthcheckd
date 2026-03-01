"""Tests for async check scheduler."""

import asyncio
from unittest import mock

import pytest

from healthcheckd.checks import CheckResult
from healthcheckd.metrics import MetricsManager
from healthcheckd.scheduler import MAX_CONCURRENT_SUBPROCESSES, CheckScheduler


def _make_check(name: str, healthy: bool = True, delay: float = 0.0):
    """Create a mock check that returns a fixed result."""
    check = mock.AsyncMock()
    check.name = name

    async def execute():
        if delay > 0:
            await asyncio.sleep(delay)
        return CheckResult(name=name, healthy=healthy)

    check.execute = execute
    return check


def _make_failing_check(name: str, exc: Exception):
    """Create a mock check that raises an exception."""
    check = mock.AsyncMock()
    check.name = name

    async def execute():
        raise exc

    check.execute = execute
    return check


class TestCheckSchedulerInit:
    def test_initial_state(self):
        metrics = MetricsManager()
        checks = [_make_check("a"), _make_check("b")]
        sched = CheckScheduler(checks, metrics)
        assert sched.ready is False
        assert sched.results == {}
        assert len(sched.checks) == 2

    def test_checks_configured_metric_set(self):
        metrics = MetricsManager()
        checks = [_make_check("a"), _make_check("b"), _make_check("c")]
        CheckScheduler(checks, metrics)
        output = metrics.generate().decode()
        assert "healthcheckd_checks_configured 3.0" in output

    def test_checks_returns_copy(self):
        metrics = MetricsManager()
        checks = [_make_check("a")]
        sched = CheckScheduler(checks, metrics)
        returned = sched.checks
        returned.append(_make_check("b"))
        assert len(sched.checks) == 1

    def test_results_returns_copy(self):
        metrics = MetricsManager()
        sched = CheckScheduler([_make_check("a")], metrics)
        results = sched.results
        results["fake"] = CheckResult(name="fake", healthy=True)
        assert "fake" not in sched.results


class TestCheckSchedulerCycle:
    async def test_run_cycle_sets_ready(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics)
        assert sched.ready is False
        await sched._run_cycle()
        assert sched.ready is True

    async def test_run_cycle_caches_results(self):
        metrics = MetricsManager()
        check = _make_check("sshd", healthy=True)
        sched = CheckScheduler([check], metrics)
        await sched._run_cycle()
        assert sched.results["sshd"].healthy is True

    async def test_run_cycle_unhealthy_result(self):
        metrics = MetricsManager()
        check = _make_check("db", healthy=False)
        sched = CheckScheduler([check], metrics)
        await sched._run_cycle()
        assert sched.results["db"].healthy is False

    async def test_run_cycle_updates_metrics(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics)
        await sched._run_cycle()
        output = metrics.generate().decode()
        assert 'healthcheckd_check_status{check="sshd"} 1.0' in output
        assert "healthcheckd_last_cycle_timestamp_seconds" in output
        assert "healthcheckd_last_cycle_duration_seconds" in output

    async def test_run_cycle_handles_exception(self):
        metrics = MetricsManager()
        check = _make_failing_check("bad", RuntimeError("boom"))
        sched = CheckScheduler([check], metrics)
        await sched._run_cycle()
        assert sched.results["bad"].healthy is False
        assert "RuntimeError" in sched.results["bad"].detail

    async def test_run_cycle_mixed_results(self):
        metrics = MetricsManager()
        good = _make_check("good", healthy=True)
        bad = _make_failing_check("bad", ValueError("oops"))
        sched = CheckScheduler([good, bad], metrics)
        await sched._run_cycle()
        assert sched.results["good"].healthy is True
        assert sched.results["bad"].healthy is False

    async def test_run_cycle_calls_watchdog(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        notified = []
        sched = CheckScheduler(
            [check], metrics, watchdog_notify=lambda: notified.append(True)
        )
        await sched._run_cycle()
        assert len(notified) == 1

    async def test_run_cycle_no_watchdog(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics, watchdog_notify=None)
        await sched._run_cycle()  # Should not raise

    async def test_cycle_in_progress_cleared_on_exception(self):
        """Ensure _cycle_in_progress is reset even if gather raises."""
        metrics = MetricsManager()
        check = _make_failing_check("fail", RuntimeError("boom"))
        sched = CheckScheduler([check], metrics)
        await sched._run_cycle()
        assert sched._cycle_in_progress is False


class TestCheckSchedulerSingleCheck:
    async def test_single_check_timeout(self):
        metrics = MetricsManager()
        check = _make_check("slow", delay=10.0)
        sched = CheckScheduler([check], metrics, check_timeout=0.01)
        result = await sched._run_single_check(check)
        assert result.healthy is False
        assert "timed out" in result.detail

    async def test_single_check_success(self):
        metrics = MetricsManager()
        check = _make_check("fast")
        sched = CheckScheduler([check], metrics)
        result = await sched._run_single_check(check)
        assert result.healthy is True

    async def test_single_check_updates_metrics(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics)
        await sched._run_single_check(check)
        output = metrics.generate().decode()
        assert 'healthcheckd_check_status{check="sshd"} 1.0' in output
        assert 'healthcheckd_check_duration_seconds{check="sshd"}' in output


class TestCheckSchedulerLoop:
    async def test_start_and_stop(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics, frequency=60)
        sched.start()
        # Wait for first cycle to complete
        for _ in range(50):
            if sched.ready:
                break
            await asyncio.sleep(0.01)
        assert sched.ready is True
        await sched.stop()

    async def test_start_idempotent(self):
        metrics = MetricsManager()
        check = _make_check("sshd")
        sched = CheckScheduler([check], metrics, frequency=60)
        sched.start()
        task1 = sched._task
        sched.start()  # Should not create a second task
        assert sched._task is task1
        await sched.stop()

    async def test_stop_when_not_started(self):
        metrics = MetricsManager()
        sched = CheckScheduler([_make_check("a")], metrics)
        await sched.stop()  # Should not raise

    async def test_loop_runs_multiple_cycles(self):
        metrics = MetricsManager()
        call_count = []
        check = mock.AsyncMock()
        check.name = "counter"

        async def execute():
            call_count.append(1)
            return CheckResult(name="counter", healthy=True)

        check.execute = execute
        sched = CheckScheduler([check], metrics, frequency=0.05)
        sched.start()
        # Wait for at least 2 cycles
        for _ in range(100):
            if len(call_count) >= 2:
                break
            await asyncio.sleep(0.01)
        await sched.stop()
        assert len(call_count) >= 2

    async def test_loop_exits_while_condition_with_zero_frequency(self):
        """While loop exits naturally when _running becomes False (95->exit).

        Also covers sleep_time <= 0 skip (98->101) since frequency=0 means
        the computed sleep_time is always <= 0.
        """
        metrics = MetricsManager()
        call_count = [0]
        check = mock.AsyncMock()
        check.name = "counter"

        # We need sched to exist before defining execute, so use a list wrapper
        sched_ref = [None]

        async def execute():
            call_count[0] += 1
            if call_count[0] >= 2:
                sched_ref[0]._running = False
            return CheckResult(name="counter", healthy=True)

        check.execute = execute
        sched = CheckScheduler([check], metrics, frequency=0)
        sched_ref[0] = sched
        sched._running = True
        await sched._run_loop()
        assert call_count[0] >= 2

    async def test_loop_breaks_when_stopped_during_sleep(self):
        """Loop breaks if _running set to False during sleep (line 102)."""
        metrics = MetricsManager()
        check = _make_check("a")
        sched = CheckScheduler([check], metrics, frequency=60)

        async def stop_during_sleep(seconds):
            sched._running = False

        with mock.patch("asyncio.sleep", side_effect=stop_during_sleep):
            sched._running = True
            await sched._run_loop()
        assert sched.ready is True

    async def test_overlap_guard_logs_and_skips(self):
        """Overlap guard logs warning and skips cycle (lines 105-106)."""
        metrics = MetricsManager()
        check = _make_check("a")
        sched = CheckScheduler([check], metrics, frequency=0.01)

        sleep_count = [0]

        async def fake_sleep(seconds):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                # Simulate a long-running cycle still in progress
                sched._cycle_in_progress = True
            else:
                # Clear the flag and stop the loop
                sched._cycle_in_progress = False
                sched._running = False

        with mock.patch("asyncio.sleep", side_effect=fake_sleep):
            sched._running = True
            await sched._run_loop()
        assert sleep_count[0] >= 2


class TestCheckSchedulerUpdateChecks:
    async def test_update_adds_new_checks(self):
        metrics = MetricsManager()
        check_a = _make_check("a")
        sched = CheckScheduler([check_a], metrics)
        await sched._run_cycle()

        check_b = _make_check("b")
        sched.update_checks([check_a, check_b])
        assert len(sched.checks) == 2

    async def test_update_removes_old_checks(self):
        metrics = MetricsManager()
        check_a = _make_check("a")
        check_b = _make_check("b")
        sched = CheckScheduler([check_a, check_b], metrics)
        await sched._run_cycle()

        sched.update_checks([check_a])
        assert len(sched.checks) == 1
        assert "b" not in sched.results

    async def test_update_removes_metrics_for_deleted_checks(self):
        metrics = MetricsManager()
        check_a = _make_check("a")
        check_b = _make_check("b")
        sched = CheckScheduler([check_a, check_b], metrics)
        await sched._run_cycle()
        output = metrics.generate().decode()
        assert 'check="b"' in output

        sched.update_checks([check_a])
        output = metrics.generate().decode()
        assert 'check="b"' not in output

    async def test_update_updates_configured_count(self):
        metrics = MetricsManager()
        sched = CheckScheduler([_make_check("a")], metrics)
        sched.update_checks([_make_check("x"), _make_check("y"), _make_check("z")])
        output = metrics.generate().decode()
        assert "healthcheckd_checks_configured 3.0" in output


class TestCheckSchedulerDebug:
    async def test_debug_logs_check_results(self, caplog):
        metrics = MetricsManager()
        check = _make_check("sshd", healthy=True)
        sched = CheckScheduler([check], metrics, debug=True)
        with caplog.at_level("INFO", logger="healthcheckd.scheduler"):
            await sched._run_cycle()
        assert "Check sshd: healthy" in caplog.text
        assert "Cycle completed in" in caplog.text

    async def test_debug_logs_unhealthy_with_detail(self, caplog):
        metrics = MetricsManager()
        check = _make_failing_check("db", RuntimeError("connection refused"))
        sched = CheckScheduler([check], metrics, debug=True)
        with caplog.at_level("INFO", logger="healthcheckd.scheduler"):
            await sched._run_cycle()
        assert "Check db: UNHEALTHY (Exception: RuntimeError)" in caplog.text

    async def test_debug_off_no_check_logs(self, caplog):
        metrics = MetricsManager()
        check = _make_check("sshd", healthy=True)
        sched = CheckScheduler([check], metrics, debug=False)
        with caplog.at_level("INFO", logger="healthcheckd.scheduler"):
            await sched._run_cycle()
        assert "Check sshd:" not in caplog.text
        assert "Cycle completed in" not in caplog.text


class TestCheckSchedulerConstants:
    def test_max_concurrent_subprocesses(self):
        assert MAX_CONCURRENT_SUBPROCESSES == 10
