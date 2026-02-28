"""Tests for HTTP endpoint health check."""

import asyncio
from unittest import mock

import aiohttp
import pytest
from aioresponses import aioresponses

from healthcheckd.checks.http import (
    HttpCheck,
    SafeResolver,
    SSRFProtectionError,
    is_blocked_ip,
)


class TestIsBlockedIp:
    def test_blocks_aws_metadata(self):
        assert is_blocked_ip("169.254.169.254") is True

    def test_blocks_link_local(self):
        assert is_blocked_ip("169.254.1.1") is True

    def test_blocks_loopback(self):
        assert is_blocked_ip("127.0.0.1") is True

    def test_blocks_ipv6_loopback(self):
        assert is_blocked_ip("::1") is True

    def test_blocks_ipv6_link_local(self):
        assert is_blocked_ip("fe80::1") is True

    def test_blocks_this_network(self):
        assert is_blocked_ip("0.0.0.0") is True

    def test_allows_public_ip(self):
        assert is_blocked_ip("93.184.216.34") is False

    def test_allows_private_rfc1918(self):
        assert is_blocked_ip("10.0.0.1") is False

    def test_invalid_ip_returns_false(self):
        assert is_blocked_ip("not-an-ip") is False


class TestSafeResolver:
    async def test_rejects_blocked_ip(self):
        resolver = SafeResolver()
        with mock.patch.object(
            aiohttp.DefaultResolver,
            "resolve",
            return_value=[{"hostname": "evil.com", "host": "169.254.169.254",
                           "port": 80, "family": 2, "proto": 0, "flags": 0}],
        ):
            with pytest.raises(SSRFProtectionError, match="blocked address"):
                await resolver.resolve("evil.com", 80)

    async def test_allows_safe_ip(self):
        resolver = SafeResolver()
        with mock.patch.object(
            aiohttp.DefaultResolver,
            "resolve",
            return_value=[{"hostname": "example.com", "host": "93.184.216.34",
                           "port": 80, "family": 2, "proto": 0, "flags": 0}],
        ):
            results = await resolver.resolve("example.com", 80)
            assert results[0]["host"] == "93.184.216.34"


class TestHttpCheck:
    async def test_healthy_when_status_matches(self):
        check = HttpCheck(name="web", url="http://example.com")
        with aioresponses() as m:
            m.get("http://example.com", status=200)
            result = await check.execute()
        assert result.healthy is True
        assert result.name == "web"

    async def test_unhealthy_when_status_mismatches(self):
        check = HttpCheck(name="web", url="http://example.com", expected_result=200)
        with aioresponses() as m:
            m.get("http://example.com", status=503)
            result = await check.execute()
        assert result.healthy is False
        assert "Expected status 200, got 503" in result.detail

    async def test_healthy_with_containing_string(self):
        check = HttpCheck(
            name="web",
            url="http://example.com",
            containing_string="Welcome",
        )
        with aioresponses() as m:
            m.get("http://example.com", status=200, body="Welcome to our site")
            result = await check.execute()
        assert result.healthy is True

    async def test_unhealthy_when_string_missing(self):
        check = HttpCheck(
            name="web",
            url="http://example.com",
            containing_string="Welcome",
        )
        with aioresponses() as m:
            m.get("http://example.com", status=200, body="Not found")
            result = await check.execute()
        assert result.healthy is False
        assert "does not contain" in result.detail

    async def test_unhealthy_on_connection_error(self):
        check = HttpCheck(name="web", url="http://example.com")
        with aioresponses() as m:
            m.get("http://example.com", exception=aiohttp.ClientError("conn refused"))
            result = await check.execute()
        assert result.healthy is False
        assert "HTTP request failed" in result.detail

    async def test_unhealthy_on_timeout(self):
        check = HttpCheck(name="web", url="http://example.com", timeout=0.01)
        with aioresponses() as m:
            m.get("http://example.com", exception=TimeoutError())
            result = await check.execute()
        assert result.healthy is False
        assert "timed out" in result.detail

    async def test_ssrf_protection_blocks_metadata(self):
        check = HttpCheck(name="ssrf", url="http://metadata.internal")
        with mock.patch.object(
            aiohttp.DefaultResolver,
            "resolve",
            return_value=[{"hostname": "metadata.internal",
                           "host": "169.254.169.254",
                           "port": 80, "family": 2, "proto": 0, "flags": 0}],
        ):
            result = await check.execute()
        assert result.healthy is False
        assert "SSRF protection" in result.detail

    async def test_custom_expected_status(self):
        check = HttpCheck(name="redir", url="http://example.com", expected_result=301)
        with aioresponses() as m:
            m.get("http://example.com", status=301)
            result = await check.execute()
        assert result.healthy is True

    async def test_name_property(self):
        check = HttpCheck(name="web", url="http://example.com")
        assert check.name == "web"

    async def test_tls_validation_disabled(self):
        check = HttpCheck(
            name="web",
            url="https://self-signed.example.com",
            validate_tls=False,
        )
        with aioresponses() as m:
            m.get("https://self-signed.example.com", status=200)
            result = await check.execute()
        assert result.healthy is True
