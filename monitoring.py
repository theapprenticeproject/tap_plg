# tap_plg/monitoring.py
#
# Structured JSON logging for tap_plg.
#
# Unlike tap_lms and rag_service (Frappe apps), tap_plg uses Python's
# standard logging module. This module provides:
#
#   1. StructuredJsonFormatter — replaces the default plain-text formatter.
#      Swap it in once in app.py and EVERY existing logger.* call across
#      the entire codebase emits JSON automatically. Zero changes elsewhere.
#
#   2. emit() — for explicit structured log lines with extra fields
#      (submission_id, step timings, etc.) where the standard logger
#      doesn't carry enough context.

import json
import logging
import time
import traceback as tb
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Fields that are part of LogRecord internals — excluded from the JSON output
# to avoid noise.
_EXCLUDED_LOG_RECORD_FIELDS = frozenset({
    "msg", "args", "levelname", "name", "exc_info", "exc_text",
    "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName",
    "process", "message", "asctime", "filename", "module", "pathname",
})


class StructuredJsonFormatter(logging.Formatter):
    """
    Replaces the default log formatter with structured JSON output.

    GCP Cloud Logging parses the `severity` and `message` fields automatically.
    All extra fields passed via logger.info("msg", extra={...}) are included
    as top-level JSON fields and become queryable in Log Explorer.

    Usage in app.py:
        from tap_plg.monitoring import StructuredJsonFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter(app_name="tap_plg"))
        logging.root.setLevel(logging.INFO)
        logging.root.addHandler(handler)
    """

    # Map Python log level names to GCP severity labels
    _SEVERITY_MAP = {
        "DEBUG":    "DEBUG",
        "INFO":     "INFO",
        "WARNING":  "WARNING",
        "ERROR":    "ERROR",
        "CRITICAL": "CRITICAL",
    }

    def __init__(self, app_name: str = "tap_plg"):
        super().__init__()
        self.app_name = app_name
        # Read once at startup — APP_ENV is stable for the process lifetime
        import os
        self.app_env = os.environ.get("APP_ENV", "unknown")

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "severity": self._SEVERITY_MAP.get(record.levelname, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "app": self.app_name,
            "app_env": self.app_env,
        }

        # Include exception traceback if present
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)

        # Include any extra fields passed via logger.info(..., extra={...})
        for key, val in record.__dict__.items():
            if key not in _EXCLUDED_LOG_RECORD_FIELDS:
                payload[key] = val

        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            # Fallback to plain text if JSON serialisation fails
            return f'{{"severity":"ERROR","message":"log serialisation failed","raw":"{record.getMessage()}"}}'


def emit(logger: logging.Logger, severity: str, message: str, **kwargs) -> None:
    """
    Emit a structured log line with explicit extra fields.

    Args:
        logger:   the module-level logger (logging.getLogger(__name__))
        severity: "info" | "warning" | "error"
        message:  short machine-readable event name
        **kwargs: extra fields (submission_id, step, duration_ms, etc.)
    """
    try:
        level = getattr(logging, severity.upper(), logging.INFO)
        logger.log(level, message, extra={"message_event": message, **kwargs})
    except Exception:
        pass


# ── Convenience wrappers for pipeline events ──────────────────────────────────

def record_submission_received(logger: logging.Logger, submission_id: str, student_id: str = None) -> None:
    emit(logger, "info", "plg_submission_received",
         submission_id=submission_id, student_id=student_id)


def record_detection_step(
    logger: logging.Logger,
    submission_id: str,
    step: str,
    status: str,
    duration_ms: float,
    result: str = None,
    error: str = None,
) -> None:
    """
    Emit one log line per detection step.

    step:   "image_validation" | "hash_check" | "ai_detection" |
            "clip_similarity" | "pgvector_search"
    status: "complete" | "failed" | "skip"
    result: e.g. "original", "near_duplicate", "ai_generated"
    """
    emit(
        logger,
        "info" if status != "failed" else "error",
        f"detection_step_{status}",
        submission_id=submission_id,
        step=step,
        duration_ms=round(duration_ms, 2),
        result=result,
        error=error,
    )


def record_result_published(
    logger: logging.Logger,
    submission_id: str,
    plagiarism_status: str,
    is_plagiarized: bool,
    is_ai_generated: bool,
    total_duration_ms: float,
) -> None:
    emit(
        logger,
        "info",
        "plg_result_published",
        submission_id=submission_id,
        plagiarism_status=plagiarism_status,
        is_plagiarized=is_plagiarized,
        is_ai_generated=is_ai_generated,
        total_duration_ms=round(total_duration_ms, 2),
    )
