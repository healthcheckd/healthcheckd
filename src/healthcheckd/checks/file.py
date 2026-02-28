"""File existence and age health check."""

from __future__ import annotations

import logging
import os
import time

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)


class FileCheck:
    """Check that a file exists and is not too old."""

    def __init__(
        self,
        name: str,
        path: str,
        max_age: float = 0,
    ) -> None:
        self._name = name
        self._path = path
        self._max_age = max_age  # 0 means no age check

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        try:
            stat = os.stat(self._path)
        except OSError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"File {self._path} not accessible: {e}",
            )

        if self._max_age > 0:
            age = time.time() - stat.st_mtime
            if age > self._max_age:
                return CheckResult(
                    name=self._name,
                    healthy=False,
                    detail=(
                        f"File {self._path} is {age:.0f}s old, "
                        f"max allowed {self._max_age:.0f}s"
                    ),
                )

        return CheckResult(
            name=self._name,
            healthy=True,
            detail=f"File {self._path} exists",
        )
