"""
Project Dashboard — окно управления проектами в стиле ZennoPoster.

Содержит:
  - Таблицу проектов с колонками (статус, имя, прогресс, успехи, потоки, метки...)
  - Боковое меню фильтрации (по статусу, меткам)
  - Диалог запуска проекта (потоки, попытки, режим, расписание, bottleneck)
  - Кнопки управления (Старт/Стоп/Пауза/+N/∞)
  - Глобальную статистику потоков
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QBrush, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QFrame, QToolBar,
    QLineEdit, QMessageBox, QMenu, QApplication,
    QTabWidget, QTextEdit, QScrollArea, QSizePolicy,
    QComboBox, QSpinBox, QCheckBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QFormLayout, QGroupBox,
    QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QProgressBar, QDateTimeEdit,
    QTreeWidget, QTreeWidgetItem, QInputDialog, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem
)
try:
    from ui.i18n import tr as _dashboard_tr
except ImportError:
    def _dashboard_tr(s): return s

from constructor.project_manager import (
    ProjectExecutionManager, ProjectEntry, ProjectStatus,
    ThreadMode, StopCondition
)

def _tr(s):
    return _dashboard_tr(s)

# ══════════════════════════════════════════════════════════
#  СТИЛИ
# ══════════════════════════════════════════════════════════

def _make_dashboard_style() -> str:
    try:
        from ui.theme_manager import get_color
    except ImportError:
        def get_color(k):
            return {
                "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722", "bg3": "#1A1D2E",
                "bd": "#2E3148", "bd2": "#1E2030",
                "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
                "ac": "#7AA2F7", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
            }.get(k, "#CDD6F4")
    return f"""
