"""Prometheus metrics management for healthcheckd."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from prometheus_client import CollectorRegistry, Gauge, generate_latest

logger = logging.getLogger(__name__)


class MetricsManager:
    """Manages Prometheus metrics for health checks."""

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self._registry = registry or CollectorRegistry()
        self._check_status = Gauge(
            "healthcheckd_check_status",
            "Health check status (1=healthy, 0=unhealthy)",
            ["check"],
            registry=self._registry,
        )
        self._check_duration = Gauge(
            "healthcheckd_check_duration_seconds",
            "Time taken for last check execution",
            ["check"],
            registry=self._registry,
        )
        self._up = Gauge(
            "healthcheckd_up",
            "Whether healthcheckd is running (1=up)",
            registry=self._registry,
        )
        self._last_cycle_timestamp = Gauge(
            "healthcheckd_last_cycle_timestamp_seconds",
            "Unix timestamp of last completed check cycle",
            registry=self._registry,
        )
        self._last_cycle_duration = Gauge(
            "healthcheckd_last_cycle_duration_seconds",
            "Duration of last check cycle in seconds",
            registry=self._registry,
        )
        self._checks_configured = Gauge(
            "healthcheckd_checks_configured",
            "Number of configured health checks",
            registry=self._registry,
        )
        self._up.set(1)

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def update_check(self, name: str, healthy: bool, duration: float) -> None:
        """Update metrics for a single check."""
        self._check_status.labels(check=name).set(1.0 if healthy else 0.0)
        self._check_duration.labels(check=name).set(duration)

    def update_cycle(self, timestamp: float, duration: float) -> None:
        """Update metrics for a completed check cycle."""
        self._last_cycle_timestamp.set(timestamp)
        self._last_cycle_duration.set(duration)

    def set_checks_configured(self, count: int) -> None:
        """Set the number of configured checks."""
        self._checks_configured.set(count)

    def remove_check(self, name: str) -> None:
        """Remove metrics for a check that no longer exists."""
        self._check_status.remove(name)
        self._check_duration.remove(name)

    def generate(self) -> bytes:
        """Generate Prometheus exposition format output."""
        return generate_latest(self._registry)
