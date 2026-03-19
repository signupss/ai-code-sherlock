"""
Enhanced Code Editor with:
  - Line number gutter
  - Ctrl+F search bar
  - Right-click context menu (Send selection to AI, etc.)
  - Current line highlight
  - Bracket matching
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QRect, QSize, QRegularExpression, pyqtSignal, QTimer
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPaintEvent, QResizeEvent,
    QTextCharFormat, QTextCursor, QKeySequence, QTextDocument
)
from PyQt6.QtWidgets import (
    QWidget, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
    QFrame, QLabel, QPushButton, QLineEdit, QCheckBox, QMenu
)

from ui.widgets.syntax_highlighter import create_highlighter, language_name


# ──────────────────────────────────────────────────────────
#  Line Number Area
# ──────────────────────────────────────────────────────────

class LineNumberArea(QWidget):

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent):
        self._editor.line_number_area_paint_event(event)


# ──────────────────────────────────────────────────────────
#  Code Editor (QPlainTextEdit + line numbers + search)
# ──────────────────────────────────────────────────────────

class CodeEditor(QPlainTextEdit):
    """
    Full-featured code editor widget.
    Embed in CodeEditorPanel for the complete experience.
    """

    send_to_ai_requested = pyqtSignal(str)    # selected text or whole file
    find_references      = pyqtSignal(str)    # selected word

    LINE_COLOR      = QColor("#1A1F2E")       # current line highlight
    GUTTER_BG       = QColor("#0A0D14")
    GUTTER_FG       = QColor("#3B4261")
    GUTTER_CURR     = QColor("#565f89")
    BRACKET_FMT     = QTextCharFormat()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: str | None = None
        self._highlighter = None

        # Fonts
        code_font = QFont("JetBrains Mono,Cascadia Code,Fira Code,Consolas", 13)
        code_font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(code_font)

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(28)  # 4 spaces equivalent

        # Line number area
        self._line_num_area = LineNumberArea(self)

        # Bracket format
        self.BRACKET_FMT.setBackground(QColor("#2E3148"))
        self.BRACKET_FMT.setForeground(QColor("#89DDFF"))

        # Connections
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.cursorPositionChanged.connect(self._match_brackets)

        self._update_line_number_area_width(0)
        self._highlight_current_line()

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def load_file(self, path: str) -> None:
        self._file_path = path
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.setPlainText(content)
        self._highlighter = create_highlighter(self.document(), path)

    def set_content(self, content: str, file_path: str = "") -> None:
        self._file_path = file_path
        self.setPlainText(content)
        if file_path:
            self._highlighter = create_highlighter(self.document(), file_path)

    def get_content(self) -> str:
        return self.toPlainText()

    def get_selected_text(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def get_current_word(self) -> str:
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        return cursor.selectedText()

    def language(self) -> str:
        return language_name(self._file_path or "")

    # ── Line Number Area ───────────────────────────────────

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int):
        if dy:
            self._line_num_area.scroll(0, dy)
        else:
            self._line_num_area.update(0, rect.y(), self._line_num_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_num_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event: QPaintEvent):
        painter = QPainter(self._line_num_area)
        painter.fillRect(event.rect(), self.GUTTER_BG)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                color = self.GUTTER_CURR if block_number == current_line else self.GUTTER_FG
                painter.setPen(color)
                painter.drawText(
                    0, top,
                    self._line_num_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    # ── Current Line Highlight ─────────────────────────────

    def _highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QPlainTextEdit.ExtraSelection()
            selection.format.setBackground(self.LINE_COLOR)
            selection.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True
            )
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)

    # ── Bracket Matching ───────────────────────────────────

    _OPEN  = set("([{")
    _CLOSE = set(")]}")
    _PAIRS = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}

    def _match_brackets(self):
        # Very lightweight bracket matcher
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        if pos >= len(text):
            return

        ch = text[pos] if pos < len(text) else ""
        if ch not in self._OPEN and ch not in self._CLOSE:
            return

        # Find matching bracket
        if ch in self._OPEN:
            match_pos = self._find_forward(text, pos, ch, self._PAIRS[ch])
        else:
            match_pos = self._find_backward(text, pos, ch, self._PAIRS[ch])

        if match_pos is None:
            return

        # Highlight both
        extras = list(self.extraSelections())
        for p in (pos, match_pos):
            sel = QPlainTextEdit.ExtraSelection()
            sel.format = self.BRACKET_FMT
            sel.cursor = self.textCursor()
            sel.cursor.setPosition(p)
            sel.cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor
            )
            extras.append(sel)
        self.setExtraSelections(extras)

    def _find_forward(self, text: str, start: int, open_ch: str, close_ch: str):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _find_backward(self, text: str, start: int, close_ch: str, open_ch: str):
        depth = 0
        for i in range(start, -1, -1):
            if text[i] == close_ch:
                depth += 1
            elif text[i] == open_ch:
                depth -= 1
                if depth == 0:
                    return i
        return None

    # ── Context Menu ───────────────────────────────────────

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1E2030; border: 1px solid #2E3148;
                border-radius: 6px; padding: 4px;
                color: #CDD6F4; font-size: 12px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background: #2E3148; }
            QMenu::separator { background: #2E3148; height: 1px; margin: 4px 0; }
        """)

        selected = self.get_selected_text()
        word = self.get_current_word()

        # AI actions
        if selected:
            act = menu.addAction("🔍  Отправить выделенное в AI")
            act.triggered.connect(lambda: self.send_to_ai_requested.emit(selected))

            act2 = menu.addAction("🛠  Улучшить выделенный код")
            act2.triggered.connect(
                lambda: self.send_to_ai_requested.emit(
                    f"Улучши этот код:\n```\n{selected}\n```"
                )
            )

        act_all = menu.addAction("📄  Отправить весь файл в AI")
        act_all.triggered.connect(
            lambda: self.send_to_ai_requested.emit(self.get_content())
        )

        menu.addSeparator()

        # Standard actions
        act_cut = menu.addAction("✂️  Вырезать  Ctrl+X")
        act_cut.triggered.connect(self.cut)
        act_cut.setEnabled(bool(selected))

        act_copy = menu.addAction("📋  Копировать  Ctrl+C")
        act_copy.triggered.connect(self.copy)
        act_copy.setEnabled(bool(selected))

        act_paste = menu.addAction("📌  Вставить  Ctrl+V")
        act_paste.triggered.connect(self.paste)

        menu.addSeparator()

        act_find = menu.addAction("🔎  Найти  Ctrl+F")
        act_find.triggered.connect(lambda: self.parent().show_search() if hasattr(self.parent(), "show_search") else None)

        if word:
            act_ref = menu.addAction(f"⚡  Найти '{word}' в проекте")
            act_ref.triggered.connect(lambda: self.find_references.emit(word))

        menu.exec(self.mapToGlobal(pos))

    # ── Tab / Indent handling ──────────────────────────────

    def keyPressEvent(self, event):
        # Tab → insert 4 spaces
        if event.key() == Qt.Key.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(cursor)
            else:
                cursor.insertText("    ")
            return

        # Shift+Tab → unindent
        if event.key() == Qt.Key.Key_Backtab:
            cursor = self.textCursor()
            self._unindent_selection(cursor)
            return

        # Auto-close brackets
        pairs = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
        ch = event.text()
        if ch in pairs:
            cursor = self.textCursor()
            cursor.insertText(ch + pairs[ch])
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return

        super().keyPressEvent(event)

    def _indent_selection(self, cursor: QTextCursor):
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.beginEditBlock()
        while cursor.position() <= end:
            cursor.insertText("    ")
            end += 4
            if not cursor.movePosition(QTextCursor.MoveOperation.Down):
                break
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.endEditBlock()

    def _unindent_selection(self, cursor: QTextCursor):
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.beginEditBlock()
        while cursor.position() <= end:
            line = cursor.block().text()
            spaces = len(line) - len(line.lstrip(" "))
            remove = min(4, spaces)
            if remove > 0:
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor, remove
                )
                cursor.removeSelectedText()
                end -= remove
            if not cursor.movePosition(QTextCursor.MoveOperation.Down):
                break
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.endEditBlock()


