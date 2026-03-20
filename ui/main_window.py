"""
Main Window — full IDE layout
Left: File Tree | Center: Code Editor | Right-center: Chat+Logs+Input | Right: AI Patches
"""
from __future__ import annotations
import asyncio
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QComboBox, QTextEdit,
    QPlainTextEdit, QTabWidget, QFrame, QFileDialog,
    QCheckBox, QMessageBox, QScrollArea, QSizePolicy, QProgressBar,
    QMenu, QApplication, QSpinBox, QGroupBox,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox
)

from core.models import (
    AppSettings, ChatMessage, MessageRole, ModelDefinition,
    ModelSourceType, PatchBlock, PatchStatus, ProjectContext,
    FileEntry, TokenBudget, LogLevel, LogEntry
)
from services.engine import (
    PatchEngine, PromptEngine, ContextCompressor,
    ModelManager, SherlockAnalyzer, SherlockRequest,
    CODE_EXTENSIONS, IGNORED_DIRS
)
from services.logger_service import StructuredLogger
from services.settings_manager import SettingsManager
from services.version_control import VersionControlService
from services.error_map import ErrorMapService
from services.response_filter import ResponseFilter, FilterConfig
from services.project_manager import ProjectManager, ProjectMode
from services.signal_watcher import SignalMonitorWidget
from services.auto_improve_engine import AutoImproveEngine
from services.script_runner import ScriptRunner
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.patch_preview import PatchPreviewDialog
from ui.dialogs.version_history import VersionHistoryDialog
from ui.dialogs.error_map_dialog import ErrorMapDialog
from ui.widgets.file_tree import FileTreeWidget

try:
    from ui.i18n import tr, register_listener, retranslate_widget
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass
    def retranslate_widget(w): pass


# ──────────────────────────────────────────────────────────
#  ASYNC WORKER
# ──────────────────────────────────────────────────────────

class AiWorkerSignals(QObject):
    chunk       = pyqtSignal(str)
    finished    = pyqtSignal(str)
    patches     = pyqtSignal(list)
    error       = pyqtSignal(str)
    status      = pyqtSignal(str)
    new_variant = pyqtSignal(int, int)   # current, total — open a new bubble


class AiWorker(QRunnable):
    def __init__(self, coro_factory, signals: AiWorkerSignals):
        super().__init__()
        self._factory = coro_factory
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._factory())
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            loop.close()


# ──────────────────────────────────────────────────────────
#  PATCH CARD
# ──────────────────────────────────────────────────────────

