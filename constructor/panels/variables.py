"""Панель переменных проекта и заметок."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QPlainTextEdit, QTextEdit, QListWidget,
    QListWidgetItem, QComboBox, QCheckBox, QGroupBox,
    QFileDialog, QMessageBox, QMenu, QApplication,
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QInputDialog, QSplitter, QSpinBox
)

from services.agent_models import AgentWorkflow

try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): return "#CDD6F4"
    def register_theme_refresh(cb): pass

try:
    from ui.i18n import tr
except ImportError:
    def tr(s): return s

class ProjectVariablesPanel(QWidget):
    """Панель переменных проекта как в ZennoPoster."""
    
    variables_changed = pyqtSignal()  # <-- ДОБАВИТЬ ЭТУ СТРОКУ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow: AgentWorkflow | None = None
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._var_filter = QLineEdit()
        self._snippet_loading = False
        # ── Списки и таблицы проекта (ZennoPoster-style) ──────────
        # Формат списка: {id, name, items: [str], file_path, load_mode, encoding}
        # load_mode: 'static'|'on_start'|'always'
        # Формат таблицы: {id, name, columns:[str], rows:[[str]], file_path, load_mode, has_header}
        self._project_lists: list = []
        self._project_tables: list = []
        
        # Сначала создаем UI, потом применяем стили!
        self._build_ui()
        self._apply_styles()
        
        # Регистрируем callback для обновления при смене темы
        try:
            register_theme_refresh(self._on_theme_changed)
        except Exception:
            pass
    
    def load_from_workflow(self, workflow: AgentWorkflow):
        """Загрузить переменные при открытии проекта."""
        self._workflow = workflow
        
        if hasattr(self, '_refresh_table'):
            self._refresh_table()
        elif hasattr(self, '_update_ui'):
            self._update_ui()
        elif hasattr(self, 'refresh'):
            self.refresh()

        self._load_lists_tables_from_workflow()
        self._load_global_vars_from_workflow()
    
    def _apply_styles(self):
        """Применить текущие цвета темы ко всем виджетам панели"""
        # ═══ ИСПРАВЛЕНИЕ: полный стиль для QTabWidget включая pane и base background ═══
        self._tabs.setStyleSheet(f"""
            QTabWidget {{ background: {get_color('bg1')}; border: none; }}
            QTabWidget::pane {{ 
                border: 1px solid {get_color('bd2')}; 
                background: {get_color('bg1')}; 
                top: -1px;
            }}
            QTabBar::tab {{ 
                padding: 6px 12px; 
                background: {get_color('bg2')}; 
                color: {get_color('tx1')}; 
                border: 1px solid {get_color('bd2')};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{ 
                background: {get_color('bg3')}; 
                color: {get_color('ac')}; 
            }}
            QTabBar::tab:hover {{ 
                background: {get_color('bg3')}; 
            }}
        """)
        
        # ═══ ИСПРАВЛЕНИЕ: стиль для самой панели (контейнера) ═══
        self.setStyleSheet(f"""
            ProjectVariablesPanel {{
                background: {get_color('bg1')};
                border: none;
            }}
            QWidget {{
                background: {get_color('bg1')};
            }}
        """)
        
        # Обновляем кнопку заметки
        self._apply_note_button_style()
        
        # Обновляем стиль таблицы переменных
        if hasattr(self, '_var_table'):
            self._var_table.setStyleSheet(f"""
                QTableWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; gridline-color: {get_color('bd2')}; font-size: 11px; }}
                QTableWidget::item {{ padding: 2px 4px; }}
                QTableWidget::item:selected {{ background: {get_color('bg3')}; }}
                QHeaderView::section {{ background: {get_color('bg2')}; color: {get_color('tx1')}; border: 1px solid {get_color('bd2')}; padding: 3px; font-size: 10px; }}
            """)
        
        # Обновляем стиль списка заметок
        if hasattr(self, '_notes_list'):
            self._notes_list.setStyleSheet(f"""
                QListWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; border: 1px solid {get_color('bd2')}; }}
                QListWidget::item {{ padding: 6px; border-bottom: 1px solid {get_color('bd2')}; }}
                QListWidget::item:selected {{ background: {get_color('bg3')}; }}
            """)
        
        # ═══ ИСПРАВЛЕНИЕ: обновляем кнопки если они есть ═══
        if hasattr(self, '_btn_style_template'):
            btn_style = self._btn_style_template % (
                get_color('bg2'), get_color('tx0'), get_color('bd2'), get_color('bg3')
            )
            # Найдём кнопки в layout и обновим их стили
            for btn in [self.findChild(QPushButton, name) for name in ['btn_add', 'btn_del', 'btn_import']]:
                if btn:
                    btn.setStyleSheet(btn_style)
    
    def _apply_note_button_style(self):
        """Применить стиль к кнопке добавления заметки"""
        if hasattr(self, '_btn_add_note'):
            self._btn_add_note.setStyleSheet(f"""
                QPushButton {{ 
                    background: {get_color('bg2')}; 
                    color: {get_color('tx0')}; 
                    border: 1px solid {get_color('bd2')}; 
                    padding: 6px; 
                }}
                QPushButton:hover {{ background: {get_color('bg3')}; }}
            """)
    
    def _on_theme_changed(self):
        """Вызывается при смене темы"""
        self._apply_styles()
        # ── Обновляем кнопки в табе Списки/Таблицы ──────────────
        _btn_base = f"""
            QPushButton {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                          border: 1px solid {get_color('bd')}; border-radius: 4px; padding: 4px 8px; }}
            QPushButton:hover {{ background: {get_color('bg3')}; color: {get_color('tx0')}; }}
        """
        _btn_ok = f"""
            QPushButton {{ background: {get_color('bg2')}; color: {get_color('ac')};
                          border: 1px solid {get_color('ac')}; border-radius: 4px; padding: 4px 8px; }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
        """
        _btn_err = f"""
            QPushButton {{ background: {get_color('bg2')}; color: {get_color('err')};
                          border: 1px solid {get_color('err')}; border-radius: 4px; padding: 4px 8px; }}
            QPushButton:hover {{ background: {get_color('err')}; color: #000; }}
        """
        for attr in ['_btn_lt_add_list', '_btn_lt_add_table', '_btn_lt_open', '_btn_lt_delete', '_btn_lt_refresh']:
            btn = getattr(self, attr, None)
            if btn:
                if 'add' in attr or 'open' in attr:
                    btn.setStyleSheet(_btn_ok)
                elif 'delete' in attr:
                    btn.setStyleSheet(_btn_err)
                else:
                    btn.setStyleSheet(_btn_base)
        # Обновляем виджеты Regex Tester которые имеют встроенные стили
        if hasattr(self, '_regex_result'):
            self._regex_result.setStyleSheet(f"""
                QPlainTextEdit {{
                    background: {get_color('bg0')};
                    color: #9ECE6A;
                    font-family: 'Consolas', monospace;
                    font-size: 11px;
                    border: 1px solid {get_color('bd')};
                    border-radius: 4px;
                }}
            """)
        if hasattr(self, '_regex_input'):
            self._regex_input.setStyleSheet(f"""
                QPlainTextEdit {{
                    background: {get_color('bg2')};
                    color: {get_color('tx0')};
                    border: 1px solid {get_color('bd')};
                    border-radius: 4px;
                }}
            """)
        if hasattr(self, '_regex_pattern'):
            self._regex_pattern.setStyleSheet(f"""
                QLineEdit {{
                    background: {get_color('bg2')};
                    color: {get_color('tx0')};
                    border: 1px solid {get_color('bd')};
                    border-radius: 4px;
                    padding: 3px;
                }}
            """)
        if hasattr(self, '_tabs'):
            self._tabs.setStyleSheet(f"""
                QTabWidget::pane {{ background: {get_color('bg1')}; border: 1px solid {get_color('bd')}; }}
                QTabBar::tab {{ background: {get_color('bg2')}; color: {get_color('tx1')}; padding: 4px 10px; border-radius: 4px 4px 0 0; }}
                QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('tx0')}; }}
            """)
        # ── Обновляем sub-tabs и виджеты вкладки Списки/Таблицы ──
        if hasattr(self, '_lists_tables_sub_tabs'):
            self._lists_tables_sub_tabs.setStyleSheet(f"""
                QTabWidget::pane {{ background: {get_color('bg1')}; border: 1px solid {get_color('bd2')}; }}
                QTabBar::tab {{ background: {get_color('bg2')}; color: {get_color('tx1')}; padding: 4px 10px; }}
                QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}
            """)
        if hasattr(self, '_lists_widget'):
            self._lists_widget.setStyleSheet(
                f"QListWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; "
                f"border: 1px solid {get_color('bd2')}; }}"
                f"QListWidget::item {{ padding: 5px; border-bottom: 1px solid {get_color('bg3')}; }}"
                f"QListWidget::item:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}"
            )
        if hasattr(self, '_list_preview'):
            self._list_preview.setStyleSheet(
                f"QPlainTextEdit {{ background: {get_color('bg0')}; color: #9ECE6A; "
                f"font-size: 10px; border: 1px solid {get_color('bd2')}; }}"
            )
        if hasattr(self, '_tables_widget'):
            self._tables_widget.setStyleSheet(
                f"QListWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; "
                f"border: 1px solid {get_color('bd2')}; }}"
                f"QListWidget::item {{ padding: 5px; border-bottom: 1px solid {get_color('bg3')}; }}"
                f"QListWidget::item:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}"
            )
        if hasattr(self, '_table_preview'):
            self._table_preview.setStyleSheet(
                f"QTableWidget {{ background: {get_color('bg0')}; color: {get_color('ac')}; "
                f"font-size: 10px; gridline-color: {get_color('bd2')}; }}"
                f"QHeaderView::section {{ background: {get_color('bg2')}; color: {get_color('tx1')}; "
                f"border: 1px solid {get_color('bd2')}; }}"
            )
        if hasattr(self, '_global_var_table'):
            self._global_var_table.setStyleSheet(
                f"QTableWidget {{ background: {get_color('bg0')}; color: {get_color('tx0')}; "
                f"gridline-color: {get_color('bd2')}; border: 1px solid {get_color('bd')}; }}"
                f"QHeaderView::section {{ background: {get_color('bg2')}; color: {get_color('tx1')}; "
                f"border: 1px solid {get_color('bd2')}; }}"
            )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # self._tabs уже создан в __init__
        layout.addWidget(self._tabs)
        
        # ── Таб 1: Переменные ──
        var_widget = QWidget()
        var_layout = QVBoxLayout(var_widget)
        var_layout.setContentsMargins(2, 2, 2, 2)

        # Фильтр (стили теперь в _apply_styles)
        self._var_filter.setPlaceholderText("Фильтр переменных...")
        self._var_filter.textChanged.connect(self._filter_variables)
        var_layout.addWidget(self._var_filter)

        # Таблица переменных
        self._var_table = QTableWidget()
        self._var_table.setColumnCount(4)
        # ═══ ФИС: гарантируем что таблица всегда обновляется ═══
        self._var_table.setUpdatesEnabled(True)
        self._var_table.setHorizontalHeaderLabels([tr("Имя"), tr("Значение"), tr("Тип"), tr("По умолч.")])
        self._var_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._var_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._var_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._var_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self._var_table.setColumnWidth(2, 70)
        self._var_table.verticalHeader().setVisible(False)
        self._var_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._var_table.setAlternatingRowColors(True)
        self._var_table.cellChanged.connect(self._on_variable_edited)
        # Стили перенесены в _apply_styles()
        var_layout.addWidget(self._var_table)

        # Кнопки CRUD
        btn_row = QHBoxLayout()
        self._btn_style_template = """
            QPushButton {{ background: %s; color: %s; border: 1px solid %s; padding: 4px 8px; }}
            QPushButton:hover {{ background: %s; }}
        """
        btn_style = self._btn_style_template % (
            get_color('bg2'), get_color('tx0'), get_color('bd2'), get_color('bg3')
        )
        btn_add = QPushButton(tr("➕ Добавить"))
        btn_del = QPushButton(tr("🗑 Удалить"))
        btn_import = QPushButton(tr("📥"))
        btn_add.setStyleSheet(btn_style)
        btn_del.setStyleSheet(btn_style)
        btn_import.setStyleSheet(btn_style)
        btn_import.setToolTip("Импорт из JSON/TXT")
        btn_import.setFixedWidth(32)
        btn_import.clicked.connect(self._import_variables)
        btn_add.clicked.connect(self._add_variable)      # <-- ДОБАВИТЬ
        btn_del.clicked.connect(self._delete_variable)   # <-- ДОБАВИТЬ
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_import)
        var_layout.addLayout(btn_row)

        self._tabs.addTab(var_widget, tr("📋 Переменные"))
        
        # ── Таб: Тестер Regex ──
        regex_widget = QWidget()
        regex_layout = QVBoxLayout(regex_widget)
        regex_layout.setSpacing(6)
        
        # Входной текст
        regex_input_lbl = QLabel(tr("Текст для обработки:"))
        regex_input_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #7AA2F7;")
        regex_layout.addWidget(regex_input_lbl)
        
        self._regex_input = QPlainTextEdit()
        self._regex_input.setPlaceholderText("Вставьте текст для поиска регулярным выражением...")
        self._regex_input.setMaximumHeight(120)
        regex_layout.addWidget(self._regex_input)
        
        # Regex строка
        regex_row = QHBoxLayout()
        regex_row.addWidget(QLabel("Regex:"))
        self._regex_pattern = QLineEdit()
        self._regex_pattern.setPlaceholderText("(?<=<title>).*(?=</title>)")
        regex_row.addWidget(self._regex_pattern)
        
        self._regex_btn_test = QPushButton("▶ Тест")
        self._regex_btn_test.setStyleSheet("background: #7AA2F7; color: white; padding: 4px 12px; border-radius: 4px;")
        self._regex_btn_test.clicked.connect(self._run_regex_test)
        regex_row.addWidget(self._regex_btn_test)
        regex_layout.addLayout(regex_row)
        
        # Опции
        regex_opts = QHBoxLayout()
        self._regex_chk_ignorecase = QCheckBox(tr("Без учёта регистра"))
        self._regex_chk_ignorecase.setChecked(True)
        self._regex_chk_dotall = QCheckBox(tr("Точка = любой символ"))
        self._regex_chk_multiline = QCheckBox(tr("Многострочный"))
        self._regex_chk_shortest = QCheckBox(tr("Самое короткое"))
        regex_opts.addWidget(self._regex_chk_ignorecase)
        regex_opts.addWidget(self._regex_chk_dotall)
        regex_opts.addWidget(self._regex_chk_multiline)
        regex_opts.addWidget(self._regex_chk_shortest)
        regex_opts.addStretch()
        regex_layout.addLayout(regex_opts)
        
        # ═══ Помощник по созданию регулярных выражений ═══
        helper_group = QGroupBox(tr("🔨 Помощник по созданию regex"))
        helper_group.setStyleSheet(f"QGroupBox {{ color: #7AA2F7; font-size: 11px; border: 1px solid {get_color('bd')}; border-radius: 4px; margin-top: 6px; padding-top: 14px; }}")
        helper_layout = QVBoxLayout(helper_group)
        helper_layout.setSpacing(4)
        
        # Строка 1
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("Перед текстом всегда есть:")))
        self._regex_before = QLineEdit()
        self._regex_before.setPlaceholderText('Пример: <title>')
        self._regex_before.setToolTip("Текст который ВСЕГДА идёт ДО искомого. НЕ включается в результат (lookbehind)")
        row1.addWidget(self._regex_before)
        helper_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("Это идёт после искомого текста:")))
        self._regex_after = QLineEdit()
        self._regex_after.setPlaceholderText('Пример: </title>')
        self._regex_after.setToolTip("Текст который ВСЕГДА идёт ПОСЛЕ искомого. НЕ включается в результат (lookahead)")
        row2.addWidget(self._regex_after)
        helper_layout.addLayout(row2)
        
        # Строка 2: Начинается с / Заканчивается на (ВКЛЮЧАЮТСЯ в результат)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel(tr("Искомый текст начинается с:")))
        self._regex_starts = QLineEdit()
        self._regex_starts.setPlaceholderText('Пример: http')
        self._regex_starts.setToolTip("Начало искомого текста — ВКЛЮЧАЕТСЯ в результат")
        row3.addWidget(self._regex_starts)
        helper_layout.addLayout(row3)
        
        row4 = QHBoxLayout()
        row4.addWidget(QLabel(tr("Этим заканчивается искомый текст:")))
        self._regex_ends = QLineEdit()
        self._regex_ends.setPlaceholderText('Пример: .html')
        self._regex_ends.setToolTip("Конец искомого текста — ВКЛЮЧАЕТСЯ в результат")
        row4.addWidget(self._regex_ends)
        helper_layout.addLayout(row4)
        
        # Кнопка сборки
        btn_row = QHBoxLayout()
        btn_build = QPushButton(tr("🔨 Собрать regex"))
        btn_build.setStyleSheet("background: #E0AF68; color: #1a1b26; padding: 4px 16px; border-radius: 4px; font-weight: bold;")
        btn_build.clicked.connect(self._build_regex_from_helper)
        btn_row.addWidget(btn_build)
        btn_row.addStretch()
        helper_layout.addLayout(btn_row)
        
        regex_layout.addWidget(helper_group)
        
        # Результат
        regex_result_lbl = QLabel(tr("Результат:"))
        regex_result_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #9ECE6A;")
        regex_layout.addWidget(regex_result_lbl)
        
        self._regex_result = QPlainTextEdit()
        self._regex_result.setReadOnly(True)
        self._regex_result.setMaximumHeight(150)
        self._regex_result.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {get_color('bg0')};
                color: #9ECE6A;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
            }}
        """)
        regex_layout.addWidget(self._regex_result)
        
        # Статус + копирование
        regex_bottom = QHBoxLayout()
        self._regex_status = QLabel("")
        self._regex_status.setStyleSheet("color: #565f89; font-size: 10px;")
        regex_bottom.addWidget(self._regex_status)
        regex_bottom.addStretch()
        btn_copy_regex = QPushButton(tr("📋 Копировать regex"))
        btn_copy_regex.clicked.connect(lambda: QApplication.clipboard().setText(self._regex_pattern.text()))
        btn_copy_result = QPushButton(tr("📋 Копировать результат"))
        btn_copy_result.clicked.connect(lambda: QApplication.clipboard().setText(self._regex_result.toPlainText()))
        btn_to_snippet = QPushButton(tr("📥 В поле сниппета"))
        btn_to_snippet.setToolTip("Вставить regex в поле 'Regex / Что искать' текущего сниппета")
        btn_to_snippet.clicked.connect(self._regex_to_snippet_field)
        regex_bottom.addWidget(btn_copy_regex)
        regex_bottom.addWidget(btn_copy_result)
        regex_bottom.addWidget(btn_to_snippet)
        regex_layout.addLayout(regex_bottom)
        
        # Шпаргалка
        cheat_lbl = QLabel(
            "<b>Шпаргалка:</b> "
            "<code>.</code> любой символ | <code>\\d</code> цифра | <code>\\w</code> буква/цифра | "
            "<code>\\s</code> пробел | <code>*</code> 0+ | <code>+</code> 1+ | <code>?</code> 0-1 | "
            "<code>(?<=X)</code> после X | <code>(?=X)</code> перед X | "
            "<code>[abc]</code> один из | <code>(a|b)</code> или"
        )
        cheat_lbl.setWordWrap(True)
        cheat_lbl.setStyleSheet("color: #565f89; font-size: 9px; padding: 4px;")
        regex_layout.addWidget(cheat_lbl)
        
        regex_layout.addStretch()
        self._tabs.addTab(regex_widget, tr("🔍 Regex Тестер"))

        # ── Таб: JS Тестер ────────────────────────────────────────
        js_widget = self._build_js_tester_tab()
        self._tabs.addTab(js_widget, tr("🟨 JS Тестер"))

        # ── Таб: XPath / JSONPath Тестер ─────────────────────────
        xjson_widget = self._build_xjson_tester_tab()
        self._tabs.addTab(xjson_widget, tr("🔣 X/JSON Path"))
        
        # ── Таб: Списки / Таблицы ─────────────────────────────────
        self._tabs.addTab(self._build_lists_tables_tab(), tr("📋 Списки / Таблицы"))

        # ── Таб: Глобальные переменные (между потоками) ────────────
        self._tabs.addTab(self._build_global_vars_tab(), tr("🌍 Глобальные"))
        
        # ── Таб 2: Заметки ──
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        notes_layout.setContentsMargins(2, 2, 2, 2)

        self._btn_add_note = QPushButton(tr("📝 Новая заметка"))
        self._apply_note_button_style()
        self._btn_add_note.clicked.connect(self._add_note)  # <-- исправлено
        notes_layout.addWidget(self._btn_add_note)  # <-- исправлено

        self._notes_list = QListWidget()
        # Стили перенесены в _apply_styles()
        self._notes_list.itemDoubleClicked.connect(self._edit_note)
        self._notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._notes_list.customContextMenuRequested.connect(self._note_context_menu)
        notes_layout.addWidget(self._notes_list)

        self._tabs.addTab(notes_widget, tr("📌 Заметки"))

        # При каждом открытии вкладки "Списки / Таблицы" — принудительно перезагружать
        self._tabs.currentChanged.connect(self._on_main_tab_changed)

        layout.addWidget(self._tabs)
    
    def _build_global_vars_tab(self) -> QWidget:
        """Вкладка глобальных переменных, доступных между потоками."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)

        lbl = QLabel(tr("🌍 Глобальные переменные (общие между потоками)"))
        lbl.setStyleSheet(f"color: {get_color('ac')}; font-weight: bold; font-size: 11px; padding: 4px;")
        lay.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_add = QPushButton(tr("➕ Добавить"))
        btn_add.setStyleSheet(f"""
            QPushButton {{ background: {get_color('bg2')}; color: {get_color('ac')};
                          border: 1px solid {get_color('ac')}; border-radius: 4px; padding: 4px 8px; }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
        """)
        btn_add.clicked.connect(self._add_global_var)
        btn_del = QPushButton(tr("🗑 Удалить"))
        btn_del.setStyleSheet(f"""
            QPushButton {{ background: {get_color('bg2')}; color: {get_color('err')};
                          border: 1px solid {get_color('err')}; border-radius: 4px; padding: 4px 8px; }}
            QPushButton:hover {{ background: {get_color('err')}; color: #000; }}
        """)
        btn_del.clicked.connect(self._del_global_var)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._global_var_table = QTableWidget(0, 3)
        self._global_var_table.setHorizontalHeaderLabels([tr("Имя"), tr("Значение"), tr("По умолчанию")])
        self._global_var_table.horizontalHeader().setStretchLastSection(True)
        self._global_var_table.setStyleSheet(
            f"QTableWidget {{ background: {get_color('bg0')}; color: {get_color('tx0')}; "
            f"gridline-color: {get_color('bd2')}; border: 1px solid {get_color('bd')}; }}"
        )
        self._global_var_table.cellChanged.connect(self._save_global_vars_to_workflow)
        lay.addWidget(self._global_var_table)

        info = QLabel(tr("Эти переменные доступны из всех потоков при многопоточном запуске через менеджер."))
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {get_color('tx2')}; font-size: 9px; padding: 4px;")
        lay.addWidget(info)
        return w

    def _add_global_var(self):
        row = self._global_var_table.rowCount()
        self._global_var_table.insertRow(row)
        self._global_var_table.setItem(row, 0, QTableWidgetItem(f"global_{row + 1}"))
        self._global_var_table.setItem(row, 1, QTableWidgetItem(""))
        self._global_var_table.setItem(row, 2, QTableWidgetItem(""))
        self._save_global_vars_to_workflow()

    def _del_global_var(self):
        row = self._global_var_table.currentRow()
        if row >= 0:
            self._global_var_table.removeRow(row)
            self._save_global_vars_to_workflow()

    def _save_global_vars_to_workflow(self):
        if not self._workflow:
            return
        gvars = []
        for r in range(self._global_var_table.rowCount()):
            name_item = self._global_var_table.item(r, 0)
            val_item = self._global_var_table.item(r, 1)
            def_item = self._global_var_table.item(r, 2)
            gvars.append({
                'name': name_item.text() if name_item else '',
                'value': val_item.text() if val_item else '',
                'default': def_item.text() if def_item else '',
            })
        meta = getattr(self._workflow, 'metadata', {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        meta['global_variables'] = gvars
        self._workflow.metadata = meta

    def _load_global_vars_from_workflow(self):
        if not self._workflow or not hasattr(self, '_global_var_table'):
            return
        meta = getattr(self._workflow, 'metadata', {}) or {}
        if not isinstance(meta, dict):
            return
        gvars = meta.get('global_variables', [])
        # Не затираем таблицу если в metadata ещё нет данных, но в таблице уже что-то есть
        if not gvars and self._global_var_table.rowCount() > 0:
            return
        self._global_var_table.blockSignals(True)
        try:
            self._global_var_table.setRowCount(0)
            for gv in gvars:
                if not isinstance(gv, dict):
                    continue
                row = self._global_var_table.rowCount()
                self._global_var_table.insertRow(row)
                self._global_var_table.setItem(row, 0, QTableWidgetItem(gv.get('name', '')))
                self._global_var_table.setItem(row, 1, QTableWidgetItem(gv.get('value', '')))
                self._global_var_table.setItem(row, 2, QTableWidgetItem(gv.get('default', '')))
        finally:
            self._global_var_table.blockSignals(False)
    
    def _on_main_tab_changed(self, index: int):
        """Вызывается при переключении основных вкладок панели переменных."""
        # Сохраняем глобальные переменные при уходе с любой другой вкладки
        # (на случай если cellChanged не сработал — доп. страховка)
        self._save_global_vars_to_workflow()

        # 0: Переменные, 1: Regex, 2: Списки/Таблицы, 3: Глобальные, 4: Заметки
        if index == 2:
            self._load_lists_tables_from_workflow()
        elif index == 3:
            self._load_global_vars_from_workflow()

    def _sync_variable_to_ui(self, name: str, value: str):
        """Обновить значение переменной в таблице UI без полной перезагрузки"""
        # ═══ НОВОЕ: сначала обновляем модель, потом UI ═══
        if self._workflow and name in self._workflow.project_variables:
            self._workflow.project_variables[name]['value'] = str(value)
        
        self._var_table.blockSignals(True)
        try:
            found = False
            for row in range(self._var_table.rowCount()):
                name_item = self._var_table.item(row, 0)
                # ═══ ФИКС: более надежная проверка имени ═══
                if name_item is None:
                    continue
                item_text = name_item.text()
                if item_text is None:
                    continue
                if item_text.strip() == name.strip():
                    value_item = self._var_table.item(row, 1)
                    if value_item is None:
                        # Создаем item если его нет
                        value_item = QTableWidgetItem(str(value))
                        self._var_table.setItem(row, 1, value_item)
                    else:
                        value_item.setText(str(value))
                    # Принудительно обновляем
                    self._var_table.viewport().update()
                    found = True
                    print(f"[UI SYNC] Обновлена строка {row}: {name} = {value}")
                    break
            
            if not found:
                print(f"[UI SYNC WARNING] Переменная {name} не найдена в таблице!")
                # ═══ ФИКС: добавляем новую строку если переменная не найдена ═══
                row = self._var_table.rowCount()
                self._var_table.insertRow(row)
                name_item = QTableWidgetItem(name)
                value_item = QTableWidgetItem(str(value))
                type_combo = QComboBox()
                type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
                self._var_table.setItem(row, 0, name_item)
                self._var_table.setItem(row, 1, value_item)
                self._var_table.setCellWidget(row, 2, type_combo)
                self._var_table.setItem(row, 3, QTableWidgetItem(""))
        finally:
            self._var_table.blockSignals(False)
    
    def set_workflow(self, wf: AgentWorkflow):
        self._workflow = wf
        self._reload_variables()
        self._reload_notes()
        self._load_lists_tables_from_workflow()
        self._load_global_vars_from_workflow()
        # Принудительно сбрасываем переменные к дефолтным при загрузке
        self.reset_variables_to_defaults()

    # ── Переменные ──────────────────────────────

    def _reload_variables(self):
        self._var_table.blockSignals(True)
        self._var_table.setRowCount(0)
        if not self._workflow:
            self._var_table.blockSignals(False)
            self._var_table.viewport().update()  # Принудительное обновление
            return
        variables = getattr(self._workflow, 'project_variables', {}) or {}
        if not variables:
            self._var_table.blockSignals(False)
            self._var_table.viewport().update()  # Принудительное обновление
            return
        variables = getattr(self._workflow, 'project_variables', {})
        for name, info in variables.items():
            row = self._var_table.rowCount()
            self._var_table.insertRow(row)
            self._var_table.setItem(row, 0, QTableWidgetItem(name))
            # ТЕКУЩЕЕ значение: приоритет value > default
            current_val = str(info.get('value', info.get('default', '')))
            self._var_table.setItem(row, 1, QTableWidgetItem(current_val))
            # Тип — комбобокс
            type_combo = QComboBox()
            for t in ["string", "int", "float", "bool", "list", "json"]:
                type_combo.addItem(t, t)
            idx = type_combo.findData(info.get('type', 'string'))
            type_combo.setCurrentIndex(max(0, idx))
            type_combo.currentIndexChanged.connect(self._on_variable_edited)
            self._var_table.setCellWidget(row, 2, type_combo)
            self._var_table.setItem(row, 3, QTableWidgetItem(str(info.get('default', ''))))
        self._var_table.blockSignals(False)

    def _save_variables_to_workflow(self):
        if not self._workflow:
            return
        variables = {}
        for row in range(self._var_table.rowCount()):
            name_item = self._var_table.item(row, 0)
            value_item = self._var_table.item(row, 1)
            type_widget = self._var_table.cellWidget(row, 2)
            default_item = self._var_table.item(row, 3)
            if not name_item or not name_item.text().strip():
                continue
            var_type = type_widget.currentData() if type_widget else "string"
            variables[name_item.text().strip()] = {
                'value': value_item.text() if value_item else '',
                'type': var_type,
                'default': default_item.text() if default_item else '',
            }
        self._workflow.project_variables = variables
        self.variables_changed.emit()  # <-- ДОБАВИТЬ ЭТУ СТРОКУ

    def _on_variable_edited(self, *_):
        self._save_variables_to_workflow()

    def _add_variable(self):
        self._var_table.blockSignals(True)
        row = self._var_table.rowCount()
        self._var_table.insertRow(row)
        self._var_table.setItem(row, 0, QTableWidgetItem(f"var_{row + 1}"))
        self._var_table.setItem(row, 1, QTableWidgetItem(""))
        type_combo = QComboBox()
        for t in ["string", "int", "float", "bool", "list", "json"]:
            type_combo.addItem(t, t)
        type_combo.currentIndexChanged.connect(self._on_variable_edited)
        self._var_table.setCellWidget(row, 2, type_combo)
        self._var_table.setItem(row, 3, QTableWidgetItem(""))
        self._var_table.blockSignals(False)
        self._var_table.editItem(self._var_table.item(row, 0))
        self._save_variables_to_workflow()

    def _delete_variable(self):
        rows = sorted(set(idx.row() for idx in self._var_table.selectedIndexes()), reverse=True)
        for row in rows:
            self._var_table.removeRow(row)
        self._save_variables_to_workflow()

    def _filter_variables(self, text):
        q = text.lower()
        for row in range(self._var_table.rowCount()):
            name_item = self._var_table.item(row, 0)
            match = not q or (name_item and q in name_item.text().lower())
            self._var_table.setRowHidden(row, not match)

    def _import_variables(self):
        """Импорт переменных из JSON/TXT файла."""
        path, _ = QFileDialog.getOpenFileName(self, "Импорт переменных", "", "JSON (*.json);;Text (*.txt);;All (*)")
        if not path:
            return
        try:
            import json as _json
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            try:
                data = _json.loads(content)
                if isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, dict) and 'value' in val:
                            self._workflow.project_variables[key] = val
                        else:
                            self._workflow.project_variables[key] = {'value': str(val), 'type': 'string', 'default': ''}
                    self._reload_variables()
            except _json.JSONDecodeError:
                # TXT формат: key=value построчно
                for line in content.splitlines():
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, val = line.split('=', 1)
                        self._workflow.project_variables[key.strip()] = {'value': val.strip(), 'type': 'string', 'default': ''}
                self._reload_variables()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось импортировать: {e}")

    # ── Заметки ──────────────────────────────────

    def _reload_notes(self):
        self._notes_list.clear()
        if not self._workflow:
            return
        notes = getattr(self._workflow, 'project_notes', [])
        for note in notes:
            item = QListWidgetItem(f"📝 {note.get('title', 'Без названия')}")
            item.setData(Qt.ItemDataRole.UserRole, note.get('id', ''))
            color = note.get('color', '')
            if color:
                item.setForeground(QColor(color))
            item.setToolTip(note.get('content', '')[:200])
            self._notes_list.addItem(item)

    def _add_note(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        import uuid
        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("Новая заметка"))
        dlg.setMinimumWidth(400)
        lay = QVBoxLayout(dlg)

        fld_title = QLineEdit()
        fld_title.setPlaceholderText("Заголовок...")
        lay.addWidget(fld_title)

        fld_content = QTextEdit()
        fld_content.setPlaceholderText("Текст заметки...")
        lay.addWidget(fld_content)

        # Цвет
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Цвет:"))
        color_btn = QPushButton("🎨 Выбрать")
        _selected_color = ["#CDD6F4"]
        def pick_color():
            c = QColorDialog.getColor(QColor(_selected_color[0]), dlg)
            if c.isValid():
                _selected_color[0] = c.name()
                color_btn.setStyleSheet(f"background: {c.name()};")
        color_btn.clicked.connect(pick_color)
        color_row.addWidget(color_btn)
        lay.addLayout(color_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted and fld_title.text().strip():
            from datetime import datetime
            note = {
                'id': str(uuid.uuid4())[:8],
                'title': fld_title.text().strip(),
                'content': fld_content.toPlainText(),
                'color': _selected_color[0],
                'created_at': datetime.now().isoformat(),
            }
            if not hasattr(self._workflow, 'project_notes'):
                self._workflow.project_notes = []
            self._workflow.project_notes.append(note)
            self._reload_notes()

    def _edit_note(self, item):
        note_id = item.data(Qt.ItemDataRole.UserRole)
        notes = getattr(self._workflow, 'project_notes', [])
        note = next((n for n in notes if n.get('id') == note_id), None)
        if not note:
            return
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("Заметка: {0}").format(note['title']))
        dlg.setMinimumWidth(400)
        lay = QVBoxLayout(dlg)
        fld_title = QLineEdit(note['title'])
        lay.addWidget(fld_title)
        fld_content = QTextEdit()
        fld_content.setPlainText(note.get('content', ''))
        lay.addWidget(fld_content)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            note['title'] = fld_title.text()
            note['content'] = fld_content.toPlainText()
            self._reload_notes()

    def _note_context_menu(self, position):
        item = self._notes_list.itemAt(position)
        if not item:
            return
        menu = QMenu(self)
        act_edit = menu.addAction(self.tr("✏️ Редактировать"))
        act_edit.triggered.connect(lambda: self._edit_note(item))
        act_del = menu.addAction(self.tr("🗑️ Удалить"))
        note_id = item.data(Qt.ItemDataRole.UserRole)
        act_del.triggered.connect(lambda: self._delete_note(note_id))
        menu.exec(self._notes_list.mapToGlobal(position))

    def _delete_note(self, note_id):
        notes = getattr(self._workflow, 'project_notes', [])
        self._workflow.project_notes = [n for n in notes if n.get('id') != note_id]
        self._reload_notes()
    
    # ══════════════════════════════════════════════════════════
    #  СПИСКИ И ТАБЛИЦЫ ПРОЕКТА (ZennoPoster-style)
    # ══════════════════════════════════════════════════════════

    def _build_lists_tables_tab(self) -> QWidget:
        """Вкладка управления списками и таблицами проекта."""
        import uuid as _uuid
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        sub_tabs = QTabWidget()
        sub_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._lists_tables_sub_tabs = sub_tabs
        sub_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ background: {get_color('bg1')}; border: 1px solid {get_color('bd2')}; }}
            QTabBar::tab {{ background: {get_color('bg2')}; color: {get_color('tx1')}; padding: 4px 10px; }}
            QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}
        """)

        sub_tabs.addTab(self._build_lists_sub_tab(), tr("📃 Списки"))
        sub_tabs.addTab(self._build_tables_sub_tab(), tr("📊 Таблицы"))

        lay.addWidget(sub_tabs)
        return w

    # ─── СПИСКИ ───────────────────────────────────────────────

    def _build_lists_sub_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)

        # Кнопки управления
        btn_row = QHBoxLayout()
        btn_add_list = QPushButton(tr("➕ Добавить список"))
        btn_add_list.setStyleSheet(
            f"QPushButton {{ background: {get_color('bg2')}; color: #9ECE6A; "
            f"border: 1px solid #9ECE6A; border-radius: 4px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: #9ECE6A; color: #000; }}"
        )
        btn_add_list.clicked.connect(self._add_project_list)
        btn_del_list = QPushButton(tr("🗑 Удалить"))
        btn_del_list.setStyleSheet(
            f"QPushButton {{ background: {get_color('bg2')}; color: #F7768E; "
            f"border: 1px solid #F7768E; border-radius: 4px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: #F7768E; color: #000; }}"
        )
        btn_del_list.clicked.connect(self._del_project_list)
        btn_edit_list = QPushButton(tr("✏ Открыть"))
        btn_edit_list.clicked.connect(self._edit_project_list)
        btn_row.addWidget(btn_add_list)
        btn_row.addWidget(btn_edit_list)
        btn_row.addWidget(btn_del_list)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Список проектных списков
        self._lists_widget = QListWidget()
        self._lists_widget.setStyleSheet(
            f"QListWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; "
            f"border: 1px solid {get_color('bd2')}; }}"
            f"QListWidget::item {{ padding: 5px; border-bottom: 1px solid {get_color('bg3')}; }}"
            f"QListWidget::item:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}"
        )
        self._lists_widget.itemDoubleClicked.connect(self._edit_project_list)
        lay.addWidget(self._lists_widget)

        # Быстрый просмотр содержимого
        lbl_prev = QLabel(tr("Содержимое:"))
        lbl_prev.setStyleSheet("color: #565f89; font-size: 10px;")
        lay.addWidget(lbl_prev)
        self._list_preview = QPlainTextEdit()
        self._list_preview.setReadOnly(True)
        self._list_preview.setMaximumHeight(80)
        self._list_preview.setStyleSheet(
            f"QPlainTextEdit {{ background: {get_color('bg0')}; color: #9ECE6A; "
            f"font-size: 10px; border: 1px solid {get_color('bd2')}; }}"
        )
        self._lists_widget.currentRowChanged.connect(self._on_list_selected)
        lay.addWidget(self._list_preview)

        return w

    def _build_tables_sub_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)

        btn_row = QHBoxLayout()
        btn_add_tbl = QPushButton(tr("➕ Добавить таблицу"))
        btn_add_tbl.setStyleSheet(
            f"QPushButton {{ background: {get_color('bg2')}; color: #7AA2F7; "
            f"border: 1px solid #7AA2F7; border-radius: 4px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: #7AA2F7; color: #000; }}"
        )
        btn_add_tbl.clicked.connect(self._add_project_table)
        btn_del_tbl = QPushButton(tr("🗑 Удалить"))
        btn_del_tbl.setStyleSheet(
            f"QPushButton {{ background: {get_color('bg2')}; color: #F7768E; "
            f"border: 1px solid #F7768E; border-radius: 4px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: #F7768E; color: #000; }}"
        )
        btn_del_tbl.clicked.connect(self._del_project_table)
        btn_edit_tbl = QPushButton(tr("✏ Открыть"))
        btn_edit_tbl.clicked.connect(self._edit_project_table)
        btn_row.addWidget(btn_add_tbl)
        btn_row.addWidget(btn_edit_tbl)
        btn_row.addWidget(btn_del_tbl)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._tables_widget = QListWidget()
        self._tables_widget.setStyleSheet(
            f"QListWidget {{ background: {get_color('bg1')}; color: {get_color('tx0')}; "
            f"border: 1px solid {get_color('bd2')}; }}"
            f"QListWidget::item {{ padding: 5px; border-bottom: 1px solid {get_color('bg3')}; }}"
            f"QListWidget::item:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}"
        )
        self._tables_widget.itemDoubleClicked.connect(self._edit_project_table)
        lay.addWidget(self._tables_widget)

        lbl_prev = QLabel(tr("Предпросмотр:"))
        lbl_prev.setStyleSheet("color: #565f89; font-size: 10px;")
        lay.addWidget(lbl_prev)
        self._table_preview = QTableWidget(0, 1)
        self._table_preview.setMaximumHeight(80)
        self._table_preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_preview.setStyleSheet(
            f"QTableWidget {{ background: {get_color('bg0')}; color: {get_color('ac')}; "
            f"font-size: 10px; gridline-color: {get_color('bd2')}; }}"
            f"QHeaderView::section {{ background: {get_color('bg2')}; color: {get_color('tx1')}; "
            f"border: 1px solid {get_color('bd2')}; }}"
        )
        self._tables_widget.currentRowChanged.connect(self._on_table_selected)
        lay.addWidget(self._table_preview)

        return w

    # ─── Операции со списками ─────────────────────────────────

    def _add_project_list(self):
        import uuid as _uuid
        lst = {
            'id': str(_uuid.uuid4())[:8],
            'name': f'Список {len(self._project_lists)+1}',
            'items': [],
            'file_path': '',
            'load_mode': 'static',   # static | on_start | always
            'encoding': 'utf-8',
            'save_contents': True,   # Сохранять содержимое в файле проекта
        }
        self._project_lists.append(lst)
        self._refresh_lists_widget()
        self._lists_widget.setCurrentRow(len(self._project_lists) - 1)
        self._save_lists_tables_to_workflow()
        self._edit_project_list()

    def _del_project_list(self):
        row = self._lists_widget.currentRow()
        if row < 0 or row >= len(self._project_lists):
            return
        name = self._project_lists[row]['name']
        if QMessageBox.question(self, tr("Удалить список"),
                                tr(f"Удалить список «{name}»?"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            self._project_lists.pop(row)
            self._refresh_lists_widget()
            self._save_lists_tables_to_workflow()

    def _edit_project_list(self):
        row = self._lists_widget.currentRow()
        if row < 0 or row >= len(self._project_lists):
            return
        lst = self._project_lists[row]
        dlg = ProjectListEditDialog(lst, self)
        if dlg.exec():
            self._project_lists[row] = dlg.get_data()
            self._refresh_lists_widget()
            self._on_list_selected(row)
            self._save_lists_tables_to_workflow()

    def _refresh_lists_widget(self):
        self._lists_widget.clear()
        for lst in self._project_lists:
            count = len(lst.get('items', []))
            # ═══ Если items пуст но есть файл — показать count из файла ═══
            if count == 0 and lst.get('file_path') and lst.get('load_mode') in ('on_start', 'always'):
                try:
                    with open(lst['file_path'], 'r', encoding=lst.get('encoding', 'utf-8') or 'utf-8', errors='replace') as f:
                        count = sum(1 for line in f if line.strip())
                except Exception:
                    pass
            mode_icons = {'static': '📝', 'on_start': '🔄', 'always': '♻️'}
            icon = mode_icons.get(lst.get('load_mode', 'static'), '📝')
            fp = lst.get('file_path', '')
            file_hint = f"  📄 {fp[:30]}" if fp else ""
            self._lists_widget.addItem(
                f"{icon}  {lst['name']}  [{count} {tr('строк')}]{file_hint}"
            )

    def _on_list_selected(self, row: int):
        if row < 0 or row >= len(self._project_lists):
            self._list_preview.setPlainText("")
            return
        lst = self._project_lists[row]
        items = lst.get('items', [])
        # ═══ Если items пуст, но есть файл — загрузить оттуда ═══
        if not items and lst.get('file_path') and lst.get('load_mode') in ('on_start', 'always'):
            try:
                fp = lst['file_path']
                enc = lst.get('encoding', 'utf-8') or 'utf-8'
                with open(fp, 'r', encoding=enc, errors='replace') as f:
                    items = [line.rstrip('\n\r') for line in f if line.strip()]
                lst['items'] = items
            except Exception:
                pass
        preview = '\n'.join(items[:20])
        if len(items) > 20:
            preview += f"\n... (+{len(items)-20} {tr('строк')})"
        self._list_preview.setPlainText(preview)

    # ─── Операции с таблицами ─────────────────────────────────

    def _add_project_table(self):
        import uuid as _uuid
        tbl = {
            'id': str(_uuid.uuid4())[:8],
            'name': f'Таблица {len(self._project_tables)+1}',
            'columns': ['Колонка 1'],
            'rows': [],
            'file_path': '',
            'load_mode': 'static',
            'has_header': True,
            'encoding': 'utf-8',
            'save_contents': True,   # Сохранять содержимое в файле проекта
        }
        self._project_tables.append(tbl)
        self._refresh_tables_widget()
        self._tables_widget.setCurrentRow(len(self._project_tables) - 1)
        self._save_lists_tables_to_workflow()
        self._edit_project_table()

    def _del_project_table(self):
        row = self._tables_widget.currentRow()
        if row < 0 or row >= len(self._project_tables):
            return
        name = self._project_tables[row]['name']
        if QMessageBox.question(self, tr("Удалить таблицу"),
                                tr(f"Удалить таблицу «{name}»?"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            self._project_tables.pop(row)
            self._refresh_tables_widget()
            self._save_lists_tables_to_workflow()

    def _edit_project_table(self):
        row = self._tables_widget.currentRow()
        if row < 0 or row >= len(self._project_tables):
            return
        tbl = self._project_tables[row]
        dlg = ProjectTableEditDialog(tbl, self)
        if dlg.exec():
            self._project_tables[row] = dlg.get_data()
            self._refresh_tables_widget()
            self._on_table_selected(row)
            self._save_lists_tables_to_workflow()

    def _refresh_tables_widget(self):
        self._tables_widget.clear()
        for tbl in self._project_tables:
            cols = len(tbl.get('columns', []))
            rows = len(tbl.get('rows', []))
            mode_icons = {'static': '📝', 'on_start': '🔄', 'always': '♻️'}
            icon = mode_icons.get(tbl.get('load_mode', 'static'), '📝')
            fp = tbl.get('file_path', '')
            file_hint = f"  📄 {fp[:25]}" if fp else ""
            self._tables_widget.addItem(
                f"{icon}  {tbl['name']}  [{rows}{tr('р')} × {cols}{tr('к')}]{file_hint}"
            )

    def _on_table_selected(self, row: int):
        if row < 0 or row >= len(self._project_tables):
            self._table_preview.setRowCount(0)
            self._table_preview.setColumnCount(1)
            return
        tbl = self._project_tables[row]
        # ═══ Если rows пуст, но есть файл — загрузить оттуда ═══
        if not tbl.get('rows') and tbl.get('file_path') and tbl.get('load_mode') in ('on_start', 'always'):
            try:
                import csv
                fp = tbl['file_path']
                enc = tbl.get('encoding', 'utf-8') or 'utf-8'
                with open(fp, 'r', encoding=enc, errors='replace') as f:
                    reader = csv.reader(f)
                    all_rows = list(reader)
                if tbl.get('has_header') and all_rows:
                    tbl['columns'] = all_rows[0]
                    all_rows = all_rows[1:]
                tbl['rows'] = all_rows
            except Exception:
                pass
        cols = tbl.get('columns', [''])
        rows = tbl.get('rows', [])
        self._table_preview.setColumnCount(len(cols))
        self._table_preview.setHorizontalHeaderLabels(cols)
        preview_rows = rows[:5]
        self._table_preview.setRowCount(len(preview_rows))
        for r, row_data in enumerate(preview_rows):
            for c, cell in enumerate(row_data[:len(cols)]):
                self._table_preview.setItem(r, c, QTableWidgetItem(str(cell)))
        self._table_preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)

    # ─── Сохранение/загрузка в workflow ──────────────────────

    def _save_lists_tables_to_workflow(self):
        if not self._workflow:
            return
        if not hasattr(self._workflow, 'metadata') or self._workflow.metadata is None:
            self._workflow.metadata = {}
        import copy
        
        # ═══ Списки: не сохраняем items если save_contents=False ═══
        lists_to_save = []
        for lst in self._project_lists:
            lst_copy = copy.deepcopy(lst)
            if not lst_copy.get('save_contents', True):
                lst_copy['items'] = []  # Не хранить в проекте — подгрузятся из файла
            lists_to_save.append(lst_copy)
        
        # ═══ Таблицы: не сохраняем rows если save_contents=False ═══
        tables_to_save = []
        for tbl in self._project_tables:
            tbl_copy = copy.deepcopy(tbl)
            if not tbl_copy.get('save_contents', True):
                tbl_copy['rows'] = []  # Не хранить в проекте — подгрузятся из файла
            # Гарантируем что columns и rows — это списки, а не None
            if not isinstance(tbl_copy.get('columns'), list):
                tbl_copy['columns'] = []
            if not isinstance(tbl_copy.get('rows'), list):
                tbl_copy['rows'] = []
            tables_to_save.append(tbl_copy)
        
        self._workflow.metadata['project_lists'] = lists_to_save
        self._workflow.metadata['project_tables'] = tables_to_save
        # ═══ Сохраняем настройки проекта и БД ═══
        if hasattr(self, '_project_input_settings'):
            self._workflow.metadata['project_input_settings'] = self._project_input_settings
        if hasattr(self, '_project_databases'):
            self._workflow.metadata['project_databases'] = self._project_databases
        self.variables_changed.emit()

    def _load_lists_tables_from_workflow(self):
        if not self._workflow:
            self._project_lists = []
            self._project_tables = []
            if hasattr(self, '_lists_widget'):
                self._lists_widget.clear()
                self._list_preview.setPlainText("")
            if hasattr(self, '_tables_widget'):
                self._tables_widget.clear()
                self._table_preview.setRowCount(0)
                self._table_preview.setColumnCount(1)
            return
        meta = getattr(self._workflow, 'metadata', {}) or {}
        import copy
        self._project_lists = copy.deepcopy(meta.get('project_lists', []))
        self._project_tables = copy.deepcopy(meta.get('project_tables', []))
        # ═══ Восстанавливаем настройки проекта и БД ═══
        self._project_input_settings = copy.deepcopy(meta.get('project_input_settings', []))
        self._project_databases = copy.deepcopy(meta.get('project_databases', []))
        if hasattr(self, '_lists_widget'):
            self._lists_widget.blockSignals(True)
            self._lists_widget.clear()
            self._refresh_lists_widget()
            self._list_preview.setPlainText("")
            self._lists_widget.setCurrentRow(-1)
            self._lists_widget.blockSignals(False)
            self._lists_widget.update()
        if hasattr(self, '_tables_widget'):
            self._tables_widget.blockSignals(True)
            self._tables_widget.clear()
            self._refresh_tables_widget()
            self._table_preview.setRowCount(0)
            self._table_preview.setColumnCount(1)
            self._tables_widget.setCurrentRow(-1)
            self._tables_widget.blockSignals(False)
            self._tables_widget.update()
            self._table_preview.update()
        # Принудительный перерендер скрытых вкладок
        if hasattr(self, '_lists_tables_sub_tabs'):
            self._lists_tables_sub_tabs.update()
        if hasattr(self, '_tabs'):
            self._tabs.update()

    def get_project_lists(self) -> list:
        """Вернуть все списки проекта (для runtime и сниппетов)."""
        return self._project_lists

    def get_project_tables(self) -> list:
        """Вернуть все таблицы проекта (для runtime и сниппетов)."""
        return self._project_tables

    def get_list_items(self, list_name: str, resolve_vars_fn=None) -> list:
        """Получить строки списка по имени; если load_mode=always — перечитать файл."""
        for lst in self._project_lists:
            if lst['name'] == list_name:
                if lst.get('load_mode') == 'always' and lst.get('file_path'):
                    fp = lst['file_path']
                    if resolve_vars_fn:
                        fp = resolve_vars_fn(fp)
                    try:
                        with open(fp, 'r', encoding=lst.get('encoding', 'utf-8')) as f:
                            return [line.rstrip('\n') for line in f if line.strip()]
                    except Exception:
                        pass
                return list(lst.get('items', []))
        return []

    def get_table_rows(self, table_name: str, resolve_vars_fn=None) -> list:
        """Получить строки таблицы по имени; если load_mode=always — перечитать файл."""
        for tbl in self._project_tables:
            if tbl['name'] == table_name:
                if tbl.get('load_mode') == 'always' and tbl.get('file_path'):
                    fp = tbl['file_path']
                    if resolve_vars_fn:
                        fp = resolve_vars_fn(fp)
                    try:
                        import csv
                        with open(fp, 'r', encoding=tbl.get('encoding', 'utf-8')) as f:
                            reader = csv.reader(f)
                            rows = list(reader)
                        if tbl.get('has_header') and rows:
                            rows = rows[1:]
                        return rows
                    except Exception:
                        pass
                return list(tbl.get('rows', []))
        return []
    
    def get_variables_for_context(self) -> dict:
        """Получить переменные для подстановки в контексте выполнения.
        Берём ТЕКУЩИЕ значения из таблицы UI (колонка Значение), а не из модели.
        Включает глобальные переменные из metadata['global_variables'].
        """
        if not self._workflow:
            return {}
        result = {}
        # Сначала читаем актуальные значения прямо из таблицы UI
        ui_values = {}
        for row in range(self._var_table.rowCount()):
            name_item = self._var_table.item(row, 0)
            value_item = self._var_table.item(row, 1)
            if name_item and name_item.text().strip():
                ui_values[name_item.text().strip()] = value_item.text() if value_item else ''

        for name, info in getattr(self._workflow, 'project_variables', {}).items():
            val = ui_values.get(name, info.get('value', info.get('default', '')))
            var_type = info.get('type', 'string')
            try:
                if var_type == 'int':
                    val = int(val) if val else 0
                elif var_type == 'float':
                    val = float(val) if val else 0.0
                elif var_type == 'bool':
                    val = val.lower() in ('true', '1', 'yes') if isinstance(val, str) else bool(val)
                elif var_type in ('list', 'json'):
                    import json as _json
                    val = _json.loads(val) if val else ([] if var_type == 'list' else {})
            except Exception:
                pass
            result[name] = val

        # ── Добавляем глобальные переменные из metadata (приоритет: UI таблица > metadata) ──
        _meta = getattr(self._workflow, 'metadata', {}) or {}
        if isinstance(_meta, dict):
            # Читаем актуальные значения из UI таблицы глобальных переменных
            _global_ui = {}
            if hasattr(self, '_global_var_table'):
                for _r in range(self._global_var_table.rowCount()):
                    _n = self._global_var_table.item(_r, 0)
                    _v = self._global_var_table.item(_r, 1)
                    if _n and _n.text().strip():
                        _global_ui[_n.text().strip()] = _v.text() if _v else ''
            for gv in _meta.get('global_variables', []):
                if not isinstance(gv, dict):
                    continue
                gname = gv.get('name', '').strip()
                if not gname:
                    continue
                gval = _global_ui.get(gname, gv.get('value', gv.get('default', '')))
                result[gname] = gval   # глобальные не перетирают уже вычисленные project vars
        return result
    
    def reset_variables_to_defaults(self):
        """Сбросить все значения переменных к колонке 'По умолч.'
        Вызывается при открытии проекта и перед каждым новым запуском.
        """
        if not self._workflow:
            return
        variables = getattr(self._workflow, 'project_variables', {})
        # Сбрасываем в модели value = default
        for name, info in variables.items():
            info['value'] = info.get('default', '')
        # Синхронизируем таблицу локальных переменных
        self._var_table.blockSignals(True)
        for row in range(self._var_table.rowCount()):
            name_item = self._var_table.item(row, 0)
            if not name_item:
                continue
            name = name_item.text().strip()
            if name in variables:
                default_val = variables[name].get('default', '')
                value_item = self._var_table.item(row, 1)
                if value_item:
                    value_item.setText(str(default_val))
        self._var_table.blockSignals(False)
        if variables:
            self._save_variables_to_workflow()
        # Сбрасываем глобальные переменные к дефолту
        self._reset_global_vars_to_defaults()

    def _reset_global_vars_to_defaults(self):
        """Сбросить глобальные переменные к значениям по умолчанию."""
        if not self._workflow or not hasattr(self, '_global_var_table'):
            return
        meta = getattr(self._workflow, 'metadata', {}) or {}
        if not isinstance(meta, dict):
            return
        gvars = meta.get('global_variables', [])
        self._global_var_table.blockSignals(True)
        for i, gv in enumerate(gvars):
            if not isinstance(gv, dict):
                continue
            default_val = gv.get('default', '')
            gv['value'] = default_val  # сброс в модели
            if i < self._global_var_table.rowCount():
                val_item = self._global_var_table.item(i, 1)
                if val_item:
                    val_item.setText(str(default_val))
        self._global_var_table.blockSignals(False)
        # Сохраняем обновлённое состояние
        meta['global_variables'] = gvars
        self._workflow.metadata = meta  
    
    def get_variables(self) -> dict:
        """Получить все переменные в формате {name: {...}}, включая глобальные."""
        result = {}
        if hasattr(self, '_workflow') and self._workflow:
            if hasattr(self._workflow, 'project_variables'):
                result = self._workflow.project_variables.copy()
            # Добавляем глобальные переменные из metadata
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            if isinstance(_meta, dict):
                for gv in _meta.get('global_variables', []):
                    if not isinstance(gv, dict):
                        continue
                    gname = gv.get('name', '').strip()
                    if gname and gname not in result:
                        result[gname] = {
                            'value':   gv.get('value', gv.get('default', '')),
                            'type':    'string',
                            'default': gv.get('default', ''),
                            'description': '🌍 global',
                        }
            return result
        # Или собираем из таблицы
        if hasattr(self, '_var_table'):
            for row in range(self._var_table.rowCount()):
                name_item = self._var_table.item(row, 0)
                value_item = self._var_table.item(row, 1)
                type_item = self._var_table.cellWidget(row, 2) if self._var_table.columnCount() > 2 else None
                
                if name_item:
                    name = name_item.text().strip()
                    value = value_item.text() if value_item else ''
                    var_type = type_item.currentText() if type_item else 'string'
                    result[name] = {'value': value, 'type': var_type}
        return result
    
    def _run_regex_test(self):
        """Запустить тест регулярного выражения."""
        import re
        text = self._regex_input.toPlainText()
        pattern = self._regex_pattern.text()
        
        if not pattern:
            self._regex_result.setPlainText("⚠ Введите регулярное выражение")
            return
        
        flags = 0
        if self._regex_chk_ignorecase.isChecked():
            flags |= re.IGNORECASE
        if self._regex_chk_dotall.isChecked():
            flags |= re.DOTALL
        if self._regex_chk_multiline.isChecked():
            flags |= re.MULTILINE
        
        p = pattern
        if self._regex_chk_shortest.isChecked():
            p = re.sub(r'(?<!\\)\*(?!\?)', '*?', p)
            p = re.sub(r'(?<!\\)\+(?!\?)', '+?', p)
        
        try:
            matches = re.findall(p, text, flags)
            
            if not matches:
                self._regex_result.setPlainText("❌ Совпадений не найдено")
                self._regex_status.setText("0 совпадений")
                return
            
            lines = []
            for i, m in enumerate(matches):
                if isinstance(m, tuple):
                    groups = ' | '.join(str(g) for g in m)
                    lines.append(f"[{i}] {groups}")
                else:
                    lines.append(f"[{i}] {m}")
            
            self._regex_result.setPlainText('\n'.join(lines))
            self._regex_status.setText(f"✅ {len(matches)} совпадений | Regex: {p}")
            
        except re.error as e:
            self._regex_result.setPlainText(f"⚠ Ошибка в regex: {e}")
            self._regex_status.setText(f"❌ Ошибка: {e}")

    def _build_regex_from_helper(self):
        """Собрать regex из полей помощника (4 поля как в ZennoPoster)."""
        import re as _re
        before = self._regex_before.text().strip()  # lookbehind — НЕ в результате
        after = self._regex_after.text().strip()      # lookahead — НЕ в результате
        starts = getattr(self, '_regex_starts', None)
        starts = starts.text().strip() if starts else ''  # начало — В результате
        ends = getattr(self, '_regex_ends', None)
        ends = ends.text().strip() if ends else ''    # конец — В результате
        
        parts = []
        
        # Lookbehind: перед искомым всегда есть (не включается)
        if before:
            parts.append(f"(?<={_re.escape(before)})")
        
        # Начало искомого текста (включается в результат)
        if starts:
            parts.append(_re.escape(starts))
        
        # Середина — любые символы
        parts.append(".*")
        
        # Конец искомого текста (включается в результат)
        if ends:
            parts.append(_re.escape(ends))
        
        # Lookahead: после искомого всегда есть (не включается)
        if after:
            parts.append(f"(?={_re.escape(after)})")
        
        result = ''.join(parts)
        self._regex_pattern.setText(result)
        
        # Подсказка что получилось
        explanation = []
        if before: explanation.append(f"после «{before}»")
        if starts: explanation.append(f"начинается с «{starts}»")
        explanation.append("любой текст")
        if ends: explanation.append(f"заканчивается на «{ends}»")
        if after: explanation.append(f"перед «{after}»")
        self._regex_status.setText(f"🔨 Собрано: {' → '.join(explanation)}")
    
    # ══════════════════════════════════════════════════════
    #  JS ТЕСТЕР
    # ══════════════════════════════════════════════════════

    def _build_js_tester_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)

        lbl_info = QLabel(tr(
            "Проверка JS-кода локального выполнения. "
            "Тестер покажет результат и готовый фрагмент для вставки в сниппет."
        ))
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #7AA2F7; font-size: 11px; padding-bottom: 4px;")
        lay.addWidget(lbl_info)

        # Редактор кода
        lay.addWidget(QLabel(tr("1. Код для проверки:")))
        self._js_editor = QPlainTextEdit()
        self._js_editor.setPlaceholderText("// ваш JavaScript\nreturn 'hello';")
        self._js_editor.setStyleSheet(
            f"font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px;"
        )
        self._js_editor.setMinimumHeight(120)
        lay.addWidget(self._js_editor)

        # Режим вставки
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("2. Формат для экшена JS:")))
        self._js_mode_combo = QComboBox()
        self._js_mode_combo.addItem(tr("Как есть (raw)"), "raw")
        self._js_mode_combo.addItem(tr("Одна строка (escaped)"), "oneline")
        self._js_mode_combo.addItem(tr("Base64"), "base64")
        row.addWidget(self._js_mode_combo)
        lay.addLayout(row)

        # Кнопка теста
        btn_row = QHBoxLayout()
        self._js_btn_test = QPushButton(tr("▶ Тест"))
        self._js_btn_test.clicked.connect(self._run_js_test)
        btn_row.addWidget(self._js_btn_test)
        self._js_btn_copy = QPushButton(tr("📋 Копировать для вставки"))
        self._js_btn_copy.clicked.connect(self._copy_js_for_snippet)
        btn_row.addWidget(self._js_btn_copy)
        lay.addLayout(btn_row)

        # Результат
        lay.addWidget(QLabel(tr("3. Результат выполнения:")))
        self._js_result = QPlainTextEdit()
        self._js_result.setReadOnly(True)
        self._js_result.setMaximumHeight(80)
        lay.addWidget(self._js_result)

        lay.addStretch()
        return w

    def _run_js_test(self):
        """Выполнить JS через subprocess node.js или встроенный движок."""
        import subprocess, shutil
        code = self._js_editor.toPlainText().strip()
        if not code:
            self._js_result.setPlainText(tr("Нет кода для выполнения."))
            return

        wrapped = f"(function(){{\n{code}\n}})();"
        node_bin = shutil.which("node")
        if node_bin:
            try:
                r = subprocess.run(
                    [node_bin, "-e", f"console.log({wrapped})"],
                    capture_output=True, text=True, timeout=5
                )
                out = r.stdout.strip() or r.stderr.strip() or "(нет вывода)"
                self._js_result.setPlainText(out)
            except Exception as e:
                self._js_result.setPlainText(f"Ошибка: {e}")
        else:
            self._js_result.setPlainText(
                tr("Node.js не найден. Установите node.js для выполнения JS-кода.")
            )

    def _copy_js_for_snippet(self):
        """Скопировать JS в буфер в выбранном формате."""
        import base64 as _b64
        code = self._js_editor.toPlainText().strip()
        mode = self._js_mode_combo.currentData()
        if mode == "oneline":
            result = code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        elif mode == "base64":
            result = _b64.b64encode(code.encode()).decode()
        else:
            result = code
        QApplication.clipboard().setText(result)

    # ══════════════════════════════════════════════════════
    #  X/JSON PATH ТЕСТЕР
    # ══════════════════════════════════════════════════════

    def _build_xjson_tester_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)

        lbl_info = QLabel(tr(
            "Проверка XPath и JSONPath выражений. "
            "Вставьте XML/JSON в поле Данные, введите выражение и нажмите Тест."
        ))
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #7AA2F7; font-size: 11px; padding-bottom: 4px;")
        lay.addWidget(lbl_info)

        # Выбор режима
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("Режим:")))
        self._xj_mode = QComboBox()
        self._xj_mode.addItem("JSONPath", "jsonpath")
        self._xj_mode.addItem("XPath", "xpath")
        mode_row.addWidget(self._xj_mode)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # Данные
        lay.addWidget(QLabel(tr("1. Данные (XML / JSON):")))
        self._xj_data = QPlainTextEdit()
        self._xj_data.setPlaceholderText('{"store": {"book": [{"title": "Moby Dick"}]}}')
        self._xj_data.setMinimumHeight(100)
        self._xj_data.setStyleSheet(
            "font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11px;"
        )
        lay.addWidget(self._xj_data)

        # Выражение
        expr_row = QHBoxLayout()
        expr_row.addWidget(QLabel(tr("2. Выражение:")))
        self._xj_expr = QLineEdit()
        self._xj_expr.setPlaceholderText("$.store.book[*].title")
        expr_row.addWidget(self._xj_expr)
        lay.addLayout(expr_row)

        # Кнопки
        btn_row = QHBoxLayout()
        self._xj_btn_test = QPushButton(tr("▶ Тест"))
        self._xj_btn_test.clicked.connect(self._run_xjson_test)
        btn_row.addWidget(self._xj_btn_test)
        self._xj_btn_beautify = QPushButton(tr("✨ Beautify"))
        self._xj_btn_beautify.clicked.connect(self._beautify_xjson_data)
        btn_row.addWidget(self._xj_btn_beautify)
        lay.addLayout(btn_row)

        # Результат
        lay.addWidget(QLabel(tr("3. Результат:")))
        self._xj_result = QPlainTextEdit()
        self._xj_result.setReadOnly(True)
        self._xj_result.setMaximumHeight(90)
        lay.addWidget(self._xj_result)

        lay.addStretch()
        return w

    def _run_xjson_test(self):
        mode = self._xj_mode.currentData()
        raw = self._xj_data.toPlainText().strip()
        expr = self._xj_expr.text().strip()
        if not raw or not expr:
            self._xj_result.setPlainText(tr("Заполните Данные и Выражение."))
            return
        try:
            if mode == "jsonpath":
                import json as _json
                try:
                    from jsonpath_ng import parse as jp_parse
                    data = _json.loads(raw)
                    matches = [m.value for m in jp_parse(expr).find(data)]
                    self._xj_result.setPlainText(_json.dumps(matches, ensure_ascii=False, indent=2))
                except ImportError:
                    self._xj_result.setPlainText(
                        tr("Установите: pip install jsonpath-ng") + "\n\n"
                        + tr("Или используйте режим XPath для XML.")
                    )
            else:
                # XPath
                try:
                    from lxml import etree
                    root = etree.fromstring(raw.encode())
                    results = root.xpath(expr)
                    out = []
                    for r in results:
                        if isinstance(r, etree._Element):
                            out.append(etree.tostring(r, encoding='unicode'))
                        else:
                            out.append(str(r))
                    self._xj_result.setPlainText("\n".join(out) if out else tr("(нет совпадений)"))
                except ImportError:
                    self._xj_result.setPlainText(tr("Установите: pip install lxml"))
        except Exception as e:
            self._xj_result.setPlainText(f"Ошибка: {e}")

    def _beautify_xjson_data(self):
        raw = self._xj_data.toPlainText().strip()
        mode = self._xj_mode.currentData()
        try:
            if mode == "jsonpath":
                import json as _json
                data = _json.loads(raw)
                self._xj_data.setPlainText(_json.dumps(data, ensure_ascii=False, indent=2))
            else:
                from lxml import etree
                root = etree.fromstring(raw.encode())
                self._xj_data.setPlainText(
                    etree.tostring(root, pretty_print=True, encoding='unicode')
                )
        except Exception as e:
            self._xj_result.setPlainText(f"Beautify error: {e}")
    
    def _regex_to_snippet_field(self):
        """Вставить regex из тестера в поле 'pattern' текущего сниппета."""
        pattern = self._regex_pattern.text()
        if not pattern:
            return
        # Ищем главное окно через parent()
        mw = self.parent()
        while mw and not isinstance(mw, QMainWindow):
            mw = mw.parent()
        if mw and hasattr(mw, '_snippet_widgets'):
            w = mw._snippet_widgets.get('pattern')
            if w and isinstance(w, QLineEdit):
                w.setText(pattern)
                if hasattr(mw, '_log_msg'):
                    mw._log_msg(f"🔍 Regex вставлен в поле сниппета: {pattern[:60]}")
                return
        QApplication.clipboard().setText(pattern)
        
