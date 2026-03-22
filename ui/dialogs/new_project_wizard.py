"""
New Project Wizard — creates a new project with mode selection.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QButtonGroup, QRadioButton,
    QFileDialog, QWidget, QGroupBox, QFormLayout
)

from services.project_manager import ProjectMode

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return {
        "bg1": "#0E1117", "bg3": "#1A1D2E", "bd2": "#1E2030",
        "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
    }.get(k, "#CDD6F4")
    def register_theme_refresh(cb): pass

try:
    from ui.i18n import tr, register_listener
except ImportError:
    def tr(s): return s
    def register_listener(cb): pass


class NewProjectWizard(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Новый проект — AI Code Sherlock"))
        self.setMinimumSize(520, 400)
        self.setFixedSize(540, 430)
        self.setModal(True)
        self._result: tuple | None = None
        self._build_ui()
        self._refresh_styles()
        register_listener(self._retranslate)
        register_theme_refresh(self._refresh_styles)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass

    def _refresh_styles(self) -> None:
        """Apply theme-aware inline styles."""
        tx0 = get_color("tx0")
        tx2 = get_color("tx2")
        bd2 = get_color("bd2")
        fs  = "13px"
        fs_s = "11px"
        # Bold mode labels
        for lbl in (self._lbl_new, self._lbl_ex):
            lbl.setStyleSheet(f"color:{tx0}; font-size:{fs}; font-weight:bold;")
        # Description labels
        for lbl in (self._desc_new, self._desc_ex):
            lbl.setStyleSheet(f"color:{tx2}; font-size:{fs_s};")
        # Find all hSeparator frames and style them
        for obj in self.findChildren(QFrame, "hSeparator"):
            obj.setStyleSheet(f"background:{bd2}; max-height:1px;")

    def _retranslate(self, _lang: str = ""):
        self.setWindowTitle(tr("Новый проект — AI Code Sherlock"))
        self._title_lbl.setText(tr("🆕 Создать новый проект"))
        self._sub_lbl.setText(tr("Настрой проект перед началом работы с AI Code Sherlock"))
        self._grp_info.setTitle(tr("Информация о проекте"))
        self._grp_mode.setTitle(tr("Режим работы с AI"))
        self._lbl_new.setText(tr("🆕 Новый проект — разработка с нуля"))
        self._desc_new.setText(tr("AI даёт полные реализации кода, объяснения архитектуры.\nПодходит для создания новых скриптов и приложений."))
        self._lbl_ex.setText(tr("🔧 Существующий проект — доработка"))
        self._desc_ex.setText(tr("AI даёт ТОЛЬКО точечные патчи [SEARCH/REPLACE].\nПодходит для улучшения готового кода без переписывания."))
        self._btn_cancel.setText(tr("Отмена"))
        self._btn_create.setText(tr("Создать проект"))
        self._fld_name_form_lbl.setText(tr("Название:"))
        self._fld_path_form_lbl.setText(tr("Папка:"))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)

        self._title_lbl = QLabel(tr("🆕 Создать новый проект"))
        self._title_lbl.setObjectName("titleLabel")
        layout.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(tr("Настрой проект перед началом работы с AI Code Sherlock"))
        self._sub_lbl.setObjectName("statusLabel")
        layout.addWidget(self._sub_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("hSeparator")
        layout.addWidget(sep)

        # Name + folder
        self._grp_info = QGroupBox(tr("Информация о проекте"))
        form = QFormLayout(self._grp_info); form.setSpacing(10)

        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText("MyProject")
        self._fld_name_form_lbl = QLabel(tr("Название:"))
        form.addRow(self._fld_name_form_lbl, self._fld_name)

        path_row = QHBoxLayout()
        self._fld_path = QLineEdit()
        self._fld_path.setPlaceholderText(tr("Выберите папку проекта..."))
        self._fld_path.setReadOnly(True)
        btn_pick = QPushButton("...")
        btn_pick.setObjectName("iconBtn"); btn_pick.setFixedWidth(32)
        btn_pick.clicked.connect(self._pick_folder)
        path_row.addWidget(self._fld_path); path_row.addWidget(btn_pick)
        self._fld_path_form_lbl = QLabel(tr("Папка:"))
        form.addRow(self._fld_path_form_lbl, path_row)
        layout.addWidget(self._grp_info)

        # Mode selection
        self._grp_mode = QGroupBox(tr("Режим работы с AI"))
        ml = QVBoxLayout(self._grp_mode); ml.setSpacing(12)

        self._radio_new = QRadioButton()
        self._radio_new.setChecked(True)
        new_row = QHBoxLayout()
        new_row.addWidget(self._radio_new)
        new_info = QWidget()
        ni_l = QVBoxLayout(new_info); ni_l.setContentsMargins(0, 0, 0, 0); ni_l.setSpacing(2)
        self._lbl_new = QLabel(tr("🆕 Новый проект — разработка с нуля"))
        self._lbl_new.setObjectName("modeLabelBold")
        self._desc_new = QLabel(tr("AI даёт полные реализации кода, объяснения архитектуры.\nПодходит для создания новых скриптов и приложений."))
        self._desc_new.setObjectName("modeDesc")
        self._desc_new.setWordWrap(True)
        ni_l.addWidget(self._lbl_new); ni_l.addWidget(self._desc_new)
        new_row.addWidget(new_info); new_row.addStretch()
        ml.addLayout(new_row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setObjectName("hSeparator")
        ml.addWidget(sep2)

        self._radio_existing = QRadioButton()
        exist_row = QHBoxLayout()
        exist_row.addWidget(self._radio_existing)
        exist_info = QWidget()
        ei_l = QVBoxLayout(exist_info); ei_l.setContentsMargins(0, 0, 0, 0); ei_l.setSpacing(2)
        self._lbl_ex = QLabel(tr("🔧 Существующий проект — доработка"))
        self._lbl_ex.setObjectName("modeLabelBold")
        self._desc_ex = QLabel(tr("AI даёт ТОЛЬКО точечные патчи [SEARCH/REPLACE].\nПодходит для улучшения готового кода без переписывания."))
        self._desc_ex.setObjectName("modeDesc")
        self._desc_ex.setWordWrap(True)
        ei_l.addWidget(self._lbl_ex); ei_l.addWidget(self._desc_ex)
        exist_row.addWidget(exist_info); exist_row.addStretch()
        ml.addLayout(exist_row)

        self._btn_group = QButtonGroup()
        self._btn_group.addButton(self._radio_new, 0)
        self._btn_group.addButton(self._radio_existing, 1)
        layout.addWidget(self._grp_mode)

        layout.addStretch()

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        self._btn_cancel = QPushButton(tr("Отмена"))
        self._btn_cancel.setFixedWidth(90)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_create = QPushButton(tr("Создать проект"))
        self._btn_create.setObjectName("primaryBtn")
        self._btn_create.setFixedWidth(140)
        self._btn_create.clicked.connect(self._create)
        footer.addWidget(self._btn_cancel); footer.addSpacing(8); footer.addWidget(self._btn_create)
        layout.addLayout(footer)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Выберите папку проекта"))
        if folder:
            self._fld_path.setText(folder)
            if not self._fld_name.text():
                self._fld_name.setText(Path(folder).name)

    def _create(self):
        path = self._fld_path.text().strip()
        name = self._fld_name.text().strip()
        if not path:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("Нет папки"), tr("Укажи папку проекта."))
            return
        if not name:
            name = Path(path).name or "Project"
        mode = (ProjectMode.NEW_PROJECT if self._radio_new.isChecked()
                else ProjectMode.EXISTING_PROJECT)
        self._result = (path, name, mode)
        self.accept()

    def result_data(self) -> tuple[str, str, ProjectMode]:
        return self._result or (".", "Project", ProjectMode.NEW_PROJECT)
