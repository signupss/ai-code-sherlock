"""
Version Control Service — file-level backup and restore system.

Every time a patch is applied:
  1. The original file is backed up with timestamp + hash
  2. The patch metadata is stored alongside
  3. User can list, preview, and restore any version

Storage layout:
  .sherlock_versions/
    <relative_path>/
      20241215_143022_abc123.py      ← file snapshot
      20241215_143022_abc123.meta    ← JSON metadata
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────
#  Data Models
# ──────────────────────────────────────────────────────────

@dataclass
class FileVersion:
    file_path: str              # absolute original path
    relative_path: str          # relative to project root
    timestamp: str              # "20241215_143022"
    content_hash: str           # sha256[:12]
    backup_path: str            # absolute path to backup file
    description: str = ""       # patch description or "manual save"
    patch_search: str = ""      # what was searched
    patch_replace: str = ""     # what was replaced
    lines_before: int = 0
    lines_after: int = 0
    size_bytes: int = 0

    @property
    def display_time(self) -> str:
        try:
            dt = datetime.strptime(self.timestamp, "%Y%m%d_%H%M%S")
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            return self.timestamp

    @property
    def version_id(self) -> str:
        return f"{self.timestamp}_{self.content_hash}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FileVersion":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ProjectVersionSnapshot:
    """A named snapshot of multiple files at once (like a git commit)."""
    snapshot_id: str
    name: str
    description: str
    timestamp: str
    file_versions: list[FileVersion] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "name": self.name,
            "description": self.description,
            "timestamp": self.timestamp,
            "file_versions": [v.to_dict() for v in self.file_versions],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectVersionSnapshot":
        fvs = [FileVersion.from_dict(v) for v in d.get("file_versions", [])]
        return cls(
            snapshot_id=d["snapshot_id"],
            name=d["name"],
            description=d["description"],
            timestamp=d["timestamp"],
            file_versions=fvs,
            created_at=d.get("created_at", ""),
        )


# ──────────────────────────────────────────────────────────
#  Version Control Service
# ──────────────────────────────────────────────────────────

class VersionControlService:

    VERSIONS_DIR = ".sherlock_versions"
    INDEX_FILE   = "index.json"

    def __init__(self, project_root: Optional[str] = None):
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._versions_dir = self._project_root / self.VERSIONS_DIR
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._versions_dir / self.INDEX_FILE
        self._index: dict[str, list[dict]] = self._load_index()

    # ── Core Operations ───────────────────────────────────

    def backup_file(
        self,
        file_path: str,
        description: str = "",
        patch_search: str = "",
        patch_replace: str = "",
    ) -> FileVersion:
        """
        Create a backup of a file BEFORE modifying it.
        Returns FileVersion with backup path.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Cannot backup — file not found: {file_path}")

        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Determine relative path (for grouping)
        try:
            rel = str(path.relative_to(self._project_root))
        except ValueError:
            rel = path.name

        # Create backup directory for this file
        safe_rel = rel.replace("\\", "_").replace("/", "_").replace(":", "_")
        file_backup_dir = self._versions_dir / safe_rel
        file_backup_dir.mkdir(parents=True, exist_ok=True)

        # Copy file
        backup_name = f"{timestamp}_{content_hash}{path.suffix}"
        backup_path = file_backup_dir / backup_name
        shutil.copy2(str(path), str(backup_path))

        text_content = content.decode("utf-8", errors="replace")
        version = FileVersion(
            file_path=str(path),
            relative_path=rel,
            timestamp=timestamp,
            content_hash=content_hash,
            backup_path=str(backup_path),
            description=description or "auto-backup before patch",
            patch_search=patch_search[:500],
            patch_replace=patch_replace[:500],
            lines_before=len(text_content.splitlines()),
            lines_after=0,  # filled after patch
            size_bytes=len(content),
        )

        # Save metadata
        meta_path = file_backup_dir / f"{timestamp}_{content_hash}.meta"
        meta_path.write_text(
            json.dumps(version.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Update index
        key = rel
        if key not in self._index:
            self._index[key] = []
        self._index[key].insert(0, version.to_dict())
        self._save_index()

        return version

    def update_lines_after(self, version: FileVersion, new_content: str) -> None:
        """Call after patch applied to record line count delta."""
        version.lines_after = len(new_content.splitlines())
        # Update meta file
        meta_path = Path(version.backup_path).with_suffix(".meta")
        if meta_path.exists():
            meta_path.write_text(
                json.dumps(version.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        # Update index
        key = version.relative_path
        if key in self._index:
            for item in self._index[key]:
                if item.get("version_id") == version.version_id or (
                    item.get("timestamp") == version.timestamp and
                    item.get("content_hash") == version.content_hash
                ):
                    item["lines_after"] = version.lines_after
                    break
            self._save_index()

    def restore_version(self, version: FileVersion) -> str:
        """
        Restore a file to a previous version.
        Returns the restored content.
        Automatically backs up current file before restoring.
        """
        backup_path = Path(version.backup_path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        target = Path(version.file_path)

        # Backup current state before restoring
        if target.exists():
            self.backup_file(
                str(target),
                description=f"auto-backup before restore to {version.display_time}"
            )

        # Restore
        shutil.copy2(str(backup_path), str(target))
        content = target.read_text(encoding="utf-8", errors="replace")
        return content

    def get_versions(self, file_path: str) -> list[FileVersion]:
        """
        Get all saved versions of a file, newest first.
        """
        path = Path(file_path).resolve()
        try:
            rel = str(path.relative_to(self._project_root))
        except ValueError:
            rel = path.name

        raw = self._index.get(rel, [])
        versions = []
        for item in raw:
            try:
                v = FileVersion.from_dict(item)
                if Path(v.backup_path).exists():
                    versions.append(v)
            except (KeyError, TypeError):
                continue
        return versions

    def get_version_content(self, version: FileVersion) -> str:
        """Read the content of a backup version."""
        return Path(version.backup_path).read_text(encoding="utf-8", errors="replace")

    def diff_versions(self, old: FileVersion, new_content: str) -> list[str]:
        """
        Simple line-by-line diff between a version backup and current content.
        Returns list of diff lines.
        """
        import difflib
        old_lines = self.get_version_content(old).splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        return list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"backup ({old.display_time})",
            tofile="current",
            n=3,
        ))

    # ── Project Snapshots ─────────────────────────────────

    def create_snapshot(self, name: str, description: str, file_paths: list[str]) -> ProjectVersionSnapshot:
        """Create a named snapshot of multiple files simultaneously."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"snap_{timestamp}"

        versions = []
        for fp in file_paths:
            try:
                v = self.backup_file(fp, description=f"snapshot: {name}")
                versions.append(v)
            except FileNotFoundError:
                continue

        snap = ProjectVersionSnapshot(
            snapshot_id=snapshot_id,
            name=name,
            description=description,
            timestamp=timestamp,
            file_versions=versions,
        )

        snap_path = self._versions_dir / f"{snapshot_id}.snapshot"
        snap_path.write_text(
            json.dumps(snap.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return snap

    def list_snapshots(self) -> list[ProjectVersionSnapshot]:
        snaps = []
        for f in sorted(self._versions_dir.glob("*.snapshot"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snaps.append(ProjectVersionSnapshot.from_dict(data))
            except Exception:
                continue
        return snaps

    def restore_snapshot(self, snapshot: ProjectVersionSnapshot) -> list[str]:
        """Restore all files in a snapshot. Returns list of restored paths."""
        restored = []
        for version in snapshot.file_versions:
            try:
                self.restore_version(version)
                restored.append(version.file_path)
            except Exception as e:
                print(f"[VersionControl] Failed to restore {version.file_path}: {e}")
        return restored

    # ── Cleanup ────────────────────────────────────────────

    def cleanup_old_versions(self, keep_last: int = 20) -> int:
        """Remove old backup files, keeping `keep_last` per file. Returns deleted count."""
        deleted = 0
        for key, versions in list(self._index.items()):
            if len(versions) > keep_last:
                to_delete = versions[keep_last:]
                for item in to_delete:
                    try:
                        bp = Path(item.get("backup_path", ""))
                        if bp.exists():
                            bp.unlink()
                            bp.with_suffix(".meta").unlink(missing_ok=True)
                            deleted += 1
                    except OSError:
                        pass
                self._index[key] = versions[:keep_last]
        self._save_index()
        return deleted

    def get_storage_size(self) -> int:
        """Total bytes used by version storage."""
        return sum(
            f.stat().st_size
            for f in self._versions_dir.rglob("*")
            if f.is_file()
        )

    # ── Index Persistence ─────────────────────────────────

    def _load_index(self) -> dict[str, list[dict]]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def set_project_root(self, root: str) -> None:
        self._project_root = Path(root)
        self._versions_dir = self._project_root / self.VERSIONS_DIR
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._versions_dir / self.INDEX_FILE
        self._index = self._load_index()
