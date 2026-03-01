"""HTTP server factory for healthcheckd."""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING, Tuple

from aiohttp import web

from healthcheckd.handlers import handle_complex, handle_metrics, handle_simple

if TYPE_CHECKING:
    from healthcheckd.config import LogFilter
    from healthcheckd.metrics import MetricsManager
    from healthcheckd.scheduler import CheckScheduler

logger = logging.getLogger(__name__)


class AccessLogFilter(logging.Filter):
    """Drop access log entries matching any configured filter rule."""

    def __init__(self, rules: Tuple[LogFilter, ...] = ()) -> None:
        super().__init__()
        self.rules = rules

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.rules:
            return True

        msg = record.getMessage()

        # aiohttp access log format:
        # "1.2.3.4 [date] \"METHOD /path HTTP/1.1\" status size \"ref\" \"UA\""
        # Extract remote IP (first token before space)
        ip_str = msg.split(" ", 1)[0] if msg else ""

        # Extract user agent (last quoted string)
        ua = ""
        last_quote = msg.rfind('"')
        if last_quote > 0:
            second_last = msg.rfind('"', 0, last_quote)
            if second_last >= 0:
                ua = msg[second_last + 1:last_quote]

        # Extract request path from first quoted string: "METHOD /path HTTP/x.x"
        req_path = ""
        first_quote = msg.find('"')
        if first_quote >= 0:
            close_quote = msg.find('"', first_quote + 1)
            if close_quote > first_quote:
                parts = msg[first_quote + 1:close_quote].split(" ")
                if len(parts) >= 2:
                    req_path = parts[1]

        for rule in self.rules:
            match = True

            if rule.remote_ip is not None:
                try:
                    match = ipaddress.ip_address(ip_str) in rule.remote_ip
                except ValueError:
                    match = False

            if match and rule.user_agent is not None:
                match = rule.user_agent.search(ua) is not None

            if match and rule.path is not None:
                match = req_path == rule.path

            if match:
                return False

        return True

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
