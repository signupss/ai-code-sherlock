"""
Enhanced Code Editor — Notepad++-style with full features:
  - Line numbers with click-to-select
  - Syntax highlighting (Python, JS, JSON, YAML, SQL, Bash, Markdown + 12 more)
  - Real-time syntax error detection (Python AST)
  - Current line highlight
  - Bracket matching
  - Auto-indent / auto-close brackets
  - Find & Replace (Ctrl+F / Ctrl+H)
  - Multi-cursor word selection (Ctrl+D)
  - Code folding indicator
  - Tab/untab selection (Tab / Shift+Tab)
  - Go-to line (Ctrl+G)
  - Zoom in/out (Ctrl+= / Ctrl+-)
  - Modified indicator (dot in tab title)
  - Context menu: AI actions, standard edit

Upgrades:
  * Smart Minimap — cached QPixmap, error heatmap, draggable viewport
  * Inline Ghost Text — semi-transparent patch preview before applying
  * AST-based error heatmap on minimap
"""
from __future__ import annotations
import ast
import re
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QRect, QSize, QTimer, pyqtSignal, QPoint
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QBrush,
    QTextCursor, QTextCharFormat, QTextDocument, QKeySequence,
    QSyntaxHighlighter, QPalette, QTextFormat, QPolygon, QPixmap
)
from PyQt6.QtWidgets import (
    QWidget, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QCheckBox,
    QTextEdit, QScrollArea, QSizePolicy, QTabWidget,
    QDialog, QFormLayout, QSpinBox, QMessageBox,
    QToolBar, QMenu, QApplication, QScrollBar
)

from ui.widgets.syntax_highlighter import create_highlighter, language_name

try:
    from ui.i18n import tr
except ImportError:
    def tr(s): return s

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {
        "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722", "bg3": "#1A1D2E",
        "bd": "#2E3148", "bd2": "#1E2030",
        "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89", "tx3": "#3B4261",
        "sel": "#2E3148", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
        "ac": "#7AA2F7",
    }.get(k, "#CDD6F4")
    def register_theme_refresh(cb): pass


# ══════════════════════════════════════════════════════════════
#  LINE NUMBER AREA
# ══════════════════════════════════════════════════════════════

class LineNumberArea(QWidget):
    """Gutter with line numbers, fold arrows, bookmark dots, error dots."""

    FOLD_W = 14

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor
        self._error_lines: set[int] = set()
        self._bookmark_lines: set[int] = set()
        self._folded_blocks: set[int] = set()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._gutter_context)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._editor._line_number_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)

    def set_error_lines(self, lines: set[int]) -> None:
        self._error_lines = lines
        self.update()

    def mousePressEvent(self, event):
        x = event.pos().x()
        y = event.pos().y()
        w = self._editor._line_number_width()

        block = self._editor.firstVisibleBlock()
        offset = self._editor.contentOffset()
        while block.isValid():
            top = int(self._editor.blockBoundingGeometry(block).translated(offset).top())
            height = int(self._editor.blockBoundingRect(block).height())
            if top <= y <= top + height:
                line_num = block.blockNumber() + 1
                if x < self.FOLD_W:
                    # Click in fold area
                    if self._editor._is_foldable(block):
                        self._editor._toggle_fold(block)
                else:
                    # Click on line number → select entire line
                    cursor = QTextCursor(block)
                    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                    self._editor.setTextCursor(cursor)
                return
            block = block.next()

    def _gutter_context(self, pos):
        block = self._editor.firstVisibleBlock()
        offset = self._editor.contentOffset()
        while block.isValid():
            top = int(self._editor.blockBoundingGeometry(block).translated(offset).top())
            height = int(self._editor.blockBoundingRect(block).height())
            if top <= pos.y() <= top + height:
                line_num = block.blockNumber() + 1
                menu = QMenu(self)
                act_bm = menu.addAction(tr("📌 Переключить закладку"))
                act_bm.triggered.connect(lambda _, ln=line_num: self._toggle_bookmark(ln))
                act_clr = menu.addAction(tr("Очистить закладки"))
                act_clr.triggered.connect(self._clear_bookmarks)
                menu.addSeparator()
                act_fold_all = menu.addAction(tr("⊕ Развернуть всё"))
                act_fold_all.triggered.connect(self._editor._unfold_all)
                act_collapse_all = menu.addAction(tr("⊖ Свернуть всё"))
                act_collapse_all.triggered.connect(self._editor._fold_all)
                menu.exec(self.mapToGlobal(pos))
                return
            block = block.next()

    def _toggle_bookmark(self, line: int):
        if line in self._bookmark_lines:
            self._bookmark_lines.discard(line)
        else:
            self._bookmark_lines.add(line)
        self.update()

    def _clear_bookmarks(self):
        self._bookmark_lines.clear()
        self.update()


# ══════════════════════════════════════════════════════════════
#  CODE EDITOR
# ══════════════════════════════════════════════════════════════

