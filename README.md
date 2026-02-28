# healthcheckd

A health check daemon for AWS ALB/NLB integration with Prometheus metrics and systemd notify support.

healthcheckd runs as a systemd service, periodically executing configurable health checks and exposing their results over HTTP. Load balancers poll the HTTP endpoints to determine instance health, while Prometheus scrapes the `/metrics` endpoint for observability.

## Features

- **Six check types**: systemd unit state, command execution, HTTP endpoint, TCP port, file existence/age, disk free space
- **Three HTTP endpoints**: `/simple` (pass/fail), `/complex` (per-check detail), `/metrics` (Prometheus)
- **Zero runtime dependencies**: Ships as a self-contained PyInstaller binary — no Python installation required on target hosts
- **systemd integration**: `Type=notify` with `READY=1`, `WATCHDOG=1`, `STOPPING=1` and `SIGHUP` hot-reload
- **Security hardened**: SSRF protection on HTTP checks, empty subprocess environments, strict input validation, locked-down systemd unit
- **DEB and RPM packages**: Built automatically via GitHub Actions on version tags

## Installation

### From GitHub Releases

Download the `.deb` or `.rpm` from the [latest release](https://github.com/JonTheNiceGuy/healthcheckd/releases/latest):

```bash
# Debian/Ubuntu
sudo dpkg -i healthcheckd_*.deb

# RHEL/AlmaLinux/Fedora
sudo rpm -i healthcheckd-*.rpm
```

### From source

```bash
pip install . pyinstaller
pyinstaller --onefile --name healthcheckd src/healthcheckd/__main__.py
sudo cp dist/healthcheckd /usr/bin/healthcheckd
```

## Configuration

### Main config: `/etc/healthcheckd/config`

```yaml
port: 9990           # TCP port to listen on (default: 9990)
bind: "0.0.0.0"      # Bind address (default: 0.0.0.0)
check_frequency: 30  # Seconds between check cycles (default: 30, minimum: 1)
log_level: INFO      # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

All fields are optional. Sensible defaults are used if the file is missing.

### Check configs: `/etc/healthcheckd/config.d/`

Each check is defined in its own file. Supported formats: `.yaml`, `.yml`, `.json`, `.toml`. The check name is derived from the filename (e.g., `sshd.yaml` creates a check named `sshd`).

## Health Check Types

### systemd — Unit State

Verifies a systemd unit is in the expected state(s).

```yaml
type: systemd
unit: sshd.service
expected_states: running,enabled
```

Valid states include: `active`, `inactive`, `running`, `dead`, `exited`, `enabled`, `disabled`, `static`, `masked`, and others. Timer-controlled services can use `expected_states: enabled` alone since they are inactive between runs.

### run — Command Execution

Runs a command and checks the exit code.

```yaml
type: run
command: ["/usr/bin/systemctl", "is-active", "nginx.service"]
expected_result: "0"          # default: "0"
```

`expected_result` supports:
- `"0"` — must exit with code 0
- `"0,1,2"` — must exit with one of these codes
- `"!0"` — must NOT exit with code 0

Commands must use absolute paths and are executed with an empty environment. Shell metacharacters are rejected at config validation time.

### http — HTTP Endpoint

Makes a GET request and checks the response.

```yaml
type: http
url: https://example.com/health
expected_result: 200          # HTTP status code (default: 200)
validate_tls: true            # default: true
containing_string: "ok"       # optional: string that must appear in response body
```

Redirects are not followed. SSRF protection blocks requests that resolve to link-local addresses (`169.254.0.0/16`, including the AWS metadata service), loopback (`127.0.0.0/8`, `::1`), and other dangerous ranges. Private RFC-1918 ranges are allowed, so checks against internal services work.

### tcp — TCP Port Connectivity

Opens a TCP connection and immediately closes it.

```yaml
type: tcp
host: 127.0.0.1
port: 22
```

### file — File Existence / Age

Checks that a file exists, and optionally that it is not too old.

```yaml
type: file
path: /var/run/my-app/heartbeat
max_age: 300                  # optional: max age in seconds
```

### disk — Disk Free Space

Checks that a filesystem has at least a minimum percentage of free space.

```yaml
type: disk
path: /
min_free_percent: 10
```

## HTTP Endpoints

| Endpoint | Description |
|---|---|
| `GET /simple` | Returns `200` if all checks are healthy, `400` if any are unhealthy. No response body. |
| `GET /complex` | Same status codes as `/simple`, but returns a plain-text body listing each check and its status (`1` = healthy, `0` = unhealthy). |
| `GET /metrics` | Prometheus exposition format with per-check and daemon-level metrics. |

All endpoints return `503` until the first check cycle completes, preventing load balancers from routing traffic during startup.

### Example `/complex` response

```
sshd 1
disk_root 1
app_health 0
```

### Prometheus metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `healthcheckd_check_status` | Gauge | `check` | `1` = healthy, `0` = unhealthy |
| `healthcheckd_check_duration_seconds` | Gauge | `check` | Execution time of the last check run |
| `healthcheckd_up` | Gauge | — | Always `1` while the daemon is running |
| `healthcheckd_last_cycle_timestamp_seconds` | Gauge | — | Unix timestamp of the last completed check cycle |
| `healthcheckd_last_cycle_duration_seconds` | Gauge | — | Wall-clock duration of the last check cycle |
| `healthcheckd_checks_configured` | Gauge | — | Number of checks currently loaded |

## systemd Integration

healthcheckd uses `Type=notify` for reliable startup notification. The daemon sends:

- `READY=1` after the first check cycle completes and the HTTP server is listening
- `WATCHDOG=1` after every subsequent check cycle (systemd kills the process if this stops arriving within `WatchdogSec=90`)
- `STOPPING=1` on SIGTERM/SIGINT before graceful shutdown

### Hot-reload

Send `SIGHUP` to reload check configs from `/etc/healthcheckd/config.d/` without restarting:

```bash
sudo systemctl reload healthcheckd
```

If the new config fails to parse, the existing configuration is preserved and an error is logged.

### Service management

```bash
sudo systemctl enable --now healthcheckd   # start and enable on boot
sudo systemctl status healthcheckd         # check status
sudo systemctl reload healthcheckd         # reload check configs
journalctl -u healthcheckd -f             # follow logs
```

## Security

The systemd unit runs with extensive hardening:

- Dedicated `healthcheckd` user/group with no login shell
- `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`
- Kernel protections: `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectKernelLogs`
- `NoNewPrivileges=yes`, empty `CapabilityBoundingSet`
- System call filter restricted to `@system-service` minus privileged categories
- Network restricted to `AF_INET`, `AF_INET6`, `AF_UNIX`
- Resource limits: `MemoryMax=256M`, `LimitNPROC=64`, `LimitNOFILE=1024`

Application-level protections:

- All config values are validated at load time against strict patterns
- Subprocess commands run with an empty environment (`env={}`)
- HTTP checks include SSRF protection that validates resolved IPs before connecting
- Shell metacharacters are rejected in command arguments
- Symlinks outside the config directory are silently skipped

## Development

### Running from source

```bash
pip install -e '.[dev]'
python -m healthcheckd
```

### Running tests

```bash
pytest
```

### Vagrant testing

A Vagrantfile is included to test RPM packaging on AlmaLinux 10:

```bash
vagrant up        # builds binary, creates RPM, installs, starts service, runs smoke tests
vagrant provision # re-run the full test cycle
vagrant destroy   # clean up
```

## Project Structure

```
src/healthcheckd/
├── __init__.py          # Package version
├── __main__.py          # Entry point, signal handling, logging
├── config.py            # Config loading and validation
├── server.py            # aiohttp app factory and routes
├── handlers.py          # HTTP endpoint handlers
├── metrics.py           # Prometheus metrics management
├── scheduler.py         # Async check scheduler with watchdog
├── security.py          # Input validation
├── compat.py            # Python 3.10/3.11+ TOML compatibility
└── checks/
    ├── __init__.py      # CheckResult dataclass, Check protocol
    ├── disk.py          # Disk free space check
    ├── file.py          # File existence/age check
    ├── http.py          # HTTP endpoint check with SSRF protection
    ├── run.py           # Command execution check
    ├── systemd.py       # systemd unit state check
    └── tcp.py           # TCP port connectivity check
```

## License

[Unlicense](LICENSE) — public domain.
