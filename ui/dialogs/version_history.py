"""
Version History Dialog — browse and restore file versions.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QFrame, QTabWidget, QWidget, QMessageBox, QSizePolicy
)

from services.version_control import VersionControlService, FileVersion


class VersionHistoryDialog(QDialog):

    version_restored = pyqtSignal(str, str)  # file_path, new_content

    def __init__(
        self,
        vc: VersionControlService,
        file_path: str,
        current_content: str,
        parent=None,
    ):
        super().__init__(parent)
        self._vc = vc
        self._file_path = file_path
        self._current_content = current_content
        self._versions = vc.get_versions(file_path)

        self.setWindowTitle(f"История версий — {Path(file_path).name}")
        self.setMinimumSize(900, 600)
        self.resize(1000, 680)
        self.setModal(True)

        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel(f"📋 История: {Path(self._file_path).name}")
        title.setObjectName("titleLabel")
        hdr.addWidget(title)
        hdr.addStretch()

        stats = QLabel(f"{len(self._versions)} версий")
        stats.setStyleSheet("color: #E0AF68; font-size: 12px;")
        hdr.addWidget(stats)
        layout.addLayout(hdr)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: version list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        lbl_list = QLabel("ВЕРСИИ")
        lbl_list.setObjectName("sectionLabel")
        ll.addWidget(lbl_list)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget { background: #0E1117; border: 1px solid #1E2030; border-radius: 6px; }
            QListWidget::item { padding: 8px 12px; border-bottom: 1px solid #1E2030; }
            QListWidget::item:selected { background: #2E3148; }
        """)
        self._list.currentItemChanged.connect(self._on_version_selected)
        ll.addWidget(self._list)

        left.setMinimumWidth(260)
        splitter.addWidget(left)

        # Right: diff / content preview
        right = QTabWidget()

        # Diff view
        self._diff_view = QTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 11))
        self._diff_view.setStyleSheet("background: #0A0D14; border: none; color: #CDD6F4;")
        right.addTab(self._diff_view, "Diff (относительно текущего)")

        # Content view
        self._content_view = QTextEdit()
        self._content_view.setReadOnly(True)
        self._content_view.setFont(QFont("JetBrains Mono,Cascadia Code,Consolas", 11))
        self._content_view.setStyleSheet("background: #0A0D14; border: none; color: #CDD6F4;")
        right.addTab(self._content_view, "Содержимое версии")

        # Meta view
        self._meta_view = QTextEdit()
        self._meta_view.setReadOnly(True)
        self._meta_view.setStyleSheet("background: #0A0D14; border: none; color: #A9B1D6; font-size: 12px;")
        right.addTab(self._meta_view, "Метаданные")

        splitter.addWidget(right)
        splitter.setSizes([270, 700])
        layout.addWidget(splitter, stretch=1)

        # Footer
        footer = QHBoxLayout()

        btn_snapshot = QPushButton("📸 Создать снапшот")
        btn_snapshot.setToolTip("Сохранить состояние всего проекта")
        btn_snapshot.clicked.connect(self._create_snapshot)
        footer.addWidget(btn_snapshot)

        footer.addStretch()

        self._btn_restore = QPushButton("⏪ Восстановить эту версию")
        self._btn_restore.setObjectName("primaryBtn")
        self._btn_restore.setEnabled(False)
        self._btn_restore.clicked.connect(self._restore_selected)
        footer.addWidget(self._btn_restore)

        btn_close = QPushButton("Закрыть")
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_close)

        layout.addLayout(footer)

    def _populate(self):
        self._list.clear()

        # Current version at top
        curr_item = QListWidgetItem("● Текущая версия")
        curr_item.setForeground(QColor("#9ECE6A"))
        curr_item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(curr_item)

        for version in self._versions:
            item = QListWidgetItem(
                f"⏱ {version.display_time}\n"
                f"   {version.description[:50]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, version)
            delta_str = ""
            if version.lines_before and version.lines_after:
                delta = version.lines_after - version.lines_before
                delta_str = f" Δ{delta:+d}"
            item.setToolTip(
                f"Hash: {version.content_hash}\n"
                f"Строк: {version.lines_before}{delta_str}\n"
                f"Размер: {version.size_bytes} байт"
            )
            self._list.addItem(item)

    def _on_version_selected(self, current, _previous):
        if not current:
            return

        version: FileVersion | None = current.data(Qt.ItemDataRole.UserRole)

        if version is None:
            # Current version
            self._diff_view.setHtml("<span style='color:#565f89'>Это текущая версия файла.</span>")
            self._content_view.setPlainText(self._current_content)
            self._meta_view.setPlainText("Текущая версия — не сохранена в истории.")
            self._btn_restore.setEnabled(False)
            return

        # Load backup content
        try:
            backup_content = self._vc.get_version_content(version)
        except Exception as e:
            self._diff_view.setHtml(f"<span style='color:#F7768E'>Ошибка: {e}</span>")
            return

        # Show diff
        diff_lines = self._vc.diff_versions(version, self._current_content)
        self._render_diff(diff_lines)

        # Show content
        self._content_view.setPlainText(backup_content)

        # Show meta
        meta = (
            f"Файл:        {version.relative_path}\n"
            f"Время:       {version.display_time}\n"
            f"Hash:        {version.content_hash}\n"
            f"Описание:    {version.description}\n"
            f"Строк до:    {version.lines_before}\n"
            f"Строк после: {version.lines_after}\n"
            f"Размер:      {version.size_bytes} байт\n"
        )
        if version.patch_search:
            meta += f"\nПоиск:\n{version.patch_search[:300]}\n"
        if version.patch_replace:
            meta += f"\nЗамена:\n{version.patch_replace[:300]}\n"
        self._meta_view.setPlainText(meta)

        self._btn_restore.setEnabled(True)

    def _render_diff(self, diff_lines: list[str]):
        if not diff_lines:
            self._diff_view.setHtml(
                "<span style='color:#565f89'>Изменений нет — файл идентичен текущей версии.</span>"
            )
            return

        html_parts = ["<pre style='font-family: monospace; font-size: 11px;'>"]
        for line in diff_lines:
            if line.startswith("+"):
                color = "#9ECE6A"
            elif line.startswith("-"):
                color = "#F7768E"
            elif line.startswith("@@"):
                color = "#7AA2F7"
            elif line.startswith("---") or line.startswith("+++"):
                color = "#E0AF68"
            else:
                color = "#565f89"

            # Escape HTML
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(f'<span style="color:{color}">{safe}</span>\n')

        html_parts.append("</pre>")
        self._diff_view.setHtml("".join(html_parts))

    def _restore_selected(self):
        item = self._list.currentItem()
        if not item:
            return
        version: FileVersion | None = item.data(Qt.ItemDataRole.UserRole)
        if not version:
            return

        reply = QMessageBox.question(
            self, "Восстановить версию",
            f"Восстановить файл к версии от {version.display_time}?\n\n"
            f"Описание: {version.description}\n\n"
            "Текущий файл будет сохранён как резервная копия.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            new_content = self._vc.restore_version(version)
            self.version_restored.emit(self._file_path, new_content)
            self._current_content = new_content
            QMessageBox.information(
                self, "Успешно",
                f"Файл восстановлен к версии {version.display_time}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось восстановить: {e}")

    def _create_snapshot(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Снапшот проекта",
            "Название снапшота:"
        )
        if ok and name:
            desc, ok2 = QInputDialog.getText(
                self, "Описание", "Описание (необязательно):"
            )
            # Get all tracked file paths — simplified to just current file
            snap = self._vc.create_snapshot(name, desc or "", [self._file_path])
            QMessageBox.information(
                self, "Снапшот создан",
                f"Снапшот '{name}' создан.\n{len(snap.file_versions)} файл(ов) сохранено."
            )