# ══════════════════════════════════════════════════════════
#  ДИАЛОГ РЕДАКТИРОВАНИЯ СПИСКА
# ══════════════════════════════════════════════════════════

class ProjectListEditDialog(QDialog):
    """Диалог редактирования проектного списка."""

    def __init__(self, lst: dict, parent=None):
        super().__init__(parent)
        import copy
        self._data = copy.deepcopy(lst)
        self.setWindowTitle(f"{tr('📃 Список')}: {lst.get('name', '')}")
        self.resize(600, 550)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        from PyQt6.QtWidgets import QDialogButtonBox
        lay = QVBoxLayout(self)

        # Имя
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Имя:")))
        self._name = QLineEdit()
        row.addWidget(self._name)
        lay.addLayout(row)

        # Файл
        grp_file = QGroupBox(tr("Источник файла (необязательно)"))
        gl = QFormLayout(grp_file)

        fp_row = QHBoxLayout()
        self._file_path = QLineEdit()
        self._file_path.setPlaceholderText(tr("Путь к файлу (поддерживает {переменные})"))
        btn_browse = QPushButton("📂")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_file)
        fp_row.addWidget(self._file_path)
        fp_row.addWidget(btn_browse)
        gl.addRow(tr("Путь к файлу:"), fp_row)

        self._load_mode = QComboBox()
        self._load_mode.addItem(tr("📝 Статически (только ручной ввод)"), "static")
        self._load_mode.addItem(tr("🔄 Загрузить из файла при старте проекта"), "on_start")
        self._load_mode.addItem(tr("♻️ Всегда читать из файла при обращении"), "always")
        gl.addRow(tr("Режим загрузки:"), self._load_mode)

        self._encoding = QComboBox()
        self._encoding.addItems(["utf-8", "utf-8-sig", "cp1251", "latin-1"])
        gl.addRow(tr("Кодировка:"), self._encoding)

        btn_load_now = QPushButton(tr("📥 Загрузить из файла сейчас"))
        btn_load_now.clicked.connect(self._load_from_file_now)
        gl.addRow(btn_load_now)

        self._chk_save_contents = QCheckBox(tr("💾 Сохранять содержимое в файле проекта"))
        self._chk_save_contents.setToolTip(tr(
            "Если ВЫКЛЮЧЕНО — содержимое НЕ будет храниться в .workflow.json\n"
            "и будет загружаться из файла при каждом открытии проекта.\n"
            "Рекомендуется выключить для больших списков (тысячи строк)."
        ))
        gl.addRow(self._chk_save_contents)

        lay.addWidget(grp_file)

        # Редактор строк
        grp_items = QGroupBox(tr("Строки списка (каждая строка — отдельный элемент)"))
        gl2 = QVBoxLayout(grp_items)

        toolbar = QHBoxLayout()
        btn_add_line = QPushButton("➕")
        btn_add_line.setFixedWidth(28)
        btn_add_line.setToolTip(tr("Добавить пустую строку"))
        btn_add_line.clicked.connect(self._add_empty_line)
        btn_del_line = QPushButton("🗑")
        btn_del_line.setFixedWidth(28)
        btn_del_line.setToolTip(tr("Удалить выбранную строку"))
        btn_del_line.clicked.connect(self._del_line)
        btn_sort = QPushButton("↕ Сорт.")
        btn_sort.setFixedWidth(50)
        btn_sort.clicked.connect(self._sort_lines)
        btn_dedup = QPushButton("🔁 Дубли")
        btn_dedup.setFixedWidth(55)
        btn_dedup.setToolTip(tr("Удалить дублирующиеся строки"))
        btn_dedup.clicked.connect(self._remove_duplicates)
        lbl_count = QLabel()
        self._lbl_count = lbl_count

        toolbar.addWidget(btn_add_line)
        toolbar.addWidget(btn_del_line)
        toolbar.addWidget(btn_sort)
        toolbar.addWidget(btn_dedup)
        toolbar.addStretch()
        toolbar.addWidget(lbl_count)
        gl2.addLayout(toolbar)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(tr(
            "Введите строки — каждая строка будет отдельным элементом списка"
        ))
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {get_color('bg0')}; color: #9ECE6A; "
            f"font-family: Consolas, monospace; font-size: 11px; "
            f"border: 1px solid {get_color('bd2')}; }}"
        )
        self._editor.textChanged.connect(self._update_count)
        gl2.addWidget(self._editor)
        lay.addWidget(grp_items)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load_data(self):
        self._name.setText(self._data.get('name', ''))
        self._file_path.setText(self._data.get('file_path', ''))
        idx = self._load_mode.findData(self._data.get('load_mode', 'static'))
        self._load_mode.setCurrentIndex(max(0, idx))
        enc_idx = self._encoding.findText(self._data.get('encoding', 'utf-8'))
        self._encoding.setCurrentIndex(max(0, enc_idx))
        self._chk_save_contents.setChecked(self._data.get('save_contents', True))
        self._editor.setPlainText('\n'.join(self._data.get('items', [])))
        self._update_count()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл списка", "",
            "Text Files (*.txt *.csv *.tsv);;All Files (*)"
        )
        if path:
            self._file_path.setText(path)

    def _load_from_file_now(self):
        path = self._file_path.text().strip()
        if not path:
            QMessageBox.warning(self, "Нет пути", "Укажите путь к файлу.")
            return
        enc = self._encoding.currentText()
        try:
            with open(path, 'r', encoding=enc) as f:
                lines = [l.rstrip('\n') for l in f if l.strip()]
            self._editor.setPlainText('\n'.join(lines))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")

    def _add_empty_line(self):
        text = self._editor.toPlainText()
        self._editor.setPlainText(text + '\n')
        c = self._editor.textCursor()
        c.movePosition(c.MoveOperation.End)
        self._editor.setTextCursor(c)

    def _del_line(self):
        c = self._editor.textCursor()
        c.select(c.SelectionType.LineUnderCursor)
        c.removeSelectedText()
        c.deleteChar()
        self._editor.setTextCursor(c)

    def _sort_lines(self):
        lines = [l for l in self._editor.toPlainText().splitlines() if l.strip()]
        lines.sort()
        self._editor.setPlainText('\n'.join(lines))

    def _remove_duplicates(self):
        seen = set()
        result = []
        for l in self._editor.toPlainText().splitlines():
            if l not in seen:
                seen.add(l)
                result.append(l)
        self._editor.setPlainText('\n'.join(result))

    def _update_count(self):
        lines = [l for l in self._editor.toPlainText().splitlines() if l]
        self._lbl_count.setText(f"{len(lines)} {tr('строк')}")

    def _accept(self):
        lines = [l for l in self._editor.toPlainText().splitlines()]
        self._data['name'] = self._name.text().strip() or self._data['name']
        self._data['file_path'] = self._file_path.text().strip()
        self._data['load_mode'] = self._load_mode.currentData() or 'static'
        self._data['encoding'] = self._encoding.currentText()
        self._data['save_contents'] = self._chk_save_contents.isChecked()
        self._data['items'] = lines
        self.accept()

    def get_data(self) -> dict:
        return self._data


