"""
Patch Preview Dialog — before/after diff with syntax highlight.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QSplitter, QFrame, QWidget
)


class PatchPreviewDialog(QDialog):

    def __init__(self, search_content: str, replace_content: str,
                 file_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Предпросмотр патча — {file_path or 'patch'}")
        self.setMinimumSize(800, 500)
        self.resize(900, 600)
        self.setModal(True)
        self._build_ui(search_content, replace_content, file_path)

    def _build_ui(self, search: str, replace: str, file_path: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("📋 Предпросмотр изменений")
        title.setObjectName("titleLabel")
        hdr.addWidget(title)
        hdr.addStretch()
        if file_path:
            fp_label = QLabel(f"📄 {file_path}")
            fp_label.setObjectName("accentLabel")
            hdr.addWidget(fp_label)
        layout.addLayout(hdr)

        # Stats row
        search_lines = len(search.splitlines())
        replace_lines = len(replace.splitlines())
        delta = replace_lines - search_lines
        delta_str = (f"+{delta}" if delta > 0 else str(delta)) if delta != 0 else "±0"
        delta_color = "#9ECE6A" if delta >= 0 else "#F7768E"

        stats = QHBoxLayout()
        stats.addWidget(self._badge(f"− {search_lines} строк", "#F7768E", "#2D1A1A"))
        stats.addWidget(self._badge(f"+ {replace_lines} строк", "#9ECE6A", "#1A2D1A"))
        stats.addWidget(self._badge(f"Δ {delta_str}", delta_color, "#1A1A2D"))
        stats.addStretch()
        layout.addLayout(stats)

        # Diff panels
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # BEFORE panel
        before_w = QWidget()
        before_l = QVBoxLayout(before_w)
        before_l.setContentsMargins(0, 0, 0, 0)
        before_l.setSpacing(4)
        before_hdr = QLabel("ПОИСК (удаляемый код)")
        before_hdr.setObjectName("sectionLabel")
        before_hdr.setStyleSheet("color: #F7768E; letter-spacing: 1px;")
        before_l.addWidget(before_hdr)
        self._before_view = QTextEdit()
        self._before_view.setObjectName("diffSearch")
        self._before_view.setReadOnly(True)
        self._before_view.setPlainText(search)
        self._before_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 12))
        before_l.addWidget(self._before_view)
        splitter.addWidget(before_w)

        # AFTER panel
        after_w = QWidget()
        after_l = QVBoxLayout(after_w)
        after_l.setContentsMargins(0, 0, 0, 0)
        after_l.setSpacing(4)
        after_hdr = QLabel("ЗАМЕНА (новый код)")
        after_hdr.setObjectName("sectionLabel")
        after_hdr.setStyleSheet("color: #9ECE6A; letter-spacing: 1px;")
        after_l.addWidget(after_hdr)
        self._after_view = QTextEdit()
        self._after_view.setObjectName("diffReplace")
        self._after_view.setReadOnly(True)
        self._after_view.setPlainText(replace)
        self._after_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 12))
        after_l.addWidget(self._after_view)
        splitter.addWidget(after_w)

        layout.addWidget(splitter, stretch=1)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        btn_close = QPushButton("Закрыть")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

    @staticmethod
    def _badge(text: str, color: str, bg: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; background: {bg}; "
            f"border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
        )
        return lbl
