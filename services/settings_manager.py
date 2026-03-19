"""
Settings persistence — JSON file with atomic save and corruption recovery.
"""
from __future__ import annotations
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from threading import Lock

from core.interfaces import ISettingsManager
from core.models import AppSettings


class SettingsManager(ISettingsManager):

    DEFAULT_PATH = Path.home() / ".ai_code_sherlock" / "settings.json"

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else self.DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def load(self) -> AppSettings:
        with self._lock:
            if not self._path.exists():
                return AppSettings()
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                return AppSettings.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # Backup corrupted file, return defaults
                backup = self._path.with_suffix(
                    f".backup.{datetime.now():%Y%m%d_%H%M%S}.json"
                )
                shutil.copy2(self._path, backup)
                print(f"[SettingsManager] Corrupted settings backed up to {backup}: {e}")
                return AppSettings()

    def save(self, settings: AppSettings) -> None:
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False)
                # Atomic rename
                shutil.move(str(tmp), str(self._path))
            except Exception:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                raise
