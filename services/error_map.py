"""
Error Map — Persistent database of errors and their solutions.

Purpose:
  - Track every error encountered during development
  - Store confirmed solutions
  - Inject relevant past solutions into AI prompts
  - Prevent repeating same mistakes
  - Build "project memory" of what has been tried

Storage: JSON file at <project_root>/.sherlock_versions/error_map.json
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────
#  Data Models
# ──────────────────────────────────────────────────────────

@dataclass
class ErrorRecord:
    error_id: str               # sha256 of normalized error signature
    error_type: str             # "TypeError", "AttributeError", etc.
    error_message: str          # full error message
    error_signature: str        # normalized key for dedup
    file_path: str              # where it occurred
    line_number: int            # approximate line
    first_seen: str             # ISO timestamp
    last_seen: str              # ISO timestamp
    occurrences: int = 1
    status: str = "open"        # "open" | "resolved" | "ignored"
    root_cause: str = ""        # AI-determined root cause
    solution: str = ""          # confirmed fix description
    patch_search: str = ""      # the actual patch that fixed it
    patch_replace: str = ""
    ai_analysis: str = ""       # full AI analysis
    tags: list[str] = field(default_factory=list)
    notes: str = ""             # user notes

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ErrorRecord":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def short_summary(self) -> str:
        return (
            f"[{self.status.upper()}] {self.error_type}: "
            f"{self.error_message[:80]}... "
            f"(seen {self.occurrences}x)"
        )


@dataclass
class AvoidPattern:
    """Things AI tried that made things WORSE — never repeat these."""
    pattern_id: str
    description: str          # "AI tried to add X which broke Y"
    error_context: str        # what the original error was
    bad_approach: str         # what was tried that failed
    better_approach: str      # what to do instead
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AvoidPattern":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


# ──────────────────────────────────────────────────────────
#  Error Map Service
# ──────────────────────────────────────────────────────────

class ErrorMapService:

    MAP_FILE = ".sherlock_versions/error_map.json"

    def __init__(self, project_root: Optional[str] = None):
        self._root = Path(project_root) if project_root else Path.cwd()
        self._map_path = self._root / self.MAP_FILE
        self._map_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, ErrorRecord] = {}
        self._avoid: list[AvoidPattern] = []
        self._load()

    # ── Error Recording ────────────────────────────────────

    def record_error(
        self,
        error_message: str,
        error_type: str = "",
        file_path: str = "",
        line_number: int = 0,
    ) -> ErrorRecord:
        """Record or update an error. Returns the record."""
        sig = self._normalize_signature(error_type, error_message)
        error_id = hashlib.sha256(sig.encode()).hexdigest()[:16]
        now = datetime.now().isoformat()

        if error_id in self._records:
            rec = self._records[error_id]
            rec.occurrences += 1
            rec.last_seen = now
            if file_path:
                rec.file_path = file_path
            if line_number:
                rec.line_number = line_number
        else:
            rec = ErrorRecord(
                error_id=error_id,
                error_type=error_type or self._extract_error_type(error_message),
                error_message=error_message[:1000],
                error_signature=sig,
                file_path=file_path,
                line_number=line_number,
                first_seen=now,
                last_seen=now,
            )
            self._records[error_id] = rec

        self._save()
        return rec

    def mark_resolved(
        self,
        error_id: str,
        root_cause: str = "",
        solution: str = "",
        patch_search: str = "",
        patch_replace: str = "",
        ai_analysis: str = "",
    ) -> Optional[ErrorRecord]:
        """Mark error as resolved with the confirmed solution."""
        if error_id not in self._records:
            return None
        rec = self._records[error_id]
        rec.status = "resolved"
        rec.root_cause = root_cause
        rec.solution = solution
        rec.patch_search = patch_search[:2000]
        rec.patch_replace = patch_replace[:2000]
        rec.ai_analysis = ai_analysis[:3000]
        self._save()
        return rec

    def add_avoid_pattern(
        self,
        description: str,
        error_context: str,
        bad_approach: str,
        better_approach: str,
    ) -> AvoidPattern:
        """Record an approach that was tried and made things worse."""
        pid = hashlib.sha256(
            (description + bad_approach).encode()
        ).hexdigest()[:12]
        pattern = AvoidPattern(
            pattern_id=pid,
            description=description,
            error_context=error_context,
            bad_approach=bad_approach,
            better_approach=better_approach,
        )
        # Avoid duplicates
        if not any(p.pattern_id == pid for p in self._avoid):
            self._avoid.append(pattern)
            self._save()
        return pattern

    # ── Query ─────────────────────────────────────────────

    def find_similar(
        self,
        error_message: str,
        error_type: str = "",
        max_results: int = 5,
    ) -> list[ErrorRecord]:
        """Find errors similar to the given one."""
        sig = self._normalize_signature(error_type, error_message)
        error_id = hashlib.sha256(sig.encode()).hexdigest()[:16]

        # Exact match first
        if error_id in self._records:
            return [self._records[error_id]]

        # Fuzzy: keyword overlap
        keywords = set(re.findall(r"\b\w{4,}\b", error_message.lower()))
        scored: list[tuple[float, ErrorRecord]] = []

        for rec in self._records.values():
            rec_keywords = set(re.findall(r"\b\w{4,}\b", rec.error_message.lower()))
            if not rec_keywords:
                continue
            overlap = len(keywords & rec_keywords)
            if overlap > 0:
                score = overlap / max(len(keywords), len(rec_keywords))
                scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored[:max_results]]

    def get_resolved_for_context(self, max_items: int = 8) -> list[ErrorRecord]:
        """Return resolved errors relevant for AI context (most recent first)."""
        resolved = [
            r for r in self._records.values()
            if r.is_resolved and r.root_cause
        ]
        resolved.sort(key=lambda r: r.last_seen, reverse=True)
        return resolved[:max_items]

    def get_open_errors(self) -> list[ErrorRecord]:
        return [r for r in self._records.values() if r.status == "open"]

    def get_avoid_patterns(self) -> list[AvoidPattern]:
        return list(self._avoid)

    # ── AI Context Builder ────────────────────────────────

    def build_context_block(
        self,
        current_error: str = "",
        max_chars: int = 2000,
    ) -> str:
        """
        Build a compact context block for injection into AI prompts.
        Shows: relevant past solutions + patterns to avoid.
        """
        lines: list[str] = []

        # Find similar resolved errors
        if current_error:
            similar = [r for r in self.find_similar(current_error) if r.is_resolved]
        else:
            similar = self.get_resolved_for_context(4)

        if similar:
            lines.append("## 🗂 КАРТА ОШИБОК — Ранее решённые проблемы:")
            for rec in similar[:4]:
                lines.append(f"\n**Ошибка:** {rec.error_type}: {rec.error_message[:100]}")
                if rec.root_cause:
                    lines.append(f"**Причина:** {rec.root_cause[:200]}")
                if rec.solution:
                    lines.append(f"**Решение:** {rec.solution[:200]}")
                if rec.patch_search and rec.patch_replace:
                    lines.append("**Патч:**")
                    lines.append(f"```\n- {rec.patch_search[:150]}\n+ {rec.patch_replace[:150]}\n```")

        # Avoid patterns
        if self._avoid:
            lines.append("\n## ⚠️ ЗАПРЕЩЁННЫЕ ПОДХОДЫ (уже пробовали — стало хуже):")
            for pat in self._avoid[-5:]:
                lines.append(f"- НЕ делать: {pat.bad_approach[:150]}")
                lines.append(f"  Вместо этого: {pat.better_approach[:150]}")

        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (сокращено)"
        return result

    # ── Stats ─────────────────────────────────────────────

    def stats(self) -> dict:
        total = len(self._records)
        resolved = sum(1 for r in self._records.values() if r.is_resolved)
        return {
            "total_errors": total,
            "resolved": resolved,
            "open": total - resolved,
            "avoid_patterns": len(self._avoid),
            "resolution_rate": f"{resolved/total*100:.0f}%" if total else "0%",
        }

    # ── Persistence ────────────────────────────────────────

    def _save(self) -> None:
        data = {
            "records": {k: v.to_dict() for k, v in self._records.items()},
            "avoid_patterns": [p.to_dict() for p in self._avoid],
        }
        tmp = self._map_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        import shutil
        shutil.move(str(tmp), str(self._map_path))

    def _load(self) -> None:
        if not self._map_path.exists():
            return
        try:
            data = json.loads(self._map_path.read_text(encoding="utf-8"))
            for k, v in data.get("records", {}).items():
                try:
                    self._records[k] = ErrorRecord.from_dict(v)
                except Exception:
                    pass
            for p in data.get("avoid_patterns", []):
                try:
                    self._avoid.append(AvoidPattern.from_dict(p))
                except Exception:
                    pass
        except json.JSONDecodeError:
            pass

    def set_project_root(self, root: str) -> None:
        self._root = Path(root)
        self._map_path = self._root / self.MAP_FILE
        self._map_path.parent.mkdir(parents=True, exist_ok=True)
        self._records = {}
        self._avoid = []
        self._load()

    # ── Helpers ────────────────────────────────────────────

    @staticmethod
    def _normalize_signature(error_type: str, message: str) -> str:
        """Normalize error for deduplication — strip line numbers, addresses."""
        sig = f"{error_type}:{message}"
        # Remove memory addresses
        sig = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", sig)
        # Remove line numbers in tracebacks
        sig = re.sub(r"line \d+", "line N", sig)
        # Remove timestamps
        sig = re.sub(r"\d{2}:\d{2}:\d{2}", "HH:MM:SS", sig)
        return sig.lower()[:500]

    @staticmethod
    def _extract_error_type(message: str) -> str:
        """Extract error class name from message."""
        m = re.search(
            r"\b(TypeError|ValueError|AttributeError|IndexError|KeyError|"
            r"RuntimeError|ImportError|ModuleNotFoundError|NameError|"
            r"OSError|IOError|FileNotFoundError|PermissionError|"
            r"SyntaxError|IndentationError|AssertionError|Exception)\b",
            message
        )
        return m.group(1) if m else "Error"

    def all_records(self) -> list[ErrorRecord]:
        return list(self._records.values())
