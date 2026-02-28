"""HTTP server factory for healthcheckd."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from healthcheckd.handlers import handle_complex, handle_metrics, handle_simple

if TYPE_CHECKING:
    from healthcheckd.metrics import MetricsManager
    from healthcheckd.scheduler import CheckScheduler

logger = logging.getLogger(__name__)

scheduler_key: web.AppKey[CheckScheduler] = web.AppKey("scheduler")
metrics_key: web.AppKey[MetricsManager] = web.AppKey("metrics")


@web.middleware
async def error_middleware(
    request: web.Request,
    handler: web.RequestHandler,
) -> web.StreamResponse:
    """Catch unhandled exceptions and return generic 500."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled exception in request handler")
        return web.Response(status=500)


def create_app(
    scheduler: CheckScheduler,
    metrics: MetricsManager,
) -> web.Application:
    """Create the aiohttp application with routes and middleware."""
    app = web.Application(
        middlewares=[error_middleware],
        client_max_size=1024,
    )
    app[scheduler_key] = scheduler
    app[metrics_key] = metrics

    app.router.add_get("/simple", handle_simple)
    app.router.add_get("/complex", handle_complex)
    app.router.add_get("/metrics", handle_metrics)

    return app