# ──────────────────────────────────────────────────────────
#  Search Bar Widget
# ──────────────────────────────────────────────────────────

class SearchBar(QFrame):
    """Inline Ctrl+F search bar — appears at top of editor."""

    closed = pyqtSignal()

    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._matches: list = []
        self._current_match = -1
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            "SearchBar { background: #1E2030; border-bottom: 1px solid #2E3148; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        lbl = QLabel("Поиск:")
        lbl.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(lbl)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Найти...")
        self._search_input.setFixedWidth(200)
        self._search_input.textChanged.connect(self._do_search)
        self._search_input.returnPressed.connect(self._next_match)
        layout.addWidget(self._search_input)

        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Заменить на...")
        self._replace_input.setFixedWidth(180)
        layout.addWidget(self._replace_input)

        self._chk_case = QCheckBox("Aа")
        self._chk_case.setToolTip("Учитывать регистр")
        self._chk_case.stateChanged.connect(self._do_search)
        layout.addWidget(self._chk_case)

        self._chk_regex = QCheckBox(".*")
        self._chk_regex.setToolTip("Регулярное выражение")
        self._chk_regex.stateChanged.connect(self._do_search)
        layout.addWidget(self._chk_regex)

        self._lbl_count = QLabel("0 / 0")
        self._lbl_count.setStyleSheet("color: #565f89; font-size: 11px; min-width: 50px;")
        layout.addWidget(self._lbl_count)

        btn_prev = QPushButton("↑")
        btn_prev.setFixedWidth(28)
        btn_prev.clicked.connect(self._prev_match)
        layout.addWidget(btn_prev)

        btn_next = QPushButton("↓")
        btn_next.setFixedWidth(28)
        btn_next.clicked.connect(self._next_match)
        layout.addWidget(btn_next)

        btn_replace = QPushButton("Заменить")
        btn_replace.setFixedWidth(80)
        btn_replace.clicked.connect(self._replace_current)
        layout.addWidget(btn_replace)

        btn_replace_all = QPushButton("Все")
        btn_replace_all.setFixedWidth(50)
        btn_replace_all.clicked.connect(self._replace_all)
        layout.addWidget(btn_replace_all)

        layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setObjectName("iconBtn")
        btn_close.setFixedWidth(24)
        btn_close.clicked.connect(self._close)
        layout.addWidget(btn_close)

    def show_and_focus(self):
        self.show()
        selected = self._editor.get_selected_text()
        if selected and "\n" not in selected:
            self._search_input.setText(selected)
        self._search_input.setFocus()
        self._search_input.selectAll()
        self._do_search()

    def _build_flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self._chk_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def _do_search(self):
        query = self._search_input.text()
        self._matches = []
        self._current_match = -1

        if not query:
            self._lbl_count.setText("0 / 0")
            self._clear_highlights()
            return

        doc = self._editor.document()
        cursor = QTextCursor(doc)

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3B4261"))
        fmt.setForeground(QColor("#CDD6F4"))

        self._clear_highlights()

        flags = self._build_flags()
        if self._chk_regex.isChecked():
            rx = QRegularExpression(query)
            if not self._chk_case.isChecked():
                rx.setPatternOptions(
                    QRegularExpression.PatternOption.CaseInsensitiveOption
                )
            cursor = doc.find(rx, 0)
        else:
            cursor = doc.find(query, 0, flags)

        while not cursor.isNull():
            self._matches.append(QTextCursor(cursor))
            if self._chk_regex.isChecked():
                rx = QRegularExpression(query)
                cursor = doc.find(rx, cursor)
            else:
                cursor = doc.find(query, cursor, flags)

        total = len(self._matches)
        if total > 0:
            self._current_match = 0
            self._jump_to(0)
        self._lbl_count.setText(
            f"{self._current_match + 1 if total else 0} / {total}"
        )

    def _jump_to(self, index: int):
        if 0 <= index < len(self._matches):
            self._editor.setTextCursor(self._matches[index])
            self._editor.ensureCursorVisible()
            self._lbl_count.setText(f"{index + 1} / {len(self._matches)}")

    def _next_match(self):
        if self._matches:
            self._current_match = (self._current_match + 1) % len(self._matches)
            self._jump_to(self._current_match)

    def _prev_match(self):
        if self._matches:
            self._current_match = (self._current_match - 1) % len(self._matches)
            self._jump_to(self._current_match)

    def _replace_current(self):
        if 0 <= self._current_match < len(self._matches):
            c = self._matches[self._current_match]
            c.insertText(self._replace_input.text())
            self._do_search()

    def _replace_all(self):
        query = self._search_input.text()
        replace = self._replace_input.text()
        if not query:
            return
        content = self._editor.get_content()
        if self._chk_regex.isChecked():
            flags = 0 if self._chk_case.isChecked() else re.IGNORECASE
            new = re.sub(query, replace, content, flags=flags)
        else:
            if self._chk_case.isChecked():
                new = content.replace(query, replace)
            else:
                new = re.sub(re.escape(query), replace, content, flags=re.IGNORECASE)
        self._editor.setPlainText(new)
        self._do_search()

    def _clear_highlights(self):
        cursor = QTextCursor(self._editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        cursor.setCharFormat(fmt)

    def _close(self):
        self.hide()
        self._clear_highlights()
        self._editor.setFocus()
        self.closed.emit()


# ──────────────────────────────────────────────────────────
#  Complete Editor Panel  (editor + search bar + status)
# ──────────────────────────────────────────────────────────

class CodeEditorPanel(QWidget):
    """
    Full panel: file tab bar + code editor + search bar + status line.
    Replaces the plain QTabWidget in MainWindow.
    """

    file_modified    = pyqtSignal(str, str)   # path, content
    send_to_ai       = pyqtSignal(str)
    find_in_project  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open_files: dict[str, CodeEditor] = {}
        self._active_path: str | None = None
        self._build_ui()

    # ── Build ──────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        from PyQt6.QtWidgets import QTabWidget, QShortcut
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, stretch=1)

        # Search bar (hidden by default)
        self._search_bar = None  # Created lazily per editor

        # Status line
        status = QFrame()
        status.setFixedHeight(20)
        status.setStyleSheet("background: #0A0D14; border-top: 1px solid #1E2030;")
        sl = QHBoxLayout(status)
        sl.setContentsMargins(10, 0, 10, 0)

        self._lbl_lang = QLabel("Plain Text")
        self._lbl_lang.setStyleSheet("color: #565f89; font-size: 10px;")
        sl.addWidget(self._lbl_lang)
        sl.addStretch()
        self._lbl_pos = QLabel("Ln 1, Col 1")
        self._lbl_pos.setStyleSheet("color: #565f89; font-size: 10px;")
        sl.addWidget(self._lbl_pos)
        layout.addWidget(status)

        # Keyboard shortcuts (work on this panel)
        from PyQt6.QtGui import QShortcut as GShortcut
        GShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.show_search)
        GShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_active)

    # ── Public API ─────────────────────────────────────────

    def open_file(self, path: str) -> None:
        if path in self._open_files:
            # Switch to existing tab
            for i in range(self._tabs.count()):
                if self._tabs.tabToolTip(i) == path:
                    self._tabs.setCurrentIndex(i)
                    return

        editor = CodeEditor()
        editor.load_file(path)
        editor.textChanged.connect(lambda: self._on_content_changed(path, editor))
        editor.send_to_ai_requested.connect(self.send_to_ai)
        editor.find_references.connect(self.find_in_project)
        editor.cursorPositionChanged.connect(self._update_position)

        self._open_files[path] = editor

        # Container with optional search bar
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        search_bar = SearchBar(editor)
        search_bar.hide()
        search_bar.setProperty("is_search_bar", True)
        cl.addWidget(search_bar)
        cl.addWidget(editor, stretch=1)

        name = Path(path).name
        idx = self._tabs.addTab(container, name)
        self._tabs.setTabToolTip(idx, path)
        self._tabs.setCurrentIndex(idx)

    def set_content(self, path: str, content: str) -> None:
        """Update editor content after patch apply."""
        if path in self._open_files:
            editor = self._open_files[path]
            editor.blockSignals(True)
            pos = editor.textCursor().position()
            editor.setPlainText(content)
            cursor = editor.textCursor()
            cursor.setPosition(min(pos, len(content)))
            editor.setTextCursor(cursor)
            editor.blockSignals(False)

    def get_active_path(self) -> str | None:
        return self._active_path

    def get_active_content(self) -> str:
        if self._active_path and self._active_path in self._open_files:
            return self._open_files[self._active_path].get_content()
        return ""

    def get_all_open(self) -> dict[str, str]:
        return {
            path: editor.get_content()
            for path, editor in self._open_files.items()
        }

    def save_active(self):
        if not self._active_path:
            return
        content = self.get_active_content()
        try:
            with open(self._active_path, "w", encoding="utf-8") as f:
                f.write(content)
            # Mark tab as saved (remove asterisk)
            for i in range(self._tabs.count()):
                if self._tabs.tabToolTip(i) == self._active_path:
                    self._tabs.setTabText(i, Path(self._active_path).name)
                    break
        except Exception as e:
            pass  # Handled by caller

    def show_search(self):
        container = self._tabs.currentWidget()
        if not container:
            return
        layout = container.layout()
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w and w.property("is_search_bar"):
                w.show_and_focus()
                break

    # ── Internals ──────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        if index < 0:
            self._active_path = None
            return
        path = self._tabs.tabToolTip(index)
        self._active_path = path
        if path:
            self._lbl_lang.setText(language_name(path))

    def _on_content_changed(self, path: str, editor: CodeEditor):
        # Mark tab as modified
        for i in range(self._tabs.count()):
            if self._tabs.tabToolTip(i) == path:
                name = Path(path).name
                if not self._tabs.tabText(i).endswith("●"):
                    self._tabs.setTabText(i, f"{name} ●")
                break
        self.file_modified.emit(path, editor.get_content())

    def _update_position(self):
        editor = self._open_files.get(self._active_path or "")
        if not editor:
            return
        cursor = editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self._lbl_pos.setText(f"Ln {line}, Col {col}")

    def _close_tab(self, index: int):
        path = self._tabs.tabToolTip(index)
        if path in self._open_files:
            del self._open_files[path]
        self._tabs.removeTab(index)

    def _active_editor(self) -> CodeEditor | None:
        return self._open_files.get(self._active_path or "")


import re  # needed by SearchBar._replace_all
