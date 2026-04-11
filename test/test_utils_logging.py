"""
test/test_utils_logging.py -- src/utils/logging.py 단위 테스트
"""

from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

import pytest

pytestmark = [pytest.mark.unit]


class TestGetLogger:
    def test_returns_logger_instance(self):
        from src.utils.logging import get_logger

        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_same_name_returns_same_logger(self):
        from src.utils.logging import get_logger

        logger1 = get_logger("test_same")
        logger2 = get_logger("test_same")
        assert logger1 is logger2

    def test_different_name_returns_different_logger(self):
        from src.utils.logging import get_logger

        logger1 = get_logger("module_a")
        logger2 = get_logger("module_b")
        assert logger1 is not logger2


class TestSetupLogging:
    def test_sets_root_logger_level(self):
        from src.utils.logging import setup_logging

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"

        with patch("src.utils.logging.get_settings", return_value=mock_settings):
            setup_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_suppresses_external_loggers(self):
        from src.utils.logging import setup_logging

        mock_settings = MagicMock()
        mock_settings.log_level = "INFO"

        with patch("src.utils.logging.get_settings", return_value=mock_settings):
            setup_logging()

        assert logging.getLogger("asyncio").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_handler_format(self):
        from src.utils.logging import setup_logging

        mock_settings = MagicMock()
        mock_settings.log_level = "INFO"

        with patch("src.utils.logging.get_settings", return_value=mock_settings):
            setup_logging()

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        fmt = root.handlers[0].formatter
        assert fmt is not None
