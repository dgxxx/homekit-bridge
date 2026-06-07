import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe in-process event bus.

    Handler errors are caught and logged, never propagated — a broken handler
    cannot disrupt subsequent handlers or the publisher.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def publish(self, topic: str, event: Any) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("EventBus handler error on topic %r", topic)
