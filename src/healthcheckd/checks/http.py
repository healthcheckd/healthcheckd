"""HTTP endpoint health check with SSRF protection."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import List, Optional

import aiohttp

from healthcheckd.checks import CheckResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MiB

# IP ranges blocked to prevent SSRF attacks
BLOCKED_NETWORKS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("169.254.0.0/16"),     # link-local / AWS metadata
    ipaddress.ip_network("127.0.0.0/8"),         # loopback
    ipaddress.ip_network("::1/128"),             # IPv6 loopback
    ipaddress.ip_network("fe80::/10"),           # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),           # "this" network
]


def is_blocked_ip(addr: str) -> bool:
    """Check if an IP address is in a blocked SSRF range."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in network for network in BLOCKED_NETWORKS)


class SSRFProtectionError(Exception):
    """Raised when an HTTP check target resolves to a blocked IP."""


class SafeResolver(aiohttp.DefaultResolver):
    """DNS resolver that validates resolved IPs against SSRF blocklist."""

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> List[dict]:
        results = await super().resolve(host, port, family)
        for result in results:
            addr = result.get("host", "")
            if is_blocked_ip(addr):
                raise SSRFProtectionError(
                    f"HTTP check target {host!r} resolves to blocked "
                    f"address {addr}"
                )
        return results


class HttpCheck:
    """Check an HTTP endpoint for expected status and content."""

    def __init__(
        self,
        name: str,
        url: str,
        expected_result: int = 200,
        validate_tls: bool = True,
        containing_string: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._name = name
        self._url = url
        self._expected_status = expected_result
        self._validate_tls = validate_tls
        self._containing_string = containing_string
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    async def execute(self) -> CheckResult:
        connector = aiohttp.TCPConnector(
            resolver=SafeResolver(),
            ssl=self._validate_tls if self._validate_tls else False,
        )
        client_timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with aiohttp.ClientSession(
                connector=connector, timeout=client_timeout
            ) as session:
                async with session.get(
                    self._url, allow_redirects=False
                ) as response:
                    status = response.status

                    body = None
                    if self._containing_string is not None:
                        body = await response.content.read(MAX_RESPONSE_BYTES)
                        body = body.decode("utf-8", errors="replace")

        except SSRFProtectionError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"SSRF protection: {e}",
            )
        except aiohttp.ClientError as e:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"HTTP request failed: {e}",
            )
        except TimeoutError:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=f"HTTP request timed out after {self._timeout}s",
            )

        if status != self._expected_status:
            return CheckResult(
                name=self._name,
                healthy=False,
                detail=(
                    f"Expected status {self._expected_status}, got {status}"
                ),
            )

        if self._containing_string is not None and body is not None:
            if self._containing_string not in body:
                return CheckResult(
                    name=self._name,
                    healthy=False,
                    detail=(
                        f"Response body does not contain "
                        f"expected string {self._containing_string!r}"
                    ),
                )

        return CheckResult(
            name=self._name,
            healthy=True,
            detail=f"HTTP {status}",
        )
