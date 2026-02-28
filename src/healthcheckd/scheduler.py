"""Async check scheduler with anchored intervals and watchdog support."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from healthcheckd.checks import CheckResult
from healthcheckd.metrics import MetricsManager

logger = logging.getLogger(__name__)

DEFAULT_CHECK_TIMEOUT = 30
MAX_CONCURRENT_SUBPROCESSES = 10


class CheckScheduler:
    """Runs health checks on a schedule and caches results."""

    def __init__(
        self,
        checks: List[Any],
        metrics: MetricsManager,
        frequency: int = 30,
        check_timeout: float = DEFAULT_CHECK_TIMEOUT,
        watchdog_notify: Optional[Callable[[], None]] = None,
    ) -> None:
        self._checks = list(checks)
        self._metrics = metrics
        self._frequency = frequency
        self._check_timeout = check_timeout
        self._watchdog_notify = watchdog_notify
        self._results: Dict[str, CheckResult] = {}
        self._ready = False
        self._running = False
        self._cycle_in_progress = False
        self._task: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBPROCESSES)
        metrics.set_checks_configured(len(checks))

    @property
    def ready(self) -> bool:
        """Whether at least one check cycle has completed."""
        return self._ready

    @property
    def results(self) -> Dict[str, CheckResult]:
        """Current cached check results."""
        return dict(self._results)

    @property
    def checks(self) -> List[Any]:
        """Current list of checks."""
        return list(self._checks)

    def update_checks(self, checks: List[Any]) -> None:
        """Replace the check list (for SIGHUP reload)."""
        old_names = {c.name for c in self._checks}
        new_names = {c.name for c in checks}

        # Remove metrics for deleted checks
        for name in old_names - new_names:
            self._metrics.remove_check(name)
            self._results.pop(name, None)

        self._checks = list(checks)
        self._metrics.set_checks_configured(len(checks))

    def start(self) -> None:
        """Start the scheduler background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())

    async def stop(self) -> None:
        """Stop the scheduler and wait for it to finish."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        """Main scheduler loop with anchored intervals."""
        try:
            # Run immediately on startup
            await self._run_cycle()

            while self._running:
                next_run = time.monotonic() + self._frequency
                sleep_time = next_run - time.monotonic()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                if not self._running:
                    break

                if self._cycle_in_progress:
                    logger.warning("Check cycle overlap detected, skipping cycle")
                    continue

                await self._run_cycle()
        except asyncio.CancelledError:
            raise

    async def _run_cycle(self) -> None:
        """Execute all checks concurrently and update results."""
        self._cycle_in_progress = True
        cycle_start = time.monotonic()

        try:
            tasks = [
                self._run_single_check(check) for check in self._checks
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for check, result in zip(self._checks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Check %s raised exception: %s", check.name, result
                    )
                    result = CheckResult(
                        name=check.name,
                        healthy=False,
                        detail=f"Exception: {type(result).__name__}",
                    )
                self._results[check.name] = result
        finally:
            self._cycle_in_progress = False

        cycle_duration = time.monotonic() - cycle_start
        self._metrics.update_cycle(time.time(), cycle_duration)

        if not self._ready:
            self._ready = True

        if self._watchdog_notify is not None:
            self._watchdog_notify()

    async def _run_single_check(self, check: Any) -> CheckResult:
        """Run a single check with timeout and concurrency limiting."""
        async with self._semaphore:
            check_start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    check.execute(), timeout=self._check_timeout
                )
            except asyncio.TimeoutError:
                result = CheckResult(
                    name=check.name,
                    healthy=False,
                    detail=f"Check timed out after {self._check_timeout}s",
                )
            check_duration = time.monotonic() - check_start
            self._metrics.update_check(
                check.name, result.healthy, check_duration
            )
            return result
