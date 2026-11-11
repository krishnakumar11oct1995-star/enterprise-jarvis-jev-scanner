"""Thread-safe event bus for inter-module communication in Jarvis PC Application."""

from __future__ import annotations
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from app.models import EventTopic

logger = logging.getLogger("jarvis.event_bus")


class EventBus:
    """Thread-safe publish/subscribe bus for decoupled component messaging."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._latest_payloads: Dict[str, Any] = {}

    def subscribe(self, topic: EventTopic | str, callback: Callable[[Any], None]) -> None:
        """Subscribe a callback function to an event topic."""
        topic_key = topic.value if isinstance(topic, EventTopic) else str(topic)
        with self._lock:
            if topic_key not in self._subscribers:
                self._subscribers[topic_key] = []
            if callback not in self._subscribers[topic_key]:
                self._subscribers[topic_key].append(callback)
                logger.debug("Subscribed %s to %s", callback, topic_key)

    def unsubscribe(self, topic: EventTopic | str, callback: Callable[[Any], None]) -> None:
        """Unsubscribe a callback from an event topic."""
        topic_key = topic.value if isinstance(topic, EventTopic) else str(topic)
        with self._lock:
            if topic_key in self._subscribers:
                try:
                    self._subscribers[topic_key].remove(callback)
                except ValueError:
                    pass

    def get_latest_payload(self, topic: EventTopic | str, default: Any = None) -> Any:
        """Thread-safely retrieve the most recent payload published for a given topic."""
        topic_key = topic.value if isinstance(topic, EventTopic) else str(topic)
        with self._lock:
            return self._latest_payloads.get(topic_key, default)

    def publish(self, topic: EventTopic | str, payload: Any = None) -> None:
        """Publish an event to all subscribed callbacks thread-safely and cache latest payload."""
        topic_key = topic.value if isinstance(topic, EventTopic) else str(topic)
        with self._lock:
            self._latest_payloads[topic_key] = payload
            callbacks = list(self._subscribers.get(topic_key, []))

        logger.debug("Publishing topic '%s' to %d subscribers", topic_key, len(callbacks))
        for callback in callbacks:
            try:
                callback(payload)
            except Exception as e:
                logger.exception("Error executing subscriber callback for topic %s: %s", topic_key, e)

    def clear(self) -> None:
        """Clear all registered subscribers and cached payloads."""
        with self._lock:
            self._subscribers.clear()
            self._latest_payloads.clear()


# Global singleton instance for convenient access across modules
default_event_bus = EventBus()
