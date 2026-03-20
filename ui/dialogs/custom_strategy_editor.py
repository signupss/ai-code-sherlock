"""
Custom Strategy Editor — create and manage user-defined AI strategies.
"""
from __future__ import annotations
import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QWidget, QFrame, QFormLayout,
    QGroupBox, QListWidget, QListWidgetItem, QSplitter,
    QSpinBox, QDoubleSpinBox, QCheckBox, QMessageBox,
    QFileDialog, QScrollArea
)

from services.pipeline_models import CustomStrategy


class CustomStrategyEditor(QDialog):
    """
    Full editor for custom AI strategies.
    Can be opened standalone or embedded in pipeline dialog.
    """
    strategy_saved = pyqtSignal(object)   # CustomStrategy

    # Default template strategies users can start from
    TEMPLATES = {
        "Пустой шаблон": CustomStrategy(
            name="Моя стратегия",
            description="Описание стратегии",
            system_prompt="",
            icon="✏️",
        ),
        "Оптимизация метрик": CustomStrategy(
            name="Metric Pusher",
            description="Фокус на улучшении числовых метрик из лога",
            icon="📈",
            system_prompt=(
                "СТРАТЕГИЯ: ОПТИМИЗАЦИЯ МЕТРИК\n"
                "- Извлеки все числовые метрики из лога\n"
                "- Определи какая метрика отстаёт от цели\n"
                "- Внеси изменение которое ПРЯМО влияет на эту метрику\n"
                "- В анализе укажи: текущее значение → ожидаемое после патча\n"
                "- Не трогай код не связанный с метриками"
            ),
            focus_on_metrics=True,
            max_patches_per_iter=2,
        ),
        "Дебаггер": CustomStrategy(
            name="Bug Hunter",
            description="Охота на баги — только ошибки, никаких улучшений",
            icon="🐛",
            system_prompt=(
                "СТРАТЕГИЯ: ОХОТНИК НА БАГИ\n"
                "- Найди ВСЕ ошибки и исключения в логе\n"
                "- Для каждой ошибки: опиши root cause (одно предложение)\n"
                "- Исправляй ТОЛЬКО ошибки — не улучшай ничего\n"
                "- Если ошибок нет — напиши GOAL_ACHIEVED\n"
                "- Каждый патч должен исправлять ровно одну ошибку"
            ),
            focus_on_metrics=False,
            max_patches_per_iter=5,
        ),
        "Рефакторинг": CustomStrategy(
            name="Refactor Mode",
            description="Улучшение структуры и читаемости кода",
            icon="🔧",
            system_prompt=(
                "СТРАТЕГИЯ: РЕФАКТОРИНГ\n"
                "- Улучшай структуру, читаемость и надёжность кода\n"
                "- Извлекай повторяющийся код в функции\n"
                "- Добавляй обработку исключений где её нет\n"
                "- Улучшай имена переменных и функций\n"
                "- НЕ меняй алгоритмическую логику"
            ),
            focus_on_metrics=False,
            max_patches_per_iter=4,
        ),
        "Параметры ML": CustomStrategy(
            name="Hyperopt Assistant",
            description="Оптимизация гиперпараметров ML моделей",
            icon="⚗️",
            system_prompt=(
                "СТРАТЕГИЯ: ОПТИМИЗАЦИЯ ГИПЕРПАРАМЕТРОВ\n"
                "- Анализируй метрики обучения в логе\n"
                "- Определи признаки переобучения (train >> val) или недообучения (train ≈ val, оба низкие)\n"
                "- При переобучении: уменьши learning rate, добавь регуляризацию, уменьши сложность\n"
                "- При недообучении: увеличь capacity, lr, epochs\n"
                "- Меняй только числовые параметры — не трогай архитектуру\n"
                "- Документируй почему выбрал именно эти значения"
            ),
            focus_on_metrics=True,
            max_patches_per_iter=3,
        ),
    }

    def __init__(self, strategy: CustomStrategy | None = None,
                 all_strategies: list[CustomStrategy] | None = None,
                 parent=None):
        super().__init__(parent)
        self._current = strategy or CustomStrategy()
        self._all_strategies = list(all_strategies or [])
        self._editing_idx = -1

        self.setWindowTitle("Редактор пользовательских стратегий")
        self.setMinimumSize(860, 640)
        self.resize(960, 700)
        self.setModal(True)
        self._build_ui()
        self._load_all()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet("background:#0A0D14;border-bottom:1px solid #1E2030;")
        hdr.setFixedHeight(50)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 0, 20, 0)
        t = QLabel("✏️ Пользовательские стратегии AI")
        t.setStyleSheet("font-size:15px;font-weight:bold;color:#CDD6F4;")
        hl.addWidget(t); hl.addStretch()
        layout.addWidget(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: list of strategies ───────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 12, 6, 12)
        lbl = QLabel("МОИ СТРАТЕГИИ")
        lbl.setObjectName("sectionLabel")
        ll.addWidget(lbl)

        self._strategy_list = QListWidget()
        self._strategy_list.setStyleSheet(
            "QListWidget{background:#131722;border:1px solid #1E2030;border-radius:8px;}"
            "QListWidget::item{padding:10px 12px;border-bottom:1px solid #1E2030;}"
            "QListWidget::item:selected{background:#2E3148;}"
        )
        self._strategy_list.currentRowChanged.connect(self._on_strategy_selected)
        ll.addWidget(self._strategy_list)

        # Templates
        tmpl_lbl = QLabel("Шаблоны:")
        tmpl_lbl.setStyleSheet("color:#565f89;font-size:11px;margin-top:8px;")
        ll.addWidget(tmpl_lbl)

        self._cmb_template = QListWidget()
        self._cmb_template.setMaximumHeight(120)
        self._cmb_template.setStyleSheet(
            "QListWidget{background:#0A0D14;border:1px solid #1E2030;border-radius:6px;}"
            "QListWidget::item{padding:5px 10px;font-size:11px;}"
            "QListWidget::item:selected{background:#1E2030;}"
        )
        for name in self.TEMPLATES:
            item = QListWidgetItem(name)
            self._cmb_template.addItem(item)
        ll.addWidget(self._cmb_template)

        btn_from_template = QPushButton("Создать из шаблона")
        btn_from_template.clicked.connect(self._create_from_template)
        ll.addWidget(btn_from_template)

        btn_row = QHBoxLayout()
        btn_new = QPushButton("+ Новая")
        btn_new.setObjectName("successBtn")
        btn_new.clicked.connect(self._new_strategy)
        btn_del = QPushButton("✕ Удалить")
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete_strategy)
        btn_row.addWidget(btn_new); btn_row.addWidget(btn_del)
        ll.addLayout(btn_row)

        left.setMinimumWidth(220)
        left.setMaximumWidth(280)
        splitter.addWidget(left)

        # ── Right: editor ──────────────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_inner = QWidget()
        rl = QVBoxLayout(right_inner)
        rl.setContentsMargins(12, 12, 16, 12)
        rl.setSpacing(16)

        lbl2 = QLabel("РЕДАКТОР СТРАТЕГИИ")
        lbl2.setObjectName("sectionLabel")
        rl.addWidget(lbl2)

        # Basic info
        grp_basic = QGroupBox("Основное")
        bf = QFormLayout(grp_basic); bf.setSpacing(10)

        name_row = QHBoxLayout()
        self._fld_icon = QLineEdit(); self._fld_icon.setFixedWidth(48)
        self._fld_icon.setPlaceholderText("🔬")
        self._fld_icon.setFont(QFont("Segoe UI Emoji", 14))
        self._fld_name = QLineEdit(); self._fld_name.setPlaceholderText("Название стратегии")
        name_row.addWidget(self._fld_icon); name_row.addWidget(self._fld_name)
        bf.addRow("Иконка + Название:", name_row)

        self._fld_desc = QLineEdit()
        self._fld_desc.setPlaceholderText("Краткое описание (будет показано в списке)")
        bf.addRow("Описание:", self._fld_desc)

        rl.addWidget(grp_basic)

        # System prompt
        grp_prompt = QGroupBox("Системный промпт стратегии")
        pl = QVBoxLayout(grp_prompt)
        hint = QLabel(
            "Инструкции для AI. Что именно делать, как принимать решения, "
            "на что обращать внимание. Пиши чётко и директивно."
        )
        hint.setStyleSheet("color:#565f89;font-size:11px;")
        hint.setWordWrap(True)
        pl.addWidget(hint)

        self._fld_prompt = QTextEdit()
        self._fld_prompt.setPlaceholderText(
            "СТРАТЕГИЯ: МОЯ\n"
            "- Сначала анализируй ошибки в логе\n"
            "- Затем проверяй метрики\n"
            "- Делай минимальные изменения\n"
            "- Объясняй каждый патч"
        )
        self._fld_prompt.setFont(QFont("Cascadia Code,JetBrains Mono,Consolas", 11))
        self._fld_prompt.setMinimumHeight(200)
        pl.addWidget(self._fld_prompt)

        rl.addWidget(grp_prompt)

        # Behavior options
        grp_opts = QGroupBox("Параметры поведения")
        of = QFormLayout(grp_opts); of.setSpacing(10)

        self._chk_require_analysis = QCheckBox(
            "Требовать анализ перед патчами (3-5 предложений)")
        self._chk_require_analysis.setChecked(True)
        of.addRow("", self._chk_require_analysis)

        self._chk_focus_metrics = QCheckBox(
            "Акцент на метриках из лога")
        self._chk_focus_metrics.setChecked(True)
        of.addRow("", self._chk_focus_metrics)

        self._spn_max_patches = QSpinBox()
        self._spn_max_patches.setRange(0, 20)
        self._spn_max_patches.setValue(3)
        self._spn_max_patches.setToolTip("0 = без ограничений")
        of.addRow("Макс. патчей за итерацию:", self._spn_max_patches)

        self._spn_temp = QDoubleSpinBox()
        self._spn_temp.setRange(-1.0, 2.0)
        self._spn_temp.setValue(-1.0)
        self._spn_temp.setSingleStep(0.05)
        self._spn_temp.setToolTip("-1 = использовать температуру из настроек модели")
        of.addRow("Temperature (−1 = default):", self._spn_temp)

        rl.addWidget(grp_opts)

        # Save button
        btn_save = QPushButton("💾 Сохранить стратегию")
        btn_save.setObjectName("primaryBtn")
        btn_save.clicked.connect(self._save_current)
        rl.addWidget(btn_save)
        rl.addStretch()

        right_scroll.setWidget(right_inner)
        splitter.addWidget(right_scroll)
        splitter.setSizes([250, 680])
        layout.addWidget(splitter, stretch=1)

        # Footer
        footer = QFrame()
        footer.setStyleSheet("background:#0A0D14;border-top:1px solid #1E2030;")
        footer.setFixedHeight(52)
        fl = QHBoxLayout(footer); fl.setContentsMargins(16, 0, 16, 0)
        btn_imp = QPushButton("📂 Импорт JSON")
        btn_imp.clicked.connect(self._import_json)
        btn_exp = QPushButton("💾 Экспорт JSON")
        btn_exp.clicked.connect(self._export_json)
        fl.addWidget(btn_imp); fl.addWidget(btn_exp)
        fl.addStretch()
        btn_close = QPushButton("Закрыть")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        fl.addWidget(btn_close)
        layout.addWidget(footer)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_all(self):
        self._strategy_list.clear()
        for s in self._all_strategies:
            item = QListWidgetItem(f"{s.icon}  {s.name}")
            item.setToolTip(s.description)
            self._strategy_list.addItem(item)
        if self._all_strategies:
            self._strategy_list.setCurrentRow(0)

    def _on_strategy_selected(self, row: int):
        if row < 0 or row >= len(self._all_strategies):
            return
        self._editing_idx = row
        s = self._all_strategies[row]
        self._fld_icon.setText(s.icon)
        self._fld_name.setText(s.name)
        self._fld_desc.setText(s.description)
        self._fld_prompt.setPlainText(s.system_prompt)
        self._chk_require_analysis.setChecked(s.require_analysis)
        self._chk_focus_metrics.setChecked(s.focus_on_metrics)
        self._spn_max_patches.setValue(s.max_patches_per_iter)
        self._spn_temp.setValue(s.temperature_override)

    def _collect_current(self) -> CustomStrategy:
        idx = self._editing_idx
        sid = (self._all_strategies[idx].id
               if 0 <= idx < len(self._all_strategies) else None)
        from services.pipeline_models import CustomStrategy as CS
        s = CS(
            name=self._fld_name.text().strip() or "Стратегия",
            description=self._fld_desc.text().strip(),
            system_prompt=self._fld_prompt.toPlainText().strip(),
            icon=self._fld_icon.text().strip() or "✏️",
            require_analysis=self._chk_require_analysis.isChecked(),
            focus_on_metrics=self._chk_focus_metrics.isChecked(),
            max_patches_per_iter=self._spn_max_patches.value(),
            temperature_override=self._spn_temp.value(),
        )
        if sid:
            s.id = sid
        return s

    def _save_current(self):
        s = self._collect_current()
        if 0 <= self._editing_idx < len(self._all_strategies):
            self._all_strategies[self._editing_idx] = s
        else:
            self._all_strategies.append(s)
            self._editing_idx = len(self._all_strategies) - 1
        self._load_all()
        self._strategy_list.setCurrentRow(self._editing_idx)
        self.strategy_saved.emit(s)

    def _new_strategy(self):
        from services.pipeline_models import CustomStrategy as CS
        s = CS(name="Новая стратегия")
        self._all_strategies.append(s)
        self._editing_idx = len(self._all_strategies) - 1
        self._load_all()
        self._strategy_list.setCurrentRow(self._editing_idx)

    def _delete_strategy(self):
        row = self._strategy_list.currentRow()
        if 0 <= row < len(self._all_strategies):
            del self._all_strategies[row]
            self._editing_idx = -1
            self._load_all()

    def _create_from_template(self):
        item = self._cmb_template.currentItem()
        if not item:
            return
        tmpl = self.TEMPLATES.get(item.text())
        if not tmpl:
            return
        import copy
        new_s = copy.deepcopy(tmpl)
        import uuid
        new_s.id = str(uuid.uuid4())[:8]
        self._all_strategies.append(new_s)
        self._editing_idx = len(self._all_strategies) - 1
        self._load_all()
        self._strategy_list.setCurrentRow(self._editing_idx)

    def get_all_strategies(self) -> list[CustomStrategy]:
        return list(self._all_strategies)

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт стратегий", filter="JSON (*.json)"
        )
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                from services.pipeline_models import CustomStrategy as CS
                imported = [CS.from_dict(d) for d in data]
                self._all_strategies.extend(imported)
                self._load_all()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось импортировать: {e}")

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт стратегий", "my_strategies.json",
            "JSON (*.json)"
        )
        if path:
            data = [s.to_dict() for s in self._all_strategies]
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
