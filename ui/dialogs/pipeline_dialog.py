"""
Pipeline Dialog — full configuration UI.
Features: auto-input, 99-hour timeouts, 2M token limit, 8 AI strategies.
"""
from __future__ import annotations
import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QTabWidget, QWidget, QFrame,
    QFileDialog, QComboBox, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QGroupBox, QFormLayout, QScrollArea,
    QSplitter, QPlainTextEdit, QListWidget, QListWidgetItem,
    QSizePolicy, QDoubleSpinBox
)

from services.pipeline_models import (
    PipelineConfig, ScriptConfig, ScriptRole, AutoInputConfig,
    PipelineStopCondition, AIStrategy, AI_STRATEGY_DESCRIPTIONS
)


class PipelineDialog(QDialog):
    pipeline_saved = pyqtSignal(object)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._config = config or PipelineConfig()
        self._scripts: list[ScriptConfig] = list(self._config.scripts)
        self._current_script_row = -1
        self.setWindowTitle("⚡ Auto-Improve Pipeline")
        self.setMinimumSize(900, 720)
        self.resize(980, 800)
        self.setModal(True)
        self._build_ui()
        self._load_config(self._config)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet("background:#0A0D14;border-bottom:1px solid #1E2030;")
        hdr.setFixedHeight(54)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 0, 20, 0)
        t1 = QLabel("⚡ Auto-Improve Pipeline")
        t1.setStyleSheet("font-size:17px;font-weight:bold;color:#BB9AF7;")
        t2 = QLabel("  Настрой автономный цикл самоулучшения скриптов")
        t2.setStyleSheet("color:#565f89;font-size:12px;")
        hl.addWidget(t1); hl.addWidget(t2); hl.addStretch()
        layout.addWidget(hdr)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_main_tab(),     "⚙️  Основное")
        self._tabs.addTab(self._build_scripts_tab(),  "📜  Скрипты")
        self._tabs.addTab(self._build_outputs_tab(),  "📁  Файлы вывода")
        self._tabs.addTab(self._build_strategy_tab(), "🧠  Стратегия AI")
        self._tabs.addTab(self._build_advanced_tab(), "🔧  Расширенные")
        layout.addWidget(self._tabs, stretch=1)

        footer = QFrame()
        footer.setStyleSheet("background:#0A0D14;border-top:1px solid #1E2030;")
        footer.setFixedHeight(54)
        fl = QHBoxLayout(footer); fl.setContentsMargins(16, 0, 16, 0)
        b_load = QPushButton("📂 Загрузить"); b_load.clicked.connect(self._load_from_file)
        b_save = QPushButton("💾 Сохранить в файл"); b_save.clicked.connect(self._save_to_file)
        fl.addWidget(b_load); fl.addWidget(b_save); fl.addStretch()
        b_cancel = QPushButton("Отмена"); b_cancel.setFixedWidth(90)
        b_cancel.clicked.connect(self.reject)
        b_once = QPushButton("▶ Запустить 1 раз"); b_once.setFixedWidth(155)
        b_once.setToolTip("Одна итерация без цикла")
        b_once.clicked.connect(self._run_once)
        b_start = QPushButton("⚡ Запустить Pipeline")
        b_start.setObjectName("primaryBtn"); b_start.setFixedWidth(185)
        b_start.clicked.connect(self._on_start)
        fl.addWidget(b_cancel); fl.addSpacing(8)
        fl.addWidget(b_once); fl.addSpacing(8)
        fl.addWidget(b_start)
        layout.addWidget(footer)

    # ── Main Tab ──────────────────────────────────────────────────────────────

    def _build_main_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w); outer.setContentsMargins(0,0,0,0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner); layout.setContentsMargins(20,16,20,16)
        layout.setSpacing(14)

        grp_id = QGroupBox("Задание")
        f = QFormLayout(grp_id); f.setSpacing(10)
        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText("Название пайплайна")
        f.addRow("Название:", self._fld_name)
        layout.addWidget(grp_id)

        grp_goal = QGroupBox("Цель оптимизации")
        gl = QVBoxLayout(grp_goal)
        gl.addWidget(QLabel("Опиши что нужно улучшить. AI использует это как критерий успеха.",
                            styleSheet="color:#565f89;font-size:11px;"))
        self._fld_goal = QTextEdit()
        self._fld_goal.setPlaceholderText(
            "Пример: Улучшить Precision > 70% и Signal Rate > 25%.\n"
            "Устранять все ошибки в логах.\n"
            "Оптимизировать параметры CatBoost без переобучения.")
        self._fld_goal.setFixedHeight(110)
        gl.addWidget(self._fld_goal)
        layout.addWidget(grp_goal)

        grp_stop = QGroupBox("Условие остановки")
        sf = QFormLayout(grp_stop); sf.setSpacing(10)
        self._cmb_stop = QComboBox()
        self._cmb_stop.addItem("Максимум итераций", PipelineStopCondition.MAX_ITERATIONS.value)
        self._cmb_stop.addItem("Успешное завершение (exit 0)", PipelineStopCondition.SUCCESS.value)
        self._cmb_stop.addItem("Цель достигнута (AI пишет GOAL_ACHIEVED)", PipelineStopCondition.GOAL_REACHED.value)
        self._cmb_stop.addItem("Ручная остановка", PipelineStopCondition.MANUAL.value)
        sf.addRow("Условие:", self._cmb_stop)
        self._spn_iterations = QSpinBox()
        self._spn_iterations.setRange(1, 9999); self._spn_iterations.setValue(10)
        sf.addRow("Макс. итераций:", self._spn_iterations)
        self._chk_auto_apply = QCheckBox("Автоматически применять патчи")
        self._chk_auto_apply.setChecked(True)
        sf.addRow("", self._chk_auto_apply)
        self._chk_auto_rollback = QCheckBox("Автооткат при синтаксической ошибке")
        self._chk_auto_rollback.setChecked(True)
        sf.addRow("", self._chk_auto_rollback)
        self._spn_retry = QSpinBox()
        self._spn_retry.setRange(0, 10); self._spn_retry.setValue(2)
        sf.addRow("Повторов при неудаче:", self._spn_retry)
        layout.addWidget(grp_stop)
        layout.addStretch()
        scroll.setWidget(inner); outer.addWidget(scroll)
        return w

    # ── Scripts Tab ───────────────────────────────────────────────────────────

    def _build_scripts_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(0,0,0,0)
        splitter = QSplitter(Qt.Orientation.Vertical); splitter.setHandleWidth(1)

        list_w = QWidget()
        ll = QVBoxLayout(list_w); ll.setContentsMargins(12,8,12,4)
        lbl = QLabel("СКРИПТЫ В ПАЙПЛАЙНЕ"); lbl.setObjectName("sectionLabel")
        ll.addWidget(lbl)

        self._script_table = QTableWidget(0, 5)
        self._script_table.setHorizontalHeaderLabels(["Роль","Файл","Аргументы","Таймаут","Патчить"])
        self._script_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._script_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._script_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._script_table.setStyleSheet("""
            QTableWidget{background:#131722;border:none;gridline-color:#1E2030;}
            QTableWidget::item{padding:4px 8px;}
            QTableWidget::item:selected{background:#2E3148;}
            QHeaderView::section{background:#0A0D14;border:none;
                border-bottom:1px solid #1E2030;padding:5px 8px;color:#565f89;font-size:11px;}
        """)
        self._script_table.currentCellChanged.connect(self._on_script_selected)
        ll.addWidget(self._script_table)

        br = QHBoxLayout()
        bp = QPushButton("+ Добавить основной"); bp.setObjectName("successBtn")
        bp.clicked.connect(lambda: self._add_script(ScriptRole.PRIMARY))
        bv = QPushButton("+ Добавить валидатор")
        bv.clicked.connect(lambda: self._add_script(ScriptRole.VALIDATOR))
        bd = QPushButton("✕ Удалить"); bd.setObjectName("dangerBtn"); bd.clicked.connect(self._remove_script)
        bu = QPushButton("↑"); bu.setFixedWidth(32); bu.clicked.connect(lambda: self._move_script(-1))
        bdn = QPushButton("↓"); bdn.setFixedWidth(32); bdn.clicked.connect(lambda: self._move_script(1))
        br.addWidget(bp); br.addWidget(bv); br.addStretch()
        br.addWidget(bu); br.addWidget(bdn); br.addWidget(bd)
        ll.addLayout(br)
        splitter.addWidget(list_w)

        ds = QScrollArea(); ds.setWidgetResizable(True); ds.setFrameShape(QFrame.Shape.NoFrame)
        di = QWidget(); dl = QVBoxLayout(di); dl.setContentsMargins(12,8,12,8); dl.setSpacing(10)
        lbl2 = QLabel("ДЕТАЛИ СКРИПТА"); lbl2.setObjectName("sectionLabel")
        dl.addWidget(lbl2)

        frm = QFormLayout(); frm.setSpacing(10)

        pr = QHBoxLayout()
        self._fld_script_path = QLineEdit(); self._fld_script_path.setPlaceholderText("Путь к скрипту...")
        bb = QPushButton("..."); bb.setObjectName("iconBtn"); bb.setFixedWidth(32)
        bb.clicked.connect(self._browse_script)
        pr.addWidget(self._fld_script_path); pr.addWidget(bb)
        frm.addRow("Файл:", pr)

        self._fld_args = QLineEdit(); self._fld_args.setPlaceholderText("arg1 arg2 ...")
        frm.addRow("Аргументы:", self._fld_args)

        wr = QHBoxLayout()
        self._fld_workdir = QLineEdit(); self._fld_workdir.setPlaceholderText("(по умолчанию: папка скрипта)")
        bw = QPushButton("..."); bw.setObjectName("iconBtn"); bw.setFixedWidth(32)
        bw.clicked.connect(self._browse_workdir)
        wr.addWidget(self._fld_workdir); wr.addWidget(bw)
        frm.addRow("Рабочая папка:", wr)

        # Extended timeout
        tr = QHBoxLayout()
        self._spn_script_timeout = QSpinBox()
        self._spn_script_timeout.setRange(10, 356400)  # up to 99 hours
        self._spn_script_timeout.setValue(3600); self._spn_script_timeout.setSuffix(" сек")
        self._spn_script_timeout.setToolTip("3600=1ч  21600=6ч  86400=24ч  356400=99ч")
        self._lbl_timeout_human = QLabel("= 1 ч 0 мин")
        self._lbl_timeout_human.setStyleSheet("color:#565f89;font-size:11px;")
        self._spn_script_timeout.valueChanged.connect(self._update_timeout_label)
        tr.addWidget(self._spn_script_timeout); tr.addWidget(self._lbl_timeout_human); tr.addStretch()
        for lbl3, secs in [("1ч",3600),("6ч",21600),("12ч",43200),("24ч",86400),("99ч",356400)]:
            bt = QPushButton(lbl3); bt.setFixedWidth(38)
            bt.clicked.connect(lambda _,s=secs: self._spn_script_timeout.setValue(s))
            tr.addWidget(bt)
        frm.addRow("Таймаут:", tr)

        self._chk_patchable = QCheckBox("Разрешить AI патчить этот скрипт")
        self._chk_patchable.setChecked(True)
        frm.addRow("", self._chk_patchable)

        self._fld_env_vars = QLineEdit(); self._fld_env_vars.setPlaceholderText("KEY=VALUE, KEY2=VALUE2")
        frm.addRow("Переменные среды:", self._fld_env_vars)
        dl.addLayout(frm)

        # Auto-input
        ai_grp = QGroupBox("Авто-ввод (автоматические ответы скрипту)")
        ai_grp.setToolTip("Если скрипт спрашивает пользователя — задай автоответы здесь")
        ail = QVBoxLayout(ai_grp); ail.setSpacing(6)
        self._chk_auto_input = QCheckBox("Включить автоматические ответы stdin")
        ail.addWidget(self._chk_auto_input)
        hint = QLabel(
            "Каждая строка = один ответ, отправляемый в stdin по порядку.\n"
            "Пустая строка = Enter. Примеры: 'y', 'yes', 'all', '1', '0'"
        )
        hint.setStyleSheet("color:#565f89;font-size:11px;"); hint.setWordWrap(True)
        ail.addWidget(hint)
        self._fld_auto_input = QPlainTextEdit()
        self._fld_auto_input.setPlaceholderText("y\n\nall\n\n(пустая строка = Enter)")
        self._fld_auto_input.setFixedHeight(80)
        self._fld_auto_input.setFont(QFont("Cascadia Code,Consolas", 11))
        ail.addWidget(self._fld_auto_input)
        dr = QHBoxLayout()
        dr.addWidget(QLabel("Задержка:"))
        self._spn_input_delay = QDoubleSpinBox()
        self._spn_input_delay.setRange(0.0,10.0); self._spn_input_delay.setValue(0.3)
        self._spn_input_delay.setSingleStep(0.1); self._spn_input_delay.setSuffix(" сек")
        dr.addWidget(self._spn_input_delay); dr.addStretch()
        ail.addLayout(dr)
        dl.addWidget(ai_grp)

        bsave = QPushButton("💾 Сохранить изменения скрипта")
        bsave.setObjectName("primaryBtn"); bsave.clicked.connect(self._save_script_detail)
        dl.addWidget(bsave); dl.addStretch()
        ds.setWidget(di)
        splitter.addWidget(ds); splitter.setSizes([250,370])
        layout.addWidget(splitter)
        return w

    # ── Outputs Tab ───────────────────────────────────────────────────────────

    def _build_outputs_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20,16,20,16); layout.setSpacing(12)
        info = QLabel("Файлы которые скрипт генерирует — будут прикреплены к контексту AI.\n"
                      "Поддерживаются: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet и любой текст.")
        info.setStyleSheet("color:#565f89;font-size:12px;"); info.setWordWrap(True)
        layout.addWidget(info)

        grp = QGroupBox("Выходные файлы по скриптам")
        gl = QVBoxLayout(grp)
        self._cmb_script_sel = QComboBox()
        self._cmb_script_sel.currentIndexChanged.connect(self._on_output_script_changed)
        gl.addWidget(self._cmb_script_sel)
        self._output_list = QListWidget()
        self._output_list.setStyleSheet("background:#131722;border:1px solid #1E2030;border-radius:6px;")
        self._output_list.setMinimumHeight(160)
        gl.addWidget(self._output_list)
        ob = QHBoxLayout()
        for label, fn in [("+ Файл", self._add_output_file), ("+ Паттерн (glob)", self._add_output_pattern)]:
            b = QPushButton(label); b.clicked.connect(fn); ob.addWidget(b)
        bd = QPushButton("✕ Удалить"); bd.setObjectName("dangerBtn"); bd.clicked.connect(self._remove_output)
        ob.addStretch(); ob.addWidget(bd)
        gl.addLayout(ob)
        gl.addWidget(QLabel("Примеры: *.csv   results/*.json   output_*   models/*.pkl",
                            styleSheet="color:#3B4261;font-size:10px;"))
        layout.addWidget(grp)

        grp2 = QGroupBox("Лимиты контекста")
        fl = QFormLayout(grp2); fl.setSpacing(10)
        self._spn_log_chars = QSpinBox(); self._spn_log_chars.setRange(1000,200000)
        self._spn_log_chars.setValue(12000); self._spn_log_chars.setSingleStep(1000)
        self._spn_log_chars.setSuffix(" симв")
        fl.addRow("Макс. символов лога:", self._spn_log_chars)
        self._spn_file_chars = QSpinBox(); self._spn_file_chars.setRange(500,50000)
        self._spn_file_chars.setValue(6000); self._spn_file_chars.setSingleStep(500)
        self._spn_file_chars.setSuffix(" симв")
        fl.addRow("Макс. символов на файл:", self._spn_file_chars)
        layout.addWidget(grp2); layout.addStretch()
        return w

    # ── Strategy Tab ──────────────────────────────────────────────────────────

    def _build_strategy_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20,16,20,16); layout.setSpacing(14)
        layout.addWidget(QLabel(
            "Стратегия определяет как AI подходит к улучшению кода — "
            "консервативно или агрессивно, исследуя или эксплуатируя успех.",
            styleSheet="color:#A9B1D6;font-size:12px;"))

        grp_s = QGroupBox("Стратегия AI")
        sl = QFormLayout(grp_s); sl.setSpacing(10)
        self._cmb_strategy = QComboBox()
        for strat in AIStrategy:
            icon = {"conservative":"🛡","balanced":"⚖️","aggressive":"🚀",
                    "explorer":"🔭","exploit":"💎","safe_ratchet":"🔒",
                    "hypothesis":"🔬","ensemble":"🎭"}.get(strat.value, "●")
            self._cmb_strategy.addItem(f"{icon} {strat.value.replace('_',' ').title()}", strat.value)
        self._cmb_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        sl.addRow("Стратегия:", self._cmb_strategy)

        self._lbl_strategy_desc = QLabel()
        self._lbl_strategy_desc.setStyleSheet(
            "color:#A9B1D6;font-size:12px;background:#131722;"
            "border:1px solid #1E2030;border-radius:6px;padding:10px;")
        self._lbl_strategy_desc.setWordWrap(True); self._lbl_strategy_desc.setMinimumHeight(70)
        sl.addRow("", self._lbl_strategy_desc)

        self._spn_strategy_switch = QSpinBox()
        self._spn_strategy_switch.setRange(1,20); self._spn_strategy_switch.setValue(3)
        self._spn_strategy_switch.setToolTip("Для EXPLORER: через сколько итераций менять подход")
        sl.addRow("Ротация (Explorer):", self._spn_strategy_switch)
        layout.addWidget(grp_s)

        grp_m = QGroupBox("Память и лимит токенов")
        ml = QFormLayout(grp_m); ml.setSpacing(10)
        self._chk_include_patches = QCheckBox("Включать историю патчей в промпт")
        self._chk_include_patches.setChecked(True)
        ml.addRow("", self._chk_include_patches)
        self._spn_memory = QSpinBox()
        self._spn_memory.setRange(1,50); self._spn_memory.setValue(5)
        self._spn_memory.setToolTip("Сколько прошлых итераций включать в контекст")
        ml.addRow("Итераций в памяти:", self._spn_memory)

        # Token limit up to 2M
        tr = QHBoxLayout()
        self._spn_tokens = QSpinBox()
        self._spn_tokens.setRange(4096, 2_000_000); self._spn_tokens.setValue(200_000)
        self._spn_tokens.setSingleStep(10_000)
        self._spn_tokens.setToolTip("200k=стандарт, 1M=Gemini 1.5 Pro, 2M=Gemini 1.5 Ultra")
        tr.addWidget(self._spn_tokens)
        for label, val in [("200k",200_000),("500k",500_000),("1M",1_000_000),("2M",2_000_000)]:
            bt = QPushButton(label); bt.setFixedWidth(46)
            bt.clicked.connect(lambda _,v=val: self._spn_tokens.setValue(v))
            tr.addWidget(bt)
        tr.addStretch()
        ml.addRow("Лимит токенов:", tr)
        layout.addWidget(grp_m)

        grp_met = QGroupBox("Паттерны извлечения метрик из лога (regex)")
        gml = QVBoxLayout(grp_met)
        gml.addWidget(QLabel(
            "Первая группа захвата = числовое значение метрики.\n"
            "AI будет видеть тренд метрик и принимать решения на основе них.",
            styleSheet="color:#565f89;font-size:11px;"))
        self._fld_metrics = QPlainTextEdit()
        self._fld_metrics.setPlaceholderText(
            r"precision[:\s=]+(\d+\.?\d*)" + "\n" +
            r"accuracy[:\s=]+(\d+\.?\d*)" + "\n" +
            r"loss[:\s=]+(\d+\.?\d*)")
        self._fld_metrics.setFixedHeight(90)
        self._fld_metrics.setFont(QFont("Cascadia Code,Consolas", 10))
        gml.addWidget(self._fld_metrics)
        layout.addWidget(grp_met)
        layout.addStretch()
        return w

    # ── Advanced Tab ──────────────────────────────────────────────────────────

    def _build_advanced_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20,16,20,16); layout.setSpacing(12)
        grp = QGroupBox("Поведение AI")
        al = QFormLayout(grp); al.setSpacing(10)
        self._chk_prev_patches = QCheckBox("Включать историю патчей (AI не повторяет неудачные)")
        self._chk_prev_patches.setChecked(True)
        al.addRow("", self._chk_prev_patches)
        self._chk_error_map = QCheckBox("Использовать карту ошибок (запрещённые подходы)")
        self._chk_error_map.setChecked(True)
        al.addRow("", self._chk_error_map)
        layout.addWidget(grp)
        grp2 = QGroupBox("Безопасность")
        sl2 = QFormLayout(grp2); sl2.setSpacing(10)
        self._chk_syntax_check = QCheckBox("Проверять синтаксис Python перед применением патча")
        self._chk_syntax_check.setChecked(True)
        sl2.addRow("", self._chk_syntax_check)
        self._chk_backup = QCheckBox("Резервная копия перед каждым патчем (.backups/)")
        self._chk_backup.setChecked(True)
        sl2.addRow("", self._chk_backup)
        layout.addWidget(grp2)
        layout.addStretch()
        return w

    # ══════════════════════════════════════════════════════
    #  Config load / collect
    # ══════════════════════════════════════════════════════

    def _load_config(self, cfg: PipelineConfig):
        self._fld_name.setText(cfg.name)
        self._fld_goal.setPlainText(cfg.goal)
        idx = next((i for i in range(self._cmb_stop.count())
                    if self._cmb_stop.itemData(i) == cfg.stop_condition.value), 0)
        self._cmb_stop.setCurrentIndex(idx)
        self._spn_iterations.setValue(cfg.max_iterations)
        self._chk_auto_apply.setChecked(cfg.auto_apply_patches)
        self._chk_auto_rollback.setChecked(cfg.auto_rollback_on_error)
        self._spn_retry.setValue(cfg.retry_on_patch_failure)
        sidx = next((i for i in range(self._cmb_strategy.count())
                     if self._cmb_strategy.itemData(i) == cfg.ai_strategy.value), 1)
        self._cmb_strategy.setCurrentIndex(sidx)
        self._spn_strategy_switch.setValue(cfg.strategy_switch_after)
        self._chk_include_patches.setChecked(cfg.include_previous_patches)
        self._spn_memory.setValue(cfg.memory_iterations)
        self._spn_tokens.setValue(cfg.max_context_tokens)
        self._spn_log_chars.setValue(cfg.log_max_chars)
        self._spn_file_chars.setValue(cfg.output_max_chars)
        self._fld_metrics.setPlainText("\n".join(cfg.metric_patterns))
        self._scripts = list(cfg.scripts)
        self._refresh_script_table()
        self._refresh_output_script_combo()
        self._on_strategy_changed()

    def _collect_config(self) -> PipelineConfig:
        cfg = PipelineConfig()
        cfg.name = self._fld_name.text().strip() or "Pipeline"
        cfg.goal = self._fld_goal.toPlainText().strip()
        cfg.stop_condition = PipelineStopCondition(self._cmb_stop.currentData())
        cfg.max_iterations = self._spn_iterations.value()
        cfg.auto_apply_patches = self._chk_auto_apply.isChecked()
        cfg.auto_rollback_on_error = self._chk_auto_rollback.isChecked()
        cfg.retry_on_patch_failure = self._spn_retry.value()
        cfg.ai_strategy = AIStrategy(self._cmb_strategy.currentData())
        cfg.strategy_switch_after = self._spn_strategy_switch.value()
        cfg.include_previous_patches = self._chk_include_patches.isChecked()
        cfg.memory_iterations = self._spn_memory.value()
        cfg.max_context_tokens = self._spn_tokens.value()
        cfg.log_max_chars = self._spn_log_chars.value()
        cfg.output_max_chars = self._spn_file_chars.value()
        raw = self._fld_metrics.toPlainText().strip()
        cfg.metric_patterns = [p.strip() for p in raw.splitlines() if p.strip()]
        cfg.scripts = list(self._scripts)
        return cfg

    # ══════════════════════════════════════════════════════
    #  Script table
    # ══════════════════════════════════════════════════════

    def _refresh_script_table(self):
        self._script_table.setRowCount(len(self._scripts))
        for row, sc in enumerate(self._scripts):
            if sc.role == ScriptRole.PRIMARY:
                rt, rc = "🎯 Основной", "#9ECE6A"
            else:
                rt, rc = "✓ Валидатор", "#7AA2F7"
            ri = QTableWidgetItem(rt); ri.setForeground(QColor(rc))
            self._script_table.setItem(row, 0, ri)
            self._script_table.setItem(row, 1, QTableWidgetItem(sc.name))
            self._script_table.setItem(row, 2, QTableWidgetItem(" ".join(sc.args)))
            h, r2 = divmod(sc.timeout_seconds, 3600)
            m, _ = divmod(r2, 60)
            ts = f"{h}ч {m}м" if h else f"{m}м" if m else f"{sc.timeout_seconds}с"
            self._script_table.setItem(row, 3, QTableWidgetItem(ts))
            self._script_table.setItem(row, 4, QTableWidgetItem("✓" if sc.allow_patching else "─"))
            self._script_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, sc.id)

    def _on_script_selected(self, row, *_):
        if row < 0 or row >= len(self._scripts): return
        self._current_script_row = row
        sc = self._scripts[row]
        self._fld_script_path.setText(sc.script_path)
        self._fld_args.setText(" ".join(sc.args))
        self._fld_workdir.setText(sc.working_dir)
        self._spn_script_timeout.setValue(sc.timeout_seconds)
        self._chk_patchable.setChecked(sc.allow_patching)
        self._fld_env_vars.setText(", ".join(f"{k}={v}" for k,v in sc.env_vars.items()))
        self._chk_auto_input.setChecked(sc.auto_input.enabled)
        self._fld_auto_input.setPlainText("\n".join(sc.auto_input.sequences))
        self._spn_input_delay.setValue(sc.auto_input.delay_seconds)

    def _save_script_detail(self):
        row = self._current_script_row
        if row < 0 or row >= len(self._scripts): return
        sc = self._scripts[row]
        sc.script_path = self._fld_script_path.text().strip()
        sc.args = [a for a in self._fld_args.text().split() if a]
        sc.working_dir = self._fld_workdir.text().strip()
        sc.timeout_seconds = self._spn_script_timeout.value()
        sc.allow_patching = self._chk_patchable.isChecked()
        sc.env_vars = {}
        for pair in self._fld_env_vars.text().split(","):
            if "=" in pair:
                k, _, v = pair.strip().partition("=")
                sc.env_vars[k.strip()] = v.strip()
        sc.auto_input.enabled = self._chk_auto_input.isChecked()
        sc.auto_input.sequences = self._fld_auto_input.toPlainText().splitlines()
        sc.auto_input.delay_seconds = self._spn_input_delay.value()
        self._refresh_script_table(); self._refresh_output_script_combo()

    def _add_script(self, role):
        path, _ = QFileDialog.getOpenFileName(self, "Выбери скрипт",
                                              filter="Scripts (*.py *.bat *.sh *.ps1);;All (*)")
        if path:
            sc = ScriptConfig(script_path=path, role=role)
            self._scripts.append(sc)
            self._refresh_script_table(); self._refresh_output_script_combo()
            self._script_table.setCurrentCell(len(self._scripts)-1, 0)

    def _remove_script(self):
        row = self._script_table.currentRow()
        if 0 <= row < len(self._scripts):
            del self._scripts[row]; self._refresh_script_table(); self._refresh_output_script_combo()

    def _move_script(self, d):
        row = self._script_table.currentRow()
        nr = row + d
        if 0 <= nr < len(self._scripts):
            self._scripts[row], self._scripts[nr] = self._scripts[nr], self._scripts[row]
            self._refresh_script_table(); self._script_table.setCurrentCell(nr, 0)

    def _browse_script(self):
        p, _ = QFileDialog.getOpenFileName(self, "Скрипт", filter="Scripts (*.py *.bat *.sh);;All (*)")
        if p: self._fld_script_path.setText(p)

    def _browse_workdir(self):
        d = QFileDialog.getExistingDirectory(self, "Рабочая папка")
        if d: self._fld_workdir.setText(d)

    def _update_timeout_label(self, secs):
        h, r = divmod(secs, 3600); m, s = divmod(r, 60)
        if h: self._lbl_timeout_human.setText(f"= {h} ч {m} мин")
        elif m: self._lbl_timeout_human.setText(f"= {m} мин {s} сек")
        else: self._lbl_timeout_human.setText(f"= {s} сек")

    # ── Output files ──────────────────────────────────────────────────────────

    def _refresh_output_script_combo(self):
        self._cmb_script_sel.clear()
        for sc in self._scripts: self._cmb_script_sel.addItem(sc.name, sc.id)

    def _on_output_script_changed(self, idx):
        if idx < 0 or idx >= len(self._scripts): return
        sc = self._scripts[idx]; self._output_list.clear()
        for f in sc.output_files:
            item = QListWidgetItem(f"📄 {f}")
            item.setData(Qt.ItemDataRole.UserRole, ("file", f)); self._output_list.addItem(item)
        for p in sc.output_patterns:
            item = QListWidgetItem(f"🔍 {p}  [паттерн]")
            item.setData(Qt.ItemDataRole.UserRole, ("pattern", p))
            item.setForeground(QColor("#E0AF68")); self._output_list.addItem(item)

    def _add_output_file(self):
        idx = self._cmb_script_sel.currentIndex()
        if idx < 0 or idx >= len(self._scripts): return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выходные файлы",
            filter="Data (*.csv *.json *.txt *.log *.xlsx *.pkl *.npy *.npz *.parquet);;All (*)")
        for p in paths: self._scripts[idx].output_files.append(p)
        self._on_output_script_changed(idx)

    def _add_output_pattern(self):
        idx = self._cmb_script_sel.currentIndex()
        if idx < 0 or idx >= len(self._scripts): return
        from PyQt6.QtWidgets import QInputDialog
        pattern, ok = QInputDialog.getText(self, "Glob-паттерн", "Паттерн (*.csv, results/*.json, ...): ")
        if ok and pattern.strip():
            self._scripts[idx].output_patterns.append(pattern.strip())
            self._on_output_script_changed(idx)

    def _remove_output(self):
        idx = self._cmb_script_sel.currentIndex()
        item = self._output_list.currentItem()
        if not item or idx < 0: return
        kind, val = item.data(Qt.ItemDataRole.UserRole)
        sc = self._scripts[idx]
        if kind == "file" and val in sc.output_files: sc.output_files.remove(val)
        elif kind == "pattern" and val in sc.output_patterns: sc.output_patterns.remove(val)
        self._on_output_script_changed(idx)

    # ── Strategy ──────────────────────────────────────────────────────────────

    def _on_strategy_changed(self):
        val = self._cmb_strategy.currentData()
        if val:
            try:
                desc = AI_STRATEGY_DESCRIPTIONS.get(AIStrategy(val), "")
                self._lbl_strategy_desc.setText(desc)
            except Exception: pass

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _save_to_file(self):
        cfg = self._collect_config()
        p, _ = QFileDialog.getSaveFileName(self, "Сохранить", f"{cfg.name}.pipeline.json",
                                           "Pipeline (*.pipeline.json);;JSON (*.json)")
        if p: Path(p).write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_from_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Загрузить", filter="Pipeline (*.pipeline.json *.json)")
        if p:
            try:
                cfg = PipelineConfig.from_dict(json.loads(Path(p).read_text(encoding="utf-8")))
                self._scripts = list(cfg.scripts)
                self._load_config(cfg)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить: {e}")

    def _run_once(self):
        cfg = self._collect_config()
        if not cfg.scripts:
            QMessageBox.warning(self, "Нет скриптов", "Добавь скрипты."); return
        cfg.max_iterations = 1
        cfg.stop_condition = PipelineStopCondition.MAX_ITERATIONS
        self._config = cfg; self.pipeline_saved.emit(cfg); self.accept()

    def _on_start(self):
        cfg = self._collect_config()
        if not cfg.scripts:
            QMessageBox.warning(self, "Нет скриптов", "Добавь скрипты."); return
        if not cfg.goal.strip():
            QMessageBox.warning(self, "Нет цели", "Укажи цель на вкладке 'Основное'."); return
        self._config = cfg; self.pipeline_saved.emit(cfg); self.accept()
