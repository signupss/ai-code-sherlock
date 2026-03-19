"""
Signal Folder Watcher — monitors request/response folders in real-time.
Used for diagnostics and debugging ZennoPoster integration.
"""
from __future__ import annotations
import asyncio
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer


class SignalEvent:
    """Represents a file signal event."""
    def __init__(self, event_type: str, file_path: str, folder_type: str):
        self.event_type = event_type       # "created" | "deleted" | "modified"
        self.file_path = file_path
        self.folder_type = folder_type     # "request" | "response"
        self.timestamp = datetime.now()
        self.file_size: int = 0
        self.content_preview: str = ""

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S")
        return f"[{ts}] {self.folder_type.upper()} {self.event_type}: {Path(self.file_path).name}"


class FolderWatcherThread(QThread):
    """
    Background thread that polls signal folders for changes.
    Uses polling (250ms) rather than inotify for cross-platform reliability.
    """

    signal_event = pyqtSignal(object)   # SignalEvent

    def __init__(
        self,
        request_folder: str,
        response_folder: str,
        poll_interval: float = 0.25,
        parent=None,
    ):
        super().__init__(parent)
        self._req_folder = Path(request_folder)
        self._res_folder = Path(response_folder)
        self._poll_interval = poll_interval
        self._running = False
        self._known_req: dict[str, float] = {}   # filename → mtime
        self._known_res: dict[str, float] = {}

    def run(self):
        self._running = True
        self._req_folder.mkdir(parents=True, exist_ok=True)
        self._res_folder.mkdir(parents=True, exist_ok=True)

        # Initialize known state
        self._known_req = self._scan(self._req_folder)
        self._known_res = self._scan(self._res_folder)

        while self._running:
            self._check_folder(self._req_folder, self._known_req, "request")
            self._check_folder(self._res_folder, self._known_res, "response")
            self.msleep(int(self._poll_interval * 1000))

    def stop(self):
        self._running = False
        self.wait(2000)

    def _check_folder(
        self,
        folder: Path,
        known: dict[str, float],
        folder_type: str,
    ):
        try:
            current = self._scan(folder)
        except OSError:
            return

        # Created / modified
        for fname, mtime in current.items():
            if fname not in known:
                evt = self._make_event("created", folder / fname, folder_type)
                self.signal_event.emit(evt)
            elif mtime != known[fname]:
                evt = self._make_event("modified", folder / fname, folder_type)
                self.signal_event.emit(evt)

        # Deleted
        for fname in list(known):
            if fname not in current:
                evt = SignalEvent("deleted", str(folder / fname), folder_type)
                self.signal_event.emit(evt)

        known.clear()
        known.update(current)

    @staticmethod
    def _scan(folder: Path) -> dict[str, float]:
        try:
            return {
                e.name: e.stat().st_mtime
                for e in folder.iterdir()
                if e.is_file() and e.suffix == ".txt"
            }
        except OSError:
            return {}

    @staticmethod
    def _make_event(event_type: str, path: Path, folder_type: str) -> SignalEvent:
        evt = SignalEvent(event_type, str(path), folder_type)
        try:
            evt.file_size = path.stat().st_size
            if evt.file_size < 4096:  # Only preview small files
                with open(path, encoding="utf-8", errors="replace") as f:
                    evt.content_preview = f.read(200)
        except OSError:
            pass
        return evt


class SignalMonitorWidget(QObject):
    """
    Manages watcher thread lifecycle and exposes status to UI.
    """

    status_changed = pyqtSignal(str, str)   # status_text, color
    event_received = pyqtSignal(object)     # SignalEvent

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: FolderWatcherThread | None = None
        self._request_folder: str = ""
        self._response_folder: str = ""
        self._active = False
        self._event_count = 0

    def start(self, request_folder: str, response_folder: str):
        self.stop()
        self._request_folder = request_folder
        self._response_folder = response_folder
        self._active = True

        self._thread = FolderWatcherThread(request_folder, response_folder)
        self._thread.signal_event.connect(self._on_event)
        self._thread.start()

        self.status_changed.emit("● Мониторинг активен", "#9ECE6A")

    def stop(self):
        if self._thread and self._thread.isRunning():
            self._thread.stop()
        self._thread = None
        self._active = False
        self.status_changed.emit("○ Мониторинг остановлен", "#565f89")

    def is_active(self) -> bool:
        return self._active

    def _on_event(self, evt: SignalEvent):
        self._event_count += 1
        self.event_received.emit(evt)

    @property
    def event_count(self) -> int:
        return self._event_count
