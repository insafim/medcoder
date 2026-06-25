"""Structured JSON logging keyed by trace_id.

Every log record carries (at minimum) `trace_id`, `stage`, and elapsed_ms when
emitted via the helper `log_event`. This is the audit trail the brief asks for.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # python-json-logger < 3.x
    from pythonjsonlogger.jsonlogger import JsonFormatter

_TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)
_configured = False


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _TRACE_ID.get() or "no-trace"
        return True


def configure_logging(level: str = "INFO", json_mode: bool = True) -> None:
    """Idempotent root-logger configuration."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    if json_mode:
        formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(trace_id)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s"
        )
    handler.setFormatter(formatter)
    handler.addFilter(_TraceIdFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # litellm + sentence-transformers + faiss are noisy at INFO
    for noisy in ("LiteLLM", "httpx", "sentence_transformers", "faiss"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def trace_context(trace_id: str | None = None):
    """Bind a trace_id for the duration of the block (and child threads via contextvars)."""
    tid = trace_id or new_trace_id()
    token = _TRACE_ID.set(tid)
    try:
        yield tid
    finally:
        _TRACE_ID.reset(token)


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


@contextmanager
def timed(stage: str, sink: dict[str, float] | None = None):
    """Record per-stage latency (ms) into `sink` if provided; always logs the timing."""
    log = get_logger("medcoder.timing")
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        if sink is not None:
            sink[stage] = sink.get(stage, 0.0) + ms
        log.info("stage_complete", extra={"stage": stage, "elapsed_ms": round(ms, 2)})
