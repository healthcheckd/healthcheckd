"""Tests for healthcheckd entry point."""

from pathlib import Path
from unittest import mock

import pytest

from healthcheckd.__main__ import main
from healthcheckd.config import ConfigError, MainConfig


class TestMain:
    def test_success(self):
        with mock.patch("healthcheckd.__main__.load_main_config") as mc, \
             mock.patch("healthcheckd.__main__.load_check_configs", return_value=[]), \
             mock.patch("healthcheckd.__main__.asyncio.run") as mock_run, \
             mock.patch("healthcheckd.__main__.sdnotify"):
            mc.return_value = MainConfig()
            result = main()
            mock_run.call_args[0][0].close()
        assert result == 0

    def test_config_error_returns_1(self):
        with mock.patch(
            "healthcheckd.__main__.load_main_config",
            side_effect=ConfigError("bad config"),
        ):
            result = main()
        assert result == 1

    def test_check_config_error_returns_1(self):
        with mock.patch("healthcheckd.__main__.load_main_config") as mc, \
             mock.patch(
                 "healthcheckd.__main__.load_check_configs",
                 side_effect=ConfigError("bad check"),
             ):
            mc.return_value = MainConfig()
            result = main()
        assert result == 1

    def test_creates_checks_from_configs(self):
        from healthcheckd.config import CheckConfig

        configs = [
            CheckConfig(
                name="test",
                check_type="tcp",
                params={"host": "127.0.0.1", "port": 22},
            ),
        ]
        with mock.patch("healthcheckd.__main__.load_main_config") as mc, \
             mock.patch(
                 "healthcheckd.__main__.load_check_configs",
                 return_value=configs,
             ), \
             mock.patch("healthcheckd.__main__.asyncio.run") as mock_run, \
             mock.patch("healthcheckd.__main__.sdnotify"):
            mc.return_value = MainConfig()
            result = main()
            # Close coroutine immediately to avoid unawaited warning
            mock_run.call_args[0][0].close()
        assert result == 0

    def test_calls_asyncio_run(self):
        with mock.patch("healthcheckd.__main__.load_main_config") as mc, \
             mock.patch("healthcheckd.__main__.load_check_configs", return_value=[]), \
             mock.patch("healthcheckd.__main__.asyncio.run") as mock_run, \
             mock.patch("healthcheckd.__main__.sdnotify"):
            mc.return_value = MainConfig()
            main()
            mock_run.assert_called_once()
            mock_run.call_args[0][0].close()

    def test_creates_sdnotify_notifier(self):
        mock_notifier = mock.Mock()
        mock_sdnotify = mock.Mock()
        mock_sdnotify.SystemdNotifier.return_value = mock_notifier

        with mock.patch("healthcheckd.__main__.load_main_config") as mc, \
             mock.patch("healthcheckd.__main__.load_check_configs", return_value=[]), \
             mock.patch("healthcheckd.__main__.asyncio.run") as mock_run, \
             mock.patch("healthcheckd.__main__.sdnotify", mock_sdnotify):
            mc.return_value = MainConfig()
            main()
            mock_sdnotify.SystemdNotifier.assert_called_once_with(False)
            mock_run.call_args[0][0].close()
