"""TCP port connectivity health check."""

from __future__ import annotations

import asyncio
import logging

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


class TcpCheck:
    """Check TCP port connectivity."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._name = name
        self._host = host
        self._port = port
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            writer.close()
            await writer.wait_closed()
            return CheckResult(
                name=self._name,
                healthy=True,
                detail=f"TCP {self._host}:{self._port} connected",
            )
        except asyncio.TimeoutError:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=(
                    f"TCP {self._host}:{self._port} timed out "
                    f"after {self._timeout}s"
                ),
            )
        except OSError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"TCP {self._host}:{self._port} failed: {e}",
            )
