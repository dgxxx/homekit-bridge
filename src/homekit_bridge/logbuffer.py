"""In-memory ring buffer logging handler for the web log viewer.

Keeps the most recent log records in a bounded, thread-safe deque so the web
API can expose them at /api/logs.  No persistence — the buffer is RAM only and
resets on restart.
"""

import collections
import logging
import threading

DEFAULT_CAPACITY = 500


class RingBufferLogHandler(logging.Handler):
    """A logging.Handler that keeps the last *capacity* records in memory."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._buf: collections.deque[dict] = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": record.created,
                "level": record.levelname,
                "levelno": record.levelno,
                "logger": record.name,
                "message": record.getMessage(),
            }
        except Exception:
            self.handleError(record)
            return
        with self._lock:
            self._buf.append(entry)

    def records(self, level: str | None = None, limit: int | None = None) -> list[dict]:
        """Return buffered records oldest-first.

        *level* (if given and valid) keeps only records at or above that level —
        e.g. ``"WARNING"`` yields WARNING/ERROR/CRITICAL.  An unknown level string
        is treated as no filter.  *limit* keeps only the last N records.
        """
        with self._lock:
            items = list(self._buf)
        if level:
            threshold = logging.getLevelName(level.upper())
            if isinstance(threshold, int):
                items = [r for r in items if r["levelno"] >= threshold]
        if limit is not None:
            items = items[-limit:] if limit > 0 else []
        return items
