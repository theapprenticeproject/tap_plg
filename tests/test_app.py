"""
Comprehensive tests for app.py

Tests for application initialization, health checks, signal handling, and main orchestration.
"""

import asyncio
import signal
import pytest
from unittest.mock import AsyncMock
import sys

from app import validate_configuration, health_check, setup_signal_handlers


class TestConfigurationValidation:
    """Tests for configuration validation."""

    def test_validate_configuration_success(self, monkeypatch):
        """Test configuration validation with all required env vars."""
        monkeypatch.setenv("POSTGRES_USER", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DB", "db")
        monkeypatch.setenv("POSTGRES_HOST", "host")
        monkeypatch.setenv("RABBITMQ_HOST", "rmq")
        monkeypatch.setenv("RABBITMQ_USER", "user")
        monkeypatch.setenv("RABBITMQ_PASS", "pass")

        # Should not raise
        validate_configuration()

    def test_validate_configuration_missing_vars(self, monkeypatch):
        """Test configuration validation with missing env vars."""
        # Clear any existing env vars
        for var in [
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "POSTGRES_HOST",
            "RABBITMQ_HOST",
            "RABBITMQ_USER",
            "RABBITMQ_PASS",
        ]:
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(ValueError) as exc_info:
            validate_configuration()

        assert "Missing required environment variables" in str(exc_info.value)

    def test_validate_configuration_partial_missing(self, monkeypatch):
        """Test configuration validation with some missing env vars."""
        monkeypatch.setenv("POSTGRES_USER", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.delenv("POSTGRES_DB", raising=False)
        monkeypatch.delenv("RABBITMQ_HOST", raising=False)

        with pytest.raises(ValueError):
            validate_configuration()


class TestHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self):
        """Test health check when all services are healthy."""
        mock_mq = AsyncMock()
        mock_db = AsyncMock()
        mock_mq.connect = AsyncMock()
        mock_db.init_pool = AsyncMock()

        result = await health_check(mock_mq, mock_db)

        assert result["status"] == "healthy"
        assert result["checks"]["database"] == "healthy"
        assert result["checks"]["message_queue"] == "healthy"
        assert "timestamp" in result
        mock_db.init_pool.assert_called_once()
        mock_mq.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_database_unhealthy(self):
        """Test health check when database is unhealthy."""
        mock_mq = AsyncMock()
        mock_db = AsyncMock()
        mock_mq.connect = AsyncMock()
        mock_db.init_pool = AsyncMock(side_effect=Exception("DB connection failed"))

        result = await health_check(mock_mq, mock_db)

        assert result["status"] == "unhealthy"
        assert "unhealthy" in result["checks"]["database"]
        assert "DB connection failed" in result["checks"]["database"]

    @pytest.mark.asyncio
    async def test_health_check_mq_unhealthy(self):
        """Test health check when message queue is unhealthy."""
        mock_mq = AsyncMock()
        mock_db = AsyncMock()
        mock_mq.connect = AsyncMock(side_effect=Exception("MQ connection failed"))
        mock_db.init_pool = AsyncMock()

        result = await health_check(mock_mq, mock_db)

        assert result["status"] == "unhealthy"
        assert "unhealthy" in result["checks"]["message_queue"]
        assert "MQ connection failed" in result["checks"]["message_queue"]

    @pytest.mark.asyncio
    async def test_health_check_both_unhealthy(self):
        """Test health check when both services are unhealthy."""
        mock_mq = AsyncMock()
        mock_db = AsyncMock()
        mock_mq.connect = AsyncMock(side_effect=Exception("MQ failed"))
        mock_db.init_pool = AsyncMock(side_effect=Exception("DB failed"))

        result = await health_check(mock_mq, mock_db)

        assert result["status"] == "unhealthy"
        assert "unhealthy" in result["checks"]["database"]
        assert "unhealthy" in result["checks"]["message_queue"]


class TestSignalHandlers:
    """Tests for signal handler setup."""

    def test_setup_signal_handlers_basic(self):
        """Test basic signal handler setup."""
        shutdown_evt = asyncio.Event()

        setup_signal_handlers(shutdown_evt)

        # Verify handlers are registered (they should not raise)
        assert signal.getsignal(signal.SIGINT) is not signal.SIG_DFL
        assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL

    def test_signal_handler_sets_event(self):
        """Test that signal handler sets the shutdown event."""
        shutdown_evt = asyncio.Event()
        setup_signal_handlers(shutdown_evt)

        # Simulate receiving SIGINT
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)

        # Event should be set
        assert shutdown_evt.is_set()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_setup_signal_handlers_windows(self):
        """Test signal handler setup on Windows includes SIGBREAK."""
        shutdown_evt = asyncio.Event()

        setup_signal_handlers(shutdown_evt)

        # On Windows, SIGBREAK should also be registered
        assert signal.getsignal(signal.SIGBREAK) is not signal.SIG_DFL
