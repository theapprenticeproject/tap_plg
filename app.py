import asyncio
import logging
import signal
import sys
import os
from dotenv import load_dotenv
from mq.rmq_client import RabbitMQClient
from plag_checker.submissions_checker import SubmissionChecker

__version__ = "1.0.0"

load_dotenv()

def _configure_structured_logging(log_level: str = "INFO") -> None:
    """
    Replace the default plain-text formatter with StructuredJsonFormatter.
    Called once at startup — after this, every logger.info() / logger.error()
    across the entire codebase emits JSON automatically. No other files need changing.
    """
    from monitoring import StructuredJsonFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter(app_name="tap_plg"))
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)


# Configure structured JSON logging at startup
_configure_structured_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def validate_configuration():
    """Validate required environment variables and configuration."""
    required_env_vars = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "RABBITMQ_HOST",
        "RABBITMQ_USER",
        "RABBITMQ_PASS",
    ]

    missing = [var for var in required_env_vars if not os.getenv(var)]
    #print the required env vars and their values for debugging
    # for var in required_env_vars:
    #     logger.info("###################")
    #     logger.info(f"{var}={os.getenv(var)}")
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        raise ValueError(f"Missing required environment variables: {missing}")

    logger.info("Configuration validation passed")


async def health_check(mq_client, db_manager):
    """Perform health checks on critical dependencies."""
    from datetime import datetime

    health_status = {
        "status": "healthy",
        "checks": {},
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        # Check database connection
        await db_manager.init_pool()
        health_status["checks"]["database"] = "healthy"
    except Exception as e:
        health_status["checks"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    try:
        # Check message queue connection
        await mq_client.connect()
        health_status["checks"]["message_queue"] = "healthy"
    except Exception as e:
        health_status["checks"]["message_queue"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    return health_status


def setup_signal_handlers(shutdown_evt):
    """
    Setup signal handlers for graceful shutdown.

    Handles:
    - SIGINT (Ctrl+C)
    - SIGTERM (docker stop, systemctl stop)
    - SIGBREAK (Windows Ctrl+Break)
    """

    def signal_handler(signum, frame):
        sig_name = (
            signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        )
        logger.info(f"Received signal {sig_name}, initiating graceful shutdown...")
        shutdown_evt.set()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Windows-specific signal
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal_handler)

    logger.info("Signal handlers registered (SIGINT, SIGTERM)")


async def main():
    """
    Main application entry point with proper resource management.

    Lifecycle:
    1. Initialize shared database connection pool (ONCE)
    2. Initialize RabbitMQ client and submission checker with shared pool
    3. Connect to database and message queue
    4. Start consuming messages
    5. Wait for shutdown signal
    6. Gracefully cleanup all resources
    """
    global consumer_task
    import os

    os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
    logger.info(f"Starting plagiarism checker application v{__version__}")

    # Validate configuration
    validate_configuration()

    # Initialize shared database connection pool ONCE
    from database.db_manager import DatabaseManager

    db_manager = DatabaseManager()
    await db_manager.init_pool()
    logger.info("Shared database connection pool initialized")

    mq_client = RabbitMQClient()
    # Pass shared database manager to checker
    checker = SubmissionChecker(mq_client, db_manager=db_manager)
    shutdown_evt = asyncio.Event()

    # Setup signal handlers
    setup_signal_handlers(shutdown_evt)

    try:
        # Initialize message queue (database already initialized)
        logger.info("Initializing resources...")
        await checker.initialize()

        logger.info("Application ready, processing submissions")

        # Wait for shutdown signal with periodic checks
        while not shutdown_evt.is_set():
            try:
                await asyncio.wait_for(shutdown_evt.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                # Timeout is expected, continue checking
                continue

        logger.info("Shutdown signal received, cleaning up resources...")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        # Ensure resources are cleaned up with timeout
        logger.info("Closing database and message queue connections...")
        try:
            # Give 30 seconds for graceful shutdown
            await asyncio.wait_for(checker.close(), timeout=30.0)
            # Close shared database pool last
            await db_manager.close()
            logger.info("Application shutdown complete")
        except asyncio.TimeoutError:
            logger.warning("Shutdown timeout exceeded, forcing exit")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated")
    sys.exit(0)
