"""
Patch Preview Dialog — before/after diff with syntax highlight.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QSplitter, QWidget
)

try:
    from ui.i18n import tr, register_listener
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {
        "bg2": "#131722", "bd2": "#1E2030", "tx0": "#CDD6F4",
        "ok": "#9ECE6A", "err": "#F7768E",
    }.get(k, "#CDD6F4")
    def register_theme_refresh(cb): pass


class PatchPreviewDialog(QDialog):

    def __init__(self, search_content: str, replace_content: str,
                 file_path: str = "", parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self.setWindowTitle(f"{tr('Предпросмотр патча')} — {file_path or 'patch'}")
        self.setMinimumSize(800, 500)
        self.resize(900, 600)
        self.setModal(True)
        self._build_ui(search_content, replace_content, file_path)
        register_listener(self._retranslate)
        register_theme_refresh(self._refresh_styles)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass

    def _retranslate(self, _lang: str = ""):
        self.setWindowTitle(f"{tr('Предпросмотр патча')} — {self._file_path or 'patch'}")
        self._title_lbl.setText(tr("📋 Предпросмотр изменений"))
        self._before_hdr.setText(tr("ПОИСК (удаляемый код)"))
        self._after_hdr.setText(tr("ЗАМЕНА (новый код)"))
        self._btn_close.setText(tr("Закрыть"))

    def _build_ui(self, search: str, replace: str, file_path: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        self._title_lbl = QLabel(tr("📋 Предпросмотр изменений"))
        self._title_lbl.setObjectName("titleLabel")
        hdr.addWidget(self._title_lbl)
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
        ok_c  = get_color("ok")
        err_c = get_color("err")
        delta_color = ok_c if delta >= 0 else err_c

        stats = QHBoxLayout()
        self._badge_del = self._make_badge(f"− {search_lines} {tr('строк')}", "del")
        self._badge_add = self._make_badge(f"+ {replace_lines} {tr('строк')}", "add")
        self._badge_delta = self._make_badge(f"Δ {delta_str}", "ok" if delta >= 0 else "err")
        stats.addWidget(self._badge_del)
        stats.addWidget(self._badge_add)
        stats.addWidget(self._badge_delta)
        stats.addStretch()
        layout.addLayout(stats)

        # Diff panels
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # BEFORE panel
        before_w = QWidget()
        before_l = QVBoxLayout(before_w)
        before_l.setContentsMargins(0, 0, 0, 0)
        before_l.setSpacing(4)
        self._before_hdr = QLabel(tr("ПОИСК (удаляемый код)"))
        self._before_hdr.setObjectName("sectionLabel")
        before_l.addWidget(self._before_hdr)
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
        self._after_hdr = QLabel(tr("ЗАМЕНА (новый код)"))
        self._after_hdr.setObjectName("sectionLabel")
        after_l.addWidget(self._after_hdr)
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
        self._btn_close = QPushButton(tr("Закрыть"))
        self._btn_close.setFixedWidth(100)
        self._btn_close.clicked.connect(self.accept)
        footer.addWidget(self._btn_close)
        layout.addLayout(footer)

        # Apply initial theme-aware styles
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        """Re-apply inline styles using current theme colors."""
        ok_c  = get_color("ok")
        err_c = get_color("err")
        bg2   = get_color("bg2")
        bd2   = get_color("bd2")
        # Panel headers
        self._before_hdr.setStyleSheet(f"color: {err_c}; letter-spacing: 1px;")
        self._after_hdr.setStyleSheet(f"color: {ok_c}; letter-spacing: 1px;")
        # Diff viewers (complement the QSS diffSearch/diffReplace rules)
        self._before_view.setStyleSheet(
            f"background-color: {bg2}; color: {err_c}; border-radius: 4px;"
            f" padding: 8px; border: 1px solid {err_c}33;"
        )
        self._after_view.setStyleSheet(
            f"background-color: {bg2}; color: {ok_c}; border-radius: 4px;"
            f" padding: 8px; border: 1px solid {ok_c}33;"
        )
        # Re-apply badge styles
        self._apply_badge_style(self._badge_del,   err_c, bg2)
        self._apply_badge_style(self._badge_add,   ok_c,  bg2)
        delta_color = ok_c if "+" in self._badge_delta.text() or "±" in self._badge_delta.text() else err_c
        self._apply_badge_style(self._badge_delta, delta_color, bg2)

    @staticmethod
    def _apply_badge_style(lbl: "QLabel", color: str, bg: str) -> None:
        lbl.setStyleSheet(
            f"color: {color}; background: {bg}; border: 1px solid {color}44;"
            f" border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
        )

    def _make_badge(self, text: str, kind: str) -> "QLabel":
        """Create a badge label; style applied later by _refresh_styles."""
        lbl = QLabel(text)
        return lbl

    @staticmethod
    def _badge(text: str, color: str, bg: str) -> QLabel:  # legacy compat
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; background: {bg}; "
            f"border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
        )
        return lbl
