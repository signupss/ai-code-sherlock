"""
Project File Tree — QTreeWidget-based file browser with context menu.
"""
from __future__ import annotations
import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QMenu, QFrame, QLineEdit,
    QFileDialog, QSizePolicy
)

from services.engine import CODE_EXTENSIONS, IGNORED_DIRS

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {"bg0":"#07080C","bg1":"#0E1117","bg2":"#131722",
        "bd":"#2E3148","bd2":"#1E2030","tx0":"#CDD6F4","tx1":"#A9B1D6",
        "tx2":"#565f89","tx3":"#3B4261","ac":"#7AA2F7"}.get(k,"#CDD6F4")
    def register_theme_refresh(cb): pass

try:
    from ui.i18n import tr, register_listener
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass


# File-type icon map (emoji fallback — no external assets needed)
_FILE_ICONS: dict[str, str] = {
    ".py":    "🐍", ".js": "📜", ".ts": "📘", ".jsx": "⚛️",
    ".tsx":   "⚛️", ".json": "📋", ".yaml": "📄", ".yml": "📄",
    ".sql":   "🗃️", ".md": "📝", ".html": "🌐", ".css": "🎨",
    ".sh":    "⚡", ".bash": "⚡", ".go": "🐹", ".rs": "🦀",
    ".java":  "☕", ".cs": "⚙️", ".cpp": "⚙️", ".c": "⚙️",
    ".h":     "📎", ".rb": "💎", ".php": "🐘", ".kt": "🎯",
    ".swift": "🦅", ".xml": "📄", ".toml": "⚙️", ".env": "🔐",
    ".lock":  "🔒", ".txt": "📄",
}

_DIR_ICON = "📁"
_DIR_OPEN_ICON = "📂"


