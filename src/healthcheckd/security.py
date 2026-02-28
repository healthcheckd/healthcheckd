"""Input validation functions for OWASP compliance.

All validation functions raise ValueError with a descriptive message on failure.
"""

from __future__ import annotations

import os
import re
from typing import List
from urllib.parse import urlparse

CHECK_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

SYSTEMD_UNIT_RE = re.compile(
    r"^[a-zA-Z0-9@_.\-]+\.(service|socket|timer|mount|target|path|slice|scope)$"
)

VALID_SYSTEMD_STATES = frozenset({
    "active", "inactive", "activating", "deactivating", "failed", "reloading",
    "running", "dead", "exited", "waiting", "listening", "mounted", "plugged",
    "enabled", "disabled", "static", "masked", "indirect", "generated", "alias",
    "enabled-runtime",
})

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# Shell metacharacters that must never appear in command arguments
SHELL_METACHARACTERS = frozenset(";&|`$(){}[]!#~<>\\'\"\n\r")


def validate_check_name(name: str) -> None:
    """Validate a check name (derived from config filename)."""
    if not isinstance(name, str):
        raise ValueError(f"Check name must be a string, got {type(name).__name__}")
    if not CHECK_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid check name: {name!r}. "
            "Must match ^[a-zA-Z0-9_-]{{1,128}}$"
        )


def validate_systemd_unit(unit: str) -> None:
    """Validate a systemd unit name."""
    if not isinstance(unit, str):
        raise ValueError(f"Unit name must be a string, got {type(unit).__name__}")
    if not SYSTEMD_UNIT_RE.fullmatch(unit):
        raise ValueError(
            f"Invalid systemd unit name: {unit!r}. "
            "Must be alphanumeric with a valid unit suffix"
        )


def validate_expected_states(states_csv: str) -> List[str]:
    """Validate and parse a CSV of expected systemd states.

    Returns the list of validated state strings.
    """
    if not isinstance(states_csv, str):
        raise ValueError(
            f"Expected states must be a string, got {type(states_csv).__name__}"
        )
    if not states_csv.strip():
        raise ValueError("Expected states must not be empty")

    states = [s.strip() for s in states_csv.split(",")]
    for state in states:
        if state not in VALID_SYSTEMD_STATES:
            raise ValueError(
                f"Unknown systemd state: {state!r}. "
                f"Valid states: {sorted(VALID_SYSTEMD_STATES)}"
            )
    return states


def validate_command(command: list) -> None:
    """Validate a command list for the run check type."""
    if not isinstance(command, list):
        raise ValueError(
            f"Command must be a list, got {type(command).__name__}"
        )
    if len(command) == 0:
        raise ValueError("Command list must not be empty")
    if len(command) > 64:
        raise ValueError(
            f"Command list too long ({len(command)} elements, max 64)"
        )

    for i, arg in enumerate(command):
        if not isinstance(arg, str):
            raise ValueError(
                f"Command argument {i} must be a string, got {type(arg).__name__}"
            )

    executable = command[0]
    if not os.path.isabs(executable):
        raise ValueError(
            f"Command executable must be an absolute path, got: {executable!r}"
        )


def validate_expected_result(result: str) -> None:
    """Validate an expected_result string for run checks.

    Valid formats: "0", "!0", "0,1,2,3"
    """
    if not isinstance(result, str):
        raise ValueError(
            f"Expected result must be a string, got {type(result).__name__}"
        )
    result = result.strip()
    if not result:
        raise ValueError("Expected result must not be empty")

    if result.startswith("!"):
        # Negation format: !N
        num_part = result[1:]
        try:
            val = int(num_part)
        except ValueError:
            raise ValueError(
                f"Invalid negation in expected_result: {result!r}. "
                "Format: !N where N is 0-255"
            )
        if val < 0 or val > 255:
            raise ValueError(
                f"Exit code in expected_result out of range: {val}. Must be 0-255"
            )
    else:
        # CSV of integers
        parts = [p.strip() for p in result.split(",")]
        for part in parts:
            try:
                val = int(part)
            except ValueError:
                raise ValueError(
                    f"Invalid integer in expected_result: {part!r}"
                )
            if val < 0 or val > 255:
                raise ValueError(
                    f"Exit code in expected_result out of range: {val}. Must be 0-255"
                )


def validate_url(url: str) -> None:
    """Validate a URL for the http check type."""
    if not isinstance(url, str):
        raise ValueError(f"URL must be a string, got {type(url).__name__}")
    if len(url) > 2048:
        raise ValueError(f"URL too long ({len(url)} chars, max 2048)")

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"URL scheme must be http or https, got: {parsed.scheme!r}"
        )
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain credentials (userinfo)")


def validate_file_path(path: str) -> None:
    """Validate a file path for the file check type."""
    if not isinstance(path, str):
        raise ValueError(f"File path must be a string, got {type(path).__name__}")
    if not path:
        raise ValueError("File path must not be empty")
    if not os.path.isabs(path):
        raise ValueError(
            f"File path must be absolute, got: {path!r}"
        )
    if "\x00" in path:
        raise ValueError("File path must not contain null bytes")


def validate_port(port: int) -> None:
    """Validate a TCP port number."""
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError(f"Port must be an integer, got {type(port).__name__}")
    if port < 1 or port > 65535:
        raise ValueError(
            f"Port out of range: {port}. Must be 1-65535"
        )


def validate_percentage(value: object, field_name: str) -> None:
    """Validate a percentage value (0-100)."""
    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be a number, got bool"
        )
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a number, got {type(value).__name__}"
        )
    if value < 0 or value > 100:
        raise ValueError(
            f"{field_name} out of range: {value}. Must be 0-100"
        )
