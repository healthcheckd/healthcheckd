"""HTTP request handlers for healthcheckd endpoints."""

from __future__ import annotations

from aiohttp import web


async def handle_simple(request: web.Request) -> web.Response:
    """Return 200 if all checks healthy, 400 if any unhealthy, 503 if not ready."""
    from healthcheckd.server import scheduler_key

    scheduler = request.app[scheduler_key]
    if not scheduler.ready:
        return web.Response(status=503)

    results = scheduler.results
    all_healthy = all(r.healthy for r in results.values())
    return web.Response(status=200 if all_healthy else 400)


async def handle_complex(request: web.Request) -> web.Response:
    """Return check details as plain text, 503 if not ready."""
    from healthcheckd.server import scheduler_key

    scheduler = request.app[scheduler_key]
    if not scheduler.ready:
        return web.Response(status=503)

    results = scheduler.results
    lines = []
    all_healthy = True
    for check in scheduler.checks:
        result = results.get(check.name)
        if result is not None:
            status = 1 if result.healthy else 0
            if not result.healthy:
                all_healthy = False
            lines.append(f"{result.name} {status}")

    body = ("\n".join(lines) + "\n") if lines else ""
    return web.Response(
        status=200 if all_healthy else 400,
        text=body,
        content_type="text/plain",
    )


async def handle_metrics(request: web.Request) -> web.Response:
    """Return Prometheus metrics, 503 if not ready."""
    from healthcheckd.server import metrics_key, scheduler_key

    scheduler = request.app[scheduler_key]
    if not scheduler.ready:
        return web.Response(status=503)

    metrics = request.app[metrics_key]
    return web.Response(
        status=200,
        body=metrics.generate(),
        content_type="text/plain; version=0.0.4",
        charset="utf-8",
    )
