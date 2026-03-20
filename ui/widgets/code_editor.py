"""
Enhanced Code Editor — Notepad++-style with full features:
  - Line numbers with click-to-select
  - Syntax highlighting (Python, JS, JSON, YAML, SQL, Bash, Markdown)
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
  - Minimap scrollbar
  - Modified indicator (● in tab title)
  - Context menu: AI actions, standard edit
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
    QSyntaxHighlighter, QPalette, QTextFormat, QPolygon
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



# ══════════════════════════════════════════════════════════════
#  LINE NUMBER AREA
# ══════════════════════════════════════════════════════════════

class LineNumberArea(QWidget):
    """Gutter with line numbers, fold arrows, bookmark dots, error dots."""

    FOLD_W = 14   # width of the fold arrow column

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor
        self._error_lines: set[int] = set()
        self._bookmark_lines: set[int] = set()
        self._folded_blocks: set[int] = set()   # first-line numbers of folded ranges
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
                ln = block.blockNumber() + 1
                # Click in the fold arrow area (left FOLD_W pixels)
                if x <= self.FOLD_W:
                    if self._editor._is_foldable(block):
                        self._editor._toggle_fold(block)
                else:
                    # Click on line number → select that line
                    cursor = self._editor.textCursor()
                    cursor.setPosition(block.position())
                    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                    self._editor.setTextCursor(cursor)
                break
            block = block.next()

    def _gutter_context(self, pos: QPoint):
        menu = QMenu(self)
        menu.addAction(tr("📌 Переключить закладку"), lambda: self._toggle_bookmark(pos))
        menu.addAction(tr("Очистить закладки"), self._clear_bookmarks)
        menu.addSeparator()
        menu.addAction(tr("⊕ Развернуть всё"), self._editor._unfold_all)
        menu.addAction(tr("⊖ Свернуть всё"), self._editor._fold_all)
        menu.exec(self.mapToGlobal(pos))

    def _toggle_bookmark(self, pos):
        y = pos.y()
        block = self._editor.firstVisibleBlock()
        offset = self._editor.contentOffset()
        while block.isValid():
            top = int(self._editor.blockBoundingGeometry(block).translated(offset).top())
            height = int(self._editor.blockBoundingRect(block).height())
            if top <= y <= top + height:
                ln = block.blockNumber() + 1
                if ln in self._bookmark_lines:
                    self._bookmark_lines.remove(ln)
                else:
                    self._bookmark_lines.add(ln)
                self.update()
                break
            block = block.next()

    def _clear_bookmarks(self):
        self._bookmark_lines.clear()
        self.update()


# ══════════════════════════════════════════════════════════════
#  MAIN CODE EDITOR
# ══════════════════════════════════════════════════════════════

class CodeEditor(QPlainTextEdit):
    """
    Full-featured code editor widget.
    Signals:
        modified_changed(bool) — emitted when dirty state changes
        cursor_pos_changed(int, int) — line, column
        syntax_errors_changed(list[dict]) — list of {line, message}
    """
    modified_changed    = pyqtSignal(bool)
    cursor_pos_changed  = pyqtSignal(int, int)
    syntax_errors_changed = pyqtSignal(list)
    hide_search_requested = pyqtSignal()   # emitted when Escape pressed in editor

    # Bracket pairs
    _BRACKETS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
    _CLOSE_BRACKETS = set(")]}")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: str = ""
        self._is_modified = False
        self._error_lines: set[int] = set()
        self._base_font_size = 12
        self._highlighter = None
        self._folded_ranges: dict[int, int] = {}   # start_line → end_line (1-based)

        # Line number area
        self._line_num_area = LineNumberArea(self)

        # Auto-save dirty check timer
        self._syntax_check_timer = QTimer(self)
        self._syntax_check_timer.setSingleShot(True)
        self._syntax_check_timer.timeout.connect(self._check_syntax)

        self._setup_appearance()
        self._connect_signals()

    def _setup_appearance(self):
        font = QFont()
        font.setFamilies(["JetBrains Mono", "Cascadia Code", "Consolas", "Courier New"])
        font.setPointSize(self._base_font_size)
        self.setFont(font)

        # Dark editor colors
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#0D1117"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#CDD6F4"))
        self.setPalette(palette)
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0D1117;
                color: #CDD6F4;
                border: none;
                selection-background-color: #2E3148;
                selection-color: #CDD6F4;
            }
        """)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(' ') * 4)
        self.updateRequest.connect(self._update_line_number_area)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self._update_line_number_area_width()

    def _connect_signals(self):
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.cursorPositionChanged.connect(self._match_brackets)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_file(self, path: str, content: str) -> None:
        self._file_path = path
        self.setPlainText(content)
        self._is_modified = False
        self.modified_changed.emit(False)
        # Attach highlighter
        if self._highlighter:
            self._highlighter.setDocument(None)
        self._highlighter = create_highlighter(self.document(), path)
        # Trigger initial syntax check
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

    def _apply_font_size(self):
        font = self.font()
        font.setPointSize(self._base_font_size)
        self.setFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(' ') * 4)
        self._update_line_number_area_width()

    def go_to_line(self, line: int) -> None:
        block = self.document().findBlockByLineNumber(line - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()

    def get_error_lines(self) -> set[int]:
        return set(self._error_lines)

    # ── Line Numbers ───────────────────────────────────────────────────────────

    def _line_number_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        num_w = 14 + QFontMetrics(self.font()).horizontalAdvance('9') * max(digits, 3)
        return num_w + LineNumberArea.FOLD_W   # fold arrow column on the left

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
        painter.fillRect(event.rect(), QColor("#0A0D14"))

        fold_w = LineNumberArea.FOLD_W
        total_w = self._line_num_area.width()

        # Fold column separator line
        painter.setPen(QPen(QColor("#1A1E2E"), 1))
        painter.drawLine(fold_w, event.rect().top(), fold_w, event.rect().bottom())

        # Right border line
        painter.setPen(QPen(QColor("#1E2030"), 1))
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

                # Current-line background
                if block_num == current_line:
                    painter.fillRect(fold_w, top, total_w - fold_w - 1, lh, QColor("#131722"))
                    painter.setPen(QColor("#CDD6F4"))
                elif line_num in self._line_num_area._error_lines:
                    painter.fillRect(fold_w, top, total_w - fold_w - 1, lh, QColor("#2A0A0A"))
                    painter.setPen(QColor("#F7768E"))
                else:
                    painter.setPen(QColor("#3B4261"))

                # Line number text
                painter.drawText(
                    fold_w, top, total_w - fold_w - 8, lh,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(line_num)
                )

                # ── Fold arrow ────────────────────────────────
                is_foldable = self._is_foldable(block)
                is_folded   = line_num in self._folded_ranges

                if is_foldable:
                    arrow_size = 8
                    ax = fold_w // 2 - arrow_size // 2
                    ay = mid_y - arrow_size // 2

                    painter.setPen(Qt.PenStyle.NoPen)
                    if is_folded:
                        # ▶ right-pointing (collapsed)
                        painter.setBrush(QBrush(QColor("#7AA2F7")))
                        pts = [
                            QPoint(ax, ay),
                            QPoint(ax, ay + arrow_size),
                            QPoint(ax + arrow_size, ay + arrow_size // 2),
                        ]
                    else:
                        # ▼ down-pointing (expanded)
                        painter.setBrush(QBrush(QColor("#565f89")))
                        pts = [
                            QPoint(ax, ay),
                            QPoint(ax + arrow_size, ay),
                            QPoint(ax + arrow_size // 2, ay + arrow_size),
                        ]
                    painter.drawPolygon(QPolygon(pts))

                # ── Fold range vertical line ───────────────────
                elif self._is_inside_fold(line_num):
                    painter.setPen(QPen(QColor("#2E3148"), 1))
                    cx = fold_w // 2
                    painter.drawLine(cx, top, cx, top + lh)

                # ── Bookmark dot ──────────────────────────────
                if line_num in self._line_num_area._bookmark_lines:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor("#E0AF68")))
                    painter.drawEllipse(2, mid_y - 4, 8, 8)

                # ── Error dot ─────────────────────────────────
                if line_num in self._line_num_area._error_lines:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor("#F7768E")))
                    painter.drawEllipse(2, mid_y - 4, 8, 8)

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

    # ── Current Line Highlight ─────────────────────────────────────────────────

    def _highlight_current_line(self):
        extras = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor("#131722"))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extras.append(sel)
        self.setExtraSelections(extras)

    # ── Bracket Matching ───────────────────────────────────────────────────────

    def _match_brackets(self):
        cursor = self.textCursor()
        pos = cursor.position()
        text = self.toPlainText()

        def make_highlight(p: int, good: bool) -> QTextEdit.ExtraSelection:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            color = QColor("#9ECE6A") if good else QColor("#F7768E")
            fmt.setBackground(color)
            fmt.setForeground(QColor("#0D1117"))
            sel.format = fmt
            c = self.textCursor()
            c.setPosition(p)
            c.movePosition(QTextCursor.MoveOperation.NextCharacter,
                           QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            return sel

        current = self.extraSelections()
        # Remove old bracket highlights (keep current line highlight)
        current = [s for s in current
                   if s.format.background().color() == QColor("#131722")]

        if pos < len(text):
            ch = text[pos]
            pairs = {"(": ")", "[": "]", "{": "}",
                     ")": "(", "]": "[", "}": "{"}
            if ch in pairs:
                match_pos = self._find_matching_bracket(text, pos, ch, pairs[ch])
                good = match_pos >= 0
                current.append(make_highlight(pos, good))
                if good:
                    current.append(make_highlight(match_pos, True))

        self.setExtraSelections(current)

    def _find_matching_bracket(self, text: str, pos: int, open_ch: str, close_ch: str) -> int:
        forward = open_ch in "([{"
        depth = 0
        rng = range(pos, len(text)) if forward else range(pos, -1, -1)
        for i in rng:
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    # ── Key Handling ───────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier

        # Zoom
        if ctrl and key == Qt.Key.Key_Equal:
            self.zoom_in(); return
        if ctrl and key == Qt.Key.Key_Minus:
            self.zoom_out(); return
        if ctrl and key == Qt.Key.Key_0:
            self.zoom_reset(); return

        # Escape → hide search bar
        if key == Qt.Key.Key_Escape:
            self.hide_search_requested.emit()
            return

        # Fold/unfold current block (Ctrl+Shift+[ / Ctrl+Shift+])
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_BracketLeft:
            block = self.textCursor().block()
            if self._is_foldable(block):
                self._toggle_fold(block)
            return
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_BracketRight:
            self._unfold_all(); return

        # Go to line
        if ctrl and key == Qt.Key.Key_G:
            self._show_goto_line(); return

        # Select word (Ctrl+D like VS Code)
        if ctrl and key == Qt.Key.Key_D:
            self._select_word_under_cursor(); return

        # Tab → 4 spaces
        if key == Qt.Key.Key_Tab:
            if self.textCursor().hasSelection():
                self._indent_selection(True)
            else:
                self.textCursor().insertText("    ")
            return

        # Shift+Tab → unindent
        if key == Qt.Key.Key_Backtab:
            self._indent_selection(False); return

        # Auto-close brackets/quotes
        if not ctrl and key in (Qt.Key.Key_ParenLeft, Qt.Key.Key_BracketLeft,
                                 Qt.Key.Key_BraceLeft):
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

        # Skip closing bracket if already there
        if key in (Qt.Key.Key_ParenRight, Qt.Key.Key_BracketRight, Qt.Key.Key_BraceRight):
            cursor = self.textCursor()
            pos = cursor.position()
            text = self.toPlainText()
            char_map = {Qt.Key.Key_ParenRight: ")",
                        Qt.Key.Key_BracketRight: "]",
                        Qt.Key.Key_BraceRight: "}"}
            expected = char_map[key]
            if pos < len(text) and text[pos] == expected:
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
                self.setTextCursor(cursor)
                return

        # Auto-indent on Enter
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._handle_enter(); return

        # Comment toggle (Ctrl+/)
        if ctrl and key == Qt.Key.Key_Slash:
            self._toggle_comment(); return

        # Duplicate line (Ctrl+Shift+D)
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_D:
            self._duplicate_line(); return

        # Delete line (Ctrl+Shift+K)
        if ctrl and mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_K:
            self._delete_line(); return

        super().keyPressEvent(event)

    def _handle_enter(self):
        cursor = self.textCursor()
        block_text = cursor.block().text()
        indent = len(block_text) - len(block_text.lstrip())
        indent_str = block_text[:indent]
        # Increase indent after colon
        stripped = block_text.rstrip()
        if stripped.endswith(":"):
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
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        lines = text.split("\u2029")  # Qt paragraph separator
        if indent:
            new_lines = ["    " + l for l in lines]
        else:
            new_lines = [l[4:] if l.startswith("    ") else
                         l[1:] if l.startswith("\t") else l
                         for l in lines]
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
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        lines = text.split("\u2029")
        all_commented = all(l.lstrip().startswith(prefix) for l in lines if l.strip())
        if all_commented:
            new_lines = [l.replace(prefix + " ", "", 1).replace(prefix, "", 1)
                         if l.lstrip().startswith(prefix) else l
                         for l in lines]
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
        cursor.deleteChar()  # remove the newline too

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

    # ── Syntax checking ────────────────────────────────────────────────────────

    def _on_text_changed(self):
        if not self._is_modified:
            self._is_modified = True
            self.modified_changed.emit(True)
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
        # Underline errors
        self._underline_errors(errors)

    def _underline_errors(self, errors: list[dict]):
        """Use ExtraSelections for error underlines — never wipe the syntax highlighting."""
        # QColor is not hashable — compare via .rgb() integer
        _KEEP_RGBS = {
            QColor("#131722").rgb(),   # current line highlight
            QColor("#2E3148").rgb(),   # search result
            QColor("#7AA2F7").rgb(),   # current search result
            QColor("#9ECE6A").rgb(),   # bracket match good
        }
        existing = [
            s for s in self.extraSelections()
            if (s.format.background().color().rgb() in _KEEP_RGBS
                and s.format.underlineStyle() != QTextCharFormat.UnderlineStyle.WaveUnderline)
        ]

        error_sels = []
        fmt = QTextCharFormat()
        fmt.setUnderlineColor(QColor("#F7768E"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)

        for err in errors:
            line_no = err.get("line", 0)
            if line_no <= 0:
                continue
            block = self.document().findBlockByLineNumber(line_no - 1)
            if block.isValid():
                c = QTextCursor(block)
                c.select(QTextCursor.SelectionType.LineUnderCursor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = c
                sel.format = fmt
                error_sels.append(sel)

        self.setExtraSelections(existing + error_sels)

    # ── Cursor info ────────────────────────────────────────────────────────────

    def _on_cursor_moved(self):
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col  = cursor.positionInBlock() + 1
        self.cursor_pos_changed.emit(line, col)
        # Highlight all occurrences of selected word
        self._highlight_all_occurrences()

    def _highlight_all_occurrences(self):
        """Highlight all occurrences of the word under cursor (VS Code style)."""
        cursor = self.textCursor()
        sel_text = cursor.selectedText().strip()

        if not sel_text or len(sel_text) < 2 or ' ' in sel_text or '\n' in sel_text:
            self._clear_occurrence_highlights()
            return

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#1E2A40"))
        fmt.setForeground(QColor("#CDD6F4"))
        _occ_rgb = QColor("#1E2A40").rgb()

        occurrences = []
        doc = self.document()
        search_cursor = QTextCursor(doc)
        flags = QTextDocument.FindFlag.FindWholeWords | QTextDocument.FindFlag.FindCaseSensitively
        while True:
            found = doc.find(sel_text, search_cursor, flags)
            if found.isNull():
                break
            if found.selectionStart() != cursor.selectionStart():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = found
                sel.format = fmt
                occurrences.append(sel)
            search_cursor = found

        _WAVE = QTextCharFormat.UnderlineStyle.WaveUnderline
        current = [
            s for s in self.extraSelections()
            if s.format.background().color().rgb() == QColor("#131722").rgb()
            or s.format.underlineStyle() == _WAVE
        ]
        self.setExtraSelections(current + occurrences)

    def _clear_occurrence_highlights(self):
        _OCC_RGB = QColor("#1E2A40").rgb()
        _WAVE = QTextCharFormat.UnderlineStyle.WaveUnderline
        keep = [
            s for s in self.extraSelections()
            if s.format.background().color().rgb() != _OCC_RGB
        ]
        self.setExtraSelections(keep)

    # ── Code Folding ───────────────────────────────────────────────────────────

    def _is_foldable(self, block) -> bool:
        """Return True if this block starts a foldable region (def/class/if/for/etc.)."""
        text = block.text()
        stripped = text.rstrip()
        if not stripped:
            return False
        # Python: lines ending with ':'
        if self._file_path.endswith(".py"):
            return stripped.endswith(":")
        # C-like: lines ending with '{' or containing a function/class definition
        if any(self._file_path.endswith(e) for e in
               (".c", ".cpp", ".h", ".hpp", ".cs", ".java", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".kt", ".swift", ".php")):
            return stripped.endswith("{")
        return False

    def _find_fold_end(self, start_block) -> int:
        """Find the last line of the foldable block starting at start_block. Returns 1-based line number."""
        import re
        start_line = start_block.blockNumber() + 1
        start_text = start_block.text()
        start_indent = len(start_text) - len(start_text.lstrip())

        block = start_block.next()
        last_content_line = start_line

        while block.isValid():
            text = block.text()
            ln = block.blockNumber() + 1
            if text.strip():  # non-empty line
                indent = len(text) - len(text.lstrip())
                if indent <= start_indent:
                    break
                last_content_line = ln
            else:
                last_content_line = ln  # keep blank lines inside
            block = block.next()

        return last_content_line

    def _toggle_fold(self, block):
        """Collapse or expand the block starting at `block`."""
        line_num = block.blockNumber() + 1
        if line_num in self._folded_ranges:
            # Unfold
            end_line = self._folded_ranges.pop(line_num)
            self._line_num_area._folded_blocks.discard(line_num)
            b = block.next()
            while b.isValid() and b.blockNumber() + 1 <= end_line:
                b.setVisible(True)
                b = b.next()
        else:
            # Fold
            end_line = self._find_fold_end(block)
            if end_line <= line_num:
                return
            self._folded_ranges[line_num] = end_line
            self._line_num_area._folded_blocks.add(line_num)
            b = block.next()
            while b.isValid() and b.blockNumber() + 1 <= end_line:
                b.setVisible(False)
                b = b.next()

        # Force layout and repaint
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()
        self._line_num_area.update()
        self._update_line_number_area_width()

    def _is_inside_fold(self, line_num: int) -> bool:
        """True if this line is inside (but not the header of) a folded block."""
        for start, end in self._folded_ranges.items():
            if start < line_num <= end:
                return True
        return False

    def _fold_all(self):
        """Fold all top-level foldable blocks."""
        block = self.document().begin()
        while block.isValid():
            if self._is_foldable(block):
                ln = block.blockNumber() + 1
                if ln not in self._folded_ranges:
                    self._toggle_fold(block)
            block = block.next()

    def _unfold_all(self):
        """Expand all folded blocks."""
        for ln in list(self._folded_ranges.keys()):
            block = self.document().findBlockByLineNumber(ln - 1)
            if block.isValid():
                self._toggle_fold(block)

    # ── Context Menu ───────────────────────────────────────────────────────────

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
        act_fold = menu.addAction(tr("⊖ Свернуть блок  Ctrl+Shift+["))
        act_fold.triggered.connect(lambda: self._toggle_fold(self.textCursor().block())
                                   if self._is_foldable(self.textCursor().block()) else None)
        act_unfold_all = menu.addAction(tr("⊕ Развернуть всё  Ctrl+Shift+]"))
        act_unfold_all.triggered.connect(self._unfold_all)
        act_fold_all = menu.addAction(tr("⊖ Свернуть всё"))
        act_fold_all.triggered.connect(self._fold_all)

        menu.addSeparator()
        act_goto = menu.addAction(tr("↗ Перейти к строке...  Ctrl+G"))
        act_goto.triggered.connect(self._show_goto_line)

        act_dup = menu.addAction(tr("⧉ Дублировать строку  Ctrl+Shift+D"))
        act_dup.triggered.connect(self._duplicate_line)

        act_del = menu.addAction(tr("⌫ Удалить строку  Ctrl+Shift+K"))
        act_del.triggered.connect(self._delete_line)

        act_comment = menu.addAction(tr("// Переключить комментарий  Ctrl+/"))
        act_comment.triggered.connect(self._toggle_comment)

        menu.addSeparator()
        zi = menu.addAction(tr("🔍+ Увеличить шрифт  Ctrl+="))
        zi.triggered.connect(self.zoom_in)
        zo = menu.addAction(tr("🔍- Уменьшить шрифт  Ctrl+−"))
        zo.triggered.connect(self.zoom_out)
        zr = menu.addAction(tr("🔍 Сбросить размер  Ctrl+0"))
        zr.triggered.connect(self.zoom_reset)

        menu.exec(event.globalPos())

    def _send_to_ai(self, text: str):
        # Walk up to find MainWindow and call its method
        parent = self.parent()
        while parent:
            if hasattr(parent, "_input_box") and hasattr(parent, "_send_message"):
                parent._input_box.setPlainText(
                    f"Проанализируй этот код:\n```\n{text[:3000]}\n```"
                )
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
        self.setStyleSheet("""
            QFrame#searchBar {
                background: #111820;
                border-top: 1px solid #1E2030;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        # Find
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
        layout.addWidget(self._chk_case)
        layout.addWidget(self._chk_regex)

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet("color:#565f89;font-size:11px;min-width:60px;")
        layout.addWidget(self._lbl_count)

        btn_prev = QPushButton("↑"); btn_prev.setFixedWidth(28)
        btn_next = QPushButton("↓"); btn_next.setFixedWidth(28)
        btn_prev.clicked.connect(self.find_prev)
        btn_next.clicked.connect(self.find_next)
        layout.addWidget(btn_prev); layout.addWidget(btn_next)
        layout.addWidget(QLabel("|"))

        # Replace
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
        btn_close.setStyleSheet("border:none;color:#565f89;")
        layout.addWidget(btn_close)

    def show_find(self):
        self.show()
        self._fld_find.setFocus()
        self._fld_find.selectAll()

    def show_replace(self):
        self.show()
        self._fld_replace.setFocus()

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
                found = self._editor.document().find(
                    __import__('PyQt6.QtCore', fromlist=['QRegularExpression']).QRegularExpression(pattern), cursor, flags)
            else:
                found = self._editor.document().find(pattern, cursor, flags)
            if found.isNull():
                break
            self._results.append(found)
            cursor = found
        count = len(self._results)
        self._lbl_count.setText(f"{count} совп." if count else tr("Не найдено"))
        self._lbl_count.setStyleSheet(
            "color:#F7768E;font-size:11px;" if not count else "color:#565f89;font-size:11px;"
        )
        self._current_idx = 0
        self._highlight_results()

    def _highlight_results(self):
        extras = []
        fmt_all = QTextCharFormat()
        fmt_all.setBackground(QColor("#2E3148"))
        fmt_current = QTextCharFormat()
        fmt_current.setBackground(QColor("#7AA2F7"))
        fmt_current.setForeground(QColor("#0D1117"))

        for i, cursor in enumerate(self._results):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt_current if i == self._current_idx else fmt_all
            extras.append(sel)

        self._editor.setExtraSelections(extras)
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
#  CODE EDITOR PANEL (editor + toolbar + search + status)
# ══════════════════════════════════════════════════════════════

class CodeEditorPanel(QWidget):
    """
    Complete editor panel wrapping CodeEditor with:
    - Mini toolbar (zoom, format, run)
    - Search/replace bar
    - Status line (Ln/Col, encoding, language, errors)
    """
    send_to_ai = pyqtSignal(str)      # text to send
    run_requested = pyqtSignal(str)   # file path to run

    def __init__(self, path: str, content: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._error_count = 0
        self._build_ui(content)

    def _build_ui(self, content: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Breadcrumb bar ─────────────────────────────────────
        self._breadcrumb = QLabel("")
        self._breadcrumb.setObjectName("breadcrumb")
        self._breadcrumb.setStyleSheet(
            "background:#080B12;border-bottom:1px solid #1E2030;color:#7AA2F7;font-size:10px;padding:2px 12px;font-family:'JetBrains Mono',monospace;"
        )
        self._breadcrumb.setFixedHeight(20)
        layout.addWidget(self._breadcrumb)

        # ── Micro toolbar ──────────────────────────────────────
        toolbar = QFrame()
        toolbar.setObjectName("editorToolbar")
        toolbar.setFixedHeight(28)
        toolbar.setStyleSheet(
            "QFrame#editorToolbar{background:#0A0D14;border-bottom:1px solid #1E2030;}QPushButton{background:transparent;border:none;color:#565f89;padding:2px 8px;font-size:11px;border-radius:3px;}QPushButton:hover{background:#1E2030;color:#CDD6F4;}"
        )
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

        # Word wrap toggle
        self._btn_wrap = QPushButton("↵ Wrap")
        self._btn_wrap.setToolTip(tr("Перенос строк (Alt+Z)"))
        self._btn_wrap.setCheckable(True)
        self._btn_wrap.toggled.connect(self._toggle_wrap)
        tl.addWidget(self._btn_wrap)

        tl.addWidget(self._vline())

        btn_run = QPushButton(tr("▶ Запустить"))
        btn_run.setToolTip(tr("Запустить этот скрипт"))
        btn_run.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#39FF84;padding:2px 8px;font-size:11px;}QPushButton:hover{background:#0D2B1A;}"
        )
        btn_run.clicked.connect(lambda: self.run_requested.emit(self._path))
        tl.addWidget(btn_run)

        tl.addStretch()

        # Language indicator
        self._lbl_lang = QLabel(language_name(self._path) or "Plain Text")
        self._lbl_lang.setStyleSheet("color:#3B4261;font-size:10px;padding:0 8px;")
        tl.addWidget(self._lbl_lang)

        layout.addWidget(toolbar)

        # ── Editor in horizontal layout with minimap ───────────
        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(0)

        self.editor = CodeEditor()
        self.editor.set_file(self._path, content)
        self.editor.syntax_errors_changed.connect(self._on_errors)
        self.editor.cursor_pos_changed.connect(self._on_cursor)
        self.editor.textChanged.connect(self._update_breadcrumb)
        editor_row.addWidget(self.editor, stretch=1)

        # Minimap panel
        self._minimap = MinimapWidget(self.editor)
        editor_row.addWidget(self._minimap)

        layout.addLayout(editor_row, stretch=1)

        # ── Search bar ─────────────────────────────────────────
        self.search_bar = SearchBar(self.editor)
        self.search_bar.hide()
        layout.addWidget(self.search_bar)
        # Escape in editor or search bar closes the bar
        self.editor.hide_search_requested.connect(self.search_bar.hide)

        # ── Status line ────────────────────────────────────────
        status = QFrame()
        status.setObjectName("editorStatus")
        status.setFixedHeight(20)
        status.setStyleSheet(
            "QFrame#editorStatus{background:#0A0D14;border-top:1px solid #1E2030;}QLabel{font-size:10px;font-family:'JetBrains Mono',monospace;color:#3B4261;}"
        )
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

        # Initial breadcrumb
        self._update_breadcrumb()
        # Word count update timer
        self._wc_timer = QTimer(self)
        self._wc_timer.setSingleShot(True)
        self._wc_timer.setInterval(500)
        self._wc_timer.timeout.connect(self._update_word_count)
        self.editor.textChanged.connect(lambda: self._wc_timer.start())

    def _toggle_wrap(self, checked: bool):
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if checked else QPlainTextEdit.LineWrapMode.NoWrap
        self.editor.setLineWrapMode(mode)
        self._btn_wrap.setStyleSheet(
            "QPushButton{background:#1E2A1A;color:#9ECE6A;border:none;padding:2px 8px;font-size:11px;}"
            if checked else ""
        )

    def _update_breadcrumb(self):
        """Show current class/function path for Python files."""
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
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1)
        f.setStyleSheet("background:#1E2030;margin:3px 4px;")
        return f

    def _show_find(self):
        self.search_bar.show_find()

    def _show_replace(self):
        self.search_bar.show_replace()

    def _on_errors(self, errors: list[dict]):
        self._error_count = len(errors)
        if errors:
            msg = f"⚠ {len(errors)} {tr('ошибок')}"
            self._lbl_err.setText(msg)
            self._lbl_err.setStyleSheet("color:#F7768E;font-size:10px;")
        else:
            self._lbl_err.setText("")

    def _on_cursor(self, line: int, col: int):
        self._lbl_pos.setText(f"Ln {line}, Col {col}")
        # Selection info
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            sel_len = len(cursor.selectedText())
            self._lbl_sel.setText(f"({sel_len} {tr('выбр.')})") 
            self._lbl_sel.setStyleSheet("color:#7AA2F7;font-size:10px;")
        else:
            self._lbl_sel.setText("")
        self._update_breadcrumb()

    @property
    def file_path(self) -> str:
        return self._path

    @property
    def is_modified(self) -> bool:
        return self.editor.is_modified

    def get_content(self) -> str:
        return self.editor.get_content()


# ══════════════════════════════════════════════════════════════
#  MINIMAP WIDGET
# ══════════════════════════════════════════════════════════════

class MinimapWidget(QWidget):
    """
    Minimap — a scaled-down read-only overview of the document.
    Click or drag to scroll the main editor.
    """
    MINIMAP_WIDTH = 80
    CHAR_W = 1    # pixels per character in minimap
    CHAR_H = 2    # pixels per line in minimap

    def __init__(self, editor: "CodeEditor", parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setFixedWidth(self.MINIMAP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Миникарта — нажми для прокрутки"))
        # Repaint when document changes
        editor.textChanged.connect(self.update)
        editor.verticalScrollBar().valueChanged.connect(self.update)
        self._dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#070A10"))

        doc = self._editor.document()
        total_lines = doc.blockCount()
        if total_lines == 0:
            return

        visible_h = self._editor.viewport().height()
        line_h = max(1, int(self._editor.blockBoundingRect(doc.begin()).height()))
        visible_lines = max(1, visible_h // line_h)
        scroll_val = self._editor.verticalScrollBar().value()
        scroll_max = max(1, self._editor.verticalScrollBar().maximum())

        # Draw viewport indicator
        vp_top = int((scroll_val / max(1, scroll_max + visible_lines))
                     * self.height())
        vp_h = max(10, int(visible_lines / max(1, total_lines) * self.height()))
        painter.fillRect(0, vp_top, self.MINIMAP_WIDTH, vp_h, QColor("#1E2A40"))

        # Draw simplified text lines
        block = doc.begin()
        y = 0
        max_draw = self.height() // self.CHAR_H
        drawn = 0

        while block.isValid() and drawn < max_draw:
            text = block.text()
            stripped = text.lstrip()
            indent = len(text) - len(stripped)
            x = min(indent, 16) + 2

            # Color approximation based on first token
            if stripped.startswith("#") or stripped.startswith("//"):
                col = QColor("#2A3050")
            elif stripped.startswith(("def ", "fn ", "func ", "function ")):
                col = QColor("#2A4870")
            elif stripped.startswith(("class ", "struct ", "interface ")):
                col = QColor("#3A4020")
            elif stripped.startswith(("import ", "from ", "use ", "using ")):
                col = QColor("#2A4035")
            else:
                col = QColor("#1A2028")

            line_width = min(len(stripped) * self.CHAR_W, self.MINIMAP_WIDTH - x)
            if line_width > 0:
                painter.fillRect(x, y, line_width, max(1, self.CHAR_H - 1), col)

            y += self.CHAR_H
            drawn += 1
            block = block.next()

        # Viewport highlight border
        painter.setPen(QPen(QColor("#3B4C70"), 1))
        painter.drawRect(0, vp_top, self.MINIMAP_WIDTH - 1, vp_h)

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