class FileTreeWidget(QWidget):
    """
    File explorer panel — shows project directory tree,
    emits signals when files are opened or context-actioned.
    """

    file_open_requested  = pyqtSignal(str)   # file path
    file_send_to_ai      = pyqtSignal(str)   # file path
    folder_changed       = pyqtSignal(str)   # new root path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_path: str | None = None
        self._filter_text = ""
        self._build_ui()

    # ── UI Construction ────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setObjectName("panelHeader")
        hdr.setFixedHeight(32)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 6, 0)

        lbl = QLabel(tr("ПРОВОДНИК"))
        lbl.setObjectName("sectionLabel")
        hl.addWidget(lbl)
        hl.addStretch()

        btn_open = QPushButton("📁")
        btn_open.setObjectName("iconBtn")
        btn_open.setToolTip(tr("Открыть папку проекта"))
        btn_open.clicked.connect(self._pick_folder)
        hl.addWidget(btn_open)

        btn_refresh = QPushButton("↺")
        btn_refresh.setObjectName("iconBtn")
        btn_refresh.setToolTip(tr("Обновить"))
        btn_refresh.clicked.connect(self._refresh)
        hl.addWidget(btn_refresh)

        layout.addWidget(hdr)

        # Search filter — style applied by _apply_theme_styles()
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Поиск файлов..."))
        self._search.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search)

        # Root path label
        self._root_label = QLabel(tr("Папка не открыта"))
        self._root_label.setWordWrap(False)
        self._root_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._root_label)

        # Tree — no inline stylesheet; global QSS handles it
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 11))
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, stretch=1)

        # Apply theme-aware colors and register for live refresh
        self._apply_theme_styles()
        register_theme_refresh(self._apply_theme_styles)

    def _apply_theme_styles(self):
        """Rebuild all inline styles using the current palette."""
        bg0  = get_color("bg0")
        bg1  = get_color("bg1")
        bg2  = get_color("bg2")
        bg3  = get_color("bg3")
        bd2  = get_color("bd2")
        tx0  = get_color("tx0")
        tx1  = get_color("tx1")
        tx2  = get_color("tx2")
        tx3  = get_color("tx3")
        ac   = get_color("ac")
        sel  = get_color("sel")

        self._search.setStyleSheet(
            f"border: none; border-bottom: 1px solid {bd2};"
            f" background: {bg0}; color: {tx0}; padding: 4px 10px; font-size: 12px;"
        )
        self._root_label.setStyleSheet(
            f"color: {tx2}; font-size: 10px; padding: 3px 10px;"
            f" background: {bg0}; border-bottom: 1px solid {bd2};"
        )
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {bg1};
                border: none;
                color: {tx0};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 3px 4px;
                border-radius: 3px;
            }}
            QTreeWidget::item:selected {{
                background: {sel};
                color: {ac};
            }}
            QTreeWidget::item:hover {{
                background: {bg3};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
        """)
        # Re-populate tree so item foreground colors use new palette
        if hasattr(self, "_root_path") and self._root_path:
            self._refresh()

    # ── Public API ─────────────────────────────────────────

    def load_folder(self, path: str, emit_signal: bool = False) -> None:
        """Load a directory into the tree.
        emit_signal=False when called programmatically (avoids re-triggering _load_project).
        emit_signal=True only when user explicitly picks a NEW folder via the tree UI.
        """
        self._root_path = path
        short = self._truncate_path(path, 36)
        self._root_label.setText(f"  {short}")
        self._root_label.setToolTip(path)
        self._refresh()
        if emit_signal:
            self.folder_changed.emit(path)

    def select_file(self, path: str) -> None:
        """Highlight and scroll to a file in the tree."""
        self._find_and_select(self._tree.invisibleRootItem(), path)

    # ── Build Tree ─────────────────────────────────────────

    def _refresh(self):
        if not self._root_path:
            return
        self._tree.clear()
        self._populate_dir(self._tree.invisibleRootItem(), self._root_path, depth=0)

    def _populate_dir(self, parent: QTreeWidgetItem, dir_path: str, depth: int):
        if depth > 8:  # Safety limit
            return
        try:
            entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            name = entry.name

            # Skip hidden and ignored
            if name.startswith(".") and depth == 0:
                if name not in {".env", ".gitignore", ".env.example"}:
                    continue
            if name in IGNORED_DIRS:
                continue

            if entry.is_dir(follow_symlinks=False):
                item = QTreeWidgetItem(parent)
                item.setText(0, f"{_DIR_ICON} {name}")
                item.setData(0, Qt.ItemDataRole.UserRole, entry.path)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, "dir")
                item.setForeground(0, QColor(get_color("ac")))
                # Add a placeholder child so the expand arrow shows
                placeholder = QTreeWidgetItem(item)
                placeholder.setText(0, "...")
                placeholder.setData(0, Qt.ItemDataRole.UserRole + 1, "placeholder")

            elif entry.is_file(follow_symlinks=False):
                ext = Path(name).suffix.lower()
                if self._filter_text and self._filter_text.lower() not in name.lower():
                    continue

                icon = _FILE_ICONS.get(ext, "📄")
                item = QTreeWidgetItem(parent)
                item.setText(0, f"  {icon} {name}")
                item.setData(0, Qt.ItemDataRole.UserRole, entry.path)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, "file")

                # Color by type
                if ext in CODE_EXTENSIONS:
                    item.setForeground(0, QColor(get_color("tx0")))
                else:
                    item.setForeground(0, QColor(get_color("tx2")))

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Lazy-load directory contents on expand."""
        if item.data(0, Qt.ItemDataRole.UserRole + 1) != "dir":
            return

        item.setText(0, item.text(0).replace(_DIR_ICON, _DIR_OPEN_ICON, 1))

        # Remove placeholder
        for i in range(item.childCount()):
            child = item.child(i)
            if child and child.data(0, Qt.ItemDataRole.UserRole + 1) == "placeholder":
                item.removeChild(child)
                break

        # Load real children
        dir_path = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_path:
            depth = self._get_depth(item)
            self._populate_dir(item, dir_path, depth)

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        item.setText(0, item.text(0).replace(_DIR_OPEN_ICON, _DIR_ICON, 1))
        # Clear children and add placeholder back
        item.takeChildren()
        placeholder = QTreeWidgetItem(item)
        placeholder.setText(0, "...")
        placeholder.setData(0, Qt.ItemDataRole.UserRole + 1, "placeholder")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int):
        kind = item.data(0, Qt.ItemDataRole.UserRole + 1)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if kind == "file" and path:
            self.file_open_requested.emit(path)

    # ── Context Menu ───────────────────────────────────────

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return

        kind = item.data(0, Qt.ItemDataRole.UserRole + 1)
        path = item.data(0, Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        bg2 = get_color("bg2"); bg3 = get_color("bg3")
        bd  = get_color("bd");  tx0 = get_color("tx0"); ac = get_color("ac")
        menu.setStyleSheet(f"""
            QMenu {{
                background: {bg2}; border: 1px solid {bd};
                border-radius: 6px; padding: 4px;
                color: {tx0}; font-size: 12px;
            }}
            QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {bg3}; color: {ac}; }}
            QMenu::separator {{ background: {bd}; height: 1px; margin: 4px 0; }}
        """)

        if kind == "file" and path:
            act_open = menu.addAction(tr("📄  Открыть в редакторе"))
            act_open.triggered.connect(lambda: self.file_open_requested.emit(path))

            act_ai = menu.addAction(tr("🔍  Отправить в AI"))
            act_ai.triggered.connect(lambda: self.file_send_to_ai.emit(path))

            menu.addSeparator()
            act_copy = menu.addAction(tr("📋  Копировать путь"))
            act_copy.triggered.connect(lambda: self._copy_path(path))

            act_reveal = menu.addAction(tr("🗂  Показать в проводнике"))
            act_reveal.triggered.connect(lambda: self._reveal_in_explorer(path))

        elif kind == "dir" and path:
            act_expand = menu.addAction(tr("📂  Раскрыть"))
            act_expand.triggered.connect(lambda: item.setExpanded(True))

            act_copy = menu.addAction(tr("📋  Копировать путь"))
            act_copy.triggered.connect(lambda: self._copy_path(path))

        menu.exec(self._tree.mapToGlobal(pos))

    # ── Filter ─────────────────────────────────────────────

    def _on_filter_changed(self, text: str):
        self._filter_text = text
        if self._root_path:
            self._refresh()
            if text:
                self._tree.expandAll()

    # ── Helpers ────────────────────────────────────────────

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Открыть папку проекта"))
        if folder:
            self.load_folder(folder, emit_signal=True)

    def _copy_path(self, path: str):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(path)

    def _reveal_in_explorer(self, path: str):
        import subprocess, sys, os
        abs_path = str(Path(path).resolve())
        if sys.platform == "win32":
            win_path = abs_path.replace("/", "\\")
            # shell=True + quoted path is most reliable on all Windows versions
            subprocess.Popen(f'explorer /select,"{win_path}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", abs_path])
        else:
            folder = str(Path(abs_path).parent)
            for cmd in (["nautilus", "--select", abs_path],
                        ["dolphin", "--select", abs_path],
                        ["nemo", folder],
                        ["xdg-open", folder]):
                try:
                    subprocess.Popen(cmd); break
                except FileNotFoundError:
                    continue

    def _find_and_select(self, parent: QTreeWidgetItem, path: str) -> bool:
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == path:
                self._tree.setCurrentItem(child)
                self._tree.scrollToItem(child)
                return True
            if self._find_and_select(child, path):
                return True
        return False

    @staticmethod
    def _get_depth(item: QTreeWidgetItem) -> int:
        depth = 0
        p = item.parent()
        while p:
            depth += 1
            p = p.parent()
        return depth

    @staticmethod
    def _truncate_path(path: str, max_len: int) -> str:
        if len(path) <= max_len:
            return path
        parts = Path(path).parts
        if len(parts) > 3:
            return f".../{'/'.join(parts[-2:])}"
        return path[-max_len:]