# ══════════════════════════════════════════════════════════
#  ДИАЛОГ РЕДАКТИРОВАНИЯ ТАБЛИЦЫ
# ══════════════════════════════════════════════════════════

class ProjectTableEditDialog(QDialog):
    """Диалог редактирования проектной таблицы."""

    def __init__(self, tbl: dict, parent=None):
        super().__init__(parent)
        import copy
        self._data = copy.deepcopy(tbl)
        self.setWindowTitle(f"{tr('📊 Таблица')}: {tbl.get('name', '')}")
        self.resize(700, 600)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        from PyQt6.QtWidgets import QDialogButtonBox, QSplitter, QSpinBox
        lay = QVBoxLayout(self)

        # Имя
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Имя:")))
        self._name = QLineEdit()
        row.addWidget(self._name)
        lay.addLayout(row)

        # Файл
        grp_file = QGroupBox(tr("Источник файла (CSV/TSV)"))
        gl = QFormLayout(grp_file)

        fp_row = QHBoxLayout()
        self._file_path = QLineEdit()
        self._file_path.setPlaceholderText(tr("Путь к CSV/TSV файлу (поддерживает {переменные})"))
        btn_browse = QPushButton("📂")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_file)
        fp_row.addWidget(self._file_path)
        fp_row.addWidget(btn_browse)
        gl.addRow(tr("Путь к файлу:"), fp_row)

        self._load_mode = QComboBox()
        self._load_mode.addItem(tr("📝 Статически (только ручной ввод)"), "static")
        self._load_mode.addItem(tr("🔄 Загрузить из файла при старте проекта"), "on_start")
        self._load_mode.addItem(tr("♻️ Всегда читать из файла при обращении"), "always")
        gl.addRow(tr("Режим загрузки:"), self._load_mode)

        self._encoding = QComboBox()
        self._encoding.addItems(["utf-8", "utf-8-sig", "cp1251", "latin-1"])
        gl.addRow(tr("Кодировка:"), self._encoding)

        self._has_header = QCheckBox(tr("Первая строка — заголовок"))
        self._has_header.setChecked(True)
        gl.addRow(self._has_header)

        btn_load_now = QPushButton(tr("📥 Загрузить из файла сейчас"))
        btn_load_now.clicked.connect(self._load_from_file_now)
        gl.addRow(btn_load_now)

        self._chk_save_contents = QCheckBox(tr("💾 Сохранять содержимое в файле проекта"))
        self._chk_save_contents.setToolTip(tr(
            "Если ВЫКЛЮЧЕНО — данные таблицы НЕ будут храниться в .workflow.json\n"
            "и будут загружаться из файла при каждом открытии.\n"
            "Рекомендуется выключить для больших таблиц."
        ))
        gl.addRow(self._chk_save_contents)

        lay.addWidget(grp_file)

        # Редактор колонок
        grp_cols = QGroupBox(tr("Колонки"))
        col_lay = QHBoxLayout(grp_cols)
        self._cols_list = QListWidget()
        self._cols_list.setMaximumWidth(180)
        col_lay.addWidget(self._cols_list)
        col_btns = QVBoxLayout()
        btn_add_col = QPushButton("➕")
        btn_add_col.clicked.connect(self._add_column)
        btn_del_col = QPushButton("🗑")
        btn_del_col.clicked.connect(self._del_column)
        btn_ren_col = QPushButton("✏")
        btn_ren_col.clicked.connect(self._rename_column)
        col_btns.addWidget(btn_add_col)
        col_btns.addWidget(btn_ren_col)
        col_btns.addWidget(btn_del_col)
        col_btns.addStretch()
        col_lay.addLayout(col_btns)
        lay.addWidget(grp_cols)

        # Редактор строк
        grp_rows = QGroupBox(tr("Данные таблицы"))
        row_lay = QVBoxLayout(grp_rows)

        row_toolbar = QHBoxLayout()
        btn_add_row = QPushButton(tr("➕ Строка"))
        btn_add_row.clicked.connect(self._add_row)
        btn_del_row = QPushButton(tr("🗑 Строку"))
        btn_del_row.clicked.connect(self._del_row)
        lbl_rc = QLabel()
        self._lbl_row_count = lbl_rc
        row_toolbar.addWidget(btn_add_row)
        row_toolbar.addWidget(btn_del_row)
        row_toolbar.addStretch()
        row_toolbar.addWidget(lbl_rc)
        row_lay.addLayout(row_toolbar)

        self._table = QTableWidget(0, 1)
        self._table.setStyleSheet(f"""
            QTableWidget {{ background: {get_color('bg0')}; color: {get_color('ac')};
                           gridline-color: {get_color('bd')}; }}
            QHeaderView::section {{ background: {get_color('bg2')}; color: {get_color('tx1')}; }}
        """)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._update_row_count)
        row_lay.addWidget(self._table)
        lay.addWidget(grp_rows)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load_data(self):
        self._name.setText(self._data.get('name', ''))
        self._file_path.setText(self._data.get('file_path', ''))
        idx = self._load_mode.findData(self._data.get('load_mode', 'static'))
        self._load_mode.setCurrentIndex(max(0, idx))
        enc_idx = self._encoding.findText(self._data.get('encoding', 'utf-8'))
        self._encoding.setCurrentIndex(max(0, enc_idx))
        self._has_header.setChecked(self._data.get('has_header', True))
        self._chk_save_contents.setChecked(self._data.get('save_contents', True))
        self._rebuild_columns(self._data.get('columns', ['Колонка 1']))
        self._rebuild_rows(self._data.get('rows', []))

    def _rebuild_columns(self, cols: list):
        self._cols_list.clear()
        for c in cols:
            self._cols_list.addItem(c)
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)

    def _rebuild_rows(self, rows: list):
        cols = self._table.columnCount()
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row[:cols]):
                self._table.setItem(r, c, QTableWidgetItem(str(cell)))
        self._update_row_count()

    def _get_columns(self) -> list:
        return [self._cols_list.item(i).text()
                for i in range(self._cols_list.count())]

    def _add_column(self):
        name, ok = QInputDialog.getText(self, tr("Добавить колонку"), tr("Имя колонки:"))
        if ok and name.strip():
            self._cols_list.addItem(name.strip())
            cols = self._get_columns()
            self._table.setColumnCount(len(cols))
            self._table.setHorizontalHeaderLabels(cols)

    def _del_column(self):
        row = self._cols_list.currentRow()
        if row < 0:
            return
        self._cols_list.takeItem(row)
        self._table.removeColumn(row)
        self._table.setHorizontalHeaderLabels(self._get_columns())

    def _rename_column(self):
        row = self._cols_list.currentRow()
        if row < 0:
            return
        old = self._cols_list.item(row).text()
        name, ok = QInputDialog.getText(self, tr("Переименовать"), tr("Новое имя:"), text=old)
        if ok and name.strip():
            self._cols_list.item(row).setText(name.strip())
            self._table.setHorizontalHeaderLabels(self._get_columns())

    def _add_row(self):
        r = self._table.rowCount()
        self._table.insertRow(r)
        for c in range(self._table.columnCount()):
            self._table.setItem(r, c, QTableWidgetItem(""))
        self._update_row_count()

    def _del_row(self):
        r = self._table.currentRow()
        if r >= 0:
            self._table.removeRow(r)
            self._update_row_count()

    def _update_row_count(self):
        self._lbl_row_count.setText(f"{self._table.rowCount()} {tr('строк')}")

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать CSV/TSV файл", "",
            "CSV/TSV Files (*.csv *.tsv *.txt);;All Files (*)"
        )
        if path:
            self._file_path.setText(path)

    def _load_from_file_now(self):
        path = self._file_path.text().strip()
        if not path:
            QMessageBox.warning(self, "Нет пути", "Укажите путь к файлу.")
            return
        enc = self._encoding.currentText()
        try:
            import csv
            with open(path, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                all_rows = list(reader)
            if not all_rows:
                return
            if self._has_header.isChecked():
                cols = all_rows[0]
                data_rows = all_rows[1:]
            else:
                cols = [f"Колонка {i+1}" for i in range(len(all_rows[0]))]
                data_rows = all_rows
            self._rebuild_columns(cols)
            self._rebuild_rows(data_rows)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")

    def _accept(self):
        rows = []
        for r in range(self._table.rowCount()):
            row_data = []
            for c in range(self._table.columnCount()):
                item = self._table.item(r, c)
                row_data.append(item.text() if item else "")
            rows.append(row_data)
        self._data['name'] = self._name.text().strip() or self._data['name']
        self._data['file_path'] = self._file_path.text().strip()
        self._data['load_mode'] = self._load_mode.currentData() or 'static'
        self._data['encoding'] = self._encoding.currentText()
        self._data['has_header'] = self._has_header.isChecked()
        self._data['save_contents'] = self._chk_save_contents.isChecked()
        self._data['columns'] = self._get_columns()
        self._data['rows'] = rows
        self.accept()

    def get_data(self) -> dict:
        return self._data
