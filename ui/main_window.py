"""
Main Window — full IDE layout
Left: File Tree | Center: Code Editor | Right-center: Chat+Logs+Input | Right: AI Patches

Upgrades:
  * Debounce/throttle for resize and input events (60 FPS)
  * Toast notification system — non-blocking in-app popups for errors
  * Global exception handler — AI engine crashes show toasts, not crashes
  * Skeleton shimmer loaders in chat/log areas during AI processing
"""
from __future__ import annotations
import asyncio
import os
import traceback
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal,
    QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QKeySequence, QShortcut, QPainter, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QComboBox, QTextEdit,
    QPlainTextEdit, QTabWidget, QFrame, QFileDialog,
    QCheckBox, QMessageBox, QScrollArea, QSizePolicy, QProgressBar,
    QMenu, QApplication, QSpinBox, QGroupBox,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox, QLineEdit,
    QGraphicsOpacityEffect,
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
from services.skill_registry import SkillRegistry
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.patch_preview import PatchPreviewDialog
from ui.dialogs.version_history import VersionHistoryDialog
from ui.dialogs.error_map_dialog import ErrorMapDialog
from ui.widgets.file_tree import FileTreeWidget

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {"bg0":"#07080C","bg1":"#0E1117","bg2":"#131722",
        "bd":"#2E3148","bd2":"#1E2030","tx0":"#CDD6F4","tx1":"#A9B1D6",
        "tx2":"#565f89","tx3":"#3B4261","ac":"#7AA2F7","ok":"#9ECE6A",
        "err":"#F7768E","warn":"#E0AF68","sel":"#2E3148"}.get(k,"#CDD6F4")
    def register_theme_refresh(cb): pass

try:
    from ui.i18n import tr, register_listener, retranslate_widget
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass
    def retranslate_widget(w): pass


# ──────────────────────────────────────────────────────────
#  DEBOUNCE UTILITY
# ──────────────────────────────────────────────────────────

class _Debounce:
    """Debounce a callable — only fires after `delay_ms` of silence."""
    def __init__(self, callback, delay_ms: int = 150):
        self._callback = callback
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._fire)
        self._args = ()
        self._kwargs = {}

    def __call__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs
        self._timer.start()

    def _fire(self):
        self._callback(*self._args, **self._kwargs)

    def cancel(self):
        self._timer.stop()


# ──────────────────────────────────────────────────────────
#  TOAST NOTIFICATION
# ──────────────────────────────────────────────────────────

class ToastNotification(QFrame):
    """
    Non-blocking in-app notification that slides in from top-right
    and auto-dismisses after a timeout.
    """

    def __init__(self, message: str, level: str = "error",
                 duration_ms: int = 5000, parent=None):
        super().__init__(parent)
        self.setFixedWidth(380)
        self.setMinimumHeight(40)
        self.setMaximumHeight(120)

        colors = {
            "error":   (get_color("err"), "#2A0A0A"),
            "warning": (get_color("warn"), "#2A1A0A"),
            "info":    (get_color("ac"), "#0A1A2A"),
            "success": (get_color("ok"), "#0A2A0A"),
        }
        fg, bg = colors.get(level, colors["info"])

        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {fg}44;"
            f" border-radius: 8px; padding: 8px 12px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        icons = {"error": "❌", "warning": "⚠️", "info": "ℹ️", "success": "✅"}
        icon_lbl = QLabel(icons.get(level, "ℹ️"))
        icon_lbl.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            f"color: {fg}; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(msg_lbl, stretch=1)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(20, 20)
        btn_close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {fg}; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {get_color('tx0')}; }}"
        )
        btn_close.clicked.connect(self._dismiss)
        layout.addWidget(btn_close)

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(duration_ms)
        self._dismiss_timer.timeout.connect(self._dismiss)

    def show_toast(self):
        self.show()
        self.raise_()
        self._dismiss_timer.start()

    def _dismiss(self):
        self._dismiss_timer.stop()
        try:
            opacity = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(opacity)
            anim = QPropertyAnimation(opacity, b"opacity")
            anim.setDuration(200)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(self.deleteLater)
            self._fade_anim = anim
            anim.start()
        except Exception:
            self.deleteLater()


class ToastManager:
    """Manages toast positioning within a parent widget."""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._toasts: list[ToastNotification] = []

    def show(self, message: str, level: str = "error", duration_ms: int = 5000):
        toast = ToastNotification(message, level, duration_ms, self._parent)
        self._toasts = [t for t in self._toasts if t.isVisible()]
        y_offset = 8
        for t in self._toasts:
            y_offset += t.height() + 6
        toast.move(self._parent.width() - toast.width() - 12, y_offset)
        toast.show_toast()
        self._toasts.append(toast)

    def reposition(self):
        """Reposition all visible toasts (call on parent resize)."""
        y_offset = 8
        alive = []
        for t in self._toasts:
            if t.isVisible():
                t.move(self._parent.width() - t.width() - 12, y_offset)
                y_offset += t.height() + 6
                alive.append(t)
        self._toasts = alive


# ──────────────────────────────────────────────────────────
#  SKELETON SHIMMER LOADER
# ──────────────────────────────────────────────────────────

