"""Systemd unit health check."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Set

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class SystemdCheck:
    """Check the state of a systemd unit."""

    def __init__(
        self,
        name: str,
        unit: str,
        expected_states: List[str],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._name = name
        self._unit = unit
        self._expected_states = expected_states
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        try:
            actual_states = await asyncio.wait_for(
                self._get_unit_states(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Timeout querying unit {self._unit}",
            )
        except OSError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Error querying unit {self._unit}: {e}",
            )

        missing = set(self._expected_states) - actual_states
        if missing:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=(
                    f"Unit {self._unit} missing states: {sorted(missing)}. "
                    f"Actual: {sorted(actual_states)}"
                ),
            )

        return CheckResult(
            name=self._name,
            healthy=True,
            detail=f"Unit {self._unit} states: {sorted(actual_states)}",
        )

    async def _get_unit_states(self) -> Set[str]:
        """Query systemctl for unit state properties."""
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/systemctl", "show",
            "--property=ActiveState,SubState,UnitFileState",
            self._unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={},
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:1024]
            raise OSError(
                f"systemctl exited with code {proc.returncode}: {stderr_text}"
            )

        states: Set[str] = set()
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if "=" in line:
                value = line.split("=", 1)[1].strip()
                if value:
                    states.add(value)

        return states
