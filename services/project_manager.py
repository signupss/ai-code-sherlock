"""
Project Manager — Smart project context loading and mode management.

Two modes:
  NEW_PROJECT    → AI gives full code, explanations, complete implementations
  EXISTING_PROJECT → AI gives ONLY [SEARCH_BLOCK]/[REPLACE_BLOCK] patches

Rust-style AST context compression:
  - Python AST extracts class/function signatures with docstrings
  - Bodies replaced with `...`
  - Result is like a .pyi stub — compact, precise, complete interface
  - No information loss for AI code understanding
"""
from __future__ import annotations

import ast
import json
import os
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from core.models import FileEntry, ProjectContext, TokenBudget
from services.engine import CODE_EXTENSIONS, IGNORED_DIRS


# ──────────────────────────────────────────────────────────
#  Project Mode
# ──────────────────────────────────────────────────────────

class ProjectMode(str, Enum):
    NEW_PROJECT      = "new_project"       # Full code responses
    EXISTING_PROJECT = "existing_project"  # Patches only


@dataclass
class ProjectState:
    """Persisted project state."""
    project_root: str
    mode: ProjectMode = ProjectMode.NEW_PROJECT
    tracked_files: list[str] = field(default_factory=list)
    focused_files: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())
    name: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "project_root": self.project_root,
            "mode": self.mode.value,
            "tracked_files": self.tracked_files,
            "focused_files": self.focused_files,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "name": self.name,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectState":
        return cls(
            project_root=d.get("project_root", ""),
            mode=ProjectMode(d.get("mode", "new_project")),
            tracked_files=d.get("tracked_files", []),
            focused_files=d.get("focused_files", []),
            created_at=d.get("created_at", ""),
            last_accessed=d.get("last_accessed", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
        )


# ──────────────────────────────────────────────────────────
#  AST-based Python skeleton extractor
# ──────────────────────────────────────────────────────────

class PythonSkeletonExtractor:
    """
    Extracts API skeleton from Python source — like a .pyi stub.

    Input:
        def process_order(order_id: int, discount: float = 0.0) -> dict:
            '''Process an order and apply discount.'''
            db = get_db()
            order = db.query(Order).filter_by(id=order_id).first()
            if not order:
                raise ValueError(f"Order {order_id} not found")
            order.total *= (1 - discount)
            db.commit()
            return order.to_dict()

    Output:
        def process_order(order_id: int, discount: float = 0.0) -> dict:
            '''Process an order and apply discount.'''
            ...
    """

    def extract(self, source: str, file_path: str = "") -> str:
        try:
            tree = ast.parse(source)
            return self._render(tree, source)
        except SyntaxError as e:
            # Fall back to regex extraction for broken syntax
            return self._regex_extract(source, file_path)

    def _render(self, tree: ast.Module, source: str) -> str:
        lines: list[str] = []
        source_lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Module):
                # Top-level: imports, constants, class/function defs
                for child in node.body:
                    rendered = self._render_node(child, source_lines, indent=0)
                    if rendered:
                        lines.append(rendered)
                break

        return "\n".join(lines)

    def _render_node(
        self,
        node: ast.AST,
        source_lines: list[str],
        indent: int,
    ) -> str:
        pad = "    " * indent

        # Imports: keep as-is
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return ast.unparse(node)

        # Module-level constants (ALL_CAPS or simple assignments)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.isupper() or (indent == 0 and not name.startswith("_")):
                        try:
                            return f"{pad}{name} = {ast.unparse(node.value)}"
                        except Exception:
                            return f"{pad}{name} = ..."
            return ""

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            try:
                ann = ast.unparse(node.annotation)
                val = f" = {ast.unparse(node.value)}" if node.value else ""
                return f"{pad}{node.target.id}: {ann}{val}"
            except Exception:
                return ""

        # Function / async function
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._render_func(node, source_lines, indent)

        # Class
        if isinstance(node, ast.ClassDef):
            return self._render_class(node, source_lines, indent)

        return ""

    def _render_func(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        source_lines: list[str],
        indent: int,
    ) -> str:
        pad = "    " * indent
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""

        # Decorators
        deco_lines = []
        for d in node.decorator_list:
            try:
                deco_lines.append(f"{pad}@{ast.unparse(d)}")
            except Exception:
                pass

        # Signature
        try:
            sig = ast.unparse(node)
            # Extract just the def line
            sig_line = sig.split("\n")[0]
            # Remove 'async ' prefix issue
            if prefix and not sig_line.startswith("async "):
                sig_line = "async " + sig_line
        except Exception:
            sig_line = f"{prefix}def {node.name}(...):"

        # Docstring
        docstring = self._get_docstring(node)

        parts = deco_lines[:]
        parts.append(f"{pad}{sig_line}")
        if docstring:
            doc_indent = pad + "    "
            # Limit docstring to first 2 lines
            doc_lines = [l for l in docstring.strip().split("\n") if l.strip()][:2]
            parts.append(f'{doc_indent}"""{" ".join(doc_lines)}"""')
        parts.append(f"{pad}    ...")

        return "\n".join(parts)

    def _render_class(
        self,
        node: ast.ClassDef,
        source_lines: list[str],
        indent: int,
    ) -> str:
        pad = "    " * indent

        # Decorators
        deco_lines = []
        for d in node.decorator_list:
            try:
                deco_lines.append(f"{pad}@{ast.unparse(d)}")
            except Exception:
                pass

        # Class signature with bases
        try:
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            class_line = f"class {node.name}({bases}):" if bases else f"class {node.name}:"
        except Exception:
            class_line = f"class {node.name}:"

        docstring = self._get_docstring(node)
        parts = deco_lines[:]
        parts.append(f"{pad}{class_line}")

        if docstring:
            doc_indent = pad + "    "
            doc_lines = [l for l in docstring.strip().split("\n") if l.strip()][:2]
            parts.append(f'{doc_indent}"""{" ".join(doc_lines)}"""')

        # Class body: attributes and methods
        has_content = False
        for child in node.body:
            rendered = self._render_node(child, source_lines, indent + 1)
            if rendered:
                parts.append(rendered)
                has_content = True

        if not has_content:
            parts.append(f"{pad}    ...")

        return "\n".join(parts)

    @staticmethod
    def _get_docstring(node) -> str:
        if (
            isinstance(node.body, list)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            return node.body[0].value.value
        return ""

    @staticmethod
    def _regex_extract(source: str, file_path: str = "") -> str:
        """Fallback: regex-based extraction when AST fails."""
        lines = source.splitlines()
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()

            # Keep imports
            if stripped.startswith(("import ", "from ", "#")):
                result.append(line)
                i += 1
                continue

            # Keep class/function signatures
            if re.match(r"^\s*(async\s+)?def\s+\w+|^\s*class\s+\w+", line):
                result.append(line)
                # Keep first line if it's a docstring
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.startswith('"""') or next_line.startswith("'''"):
                        result.append(lines[i + 1])
                result.append(re.sub(r"[^\s].*", "    ...", line, count=0))
                i += 1
                # Skip body
                indent = len(line) - len(line.lstrip())
                while i < len(lines):
                    next_indent = len(lines[i]) - len(lines[i].lstrip())
                    if lines[i].strip() and next_indent <= indent:
                        break
                    i += 1
                continue

            # Keep module-level constants
            if re.match(r"^[A-Z_][A-Z0-9_]*\s*=", stripped):
                result.append(line)

            i += 1

        return "\n".join(result)


# ──────────────────────────────────────────────────────────
#  Generic skeleton extractor (JS, TS, etc.)
# ──────────────────────────────────────────────────────────

class GenericSkeletonExtractor:
    """
    Regex-based skeleton extraction for non-Python files.
    Extracts function/class signatures and strips bodies.
    """

    def extract(self, source: str, extension: str) -> str:
        if extension in (".js", ".ts", ".jsx", ".tsx"):
            return self._extract_js(source)
        if extension in (".java", ".cs"):
            return self._extract_java_like(source)
        if extension in (".go",):
            return self._extract_go(source)
        # Fallback: first 60 lines
        lines = source.splitlines()
        header = lines[:60]
        return "\n".join(header) + (f"\n// ... ({len(lines) - 60} more lines)" if len(lines) > 60 else "")

    def _extract_js(self, source: str) -> str:
        result = []
        for line in source.splitlines():
            stripped = line.strip()
            # imports
            if stripped.startswith(("import ", "export ", "const ", "let ", "var ", "//", "/*")):
                if "function" not in stripped and "=>" not in stripped:
                    result.append(line)
                    continue
            # function/class signatures
            if re.match(
                r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+|"
                r"^\s*(export\s+)?class\s+\w+|"
                r"^\s*(const|let|var)\s+\w+\s*=\s*(async\s*)?\(",
                line
            ):
                result.append(line.rstrip("{").rstrip() + " { ... }")
                continue
        return "\n".join(result) or source[:2000]

    def _extract_java_like(self, source: str) -> str:
        result = []
        for line in source.splitlines():
            if re.match(r"^\s*(public|private|protected|static|class|interface|void|@)", line.strip()):
                result.append(line.rstrip("{").rstrip() + " { ... }")
            elif "import " in line or "package " in line:
                result.append(line)
        return "\n".join(result) or source[:2000]

    def _extract_go(self, source: str) -> str:
        result = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("func ", "type ", "package ", "import ", "//")):
                result.append(line.rstrip("{").rstrip())
        return "\n".join(result) or source[:2000]


