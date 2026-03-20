"""
Auto-Run Panel — live monitoring panel for the Auto-Improve pipeline.
Shows real-time progress, logs, iteration stats, and patch history.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QPlainTextEdit, QProgressBar,
    QScrollArea, QSizePolicy, QSplitter
)

from services.pipeline_models import PipelineConfig, PipelineStatus, PipelineRun
from services.auto_improve_engine import AutoImproveEngine, PipelineEvent

try:
    from ui.i18n import tr
except ImportError:
    def tr(s): return s


class PipelineWorkerSignals(QObject):
    event_received = pyqtSignal(object)   # PipelineEvent
    finished       = pyqtSignal(object)   # PipelineRun
    error          = pyqtSignal(str)


class PipelineWorker(QRunnable):
    def __init__(self, engine: AutoImproveEngine, config: PipelineConfig,
                 signals: PipelineWorkerSignals):
        super().__init__()
        self._engine = engine
        self._config = config
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._engine.subscribe(
            lambda evt: self.signals.event_received.emit(evt)
        )
        try:
            run = loop.run_until_complete(
                self._engine.run_pipeline(self._config)
            )
            self.signals.finished.emit(run)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            loop.close()


class IterationCard(QFrame):
    """Compact card showing one iteration result."""

    def __init__(self, iteration: int, parent=None):
        super().__init__(parent)
        self.setObjectName("patchCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._iteration = iteration
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        self._lbl_num = QLabel(f"#{self._iteration}")
        self._lbl_num.setFixedWidth(30)
        self._lbl_num.setStyleSheet("color:#7AA2F7;font-weight:bold;font-size:13px;")

        self._lbl_status = QLabel(tr("● запуск..."))
        self._lbl_status.setStyleSheet("color:#E0AF68;font-size:12px;")
        self._lbl_status.setFixedWidth(140)

        self._lbl_patches = QLabel("")
        self._lbl_patches.setStyleSheet("color:#9ECE6A;font-size:11px;")
        self._lbl_patches.setFixedWidth(120)

        self._lbl_time = QLabel("")
        self._lbl_time.setStyleSheet("color:#565f89;font-size:11px;")
        self._lbl_time.setFixedWidth(70)

        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("color:#565f89;font-size:11px;")
        self._lbl_detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._lbl_detail.setWordWrap(False)

        layout.addWidget(self._lbl_num)
        layout.addWidget(self._lbl_status)
        layout.addWidget(self._lbl_patches)
        layout.addWidget(self._lbl_time)
        layout.addWidget(self._lbl_detail)

    def update_status(self, status: str, color: str = "#E0AF68"):
        self._lbl_status.setText(status)
        self._lbl_status.setStyleSheet(f"color:{color};font-size:12px;")

    def update_patches(self, applied: int, failed: int, rolled_back: bool):
        if rolled_back:
            text = tr("↩ откат")
            color = "#F7768E"
        else:
            text = f"+{applied} патчей"
            color = "#9ECE6A" if applied > 0 else "#565f89"
        if failed:
            text += f" ({failed} неудач)"
        self._lbl_patches.setText(text)
        self._lbl_patches.setStyleSheet(f"color:{color};font-size:11px;")

    def update_time(self, elapsed: str):
        self._lbl_time.setText(elapsed)

    def update_detail(self, text: str):
        self._lbl_detail.setText(text[:80])


class AutoRunPanel(QWidget):
    """
    Main auto-run panel embedded in the main window.
    Shown as a tab or docked panel.
    """

    status_changed = pyqtSignal(str)   # status message for status bar

    def __init__(self, engine: AutoImproveEngine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._pool = QThreadPool.globalInstance()
        self._current_run: PipelineRun | None = None
        self._worker_signals = PipelineWorkerSignals()
        self._iteration_cards: list[IterationCard] = []
        self._current_card: IterationCard | None = None
        self._start_time: datetime | None = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_elapsed)

        self._build_ui()
        self._connect_signals()

    # ── UI Build ──────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Status bar
        status_bar = QFrame()
        status_bar.setObjectName("panelHeader")
        status_bar.setFixedHeight(40)
        sl = QHBoxLayout(status_bar); sl.setContentsMargins(12, 0, 12, 0)

        self._lbl_pipeline_name = QLabel(tr("Нет активного пайплайна"))
        self._lbl_pipeline_name.setStyleSheet("color:#CDD6F4;font-size:13px;font-weight:bold;")
        sl.addWidget(self._lbl_pipeline_name)

        self._lbl_iteration = QLabel("")
        self._lbl_iteration.setStyleSheet("color:#E0AF68;font-size:12px;")
        sl.addWidget(self._lbl_iteration)

        sl.addStretch()

        self._lbl_elapsed = QLabel("00:00")
        self._lbl_elapsed.setStyleSheet("color:#565f89;font-size:12px;font-family:monospace;")
        sl.addWidget(self._lbl_elapsed)

        self._lbl_status = QLabel(tr("○ Ожидание"))
        self._lbl_status.setStyleSheet("color:#565f89;font-size:12px;")
        sl.addWidget(self._lbl_status)

        self._btn_stop = QPushButton(tr("■ Остановить"))
        self._btn_stop.setObjectName("dangerBtn")
        self._btn_stop.setFixedWidth(120)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_pipeline)
        sl.addWidget(self._btn_stop)

        layout.addWidget(status_bar)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background:#1E2030; border:none; }QProgressBar::chunk { background:#3D59A1; }"
        )
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # Main content: iterations + live log
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setHandleWidth(1)

        # Left: iteration history
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(0)

        iter_hdr = QFrame(); iter_hdr.setObjectName("panelHeader"); iter_hdr.setFixedHeight(28)
        ih_l = QHBoxLayout(iter_hdr); ih_l.setContentsMargins(12, 0, 12, 0)
        lbl_i = QLabel(tr("ИТЕРАЦИИ")); lbl_i.setObjectName("sectionLabel")
        self._lbl_iter_count = QLabel("0 / 0")
        self._lbl_iter_count.setStyleSheet("color:#565f89;font-size:11px;")
        ih_l.addWidget(lbl_i); ih_l.addStretch(); ih_l.addWidget(self._lbl_iter_count)
        ll.addWidget(iter_hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._iter_container = QWidget()
        self._iter_layout = QVBoxLayout(self._iter_container)
        self._iter_layout.setContentsMargins(6, 6, 6, 6)
        self._iter_layout.setSpacing(4)
        self._iter_layout.addStretch()
        scroll.setWidget(self._iter_container)
        self._iter_scroll = scroll
        ll.addWidget(scroll, stretch=1)

        # Summary stats
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background:#0A0D14;border-top:1px solid #1E2030;")
        stats_frame.setFixedHeight(60)
        sf_l = QVBoxLayout(stats_frame); sf_l.setContentsMargins(12, 6, 12, 6); sf_l.setSpacing(4)
        self._lbl_stats1 = QLabel(tr("Патчей применено: 0  |  Откатов: 0"))
        self._lbl_stats1.setStyleSheet("color:#A9B1D6;font-size:11px;")
        self._lbl_stats2 = QLabel("")
        self._lbl_stats2.setStyleSheet("color:#565f89;font-size:10px;")
        sf_l.addWidget(self._lbl_stats1); sf_l.addWidget(self._lbl_stats2)
        ll.addWidget(stats_frame)

        left.setMinimumWidth(320)
        main_split.addWidget(left)

        # Right: tabbed output
        right_tabs = QTabWidget()
        right_tabs.addTab(self._build_live_log_tab(), tr("📡 Лайв-лог"))
        right_tabs.addTab(self._build_ai_tab(),       tr("🤖 AI анализ"))
        right_tabs.addTab(self._build_patches_tab(),  tr("✂️ Патчи"))
        self._right_tabs = right_tabs
        main_split.addWidget(right_tabs)
        main_split.setSizes([330, 700])

        layout.addWidget(main_split, stretch=1)

    def _build_live_log_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(0, 0, 0, 0)

        self._live_log = QPlainTextEdit()
        self._live_log.setReadOnly(True)
        self._live_log.setObjectName("logView")
        self._live_log.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._live_log.setMaximumBlockCount(5000)

        btn_row = QHBoxLayout()
        btn_clr = QPushButton(tr("Очистить")); btn_clr.clicked.connect(self._live_log.clear)
        self._chk_autoscroll = QPushButton(tr("↓ Автоскролл"))
        self._chk_autoscroll.setCheckable(True); self._chk_autoscroll.setChecked(True)
        self._chk_autoscroll.setFixedWidth(110)
        btn_row.addStretch(); btn_row.addWidget(self._chk_autoscroll); btn_row.addWidget(btn_clr)

        layout.addWidget(self._live_log, stretch=1)
        layout.addLayout(btn_row)
        return w

    def _build_ai_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(0, 0, 0, 0)
        self._ai_view = QPlainTextEdit()
        self._ai_view.setReadOnly(True)
        self._ai_view.setFont(QFont("Segoe UI,Arial", 12))
        self._ai_view.setStyleSheet("background:#0A0D14;color:#CDD6F4;border:none;padding:8px;")
        layout.addWidget(self._ai_view)
        return w

    def _build_patches_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(0, 0, 0, 0)
        self._patches_view = QPlainTextEdit()
        self._patches_view.setReadOnly(True)
        self._patches_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 10))
        self._patches_view.setObjectName("logView")
        layout.addWidget(self._patches_view)
        return w

    # ── Signals ────────────────────────────────────────────

    def _connect_signals(self):
        self._worker_signals.event_received.connect(self._on_event)
        self._worker_signals.finished.connect(self._on_pipeline_finished)
        self._worker_signals.error.connect(self._on_pipeline_error)

    # ── Public API ─────────────────────────────────────────

    def start_pipeline(self, config: PipelineConfig):
        if self._engine.is_running:
            return

        # Reset UI
        for card in self._iteration_cards:
            self._iter_layout.removeWidget(card)
            card.deleteLater()
        self._iteration_cards.clear()
        self._live_log.clear()
        self._ai_view.clear()
        self._patches_view.clear()
        self._progress.setValue(0)

        self._lbl_pipeline_name.setText(f"⚡ {config.name}")
        self._lbl_iter_count.setText(f"0 / {config.max_iterations}")
        self._btn_stop.setEnabled(True)
        self._start_time = datetime.now()
        self._timer.start(1000)

        worker = PipelineWorker(self._engine, config, self._worker_signals)
        self._pool.start(worker)

        self._log_system(f"Pipeline '{config.name}' запущен • Цель: {config.goal[:60]}")

    def _stop_pipeline(self):
        self._engine.cancel()
        self._btn_stop.setEnabled(False)
        self._set_status(tr("⏹ Остановка..."), "#E0AF68")

    # ── Event Handlers ─────────────────────────────────────

    def _on_event(self, evt: PipelineEvent):
        t = evt.event_type
        d = evt.data

        if t == "pipeline_start":
            self._set_status(tr("▶ Запуск"), "#9ECE6A")
            self._progress.setMaximum(d.get("max_iterations", 10))

        elif t == "iteration_start":
            n = d["iteration"]
            card = IterationCard(n)
            count = self._iter_layout.count()
            self._iter_layout.insertWidget(count - 1, card)
            self._iteration_cards.append(card)
            self._current_card = card
            self._lbl_iteration.setText(f"Итерация {n}")
            self._progress.setValue(n - 1)
            self._scroll_iter_to_bottom()

        elif t == "script_start":
            role_tag = "🎯" if d.get("role") == "primary" else "✓"
            msg = f"{role_tag} Запуск: {d['script']}"
            self._log_system(msg)
            if self._current_card:
                self._current_card.update_status(f"▶ {d['script'][:20]}", "#7AA2F7")

        elif t == "script_done":
            c = "#9ECE6A" if d["success"] else "#F7768E"
            status = "✓ OK" if d["success"] else f"✗ код {d['exit_code']}"
            self._log_system(f"[{d['script']}] {status} ({d['elapsed']})", c)

        elif t == "log_line":
            line = d.get("line", "")
            stream = d.get("stream", "OUT")
            if stream == "ERR":
                self._log_line(f"[ERR] {line}", "#F7768E")
            else:
                # Color-code important lines
                if any(w in line.lower() for w in ("error", "exception", "traceback")):
                    self._log_line(line, "#F7768E")
                elif any(w in line.lower() for w in ("warning", "warn")):
                    self._log_line(line, "#E0AF68")
                elif any(w in line.lower() for w in ("epoch", "loss", "acc", "score", "precision", "recall")):
                    self._log_line(line, "#BB9AF7")
                else:
                    self._log_line(line, "#CDD6F4")

        elif t == "ai_thinking":
            self._log_system(f"🤖 {d['message']}", "#7AA2F7")
            if self._current_card:
                self._current_card.update_status(f"🤖 {d['message'][:20]}", "#7AA2F7")

        elif t == "ai_response":
            count = d.get("patches_found", 0)
            msg = f"🤖 AI: найдено {count} патч(ей)"
            if d.get("has_goal_signal"):
                msg += tr(" • ЦЕЛЬ ДОСТИГНУТА")
            self._log_system(msg, "#9ECE6A")

        elif t == "patch_applied":
            self._log_system(
                f"✓ Патч → {d['file']} ({d.get('lines_changed', '?'):+d} строк)",
                "#9ECE6A"
            )
            self._patches_view.appendPlainText(
                f"[{datetime.now().strftime('%H:%M:%S')}] Применён к {d['file']}\n"
            )

        elif t == "patch_failed":
            self._log_system(f"✗ Патч не применён: {d.get('reason','?')[:60]}", "#F7768E")
            self._patches_view.appendPlainText(
                f"[{datetime.now().strftime('%H:%M:%S')}] НЕУДАЧА: {d.get('reason','?')}\n"
            )

        elif t == "rollback":
            self._log_system(f"↩ Откат: {d.get('reason','')}", "#F7768E")
            if self._current_card:
                self._current_card.update_status(tr("↩ Откат"), "#F7768E")

        elif t == "rollback_file":
            self._log_system(f"  ↩ Файл восстановлен: {d['file']}", "#E0AF68")

        elif t == "iteration_done":
            n = d["iteration"]
            if self._current_card:
                success = d["success"] and not d["rolled_back"]
                c = "#9ECE6A" if success else "#F7768E"
                status_txt = tr("✓ Успешно") if success else (tr("↩ Откат") if d["rolled_back"] else tr("⚠ Ошибки"))
                if d.get("goal_achieved"):
                    status_txt = tr("🎯 Цель!")
                self._current_card.update_status(status_txt, c)
                self._current_card.update_patches(
                    d["patches_applied"], 0, d["rolled_back"])
                self._current_card.update_time(d["elapsed"])
            self._progress.setValue(n)
            self._update_stats()

        elif t == "pipeline_error":
            self._log_system(f"❌ Ошибка: {d['error']}", "#F7768E")
            self._set_status(f"❌ Ошибка", "#F7768E")

    def _on_pipeline_finished(self, run: PipelineRun):
        self._current_run = run
        self._timer.stop()
        self._btn_stop.setEnabled(False)

        stop = run.stop_reason or tr("Завершён")
        total_patches = run.total_patches_applied
        self._set_status(f"✓ Завершён: {stop}", "#9ECE6A")
        self._log_system(
            f"Pipeline завершён • {run.current_iteration} итераций • "
            f"{total_patches} патчей • {run.total_rollbacks} откатов • {stop}",
            "#9ECE6A"
        )
        self._progress.setValue(self._progress.maximum())

        # Show last AI analysis
        if run.iterations:
            last = run.iterations[-1]
            self._ai_view.setPlainText(last.ai_analysis)
            self._right_tabs.setCurrentIndex(1)

        self._update_stats()
        self.status_changed.emit(f"Pipeline завершён: {stop}")

    def _on_pipeline_error(self, error: str):
        self._timer.stop()
        self._btn_stop.setEnabled(False)
        self._set_status(f"❌ {error[:40]}", "#F7768E")
        self.status_changed.emit(f"Pipeline ошибка: {error}")

    # ── Helpers ────────────────────────────────────────────

    def _log_line(self, line: str, color: str = "#CDD6F4"):
        html = (f'<span style="color:{color};font-family:monospace;font-size:10px;">'
                f'{line.replace("&","&amp;").replace("<","&lt;")}</span>')
        self._live_log.appendHtml(html)
        if self._chk_autoscroll.isChecked():
            self._live_log.verticalScrollBar().setValue(
                self._live_log.verticalScrollBar().maximum())

    def _log_system(self, message: str, color: str = "#565f89"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_line(f"[{ts}] {message}", color)

    def _set_status(self, text: str, color: str = "#CDD6F4"):
        self._lbl_status.setText(text)
        self._lbl_status.setStyleSheet(f"color:{color};font-size:12px;")

    def _scroll_iter_to_bottom(self):
        QTimer.singleShot(50, lambda:
            self._iter_scroll.verticalScrollBar().setValue(
                self._iter_scroll.verticalScrollBar().maximum()))

    def _update_elapsed(self):
        if self._start_time:
            elapsed = (datetime.now() - self._start_time).seconds
            m, s = divmod(elapsed, 60)
            self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")

    def _update_stats(self):
        if self._current_run:
            run = self._current_run
        else:
            run = None

        total_p = sum(c.patches_applied for c in
                      (self._current_run.iterations if self._current_run else []))
        total_r = sum(1 for c in
                      (self._current_run.iterations if self._current_run else [])
                      if c.rolled_back)
        n = len(self._iteration_cards)
        max_i = self._progress.maximum()

        self._lbl_iter_count.setText(f"{n} / {max_i}")
        self._lbl_stats1.setText(f"Патчей применено: {total_p}  |  Откатов: {total_r}")
        self._lbl_stats2.setText(
            f"Итераций: {n} / {max_i}"
            + (f"  •  {self._start_time.strftime('%H:%M:%S') if self._start_time else ''}" )
        )
