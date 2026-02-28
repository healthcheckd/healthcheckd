"""Health check implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:

    class Check(Protocol):
        """Protocol that all health check implementations must follow."""

        @property
        def name(self) -> str: ...

        async def execute(self) -> CheckResult: ...


@dataclass(frozen=True)
class CheckResult:
    """Result of a single health check execution."""

    name: str
    healthy: bool
    detail: str = ""
