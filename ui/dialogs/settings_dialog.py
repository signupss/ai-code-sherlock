"""
Settings Dialog — model CRUD, API keys, signal folders, context settings, custom strategies.
"""
from __future__ import annotations
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
    QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QCheckBox, QFrame, QScrollArea, QSizePolicy,
    QDialogButtonBox, QTextEdit
)

from core.models import AppSettings, ModelDefinition, ModelSourceType

try:
    from ui.i18n import tr, register_listener, retranslate_widget
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass
    def retranslate_widget(w): pass


class SettingsDialog(QDialog):

    settings_saved = pyqtSignal(AppSettings)

    def __init__(self, current_settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Настройки — AI Code Sherlock"))
        self.setMinimumSize(700, 550)
        self.resize(760, 600)
        self.setModal(True)

        self._settings = AppSettings.from_dict(current_settings.to_dict())  # deep copy
        self._selected_model_id: str | None = None

        self._build_ui()
        self._populate_model_list()
        register_listener(self._retranslate)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass

    def _retranslate(self, _lang: str = ""):
        self.setWindowTitle(tr("Настройки — AI Code Sherlock"))
        retranslate_widget(self)

    # ── Build UI ──────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(self._build_models_tab(), tr("Модели"))
        tabs.addTab(self._build_signals_tab(), tr("Файловый сигнал"))
        tabs.addTab(self._build_general_tab(), tr("Общие"))
        tabs.addTab(self._build_appearance_tab(), tr("🎨 Внешний вид"))
        layout.addWidget(tabs)

        # Footer buttons
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer.setFixedHeight(56)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.addStretch()

        btn_cancel = QPushButton(tr("Отмена"))
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(tr("Сохранить"))
        btn_save.setObjectName("primaryBtn")
        btn_save.setFixedWidth(120)
        btn_save.clicked.connect(self._save)

        fl.addWidget(btn_cancel)
        fl.addSpacing(8)
        fl.addWidget(btn_save)
        layout.addWidget(footer)

    # ── Models Tab ────────────────────────────────────────────

    def _build_models_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Left: model list
        left = QVBoxLayout()
        lbl = QLabel(tr("МОДЕЛИ"))
        lbl.setObjectName("sectionLabel")
        left.addWidget(lbl)

        self._model_list = QListWidget()
        self._model_list.setFixedWidth(200)
        self._model_list.currentItemChanged.connect(self._on_model_selected)
        left.addWidget(self._model_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton(tr("+ Добавить"))
        btn_add.clicked.connect(self._add_model)
        btn_del = QPushButton(tr("Удалить"))
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete_model)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        left.addLayout(btn_row)

        layout.addLayout(left)

        # Right: model form
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.Shape.NoFrame)

        self._model_form_container = QWidget()
        self._model_form_layout = QVBoxLayout(self._model_form_container)
        self._model_form_layout.setSpacing(12)

        self._build_model_form()
        right.setWidget(self._model_form_container)
        layout.addWidget(right, stretch=1)

        return w

    def _build_model_form(self):
        fl = self._model_form_layout

        # Basic info
        grp_basic = QGroupBox(tr("Основные параметры"))
        form = QFormLayout(grp_basic)
        form.setSpacing(10)

        self._fld_display_name = QLineEdit()
        self._fld_display_name.setPlaceholderText(tr("Например: GPT-4o Local"))
        form.addRow(tr("Название:"), self._fld_display_name)

        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText("llama3.2 / gpt-4o / custom-model")
        form.addRow(tr("Имя модели:"), self._fld_name)

        self._cmb_source = QComboBox()
        self._cmb_source.addItem(tr("Ollama (локальная)"), ModelSourceType.OLLAMA.value)
        self._cmb_source.addItem(tr("Custom API (OpenAI-совместимый)"), ModelSourceType.CUSTOM_API.value)
        self._cmb_source.addItem("File Signal (ZennoPoster)", ModelSourceType.FILE_SIGNAL.value)
        self._cmb_source.currentIndexChanged.connect(self._on_source_changed)
        form.addRow(tr("Тип источника:"), self._cmb_source)

        self._spn_tokens = QSpinBox()
        self._spn_tokens.setRange(1024, 2_000_000)   # up to 2M tokens
        self._spn_tokens.setValue(8192)
        self._spn_tokens.setSingleStep(4096)
        self._spn_tokens.setToolTip(
            tr("Максимум токенов в запросе к модели.\n8192 = стандарт, 32768 = большой контекст,\n200000 = Claude/Gemini, 1000000+ = Gemini Ultra")
        )
        # Quick preset buttons
        tok_row = QHBoxLayout()
        tok_row.addWidget(self._spn_tokens)
        for label, val in [("8k", 8192), ("32k", 32768), ("128k", 131072),
                            ("200k", 200000), ("1M", 1000000), ("2M", 2000000)]:
            bt = QPushButton(label)
            bt.setFixedWidth(38)
            bt.clicked.connect(lambda _, v=val: self._spn_tokens.setValue(v))
            tok_row.addWidget(bt)
        form.addRow("Max tokens:", tok_row)

        self._spn_temp = QDoubleSpinBox()
        self._spn_temp.setRange(0.0, 2.0)
        self._spn_temp.setValue(0.2)
        self._spn_temp.setSingleStep(0.05)
        form.addRow("Temperature:", self._spn_temp)

        self._chk_default = QCheckBox(tr("Использовать по умолчанию"))
        form.addRow("", self._chk_default)

        fl.addWidget(grp_basic)

        # Ollama group
        self._grp_ollama = QGroupBox("Ollama")
        fo = QFormLayout(self._grp_ollama)
        fo.setSpacing(10)
        self._fld_ollama_url = QLineEdit()
        self._fld_ollama_url.setPlaceholderText("http://localhost:11434")
        self._fld_ollama_url.setText("http://localhost:11434")
        fo.addRow("Base URL:", self._fld_ollama_url)

        btn_test_ollama = QPushButton(tr("Проверить соединение"))
        btn_test_ollama.clicked.connect(self._test_ollama)
        fo.addRow("", btn_test_ollama)
        fl.addWidget(self._grp_ollama)

        # Custom API group
        self._grp_api = QGroupBox("Custom API")
        fa = QFormLayout(self._grp_api)
        fa.setSpacing(10)
        self._fld_api_url = QLineEdit()
        self._fld_api_url.setPlaceholderText("https://api.openai.com")
        fa.addRow("Base URL:", self._fld_api_url)

        self._fld_api_key = QLineEdit()
        self._fld_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._fld_api_key.setPlaceholderText("sk-...")
        fa.addRow("API Key:", self._fld_api_key)

        self._fld_api_model_id = QLineEdit()
        self._fld_api_model_id.setPlaceholderText(tr("gpt-4o (оставь пустым для имени модели)"))
        fa.addRow("Model ID:", self._fld_api_model_id)

        self._fld_custom_headers = QLineEdit()
        self._fld_custom_headers.setPlaceholderText('X-Header: value, X-Other: value2')
        fa.addRow(tr("Доп. заголовки:"), self._fld_custom_headers)

        btn_test_api = QPushButton(tr("Проверить API"))
        btn_test_api.clicked.connect(self._test_api)
        fa.addRow("", btn_test_api)
        fl.addWidget(self._grp_api)

        # File Signal group
        self._grp_signal = QGroupBox("File Signal (ZennoPoster)")
        fs = QFormLayout(self._grp_signal)
        fs.setSpacing(10)

        req_row = QHBoxLayout()
        self._fld_req_folder = QLineEdit()
        self._fld_req_folder.setPlaceholderText("signals/request")
        btn_req = QPushButton("...")
        btn_req.setObjectName("iconBtn")
        btn_req.setFixedWidth(32)
        btn_req.clicked.connect(lambda: self._pick_folder(self._fld_req_folder))
        req_row.addWidget(self._fld_req_folder)
        req_row.addWidget(btn_req)
        fs.addRow(tr("Папка запросов:"), req_row)

        res_row = QHBoxLayout()
        self._fld_res_folder = QLineEdit()
        self._fld_res_folder.setPlaceholderText("signals/response")
        btn_res = QPushButton("...")
        btn_res.setObjectName("iconBtn")
        btn_res.setFixedWidth(32)
        btn_res.clicked.connect(lambda: self._pick_folder(self._fld_res_folder))
        res_row.addWidget(self._fld_res_folder)
        res_row.addWidget(btn_res)
        fs.addRow(tr("Папка ответов:"), res_row)

        self._spn_timeout = QSpinBox()
        self._spn_timeout.setRange(5, 600)
        self._spn_timeout.setValue(60)
        self._spn_timeout.setSuffix(tr(" сек"))
        fs.addRow(tr("Таймаут:"), self._spn_timeout)
        fl.addWidget(self._grp_signal)

        fl.addStretch()
        self._on_source_changed()

    # ── Signal Tab ────────────────────────────────────────────

    def _build_signals_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        grp = QGroupBox(tr("Глобальные пути сигналов"))
        form = QFormLayout(grp)
        form.setSpacing(10)

        req_row = QHBoxLayout()
        self._fld_global_req = QLineEdit(self._settings.signal_request_folder)
        btn = QPushButton("...")
        btn.setObjectName("iconBtn")
        btn.setFixedWidth(32)
        btn.clicked.connect(lambda: self._pick_folder(self._fld_global_req))
        req_row.addWidget(self._fld_global_req)
        req_row.addWidget(btn)
        form.addRow(tr("Папка запросов:"), req_row)

        res_row = QHBoxLayout()
        self._fld_global_res = QLineEdit(self._settings.signal_response_folder)
        btn2 = QPushButton("...")
        btn2.setObjectName("iconBtn")
        btn2.setFixedWidth(32)
        btn2.clicked.connect(lambda: self._pick_folder(self._fld_global_res))
        res_row.addWidget(self._fld_global_res)
        res_row.addWidget(btn2)
        form.addRow(tr("Папка ответов:"), res_row)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── General Tab ────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Поведение ──────────────────────────────────────────
        grp_beh = QGroupBox(tr("Поведение"))
        fb = QFormLayout(grp_beh); fb.setSpacing(10)
        self._chk_sherlock = QCheckBox(tr("Включить режим Шерлока по умолчанию"))
        self._chk_sherlock.setChecked(self._settings.sherlock_mode_enabled)
        self._chk_send_logs = QCheckBox(tr("Автоматически прикреплять логи к запросам"))
        self._chk_send_logs.setChecked(self._settings.send_logs_to_ai)
        fb.addRow("", self._chk_sherlock)
        fb.addRow("", self._chk_send_logs)
        layout.addWidget(grp_beh)

        # ── Контекст и токены ──────────────────────────────────
        grp_ctx = QGroupBox(tr("Контекст и токены"))
        fc = QFormLayout(grp_ctx); fc.setSpacing(10)

        self._chk_compress = QCheckBox(tr("Сжимать контекст для экономии токенов"))
        self._chk_compress.setChecked(getattr(self._settings, "compress_context", True))
        self._chk_compress.setToolTip(
            tr("ВКЛ (по умолчанию): файлы и логи обрезаются до лимита токенов.\nВЫКЛ: передаётся полный контент без обрезки — для точного анализа.")
        )
        fc.addRow("", self._chk_compress)

        self._chk_full_logs = QCheckBox(tr("Включать полный лог без обрезки"))
        self._chk_full_logs.setChecked(getattr(self._settings, "include_full_logs", False))
        self._chk_full_logs.setToolTip(
            tr("Передавать весь лог ошибок целиком (может сильно увеличить контекст).")
        )
        fc.addRow("", self._chk_full_logs)

        self._spn_history = QSpinBox()
        self._spn_history.setRange(1, 100)
        self._spn_history.setValue(getattr(self._settings, "max_conversation_history", 12))
        self._spn_history.setToolTip(tr("Сколько прошлых сообщений включать в каждый запрос к AI."))
        fc.addRow(tr("История диалога (сообщений):"), self._spn_history)

        self._spn_file_chars = QSpinBox()
        self._spn_file_chars.setRange(500, 500_000)
        self._spn_file_chars.setSingleStep(1000)
        self._spn_file_chars.setValue(getattr(self._settings, "max_file_chars", 6000))
        self._spn_file_chars.setSuffix(tr(" симв"))
        self._spn_file_chars.setToolTip(tr("Максимум символов одного файла в контексте AI."))
        fc.addRow(tr("Лимит символов файла:"), self._spn_file_chars)

        self._spn_log_chars = QSpinBox()
        self._spn_log_chars.setRange(500, 500_000)
        self._spn_log_chars.setSingleStep(1000)
        self._spn_log_chars.setValue(getattr(self._settings, "max_log_chars", 8000))
        self._spn_log_chars.setSuffix(tr(" симв"))
        self._spn_log_chars.setToolTip(tr("Максимум символов лога ошибок в контексте AI."))
        fc.addRow(tr("Лимит символов лога:"), self._spn_log_chars)

        layout.addWidget(grp_ctx)

        # ── Кастомные стратегии ────────────────────────────────
        grp_strat = QGroupBox(tr("Кастомные стратегии AI"))
        fs_l = QVBoxLayout(grp_strat); fs_l.setSpacing(8)

        hint = QLabel(
            tr("Создавай собственные стратегии поведения AI для основного чата.\nВыбранная стратегия добавляется к системному промпту вместо стандартной.")
        )
        hint.setStyleSheet("color:#565f89;font-size:11px;"); hint.setWordWrap(True)
        fs_l.addWidget(hint)

        self._strat_list = QListWidget()
        self._strat_list.setMaximumHeight(140)
        self._strat_list.setStyleSheet(
            "QListWidget{background:#0E1117;border:1px solid #1E2030;border-radius:6px;}QListWidget::item{padding:6px 10px;border-bottom:1px solid #1A1E2E;}QListWidget::item:selected{background:#2E3148;}"
        )
        self._strat_list.currentItemChanged.connect(self._on_strat_selected)
        fs_l.addWidget(self._strat_list)

        btn_row = QHBoxLayout()
        btn_new   = QPushButton(tr("+ Создать"));   btn_new.clicked.connect(self._new_strategy)
        btn_edit  = QPushButton(tr("✏ Изменить"));  btn_edit.clicked.connect(self._edit_strategy)
        btn_del_s = QPushButton(tr("✕ Удалить"));   btn_del_s.setObjectName("dangerBtn")
        btn_del_s.clicked.connect(self._delete_strategy)
        btn_row.addWidget(btn_new); btn_row.addWidget(btn_edit)
        btn_row.addStretch(); btn_row.addWidget(btn_del_s)
        fs_l.addLayout(btn_row)
        layout.addWidget(grp_strat)
        layout.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._load_strategies()
        return w

    # ── Appearance Tab ─────────────────────────────────────────

    def _build_appearance_tab(self) -> QWidget:
        from PyQt6.QtWidgets import QColorDialog
        w = QWidget()
        outer = QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Цвет акцента ──────────────────────────────────────
        grp_color = QGroupBox(tr("Цвет темы (акцент)"))
        gc = QVBoxLayout(grp_color); gc.setSpacing(12)

        hint_c = QLabel(
            tr("Основной цвет интерфейса — кнопки, выделения, активные элементы.\nИзменение применится после перезапуска.")
        )
        hint_c.setStyleSheet("color:#565f89;font-size:11px;"); hint_c.setWordWrap(True)
        gc.addWidget(hint_c)

        # Preset palette row
        palette_row = QHBoxLayout()
        current_accent = getattr(self._settings, "accent_color", "#7AA2F7")
        self._accent_color = current_accent

        PRESETS = [
            ("#7AA2F7", "TokyoNight Blue"),
            ("#BB9AF7", "Purple"),
            ("#9ECE6A", "Green"),
            ("#E0AF68", "Amber"),
            ("#F7768E", "Rose"),
            ("#73DACA", "Teal"),
            ("#FF9E64", "Orange"),
            ("#2AC3DE", "Cyan"),
            ("#C0CAF5", "Lavender"),
            ("#FFFFFF", "White"),
        ]
        for hex_color, name in PRESETS:
            btn = QPushButton()
            btn.setFixedSize(32, 32)
            btn.setToolTip(f"{name} ({hex_color})")
            btn.setStyleSheet(
                f"QPushButton{{background:{hex_color};border-radius:6px;"
                f"border:2px solid {'#CDD6F4' if hex_color == current_accent else 'transparent'};}}"
                f"QPushButton:hover{{border:2px solid #CDD6F4;}}"
            )
            btn.clicked.connect(lambda _, hx=hex_color, b=btn: self._select_preset_color(hx, b))
            palette_row.addWidget(btn)
        palette_row.addStretch()
        gc.addLayout(palette_row)

        # Custom color picker
        custom_row = QHBoxLayout()
        self._fld_accent = QLineEdit(current_accent)
        self._fld_accent.setMaximumWidth(110)
        self._fld_accent.setPlaceholderText("#7AA2F7")
        self._fld_accent.textChanged.connect(self._on_accent_typed)

        self._btn_color_pick = QPushButton(tr("🎨 Выбрать цвет…"))
        self._btn_color_pick.setFixedWidth(150)
        self._btn_color_pick.clicked.connect(self._open_color_dialog)

        self._lbl_color_preview = QLabel()
        self._lbl_color_preview.setFixedSize(48, 28)
        self._lbl_color_preview.setStyleSheet(
            f"background:{current_accent};border-radius:6px;border:1px solid #2E3148;"
        )

        custom_row.addWidget(QLabel("HEX:"))
        custom_row.addWidget(self._fld_accent)
        custom_row.addWidget(self._lbl_color_preview)
        custom_row.addSpacing(8)
        custom_row.addWidget(self._btn_color_pick)
        custom_row.addStretch()
        gc.addLayout(custom_row)
        layout.addWidget(grp_color)

        # ── Размер шрифта интерфейса ──────────────────────────
        grp_font = QGroupBox(tr("Шрифт интерфейса"))
        gf = QFormLayout(grp_font); gf.setSpacing(10)

        hint_f = QLabel(tr("Размер шрифта всех меню, кнопок и панелей (не редактора кода)."))
        hint_f.setStyleSheet("color:#565f89;font-size:11px;"); hint_f.setWordWrap(True)
        gf.addRow(hint_f)

        size_row = QHBoxLayout()
        self._spn_ui_font = QSpinBox()
        self._spn_ui_font.setRange(8, 18)
        self._spn_ui_font.setValue(getattr(self._settings, "ui_font_size", 11))
        self._spn_ui_font.setSuffix(" pt")
        self._spn_ui_font.setFixedWidth(80)
        self._spn_ui_font.valueChanged.connect(self._on_font_size_changed)

        self._lbl_font_preview = QLabel(tr("Предпросмотр текста интерфейса"))
        self._lbl_font_preview.setStyleSheet("color:#CDD6F4;")
        self._on_font_size_changed(self._spn_ui_font.value())

        size_row.addWidget(self._spn_ui_font)
        for sz in [9, 10, 11, 12, 13, 14]:
            b = QPushButton(str(sz))
            b.setFixedWidth(34)
            b.clicked.connect(lambda _, s=sz: self._spn_ui_font.setValue(s))
            size_row.addWidget(b)
        size_row.addStretch()
        gf.addRow(tr("Размер:"), size_row)
        gf.addRow(tr("Превью:"), self._lbl_font_preview)
        layout.addWidget(grp_font)

        # ── Язык интерфейса ────────────────────────────────────
        grp_lang = QGroupBox(tr("Язык интерфейса"))
        gl = QFormLayout(grp_lang); gl.setSpacing(10)

        hint_l = QLabel(
            tr("Язык меню, кнопок и сообщений. Изменение применится при перезапуске.\nЯзык AI-ответов задаётся в системном промпте.")
        )
        hint_l.setStyleSheet("color:#565f89;font-size:11px;"); hint_l.setWordWrap(True)
        gl.addRow(hint_l)

        self._cmb_lang = QComboBox()
        self._cmb_lang.addItem(tr("🇷🇺  Русский"), "ru")
        self._cmb_lang.addItem("🇬🇧  English", "en")
        current_lang = getattr(self._settings, "language", "ru")
        self._cmb_lang.setCurrentIndex(0 if current_lang == "ru" else 1)
        gl.addRow(tr("Язык:"), self._cmb_lang)
        layout.addWidget(grp_lang)

        layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return w

    def _select_preset_color(self, hex_color: str, clicked_btn: QPushButton):
        self._accent_color = hex_color
        self._fld_accent.blockSignals(True)
        self._fld_accent.setText(hex_color)
        self._fld_accent.blockSignals(False)
        self._lbl_color_preview.setStyleSheet(
            f"background:{hex_color};border-radius:6px;border:1px solid #2E3148;"
        )

    def _on_accent_typed(self, text: str):
        if len(text) == 7 and text.startswith("#"):
            try:
                int(text[1:], 16)
                self._accent_color = text
                self._lbl_color_preview.setStyleSheet(
                    f"background:{text};border-radius:6px;border:1px solid #2E3148;"
                )
            except ValueError:
                pass

    def _open_color_dialog(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        color = QColorDialog.getColor(
            QColor(self._accent_color), self,
            tr("Выбрать цвет акцента"),
            QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if color.isValid():
            self._select_preset_color(color.name(), self._btn_color_pick)

    def _on_font_size_changed(self, size: int):
        try:
            f = self._lbl_font_preview.font()
            f.setPointSize(size)
            self._lbl_font_preview.setFont(f)
        except Exception:
            pass

    @staticmethod
    def _strategies_path() -> "Path":
        p = Path.home() / ".ai_code_sherlock" / "custom_strategies.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load_strategies(self):
        import json
        self._strategies: list[dict] = []
        p = self._strategies_path()
        if p.exists():
            try:
                self._strategies = json.loads(p.read_text("utf-8"))
            except Exception:
                self._strategies = []
        self._refresh_strat_list()

    def _save_strategies(self):
        import json
        self._strategies_path().write_text(
            json.dumps(self._strategies, ensure_ascii=False, indent=2), "utf-8"
        )

    def _refresh_strat_list(self):
        self._strat_list.clear()
        for s in self._strategies:
            icon = s.get("icon", "🎯")
            item = QListWidgetItem(f"{icon}  {s.get('name', '?')}")
            item.setData(Qt.ItemDataRole.UserRole, s.get("id", ""))
            item.setToolTip(s.get("description", ""))
            self._strat_list.addItem(item)

    def _on_strat_selected(self, current, _prev):
        pass  # could show preview

    def _new_strategy(self):
        self._open_strategy_editor(None)

    def _edit_strategy(self):
        item = self._strat_list.currentItem()
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        s = next((x for x in self._strategies if x.get("id") == sid), None)
        self._open_strategy_editor(s)

    def _delete_strategy(self):
        item = self._strat_list.currentItem()
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, tr("Удалить стратегию"),
            tr("Удалить эту стратегию?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._strategies = [x for x in self._strategies if x.get("id") != sid]
            self._save_strategies()
            self._refresh_strat_list()

    def _open_strategy_editor(self, existing: dict | None):
        import uuid as _uuid
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Редактор стратегии"))
        dlg.setMinimumSize(520, 420)
        dlg.setModal(True)
        dl = QVBoxLayout(dlg); dl.setSpacing(10); dl.setContentsMargins(16, 16, 16, 12)

        form = QFormLayout(); form.setSpacing(10)

        fld_icon = QLineEdit(); fld_icon.setPlaceholderText("🎯"); fld_icon.setMaximumWidth(60)
        fld_name = QLineEdit(); fld_name.setPlaceholderText(tr("Название стратегии"))
        fld_desc = QLineEdit(); fld_desc.setPlaceholderText(tr("Краткое описание (необязательно)"))

        fld_prompt = QTextEdit()
        fld_prompt.setPlaceholderText(
            tr("Инструкции для AI (добавляются к системному промпту).\n\nПример:\nТы — строгий code reviewer. При каждом ответе:\n1. Указывай потенциальные проблемы с производительностью\n2. Предлагай альтернативные реализации\n3. Давай только минимально необходимые патчи.")
        )
        fld_prompt.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 11))
        fld_prompt.setMinimumHeight(180)

        if existing:
            fld_icon.setText(existing.get("icon", "🎯"))
            fld_name.setText(existing.get("name", ""))
            fld_desc.setText(existing.get("description", ""))
            fld_prompt.setPlainText(existing.get("system_prompt", ""))

        form.addRow(tr("Иконка:"), fld_icon)
        form.addRow(tr("Название:"), fld_name)
        form.addRow(tr("Описание:"), fld_desc)
        form.addRow(tr("Системный промпт:"), fld_prompt)
        dl.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dl.addWidget(btns)

        if dlg.exec():
            name = fld_name.text().strip()
            if not name:
                return
            sid = existing.get("id", str(_uuid.uuid4())) if existing else str(_uuid.uuid4())
            entry = {
                "id": sid,
                "icon": fld_icon.text().strip() or "🎯",
                "name": name,
                "description": fld_desc.text().strip(),
                "system_prompt": fld_prompt.toPlainText().strip(),
            }
            if existing:
                self._strategies = [entry if x.get("id") == sid else x for x in self._strategies]
            else:
                self._strategies.append(entry)
            self._save_strategies()
            self._refresh_strat_list()

    # ── Model List Logic ──────────────────────────────────────

    def _populate_model_list(self):
        self._model_list.clear()
        for m in self._settings.models:
            item = QListWidgetItem(m.display_name)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            if m.id == self._settings.default_model_id:
                item.setText(f"★ {m.display_name}")
            self._model_list.addItem(item)

    def _on_model_selected(self, current, _previous):
        if not current:
            return
        model_id = current.data(Qt.ItemDataRole.UserRole)
        self._selected_model_id = model_id
        model = next((m for m in self._settings.models if m.id == model_id), None)
        if model:
            self._load_model_into_form(model)

    def _load_model_into_form(self, m: ModelDefinition):
        self._fld_display_name.setText(m.display_name)
        self._fld_name.setText(m.name)
        self._spn_tokens.setValue(m.max_context_tokens)
        self._spn_temp.setValue(m.temperature)
        self._chk_default.setChecked(m.is_default)

        idx = {
            ModelSourceType.OLLAMA: 0,
            ModelSourceType.CUSTOM_API: 1,
            ModelSourceType.FILE_SIGNAL: 2,
        }.get(m.source_type, 0)
        self._cmb_source.setCurrentIndex(idx)

        self._fld_ollama_url.setText(m.ollama_base_url or "http://localhost:11434")
        self._fld_api_url.setText(m.api_base_url or "")
        self._fld_api_key.setText(m.api_key or "")
        self._fld_api_model_id.setText(m.api_model_id or "")

        headers_str = ", ".join(f"{k}: {v}" for k, v in m.custom_headers.items())
        self._fld_custom_headers.setText(headers_str)

        self._fld_req_folder.setText(m.signal_request_folder or "")
        self._fld_res_folder.setText(m.signal_response_folder or "")
        self._spn_timeout.setValue(m.signal_timeout_seconds)

        self._on_source_changed()

    def _save_current_model_form(self):
        """Write form fields back to settings._models."""
        if not self._selected_model_id:
            return
        idx = next(
            (i for i, m in enumerate(self._settings.models)
             if m.id == self._selected_model_id),
            None
        )
        if idx is None:
            return

        source = ModelSourceType(self._cmb_source.currentData())
        headers = {}
        for pair in self._fld_custom_headers.text().split(","):
            if ":" in pair:
                k, _, v = pair.partition(":")
                headers[k.strip()] = v.strip()

        is_default = self._chk_default.isChecked()

        m = self._settings.models[idx]
        self._settings.models[idx] = ModelDefinition(
            id=m.id,
            name=self._fld_name.text().strip(),
            display_name=self._fld_display_name.text().strip(),
            source_type=source,
            ollama_base_url=self._fld_ollama_url.text().strip() or "http://localhost:11434",
            api_base_url=self._fld_api_url.text().strip() or None,
            api_key=self._fld_api_key.text().strip() or None,
            api_model_id=self._fld_api_model_id.text().strip() or None,
            custom_headers=headers,
            signal_request_folder=self._fld_req_folder.text().strip() or None,
            signal_response_folder=self._fld_res_folder.text().strip() or None,
            signal_timeout_seconds=self._spn_timeout.value(),
            max_context_tokens=self._spn_tokens.value(),
            temperature=self._spn_temp.value(),
            is_default=is_default,
        )

        if is_default:
            self._settings.default_model_id = m.id

        self._populate_model_list()

    def _add_model(self):
        self._save_current_model_form()
        new_model = ModelDefinition(
            id=str(uuid.uuid4()),
            name="new-model",
            display_name=tr("Новая модель"),
            source_type=ModelSourceType.OLLAMA,
        )
        self._settings.models.append(new_model)
        self._populate_model_list()
        self._model_list.setCurrentRow(len(self._settings.models) - 1)

    def _delete_model(self):
        if not self._selected_model_id:
            return
        reply = QMessageBox.question(
            self, tr("Подтверждение"),
            tr("Удалить эту модель?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._settings.models = [
            m for m in self._settings.models if m.id != self._selected_model_id
        ]
        self._selected_model_id = None
        self._populate_model_list()

    def _on_source_changed(self):
        src = self._cmb_source.currentData()
        self._grp_ollama.setVisible(src == ModelSourceType.OLLAMA.value)
        self._grp_api.setVisible(src == ModelSourceType.CUSTOM_API.value)
        self._grp_signal.setVisible(src == ModelSourceType.FILE_SIGNAL.value)

    # ── Actions ──────────────────────────────────────────────

    def _pick_folder(self, target: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, tr("Выберите папку"))
        if folder:
            target.setText(folder)

    def _test_ollama(self):
        import asyncio
        url = self._fld_ollama_url.text().strip() or "http://localhost:11434"
        from providers.providers import OllamaProvider
        from core.models import ModelDefinition, ModelSourceType
        tmp = ModelDefinition(
            name="test", display_name="test",
            source_type=ModelSourceType.OLLAMA,
            ollama_base_url=url,
        )
        provider = OllamaProvider(tmp)

        async def _check():
            return await provider.is_available()

        try:
            loop = asyncio.new_event_loop()
            ok = loop.run_until_complete(_check())
            loop.close()
        except Exception as e:
            ok = False

        if ok:
            QMessageBox.information(self, "Ollama", f"{tr('✅ Соединение успешно!')}\n{url}")
        else:
            QMessageBox.warning(self, "Ollama", f"{tr('❌ Недоступен:')} {url}\n{tr('Проверь, что Ollama запущена.')}")

    def _test_api(self):
        QMessageBox.information(
            self, "API",
            tr("Тест API будет вызван при первом запросе к модели.\nУбедись что URL и API Key правильные.")
        )

    def _save(self):
        self._save_current_model_form()
        self._settings.signal_request_folder = self._fld_global_req.text().strip()
        self._settings.signal_response_folder = self._fld_global_res.text().strip()
        self._settings.sherlock_mode_enabled = self._chk_sherlock.isChecked()
        self._settings.send_logs_to_ai = self._chk_send_logs.isChecked()
        self._settings.compress_context = self._chk_compress.isChecked()
        self._settings.include_full_logs = self._chk_full_logs.isChecked()
        self._settings.max_conversation_history = self._spn_history.value()
        self._settings.max_file_chars = self._spn_file_chars.value()
        self._settings.max_log_chars = self._spn_log_chars.value()
        # Appearance
        self._settings.accent_color = getattr(self, "_accent_color",
                                               self._settings.accent_color)
        self._settings.ui_font_size = self._spn_ui_font.value()
        self._settings.language = self._cmb_lang.currentData()
        self.settings_saved.emit(self._settings)
        self.accept()