class CodeEditor(QPlainTextEdit):
    """
    Full-featured code editor widget with ghost text support.
    """
    modified_changed      = pyqtSignal(bool)
    cursor_pos_changed    = pyqtSignal(int, int)
    syntax_errors_changed = pyqtSignal(list)
    hide_search_requested = pyqtSignal()

    _BRACKETS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
    _CLOSE_BRACKETS = set(")]}")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: str = ""
        self._is_modified = False
        self._error_lines: set[int] = set()
        self._base_font_size = 12
        self._highlighter = None
        self._folded_ranges: dict[int, int] = {}

        # Ghost text state
        self._ghost_text: str = ""
        self._ghost_line: int = -1  # 0-based block number

        # Unified Extra Selections state
        self._sel_current_line = []
        self._sel_occurrences = []
        self._sel_brackets = []
        self._sel_errors = []
        self._sel_search = []
        self._sel_patched = []   # patched block highlights

        # Line number area
        self._line_num_area = LineNumberArea(self)

        # Syntax check timer
        self._syntax_check_timer = QTimer(self)
        self._syntax_check_timer.setSingleShot(True)
        self._syntax_check_timer.timeout.connect(self._check_syntax)

        self._setup_appearance()
        self._connect_signals()
    
    def _update_extra_selections(self):
        """Combine all selection layers and apply them safely at once."""
        self.setExtraSelections(
            self._sel_current_line +
            self._sel_patched +
            self._sel_errors +
            self._sel_search +
            self._sel_occurrences +
            self._sel_brackets
        )

    def set_search_selections(self, selections: list[QTextEdit.ExtraSelection]):
        """API for SearchBar to set highlights without breaking editor state."""
        self._sel_search = selections
        self._update_extra_selections()

    def set_patched_lines(self, lines: set[int]) -> None:
        """
        Highlight lines that were modified by applied patches.
        lines: set of 1-based line numbers.
        """
        if not lines:
            self.clear_patched_lines()
            return

        sels = []
        # Semi-transparent green background for patched blocks
        fmt = QTextCharFormat()
        patch_bg = QColor(get_color("ok"))
        patch_bg.setAlpha(25)
        fmt.setBackground(patch_bg)
        fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)

        # Left-border indicator using a slightly stronger color
        border_fmt = QTextCharFormat()
        border_bg = QColor(get_color("ok"))
        border_bg.setAlpha(40)
        border_fmt.setBackground(border_bg)
        border_fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)

        for line_num in sorted(lines):
            block = self.document().findBlockByLineNumber(line_num - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                cursor = QTextCursor(block)
                cursor.clearSelection()
                sel.cursor = cursor
                sels.append(sel)

        self._sel_patched = sels
        self._update_extra_selections()

    def clear_patched_lines(self) -> None:
        """Remove all patched-block highlights."""
        self._sel_patched = []
        self._update_extra_selections()
    
    def _setup_appearance(self):
        font = QFont()
        font.setFamilies(["JetBrains Mono", "Cascadia Code", "Consolas", "Courier New"])
        font.setPointSize(self._base_font_size)
        self.setFont(font)
        self._apply_editor_theme()
        register_theme_refresh(self._apply_editor_theme)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(' ') * 4)
        self.updateRequest.connect(self._update_line_number_area)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self._update_line_number_area_width()

    def _apply_editor_theme(self):
        """
        Re-apply palette and stylesheet from current theme.
        SAFE: preserves document, cursor, and syntax highlighter state.
        """
        bg  = get_color("bg0")
        fg  = get_color("tx0")
        sel = get_color("sel")
        bd  = get_color("bd")
        ac  = get_color("ac")

        # Save state before any changes
        doc = self.document()
        cursor_pos = self.textCursor().position()
        scroll_val = self.verticalScrollBar().value()
        had_highlighter = self._highlighter is not None

        # Block signals to prevent textChanged / cursorMoved noise
        self.blockSignals(True)

        # Set palette — this is safe and doesn't touch the document
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base,            QColor(bg))
        palette.setColor(QPalette.ColorRole.Text,            QColor(fg))
        palette.setColor(QPalette.ColorRole.Highlight,       QColor(sel))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(fg))
        palette.setColor(QPalette.ColorRole.Window,          QColor(bg))
        palette.setColor(QPalette.ColorRole.Button,          QColor(bd))
        self.setPalette(palette)

        # Restore font (setPalette can reset it)
        font = self.font()
        font.setPointSize(self._base_font_size)
        self.setFont(font)

        # Build new QSS — only apply if actually changed
        new_qss = (
            f"QPlainTextEdit {{"
            f" background-color: {bg}; color: {fg}; border: none;"
            f" selection-background-color: {sel}; selection-color: {fg};"
            f" font-size: {self._base_font_size}pt;"
            f"}}"
            f"QScrollBar:vertical {{"
            f" background: {bg}; width: 8px; border-radius: 4px; margin: 0;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f" background: {bd}; border-radius: 4px; min-height: 30px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{ background: {ac}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}"
            f"QScrollBar:horizontal {{"
            f" background: {bg}; height: 8px; border-radius: 4px; margin: 0;"
            f"}}"
            f"QScrollBar::handle:horizontal {{"
            f" background: {bd}; border-radius: 4px; min-width: 30px;"
            f"}}"
            f"QScrollBar::handle:horizontal:hover {{ background: {ac}; }}"
            f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}"
            f"QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}"
        )
        old_qss = self.styleSheet()
        if new_qss != old_qss:
            self.setStyleSheet(new_qss)

        # CRITICAL: Verify document survived the stylesheet change
        if self.document() is not doc:
            # Qt replaced the document — restore it
            self.setDocument(doc)

        # Restore cursor position
        try:
            c = self.textCursor()
            c.setPosition(min(cursor_pos, doc.characterCount() - 1))
            self.setTextCursor(c)
        except Exception:
            pass

        # Restore scroll
        self.verticalScrollBar().setValue(scroll_val)

        # Re-enable signals
        self.blockSignals(False)

        # Force viewport repaint
        self.viewport().update()
        self._line_num_area.update()

    def _connect_signals(self):
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.cursorPositionChanged.connect(self._match_brackets)

    # ── Public API ─────────────────────────────────────────

    def set_file(self, path: str, content: str) -> None:
        self._file_path = path
        
        # Блокируем сигналы при загрузке, чтобы не вызвать textChanged
        self.blockSignals(True)
        self.setPlainText(content)
        self.blockSignals(False)
        
        # Явно сбрасываем флаг модификации документа Qt
        self.document().setModified(False)
        
        self._is_modified = False
        self.modified_changed.emit(False)
        if self._highlighter:
            self._highlighter.setDocument(None)
        self._highlighter = create_highlighter(self.document(), path)
        self._syntax_check_timer.start(500)

    @property
    def file_path(self) -> str:
        return self._file_path

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    def get_content(self) -> str:
        return self.toPlainText()

    def zoom_in(self):
        self._base_font_size = min(32, self._base_font_size + 1)
        self._apply_font_size()

    def zoom_out(self):
        self._base_font_size = max(6, self._base_font_size - 1)
        self._apply_font_size()

    def zoom_reset(self):
        self._base_font_size = 12
        self._apply_font_size()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0: self.zoom_in()
            elif delta < 0: self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)

    def _apply_font_size(self):
        font = self.font()
        font.setPointSize(self._base_font_size)
        self.setFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(' ') * 4)
        self._update_line_number_area_width()
        self._apply_editor_theme()
        self.viewport().update()
        self._line_num_area.update()

    def go_to_line(self, line: int) -> None:
        block = self.document().findBlockByLineNumber(line - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()

    def get_error_lines(self) -> set[int]:
        return set(self._error_lines)

    # ── Ghost Text (inline patch preview) ──────────────────

    def set_ghost_text(self, text: str, at_line: int = -1) -> None:
        """
        Show semi-transparent ghost text after the specified line.
        Use at_line=-1 to show after current cursor line.
        Call clear_ghost_text() to remove.
        """
        self._ghost_text = text
        self._ghost_line = at_line if at_line >= 0 else self.textCursor().blockNumber()
        self.viewport().update()

    def clear_ghost_text(self) -> None:
        self._ghost_text = ""
        self._ghost_line = -1
        self.viewport().update()

    def paintEvent(self, event):
        """Override to paint ghost text overlay after normal rendering."""
        super().paintEvent(event)
        if self._ghost_text and self._ghost_line >= 0:
            self._paint_ghost_text()

    def _paint_ghost_text(self):
        """Render ghost text as semi-transparent overlay below the target line."""
        block = self.document().findBlockByNumber(self._ghost_line)
        if not block.isValid():
            return
        geom = self.blockBoundingGeometry(block).translated(self.contentOffset())
        y_start = int(geom.bottom())

        painter = QPainter(self.viewport())
        ghost_color = QColor(get_color("ok"))
        ghost_color.setAlpha(60)
        bg_color = QColor(get_color("bg0"))
        bg_color.setAlpha(180)

        font = QFont(self.font())
        font.setItalic(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        line_h = fm.height()

        lines = self._ghost_text.split("\n")
        # Background overlay
        total_h = line_h * len(lines) + 4
        overlay_rect = QRect(0, y_start, self.viewport().width(), total_h)
        painter.fillRect(overlay_rect, bg_color)

        # Draw ghost border
        border_color = QColor(get_color("ok"))
        border_color.setAlpha(80)
        painter.setPen(QPen(border_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, y_start, self.viewport().width(), y_start)

        # Draw text
        painter.setPen(ghost_color)
        for i, line in enumerate(lines):
            y = y_start + 2 + i * line_h
            if y > self.viewport().height():
                break
            painter.drawText(4, y + fm.ascent(), line)

        painter.end()

    # ── Line Numbers ───────────────────────────────────────

    def _line_number_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        num_w = 14 + QFontMetrics(self.font()).horizontalAdvance('9') * max(digits, 3)
        return num_w + LineNumberArea.FOLD_W

    def _update_line_number_area_width(self, *_):
        self.setViewportMargins(self._line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_num_area.scroll(0, dy)
        else:
            self._line_num_area.update(0, rect.y(),
                                       self._line_num_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_num_area.setGeometry(
            QRect(cr.left(), cr.top(), self._line_number_width(), cr.height())
        )

    def _paint_line_numbers(self, event):
        painter = QPainter(self._line_num_area)
        bg0  = QColor(get_color("bg0"))
        bd2  = QColor(get_color("bd2"))
        tx0  = QColor(get_color("tx0"))
        tx3  = QColor(get_color("tx3"))
        bg2  = QColor(get_color("bg2"))
        err  = QColor(get_color("err"))
        sel  = QColor(get_color("sel"))
        ac   = QColor(get_color("ac"))

        painter.fillRect(event.rect(), bg0)

        fold_w  = LineNumberArea.FOLD_W
        total_w = self._line_num_area.width()

        painter.setPen(QPen(bd2, 1))
        painter.drawLine(fold_w, event.rect().top(), fold_w, event.rect().bottom())
        painter.drawLine(total_w - 1, event.rect().top(), total_w - 1, event.rect().bottom())

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        offset = self.contentOffset()
        top = int(self.blockBoundingGeometry(block).translated(offset).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()
        fm = QFontMetrics(self.font())
        lh = fm.height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_num = block_num + 1
                mid_y = top + lh // 2

                if block_num == current_line:
                    painter.fillRect(fold_w, top, total_w - fold_w - 1, lh, bg2)
                    painter.setPen(tx0)
                elif line_num in self._line_num_area._error_lines:
                    err_fill = QColor(err); err_fill.setAlpha(40)
                    painter.fillRect(fold_w, top, total_w - fold_w - 1, lh, err_fill)
                    painter.setPen(err)
                else:
                    painter.setPen(tx3)

                painter.drawText(
                    fold_w, top, total_w - fold_w - 8, lh,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(line_num)
                )

                # Fold arrow
                is_foldable = self._is_foldable(block)
                is_folded   = line_num in self._folded_ranges

                if is_foldable:
                    arrow_size = 8
                    ax = fold_w // 2 - arrow_size // 2
                    ay = mid_y - arrow_size // 2
                    painter.setPen(Qt.PenStyle.NoPen)
                    if is_folded:
                        painter.setBrush(QBrush(ac))
                        pts = [QPoint(ax, ay), QPoint(ax, ay + arrow_size),
                               QPoint(ax + arrow_size, ay + arrow_size // 2)]
                    else:
                        painter.setBrush(QBrush(tx3))
                        pts = [QPoint(ax, ay), QPoint(ax + arrow_size, ay),
                               QPoint(ax + arrow_size // 2, ay + arrow_size)]
                    painter.drawPolygon(QPolygon(pts))
                elif self._is_inside_fold(line_num):
                    painter.setPen(QPen(bd2, 1))
                    cx = fold_w // 2
                    painter.drawLine(cx, top, cx, top + lh)

                # Bookmark dot
                if line_num in self._line_num_area._bookmark_lines:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(get_color("warn"))))
                    painter.drawEllipse(2, mid_y - 4, 8, 8)

                # Error dot
                if line_num in self._line_num_area._error_lines:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(err))
                    painter.drawEllipse(2, mid_y - 4, 8, 8)

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

    # ── Current Line Highlight ─────────────────────────────

    def _highlight_current_line(self):
        self._sel_current_line = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(get_color("bg2")))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            self._sel_current_line.append(sel)
        self._update_extra_selections()

    # ── Bracket Matching ───────────────────────────────────

    def _match_brackets(self):
        self._sel_brackets = []
        cursor = self.textCursor()
        pos = cursor.position()
        doc = self.document()

        def make_highlight(p: int, good: bool) -> QTextEdit.ExtraSelection:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            color = QColor(get_color("ok")) if good else QColor(get_color("err"))
            fmt.setBackground(color)
            fmt.setForeground(QColor(get_color("bg0")))
            sel.format = fmt
            c = QTextCursor(doc)
            c.setPosition(p)
            c.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            return sel

        if pos < doc.characterCount():
            ch = doc.characterAt(pos)
            pairs = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
            if ch in pairs:
                match_pos = self._find_matching_bracket(doc, pos, ch, pairs[ch])
                good = match_pos >= 0
                self._sel_brackets.append(make_highlight(pos, good))
                if good:
                    self._sel_brackets.append(make_highlight(match_pos, True))

        self._update_extra_selections()

    def _find_matching_bracket(self, doc, pos: int, open_ch: str, close_ch: str) -> int:
        forward = open_ch in "([{"
        depth = 0
        step = 1 if forward else -1
        curr = pos
        while 0 <= curr < doc.characterCount():
            c = doc.characterAt(curr)
            if c == open_ch: depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0: return curr
            curr += step
        return -1

    # ── Key Handling ───────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier

        # Clear ghost text on any edit
        if self._ghost_text:
            self.clear_ghost_text()

        if ctrl and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            self.zoom_in(); return
        if ctrl and key == Qt.Key.Key_Minus:
            self.zoom_out(); return
        if ctrl and key in (Qt.Key.Key_0, Qt.Key.Key_Insert):
            self.zoom_reset(); return
        if key == Qt.Key.Key_Escape:
            self.hide_search_requested.emit(); return
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_BracketLeft:
            block = self.textCursor().block()
            if self._is_foldable(block): self._toggle_fold(block)
            return
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_BracketRight:
            self._unfold_all(); return
        if ctrl and key == Qt.Key.Key_G:
            self._show_goto_line(); return
        if ctrl and key == Qt.Key.Key_D:
            self._select_word_under_cursor(); return
        if key == Qt.Key.Key_Tab:
            if self.textCursor().hasSelection():
                self._indent_selection(True)
            else:
                self.textCursor().insertText("    ")
            return
        if key == Qt.Key.Key_Backtab:
            self._indent_selection(False); return

        # Auto-close brackets/quotes
        if not ctrl and key in (Qt.Key.Key_ParenLeft, Qt.Key.Key_BracketLeft, Qt.Key.Key_BraceLeft):
            pairs = {Qt.Key.Key_ParenLeft: ("(", ")"),
                     Qt.Key.Key_BracketLeft: ("[", "]"),
                     Qt.Key.Key_BraceLeft: ("{", "}")}
            open_ch, close_ch = pairs[key]
            cursor = self.textCursor()
            if cursor.hasSelection():
                sel = cursor.selectedText()
                cursor.insertText(open_ch + sel + close_ch)
            else:
                cursor.insertText(open_ch + close_ch)
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
                self.setTextCursor(cursor)
            return

        # Skip closing bracket
        if key in (Qt.Key.Key_ParenRight, Qt.Key.Key_BracketRight, Qt.Key.Key_BraceRight):
            cursor = self.textCursor()
            pos = cursor.position()
            text = self.toPlainText()
            char_map = {Qt.Key.Key_ParenRight: ")", Qt.Key.Key_BracketRight: "]", Qt.Key.Key_BraceRight: "}"}
            expected = char_map[key]
            if pos < len(text) and text[pos] == expected:
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
                self.setTextCursor(cursor)
                return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._handle_enter(); return
        if ctrl and key == Qt.Key.Key_Slash:
            self._toggle_comment(); return
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_D:
            self._duplicate_line(); return
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_K:
            self._delete_line(); return

        super().keyPressEvent(event)

    def _handle_enter(self):
        cursor = self.textCursor()
        block_text = cursor.block().text()
        indent = len(block_text) - len(block_text.lstrip())
        indent_str = block_text[:indent]
        if block_text.rstrip().endswith(":"):
            indent_str += "    "
        cursor.insertText("\n" + indent_str)
        self.setTextCursor(cursor)

    def _indent_selection(self, indent: bool):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        lines = text.split("\u2029")
        if indent:
            new_lines = ["    " + l for l in lines]
        else:
            new_lines = [l[4:] if l.startswith("    ") else l[1:] if l.startswith("\t") else l for l in lines]
        cursor.insertText("\u2029".join(new_lines))

    def _toggle_comment(self):
        ext = Path(self._file_path).suffix.lower() if self._file_path else ""
        prefix = "#" if ext in (".py", ".sh", ".rb", ".yaml", ".yml") else "//"
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        lines = text.split("\u2029")
        all_commented = all(l.lstrip().startswith(prefix) for l in lines if l.strip())
        if all_commented:
            new_lines = [l.replace(prefix + " ", "", 1).replace(prefix, "", 1) if l.lstrip().startswith(prefix) else l for l in lines]
        else:
            new_lines = [prefix + " " + l if l.strip() else l for l in lines]
        cursor.insertText("\u2029".join(new_lines))

    def _duplicate_line(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        text = cursor.selectedText()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        cursor.insertText("\n" + text)

    def _delete_line(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.deleteChar()

    def _select_word_under_cursor(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        self.setTextCursor(cursor)

    def _show_goto_line(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Перейти к строке"))
        dlg.setFixedSize(280, 100)
        layout = QFormLayout(dlg)
        spn = QSpinBox(); spn.setRange(1, self.blockCount()); spn.setValue(1)
        layout.addRow(tr("Строка:"), spn)
        btn = QPushButton(tr("Перейти"))
        btn.clicked.connect(lambda: (self.go_to_line(spn.value()), dlg.accept()))
        layout.addRow(btn)
        dlg.exec()

    # ── Syntax checking ────────────────────────────────────

    def _on_text_changed(self):
        # Проверяем реальное состояние документа, а не наш флаг
        if self.document().isModified():
            if not self._is_modified:
                self._is_modified = True
                self.modified_changed.emit(True)
        else:
            # Документ считается неизменённым — сбрасываем наш флаг
            if self._is_modified:
                self._is_modified = False
                self.modified_changed.emit(False)
        self._syntax_check_timer.start(800)

    def _check_syntax(self):
        if not self._file_path or not self._file_path.endswith(".py"):
            return
        errors = []
        try:
            ast.parse(self.toPlainText(), filename=self._file_path)
        except SyntaxError as e:
            errors.append({"line": e.lineno or 0, "message": str(e.msg)})
        self._error_lines = {e["line"] for e in errors}
        self._line_num_area.set_error_lines(self._error_lines)
        self.syntax_errors_changed.emit(errors)
        self._underline_errors(errors)

    def _underline_errors(self, errors: list[dict]):
        self._sel_errors = []
        fmt = QTextCharFormat()
        fmt.setUnderlineColor(QColor(get_color("err")))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        for err_info in errors:
            line_no = err_info.get("line", 0)
            if line_no <= 0: continue
            block = self.document().findBlockByLineNumber(line_no - 1)
            if block.isValid():
                c = QTextCursor(block)
                c.select(QTextCursor.SelectionType.LineUnderCursor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = c
                sel.format = fmt
                self._sel_errors.append(sel)
        self._update_extra_selections()

    # ── Cursor info ────────────────────────────────────────

    def _on_cursor_moved(self):
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col  = cursor.positionInBlock() + 1
        self.cursor_pos_changed.emit(line, col)
        self._highlight_all_occurrences()

    def _highlight_all_occurrences(self):
        self._sel_occurrences = []
        cursor = self.textCursor()
        sel_text = cursor.selectedText().strip()
        if not sel_text or len(sel_text) < 2 or ' ' in sel_text or '\n' in sel_text:
            self._update_extra_selections()
            return
        occ_bg = QColor(get_color("sel"))
        fmt = QTextCharFormat()
        fmt.setBackground(occ_bg)
        fmt.setForeground(QColor(get_color("tx0")))
        doc = self.document()
        search_cursor = QTextCursor(doc)
        flags = QTextDocument.FindFlag.FindWholeWords | QTextDocument.FindFlag.FindCaseSensitively
        while True:
            found = doc.find(sel_text, search_cursor, flags)
            if found.isNull(): break
            if found.selectionStart() != cursor.selectionStart():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = found
                sel.format = fmt
                self._sel_occurrences.append(sel)
            search_cursor = found
        self._update_extra_selections()

    def _clear_occurrence_highlights(self):
        self._sel_occurrences = []
        self._update_extra_selections()

    # ── Code Folding ───────────────────────────────────────

    def _is_foldable(self, block) -> bool:
        text = block.text()
        stripped = text.rstrip()
        if not stripped: return False
        if self._file_path.endswith(".py"):
            return stripped.endswith(":")
        if any(self._file_path.endswith(e) for e in
               (".c", ".cpp", ".h", ".hpp", ".cs", ".java", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".kt", ".swift", ".php")):
            return stripped.endswith("{")
        return False

    def _find_fold_end(self, start_block) -> int:
        start_line = start_block.blockNumber() + 1
        start_text = start_block.text()
        start_indent = len(start_text) - len(start_text.lstrip())
        block = start_block.next()
        last_content_line = start_line
        while block.isValid():
            text = block.text()
            ln = block.blockNumber() + 1
            if text.strip():
                indent = len(text) - len(text.lstrip())
                if indent <= start_indent: break
                last_content_line = ln
            else:
                last_content_line = ln
            block = block.next()
        return last_content_line

    def _toggle_fold(self, block):
        line_num = block.blockNumber() + 1
        if line_num in self._folded_ranges:
            end_line = self._folded_ranges.pop(line_num)
            self._line_num_area._folded_blocks.discard(line_num)
            b = block.next()
            while b.isValid() and b.blockNumber() + 1 <= end_line:
                b.setVisible(True); b = b.next()
        else:
            end_line = self._find_fold_end(block)
            if end_line <= line_num: return
            self._folded_ranges[line_num] = end_line
            self._line_num_area._folded_blocks.add(line_num)
            b = block.next()
            while b.isValid() and b.blockNumber() + 1 <= end_line:
                b.setVisible(False); b = b.next()
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()
        self._line_num_area.update()
        self._update_line_number_area_width()

    def _is_inside_fold(self, line_num: int) -> bool:
        for start, end in self._folded_ranges.items():
            if start < line_num <= end: return True
        return False

    def _fold_all(self):
        block = self.document().begin()
        while block.isValid():
            if self._is_foldable(block):
                ln = block.blockNumber() + 1
                if ln not in self._folded_ranges: self._toggle_fold(block)
            block = block.next()

    def _unfold_all(self):
        for ln in list(self._folded_ranges.keys()):
            block = self.document().findBlockByLineNumber(ln - 1)
            if block.isValid(): self._toggle_fold(block)

    # ── Context Menu ───────────────────────────────────────

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        act_send = menu.addAction(tr("🤖 Отправить выделение в AI"))
        act_send.setEnabled(has_sel)
        act_send.triggered.connect(lambda: self._send_to_ai(cursor.selectedText()))
        act_send_file = menu.addAction(tr("🤖 Отправить файл в AI"))
        act_send_file.triggered.connect(lambda: self._send_to_ai(self.toPlainText()))
        menu.addSeparator()
        menu.addAction(tr("⊖ Свернуть блок  Ctrl+Shift+["),
                       lambda: self._toggle_fold(self.textCursor().block()) if self._is_foldable(self.textCursor().block()) else None)
        menu.addAction(tr("⊕ Развернуть всё  Ctrl+Shift+]"), self._unfold_all)
        menu.addAction(tr("⊖ Свернуть всё"), self._fold_all)
        menu.addSeparator()
        menu.addAction(tr("↗ Перейти к строке...  Ctrl+G"), self._show_goto_line)
        menu.addAction(tr("⧉ Дублировать строку  Ctrl+Shift+D"), self._duplicate_line)
        menu.addAction(tr("⌫ Удалить строку  Ctrl+Shift+K"), self._delete_line)
        menu.addAction(tr("// Переключить комментарий  Ctrl+/"), self._toggle_comment)
        menu.addSeparator()
        menu.addAction(tr("🔍+ Увеличить шрифт  Ctrl+="), self.zoom_in)
        menu.addAction(tr("🔍- Уменьшить шрифт  Ctrl+−"), self.zoom_out)
        menu.addAction(tr("🔍 Сбросить размер  Ctrl+0"), self.zoom_reset)
        menu.exec(event.globalPos())

    def _send_to_ai(self, text: str):
        parent = self.parent()
        while parent:
            if hasattr(parent, "_input_box") and hasattr(parent, "_send_message"):
                parent._input_box.setPlainText(f"Проанализируй этот код:\n```\n{text[:3000]}\n```")
                break
            parent = parent.parent()


# ══════════════════════════════════════════════════════════════
#  SEARCH BAR
# ══════════════════════════════════════════════════════════════

class SearchBar(QFrame):
    """Find & Replace bar (Ctrl+F / Ctrl+H)."""

    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._results: list[QTextCursor] = []
        self._current_idx = 0
        self.setObjectName("searchBar")
        self._build_ui()

    def _build_ui(self):
        bg0 = get_color("bg0"); bd2 = get_color("bd2"); tx2 = get_color("tx2")
        self.setStyleSheet(f"QFrame#searchBar {{ background: {bg0}; border-top: 1px solid {bd2}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self._fld_find = QLineEdit()
        self._fld_find.setPlaceholderText(tr("Найти..."))
        self._fld_find.setFixedWidth(200)
        self._fld_find.textChanged.connect(self._do_find)
        self._fld_find.returnPressed.connect(self.find_next)
        layout.addWidget(self._fld_find)

        self._chk_case = QCheckBox("Aa"); self._chk_case.setFixedWidth(36)
        self._chk_regex = QCheckBox(".*"); self._chk_regex.setFixedWidth(36)
        self._chk_case.toggled.connect(self._do_find)
        self._chk_regex.toggled.connect(self._do_find)
        layout.addWidget(self._chk_case); layout.addWidget(self._chk_regex)

        self._lbl_count = QLabel("")
        self._lbl_count.setObjectName("statusLabel")
        self._lbl_count.setMinimumWidth(60)
        layout.addWidget(self._lbl_count)

        btn_prev = QPushButton("↑"); btn_prev.setFixedWidth(28)
        btn_next = QPushButton("↓"); btn_next.setFixedWidth(28)
        btn_prev.clicked.connect(self.find_prev)
        btn_next.clicked.connect(self.find_next)
        layout.addWidget(btn_prev); layout.addWidget(btn_next)
        layout.addWidget(QLabel("|"))

        self._fld_replace = QLineEdit()
        self._fld_replace.setPlaceholderText(tr("Заменить..."))
        self._fld_replace.setFixedWidth(180)
        layout.addWidget(self._fld_replace)

        btn_repl_one = QPushButton(tr("Заменить")); btn_repl_one.setFixedWidth(90)
        btn_repl_all = QPushButton(tr("Все")); btn_repl_all.setFixedWidth(48)
        btn_repl_one.clicked.connect(self.replace_current)
        btn_repl_all.clicked.connect(self.replace_all)
        layout.addWidget(btn_repl_one); layout.addWidget(btn_repl_all)
        layout.addStretch()

        btn_close = QPushButton("✕"); btn_close.setFixedWidth(24)
        btn_close.clicked.connect(self.hide)
        btn_close.setStyleSheet(f"border:none;color:{tx2};")
        layout.addWidget(btn_close)

    def show_find(self):
        self.show(); self._fld_find.setFocus(); self._fld_find.selectAll()

    def show_replace(self):
        self.show(); self._fld_replace.setFocus()

    def _do_find(self):
        pattern = self._fld_find.text()
        if not pattern:
            self._lbl_count.setText(""); return
        flags = QTextDocument.FindFlag(0)
        if self._chk_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        self._results = []
        cursor = QTextCursor(self._editor.document())
        while True:
            if self._chk_regex.isChecked():
                from PyQt6.QtCore import QRegularExpression
                found = self._editor.document().find(QRegularExpression(pattern), cursor, flags)
            else:
                found = self._editor.document().find(pattern, cursor, flags)
            if found.isNull(): break
            self._results.append(found)
            cursor = found
        count = len(self._results)
        self._lbl_count.setText(f"{count} совп." if count else tr("Не найдено"))
        self._lbl_count.setStyleSheet(
            f"color:{get_color('err')};font-size:11px;" if not count
            else f"color:{get_color('tx2')};font-size:11px;")
        self._current_idx = 0
        self._highlight_results()

    def _highlight_results(self):
        extras = []
        fmt_all = QTextCharFormat()
        fmt_all.setBackground(QColor(get_color("sel")))
        fmt_current = QTextCharFormat()
        fmt_current.setBackground(QColor(get_color("ac")))
        fmt_current.setForeground(QColor(get_color("bg0")))
        for i, cursor in enumerate(self._results):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt_current if i == self._current_idx else fmt_all
            extras.append(sel)
        self._editor.set_search_selections(extras)
        if self._results and self._current_idx < len(self._results):
            self._editor.setTextCursor(self._results[self._current_idx])
            self._editor.centerCursor()

    def find_next(self):
        if not self._results: self._do_find(); return
        self._current_idx = (self._current_idx + 1) % len(self._results)
        self._highlight_results()

    def find_prev(self):
        if not self._results: self._do_find(); return
        self._current_idx = (self._current_idx - 1) % len(self._results)
        self._highlight_results()

    def replace_current(self):
        if self._results and self._current_idx < len(self._results):
            self._results[self._current_idx].insertText(self._fld_replace.text())
            self._do_find()

    def replace_all(self):
        for cursor in reversed(self._results):
            cursor.insertText(self._fld_replace.text())
        self._do_find()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide(); return
        super().keyPressEvent(event)


# ══════════════════════════════════════════════════════════════
#  MINIMAP WIDGET (Smart — cached pixmap + error heatmap)
# ══════════════════════════════════════════════════════════════

class MinimapWidget(QWidget):
    """
    Smart minimap with:
      - Cached QPixmap (only regenerates when document changes)
      - Error heatmap — red marks at error line positions
      - Draggable semi-transparent viewport overlay
    """
    MINIMAP_WIDTH = 80
    CHAR_W = 1
    CHAR_H = 2

    def __init__(self, editor: "CodeEditor", parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setFixedWidth(self.MINIMAP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Миникарта — нажми для прокрутки"))

        self._dragging = False
        self._cache: QPixmap | None = None
        self._cache_block_count = -1
        self._cache_version = -1

        # Repaint on scroll (viewport overlay moves)
        editor.verticalScrollBar().valueChanged.connect(self.update)
        # Regenerate cache on content change (debounced)
        self._regen_timer = QTimer(self)
        self._regen_timer.setSingleShot(True)
        self._regen_timer.setInterval(200)
        self._regen_timer.timeout.connect(self._invalidate_cache)
        editor.textChanged.connect(lambda: self._regen_timer.start())
        # Also invalidate when errors change
        editor.syntax_errors_changed.connect(lambda _: self._invalidate_cache())

    def _invalidate_cache(self):
        self._cache = None
        self.update()

    def _build_cache(self) -> QPixmap:
        """Render the entire document to a cached pixmap."""
        h = max(10, self.height())
        pixmap = QPixmap(self.MINIMAP_WIDTH, h)
        pixmap.fill(QColor(get_color("bg0")))

        painter = QPainter(pixmap)
        doc = self._editor.document()
        total_lines = doc.blockCount()
        if total_lines == 0:
            painter.end()
            return pixmap

        # Color lookup
        _dim1   = QColor(get_color("bd2"))
        _dim_ac = QColor(get_color("ac"));  _dim_ac.setAlpha(60)
        _dim_ok = QColor(get_color("ok"));  _dim_ok.setAlpha(40)
        _dim_tx = QColor(get_color("tx2")); _dim_tx.setAlpha(40)
        _dim_n  = QColor(get_color("tx3")); _dim_n.setAlpha(60)
        _err_c  = QColor(get_color("err")); _err_c.setAlpha(180)

        error_lines = self._editor.get_error_lines()
        max_draw = h // self.CHAR_H

        block = doc.begin()
        y = 0
        drawn = 0
        while block.isValid() and drawn < max_draw:
            text = block.text()
            stripped = text.lstrip()
            indent = len(text) - len(stripped)
            x = min(indent, 16) + 2
            line_num = block.blockNumber() + 1

            if stripped.startswith("#") or stripped.startswith("//"):
                col = _dim1
            elif stripped.startswith(("def ", "fn ", "func ", "function ")):
                col = _dim_ac
            elif stripped.startswith(("class ", "struct ", "interface ")):
                col = _dim_ok
            elif stripped.startswith(("import ", "from ", "use ", "using ")):
                col = _dim_tx
            else:
                col = _dim_n

            line_width = min(len(stripped) * self.CHAR_W, self.MINIMAP_WIDTH - x)
            if line_width > 0:
                painter.fillRect(x, y, line_width, max(1, self.CHAR_H - 1), col)

            # Error heatmap — red stripe on right edge
            if line_num in error_lines:
                painter.fillRect(self.MINIMAP_WIDTH - 4, y, 4, self.CHAR_H, _err_c)

            y += self.CHAR_H
            drawn += 1
            block = block.next()

        painter.end()
        return pixmap

    def paintEvent(self, event):
        # Regenerate cache if needed
        current_version = self._editor.document().revision()
        if self._cache is None or current_version != self._cache_version:
            self._cache = self._build_cache()
            self._cache_version = current_version

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)

        # Draw viewport overlay
        doc = self._editor.document()
        total_lines = max(1, doc.blockCount())
        visible_h = self._editor.viewport().height()
        line_h = max(1, int(self._editor.blockBoundingRect(doc.begin()).height()))
        visible_lines = max(1, visible_h // line_h)
        scroll_val = self._editor.verticalScrollBar().value()
        scroll_max = max(1, self._editor.verticalScrollBar().maximum())

        vp_top = int((scroll_val / max(1, scroll_max + visible_lines)) * self.height())
        vp_h = max(10, int(visible_lines / max(1, total_lines) * self.height()))

        # Viewport fill
        vp_color = QColor(get_color("sel")); vp_color.setAlpha(100)
        painter.fillRect(0, vp_top, self.MINIMAP_WIDTH, vp_h, vp_color)

        # Viewport border
        border_c = QColor(get_color("ac")); border_c.setAlpha(150)
        painter.setPen(QPen(border_c, 1))
        painter.drawRect(0, vp_top, self.MINIMAP_WIDTH - 1, vp_h)
        painter.end()

    def mousePressEvent(self, event):
        self._dragging = True
        self._scroll_to(event.pos().y())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._scroll_to(event.pos().y())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _scroll_to(self, y: int):
        ratio = max(0.0, min(1.0, y / max(1, self.height())))
        bar = self._editor.verticalScrollBar()
        bar.setValue(int(ratio * bar.maximum()))


# ══════════════════════════════════════════════════════════════
#  CODE EDITOR PANEL (editor + toolbar + search + minimap + status)
# ══════════════════════════════════════════════════════════════

class CodeEditorPanel(QWidget):
    """Complete editor panel wrapping CodeEditor."""
    send_to_ai    = pyqtSignal(str)
    run_requested = pyqtSignal(str)

    def __init__(self, path: str, content: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._error_count = 0
        self._build_ui(content)
        register_theme_refresh(self._refresh_panel_styles)

    def _build_ui(self, content: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Breadcrumb bar
        self._breadcrumb = QLabel("")
        self._breadcrumb.setObjectName("breadcrumb")
        self._breadcrumb.setFixedHeight(20)
        layout.addWidget(self._breadcrumb)
        self._refresh_panel_styles()

        # Micro toolbar
        toolbar = QFrame()
        toolbar.setObjectName("editorToolbar")
        toolbar.setFixedHeight(28)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(6, 0, 6, 0); tl.setSpacing(1)

        for icon, tip, fn in [
            ("🔍+", tr("Увеличить (Ctrl+=)"), lambda: self.editor.zoom_in()),
            ("🔍-", tr("Уменьшить (Ctrl+-)"), lambda: self.editor.zoom_out()),
            ("⟳",  tr("Сбросить размер (Ctrl+0)"), lambda: self.editor.zoom_reset()),
        ]:
            b = QPushButton(icon); b.setToolTip(tip); b.clicked.connect(fn)
            tl.addWidget(b)

        tl.addWidget(self._vline())

        for icon, tip, fn in [
            ("//", tr("Комментарий (Ctrl+/)"), lambda: self.editor._toggle_comment()),
            ("⧉",  tr("Дублировать строку (Ctrl+Shift+D)"), lambda: self.editor._duplicate_line()),
            ("⌫",  tr("Удалить строку (Ctrl+Shift+K)"), lambda: self.editor._delete_line()),
        ]:
            b = QPushButton(icon); b.setToolTip(tip); b.clicked.connect(fn)
            tl.addWidget(b)

        tl.addWidget(self._vline())

        btn_find = QPushButton(tr("🔍 Найти"))
        btn_find.setToolTip(tr("Найти (Ctrl+F)")); btn_find.clicked.connect(self._show_find)
        tl.addWidget(btn_find)

        btn_replace = QPushButton(tr("⇄ Заменить"))
        btn_replace.setToolTip(tr("Найти и заменить (Ctrl+H)")); btn_replace.clicked.connect(self._show_replace)
        tl.addWidget(btn_replace)

        tl.addWidget(self._vline())

        self._btn_wrap = QPushButton("↵ Wrap")
        self._btn_wrap.setToolTip(tr("Перенос строк (Alt+Z)"))
        self._btn_wrap.setCheckable(True)
        self._btn_wrap.toggled.connect(self._toggle_wrap)
        tl.addWidget(self._btn_wrap)

        tl.addWidget(self._vline())

        btn_run = QPushButton(tr("▶ Запустить"))
        btn_run.setToolTip(tr("Запустить этот скрипт"))
        btn_run.setObjectName("successBtn")
        btn_run.clicked.connect(lambda: self.run_requested.emit(self._path))
        tl.addWidget(btn_run)

        tl.addStretch()

        self._lbl_lang = QLabel(language_name(self._path) or "Plain Text")
        self._lbl_lang.setObjectName("statusLabel")
        tl.addWidget(self._lbl_lang)

        layout.addWidget(toolbar)

        # Editor + minimap horizontal layout
        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(0)

        self.editor = CodeEditor()
        self.editor.set_file(self._path, content)
        self.editor.syntax_errors_changed.connect(self._on_errors)
        self.editor.cursor_pos_changed.connect(self._on_cursor)
        self.editor.textChanged.connect(self._update_breadcrumb)
        editor_row.addWidget(self.editor, stretch=1)

        self._minimap = MinimapWidget(self.editor)
        editor_row.addWidget(self._minimap)

        layout.addLayout(editor_row, stretch=1)

        # Search bar
        self.search_bar = SearchBar(self.editor)
        self.search_bar.hide()
        layout.addWidget(self.search_bar)
        self.editor.hide_search_requested.connect(self.search_bar.hide)

        # Status line
        status = QFrame()
        status.setObjectName("editorStatus")
        status.setFixedHeight(20)
        sl = QHBoxLayout(status); sl.setContentsMargins(10, 0, 10, 0); sl.setSpacing(16)

        self._lbl_pos   = QLabel("Ln 1, Col 1")
        self._lbl_sel   = QLabel("")
        self._lbl_err   = QLabel("")
        self._lbl_words = QLabel("")
        self._lbl_enc   = QLabel("UTF-8")
        self._lbl_tabs  = QLabel("Spaces: 4")

        sl.addWidget(self._lbl_pos)
        sl.addWidget(self._lbl_sel)
        sl.addWidget(self._lbl_err)
        sl.addStretch()
        sl.addWidget(self._lbl_words)
        sl.addWidget(self._lbl_tabs)
        sl.addWidget(self._lbl_enc)
        layout.addWidget(status)

        # Shortcuts
        from PyQt6.QtGui import QShortcut as QSC
        QSC(QKeySequence("Ctrl+F"), self).activated.connect(self._show_find)
        QSC(QKeySequence("Ctrl+H"), self).activated.connect(self._show_replace)
        QSC(QKeySequence("Alt+Z"), self).activated.connect(lambda: self._btn_wrap.toggle())

        self._update_breadcrumb()

        # Word count timer
        self._wc_timer = QTimer(self)
        self._wc_timer.setSingleShot(True)
        self._wc_timer.setInterval(500)
        self._wc_timer.timeout.connect(self._update_word_count)
        self.editor.textChanged.connect(lambda: self._wc_timer.start())

    def _refresh_panel_styles(self):
        bg0 = get_color("bg0"); bd2 = get_color("bd2"); ac = get_color("ac")
        self._breadcrumb.setStyleSheet(
            f"background:{bg0};border-bottom:1px solid {bd2};color:{ac};"
            f"font-size:10px;padding:2px 12px;font-family:'JetBrains Mono',monospace;"
        )

    def _toggle_wrap(self, checked: bool):
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if checked else QPlainTextEdit.LineWrapMode.NoWrap
        self.editor.setLineWrapMode(mode)
        if checked:
            self._btn_wrap.setStyleSheet(
                f"QPushButton{{background:transparent;color:{get_color('ok')};border:none;padding:2px 8px;font-size:11px;}}"
            )
        else:
            self._btn_wrap.setStyleSheet("")

    def _update_breadcrumb(self):
        if not self._path.endswith(".py"):
            self._breadcrumb.setText(f"  {self._path.replace(chr(92), '/')}")
            return
        try:
            import ast as _ast
            src = self.editor.toPlainText()
            tree = _ast.parse(src)
            cursor_line = self.editor.textCursor().blockNumber() + 1
            path_parts = []
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
                    if hasattr(node, "lineno") and node.lineno <= cursor_line:
                        end = getattr(node, "end_lineno", cursor_line + 1)
                        if end >= cursor_line:
                            icon = "🔵" if isinstance(node, _ast.ClassDef) else "🟢"
                            path_parts.append(f"{icon} {node.name}")
            if path_parts:
                self._breadcrumb.setText("  " + "  ›  ".join(path_parts[-3:]))
            else:
                short = self._path.replace("\\", "/").split("/")[-1]
                self._breadcrumb.setText(f"  📄 {short}")
        except Exception:
            self._breadcrumb.setText("")

    def _update_word_count(self):
        text = self.editor.toPlainText()
        words = len(text.split())
        lines = self.editor.blockCount()
        self._lbl_words.setText(f"{lines} {tr('стр')} · {words} {tr('слов')}")

    def _vline(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1); f.setStyleSheet("background:#1E2030;margin:3px 4px;")
        return f

    def _show_find(self):
        self.search_bar.show_find()

    def _show_replace(self):
        self.search_bar.show_replace()

    def _on_errors(self, errors: list[dict]):
        self._error_count = len(errors)
        if errors:
            self._lbl_err.setText(f"⚠ {len(errors)} {tr('ошибок')}")
            self._lbl_err.setStyleSheet("color:#F7768E;font-size:10px;")
        else:
            self._lbl_err.setText("")

    def _on_cursor(self, line: int, col: int):
        self._lbl_pos.setText(f"Ln {line}, Col {col}")
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            sel_len = len(cursor.selectedText())
            self._lbl_sel.setText(f"({sel_len} {tr('выбр.')})")
            self._lbl_sel.setStyleSheet("color:#7AA2F7;font-size:10px;")
        else:
            self._lbl_sel.setText("")
        self._update_breadcrumb()

    @property
    def is_modified(self) -> bool:
        # Используем реальное состояние документа Qt
        return self.editor.document().isModified()

    @property
    def is_modified(self) -> bool:
        return self.editor.is_modified

    def get_content(self) -> str:
        return self.editor.get_content()
