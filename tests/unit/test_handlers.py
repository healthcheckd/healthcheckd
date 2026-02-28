"""Tests for HTTP request handlers."""

from unittest import mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from healthcheckd.checks import CheckResult
from healthcheckd.handlers import handle_complex, handle_metrics, handle_simple
from healthcheckd.metrics import MetricsManager
from healthcheckd.server import metrics_key, scheduler_key


def _make_mock_scheduler(ready=True, results=None, checks=None):
    """Create a mock scheduler with configurable state."""
    scheduler = mock.MagicMock()
    scheduler.ready = ready
    scheduler.results = results or {}
    scheduler.checks = checks or []
    return scheduler


def _make_check_stub(name):
    """Create a stub with a .name attribute."""
    stub = mock.MagicMock()
    stub.name = name
    return stub


def _make_app(scheduler, metrics=None):
    """Create a minimal app with handlers for testing."""
    if metrics is None:
        metrics = MetricsManager()
    app = web.Application()
    app[scheduler_key] = scheduler
    app[metrics_key] = metrics
    app.router.add_get("/simple", handle_simple)
    app.router.add_get("/complex", handle_complex)
    app.router.add_get("/metrics", handle_metrics)
    return app


class TestHandleSimple:
    async def test_503_when_not_ready(self, aiohttp_client):
        scheduler = _make_mock_scheduler(ready=False)
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/simple")
        assert resp.status == 503

    async def test_200_when_all_healthy(self, aiohttp_client):
        scheduler = _make_mock_scheduler(
            results={
                "a": CheckResult(name="a", healthy=True),
                "b": CheckResult(name="b", healthy=True),
            }
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/simple")
        assert resp.status == 200

    async def test_400_when_any_unhealthy(self, aiohttp_client):
        scheduler = _make_mock_scheduler(
            results={
                "a": CheckResult(name="a", healthy=True),
                "b": CheckResult(name="b", healthy=False),
            }
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/simple")
        assert resp.status == 400

    async def test_200_with_empty_results(self, aiohttp_client):
        """No checks configured = healthy (vacuous truth)."""
        scheduler = _make_mock_scheduler(results={})
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/simple")
        assert resp.status == 200

    async def test_empty_body(self, aiohttp_client):
        scheduler = _make_mock_scheduler(
            results={"a": CheckResult(name="a", healthy=True)}
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/simple")
        body = await resp.read()
        assert body == b""


class TestHandleComplex:
    async def test_503_when_not_ready(self, aiohttp_client):
        scheduler = _make_mock_scheduler(ready=False)
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert resp.status == 503

    async def test_200_all_healthy(self, aiohttp_client):
        checks = [_make_check_stub("sshd"), _make_check_stub("nginx")]
        scheduler = _make_mock_scheduler(
            results={
                "sshd": CheckResult(name="sshd", healthy=True),
                "nginx": CheckResult(name="nginx", healthy=True),
            },
            checks=checks,
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert resp.status == 200
        body = await resp.text()
        assert body == "sshd 1\nnginx 1\n"

    async def test_400_when_unhealthy(self, aiohttp_client):
        checks = [_make_check_stub("sshd"), _make_check_stub("nginx")]
        scheduler = _make_mock_scheduler(
            results={
                "sshd": CheckResult(name="sshd", healthy=True),
                "nginx": CheckResult(name="nginx", healthy=False),
            },
            checks=checks,
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert resp.status == 400
        body = await resp.text()
        assert body == "sshd 1\nnginx 0\n"

    async def test_empty_body_when_no_checks(self, aiohttp_client):
        scheduler = _make_mock_scheduler(results={}, checks=[])
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert resp.status == 200
        body = await resp.text()
        assert body == ""

    async def test_skips_checks_without_results(self, aiohttp_client):
        """New checks added via SIGHUP don't appear until they've run."""
        checks = [_make_check_stub("old"), _make_check_stub("new")]
        scheduler = _make_mock_scheduler(
            results={"old": CheckResult(name="old", healthy=True)},
            checks=checks,
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert resp.status == 200
        body = await resp.text()
        assert "old 1" in body
        assert "new" not in body

    async def test_content_type_is_plain_text(self, aiohttp_client):
        scheduler = _make_mock_scheduler(
            results={"a": CheckResult(name="a", healthy=True)},
            checks=[_make_check_stub("a")],
        )
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/complex")
        assert "text/plain" in resp.headers["Content-Type"]


class TestHandleMetrics:
    async def test_503_when_not_ready(self, aiohttp_client):
        scheduler = _make_mock_scheduler(ready=False)
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/metrics")
        assert resp.status == 503

    async def test_200_with_prometheus_format(self, aiohttp_client):
        metrics = MetricsManager()
        metrics.update_check("sshd", True, 0.01)
        scheduler = _make_mock_scheduler()
        client = await aiohttp_client(_make_app(scheduler, metrics))
        resp = await client.get("/metrics")
        assert resp.status == 200
        body = await resp.text()
        assert "healthcheckd_check_status" in body
        assert "healthcheckd_up" in body

    async def test_content_type_is_prometheus(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        client = await aiohttp_client(_make_app(scheduler))
        resp = await client.get("/metrics")
        assert "text/plain" in resp.headers["Content-Type"]
