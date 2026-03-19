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


class NewProjectWizard(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый проект — AI Code Sherlock")
        self.setMinimumSize(520, 400)
        self.setFixedSize(540, 430)
        self.setModal(True)
        self._result: tuple | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)

        # Title
        title = QLabel("🆕 Создать новый проект")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#CDD6F4;")
        layout.addWidget(title)

        sub = QLabel("Настрой проект перед началом работы с AI Code Sherlock")
        sub.setStyleSheet("color:#565f89;font-size:12px;")
        layout.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#1E2030;")
        layout.addWidget(sep)

        # Name + folder
        grp_info = QGroupBox("Информация о проекте")
        form = QFormLayout(grp_info); form.setSpacing(10)

        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText("MyProject")
        form.addRow("Название:", self._fld_name)

        path_row = QHBoxLayout()
        self._fld_path = QLineEdit()
        self._fld_path.setPlaceholderText("Выберите папку проекта...")
        self._fld_path.setReadOnly(True)
        btn_pick = QPushButton("...")
        btn_pick.setObjectName("iconBtn"); btn_pick.setFixedWidth(32)
        btn_pick.clicked.connect(self._pick_folder)
        path_row.addWidget(self._fld_path); path_row.addWidget(btn_pick)
        form.addRow("Папка:", path_row)
        layout.addWidget(grp_info)

        # Mode selection
        grp_mode = QGroupBox("Режим работы с AI")
        ml = QVBoxLayout(grp_mode); ml.setSpacing(12)

        self._radio_new = QRadioButton()
        self._radio_new.setChecked(True)
        new_row = QHBoxLayout()
        new_row.addWidget(self._radio_new)
        new_info = QWidget()
        ni_l = QVBoxLayout(new_info); ni_l.setContentsMargins(0, 0, 0, 0); ni_l.setSpacing(2)
        lbl_new = QLabel("🆕 Новый проект — разработка с нуля")
        lbl_new.setStyleSheet("color:#CDD6F4;font-size:13px;font-weight:bold;")
        desc_new = QLabel("AI даёт полные реализации кода, объяснения архитектуры.\nПодходит для создания новых скриптов и приложений.")
        desc_new.setStyleSheet("color:#565f89;font-size:11px;")
        desc_new.setWordWrap(True)
        ni_l.addWidget(lbl_new); ni_l.addWidget(desc_new)
        new_row.addWidget(new_info); new_row.addStretch()
        ml.addLayout(new_row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background:#1E2030;max-height:1px;")
        ml.addWidget(sep2)

        self._radio_existing = QRadioButton()
        exist_row = QHBoxLayout()
        exist_row.addWidget(self._radio_existing)
        exist_info = QWidget()
        ei_l = QVBoxLayout(exist_info); ei_l.setContentsMargins(0, 0, 0, 0); ei_l.setSpacing(2)
        lbl_ex = QLabel("🔧 Существующий проект — доработка")
        lbl_ex.setStyleSheet("color:#CDD6F4;font-size:13px;font-weight:bold;")
        desc_ex = QLabel("AI даёт ТОЛЬКО точечные патчи [SEARCH/REPLACE].\nПодходит для улучшения готового кода без переписывания.")
        desc_ex.setStyleSheet("color:#565f89;font-size:11px;")
        desc_ex.setWordWrap(True)
        ei_l.addWidget(lbl_ex); ei_l.addWidget(desc_ex)
        exist_row.addWidget(exist_info); exist_row.addStretch()
        ml.addLayout(exist_row)

        self._btn_group = QButtonGroup()
        self._btn_group.addButton(self._radio_new, 0)
        self._btn_group.addButton(self._radio_existing, 1)
        layout.addWidget(grp_mode)

        layout.addStretch()

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedWidth(90)
        btn_cancel.clicked.connect(self.reject)
        btn_create = QPushButton("Создать проект")
        btn_create.setObjectName("primaryBtn")
        btn_create.setFixedWidth(140)
        btn_create.clicked.connect(self._create)
        footer.addWidget(btn_cancel); footer.addSpacing(8); footer.addWidget(btn_create)
        layout.addLayout(footer)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку проекта")
        if folder:
            self._fld_path.setText(folder)
            if not self._fld_name.text():
                self._fld_name.setText(Path(folder).name)

    def _create(self):
        path = self._fld_path.text().strip()
        name = self._fld_name.text().strip()
        if not path:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Нет папки", "Укажи папку проекта.")
            return
        if not name:
            name = Path(path).name or "Project"
        mode = (ProjectMode.NEW_PROJECT if self._radio_new.isChecked()
                else ProjectMode.EXISTING_PROJECT)
        self._result = (path, name, mode)
        self.accept()

    def result_data(self) -> tuple[str, str, ProjectMode]:
        return self._result or (".", "Project", ProjectMode.NEW_PROJECT)
