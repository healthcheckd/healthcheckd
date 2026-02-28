"""Entry point for healthcheckd daemon."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, List, Optional

import sdnotify
from aiohttp import web

from healthcheckd import __version__
from healthcheckd.checks.disk import DiskCheck
from healthcheckd.checks.file import FileCheck
from healthcheckd.checks.http import HttpCheck
from healthcheckd.checks.run import RunCheck
from healthcheckd.checks.systemd import SystemdCheck
from healthcheckd.checks.tcp import TcpCheck
from healthcheckd.config import (
    CheckConfig,
    ConfigError,
    load_check_configs,
    load_main_config,
    MainConfig,
)
from healthcheckd.metrics import MetricsManager
from healthcheckd.scheduler import CheckScheduler
from healthcheckd.server import create_app

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/etc/healthcheckd/config")
CONFIG_DIR = Path("/etc/healthcheckd/config.d")


def _create_systemd_check(name: str, params: dict) -> SystemdCheck:
    states = [s.strip() for s in str(params["expected_states"]).split(",")]
    return SystemdCheck(name=name, unit=params["unit"], expected_states=states)


def _create_run_check(name: str, params: dict) -> RunCheck:
    return RunCheck(
        name=name,
        command=params["command"],
        expected_result=str(params.get("expected_result", "0")),
    )


def _create_http_check(name: str, params: dict) -> HttpCheck:
    return HttpCheck(
        name=name,
        url=params["url"],
        expected_result=params.get("expected_result", 200),
        validate_tls=params.get("validate_tls", True),
        containing_string=params.get("containing_string"),
    )


def _create_tcp_check(name: str, params: dict) -> TcpCheck:
    return TcpCheck(name=name, host=params["host"], port=params["port"])


def _create_file_check(name: str, params: dict) -> FileCheck:
    return FileCheck(
        name=name, path=params["path"], max_age=params.get("max_age", 0)
    )


def _create_disk_check(name: str, params: dict) -> DiskCheck:
    return DiskCheck(
        name=name,
        path=params["path"],
        min_free_percent=params["min_free_percent"],
    )


_CHECK_FACTORIES = {
    "systemd": _create_systemd_check,
    "run": _create_run_check,
    "http": _create_http_check,
    "tcp": _create_tcp_check,
    "file": _create_file_check,
    "disk": _create_disk_check,
}


def create_check(config: CheckConfig) -> Any:
    """Create a check instance from a CheckConfig."""
    factory = _CHECK_FACTORIES[config.check_type]
    return factory(config.name, config.params)


def _reload_checks(scheduler: CheckScheduler, config_dir: Path) -> None:
    """Reload check configuration from disk."""
    try:
        new_configs = load_check_configs(config_dir)
        new_checks = [create_check(cc) for cc in new_configs]
        scheduler.update_checks(new_checks)
        logger.info("Config reloaded: %d checks", len(new_checks))
    except Exception:
        logger.exception("Config reload failed, keeping current config")


def _notify(notifier: Optional[Any], msg: str) -> None:
    """Send an sd_notify message if a notifier is available."""
    if notifier is not None:
        notifier.notify(msg)


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter that prevents log injection."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "logger": record.name,
            "level": record.levelname,
            "message": _CONTROL_CHAR_RE.sub("", record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = traceback.format_exception(*record.exc_info)
        return json.dumps(entry)


def setup_logging(level: str) -> None:
    """Configure structured JSON logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level))


async def run_daemon(
    main_config: MainConfig,
    checks: List[Any],
    config_dir: Path = CONFIG_DIR,
    notifier: Optional[Any] = None,
) -> None:
    """Run the healthcheckd daemon."""
    metrics = MetricsManager()

    watchdog_cb = None
    if notifier is not None:
        def watchdog_cb() -> None:
            notifier.notify("WATCHDOG=1")

    scheduler = CheckScheduler(
        checks=checks,
        metrics=metrics,
        frequency=main_config.check_frequency,
        watchdog_notify=watchdog_cb,
    )

    app = create_app(scheduler, metrics)
    runner = web.AppRunner(app, server_header="")
    await runner.setup()

    site = web.TCPSite(runner, main_config.bind, main_config.port, backlog=128)
    await site.start()

    scheduler.start()

    while not scheduler.ready:
        await asyncio.sleep(0.1)

    _notify(notifier, "READY=1")
    logger.info("Ready, listening on %s:%d", main_config.bind, main_config.port)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(
        signal.SIGHUP, lambda: _reload_checks(scheduler, config_dir)
    )

    await stop_event.wait()

    loop.remove_signal_handler(signal.SIGTERM)
    loop.remove_signal_handler(signal.SIGINT)
    loop.remove_signal_handler(signal.SIGHUP)

    logger.info("Shutting down...")
    _notify(notifier, "STOPPING=1")
    await scheduler.stop()
    await runner.cleanup()


def main() -> int:
    """Run the healthcheckd daemon."""
    try:
        main_config = load_main_config(CONFIG_PATH)
    except ConfigError as e:
        sys.stderr.write(f"Error loading config: {e}\n")
        return 1

    setup_logging(main_config.log_level)

    try:
        check_configs = load_check_configs(CONFIG_DIR)
    except ConfigError as e:
        logger.error("Failed to load check configs: %s", e)
        return 1

    checks = [create_check(cc) for cc in check_configs]
    logger.info(
        "Starting healthcheckd %s with %d checks", __version__, len(checks)
    )

    notifier = sdnotify.SystemdNotifier(False)
    asyncio.run(run_daemon(main_config, checks, CONFIG_DIR, notifier))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
