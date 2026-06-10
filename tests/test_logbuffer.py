"""Unit tests for the in-memory ring buffer log handler."""

import logging

from homekit_bridge.logbuffer import RingBufferLogHandler


def _log(handler, level, msg, name="test"):
    record = logging.LogRecord(name, level, __file__, 0, msg, None, None)
    handler.emit(record)


def test_records_capture_shape():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.INFO, "hello", name="ccu3")
    recs = h.records()
    assert len(recs) == 1
    r = recs[0]
    assert r["level"] == "INFO"
    assert r["logger"] == "ccu3"
    assert r["message"] == "hello"
    assert isinstance(r["ts"], float)
    assert set(r) == {"ts", "level", "logger", "message"}


def test_maxlen_eviction():
    h = RingBufferLogHandler(capacity=3)
    for i in range(5):
        _log(h, logging.INFO, f"m{i}")
    assert [r["message"] for r in h.records()] == ["m2", "m3", "m4"]


def test_level_filter_is_gte():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.DEBUG, "d")
    _log(h, logging.INFO, "i")
    _log(h, logging.WARNING, "w")
    _log(h, logging.ERROR, "e")
    assert [r["message"] for r in h.records(level="WARNING")] == ["w", "e"]


def test_limit_keeps_last_n():
    h = RingBufferLogHandler(capacity=10)
    for i in range(5):
        _log(h, logging.INFO, f"m{i}")
    assert [r["message"] for r in h.records(limit=2)] == ["m3", "m4"]


def test_unknown_level_means_no_filter():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.INFO, "i")
    assert len(h.records(level="BOGUS")) == 1


def test_limit_zero_returns_empty():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.INFO, "i")
    assert h.records(limit=0) == []


def test_level_filter_includes_critical():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.WARNING, "w")
    _log(h, logging.CRITICAL, "c")
    assert [r["message"] for r in h.records(level="WARNING")] == ["w", "c"]


def test_custom_numeric_level_does_not_crash_filter():
    h = RingBufferLogHandler(capacity=10)
    _log(h, 15, "custom")          # non-standard level -> levelname "Level 15"
    _log(h, logging.ERROR, "e")
    # Must not raise; the custom-level (15 < WARNING=30) record is filtered out.
    assert [r["message"] for r in h.records(level="WARNING")] == ["e"]
