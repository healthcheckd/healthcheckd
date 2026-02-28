"""Tests for configuration loading and validation."""

import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from healthcheckd.config import (
    ConfigError,
    CheckConfig,
    MainConfig,
    load_check_configs,
    load_main_config,
    _load_single_check,
    _read_config_file,
    _validate_check_params,
    DEFAULT_BIND,
    DEFAULT_CHECK_FREQUENCY,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PORT,
)


# --- MainConfig ---


class TestLoadMainConfig:
    def test_defaults_when_file_missing(self, tmp_path):
        config = load_main_config(tmp_path / "nonexistent")
        assert config.port == DEFAULT_PORT
        assert config.bind == DEFAULT_BIND
        assert config.check_frequency == DEFAULT_CHECK_FREQUENCY
        assert config.log_level == DEFAULT_LOG_LEVEL

    def test_defaults_when_file_empty(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text("")
        config = load_main_config(cfg)
        assert config == MainConfig()

    def test_custom_values(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({
            "port": 8080,
            "bind": "127.0.0.1",
            "check_frequency": 60,
            "log_level": "DEBUG",
        }))
        config = load_main_config(cfg)
        assert config.port == 8080
        assert config.bind == "127.0.0.1"
        assert config.check_frequency == 60
        assert config.log_level == "DEBUG"

    def test_partial_values_use_defaults(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"port": 8080}))
        config = load_main_config(cfg)
        assert config.port == 8080
        assert config.bind == DEFAULT_BIND
        assert config.check_frequency == DEFAULT_CHECK_FREQUENCY

    def test_log_level_case_insensitive(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"log_level": "debug"}))
        config = load_main_config(cfg)
        assert config.log_level == "DEBUG"

    def test_check_frequency_float_truncated(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"check_frequency": 30.5}))
        config = load_main_config(cfg)
        assert config.check_frequency == 30

    def test_rejects_non_mapping(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text("just a string\n")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_main_config(cfg)

    def test_rejects_invalid_port_type(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"port": "9990"}))
        with pytest.raises(ConfigError, match="port must be an integer"):
            load_main_config(cfg)

    def test_rejects_bool_port(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"port": True}))
        with pytest.raises(ConfigError, match="port must be an integer"):
            load_main_config(cfg)

    def test_rejects_port_out_of_range(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"port": 0}))
        with pytest.raises(ConfigError):
            load_main_config(cfg)

    def test_rejects_non_string_bind(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"bind": 123}))
        with pytest.raises(ConfigError, match="bind must be a string"):
            load_main_config(cfg)

    def test_rejects_bool_check_frequency(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"check_frequency": True}))
        with pytest.raises(ConfigError, match="check_frequency must be a number"):
            load_main_config(cfg)

    def test_rejects_string_check_frequency(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"check_frequency": "fast"}))
        with pytest.raises(ConfigError, match="check_frequency must be a number"):
            load_main_config(cfg)

    def test_rejects_zero_check_frequency(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"check_frequency": 0}))
        with pytest.raises(ConfigError, match="check_frequency must be >= 1"):
            load_main_config(cfg)

    def test_rejects_non_string_log_level(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"log_level": 42}))
        with pytest.raises(ConfigError, match="log_level must be a string"):
            load_main_config(cfg)

    def test_rejects_invalid_log_level(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text(yaml.dump({"log_level": "VERBOSE"}))
        with pytest.raises(ConfigError, match="Invalid log_level"):
            load_main_config(cfg)


# --- CheckConfig loading ---


class TestLoadCheckConfigs:
    def test_empty_when_dir_missing(self, tmp_path):
        checks = load_check_configs(tmp_path / "nonexistent")
        assert checks == []

    def test_empty_when_dir_empty(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        checks = load_check_configs(config_d)
        assert checks == []

    def test_rejects_non_directory(self, tmp_path):
        not_a_dir = tmp_path / "config.d"
        not_a_dir.write_text("not a dir")
        with pytest.raises(ConfigError, match="not a directory"):
            load_check_configs(not_a_dir)

    def test_loads_yaml_check(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "sshd.yaml").write_text(yaml.dump({
            "type": "systemd",
            "unit": "sshd.service",
            "expected_states": "running,enabled",
        }))
        checks = load_check_configs(config_d)
        assert len(checks) == 1
        assert checks[0].name == "sshd"
        assert checks[0].check_type == "systemd"

    def test_loads_yml_extension(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "nginx.yml").write_text(yaml.dump({
            "type": "systemd",
            "unit": "nginx.service",
            "expected_states": "running,enabled",
        }))
        checks = load_check_configs(config_d)
        assert len(checks) == 1
        assert checks[0].name == "nginx"

    def test_loads_json_check(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "mycheck.json").write_text(json.dumps({
            "type": "run",
            "command": ["/bin/true"],
        }))
        checks = load_check_configs(config_d)
        assert len(checks) == 1
        assert checks[0].name == "mycheck"
        assert checks[0].check_type == "run"

    def test_loads_toml_check(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "diskcheck.toml").write_text(
            'path = "/"\ntype = "disk"\nmin_free_percent = 10\n'
        )
        checks = load_check_configs(config_d)
        assert len(checks) == 1
        assert checks[0].name == "diskcheck"
        assert checks[0].check_type == "disk"

    def test_loads_multiple_checks_sorted(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "alpha.yaml").write_text(yaml.dump({
            "type": "run", "command": ["/bin/true"],
        }))
        (config_d / "beta.yaml").write_text(yaml.dump({
            "type": "run", "command": ["/bin/true"],
        }))
        checks = load_check_configs(config_d)
        assert len(checks) == 2
        assert checks[0].name == "alpha"
        assert checks[1].name == "beta"

    def test_ignores_non_config_extensions(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "notes.txt").write_text("not a check")
        (config_d / "backup.bak").write_text("not a check")
        (config_d / "valid.yaml").write_text(yaml.dump({
            "type": "run", "command": ["/bin/true"],
        }))
        checks = load_check_configs(config_d)
        assert len(checks) == 1

    def test_ignores_directories(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "subdir").mkdir()
        checks = load_check_configs(config_d)
        assert checks == []

    def test_rejects_duplicate_names(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "sshd.yaml").write_text(yaml.dump({
            "type": "systemd", "unit": "sshd.service",
            "expected_states": "running,enabled",
        }))
        (config_d / "sshd.json").write_text(json.dumps({
            "type": "systemd", "unit": "sshd.service",
            "expected_states": "running,enabled",
        }))
        with pytest.raises(ConfigError, match="Duplicate check name"):
            load_check_configs(config_d)

    def test_rejects_invalid_filename(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad name.yaml").write_text(yaml.dump({
            "type": "run", "command": ["/bin/true"],
        }))
        with pytest.raises(ConfigError, match="Invalid check name"):
            load_check_configs(config_d)

    def test_rejects_too_large_file(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        large_file = config_d / "big.yaml"
        large_file.write_text("x" * (64 * 1024 + 1))
        with pytest.raises(ConfigError, match="too large"):
            load_check_configs(config_d)

    def test_rejects_empty_file(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "empty.yaml").write_text("")
        with pytest.raises(ConfigError, match="Empty config file"):
            load_check_configs(config_d)

    def test_rejects_missing_type(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "nocheck.yaml").write_text(yaml.dump({
            "unit": "sshd.service",
        }))
        with pytest.raises(ConfigError, match="Missing 'type'"):
            load_check_configs(config_d)

    def test_rejects_unknown_type(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "banana",
        }))
        with pytest.raises(ConfigError, match="Unknown check type"):
            load_check_configs(config_d)

    def test_rejects_non_mapping_check(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text("just a string\n")
        with pytest.raises(ConfigError, match="must be a mapping"):
            load_check_configs(config_d)

    def test_rejects_too_many_files(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        for i in range(257):
            (config_d / f"check{i:04d}.yaml").write_text(yaml.dump({
                "type": "run", "command": ["/bin/true"],
            }))
        with pytest.raises(ConfigError, match="Too many config files"):
            load_check_configs(config_d)

    def test_rejects_symlink_escape(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        external = tmp_path / "external.yaml"
        external.write_text(yaml.dump({
            "type": "run", "command": ["/bin/true"],
        }))
        (config_d / "escaped.yaml").symlink_to(external)
        # The symlink resolves outside config_d, so it gets skipped
        checks = load_check_configs(config_d)
        assert len(checks) == 0

    def test_handles_broken_symlink(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "broken.yaml").symlink_to("/nonexistent/file")
        checks = load_check_configs(config_d)
        assert len(checks) == 0


# --- Check type validation ---


class TestSystemdCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "sshd.yaml").write_text(yaml.dump({
            "type": "systemd",
            "unit": "sshd.service",
            "expected_states": "running,enabled",
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["unit"] == "sshd.service"

    def test_missing_unit(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "systemd",
            "expected_states": "running",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'unit'"):
            load_check_configs(config_d)

    def test_missing_expected_states(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "systemd",
            "unit": "sshd.service",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'expected_states'"):
            load_check_configs(config_d)

    def test_invalid_unit(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "systemd",
            "unit": "not-a-unit",
            "expected_states": "running",
        }))
        with pytest.raises(ConfigError, match="Invalid systemd unit"):
            load_check_configs(config_d)


class TestRunCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "mycheck.yaml").write_text(yaml.dump({
            "type": "run",
            "command": ["/bin/true"],
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["command"] == ["/bin/true"]

    def test_valid_with_expected_result(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "mycheck.yaml").write_text(yaml.dump({
            "type": "run",
            "command": ["/bin/false"],
            "expected_result": "!0",
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["expected_result"] == "!0"

    def test_missing_command(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "run",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'command'"):
            load_check_configs(config_d)

    def test_invalid_command(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "run",
            "command": "not-a-list",
        }))
        with pytest.raises(ConfigError, match="must be a list"):
            load_check_configs(config_d)


class TestHttpCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "web.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["url"] == "https://example.com"

    def test_valid_with_all_options(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "web.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "validate_tls": False,
            "expected_result": 200,
            "containing_string": "Welcome",
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["validate_tls"] is False

    def test_missing_url(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'url'"):
            load_check_configs(config_d)

    def test_invalid_expected_result_type(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "expected_result": "200",
        }))
        with pytest.raises(ConfigError, match="must be an integer HTTP status"):
            load_check_configs(config_d)

    def test_invalid_expected_result_bool(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "expected_result": True,
        }))
        with pytest.raises(ConfigError, match="must be an integer HTTP status"):
            load_check_configs(config_d)

    def test_invalid_expected_result_range(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "expected_result": 999,
        }))
        with pytest.raises(ConfigError, match="out of range"):
            load_check_configs(config_d)

    def test_invalid_validate_tls(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "validate_tls": "false",
        }))
        with pytest.raises(ConfigError, match="validate_tls must be a boolean"):
            load_check_configs(config_d)

    def test_invalid_containing_string(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "http",
            "url": "https://example.com",
            "containing_string": 123,
        }))
        with pytest.raises(ConfigError, match="containing_string must be a string"):
            load_check_configs(config_d)


class TestTcpCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "postgres.yaml").write_text(yaml.dump({
            "type": "tcp",
            "host": "127.0.0.1",
            "port": 5432,
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["host"] == "127.0.0.1"
        assert checks[0].params["port"] == 5432

    def test_missing_host(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "tcp", "port": 5432,
        }))
        with pytest.raises(ConfigError, match="Missing required field 'host'"):
            load_check_configs(config_d)

    def test_missing_port(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "tcp", "host": "127.0.0.1",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'port'"):
            load_check_configs(config_d)

    def test_invalid_host_type(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "tcp", "host": 123, "port": 5432,
        }))
        with pytest.raises(ConfigError, match="host must be a string"):
            load_check_configs(config_d)


class TestFileCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "heartbeat.yaml").write_text(yaml.dump({
            "type": "file",
            "path": "/var/run/myapp/heartbeat",
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["path"] == "/var/run/myapp/heartbeat"

    def test_valid_with_max_age(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "heartbeat.yaml").write_text(yaml.dump({
            "type": "file",
            "path": "/var/run/myapp/heartbeat",
            "max_age": 60,
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["max_age"] == 60

    def test_missing_path(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "file",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'path'"):
            load_check_configs(config_d)

    def test_invalid_max_age_bool(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "file",
            "path": "/var/run/heartbeat",
            "max_age": True,
        }))
        with pytest.raises(ConfigError, match="max_age must be a number"):
            load_check_configs(config_d)

    def test_invalid_max_age_string(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "file",
            "path": "/var/run/heartbeat",
            "max_age": "60",
        }))
        with pytest.raises(ConfigError, match="max_age must be a number"):
            load_check_configs(config_d)

    def test_invalid_max_age_zero(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "file",
            "path": "/var/run/heartbeat",
            "max_age": 0,
        }))
        with pytest.raises(ConfigError, match="max_age must be positive"):
            load_check_configs(config_d)


class TestDiskCheckValidation:
    def test_valid(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "rootdisk.yaml").write_text(yaml.dump({
            "type": "disk",
            "path": "/",
            "min_free_percent": 10,
        }))
        checks = load_check_configs(config_d)
        assert checks[0].params["min_free_percent"] == 10

    def test_missing_path(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "disk",
            "min_free_percent": 10,
        }))
        with pytest.raises(ConfigError, match="Missing required field 'path'"):
            load_check_configs(config_d)

    def test_missing_min_free_percent(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "disk",
            "path": "/",
        }))
        with pytest.raises(ConfigError, match="Missing required field 'min_free_percent'"):
            load_check_configs(config_d)

    def test_invalid_min_free_percent(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        (config_d / "bad.yaml").write_text(yaml.dump({
            "type": "disk",
            "path": "/",
            "min_free_percent": 101,
        }))
        with pytest.raises(ConfigError, match="out of range"):
            load_check_configs(config_d)


# --- Internal function edge cases ---


class TestReadConfigFile:
    def test_rejects_unsupported_extension(self, tmp_path):
        bad_file = tmp_path / "check.xml"
        bad_file.write_text("<check/>")
        with pytest.raises(ConfigError, match="Unsupported config format"):
            _read_config_file(bad_file)


class TestValidateCheckParams:
    def test_rejects_unknown_check_type(self, tmp_path):
        with pytest.raises(ConfigError, match="No validator for check type"):
            _validate_check_params("unknown_type", {}, tmp_path / "fake.yaml")


class TestLoadSingleCheckStatError:
    def test_handles_stat_oserror(self, tmp_path):
        config_d = tmp_path / "config.d"
        config_d.mkdir()
        check_file = config_d / "test.yaml"
        check_file.write_text("type: run\ncommand: ['/bin/true']\n")
        with mock.patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            with pytest.raises(ConfigError, match="Cannot stat config file"):
                _load_single_check(check_file, config_d)
