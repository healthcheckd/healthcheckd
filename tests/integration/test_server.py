"""Integration tests for the HTTP server."""

from unittest import mock

import pytest
from aiohttp import web

from healthcheckd.checks import CheckResult
from healthcheckd.metrics import MetricsManager
from healthcheckd.server import create_app, error_middleware


def _make_mock_scheduler(ready=True, results=None, checks=None):
    scheduler = mock.MagicMock()
    scheduler.ready = ready
    scheduler.results = results or {}
    scheduler.checks = checks or []
    return scheduler


def _make_check_stub(name):
    stub = mock.MagicMock()
    stub.name = name
    return stub


class TestCreateApp:
    async def test_simple_endpoint_exists(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        metrics = MetricsManager()
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)
        resp = await client.get("/simple")
        assert resp.status == 200

    async def test_complex_endpoint_exists(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        metrics = MetricsManager()
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)
        resp = await client.get("/complex")
        assert resp.status == 200

    async def test_metrics_endpoint_exists(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        metrics = MetricsManager()
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        assert resp.status == 200

    async def test_404_for_unknown_path(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        metrics = MetricsManager()
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)
        resp = await client.get("/unknown")
        assert resp.status == 404

    async def test_405_for_post(self, aiohttp_client):
        scheduler = _make_mock_scheduler()
        metrics = MetricsManager()
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)
        resp = await client.post("/simple")
        assert resp.status == 405


class TestErrorMiddleware:
    async def test_catches_unhandled_exception(self, aiohttp_client):
        async def bad_handler(request):
            raise RuntimeError("boom")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/bad", bad_handler)
        client = await aiohttp_client(app)
        resp = await client.get("/bad")
        assert resp.status == 500

    async def test_passes_through_http_exceptions(self, aiohttp_client):
        async def not_found_handler(request):
            raise web.HTTPNotFound()

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/nf", not_found_handler)
        client = await aiohttp_client(app)
        resp = await client.get("/nf")
        assert resp.status == 404

    async def test_passes_through_normal_responses(self, aiohttp_client):
        async def ok_handler(request):
            return web.Response(text="ok")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/ok", ok_handler)
        client = await aiohttp_client(app)
        resp = await client.get("/ok")
        assert resp.status == 200
        assert await resp.text() == "ok"


class TestFullRequestFlow:
    async def test_healthy_flow(self, aiohttp_client):
        """Full request through middleware -> handler -> response."""
        checks = [_make_check_stub("sshd")]
        scheduler = _make_mock_scheduler(
            results={"sshd": CheckResult(name="sshd", healthy=True)},
            checks=checks,
        )
        metrics = MetricsManager()
        metrics.update_check("sshd", True, 0.01)
        app = create_app(scheduler, metrics)
        client = await aiohttp_client(app)

        # Simple
        resp = await client.get("/simple")
        assert resp.status == 200

        # Complex
        resp = await client.get("/complex")
        assert resp.status == 200
        body = await resp.text()
        assert "sshd 1" in body

        # Metrics
        resp = await client.get("/metrics")
        assert resp.status == 200
        body = await resp.text()
        assert "healthcheckd_check_status" in body

    async def test_unhealthy_flow(self, aiohttp_client):
        checks = [_make_check_stub("db")]
        scheduler = _make_mock_scheduler(
            results={"db": CheckResult(name="db", healthy=False)},
            checks=checks,
        )
        app = create_app(scheduler, MetricsManager())
        client = await aiohttp_client(app)

        resp = await client.get("/simple")
        assert resp.status == 400

        resp = await client.get("/complex")
        assert resp.status == 400
        assert "db 0" in await resp.text()

    async def test_not_ready_flow(self, aiohttp_client):
        scheduler = _make_mock_scheduler(ready=False)
        app = create_app(scheduler, MetricsManager())
        client = await aiohttp_client(app)

        for path in ("/simple", "/complex", "/metrics"):
            resp = await client.get(path)
            assert resp.status == 503, f"Expected 503 for {path}"
