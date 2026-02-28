"""Exhaustive tests for security validation functions."""

import pytest

from healthcheckd.security import (
    validate_check_name,
    validate_command,
    validate_expected_result,
    validate_expected_states,
    validate_file_path,
    validate_percentage,
    validate_port,
    validate_systemd_unit,
    validate_url,
)


# --- validate_check_name ---


class TestValidateCheckName:
    def test_valid_simple(self):
        validate_check_name("sshd")

    def test_valid_with_hyphens(self):
        validate_check_name("http-check")

    def test_valid_with_underscores(self):
        validate_check_name("my_check_1")

    def test_valid_numbers(self):
        validate_check_name("check123")

    def test_valid_single_char(self):
        validate_check_name("a")

    def test_valid_max_length(self):
        validate_check_name("a" * 128)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("a" * 129)

    def test_rejects_dots(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("my.check")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("my check")

    def test_rejects_slashes(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("../../etc/passwd")

    def test_rejects_shell_chars(self):
        with pytest.raises(ValueError, match="Invalid check name"):
            validate_check_name("check;rm -rf")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_check_name(123)


# --- validate_systemd_unit ---


class TestValidateSystemdUnit:
    def test_valid_service(self):
        validate_systemd_unit("sshd.service")

    def test_valid_socket(self):
        validate_systemd_unit("sshd.socket")

    def test_valid_timer(self):
        validate_systemd_unit("certbot-renew.timer")

    def test_valid_mount(self):
        validate_systemd_unit("home.mount")

    def test_valid_target(self):
        validate_systemd_unit("multi-user.target")

    def test_valid_path(self):
        validate_systemd_unit("cups.path")

    def test_valid_slice(self):
        validate_systemd_unit("user.slice")

    def test_valid_scope(self):
        validate_systemd_unit("session-1.scope")

    def test_valid_with_at(self):
        validate_systemd_unit("getty@tty1.service")

    def test_valid_with_dots(self):
        validate_systemd_unit("systemd-resolved.service")

    def test_rejects_no_suffix(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("sshd")

    def test_rejects_invalid_suffix(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("sshd.invalid")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("../etc/passwd.service")

    def test_rejects_shell_injection(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("sshd;id.service")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("my service.service")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid systemd unit"):
            validate_systemd_unit("")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_systemd_unit(42)


# --- validate_expected_states ---


class TestValidateExpectedStates:
    def test_single_state(self):
        result = validate_expected_states("running")
        assert result == ["running"]

    def test_multiple_states(self):
        result = validate_expected_states("running,enabled")
        assert result == ["running", "enabled"]

    def test_all_common_states(self):
        for state in ["active", "inactive", "running", "dead", "exited",
                       "enabled", "disabled", "static", "masked"]:
            result = validate_expected_states(state)
            assert result == [state]

    def test_strips_whitespace(self):
        result = validate_expected_states("running , enabled")
        assert result == ["running", "enabled"]

    def test_rejects_unknown_state(self):
        with pytest.raises(ValueError, match="Unknown systemd state"):
            validate_expected_states("banana")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_expected_states("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_expected_states("   ")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_expected_states(123)

    def test_timer_states(self):
        result = validate_expected_states("enabled")
        assert result == ["enabled"]

    def test_waiting_state(self):
        result = validate_expected_states("waiting")
        assert result == ["waiting"]

    def test_enabled_runtime_state(self):
        result = validate_expected_states("enabled-runtime")
        assert result == ["enabled-runtime"]


# --- validate_command ---


class TestValidateCommand:
    def test_valid_simple_command(self):
        validate_command(["/bin/true"])

    def test_valid_command_with_args(self):
        validate_command(["/usr/bin/curl", "-sf", "http://localhost"])

    def test_rejects_non_list(self):
        with pytest.raises(ValueError, match="must be a list"):
            validate_command("/bin/true")

    def test_rejects_empty_list(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_command([])

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            validate_command(["/bin/true"] + ["arg"] * 64)

    def test_rejects_relative_path(self):
        with pytest.raises(ValueError, match="absolute path"):
            validate_command(["bin/true"])

    def test_rejects_bare_name(self):
        with pytest.raises(ValueError, match="absolute path"):
            validate_command(["true"])

    def test_rejects_non_string_arg(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_command(["/bin/true", 42])

    def test_rejects_non_string_executable(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_command([42])


# --- validate_expected_result ---


class TestValidateExpectedResult:
    def test_valid_zero(self):
        validate_expected_result("0")

    def test_valid_nonzero(self):
        validate_expected_result("1")

    def test_valid_negation(self):
        validate_expected_result("!0")

    def test_valid_negation_nonzero(self):
        validate_expected_result("!1")

    def test_valid_csv(self):
        validate_expected_result("0,1,2,3")

    def test_valid_max_exit_code(self):
        validate_expected_result("255")

    def test_valid_negation_max(self):
        validate_expected_result("!255")

    def test_strips_whitespace(self):
        validate_expected_result("  0 , 1 , 2  ")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_expected_result("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_expected_result("   ")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_expected_result(0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_expected_result("-1")

    def test_rejects_over_255(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_expected_result("256")

    def test_rejects_negation_over_255(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_expected_result("!256")

    def test_rejects_negation_negative(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_expected_result("!-1")

    def test_rejects_non_integer(self):
        with pytest.raises(ValueError, match="Invalid integer"):
            validate_expected_result("abc")

    def test_rejects_non_integer_in_csv(self):
        with pytest.raises(ValueError, match="Invalid integer"):
            validate_expected_result("0,abc,1")

    def test_rejects_invalid_negation(self):
        with pytest.raises(ValueError, match="Invalid negation"):
            validate_expected_result("!abc")


# --- validate_url ---


class TestValidateUrl:
    def test_valid_http(self):
        validate_url("http://example.com")

    def test_valid_https(self):
        validate_url("https://example.com/health")

    def test_valid_with_port(self):
        validate_url("http://localhost:8080/health")

    def test_valid_with_path(self):
        validate_url("https://example.com/api/v1/health")

    def test_rejects_ftp(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("ftp://example.com")

    def test_rejects_file(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("file:///etc/passwd")

    def test_rejects_gopher(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("gopher://evil.com")

    def test_rejects_no_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("example.com")

    def test_rejects_no_hostname(self):
        with pytest.raises(ValueError, match="must have a hostname"):
            validate_url("http://")

    def test_rejects_credentials(self):
        with pytest.raises(ValueError, match="must not contain credentials"):
            validate_url("http://user:pass@example.com")

    def test_rejects_username_only(self):
        with pytest.raises(ValueError, match="must not contain credentials"):
            validate_url("http://user@example.com")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            validate_url("https://example.com/" + "a" * 2048)

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_url(123)


# --- validate_file_path ---


class TestValidateFilePath:
    def test_valid_absolute(self):
        validate_file_path("/var/run/myapp/heartbeat")

    def test_valid_root(self):
        validate_file_path("/")

    def test_rejects_relative(self):
        with pytest.raises(ValueError, match="must be absolute"):
            validate_file_path("var/run/heartbeat")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_file_path("")

    def test_rejects_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            validate_file_path("/var/run/\x00evil")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_file_path(42)


# --- validate_port ---


class TestValidatePort:
    def test_valid_min(self):
        validate_port(1)

    def test_valid_max(self):
        validate_port(65535)

    def test_valid_common(self):
        validate_port(9990)

    def test_rejects_zero(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_port(0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_port(-1)

    def test_rejects_too_high(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_port(65536)

    def test_rejects_string(self):
        with pytest.raises(ValueError, match="must be an integer"):
            validate_port("9990")

    def test_rejects_float(self):
        with pytest.raises(ValueError, match="must be an integer"):
            validate_port(9990.0)

    def test_rejects_bool(self):
        with pytest.raises(ValueError, match="must be an integer"):
            validate_port(True)


# --- validate_percentage ---


class TestValidatePercentage:
    def test_valid_zero(self):
        validate_percentage(0, "test")

    def test_valid_hundred(self):
        validate_percentage(100, "test")

    def test_valid_float(self):
        validate_percentage(10.5, "test")

    def test_valid_integer(self):
        validate_percentage(50, "test")

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_percentage(-1, "min_free_percent")

    def test_rejects_over_hundred(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_percentage(101, "min_free_percent")

    def test_rejects_string(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_percentage("50", "test")

    def test_rejects_bool(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_percentage(True, "test")

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_percentage(None, "test")

    def test_field_name_in_message(self):
        with pytest.raises(ValueError, match="min_free_percent"):
            validate_percentage(-1, "min_free_percent")
