"""
Settings Dialog — model CRUD, API keys, signal folders.
"""
from __future__ import annotations
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
    QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QCheckBox, QFrame, QScrollArea, QSizePolicy
)

from core.models import AppSettings, ModelDefinition, ModelSourceType


class SettingsDialog(QDialog):

    settings_saved = pyqtSignal(AppSettings)

    def __init__(self, current_settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки — AI Code Sherlock")
        self.setMinimumSize(700, 550)
        self.resize(760, 600)
        self.setModal(True)

        self._settings = AppSettings.from_dict(current_settings.to_dict())  # deep copy
        self._selected_model_id: str | None = None

        self._build_ui()
        self._populate_model_list()

    # ── Build UI ──────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(self._build_models_tab(), "Модели")
        tabs.addTab(self._build_signals_tab(), "Файловый сигнал")
        tabs.addTab(self._build_general_tab(), "Общие")
        layout.addWidget(tabs)

        # Footer buttons
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer.setFixedHeight(56)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.addStretch()

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("Сохранить")
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
        lbl = QLabel("МОДЕЛИ")
        lbl.setObjectName("sectionLabel")
        left.addWidget(lbl)

        self._model_list = QListWidget()
        self._model_list.setFixedWidth(200)
        self._model_list.currentItemChanged.connect(self._on_model_selected)
        left.addWidget(self._model_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Добавить")
        btn_add.clicked.connect(self._add_model)
        btn_del = QPushButton("Удалить")
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
        grp_basic = QGroupBox("Основные параметры")
        form = QFormLayout(grp_basic)
        form.setSpacing(10)

        self._fld_display_name = QLineEdit()
        self._fld_display_name.setPlaceholderText("Например: GPT-4o Local")
        form.addRow("Название:", self._fld_display_name)

        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText("llama3.2 / gpt-4o / custom-model")
        form.addRow("Имя модели:", self._fld_name)

        self._cmb_source = QComboBox()
        self._cmb_source.addItem("Ollama (локальная)", ModelSourceType.OLLAMA.value)
        self._cmb_source.addItem("Custom API (OpenAI-совместимый)", ModelSourceType.CUSTOM_API.value)
        self._cmb_source.addItem("File Signal (ZennoPoster)", ModelSourceType.FILE_SIGNAL.value)
        self._cmb_source.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("Тип источника:", self._cmb_source)

        self._spn_tokens = QSpinBox()
        self._spn_tokens.setRange(1024, 200000)
        self._spn_tokens.setValue(8192)
        self._spn_tokens.setSingleStep(1024)
        form.addRow("Max tokens:", self._spn_tokens)

        self._spn_temp = QDoubleSpinBox()
        self._spn_temp.setRange(0.0, 2.0)
        self._spn_temp.setValue(0.2)
        self._spn_temp.setSingleStep(0.05)
        form.addRow("Temperature:", self._spn_temp)

        self._chk_default = QCheckBox("Использовать по умолчанию")
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

        btn_test_ollama = QPushButton("Проверить соединение")
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
        self._fld_api_model_id.setPlaceholderText("gpt-4o (оставь пустым для имени модели)")
        fa.addRow("Model ID:", self._fld_api_model_id)

        self._fld_custom_headers = QLineEdit()
        self._fld_custom_headers.setPlaceholderText('X-Header: value, X-Other: value2')
        fa.addRow("Доп. заголовки:", self._fld_custom_headers)

        btn_test_api = QPushButton("Проверить API")
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
        fs.addRow("Папка запросов:", req_row)

        res_row = QHBoxLayout()
        self._fld_res_folder = QLineEdit()
        self._fld_res_folder.setPlaceholderText("signals/response")
        btn_res = QPushButton("...")
        btn_res.setObjectName("iconBtn")
        btn_res.setFixedWidth(32)
        btn_res.clicked.connect(lambda: self._pick_folder(self._fld_res_folder))
        res_row.addWidget(self._fld_res_folder)
        res_row.addWidget(btn_res)
        fs.addRow("Папка ответов:", res_row)

        self._spn_timeout = QSpinBox()
        self._spn_timeout.setRange(5, 600)
        self._spn_timeout.setValue(60)
        self._spn_timeout.setSuffix(" сек")
        fs.addRow("Таймаут:", self._spn_timeout)
        fl.addWidget(self._grp_signal)

        fl.addStretch()
        self._on_source_changed()

    # ── Signal Tab ────────────────────────────────────────────

    def _build_signals_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        grp = QGroupBox("Глобальные пути сигналов")
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
        form.addRow("Папка запросов:", req_row)

        res_row = QHBoxLayout()
        self._fld_global_res = QLineEdit(self._settings.signal_response_folder)
        btn2 = QPushButton("...")
        btn2.setObjectName("iconBtn")
        btn2.setFixedWidth(32)
        btn2.clicked.connect(lambda: self._pick_folder(self._fld_global_res))
        res_row.addWidget(self._fld_global_res)
        res_row.addWidget(btn2)
        form.addRow("Папка ответов:", res_row)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── General Tab ────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        grp = QGroupBox("Поведение")
        form = QFormLayout(grp)
        self._chk_sherlock = QCheckBox("Включить режим Шерлока по умолчанию")
        self._chk_sherlock.setChecked(self._settings.sherlock_mode_enabled)
        self._chk_send_logs = QCheckBox("Автоматически прикреплять логи к запросам")
        self._chk_send_logs.setChecked(self._settings.send_logs_to_ai)
        form.addRow("", self._chk_sherlock)
        form.addRow("", self._chk_send_logs)
        layout.addWidget(grp)
        layout.addStretch()
        return w

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
            display_name="Новая модель",
            source_type=ModelSourceType.OLLAMA,
        )
        self._settings.models.append(new_model)
        self._populate_model_list()
        self._model_list.setCurrentRow(len(self._settings.models) - 1)

    def _delete_model(self):
        if not self._selected_model_id:
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Удалить эту модель?",
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
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
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
            QMessageBox.information(self, "Ollama", f"✅ Соединение успешно!\n{url}")
        else:
            QMessageBox.warning(self, "Ollama", f"❌ Недоступен: {url}\nПроверь, что Ollama запущена.")

    def _test_api(self):
        QMessageBox.information(
            self, "API",
            "Тест API будет вызван при первом запросе к модели.\n"
            "Убедись что URL и API Key правильные."
        )

    def _save(self):
        self._save_current_model_form()
        self._settings.signal_request_folder = self._fld_global_req.text().strip()
        self._settings.signal_response_folder = self._fld_global_res.text().strip()
        self._settings.sherlock_mode_enabled = self._chk_sherlock.isChecked()
        self._settings.send_logs_to_ai = self._chk_send_logs.isChecked()

        self.settings_saved.emit(self._settings)
        self.accept()
