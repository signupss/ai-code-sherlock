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
    QCheckBox, QMessageBox, QScrollArea, QSizePolicy, QProgressBar
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


# ──────────────────────────────────────────────────────────
#  ASYNC WORKER
# ──────────────────────────────────────────────────────────

class AiWorkerSignals(QObject):
    chunk    = pyqtSignal(str)
    finished = pyqtSignal(str)
    patches  = pyqtSignal(list)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)


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
        num = QLabel(f"ПАТЧ #{idx + 1}")
        num.setObjectName("sectionLabel")
        num.setStyleSheet("color: #E0AF68;")
        fp_text = Path(self.patch.file_path).name if self.patch.file_path else "текущий файл"
        fp = QLabel(fp_text)
        fp.setStyleSheet("font-size: 12px; color: #7AA2F7;")

        self._status_lbl = QLabel("● ожидает")
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

        diff_tabs.addTab(sv, "─ Удалить")
        diff_tabs.addTab(rv, "+ Добавить")
        layout.addWidget(diff_tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        bp = QPushButton("👁 Просмотр"); bp.setFixedWidth(100)
        bp.clicked.connect(lambda: self.preview_requested.emit(self.patch))
        ba = QPushButton("✓ Применить"); ba.setObjectName("successBtn"); ba.setFixedWidth(110)
        ba.clicked.connect(self._do_apply)
        br = QPushButton("✕ Отклонить"); br.setObjectName("dangerBtn"); br.setFixedWidth(110)
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
        t_map = {PatchStatus.APPLIED:"● применён", PatchStatus.REJECTED:"● отклонён",
                 PatchStatus.FAILED:"● ошибка",   PatchStatus.PENDING:"● ожидает"}
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
        self._worker_signals = AiWorkerSignals()
        self._current_stream_edit: QPlainTextEdit | None = None
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

        # Pre-create status label so _build_auto_run_tab can connect to it
        # (it gets added to the real status bar in _build_status_bar)
        self._lbl_status_left = QLabel("Готов")
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
        badge.setStyleSheet("background:#1A2E1A;color:#9ECE6A;border:1px solid #9ECE6A;"
                            "border-radius:4px;padding:1px 7px;font-size:9px;font-weight:bold;")
        layout.addWidget(badge)

        # Project mode indicator
        self._lbl_mode = QLabel("🆕 Новый проект")
        self._lbl_mode.setStyleSheet("color:#E0AF68;font-size:11px;padding:0 8px;")
        layout.addWidget(self._lbl_mode)

        layout.addStretch()

        lbl = QLabel("Модель:")
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
        btn_s.setToolTip("Настройки")
        btn_s.clicked.connect(self._open_settings)
        layout.addWidget(btn_s)
        return bar

    # ── Toolbar ────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("toolbar"); bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(5)

        def sep():
            s = QFrame(); s.setFrameShape(QFrame.Shape.VLine)
            s.setFixedWidth(1); s.setStyleSheet("background:#1E2030;")
            return s

        btn_new = QPushButton("📋 Новый проект"); btn_new.clicked.connect(self._new_project)
        btn_open_proj = QPushButton("📁 Открыть проект"); btn_open_proj.clicked.connect(self._open_project)
        btn_open_file = QPushButton("📄 Файл"); btn_open_file.clicked.connect(self._open_file)
        btn_save = QPushButton("💾 Сохранить"); btn_save.clicked.connect(self._save_active_file)
        layout.addWidget(btn_new); layout.addWidget(btn_open_proj)
        layout.addWidget(btn_open_file); layout.addWidget(btn_save)
        layout.addWidget(sep())

        self._btn_sherlock = QPushButton("🔍 Шерлок")
        self._btn_sherlock.setObjectName("toggleBtn"); self._btn_sherlock.setCheckable(True)
        self._btn_sherlock.setToolTip("Режим анализа ошибок")
        layout.addWidget(self._btn_sherlock)

        self._btn_send_logs = QPushButton("📋 Логи→AI")
        self._btn_send_logs.setObjectName("toggleBtn"); self._btn_send_logs.setCheckable(True)
        layout.addWidget(self._btn_send_logs)

        self._btn_mode = QPushButton("🆕 Новый")
        self._btn_mode.setObjectName("toggleBtn"); self._btn_mode.setCheckable(True)
        self._btn_mode.setChecked(True)
        self._btn_mode.setToolTip("Вкл = Новый проект (полные ответы)\nВыкл = Только патчи")
        self._btn_mode.toggled.connect(self._on_mode_toggled)
        layout.addWidget(self._btn_mode)

        layout.addWidget(sep())

        btn_history = QPushButton("⏪ История")
        btn_history.setToolTip("История версий файла")
        btn_history.clicked.connect(self._open_version_history)
        layout.addWidget(btn_history)

        btn_errormap = QPushButton("🗂 Карта ошибок")
        btn_errormap.clicked.connect(self._open_error_map)
        layout.addWidget(btn_errormap)

        btn_pipeline = QPushButton("⚡ Pipeline")
        btn_pipeline.setStyleSheet(
            "background:#1A1A2E;color:#BB9AF7;border:1px solid #9B59B6;"
            "border-radius:5px;padding:4px 12px;font-weight:bold;"
        )
        btn_pipeline.setToolTip("Настроить и запустить Auto-Improve Pipeline")
        btn_pipeline.clicked.connect(self._open_pipeline_dialog)
        layout.addWidget(btn_pipeline)

        btn_export = QPushButton("📥 Логи")
        btn_export.clicked.connect(self._export_logs)
        layout.addWidget(btn_export)

        layout.addStretch()

        # Signal monitor status
        self._lbl_signal = QLabel("○ Сигнал")
        self._lbl_signal.setStyleSheet("color:#565f89;font-size:11px;")
        layout.addWidget(self._lbl_signal)

        layout.addWidget(sep())

        self._lbl_processing = QLabel("⟳ Обработка...")
        self._lbl_processing.setStyleSheet("color:#7AA2F7;font-size:12px;")
        self._lbl_processing.hide()
        layout.addWidget(self._lbl_processing)

        self._btn_stop = QPushButton("■ Стоп")
        self._btn_stop.setObjectName("dangerBtn"); self._btn_stop.hide()
        self._btn_stop.clicked.connect(self._stop_processing)
        layout.addWidget(self._btn_stop)

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

        # Header
        hdr = QFrame(); hdr.setObjectName("panelHeader"); hdr.setFixedHeight(32)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        lbl = QLabel("КОД"); lbl.setObjectName("sectionLabel")
        self._lbl_active_file = QLabel("нет файла")
        self._lbl_active_file.setStyleSheet("color:#7AA2F7;font-size:11px;")
        hl.addWidget(lbl); hl.addStretch(); hl.addWidget(self._lbl_active_file)
        layout.addWidget(hdr)

        # Context bar (token usage per file)
        self._ctx_bar = QFrame()
        self._ctx_bar.setStyleSheet("background:#0A0D14;border-bottom:1px solid #1E2030;")
        self._ctx_bar.setFixedHeight(22)
        cb_l = QHBoxLayout(self._ctx_bar)
        cb_l.setContentsMargins(10, 0, 10, 0)
        self._lbl_ctx_files = QLabel("0 файлов открыто")
        self._lbl_ctx_files.setStyleSheet("color:#565f89;font-size:10px;")
        self._lbl_ctx_tokens = QLabel("~0 токенов")
        self._lbl_ctx_tokens.setStyleSheet("color:#565f89;font-size:10px;")
        cb_l.addWidget(self._lbl_ctx_files); cb_l.addStretch()
        cb_l.addWidget(self._lbl_ctx_tokens)
        layout.addWidget(self._ctx_bar)

        # Tab-based file editor
        self._file_tabs = QTabWidget()
        self._file_tabs.setTabsClosable(True)
        self._file_tabs.tabCloseRequested.connect(self._close_file_tab)
        self._file_tabs.currentChanged.connect(self._on_tab_changed)
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
        self._center_tabs.addTab(self._build_conversation_tab(), "💬 Диалог")
        self._center_tabs.addTab(self._build_logs_tab(),         "📋 Логи")
        self._center_tabs.addTab(self._build_context_tab(),      "📦 Контекст")
        self._center_tabs.addTab(self._build_signals_tab(),      "📡 Сигналы")
        self._center_tabs.addTab(self._build_auto_run_tab(),     "⚡ Авто-запуск")
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
        btn_clr = QPushButton("Очистить"); btn_clr.clicked.connect(self._log_view.clear)
        btn_copy = QPushButton("📋 Копировать"); btn_copy.clicked.connect(self._copy_logs)
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
        lbl = QLabel("КОНТЕКСТ AI")
        lbl.setObjectName("sectionLabel")
        hdr.addWidget(lbl)
        hdr.addStretch()
        btn_refresh = QPushButton("↺ Обновить")
        btn_refresh.clicked.connect(self._refresh_context_view)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        self._ctx_summary = QLabel("Контекст не построен")
        self._ctx_summary.setStyleSheet("color:#565f89;font-size:11px;")
        self._ctx_summary.setWordWrap(True)
        layout.addWidget(self._ctx_summary)

        self._ctx_detail = QPlainTextEdit()
        self._ctx_detail.setReadOnly(True)
        self._ctx_detail.setObjectName("logView")
        self._ctx_detail.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._ctx_detail.setPlaceholderText("Открой файл и отправь запрос для построения контекста...")
        layout.addWidget(self._ctx_detail, stretch=1)

        return w

    def _build_signals_tab(self) -> QWidget:
        """Real-time monitor for FileSignal folders."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        lbl = QLabel("МОНИТОРИНГ СИГНАЛОВ")
        lbl.setObjectName("sectionLabel")
        hdr.addWidget(lbl)
        hdr.addStretch()

        self._lbl_monitor_status = QLabel("○ Остановлен")
        self._lbl_monitor_status.setStyleSheet("color:#565f89;font-size:11px;")
        hdr.addWidget(self._lbl_monitor_status)

        btn_start = QPushButton("▶ Запустить")
        btn_start.setObjectName("successBtn"); btn_start.setFixedWidth(100)
        btn_start.clicked.connect(self._start_signal_monitor)
        btn_stop = QPushButton("■ Стоп")
        btn_stop.setObjectName("dangerBtn"); btn_stop.setFixedWidth(80)
        btn_stop.clicked.connect(lambda: self._signal_monitor.stop())
        hdr.addWidget(btn_start); hdr.addWidget(btn_stop)
        layout.addLayout(hdr)

        self._signal_log = QPlainTextEdit()
        self._signal_log.setReadOnly(True)
        self._signal_log.setObjectName("logView")
        self._signal_log.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._signal_log.setMaximumBlockCount(500)
        self._signal_log.setPlaceholderText("События файловых сигналов появятся здесь...")
        layout.addWidget(self._signal_log, stretch=1)

        # Stats row
        stats = QHBoxLayout()
        self._lbl_signal_count = QLabel("Событий: 0")
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
        w = QWidget()
        w.setObjectName("inputArea")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(5)

        # Options row
        opts = QHBoxLayout()
        self._chk_include_file = QCheckBox("Активный файл")
        self._chk_include_file.setChecked(True)
        self._chk_include_logs = QCheckBox("Логи ошибок")
        self._chk_include_all  = QCheckBox("Весь проект (скелет)")

        self._lbl_tokens = QLabel("~0 токенов")
        self._lbl_tokens.setObjectName("statusLabel")

        opts.addWidget(self._chk_include_file)
        opts.addWidget(self._chk_include_logs)
        opts.addWidget(self._chk_include_all)
        opts.addStretch()
        opts.addWidget(self._lbl_tokens)
        layout.addLayout(opts)

        # Text input
        self._input_box = QTextEdit()
        self._input_box.setObjectName("chatInput")
        self._input_box.setPlaceholderText(
            "Задай вопрос или опиши изменение...  (Ctrl+Enter — отправить)"
        )
        self._input_box.setMaximumHeight(110)
        self._input_box.setMinimumHeight(75)
        self._input_box.setFont(QFont("Segoe UI,Arial", 12))

        # Send row
        send_row = QHBoxLayout()
        send_row.addStretch()
        self._btn_send = QPushButton("▶ Отправить  Ctrl+↵")
        self._btn_send.setObjectName("primaryBtn")
        self._btn_send.setFixedWidth(185)
        self._btn_send.clicked.connect(self._send_message)
        send_row.addWidget(self._btn_send)

        layout.addWidget(self._input_box)
        layout.addLayout(send_row)
        return w

    # ── Patches Panel ──────────────────────────────────────

    def _build_patches_panel(self) -> QWidget:
        panel = QFrame(); panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QFrame(); hdr.setObjectName("panelHeader"); hdr.setFixedHeight(32)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        lbl = QLabel("ПАТЧИ AI"); lbl.setObjectName("sectionLabel")
        self._lbl_patch_count = QLabel("0 патчей")
        self._lbl_patch_count.setStyleSheet("color:#E0AF68;font-size:11px;")
        btn_all = QPushButton("✓ Все"); btn_all.setObjectName("successBtn")
        btn_all.setFixedWidth(55); btn_all.setToolTip("Применить все")
        btn_all.clicked.connect(self._apply_all_patches)
        btn_clr = QPushButton("✕"); btn_clr.setObjectName("dangerBtn")
        btn_clr.setFixedWidth(28); btn_clr.setToolTip("Очистить список")
        btn_clr.clicked.connect(self._clear_patches)
        hl.addWidget(lbl); hl.addStretch()
        hl.addWidget(self._lbl_patch_count)
        hl.addWidget(btn_all); hl.addWidget(btn_clr)
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

        self._empty_patches = QLabel("🔍\n\nПатчей нет\nОтправь запрос AI")
        self._empty_patches.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_patches.setStyleSheet("color:#2E3148;font-size:13px;padding:30px;")
        layout.addWidget(self._empty_patches)

        return panel

    # ── Status Bar ─────────────────────────────────────────

    def _build_status_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("statusBar"); bar.setFixedHeight(22)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)

        # Re-use the pre-created label (created in __init__ to avoid order issues)
        layout.addWidget(self._lbl_status_left)
        layout.addStretch()

        self._lbl_status_model = QLabel("нет модели")
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

        self._logger.info("AI Code Sherlock инициализирован", source="App")
        self._add_system_message(
            "AI Code Sherlock готов к работе.\n"
            "Открой проект (📁) или файл (📄), выбери модель и начни работу."
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
            QMessageBox.warning(self, "Нет модели",
                "Настрой модель через ⚙ перед отправкой.")
            return

        # Auto-record error if sherlock + logs
        if self._btn_sherlock.isChecked():
            logs = self._logger.format_for_ai()
            if logs:
                self._error_map.record_error(logs[:500], file_path=self._active_file or "")

        self._input_box.clear()
        self._add_user_message(user_text)
        self._set_processing(True, "Обработка...")

        sherlock = self._btn_sherlock.isChecked()
        send_logs = self._btn_send_logs.isChecked() or self._chk_include_logs.isChecked()
        context = self._build_context()
        if send_logs:
            context.error_logs = self._logger.format_for_ai()
        signals = self._worker_signals

        if sherlock and context.error_logs:
            async def _sherlock_task():
                if not self._sherlock:
                    signals.error.emit("SherlockAnalyzer не инициализирован.")
                    return
                req = SherlockRequest(
                    error_logs=context.error_logs or "",
                    context=context, user_hint=user_text
                )
                signals.status.emit("🔍 Шерлок анализирует...")
                result = await self._sherlock.analyze(req, signals.status.emit)
                full = self._response_filter.filter(result.analysis).filtered
                signals.patches.emit(result.patches)
                signals.finished.emit(full)
            self._pool.start(AiWorker(_sherlock_task, signals))
        else:
            async def _stream_task():
                if not self._model_manager.active_provider:
                    signals.error.emit("Нет активной модели"); return

                signals.status.emit("Сжимаю контекст...")
                if self._compressor and context.files:
                    budget = TokenBudget(max_tokens=(
                        self._model_manager.active_model.max_context_tokens
                        if self._model_manager.active_model else 8192))
                    compressed = await self._compressor.compress(context, budget)
                else:
                    compressed = context

                self._update_context_view(compressed)

                # System prompt with mode + error map
                system = self._prompt_engine.build_system_prompt(False)
                system += self._project_mgr.get_mode_system_addon()
                err_ctx = self._error_map.build_context_block(context.error_logs or "")
                if err_ctx:
                    system += f"\n\n{err_ctx}"

                user_prompt = self._prompt_engine.build_analysis_prompt(user_text, compressed)
                messages = [
                    ChatMessage(role=MessageRole.SYSTEM, content=system),
                    *self._conversation[-12:],
                    ChatMessage(role=MessageRole.USER, content=user_prompt),
                ]
                self._conversation.append(ChatMessage(role=MessageRole.USER, content=user_text))

                signals.status.emit("Генерирую ответ...")
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
        rl = QLabel(f"Шерлок  •  {model_name}")
        rl.setStyleSheet("color:#9ECE6A;font-size:11px;font-weight:bold;")
        hdr.addWidget(rl); hdr.addStretch()
        fl.addLayout(hdr)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setFrameShape(QFrame.Shape.NoFrame)
        editor.setStyleSheet("background:transparent;color:#CDD6F4;font-size:13px;border:none;")
        editor.setFont(QFont("Segoe UI,Arial", 12))
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        fl.addWidget(editor)
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
        names  = {"user":"Вы", "assistant":"Шерлок",
                  "system":"Система", "error":"Ошибка"}
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
        self._lbl_patch_count.setText(f"{len(self._patches)} патч(ей)")

    def _apply_patch(self, patch: PatchBlock):
        if not self._active_file:
            self._add_error_message("Нет активного файла для патча.")
            return
        content = self._open_files.get(self._active_file, "")

        # Filter invisible chars in patch blocks
        clean_patch = PatchBlock(
            search_content  = self._response_filter.filter_patch_blocks(patch.search_content),
            replace_content = self._response_filter.filter_patch_blocks(patch.replace_content),
            file_path=patch.file_path, description=patch.description,
        )

        v = self._patch_engine.validate(content, clean_patch)
        if not v.is_valid:
            QMessageBox.warning(self, "Патч не применён",
                f"Блок не найден в файле:\n\n{v.error_message}\n\nВхождений: {v.match_count}")
            for c in self._patches:
                if c.patch is patch: c.set_status(PatchStatus.FAILED, v.error_message or "")
            return

        try:
            # Backup before modify
            version = self._version_ctrl.backup_file(
                self._active_file,
                description=patch.description or "patch",
                patch_search=clean_patch.search_content,
                patch_replace=clean_patch.replace_content,
            )

            patched = self._patch_engine.apply_patch(content, clean_patch)
            self._open_files[self._active_file] = patched
            self._refresh_editor_content(patched)
            with open(self._active_file, "w", encoding="utf-8") as f:
                f.write(patched)
            self._version_ctrl.update_lines_after(version, patched)

            # Auto-resolve open error
            open_errs = self._error_map.get_open_errors()
            if open_errs and self._btn_sherlock.isChecked():
                self._error_map.mark_resolved(
                    open_errs[0].error_id, solution="Патч применён",
                    patch_search=clean_patch.search_content,
                    patch_replace=clean_patch.replace_content)

            for c in self._patches:
                if c.patch is patch: c.set_status(PatchStatus.APPLIED)

            name = Path(self._active_file).name
            self._add_system_message(f"✅ Патч применён → `{name}` (резервная копия сохранена)")
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
        self._lbl_patch_count.setText("0 патчей")
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
            self, "Открыть файл", "",
            "Code Files (*.py *.js *.ts *.java *.go *.rs *.cs *.cpp *.c "
            "*.h *.json *.yaml *.yml *.xml *.md *.sql *.rb *.php *.sh);;All (*)")
        if path: self._load_file(path)

    def _open_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Открыть папку проекта")
        if not folder: return
        self._load_project(folder)

    def _load_project(self, folder: str):
        state = self._project_mgr.open_project(folder)
        self._version_ctrl.set_project_root(folder)
        self._error_map.set_project_root(folder)
        self._file_tree.load_folder(folder)

        # Load first 12 code files
        loaded = 0
        for f in state.tracked_files[:12]:
            self._load_file(f)
            loaded += 1

        mode_txt = "🆕 Новый" if state.mode.value == "new_project" else "🔧 Существующий"
        self._btn_mode.setChecked(state.mode.value == "new_project")
        self._add_system_message(
            f"📁 Проект: **{state.name}**\n"
            f"Найдено файлов: {len(state.tracked_files)} | Открыто: {loaded}\n"
            f"Режим: {mode_txt}"
        )
        self._lbl_status_left.setText(f"Проект: {state.name}")
        self._update_context_tokens()

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
            self._add_system_message(
                f"🆕 Новый проект создан: **{name}**\n"
                f"Папка: {folder}"
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
        except Exception as e:
            self._add_error_message(f"Не удалось открыть {path}: {e}")

    def _create_editor_tab(self, path: str, content: str):
        # Try to use the advanced editor, fall back to plain
        try:
            from ui.widgets.code_editor import CodeEditorPanel
            from ui.widgets.syntax_highlighter import create_highlighter
            editor = QPlainTextEdit()
            editor.setObjectName("codeEditor")
            editor.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 13))
            editor.setPlainText(content)
            editor.setProperty("file_path", path)
            create_highlighter(editor.document(), path)
            editor.textChanged.connect(lambda: self._on_editor_changed(path, editor))
        except Exception:
            editor = QPlainTextEdit()
            editor.setObjectName("codeEditor")
            editor.setFont(QFont("Consolas", 12))
            editor.setPlainText(content)
            editor.setProperty("file_path", path)
            editor.textChanged.connect(lambda: self._on_editor_changed(path, editor))

        name = Path(path).name
        idx = self._file_tabs.addTab(editor, name)
        self._file_tabs.setTabToolTip(idx, path)
        self._file_tabs.setCurrentIndex(idx)

    def _on_editor_changed(self, path: str, editor: QPlainTextEdit):
        self._open_files[path] = editor.toPlainText()
        # Mark tab modified
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                name = Path(path).name
                if not self._file_tabs.tabText(i).endswith("●"):
                    self._file_tabs.setTabText(i, f"{name} ●")
                break

    def _refresh_editor_content(self, new_content: str):
        w = self._file_tabs.currentWidget()
        if isinstance(w, QPlainTextEdit):
            pos = w.textCursor().position()
            w.blockSignals(True)
            w.setPlainText(new_content)
            w.blockSignals(False)
            c = w.textCursor()
            c.setPosition(min(pos, len(new_content)))
            w.setTextCursor(c)

    def _close_file_tab(self, idx: int):
        w = self._file_tabs.widget(idx)
        path = w.property("file_path") if w else None
        if path and path in self._open_files:
            del self._open_files[path]
        self._file_tabs.removeTab(idx)
        self._update_context_tokens()

    def _on_tab_changed(self, idx: int):
        w = self._file_tabs.widget(idx)
        if w:
            path = w.property("file_path")
            if path:
                self._active_file = path
                self._lbl_active_file.setText(Path(path).name)

    def _switch_to_tab(self, path: str):
        for i in range(self._file_tabs.count()):
            if self._file_tabs.tabToolTip(i) == path:
                self._file_tabs.setCurrentIndex(i); return

    def _save_active_file(self):
        if not self._active_file: return
        try:
            with open(self._active_file, "w", encoding="utf-8") as f:
                f.write(self._open_files.get(self._active_file, ""))
            # Remove modified marker
            for i in range(self._file_tabs.count()):
                if self._file_tabs.tabToolTip(i) == self._active_file:
                    self._file_tabs.setTabText(i, Path(self._active_file).name)
                    break
            self._lbl_status_left.setText(f"💾 Сохранено: {Path(self._active_file).name}")
        except Exception as e:
            self._add_error_message(f"Ошибка сохранения: {e}")

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
            focused = [self._active_file] if self._active_file else []
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

        # Other open files (non-focused, up to 8)
        for path, content in list(self._open_files.items())[:8]:
            if path == self._active_file: continue
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
        self._lbl_tokens.setText(f"~{total:,} токенов")
        self._lbl_ctx_files.setText(f"{count} файл(ов)")
        self._lbl_ctx_tokens.setText(f"~{total:,} токенов в памяти")

    def _update_context_view(self, ctx: ProjectContext):
        """Update the context tab to show what was sent to AI."""
        lines = [f"Файлов в контексте: {len(ctx.files)}",
                 f"Токенов примерно:   ~{ctx.total_token_estimate:,}",
                 ""]
        for f in ctx.files:
            tag = " [сжато]" if f.is_compressed else " [полный]"
            tag += " ★ фокус" if f.is_focused else ""
            lines.append(f"  {f.relative_path}{tag}  (~{f.token_estimate} tok)")
        summary = "\n".join(lines)
        QTimer.singleShot(0, lambda: (
            self._ctx_summary.setText(
                f"{len(ctx.files)} файлов, ~{ctx.total_token_estimate:,} токенов"),
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
            self._btn_mode.setText("🆕 Новый")
            self._lbl_mode.setText("🆕 Новый проект")
            self._add_system_message(
                "🆕 **Режим: Новый проект** — AI даёт полные реализации кода.")
        else:
            self._btn_mode.setText("🔧 Патчи")
            self._lbl_mode.setText("🔧 Режим патчей")
            self._add_system_message(
                "🔧 **Режим: Существующий проект** — AI даёт ТОЛЬКО [SEARCH/REPLACE] патчи.")

    def _open_pipeline_dialog(self):
        from ui.dialogs.pipeline_dialog import PipelineDialog
        # Pass last used config if any
        last_cfg = getattr(self, "_last_pipeline_config", None)
        dlg = PipelineDialog(config=last_cfg, parent=self)
        dlg.pipeline_saved.connect(self._on_pipeline_start)
        dlg.exec()

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
            f"⚡ Pipeline **{config.name}** запущен!\n"
            f"Цель: {config.goal[:80]}\n"
            f"Скриптов: {len(config.scripts)} | Итераций: {config.max_iterations}"
        )

    def _open_version_history(self):
        if not self._active_file:
            QMessageBox.information(self, "История", "Открой файл для просмотра истории."); return
        dlg = VersionHistoryDialog(
            self._version_ctrl, self._active_file,
            self._open_files.get(self._active_file, ""), parent=self)
        dlg.version_restored.connect(self._on_version_restored)
        dlg.exec()

    def _on_version_restored(self, path: str, content: str):
        self._open_files[path] = content
        if path == self._active_file:
            self._refresh_editor_content(content)
        self._add_system_message(f"⏪ `{Path(path).name}` восстановлен к предыдущей версии.")

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
        self._add_system_message("✅ Настройки сохранены")

    def _on_model_changed(self, idx: int):
        if 0 <= idx < len(self._settings.models):
            self._activate_model(self._settings.models[idx])

    def _export_logs(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт логов", "sherlock.log",
            "Log Files (*.log);;Text Files (*.txt)")
        if path:
            self._logger.export(path)
            self._add_system_message(f"📥 Логи экспортированы: {path}")

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
            self._lbl_status_left.setText("Готов")

    def _stop_processing(self):
        self._pool.clear()
        self._set_processing(False)
        self._add_system_message("⏹ Операция остановлена")

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
