"""Disk space health check."""

from __future__ import annotations

import logging
import os

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)


class DiskCheck:
    """Check that a filesystem has sufficient free space."""

    def __init__(
        self,
        name: str,
        path: str,
        min_free_percent: float,
    ) -> None:
        self._name = name
        self._path = path
        self._min_free_percent = min_free_percent

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        try:
            stat = os.statvfs(self._path)
        except OSError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Cannot stat filesystem {self._path}: {e}",
            )

        if stat.f_blocks == 0:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"Filesystem {self._path} reports 0 total blocks",
            )

        free_percent = (stat.f_bavail / stat.f_blocks) * 100

        if free_percent < self._min_free_percent:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=(
                    f"Filesystem {self._path} has {free_percent:.1f}% free, "
                    f"minimum {self._min_free_percent:.1f}%"
                ),
            )

        return CheckResult(
            name=self._name,
            healthy=True,
            detail=(
                f"Filesystem {self._path} has {free_percent:.1f}% free"
            ),
        )
