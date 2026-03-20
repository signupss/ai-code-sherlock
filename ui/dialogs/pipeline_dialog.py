"""
Pipeline Dialog — full configuration UI.
Features: auto-input, 99-hour timeouts, 2M token limit, 8 AI strategies.
"""
from __future__ import annotations
import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
try:
    from ui.i18n import tr, register_listener, retranslate_widget
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass
    def retranslate_widget(w): pass
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
    PipelineStopCondition, AIStrategy, AI_STRATEGY_DESCRIPTIONS,
    CustomStrategy, ConsensusConfig, ConsensusMode
)


class PipelineDialog(QDialog):
    pipeline_saved = pyqtSignal(object)

    def __init__(self, config=None, parent=None, model_manager=None):
        super().__init__(parent)
        self._config = config or PipelineConfig()
        self._scripts: list[ScriptConfig] = list(self._config.scripts)
        self._current_script_row = -1
        self._model_manager = model_manager   # for model selector in consensus
        self._custom_strategies: list[CustomStrategy] = []
        self._patch_only_files: list[dict] = []   # [{"path": str, "rel": str, "group": str}]
        self.setWindowTitle("⚡ Auto-Improve Pipeline")
        self.setMinimumSize(960, 740)
        self.resize(1020, 820)
        self.setModal(True)
        self._build_ui()
        self._load_config(self._config)
        register_listener(lambda lang: self._retranslate_tabs())

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass
        # Retranslate on show in case language changed while dialog was hidden
        self._retranslate_tabs()

    def _retranslate_tabs(self):
        """Update tab labels and footer buttons to current language."""
        if not hasattr(self, "_tabs"):
            return
        tab_labels = [
            tr("⚙️  Основное"), tr("📜  Скрипты"), tr("📁  Файлы вывода"),
            tr("🧠  Стратегия AI"), tr("🤝  Консенсус AI"),
            tr("✏️  Мои стратегии"), tr("🔧  Расширенные"),
        ]
        for i, lbl in enumerate(tab_labels):
            if i < self._tabs.count():
                self._tabs.setTabText(i, lbl)
        # Footer buttons
        if hasattr(self, "_btn_load"):
            self._btn_load.setText(tr("📂 Загрузить"))
            self._btn_save_file.setText(tr("💾 Сохранить в файл"))
            self._btn_cancel.setText(tr("Отмена"))
            self._btn_once.setText(tr("▶ Запустить 1 раз"))
            self._btn_start.setText(tr("⚡ Запустить Pipeline"))

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
        t2 = QLabel(tr("  Настрой автономный цикл самоулучшения скриптов"))
        t2.setStyleSheet("color:#565f89;font-size:12px;")
        hl.addWidget(t1); hl.addWidget(t2); hl.addStretch()
        layout.addWidget(hdr)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_main_tab(),       tr("⚙️  Основное"))
        self._tabs.addTab(self._build_scripts_tab(),    tr("📜  Скрипты"))
        self._tabs.addTab(self._build_outputs_tab(),    tr("📁  Файлы вывода"))
        self._tabs.addTab(self._build_strategy_tab(),   tr("🧠  Стратегия AI"))
        self._tabs.addTab(self._build_consensus_tab(),  tr("🤝  Консенсус AI"))
        self._tabs.addTab(self._build_custom_strat_tab(), tr("✏️  Мои стратегии"))
        self._tabs.addTab(self._build_advanced_tab(),   tr("🔧  Расширенные"))
        layout.addWidget(self._tabs, stretch=1)

        footer = QFrame()
        footer.setStyleSheet("background:#0A0D14;border-top:1px solid #1E2030;")
        footer.setFixedHeight(54)
        fl = QHBoxLayout(footer); fl.setContentsMargins(16, 0, 16, 0)
        self._btn_load = QPushButton(tr("📂 Загрузить")); self._btn_load.clicked.connect(self._load_from_file)
        self._btn_save_file = QPushButton(tr("💾 Сохранить в файл")); self._btn_save_file.clicked.connect(self._save_to_file)
        fl.addWidget(self._btn_load); fl.addWidget(self._btn_save_file); fl.addStretch()
        self._btn_cancel = QPushButton(tr("Отмена")); self._btn_cancel.setFixedWidth(90)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_once = QPushButton(tr("▶ Запустить 1 раз")); self._btn_once.setFixedWidth(155)
        self._btn_once.setToolTip(tr("Одна итерация без цикла"))
        self._btn_once.clicked.connect(self._run_once)
        self._btn_start = QPushButton(tr("⚡ Запустить Pipeline"))
        self._btn_start.setObjectName("primaryBtn"); self._btn_start.setFixedWidth(185)
        self._btn_start.setStyleSheet(
            "QPushButton#primaryBtn{background:#BB9AF7;border:2px solid #9D7CD8;"
            "color:#0E1117;font-weight:bold;font-size:13px;border-radius:7px;}"
            "QPushButton#primaryBtn:hover{background:#CFA8FF;border-color:#BB9AF7;}"
            "QPushButton#primaryBtn:pressed{background:#9D7CD8;}"
        )
        self._btn_start.clicked.connect(self._on_start)
        fl.addWidget(self._btn_cancel); fl.addSpacing(8)
        fl.addWidget(self._btn_once); fl.addSpacing(8)
        fl.addWidget(self._btn_start)
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

        grp_id = QGroupBox(tr("Задание"))
        f = QFormLayout(grp_id); f.setSpacing(10)
        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText(tr("Название пайплайна"))
        f.addRow(tr("Название:"), self._fld_name)
        layout.addWidget(grp_id)

        grp_goal = QGroupBox(tr("Цель оптимизации"))
        gl = QVBoxLayout(grp_goal)
        gl.addWidget(QLabel(tr("Опиши что нужно улучшить. AI использует это как критерий успеха."),
                            styleSheet="color:#565f89;font-size:11px;"))
        self._fld_goal = QTextEdit()
        self._fld_goal.setPlaceholderText(
            tr("Пример: Улучшить Precision > 70% и Signal Rate > 25%.\nУстранять все ошибки в логах.\nОптимизировать параметры CatBoost без переобучения."))
        self._fld_goal.setFixedHeight(110)
        gl.addWidget(self._fld_goal)
        layout.addWidget(grp_goal)

        grp_stop = QGroupBox(tr("Условие остановки"))
        sf = QFormLayout(grp_stop); sf.setSpacing(10)
        self._cmb_stop = QComboBox()
        self._cmb_stop.addItem(tr("Максимум итераций"), PipelineStopCondition.MAX_ITERATIONS.value)
        self._cmb_stop.addItem(tr("Успешное завершение (exit 0)"), PipelineStopCondition.SUCCESS.value)
        self._cmb_stop.addItem(tr("Цель достигнута (AI пишет GOAL_ACHIEVED)"), PipelineStopCondition.GOAL_REACHED.value)
        self._cmb_stop.addItem(tr("Ручная остановка"), PipelineStopCondition.MANUAL.value)
        sf.addRow(tr("Условие:"), self._cmb_stop)
        self._spn_iterations = QSpinBox()
        self._spn_iterations.setRange(1, 9999); self._spn_iterations.setValue(10)
        sf.addRow(tr("Макс. итераций:"), self._spn_iterations)
        self._chk_auto_apply = QCheckBox(tr("Автоматически применять патчи"))
        self._chk_auto_apply.setChecked(True)
        sf.addRow("", self._chk_auto_apply)
        self._chk_auto_rollback = QCheckBox(tr("Автооткат при синтаксической ошибке"))
        self._chk_auto_rollback.setChecked(True)
        sf.addRow("", self._chk_auto_rollback)
        self._spn_retry = QSpinBox()
        self._spn_retry.setRange(0, 10); self._spn_retry.setValue(2)
        sf.addRow(tr("Повторов при неудаче:"), self._spn_retry)
        layout.addWidget(grp_stop)
        layout.addStretch()
        scroll.setWidget(inner); outer.addWidget(scroll)
        return w

    # ── Scripts Tab ───────────────────────────────────────────────────────────

    def _build_scripts_tab(self):
        w = QWidget()
        root = QVBoxLayout(w); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Top horizontal split: LEFT = script list, RIGHT = patch-only files ──
        top_split = QSplitter(Qt.Orientation.Horizontal); top_split.setHandleWidth(1)

        # ── LEFT: script list ──────────────────────────────────────────────────
        list_w = QWidget()
        ll = QVBoxLayout(list_w); ll.setContentsMargins(12, 8, 6, 4)

        hdr_l = QHBoxLayout()
        lbl = QLabel(tr("СКРИПТЫ В ПАЙПЛАЙНЕ")); lbl.setObjectName("sectionLabel")
        hdr_l.addWidget(lbl); hdr_l.addStretch()
        hint_run = QLabel(tr("● исполняются"))
        hint_run.setStyleSheet("color:#9ECE6A;font-size:10px;")
        hdr_l.addWidget(hint_run)
        ll.addLayout(hdr_l)

        self._script_table = QTableWidget(0, 5)
        self._script_table.setHorizontalHeaderLabels([tr("Роль"), tr("Файл"), tr("Аргументы"), tr("Таймаут"), tr("Патчить")])
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
        bp = QPushButton(tr("+ Добавить основной")); bp.setObjectName("successBtn")
        bp.clicked.connect(lambda: self._add_script(ScriptRole.PRIMARY))
        bv = QPushButton(tr("+ Добавить валидатор"))
        bv.clicked.connect(lambda: self._add_script(ScriptRole.VALIDATOR))
        bd = QPushButton(tr("✕ Удалить")); bd.setObjectName("dangerBtn"); bd.clicked.connect(self._remove_script)
        bu = QPushButton("↑"); bu.setFixedWidth(32); bu.clicked.connect(lambda: self._move_script(-1))
        bdn = QPushButton("↓"); bdn.setFixedWidth(32); bdn.clicked.connect(lambda: self._move_script(1))
        br.addWidget(bp); br.addWidget(bv); br.addStretch()
        br.addWidget(bu); br.addWidget(bdn); br.addWidget(bd)
        ll.addLayout(br)
        top_split.addWidget(list_w)

        # ── RIGHT: patch-only module files ────────────────────────────────────
        patch_w = QWidget()
        pl = QVBoxLayout(patch_w); pl.setContentsMargins(6, 8, 12, 4)

        hdr_r = QHBoxLayout()
        lbl_p = QLabel(tr("ФАЙЛЫ ДЛЯ ПАТЧИНГА")); lbl_p.setObjectName("sectionLabel")
        hdr_r.addWidget(lbl_p); hdr_r.addStretch()
        hint_patch = QLabel(tr("◈ не запускаются"))
        hint_patch.setStyleSheet("color:#BB9AF7;font-size:10px;")
        hdr_r.addWidget(hint_patch)
        pl.addLayout(hdr_r)

        pl.addWidget(QLabel(
            tr("Файлы которые AI будет патчить вместе со скриптом,\nно НЕ запускать — модули, конфиги, библиотеки."),
            styleSheet="color:#565f89;font-size:10px;"
        ))

        self._patch_files_table = QTableWidget(0, 3)
        self._patch_files_table.setHorizontalHeaderLabels([tr("Файл"), tr("Относительный путь"), tr("Группа")])
        self._patch_files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._patch_files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._patch_files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._patch_files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._patch_files_table.setStyleSheet("""
            QTableWidget{background:#131722;border:none;gridline-color:#1E2030;}
            QTableWidget::item{padding:3px 6px;}
            QTableWidget::item:selected{background:#1E2A3A;}
            QHeaderView::section{background:#0A0D14;border:none;
                border-bottom:1px solid #1E2030;padding:4px 6px;color:#565f89;font-size:10px;}
        """)
        pl.addWidget(self._patch_files_table)

        # Quick add bar
        qadd = QHBoxLayout()
        self._fld_patch_group = QLineEdit()
        self._fld_patch_group.setPlaceholderText(tr("Группа (напр. utils, models, config)…"))
        self._fld_patch_group.setMaximumWidth(180)
        self._fld_patch_group.setToolTip(
            tr("Необязательная метка группы — AI увидит связь файлов.\nНапример: 'models', 'utils', 'config', 'shared'")
        )
        qadd.addWidget(self._fld_patch_group)

        btn_add_patch_files = QPushButton(tr("+ Файлы"))
        btn_add_patch_files.setObjectName("successBtn")
        btn_add_patch_files.setToolTip(tr("Добавить отдельные файлы (модули, конфиги…)"))
        btn_add_patch_files.clicked.connect(self._add_patch_only_files)
        qadd.addWidget(btn_add_patch_files)

        btn_add_patch_folder = QPushButton(tr("+ Папка"))
        btn_add_patch_folder.setToolTip(
            tr("Добавить все файлы с нужными расширениями из папки.\nВыбор расширений появится после выбора папки.")
        )
        btn_add_patch_folder.clicked.connect(self._add_patch_only_folder)
        qadd.addWidget(btn_add_patch_folder)

        btn_rm_patch = QPushButton("✕"); btn_rm_patch.setObjectName("dangerBtn")
        btn_rm_patch.setFixedWidth(28)
        btn_rm_patch.clicked.connect(self._remove_patch_only_file)
        qadd.addWidget(btn_rm_patch)
        pl.addLayout(qadd)

        # Patch scope options
        scope_row = QHBoxLayout()
        self._chk_patch_scope_active = QCheckBox(tr("Только активный скрипт"))
        self._chk_patch_scope_active.setChecked(True)
        self._chk_patch_scope_active.setToolTip(
            tr("AI патчит только выбранный основной скрипт + файлы из этого списка.\nСнять галочку = патчить также все файлы открытые в редакторе.")
        )
        self._chk_patch_scope_active.setStyleSheet("font-size:11px;color:#A9B1D6;")

        self._chk_patch_scope_open = QCheckBox(tr("+ Все открытые в редакторе"))
        self._chk_patch_scope_open.setToolTip(
            tr("Дополнительно включить в патчинг все файлы,\nкоторые открыты во вкладках главного редактора.")
        )
        self._chk_patch_scope_open.setStyleSheet("font-size:11px;color:#A9B1D6;")
        scope_row.addWidget(self._chk_patch_scope_active)
        scope_row.addWidget(self._chk_patch_scope_open)
        scope_row.addStretch()
        pl.addLayout(scope_row)

        # Summary label
        self._lbl_patch_files_count = QLabel(tr("0 файлов для патчинга"))
        self._lbl_patch_files_count.setStyleSheet("color:#565f89;font-size:10px;")
        pl.addWidget(self._lbl_patch_files_count)

        top_split.addWidget(patch_w)
        top_split.setSizes([500, 460])
        root.addWidget(top_split, stretch=1)

        # ── BOTTOM: script details (scrollable) ───────────────────────────────
        # Collapsible header bar
        detail_hdr = QFrame()
        detail_hdr.setObjectName("panelHeader")
        detail_hdr.setFixedHeight(26)
        dhl = QHBoxLayout(detail_hdr); dhl.setContentsMargins(12, 0, 8, 0)
        lbl_d = QLabel(tr("ДЕТАЛИ СКРИПТА")); lbl_d.setObjectName("sectionLabel")
        self._lbl_detail_script = QLabel(tr("— нет выбранного —"))
        self._lbl_detail_script.setStyleSheet("color:#7AA2F7;font-size:11px;")
        dhl.addWidget(lbl_d); dhl.addSpacing(12); dhl.addWidget(self._lbl_detail_script)
        dhl.addStretch()
        root.addWidget(detail_hdr)

        ds = QScrollArea(); ds.setWidgetResizable(True); ds.setFrameShape(QFrame.Shape.NoFrame)
        ds.setMaximumHeight(360)
        di = QWidget(); dl = QVBoxLayout(di); dl.setContentsMargins(12, 8, 12, 8); dl.setSpacing(10)

        frm = QFormLayout(); frm.setSpacing(10)

        pr = QHBoxLayout()
        self._fld_script_path = QLineEdit(); self._fld_script_path.setPlaceholderText(tr("Путь к скрипту..."))
        bb = QPushButton("..."); bb.setObjectName("iconBtn"); bb.setFixedWidth(32)
        bb.clicked.connect(self._browse_script)
        pr.addWidget(self._fld_script_path); pr.addWidget(bb)
        frm.addRow(tr("Файл:"), pr)

        self._fld_args = QLineEdit(); self._fld_args.setPlaceholderText("arg1 arg2 ...")
        frm.addRow(tr("Аргументы:"), self._fld_args)

        wr = QHBoxLayout()
        self._fld_workdir = QLineEdit(); self._fld_workdir.setPlaceholderText(tr("(по умолчанию: папка скрипта)"))
        bw = QPushButton("..."); bw.setObjectName("iconBtn"); bw.setFixedWidth(32)
        bw.clicked.connect(self._browse_workdir)
        wr.addWidget(self._fld_workdir); wr.addWidget(bw)
        frm.addRow(tr("Рабочая папка:"), wr)

        # Extended timeout
        timeout_row = QHBoxLayout()
        self._spn_script_timeout = QSpinBox()
        self._spn_script_timeout.setRange(10, 356400)
        self._spn_script_timeout.setValue(3600); self._spn_script_timeout.setSuffix(tr(" сек"))
        self._spn_script_timeout.setToolTip(tr("3600=1ч  21600=6ч  86400=24ч  356400=99ч"))
        self._lbl_timeout_human = QLabel(tr("= 1 ч 0 мин"))
        self._lbl_timeout_human.setStyleSheet("color:#565f89;font-size:11px;")
        self._spn_script_timeout.valueChanged.connect(self._update_timeout_label)
        timeout_row.addWidget(self._spn_script_timeout); timeout_row.addWidget(self._lbl_timeout_human); timeout_row.addStretch()
        for lbl3, secs in [("1ч", 3600), ("6ч", 21600), ("12ч", 43200), ("24ч", 86400), ("99ч", 356400)]:
            bt = QPushButton(lbl3); bt.setFixedWidth(38)
            bt.clicked.connect(lambda _, s=secs: self._spn_script_timeout.setValue(s))
            timeout_row.addWidget(bt)
        frm.addRow(tr("Таймаут:"), timeout_row)

        self._chk_patchable = QCheckBox(tr("Разрешить AI патчить этот скрипт"))
        self._chk_patchable.setChecked(True)
        frm.addRow("", self._chk_patchable)

        self._fld_env_vars = QLineEdit(); self._fld_env_vars.setPlaceholderText("KEY=VALUE, KEY2=VALUE2")
        frm.addRow(tr("Переменные среды:"), self._fld_env_vars)
        dl.addLayout(frm)

        # Auto-input
        ai_grp = QGroupBox(tr("Авто-ввод (автоматические ответы скрипту)"))
        ai_grp.setToolTip(tr("Если скрипт спрашивает пользователя — задай автоответы здесь"))
        ail = QVBoxLayout(ai_grp); ail.setSpacing(6)
        self._chk_auto_input = QCheckBox(tr("Включить автоматические ответы stdin"))
        ail.addWidget(self._chk_auto_input)
        hint = QLabel(
            tr("Каждая строка = один ответ, отправляемый в stdin по порядку.\nПустая строка = Enter. Примеры: 'y', 'yes', 'all', '1', '0'")
        )
        hint.setStyleSheet("color:#565f89;font-size:11px;"); hint.setWordWrap(True)
        ail.addWidget(hint)
        self._fld_auto_input = QPlainTextEdit()
        self._fld_auto_input.setPlaceholderText(tr("y\n\nall\n\n(пустая строка = Enter)"))
        self._fld_auto_input.setFixedHeight(80)
        self._fld_auto_input.setFont(QFont("Cascadia Code,Consolas", 11))
        ail.addWidget(self._fld_auto_input)
        dr = QHBoxLayout()
        dr.addWidget(QLabel(tr("Задержка:")))
        self._spn_input_delay = QDoubleSpinBox()
        self._spn_input_delay.setRange(0.0, 10.0); self._spn_input_delay.setValue(0.3)
        self._spn_input_delay.setSingleStep(0.1); self._spn_input_delay.setSuffix(tr(" сек"))
        dr.addWidget(self._spn_input_delay); dr.addStretch()
        ail.addLayout(dr)
        dl.addWidget(ai_grp)

        bsave = QPushButton(tr("💾 Сохранить изменения скрипта"))
        bsave.setObjectName("primaryBtn"); bsave.clicked.connect(self._save_script_detail)
        dl.addWidget(bsave); dl.addStretch()
        ds.setWidget(di)
        root.addWidget(ds)
        return w

    # ── Patch-only files helpers ───────────────────────────────────────────────

    def _refresh_patch_files_table(self):
        """Rebuild the patch-only files table from self._patch_only_files."""
        self._patch_files_table.setRowCount(0)
        for entry in self._patch_only_files:
            row = self._patch_files_table.rowCount()
            self._patch_files_table.insertRow(row)
            from pathlib import Path as _Path
            p = _Path(entry["path"])
            name_item = QTableWidgetItem(f"◈ {p.name}")
            name_item.setForeground(QColor("#BB9AF7"))
            name_item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            rel_item  = QTableWidgetItem(entry.get("rel", str(p)))
            rel_item.setForeground(QColor("#565f89"))
            grp_item  = QTableWidgetItem(entry.get("group", ""))
            grp_item.setForeground(QColor("#E0AF68"))
            self._patch_files_table.setItem(row, 0, name_item)
            self._patch_files_table.setItem(row, 1, rel_item)
            self._patch_files_table.setItem(row, 2, grp_item)
        n = len(self._patch_only_files)
        if n == 0:
            count_text = tr("0 файлов для патчинга")
        elif n == 1:
            count_text = f"1 {tr('файл для патчинга')}"
        elif 1 < n < 5:
            count_text = f"{n} {tr('файла для патчинга')}"
        else:
            count_text = f"{n} {tr('файлов для патчинга')}"
        self._lbl_patch_files_count.setText(count_text)

    def _add_patch_only_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Выбери файлы для патчинга"),
            filter="Python & Code (*.py *.js *.ts *.json *.yaml *.yml *.toml *.cfg *.ini *.sql *.md);;All (*)"
        )
        group = self._fld_patch_group.text().strip()
        if paths:
            existing = {e["path"] for e in self._patch_only_files}
            from pathlib import Path as _Path
            for p in paths:
                if p not in existing:
                    self._patch_only_files.append({"path": p, "rel": _Path(p).name, "group": group})
            self._refresh_patch_files_table()

    def _add_patch_only_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Выбери папку с модулями"))
        if not folder:
            return
        from PyQt6.QtWidgets import QInputDialog
        exts_str, ok = QInputDialog.getText(
            self, tr("Расширения файлов"),
            tr("Включить файлы с расширениями (через пробел или запятую):"),
            text=".py .js .ts .json .yaml .yml .toml"
        )
        if not ok:
            return
        allowed = {e.strip().lstrip("*").lower() for e in exts_str.replace(",", " ").split() if e.strip()}
        group = self._fld_patch_group.text().strip() or folder.split("/")[-1]
        import os
        from pathlib import Path as _Path
        existing = {e["path"] for e in self._patch_only_files}
        added = 0
        for root_dir, dirs, files in os.walk(folder):
            # Skip hidden and venv dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".venv", "venv")]
            for fname in sorted(files):
                if allowed and _Path(fname).suffix.lower() not in allowed:
                    continue
                fpath = os.path.join(root_dir, fname)
                if fpath not in existing:
                    rel = os.path.relpath(fpath, folder)
                    self._patch_only_files.append({"path": fpath, "rel": rel, "group": group})
                    added += 1
        self._refresh_patch_files_table()
        if added == 0:
            QMessageBox.information(self, tr("Нет файлов"), f"{tr('В папке не найдено файлов с расширениями:')} {exts_str}")

    def _remove_patch_only_file(self):
        rows = sorted({idx.row() for idx in self._patch_files_table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self._patch_only_files):
                del self._patch_only_files[row]
        self._refresh_patch_files_table()

    # ── Outputs Tab ───────────────────────────────────────────────────────────

    def _build_outputs_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner); layout.setContentsMargins(20, 16, 20, 20); layout.setSpacing(14)

        info = QLabel(
            tr("Файлы которые скрипт генерирует — будут прикреплены к контексту AI.\nПоддерживаются: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet и любой текст.\nТакже можно мониторить папки и захватывать снимки окон программы.")
        )
        info.setStyleSheet("color:#565f89;font-size:12px;"); info.setWordWrap(True)
        layout.addWidget(info)

        # ── Specific output files per script ──────────────────────────────────
        grp_files = QGroupBox(tr("Выходные файлы по скриптам"))
        gl = QVBoxLayout(grp_files); gl.setSpacing(6)
        self._cmb_script_sel = QComboBox()
        self._cmb_script_sel.currentIndexChanged.connect(self._on_output_script_changed)
        gl.addWidget(self._cmb_script_sel)
        self._output_list = QListWidget()
        self._output_list.setStyleSheet("background:#131722;border:1px solid #1E2030;border-radius:6px;")
        self._output_list.setMinimumHeight(120)
        self._output_list.setMaximumHeight(130)
        gl.addWidget(self._output_list)
        ob = QHBoxLayout()
        for label, fn in [(tr("+ Файл"), self._add_output_file), (tr("+ Паттерн (glob)"), self._add_output_pattern)]:
            b = QPushButton(label); b.clicked.connect(fn); ob.addWidget(b)
        bd = QPushButton(tr("✕ Удалить")); bd.setObjectName("dangerBtn"); bd.clicked.connect(self._remove_output)
        ob.addStretch(); ob.addWidget(bd)
        gl.addLayout(ob)
        gl.addWidget(QLabel(tr("Примеры: *.csv   results/*.json   output_*   models/*.pkl"),
                            styleSheet="color:#3B4261;font-size:10px;"))
        layout.addWidget(grp_files)

        # ── Folder Monitoring ─────────────────────────────────────────────────
        grp_dirs = QGroupBox(tr("Мониторинг папок с файлами"))
        grp_dirs.setToolTip(
            tr("Наблюдает за папками — автоматически подхватывает новые и изменённые файлы, добавляет их в контекст AI.")
        )
        dl = QVBoxLayout(grp_dirs); dl.setSpacing(8)

        self._chk_folder_monitor = QCheckBox(tr("Включить мониторинг папок"))
        self._chk_folder_monitor.toggled.connect(self._on_folder_monitor_toggled)
        dl.addWidget(self._chk_folder_monitor)

        dl.addWidget(QLabel(
            tr("Добавь папки — все новые/изменённые файлы с нужными расширениями будут прикрепляться к контексту каждой итерации:"),
            styleSheet="color:#565f89;font-size:11px;"
        ))

        self._folder_list = QListWidget()
        self._folder_list.setStyleSheet(
            "QListWidget{background:#131722;border:1px solid #1E2030;border-radius:6px;}QListWidget::item{padding:5px 10px;}QListWidget::item:selected{background:#2E3148;}"
        )
        self._folder_list.setMaximumHeight(110)
        dl.addWidget(self._folder_list)

        fb_row = QHBoxLayout()
        btn_add_dir = QPushButton(tr("📁 Добавить папку"))
        btn_add_dir.clicked.connect(self._add_watch_folder)
        btn_rm_dir = QPushButton(tr("✕ Удалить")); btn_rm_dir.setObjectName("dangerBtn")
        btn_rm_dir.clicked.connect(self._remove_watch_folder)
        fb_row.addWidget(btn_add_dir); fb_row.addWidget(btn_rm_dir); fb_row.addStretch()
        dl.addLayout(fb_row)

        dir_form = QFormLayout(); dir_form.setSpacing(8)
        self._chk_subdirs = QCheckBox(tr("Включать подпапки рекурсивно"))
        self._chk_subdirs.setChecked(True)
        dir_form.addRow("", self._chk_subdirs)

        self._fld_watch_exts = QLineEdit()
        self._fld_watch_exts.setText(".csv .json .txt .log .xlsx .pkl .npy .npz .parquet .html .md")
        self._fld_watch_exts.setPlaceholderText(".csv .json .txt .log ...")
        self._fld_watch_exts.setToolTip(tr("Разделяй пробелом или запятой. Пусто = все файлы."))
        dir_form.addRow(tr("Расширения файлов:"), self._fld_watch_exts)

        self._chk_auto_ctx = QCheckBox(tr("Авто-включать новые файлы в контекст AI"))
        self._chk_auto_ctx.setChecked(True)
        dir_form.addRow("", self._chk_auto_ctx)

        self._spn_max_file_kb = QSpinBox()
        self._spn_max_file_kb.setRange(1, 50000); self._spn_max_file_kb.setValue(2048)
        self._spn_max_file_kb.setSuffix(tr(" КБ"))
        self._spn_max_file_kb.setToolTip(tr("Файлы крупнее этого порога будут усечены"))
        dir_form.addRow(tr("Макс. размер файла:"), self._spn_max_file_kb)

        self._chk_autoparse = QCheckBox(tr("Автопарсинг CSV/JSON — передавать структуру данных AI"))
        self._chk_autoparse.setChecked(True)
        dir_form.addRow("", self._chk_autoparse)

        self._chk_autoenc = QCheckBox(tr("Определять кодировку файлов автоматически"))
        self._chk_autoenc.setChecked(True)
        dir_form.addRow("", self._chk_autoenc)

        dl.addLayout(dir_form)
        layout.addWidget(grp_dirs)

        # ── Screenshot Capture ────────────────────────────────────────────────
        grp_ss = QGroupBox(tr("Захват снимка экрана / окна программы"))
        grp_ss.setToolTip(
            tr("Если скрипт открывает GUI-окно (например, браузер, программа-трекер), снимок экрана можно автоматически включить в контекст AI для анализа.")
        )
        sl = QVBoxLayout(grp_ss); sl.setSpacing(8)

        self._chk_screenshot = QCheckBox(tr("Включить захват снимков экрана"))
        self._chk_screenshot.toggled.connect(self._on_screenshot_toggled)
        sl.addWidget(self._chk_screenshot)

        sl.addWidget(QLabel(
            tr("Делает скриншот указанного окна (по паттерну заголовка) или всего экрана.\nИзображение передаётся AI для визуального анализа прогресса."),
            styleSheet="color:#565f89;font-size:11px;"
        ))

        ss_form = QFormLayout(); ss_form.setSpacing(8)

        self._fld_window_title = QLineEdit()
        self._fld_window_title.setPlaceholderText(tr("часть заголовка окна  (пусто = весь экран)"))
        self._fld_window_title.setToolTip(
            tr("Пример: 'Chrome', 'Notepad', 'TradingView'\nЗахватывается первое окно, заголовок которого содержит этот текст (регистр не важен).\nОставь пустым, чтобы снимать весь экран.")
        )
        ss_form.addRow(tr("Паттерн заголовка окна:"), self._fld_window_title)

        self._spn_ss_interval = QDoubleSpinBox()
        self._spn_ss_interval.setRange(0.5, 600); self._spn_ss_interval.setValue(5.0)
        self._spn_ss_interval.setSingleStep(0.5); self._spn_ss_interval.setSuffix(tr(" сек"))
        self._spn_ss_interval.setToolTip(tr("0.5=полсекунды  5=каждые 5 сек  60=раз в минуту"))
        ss_form.addRow(tr("Интервал захвата:"), self._spn_ss_interval)

        self._spn_ss_max = QSpinBox()
        self._spn_ss_max.setRange(1, 20); self._spn_ss_max.setValue(3)
        self._spn_ss_max.setToolTip(tr("Последние N снимков будут включены в контекст AI на каждой итерации"))
        ss_form.addRow(tr("Макс. снимков на итерацию:"), self._spn_ss_max)

        ss_path_row = QHBoxLayout()
        self._fld_ss_folder = QLineEdit()
        self._fld_ss_folder.setPlaceholderText(tr("screenshots/  (по умолчанию, рядом со скриптом)"))
        btn_ss_dir = QPushButton("..."); btn_ss_dir.setObjectName("iconBtn"); btn_ss_dir.setFixedWidth(32)
        btn_ss_dir.clicked.connect(self._browse_screenshot_folder)
        ss_path_row.addWidget(self._fld_ss_folder); ss_path_row.addWidget(btn_ss_dir)
        ss_form.addRow(tr("Папка для снимков:"), ss_path_row)

        ss_fmt_row = QHBoxLayout()
        self._cmb_ss_format = QComboBox()
        for fmt in [tr("PNG (без потерь)"), tr("JPEG (меньше размер)"), tr("WebP (сбаланс.)")]:
            self._cmb_ss_format.addItem(fmt)
        ss_fmt_row.addWidget(self._cmb_ss_format); ss_fmt_row.addStretch()
        ss_form.addRow(tr("Формат:"), ss_fmt_row)

        self._chk_ss_in_ctx = QCheckBox(tr("Включить снимки в контекст AI (multimodal)"))
        self._chk_ss_in_ctx.setChecked(True)
        self._chk_ss_in_ctx.setToolTip(
            tr("Передаёт снимки в запросы к AI-модели.\nТребует поддержки vision (GPT-4o, Claude, Gemini и др.).")
        )
        ss_form.addRow("", self._chk_ss_in_ctx)

        self._chk_ss_diff = QCheckBox(tr("Сохранять только снимки с изменениями (diff-порог)"))
        self._chk_ss_diff.setChecked(False)
        self._chk_ss_diff.setToolTip(
            tr("Пропускает снимки идентичные предыдущему (экономит контекст и место на диске).")
        )
        ss_form.addRow("", self._chk_ss_diff)

        sl.addLayout(ss_form)

        ss_hint = QLabel(
            tr("⚠  Для захвата окон на Windows используется win32gui/mss.\n   На Linux — scrot/gnome-screenshot (должен быть установлен).\n   Для работы multimodal AI нужна модель с поддержкой vision.")
        )
        ss_hint.setStyleSheet(
            "color:#565f89;font-size:10px;background:#0A0D14;border:1px solid #1E2030;border-radius:4px;padding:6px;"
        )
        ss_hint.setWordWrap(True)
        sl.addWidget(ss_hint)
        layout.addWidget(grp_ss)

        # ── Context limits ────────────────────────────────────────────────────
        grp2 = QGroupBox(tr("Лимиты контекста"))
        fl = QFormLayout(grp2); fl.setSpacing(10)
        self._spn_log_chars = QSpinBox(); self._spn_log_chars.setRange(1000, 200000)
        self._spn_log_chars.setValue(12000); self._spn_log_chars.setSingleStep(1000)
        self._spn_log_chars.setSuffix(tr(" симв"))
        fl.addRow(tr("Макс. символов лога:"), self._spn_log_chars)
        self._spn_file_chars = QSpinBox(); self._spn_file_chars.setRange(500, 50000)
        self._spn_file_chars.setValue(6000); self._spn_file_chars.setSingleStep(500)
        self._spn_file_chars.setSuffix(tr(" симв"))
        fl.addRow(tr("Макс. символов на файл:"), self._spn_file_chars)
        layout.addWidget(grp2)
        layout.addStretch()

        # Disable dependent widgets by default
        self._on_folder_monitor_toggled(False)
        self._on_screenshot_toggled(False)

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return w

    # ── Folder monitor / screenshot helpers ───────────────────────────────────

    def _on_folder_monitor_toggled(self, enabled: bool):
        for w in (self._folder_list, self._chk_subdirs, self._fld_watch_exts,
                  self._chk_auto_ctx, self._spn_max_file_kb,
                  self._chk_autoparse, self._chk_autoenc):
            if hasattr(self, w) if isinstance(w, str) else True:
                w.setEnabled(enabled)

    def _on_screenshot_toggled(self, enabled: bool):
        for w in (self._fld_window_title, self._spn_ss_interval, self._spn_ss_max,
                  self._fld_ss_folder, self._cmb_ss_format,
                  self._chk_ss_in_ctx, self._chk_ss_diff):
            w.setEnabled(enabled)

    def _add_watch_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Выбери папку для мониторинга"))
        if d:
            item = QListWidgetItem(f"📁 {d}")
            item.setData(Qt.ItemDataRole.UserRole, d)
            self._folder_list.addItem(item)

    def _remove_watch_folder(self):
        row = self._folder_list.currentRow()
        if row >= 0:
            self._folder_list.takeItem(row)

    def _browse_screenshot_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Папка для снимков экрана"))
        if d:
            self._fld_ss_folder.setText(d)

    # ── Strategy Tab ──────────────────────────────────────────────────────────

    def _build_strategy_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20,16,20,16); layout.setSpacing(14)
        layout.addWidget(QLabel(
            tr("Стратегия определяет как AI подходит к улучшению кода — консервативно или агрессивно, исследуя или эксплуатируя успех."),
            styleSheet="color:#A9B1D6;font-size:12px;"))

        grp_s = QGroupBox(tr("Стратегия AI"))
        sl = QFormLayout(grp_s); sl.setSpacing(10)
        self._cmb_strategy = QComboBox()
        for strat in AIStrategy:
            icon = {"conservative":"🛡","balanced":"⚖️","aggressive":"🚀",
                    "explorer":"🔭","exploit":"💎","safe_ratchet":"🔒",
                    "hypothesis":"🔬","ensemble":"🎭"}.get(strat.value, "●")
            self._cmb_strategy.addItem(f"{icon} {strat.value.replace('_',' ').title()}", strat.value)
        self._cmb_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        sl.addRow(tr("Стратегия:"), self._cmb_strategy)

        self._lbl_strategy_desc = QLabel()
        self._lbl_strategy_desc.setStyleSheet(
            "color:#A9B1D6;font-size:12px;background:#131722;border:1px solid #1E2030;border-radius:6px;padding:10px;")
        self._lbl_strategy_desc.setWordWrap(True); self._lbl_strategy_desc.setMinimumHeight(70)
        sl.addRow("", self._lbl_strategy_desc)

        self._spn_strategy_switch = QSpinBox()
        self._spn_strategy_switch.setRange(1,20); self._spn_strategy_switch.setValue(3)
        self._spn_strategy_switch.setToolTip(tr("Для EXPLORER: через сколько итераций менять подход"))
        sl.addRow(tr("Ротация (Explorer):"), self._spn_strategy_switch)
        layout.addWidget(grp_s)

        grp_m = QGroupBox(tr("Память и лимит токенов"))
        ml = QFormLayout(grp_m); ml.setSpacing(10)
        self._chk_include_patches = QCheckBox(tr("Включать историю патчей в промпт"))
        self._chk_include_patches.setChecked(True)
        ml.addRow("", self._chk_include_patches)
        self._spn_memory = QSpinBox()
        self._spn_memory.setRange(1,50); self._spn_memory.setValue(5)
        self._spn_memory.setToolTip(tr("Сколько прошлых итераций включать в контекст"))
        ml.addRow(tr("Итераций в памяти:"), self._spn_memory)

        # Token limit up to 2M
        tokens_row = QHBoxLayout()
        self._spn_tokens = QSpinBox()
        self._spn_tokens.setRange(4096, 2_000_000); self._spn_tokens.setValue(200_000)
        self._spn_tokens.setSingleStep(10_000)
        self._spn_tokens.setToolTip(tr("200k=стандарт, 1M=Gemini 1.5 Pro, 2M=Gemini 1.5 Ultra"))
        tokens_row.addWidget(self._spn_tokens)
        for label, val in [("200k", 200_000), ("500k", 500_000), ("1M", 1_000_000), ("2M", 2_000_000)]:
            bt = QPushButton(label); bt.setFixedWidth(52)
            bt.clicked.connect(lambda _, v=val: self._spn_tokens.setValue(v))
            tokens_row.addWidget(bt)
        tokens_row.addStretch()
        ml.addRow(tr("Лимит токенов:"), tokens_row)
        layout.addWidget(grp_m)

        grp_met = QGroupBox(tr("Паттерны извлечения метрик из лога (regex)"))
        gml = QVBoxLayout(grp_met)
        gml.addWidget(QLabel(
            tr("Первая группа захвата = числовое значение метрики.\nAI будет видеть тренд метрик и принимать решения на основе них."),
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

    def _build_consensus_tab(self):
        """Multi-AI consensus configuration."""
        w = QWidget()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner); layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        top_hint = QLabel(
            tr("Консенсус AI — запрашивает несколько моделей одновременно и выбирает лучший ответ.\nПовышает качество патчей за счёт перекрёстной проверки.")
        )
        top_hint.setStyleSheet("color:#A9B1D6;font-size:12px;"); top_hint.setWordWrap(True)
        layout.addWidget(top_hint)

        grp_en = QGroupBox(tr("Включить консенсус"))
        el = QFormLayout(grp_en); el.setSpacing(10)
        self._chk_consensus = QCheckBox(tr("Использовать несколько AI-моделей"))
        self._chk_consensus.toggled.connect(self._on_consensus_toggled)
        el.addRow("", self._chk_consensus)

        self._cmb_consensus_mode = QComboBox()
        self._cmb_consensus_mode.addItem(tr("🗳 Голосование (Vote) — патч принимается если ≥N моделей согласны"), ConsensusMode.VOTE.value)
        self._cmb_consensus_mode.addItem(tr("🏆 Best-of-N — лучший ответ (больше патчей)"), ConsensusMode.BEST_OF_N.value)
        self._cmb_consensus_mode.addItem(tr("🔀 Merge — объединить уникальные патчи из всех"), ConsensusMode.MERGE.value)
        self._cmb_consensus_mode.addItem(tr("⚖️ Judge — одна модель оценивает ответы других"), ConsensusMode.JUDGE.value)
        self._cmb_consensus_mode.currentIndexChanged.connect(self._on_consensus_mode_changed)
        el.addRow(tr("Режим:"), self._cmb_consensus_mode)

        self._spn_min_agree = QSpinBox()
        self._spn_min_agree.setRange(2, 10); self._spn_min_agree.setValue(2)
        self._spn_min_agree.setToolTip(tr("Для режима Vote: сколько моделей должны предложить один патч"))
        el.addRow(tr("Мин. согласие (Vote):"), self._spn_min_agree)

        self._spn_timeout_per = QSpinBox()
        self._spn_timeout_per.setRange(10, 600); self._spn_timeout_per.setValue(120)
        self._spn_timeout_per.setSuffix(tr(" сек"))
        el.addRow(tr("Таймаут на модель:"), self._spn_timeout_per)

        layout.addWidget(grp_en)

        grp_models = QGroupBox(tr("Модели для консенсуса"))
        ml = QVBoxLayout(grp_models)
        ml.addWidget(QLabel(tr("Выбери модели которые будут участвовать в консенсусе:"),
                            styleSheet="color:#565f89;font-size:11px;"))

        self._consensus_model_list = QListWidget()
        self._consensus_model_list.setMaximumHeight(160)
        self._consensus_model_list.setStyleSheet(
            "QListWidget{background:#131722;border:1px solid #1E2030;border-radius:8px;}QListWidget::item{padding:7px 12px;border-bottom:1px solid #1E2030;}QListWidget::item:selected{background:#2E3148;}"
        )
        ml.addWidget(self._consensus_model_list)

        ml.addWidget(QLabel(tr("Нажми ↑ чтобы обновить список из настроек моделей."),
                            styleSheet="color:#3B4261;font-size:10px;"))
        btn_refresh_models = QPushButton(tr("↑ Обновить список моделей"))
        btn_refresh_models.clicked.connect(self._refresh_consensus_models)
        ml.addWidget(btn_refresh_models)

        layout.addWidget(grp_models)

        grp_judge = QGroupBox(tr("Судья (для режима Judge)"))
        jl = QFormLayout(grp_judge); jl.setSpacing(10)
        self._cmb_judge_model = QComboBox()
        jl.addRow(tr("Модель-судья:"), self._cmb_judge_model)
        self._refresh_consensus_models()  # both _consensus_model_list and _cmb_judge_model now exist
        self._judge_hint = QLabel(
            tr("Судья получает все ответы других моделей и выбирает лучший.")
        )
        self._judge_hint.setStyleSheet("color:#565f89;font-size:11px;")
        jl.addRow("", self._judge_hint)
        layout.addWidget(grp_judge)

        self._on_consensus_toggled(False)  # disabled by default
        layout.addStretch()
        scroll.setWidget(inner)
        outer = QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return w

    def _build_custom_strat_tab(self):
        """Custom strategy management tab."""
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        hint = QLabel(
            tr("Создавай собственные стратегии AI с полностью кастомными инструкциями.\nАктивная кастомная стратегия заменяет стандартную стратегию из вкладки 'Стратегия AI'.")
        )
        hint.setStyleSheet("color:#A9B1D6;font-size:12px;"); hint.setWordWrap(True)
        layout.addWidget(hint)

        grp = QGroupBox(tr("Активная кастомная стратегия"))
        gl = QFormLayout(grp); gl.setSpacing(10)

        self._chk_use_custom = QCheckBox(tr("Использовать кастомную стратегию вместо стандартной"))
        gl.addRow("", self._chk_use_custom)

        strat_row = QHBoxLayout()
        self._cmb_custom_strat = QComboBox()
        self._cmb_custom_strat.addItem(tr("(нет кастомных стратегий)"), "")
        btn_edit_strats = QPushButton(tr("✏️ Редактор стратегий"))
        btn_edit_strats.clicked.connect(self._open_strategy_editor)
        strat_row.addWidget(self._cmb_custom_strat, stretch=1)
        strat_row.addWidget(btn_edit_strats)
        gl.addRow(tr("Стратегия:"), strat_row)

        self._lbl_custom_desc = QLabel("")
        self._lbl_custom_desc.setStyleSheet(
            "color:#A9B1D6;font-size:11px;background:#131722;border:1px solid #1E2030;border-radius:6px;padding:8px;"
        )
        self._lbl_custom_desc.setWordWrap(True)
        self._lbl_custom_desc.setMinimumHeight(50)
        gl.addRow("", self._lbl_custom_desc)

        self._cmb_custom_strat.currentIndexChanged.connect(self._on_custom_strat_changed)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _build_advanced_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w); layout.setContentsMargins(20,16,20,16); layout.setSpacing(12)
        grp = QGroupBox(tr("Поведение AI"))
        al = QFormLayout(grp); al.setSpacing(10)
        self._chk_prev_patches = QCheckBox(tr("Включать историю патчей (AI не повторяет неудачные)"))
        self._chk_prev_patches.setChecked(True)
        al.addRow("", self._chk_prev_patches)
        self._chk_error_map = QCheckBox(tr("Использовать карту ошибок (запрещённые подходы)"))
        self._chk_error_map.setChecked(True)
        al.addRow("", self._chk_error_map)
        layout.addWidget(grp)
        grp2 = QGroupBox(tr("Безопасность"))
        sl2 = QFormLayout(grp2); sl2.setSpacing(10)
        self._chk_syntax_check = QCheckBox(tr("Проверять синтаксис Python перед применением патча"))
        self._chk_syntax_check.setChecked(True)
        sl2.addRow("", self._chk_syntax_check)
        self._chk_backup = QCheckBox(tr("Резервная копия перед каждым патчем (.backups/)"))
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
        # Restore patch-only files
        self._patch_only_files = list(getattr(cfg, "patch_only_files", []))
        self._refresh_patch_files_table()
        if getattr(cfg, "patch_scope_open_files", False):
            self._chk_patch_scope_open.setChecked(True)
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

        # Patch-only module files
        cfg.patch_only_files = list(self._patch_only_files)
        cfg.patch_scope_open_files = getattr(self, "_chk_patch_scope_open", None) and \
                                     self._chk_patch_scope_open.isChecked()

        # Custom strategy
        if self._chk_use_custom.isChecked():
            sid = self._cmb_custom_strat.currentData()
            cfg.custom_strategy = next(
                (s for s in self._custom_strategies if s.id == sid), None
            )
        else:
            cfg.custom_strategy = None

        # Consensus
        if self._chk_consensus.isChecked():
            checked_ids = []
            from PyQt6.QtCore import Qt
            for i in range(self._consensus_model_list.count()):
                item = self._consensus_model_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    checked_ids.append(item.data(Qt.ItemDataRole.UserRole))
            cfg.consensus = ConsensusConfig(
                enabled=True,
                mode=ConsensusMode(self._cmb_consensus_mode.currentData()),
                model_ids=checked_ids,
                judge_model_id=self._cmb_judge_model.currentData() or "",
                min_agreement=self._spn_min_agree.value(),
                timeout_per_model=self._spn_timeout_per.value(),
            )
        else:
            cfg.consensus = None

        return cfg

    # ══════════════════════════════════════════════════════
    #  Script table
    # ══════════════════════════════════════════════════════

    def _refresh_script_table(self):
        self._script_table.setRowCount(len(self._scripts))
        for row, sc in enumerate(self._scripts):
            if sc.role == ScriptRole.PRIMARY:
                rt, rc = tr("🎯 Основной"), "#9ECE6A"
            else:
                rt, rc = tr("✓ Валидатор"), "#7AA2F7"
            ri = QTableWidgetItem(rt); ri.setForeground(QColor(rc))
            self._script_table.setItem(row, 0, ri)
            self._script_table.setItem(row, 1, QTableWidgetItem(sc.name))
            self._script_table.setItem(row, 2, QTableWidgetItem(" ".join(sc.args)))
            h, r2 = divmod(sc.timeout_seconds, 3600)
            m, _ = divmod(r2, 60)
            ts = f"{h}{tr('ч')} {m}{tr('м')}" if h else f"{m}{tr('м')}" if m else f"{sc.timeout_seconds}{tr('с')}"
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
        self._fld_env_vars.setText(", ".join(f"{k}={v}" for k, v in sc.env_vars.items()))
        self._chk_auto_input.setChecked(sc.auto_input.enabled)
        self._fld_auto_input.setPlainText("\n".join(sc.auto_input.sequences))
        self._spn_input_delay.setValue(sc.auto_input.delay_seconds)
        # Update detail header
        from pathlib import Path as _Path
        name = _Path(sc.script_path).name if sc.script_path else tr("— нет выбранного —")
        role_badge = "🎯 " if sc.role == ScriptRole.PRIMARY else "✓ "
        self._lbl_detail_script.setText(f"{role_badge}{name}")

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
        path, _ = QFileDialog.getOpenFileName(self, tr("Выбери скрипт"),
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
        p, _ = QFileDialog.getOpenFileName(self, tr("Скрипт"), filter="Scripts (*.py *.bat *.sh);;All (*)")
        if p: self._fld_script_path.setText(p)

    def _browse_workdir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Рабочая папка"))
        if d: self._fld_workdir.setText(d)

    def _update_timeout_label(self, secs):
        h, r = divmod(secs, 3600); m, s = divmod(r, 60)
        if h: self._lbl_timeout_human.setText(f"= {h} {tr('ч')} {m} {tr('мин')}")
        elif m: self._lbl_timeout_human.setText(f"= {m} {tr('мин')} {s} {tr('сек')}")
        else: self._lbl_timeout_human.setText(f"= {s} {tr('сек')}")

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
            item = QListWidgetItem(f"🔍 {p}  [{tr('паттерн')}]")
            item.setData(Qt.ItemDataRole.UserRole, ("pattern", p))
            item.setForeground(QColor("#E0AF68")); self._output_list.addItem(item)

    def _add_output_file(self):
        idx = self._cmb_script_sel.currentIndex()
        if idx < 0 or idx >= len(self._scripts): return
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Выходные файлы"),
            filter="Data (*.csv *.json *.txt *.log *.xlsx *.pkl *.npy *.npz *.parquet);;All (*)")
        for p in paths: self._scripts[idx].output_files.append(p)
        self._on_output_script_changed(idx)

    def _add_output_pattern(self):
        idx = self._cmb_script_sel.currentIndex()
        if idx < 0 or idx >= len(self._scripts): return
        from PyQt6.QtWidgets import QInputDialog
        pattern, ok = QInputDialog.getText(self, tr("Glob-паттерн"), tr("Паттерн (*.csv, results/*.json, ...): "))
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

    def _on_consensus_toggled(self, enabled: bool):
        widgets = [
            "_cmb_consensus_mode", "_spn_min_agree",
            "_spn_timeout_per", "_consensus_model_list", "_cmb_judge_model"
        ]
        for name in widgets:
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(enabled)

    def _on_consensus_mode_changed(self):
        mode = self._cmb_consensus_mode.currentData()
        if hasattr(self, "_spn_min_agree"):
            self._spn_min_agree.setEnabled(mode == ConsensusMode.VOTE.value)
        if hasattr(self, "_cmb_judge_model"):
            self._cmb_judge_model.setEnabled(mode == ConsensusMode.JUDGE.value)

    def _refresh_consensus_models(self):
        self._consensus_model_list.clear()
        self._cmb_judge_model.clear()
        models = []
        if self._model_manager:
            try:
                models = self._model_manager.get_all_model_ids()
            except Exception:
                pass
        if not models:
            # Try loading from settings
            try:
                from services.settings_manager import SettingsManager
                s = SettingsManager().load()
                models = [(m.id, m.display_name) for m in s.models]
            except Exception:
                pass
        for mid, name in models:
            item = __import__('PyQt6.QtWidgets', fromlist=['QListWidgetItem']).QListWidgetItem(name)
            item.setFlags(item.flags() | __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.CheckState.Unchecked)
            item.setData(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.ItemDataRole.UserRole, mid)
            self._consensus_model_list.addItem(item)
            self._cmb_judge_model.addItem(name, mid)

    def _open_strategy_editor(self):
        from ui.dialogs.custom_strategy_editor import CustomStrategyEditor
        dlg = CustomStrategyEditor(
            all_strategies=self._custom_strategies, parent=self
        )
        if dlg.exec():
            self._custom_strategies = dlg.get_all_strategies()
            self._refresh_custom_strat_combo()

    def _refresh_custom_strat_combo(self):
        self._cmb_custom_strat.clear()
        self._cmb_custom_strat.addItem(tr("(нет / использовать стандартную)"), "")
        for s in self._custom_strategies:
            self._cmb_custom_strat.addItem(f"{s.icon} {s.name}", s.id)

    def _on_custom_strat_changed(self):
        sid = self._cmb_custom_strat.currentData()
        s = next((x for x in self._custom_strategies if x.id == sid), None)
        if s:
            self._lbl_custom_desc.setText(s.description or s.system_prompt[:120])
        else:
            self._lbl_custom_desc.setText("")

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _save_to_file(self):
        cfg = self._collect_config()
        p, _ = QFileDialog.getSaveFileName(self, tr("Сохранить"), f"{cfg.name}.pipeline.json",
                                           "Pipeline (*.pipeline.json);;JSON (*.json)")
        if p: Path(p).write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_from_file(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("Загрузить"), filter="Pipeline (*.pipeline.json *.json)")
        if p:
            try:
                cfg = PipelineConfig.from_dict(json.loads(Path(p).read_text(encoding="utf-8")))
                self._scripts = list(cfg.scripts)
                self._load_config(cfg)
            except Exception as e:
                QMessageBox.critical(self, tr("Ошибка"), f"{tr('Не удалось загрузить:')} {e}")

    def _run_once(self):
        cfg = self._collect_config()
        if not cfg.scripts:
            QMessageBox.warning(self, tr("Нет скриптов"), tr("Добавь скрипты.")); return
        cfg.max_iterations = 1
        cfg.stop_condition = PipelineStopCondition.MAX_ITERATIONS
        self._config = cfg; self.pipeline_saved.emit(cfg); self.accept()

    def _on_start(self):
        cfg = self._collect_config()
        if not cfg.scripts:
            QMessageBox.warning(self, tr("Нет скриптов"), tr("Добавь скрипты.")); return
        if not cfg.goal.strip():
            QMessageBox.warning(self, tr("Нет цели"), tr("Укажи цель на вкладке 'Основное'.")); return
        self._config = cfg; self.pipeline_saved.emit(cfg); self.accept()