"""Tests for check base types."""

from healthcheckd.checks import CheckResult


class TestCheckResult:
    def test_create_healthy(self):
        result = CheckResult(name="test", healthy=True, detail="ok")
        assert result.name == "test"
        assert result.healthy is True
        assert result.detail == "ok"

    def test_create_unhealthy(self):
        result = CheckResult(name="test", healthy=False, detail="failed")
        assert result.healthy is False

    def test_default_detail(self):
        result = CheckResult(name="test", healthy=True)
        assert result.detail == ""

    def test_is_frozen(self):
        result = CheckResult(name="test", healthy=True)
        try:
            result.name = "changed"
            assert False, "Should have raised"
        except AttributeError:
            pass
