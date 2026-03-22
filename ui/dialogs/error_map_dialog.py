"""
Error Map Dialog — view and manage the error knowledge base.
"""
from __future__ import annotations
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QSplitter, QWidget, QTabWidget, QFrame, QLineEdit,
    QMessageBox, QComboBox
)

from services.error_map import ErrorMapService, ErrorRecord, AvoidPattern

try:
    from ui.i18n import tr, register_listener, retranslate_widget
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass
    def retranslate_widget(w): pass

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {
        "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722",
        "bd2": "#1E2030", "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
        "sel": "#2E3148", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
    }.get(k, "#CDD6F4")
    def register_theme_refresh(cb): pass


class ErrorMapDialog(QDialog):

    def __init__(self, error_map: ErrorMapService, parent=None):
        super().__init__(parent)
        self._em = error_map
        self.setWindowTitle(tr("Карта ошибок — AI Code Sherlock"))
        self.setMinimumSize(900, 580)
        self.resize(1050, 660)
        self.setModal(True)
        self._build_ui()
        self._refresh()
        register_listener(lambda lang: retranslate_widget(self))

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header + stats
        hdr = QHBoxLayout()
        title = QLabel(tr("🗂 Карта ошибок и решений"))
        title.setObjectName("titleLabel")
        hdr.addWidget(title)
        hdr.addStretch()

        self._lbl_stats = QLabel("...")
        self._lbl_stats.setObjectName("statusLabel")
        hdr.addWidget(self._lbl_stats)
        layout.addLayout(hdr)

        # Search + filter
        filter_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Поиск по ошибкам..."))
        self._search.textChanged.connect(self._refresh)
        filter_row.addWidget(self._search)

        self._cmb_status = QComboBox()
        self._cmb_status.addItems([tr("Все"), tr("Открытые"), tr("Решённые"), tr("Игнорируемые")])
        self._cmb_status.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self._cmb_status)
        layout.addLayout(filter_row)

        # Main tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_errors_tab(), tr("⚠️ Ошибки"))
        tabs.addTab(self._build_avoid_tab(), tr("🚫 Запрещённые подходы"))
        tabs.addTab(self._build_add_tab(), tr("➕ Добавить"))
        layout.addWidget(tabs, stretch=1)

        # Footer
        footer = QHBoxLayout()
        btn_clean = QPushButton(tr("🗑 Очистить решённые"))
        btn_clean.clicked.connect(self._clean_resolved)
        footer.addWidget(btn_clean)
        footer.addStretch()
        btn_close = QPushButton(tr("Закрыть"))
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

    # ── Errors Tab ─────────────────────────────────────────

    def _build_errors_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            [tr("Тип"), tr("Сообщение"), tr("Файл"), tr("Кол-во"), tr("Статус"), tr("Последний раз")]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setStyleSheet(
            f"QTableWidget {{background:{get_color('bg2')};border:none;gridline-color:{get_color('bd2')};}} "
            f"QTableWidget::item {{padding:4px 8px;}} "
            f"QTableWidget::item:selected {{background:{get_color('sel')};}} "
            f"QHeaderView::section {{background:{get_color('bg0')};border:none;"
            f"border-bottom:1px solid {get_color('bd2')};padding:6px 8px;"
            f"color:{get_color('tx2')};font-size:11px;}}"
        )
        self._table.currentCellChanged.connect(self._on_row_selected)
        splitter.addWidget(self._table)

        # Detail panel
        detail_w = QWidget()
        dl = QVBoxLayout(detail_w)
        dl.setContentsMargins(0, 4, 0, 0)

        detail_hdr = QHBoxLayout()
        lbl = QLabel(tr("ДЕТАЛИ"))
        lbl.setObjectName("sectionLabel")
        detail_hdr.addWidget(lbl)
        detail_hdr.addStretch()

        self._btn_resolve = QPushButton(tr("✓ Отметить решённой"))
        self._btn_resolve.setObjectName("successBtn")
        self._btn_resolve.setEnabled(False)
        self._btn_resolve.clicked.connect(self._resolve_selected)
        detail_hdr.addWidget(self._btn_resolve)

        self._btn_ignore = QPushButton(tr("Игнорировать"))
        self._btn_ignore.setEnabled(False)
        self._btn_ignore.clicked.connect(self._ignore_selected)
        detail_hdr.addWidget(self._btn_ignore)

        self._btn_add_avoid = QPushButton(tr("🚫 Добавить запрет"))
        self._btn_add_avoid.setEnabled(False)
        self._btn_add_avoid.clicked.connect(self._add_avoid_from_error)
        detail_hdr.addWidget(self._btn_add_avoid)

        dl.addLayout(detail_hdr)

        self._detail_view = QTextEdit()
        self._detail_view.setReadOnly(True)
        self._detail_view.setFont(QFont("JetBrains Mono,Consolas", 11))
        self._detail_view.setStyleSheet(f"background:{get_color('bg0')};border:none;color:{get_color('tx0')};")
        self._detail_view.setMaximumHeight(200)
        dl.addWidget(self._detail_view)
        splitter.addWidget(detail_w)

        splitter.setSizes([350, 200])
        layout.addWidget(splitter)
        return w

    # ── Avoid Tab ──────────────────────────────────────────

    def _build_avoid_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        self._avoid_list = QTableWidget(0, 3)
        self._avoid_list.setHorizontalHeaderLabels([tr("Плохой подход"), tr("Лучше делать"), tr("Контекст")])
        self._avoid_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._avoid_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._avoid_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._avoid_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._avoid_list.setStyleSheet(
            f"QTableWidget {{background:{get_color('bg2')};border:none;gridline-color:{get_color('bd2')};}} "
            f"QTableWidget::item {{padding:4px 8px;}} "
            f"QTableWidget::item:selected {{background:{get_color('sel')};}} "
            f"QHeaderView::section {{background:{get_color('bg0')};border:none;"
            f"border-bottom:1px solid {get_color('bd2')};padding:6px 8px;color:{get_color('tx2')};}}"
        )
        layout.addWidget(self._avoid_list)

        btn_row = QHBoxLayout()
        btn_del = QPushButton(tr("🗑 Удалить выбранный"))
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete_avoid)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    # ── Add Tab ────────────────────────────────────────────

    def _build_add_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        layout.addWidget(QLabel(tr("Добавить запрещённый подход вручную:")))

        self._fld_bad_desc = QLineEdit()
        self._fld_bad_desc.setPlaceholderText(tr("Описание плохого подхода..."))
        layout.addWidget(QLabel(tr("Плохой подход:")))
        layout.addWidget(self._fld_bad_desc)

        self._fld_better = QLineEdit()
        self._fld_better.setPlaceholderText(tr("Что делать вместо этого..."))
        layout.addWidget(QLabel(tr("Правильный подход:")))
        layout.addWidget(self._fld_better)

        self._fld_ctx = QLineEdit()
        self._fld_ctx.setPlaceholderText(tr("В каком контексте это произошло..."))
        layout.addWidget(QLabel(tr("Контекст (необязательно):")))
        layout.addWidget(self._fld_ctx)

        btn_add = QPushButton(tr("➕ Добавить запрет"))
        btn_add.setObjectName("primaryBtn")
        btn_add.clicked.connect(self._add_avoid_manual)
        layout.addWidget(btn_add)

        layout.addStretch()
        return w

    # ── Data Loading ───────────────────────────────────────

    def _refresh(self):
        stats = self._em.stats()
        self._lbl_stats.setText(
            f"{tr('Всего:')} {stats['total_errors']}  |  "
            f"{tr('Открытых:')} {stats['open']}  |  "
            f"{tr('Решённых:')} {stats['resolved']}  |  "
            f"{tr('Запретов:')} {stats['avoid_patterns']}"
        )
        self._fill_table()
        self._fill_avoid_table()

    def _fill_table(self):
        query = self._search.text().lower()
        status_filter = {0: None, 1: "open", 2: "resolved", 3: "ignored"}[
            self._cmb_status.currentIndex()
        ]

        records = self._em.all_records()
        if query:
            records = [r for r in records if query in r.error_message.lower()
                       or query in r.error_type.lower()]
        if status_filter:
            records = [r for r in records if r.status == status_filter]

        records.sort(key=lambda r: r.last_seen, reverse=True)

        self._table.setRowCount(len(records))
        status_colors = {
            "open":     get_color("warn"),
            "resolved": get_color("ok"),
            "ignored":  get_color("tx2"),
        }

        for row, rec in enumerate(records):
            self._table.setItem(row, 0, QTableWidgetItem(rec.error_type))
            self._table.setItem(row, 1, QTableWidgetItem(rec.error_message[:80]))
            self._table.setItem(row, 2, QTableWidgetItem(rec.file_path[-30:] if rec.file_path else ""))
            self._table.setItem(row, 3, QTableWidgetItem(str(rec.occurrences)))

            status_item = QTableWidgetItem(rec.status)
            color = status_colors.get(rec.status, get_color("tx0"))
            status_item.setForeground(QColor(color))
            self._table.setItem(row, 4, status_item)

            try:
                dt = datetime.fromisoformat(rec.last_seen)
                time_str = dt.strftime("%d.%m %H:%M")
            except Exception:
                time_str = rec.last_seen[:16]
            self._table.setItem(row, 5, QTableWidgetItem(time_str))

            # Store record ID in hidden column
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, rec.error_id)

    def _fill_avoid_table(self):
        patterns = self._em.get_avoid_patterns()
        self._avoid_list.setRowCount(len(patterns))
        for row, p in enumerate(patterns):
            self._avoid_list.setItem(row, 0, QTableWidgetItem(p.bad_approach[:80]))
            self._avoid_list.setItem(row, 1, QTableWidgetItem(p.better_approach[:80]))
            self._avoid_list.setItem(row, 2, QTableWidgetItem(p.error_context[:60]))
            self._avoid_list.item(row, 0).setData(Qt.ItemDataRole.UserRole, p.pattern_id)

    def _on_row_selected(self, row, *_):
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        error_id = item.data(Qt.ItemDataRole.UserRole)
        rec = next((r for r in self._em.all_records() if r.error_id == error_id), None)
        if not rec:
            return

        text = (
            f"ID:          {rec.error_id}\n"
            f"Тип:         {rec.error_type}\n"
            f"Сообщение:   {rec.error_message}\n"
            f"Файл:        {rec.file_path}\n"
            f"Строка:      {rec.line_number}\n"
            f"Кол-во:      {rec.occurrences}\n"
            f"Статус:      {rec.status}\n"
            f"Первый раз:  {rec.first_seen[:19]}\n"
            f"Последний:   {rec.last_seen[:19]}\n"
        )
        if rec.root_cause:
            text += f"\nПричина:\n{rec.root_cause}\n"
        if rec.solution:
            text += f"\nРешение:\n{rec.solution}\n"

        self._detail_view.setPlainText(text)
        self._btn_resolve.setEnabled(rec.status != "resolved")
        self._btn_ignore.setEnabled(rec.status == "open")
        self._btn_add_avoid.setEnabled(True)

    # ── Actions ────────────────────────────────────────────

    def _get_selected_error_id(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _resolve_selected(self):
        eid = self._get_selected_error_id()
        if not eid:
            return
        from PyQt6.QtWidgets import QInputDialog
        solution, ok = QInputDialog.getMultiLineText(
            self, tr("Отметить решённой"),
            tr("Опиши решение (необязательно):")
        )
        if ok:
            self._em.mark_resolved(eid, solution=solution)
            self._refresh()

    def _ignore_selected(self):
        eid = self._get_selected_error_id()
        if eid and eid in self._em._records:
            self._em._records[eid].status = "ignored"
            self._em._save()
            self._refresh()

    def _add_avoid_from_error(self):
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        eid = item.data(Qt.ItemDataRole.UserRole) if item else None
        rec = next((r for r in self._em.all_records() if r.error_id == eid), None)
        if not rec:
            return

        from PyQt6.QtWidgets import QInputDialog
        bad, ok1 = QInputDialog.getText(
            self, tr("Запрещённый подход"),
            tr("Что НЕ нужно делать?"),
            text=f"Пробовали решить {rec.error_type} через..."
        )
        if not ok1:
            return
        better, ok2 = QInputDialog.getText(
            self, tr("Лучший подход"),
            tr("Что нужно делать вместо этого?")
        )
        if ok2 and bad and better:
            self._em.add_avoid_pattern(
                description=f"Плохой подход для {rec.error_type}",
                error_context=rec.error_message[:200],
                bad_approach=bad,
                better_approach=better,
            )
            self._refresh()

    def _add_avoid_manual(self):
        bad = self._fld_bad_desc.text().strip()
        better = self._fld_better.text().strip()
        ctx = self._fld_ctx.text().strip()
        if not bad or not better:
            QMessageBox.warning(self, tr("Ошибка"), tr("Заполни оба поля."))
            return
        self._em.add_avoid_pattern(
            description=bad,
            error_context=ctx,
            bad_approach=bad,
            better_approach=better,
        )
        self._fld_bad_desc.clear()
        self._fld_better.clear()
        self._fld_ctx.clear()
        self._refresh()
        QMessageBox.information(self, tr("Добавлено"), tr("Запрещённый подход добавлен."))

    def _delete_avoid(self):
        row = self._avoid_list.currentRow()
        if row < 0:
            return
        item = self._avoid_list.item(row, 0)
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        self._em._avoid = [p for p in self._em._avoid if p.pattern_id != pid]
        self._em._save()
        self._refresh()

    def _clean_resolved(self):
        reply = QMessageBox.question(
            self, tr("Очистить"),
            tr("Удалить все решённые ошибки из базы?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._em._records = {
                k: v for k, v in self._em._records.items() if v.status != "resolved"
            }
            self._em._save()
            self._refresh()
