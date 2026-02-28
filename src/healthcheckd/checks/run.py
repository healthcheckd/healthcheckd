"""Command execution health check."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import List, Set

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_OUTPUT_BYTES = 8 * 1024  # 8 KiB
KILL_GRACE_PERIOD = 5


def parse_expected_result(result_str: str) -> tuple:
    """Parse expected_result string into a check function.

    Returns (negated: bool, values: set[int]).
    - ("!0") -> (True, {0}) meaning "not 0"
    - ("0") -> (False, {0}) meaning "exactly 0"
    - ("0,1,2") -> (False, {0, 1, 2}) meaning "one of 0, 1, 2"
    """
    result_str = result_str.strip()
    if result_str.startswith("!"):
        val = int(result_str[1:])
        return (True, {val})
    else:
        values = {int(p.strip()) for p in result_str.split(",")}
        return (False, values)


def check_exit_code(returncode: int, negated: bool, values: Set[int]) -> bool:
    """Check if an exit code matches the expected result."""
    if negated:
        return returncode not in values
    return returncode in values


class RunCheck:
    """Execute a command and check its exit code."""

    def __init__(
        self,
        name: str,
        command: List[str],
        expected_result: str = "0",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._name = name
        self._command = command
        self._negated, self._expected_values = parse_expected_result(expected_result)
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={},
            )
            stdout, stderr = await asyncio.wait_for(
                self._read_limited(proc), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            await self._kill_process(proc)
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Command timed out after {self._timeout}s",
            )
        except OSError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Failed to execute command: {e}",
            )

        healthy = check_exit_code(
            proc.returncode, self._negated, self._expected_values
        )

        return CheckResult(
            name=self._name,
            healthy=healthy,
            detail=f"Exit code: {proc.returncode}",
        )

    async def _read_limited(self, proc: asyncio.subprocess.Process) -> tuple:
        """Read stdout/stderr with size limits."""
        stdout = await proc.stdout.read(MAX_OUTPUT_BYTES)
        stderr = await proc.stderr.read(MAX_OUTPUT_BYTES)
        await proc.wait()
        return stdout, stderr

    async def _kill_process(self, proc: asyncio.subprocess.Process) -> None:
        """Gracefully terminate then kill a process."""
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_PERIOD)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                return
            await proc.wait()
