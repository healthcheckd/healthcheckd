"""Tests for Prometheus metrics management."""

from prometheus_client import CollectorRegistry

from healthcheckd.metrics import MetricsManager


class TestMetricsManager:
    def test_creates_with_custom_registry(self):
        registry = CollectorRegistry()
        mm = MetricsManager(registry=registry)
        assert mm.registry is registry

    def test_creates_with_default_registry(self):
        mm = MetricsManager()
        assert mm.registry is not None

    def test_up_gauge_set_on_init(self):
        mm = MetricsManager()
        output = mm.generate().decode()
        assert "healthcheckd_up 1.0" in output

    def test_update_check_healthy(self):
        mm = MetricsManager()
        mm.update_check("sshd", True, 0.05)
        output = mm.generate().decode()
        assert 'healthcheckd_check_status{check="sshd"} 1.0' in output
        assert 'healthcheckd_check_duration_seconds{check="sshd"} 0.05' in output

    def test_update_check_unhealthy(self):
        mm = MetricsManager()
        mm.update_check("sshd", False, 0.1)
        output = mm.generate().decode()
        assert 'healthcheckd_check_status{check="sshd"} 0.0' in output

    def test_update_cycle(self):
        mm = MetricsManager()
        mm.update_cycle(1740700830.0, 0.45)
        output = mm.generate().decode()
        assert "healthcheckd_last_cycle_timestamp_seconds 1.74070083e+09" in output
        assert "healthcheckd_last_cycle_duration_seconds 0.45" in output

    def test_set_checks_configured(self):
        mm = MetricsManager()
        mm.set_checks_configured(5)
        output = mm.generate().decode()
        assert "healthcheckd_checks_configured 5.0" in output

    def test_remove_check(self):
        mm = MetricsManager()
        mm.update_check("gone", True, 0.01)
        output = mm.generate().decode()
        assert 'healthcheckd_check_status{check="gone"}' in output

        mm.remove_check("gone")
        output = mm.generate().decode()
        assert 'healthcheckd_check_status{check="gone"}' not in output
        assert 'healthcheckd_check_duration_seconds{check="gone"}' not in output

    def test_generate_returns_bytes(self):
        mm = MetricsManager()
        result = mm.generate()
        assert isinstance(result, bytes)

    def test_multiple_checks(self):
        mm = MetricsManager()
        mm.update_check("sshd", True, 0.01)
        mm.update_check("nginx", False, 0.5)
        output = mm.generate().decode()
        assert 'healthcheckd_check_status{check="sshd"} 1.0' in output
        assert 'healthcheckd_check_status{check="nginx"} 0.0' in output

    def test_all_metric_families_present(self):
        mm = MetricsManager()
        mm.update_check("test", True, 0.01)
        mm.update_cycle(1000.0, 0.1)
        mm.set_checks_configured(1)
        output = mm.generate().decode()
        assert "healthcheckd_check_status" in output
        assert "healthcheckd_check_duration_seconds" in output
        assert "healthcheckd_up" in output
        assert "healthcheckd_last_cycle_timestamp_seconds" in output
        assert "healthcheckd_last_cycle_duration_seconds" in output
        assert "healthcheckd_checks_configured" in output