class PatchCard(QFrame):
    apply_requested   = pyqtSignal(object)
    reject_requested  = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, patch: PatchBlock, index: int, parent=None):
        super().__init__(parent)
        self.patch = patch
        self._status = PatchStatus.PENDING
        self.setObjectName("patchCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build(index)

    def _build(self, idx: int):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        num = QLabel(f"{tr("ПАТЧ #")}{idx + 1}")
        num.setObjectName("sectionLabel")
        num.setStyleSheet("color: #E0AF68;")
        fp_text = Path(self.patch.file_path).name if self.patch.file_path else tr("текущий файл")
        fp = QLabel(fp_text)
        fp.setStyleSheet("font-size: 12px; color: #7AA2F7;")

        self._status_lbl = QLabel(tr("● ожидает"))
        self._status_lbl.setStyleSheet("font-size: 11px; color: #E0AF68;")

        hdr.addWidget(num)
        hdr.addWidget(fp)
        hdr.addStretch()
        hdr.addWidget(self._status_lbl)
        layout.addLayout(hdr)

        if self.patch.description:
            desc = QLabel(self.patch.description)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 12px; color: #A9B1D6;")
            layout.addWidget(desc)

        diff_tabs = QTabWidget()
        diff_tabs.setMaximumHeight(150)
        diff_tabs.setStyleSheet("QTabBar::tab { padding: 3px 10px; font-size: 10px; }")
        mono = QFont("JetBrains Mono,Cascadia Code,Consolas", 10)

        sv = QPlainTextEdit(self.patch.search_content[:500])
        sv.setReadOnly(True); sv.setObjectName("diffSearch"); sv.setFont(mono)
        rv = QPlainTextEdit(self.patch.replace_content[:500])
        rv.setReadOnly(True); rv.setObjectName("diffReplace"); rv.setFont(mono)

        diff_tabs.addTab(sv, tr("─ Удалить"))
        diff_tabs.addTab(rv, tr("+ Добавить"))
        layout.addWidget(diff_tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        bp = QPushButton(tr("👁 Просмотр")); bp.setFixedWidth(100)
        bp.clicked.connect(lambda: self.preview_requested.emit(self.patch))
        ba = QPushButton(tr("✓ Применить")); ba.setObjectName("successBtn"); ba.setFixedWidth(110)
        ba.clicked.connect(self._do_apply)
        br = QPushButton(tr("✕ Отклонить")); br.setObjectName("dangerBtn"); br.setFixedWidth(110)
        br.clicked.connect(self._do_reject)
        btn_row.addWidget(bp); btn_row.addWidget(ba); btn_row.addWidget(br)
        layout.addLayout(btn_row)
        self._btn_apply = ba; self._btn_reject = br

    def _do_apply(self):  self.apply_requested.emit(self.patch)
    def _do_reject(self):
        self.reject_requested.emit(self.patch)
        self.set_status(PatchStatus.REJECTED)

    def set_status(self, status: PatchStatus, message: str = ""):
        self._status = status
        c_map = {PatchStatus.APPLIED:"#9ECE6A", PatchStatus.REJECTED:"#565f89",
                 PatchStatus.FAILED:"#F7768E", PatchStatus.PENDING:"#E0AF68"}
        t_map = {PatchStatus.APPLIED: tr("● применён"), PatchStatus.REJECTED: tr("● отклонён"),
                 PatchStatus.FAILED:  tr("● ошибка"),   PatchStatus.PENDING:  tr("● ожидает")}
        c = c_map.get(status, "#565f89")
        t = t_map.get(status, status.value)
        self._status_lbl.setStyleSheet(f"font-size:11px;color:{c};")
        self._status_lbl.setText(t + (f": {message[:50]}" if message else ""))
        if status in (PatchStatus.APPLIED, PatchStatus.REJECTED, PatchStatus.FAILED):
            self._btn_apply.setEnabled(False); self._btn_reject.setEnabled(False)
        bc_map = {PatchStatus.APPLIED:"#9ECE6A", PatchStatus.REJECTED:"#2E3148",
                  PatchStatus.FAILED:"#F7768E",  PatchStatus.PENDING:"#E0AF68"}
        bc = bc_map.get(status, "#2E3148")
        self.setStyleSheet(f"PatchCard {{ border-left: 3px solid {bc}; }}")


# ──────────────────────────────────────────────────────────
#  MAIN WINDOW
# ──────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    settings_changed = pyqtSignal(object)   # emitted after settings saved, passes AppSettings

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Code Sherlock")
        self.setMinimumSize(1280, 720)
        self.resize(1600, 900)

        # ── Services ──
        self._logger          = StructuredLogger()
        self._settings_mgr    = SettingsManager()
        self._patch_engine    = PatchEngine()
        self._prompt_engine   = PromptEngine()
        self._model_manager   = ModelManager(self._settings_mgr, self._logger)
        self._compressor: ContextCompressor | None = None
        self._sherlock: SherlockAnalyzer | None = None
        self._version_ctrl    = VersionControlService()
        self._error_map       = ErrorMapService()
        self._response_filter = ResponseFilter(FilterConfig(use_tabs=False))
        self._project_mgr     = ProjectManager(self._logger)
        self._signal_monitor  = SignalMonitorWidget(self)
        self._script_runner   = ScriptRunner(self._logger)
        self._auto_engine: AutoImproveEngine | None = None  # built after model ready

        # ── State ──
        self._settings: AppSettings = AppSettings()
        self._open_files: dict[str, str] = {}
        self._active_file: str | None = None
        self._patches: list[PatchCard] = []
        self._conversation: list[ChatMessage] = []
        self._is_processing = False
        self._consensus_model_ids: list[str] = []   # for consensus model picker
        self._worker_signals = AiWorkerSignals()
        self._current_stream_edit: QPlainTextEdit | None = None
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

        # Pre-create status label so _build_auto_run_tab can connect to it
        # (it gets added to the real status bar in _build_status_bar)
        self._lbl_status_left = QLabel(tr("Готов"))
        self._lbl_status_left.setObjectName("statusLabel")

        self._build_ui()
        self._connect_signals()
        self._load_settings()

        QShortcut(QKeySequence("Ctrl+Return"), self, self._send_message)
        QShortcut(QKeySequence("Ctrl+O"),      self, self._open_file)
        QShortcut(QKeySequence("Ctrl+Shift+O"),self, self._open_project)
        QShortcut(QKeySequence("Ctrl+S"),      self, self._save_active_file)

    # ══════════════════════════════════════════════════════
    #  UI BUILD
    # ══════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_toolbar())

        # Four-panel layout: File Tree | Code Editor | Chat | AI Patches
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setHandleWidth(1)

        main_split.addWidget(self._build_file_tree_panel())
        main_split.addWidget(self._build_editor_panel())
        main_split.addWidget(self._build_chat_panel())
        main_split.addWidget(self._build_patches_panel())
        main_split.setSizes([200, 480, 560, 340])

        root.addWidget(main_split, stretch=1)
        root.addWidget(self._build_status_bar())

    # ── Title Bar ──────────────────────────────────────────

    def _build_title_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("titleBar"); bar.setFixedHeight(44)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 12, 0)

        logo = QLabel("🔍 AI Code Sherlock")
        logo.setStyleSheet("font-size:15px;font-weight:bold;color:#7AA2F7;font-family:sans-serif;")
        layout.addWidget(logo)

        badge = QLabel("ACTIVE")
        badge.setStyleSheet("background:#1A2E1A;color:#9ECE6A;border:1px solid #9ECE6A;border-radius:4px;padding:1px 7px;font-size:9px;font-weight:bold;")
        layout.addWidget(badge)

        # Project mode indicator
        self._lbl_mode = QLabel(tr("🆕 Новый проект"))
        self._lbl_mode.setStyleSheet("color:#E0AF68;font-size:11px;padding:0 8px;")
        layout.addWidget(self._lbl_mode)

        layout.addStretch()

        lbl = QLabel(tr("Модель:"))
        lbl.setStyleSheet("color:#565f89;font-size:12px;")
        layout.addWidget(lbl)

        self._cmb_model = QComboBox()
        self._cmb_model.setMinimumWidth(220)
        self._cmb_model.currentIndexChanged.connect(self._on_model_changed)
        layout.addWidget(self._cmb_model)

        self._lbl_model_status = QLabel("●")
        self._lbl_model_status.setStyleSheet("color:#565f89;font-size:14px;")
        layout.addWidget(self._lbl_model_status)

        layout.addSpacing(10)
        btn_s = QPushButton("⚙")
        btn_s.setObjectName("iconBtn")
        btn_s.setToolTip(tr("Настройки"))
        btn_s.clicked.connect(self._open_settings)
        layout.addWidget(btn_s)
        return bar

    # ── Toolbar ────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("toolbar"); bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        def sep():
            s = QFrame(); s.setFrameShape(QFrame.Shape.VLine)
            s.setFixedWidth(1); s.setStyleSheet("background:#1E2030;margin:6px 2px;")
            return s

        btn_new = QPushButton(tr("📋 Новый проект")); btn_new.clicked.connect(self._new_project)
        btn_open_proj = QPushButton(tr("📁 Открыть проект")); btn_open_proj.clicked.connect(self._open_project)
        btn_open_file = QPushButton(tr("📄 Файл")); btn_open_file.clicked.connect(self._open_file)
        btn_save = QPushButton(tr("💾 Сохранить")); btn_save.clicked.connect(self._save_active_file)
        layout.addWidget(btn_new); layout.addWidget(btn_open_proj)
        layout.addWidget(btn_open_file); layout.addWidget(btn_save)
        layout.addWidget(sep())

        self._btn_sherlock = QPushButton(tr("🔍 Шерлок"))
        self._btn_sherlock.setObjectName("toggleBtn"); self._btn_sherlock.setCheckable(True)
        self._btn_sherlock.setToolTip(tr("Режим анализа ошибок"))
        layout.addWidget(self._btn_sherlock)

        self._btn_send_logs = QPushButton(tr("📋 Логи→AI"))
        self._btn_send_logs.setObjectName("toggleBtn"); self._btn_send_logs.setCheckable(True)
        layout.addWidget(self._btn_send_logs)

        self._btn_mode = QPushButton(tr("🆕 Новый"))
        self._btn_mode.setObjectName("toggleBtn"); self._btn_mode.setCheckable(True)
        self._btn_mode.setChecked(True)
        self._btn_mode.setToolTip(tr("Вкл = Новый проект (полные ответы)\nВыкл = Только патчи"))
        self._btn_mode.toggled.connect(self._on_mode_toggled)
        layout.addWidget(self._btn_mode)

        layout.addWidget(sep())

        btn_history = QPushButton(tr("⏪ История"))
        btn_history.setToolTip(tr("История версий файла"))
        btn_history.clicked.connect(self._open_version_history)
        layout.addWidget(btn_history)

        btn_errormap = QPushButton(tr("🗂 Карта ошибок"))
        btn_errormap.clicked.connect(self._open_error_map)
        layout.addWidget(btn_errormap)

        self._btn_pipeline = QPushButton(tr("⚡ Pipeline"))
        self._btn_pipeline.setStyleSheet(
            "QPushButton{background:#1A1A2E;color:#BB9AF7;border:1px solid #9B59B6;border-radius:5px;padding:3px 10px;font-weight:bold;}QPushButton:hover{background:#252040;border-color:#BB9AF7;color:#D4AAFF;}"
        )
        self._btn_pipeline.setToolTip(tr("Настроить и запустить Auto-Improve Pipeline"))
        self._btn_pipeline.clicked.connect(self._open_pipeline_dialog)
        layout.addWidget(self._btn_pipeline)

        btn_run_script = QPushButton(tr("▶ Запустить скрипт"))
        btn_run_script.setStyleSheet(
            "QPushButton{background:#0D2B1A;color:#39FF84;border:1px solid #22B35A;border-radius:5px;padding:3px 10px;font-weight:bold;}QPushButton:hover{background:#133D24;border-color:#39FF84;color:#5AFF9A;}"
        )
        btn_run_script.setToolTip(tr("Запустить активный файл или выбрать скрипт из проекта."))
        btn_run_script.clicked.connect(self._run_script_manually)
        layout.addWidget(btn_run_script)

        btn_export = QPushButton(tr("📥 Логи"))
        btn_export.clicked.connect(self._export_logs)
        layout.addWidget(btn_export)

        layout.addStretch()

        self._lbl_signal = QLabel(tr("○ Сигнал"))
        self._lbl_signal.setStyleSheet("color:#565f89;font-size:11px;")
        layout.addWidget(self._lbl_signal)

        layout.addWidget(sep())

        self._lbl_processing = QLabel(tr("⟳ Обработка..."))
        self._lbl_processing.setStyleSheet("color:#7AA2F7;font-size:12px;")
        self._lbl_processing.hide()
        layout.addWidget(self._lbl_processing)

        self._btn_stop = QPushButton(tr("■ Стоп"))
        self._btn_stop.setObjectName("dangerBtn"); self._btn_stop.hide()
        self._btn_stop.clicked.connect(self._stop_processing)
        layout.addWidget(self._btn_stop)

        # Register for live language retranslation
        register_listener(lambda lang: retranslate_widget(bar))
        register_listener(lambda lang: self._btn_pipeline.setText(tr("⚡ Pipeline")))

        return bar

    # ── File Tree Panel ────────────────────────────────────

    def _build_file_tree_panel(self) -> QWidget:
        self._file_tree = FileTreeWidget()
        self._file_tree.file_open_requested.connect(self._load_file)
        self._file_tree.file_send_to_ai.connect(self._send_file_to_ai)
        self._file_tree.folder_changed.connect(self._on_folder_changed)
        return self._file_tree

    # ── Code Editor Panel ──────────────────────────────────

    def _build_editor_panel(self) -> QWidget:
        panel = QFrame(); panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with context-menu-friendly tab strip
        hdr = QFrame(); hdr.setObjectName("panelHeader"); hdr.setFixedHeight(32)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        lbl = QLabel(tr("КОД")); lbl.setObjectName("sectionLabel")
        self._lbl_active_file = QLabel(tr("нет файла"))
        self._lbl_active_file.setStyleSheet("color:#7AA2F7;font-size:11px;")
        hl.addWidget(lbl); hl.addStretch(); hl.addWidget(self._lbl_active_file)
        layout.addWidget(hdr)

        # Context bar
        self._ctx_bar = QFrame()
        self._ctx_bar.setStyleSheet("background:#0A0D14;border-bottom:1px solid #1E2030;")
        self._ctx_bar.setFixedHeight(22)
        cb_l = QHBoxLayout(self._ctx_bar); cb_l.setContentsMargins(10, 0, 10, 0)
        self._lbl_ctx_files = QLabel(tr("0 файлов"))
        self._lbl_ctx_files.setStyleSheet("color:#565f89;font-size:10px;")
        self._lbl_ctx_tokens = QLabel(tr("~0 токенов"))
        self._lbl_ctx_tokens.setStyleSheet("color:#565f89;font-size:10px;")
        cb_l.addWidget(self._lbl_ctx_files); cb_l.addStretch()
        cb_l.addWidget(self._lbl_ctx_tokens)
        layout.addWidget(self._ctx_bar)

        # Tab widget with extended context menu
        self._file_tabs = QTabWidget()
        self._file_tabs.setTabsClosable(True)
        self._file_tabs.setMovable(True)   # drag-to-reorder tabs
        self._file_tabs.setDocumentMode(True)
        self._file_tabs.tabCloseRequested.connect(self._close_file_tab)
        self._file_tabs.currentChanged.connect(self._on_tab_changed)
        self._file_tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_tabs.tabBar().customContextMenuRequested.connect(
            self._tab_bar_context_menu)
        layout.addWidget(self._file_tabs, stretch=1)

        return panel

    # ── Chat Panel (center-right) ──────────────────────────

    def _build_chat_panel(self) -> QWidget:
        panel = QFrame(); panel.setObjectName("centerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tabs: Conversation | Logs | Context | Signals
        self._center_tabs = QTabWidget()
        self._center_tabs.addTab(self._build_conversation_tab(), tr("💬 Диалог"))
        self._center_tabs.addTab(self._build_logs_tab(),         tr("📋 Логи"))
        self._center_tabs.addTab(self._build_context_tab(),      tr("📦 Контекст"))
        self._center_tabs.addTab(self._build_signals_tab(),      tr("📡 Сигналы"))
        self._center_tabs.addTab(self._build_auto_run_tab(),     tr("⚡ Авто-запуск"))
        layout.addWidget(self._center_tabs, stretch=1)

        layout.addWidget(self._build_input_area())
        return panel

    def _build_conversation_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("chatScroll")

        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(8, 8, 8, 8)
        self._chat_layout.setSpacing(4)
        self._chat_layout.addStretch()

        scroll.setWidget(self._chat_container)
        self._chat_scroll = scroll
        layout.addWidget(scroll)
        return w

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(5000)
        self._log_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))

        btn_row = QHBoxLayout()
        btn_clr = QPushButton(tr("Очистить")); btn_clr.clicked.connect(self._log_view.clear)
        btn_copy = QPushButton(tr("📋 Копировать")); btn_copy.clicked.connect(self._copy_logs)
        btn_row.addStretch(); btn_row.addWidget(btn_copy); btn_row.addWidget(btn_clr)

        layout.addWidget(self._log_view, stretch=1)
        layout.addLayout(btn_row)
        return w

    def _build_context_tab(self) -> QWidget:
        """Shows what's currently in AI context — files, tokens, skeletons."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        lbl = QLabel(tr("КОНТЕКСТ AI"))
        lbl.setObjectName("sectionLabel")
        hdr.addWidget(lbl)
        hdr.addStretch()
        btn_refresh = QPushButton(tr("↺ Обновить"))
        btn_refresh.clicked.connect(self._refresh_context_view)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        self._ctx_summary = QLabel(tr("Контекст не построен"))
        self._ctx_summary.setStyleSheet("color:#565f89;font-size:11px;")
        self._ctx_summary.setWordWrap(True)
        layout.addWidget(self._ctx_summary)

        self._ctx_detail = QPlainTextEdit()
        self._ctx_detail.setReadOnly(True)
        self._ctx_detail.setObjectName("logView")
        self._ctx_detail.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._ctx_detail.setPlaceholderText(tr("Открой файл и отправь запрос для построения контекста..."))
        layout.addWidget(self._ctx_detail, stretch=1)

        return w

    def _build_signals_tab(self) -> QWidget:
        """Real-time monitor for FileSignal folders."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        lbl = QLabel(tr("МОНИТОРИНГ СИГНАЛОВ"))
        lbl.setObjectName("sectionLabel")
        hdr.addWidget(lbl)
        hdr.addStretch()

        self._lbl_monitor_status = QLabel(tr("○ Остановлен"))
        self._lbl_monitor_status.setStyleSheet("color:#565f89;font-size:11px;")
        hdr.addWidget(self._lbl_monitor_status)

        btn_start = QPushButton(tr("▶ Запустить"))
        btn_start.setObjectName("successBtn"); btn_start.setFixedWidth(100)
        btn_start.clicked.connect(self._start_signal_monitor)
        btn_stop = QPushButton(tr("■ Стоп"))
        btn_stop.setObjectName("dangerBtn"); btn_stop.setFixedWidth(80)
        btn_stop.clicked.connect(lambda: self._signal_monitor.stop())
        hdr.addWidget(btn_start); hdr.addWidget(btn_stop)
        layout.addLayout(hdr)

        self._signal_log = QPlainTextEdit()
        self._signal_log.setReadOnly(True)
        self._signal_log.setObjectName("logView")
        self._signal_log.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._signal_log.setMaximumBlockCount(500)
        self._signal_log.setPlaceholderText(tr("События файловых сигналов появятся здесь..."))
        layout.addWidget(self._signal_log, stretch=1)

        # Stats row
        stats = QHBoxLayout()
        self._lbl_signal_count = QLabel(tr("Событий: 0"))
        self._lbl_signal_count.setStyleSheet("color:#565f89;font-size:11px;")
        stats.addWidget(self._lbl_signal_count); stats.addStretch()
        layout.addLayout(stats)

        return w

    def _build_auto_run_tab(self) -> QWidget:
        """Auto-Improve Pipeline tab — embedded AutoRunPanel."""
        from ui.panels.auto_run_panel import AutoRunPanel
        self._auto_run_panel = AutoRunPanel(self._get_or_create_auto_engine())
        self._auto_run_panel.status_changed.connect(self._lbl_status_left.setText)
        return self._auto_run_panel

    def _get_or_create_auto_engine(self) -> AutoImproveEngine:
        if self._auto_engine is None:
            self._auto_engine = AutoImproveEngine(
                model_manager=self._model_manager,
                patch_engine=self._patch_engine,
                prompt_engine=self._prompt_engine,
                version_ctrl=self._version_ctrl,
                error_map=self._error_map,
                logger=self._logger,
            )
        return self._auto_engine

    def _build_input_area(self) -> QWidget:
        from services.pipeline_models import AIStrategy, AI_STRATEGY_DESCRIPTIONS

        w = QWidget()
        w.setObjectName("inputArea")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)

        # ── Context options row ───────────────────────────────
        opts = QHBoxLayout()
        self._chk_include_file = QCheckBox(tr("Активный файл"))
        self._chk_include_file.setChecked(True)
        self._chk_include_logs = QCheckBox(tr("Логи ошибок"))
        self._chk_include_all  = QCheckBox(tr("Весь проект (скелет)"))
        self._lbl_tokens = QLabel(tr("~0 токенов"))
        self._lbl_tokens.setObjectName("statusLabel")
        opts.addWidget(self._chk_include_file)
        opts.addWidget(self._chk_include_logs)
        opts.addWidget(self._chk_include_all)
        opts.addStretch()
        opts.addWidget(self._lbl_tokens)
        layout.addLayout(opts)

        # ── Patch targets row ─────────────────────────────────
        # Shows which files AI is allowed to patch in this request
        self._patch_targets: list[str] = []   # extra files beyond active_file

        pt_row = QHBoxLayout(); pt_row.setSpacing(4)
        lbl_pt = QLabel(tr("Патчить:"))
        lbl_pt.setStyleSheet("color:#565f89;font-size:10px;min-width:46px;")
        pt_row.addWidget(lbl_pt)

        # Chips container — scrollable horizontal area
        self._pt_chips_widget = QWidget()
        self._pt_chips_layout = QHBoxLayout(self._pt_chips_widget)
        self._pt_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._pt_chips_layout.setSpacing(3)
        self._pt_chips_layout.addStretch()

        pt_scroll = QScrollArea()
        pt_scroll.setWidget(self._pt_chips_widget)
        pt_scroll.setWidgetResizable(True)
        pt_scroll.setFixedHeight(26)
        pt_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pt_scroll.setStyleSheet("background:transparent;")
        pt_row.addWidget(pt_scroll, stretch=1)

        # Buttons
        btn_pt_add = QPushButton(tr("＋ файл"))
        btn_pt_add.setFixedHeight(22)
        btn_pt_add.setToolTip(tr("Добавить файл в цели патчинга для этого запроса"))
        btn_pt_add.setStyleSheet(
            "QPushButton{background:#1A1D2E;border:1px solid #2E3148;border-radius:4px;color:#BB9AF7;font-size:10px;padding:1px 8px;}QPushButton:hover{background:#252040;border-color:#BB9AF7;}"
        )
        btn_pt_add.clicked.connect(self._add_patch_target_file)
        pt_row.addWidget(btn_pt_add)

        btn_pt_folder = QPushButton(tr("＋ папка"))
        btn_pt_folder.setFixedHeight(22)
        btn_pt_folder.setToolTip(tr("Добавить все .py файлы из папки как цели патчинга"))
        btn_pt_folder.setStyleSheet(
            "QPushButton{background:#1A1D2E;border:1px solid #2E3148;border-radius:4px;color:#BB9AF7;font-size:10px;padding:1px 8px;}QPushButton:hover{background:#252040;border-color:#BB9AF7;}"
        )
        btn_pt_folder.clicked.connect(self._add_patch_target_folder)
        pt_row.addWidget(btn_pt_folder)

        btn_pt_clr = QPushButton("✕")
        btn_pt_clr.setFixedSize(22, 22)
        btn_pt_clr.setToolTip(tr("Очистить все дополнительные цели патчинга"))
        btn_pt_clr.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#565f89;font-size:11px;}QPushButton:hover{color:#F7768E;}"
        )
        btn_pt_clr.clicked.connect(self._clear_patch_targets)
        pt_row.addWidget(btn_pt_clr)

        layout.addLayout(pt_row)
        self._refresh_patch_target_chips()   # initial state (empty)

        # ── Strategy + Consensus row ──────────────────────────
        ai_row = QHBoxLayout()
        ai_row.setSpacing(6)

        # Strategy selector
        strat_lbl = QLabel(tr("Стратегия:"))
        strat_lbl.setStyleSheet("color:#565f89;font-size:11px;")
        ai_row.addWidget(strat_lbl)

        self._cmb_chat_strategy = QComboBox()
        self._cmb_chat_strategy.setFixedWidth(168)
        self._cmb_chat_strategy.setToolTip(tr("Стратегия AI для обычного чата"))
        _strat_icons = {
            "conservative": "🛡", "balanced": "⚖️", "aggressive": "🚀",
            "explorer": "🔭", "exploit": "💎", "safe_ratchet": "🔒",
            "hypothesis": "🔬", "ensemble": "🎭",
        }
        for s in AIStrategy:
            icon = _strat_icons.get(s.value, "●")
            self._cmb_chat_strategy.addItem(
                f"{icon} {s.value.replace('_', ' ').title()}", s.value
            )
        self._cmb_chat_strategy.setCurrentIndex(1)  # balanced
        self._cmb_chat_strategy.currentIndexChanged.connect(self._on_chat_strategy_changed)
        ai_row.addWidget(self._cmb_chat_strategy)

        # Custom strategy picker button
        self._btn_custom_strat = QPushButton(tr("✏ Свои"))
        self._btn_custom_strat.setFixedWidth(68)
        self._btn_custom_strat.setToolTip(tr("Выбрать кастомную стратегию из сохранённых"))
        self._btn_custom_strat.setStyleSheet(
            "QPushButton{background:#1E2030;border:1px solid #2E3148;border-radius:4px;color:#A9B1D6;padding:2px 6px;font-size:11px;}QPushButton:hover{background:#2E3148;color:#BB9AF7;}"
        )
        self._btn_custom_strat.clicked.connect(self._pick_custom_strategy)
        self._active_custom_strategy: dict | None = None
        ai_row.addWidget(self._btn_custom_strat)

        # Strategy description tooltip label
        self._lbl_strat_desc = QLabel("")
        self._lbl_strat_desc.setStyleSheet("color:#3B4261;font-size:10px;")
        self._lbl_strat_desc.setWordWrap(False)
        ai_row.addWidget(self._lbl_strat_desc)

        ai_row.addSpacing(10)

        # Consensus toggle
        self._chk_consensus = QCheckBox(tr("🤝 Консенсус"))
        self._chk_consensus.setToolTip(
            tr("Запросить несколько моделей и выбрать лучший ответ")
        )
        self._chk_consensus.setStyleSheet("font-size:11px;color:#A9B1D6;")
        self._chk_consensus.toggled.connect(self._on_chat_consensus_toggled)
        ai_row.addWidget(self._chk_consensus)

        # Consensus mode selector (hidden by default)
        self._cmb_consensus_mode = QComboBox()
        self._cmb_consensus_mode.setFixedWidth(148)
        self._cmb_consensus_mode.setVisible(False)
        try:
            from services.pipeline_models import ConsensusMode
            self._cmb_consensus_mode.addItem(tr("🗳 Голосование"), ConsensusMode.VOTE.value)
            self._cmb_consensus_mode.addItem(tr("🏆 Best-of-N"), ConsensusMode.BEST_OF_N.value)
            self._cmb_consensus_mode.addItem(tr("🔀 Merge"),     ConsensusMode.MERGE.value)
            self._cmb_consensus_mode.addItem(tr("⚖️ Judge"),     ConsensusMode.JUDGE.value)
        except ImportError:
            pass
        ai_row.addWidget(self._cmb_consensus_mode)

        # Model picker button — opens dialog to choose which models to use
        self._btn_consensus_models = QPushButton(tr("⚙ Модели"))
        self._btn_consensus_models.setFixedWidth(80)
        self._btn_consensus_models.setVisible(False)
        self._btn_consensus_models.setToolTip(tr("Выбрать модели для консенсуса"))
        self._btn_consensus_models.setStyleSheet(
            "QPushButton{background:#1E2030;border:1px solid #2E3148;border-radius:4px;color:#A9B1D6;padding:2px 6px;font-size:11px;}QPushButton:hover{background:#2E3148;color:#CDD6F4;}"
        )
        self._btn_consensus_models.clicked.connect(self._pick_consensus_models)
        ai_row.addWidget(self._btn_consensus_models)

        ai_row.addStretch()

        # Variants spinbox (how many answer variants to request)
        variants_lbl = QLabel(tr("Вариантов:"))
        variants_lbl.setStyleSheet("color:#565f89;font-size:11px;")
        ai_row.addWidget(variants_lbl)

        self._spn_variants = QSpinBox()
        self._spn_variants.setRange(1, 5)
        self._spn_variants.setValue(1)
        self._spn_variants.setFixedWidth(46)
        self._spn_variants.setToolTip(
            tr("1 = обычный ответ\n2–5 = AI генерирует N независимых вариантов,\n      каждый показывается отдельным сообщением")
        )
        self._spn_variants.setStyleSheet("font-size:11px;")
        ai_row.addWidget(self._spn_variants)

        layout.addLayout(ai_row)

        # ── Text input ────────────────────────────────────────
        self._input_box = QTextEdit()
        self._input_box.setObjectName("chatInput")
        self._input_box.setPlaceholderText(
            tr("Задай вопрос или опиши изменение...  (Ctrl+Enter — отправить)")
        )
        self._input_box.setMaximumHeight(110)
        self._input_box.setMinimumHeight(75)
        self._input_box.setFont(QFont("Segoe UI,Arial", 12))

        # ── Send row ──────────────────────────────────────────
        send_row = QHBoxLayout()
        send_row.addStretch()
        self._btn_send = QPushButton(tr("▶ Отправить  Ctrl+↵"))
        self._btn_send.setObjectName("primaryBtn")
        self._btn_send.setFixedWidth(185)
        self._btn_send.clicked.connect(self._send_message)
        send_row.addWidget(self._btn_send)

        layout.addWidget(self._input_box)
        layout.addLayout(send_row)

        # Init strategy description
        self._on_chat_strategy_changed(1)
        return w

    # ── Patch Targets (main input area) ────────────────────────────────────

    def _refresh_patch_target_chips(self):
        """Rebuild the chip bar showing extra patch-target files."""
        # Clear existing chips (all except final stretch)
        while self._pt_chips_layout.count() > 1:
            item = self._pt_chips_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for path in self._patch_targets:
            chip = self._make_pt_chip(path)
            self._pt_chips_layout.insertWidget(self._pt_chips_layout.count() - 1, chip)

        # Show "active file" chip always (greyed if none open)
        if self._active_file:
            self._pt_chips_layout.insertWidget(
                0, self._make_pt_chip(self._active_file, is_active=True)
            )

    def _make_pt_chip(self, path: str, is_active: bool = False) -> QFrame:
        """Create a single file chip widget for the patch targets row."""
        chip = QFrame()
        chip.setFixedHeight(20)
        if is_active:
            chip.setStyleSheet(
                "QFrame{background:#1A2A3A;border:1px solid #7AA2F7;border-radius:4px;padding:0 2px;}"
            )
        else:
            chip.setStyleSheet(
                "QFrame{background:#1A1A2E;border:1px solid #BB9AF7;border-radius:4px;padding:0 2px;}"
            )
        cl = QHBoxLayout(chip); cl.setContentsMargins(5, 0, 2, 0); cl.setSpacing(2)

        name = Path(path).name
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color:{'#7AA2F7' if is_active else '#BB9AF7'};"
            "font-size:10px;background:transparent;border:none;"
        )
        lbl.setToolTip(path)
        cl.addWidget(lbl)

        if not is_active:
            btn_x = QPushButton("×")
            btn_x.setFixedSize(14, 14)
            btn_x.setStyleSheet(
                "QPushButton{background:transparent;border:none;color:#565f89;font-size:11px;padding:0;}QPushButton:hover{color:#F7768E;}"
            )
            btn_x.setToolTip(f"Убрать {name} из целей патчинга")
            btn_x.clicked.connect(lambda _, p=path: self._remove_patch_target(p))
            cl.addWidget(btn_x)

        return chip

    def _add_patch_target_file(self):
        """Open file dialog to add files to patch targets."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Файлы для патчинга"),
            filter="Code (*.py *.js *.ts *.json *.yaml *.yml *.toml *.cfg *.sql *.md);;All (*)"
        )
        changed = False
        for p in paths:
            if p not in self._patch_targets and p != self._active_file:
                self._patch_targets.append(p)
                # Auto-open file so content is available for context
                if p not in self._open_files:
                    try:
                        with open(p, "r", encoding="utf-8", errors="replace") as f:
                            self._open_files[p] = f.read()
                    except Exception:
                        self._open_files[p] = ""
                changed = True
        if changed:
            self._refresh_patch_target_chips()

    def _add_patch_target_folder(self):
        """Add all .py files from a folder as patch targets."""
        folder = QFileDialog.getExistingDirectory(self, tr("Папка с модулями для патчинга"))
        if not folder:
            return
        import os as _os
        added = 0
        existing = set(self._patch_targets) | ({self._active_file} if self._active_file else set())
        for root_dir, dirs, files in _os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules", ".venv", "venv")]
            for fname in sorted(files):
                if not fname.endswith((".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml")):
                    continue
                fpath = _os.path.join(root_dir, fname)
                if fpath not in existing:
                    self._patch_targets.append(fpath)
                    existing.add(fpath)
                    if fpath not in self._open_files:
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                                self._open_files[fpath] = f.read()
                        except Exception:
                            self._open_files[fpath] = ""
                    added += 1
        if added:
            self._refresh_patch_target_chips()
        else:
            QMessageBox.information(self, tr("Нет файлов"), tr("Подходящих файлов не найдено в папке."))

    def _remove_patch_target(self, path: str):
        if path in self._patch_targets:
            self._patch_targets.remove(path)
            self._refresh_patch_target_chips()

    def _clear_patch_targets(self):
        self._patch_targets.clear()
        self._refresh_patch_target_chips()

    def _get_all_patch_targets(self) -> list[str]:
        """Return active file + extra patch targets, deduplicated."""
        result = []
        if self._active_file:
            result.append(self._active_file)
        for p in self._patch_targets:
            if p not in result:
                result.append(p)
        return result

    def _on_chat_strategy_changed(self, idx: int):
        """Update the strategy description label."""
        try:
            from services.pipeline_models import AIStrategy, AI_STRATEGY_DESCRIPTIONS
            val = self._cmb_chat_strategy.itemData(idx)
            if val:
                desc = AI_STRATEGY_DESCRIPTIONS.get(AIStrategy(val), "")
                # Truncate to fit
                short = desc[:60] + "…" if len(desc) > 60 else desc
                self._lbl_strat_desc.setText(short)
                self._lbl_strat_desc.setToolTip(desc)
        except Exception:
            pass

    def _update_consensus_btn_label(self):
        """Update the consensus models button label to show how many are selected."""
        total = len(self._settings.models)
        selected = len(self._consensus_model_ids)
        if not self._consensus_model_ids or selected == 0:
            label = f"⚙ {tr('Модели')} ({total})"
        else:
            label = f"⚙ {tr('Модели')} ({selected}/{total})"
        self._btn_consensus_models.setText(label)

    def _retranslate_static_labels(self, _lang: str = "") -> None:
        """Retranslate all static initial labels (called on language change)."""
        # Context/token labels in the editor header area
        if hasattr(self, "_lbl_ctx_files"):
            self._lbl_ctx_files.setText(tr("0 файлов"))
        if hasattr(self, "_lbl_ctx_tokens"):
            self._lbl_ctx_tokens.setText(tr("~0 токенов"))
        if hasattr(self, "_lbl_tokens"):
            self._lbl_tokens.setText(tr("~0 токенов"))
        # Active file label
        if hasattr(self, "_lbl_active_file") and self._lbl_active_file.text() in ("нет файла", "no file"):
            self._lbl_active_file.setText(tr("нет файла"))
        # Status label
        if hasattr(self, "_lbl_status_left"):
            current = self._lbl_status_left.text()
            if current in ("Готов", "Ready"):
                self._lbl_status_left.setText(tr("Готов"))
        # Signals tab
        if hasattr(self, "_lbl_signal"):
            if self._lbl_signal.text() in ("○ Сигнал", "○ Signal"):
                self._lbl_signal.setText(tr("○ Сигнал"))
        # Refresh token counts with current language
        self._update_context_tokens()

    def _retranslate_consensus_items(self):
        """Rebuild consensus mode combobox items in current language (called on lang change)."""
        try:
            from services.pipeline_models import ConsensusMode
            current_data = self._cmb_consensus_mode.currentData()
            self._cmb_consensus_mode.blockSignals(True)
            self._cmb_consensus_mode.clear()
            self._cmb_consensus_mode.addItem(tr("🗳 Голосование"), ConsensusMode.VOTE.value)
            self._cmb_consensus_mode.addItem(tr("🏆 Best-of-N"),   ConsensusMode.BEST_OF_N.value)
            self._cmb_consensus_mode.addItem(tr("🔀 Merge"),       ConsensusMode.MERGE.value)
            self._cmb_consensus_mode.addItem(tr("⚖️ Judge"),       ConsensusMode.JUDGE.value)
            # Restore selection
            for i in range(self._cmb_consensus_mode.count()):
                if self._cmb_consensus_mode.itemData(i) == current_data:
                    self._cmb_consensus_mode.setCurrentIndex(i)
                    break
            self._cmb_consensus_mode.blockSignals(False)
        except Exception:
            pass

    def _on_chat_consensus_toggled(self, enabled: bool):
        """Show/hide consensus controls."""
        self._cmb_consensus_mode.setVisible(enabled)
        self._btn_consensus_models.setVisible(enabled)
        if enabled:
            self._chk_consensus.setStyleSheet("font-size:11px;color:#7AA2F7;")
            # Update button label with selected count
            self._update_consensus_btn_label()
        else:
            self._chk_consensus.setStyleSheet("font-size:11px;color:#A9B1D6;")

    def _pick_custom_strategy(self):
        """Show popup to pick a saved custom strategy or clear active one."""
        import json
        from pathlib import Path as _Path
        strat_file = _Path.home() / ".ai_code_sherlock" / "custom_strategies.json"
        strategies: list[dict] = []
        if strat_file.exists():
            try:
                strategies = json.loads(strat_file.read_text("utf-8"))
            except Exception:
                strategies = []

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#1E2030;border:1px solid #2E3148;border-radius:6px;
                  padding:4px;color:#CDD6F4;font-size:12px;}
            QMenu::item{padding:7px 20px;border-radius:4px;}
            QMenu::item:selected{background:#2E3148;}
            QMenu::separator{background:#2E3148;height:1px;margin:4px 0;}
        """)

        # "None" option to clear
        act_none = menu.addAction(tr("⊘  Без кастомной стратегии"))
        act_none.setCheckable(True)
        act_none.setChecked(self._active_custom_strategy is None)
        act_none.triggered.connect(lambda: self._set_custom_strategy(None))

        if strategies:
            menu.addSeparator()
            for s in strategies:
                icon = s.get("icon", "🎯")
                name = s.get("name", "?")
                act = menu.addAction(f"{icon}  {name}")
                act.setCheckable(True)
                act.setChecked(
                    self._active_custom_strategy is not None
                    and self._active_custom_strategy.get("id") == s.get("id")
                )
                act.triggered.connect(lambda checked, strat=s: self._set_custom_strategy(strat))
        else:
            menu.addSeparator()
            act_open = menu.addAction(tr("⚙  Создать стратегии в Настройках…"))
            act_open.triggered.connect(self._open_settings)

        menu.exec(self._btn_custom_strat.mapToGlobal(
            self._btn_custom_strat.rect().bottomLeft()
        ))

    def _set_custom_strategy(self, strat: dict | None):
        self._active_custom_strategy = strat
        if strat:
            icon = strat.get("icon", "🎯")
            name = strat.get("name", "")
            self._btn_custom_strat.setText(f"{icon} {name[:8]}")
            self._btn_custom_strat.setStyleSheet(
                "QPushButton{background:#1A2A1A;border:1px solid #9ECE6A;border-radius:4px;color:#9ECE6A;padding:2px 6px;font-size:11px;}QPushButton:hover{background:#1E351E;}"
            )
            self._btn_custom_strat.setToolTip(f"Кастомная стратегия: {name}\n{strat.get('description','')}")
        else:
            self._btn_custom_strat.setText(tr("✏ Свои"))
            self._btn_custom_strat.setStyleSheet(
                "QPushButton{background:#1E2030;border:1px solid #2E3148;border-radius:4px;color:#A9B1D6;padding:2px 6px;font-size:11px;}QPushButton:hover{background:#2E3148;color:#BB9AF7;}"
            )
            self._btn_custom_strat.setToolTip(tr("Выбрать кастомную стратегию из сохранённых"))
        total = len(self._settings.models)
        sel = len(self._consensus_model_ids) if self._consensus_model_ids else total
        self._btn_consensus_models.setText(f"⚙ {sel}/{total} {tr('мод.')}")

    def _pick_consensus_models(self):
        """Open model selection dialog for consensus."""
        from PyQt6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QVBoxLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Модели для консенсуса"))
        dlg.setMinimumWidth(340)
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        info = QLabel(
            tr("Выбери модели для участия в консенсусе.\nЕсли ничего не выбрано — используются все модели.")
        )
        info.setStyleSheet("color:#565f89;font-size:11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget{background:#131722;border:1px solid #1E2030;border-radius:6px;}QListWidget::item{padding:6px 10px;border-bottom:1px solid #1A1E2E;}QListWidget::item:selected{background:#2E3148;}"
        )
        from PyQt6.QtWidgets import QListWidgetItem as LWI
        for m in self._settings.models:
            item = LWI(f"{m.display_name}  [{m.source_type.value}]")
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = (not self._consensus_model_ids or m.id in self._consensus_model_ids)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            lst.addItem(item)
        layout.addWidget(lst)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec():
            selected = [
                lst.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked
            ]
            # All selected → store empty (means "all")
            self._consensus_model_ids = [] if len(selected) == len(self._settings.models) else selected
            self._update_consensus_btn_label()

    # ── Patches Panel ──────────────────────────────────────

    def _build_patches_panel(self) -> QWidget:
        panel = QFrame(); panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QFrame(); hdr.setObjectName("panelHeader"); hdr.setFixedHeight(32)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        self._lbl_patches_header = QLabel(tr("ПАТЧИ AI")); self._lbl_patches_header.setObjectName("sectionLabel")
        self._lbl_patch_count = QLabel(tr("0 патчей"))
        self._lbl_patch_count.setStyleSheet("color:#E0AF68;font-size:11px;")
        self._btn_apply_all = QPushButton(tr("✓ Все")); self._btn_apply_all.setObjectName("successBtn")
        self._btn_apply_all.setFixedWidth(55); self._btn_apply_all.setToolTip(tr("Применить все"))
        self._btn_apply_all.clicked.connect(self._apply_all_patches)
        btn_clr = QPushButton("✕"); btn_clr.setObjectName("dangerBtn")
        btn_clr.setFixedWidth(28); btn_clr.setToolTip(tr("Очистить список"))
        btn_clr.clicked.connect(self._clear_patches)
        hl.addWidget(self._lbl_patches_header); hl.addStretch()
        hl.addWidget(self._lbl_patch_count)
        hl.addWidget(self._btn_apply_all); hl.addWidget(btn_clr)
        layout.addWidget(hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._patches_container = QWidget()
        self._patches_layout = QVBoxLayout(self._patches_container)
        self._patches_layout.setContentsMargins(6, 6, 6, 6)
        self._patches_layout.setSpacing(6)
        self._patches_layout.addStretch()

        scroll.setWidget(self._patches_container)
        layout.addWidget(scroll, stretch=1)

        self._empty_patches = QLabel(tr("🔍\n\nПатчей нет\nОтправь запрос AI"))
        self._empty_patches.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_patches.setStyleSheet("color:#2E3148;font-size:13px;padding:30px;")
        layout.addWidget(self._empty_patches)

        # Register language listener for this panel
        register_listener(self._retranslate_patches_panel)
        register_listener(lambda lang: self._retranslate_consensus_items())
        register_listener(lambda lang: self._retranslate_static_labels())

        return panel

    def _retranslate_patches_panel(self, _lang: str = "") -> None:
        """Update patches panel labels when language changes."""
        self._lbl_patches_header.setText(tr("ПАТЧИ AI"))
        self._btn_apply_all.setText(tr("✓ Все"))
        self._empty_patches.setText(tr("🔍\n\nПатчей нет\nОтправь запрос AI"))
        # Patch count label — preserve number
        count = len(self._patches)
        if count == 0:
            self._lbl_patch_count.setText(tr("0 патчей"))
        else:
            self._lbl_patch_count.setText(f"{count} {tr('патч(ей)')}")

    # ── Status Bar ─────────────────────────────────────────

    def _build_status_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("statusBar"); bar.setFixedHeight(22)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)

        # Re-use the pre-created label (created in __init__ to avoid order issues)
        layout.addWidget(self._lbl_status_left)
        layout.addStretch()

        self._lbl_status_model = QLabel(tr("нет модели"))
        self._lbl_status_model.setStyleSheet("color:#7AA2F7;font-size:11px;")
        layout.addWidget(self._lbl_status_model)

        self._lbl_status_right = QLabel("Ln 1, Col 1")
        self._lbl_status_right.setObjectName("statusLabel")
        layout.addWidget(self._lbl_status_right)
        return bar

    # ══════════════════════════════════════════════════════
    #  CONNECT SIGNALS
    # ══════════════════════════════════════════════════════

    def _connect_signals(self):
        ws = self._worker_signals
        ws.chunk.connect(self._on_ai_chunk)
        ws.finished.connect(self._on_ai_finished)
        ws.patches.connect(self._on_patches_received)
        ws.error.connect(self._on_ai_error)
        ws.status.connect(self._on_status_update)
        ws.new_variant.connect(self._on_new_variant)

        self._logger.subscribe(self._on_log_entry)

        self._signal_monitor.status_changed.connect(self._on_signal_status)
        self._signal_monitor.event_received.connect(self._on_signal_event)

    # ══════════════════════════════════════════════════════
    #  INITIALIZATION
    # ══════════════════════════════════════════════════════

    def _load_settings(self):
        self._settings = self._model_manager.load()

        self._cmb_model.blockSignals(True)
        self._cmb_model.clear()
        for m in self._settings.models:
            self._cmb_model.addItem(m.display_name, m.id)
        self._cmb_model.blockSignals(False)

        if self._settings.default_model_id:
            for i in range(self._cmb_model.count()):
                if self._cmb_model.itemData(i) == self._settings.default_model_id:
                    self._cmb_model.setCurrentIndex(i)
                    break

        self._btn_sherlock.setChecked(self._settings.sherlock_mode_enabled)
        self._btn_send_logs.setChecked(self._settings.send_logs_to_ai)

        # Restore geometry
        geo = self._settings.window_geometry
        if geo:
            try:
                self.resize(geo.get("w", 1600), geo.get("h", 900))
                self.move(geo.get("x", 100), geo.get("y", 100))
            except Exception:
                pass

        if self._settings.models:
            idx = self._cmb_model.currentIndex()
            if 0 <= idx < len(self._settings.models):
                self._activate_model(self._settings.models[idx])

        self._logger.info(tr("AI Code Sherlock инициализирован"), source="App")
        self._add_system_message(
            tr("AI Code Sherlock готов к работе.\nОткрой проект (📁) или файл (📄), выбери модель и начни работу.")
        )

    def _activate_model(self, model: ModelDefinition):
        async def _switch():
            try:
                await self._model_manager.switch_model(model)
                self._rebuild_services()
                self._worker_signals.status.emit(f"Модель: {model.display_name}")
                ok = await self._model_manager.active_provider.is_available()
                c = "#9ECE6A" if ok else "#E0AF68"
                self._lbl_model_status.setStyleSheet(f"color:{c};font-size:14px;")
                self._lbl_status_model.setText(model.display_name)
            except Exception as e:
                self._worker_signals.error.emit(f"Ошибка активации модели: {e}")

        self._pool.start(AiWorker(lambda: _switch(), AiWorkerSignals()))

    def _rebuild_services(self):
        if self._model_manager.active_provider:
            self._compressor = ContextCompressor(
                self._model_manager.active_provider, self._prompt_engine, self._logger
            )
            self._sherlock = SherlockAnalyzer(
                self._model_manager, self._compressor,
                self._prompt_engine, self._patch_engine, self._logger
            )
            # Rebuild auto-improve engine with new model
            self._auto_engine = AutoImproveEngine(
                model_manager=self._model_manager,
                patch_engine=self._patch_engine,
                prompt_engine=self._prompt_engine,
                version_ctrl=self._version_ctrl,
                error_map=self._error_map,
                logger=self._logger,
            )
            if hasattr(self, "_auto_run_panel"):
                self._auto_run_panel._engine = self._auto_engine

    # ══════════════════════════════════════════════════════
    #  SEND MESSAGE
    # ══════════════════════════════════════════════════════

    def _send_message(self):
        if self._is_processing:
            return
        user_text = self._input_box.toPlainText().strip()
        if not user_text:
            return
        if not self._model_manager.active_provider:
            QMessageBox.warning(self, tr("Нет модели"),
                tr("Настрой модель через ⚙ перед отправкой."))
            return

        # Auto-record error if sherlock + logs
        if self._btn_sherlock.isChecked():
            logs = self._logger.format_for_ai()
            if logs:
                self._error_map.record_error(logs[:500], file_path=self._active_file or "")

        self._input_box.clear()
        self._add_user_message(user_text)
        self._set_processing(True, tr("Обработка..."))

        sherlock   = self._btn_sherlock.isChecked()
        send_logs  = self._btn_send_logs.isChecked() or self._chk_include_logs.isChecked()
        context    = self._build_context()
        if send_logs:
            context.error_logs = self._logger.format_for_ai()
        signals    = self._worker_signals

        # Read UI strategy / consensus / variants
        chat_strategy = ""
        try:
            chat_strategy = self._cmb_chat_strategy.currentData() or ""
        except Exception:
            pass
        use_consensus = False
        try:
            use_consensus = self._chk_consensus.isChecked()
        except Exception:
            pass
        n_variants = 1
        try:
            n_variants = max(1, self._spn_variants.value())
        except Exception:
            pass
        consensus_mode_val = ""
        try:
            consensus_mode_val = self._cmb_consensus_mode.currentData() or ""
        except Exception:
            pass
        # Custom strategy overrides standard strategy
        custom_strategy_prompt = ""
        try:
            if self._active_custom_strategy:
                custom_strategy_prompt = self._active_custom_strategy.get("system_prompt", "")
                custom_strategy_name   = self._active_custom_strategy.get("name", "")
        except Exception:
            pass
        # New settings
        do_compress    = getattr(self._settings, "compress_context", True)
        max_history    = getattr(self._settings, "max_conversation_history", 12)
        full_logs      = getattr(self._settings, "include_full_logs", False)

        if sherlock and context.error_logs:
            async def _sherlock_task():
                if not self._sherlock:
                    signals.error.emit(tr("SherlockAnalyzer не инициализирован."))
                    return
                req = SherlockRequest(
                    error_logs=context.error_logs or "",
                    context=context, user_hint=user_text
                )
                signals.status.emit(tr("🔍 Шерлок анализирует..."))
                result = await self._sherlock.analyze(req, signals.status.emit)
                full = self._response_filter.filter(result.analysis).filtered
                signals.patches.emit(result.patches)
                signals.finished.emit(full)
            self._pool.start(AiWorker(_sherlock_task, signals))

        elif use_consensus and self._model_manager:
            # ── Consensus mode ────────────────────────────────
            async def _consensus_task():
                if not self._model_manager.active_provider:
                    signals.error.emit(tr("Нет активной модели")); return

                signals.status.emit(tr("Консенсус: сжимаю контекст..."))
                if do_compress and self._compressor and context.files:
                    budget = TokenBudget(max_tokens=(
                        self._model_manager.active_model.max_context_tokens
                        if self._model_manager.active_model else 8192))
                    compressed = await self._compressor.compress(context, budget)
                else:
                    compressed = context

                if full_logs and self._btn_send_logs.isChecked():
                    compressed.error_logs = self._logger.format_for_ai(max_entries=500)

                system = self._prompt_engine.build_system_prompt(False)
                system += self._project_mgr.get_mode_system_addon()
                err_ctx = self._error_map.build_context_block(context.error_logs or "")
                if err_ctx:
                    system += f"\n\n{err_ctx}"

                if custom_strategy_prompt:
                    system += (
                        f"\n\n## КАСТОМНАЯ СТРАТЕГИЯ AI\n"
                        f"{custom_strategy_prompt}\n"
                        f"Строго следуй этим инструкциям."
                    )
                elif chat_strategy:
                    try:
                        from services.pipeline_models import AIStrategy, AI_STRATEGY_DESCRIPTIONS
                        strat_desc = AI_STRATEGY_DESCRIPTIONS.get(AIStrategy(chat_strategy), "")
                        if strat_desc:
                            system += f"\n\n## СТРАТЕГИЯ: {chat_strategy.upper()}\n{strat_desc}"
                    except Exception:
                        pass

                user_prompt = self._prompt_engine.build_analysis_prompt(user_text, compressed)

                try:
                    from services.consensus_engine import ConsensusEngine
                    from services.pipeline_models import ConsensusConfig, ConsensusMode
                    mode = ConsensusMode(consensus_mode_val) if consensus_mode_val else ConsensusMode.BEST_OF_N
                    all_model_ids = [m.id for m in self._settings.models]
                    model_ids = self._consensus_model_ids if self._consensus_model_ids else all_model_ids
                    if not model_ids:
                        signals.error.emit(tr("Нет моделей для консенсуса. Добавь модели в настройках.")); return

                    cfg = ConsensusConfig(
                        enabled=True,
                        model_ids=model_ids,
                        mode=mode,
                        min_agreement=max(2, len(model_ids) // 2),
                        timeout_per_model=120,
                    )
                    engine = ConsensusEngine(
                        model_manager=self._model_manager,
                        patch_engine=self._patch_engine,
                        logger=self._logger,
                    )
                    signals.status.emit(f"Консенсус [{mode.value}] — опрашиваю {len(model_ids)} моделей...")
                    result = await engine.run(cfg, system, user_prompt)

                    full = self._response_filter.filter(result.final_response).filtered
                    if result.final_patches:
                        signals.patches.emit(result.final_patches)
                    full = f"**🤝 Консенсус [{mode.value}]:** {result.notes}\n\n{full}"
                    self._conversation.append(ChatMessage(role=MessageRole.USER, content=user_text))
                    self._conversation.append(ChatMessage(role=MessageRole.ASSISTANT, content=full))
                    signals.finished.emit(full)
                except ImportError:
                    signals.error.emit(tr("ConsensusEngine недоступен. Проверь services/consensus_engine.py"))
                except Exception as e:
                    signals.error.emit(f"Ошибка консенсуса: {e}")

            self._pool.start(AiWorker(_consensus_task, signals))

        else:
            # ── Standard stream (with optional multiple variants) ──
            async def _stream_task():
                if not self._model_manager.active_provider:
                    signals.error.emit(tr("Нет активной модели")); return

                signals.status.emit(tr("Сжимаю контекст..."))
                if do_compress and self._compressor and context.files:
                    budget = TokenBudget(max_tokens=(
                        self._model_manager.active_model.max_context_tokens
                        if self._model_manager.active_model else 8192))
                    compressed = await self._compressor.compress(context, budget)
                else:
                    compressed = context

                # Override log content if full_logs requested
                if full_logs and self._btn_send_logs.isChecked():
                    compressed.error_logs = self._logger.format_for_ai(max_entries=500)

                self._update_context_view(compressed)

                system = self._prompt_engine.build_system_prompt(False)
                system += self._project_mgr.get_mode_system_addon()
                err_ctx = self._error_map.build_context_block(context.error_logs or "")
                if err_ctx:
                    system += f"\n\n{err_ctx}"

                # Custom strategy overrides standard strategy
                if custom_strategy_prompt:
                    system += (
                        f"\n\n## КАСТОМНАЯ СТРАТЕГИЯ AI\n"
                        f"{custom_strategy_prompt}\n"
                        f"Строго следуй этим инструкциям при формировании ответа."
                    )
                elif chat_strategy:
                    try:
                        from services.pipeline_models import AIStrategy, AI_STRATEGY_DESCRIPTIONS
                        strat_desc = AI_STRATEGY_DESCRIPTIONS.get(AIStrategy(chat_strategy), "")
                        if strat_desc:
                            system += (
                                f"\n\n## АКТИВНАЯ СТРАТЕГИЯ: {chat_strategy.upper()}\n"
                                f"{strat_desc}\n"
                                f"Применяй эту стратегию при формировании ответа и патчей."
                            )
                    except Exception:
                        pass

                user_prompt = self._prompt_engine.build_analysis_prompt(user_text, compressed)
                base_messages = [
                    ChatMessage(role=MessageRole.SYSTEM, content=system),
                    *self._conversation[-max_history:],
                    ChatMessage(role=MessageRole.USER, content=user_prompt),
                ]
                self._conversation.append(ChatMessage(role=MessageRole.USER, content=user_text))

                for variant_idx in range(n_variants):
                    if n_variants > 1:
                        signals.status.emit(f"Вариант {variant_idx + 1}/{n_variants}...")
                        if variant_idx > 0:
                            extra = ChatMessage(
                                role=MessageRole.USER,
                                content=(
                                    f"Дай другой вариант ответа (вариант {variant_idx + 1}). "
                                    f"Подход должен отличаться от предыдущего."
                                )
                            )
                            messages = base_messages + [extra]
                        else:
                            variant_msg = ChatMessage(
                                role=MessageRole.SYSTEM,
                                content=(
                                    f"Пользователь запросил {n_variants} независимых вариантов ответа. "
                                    f"Это ВАРИАНТ 1. Дай конкретный, самостоятельный ответ."
                                )
                            )
                            messages = base_messages + [variant_msg]
                    else:
                        messages = base_messages
                        signals.status.emit(tr("Генерирую ответ..."))

                    full_chunks: list[str] = []
                    async for chunk in self._model_manager.active_provider.stream(messages):
                        clean = self._response_filter.filter(chunk).filtered
                        full_chunks.append(clean)
                        signals.chunk.emit(clean)

                    full = "".join(full_chunks)
                    full = self._response_filter.filter(full).filtered
                    patches = self._patch_engine.parse_patches(full)
                    if patches:
                        signals.patches.emit(patches)
                    self._conversation.append(ChatMessage(role=MessageRole.ASSISTANT, content=full))

                    if variant_idx < n_variants - 1:
                        signals.finished.emit(full)
                        import asyncio as _aio
                        await _aio.sleep(0.15)
                        signals.new_variant.emit(variant_idx + 2, n_variants)
                        await _aio.sleep(0.05)
                    else:
                        signals.finished.emit(full)

            self._pool.start(AiWorker(_stream_task, signals))

    # ══════════════════════════════════════════════════════
    #  AI RESPONSE SLOTS
    # ══════════════════════════════════════════════════════

    def _on_ai_chunk(self, token: str):
        if self._current_stream_edit and token:
            cursor = self._current_stream_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(token)
            self._current_stream_edit.setTextCursor(cursor)
            self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum())

    def _on_ai_finished(self, _full: str):
        self._current_stream_edit = None
        self._set_processing(False)

    def _on_new_variant(self, current: int, total: int):
        """Close current streaming bubble and open a fresh one for next variant."""
        self._current_stream_edit = None
        # Re-open a new streaming bubble (keep processing=True)
        self._current_stream_edit = self._add_assistant_message_streaming()
        self._lbl_processing.setText(f"⟳ {tr('Вариант')} {current}/{total}...")
        self._center_tabs.setCurrentIndex(0)

    def _on_patches_received(self, patches: list):
        for p in patches:
            self._add_patch_card(p)

    def _on_ai_error(self, err: str):
        self._set_processing(False)
        self._add_error_message(err)
        self._logger.error(err, source="AI")

    def _on_status_update(self, msg: str):
        self._lbl_status_left.setText(msg)
        if self._is_processing:
            self._lbl_processing.setText(f"⟳ {msg}")

    # ══════════════════════════════════════════════════════
    #  CHAT BUBBLES
    # ══════════════════════════════════════════════════════

    # ── Save AI response as file ────────────────────────────────────────────────

    # Language extension map for guessing file type from markdown code fences
    _LANG_EXT: dict[str, str] = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "jsx": ".jsx", "tsx": ".tsx",
        "go": ".go", "golang": ".go",
        "rust": ".rs", "rs": ".rs",
        "java": ".java",
        "csharp": ".cs", "cs": ".cs",
        "cpp": ".cpp", "c++": ".cpp",
        "c": ".c",
        "bash": ".sh", "shell": ".sh", "sh": ".sh",
        "sql": ".sql",
        "html": ".html", "css": ".css",
        "json": ".json", "yaml": ".yaml", "yml": ".yml",
        "toml": ".toml", "xml": ".xml", "markdown": ".md", "md": ".md",
    }

    def _save_ai_response_as_file(self, editor: "QPlainTextEdit"):
        """Extract code from AI response and save it as a new file."""
        import re as _re
        text = editor.toPlainText().strip()
        if not text:
            return

        # Detect language from first fenced block
        lang_match = _re.search(r"```(\w+)\n", text)
        lang = lang_match.group(1).lower() if lang_match else ""
        ext = self._LANG_EXT.get(lang, ".py")

        # Extract code: prefer content of first code fence, else raw text
        code_match = _re.search(r"```(?:\w+)?\n(.*?)```", text, _re.DOTALL)
        code = code_match.group(1).strip() if code_match else text

        # Suggest default path
        project_root = (self._project_mgr.state.project_root
                        if self._project_mgr.state else "")
        default_name = f"script{ext}"
        start_path = os.path.join(project_root, default_name) if project_root else default_name

        # Build filter string
        _ext_filters = {
            ".py": "Python (*.py)", ".js": "JavaScript (*.js)",
            ".ts": "TypeScript (*.ts)", ".go": "Go (*.go)",
            ".rs": "Rust (*.rs)", ".java": "Java (*.java)",
            ".cs": "C# (*.cs)", ".cpp": "C++ (*.cpp)",
            ".sh": "Shell (*.sh)", ".sql": "SQL (*.sql)",
            ".html": "HTML (*.html)", ".json": "JSON (*.json)",
        }
        primary = _ext_filters.get(ext, f"(*{ext})")
        filters = f"{primary};;All files (*.*)"

        path, _ = QFileDialog.getSaveFileName(
            self, tr("Сохранить код как файл"), start_path, filters
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            self._load_file(path)
            self._add_system_message(
                f"✅ {tr('Файл создан')} → `{Path(path).name}`"
            )
        except Exception as e:
            self._add_error_message(f"{tr('Ошибка')}: {e}")

    def _add_user_message(self, text: str):
        self._insert_bubble(text, "user")

    def _add_assistant_message_streaming(self) -> QPlainTextEdit:
        model_name = (self._model_manager.active_model.display_name
                      if self._model_manager.active_model else "AI")
        frame = QFrame()
        frame.setObjectName("assistantBubble")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        fl = QVBoxLayout(frame); fl.setContentsMargins(12, 8, 12, 8); fl.setSpacing(4)

        hdr = QHBoxLayout()
        rl = QLabel(f"{tr('Шерлок')}  •  {model_name}")
        rl.setStyleSheet("color:#9ECE6A;font-size:11px;font-weight:bold;")
        hdr.addWidget(rl)
        hdr.addStretch()

        # "Save as file" button — lets the user save AI-generated code directly
        btn_save = QPushButton(tr("💾 Сохранить как файл"))
        btn_save.setObjectName("iconBtn")
        btn_save.setStyleSheet(
            "QPushButton{background:#1A2A1A;border:1px solid #9ECE6A;border-radius:4px;"
            "color:#9ECE6A;font-size:10px;padding:2px 8px;}"
            "QPushButton:hover{background:#1E351E;color:#B8E07A;}"
        )
        btn_save.setToolTip(tr("Сохранить ответ AI как новый файл"))
        hdr.addWidget(btn_save)
        fl.addLayout(hdr)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setFrameShape(QFrame.Shape.NoFrame)
        editor.setStyleSheet("background:transparent;color:#CDD6F4;font-size:13px;border:none;")
        editor.setFont(QFont("Segoe UI,Arial", 12))
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        fl.addWidget(editor)

        # Connect button after editor is created
        btn_save.clicked.connect(lambda: self._save_ai_response_as_file(editor))

        count = self._chat_layout.count()
        self._chat_layout.insertWidget(count - 1, frame)
        self._scroll_to_bottom()
        return editor

    def _add_system_message(self, text: str):
        self._insert_bubble(text, "system")

    def _add_error_message(self, text: str):
        self._insert_bubble(f"❌ {text}", "error")

    def _insert_bubble(self, text: str, role: str):
        colors = {"user":"#7AA2F7", "assistant":"#9ECE6A",
                  "system":"#9D7CD8", "error":"#F7768E"}
        names  = {"user":tr("Вы"), "assistant":tr("Шерлок"),
                  "system":tr("Система"), "error":tr("Ошибка")}
        obj_ids = {"user":"userBubble", "assistant":"assistantBubble",
                   "system":"systemBubble", "error":"errorBubble"}

        frame = QFrame()
        frame.setObjectName(obj_ids.get(role, "systemBubble"))
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        fl = QVBoxLayout(frame); fl.setContentsMargins(12, 8, 12, 8); fl.setSpacing(4)

        hdr = QHBoxLayout()
        rl = QLabel(names.get(role, role))
        rl.setStyleSheet(f"color:{colors.get(role,'#CDD6F4')};font-size:11px;font-weight:bold;")
        hdr.addWidget(rl); hdr.addStretch()
        fl.addLayout(hdr)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet("font-size:13px;color:#CDD6F4;")
        fl.addWidget(lbl)

        count = self._chat_layout.count()
        self._chat_layout.insertWidget(count - 1, frame)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        QTimer.singleShot(40, lambda:
            self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum()))

    # ══════════════════════════════════════════════════════
    #  PATCH MANAGEMENT
    # ══════════════════════════════════════════════════════

    def _add_patch_card(self, patch: PatchBlock):
        self._empty_patches.hide()
        card = PatchCard(patch, len(self._patches))
        card.apply_requested.connect(self._apply_patch)
        card.reject_requested.connect(lambda p: None)
        card.preview_requested.connect(self._preview_patch)
        count = self._patches_layout.count()
        self._patches_layout.insertWidget(count - 1, card)
        self._patches.append(card)
        self._lbl_patch_count.setText(f"{len(self._patches)} {tr('патч(ей)')}")

    # ── New-file creation detection ────────────────────────

    @staticmethod
    def _is_new_file_patch(search_content: str, replace_content: str) -> bool:
        """True when the patch creates a brand-new file (search is empty or placeholder)."""
        if not replace_content.strip():
            return False
        stripped = search_content.strip()
        if not stripped:
            return True   # explicitly empty SEARCH_BLOCK
        # engine.parse_patches already normalises placeholder strings to "",
        # but keep a fallback set here for safety
        _PLACEHOLDERS = {
            "## релевантный код", "## relevant code",
            "## код проекта", "## project code",
        }
        return stripped.lower() in _PLACEHOLDERS

    def _apply_patch(self, patch: PatchBlock):
        # Resolve which file this patch targets
        target_file = self._active_file

        # If patch has explicit file_path, try to match against known open/patch-target files
        if patch.file_path:
            patch_fname = Path(patch.file_path).name.lower()
            # 1. Exact match in patch targets
            for p in self._get_all_patch_targets():
                if Path(p).name.lower() == patch_fname or p == patch.file_path:
                    target_file = p
                    break
            # 2. Partial match in open files
            if target_file == self._active_file:
                for p in self._open_files:
                    if Path(p).name.lower() == patch_fname:
                        target_file = p
                        break

        if not target_file:
            # ── Auto-create file when AI specifies a file_path (NEW PROJECT) ──
            if patch.file_path:
                project_root = (self._project_mgr.state.project_root
                                if self._project_mgr.state else None)
                candidate = patch.file_path
                # Resolve relative path against project root
                if project_root and not os.path.isabs(candidate):
                    candidate = os.path.join(project_root, candidate)
                try:
                    Path(candidate).parent.mkdir(parents=True, exist_ok=True)
                    if not os.path.exists(candidate):
                        Path(candidate).write_text("", encoding="utf-8")
                    self._load_file(candidate)
                    target_file = candidate
                except Exception as e:
                    self._add_error_message(
                        f"{tr('Не удалось создать файл')} {Path(candidate).name}: {e}"
                    )
                    return
            else:
                self._add_error_message(tr("Нет активного файла для патча."))
                return

        content = self._open_files.get(target_file, "")
        if not content and target_file:
            try:
                with open(target_file, "r", encoding="utf-8", errors="replace") as _f:
                    content = _f.read()
                self._open_files[target_file] = content
            except Exception:
                pass

        # ── New-file creation: empty search → write replace_content directly ──
        clean_replace = self._response_filter.filter_patch_blocks(patch.replace_content)
        if self._is_new_file_patch(patch.search_content, clean_replace):
            try:
                self._version_ctrl.backup_file(
                    target_file,
                    description=patch.description or "new file",
                    patch_search="",
                    patch_replace=clean_replace,
                )
                self._open_files[target_file] = clean_replace
                if target_file == self._active_file:
                    self._refresh_editor_content(clean_replace)
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(clean_replace)
                for c in self._patches:
                    if c.patch is patch:
                        c.set_status(PatchStatus.APPLIED)
                name = Path(target_file).name
                self._add_system_message(
                    f"✅ {tr('Файл создан')} → `{name}`"
                )
                self._update_context_tokens()
                self._file_tree._refresh()
            except Exception as e:
                for c in self._patches:
                    if c.patch is patch:
                        c.set_status(PatchStatus.FAILED, str(e))
                self._add_error_message(f"Ошибка создания файла: {e}")
            return

        # Filter invisible chars in patch blocks
        clean_patch = PatchBlock(
            search_content  = self._response_filter.filter_patch_blocks(patch.search_content),
            replace_content = clean_replace,
            file_path=patch.file_path, description=patch.description,
        )

        v = self._patch_engine.validate(content, clean_patch)
        if not v.is_valid:
            # If not found in resolved target, try active file as fallback
            if target_file != self._active_file and self._active_file:
                fallback_content = self._open_files.get(self._active_file, "")
                v2 = self._patch_engine.validate(fallback_content, clean_patch)
                if v2.is_valid:
                    target_file = self._active_file
                    content = fallback_content
                    v = v2
                else:
                    QMessageBox.warning(self, tr("Патч не применён"),
                        f"Файл цели: {Path(target_file).name}\n"
                        f"Блок не найден:\n\n{v.error_message}\n\nВхождений: {v.match_count}")
                    for c in self._patches:
                        if c.patch is patch: c.set_status(PatchStatus.FAILED, v.error_message or "")
                    return
            else:
                QMessageBox.warning(self, tr("Патч не применён"),
                    f"Блок не найден в файле:\n\n{v.error_message}\n\nВхождений: {v.match_count}")
                for c in self._patches:
                    if c.patch is patch: c.set_status(PatchStatus.FAILED, v.error_message or "")
                return

        try:
            # Backup before modify
            version = self._version_ctrl.backup_file(
                target_file,
                description=patch.description or "patch",
                patch_search=clean_patch.search_content,
                patch_replace=clean_patch.replace_content,
            )

            patched = self._patch_engine.apply_patch(content, clean_patch)
            self._open_files[target_file] = patched

            # Refresh editor if this is the currently visible file
            if target_file == self._active_file:
                self._refresh_editor_content(patched)

            with open(target_file, "w", encoding="utf-8") as f:
                f.write(patched)
            self._version_ctrl.update_lines_after(version, patched)

            # Auto-resolve open error
            open_errs = self._error_map.get_open_errors()
            if open_errs and self._btn_sherlock.isChecked():
                self._error_map.mark_resolved(
                    open_errs[0].error_id, solution=tr("Патч применён"),
                    patch_search=clean_patch.search_content,
                    patch_replace=clean_patch.replace_content)

            for c in self._patches:
                if c.patch is patch: c.set_status(PatchStatus.APPLIED)

            name = Path(target_file).name
            self._add_system_message(f"✅ {tr('Патч применён')} → `{name}` ({tr('резервная копия сохранена')})")
            self._update_context_tokens()

        except Exception as e:
            for c in self._patches:
                if c.patch is patch: c.set_status(PatchStatus.FAILED, str(e))
            self._add_error_message(f"Ошибка патча: {e}")

    def _apply_all_patches(self):
        for c in list(self._patches):
            if c._status == PatchStatus.PENDING:
                self._apply_patch(c.patch)

    def _clear_patches(self):
        for c in list(self._patches):
            self._patches_layout.removeWidget(c)
            c.deleteLater()
        self._patches.clear()
        self._lbl_patch_count.setText(tr("0 патчей"))
        self._empty_patches.show()

    def _preview_patch(self, patch: PatchBlock):
        dlg = PatchPreviewDialog(
            patch.search_content, patch.replace_content,
            file_path=Path(self._active_file).name if self._active_file else "",
            parent=self)
        dlg.exec()

    # ══════════════════════════════════════════════════════
    #  FILE MANAGEMENT
    # ══════════════════════════════════════════════════════

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Открыть файл"), "",
            "Code Files (*.py *.js *.ts *.java *.go *.rs *.cs *.cpp *.c *.h *.json *.yaml *.yml *.xml *.md *.sql *.rb *.php *.sh);;All (*)")
        if path: self._load_file(path)

    def _open_project(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Открыть папку проекта"))
        if not folder: return
        self._load_project(folder)

    def _load_project(self, folder: str):
        state = self._project_mgr.open_project(folder)
        self._version_ctrl.set_project_root(folder)
        self._error_map.set_project_root(folder)
        self._file_tree.load_folder(folder)

        all_files = state.tracked_files
        total = len(all_files)

        # Ask user how many files to open
        default_limit = 12
        load_all = False

        if total > default_limit:
            # Count files in subdirs vs root
            root_files = [f for f in all_files if Path(f).parent == Path(folder)]
            sub_files  = [f for f in all_files if Path(f).parent != Path(folder)]

            msg = (
                f"{tr('В проекте найдено')} <b>{total}</b> {tr('файлов кода.')} <br><br>"
                f"{tr('В корневой папке:')} <b>{len(root_files)}</b><br>"
                f"{tr('В подпапках:')} <b>{len(sub_files)}</b><br><br>"
                f"{tr('Открыть все файлы или только первые')} {default_limit}?"
            )
            box = QMessageBox(self)
            box.setWindowTitle(tr("Открыть файлы проекта"))
            box.setText(msg)
            box.setIcon(QMessageBox.Icon.Question)
            btn_all  = box.addButton(f"{tr('Открыть все')} ({total})", QMessageBox.ButtonRole.AcceptRole)
            btn_some = box.addButton(f"{tr('Только')} {default_limit}", QMessageBox.ButtonRole.NoRole)
            btn_pick = box.addButton(tr("Выбрать..."), QMessageBox.ButtonRole.HelpRole)
            box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
            box.exec()

            clicked = box.clickedButton()
            if clicked == btn_all:
                load_all = True
                files_to_load = all_files
            elif clicked == btn_pick:
                files_to_load = self._pick_project_files_dialog(all_files)
            elif clicked == btn_some:
                files_to_load = all_files[:default_limit]
            else:
                files_to_load = all_files[:default_limit]
        else:
            files_to_load = all_files

        loaded = 0
        for f in files_to_load:
            self._load_file(f)
            loaded += 1

        mode_txt = tr("🆕 Новый") if state.mode.value == "new_project" else tr("🔧 Существующий")
        self._btn_mode.setChecked(state.mode.value == "new_project")
        self._add_system_message(
            f"📁 {tr('Проект')}: **{state.name}**\n"
            f"{tr('Найдено файлов')}: {total} | {tr('Открыто')}: {loaded}\n"
            f"{tr('Режим')}: {mode_txt}"
        )
        self._lbl_status_left.setText(f"{tr('Проект')}: {state.name}")
        self._update_context_tokens()

    def _pick_project_files_dialog(self, all_files: list) -> list:
        """Show a checklist dialog for user to pick which project files to open."""
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Выбрать файлы для открытия"))
        dlg.setMinimumSize(500, 500)
        dlg.setModal(True)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(dlg)
        except Exception:
            pass

        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        info = QLabel(tr("Отметь файлы которые нужно открыть в редакторе:"))
        info.setStyleSheet("color:#A9B1D6;font-size:12px;")
        layout.addWidget(info)

        # Search filter
        search = QLabel("")
        from PyQt6.QtWidgets import QLineEdit as _LE
        fld = _LE(); fld.setPlaceholderText(tr("Поиск файлов..."))
        layout.addWidget(fld)

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget{background:#131722;border:1px solid #1E2030;border-radius:6px;}QListWidget::item{padding:4px 10px;border-bottom:1px solid #111520;}QListWidget::item:selected{background:#2E3148;}"
        )

        root = Path(all_files[0]).parent if all_files else Path(".")
        items_all = []
        for f in all_files:
            try:
                rel = Path(f).relative_to(root)
            except ValueError:
                rel = Path(f).name
            item = QListWidgetItem(str(rel))
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            lst.addItem(item)
            items_all.append(item)
        layout.addWidget(lst, stretch=1)

        def _filter(text):
            for it in items_all:
                it.setHidden(text.lower() not in it.text().lower())
        fld.textChanged.connect(_filter)

        # Select all / none row
        sel_row = QHBoxLayout()
        btn_all2 = QPushButton(tr("Выбрать все")); btn_all2.setFixedWidth(110)
        btn_none = QPushButton(tr("Снять все"));   btn_none.setFixedWidth(110)
        btn_all2.clicked.connect(lambda: [it.setCheckState(Qt.CheckState.Checked) for it in items_all])
        btn_none.clicked.connect(lambda: [it.setCheckState(Qt.CheckState.Unchecked) for it in items_all])
        sel_row.addWidget(btn_all2); sel_row.addWidget(btn_none); sel_row.addStretch()
        layout.addLayout(sel_row)

        footer = QHBoxLayout()
        btn_ok = QPushButton(tr("Открыть выбранные"))
        btn_ok.setObjectName("primaryBtn"); btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton(tr("Отмена")); btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(dlg.reject)
        footer.addStretch(); footer.addWidget(btn_cancel); footer.addWidget(btn_ok)
        layout.addLayout(footer)

        if dlg.exec():
            return [
                items_all[i].data(Qt.ItemDataRole.UserRole)
                for i in range(len(items_all))
                if items_all[i].checkState() == Qt.CheckState.Checked
                and not items_all[i].isHidden()
            ]
        return []

    def _new_project(self):
        from ui.dialogs.new_project_wizard import NewProjectWizard
        dlg = NewProjectWizard(parent=self)
        if dlg.exec():
            folder, name, mode = dlg.result_data()
            state = self._project_mgr.create_project(folder, name, mode)
            self._version_ctrl.set_project_root(folder)
            self._error_map.set_project_root(folder)
            self._file_tree.load_folder(folder)
            self._btn_mode.setChecked(mode.value == "new_project")
            mode_hint = tr(
                "💡 Опиши что нужно создать — AI сгенерирует файл(ы) нужного расширения автоматически.\n"
                "Например: «Создай main.py — скрипт для парсинга CSV» или «Создай index.js — Express сервер»"
            ) if mode.value == "new_project" else ""
            self._add_system_message(
                f"🆕 {tr('Новый проект создан')}: **{name}**\n"
                f"{tr('Папка')}: {folder}\n"
                + (f"\n{mode_hint}" if mode_hint else "")
            )

    def _load_file(self, path: str):
        if not os.path.isfile(path): return
        try:
            if path not in self._open_files:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._open_files[path] = content
                self._create_editor_tab(path, content)
            else:
                self._switch_to_tab(path)
            self._active_file = path
            self._lbl_active_file.setText(Path(path).name)
            self._file_tree.select_file(path)
            self._update_context_tokens()
            self._refresh_patch_target_chips()
        except Exception as e:
            self._add_error_message(f"Не удалось открыть {path}: {e}")

    def _create_editor_tab(self, path: str, content: str):
        """Create a full-featured CodeEditorPanel tab."""
        try:
            from ui.widgets.code_editor import CodeEditorPanel
            panel = CodeEditorPanel(path, content)
            panel.editor.modified_changed.connect(
                lambda modified, p=path: self._on_tab_modified(p, modified))
            panel.run_requested.connect(
                lambda fp: self._run_script_with_path(fp))
            panel.editor.cursor_pos_changed.connect(
                lambda ln, col: self._lbl_status_right.setText(f"Ln {ln}, Col {col}"))
            panel.editor.syntax_errors_changed.connect(
                lambda errs, p=path: self._on_syntax_errors(p, errs))
        except Exception:
            # Fallback: plain QPlainTextEdit
            from PyQt6.QtWidgets import QPlainTextEdit
            panel = QPlainTextEdit()
            panel.setProperty("file_path", path)
            panel.setFont(QFont("JetBrains Mono,Consolas", 12))
            panel.setPlainText(content)
            panel.setStyleSheet("background:#0D1117;color:#CDD6F4;border:none;")
            panel.textChanged.connect(lambda: self._on_tab_modified(path, True))

        name = Path(path).name
        idx = self._file_tabs.addTab(panel, name)
        self._file_tabs.setTabToolTip(idx, path)
        self._file_tabs.setCurrentIndex(idx)

    def _on_tab_modified(self, path: str, modified: bool):
        """Update tab title with ● indicator when modified."""
        self._open_files[path] = self._get_editor_content(path) or ""
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                name = Path(path).name
                current_text = self._file_tabs.tabText(i)
                has_dot = current_text.endswith(" ●")
                if modified and not has_dot:
                    self._file_tabs.setTabText(i, f"{name} ●")
                elif not modified and has_dot:
                    self._file_tabs.setTabText(i, name)
                break
        self._update_context_tokens()

    def _on_syntax_errors(self, path: str, errors: list):
        """Highlight tab title red if syntax errors exist."""
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                bar = self._file_tabs.tabBar()
                if errors:
                    bar.setTabTextColor(i, QColor("#F7768E"))
                else:
                    bar.setTabTextColor(i, QColor())  # reset to default
                break

    def _get_editor_content(self, path: str) -> str:
        """Get content from the editor widget for a given path."""
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                w = self._file_tabs.widget(i)
                if hasattr(w, "get_content"):
                    return w.get_content()
                elif hasattr(w, "toPlainText"):
                    return w.toPlainText()
        return self._open_files.get(path, "")

    def _run_script_with_path(self, path: str):
        """Run a specific script path."""
        self._active_file = path
        self._run_script_manually()

    # ── Tab Bar Context Menu ───────────────────────────────────────────────────

    def _tab_bar_context_menu(self, pos):
        from PyQt6.QtCore import QPoint
        bar = self._file_tabs.tabBar()
        clicked_idx = bar.tabAt(pos)
        menu = QMenu(self)

        if clicked_idx >= 0:
            path = self._file_tabs.tabToolTip(clicked_idx)
            name = Path(path).name if path else tr("файл")

            menu.addAction(f"💾 Сохранить  {name}", lambda: self._save_tab(clicked_idx))
            menu.addAction(f"✕ Закрыть  {name}",
                           lambda: self._close_file_tab(clicked_idx))
            menu.addSeparator()

        menu.addAction(tr("💾 Сохранить все"), self._save_all_tabs)
        menu.addAction(tr("✕ Закрыть все"), self._close_all_tabs)
        menu.addAction(tr("✕ Закрыть все кроме этого"),
                       lambda idx=clicked_idx: self._close_all_except(idx))
        menu.addAction(tr("✕✓ Закрыть несохранённые"), self._close_unsaved_tabs)
        menu.addSeparator()
        menu.addAction(tr("📋 Копировать путь"),
                       lambda: QApplication.clipboard().setText(
                           self._file_tabs.tabToolTip(clicked_idx)) if clicked_idx >= 0 else None)
        menu.addAction(tr("🤖 Отправить все открытые в AI"),
                       self._send_all_open_to_ai)
        menu.exec(self._file_tabs.tabBar().mapToGlobal(pos))

    def _refresh_editor_content(self, new_content: str):
        w = self._file_tabs.currentWidget()
        if hasattr(w, "editor"):  # CodeEditorPanel
            pos = w.editor.textCursor().position()
            w.editor.blockSignals(True)
            w.editor.setPlainText(new_content)
            w.editor.blockSignals(False)
            c = w.editor.textCursor()
            c.setPosition(min(pos, len(new_content)))
            w.editor.setTextCursor(c)
        elif isinstance(w, QPlainTextEdit):
            pos = w.textCursor().position()
            w.blockSignals(True)
            w.setPlainText(new_content)
            w.blockSignals(False)
            c = w.textCursor()
            c.setPosition(min(pos, len(new_content)))
            w.setTextCursor(c)

    def _close_file_tab(self, idx: int):
        w = self._file_tabs.widget(idx)
        path = self._file_tabs.tabToolTip(idx)

        # Check if modified
        is_mod = False
        if hasattr(w, "is_modified"):
            is_mod = w.is_modified
        elif hasattr(w, "document"):
            is_mod = w.document().isModified()

        if is_mod:
            name = Path(path).name if path else tr("файл")
            reply = QMessageBox.question(
                self, tr("Несохранённые изменения"),
                f"`{name}` содержит несохранённые изменения.\nСохранить перед закрытием?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._save_tab(idx)

        if path and path in self._open_files:
            del self._open_files[path]
        self._file_tabs.removeTab(idx)
        self._update_context_tokens()

    def _save_tab(self, idx: int):
        w = self._file_tabs.widget(idx)
        path = self._file_tabs.tabToolTip(idx)
        if not path: return
        content = (w.get_content() if hasattr(w, "get_content") else
                   w.toPlainText() if hasattr(w, "toPlainText") else "")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._open_files[path] = content
            # Remove ● from tab title
            name = Path(path).name
            self._file_tabs.setTabText(idx, name)
            self._file_tabs.tabBar().setTabTextColor(idx, QColor())  # reset error color
        except Exception as e:
            self._add_error_message(f"Ошибка сохранения {Path(path).name}: {e}")

    def _save_all_tabs(self):
        for i in range(self._file_tabs.count()):
            self._save_tab(i)
        self._add_system_message(f"💾 {tr('Сохранено вкладок')}: {self._file_tabs.count()}")

    def _close_all_tabs(self):
        reply = QMessageBox.question(
            self, tr("Закрыть все"),
            tr("Закрыть все открытые файлы?\nНесохранённые изменения будут потеряны."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._open_files.clear()
            self._file_tabs.clear()
            self._active_file = None
            self._patch_targets.clear()
            self._lbl_active_file.setText(tr("нет файла"))
            self._update_context_tokens()
            self._refresh_patch_target_chips()

    def _close_all_except(self, keep_idx: int):
        """Close all tabs except the one at keep_idx."""
        for i in range(self._file_tabs.count() - 1, -1, -1):
            if i != keep_idx:
                self._close_file_tab(i)
                # Adjust keep_idx if tabs shift
                if i < keep_idx:
                    keep_idx -= 1

    def _close_unsaved_tabs(self):
        """Close only tabs with unsaved changes (no prompt — discard)."""
        closed = 0
        for i in range(self._file_tabs.count() - 1, -1, -1):
            w = self._file_tabs.widget(i)
            is_mod = (w.is_modified if hasattr(w, "is_modified") else
                      w.document().isModified() if hasattr(w, "document") else False)
            if is_mod:
                path = self._file_tabs.tabToolTip(i)
                if path in self._open_files:
                    del self._open_files[path]
                self._file_tabs.removeTab(i)
                closed += 1
        self._add_system_message(f"✕ {tr('Закрыто несохранённых')}: {closed}")
        self._update_context_tokens()

    def _send_all_open_to_ai(self):
        """Send all open files' content to the AI input."""
        parts = []
        for i in range(self._file_tabs.count()):
            path = self._file_tabs.tabToolTip(i)
            content = self._open_files.get(path, "")[:1500]
            name = Path(path).name if path else f"файл {i+1}"
            parts.append(f"### `{name}`:\n```\n{content}\n```")
        if parts:
            self._input_box.setPlainText(
                tr("Проанализируй все открытые файлы:\n\n") + "\n\n".join(parts))

    def _on_tab_changed(self, idx: int):
        w = self._file_tabs.widget(idx)
        if w:
            path = self._file_tabs.tabToolTip(idx)
            if path:
                self._active_file = path
                self._lbl_active_file.setText(Path(path).name)
                # Sync content from widget
                self._open_files[path] = self._get_editor_content(path)
                self._refresh_patch_target_chips()

    def _switch_to_tab(self, path: str):
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                self._file_tabs.setCurrentIndex(i); return

    def _save_active_file(self):
        if not self._active_file: return
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == self._active_file:
                self._save_tab(i)
                self._lbl_status_left.setText(
                    f"💾 {tr('Сохранено')}: {Path(self._active_file).name}")
                return

    def _send_file_to_ai(self, path: str):
        content = self._open_files.get(path) or ""
        if not content:
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                return
        self._input_box.setText(
            f"Проанализируй этот файл:\n```\n{content[:3000]}\n```"
        )

    # ══════════════════════════════════════════════════════
    #  CONTEXT BUILDING
    # ══════════════════════════════════════════════════════

    def _build_context(self) -> ProjectContext:
        files = []
        inc_file = self._chk_include_file.isChecked()
        inc_all  = self._chk_include_all.isChecked()

        if inc_all and self._project_mgr.state:
            # Use project manager for smart skeleton context
            # include all patch targets as focused
            focused = self._get_all_patch_targets() if self._active_file else []
            budget = TokenBudget(max_tokens=(
                self._model_manager.active_model.max_context_tokens
                if self._model_manager.active_model else 8192))
            return self._project_mgr.build_context(focused, budget)

        if inc_file and self._active_file and self._active_file in self._open_files:
            files.append(FileEntry(
                path=self._active_file,
                relative_path=Path(self._active_file).name,
                content=self._open_files[self._active_file],
                extension=Path(self._active_file).suffix.lower(),
                is_focused=True,
            ))

        # Extra patch-target files — always included, marked focused
        for path in self._patch_targets:
            if path == self._active_file:
                continue
            content = self._open_files.get(path, "")
            if not content:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as _f:
                        content = _f.read()
                    self._open_files[path] = content
                except Exception:
                    content = ""
            files.append(FileEntry(
                path=path,
                relative_path=Path(path).name,
                content=content,
                extension=Path(path).suffix.lower(),
                is_focused=True,
            ))

        # Other open files (non-focused, up to 8)
        for path, content in list(self._open_files.items())[:8]:
            if path == self._active_file: continue
            if path in self._patch_targets: continue   # already added above
            files.append(FileEntry(
                path=path,
                relative_path=Path(path).name,
                content=content,
                extension=Path(path).suffix.lower(),
            ))

        return ProjectContext(
            files=files,
            focused_file_path=self._active_file,
        )

    def _update_context_tokens(self):
        total = sum(TokenBudget.estimate_tokens(c) for c in self._open_files.values())
        count = len(self._open_files)
        self._lbl_tokens.setText(f"~{total:,} {tr('токенов')}")
        self._lbl_ctx_files.setText(f"{count} {tr('файл(ов)')}")
        self._lbl_ctx_tokens.setText(f"~{total:,} {tr('токенов в памяти')}")

    def _update_context_view(self, ctx: ProjectContext):
        """Update the context tab to show what was sent to AI."""
        lines = [f"Файлов в контексте: {len(ctx.files)}",
                 f"Токенов примерно:   ~{ctx.total_token_estimate:,}",
                 ""]
        for f in ctx.files:
            tag = tr(" [сжато]") if f.is_compressed else tr(" [полный]")
            tag += tr(" ★ фокус") if f.is_focused else ""
            lines.append(f"  {f.relative_path}{tag}  (~{f.token_estimate} tok)")
        summary = "\n".join(lines)
        QTimer.singleShot(0, lambda: (
            self._ctx_summary.setText(
                f"{len(ctx.files)} {tr('файлов')}, ~{ctx.total_token_estimate:,} {tr('токенов')}"),
            self._ctx_detail.setPlainText(summary)
        ))

    def _refresh_context_view(self):
        ctx = self._build_context()
        self._update_context_view(ctx)

    # ══════════════════════════════════════════════════════
    #  TOOLBAR ACTIONS
    # ══════════════════════════════════════════════════════

    def _on_mode_toggled(self, checked: bool):
        from services.project_manager import ProjectMode
        mode = ProjectMode.NEW_PROJECT if checked else ProjectMode.EXISTING_PROJECT
        self._project_mgr.set_mode(mode)
        if checked:
            self._btn_mode.setText(tr("🆕 Новый"))
            self._lbl_mode.setText(tr("🆕 Новый проект"))
            self._add_system_message(
                tr("🆕 **Режим: Новый проект** — AI даёт полные реализации кода."))
        else:
            self._btn_mode.setText(tr("🔧 Патчи"))
            self._lbl_mode.setText(tr("🔧 Режим патчей"))
            self._add_system_message(
                tr("🔧 **Режим: Существующий проект** — AI даёт ТОЛЬКО [SEARCH/REPLACE] патчи."))

    def _open_pipeline_dialog(self):
        from ui.dialogs.pipeline_dialog import PipelineDialog
        last_cfg = getattr(self, "_last_pipeline_config", None)
        dlg = PipelineDialog(config=last_cfg, parent=self,
                             model_manager=self._model_manager)
        dlg.pipeline_saved.connect(self._on_pipeline_start)
        dlg.exec()

    def _run_script_manually(self):
        """Run any script manually — streams live log, saves for AI post-analysis."""
        from PyQt6.QtWidgets import QFileDialog
        # Prefer active file if it's a runnable script
        start_dir = "."
        if self._project_mgr.state:
            start_dir = self._project_mgr.state.project_root

        path = self._active_file if (self._active_file and
                self._active_file.endswith((".py", ".bat", ".sh", ".ps1"))) else None

        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("Выбери скрипт для запуска"), start_dir,
                "Scripts (*.py *.bat *.sh *.ps1);;All (*)"
            )
        if not path:
            return

        self._add_system_message(f"▶ {tr('Запуск скрипта')}: `{Path(path).name}`")
        self._set_processing(True, f"Выполняю {Path(path).name}...")
        self._center_tabs.setCurrentIndex(0)

        signals = self._worker_signals
        script_path = str(path)

        async def _run_task():
            from services.script_runner import ScriptRunner
            from services.log_compressor import LogCompressor, CompressionConfig
            runner = ScriptRunner(self._logger)

            stdout_buf, stderr_buf = [], []

            def _on_line(line, stream):
                if stream == "OUT":
                    stdout_buf.append(line)
                else:
                    stderr_buf.append(line)
                signals.status.emit(line[:80] if line else "")

            result = await runner.run_async(
                script_path=script_path,
                timeout_seconds=3600,
                on_line=_on_line,
            )

            # Smart-compress log for AI context
            lc = LogCompressor(CompressionConfig(max_output_chars=10000))
            raw_log = result.combined_log or (result.stdout + "\n" + result.stderr)
            compressed_log = lc.compress_for_ai(raw_log, Path(script_path).name)

            status_icon = "✓" if result.success else f"✗ (код {result.exit_code})"
            summary = (
                f"## ▶ Запуск `{Path(script_path).name}` завершён — {status_icon}\n"
                f"Время: {result.elapsed_seconds:.1f}с  "
                f"{'| Timed out' if result.timed_out else ''}\n\n"
                f"{compressed_log}\n\n"
                "---\n_Log saved. You can ask AI about this run._"
            )
            signals.finished.emit(summary)

        self._pool.start(AiWorker(_run_task, signals))

    def _on_pipeline_start(self, config):
        from services.pipeline_models import PipelineConfig
        self._last_pipeline_config = config
        # Rebuild engine with current model
        self._auto_engine = AutoImproveEngine(
            model_manager=self._model_manager,
            patch_engine=self._patch_engine,
            prompt_engine=self._prompt_engine,
            version_ctrl=self._version_ctrl,
            error_map=self._error_map,
            logger=self._logger,
        )
        # Update panel engine and start
        self._auto_run_panel._engine = self._auto_engine
        self._auto_run_panel.start_pipeline(config)
        # Switch to Auto-Run tab
        self._center_tabs.setCurrentIndex(4)
        self._add_system_message(
            f"⚡ Pipeline **{config.name}** {tr('запущен')}!\n"
            f"Цель: {config.goal[:80]}\n"
            f"{tr('Скриптов')}: {len(config.scripts)} | {tr('Итераций')}: {config.max_iterations}"
        )

    def _open_version_history(self):
        if not self._active_file:
            QMessageBox.information(self, tr("История"), tr("Открой файл для просмотра истории.")); return
        dlg = VersionHistoryDialog(
            self._version_ctrl, self._active_file,
            self._open_files.get(self._active_file, ""), parent=self)
        dlg.version_restored.connect(self._on_version_restored)
        dlg.exec()

    def _on_version_restored(self, path: str, content: str):
        self._open_files[path] = content
        if path == self._active_file:
            self._refresh_editor_content(content)
        self._add_system_message(f"⏪ `{Path(path).name}` {tr('восстановлен к предыдущей версии.')}")

    def _open_error_map(self):
        ErrorMapDialog(self._error_map, parent=self).exec()

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, parent=self)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self, s: AppSettings):
        self._settings = s
        self._model_manager.save(s)
        self._cmb_model.blockSignals(True)
        self._cmb_model.clear()
        for m in s.models:
            self._cmb_model.addItem(m.display_name, m.id)
        self._cmb_model.blockSignals(False)
        self._btn_sherlock.setChecked(s.sherlock_mode_enabled)
        self._btn_send_logs.setChecked(s.send_logs_to_ai)
        if s.default_model_id:
            for i in range(self._cmb_model.count()):
                if self._cmb_model.itemData(i) == s.default_model_id:
                    self._cmb_model.setCurrentIndex(i)
                    self._on_model_changed(i); break
        self.settings_changed.emit(s)
        self._add_system_message(tr("✅ Настройки сохранены"))

    def _on_model_changed(self, idx: int):
        if 0 <= idx < len(self._settings.models):
            self._activate_model(self._settings.models[idx])

    def _export_logs(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Экспорт логов"), "sherlock.log",
            "Log Files (*.log);;Text Files (*.txt)")
        if path:
            self._logger.export(path)
            self._add_system_message(f"📥 {tr('Логи экспортированы')}: {path}")

    def _copy_logs(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._log_view.toPlainText())

    def _on_folder_changed(self, folder: str):
        self._load_project(folder)

    # ══════════════════════════════════════════════════════
    #  SIGNAL MONITOR
    # ══════════════════════════════════════════════════════

    def _start_signal_monitor(self):
        req = self._settings.signal_request_folder or "signals/request"
        res = self._settings.signal_response_folder or "signals/response"
        self._signal_monitor.start(req, res)

    def _on_signal_status(self, text: str, color: str):
        self._lbl_signal.setText(text)
        self._lbl_signal.setStyleSheet(f"color:{color};font-size:11px;")
        self._lbl_monitor_status.setText(text)
        self._lbl_monitor_status.setStyleSheet(f"color:{color};font-size:11px;")

    def _on_signal_event(self, evt):
        c_map = {"created":"#9ECE6A", "deleted":"#F7768E", "modified":"#E0AF68"}
        c = c_map.get(evt.event_type, "#CDD6F4")
        line = f'<span style="color:{c};font-family:monospace;font-size:11px;">{evt}</span>'
        QTimer.singleShot(0, lambda: (
            self._signal_log.appendHtml(line),
            self._lbl_signal_count.setText(
                f"Событий: {self._signal_monitor.event_count}")
        ))

    # ══════════════════════════════════════════════════════
    #  LOGGING
    # ══════════════════════════════════════════════════════

    def _on_log_entry(self, entry: LogEntry):
        QTimer.singleShot(0, lambda: self._append_log(entry))

    def _append_log(self, entry: LogEntry):
        colors = {LogLevel.INFO:"#CDD6F4", LogLevel.WARNING:"#E0AF68",
                  LogLevel.ERROR:"#F7768E", LogLevel.DEBUG:"#565f89"}
        c = colors.get(entry.level, "#CDD6F4")
        self._log_view.appendHtml(
            f'<span style="color:{c};font-family:monospace;font-size:11px;">'
            f'{entry.formatted}</span>')
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum())
        if entry.level == LogLevel.ERROR:
            self._lbl_status_left.setText(f"⚠ {entry.message[:60]}")

    # ══════════════════════════════════════════════════════
    #  PROCESSING STATE
    # ══════════════════════════════════════════════════════

    def _set_processing(self, active: bool, message: str = ""):
        self._is_processing = active
        self._btn_send.setEnabled(not active)
        self._lbl_processing.setVisible(active)
        self._btn_stop.setVisible(active)
        if active:
            self._lbl_processing.setText(f"⟳ {message}")
            # Add streaming bubble
            self._current_stream_edit = self._add_assistant_message_streaming()
            # Switch to conversation tab
            self._center_tabs.setCurrentIndex(0)
        else:
            self._lbl_status_left.setText(tr("Готов"))

    def _stop_processing(self):
        self._pool.clear()
        self._set_processing(False)
        self._add_system_message(tr("⏹ Операция остановлена"))

    # ══════════════════════════════════════════════════════
    #  WINDOW LIFECYCLE
    # ══════════════════════════════════════════════════════

    def closeEvent(self, event):
        geo = self.geometry()
        self._settings.window_geometry = {
            "x": geo.x(), "y": geo.y(),
            "w": geo.width(), "h": geo.height()
        }
        self._model_manager.save(self._settings)
        self._signal_monitor.stop()
        event.accept()