# ──────────────────────────────────────────────────────────
#  Project Manager
# ──────────────────────────────────────────────────────────

_PY_EXTRACTOR = PythonSkeletonExtractor()
_GEN_EXTRACTOR = GenericSkeletonExtractor()


class ProjectManager:
    """
    Manages project state, mode, file loading, and context building.
    """

    STATE_FILE = ".sherlock_versions/project_state.json"

    def __init__(self, logger=None):
        self._logger = logger
        self._state: Optional[ProjectState] = None
        self._file_cache: dict[str, str] = {}   # path → content
        self._skeleton_cache: dict[str, str] = {}

    # ── Project Lifecycle ─────────────────────────────────

    def create_project(
        self,
        root: str,
        name: str = "",
        mode: ProjectMode = ProjectMode.NEW_PROJECT,
    ) -> ProjectState:
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)

        state = ProjectState(
            project_root=str(root_path),
            name=name or root_path.name,
            mode=mode,
        )
        self._state = state
        self._file_cache.clear()
        self._skeleton_cache.clear()
        self._save_state()

        if self._logger:
            self._logger.info(f"Проект создан: {name} ({mode.value})", source="ProjectManager")

        return state

    def open_project(self, root: str) -> ProjectState:
        root_path = Path(root).resolve()
        state_file = root_path / self.STATE_FILE

        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self._state = ProjectState.from_dict(data)
                self._state.last_accessed = datetime.now().isoformat()
                self._save_state()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Не удалось загрузить состояние: {e}", source="ProjectManager")
                self._state = ProjectState(project_root=str(root_path))
        else:
            self._state = ProjectState(
                project_root=str(root_path),
                name=root_path.name,
                mode=ProjectMode.EXISTING_PROJECT,
            )
            self._save_state()

        self._file_cache.clear()
        self._skeleton_cache.clear()
        self._scan_project()
        return self._state

    def set_mode(self, mode: ProjectMode) -> None:
        if self._state:
            self._state.mode = mode
            self._save_state()

    @property
    def mode(self) -> ProjectMode:
        return self._state.mode if self._state else ProjectMode.NEW_PROJECT

    @property
    def state(self) -> Optional[ProjectState]:
        return self._state

    # ── File Loading ──────────────────────────────────────

    def _scan_project(self) -> None:
        if not self._state:
            return
        root = Path(self._state.project_root)
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in CODE_EXTENSIONS:
                    full_path = os.path.join(dirpath, fname)
                    found.append(full_path)

        self._state.tracked_files = found[:200]  # Safety limit
        self._save_state()

        if self._logger:
            self._logger.info(
                f"Проект просканирован: {len(found)} файлов", source="ProjectManager"
            )

    def load_file(self, path: str) -> str:
        if path not in self._file_cache:
            try:
                self._file_cache[path] = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                if self._logger:
                    self._logger.warning(f"Не удалось прочитать {path}: {e}", source="ProjectManager")
                self._file_cache[path] = ""
        return self._file_cache[path]

    def reload_file(self, path: str) -> str:
        self._file_cache.pop(path, None)
        self._skeleton_cache.pop(path, None)
        return self.load_file(path)

    # ── Context Building — The Core Intelligence ──────────

    def build_context(
        self,
        focused_paths: list[str],
        budget: TokenBudget,
        error_logs: str = "",
    ) -> ProjectContext:
        """
        Build a smart context for AI:
        1. Focused files → FULL content (never compressed)
        2. Same-directory files → full content if budget allows
        3. Rest of project → AST skeleton (Rust-like)
        4. Very distant files → just filename + one-line summary

        This mirrors how Rust/rust-analyzer sends context:
        exact problematic file in full + project API skeleton.
        """
        all_files = self._state.tracked_files if self._state else []
        focused_set = set(str(Path(p).resolve()) for p in focused_paths)

        result_files: list[FileEntry] = []
        used_tokens = 0

        # Phase 1: Focused files — ALWAYS full, no compression
        for path in focused_paths:
            content = self.load_file(path)
            entry = FileEntry(
                path=path,
                relative_path=self._rel(path),
                content=content,
                extension=Path(path).suffix.lower(),
                is_focused=True,
            )
            result_files.append(entry)
            used_tokens += entry.token_estimate

        # Phase 2: Same-directory files — try full content
        focused_dirs = {str(Path(p).parent) for p in focused_paths}
        for path in all_files:
            if str(Path(path).resolve()) in focused_set:
                continue
            if str(Path(path).parent) in focused_dirs:
                content = self.load_file(path)
                tokens = TokenBudget.estimate_tokens(content)
                if used_tokens + tokens <= budget.available_for_context * 0.6:
                    entry = FileEntry(
                        path=path,
                        relative_path=self._rel(path),
                        content=content,
                        extension=Path(path).suffix.lower(),
                    )
                    result_files.append(entry)
                    used_tokens += tokens

        # Phase 3: Rest of project — AST skeleton
        skeleton_budget = int(budget.available_for_context * 0.3)
        skeleton_used = 0

        for path in all_files:
            resolved = str(Path(path).resolve())
            if resolved in focused_set:
                continue
            if str(Path(path).parent) in focused_dirs:
                continue
            if skeleton_used >= skeleton_budget:
                break

            skeleton = self._get_skeleton(path)
            tokens = TokenBudget.estimate_tokens(skeleton)
            if skeleton_used + tokens <= skeleton_budget:
                entry = FileEntry(
                    path=path,
                    relative_path=self._rel(path),
                    content=skeleton,
                    extension=Path(path).suffix.lower(),
                    is_compressed=True,
                    summary=f"[API skeleton of {self._rel(path)}]",
                )
                result_files.append(entry)
                skeleton_used += tokens

        return ProjectContext(
            files=result_files,
            root_path=self._state.project_root if self._state else "",
            focused_file_path=focused_paths[0] if focused_paths else None,
            error_logs=error_logs if error_logs else None,
        )

    def get_skeleton(self, path: str) -> str:
        """Public: get API skeleton of a file."""
        return self._get_skeleton(path)

    def _get_skeleton(self, path: str) -> str:
        if path in self._skeleton_cache:
            return self._skeleton_cache[path]

        content = self.load_file(path)
        ext = Path(path).suffix.lower()

        if ext == ".py":
            skeleton = _PY_EXTRACTOR.extract(content, path)
        elif ext in (".json", ".yaml", ".yml", ".toml"):
            # Config files: keep first 30 lines with structure
            lines = content.splitlines()[:30]
            skeleton = "\n".join(lines) + (f"\n# ... ({len(content.splitlines())} total lines)" if len(content.splitlines()) > 30 else "")
        else:
            skeleton = _GEN_EXTRACTOR.extract(content, ext)

        # Add header
        rel = self._rel(path)
        header = f"# [SKELETON: {rel}]\n"
        skeleton = header + skeleton

        self._skeleton_cache[path] = skeleton
        return skeleton

    # ── Prompt Mode Modifiers ─────────────────────────────

    def get_mode_system_addon(self) -> str:
        """Additional system prompt text based on current mode."""
        if self.mode == ProjectMode.NEW_PROJECT:
            return """
РЕЖИМ: НОВЫЙ ПРОЕКТ
- Давай полные реализации
- Включай все необходимые импорты
- Пиши комментарии и docstrings
- Объясняй архитектурные решения
- Можно давать полные файлы целиком

СОЗДАНИЕ ФАЙЛА С НУЛЯ:
Когда файла ещё нет — SEARCH_BLOCK должен быть ПУСТЫМ:

[SEARCH_BLOCK]
[REPLACE_BLOCK]
<полный код файла>
[END_PATCH]

Перед патчем обязательно укажи имя файла:
"Создаю `main.py`:" или "Файл `app.js`:"
НИКОГДА не пиши в SEARCH_BLOCK текст типа "## РЕЛЕВАНТНЫЙ КОД" или "## КОД ПРОЕКТА".
"""
        else:
            return """
РЕЖИМ: РАБОТА С СУЩЕСТВУЮЩИМ ПРОЕКТОМ
СТРОГОЕ ПРАВИЛО: Давай ТОЛЬКО патчи в формате [SEARCH_BLOCK]/[REPLACE_BLOCK].
ЗАПРЕЩЕНО:
  ✗ Переписывать весь файл
  ✗ Давать полный код функции если нужно изменить 2 строки
  ✗ Добавлять код без точного указания места
  ✗ Давать "примерный" код — только точные замены

ОБЯЗАТЕЛЬНО:
  ✓ [SEARCH_BLOCK] должен ТОЧНО совпадать с кодом в файле
  ✓ Минимальные изменения — только что нужно поменять
  ✓ Объяснить ПОЧЕМУ это изменение (1-2 предложения)
  ✓ Указать файл если изменения в нескольких местах
"""

    # ── Persistence ────────────────────────────────────────

    def _save_state(self) -> None:
        if not self._state:
            return
        state_file = Path(self._state.project_root) / self.STATE_FILE
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _rel(self, path: str) -> str:
        if self._state:
            try:
                return str(Path(path).relative_to(self._state.project_root))
            except ValueError:
                pass
        return Path(path).name
