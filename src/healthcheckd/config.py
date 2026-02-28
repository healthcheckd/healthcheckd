"""Configuration loading and validation for healthcheckd."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from healthcheckd.compat import toml_load
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

logger = logging.getLogger(__name__)

MAX_CONFIG_FILE_SIZE = 64 * 1024  # 64 KiB
MAX_CONFIG_FILES = 256
ALLOWED_EXTENSIONS = frozenset({".yaml", ".yml", ".json", ".toml"})

VALID_CHECK_TYPES = frozenset({
    "systemd", "run", "http", "tcp", "file", "disk",
})

DEFAULT_PORT = 9990
DEFAULT_BIND = "0.0.0.0"
DEFAULT_CHECK_FREQUENCY = 30
DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigError(Exception):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class MainConfig:
    """Main daemon configuration."""

    port: int = DEFAULT_PORT
    bind: str = DEFAULT_BIND
    check_frequency: int = DEFAULT_CHECK_FREQUENCY
    log_level: str = DEFAULT_LOG_LEVEL


@dataclass(frozen=True)
class CheckConfig:
    """Configuration for a single health check."""

    name: str
    check_type: str
    params: Dict[str, Any] = field(default_factory=dict)


def load_main_config(path: Path) -> MainConfig:
    """Load and validate the main configuration file.

    If the file doesn't exist, returns defaults.
    """
    if not path.exists():
        return MainConfig()

    data = _read_yaml_file(path)
    if data is None:
        return MainConfig()

    if not isinstance(data, dict):
        raise ConfigError(
            f"Main config must be a YAML mapping, got {type(data).__name__}"
        )

    port = data.get("port", DEFAULT_PORT)
    bind = data.get("bind", DEFAULT_BIND)
    check_frequency = data.get("check_frequency", DEFAULT_CHECK_FREQUENCY)
    log_level = data.get("log_level", DEFAULT_LOG_LEVEL)

    # Validate port
    if not isinstance(port, int) or isinstance(port, bool):
        raise ConfigError(f"port must be an integer, got {type(port).__name__}")
    try:
        validate_port(port)
    except ValueError as e:
        raise ConfigError(str(e))

    # Validate bind
    if not isinstance(bind, str):
        raise ConfigError(f"bind must be a string, got {type(bind).__name__}")

    # Validate check_frequency
    if isinstance(check_frequency, bool) or not isinstance(check_frequency, (int, float)):
        raise ConfigError(
            f"check_frequency must be a number, got {type(check_frequency).__name__}"
        )
    if check_frequency < 1:
        raise ConfigError(
            f"check_frequency must be >= 1, got {check_frequency}"
        )

    # Validate log_level
    if not isinstance(log_level, str):
        raise ConfigError(
            f"log_level must be a string, got {type(log_level).__name__}"
        )
    log_level = log_level.upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"Invalid log_level: {log_level!r}. "
            f"Must be one of: {sorted(VALID_LOG_LEVELS)}"
        )

    return MainConfig(
        port=port,
        bind=bind,
        check_frequency=int(check_frequency),
        log_level=log_level,
    )


def load_check_configs(config_dir: Path) -> List[CheckConfig]:
    """Load and validate all check configuration files from a directory.

    Returns a list of validated CheckConfig objects.
    Raises ConfigError if any file is invalid.
    """
    if not config_dir.exists():
        return []

    if not config_dir.is_dir():
        raise ConfigError(f"Config directory is not a directory: {config_dir}")

    config_dir = config_dir.resolve()

    files = _discover_config_files(config_dir)
    if len(files) > MAX_CONFIG_FILES:
        raise ConfigError(
            f"Too many config files ({len(files)}), max is {MAX_CONFIG_FILES}"
        )

    checks: List[CheckConfig] = []
    seen_names: Dict[str, Path] = {}

    for file_path in files:
        check = _load_single_check(file_path, config_dir)

        if check.name in seen_names:
            raise ConfigError(
                f"Duplicate check name {check.name!r} in "
                f"{file_path} and {seen_names[check.name]}"
            )
        seen_names[check.name] = file_path
        checks.append(check)

    return checks


def _discover_config_files(config_dir: Path) -> List[Path]:
    """Discover config files, rejecting symlinks that escape the config dir."""
    files: List[Path] = []

    for entry in sorted(config_dir.iterdir()):
        # Resolve symlinks and check containment
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            logger.warning("Cannot resolve config entry: %s", entry)
            continue

        if not resolved.is_relative_to(config_dir):
            logger.warning(
                "Skipping config entry that resolves outside config dir: "
                "%s -> %s",
                entry,
                resolved,
            )
            continue

        if not resolved.is_file():
            continue

        if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        files.append(resolved)

    return files


def _load_single_check(file_path: Path, config_dir: Path) -> CheckConfig:
    """Load and validate a single check config file."""
    # Size check
    try:
        stat = file_path.stat()
    except OSError as e:
        raise ConfigError(f"Cannot stat config file {file_path}: {e}")

    if stat.st_size > MAX_CONFIG_FILE_SIZE:
        raise ConfigError(
            f"Config file too large ({stat.st_size} bytes, max "
            f"{MAX_CONFIG_FILE_SIZE}): {file_path}"
        )
    if stat.st_size == 0:
        raise ConfigError(f"Empty config file: {file_path}")

    # Derive check name from filename
    name = file_path.stem
    try:
        validate_check_name(name)
    except ValueError as e:
        raise ConfigError(f"Invalid check name from filename {file_path.name}: {e}")

    # Parse the file
    data = _read_config_file(file_path)

    if not isinstance(data, dict):
        raise ConfigError(
            f"Check config must be a mapping, got {type(data).__name__}: {file_path}"
        )

    # Validate type field
    check_type = data.get("type")
    if check_type is None:
        raise ConfigError(f"Missing 'type' field in {file_path}")
    if check_type not in VALID_CHECK_TYPES:
        raise ConfigError(
            f"Unknown check type {check_type!r} in {file_path}. "
            f"Valid types: {sorted(VALID_CHECK_TYPES)}"
        )

    # Validate type-specific params
    params = dict(data)
    del params["type"]
    _validate_check_params(check_type, params, file_path)

    return CheckConfig(name=name, check_type=check_type, params=params)


def _validate_check_params(
    check_type: str, params: Dict[str, Any], file_path: Path
) -> None:
    """Validate parameters specific to each check type."""
    validators = {
        "systemd": _validate_systemd_params,
        "run": _validate_run_params,
        "http": _validate_http_params,
        "tcp": _validate_tcp_params,
        "file": _validate_file_params,
        "disk": _validate_disk_params,
    }
    validator = validators.get(check_type)
    if validator is None:
        raise ConfigError(
            f"No validator for check type {check_type!r} in {file_path}"
        )
    try:
        validator(params)
    except (ValueError, ConfigError) as e:
        raise ConfigError(f"Invalid {check_type} check in {file_path}: {e}")


def _validate_systemd_params(params: Dict[str, Any]) -> None:
    """Validate systemd check parameters."""
    if "unit" not in params:
        raise ValueError("Missing required field 'unit'")
    validate_systemd_unit(params["unit"])

    if "expected_states" not in params:
        raise ValueError("Missing required field 'expected_states'")
    validate_expected_states(str(params["expected_states"]))


def _validate_run_params(params: Dict[str, Any]) -> None:
    """Validate run check parameters."""
    if "command" not in params:
        raise ValueError("Missing required field 'command'")
    validate_command(params["command"])

    if "expected_result" in params:
        validate_expected_result(str(params["expected_result"]))


def _validate_http_params(params: Dict[str, Any]) -> None:
    """Validate http check parameters."""
    if "url" not in params:
        raise ValueError("Missing required field 'url'")
    validate_url(params["url"])

    if "expected_result" in params:
        val = params["expected_result"]
        if not isinstance(val, int) or isinstance(val, bool):
            raise ValueError(
                f"expected_result must be an integer HTTP status code, "
                f"got {type(val).__name__}"
            )
        if val < 100 or val > 599:
            raise ValueError(
                f"expected_result HTTP status out of range: {val}. Must be 100-599"
            )

    if "validate_tls" in params:
        if not isinstance(params["validate_tls"], bool):
            raise ValueError(
                f"validate_tls must be a boolean, "
                f"got {type(params['validate_tls']).__name__}"
            )

    if "containing_string" in params:
        if not isinstance(params["containing_string"], str):
            raise ValueError(
                f"containing_string must be a string, "
                f"got {type(params['containing_string']).__name__}"
            )


def _validate_tcp_params(params: Dict[str, Any]) -> None:
    """Validate tcp check parameters."""
    if "host" not in params:
        raise ValueError("Missing required field 'host'")
    if not isinstance(params["host"], str):
        raise ValueError(
            f"host must be a string, got {type(params['host']).__name__}"
        )

    if "port" not in params:
        raise ValueError("Missing required field 'port'")
    validate_port(params["port"])


def _validate_file_params(params: Dict[str, Any]) -> None:
    """Validate file check parameters."""
    if "path" not in params:
        raise ValueError("Missing required field 'path'")
    validate_file_path(params["path"])

    if "max_age" in params:
        val = params["max_age"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(
                f"max_age must be a number, got {type(val).__name__}"
            )
        if val <= 0:
            raise ValueError(f"max_age must be positive, got {val}")


def _validate_disk_params(params: Dict[str, Any]) -> None:
    """Validate disk check parameters."""
    if "path" not in params:
        raise ValueError("Missing required field 'path'")
    validate_file_path(params["path"])

    if "min_free_percent" not in params:
        raise ValueError("Missing required field 'min_free_percent'")
    validate_percentage(params["min_free_percent"], "min_free_percent")


def _read_yaml_file(path: Path) -> Any:
    """Read and parse a YAML file safely."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _read_config_file(path: Path) -> Any:
    """Read and parse a config file based on its extension."""
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        return _read_yaml_file(path)
    elif suffix == ".json":
        with open(path, "r") as f:
            return json.load(f)
    elif suffix == ".toml":
        with open(path, "rb") as f:
            return toml_load(f)
    else:
        raise ConfigError(f"Unsupported config format: {suffix}")