QWidget {{
    background-color: {get_color('bg1')};
    color: {get_color('tx0')};
    font-family: 'Segoe UI', 'Noto Sans', sans-serif;
}}
QTableWidget {{
    background-color: {get_color('bg1')};
    alternate-background-color: {get_color('bg2')};
    gridline-color: {get_color('bd')};
    border: 1px solid {get_color('bd')};
    border-radius: 6px;
    selection-background-color: {get_color('bg3')};
    selection-color: {get_color('tx0')};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {get_color('bd')};
}}
QHeaderView::section {{
    background-color: {get_color('bg2')};
    color: {get_color('ac')};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {get_color('bd')};
    border-bottom: 2px solid {get_color('ac')};
    font-weight: bold;
    font-size: 11px;
}}
QPushButton {{
    background-color: {get_color('bg3')};
    color: {get_color('tx0')};
    border: 1px solid {get_color('bd')};
    border-radius: 5px;
    padding: 5px 12px;
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: {get_color('bd')};
    border-color: {get_color('ac')};
}}
QPushButton:pressed {{
    background-color: {get_color('ac')};
    color: {get_color('bg1')};
}}
QPushButton:disabled {{
    background-color: {get_color('bg2')};
    color: {get_color('tx2')};
}}
QGroupBox {{
    border: 1px solid {get_color('bd')};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 18px;
    font-weight: bold;
    color: {get_color('ac')};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QDateTimeEdit {{
    background-color: {get_color('bg3')};
    color: {get_color('tx0')};
    border: 1px solid {get_color('bd')};
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 22px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{
    border-color: {get_color('ac')};
}}
QProgressBar {{
    border: 1px solid {get_color('bd')};
    border-radius: 4px;
    text-align: center;
    background-color: {get_color('bg2')};
    color: {get_color('tx0')};
    font-size: 10px;
    min-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {get_color('ac')};
    border-radius: 3px;
}}
QListWidget {{
    background-color: {get_color('bg1')};
    border: 1px solid {get_color('bd')};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {get_color('bg2')};
}}
QListWidget::item:selected {{
    background-color: {get_color('bg3')};
    color: {get_color('ac')};
}}
QListWidget::item:hover {{
    background-color: {get_color('bg2')};
}}
QTextEdit {{
    background-color: {get_color('bg1')};
    color: {get_color('tx1')};
    border: 1px solid {get_color('bd')};
    border-radius: 6px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
}}
QSplitter::handle {{
    background-color: {get_color('bd')};
}}
QToolBar {{
    background-color: {get_color('bg2')};
    border-bottom: 1px solid {get_color('bd')};
    spacing: 4px;
    padding: 2px;
}}
QCheckBox {{
    spacing: 6px;
    color: {get_color('tx0')};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {get_color('bd')};
    border-radius: 3px;
    background-color: {get_color('bg3')};
}}
QCheckBox::indicator:checked {{
    background-color: {get_color('ac')};
    border-color: {get_color('ac')};
}}
"""

_DASHBOARD_STYLE = _make_dashboard_style()

# Цвета статусов
_STATUS_COLORS = {
    ProjectStatus.STOPPED:   "#565f89",
    ProjectStatus.QUEUED:    "#e0af68",
    ProjectStatus.RUNNING:   "#9ece6a",
    ProjectStatus.PAUSED:    "#e0af68",
    ProjectStatus.COMPLETED: "#7aa2f7",
    ProjectStatus.SCHEDULED: "#bb9af7",
    ProjectStatus.ERROR:     "#f7768e",
}

_STATUS_ICONS = {
    ProjectStatus.STOPPED:   "⏹",
    ProjectStatus.QUEUED:    "⏳",
    ProjectStatus.RUNNING:   "▶️",
    ProjectStatus.PAUSED:    "⏸",
    ProjectStatus.COMPLETED: "✅",
    ProjectStatus.SCHEDULED: "📅",
    ProjectStatus.ERROR:     "❌",
}

def _get_status_labels():
    return {
        ProjectStatus.STOPPED:   _tr("Остановлен"),
        ProjectStatus.QUEUED:    _tr("В очереди"),
        ProjectStatus.RUNNING:   _tr("Выполняется"),
        ProjectStatus.PAUSED:    _tr("Пауза"),
        ProjectStatus.COMPLETED: _tr("Выполнен"),
        ProjectStatus.SCHEDULED: _tr("Запланирован"),
        ProjectStatus.ERROR:     _tr("Ошибка"),
    }
_STATUS_LABELS = _get_status_labels()


# ══════════════════════════════════════════════════════════
#  ДИАЛОГ ЗАПУСКА ПРОЕКТА
# ══════════════════════════════════════════════════════════

class ProjectLaunchDialog(QDialog):
    """
    Диалог настроек запуска проекта.
    Открывается при нажатии "Запустить" — позволяет задать
    все параметры выполнения перед стартом.
    """

    def __init__(self, entry: ProjectEntry, 
                 available_snippets: list[tuple[str, str]] = None,
                 parent=None):
        super().__init__(parent)
        try:
            from ui.i18n import tr as _tr
        except ImportError:
            _tr = lambda s: s
        self.setWindowTitle(f"{_tr('▶️ Запуск проекта')}: {entry.name}")
        self.resize(560, 640)
        self.setStyleSheet(_DASHBOARD_STYLE)
        self._entry = entry
        self._snippets = available_snippets or []
        self._build_ui()
        self._load_from_entry()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # ── Вкладка: Потоки ──────────────────────────────────
        w_threads = QWidget()
        fl = QFormLayout(w_threads)
        fl.setSpacing(10)
        
        self._spn_threads = QSpinBox()
        self._spn_threads.setRange(1, 100)
        self._spn_threads.setToolTip(
            _tr("Сколько потоков одновременно выполняют этот проект.\n"
            "Каждый поток — изолированный экземпляр workflow.")
        )
        fl.addRow(_tr("Количество потоков:"), self._spn_threads)
        
        self._spn_executions = QSpinBox()
        self._spn_executions.setRange(-1, 999999)
        self._spn_executions.setSpecialValueText(_tr("∞ Бесконечно"))
        self._spn_executions.setToolTip(
            _tr("Сколько раз выполнить проект.\n"
            "-1 = бесконечно (до ручной остановки).")
        )
        fl.addRow(_tr("Количество выполнений:"), self._spn_executions)
        
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItem(_tr("Последовательно"), ThreadMode.SEQUENTIAL.value)
        self._cmb_mode.addItem(_tr("Параллельно"), ThreadMode.PARALLEL.value)
        self._cmb_mode.addItem(_tr("С семафором (bottleneck)"), ThreadMode.SEMAPHORE_WAIT.value)
        self._cmb_mode.setToolTip(
            _tr("Последовательно: потоки ждут друг друга.\n"
            "Параллельно: все потоки работают одновременно.\n"
            "С семафором: ресурсоёмкий сниппет ограничен лимитом.")
        )
        fl.addRow(_tr("Режим потоков:"), self._cmb_mode)
        
        self._cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        
        # Bottleneck группа
        self._grp_bottleneck = QGroupBox(_tr("⚠️ Узкое горлышко (Bottleneck)"))
        bl = QFormLayout(self._grp_bottleneck)
        
        self._cmb_snippet = QComboBox()
        self._cmb_snippet.addItem(_tr("(не выбран)"), "")
        for sid, sname in self._snippets:
            self._cmb_snippet.addItem(f"{sname} ({sid})", sid)
        bl.addRow(_tr("Триггерный сниппет:"), self._cmb_snippet)
        
        self._spn_bn_limit = QSpinBox()
        self._spn_bn_limit.setRange(1, 50)
        self._spn_bn_limit.setToolTip(
            _tr("Сколько потоков могут одновременно выполнять\n"
            "этот ресурсоёмкий сниппет. Остальные ждут.")
        )
        bl.addRow(_tr("Макс. одновременно:"), self._spn_bn_limit)
        
        self._grp_bottleneck.setVisible(False)
        fl.addRow(self._grp_bottleneck)
        
        self._spn_priority = QSpinBox()
        self._spn_priority.setRange(1, 10)
        self._spn_priority.setValue(5)
        self._spn_priority.setToolTip(_tr("1 = минимальный, 10 = максимальный приоритет"))
        fl.addRow(_tr("Приоритет:"), self._spn_priority)

        self._chk_close_browser = QCheckBox(_tr("Закрывать браузер по завершении"))
        self._chk_close_browser.setChecked(True)
        self._chk_close_browser.setToolTip(
            _tr("Если включено — все браузеры проекта будут закрыты\n"
            "автоматически после завершения workflow.\n"
            "Выключите, если нужно оставить браузер открытым.")
        )
        fl.addRow(_tr("🌐 Браузер:"), self._chk_close_browser)

        tabs.addTab(w_threads, _tr("🧵 Потоки"))
        
        # ── Вкладка: Расписание ──────────────────────────────
        w_schedule = QWidget()
        sl = QFormLayout(w_schedule)
        sl.setSpacing(10)
        
        self._chk_schedule = QCheckBox(_tr("Включить расписание"))
        sl.addRow(self._chk_schedule)
        
        self._grp_schedule = QGroupBox(_tr("📅 Настройки расписания"))
        schl = QFormLayout(self._grp_schedule)
        
        self._dte_next_run = QDateTimeEdit()
        self._dte_next_run.setCalendarPopup(True)
        self._dte_next_run.setDateTime(
            datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
        )
        schl.addRow(_tr("Первый запуск:"), self._dte_next_run)
        
        self._cmb_schedule_type = QComboBox()
        self._cmb_schedule_type.addItem(_tr("Однократно"), "once")
        self._cmb_schedule_type.addItem(_tr("Каждые N минут"), "interval")
        self._cmb_schedule_type.addItem(_tr("Ежедневно в указанное время"), "daily")
        schl.addRow(_tr("Тип:"), self._cmb_schedule_type)
        
        self._spn_interval = QSpinBox()
        self._spn_interval.setRange(1, 1440)
        self._spn_interval.setValue(30)
        self._spn_interval.setSuffix(_tr(" мин"))
        schl.addRow(_tr("Интервал:"), self._spn_interval)
        
        self._chk_repeat = QCheckBox(_tr("Повторять"))
        schl.addRow(self._chk_repeat)
        
        self._grp_schedule.setEnabled(False)
        sl.addRow(self._grp_schedule)
        
        self._chk_schedule.toggled.connect(self._grp_schedule.setEnabled)
        
        tabs.addTab(w_schedule, _tr("📅 Расписание"))
        
        # ── Вкладка: Остановка ───────────────────────────────
        w_stop = QWidget()
        stl = QFormLayout(w_stop)
        stl.setSpacing(10)
        
        self._cmb_stop = QComboBox()
        self._cmb_stop.addItem(_tr("Нет условия"), StopCondition.NONE.value)
        self._cmb_stop.addItem(_tr("При первой ошибке"), StopCondition.ON_FIRST_ERROR.value)
        self._cmb_stop.addItem(_tr("После N ошибок подряд"), StopCondition.ON_N_ERRORS.value)
        self._cmb_stop.addItem(_tr("После N успехов"), StopCondition.ON_SUCCESS_COUNT.value)
        self._cmb_stop.addItem(_tr("По таймауту (секунды)"), StopCondition.ON_TIME_LIMIT.value)
        stl.addRow(_tr("Условие остановки:"), self._cmb_stop)
        
        self._spn_stop_val = QSpinBox()
        self._spn_stop_val.setRange(1, 999999)
        stl.addRow(_tr("Значение:"), self._spn_stop_val)
        
        tabs.addTab(w_stop, _tr("🛑 Остановка"))
        
        # ── Вкладка: Метки ───────────────────────────────────
        w_labels = QWidget()
        ll = QVBoxLayout(w_labels)
        ll.addWidget(QLabel(_tr("Метки (через запятую):")))
        self._edt_labels = QLineEdit()
        self._edt_labels.setPlaceholderText("бот, парсер, регистрация...")
        ll.addWidget(self._edt_labels)
        ll.addStretch()
        
        tabs.addTab(w_labels, _tr("🏷 Метки"))
        
        layout.addWidget(tabs)
        
        # ── Кнопки ───────────────────────────────────────────
        bb = QDialogButtonBox()
        self._btn_start = QPushButton(_tr("▶️  Запустить"))
        self._btn_start.setStyleSheet(
            "QPushButton { background-color: #3d5940; color: #9ece6a; font-weight: bold; }"
            "QPushButton:hover { background-color: #4d6950; }"
        )
        self._btn_start.clicked.connect(self.accept)
        
        btn_cancel = QPushButton(_tr("Отмена"))
        btn_cancel.clicked.connect(self.reject)
        
        bb.addButton(self._btn_start, QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(bb)
        
    def _on_mode_changed(self, idx):
        mode = self._cmb_mode.currentData()
        self._grp_bottleneck.setVisible(mode == ThreadMode.SEMAPHORE_WAIT.value)
    
    def _load_from_entry(self):
        e = self._entry
        self._spn_threads.setValue(e.max_threads)
        wf = getattr(e, 'workflow', None)
        if wf is not None and hasattr(self, '_chk_close_browser'):
            self._chk_close_browser.setChecked(getattr(wf, 'close_browser_on_finish', True))
        self._spn_executions.setValue(e.total_executions)
        idx = self._cmb_mode.findData(e.thread_mode.value)
        if idx >= 0:
            self._cmb_mode.setCurrentIndex(idx)
        self._spn_priority.setValue(e.priority)
        
        if e.bottleneck_snippet_id:
            idx = self._cmb_snippet.findData(e.bottleneck_snippet_id)
            if idx >= 0:
                self._cmb_snippet.setCurrentIndex(idx)
        self._spn_bn_limit.setValue(e.bottleneck_max_concurrent)
        
        self._chk_schedule.setChecked(e.schedule_enabled)
        self._chk_repeat.setChecked(e.schedule_repeat)
        
        sidx = self._cmb_stop.findData(e.stop_condition.value)
        if sidx >= 0:
            self._cmb_stop.setCurrentIndex(sidx)
        self._spn_stop_val.setValue(max(1, e.stop_value))
        
        self._edt_labels.setText(", ".join(e.labels))
    
    def apply_to_entry(self) -> ProjectEntry:
        """Применить настройки из UI к ProjectEntry."""
        e = self._entry
        e.max_threads = self._spn_threads.value()
        wf = getattr(e, 'workflow', None)
        if wf is not None and hasattr(self, '_chk_close_browser'):
            wf.close_browser_on_finish = self._chk_close_browser.isChecked()
        e.total_executions = self._spn_executions.value()
        e.thread_mode = ThreadMode(self._cmb_mode.currentData())
        e.priority = self._spn_priority.value()
        
        e.bottleneck_snippet_id = self._cmb_snippet.currentData() or ""
        e.bottleneck_max_concurrent = self._spn_bn_limit.value()
        
        e.schedule_enabled = self._chk_schedule.isChecked()
        e.schedule_repeat = self._chk_repeat.isChecked()
        if e.schedule_enabled:
            e.schedule_next_run = self._dte_next_run.dateTime().toPyDateTime().isoformat()
            stype = self._cmb_schedule_type.currentData()
            if stype == "interval":
                e.schedule_cron = f"*/{self._spn_interval.value()}"
            elif stype == "daily":
                dt = self._dte_next_run.dateTime().toPyDateTime()
                e.schedule_cron = f"{dt.hour:02d}:{dt.minute:02d}"
        
        e.stop_condition = StopCondition(self._cmb_stop.currentData())
        e.stop_value = self._spn_stop_val.value()
        
        raw_labels = self._edt_labels.text()
        e.labels = [l.strip() for l in raw_labels.split(",") if l.strip()]
        
        return e


# ══════════════════════════════════════════════════════════
#  БОКОВАЯ ПАНЕЛЬ ФИЛЬТРАЦИИ
# ══════════════════════════════════════════════════════════

class SideFilterPanel(QWidget):
    """Боковая панель как в ZennoPoster: фильтрация по статусу и меткам."""
    
    filter_changed = pyqtSignal(str, str)  # (filter_type, filter_value)
    # filter_type: "all", "status", "label"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self._build_ui()
        try:
            from ui.theme_manager import register_theme_refresh
            register_theme_refresh(self._refresh_theme)
        except ImportError:
            pass
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        # ── Шапка с потоками ─────────────────────
        header = QFrame()
        try:
            from ui.theme_manager import get_color as _gc
        except ImportError:
            def _gc(k): return {"bg2": "#24283b"}.get(k, "#24283b")
        header.setStyleSheet(
            f"QFrame {{ background-color: {_gc('bg2')}; border-radius: 6px; padding: 8px; }}"
        )
        hl = QVBoxLayout(header)
        hl.setSpacing(4)
        
        self._lbl_threads = QLabel(_tr("Потоки") + ": 0")
        self._lbl_threads.setStyleSheet(f"color: {_gc('ok')}; font-weight: bold; font-size: 13px;")
        hl.addWidget(self._lbl_threads)
        
        self._lbl_max = QLabel(_tr("Максимум") + ": 10")
        self._lbl_max.setStyleSheet(f"color: {_gc('tx2')}; font-size: 11px;")
        hl.addWidget(self._lbl_max)
        
        self._progress_threads = QProgressBar()
        self._progress_threads.setRange(0, 10)
        self._progress_threads.setValue(0)
        self._progress_threads.setTextVisible(False)
        self._progress_threads.setFixedHeight(6)
        hl.addWidget(self._progress_threads)
        
        layout.addWidget(header)
        
        # ── Задания ──────────────────────────────
        layout.addWidget(QLabel(""))
        self._lbl_tasks = QLabel(f"  📋 {_tr('Задания')}")
        self._lbl_tasks.setStyleSheet("color: #7aa2f7; font-weight: bold; font-size: 12px;")
        layout.addWidget(self._lbl_tasks)
        
        self._list_statuses = QListWidget()
        self._list_statuses.setFixedHeight(180)
        
        self._status_items: dict[str, QListWidgetItem] = {}
        
        # "Все"
        item_all = QListWidgetItem(f"📋  {_tr('Все')} (0)")
        item_all.setData(Qt.ItemDataRole.UserRole, ("all", "all"))
        self._list_statuses.addItem(item_all)
        self._status_items["all"] = item_all
        
        for status in [ProjectStatus.RUNNING, ProjectStatus.COMPLETED,
                       ProjectStatus.STOPPED, ProjectStatus.SCHEDULED,
                       ProjectStatus.PAUSED, ProjectStatus.ERROR]:
            icon = _STATUS_ICONS.get(status, "")
            label = _get_status_labels().get(status, status.value)
            item = QListWidgetItem(f"{icon}  {label} (0)")
            item.setData(Qt.ItemDataRole.UserRole, ("status", status.value))
            color = _STATUS_COLORS.get(status, "#c0caf5")
            item.setForeground(QColor(color))
            self._list_statuses.addItem(item)
            self._status_items[status.value] = item
        
        self._list_statuses.currentItemChanged.connect(self._on_status_clicked)
        layout.addWidget(self._list_statuses)
        
        # ── Метки ────────────────────────────────
        self._lbl_labels = QLabel(f"  🏷 {_tr('Метки')}")
        self._lbl_labels.setStyleSheet("color: #7aa2f7; font-weight: bold; font-size: 12px;")
        layout.addWidget(self._lbl_labels)
        
        self._list_labels = QListWidget()
        self._list_labels.currentItemChanged.connect(self._on_label_clicked)
        layout.addWidget(self._list_labels)
        
        layout.addStretch()
    
    def _refresh_theme(self):
        """Применить текущую тему динамически."""
        try:
            from ui.theme_manager import get_color
        except ImportError:
            def get_color(k): return {
                "bg2": "#24283b", "ok": "#9ece6a", "tx2": "#565f89", "ac": "#7aa2f7"
            }.get(k, "#c0caf5")
        self.setStyleSheet(_make_dashboard_style())
        if hasattr(self, '_lbl_threads'):
            # Сохраняем текущий цвет (зависит от загрузки)
            current_ss = self._lbl_threads.styleSheet()
            if "f7768e" in current_ss or "err" in current_ss:
                col = get_color("err")
            elif "e0af68" in current_ss or "warn" in current_ss:
                col = get_color("warn")
            else:
                col = get_color("ok")
            self._lbl_threads.setStyleSheet(
                f"color: {col}; font-weight: bold; font-size: 13px;"
            )
        if hasattr(self, '_lbl_max'):
            self._lbl_max.setStyleSheet(
                f"color: {get_color('tx2')}; font-size: 11px;"
            )
        # Перестраиваем шапку
        try:
            from PyQt6.QtWidgets import QFrame
            for child in self.findChildren(QFrame):
                if child.objectName() == "" and child.layout() is not None:
                    child.setStyleSheet(
                        f"QFrame {{ background-color: {get_color('bg2')}; "
                        f"border-radius: 6px; padding: 8px; }}"
                    )
                    break
        except Exception:
            pass
        for lbl_name in ('_lbl_tasks', '_lbl_labels'):
            lbl = getattr(self, lbl_name, None)
            if lbl:
                lbl.setStyleSheet(
                    f"color: {get_color('ac')}; font-weight: bold; font-size: 12px;"
                )
    
    def _on_status_clicked(self, item: QListWidgetItem, prev):
        if not item:
            return
        ftype, fval = item.data(Qt.ItemDataRole.UserRole)
        self.filter_changed.emit(ftype, fval)
    
    def _on_label_clicked(self, item: QListWidgetItem, prev):
        if not item:
            return
        label = item.data(Qt.ItemDataRole.UserRole)
        self.filter_changed.emit("label", label)
    
    def update_counts(self, projects: list[ProjectEntry]):
        """Обновить счётчики в списках."""
        # Статусы
        counts = {}
        for p in projects:
            counts[p.status.value] = counts.get(p.status.value, 0) + 1
        
        total = len(projects)
        self._status_items["all"].setText(f"📋  {_dashboard_tr('Все')} ({total})")
        
        for status in ProjectStatus:
            if status.value in self._status_items:
                icon = _STATUS_ICONS.get(status, "")
                label = _get_status_labels().get(status, status.value)
                cnt = counts.get(status.value, 0)
                self._status_items[status.value].setText(f"{icon}  {label} ({cnt})")
        
        # Метки
        label_counts: dict[str, int] = {}
        for p in projects:
            for lbl in p.labels:
                label_counts[lbl] = label_counts.get(lbl, 0) + 1
        
        self._list_labels.clear()
        for lbl, cnt in sorted(label_counts.items()):
            item = QListWidgetItem(f"🏷 {lbl} ({cnt})")
            item.setData(Qt.ItemDataRole.UserRole, lbl)
            self._list_labels.addItem(item)
    
    def update_thread_stats(self, active: int, maximum: int):
        """Обновить отображение потоков."""
        self._lbl_threads.setText(f"{_dashboard_tr('Потоки')}: {active}")
        self._lbl_max.setText(f"{_dashboard_tr('Максимум')}: {maximum}")
        self._progress_threads.setMaximum(max(1, maximum))
        self._progress_threads.setValue(active)
        
        try:
            from ui.theme_manager import get_color as _gc
        except ImportError:
            def _gc(k): return {"err": "#f7768e", "warn": "#e0af68", "ok": "#9ece6a"}.get(k, "#9ece6a")
        
        if active >= maximum:
            self._lbl_threads.setStyleSheet(f"color: {_gc('err')}; font-weight: bold; font-size: 13px;")
        elif active > maximum * 0.7:
            self._lbl_threads.setStyleSheet(f"color: {_gc('warn')}; font-weight: bold; font-size: 13px;")
        else:
            self._lbl_threads.setStyleSheet(f"color: {_gc('ok')}; font-weight: bold; font-size: 13px;")


# ══════════════════════════════════════════════════════════
#  ТАБЛИЦА ПРОЕКТОВ
# ══════════════════════════════════════════════════════════

# Индексы колонок
COL_STATUS     = 0
COL_NAME       = 1
COL_PROGRESS   = 2
COL_SUCCESS    = 3
COL_FAILURES   = 4
COL_ATTEMPTS   = 5
COL_THREADS    = 6
COL_MAX_THR    = 7
COL_PRIORITY   = 8
COL_LABELS     = 9
COL_NEXT_RUN   = 10
COL_MODE       = 11

def _get_column_headers():
    return [
        _tr("Статус"), _tr("Имя"), _tr("Прогресс"),
        _tr("Успехи"), _tr("Неуспехи"), _tr("Попытки"),
        _tr("Потоки"), _tr("Макс. потоков"), _tr("Приоритет"),
        _tr("Метки"), _tr("Следующий запуск"), _tr("Режим"),
    ]
_COLUMN_HEADERS = _get_column_headers()


class ProgressBarDelegate(QStyledItemDelegate):
    """Делегат для отрисовки прогресс-бара в ячейке таблицы."""
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Guard: не рисуем если painter неактивен
        if not painter.isActive():
            return
        progress = index.data(Qt.ItemDataRole.UserRole)
        if progress is None:
            super().paint(painter, option, index)
            return
        
        painter.save()
        try:
            rect = option.rect.adjusted(4, 4, -4, -4)
            if rect.width() <= 0 or rect.height() <= 0:
                return
            painter.setPen(Qt.PenStyle.NoPen)
            try:
                from ui.theme_manager import get_color as _gc
            except ImportError:
                def _gc(k): return {
                    "bg2": "#1e2030", "ok": "#9ece6a", "ac": "#7aa2f7", "tx0": "#c0caf5"
                }.get(k, "#c0caf5")
            painter.setBrush(QColor(_gc("bg2")))
            painter.drawRoundedRect(rect, 3, 3)
            
            if progress > 0:
                fill_rect = rect.adjusted(1, 1, -1, -1)
                fill_rect.setWidth(int(fill_rect.width() * min(100, progress) / 100))
                color = _gc("ok") if progress >= 100 else _gc("ac")
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(fill_rect, 2, 2)
            
            painter.setPen(QColor(_gc("tx0")))
            text = f"{progress:.0f}%" if progress >= 0 else "∞"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        finally:
            painter.restore()


# ══════════════════════════════════════════════════════════
#  ГЛАВНОЕ ОКНО — PROJECT DASHBOARD
# ══════════════════════════════════════════════════════════

class ProjectDashboard(QWidget):
    """
    Главное окно управления проектами в стиле ZennoPoster.
    
    Может использоваться как:
    - Отдельное окно (QWidget + show())
    - Вкладка в главном окне конструктора
    """
    
    # Сигнал для открытия проекта в редакторе
    open_project_requested = pyqtSignal(str)  # project_id
    
    def __init__(self, manager: ProjectExecutionManager = None,
                 constructor_window=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_DASHBOARD_STYLE)
        try:
            from ui.i18n import tr as _tr
        except ImportError:
            _tr = lambda s: s
        self.setWindowTitle(_tr("📊 Менеджер проектов — AI Code Sherlock"))
        self.resize(1200, 700)
        
        self._manager = manager or ProjectExecutionManager.instance()
        self._constructor = constructor_window
        self._current_filter = ("all", "all")
        
        self._build_ui()
        self._connect_signals()
        
        # Обновление таблицы
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start(2000)  # 2 сек достаточно, 1 сек вызывает лаги
        
        # ═══ Загружаем сохранённое состояние менеджера ═══
        self._manager.load_state()
        # Загружаем workflow для проектов, загруженных из файлов
        self._restore_workflows_from_files()
        
        self._refresh_table()
        try:
            from ui.theme_manager import register_theme_refresh
            register_theme_refresh(self._refresh_theme)
        except ImportError:
            pass
    
    def _refresh_theme(self):
        """Динамическое обновление темы без перезапуска."""
        try:
            from ui.theme_manager import get_color
        except ImportError:
            def get_color(k): return {
                "ok": "#9ece6a", "err": "#f7768e", "warn": "#e0af68",
                "ac": "#7aa2f7", "bg3": "#1A1D2E", "tx0": "#c0caf5",
            }.get(k, "#c0caf5")
        # Главный стиль окна
        self.setStyleSheet(_make_dashboard_style())
        # Кнопки тулбара
        if hasattr(self, '_btn_start'):
            self._btn_start.setStyleSheet(
                f"QPushButton {{ color: {get_color('ok')}; }}"
                f"QPushButton:hover {{ background: {get_color('bg3')}; }}"
            )
        if hasattr(self, '_btn_stop'):
            self._btn_stop.setStyleSheet(
                f"QPushButton {{ color: {get_color('err')}; }}"
                f"QPushButton:hover {{ background: {get_color('bg3')}; }}"
            )
        # Кнопка ∞
        if hasattr(self, '_btn_inf'):
            self._btn_inf.setStyleSheet(
                f"QPushButton {{ font-size: 16px; color: {get_color('warn')}; }}"
            )

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ── Левая панель: фильтры ────────────────────────────
        self._side_panel = SideFilterPanel()
        self._side_panel.setMinimumWidth(160)
        self._side_panel.setMaximumWidth(320)
        splitter.addWidget(self._side_panel)
        
        # ── Правая панель: таблица + лог ─────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        
        # Тулбар
        self._toolbar = QToolBar()
        self._toolbar.setIconSize(QSize(16, 16))
        
        self._btn_add = QPushButton("➕ " + _tr("Добавить"))
        self._btn_add.clicked.connect(self._show_add_menu)
        self._toolbar.addWidget(self._btn_add)
        
        self._btn_remove = QPushButton("🗑 " + _tr("Удалить"))
        self._btn_remove.clicked.connect(self._remove_selected)
        self._toolbar.addWidget(self._btn_remove)
        
        self._toolbar.addSeparator()
        
        try:
            from ui.theme_manager import get_color as _gc
        except ImportError:
            def _gc(k): return {"ok": "#9ece6a", "err": "#f7768e", "warn": "#e0af68", "ac": "#7aa2f7", "bg3": "#1A1D2E"}.get(k, "#c0caf5")
        self._btn_start = QPushButton("▶️ " + _tr("Запустить"))
        self._btn_start.setStyleSheet(
            f"QPushButton {{ color: {_gc('ok')}; }} QPushButton:hover {{ background: {_gc('bg3')}; }}"
        )
        self._btn_start.clicked.connect(self._start_selected)
        self._toolbar.addWidget(self._btn_start)
        
        self._btn_stop = QPushButton("⏹ " + _tr("Остановить"))
        self._btn_stop.setStyleSheet(
            f"QPushButton {{ color: {_gc('err')}; }} QPushButton:hover {{ background: {_gc('bg3')}; }}"
        )
        self._btn_stop.clicked.connect(self._stop_selected)
        self._toolbar.addWidget(self._btn_stop)
        
        self._btn_pause = QPushButton("⏸ " + _tr("Пауза"))
        self._btn_pause.clicked.connect(self._pause_selected)
        self._toolbar.addWidget(self._btn_pause)
        
        self._toolbar.addSeparator()
        
        # Кнопки добавления попыток
        for n in [1, 5, 10, 50]:
            btn = QPushButton(f"+{n}")
            btn.setFixedWidth(36)
            btn.setToolTip(f"{_tr('Добавить попытки')}: {n}")
            btn.clicked.connect(lambda checked, count=n: self._add_executions(count))
            self._toolbar.addWidget(btn)
        
        self._btn_inf = QPushButton("∞")
        self._btn_inf.setFixedWidth(30)
        self._btn_inf.setToolTip(_tr("Бесконечное выполнение"))
        self._btn_inf.setStyleSheet("QPushButton { font-size: 16px; color: #bb9af7; }")
        self._btn_inf.clicked.connect(lambda: self._add_executions(-1))
        self._toolbar.addWidget(self._btn_inf)
        
        self._toolbar.addSeparator()
        
        self._btn_open = QPushButton("📂 " + _tr("Открыть в редакторе"))
        self._btn_open.clicked.connect(self._open_in_editor)
        self._toolbar.addWidget(self._btn_open)
        
        rl.addWidget(self._toolbar)
        
        # Разделитель: таблица + лог
        vsplitter = QSplitter(Qt.Orientation.Vertical)
        
        # Таблица проектов
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMN_HEADERS))
        self._table.setHorizontalHeaderLabels(_COLUMN_HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.setItemDelegateForColumn(COL_PROGRESS, ProgressBarDelegate())
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setSortingEnabled(True)
        
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(COL_PROGRESS, 100)
        
        vsplitter.addWidget(self._table)
        
        # Лог
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(200)
        self._log.setPlaceholderText("Лог выполнения...")
        vsplitter.addWidget(self._log)
        
        vsplitter.setStretchFactor(0, 3)
        vsplitter.setStretchFactor(1, 1)
        
        rl.addWidget(vsplitter)
        
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)   # левая панель — фиксированная
        splitter.setStretchFactor(1, 1)   # правая — растягивается
        splitter.setSizes([200, 1000])
        
        main_layout.addWidget(splitter)
    
    def _connect_signals(self):
        m = self._manager
        m.signals.project_added.connect(self._refresh_table)
        m.signals.project_removed.connect(self._refresh_table)
        m.signals.project_updated.connect(self._on_project_updated)
        m.signals.stats_updated.connect(self._side_panel.update_thread_stats)
        m.signals.log.connect(self._on_log)
        m.signals.global_log.connect(self._on_global_log)
        
        self._side_panel.filter_changed.connect(self._on_filter_changed)
    
    # ── Обновление таблицы ───────────────────────────────────
    
    def _refresh_table(self, *_args):
        """Полное обновление таблицы."""
        # Guard: не обновляем если виджет скрыт или не инициализирован
        if not self.isVisible():
            return
        projects = self._get_filtered_projects()
        
        self._table.setSortingEnabled(False)
        self._table.blockSignals(True)
        self._table.setRowCount(len(projects))
        
        for row, entry in enumerate(projects):
            self._populate_row(row, entry)
        
        self._table.blockSignals(False)
        self._table.setSortingEnabled(True)
        self._side_panel.update_counts(self._manager.get_all_projects())
    
    def _populate_row(self, row: int, entry: ProjectEntry):
        """Заполнить одну строку таблицы."""
        # Статус
        status_text = f"{_STATUS_ICONS.get(entry.status, '')} {_STATUS_LABELS.get(entry.status, entry.status.value)}"
        item = QTableWidgetItem(status_text)
        item.setData(Qt.ItemDataRole.UserRole, entry.project_id)
        color = _STATUS_COLORS.get(entry.status, "#c0caf5")
        item.setForeground(QColor(color))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_STATUS, item)
        
        # Имя
        item = QTableWidgetItem(entry.name)
        item.setData(Qt.ItemDataRole.UserRole, entry.project_id)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_NAME, item)
        
        # Прогресс
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, entry.progress)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_PROGRESS, item)
        
        # Успехи
        item = QTableWidgetItem(str(entry.completed_executions))
        item.setForeground(QColor("#9ece6a"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_SUCCESS, item)
        
        # Неуспехи
        item = QTableWidgetItem(str(entry.failed_executions))
        item.setForeground(QColor("#f7768e") if entry.failed_executions > 0 else QColor("#565f89"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_FAILURES, item)
        
        # Попытки
        total = "∞" if entry.total_executions == -1 else str(entry.total_executions)
        item = QTableWidgetItem(f"{entry.total_attempts}/{total}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_ATTEMPTS, item)
        
        # Потоки
        item = QTableWidgetItem(str(entry.current_threads))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        fg = "#9ece6a" if entry.current_threads > 0 else "#565f89"
        item.setForeground(QColor(fg))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_THREADS, item)
        
        # Макс потоков
        item = QTableWidgetItem(str(entry.max_threads))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_MAX_THR, item)
        
        # Приоритет
        item = QTableWidgetItem(str(entry.priority))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_PRIORITY, item)
        
        # Метки
        item = QTableWidgetItem(", ".join(entry.labels))
        item.setForeground(QColor("#bb9af7"))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_LABELS, item)
        
        # Следующий запуск
        next_run = ""
        if entry.schedule_enabled and entry.schedule_next_run:
            try:
                dt = datetime.fromisoformat(entry.schedule_next_run)
                next_run = dt.strftime("%d.%m %H:%M")
            except ValueError:
                next_run = "—"
        elif entry.status == ProjectStatus.RUNNING:
            next_run = "—"
        item = QTableWidgetItem(next_run)
        item.setForeground(QColor("#bb9af7"))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_NEXT_RUN, item)
        
        # Режим
        mode_labels = {
            ThreadMode.SEQUENTIAL: _tr("Последоват."),
            ThreadMode.PARALLEL: _tr("Параллельно"),
            ThreadMode.SEMAPHORE_WAIT: _tr("Семафор"),
        }
        item = QTableWidgetItem(mode_labels.get(entry.thread_mode, entry.thread_mode.value))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_MODE, item)
    
    def _get_filtered_projects(self) -> list[ProjectEntry]:
        """Применить текущий фильтр."""
        ftype, fval = self._current_filter
        projects = self._manager.get_all_projects()
        
        if ftype == "all":
            return projects
        elif ftype == "status":
            return [p for p in projects if p.status.value == fval]
        elif ftype == "label":
            return [p for p in projects if fval in p.labels]
        return projects
    
    def _on_project_updated(self, project_id: str):
        """Точечное обновление одной строки."""
        entry = self._manager.get_project(project_id)
        if not entry:
            return
        
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_STATUS)
            if item and item.data(Qt.ItemDataRole.UserRole) == project_id:
                self._populate_row(row, entry)
                break
        
        self._side_panel.update_counts(self._manager.get_all_projects())
    
    def _on_filter_changed(self, ftype: str, fval: str):
        self._current_filter = (ftype, fval)
        self._refresh_table()
    
    # ── Действия ─────────────────────────────────────────────
    
    def _get_selected_ids(self) -> list[str]:
        """Получить ID выделенных проектов."""
        ids = []
        for row in sorted(set(idx.row() for idx in self._table.selectedIndexes())):
            item = self._table.item(row, COL_STATUS)
            if item:
                pid = item.data(Qt.ItemDataRole.UserRole)
                if pid:
                    ids.append(pid)
        return ids
    
    def _show_add_menu(self):
        """Показать меню выбора источника при добавлении проекта."""
        from PyQt6.QtWidgets import QMenu
        try:
            from ui.theme_manager import get_color as _gc
        except ImportError:
            def _gc(k): return {
                "bg2": "#24283b", "bg3": "#283457", "bd": "#3b4261",
                "tx0": "#c0caf5", "ac": "#7aa2f7"
            }.get(k, "#c0caf5")
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {_gc('bg2')}; color: {_gc('tx0')}; "
            f"border: 1px solid {_gc('bd')}; border-radius: 6px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px 6px 12px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {_gc('bg3')}; color: {_gc('ac')}; }}"
        )
        menu.addAction("📋 Из открытых вкладок", self._add_project)
        menu.addAction("📄 Из файла(ов)...", self._add_projects_from_files)
        menu.addAction("📁 Из папки...", self._add_projects_from_folder)
        menu.exec(self._btn_add.mapToGlobal(
            self._btn_add.rect().bottomLeft()
        ))

    def _add_projects_from_files(self):
        """Добавить проекты выбрав один или несколько .workflow.json файлов."""
        from PyQt6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выбрать файлы проектов", "",
            "Workflow (*.workflow.json);;All Files (*)"
        )
        if not paths:
            return
        added = 0
        for path in paths:
            try:
                from services.agent_models import AgentWorkflow
                wf = AgentWorkflow.load(path)
                import os
                name = os.path.basename(path).replace('.workflow.json', '') or wf.name or "Проект"
                # Проверяем дубликат по file_path
                already = any(p.file_path == path for p in self._manager.get_all_projects())
                if already:
                    continue
                entry = ProjectEntry(
                    name=name,
                    file_path=path,
                    workflow=wf,
                    tab_reference=None,
                    window_reference=self._constructor,
                )
                self._manager.add_project(entry)
                added += 1
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить:\n{path}\n\n{e}")
        if added:
            self._refresh_table()
            self._append_log(f"➕ Добавлено {added} проект(ов) из файлов")

    def _add_projects_from_folder(self):
        """Добавить все .workflow.json проекты из выбранной папки."""
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(
            self, "Выбрать папку с проектами", ""
        )
        if not folder:
            return
        import os, glob
        files = glob.glob(os.path.join(folder, "**", "*.workflow.json"), recursive=True)
        if not files:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Инфо", "В папке не найдено файлов *.workflow.json")
            return
        added = 0
        for path in files:
            try:
                from services.agent_models import AgentWorkflow
                wf = AgentWorkflow.load(path)
                name = os.path.basename(path).replace('.workflow.json', '') or wf.name or "Проект"
                already = any(p.file_path == path for p in self._manager.get_all_projects())
                if already:
                    continue
                entry = ProjectEntry(
                    name=name,
                    file_path=path,
                    workflow=wf,
                    tab_reference=None,
                    window_reference=self._constructor,
                )
                self._manager.add_project(entry)
                added += 1
            except Exception:
                pass
        self._refresh_table()
        self._append_log(f"➕ Добавлено {added} проект(ов) из папки")

    def _add_project(self):
        """Добавить текущий открытый проект из конструктора."""
        if not self._constructor:
            QMessageBox.information(self, "Инфо", "Конструктор не подключён")
            return
        
        # Получаем все открытые проекты (вкладки)
        tabs_widget = getattr(self._constructor, '_project_tabs', None)
        if not tabs_widget:
            return
        
        items = []
        tab_map = {}
        for i in range(tabs_widget.count()):
            tab = tabs_widget.widget(i)
            if hasattr(tab, 'workflow') and tab.workflow:
                wf_name = (tab.workflow.name or '').strip()
                tab_text = tabs_widget.tabText(i).rstrip(' *').strip()
                # Предпочитаем: workflow.name > tabText > fallback
                if wf_name and wf_name not in ('...', '…', 'Новый проект'):
                    name = wf_name
                elif tab_text and tab_text not in ('...', '…'):
                    name = tab_text
                else:
                    name = f"Проект {i+1}"
                items.append(name)
                tab_map[name] = tab
        
        if not items:
            QMessageBox.information(self, "Инфо", "Нет открытых проектов")
            return
        
        name, ok = QInputDialog.getItem(
            self, "Добавить проект", "Выберите проект:", items, 0, False
        )
        if not ok or name not in tab_map:
            return
        
        tab = tab_map[name]
        
        # Проверяем не добавлен ли уже
        for p in self._manager.get_all_projects():
            if p.tab_reference is tab:
                QMessageBox.information(self, "Инфо", f"Проект '{name}' уже добавлен")
                return
        
        entry = ProjectEntry(
            name=name,
            file_path=getattr(tab, 'project_path', ''),
            workflow=tab.workflow,
            tab_reference=tab,
            window_reference=self._constructor,
        )
        
        self._manager.add_project(entry)
        self._refresh_table()
    
    def _append_log(self, msg: str):
        """Записать сообщение в лог выполнения."""
        if hasattr(self, '_log') and self._log:
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            self._log.append(f"[{ts}] {msg}")

    def _remove_selected(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        r = QMessageBox.question(
            self, "Удалить",
            f"Удалить {len(ids)} проект(ов) из менеджера?\n(Файлы не удаляются)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            for pid in ids:
                self._manager.remove_project(pid)
            self._refresh_table()
    
    def _start_selected(self):
        """Открыть диалог запуска для каждого выделенного проекта."""
        ids = self._get_selected_ids()
        if not ids:
            return
        
        for pid in ids:
            entry = self._manager.get_project(pid)
            if not entry:
                continue
            
            if entry.status == ProjectStatus.RUNNING:
                continue
            
            # Собираем список сниппетов из workflow (для bottleneck)
            snippets = []
            if entry.workflow:
                from services.agent_models import AgentType
                from constructor.constants import SNIPPET_TYPES
                for node in entry.workflow.nodes:
                    if node.agent_type in SNIPPET_TYPES:
                        snippets.append((node.id, node.name))
            
            dlg = ProjectLaunchDialog(entry, snippets, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                entry = dlg.apply_to_entry()
                
                # Устанавливаем сервисы если есть конструктор
                if self._constructor:
                    mm = getattr(self._constructor, '_model_manager', None)
                    sr = getattr(self._constructor, '_skill_registry', None)
                    if mm and sr:
                        self._manager.set_services(mm, sr)
                
                self._manager.start_project(pid)
    
    def _stop_selected(self):
        for pid in self._get_selected_ids():
            self._manager.stop_project(pid)
    
    def _pause_selected(self):
        for pid in self._get_selected_ids():
            entry = self._manager.get_project(pid)
            if entry and entry.status == ProjectStatus.RUNNING:
                self._manager.pause_project(pid)
            elif entry and entry.status == ProjectStatus.PAUSED:
                self._manager.resume_project(pid)
    
    def _add_executions(self, count: int):
        for pid in self._get_selected_ids():
            self._manager.add_executions(pid, count)
    
    def _open_in_editor(self):
        ids = self._get_selected_ids()
        if ids:
            self.open_project_requested.emit(ids[0])
    
    def _on_double_click(self, index):
        row = index.row()
        item = self._table.item(row, COL_STATUS)
        if item:
            pid = item.data(Qt.ItemDataRole.UserRole)
            entry = self._manager.get_project(pid)
            if entry:
                # Собираем сниппеты
                snippets = []
                if entry.workflow:
                    try:
                        from services.agent_models import AgentType
                        from constructor.constants import SNIPPET_TYPES
                        for node in entry.workflow.nodes:
                            if node.agent_type in SNIPPET_TYPES:
                                snippets.append((node.id, node.name))
                    except Exception:
                        pass
                
                dlg = ProjectLaunchDialog(entry, snippets, self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    dlg.apply_to_entry()
                    self._manager.signals.project_updated.emit(pid)
    
    # ── Контекстное меню ─────────────────────────────────────
    
    def _show_context_menu(self, pos):
        ids = self._get_selected_ids()
        if not ids:
            return
        
        menu = QMenu(self)
        try:
            from ui.theme_manager import get_color as _gc
        except ImportError:
            def _gc(k): return {
                "bg2": "#24283b", "bg3": "#283457", "bd": "#3b4261",
                "tx0": "#c0caf5", "ac": "#7aa2f7"
            }.get(k, "#c0caf5")
        menu.setStyleSheet(
            f"QMenu {{ background: {_gc('bg2')}; color: {_gc('tx0')}; "
            f"border: 1px solid {_gc('bd')}; border-radius: 6px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {_gc('bg3')}; color: {_gc('ac')}; }}"
            f"QMenu::separator {{ background: {_gc('bd')}; height: 1px; margin: 4px 8px; }}"
        )
        
        entry = self._manager.get_project(ids[0])
        if not entry:
            return
        
        if entry.status != ProjectStatus.RUNNING:
            menu.addAction(f"▶️  {_tr('Запустить')}", self._start_selected)
        else:
            menu.addAction(f"⏹  {_tr('Остановить')}", self._stop_selected)
            if entry.status == ProjectStatus.RUNNING:
                menu.addAction(f"⏸  {_tr('Пауза')}", self._pause_selected)
            elif entry.status == ProjectStatus.PAUSED:
                menu.addAction(f"▶️  {_tr('Возобновить')}", self._pause_selected)
        
        menu.addSeparator()
        
        add_menu = menu.addMenu(f"➕ {_tr('Добавить попытки')}")
        for n in [1, 5, 10, 50, 100]:
            add_menu.addAction(f"+{n}", lambda checked=False, c=n: self._add_executions(c))
        add_menu.addAction(f"∞ {_tr('Бесконечно')}", lambda: self._add_executions(-1))
        
        menu.addSeparator()
        
        # Изменить потоки
        thr_menu = menu.addMenu(f"🧵 {_tr('Потоки')}")
        for n in [1, 2, 3, 5, 10, 20]:
            thr_menu.addAction(
                f"{n} {_tr('потоков')}",
                lambda checked=False, c=n: self._set_threads(c)
            )
        
        menu.addSeparator()
        
        menu.addAction(f"📂  {_tr('Открыть в редакторе')}", self._open_in_editor)
        menu.addAction(f"⚙️  {_tr('Настройки...')}", lambda: self._on_double_click(
            self._table.model().index(self._table.currentRow(), 0)
        ))
        
        menu.addSeparator()
        
        menu.addAction(f"🔄  {_tr('Сбросить статистику')}", self._reset_stats)
        menu.addAction(f"🗑  {_tr('Удалить')}", self._remove_selected)
        
        menu.exec(self._table.viewport().mapToGlobal(pos))
    
    def _set_threads(self, count: int):
        for pid in self._get_selected_ids():
            self._manager.set_project_threads(pid, count)
    
    def _reset_stats(self):
        for pid in self._get_selected_ids():
            entry = self._manager.get_project(pid)
            if entry:
                entry.completed_executions = 0
                entry.failed_executions = 0
                entry.consecutive_failures = 0
                entry.total_attempts = 0
                self._manager.signals.project_updated.emit(pid)
    
    # ── Лог ──────────────────────────────────────────────────
    
    def _on_log(self, project_id: str, message: str):
        entry = self._manager.get_project(project_id)
        name = entry.name if entry else project_id
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f"<span style='color:#565f89'>[{ts}]</span> "
            f"<span style='color:#7aa2f7'>[{name}]</span> {message}"
        )
    
    def _on_global_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f"<span style='color:#565f89'>[{ts}]</span> "
            f"<span style='color:#e0af68'>[СИСТЕМА]</span> {message}"
        )
    
    # ── Внешний API для конструктора ─────────────────────────
    
    def register_from_tab(self, tab, name: str = "") -> str:
        """
        Зарегистрировать проект из вкладки конструктора.
        Возвращает project_id.
        """
        if not name:
            # 1) Пробуем имя из workflow
            wf = getattr(tab, 'workflow', None)
            if wf:
                wf_name = (wf.name or '').strip()
                if wf_name and wf_name not in ('...', '…', 'Новый проект', ''):
                    name = wf_name
            # 2) Пробуем имя из пути файла
            if not name:
                _path = getattr(tab, 'project_path', '') or ''
                if _path:
                    import os as _os
                    name = _os.path.basename(_path).replace('.workflow.json', '').strip()
            # 3) Пробуем имя из заголовка вкладки
            if not name and self._constructor:
                tabs_widget = getattr(self._constructor, '_project_tabs', None)
                if tabs_widget:
                    for i in range(tabs_widget.count()):
                        if tabs_widget.widget(i) is tab:
                            tab_text = tabs_widget.tabText(i).strip()
                            if tab_text and tab_text not in ('...', '…', '*'):
                                name = tab_text.rstrip(' *')
                            break
            if not name or name in ('...', '…'):
                name = "Проект"
        
        # Проверяем дубликат — и обновляем имя если оно стало лучше
        tab_path = getattr(tab, 'project_path', '') or ''
        for p in self._manager.get_all_projects():
            # По tab_reference (уже добавленный)
            if p.tab_reference is tab:
                if name and name != "Проект" and p.name in ("Проект", "...", "…"):
                    p.name = name
                    self._manager.signals.project_updated.emit(p.project_id)
                return p.project_id
            # По file_path (восстановлен из состояния, ещё без tab)
            if tab_path and p.file_path == tab_path:
                # Привязываем таб к существующему проекту
                p.tab_reference = tab
                p.window_reference = self._constructor
                if name and name != "Проект" and p.name in ("Проект", "...", "…"):
                    p.name = name
                self._manager.signals.project_updated.emit(p.project_id)
                return p.project_id
        
        entry = ProjectEntry(
            name=name,
            file_path=getattr(tab, 'project_path', ''),
            workflow=getattr(tab, 'workflow', None),
            tab_reference=tab,
            window_reference=self._constructor,
        )
        return self._manager.add_project(entry)
    
    def start_from_constructor(self, project_id: str, model_manager, skill_registry):
        """Запустить проект с передачей сервисов из конструктора."""
        self._manager.set_services(model_manager, skill_registry)
        self._manager.start_project(project_id)
    
    def _restore_workflows_from_files(self):
        """Восстановить workflow объекты из file_path при загрузке состояния."""
        import os
        for entry in self._manager.get_all_projects():
            if not entry.file_path or not os.path.exists(entry.file_path):
                continue
            try:
                mtime = os.path.getmtime(entry.file_path)
                # Если workflow есть и файл не изменился — пропускаем
                if entry.workflow is not None:
                    stored_mtime = getattr(entry.workflow, '_file_mtime', 0)
                    if stored_mtime >= mtime:
                        continue
                from services.agent_models import AgentWorkflow
                entry.workflow = AgentWorkflow.load(entry.file_path)
                entry.workflow._file_mtime = mtime  # Сохраняем время загрузки
            except Exception as e:
                print(f"⚠ Не удалось загрузить workflow из {entry.file_path}: {e}")
    
    def save_state(self):
        """Сохранить состояние менеджера на диск."""
        self._manager.save_state()
    
    def closeEvent(self, event):
        """При закрытии сохраняем состояние."""
        self.save_state()
        super().closeEvent(event)