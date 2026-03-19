"""
Structured logger — thread-safe, real-time subscriber notifications.
"""
from __future__ import annotations
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.interfaces import IStructuredLogger
from core.models import LogEntry, LogLevel


class StructuredLogger(IStructuredLogger):

    MAX_BUFFER = 10_000

    def __init__(self):
        self._buffer: deque[LogEntry] = deque(maxlen=self.MAX_BUFFER)
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[LogEntry], None]] = []

    def subscribe(self, callback: Callable[[LogEntry], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[LogEntry], None]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s != callback]

    def log(self, entry: LogEntry) -> None:
        with self._lock:
            self._buffer.append(entry)
            subs = list(self._subscribers)
        # Notify outside lock to avoid deadlocks
        for cb in subs:
            try:
                cb(entry)
            except Exception:
                pass

    def info(self, message: str, source: str = "") -> None:
        self.log(LogEntry(level=LogLevel.INFO, message=message, source=source or None))

    def warning(self, message: str, source: str = "") -> None:
        self.log(LogEntry(level=LogLevel.WARNING, message=message, source=source or None))

    def error(self, message: str, source: str = "", exception: str = "") -> None:
        self.log(LogEntry(
            level=LogLevel.ERROR, message=message,
            source=source or None,
            exception=exception or None
        ))

    def debug(self, message: str, source: str = "") -> None:
        self.log(LogEntry(level=LogLevel.DEBUG, message=message, source=source or None))

    def get_recent(self, count: int = 100) -> list[LogEntry]:
        with self._lock:
            entries = list(self._buffer)
        return entries[-count:]

    def get_errors(self, count: int = 50) -> list[LogEntry]:
        with self._lock:
            entries = list(self._buffer)
        return [e for e in entries if e.level in (LogLevel.ERROR, LogLevel.WARNING)][-count:]

    def export(self, file_path: str) -> None:
        with self._lock:
            entries = list(self._buffer)
        with open(file_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(e.formatted + "\n")

    def format_for_ai(self, max_entries: int = 100) -> str:
        """Format recent logs for AI consumption — errors first."""
        entries = self.get_recent(max_entries)
        lines = []
        for e in entries:
            if e.level in (LogLevel.ERROR, LogLevel.WARNING):
                lines.append(e.formatted)
        # Add last few info lines for context
        info_lines = [e.formatted for e in entries if e.level == LogLevel.INFO][-10:]
        return "\n".join(lines + info_lines)