class SkeletonLoader(QWidget):
    """Animated shimmer placeholder shown while AI is processing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)  # ~33 FPS
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._offset = 0.0
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._offset += 0.02
        if self._offset > 2.0:
            self._offset = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(get_color("bg2"))
        shimmer = QColor(get_color("bd"))
        w = self.width()
        h = self.height()

        # Draw 3 "skeleton" bars
        bar_h = 12
        bar_y_positions = [12, 34, 56]
        bar_widths = [int(w * 0.7), int(w * 0.5), int(w * 0.6)]

        for i, (y, bw) in enumerate(zip(bar_y_positions, bar_widths)):
            # Base bar
            painter.fillRect(16, y, bw, bar_h, bg)

            # Shimmer gradient sweep
            grad = QLinearGradient(0, 0, w, 0)
            shimmer_pos = (self._offset + i * 0.15) % 2.0
            if shimmer_pos < 1.0:
                center = shimmer_pos
                grad.setColorAt(max(0, center - 0.15), bg)
                grad.setColorAt(center, shimmer)
                grad.setColorAt(min(1.0, center + 0.15), bg)
            else:
                grad.setColorAt(0, bg)
                grad.setColorAt(1, bg)

            painter.fillRect(16, y, bw, bar_h, grad)

        painter.end()


# ──────────────────────────────────────────────────────────
#  ASYNC WORKER
# ──────────────────────────────────────────────────────────

class AiWorkerSignals(QObject):
    chunk       = pyqtSignal(str)
    finished    = pyqtSignal(str)
    patches     = pyqtSignal(list)
    error       = pyqtSignal(str)
    status      = pyqtSignal(str)
    new_variant = pyqtSignal(int, int)
    script_line = pyqtSignal(str, str)
    script_done = pyqtSignal(str, bool)


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
    undo_requested    = pyqtSignal(object)   # emits self (PatchCard)

    def __init__(self, patch: PatchBlock, index: int, parent=None):
        super().__init__(parent)
        self.patch = patch
        self._status = PatchStatus.PENDING
        self._applied_version = None   # FileVersion stored after apply
        self._applied_file: str = ""   # file path that was patched
        self.setObjectName("patchCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build(index)

    def _build(self, idx: int):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        num = QLabel(f"{tr('ПАТЧ #')}{idx + 1}")
        num.setObjectName("accentLabel")
        fp_text = Path(self.patch.file_path).name if self.patch.file_path else tr("текущий файл")
        fp = QLabel(fp_text)
        fp.setObjectName("accentLabel")

        self._status_lbl = QLabel(tr("● ожидает"))
        self._status_lbl.setObjectName("statusLabel")

        hdr.addWidget(num)
        hdr.addWidget(fp)
        hdr.addStretch()
        hdr.addWidget(self._status_lbl)
        layout.addLayout(hdr)

        if self.patch.description:
            desc = QLabel(self.patch.description)
            desc.setWordWrap(True)
            desc.setObjectName("statusLabel")
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
        bu = QPushButton(tr("↩ Откатить")); bu.setFixedWidth(100)
        bu.setToolTip(tr("Восстановить файл к состоянию ДО этого патча"))
        bu.setStyleSheet(
            "QPushButton{background:#1A1A2E;border:1px solid #E0AF68;border-radius:4px;"
            "color:#E0AF68;padding:2px 6px;font-size:11px;}"
            "QPushButton:hover{background:#2A1A1A;border-color:#F7768E;color:#F7768E;}"
        )
        bu.hide()  # hidden until patch is APPLIED
        bu.clicked.connect(self._do_undo)
        btn_row.addWidget(bp); btn_row.addWidget(ba); btn_row.addWidget(br); btn_row.addWidget(bu)
        layout.addLayout(btn_row)
        self._btn_apply = ba; self._btn_reject = br; self._btn_undo = bu

    def _do_apply(self):  self.apply_requested.emit(self.patch)
    def _do_reject(self):
        self.reject_requested.emit(self.patch)
        self.set_status(PatchStatus.REJECTED)
    def _do_undo(self):  self.undo_requested.emit(self)

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
        # Show undo button only for APPLIED patches that have a stored version
        if status == PatchStatus.APPLIED and self._applied_version is not None:
            self._btn_undo.show()
        elif status != PatchStatus.APPLIED:
            self._btn_undo.hide()
        bc_map = {PatchStatus.APPLIED:"#9ECE6A", PatchStatus.REJECTED:"#2E3148",
                  PatchStatus.FAILED:"#F7768E",  PatchStatus.PENDING:"#E0AF68"}
        bc = bc_map.get(status, "#2E3148")
        self.setStyleSheet(f"PatchCard {{ border-left: 3px solid {bc}; }}")


# ──────────────────────────────────────────────────────────
#  MAIN WINDOW
# ──────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    settings_changed = pyqtSignal(object)

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
        self._skill_registry  = SkillRegistry()
        self._auto_engine: AutoImproveEngine | None = None

        # ── State ──
        self._settings: AppSettings = AppSettings()
        self._open_files: dict[str, str] = {}
        self._active_file: str | None = None
        self._patches: list[PatchCard] = []
        self._patched_ranges: dict[str, list[dict]] = {}  # file → [{start, end, patch_id}]
        self._conversation: list[ChatMessage] = []
        self._is_processing = False
        self._consensus_model_ids: list[str] = []
        self._worker_signals = AiWorkerSignals()
        self._current_stream_edit: QPlainTextEdit | None = None
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

        # ── Toast manager ──
        self._toast_mgr: ToastManager | None = None  # init after setCentralWidget

        # ── Debounced resize ──
        self._debounced_resize = _Debounce(self._on_debounced_resize, 100)

        # Pre-create status label
        self._lbl_status_left = QLabel(tr("Готов"))
        self._lbl_status_left.setObjectName("statusLabel")

        # ── Global exception handler ──
        self._install_exception_handler()

        self._build_ui()

        # Init toast manager after central widget exists
        self._toast_mgr = ToastManager(self.centralWidget())

        self._connect_signals()
        self._load_settings()

        QShortcut(QKeySequence("Ctrl+Return"), self, self._send_message)
        QShortcut(QKeySequence("Ctrl+O"),      self, self._open_file)
        QShortcut(QKeySequence("Ctrl+Shift+O"),self, self._open_project)
        QShortcut(QKeySequence("Ctrl+S"),      self, self._save_active_file)

    def _install_exception_handler(self):
        """Install global exception hook that shows toast instead of crashing."""
        import sys
        self._original_excepthook = sys.excepthook

        def _handle_exception(exc_type, exc_value, exc_tb):
            if exc_type == KeyboardInterrupt:
                self._original_excepthook(exc_type, exc_value, exc_tb)
                return
            msg = f"{exc_type.__name__}: {exc_value}"
            # Log it
            self._logger.error(msg, source="Global", exception=traceback.format_exc())
            # Show toast if possible
            try:
                if self._toast_mgr:
                    self._toast_mgr.show(msg[:200], "error", 8000)
            except Exception:
                pass
            # Print to stderr as fallback
            traceback.print_exception(exc_type, exc_value, exc_tb)

        sys.excepthook = _handle_exception
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
        logo.setStyleSheet(f"font-size:15px;font-weight:bold;color:{get_color('ac')};font-family:sans-serif;")
        layout.addWidget(logo)

        self._badge_active = QLabel("ACTIVE")
        self._badge_active.setStyleSheet(f"background:{get_color('bg1')};color:{get_color('ok')};border:1px solid {get_color('ok')};border-radius:4px;padding:1px 7px;font-size:9px;font-weight:bold;")
        layout.addWidget(self._badge_active)

        # Project mode indicator
        self._lbl_mode = QLabel(tr("🆕 Новый проект"))
        self._lbl_mode.setObjectName("accentLabel")
        layout.addWidget(self._lbl_mode)

        layout.addStretch(1)   # левая пружина

        lbl = QLabel(tr("Модель:"))
        lbl.setObjectName("statusLabel")
        layout.addWidget(lbl)

        self._cmb_model = QComboBox()
        self._cmb_model.setMinimumWidth(220)
        self._cmb_model.currentIndexChanged.connect(self._on_model_changed)
        layout.addWidget(self._cmb_model)

        self._lbl_model_status = QLabel("●")
        self._lbl_model_status.setObjectName("statusLabel")
        layout.addWidget(self._lbl_model_status)

        layout.addSpacing(10)
        btn_s = QPushButton("⚙")
        btn_s.setObjectName("iconBtn")
        btn_s.setToolTip(tr("Настройки"))
        btn_s.clicked.connect(self._open_settings)
        layout.addWidget(btn_s)

        layout.addSpacing(6)

        self._btn_forum = QPushButton(tr("💬 Форум"))
        self._btn_forum.setFixedHeight(26)
        self._btn_forum.setToolTip(tr("Открыть форум поддержки в браузере"))
        self._btn_forum.setStyleSheet(f"""
            QPushButton {{
                background: {get_color('bg2')}; color: {get_color('ac')};
                border: 1px solid {get_color('ac')}; border-radius: 4px;
                font-size: 11px; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
        """)
        self._btn_forum.clicked.connect(lambda: __import__('webbrowser').open(
            "https://codesherlock.dev/forum.html"))
        layout.addWidget(self._btn_forum)

        self._btn_support = QPushButton(tr("🛟 Поддержка"))
        self._btn_support.setFixedHeight(26)
        self._btn_support.setToolTip(tr("Открыть документацию и FAQ"))
        self._btn_support.setStyleSheet(f"""
            QPushButton {{
                background: {get_color('bg2')}; color: {get_color('tx1')};
                border: 1px solid {get_color('bd')}; border-radius: 4px;
                font-size: 11px; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {get_color('bg3')}; color: {get_color('tx0')}; }}
        """)
        self._btn_support.clicked.connect(lambda: __import__('webbrowser').open(
            "https://github.com/signupss/ai-code-sherlock/issues"))
        layout.addWidget(self._btn_support)

        self._btn_donate = QPushButton(tr("❤ Донат"))
        self._btn_donate.setFixedHeight(26)
        self._btn_donate.setToolTip(tr("Поддержать разработку проекта"))
        self._btn_donate.setStyleSheet(f"""
            QPushButton {{
                background: {get_color('bg2')}; color: #FF6B6B;
                border: 1px solid #FF6B6B; border-radius: 4px;
                font-size: 11px; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #FF6B6B; color: #fff; font-weight: bold; }}
        """)
        self._btn_donate.clicked.connect(lambda: __import__('webbrowser').open(
            "https://codesherlock.dev/#donate"))
        layout.addWidget(self._btn_donate)

        return bar

    # ── Toolbar ────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("toolbar"); bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        def sep():
            s = QFrame(); s.setFrameShape(QFrame.Shape.VLine)
            s.setFixedWidth(1); s.setStyleSheet(f"background:{get_color('bd2')};margin:6px 2px;")
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
        self._btn_pipeline.setObjectName("primaryBtn")
        self._btn_pipeline.setToolTip(tr("Настроить и запустить Auto-Improve Pipeline"))
        self._btn_pipeline.clicked.connect(self._open_pipeline_dialog)
        layout.addWidget(self._btn_pipeline)

        self._btn_constructor = QPushButton(tr("🤖 Конструктор"))
        self._btn_constructor.setToolTip(tr("Конструктор AI-агентов — визуальный редактор workflow"))
        self._btn_constructor.clicked.connect(self._open_agent_constructor)
        layout.addWidget(self._btn_constructor)

        btn_run_script = QPushButton(tr("▶ Запустить скрипт"))
        btn_run_script.setObjectName("successBtn")
        btn_run_script.setToolTip(tr("Запустить активный файл или выбрать скрипт из проекта."))
        btn_run_script.clicked.connect(self._run_script_manually)
        layout.addWidget(btn_run_script)

        btn_export = QPushButton(tr("📥 Логи"))
        btn_export.clicked.connect(self._export_logs)
        layout.addWidget(btn_export)

        layout.addStretch()

        self._lbl_signal = QLabel(tr("○ Сигнал"))
        self._lbl_signal.setObjectName("statusLabel")
        layout.addWidget(self._lbl_signal)

        layout.addWidget(sep())

        self._lbl_processing = QLabel(tr("⟳ Обработка..."))
        self._lbl_processing.setObjectName("accentLabel")
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
        self._lbl_active_file.setObjectName("accentLabel")

        # Patch highlight toggle
        self._chk_show_patches = QCheckBox(tr("🎨 Патчи"))
        self._chk_show_patches.setToolTip(tr("Подсветить пропатченные блоки в редакторе"))
        self._chk_show_patches.setFixedWidth(90)
        self._chk_show_patches.setStyleSheet("QCheckBox{font-size:10px;}")
        self._chk_show_patches.toggled.connect(self._on_toggle_patch_highlights)

        hl.addWidget(lbl); hl.addStretch()
        hl.addWidget(self._chk_show_patches)
        hl.addWidget(self._lbl_active_file)
        layout.addWidget(hdr)

        # Context bar
        self._ctx_bar = QFrame()
        self._ctx_bar.setObjectName("panelHeader")
        self._ctx_bar.setFixedHeight(22)
        cb_l = QHBoxLayout(self._ctx_bar); cb_l.setContentsMargins(10, 0, 10, 0)
        self._lbl_ctx_files = QLabel(tr("0 файлов"))
        self._lbl_ctx_files.setObjectName("statusLabel")
        self._lbl_ctx_tokens = QLabel(tr("~0 токенов"))
        self._lbl_ctx_tokens.setObjectName("statusLabel")
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

        # Skeleton shimmer loader (shown during AI processing)
        self._chat_skeleton = SkeletonLoader(w)
        self._chat_skeleton.hide()
        layout.addWidget(self._chat_skeleton)

        return w

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(10000)
        self._log_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._log_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(6, 4, 6, 4)
        btn_clr  = QPushButton(tr("Очистить"))
        btn_clr.clicked.connect(self._log_view.clear)
        btn_copy = QPushButton(tr("📋 Копировать"))
        btn_copy.clicked.connect(self._copy_logs)
        btn_row.addStretch()
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_clr)

        # ── Interactive stdin row ──────────────────────────
        self._stdin_frame = QFrame()
        self._stdin_frame.setFixedHeight(36)
        self._stdin_frame.setObjectName("inputArea")
        stdin_frame = self._stdin_frame
        stdin_layout = QHBoxLayout(stdin_frame)
        stdin_layout.setContentsMargins(8, 4, 8, 4)
        stdin_layout.setSpacing(6)

        stdin_lbl = QLabel("↳")
        stdin_lbl.setObjectName("statusLabel")
        stdin_layout.addWidget(stdin_lbl)

        self._stdin_input = QLineEdit()
        self._stdin_input.setPlaceholderText(
            tr("Ввод для запущенного скрипта... (Enter — отправить)"))
        self._stdin_input.setStyleSheet(
            f"QLineEdit {{ background:{get_color('bg2')}; border:1px solid {get_color('bd')};"
            f" border-radius:4px; color:{get_color('tx0')};"
            f" font-family:'JetBrains Mono',Consolas; font-size:11px; padding:2px 8px; }}"
            f"QLineEdit:focus {{ border-color:{get_color('ac')}; }}"
            f"QLineEdit:disabled {{ color:{get_color('tx3')}; border-color:{get_color('bd2')}; }}"
        )
        self._stdin_input.setEnabled(False)
        self._stdin_input.returnPressed.connect(self._send_script_stdin)
        stdin_layout.addWidget(self._stdin_input, stretch=1)

        btn_stdin_send = QPushButton("⏎")
        btn_stdin_send.setFixedWidth(32)
        btn_stdin_send.setToolTip(tr("Отправить ввод скрипту"))
        btn_stdin_send.setObjectName("iconBtn")
        btn_stdin_send.setStyleSheet("")
        btn_stdin_send.clicked.connect(self._send_script_stdin)
        stdin_layout.addWidget(btn_stdin_send)

        layout.addWidget(self._log_view, stretch=1)
        layout.addLayout(btn_row)
        layout.addWidget(stdin_frame)
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
        self._ctx_summary.setObjectName("statusLabel")
        self._ctx_summary.setWordWrap(True)
        layout.addWidget(self._ctx_summary)

        self._ctx_detail = QPlainTextEdit()
        self._ctx_detail.setReadOnly(True)
        self._ctx_detail.setObjectName("logView")
        self._ctx_detail.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._ctx_detail.setPlaceholderText(tr("Открой файл и отправь запрос для построения контекста..."))
        self._ctx_detail.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self._lbl_monitor_status.setObjectName("statusLabel")
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
        self._signal_log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._signal_log, stretch=1)

        # Stats row
        stats = QHBoxLayout()
        self._lbl_signal_count = QLabel(tr("Событий: 0"))
        self._lbl_signal_count.setObjectName("statusLabel")
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
        lbl_pt.setObjectName("statusLabel")
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
        pass  # pt_scroll background — inherits theme
        pt_row.addWidget(pt_scroll, stretch=1)

        # Buttons
        btn_pt_add = QPushButton(tr("＋ файл"))
        btn_pt_add.setFixedHeight(22)
        btn_pt_add.setToolTip(tr("Добавить файл в цели патчинга для этого запроса"))
        btn_pt_add.setObjectName("iconBtn")
        btn_pt_add.clicked.connect(self._add_patch_target_file)
        pt_row.addWidget(btn_pt_add)

        btn_pt_folder = QPushButton(tr("＋ папка"))
        btn_pt_folder.setFixedHeight(22)
        btn_pt_folder.setToolTip(tr("Добавить все .py файлы из папки как цели патчинга"))
        btn_pt_folder.setObjectName("iconBtn")
        btn_pt_folder.clicked.connect(self._add_patch_target_folder)
        pt_row.addWidget(btn_pt_folder)

        btn_pt_clr = QPushButton("✕")
        btn_pt_clr.setFixedSize(22, 22)
        btn_pt_clr.setToolTip(tr("Очистить все дополнительные цели патчинга"))
        btn_pt_clr.setObjectName("iconBtn")
        btn_pt_clr.clicked.connect(self._clear_patch_targets)
        pt_row.addWidget(btn_pt_clr)

        layout.addLayout(pt_row)
        self._refresh_patch_target_chips()   # initial state (empty)

        # ── Strategy + Consensus row ──────────────────────────
        ai_row = QHBoxLayout()
        ai_row.setSpacing(6)

        # Strategy selector
        strat_lbl = QLabel(tr("Стратегия:"))
        strat_lbl.setObjectName("statusLabel")
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
        self._btn_custom_strat.clicked.connect(self._pick_custom_strategy)
        self._active_custom_strategy: dict | None = None
        ai_row.addWidget(self._btn_custom_strat)

        # Strategy description tooltip label
        self._lbl_strat_desc = QLabel("")
        self._lbl_strat_desc.setObjectName("statusLabel")
        self._lbl_strat_desc.setWordWrap(False)
        ai_row.addWidget(self._lbl_strat_desc)

        ai_row.addSpacing(10)

        # Consensus toggle
        self._chk_consensus = QCheckBox(tr("🤝 Консенсус"))
        self._chk_consensus.setToolTip(
            tr("Запросить несколько моделей и выбрать лучший ответ")
        )
        self._chk_consensus.setObjectName("statusLabel")
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

        # Model picker button
        self._btn_consensus_models = QPushButton(tr("⚙ Модели"))
        self._btn_consensus_models.setFixedWidth(80)
        self._btn_consensus_models.setVisible(False)
        self._btn_consensus_models.setToolTip(tr("Выбрать модели для консенсуса"))
        self._btn_consensus_models.clicked.connect(self._pick_consensus_models)
        ai_row.addWidget(self._btn_consensus_models)

        ai_row.addStretch()

        # Variants spinbox (how many answer variants to request)
        variants_lbl = QLabel(tr("Вариантов:"))
        variants_lbl.setObjectName("statusLabel")
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
        
        ac = get_color("ac"); bg1 = get_color("bg1"); bg2 = get_color("bg2")
        bd = get_color("bd"); tx1 = get_color("tx1"); tx2 = get_color("tx2"); err = get_color("err")
        
        if is_active:
            chip.setStyleSheet(
                f"QFrame{{background:{bg1};border:1px solid {ac};border-radius:4px;padding:0 2px;}}"
            )
        else:
            chip.setStyleSheet(
                f"QFrame{{background:{bg2};border:1px solid {bd};border-radius:4px;padding:0 2px;}}"
            )
        cl = QHBoxLayout(chip); cl.setContentsMargins(5, 0, 2, 0); cl.setSpacing(2)

        name = Path(path).name
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color:{ac if is_active else tx1};"
            "font-size:10px;background:transparent;border:none;"
        )
        lbl.setToolTip(path)
        cl.addWidget(lbl)

        if not is_active:
            btn_x = QPushButton("×")
            btn_x.setFixedSize(14, 14)
            btn_x.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;color:{tx2};font-size:11px;padding:0;}}QPushButton:hover{{color:{err};}}"
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
                # Переводим описание если доступно
                desc = tr(desc) if desc else ""
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
            self._chk_consensus.setObjectName("statusLabel")
            # Update button label with selected count
            self._update_consensus_btn_label()
        else:
            self._chk_consensus.setObjectName("statusLabel")

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
        bg1 = get_color("bg1"); bd = get_color("bd")
        tx0 = get_color("tx0"); sel = get_color("sel")
        menu.setStyleSheet(f"""
            QMenu{{background:{bg1};border:1px solid {bd};border-radius:6px;
                  padding:4px;color:{tx0};font-size:12px;}}
            QMenu::item{{padding:7px 20px;border-radius:4px;}}
            QMenu::item:selected{{background:{sel};}}
            QMenu::separator{{background:{bd};height:1px;margin:4px 0;}}
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
            self._btn_custom_strat.setToolTip(f"Кастомная стратегия: {name}\n{strat.get('description','')}")
        else:
            self._btn_custom_strat.setText(tr("✏ Свои"))
            self._btn_custom_strat.setToolTip(tr("Выбрать кастомную стратегию из сохранённых"))
            
        self._refresh_theme_styles()  # Применяем правильные динамические цвета
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
        info.setObjectName("statusLabel")
        info.setWordWrap(True)
        layout.addWidget(info)

        lst = QListWidget()
        bg2 = get_color("bg2"); bd = get_color("bd"); bd2 = get_color("bd2")
        tx0 = get_color("tx0"); sel = get_color("sel")
        lst.setStyleSheet(
            f"QListWidget{{background:{bg2};border:1px solid {bd};border-radius:6px;color:{tx0};}}"
            f"QListWidget::item{{padding:6px 10px;border-bottom:1px solid {bd2};}}"
            f"QListWidget::item:selected{{background:{sel};}}"
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
        self._lbl_patch_count.setObjectName("accentLabel")
        self._btn_apply_all = QPushButton(tr("✓ Все")); self._btn_apply_all.setObjectName("successBtn")
        self._btn_apply_all.setMinimumWidth(80); self._btn_apply_all.setToolTip(tr("Применить все"))
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
        self._empty_patches.setObjectName("statusLabel")
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
        
        # Найти и обновить кнопку очистки (✕)
        if hasattr(self, "_patches_container"):
            parent = self._patches_container.parent()
            while parent and not isinstance(parent, QFrame):
                parent = parent.parent()
            if parent:
                for btn in parent.findChildren(QPushButton):
                    if btn.text() == "✕" and btn.objectName() == "dangerBtn":
                        btn.setToolTip(tr("Очистить список"))
                        break

    # ── Status Bar ─────────────────────────────────────────

    def _build_status_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("statusBar"); bar.setFixedHeight(22)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)

        # Re-use the pre-created label (created in __init__ to avoid order issues)
        layout.addWidget(self._lbl_status_left)
        layout.addStretch()

        self._lbl_status_model = QLabel(tr("нет модели"))
        self._lbl_status_model.setObjectName("accentLabel")
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
        ws.script_line.connect(self._on_script_line)
        ws.script_done.connect(self._on_script_done)

        self._logger.subscribe(self._on_log_entry)

        self._signal_monitor.status_changed.connect(self._on_signal_status)
        self._signal_monitor.event_received.connect(self._on_signal_event)

        # Register theme refresh so inline styles update when user switches theme
        register_theme_refresh(self._refresh_theme_styles)

        # Register comprehensive language retranslation
        register_listener(self._retranslate_all)
        
        # Принудительно вызвать один раз для инициализации
        self._retranslate_all()

    def _retranslate_all(self, _lang: str = ""):
        """
        Comprehensive live retranslation — called on every language change.
        Covers ALL text in the main window: tabs, buttons, labels, tooltips, placeholders.
        """
        # ── Center tab labels ──
        if hasattr(self, "_center_tabs"):
            _tab_keys = [
                tr("💬 Диалог"), tr("📋 Логи"), tr("📦 Контекст"),
                tr("📡 Сигналы"), tr("⚡ Авто-запуск"),
            ]
            for i, text in enumerate(_tab_keys):
                if i < self._center_tabs.count():
                    self._center_tabs.setTabText(i, text)

        # ── Toolbar buttons — walk all children ──
        try:
            retranslate_widget(self)
        except Exception:
            pass

        # ── Static labels that use tr() ──
        self._retranslate_static_labels(_lang)
        self._retranslate_patches_panel(_lang)
        self._retranslate_consensus_items()

        # ── Input area ──
        if hasattr(self, "_input_box"):
            self._input_box.setPlaceholderText(
                tr("Задай вопрос или опиши изменение...  (Ctrl+Enter — отправить)"))
        if hasattr(self, "_btn_send"):
            self._btn_send.setText(tr("▶ Отправить  Ctrl+↵"))
        if hasattr(self, "_chk_include_file"):
            self._chk_include_file.setText(tr("Активный файл"))
        if hasattr(self, "_chk_include_logs"):
            self._chk_include_logs.setText(tr("Логи ошибок"))
        if hasattr(self, "_chk_include_all"):
            self._chk_include_all.setText(tr("Весь проект (скелет)"))
        if hasattr(self, "_chk_consensus"):
            self._chk_consensus.setText(tr("🤝 Консенсус"))

        # ── Title bar ──
        if hasattr(self, "_lbl_mode"):
            if self._btn_mode.isChecked():
                self._lbl_mode.setText(tr("🆕 Новый проект"))
            else:
                self._lbl_mode.setText(tr("🔧 Режим патчей"))
        # Кнопка режима — отдельно, т.к. текст меняется в зависимости от состояния
        if hasattr(self, "_btn_mode"):
            if self._btn_mode.isChecked():
                self._btn_mode.setText(tr("🆕 Новый"))
            else:
                self._btn_mode.setText(tr("🔧 Патчи"))

        # ── Title bar: Модель label и кнопка настроек ──
        if hasattr(self, "_cmb_model"):
            # Сохраняем текущий выбор
            current_data = self._cmb_model.currentData()
            self._cmb_model.blockSignals(True)
            # Перестраиваем список моделей с актуальными display_name
            self._cmb_model.clear()
            for m in self._settings.models:
                self._cmb_model.addItem(m.display_name, m.id)
            # Восстанавливаем выбор
            if current_data:
                for i in range(self._cmb_model.count()):
                    if self._cmb_model.itemData(i) == current_data:
                        self._cmb_model.setCurrentIndex(i)
                        break
            self._cmb_model.blockSignals(False)
        
        # Label "Модель:" в title bar
        # Находим по objectName или перебором — проще пересоздать через _build_title_bar
        # Но можно найти и обновить:
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "" and lbl.text() in ["Модель:", "Model:"]:
                lbl.setText(tr("Модель:"))

        # ── Toolbar buttons (явное обновление) ──
        if hasattr(self, "_btn_sherlock"):
            self._btn_sherlock.setText(tr("🔍 Шерлок"))
        if hasattr(self, "_btn_send_logs"):
            self._btn_send_logs.setText(tr("📋 Логи→AI"))
        if hasattr(self, "_btn_pipeline"):
            self._btn_pipeline.setText(tr("⚡ Pipeline"))
        if hasattr(self, "_btn_constructor"):
            self._btn_constructor.setText(tr("🤖 Конструктор"))

        # Кнопки в toolbar — находим по тексту или objectName
        toolbar = None
        for child in self.findChildren(QFrame):
            if child.objectName() == "toolbar":
                toolbar = child
                break
        
        if toolbar:
            for btn in toolbar.findChildren(QPushButton):
                text = btn.text()
                # Обновляем только кнопки без objectName (стандартные)
                if btn.objectName() == "":
                    if "Новый проект" in text or "New Project" in text:
                        btn.setText(tr("📋 Новый проект"))
                    elif "Открыть проект" in text or "Open Project" in text:
                        btn.setText(tr("📁 Открыть проект"))
                    elif "Файл" in text or text == "File":
                        btn.setText(tr("📄 Файл"))
                    elif "Сохранить" in text and "все" not in text.lower():
                        btn.setText(tr("💾 Сохранить"))
                    elif "История" in text or "History" in text:
                        btn.setText(tr("⏪ История"))
                    elif "Карта ошибок" in text or "Error Map" in text:
                        btn.setText(tr("🗂 Карта ошибок"))
                    elif "Запустить скрипт" in text or "Run Script" in text:
                        btn.setText(tr("▶ Запустить скрипт"))
                    elif "Логи" in text and "→" not in text:
                        btn.setText(tr("📥 Логи"))

        # ── Status bar ──
        if hasattr(self, "_lbl_status_model"):
            if self._model_manager.active_model:
                self._lbl_status_model.setText(self._model_manager.active_model.display_name)
            else:
                self._lbl_status_model.setText(tr("нет модели"))
        if hasattr(self, "_lbl_status_right"):
            self._lbl_status_right.setText(tr("Ln 1, Col 1"))
        if hasattr(self, "_lbl_status_left"):
            current = self._lbl_status_left.text()
            if any(x in current for x in ["Готов", "Ready", "Ошибка", "Error"]):
                self._lbl_status_left.setText(tr("Готов"))

        # ── Input area: Strategy label ──
        if hasattr(self, "_cmb_chat_strategy"):
            # Перестроить items с иконками
            current_strat = self._cmb_chat_strategy.currentData()
            self._cmb_chat_strategy.blockSignals(True)
            self._cmb_chat_strategy.clear()
            try:
                from services.pipeline_models import AIStrategy
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
                # Восстановить выбор
                for i in range(self._cmb_chat_strategy.count()):
                    if self._cmb_chat_strategy.itemData(i) == current_strat:
                        self._cmb_chat_strategy.setCurrentIndex(i)
                        break
            except Exception:
                pass
            self._cmb_chat_strategy.blockSignals(False)
            # Обновить описание
            self._on_chat_strategy_changed(self._cmb_chat_strategy.currentIndex())

        # Strategy label
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "statusLabel" and any(x in lbl.text() for x in ["Стратегия", "Strategy"]):
                lbl.setText(tr("Стратегия:"))
                break

        # Custom strategy button
        if hasattr(self, "_btn_custom_strat"):
            if not getattr(self, "_active_custom_strategy", None):
                self._btn_custom_strat.setText(tr("✏ Свои"))

        # Variants label
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "statusLabel" and any(x in lbl.text() for x in ["Вариантов", "Variants"]):
                lbl.setText(tr("Вариантов:"))
                break

        # ── Patch targets row ──
        if hasattr(self, "_pt_chips_widget"):
            self._refresh_patch_target_chips()

        # ── Refresh token/file counts in current language ──
        self._update_context_tokens()
        
        # ── File Tree ──
        if hasattr(self, '_file_tree') and self._file_tree:
            self._file_tree._retranslate()

    def _refresh_theme_styles(self):
        # === КЛЮЧЕВОЕ: сброс кэша стилей Qt для скроллбаров ===
        # Без этого скроллбары на активном виджете не обновляются при смене темы
        app = QApplication.instance()
        if app:
            app.setStyle(app.style())  # полный сброс стиля приложения
        
        ac   = get_color("ac")
        bg0  = get_color("bg0")
        bg1  = get_color("bg1")
        bg2  = get_color("bg2")
        bg3  = get_color("bg3")
        bd   = get_color("bd")
        bd2  = get_color("bd2")
        tx0  = get_color("tx0")
        tx1  = get_color("tx1")
        tx2  = get_color("tx2")
        tx3  = get_color("tx3")
        ok   = get_color("ok")
        err  = get_color("err")
        warn = get_color("warn")
        sel  = get_color("sel")

        # Title bar
        if hasattr(self, "_lbl_mode"):
            self._lbl_mode.setStyleSheet(f"color:{warn};font-size:11px;padding:0 8px;")
        if hasattr(self, "_lbl_model_status"):
            self._lbl_model_status.setStyleSheet(f"color:{tx2};font-size:14px;")
        if hasattr(self, "_badge_active"):
            self._badge_active.setStyleSheet(
                f"background:{bg1};color:{ok};border:1px solid {ok};"
                f"border-radius:4px;padding:1px 7px;font-size:9px;font-weight:bold;"
            )

        # Toolbar separators
        for sep in self.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QFrame"]).QFrame):
            if sep.frameShape().value == 5:  # VLine
                sep.setStyleSheet(f"background:{bd2};margin:6px 2px;")

        # Toolbar special buttons  
        if hasattr(self, "_btn_pipeline"):
            self._btn_pipeline.setStyleSheet(
                f"QPushButton{{background:{bg3};color:{ac};border:1px solid {bd};"
                f"border-radius:5px;padding:3px 10px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{sel};border-color:{ac};color:{tx0};}}"
            )

        # Editor context bar
        if hasattr(self, "_ctx_bar"):
            self._ctx_bar.setStyleSheet(f"background:{bg0};border-bottom:1px solid {bd2};")
        if hasattr(self, "_lbl_ctx_files"):
            self._lbl_ctx_files.setStyleSheet(f"color:{tx2};font-size:10px;")
        if hasattr(self, "_lbl_ctx_tokens"):
            self._lbl_ctx_tokens.setStyleSheet(f"color:{tx2};font-size:10px;")
        if hasattr(self, "_lbl_active_file"):
            self._lbl_active_file.setStyleSheet(f"color:{ac};font-size:11px;")

        # Input area
        if hasattr(self, "_lbl_tokens"):
            self._lbl_tokens.setStyleSheet(f"color:{tx2};font-size:11px;")
        if hasattr(self, "_lbl_strat_desc"):
            self._lbl_strat_desc.setStyleSheet(f"color:{tx3};font-size:10px;")
        if hasattr(self, "_chk_consensus"):
            self._chk_consensus.setStyleSheet(f"font-size:11px;color:{tx1};")

        # Signals / status
        if hasattr(self, "_lbl_signal"):
            self._lbl_signal.setStyleSheet(f"color:{tx2};font-size:11px;")
        if hasattr(self, "_lbl_processing"):
            self._lbl_processing.setStyleSheet(f"color:{ac};font-size:12px;")
        if hasattr(self, "_lbl_monitor_status"):
            self._lbl_monitor_status.setStyleSheet(f"color:{tx2};font-size:11px;")
        if hasattr(self, "_lbl_signal_count"):
            self._lbl_signal_count.setStyleSheet(f"color:{tx2};font-size:11px;")

        # Context tab
        if hasattr(self, "_ctx_summary"):
            self._ctx_summary.setStyleSheet(f"color:{tx2};font-size:11px;")

        # Stdin row in Logs tab
        if hasattr(self, "_stdin_input"):
            self._stdin_input.setStyleSheet(
                f"QLineEdit {{ background:{bg2}; border:1px solid {bd};"
                f" border-radius:4px; color:{tx0};"
                f" font-family: 'JetBrains Mono',Consolas; font-size:11px;"
                f" padding:2px 8px; }}"
                f"QLineEdit:focus {{ border-color:{ac}; }}"
                f"QLineEdit:disabled {{ color:{tx3}; border-color:{bd2}; }}"
            )

        # Patch targets row
        if hasattr(self, "_lbl_patch_count"):
            self._lbl_patch_count.setStyleSheet(f"color:{warn};font-size:11px;")
        if hasattr(self, "_empty_patches"):
            self._empty_patches.setStyleSheet(f"color:{bd};font-size:13px;padding:30px;")

        # Status bar
        if hasattr(self, "_lbl_status_model"):
            self._lbl_status_model.setStyleSheet(f"color:{ac};font-size:11px;")

        # stdin frame background
        if hasattr(self, "_stdin_frame"):
            self._stdin_frame.setStyleSheet(
                f"QFrame {{ background:{bg0}; border-top:1px solid {bd2}; }}"
            )

        # Log view — force palette reset so QSS background takes effect immediately
        if hasattr(self, "_log_view"):
            from PyQt6.QtGui import QPalette
            p = self._log_view.palette()
            p.setColor(QPalette.ColorRole.Base,   __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(bg0))
            p.setColor(QPalette.ColorRole.Text,   __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(tx0))
            p.setColor(QPalette.ColorRole.Window, __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(bg0))
            self._log_view.setPalette(p)
            self._log_view.viewport().update()
        
        # Custom strategy & Consensus models
        if hasattr(self, "_btn_custom_strat"):
            if getattr(self, "_active_custom_strategy", None):
                self._btn_custom_strat.setStyleSheet(
                    f"QPushButton{{background:{bg1};border:1px solid {ok};border-radius:4px;color:{ok};padding:2px 6px;font-size:11px;}}"
                    f"QPushButton:hover{{background:{bg3};}}"
                )
            else:
                self._btn_custom_strat.setStyleSheet(
                    f"QPushButton{{background:{bg2};border:1px solid {bd};border-radius:4px;color:{tx1};padding:2px 6px;font-size:11px;}}"
                    f"QPushButton:hover{{background:{bg3};color:{ac};}}"
                )

        if hasattr(self, "_btn_consensus_models"):
            self._btn_consensus_models.setStyleSheet(
                f"QPushButton{{background:{bg2};border:1px solid {bd};border-radius:4px;color:{tx1};padding:2px 6px;font-size:11px;}}"
                f"QPushButton:hover{{background:{bg3};color:{tx0};}}"
            )

        # Кнопки шапки: Форум / Поддержка / Донат
        if hasattr(self, "_btn_forum"):
            self._btn_forum.setStyleSheet(
                f"QPushButton{{background:{bg2};color:{ac};border:1px solid {ac};border-radius:4px;font-size:11px;padding:0 8px;}}"
                f"QPushButton:hover{{background:{ac};color:#000;}}"
            )
        if hasattr(self, "_btn_support"):
            self._btn_support.setStyleSheet(
                f"QPushButton{{background:{bg2};color:{tx1};border:1px solid {bd};border-radius:4px;font-size:11px;padding:0 8px;}}"
                f"QPushButton:hover{{background:{bg3};color:{tx0};}}"
            )
        if hasattr(self, "_btn_donate"):
            self._btn_donate.setStyleSheet(
                f"QPushButton{{background:{bg2};color:#FF6B6B;border:1px solid #FF6B6B;border-radius:4px;font-size:11px;padding:0 8px;}}"
                f"QPushButton:hover{{background:#FF6B6B;color:#fff;font-weight:bold;}}"
            )

        # Обновляем чипсы "Патчить:" под новую тему
        if hasattr(self, "_refresh_patch_target_chips"):
            self._refresh_patch_target_chips()

        # 1. Применяем стили для всех контекстных меню в приложении (включая FileTree и табы)
        self.setStyleSheet(f"""
            QMenu {{ background: {bg1}; border: 1px solid {bd}; border-radius: 6px; padding: 4px; color: {tx0}; font-size: 12px; }}
            QMenu::item {{ padding: 7px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {sel}; }}
            QMenu::separator {{ background: {bd}; height: 1px; margin: 4px 0; }}
        """)

        # 2. Форсируем обновление всех редакторов после сброса стиля
        if hasattr(self, "_file_tabs"):
            for i in range(self._file_tabs.count()):
                w = self._file_tabs.widget(i)
                
                # Получаем QPlainTextEdit из CodeEditorPanel или используем w напрямую
                target = None
                if hasattr(w, "editor"):
                    # CodeEditorPanel - берем внутренний QPlainTextEdit
                    target = w.editor
                elif isinstance(w, QPlainTextEdit):
                    target = w
                
                if not target:
                    continue
                
                # Сохраняем позицию скролла
                v_val = target.verticalScrollBar().value()
                h_val = target.horizontalScrollBar().value()
                
                # Принудительно пересоздаём палитру и стиль
                from PyQt6.QtGui import QPalette, QColor
                p = target.palette()
                p.setColor(QPalette.ColorRole.Base, QColor(get_color("bg0")))
                p.setColor(QPalette.ColorRole.Text, QColor(get_color("tx0")))
                target.setPalette(p)
                
                # Обновляем
                target.style().unpolish(target)
                target.style().polish(target)
                target.viewport().update()
                target.update()
                
                # Восстанавливаем позицию
                target.verticalScrollBar().setValue(v_val)
                target.horizontalScrollBar().setValue(h_val)
                
        # === Пересоздаём активный таб для обновления скроллбара ===
        if hasattr(self, "_file_tabs"):
            current_idx = self._file_tabs.currentIndex()
            if current_idx >= 0:
                w = self._file_tabs.widget(current_idx)
                path = self._file_tabs.tabToolTip(current_idx)
                
                # Только для CodeEditorPanel (проверяем наличие editor)
                if hasattr(w, "editor") and path:
                    # Сохраняем состояние
                    editor = w.editor
                    v_scroll = editor.verticalScrollBar().value()
                    h_scroll = editor.horizontalScrollBar().value()
                    cursor_pos = editor.textCursor().position()
                    content = editor.toPlainText()
                    
                    # Удаляем старый таб
                    self._file_tabs.removeTab(current_idx)
                    if path in self._open_files:
                        del self._open_files[path]
                    
                    # Пересоздаём (это применит новые стили)
                    self._load_file(path)
                    
                    # Восстанавливаем позицию
                    new_w = self._file_tabs.widget(current_idx)
                    if hasattr(new_w, "editor"):
                        new_w.editor.verticalScrollBar().setValue(v_scroll)
                        new_w.editor.horizontalScrollBar().setValue(h_scroll)
                        c = new_w.editor.textCursor()
                        c.setPosition(min(cursor_pos, len(content)))
                        new_w.editor.setTextCursor(c)
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
        self._refresh_theme_styles()

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
        chat_timeout   = getattr(self._settings, "chat_timeout_seconds", 600)
        chat_max_tries = max(1, getattr(self._settings, "chat_retry_count", 3) + 1)

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
                    last_err = ""
                    for _attempt in range(chat_max_tries):
                        if _attempt > 0:
                            _wait = min(10 * _attempt, 30)
                            signals.status.emit(
                                f"⏳ {tr('Повтор')} {_attempt + 1}/{chat_max_tries}, {tr('жду')} {_wait}{tr('с')}..."
                            )
                            await asyncio.sleep(_wait)
                        try:
                            full_chunks = []
                            async def _stream_with_timeout():
                                async for chunk in self._model_manager.active_provider.stream(messages):
                                    clean = self._response_filter.filter(chunk).filtered
                                    full_chunks.append(clean)
                                    signals.chunk.emit(clean)
                            await asyncio.wait_for(_stream_with_timeout(), timeout=chat_timeout)
                            if full_chunks:
                                break  # success
                            last_err = "пустой ответ"
                        except asyncio.TimeoutError:
                            last_err = f"таймаут {chat_timeout}с"
                            signals.status.emit(f"⏱ {tr('Таймаут')}: {last_err}")
                        except Exception as _e:
                            last_err = str(_e)[:80]
                            signals.status.emit(f"⚠ {last_err}")
                    if not full_chunks:
                        signals.error.emit(
                            f"AI не ответил после {chat_max_tries} попыток. {last_err}"
                        )
                        return

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
            # Stop skeleton loader on first real token
            if hasattr(self, '_chat_skeleton') and self._chat_skeleton.isVisible():
                self._chat_skeleton.stop()
            cursor = self._current_stream_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(token)
            self._current_stream_edit.setTextCursor(cursor)
            self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum())

    def _on_ai_finished(self, full: str):
        # Stop skeleton loader
        if hasattr(self, '_chat_skeleton') and self._chat_skeleton.isVisible():
            self._chat_skeleton.stop()
        # If the streaming bubble is empty, show fallback
        if self._current_stream_edit is not None:
            current_text = self._current_stream_edit.toPlainText().strip()
            if not current_text and full.strip():
                # Response came through finished signal but not through chunk — display it now
                from PyQt6.QtGui import QTextCursor
                cursor = self._current_stream_edit.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(full.strip())
                self._current_stream_edit.setTextCursor(cursor)
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
        # Show toast notification
        if self._toast_mgr:
            self._toast_mgr.show(err[:200], "error", 6000)

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
        rl.setStyleSheet(f"color:{get_color('ok')};font-size:11px;font-weight:bold;")
        hdr.addWidget(rl)
        hdr.addStretch()

        # "Save as file" button
        btn_save = QPushButton(tr("💾 Сохранить как файл"))
        btn_save.setObjectName("successBtn")
        btn_save.setToolTip(tr("Сохранить ответ AI как новый файл"))
        hdr.addWidget(btn_save)
        fl.addLayout(hdr)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setFrameShape(QFrame.Shape.NoFrame)
        editor.setStyleSheet(f"background:transparent;color:{get_color('tx0')};font-size:13px;border:none;")
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
        colors = {
            "user":      get_color("ac"),
            "assistant": get_color("ok"),
            "system":    get_color("tx2"),
            "error":     get_color("err"),
        }
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
        rl.setStyleSheet(f"color:{colors.get(role, get_color('tx0'))};font-size:11px;font-weight:bold;")
        hdr.addWidget(rl); hdr.addStretch()
        fl.addLayout(hdr)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(f"font-size:13px;color:{get_color('tx0')};")
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
        card.undo_requested.connect(self._undo_patch)
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

                # Сбросить флаг модификации после патча
                w = self._file_tabs.currentWidget()
                if hasattr(w, "editor"):
                    w.editor.document().setModified(False)
                elif hasattr(w, "document"):
                    w.document().setModified(False)

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
                if c.patch is patch:
                    c._applied_version = version
                    c._applied_file = target_file
                    c.set_status(PatchStatus.APPLIED)

            # Track patched line ranges for highlight feature
            self._record_patched_range(target_file, content, patched, clean_patch)

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

    def _undo_patch(self, card: PatchCard):
        """Undo a single applied patch by restoring from its backup version."""
        version = card._applied_version
        target_file = card._applied_file
        if not version or not target_file:
            self._add_error_message(tr("Нет данных для отката — версия не сохранена."))
            return

        reply = QMessageBox.question(
            self, tr("Откатить патч"),
            f"{tr('Восстановить файл к состоянию ДО этого патча?')}\n\n"
            f"Файл: {Path(target_file).name}\n"
            f"Версия: {version.display_time}\n"
            f"Описание: {version.description}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            restored_content = self._version_ctrl.restore_version(version)
            self._open_files[target_file] = restored_content
            if target_file == self._active_file:
                self._refresh_editor_content(restored_content)

                # Сбросить флаг модификации после отката
                w = self._file_tabs.currentWidget()
                if hasattr(w, "editor"):
                    w.editor.document().setModified(False)
                elif hasattr(w, "document"):
                    w.document().setModified(False)

            with open(target_file, "w", encoding="utf-8") as f:
                f.write(restored_content)

            # Update card status
            card._status = PatchStatus.PENDING
            card._status_lbl.setStyleSheet("font-size:11px;color:#E0AF68;")
            card._status_lbl.setText(tr("↩ откачен"))
            card._btn_undo.hide()
            card._btn_apply.setEnabled(True)
            card._btn_reject.setEnabled(True)
            card.setStyleSheet("PatchCard { border-left: 3px solid #E0AF68; }")

            # Remove patched ranges for this file
            if hasattr(self, '_patched_ranges') and target_file in self._patched_ranges:
                self._patched_ranges[target_file] = [
                    r for r in self._patched_ranges[target_file]
                    if r.get("patch_id") != id(card.patch)
                ]
                self._update_patched_highlights()

            name = Path(target_file).name
            self._add_system_message(
                f"↩ {tr('Патч откачен')} → `{name}` ({tr('файл восстановлен к')} {version.display_time})")
            self._update_context_tokens()

        except Exception as e:
            self._add_error_message(f"{tr('Ошибка отката')}: {e}")

    def _record_patched_range(self, file_path: str, old_content: str,
                              new_content: str, patch: PatchBlock):
        """Record which lines were changed by a patch for highlight feature."""
        if not hasattr(self, '_patched_ranges'):
            self._patched_ranges = {}
        if file_path not in self._patched_ranges:
            self._patched_ranges[file_path] = []

        # Find the line range of the replacement in the new content
        replace_text = patch.replace_content
        if not replace_text:
            return
        idx = new_content.find(replace_text)
        if idx < 0:
            return
        start_line = new_content[:idx].count('\n') + 1  # 1-based
        end_line = start_line + replace_text.count('\n')
        self._patched_ranges[file_path].append({
            "start": start_line,
            "end": end_line,
            "patch_id": id(patch),
            "description": patch.description or "",
        })
        # Update highlights if the patched file is currently active
        self._update_patched_highlights()

    def _update_patched_highlights(self):
        """Push patched line ranges to the active editor if toggle is ON."""
        if not hasattr(self, '_chk_show_patches'):
            return
        if not self._chk_show_patches.isChecked():
            return
        if not self._active_file:
            return
        # Find the panel for the active file in _file_tabs
        panel = None
        for i in range(self._file_tabs.count()):
            w = self._file_tabs.widget(i)
            if hasattr(w, 'editor') and hasattr(w, 'file_path'):
                if w.file_path == self._active_file:
                    panel = w
                    break
        if panel is None:
            return
        ranges = self._patched_ranges.get(self._active_file, [])
        line_set = set()
        for r in ranges:
            for ln in range(r["start"], r["end"] + 1):
                line_set.add(ln)
        panel.editor.set_patched_lines(line_set)

    def _on_toggle_patch_highlights(self, checked: bool):
        """Called when the '🎨 Патчи' checkbox is toggled."""
        if checked:
            self._update_patched_highlights()
        else:
            # Clear highlights from all open editors
            for i in range(self._file_tabs.count()):
                w = self._file_tabs.widget(i)
                if hasattr(w, 'editor'):
                    w.editor.clear_patched_lines()

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
            self._msg_box_project = QMessageBox(self)
            self._msg_box_project.setWindowTitle(tr("Открыть файлы проекта"))
            self._msg_box_project.setText(msg)
            self._msg_box_project.setIcon(QMessageBox.Icon.Question)
            btn_all  = self._msg_box_project.addButton(f"{tr('Открыть все')} ({total})", QMessageBox.ButtonRole.AcceptRole)
            btn_some = self._msg_box_project.addButton(f"{tr('Только')} {default_limit}", QMessageBox.ButtonRole.NoRole)
            btn_pick = self._msg_box_project.addButton(tr("Выбрать..."), QMessageBox.ButtonRole.HelpRole)
            self._msg_box_project.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
            self._msg_box_project.exec()

            clicked = self._msg_box_project.clickedButton()
            self._msg_box_project = None  # Очистить ссылку
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

        self._dlg_file_info = QLabel(tr("Отметь файлы которые нужно открыть в редакторе:"))
        self._dlg_file_info.setObjectName("statusLabel")
        layout.addWidget(self._dlg_file_info)

        # Search filter
        self._dlg_file_search = QLineEdit()
        self._dlg_file_search.setPlaceholderText(tr("Поиск файлов..."))
        layout.addWidget(self._dlg_file_search)

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        lst = QListWidget()
        lst.setStyleSheet(
            f"QListWidget{{background:{get_color('bg2')};border:1px solid {get_color('bd2')};border-radius:6px;}}"
            f"QListWidget::item{{padding:4px 10px;border-bottom:1px solid {get_color('bd2')};}}"
            f"QListWidget::item:selected{{background:{get_color('sel')};}}"
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
        self._dlg_file_search.textChanged.connect(_filter)

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
            result = [
                items_all[i].data(Qt.ItemDataRole.UserRole)
                for i in range(len(items_all))
                if items_all[i].checkState() == Qt.CheckState.Checked
                and not items_all[i].isHidden()
            ]
            # Очистить ссылки
            self._dlg_file_info = None
            self._dlg_file_search = None
            return result
        # Очистить ссылки
        self._dlg_file_info = None
        self._dlg_file_search = None
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

            # Сбросить флаг модификации после загрузки
            panel.editor.document().setModified(False)

        except Exception:
            # Fallback: plain QPlainTextEdit
            from PyQt6.QtWidgets import QPlainTextEdit
            panel = QPlainTextEdit()
            panel.setProperty("file_path", path)
            panel.setFont(QFont("JetBrains Mono,Consolas", 12))
            panel.setPlainText(content)
            panel.setStyleSheet(f"background:{get_color('bg0')};color:{get_color('tx0')};border:none;")
            panel.textChanged.connect(lambda: self._on_tab_modified(path, True))

            # Сбросить флаг модификации после загрузки
            panel.document().setModified(False)

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

            # Сбросить флаг модификации
            if hasattr(w, "editor"):
                w.editor.document().setModified(False)
            elif hasattr(w, "document"):
                w.document().setModified(False)

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
                # Refresh patch highlights for the new active file
                self._update_patched_highlights()

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

    def _open_agent_constructor(self):
        """Open the visual AI Agent Constructor window with full integration."""
        from ui.dialogs.agent_constructor import AgentConstructorWindow
        
        if not hasattr(self, "_constructor_window") or self._constructor_window is None:
            self._constructor_window = AgentConstructorWindow(
                settings=self._settings,
                parent=None,
                model_manager=self._model_manager,  # Передаем менеджер моделей
                skill_registry=self._skill_registry,  # Общий реестр скиллов
                project_manager=self._project_mgr,    # Менеджер проекта
                logger=self._logger
            )
        
        # Синхронизация моделей
        self._constructor_window.set_available_models(self._settings.models)
        
        # Если есть открытый проект - загрузить его скиллы
        if self._project_mgr.state and self._project_mgr.state.project_root:
            self._constructor_window.load_project_skills(
                self._project_mgr.state.project_root
            )
        
        self._constructor_window.show()
        self._constructor_window.raise_()
        self._constructor_window.activateWindow()

    def _run_script_manually(self):
        """Run any script manually — streams live log to Logs tab, supports interactive stdin."""
        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime as _dt

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

        script_name = Path(path).name

        # ── Prepare Logs tab ──────────────────────────────
        self._center_tabs.setCurrentIndex(1)  # switch to Logs tab

        # Header separator in log view
        ts = _dt.now().strftime("%H:%M:%S")
        sep = "─" * 52
        self._log_view.appendHtml(
            f'<span style="color:{get_color("tx3")};font-family:monospace;font-size:11px;">'
            f'{sep}</span>'
        )
        self._log_view.appendHtml(
            f'<span style="color:{get_color("ac")};font-family:monospace;font-size:12px;font-weight:bold;">'
            f'▶ {script_name}  &nbsp; <span style="color:#565f89;font-size:10px;">{ts}</span>'
            f'</span>'
        )

        # Enable interactive stdin
        self._stdin_input.setEnabled(True)
        self._stdin_input.setFocus()

        # Start processing indicators WITHOUT creating a chat bubble
        self._set_processing(True, f"{tr('Выполняю')} {script_name}...", create_bubble=False)

        signals = self._worker_signals
        script_path = str(path)

        async def _run_task():
            def _on_line(line: str, stream: str):
                signals.script_line.emit(line, stream)

            result = await self._script_runner.run_async(
                script_path=script_path,
                timeout_seconds=3600,
                on_line=_on_line,
            )

            status_icon = "✓ OK" if result.success else f"✗ код {result.exit_code}"
            if result.timed_out:
                status_icon = "⏱ TIMEOUT"
            summary = (
                f"{script_name} завершён — {status_icon}  "
                f"({result.elapsed_seconds:.1f}с)"
            )
            signals.script_done.emit(summary, result.success)

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

            # Сбросить флаг модификации
            w = self._file_tabs.currentWidget()
            if hasattr(w, "editor"):
                w.editor.document().setModified(False)
            elif hasattr(w, "document"):
                w.document().setModified(False)

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
        # Apply theme, accent color and font size
        try:
            from ui.theme_manager import apply_theme, apply_font
            apply_theme(
                accent=getattr(s, "accent_color", "#7AA2F7"),
                font_size=getattr(s, "ui_font_size", 11),
                theme=getattr(s, "theme", "dark"),
                animate=False,                   # диалог ещё открыт — без скриншот-оверлея
            )
            apply_font(getattr(s, "ui_font_size", 11))
            self._refresh_theme_styles()          # сразу обновить inline-стили главного окна
        except Exception:
            pass
        try:
            from ui.i18n import set_language      # применить язык и уведомить все слушатели
            lang = getattr(s, "language", None)
            if lang:
                set_language(lang)
                # Принудительно вызвать перевод после смены языка
                # (set_language уведомит слушателей, но на всякий случай)
                QTimer.singleShot(100, self._retranslate_all)
        except Exception:
            pass
        QTimer.singleShot(0, self.update)         # форсировать перерисовку в следующем тике
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
        colors = {LogLevel.INFO: get_color("tx1"), LogLevel.WARNING: get_color("warn"),
                  LogLevel.ERROR: get_color("err"), LogLevel.DEBUG: get_color("tx2")}
        c = colors.get(entry.level, get_color("tx1"))
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

    def _set_processing(self, active: bool, message: str = "", create_bubble: bool = True):
        self._is_processing = active
        self._btn_send.setEnabled(not active)
        self._lbl_processing.setVisible(active)
        self._btn_stop.setVisible(active)
        if active:
            self._lbl_processing.setText(f"⟳ {message}")
            if create_bubble:
                # Show skeleton loader
                if hasattr(self, '_chat_skeleton'):
                    self._chat_skeleton.start()
                # Add streaming bubble and switch to conversation tab
                self._current_stream_edit = self._add_assistant_message_streaming()
                self._center_tabs.setCurrentIndex(0)
        else:
            self._lbl_status_left.setText(tr("Готов"))
            # Stop skeleton loader
            if hasattr(self, '_chat_skeleton'):
                self._chat_skeleton.stop()

    def _stop_processing(self):
        self._pool.clear()
        self._script_runner.kill_current()
        self._set_processing(False)
        self._stdin_input.setEnabled(False)
        self._add_system_message(tr("⏹ Операция остановлена"))

    # ── Script output / stdin ──────────────────────────────

    def _on_script_line(self, line: str, stream: str):
        """Append one output line from a running script to the Logs tab."""
        colors = {"OUT": get_color("tx1"), "ERR": get_color("err"), "SYS": get_color("ac")}
        color  = colors.get(stream, get_color("tx1"))
        safe   = (line.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
        self._log_view.appendHtml(
            f'<span style="color:{color};font-family:monospace;font-size:12px;">'
            f'{safe}</span>'
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        # Show last line in status bar while running
        if line.strip():
            self._lbl_status_left.setText(line[:80])

    def _on_script_done(self, summary: str, success: bool):
        """Called when a manually-run script finishes."""
        self._stdin_input.setEnabled(False)
        icon  = "✅" if success else "❌"
        color = get_color("ok") if success else get_color("err")
        safe  = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log_view.appendHtml(
            f'<span style="color:{color};font-family:monospace;font-size:12px;">'
            f'{icon} {safe}</span>'
        )
        self._log_view.appendHtml(
            f'<span style="color:{get_color("tx3")};font-family:monospace;font-size:11px;">'
            '─' * 52 + '</span>'
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._set_processing(False)

    def _send_script_stdin(self):
        """Send text from the Logs-tab stdin field to the running script."""
        text = self._stdin_input.text().strip()
        if not text:
            return
        self._stdin_input.clear()
        self._script_runner.send_stdin(text + "\n")
        # Echo input to log
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log_view.appendHtml(
            f'<span style="color:#E0AF68;font-family:monospace;font-size:11px;">'
            f'&gt;&gt; {safe}</span>'
        )
    
    # ══════════════════════════════════════════════════════
    #  LANGUAGE CHANGE EVENT
    # ══════════════════════════════════════════════════════

    def changeEvent(self, event):
        """Handle system language change events."""
        if event.type() == event.Type.LanguageChange:
            self._retranslate_all()
        super().changeEvent(event)
    
    # ══════════════════════════════════════════════════════
    #  WINDOW LIFECYCLE
    # ══════════════════════════════════════════════════════

    def resizeEvent(self, event):
        """Debounced resize — prevents lag during window resizing."""
        super().resizeEvent(event)
        # Reposition toasts immediately (lightweight)
        if self._toast_mgr:
            self._toast_mgr.reposition()
        # Debounce heavier layout updates
        self._debounced_resize()

    def _on_debounced_resize(self):
        """Called after resize settles — refresh heavy UI elements."""
        try:
            self._update_context_tokens()
        except Exception:
            pass

    def closeEvent(self, event):
        """Handle application close event."""
        if self._has_unsaved_changes():
            unsaved_files = "\n".join(self._get_unsaved_files_list())
            title = tr("Несохранённые изменения")
            body_intro = tr("У вас есть несохранённые изменения в следующих файлах:")
            body_question = tr("Сохранить перед выходом?")

            msg = f"{body_intro}\n\n{unsaved_files}\n\n{body_question}"

            reply = QMessageBox.question(
                self, title, msg,
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )

            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.StandardButton.Save:
                self._save_all_unsaved()

        # Save settings and exit
        geo = self.geometry()
        self._settings.window_geometry = {
            "x": geo.x(), "y": geo.y(),
            "w": geo.width(), "h": geo.height()
        }
        self._model_manager.save(self._settings)
        self._signal_monitor.stop()
        event.accept()
    
    def _has_unsaved_changes(self) -> bool:
        """Check if any open file has unsaved changes."""
        for i in range(self._file_tabs.count()):
            w = self._file_tabs.widget(i)
            is_mod = (w.is_modified if hasattr(w, "is_modified") else
                      w.document().isModified() if hasattr(w, "document") else False)
            if is_mod:
                return True
        return False

    def _save_all_unsaved(self) -> bool:
        """Save all unsaved files. Returns True if successful."""
        for i in range(self._file_tabs.count()):
            w = self._file_tabs.widget(i)
            is_mod = (w.is_modified if hasattr(w, "is_modified") else
                      w.document().isModified() if hasattr(w, "document") else False)
            if is_mod:
                self._save_tab(i)
        return True

    def _get_unsaved_files_list(self) -> list[str]:
        """Get list of unsaved file names."""
        unsaved = []
        for i in range(self._file_tabs.count()):
            w = self._file_tabs.widget(i)
            is_mod = (w.is_modified if hasattr(w, "is_modified") else
                      w.document().isModified() if hasattr(w, "document") else False)
            if is_mod:
                path = self._file_tabs.tabToolTip(i)
                name = Path(path).name if path else f"файл {i+1}"
                unsaved.append(name)
        return unsaved