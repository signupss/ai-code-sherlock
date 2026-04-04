"""
AI Agent Constructor — Visual workflow editor for AI agent pipelines.
Main window file - after refactoring.
"""
from __future__ import annotations

import json
import math
import os
import sys
import json as _json_autosave
import tempfile
import atexit
import signal as _signal_module
import uuid
import base64
import io
from PyQt6.QtCore import QByteArray, QBuffer, QIODeviceBase
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QTimer, pyqtSignal, QLineF, QEvent, QObject,
)
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont, QPolygonF, QPainterPath,
    QLinearGradient, QKeySequence, QMouseEvent, QCursor, QPixmap, QIcon,
)
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QFrame, QStatusBar, QToolBar,
    QLineEdit, QFileDialog, QMessageBox, QMenu, QApplication,
    QTabWidget, QTextEdit, QPlainTextEdit, QScrollArea, QSizePolicy,
    QGraphicsDropShadowEffect, QColorDialog, QInputDialog,
    QListWidget, QListWidgetItem, QSlider, QComboBox, QSpinBox, 
    QCheckBox, QTableWidget, QTableWidgetItem, QFormLayout, QGroupBox, 
    QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox
)

# ══════════════════════════════════════════════════════════
#  ГЛОБАЛЬНЫЕ ПАТЧИ (ОСТАВИТЬ ЗДЕСЬ! КРИТИЧНО!)
# ══════════════════════════════════════════════════════════
import builtins
import services.workflow_runtime
from services.agent_models import EdgeCondition, AgentNode, AgentWorkflow
 
# ── Многопоточный менеджер проектов ──
from constructor.project_manager import (
    ProjectExecutionManager, ProjectEntry, ProjectStatus,
    ThreadMode, StopCondition
)
from constructor.project_dashboard import ProjectDashboard

builtins.EdgeCondition = EdgeCondition
services.workflow_runtime.EdgeCondition = EdgeCondition

def _init_extended_attrs(node):
    """Инициализация недостающих атрибутов при вставке нод."""
    defaults = {
        "orchestration_mode": "sequential", "conditional_branches": [],
        "breakpoint_enabled": False, "human_in_loop": False,
        "auto_test": False, "auto_patch": False, "auto_improve": False,
        "max_iterations": 3, "self_modify": False, "snippet_code": "",
        "variables": {}, "regex_pattern": ""
    }
    for k, v in defaults.items():
        if not hasattr(node, k):
            setattr(node, k, v)

# Патчи сериализации (перенесите сюда строки ~60-200 из оригинала)
_orig_node_to_dict = AgentNode.to_dict
def _patched_node_to_dict(self):
    d = _orig_node_to_dict(self)
    import copy
    d['available_tools'] = copy.deepcopy(getattr(self, 'available_tools', []))
    d['tool_configs'] = copy.deepcopy(getattr(self, 'tool_configs', {}))
    d['snippet_config'] = copy.deepcopy(getattr(self, 'snippet_config', {}))
    d['orchestration_mode'] = getattr(self, 'orchestration_mode', 'sequential')
    d['breakpoint_enabled'] = getattr(self, 'breakpoint_enabled', False)
    d['human_in_loop'] = getattr(self, 'human_in_loop', False)
    d['auto_test'] = getattr(self, 'auto_test', False)
    d['auto_patch'] = getattr(self, 'auto_patch', False)
    d['auto_improve'] = getattr(self, 'auto_improve', False)
    d['max_iterations'] = getattr(self, 'max_iterations', 1)
    d['self_modify'] = getattr(self, 'self_modify', False)
    d['attached_to'] = getattr(self, 'attached_to', None)
    raw_children = getattr(self, 'attached_children', [])
    d['attached_children'] = [str(c.id) if hasattr(c, 'id') else str(c) for c in raw_children]
    d['custom_color'] = getattr(self, 'custom_color', '')
    d['comment'] = getattr(self, 'comment', '')
    return d
AgentNode.to_dict = _patched_node_to_dict

_orig_node_from_dict = AgentNode.from_dict.__func__ if hasattr(AgentNode.from_dict, "__func__") else AgentNode.from_dict
@classmethod
def _patched_node_from_dict(cls, data):
    import copy
    node = _orig_node_from_dict(cls, data) if hasattr(AgentNode.from_dict, "__func__") else _orig_node_from_dict(data)
    # ═══ КРИТИЧНО: Глубокая копия при загрузке чтобы избежать shared state между нодами ═══
    node.available_tools = copy.deepcopy(data.get('available_tools', []))
    node.tool_configs = copy.deepcopy(data.get('tool_configs', {}))
    node.snippet_config = copy.deepcopy(data.get('snippet_config', {}))
    node.orchestration_mode = data.get('orchestration_mode', 'sequential')
    node.breakpoint_enabled = data.get('breakpoint_enabled', False)
    node.human_in_loop = data.get('human_in_loop', False)
    node.auto_test = data.get('auto_test', False)
    node.auto_patch = data.get('auto_patch', False)
    node.auto_improve = data.get('auto_improve', False)
    node.max_iterations = data.get('max_iterations', 1)
    node.self_modify = data.get('self_modify', False)
    node.attached_to = data.get('attached_to')
    # ═══ ИСПРАВЛЕНИЕ: attached_children всегда список строк ID ═══
    raw_children = data.get('attached_children', [])
    node.attached_children = [str(c) for c in raw_children] if raw_children else []
    node.custom_color = data.get('custom_color', '')
    node.comment = data.get('comment', '')
    return node
AgentNode.from_dict = _patched_node_from_dict


# 2. РАДИКАЛЬНЫЙ ПАТЧ I/O: перехват сохранения/загрузки на уровне записи в файл.
# Это обходит любые жесткие ограничения Pydantic/Dataclasses.
_orig_wf_save = AgentWorkflow.save
def _patched_wf_save(self, path):
    # 1. Сначала даем штатному движку сохранить файл как он умеет
    _orig_wf_save(self, path)
    
    # 2. Сразу же открываем этот файл, инжектим наши параметры и перезаписываем
    import json
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        import copy
        data['metadata'] = copy.deepcopy(getattr(self, 'metadata', {}))
        data['close_browser_on_finish'] = getattr(self, 'close_browser_on_finish', True)
        if 'nodes' in data and hasattr(self, 'nodes'):
            # Два индекса для надёжного матчинга
            node_by_id = {str(n.id): n for n in self.nodes}
            node_by_name = {n.name: n for n in self.nodes}
            matched = 0
            for nd in data['nodes']:
                node = node_by_id.get(str(nd.get('id')))
                if not node:
                    node = node_by_name.get(nd.get('name'))
                if node:
                    import copy
                    # Гарантируем, что snippet_config — это отдельный объект в JSON
                    config_data = getattr(node, 'snippet_config', {})
                    if not isinstance(config_data, dict):
                        config_data = {}
                    
                    nd['snippet_config'] = copy.deepcopy(config_data)
                    nd['tool_configs'] = copy.deepcopy(getattr(node, 'tool_configs', {}))
                    nd['available_tools'] = copy.deepcopy(getattr(node, 'available_tools', []))
                    nd['orchestration_mode'] = getattr(node, 'orchestration_mode', 'sequential')
                    nd['breakpoint_enabled'] = getattr(node, 'breakpoint_enabled', False)
                    nd['human_in_loop'] = getattr(node, 'human_in_loop', False)
                    nd['auto_test'] = getattr(node, 'auto_test', False)
                    nd['auto_patch'] = getattr(node, 'auto_patch', False)
                    nd['auto_improve'] = getattr(node, 'auto_improve', False)
                    nd['max_iterations'] = getattr(node, 'max_iterations', 1)
                    nd['self_modify'] = getattr(node, 'self_modify', False)
                    nd['snippet_config'] = copy.deepcopy(getattr(node, 'snippet_config', {}))
                    matched += 1
            if matched == 0 and len(self.nodes) > 0:
                print(f"⚠️ I/O Save: не удалось сопоставить ни одной ноды! "
                      f"JSON IDs: {[nd.get('id') for nd in data['nodes']]}, "
                      f"WF IDs: {[str(n.id) for n in self.nodes]}")
                    
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"I/O Save Injection Error: {e}")
        import traceback; traceback.print_exc()

AgentWorkflow.save = _patched_wf_save

# 3. ПАТЧ add_edge: разрешить множественные связи от Switch case-портов к одной цели
_orig_wf_add_edge = AgentWorkflow.add_edge
def _patched_wf_add_edge(self, edge):
    # ═══ ИСПРАВЛЕНИЕ: для Switch case-портов проверяем также label ═══
    # Обычная проверка: source_id + target_id должны быть уникальны
    # НО: для Switch разные case-порты (разные label) могут идти на одну цель
    # ИСПРАВЛЕНИЕ: разные condition (ALWAYS vs ON_FAILURE) — это разные рёбра!
    for existing in self.edges:
        if existing.source_id == edge.source_id and existing.target_id == edge.target_id:
            # Та же связь source→target — проверяем что делает её уникальной
            is_duplicate = True
            
            # Switch: разные case-порты (label) — разные рёбра
            if edge.label and edge.label.startswith('__sw_'):
                if existing.label != edge.label:
                    is_duplicate = False  # Разные case-порты — не дубликат!
            
            # УСПЕХ vs ОШИБКА: разные condition — разные рёбра!
            # ON_FAILURE (ошибка) и ALWAYS/ON_SUCCESS (успех) — это разные логические пути
            if edge.condition != existing.condition:
                is_duplicate = False  # Разные условия — не дубликат!
            
            if is_duplicate:
                return (False, "Такая связь уже существует")
    self.edges.append(edge)
    return (True, "")
AgentWorkflow.add_edge = _patched_wf_add_edge

_orig_wf_load = AgentWorkflow.load
@classmethod
def _patched_wf_load(cls, path):
    # 1. Штатно загружаем объект
    wf = _orig_wf_load(path)
    
    # 2. Снова открываем файл напрямую и насильно пропихиваем параметры в созданные объекты
    import json
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        wf.metadata = data.get('metadata', {})
        wf.close_browser_on_finish = data.get('close_browser_on_finish', True)
        if 'nodes' in data and hasattr(wf, 'nodes'):
            # Два индекса для надёжного матчинга: по ID и по имени (fallback)
            node_by_id = {str(n.id): n for n in wf.nodes}
            node_by_name = {n.name: n for n in wf.nodes}
            matched = 0
            for nd in data['nodes']:
                node = node_by_id.get(str(nd.get('id')))
                if not node:
                    node = node_by_name.get(nd.get('name'))
                if node:
                    import copy
                    # 1. Сначала полностью изолируем данные из JSON
                    raw_snippet_config = copy.deepcopy(nd.get('snippet_config', {}))
                    raw_tool_configs = copy.deepcopy(nd.get('tool_configs', {}))
                    
                    # 2. Насильно записываем в объект ноды, минуя возможные кэши моделей
                    node.snippet_config = raw_snippet_config
                    node.tool_configs = raw_tool_configs
                    node.available_tools = copy.deepcopy(nd.get('available_tools', []))
                    
                    # 3. Восстанавливаем остальные параметры индивидуально
                    node.orchestration_mode = nd.get('orchestration_mode', 'sequential')
                    node.max_iterations = nd.get('max_iterations', 1)
                    node.custom_color = nd.get('custom_color', '')
                    node.comment = nd.get('comment', '')
                    
                    # Специальная проверка для того, чтобы Pydantic (если он есть) не объединил их
                    if hasattr(node, '__dict__'):
                        node.__dict__['snippet_config'] = raw_snippet_config
                        
                    matched += 1
                    node.orchestration_mode = nd.get('orchestration_mode', 'sequential')
                    node.breakpoint_enabled = nd.get('breakpoint_enabled', False)
                    node.human_in_loop = nd.get('human_in_loop', False)
                    node.auto_test = nd.get('auto_test', False)
                    node.auto_patch = nd.get('auto_patch', False)
                    node.auto_improve = nd.get('auto_improve', False)
                    node.max_iterations = nd.get('max_iterations', 1)
                    node.self_modify = nd.get('self_modify', False)
                    node.attached_to = nd.get('attached_to')
                    node.attached_children = copy.deepcopy(nd.get('attached_children', []))
                    node.custom_color = nd.get('custom_color', '')
                    node.comment = nd.get('comment', '')
                    matched += 1
            if matched == 0 and len(wf.nodes) > 0:
                print(f"⚠️ I/O Load: не удалось сопоставить ни одной ноды! "
                      f"JSON IDs: {[nd.get('id') for nd in data['nodes']]}, "
                      f"WF IDs: {[str(n.id) for n in wf.nodes]}")
    except Exception as e:
        print(f"I/O Load Injection Error: {e}")
        import traceback; traceback.print_exc()
        
    return wf

AgentWorkflow.load = _patched_wf_load
# --- КОНЕЦ ПАТЧА ---

# ══════════════════════════════════════════════════════════
#  ИМПОРТЫ ИЗ МОДУЛЕЙ CONSTRUCTOR
# ══════════════════════════════════════════════════════════
from constructor.constants import (
    _AGENT_COLORS, _AGENT_ICONS, _SNIPPET_ICONS, SNIPPET_TYPES, 
    NOTE_TYPES, AI_AGENT_TYPES, get_node_category
)
from constructor.commands import HistoryManager, Command, WidgetChangeCommand
from constructor.graphics import (
    AgentNodeItem, BlockHeaderItem, EdgeItem,
    WorkflowScene, WorkflowView, MiniMapWidget
)
from constructor.panels import ProjectVariablesPanel, NodePropertiesPanel
from constructor.runtime import WorkflowDebugger, WorkflowRuntimeEngine
from constructor.browser_module import (
    BrowserManager, BrowserProfileManager, BrowserProfile, BrowserProxy,
    BrowserLaunchDialog, BrowserLaunchWidget, BrowserActionWidget,
    BrowserInstancePanel, BROWSER_ACTIONS,
    execute_browser_launch_snippet, execute_browser_action_snippet,
)

# Остальные импорты проекта
from services.agent_models import AgentType
from services.skill_registry import SkillRegistry, BUILTIN_SKILLS, SkillCategory
from services.workflow_runtime import WorkflowRuntime

# Theme и i18n
try:
    from ui.theme_manager import get_color, register_theme_refresh
except ImportError:
    def get_color(k): 
        return {
            "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722", "bg3": "#1A1D2E",
            "bd": "#2E3148", "bd2": "#1E2030",
            "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
            "ac": "#7AA2F7", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
        }.get(k, "#CDD6F4")
    def register_theme_refresh(cb): pass

try:
    from ui.i18n import tr, register_listener as _i18n_register_listener, retranslate_widget as _retranslate_widget
except ImportError:
    def tr(s): return s
    def _i18n_register_listener(cb): pass
    def _retranslate_widget(w): pass


# ══════════════════════════════════════════════════════════
#  GLOBAL SETTINGS
# ══════════════════════════════════════════════════════════

class GlobalSettings:
    """Синглтон глобальных настроек выполнения."""
    _data: dict = {}
    _DEFAULTS = {
        "max_parallel_projects":    3,
        "project_thread_timeout":   300,
        "max_ram_mb":               2048,
        "warn_ram_mb":              1500,
        "max_parallel_browsers":    5,
        "browser_screenshot_ms":    3000,
        "browser_screenshot_scale": 0.30,
        "model_semaphores":         {},   # {model_id: max_parallel_int}
        "model_exec_mode":          {},   # {model_id: "parallel"|"sequential"}
        # ═══ Новые настройки многопоточного менеджера ═══
        "max_global_threads":       10,   # Глобальный лимит потоков для всех проектов
        "resource_monitoring":      True, # Отслеживание ресурсов перед запуском потока
        "priority_threads_interrupt": False,  # Приоритетные потоки прерывают менее приоритетные
        "reset_failures_on_add":    True, # Обнулять неуспехи при добавлении попыток
        "safe_file_save":           True, # Безопасное сохранение файлов
        "auto_restart_unfinished":  False,# Запускать незавершённые при старте программы
    }
    _FILE = Path.home() / ".sherlock" / "global_settings.json"

    @classmethod
    def get(cls, key: str = None):
        if not cls._data:
            cls.load()
        if key:
            return cls._data.get(key, cls._DEFAULTS.get(key))
        return {**cls._DEFAULTS, **cls._data}

    @classmethod
    def save(cls, data: dict):
        cls._data.update(data)
        try:
            cls._FILE.parent.mkdir(exist_ok=True)
            cls._FILE.write_text(
                json.dumps(cls._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass
        cls._apply()

    @classmethod
    def load(cls):
        try:
            if cls._FILE.exists():
                cls._data = json.loads(cls._FILE.read_text(encoding="utf-8"))
        except Exception:
            cls._data = {}

    @classmethod
    def _apply(cls):
        """Применить настройки немедленно (браузеры, семафоры)."""
        try:
            from constructor.browser_module import BrowserTrayMiniature
            BrowserTrayMiniature.DEFAULT_INTERVAL = cls._data.get(
                "browser_screenshot_ms", 3000)
            BrowserTrayMiniature.DEFAULT_SCALE = cls._data.get(
                "browser_screenshot_scale", 0.30)
        except Exception:
            pass


def _apply_dialog_theme(dlg):
    """Применить тёмную тему ко всем диалогам/окнам."""
    try:
        dlg.setStyleSheet(f"""
            QDialog, QWidget {{
                background: {get_color('bg1')};
                color: {get_color('tx0')};
            }}
            QTabWidget::pane {{
                background: {get_color('bg2')};
                border: 1px solid {get_color('bd')};
            }}
            QTabBar::tab {{
                background: {get_color('bg2')};
                color: {get_color('tx1')};
                padding: 4px 10px;
                border: 1px solid {get_color('bd')};
            }}
            QTabBar::tab:selected {{
                background: {get_color('bg3')};
                color: {get_color('tx0')};
            }}
            QGroupBox {{
                background: {get_color('bg2')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
                margin-top: 8px;
                color: {get_color('tx1')};
            }}
            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
                background: {get_color('bg0')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 3px;
                padding: 2px 4px;
            }}
            QLabel {{ color: {get_color('tx0')}; }}
            QPushButton {{
                background: {get_color('bg3')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
                padding: 3px 10px;
            }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
            QTableWidget {{
                background: {get_color('bg0')};
                color: {get_color('tx0')};
                gridline-color: {get_color('bd')};
            }}
            QHeaderView::section {{
                background: {get_color('bg3')};
                color: {get_color('tx1')};
                border: 1px solid {get_color('bd')};
                padding: 4px;
            }}
            QCheckBox {{ color: {get_color('tx0')}; }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background: {get_color('bg1')};
                width: 8px; height: 8px;
            }}
            QScrollBar::handle {{ background: {get_color('bd')}; border-radius: 4px; }}
        """)
    except Exception:
        pass


class GlobalSettingsDialog(QDialog):
    """Диалог глобальных настроек (кнопка ⚙ в toolbar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("⚙  Глобальные настройки"))
        self.resize(660, 580)
        self._s = GlobalSettings.get()
        self._build_ui()
        self._load_to_ui()
        _apply_dialog_theme(self)

    # ── UI ────────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Потоки ────────────────────────────────────────
        w = QWidget(); f = QFormLayout(w)
        self._spn_proj = QSpinBox(); self._spn_proj.setRange(1, 64)
        self._spn_proj.setToolTip(
            tr("Сколько проектов можно запускать одновременно.\n"
               "Остальные ждут в очереди.")
        )
        f.addRow(tr("Макс. параллельных проектов:"), self._spn_proj)

        self._spn_timeout = QSpinBox(); self._spn_timeout.setRange(30, 7200)
        self._spn_timeout.setSuffix(tr(" сек"))
        f.addRow(tr("Таймаут одного проекта:"), self._spn_timeout)
        tabs.addTab(w, tr("🧵 Потоки"))

        # ── Память ────────────────────────────────────────
        w = QWidget(); f = QFormLayout(w)
        self._spn_ram = QSpinBox(); self._spn_ram.setRange(256, 65536)
        self._spn_ram.setSuffix(tr(" МБ"))
        f.addRow(tr("Лимит ОЗУ (мягкий):"), self._spn_ram)

        self._spn_ram_warn = QSpinBox(); self._spn_ram_warn.setRange(256, 65536)
        self._spn_ram_warn.setSuffix(tr(" МБ"))
        f.addRow(tr("Предупреждение при ОЗУ >:"), self._spn_ram_warn)
        tabs.addTab(w, tr("💾 Память"))

        # ── Браузеры ──────────────────────────────────────
        w = QWidget(); f = QFormLayout(w)
        self._spn_brs = QSpinBox(); self._spn_brs.setRange(1, 100)
        f.addRow(tr("Макс. браузеров одновременно:"), self._spn_brs)

        self._spn_ss_ms = QSpinBox()
        self._spn_ss_ms.setRange(500, 60000); self._spn_ss_ms.setSuffix(tr(" мс"))
        self._spn_ss_ms.setToolTip(
            tr("Как часто обновлять миниатюру в трее.\n"
               "500мс = нагрузка, 5000мс = почти без нагрузки.")
        )
        f.addRow(tr("Интервал скриншота (трей):"), self._spn_ss_ms)

        self._spn_ss_scale = QSpinBox()
        self._spn_ss_scale.setRange(5, 100); self._spn_ss_scale.setSuffix(tr(" %"))
        self._spn_ss_scale.setToolTip(
            tr("Масштаб скриншота для трея.\n"
               "30% = 3× меньше памяти и CPU при захвате.")
        )
        f.addRow(tr("Масштаб миниатюры:"), self._spn_ss_scale)
        tabs.addTab(w, tr("🌐 Браузеры"))
 
        # ── Глобальные потоки ─────────────────────────────
        w = QWidget(); f = QFormLayout(w)
        self._spn_global_threads = QSpinBox(); self._spn_global_threads.setRange(1, 200)
        self._spn_global_threads.setToolTip(
            tr("Максимальное количество потоков для ВСЕХ проектов вместе.\n"
               "Аналог 'Максимальное количество потоков' в ZennoPoster.")
        )
        f.addRow(tr("Макс. глобальных потоков:"), self._spn_global_threads)
 
        self._chk_resource_mon = QCheckBox(tr("Отслеживать ресурсы компьютера"))
        self._chk_resource_mon.setToolTip(
            tr("Запуск потоков только при наличии свободных ресурсов.")
        )
        f.addRow(self._chk_resource_mon)
 
        self._chk_priority_interrupt = QCheckBox(tr("Приоритетные потоки прерывают менее приоритетных"))
        f.addRow(self._chk_priority_interrupt)
 
        self._chk_reset_failures = QCheckBox(tr("Обнулять неуспехи при добавлении попыток"))
        f.addRow(self._chk_reset_failures)
 
        self._chk_safe_save = QCheckBox(tr("Безопасно сохранять файлы"))
        f.addRow(self._chk_safe_save)
 
        self._chk_auto_restart = QCheckBox(tr("Запускать незавершённые проекты при старте"))
        f.addRow(self._chk_auto_restart)
 
        tabs.addTab(w, tr("⚡ Глобальные потоки"))
 
        # ── Модели ────────────────────────────────────────
        w = QWidget(); ml = QVBoxLayout(w)
        ml.addWidget(QLabel(
            tr("Для каждой модели можно задать:\n"
               "• Макс. параллельных вызовов — семафор (1 = очередь).\n"
               "• Режим: parallel (одновременно) или sequential (по одному).\n\n"
               "Пример: локальная LLM ollama/llama3 → sequential, limit=1\n"
               "        OpenAI gpt-4o → parallel, limit=5")
        ))
        self._tbl = QTableWidget(0, 3)
        self._tbl.setHorizontalHeaderLabels([tr("ID модели"), tr("Лимит"), tr("Режим")])
        self._tbl.horizontalHeader().setStretchLastSection(True)
        ml.addWidget(self._tbl)
        
        btn_row = QHBoxLayout()
        b_add = QPushButton(tr("+ Добавить")); b_add.clicked.connect(self._add_row)
        b_del = QPushButton(tr("— Удалить"));  b_del.clicked.connect(self._del_row)
        btn_row.addWidget(b_add); btn_row.addWidget(b_del); btn_row.addStretch()
        ml.addLayout(btn_row)
        tabs.addTab(w, tr("🤖 Модели"))

        lay.addWidget(tabs)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load_to_ui(self):
        s = self._s
        self._spn_proj.setValue(s.get("max_parallel_projects", 3))
        self._spn_timeout.setValue(s.get("project_thread_timeout", 300))
        self._spn_ram.setValue(s.get("max_ram_mb", 2048))
        self._spn_ram_warn.setValue(s.get("warn_ram_mb", 1500))
        self._spn_brs.setValue(s.get("max_parallel_browsers", 5))
        self._spn_ss_ms.setValue(s.get("browser_screenshot_ms", 3000))
        self._spn_ss_scale.setValue(int(s.get("browser_screenshot_scale", 0.30) * 100))
        sems  = s.get("model_semaphores", {})
        modes = s.get("model_exec_mode", {})
        for mid in set(list(sems.keys()) + list(modes.keys())):
            self._add_row(mid, sems.get(mid, 1), modes.get(mid, "parallel"))
 
        # Глобальные потоки
        self._spn_global_threads.setValue(s.get("max_global_threads", 10))
        self._chk_resource_mon.setChecked(s.get("resource_monitoring", True))
        self._chk_priority_interrupt.setChecked(s.get("priority_threads_interrupt", False))
        self._chk_reset_failures.setChecked(s.get("reset_failures_on_add", True))
        self._chk_safe_save.setChecked(s.get("safe_file_save", True))
        self._chk_auto_restart.setChecked(s.get("auto_restart_unfinished", False))

    def _add_row(self, mid="", limit=1, mode="parallel"):
        r = self._tbl.rowCount(); self._tbl.insertRow(r)
        self._tbl.setItem(r, 0, QTableWidgetItem(mid or tr("model_id")))
        spn = QSpinBox(); spn.setRange(1, 64); spn.setValue(limit)
        self._tbl.setCellWidget(r, 1, spn)
        cmb = QComboBox(); cmb.addItems(["parallel", "sequential"])
        cmb.setCurrentText(mode)
        self._tbl.setCellWidget(r, 2, cmb)

    def _del_row(self):
        r = self._tbl.currentRow()
        if r >= 0: self._tbl.removeRow(r)

    def _accept(self):
        sems, modes = {}, {}
        for r in range(self._tbl.rowCount()):
            item = self._tbl.item(r, 0)
            spn  = self._tbl.cellWidget(r, 1)
            cmb  = self._tbl.cellWidget(r, 2)
            if item and spn and cmb:
                mid = item.text().strip()
                if mid:
                    sems[mid]  = spn.value()
                    modes[mid] = cmb.currentText()
        GlobalSettings.save({
            "max_parallel_projects":    self._spn_proj.value(),
            "project_thread_timeout":   self._spn_timeout.value(),
            "max_ram_mb":               self._spn_ram.value(),
            "warn_ram_mb":              self._spn_ram_warn.value(),
            "max_parallel_browsers":    self._spn_brs.value(),
            "browser_screenshot_ms":    self._spn_ss_ms.value(),
            "browser_screenshot_scale": self._spn_ss_scale.value() / 100.0,
            "model_semaphores":         sems,
            "model_exec_mode":          modes,
            # Глобальные потоки
            "max_global_threads":           self._spn_global_threads.value(),
            "resource_monitoring":          self._chk_resource_mon.isChecked(),
            "priority_threads_interrupt":   self._chk_priority_interrupt.isChecked(),
            "reset_failures_on_add":        self._chk_reset_failures.isChecked(),
            "safe_file_save":               self._chk_safe_save.isChecked(),
            "auto_restart_unfinished":      self._chk_auto_restart.isChecked(),
        })
        # Применить к менеджеру проектов
        try:
            pm = ProjectExecutionManager.instance()
            pm.update_global_settings(
                max_threads=self._spn_global_threads.value(),
                model_semaphores=sems,
                model_modes=modes,
            )
        except Exception:
            pass
        self.accept()

# ══════════════════════════════════════════════════════════
#  PROJECT THREAD MANAGER — многопоточный запуск проектов
# ══════════════════════════════════════════════════════════
import threading
from PyQt6.QtCore import QSemaphore

class ProjectThreadManager:
    """
    Управляет параллельным выполнением проектов.
    Лимит одновременных проектов — из GlobalSettings.
    Для каждой модели — свой семафор (sequential / parallel).
    """
    _instance: Optional['ProjectThreadManager'] = None

    def __init__(self):
        s = GlobalSettings.get()
        n = s.get("max_parallel_projects", 3)
        self._semaphore = threading.Semaphore(n)
        self._model_locks: dict[str, threading.Semaphore] = {}
        self._refresh_model_semaphores()
        self._active: dict[str, threading.Thread] = {}

    @classmethod
    def get(cls) -> 'ProjectThreadManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _refresh_model_semaphores(self):
        s = GlobalSettings.get()
        sems  = s.get("model_semaphores", {})
        modes = s.get("model_exec_mode", {})
        for mid, limit in sems.items():
            mode = modes.get(mid, "parallel")
            n = 1 if mode == "sequential" else max(1, limit)
            self._model_locks[mid] = threading.Semaphore(n)

    def get_model_semaphore(self, model_id: str) -> threading.Semaphore:
        """Вернуть семафор для конкретной модели (создать если нет)."""
        if model_id not in self._model_locks:
            s = GlobalSettings.get()
            sems  = s.get("model_semaphores", {})
            modes = s.get("model_exec_mode", {})
            limit = sems.get(model_id, 4)
            mode  = modes.get(model_id, "parallel")
            n = 1 if mode == "sequential" else max(1, limit)
            self._model_locks[model_id] = threading.Semaphore(n)
        return self._model_locks[model_id]

    def submit_project(self, project_id: str, run_fn, on_done=None):
        """Запустить проект в отдельном потоке с учётом лимита."""
        def _run():
            with self._semaphore:
                try:
                    run_fn()
                finally:
                    self._active.pop(project_id, None)
                    if on_done:
                        on_done(project_id)
        t = threading.Thread(target=_run, daemon=True, name=f"project_{project_id}")
        self._active[project_id] = t
        t.start()
        return t

    def active_count(self) -> int:
        return len(self._active)

# ══════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЙ КЛАСС (только для этого окна)
# ══════════════════════════════════════════════════════════

class SnippetWidgetTracker:
    """Отслеживает изменения в виджетах сниппета для undo/redo"""
    
    def __init__(self, history_manager: HistoryManager, parent_window):
        self.history = history_manager
        self.parent = parent_window
        self._tracking = {}  # widget -> last_value
        self._is_restoring = False  # Флаг для предотвращения циклов
    
    def track_widget(self, widget, value_getter, value_setter, description: str = ""):
        """Подключить отслеживание к виджету"""
        widget_key = id(widget)
        
        # Сохраняем начальное значение
        try:
            self._tracking[widget_key] = {
                'widget': widget,
                'getter': value_getter,
                'setter': value_setter,
                'last_value': value_getter(),
                'description': description
            }
        except Exception as e:
            print(f"[TRACKER] Error tracking widget: {e}")
            return
        
        # Подключаем сигналы в зависимости от типа виджета
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(
                lambda text, w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QTextEdit):
            widget.textChanged.connect(
                lambda w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(
                lambda w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(
                lambda idx, w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(
                lambda val, w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(
                lambda state, w=widget, k=widget_key: self._on_value_changed(k)
            )
        elif isinstance(widget, QTableWidget):
            widget.cellChanged.connect(
                lambda row, col, w=widget, k=widget_key: self._on_value_changed(k)
            )
    
    def _on_value_changed(self, widget_key):
        """Обработчик изменения значения"""
        if self._is_restoring or widget_key not in self._tracking:
            return
        
        track_info = self._tracking[widget_key]
        new_value = track_info['getter']()
        old_value = track_info['last_value']
        
        # Пропускаем если значение не изменилось
        if new_value == old_value:
            return
        
        # Создаем команду
        command = WidgetChangeCommand(
            track_info['widget'],
            old_value,
            new_value,
            track_info['setter'],
            track_info['description']
        )
        
        # Сохраняем в историю
        self.history.push_command(command)
        
        # Обновляем последнее значение
        track_info['last_value'] = new_value
        
        # Уведомляем родительское окно об изменении
        if hasattr(self.parent, '_mark_modified_from_props'):
            self.parent._mark_modified_from_props()
    
    def update_tracked_value(self, widget):
        """Обновить отслеживаемое значение после загрузки (без создания команды)"""
        widget_key = id(widget)
        if widget_key in self._tracking:
            try:
                self._tracking[widget_key]['last_value'] = self._tracking[widget_key]['getter']()
            except Exception as e:
                print(f"[TRACKER] Error updating tracked value: {e}")
    
    def clear_tracking(self):
        """Очистить всё отслеживание"""
        self._tracking.clear()
    
    def set_restoring(self, restoring: bool):
        """Установить флаг восстановления (для загрузки без создания команд)"""
        self._is_restoring = restoring


# ══════════════════════════════════════════════════════════
#  ГЛАВНОЕ ОКНО
# ══════════════════════════════════════════════════════════

class ProjectTab(QWidget):
    """
    Один проект = одна вкладка.
    Содержит собственную сцену, вид, историю, браузер-менеджер и переменные.
    """
    def __init__(self, project_id: str = "", parent=None):
        super().__init__(parent)
        self.project_id = project_id or str(uuid.uuid4())[:8]

        # Независимые ресурсы проекта
        from constructor.browser_module import ProjectBrowserManager, BrowserManager
        self._base_browser_manager = BrowserManager()
        self.browser_manager = ProjectBrowserManager(
            self.project_id, self._base_browser_manager
        )
        self.skill_registry = SkillRegistry()
        self.variables: dict = {}          # Переменные проекта
        # workflow будет создан в _add_project_tab, не здесь
        self.workflow: AgentWorkflow | None = None
        self.project_path: str = ""
        self._project_root: str = ""
        self._modified = False  # Явно сбрасываем флаг изменений при создании нового проекта
        self._autosave_path: str = ""  # Добавляем если отсутствует

        # Сцена и вид (будут инициализированы в _build_canvas)
        self.scene: WorkflowScene | None = None
        self.view: WorkflowView | None = None
        self._history = HistoryManager()
        
        # ═══ Runtime для каждого проекта ОТДЕЛЬНЫЙ ═══
        self._runtime_thread: 'WorkflowRuntime | None' = None
        self._deferred_rendering: bool = False  # Без анимации
 
        self._build_ui()

    def _build_ui(self):
        from constructor.browser_module import BrowserTrayPanel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Канвас
        self.scene = WorkflowScene()
        self.view = WorkflowView(self.scene, self)
        
        # ═══ КРИТИЧЕСКИ: инициализируем workflow здесь, где сцена уже создана ═══
        from services.agent_models import AgentWorkflow
        self.workflow = AgentWorkflow()
        self.scene.set_workflow(self.workflow)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.view, 1)
        # _main_window будет установлен снаружи после создания ProjectTab
        self.scene._main_window = None

        # Трей браузеров проекта
        self.tray_panel = BrowserTrayPanel(self._base_browser_manager, self)
        self.tray_panel.setVisible(False)   # Скрыт пока нет браузеров
        # FIX: Жестко ограничиваем высоту трей панели (max 120px) и фиксируем политику
        from PyQt6.QtWidgets import QSizePolicy
        self.tray_panel.setMaximumHeight(120)
        self.tray_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.tray_panel, 0, Qt.AlignmentFlag.AlignBottom)
    
    def resizeEvent(self, event):
        """Переопределяем чтобы предотвратить появление пустой области при ресайзе"""
        super().resizeEvent(event)
        # FIX: Если трей виден, принудительно ограничиваем его высоту
        if self.tray_panel.isVisible():
            self.tray_panel.setMaximumHeight(120)
            self.tray_panel.setFixedHeight(min(self.tray_panel.sizeHint().height(), 120))
    
    def send_browser_to_tray(self, instance_id: str, label: str = ""):
        """Отправить браузер в трей + полностью скрыть окно"""
        # FIX: Блокируем обновление layout на время добавления
        self.layout().setEnabled(False)
        
        self.tray_panel.add_instance(instance_id, label or "Browser")
        self.tray_panel.setVisible(True)
        
        inst = self.browser_manager.get_instance(instance_id)
        if inst:
            # Убеждаемся, что окно действительно скрыто
            inst.minimize_window()           # ваш текущий метод
            QTimer.singleShot(800, lambda: inst.hide_window() if hasattr(inst, 'hide_window') else None)
    
        # FIX: Включаем layout обратно и принудительно обновляем только эту панель
        self.layout().setEnabled(True)
        self.tray_panel.updateGeometry()
        # Не трогаем resize/main window
    
    def _activate_local_layout(self):
        """Активировать layout этого таба без изменения размера окна"""
        if self.layout():
            self.layout().activate()
        # Не вызываем adjustSize() чтобы не менять размер главного окна
    
    def _fix_tray_layout(self):
        """Устаревший метод - делегируем локальной активации"""
        self._activate_local_layout()

    def remove_from_tray(self, instance_id: str):
        """Удалить браузер из трея и скрыть панель если пусто"""
        if hasattr(self.tray_panel, 'remove_instance'):
            self.tray_panel.remove_instance(instance_id)
        # Скрываем панель если в ней нет браузеров
        if hasattr(self.tray_panel, 'count') and self.tray_panel.count() == 0:
            self.tray_panel.setVisible(False)
            self._fix_tray_layout()
        elif hasattr(self.tray_panel, 'is_empty') and self.tray_panel.is_empty():
            self.tray_panel.setVisible(False)
            self._fix_tray_layout()
    
    def close_all_browsers(self):
        self.browser_manager.close_all()
        # FIX: Скрываем трей и сбрасываем фиксацию высоты
        self.tray_panel.setVisible(False)
        # Если есть метод очистки - используем его
        if hasattr(self.tray_panel, 'clear'):
            self.tray_panel.clear()
        elif hasattr(self.tray_panel, 'clear_all'):
            self.tray_panel.clear_all()
        # FIX: Сбрасываем ограничения высоты при скрытии
        self.tray_panel.setMaximumHeight(16777215)  # Qt default unlimited
        self.tray_panel.setMinimumHeight(0)

class AgentConstructorWindow(QMainWindow):
    """
    Visual AI Agent Workflow Editor.
    Opened from main window via '🤖 Конструктор агентов' button.
    """

    def __init__(self, settings=None, parent=None, model_manager=None, 
                 skill_registry=None, project_manager=None, logger=None):
        super().__init__(parent)
        self.setWindowTitle(tr("🤖 Конструктор AI-агентов — AI Code Sherlock"))
        
        # ── Менеджер проектов (многопоточный) ──────────────
        self._project_exec_manager = ProjectExecutionManager.instance(self)
        self._project_dashboard: Optional[ProjectDashboard] = None
        
        # Внешние сервисы
        self._model_manager = model_manager
        self._project_manager = project_manager
        self._external_logger = logger
        
        # Инициализация runtime engine (лениво)
        self._runtime: WorkflowRuntimeEngine | None = None
        
        # Проектный режим
        self._project_mode = False
        self._auto_execute_on_save = False
        # ← Глобальные переменные, разделяемые между всеми проектами
        if not hasattr(AgentConstructorWindow, '_global_shared_vars'):
            AgentConstructorWindow._global_shared_vars: dict = {}
        
        # Восстановление потерянных базовых настроек
        self.setMinimumSize(1200, 700)
        self.resize(1500, 850)
        self._tool_configs = {}  # Initialize tool configs storage
        self._snippet_config_before_edit = {}
        self._snippet_undo_pending = False
        self._settings = settings
        self._skill_registry = skill_registry if skill_registry else SkillRegistry()
        self._workflow = AgentWorkflow()
        self._file_path: str = ""
        # ── Браузерный модуль ─────────────────────────────────────
        self._browser_manager = BrowserManager.get()
        self._browser_profiles = BrowserProfileManager()
        
        # Устанавливаем корень для профилей (отложено, _project_root будет установлен позже)
        # self._browser_profiles.set_root(self._project_root)  # <-- ПЕРЕНЕСЕНО ПОСЛЕ _build_ui
        
        pass  # self._log_msg(f"🌐 Browser module ready: manager={self._browser_manager is not None}")  # ПЕРЕНЕСТИ ПОСЛЕ self._build_ui()
        self._history = HistoryManager()
        self._snippet_tracker = SnippetWidgetTracker(self._history, self)
        # _runtime_thread ПЕРЕНЕСЁН в ProjectTab — у каждого проекта свой!
        self._is_modified = False  # Флаг несохранённых изменений
        
        # Подключаем отслеживание изменений через историю
        self._history.push = self._wrap_history_push(self._history.push)
        
        # Инициализация UI (КРИТИЧЕСКИ ВАЖНО!)
        self._build_ui()
        
        # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
        # Полный перевод сразу после создания UI
        QTimer.singleShot(0, lambda: _retranslate_widget(self))
        QTimer.singleShot(50, self._on_language_changed)   # гарантируем перевод всего
        # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

        # ── Логирование браузера ...
        self._browser_manager.log_signal.connect(self._log_msg)
        
        # Устанавливаем корень для профилей (ТЕПЕРЬ _project_root доступен через property)
        if self._project_root:
            self._browser_profiles.set_root(self._project_root)
            self._log_msg(f"🌐 Browser profiles root: {self._project_root}")
        
        self._log_msg(f"🌐 Browser module ready: manager={getattr(self, '_browser_module_ready_flag', False)}")
        
        # Глобальный перехватчик исключений для отладки крашей
        import sys
        def exception_hook(exctype, value, traceback_obj):
            import traceback
            error_msg = ''.join(traceback.format_exception(exctype, value, traceback_obj))
            print(f"=== CRITICAL ERROR ===\n{error_msg}", flush=True)
            try:
                if hasattr(self, '_log_msg'):
                    self._log_msg(f"💥 CRASH: {str(value)[:200]}")
            except:
                pass
            sys.__excepthook__(exctype, value, traceback_obj)
        sys.excepthook = exception_hook
        self._connect_signals()
        self._new_workflow()

        try:
            register_theme_refresh(self._refresh_styles)
        except Exception:
            pass
        try:
            _i18n_register_listener(self._on_language_changed)
        except Exception:
            pass
    
    # ═══ Прокси-свойство: _runtime_thread теперь живёт в ProjectTab ═══
    @property
    def _runtime_thread(self):
        if not hasattr(self, '_project_tabs'):
            return None  # Ещё не создан UI
        tab = self._current_project_tab()
        return tab._runtime_thread if tab else None
 
    @_runtime_thread.setter
    def _runtime_thread(self, value):
        if not hasattr(self, '_project_tabs'):
            return  # Ещё не создан UI, игнорируем
        tab = self._current_project_tab()
        if tab:
            tab._runtime_thread = value
    
    def _build_ui(self):
        """Build the main UI layout for Agent Constructor"""
        # Верхняя панель управления (Toolbar)
        toolbar = QToolBar("Управление проектом")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        act_new = toolbar.addAction(tr("📄 Новый"))
        act_new.triggered.connect(self._new_workflow)
        
        # === РАБОЧАЯ ДИРЕКТОРИЯ ===
        toolbar.addSeparator()
        lbl_dir = QLabel(tr("📁 Рабочая папка:"))
        toolbar.addWidget(lbl_dir)
        
        self._fld_working_dir = QLineEdit()
        self._fld_working_dir.setPlaceholderText(tr("Выберите папку для создания файлов..."))
        self._fld_working_dir.setMinimumWidth(300)
        self._fld_working_dir.textChanged.connect(self._on_working_dir_changed)
        toolbar.addWidget(self._fld_working_dir)
        
        btn_browse = QPushButton(tr("Обзор..."))
        btn_browse.clicked.connect(self._browse_working_dir)
        toolbar.addWidget(btn_browse)

        btn_new_folder = QPushButton(tr("📁+"))
        btn_new_folder.setToolTip(tr("Создать новую подпапку с датой-временем в текущей рабочей папке"))
        btn_new_folder.clicked.connect(self._create_dated_subfolder)
        toolbar.addWidget(btn_new_folder)

        btn_open_dir = QPushButton(tr("Открыть"))
        btn_open_dir.clicked.connect(self._open_working_dir)
        toolbar.addWidget(btn_open_dir)

        btn_save_project = QPushButton(tr("💾 Сохранить"))
        btn_save_project.setToolTip(tr("Сохранить путь рабочей папки в проект workflow"))
        btn_save_project.clicked.connect(self._save_project_root)
        toolbar.addWidget(btn_save_project)

        act_open = toolbar.addAction(tr("📂 Открыть"))
        act_open.triggered.connect(self._open_workflow)

        act_save = toolbar.addAction(tr("💾 Сохранить"))
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._save_workflow)

        toolbar.addSeparator()

        act_run = toolbar.addAction(tr("⚡ Запуск"))
        act_run.triggered.connect(self._run_workflow)

        # ── Глобальные настройки ──────────────────────────────
        toolbar.addSeparator()
        btn_global_settings = QPushButton("⚙")
        btn_global_settings.setToolTip(
            "Глобальные настройки выполнения:\n"
            "потоки, ОЗУ, браузеры, семафоры моделей"
        )
        btn_global_settings.setFixedWidth(32)
        btn_global_settings.clicked.connect(self._open_global_settings)
        toolbar.addWidget(btn_global_settings)
 
        # ── Кнопка менеджера проектов ─────────────────────────
        btn_dashboard = QPushButton(tr("📊 Менеджер"))
        btn_dashboard.setToolTip(tr("Менеджер проектов — управление всеми проектами\nЗапуск, остановка, расписание, потоки"))
        btn_dashboard.clicked.connect(self._open_dashboard)
        toolbar.addWidget(btn_dashboard)
 
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # LEFT: Palette (AI Агенты + Сниппеты + Скиллы)
        left_panel = self._build_palette()
        left_panel.setStyleSheet(f"background: {get_color('bg1')};")
        main_splitter.addWidget(left_panel)

        # CENTER-LEFT: Переменные проекта + Заметки
        self._vars_panel = ProjectVariablesPanel(self)
        self._vars_panel.setStyleSheet(f"background: {get_color('bg1')};")
        self._vars_panel.variables_changed.connect(self._mark_modified_from_props)
        self._vars_panel.variables_changed.connect(self._on_vars_panel_changed)
        self._vars_panel.setMinimumWidth(250)
        self._vars_panel.setMaximumWidth(500)
        main_splitter.addWidget(self._vars_panel)

        # CENTER: Canvas + Minimap + Zoom
        # ═══ Вкладки проектов ═══
        self._project_tabs = QTabWidget()
        self._project_tabs.setTabsClosable(True)
        self._project_tabs.setMovable(True)
        self._project_tabs.tabCloseRequested.connect(self._close_project_tab)
        self._project_tabs.currentChanged.connect(self._on_tab_switched)

        # Первый проект — создаём сразу
        self._add_project_tab(tr("Новый проект"))

        btn_new_tab = QPushButton("＋")
        btn_new_tab.setFixedWidth(28)
        btn_new_tab.setToolTip(tr("Новый проект"))
        btn_new_tab.clicked.connect(lambda: self._add_project_tab())
        self._project_tabs.setCornerWidget(btn_new_tab)

        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self._project_tabs, stretch=1)

        # ═══ Inline-панель списков и таблиц ═══
        canvas_layout.addWidget(self._build_lists_tables_inline_panel())

        if hasattr(self, '_build_debug_panel'):
            canvas_layout.addWidget(self._build_debug_panel())

        # ═══ Панель зума ═══
        zoom_panel = QHBoxLayout()
        zoom_panel.setContentsMargins(4, 2, 4, 2)

        btn_zoom_in = QPushButton(tr("🔍+"))
        btn_zoom_in.setFixedWidth(36)
        btn_zoom_in.setToolTip(tr("Увеличить (Ctrl+колесо)"))
        btn_zoom_in.clicked.connect(lambda: self._zoom(1.25))

        btn_zoom_out = QPushButton(tr("🔍−"))
        btn_zoom_out.setFixedWidth(36)
        btn_zoom_out.setToolTip(tr("Уменьшить"))
        btn_zoom_out.clicked.connect(lambda: self._zoom(0.8))

        btn_zoom_fit = QPushButton(tr("⊞"))
        btn_zoom_fit.setFixedWidth(36)
        btn_zoom_fit.setToolTip(tr("Вместить всё"))
        btn_zoom_fit.clicked.connect(self._zoom_fit)

        btn_zoom_100 = QPushButton(tr("100%"))
        btn_zoom_100.setFixedWidth(44)
        btn_zoom_100.setToolTip(tr("Сбросить масштаб"))
        btn_zoom_100.clicked.connect(self._zoom_reset)

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 400)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setToolTip(tr("Масштаб"))
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setFixedWidth(40)
        self._lbl_zoom.setStyleSheet("color: #A9B1D6; font-size: 10px;")

        zoom_panel.addWidget(btn_zoom_out)
        zoom_panel.addWidget(self._zoom_slider)
        zoom_panel.addWidget(btn_zoom_in)
        zoom_panel.addWidget(self._lbl_zoom)
        zoom_panel.addWidget(btn_zoom_fit)
        zoom_panel.addWidget(btn_zoom_100)
        zoom_panel.addStretch()

        # Кнопки навигации миникарты
        btn_go_start = QPushButton(tr("⏮ Начало"))
        btn_go_start.setFixedWidth(80)
        btn_go_start.setToolTip(tr("Перейти к начальному узлу"))
        btn_go_start.clicked.connect(self._navigate_to_start)
        
        btn_go_end = QPushButton(tr("Конец ⏭"))
        btn_go_end.setFixedWidth(80)
        btn_go_end.setToolTip(tr("Перейти к последнему узлу"))
        btn_go_end.clicked.connect(self._navigate_to_end)
        
        zoom_panel.addWidget(btn_go_start)
        zoom_panel.addWidget(btn_go_end)

        canvas_layout.addLayout(zoom_panel)

        # ═══ Миникарта ═══
        self._minimap = MiniMapWidget(self._scene, self._view, self)
        self._minimap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        canvas_layout.addWidget(self._minimap, alignment=Qt.AlignmentFlag.AlignHCenter)

        main_splitter.addWidget(canvas_container)
        main_splitter.setStretchFactor(main_splitter.count() - 1, 1)

        # RIGHT: Properties
        self._props = NodePropertiesPanel(self._skill_registry, self)
        main_splitter.addWidget(self._props)

        main_splitter.setSizes([200, 280, 650, 400])
        main_splitter.setCollapsible(0, False)  # Левая палитра не сворачивается
        main_splitter.setCollapsible(1, False)  # Переменные не сворачиваются
        main_splitter.setCollapsible(3, False)  # Правая панель не сворачивается
        
        # BOTTOM: Log
        bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        bottom_splitter.addWidget(main_splitter)
        
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("ЛОГ"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        # === ПАНЕЛЬ ДИАЛОГА АГЕНТА (Agent Chat) ===
        self._agent_chat = QTextEdit()
        self._agent_chat.setReadOnly(True)
        self._agent_chat.setPlaceholderText(tr("Здесь будет отображаться диалог с AI агентами..."))
        self._agent_chat.setMaximumHeight(200)
        self._agent_chat.setStyleSheet(f"""
            QTextEdit {{
                background: {get_color('bg0')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
                font-family: 'JetBrains Mono', Consolas, monospace;
                font-size: 11px;
            }}
        """)

        # Табы для переключения между логом системы и диалогом агентов
        self._bottom_tabs = QTabWidget()
        self._bottom_tabs.addTab(self._log, tr("📋 Системный лог"))
        self._bottom_tabs.addTab(self._agent_chat, tr("💬 Диалог агентов"))

        # ── Браузерная панель ─────────────────────────────────────
        self._browser_panel = BrowserInstancePanel(self._browser_manager, self)
        # Встраивание теперь происходит автоматически через сигнал instance_launched
        # (по-ячеечно в _auto_embed_if_needed)
        self._bottom_tabs.addTab(self._browser_panel, tr("🌐 Браузеры"))

        # ── Панель открытых программ (аналог BrowserInstancePanel) ──
        from constructor.browser_module import ProgramInstancePanel
        self._program_panel = ProgramInstancePanel(self)
        self._bottom_tabs.addTab(self._program_panel, tr("🖥 Программы"))

        bottom_splitter.addWidget(self._bottom_tabs)
        bottom_splitter.addWidget(log_widget)
        bottom_splitter.setSizes([600, 150])
        
        self.setCentralWidget(bottom_splitter)
        
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
    
    def _on_working_dir_changed(self, text: str):
        """Обработчик изменения рабочей папки в поле ввода."""
        # Сохраняем в текущий ProjectTab
        tab = self._current_project_tab()
        if tab:
            tab._project_root = text
        # Обновляем корень профилей браузера
        if text and os.path.exists(text):
            self._browser_profiles.set_root(text)
    
    def _on_vars_panel_changed(self):
        """Обновить inline-панель при изменении списков/таблиц."""
        if getattr(self, '_lt_inline_expanded', False):
            QTimer.singleShot(50, self._refresh_lt_inline_chips)
    
    def _open_global_settings(self):
        """Открыть диалог глобальных настроек."""
        dlg = GlobalSettingsDialog(self)
        dlg.exec()

    def _load_global_settings(self):
        """Загрузить настройки с диска и применить."""
        GlobalSettings.load()
        GlobalSettings._apply()
    
    def _retranslate_snippet_labels(self):
        """Перевести все динамические label'ы сниппетов."""
        if hasattr(self, '_translatable_labels'):
            for lbl in self._translatable_labels:
                key = lbl.property("_i18n_key")
                if key:
                    lbl.setText(tr(key))
        
        # Перевести заголовок группы сниппета
        if hasattr(self, '_snippet_group'):
            node = self._props._node if hasattr(self, '_props') else None
            if node:
                schema = SNIPPET_SCHEMA.get(node.agent_type, {})
                title_key = schema.get('title_key', '')
                if title_key:
                    self._snippet_group.setTitle(tr(title_key))
    
    @property
    def _project_root(self):
        """Получить project_root текущего активного таба."""
        tab = self._current_project_tab()
        if tab:
            return tab._project_root
        return ""

    @_project_root.setter
    def _project_root(self, value):
        """Установить project_root в текущий активный таб."""
        tab = self._current_project_tab()
        if tab:
            tab._project_root = value
    
    def _build_tower_from_selection(self):
        """Выстроить выбранные сниппеты в вертикальную башню и соединить стрелками."""
        selected = sorted(
            [item for item in self._scene.selectedItems() if isinstance(item, AgentNodeItem)],
            key=lambda it: it.pos().y()  # сортировка сверху вниз по текущей позиции
        )
        if len(selected) < 2:
            self._log_msg("⚠ Выберите минимум 2 сниппета для башни")
            return
        
        PADDING = 10  # отступ между блоками
        
        # Выравниваем по X первого элемента, расставляем вертикально
        base_x = selected[0].pos().x()
        cur_y = selected[0].pos().y()
        
        old_positions = {}
        new_positions = {}
        
        for item in selected:
            old_positions[item.node.id] = item.pos()
            new_positions[item.node.id] = QPointF(base_x, cur_y)
            cur_y += item.node.height + PADDING
        
        # Применяем позиции
        for item in selected:
            np = new_positions[item.node.id]
            item.setPos(np)
            item.node.x = np.x()
            item.node.y = np.y()
        
        self._scene.update_edges()
        
        # Создаём стрелки между соседними нодами (если ещё нет)
        for i in range(len(selected) - 1):
            src = selected[i].node
            tgt = selected[i + 1].node
            # Проверяем нет ли уже связи
            already = any(e.source_id == src.id and e.target_id == tgt.id 
                          for e in self._workflow.edges)
            if not already:
                edge = AgentEdge(
                    source_id=src.id,
                    target_id=tgt.id,
                    condition=EdgeCondition.ALWAYS,
                    label="",
                )
                self._scene.request_edge_creation(edge, src, tgt)
        
        # Undo
        _old = dict(old_positions)
        _new = dict(new_positions)
        _items = {item.node.id: item for item in selected}
        scene = self._scene
        
        def _undo_tower():
            for nid, op in _old.items():
                it = _items.get(nid)
                if it:
                    it.setPos(op); it.node.x = op.x(); it.node.y = op.y()
            scene.update_edges(); scene.update()
        
        def _redo_tower():
            for nid, np in _new.items():
                it = _items.get(nid)
                if it:
                    it.setPos(np); it.node.x = np.x(); it.node.y = np.y()
            scene.update_edges(); scene.update()
        
        self._history.push(_redo_tower, _undo_tower, f"Башня из {len(selected)} нод")
        self._log_msg(f"🗼 Башня: {len(selected)} сниппетов выстроены и соединены")
    
    def eventFilter(self, obj, event):
        """Отслеживаем фокус для сохранения состояния перед редактированием (для undo)"""
        if event.type() == QEvent.Type.FocusIn:
            # Проверяем, является ли объект одним из виджетов сниппета
            if hasattr(self, '_snippet_widgets') and not getattr(self, '_snippet_loading', False):
                for key, widget in self._snippet_widgets.items():
                    if widget is obj:
                        # Сохраняем текущее состояние перед редактированием
                        self._snippet_config_before_edit = self._get_current_snippet_config()
                        self._snippet_undo_pending = True
                        break
        return super().eventFilter(obj, event)
    
    def _update_project_variable(self, name: str, value: str):
        """Callback для runtime — обновляет переменную проекта и UI"""
        # Обновляем в данных
        if self._workflow and name in self._workflow.project_variables:
            self._workflow.project_variables[name]['value'] = str(value)
        
        # Обновляем UI таблицы
        if hasattr(self, '_vars_panel'):
            self._vars_panel._sync_variable_to_ui(name, str(value))
            # ═══ ФИКС: дополнительно обновляем всю таблицу для надежности ═══
            self._vars_panel._var_table.viewport().update()
    
    def _on_runtime_list_table_updated(self, kind: str, name: str, count: int):
        """Callback от runtime — обновляет данные списка/таблицы в _vars_panel и перерисовывает чипы."""
        if not hasattr(self, '_vars_panel') or not self._workflow:
            return
        meta = getattr(self._workflow, 'metadata', {}) or {}
        if isinstance(meta, str):
            try:
                import json; meta = json.loads(meta)
            except Exception:
                meta = {}
        if kind == 'list':
            self._vars_panel._project_lists = meta.get('project_lists', [])
        else:
            self._vars_panel._project_tables = meta.get('project_tables', [])
        if getattr(self, '_lt_inline_expanded', False):
            self._refresh_lt_inline_chips()
        # Принудительно обновить виджет списков/таблиц если он открыт
        if hasattr(self._vars_panel, '_refresh_lists_widget'):
            self._vars_panel._refresh_lists_widget()
    
    def _delayed_load_snippet_config(self, node):
        """Отложенная загрузка конфига сниппета (после создания всех виджетов)."""
        if node is None or not hasattr(node, 'id'):
            print(f"[DELAYED LOAD] node is None или не валиден, пропускаю")
            return
        self._load_snippet_config_to_widgets(node)
        self._snippet_loading = False  # Разблокируем flush после реальной загрузки
        # Обновляем видимость полей
        if hasattr(self, '_update_code_source_visibility'):
            self._update_code_source_visibility()
        if hasattr(self, '_update_if_condition_visibility'):
            self._update_if_condition_visibility()
    
    def _get_vars_table_data(self) -> list:
        """Сериализовать данные таблицы переменных"""
        data = []
        for row in range(self._vars_table.rowCount()):
            name_item = self._vars_table.item(row, 0)
            value_item = self._vars_table.item(row, 1)
            type_widget = self._vars_table.cellWidget(row, 2)
            desc_item = self._vars_table.item(row, 3)
            
            row_data = {
                'name': name_item.text() if name_item else '',
                'value': value_item.text() if value_item else '',
                'type': type_widget.currentText() if type_widget else 'string',
                'description': desc_item.text() if desc_item else ''
            }
            data.append(row_data)
        return data
    
    def _set_vars_table_data(self, data: list):
        """Восстановить данные таблицы переменных"""
        self._vars_table.blockSignals(True)
        self._vars_table.setRowCount(0)
        
        for row_data in data:
            row = self._vars_table.rowCount()
            self._vars_table.insertRow(row)
            
            # Имя
            name_item = QTableWidgetItem(row_data.get('name', ''))
            self._vars_table.setItem(row, 0, name_item)
            # Значение
            value_item = QTableWidgetItem(row_data.get('value', ''))
            self._vars_table.setItem(row, 1, value_item)
            # Тип
            type_combo = QComboBox()
            type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
            idx = type_combo.findText(row_data.get('type', 'string'))
            type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._vars_table.setCellWidget(row, 2, type_combo)
            # Описание
            desc_item = QTableWidgetItem(row_data.get('description', ''))
            self._vars_table.setItem(row, 3, desc_item)
        
        self._vars_table.blockSignals(False)

    def _add_variable_row(self):
        """Добавить строку переменной в таблицу сниппета"""
        if not hasattr(self, '_vars_table'):
            return
        row = self._vars_table.rowCount()
        self._vars_table.insertRow(row)
        
        # Имя
        name_item = QTableWidgetItem(f"var_{row+1}")
        self._vars_table.setItem(row, 0, name_item)
        
        # Значение
        val_item = QTableWidgetItem("")
        self._vars_table.setItem(row, 1, val_item)
        
        # Тип (комбобокс)
        type_combo = QComboBox()
        type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
        self._vars_table.setCellWidget(row, 2, type_combo)
        
        # Описание
        desc_item = QTableWidgetItem("")
        self._vars_table.setItem(row, 3, desc_item)
        
        # Подключаем сигнал изменения
        self._vars_table.cellChanged.connect(self._on_snippet_widget_changed)
        # Подключаем трекер для undo/redo (трекаем всю таблицу как единое целое)
        self._snippet_tracker.track_widget(
            self._vars_table,
            lambda w=self._vars_table: self._get_vars_table_data(),
            lambda v, w=self._vars_table: self._set_vars_table_data(v),
            "Изменение таблицы переменных"
        )

    def _remove_variable_row(self):
        """Удалить выбранную строку переменной"""
        if not hasattr(self, '_vars_table'):
            return
        current = self._vars_table.currentRow()
        if current >= 0:
            self._vars_table.removeRow(current)
            self._on_snippet_widget_changed()
    
    def _copy_var_reference(self):
        """Копировать ссылку {var_name} на выбранную переменную в буфер обмена."""
        if not hasattr(self, '_vars_table'):
            return
        current = self._vars_table.currentRow()
        if current < 0:
            return
        name_item = self._vars_table.item(current, 0)
        if name_item and name_item.text().strip():
            ref = "{" + name_item.text().strip() + "}"
            QApplication.clipboard().setText(ref)
            self._log_msg(f"📋 Скопировано: {ref}")

    def _move_var_row_up(self):
        """Переместить выбранную строку переменной вверх."""
        if not hasattr(self, '_vars_table'):
            return
        row = self._vars_table.currentRow()
        if row <= 0:
            return
        self._swap_var_rows(row, row - 1)
        self._vars_table.setCurrentCell(row - 1, 0)
        self._on_snippet_widget_changed()

    def _move_var_row_down(self):
        """Переместить выбранную строку переменной вниз."""
        if not hasattr(self, '_vars_table'):
            return
        row = self._vars_table.currentRow()
        if row < 0 or row >= self._vars_table.rowCount() - 1:
            return
        self._swap_var_rows(row, row + 1)
        self._vars_table.setCurrentCell(row + 1, 0)
        self._on_snippet_widget_changed()

    def _swap_var_rows(self, row_a: int, row_b: int):
        """Поменять местами две строки в таблице переменных."""
        table = self._vars_table
        table.blockSignals(True)
        for col in [0, 1, 3]:  # Имя, Значение, Описание
            item_a = table.takeItem(row_a, col)
            item_b = table.takeItem(row_b, col)
            if item_a and item_b:
                table.setItem(row_a, col, item_b)
                table.setItem(row_b, col, item_a)
            elif item_a:
                table.setItem(row_b, col, item_a)
                table.setItem(row_a, col, QTableWidgetItem(""))
            elif item_b:
                table.setItem(row_a, col, item_b)
                table.setItem(row_b, col, QTableWidgetItem(""))
        # Тип — это cellWidget (QComboBox), меняем индексы
        combo_a = table.cellWidget(row_a, 2)
        combo_b = table.cellWidget(row_b, 2)
        idx_a = combo_a.currentIndex() if combo_a else 0
        idx_b = combo_b.currentIndex() if combo_b else 0
        if combo_a:
            combo_a.setCurrentIndex(idx_b)
        if combo_b:
            combo_b.setCurrentIndex(idx_a)
        table.blockSignals(False)

    def _vars_table_context_menu(self, pos):
        """Контекстное меню для таблицы переменных."""
        if not hasattr(self, '_vars_table'):
            return
        menu = QMenu(self)
        row = self._vars_table.rowAt(pos.y())
        
        act_add = menu.addAction(tr("➕ Добавить переменную"))
        act_add.triggered.connect(self._add_variable_row)
        
        if row >= 0:
            name_item = self._vars_table.item(row, 0)
            var_name = name_item.text().strip() if name_item else ""
            
            act_del = menu.addAction(tr("🗑 Удалить строку"))
            act_del.triggered.connect(self._remove_variable_row)
            
            if var_name:
                menu.addSeparator()
                act_copy_ref = menu.addAction(tr("📋 Копировать {{{var}}}", var=var_name))
                act_copy_ref.triggered.connect(self._copy_var_reference)
                
                act_copy_val = menu.addAction(tr("📋 Копировать значение"))
                act_copy_val.triggered.connect(lambda: self._copy_var_value(row))
            
            menu.addSeparator()
            if row > 0:
                act_up = menu.addAction(tr("▲ Переместить вверх"))
                act_up.triggered.connect(self._move_var_row_up)
            if row < self._vars_table.rowCount() - 1:
                act_down = menu.addAction(tr("▼ Переместить вниз"))
                act_down.triggered.connect(self._move_var_row_down)
        
        menu.addSeparator()
        act_clear = menu.addAction(tr("🧹 Очистить всё"))
        act_clear.triggered.connect(lambda: (
            self._vars_table.setRowCount(0),
            self._on_snippet_widget_changed()
        ))
        
        menu.exec(self._vars_table.viewport().mapToGlobal(pos))
    def _copy_var_value(self, row: int):
        """Скопировать значение переменной из таблицы."""
        val_item = self._vars_table.item(row, 1)
        if val_item:
            QApplication.clipboard().setText(val_item.text())

    def _refresh_context_vars_combo(self):
        """Обновить комбобокс переменных контекста из runtime."""
        if not hasattr(self, '_cmb_ctx_vars'):
            return
        self._cmb_ctx_vars.clear()
        self._cmb_ctx_vars.addItem("— выбрать —", None)
        # Пытаемся получить контекст из runtime
        runtime = getattr(self, '_runtime', None)
        if runtime and hasattr(runtime, '_context'):
            for key, val in runtime._context.items():
                if not key.startswith('_'):
                    display = f"{key} = {str(val)[:40]}"
                    self._cmb_ctx_vars.addItem(display, key)

    def _insert_context_var_to_table(self):
        """Вставить выбранную переменную контекста как новую строку в таблицу."""
        if not hasattr(self, '_cmb_ctx_vars') or not hasattr(self, '_vars_table'):
            return
        key = self._cmb_ctx_vars.currentData()
        if not key:
            return
        # Проверяем, нет ли уже такой переменной
        for row in range(self._vars_table.rowCount()):
            item = self._vars_table.item(row, 0)
            if item and item.text().strip() == key:
                self._vars_table.setCurrentCell(row, 0)
                return
        # Добавляем
        row = self._vars_table.rowCount()
        self._vars_table.insertRow(row)
        self._vars_table.setItem(row, 0, QTableWidgetItem(key))
        # Значение из контекста
        runtime = getattr(self, '_runtime', None)
        val = ""
        if runtime and hasattr(runtime, '_context'):
            val = str(runtime._context.get(key, ""))
        self._vars_table.setItem(row, 1, QTableWidgetItem(val))
        type_combo = QComboBox()
        type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
        self._vars_table.setCellWidget(row, 2, type_combo)
        self._vars_table.setItem(row, 3, QTableWidgetItem(""))
        self._on_snippet_widget_changed()
    
    def _import_vars_from_csv(self):
        """Импорт переменных из CSV/TSV файла в таблицу."""
        start_dir = self._project_root or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт переменных из файла", start_dir,
            "CSV/TSV Files (*.csv *.tsv *.txt);;All Files (*)"
        )
        if not path:
            return
        self._load_csv_to_vars_table(path)

    def _load_csv_to_vars_table(self, path: str):
        """Загрузить CSV/TSV файл в таблицу переменных."""
        import csv
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                # Автоопределение разделителя
                sample = f.read(4096)
                f.seek(0)
                if '\t' in sample:
                    delimiter = '\t'
                elif ';' in sample:
                    delimiter = ';'
                else:
                    delimiter = ','
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
            
            if not rows:
                QMessageBox.warning(self, tr("Пусто"), tr("Файл пуст."))
                return
            
            # Определяем, есть ли заголовок
            header = rows[0]
            header_lower = [h.strip().lower() for h in header]
            known_headers = {'name', 'имя', 'variable', 'переменная', 'var', 'имя переменной'}
            has_header = bool(known_headers & set(header_lower))
            data_rows = rows[1:] if has_header else rows
            
            if not data_rows:
                QMessageBox.warning(self, tr("Пусто"), tr("Нет строк данных."))
                return
            
            self._vars_table.blockSignals(True)
            self._vars_table.setRowCount(0)
            
            for row_data in data_rows:
                if not row_data or not row_data[0].strip():
                    continue
                row = self._vars_table.rowCount()
                self._vars_table.insertRow(row)
                
                # Имя (колонка 0)
                self._vars_table.setItem(row, 0, QTableWidgetItem(row_data[0].strip()))
                # Значение (колонка 1)
                self._vars_table.setItem(row, 1, QTableWidgetItem(row_data[1].strip() if len(row_data) > 1 else ""))
                # Тип (колонка 2)
                type_combo = QComboBox()
                type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
                type_val = row_data[2].strip().lower() if len(row_data) > 2 else "string"
                idx = type_combo.findText(type_val)
                type_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self._vars_table.setCellWidget(row, 2, type_combo)
                # Описание (колонка 3)
                self._vars_table.setItem(row, 3, QTableWidgetItem(row_data[3].strip() if len(row_data) > 3 else ""))
            
            self._vars_table.blockSignals(False)
            self._on_snippet_widget_changed()
            self._log_msg(f"📥 Импортировано {self._vars_table.rowCount()} переменных из {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, tr("Ошибка импорта"), tr("Не удалось прочитать файл:\n") + str(e))

    def _export_vars_to_csv(self):
        """Экспорт переменных из таблицы в CSV файл."""
        if not hasattr(self, '_vars_table') or self._vars_table.rowCount() == 0:
            QMessageBox.information(self, tr("Пусто"), tr("Нет переменных для экспорта."))
            return
        
        start_dir = self._project_root or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт переменных в CSV", 
            os.path.join(start_dir, "variables.csv"),
            "CSV Files (*.csv);;TSV Files (*.tsv)"
        )
        if not path:
            return
        
        import csv
        delimiter = '\t' if path.endswith('.tsv') else ','
        try:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter=delimiter)
                writer.writerow(["Имя переменной", "Значение", "Тип", "Описание"])
                for row in range(self._vars_table.rowCount()):
                    name = self._vars_table.item(row, 0)
                    value = self._vars_table.item(row, 1)
                    type_w = self._vars_table.cellWidget(row, 2)
                    desc = self._vars_table.item(row, 3)
                    writer.writerow([
                        name.text() if name else "",
                        value.text() if value else "",
                        type_w.currentText() if type_w else "string",
                        desc.text() if desc else ""
                    ])
            self._log_msg(f"📤 Экспортировано {self._vars_table.rowCount()} переменных в {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, tr("Ошибка экспорта"), tr("Не удалось сохранить файл:\n") + str(e))

    def _browse_attached_table(self):
        """Выбрать CSV/TSV файл для прикрепления к сниппету."""
        start_dir = self._project_root or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Прикрепить файл таблицы с переменными", start_dir,
            "CSV/TSV Files (*.csv *.tsv *.txt);;All Files (*)"
        )
        if path:
            if self._project_root and path.startswith(self._project_root):
                path = os.path.relpath(path, self._project_root)
            self._fld_attached_table.setText(path)

    def _preview_attached_table(self):
        """Загрузить прикреплённый файл таблицы в виджет переменных (предпросмотр)."""
        if not hasattr(self, '_fld_attached_table'):
            return
        rel_path = self._fld_attached_table.text().strip()
        if not rel_path:
            QMessageBox.information(self, tr("Нет файла"), tr("Укажите путь к файлу таблицы."))
            return
        
        # Определяем полный путь
        if os.path.isabs(rel_path):
            full_path = rel_path
        else:
            full_path = os.path.join(self._project_root or "", rel_path)
        
        if not os.path.isfile(full_path):
            QMessageBox.warning(self, tr("Файл не найден"), tr("Не найден файл:\n") + str(full_path))
            return
        
        self._load_csv_to_vars_table(full_path)
    
    def _on_verification_toggled(self, state: int):
        enabled = state == Qt.CheckState.Checked.value
        self._cmb_verify_mode.setEnabled(enabled)
        self._txt_verify_prompt.setEnabled(enabled)
        self._chk_verify_strict.setEnabled(enabled)
        self._update_verify_model_visibility()
        
    def _update_verify_model_visibility(self):
        mode = self._cmb_verify_mode.currentData() if self._cmb_verify_mode.isEnabled() else None
        show_model = mode == "another_model"
        self._cmb_verify_model.setEnabled(show_model and self._chk_verify.isChecked())
    
    def _add_skill_to_node_direct(self, node: AgentNode, skill_id: str):
        """Добавить скилл к ноде напрямую (для контекстного меню)"""
        if skill_id not in node.skill_ids:
            node.skill_ids.append(skill_id)
            skill = self._skill_registry.get(skill_id)
            # Обновить визуал
            item = self._scene.get_node_item(node.id)
            if item:
                item.update()
            # Если нода выбрана - обновить панель
            if self._props._node is node:
                self._props._populate()
            self._log_msg(f"🔧 Скилл '{skill.name if skill else skill_id}' добавлен к {node.name}")
    
    def _add_skill_to_current_node(self):
        """Показать меню выбора скилла для добавления к текущей ноде"""
        if not self._props._node:
            return
        menu = QMenu(self)
        for skill in self._skill_registry.all_skills():
            act = menu.addAction(f"{skill.icon} {skill.name}")
            act.triggered.connect(lambda checked, s=skill: self._do_add_skill_to_current(s.id))
        btn = self._btn_add_skill
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
    
    def _do_add_skill_to_current(self, skill_id: str):
        """Добавить скилл к текущей выбранной ноде"""
        node = self._props._node
        if not node or skill_id in node.skill_ids:
            return
        node.skill_ids.append(skill_id)
        self._props._populate()
        self._props.node_changed.emit()
        skill = self._skill_registry.get(skill_id)
        self._log_msg(f"🔧 Скилл '{skill.name if skill else skill_id}' добавлен к {node.name}")
    
    # ── Обработка заметок ─────────────────────────────

    def _on_note_changed(self):
        """Обновить ноду-заметку при изменении полей."""
        node = self._props._node
        if not node or node.agent_type != AgentType.NOTE:
            return
        node.name = self._note_fld_title.text()
        node.note_content = self._note_txt_content.toPlainText()
        item = self._scene.get_node_item(node.id)
        if item:
            item.update()
        # Отмечаем изменение
        if not self._is_modified:
            self._is_modified = True
            self._update_window_title()

    def _pick_note_color(self):
        """Выбрать цвет заметки."""
        node = self._props._node
        if not node:
            return
        current = QColor(getattr(node, 'note_color', '#E0AF68'))
        color = QColorDialog.getColor(current, self, "Цвет заметки")
        if color.isValid():
            node.note_color = color.name()
            node.custom_color = color.name()  # Синхронизируем
            self._btn_note_color.setStyleSheet(f"background: {color.name()}; color: white; padding: 4px;")
            item = self._scene.get_node_item(node.id)
            if item:
                item.update()

    def _on_note_size_changed(self):
        """Изменить размер заметки на канвасе."""
        node = self._props._node
        if not node or node.agent_type != AgentType.NOTE:
            return
        node.width = self._note_spn_width.value()
        node.height = self._note_spn_height.value()
        item = self._scene.get_node_item(node.id)
        if item:
            item.setRect(0, 0, node.width, node.height)
            item.update()
            self._scene.update_edges()
    
    def _on_start_changed(self):
        """Обновить ноду PROJECT_START при изменении полей."""
        node = self._props._node
        if not node or node.agent_type != AgentType.PROJECT_START:
            return
        if not hasattr(node, 'snippet_config') or node.snippet_config is None:
            node.snippet_config = {}
        node.name = self._start_fld_heading.text()
        node.description = self._start_fld_desc.text()
        node.snippet_config['start_mode'] = self._start_cmb_mode.currentData() or 'simple'
        node.snippet_config['start_prompt'] = self._start_txt_prompt.toPlainText()
        # ═══ КРИТИЧНО: Явно сохраняем флаги как bool, не как строки ═══
        node.snippet_config['reset_vars'] = bool(self._start_chk_reset_vars.isChecked())
        node.snippet_config['reset_global_vars'] = bool(self._start_chk_reset_global.isChecked())
        node.snippet_config['clear_log'] = bool(self._start_chk_clear_log.isChecked())
        node.snippet_config['save_before'] = bool(self._start_chk_save_before.isChecked())
        # ═══ ДОБАВИТЬ: Сохраняем также в metadata для глобального доступа ═══
        if not hasattr(self._workflow, 'metadata'):
            self._workflow.metadata = {}
        self._workflow.metadata['start_config'] = {
            'reset_vars': node.snippet_config['reset_vars'],
            'reset_global_vars': node.snippet_config['reset_global_vars'],
            'clear_log': node.snippet_config['clear_log'],
            'save_before': node.snippet_config['save_before'],
        }
        item = self._scene.get_node_item(node.id)
        if item:
            item.update()
        if not self._is_modified:
            self._is_modified = True
            self._update_window_title()

    def _on_start_mode_changed(self):
        """Показать/скрыть поле инструкции в зависимости от режима старта."""
        is_with_model = (
            hasattr(self, '_start_cmb_mode') and
            self._start_cmb_mode.currentData() == 'with_model'
        )
        if hasattr(self, '_start_txt_prompt'):
            self._start_txt_prompt.setVisible(is_with_model)
        if hasattr(self, '_start_prompt_label'):
            self._start_prompt_label.setVisible(is_with_model)
        self._on_start_changed()

    def _pick_start_color(self):
        """Выбрать цвет ноды START."""
        node = self._props._node
        if not node:
            return
        current = QColor(node.custom_color if getattr(node, 'custom_color', '') else '#9ECE6A')
        color = QColorDialog.getColor(current, self, tr("Цвет старта"))
        if color.isValid():
            node.custom_color = color.name()
            self._btn_start_color.setStyleSheet(f"background: {color.name()}; color: #000; padding: 4px;")
            item = self._scene.get_node_item(node.id)
            if item:
                item._setup_visuals()
                item.update()
    
    def _pick_node_color(self):
        """Выбрать кастомный цвет для текущей ноды."""
        node = self._props._node
        if not node:
            return
        current = QColor(node.custom_color if getattr(node, 'custom_color', '') else _AGENT_COLORS.get(node.agent_type, "#565f89"))
        color = QColorDialog.getColor(current, self, "Цвет узла")
        if color.isValid():
            node.custom_color = color.name()
            self._btn_node_color.setStyleSheet(f"background: {color.name()}; color: white;")
            item = self._scene.get_node_item(node.id)
            if item:
                item._setup_visuals()
                item.update()

    def _reset_node_color(self):
        """Сбросить кастомный цвет ноды."""
        node = self._props._node
        if not node:
            return
        node.custom_color = ""
        self._btn_node_color.setStyleSheet("")
        item = self._scene.get_node_item(node.id)
        if item:
            item._setup_visuals()
            item.update()

    def _on_comment_changed(self, text):
        """Обновить комментарий ноды при вводе."""
        node = self._props._node
        if not node:
            return
        node.comment = text
        item = self._scene.get_node_item(node.id)
        if item:
            item.update()
    
    def _on_snippet_name_changed(self, *_):
        if getattr(self, '_snippet_loading', False):
            return
        node = self._props._node if hasattr(self, '_props') and self._props else None
        if not node or not hasattr(node, 'id'):
            return
        node.name = self._snippet_fld_name.text()
        # Обновляем canvas-лейбл
        item = self._scene.get_node_item(node.id)
        if item:
            item.update()
        self._mark_modified_from_props()

    def _on_snippet_desc_changed(self, *_):
        if getattr(self, '_snippet_loading', False):
            return
        node = self._props._node if hasattr(self, '_props') and self._props else None
        if not node:
            return
        node.description = self._snippet_fld_desc.toPlainText()
        self._mark_modified_from_props()
    
    def _edit_skill_of_current_node(self):
        """Редактировать выбранный скилл в списке текущей ноды"""
        row = self._skills_list.currentRow()
        node = self._props._node
        if row < 0 or not node or row >= len(node.skill_ids):
            return
        skill_id = node.skill_ids[row]
        skill = self._skill_registry.get(skill_id)
        if skill:
            self._edit_skill(skill)
    
    def _remove_skill_from_current_node(self):
        """Удалить выбранный скилл из текущей ноды"""
        row = self._skills_list.currentRow()
        node = self._props._node
        if row < 0 or not node or row >= len(node.skill_ids):
            return
        del node.skill_ids[row]
        self._props._populate()
        self._props.node_changed.emit()
    
    def _build_basic_tab(self):
        """Основная вкладка с базовыми настройками агента"""
        w = QWidget()
        layout = QVBoxLayout(w)
        
        # === КОНТЕЙНЕР ДЛЯ AI-АГЕНТСКИХ НАСТРОЕК ===
        self._ai_settings_group = QWidget()
        ai_layout = QFormLayout(self._ai_settings_group)
        
        # Имя агента (общее для всех)
        self._fld_name = QLineEdit()
        self._fld_name.setPlaceholderText(tr("Название"))
        ai_layout.addRow(tr("Имя:"), self._fld_name)

        # Тип агента — только AI-агенты, без сниппетов и заметок
        self._cmb_type = QComboBox()
        for at in AI_AGENT_TYPES:
            self._cmb_type.addItem(at.value.replace('_', ' ').title(), at)
        ai_layout.addRow(tr("Тип:"), self._cmb_type)

        # Модели
        self._fld_model = QComboBox()
        self._fld_model.setToolTip(tr("Наследует глобальную модель, если не выбрано"))
        ai_layout.addRow(tr("Модель:"), self._fld_model)

        self._fld_vision = QComboBox()
        self._fld_vision.setToolTip(tr("Наследует глобальную Vision модель, если не выбрано"))
        ai_layout.addRow(tr("Vision:"), self._fld_vision)
        
        # Описание
        self._fld_desc = QTextEdit()
        self._fld_desc.setPlaceholderText(tr("Описание..."))
        self._fld_desc.setMaximumHeight(80)
        ai_layout.addRow(tr("Описание:"), self._fld_desc)

        # Промпты
        self._txt_system = QTextEdit()
        self._txt_system.setMaximumHeight(60)
        ai_layout.addRow(tr("System Prompt:"), self._txt_system)

        self._txt_user = QTextEdit()
        self._txt_user.setMaximumHeight(60)
        ai_layout.addRow(tr("User Prompt:"), self._txt_user)
        
        # ПКМ с переменными для текстовых полей AI
        for _w in [self._txt_system, self._txt_user]:
            self._install_var_context_menu(_w)
        
        # Контекстное меню с переменными для текстовых полей AI
        for _w in [self._txt_system, self._txt_user, self._fld_name, self._fld_desc]:
            self._install_var_context_menu(_w)

        # Температура и Верификация
        self._spn_temp = QSpinBox()
        self._spn_temp.setRange(0, 20)
        ai_layout.addRow(tr("Температура (x10):"), self._spn_temp)

        # Верификация
        self._chk_verify = QCheckBox(tr("Включить верификацию"))
        self._chk_verify.stateChanged.connect(self._on_verification_toggled)
        ai_layout.addRow(tr("Верификация:"), self._chk_verify)
        
        self._cmb_verify_mode = QComboBox()
        self._cmb_verify_mode.addItem(tr("🔍 Самопроверка"), "self_check")
        self._cmb_verify_mode.addItem(tr("🤖 Другая модель"), "another_model")  
        self._cmb_verify_mode.addItem(tr("👤 Кастомный агент"), "custom_agent")
        self._cmb_verify_mode.setEnabled(False)
        ai_layout.addRow(tr("Режим:"), self._cmb_verify_mode)
        
        self._cmb_verify_model = QComboBox()
        self._cmb_verify_model.setPlaceholderText(tr("Выберите модель..."))
        self._cmb_verify_model.setEnabled(False)
        ai_layout.addRow(tr("Модель верификатора:"), self._cmb_verify_model)
        
        self._txt_verify_prompt = QTextEdit()
        self._txt_verify_prompt.setPlaceholderText(tr("Дополнительные инструкции..."))
        self._txt_verify_prompt.setMaximumHeight(60)
        self._txt_verify_prompt.setEnabled(False)
        ai_layout.addRow(tr("Промпт верификации:"), self._txt_verify_prompt)
        
        self._chk_verify_strict = QCheckBox(tr("Останавливать при ошибке"))
        self._chk_verify_strict.setEnabled(False)
        ai_layout.addRow(self._chk_verify_strict)
        
        # DEPRECATED: скрытое поле для совместимости
        self._fld_verifier = QLineEdit()
        self._fld_verifier.setVisible(False)

        # ═══ Кастомный цвет ноды ═══
        color_row = QHBoxLayout()
        self._btn_node_color = QPushButton(tr("🎨 Цвет ноды"))
        self._btn_node_color.setToolTip(tr("Выбрать кастомный цвет для этого узла"))
        self._btn_node_color.clicked.connect(self._pick_node_color)
        self._btn_reset_color = QPushButton("↩")
        self._btn_reset_color.setFixedWidth(28)
        self._btn_reset_color.setToolTip(tr("Сбросить к цвету по умолчанию"))
        self._btn_reset_color.clicked.connect(self._reset_node_color)
        color_row.addWidget(self._btn_node_color)
        color_row.addWidget(self._btn_reset_color)
        ai_layout.addRow(tr("Цвет:"), color_row)

        # ═══ Комментарий ═══
        self._fld_comment = QLineEdit()
        self._fld_comment.setPlaceholderText(tr("Комментарий (видимый на канвасе)..."))
        self._fld_comment.textChanged.connect(self._on_comment_changed)
        ai_layout.addRow(tr("💬 Комментарий:"), self._fld_comment)

        # Скиллы
        skills_row = QHBoxLayout()
        self._skills_list = QListWidget()
        self._skills_list.setMaximumHeight(80)
        skills_row.addWidget(self._skills_list, stretch=1)
        
        skills_btns = QVBoxLayout()
        self._btn_add_skill = QPushButton("+")
        self._btn_add_skill.setFixedWidth(30)
        self._btn_add_skill.setToolTip(tr("Добавить скилл"))
        self._btn_add_skill.clicked.connect(self._add_skill_to_current_node)
        
        self._btn_edit_skill = QPushButton("✎")
        self._btn_edit_skill.setFixedWidth(30)
        self._btn_edit_skill.setToolTip(tr("Редактировать скилл"))
        self._btn_edit_skill.clicked.connect(self._edit_skill_of_current_node)
        
        self._btn_remove_skill = QPushButton("−")
        self._btn_remove_skill.setFixedWidth(30)
        self._btn_remove_skill.setToolTip(tr("Удалить скилл"))
        self._btn_remove_skill.clicked.connect(self._remove_skill_from_current_node)
        
        skills_btns.addWidget(self._btn_add_skill)
        skills_btns.addWidget(self._btn_edit_skill)
        skills_btns.addWidget(self._btn_remove_skill)
        skills_row.addLayout(skills_btns)
        
        ai_layout.addRow(tr("Скиллы:"), skills_row)
        
        # === КОНТЕЙНЕР ДЛЯ СНИППЕТ-НАСТРОЕК (изначально скрыт) ===
        self._snippet_common_group = QWidget()
        snippet_layout = QFormLayout(self._snippet_common_group)
        
        # Имя сниппета (общее)
        self._snippet_fld_name = QLineEdit()
        self._snippet_fld_name.setPlaceholderText(tr("Название сниппета"))
        snippet_layout.addRow(tr("Имя:"), self._snippet_fld_name)
        
        # Описание сниппета
        self._snippet_fld_desc = QTextEdit()
        self._snippet_fld_desc.setPlaceholderText(tr("Описание..."))
        self._snippet_fld_desc.setMaximumHeight(80)
        snippet_layout.addRow(tr("Описание:"), self._snippet_fld_desc)
        
        # Тип сниппета (только для отображения, не редактируется)
        self._snippet_lbl_type = QLabel("")
        snippet_layout.addRow(tr("Тип:"), self._snippet_lbl_type)

        # Цвет для сниппета
        snippet_color_row = QHBoxLayout()
        self._btn_snippet_color = QPushButton(tr("🎨 Цвет"))
        self._btn_snippet_color.clicked.connect(self._pick_node_color)
        self._btn_snippet_reset_color = QPushButton("↩")
        self._btn_snippet_reset_color.setFixedWidth(28)
        self._btn_snippet_reset_color.clicked.connect(self._reset_node_color)
        snippet_color_row.addWidget(self._btn_snippet_color)
        snippet_color_row.addWidget(self._btn_snippet_reset_color)
        snippet_layout.addRow(tr("Цвет:"), snippet_color_row)

        # Комментарий для сниппета
        self._snippet_fld_comment = QLineEdit()
        self._snippet_fld_comment.setPlaceholderText(tr("Комментарий..."))
        self._snippet_fld_comment.textChanged.connect(self._on_comment_changed)
        snippet_layout.addRow(tr("💬:"), self._snippet_fld_comment)
        
        # Подключаем сигналы сниппет-полей для живого обновления
        self._snippet_fld_name.textChanged.connect(self._on_snippet_name_changed)
        self._snippet_fld_desc.textChanged.connect(self._on_snippet_desc_changed)
        
        # === ДОБАВЛЯЕМ ОБА КОНТЕЙНЕРА В ОСНОВНОЙ ЛЕЙАУТ ===
        layout.addWidget(self._ai_settings_group)
        layout.addWidget(self._snippet_common_group)
        
        # === ДИНАМИЧЕСКАЯ ПАНЕЛЬ НАСТРОЕК СНИППЕТА ===
        self._snippet_group = QGroupBox(tr("⚙️ Настройки сниппета"))
        self._snippet_group.setVisible(False)
        self._snippet_layout = QVBoxLayout(self._snippet_group)
        self._snippet_layout.setSpacing(8)
        layout.addWidget(self._snippet_group)
        
        # Контейнер для динамических виджетов настроек (per-node кэш)
        self._snippet_widgets_cache = {}  # node_id -> {widget_refs}
        
        # Подключаем смену типа к перестройке панели
        self._cmb_type.currentIndexChanged.connect(self._rebuild_snippet_panel)
        
        # === КОНТЕЙНЕР ДЛЯ ЗАМЕТОК (изначально скрыт) ===
        self._note_settings_group = QGroupBox(tr("📌 Заметка"))
        self._note_settings_group.setVisible(False)
        note_layout = QFormLayout(self._note_settings_group)
        note_layout.setSpacing(8)
        
        # Заголовок заметки
        self._note_fld_title = QLineEdit()
        self._note_fld_title.setPlaceholderText(tr("Заголовок заметки..."))
        self._note_fld_title.setStyleSheet("font-size: 13px; font-weight: bold; padding: 4px;")
        self._note_fld_title.textChanged.connect(self._on_note_changed)
        note_layout.addRow(tr("Заголовок:"), self._note_fld_title)
        
        # Текст заметки (многострочный редактор)
        self._note_txt_content = QPlainTextEdit()
        self._note_txt_content.setPlaceholderText(tr("Текст заметки...\n\nМожно писать что угодно:\n- TODO\n- Описание архитектуры\n- Ссылки\n- Идеи"))
        self._note_txt_content.setMinimumHeight(200)
        self._note_txt_content.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {get_color('bg0')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                padding: 6px;
            }}
        """)
        self._note_txt_content.textChanged.connect(self._on_note_changed)
        note_layout.addRow(self._note_txt_content)
        
        # Цвет заметки
        note_color_row = QHBoxLayout()
        self._btn_note_color = QPushButton(tr("🎨 Цвет заметки"))
        self._btn_note_color.setStyleSheet("background: #E0AF68; color: white; padding: 4px;")
        self._btn_note_color.clicked.connect(self._pick_note_color)
        note_color_row.addWidget(self._btn_note_color)
        note_layout.addRow(tr("Цвет:"), note_color_row)
        
        # Размер шрифта
        self._note_spn_font_size = QSpinBox()
        self._note_spn_font_size.setRange(6, 24)
        self._note_spn_font_size.setValue(9)
        self._note_spn_font_size.setSuffix(" pt")
        self._note_spn_font_size.valueChanged.connect(self._on_note_font_size_changed)
        note_layout.addRow(tr("Шрифт:"), self._note_spn_font_size)
        
        # Кнопка авторазмера
        btn_auto_size = QPushButton(tr("📐 Авторазмер по тексту"))
        btn_auto_size.clicked.connect(self._on_note_auto_size)
        note_layout.addRow("", btn_auto_size)
        
        # Размер заметки
        note_size_row = QHBoxLayout()
        self._note_spn_width = QSpinBox()
        self._note_spn_width.setRange(100, 600)
        self._note_spn_width.setValue(200)
        self._note_spn_width.setSuffix(" px")
        self._note_spn_width.valueChanged.connect(self._on_note_size_changed)
        self._note_spn_height = QSpinBox()
        self._note_spn_height.setRange(60, 400)
        self._note_spn_height.setValue(120)
        self._note_spn_height.setSuffix(" px")
        self._note_spn_height.valueChanged.connect(self._on_note_size_changed)
        note_size_row.addWidget(QLabel(tr("Ш:")))
        note_size_row.addWidget(self._note_spn_width)
        note_size_row.addWidget(QLabel(tr("В:")))
        note_size_row.addWidget(self._note_spn_height)
        note_layout.addRow(tr("Размер:"), note_size_row)
        
        layout.addWidget(self._note_settings_group)

        # === КОНТЕЙНЕР ДЛЯ СТАРТА ПРОЕКТА (изначально скрыт) ===
        self._start_settings_group = QGroupBox(tr("▶ Старт проекта"))
        self._start_settings_group.setVisible(False)
        start_layout = QFormLayout(self._start_settings_group)
        start_layout.setSpacing(8)

        # Заголовок (имя ноды)
        self._start_fld_heading = QLineEdit()
        self._start_fld_heading.setPlaceholderText(tr("Название стартовой точки..."))
        self._start_fld_heading.setStyleSheet("font-size: 13px; font-weight: bold; padding: 4px;")
        self._start_fld_heading.textChanged.connect(self._on_start_changed)
        start_layout.addRow(tr("Заголовок:"), self._start_fld_heading)

        # Описание
        self._start_fld_desc = QLineEdit()
        self._start_fld_desc.setPlaceholderText(tr("Описание / комментарий..."))
        self._start_fld_desc.textChanged.connect(self._on_start_changed)
        start_layout.addRow(tr("Описание:"), self._start_fld_desc)

        # Разделитель
        start_layout.addRow(QLabel(f"<hr style='color:{get_color('bd')};'>"))

        # Режим старта
        self._start_cmb_mode = QComboBox()
        self._start_cmb_mode.addItem(tr("⚡ Простой — запуск без модели"), "simple")
        self._start_cmb_mode.addItem(tr("🤖 С моделью — начать с AI-агента"), "with_model")
        self._start_cmb_mode.currentIndexChanged.connect(self._on_start_mode_changed)
        start_layout.addRow(tr("Режим старта:"), self._start_cmb_mode)

        # Начальная инструкция для модели (только при режиме with_model)
        self._start_txt_prompt = QTextEdit()
        self._start_txt_prompt.setPlaceholderText(tr("Начальная инструкция для AI-модели..."))
        self._start_txt_prompt.setMaximumHeight(80)
        self._start_txt_prompt.setStyleSheet(f"""
            QTextEdit {{
                background: {get_color('bg0')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
                font-size: 11px;
                padding: 4px;
            }}
        """)
        self._start_txt_prompt.textChanged.connect(self._on_start_changed)
        self._start_prompt_label = QLabel(tr("Инструкция:"))
        start_layout.addRow(self._start_prompt_label, self._start_txt_prompt)

        # Разделитель
        start_layout.addRow(QLabel(f"<hr style='color:{get_color('bd')};'>"))

        # Чекбоксы поведения при старте
        self._start_chk_reset_vars = QCheckBox(tr("Сбросить переменные к значениям по умолчанию"))
        self._start_chk_reset_vars.setChecked(True)
        self._start_chk_reset_vars.stateChanged.connect(self._on_start_changed)
        start_layout.addRow(self._start_chk_reset_vars)

        self._start_chk_reset_global = QCheckBox(tr("Сбросить глобальные переменные к дефолту"))
        self._start_chk_reset_global.setChecked(False)
        self._start_chk_reset_global.stateChanged.connect(self._on_start_changed)
        start_layout.addRow(self._start_chk_reset_global)

        self._start_chk_clear_log = QCheckBox(tr("Очистить системный лог при запуске"))
        self._start_chk_clear_log.setChecked(False)
        self._start_chk_clear_log.stateChanged.connect(self._on_start_changed)
        start_layout.addRow(self._start_chk_clear_log)

        self._start_chk_save_before = QCheckBox(tr("Сохранить проект перед стартом"))
        self._start_chk_save_before.setChecked(False)
        self._start_chk_save_before.stateChanged.connect(self._on_start_changed)
        start_layout.addRow(self._start_chk_save_before)

        # Цвет
        start_color_row = QHBoxLayout()
        self._btn_start_color = QPushButton(tr("🎨 Цвет"))
        self._btn_start_color.setStyleSheet("background: #9ECE6A; color: #000; padding: 4px;")
        self._btn_start_color.clicked.connect(self._pick_start_color)
        start_color_row.addWidget(self._btn_start_color)
        start_color_row.addStretch()
        start_layout.addRow(tr("Цвет:"), start_color_row)

        layout.addWidget(self._start_settings_group)

        layout.addStretch()
        return w
    
    def _on_note_font_size_changed(self, value):
        """Изменить размер шрифта заметки."""
        node = self._props._node
        if not node or node.agent_type != AgentType.NOTE:
            return
        node.note_font_size = value
        item = self._scene.get_node_item(node.id)
        if item:
            item.update()

    def _on_note_auto_size(self):
        """Автоматически подогнать размер заметки под текст."""
        node = self._props._node
        if not node or node.agent_type != AgentType.NOTE:
            return
        
        content = getattr(node, 'note_content', '')
        if not content:
            return
            
        font_size = getattr(node, 'note_font_size', 9)
        
        # Расчет высоты: 40px заголовок + строки * высота_строки + отступ снизу
        lines = content.split('\n')
        line_count = len(lines)
        # Приблизительная высота строки = font_size * 1.3
        estimated_height = int(40 + line_count * (font_size * 1.3) + 20)
        
        # Расчет ширины: находим самую длинную строку
        max_line_len = max([len(line) for line in lines]) if lines else 0
        # Приблизительная ширина символа = font_size * 0.6
        estimated_width = min(600, max(140, int(max_line_len * (font_size * 0.6) + 30)))
        
        node.width = estimated_width
        node.height = max(60, estimated_height)
        
        # Обновляем UI
        if hasattr(self, '_note_spn_width'):
            self._note_spn_width.blockSignals(True)
            self._note_spn_width.setValue(node.width)
            self._note_spn_width.blockSignals(False)
        if hasattr(self, '_note_spn_height'):
            self._note_spn_height.blockSignals(True)
            self._note_spn_height.setValue(node.height)
            self._note_spn_height.blockSignals(False)
        
        # Обновляем визуал
        item = self._scene.get_node_item(node.id)
        if item:
            item.setRect(0, 0, node.width, node.height)
            item.update()
            self._scene.update_edges()
    
    def _rebuild_snippet_panel(self):
        # Для сниппетов тип берём из самой ноды, а не из cmb_type (он для AI-агентов)
        current_node = (
            self._props._node
            if hasattr(self, '_props') and self._props and hasattr(self._props, '_node')
            else None
        )
        if current_node and current_node.agent_type in SNIPPET_TYPES:
            agent_type = current_node.agent_type
        else:
            agent_type = self._cmb_type.currentData()
        if not agent_type:
            return
        
        # Определяем категорию сниппета (используем глобальный SNIPPET_TYPES)
        is_snippet = agent_type in SNIPPET_TYPES
        is_ai = not is_snippet
        
        # === ПЕРЕКЛЮЧАЕМ ВИДИМОСТЬ ГРУПП ===
        self._ai_settings_group.setVisible(is_ai)
        self._snippet_common_group.setVisible(is_snippet)
        
        # Синхронизируем имена между полями — ТОЛЬКО если _snippet_fld_name пустой
        # (чтобы не перезатирать значение, уже установленное из _populate)
        if is_snippet and hasattr(self, '_snippet_fld_name'):
            if not self._snippet_fld_name.text().strip():
                self._snippet_fld_name.setText(self._fld_name.text())
                self._snippet_fld_desc.setText(self._fld_desc.toPlainText())
            self._snippet_lbl_type.setText(agent_type.value.replace('_', ' ').title())
        
        # Рекурсивная очистка layout (удаляет и виджеты, и вложенные layout'ы)
        def clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    clear_layout(item.layout())
        
        clear_layout(self._snippet_layout)
        self._snippet_widgets = {}  # Очищаем текущие виджеты
        self._snippet_code_editor = None  # Сбрасываем ссылку на удалённый редактор
        self._snippet_group.setVisible(is_snippet)
        
        if not is_snippet:
            return
        
        # === СОЗДАНИЕ НОВОЙ ПАНЕЛИ ===
        self._snippet_loading = True  # Блокируем flush во время загрузки
        self._create_snippet_widgets_for_type(agent_type)
        
        self._snippet_config_before_edit = self._get_current_snippet_config() if hasattr(self, '_get_current_snippet_config') else {}
        self._snippet_undo_pending = True
        
        # === ЗАГРУЗКА: Применяем сохранённые настройки из текущей ноды ===
        # КРИТИЧНО: НЕ снимаем _snippet_loading здесь!
        # Он снимается ТОЛЬКО в _delayed_load_snippet_config после реальной загрузки
        current_node = self._props._node if hasattr(self, '_props') and self._props else None
        if current_node and hasattr(current_node, 'id'):
            # Принудительно инициализируем snippet_config если его нет
            if not hasattr(current_node, 'snippet_config') or current_node.snippet_config is None:
                current_node.snippet_config = {}
            # Отложенная загрузка через таймер чтобы виджеты точно создались
            QTimer.singleShot(0, lambda: self._delayed_load_snippet_config(current_node))
        else:
            # Если ноды нет — разблокируем сразу
            self._snippet_loading = False
        
        # Обновляем видимость полей по текущему source
        if hasattr(self, '_update_code_source_visibility'):
            self._update_code_source_visibility()
        # Обновляем видимость полей IF по текущему режиму
        if hasattr(self, '_update_if_condition_visibility'):
            self._update_if_condition_visibility()
    
    def _save_current_snippet_widgets_to_node(self):
        """Сохранить текущие значения виджетов в node.snippet_config перед переключением."""
        current_node = self._props._node if hasattr(self, '_props') and self._props else None
        if not current_node or not hasattr(self, '_snippet_widgets'):
            return
        
        # ═══ КРИТИЧНО: Создаем НОВЫЙ словарь, не модифицируем существующий ═══
        import copy
        if not hasattr(current_node, 'snippet_config') or current_node.snippet_config is None:
            current_node.snippet_config = {}
        else:
            current_node.snippet_config = copy.deepcopy(current_node.snippet_config)
        
        # Собираем значения из виджетов
        for key, widget in self._snippet_widgets.items():
            if key.startswith('_'):
                continue
                
            try:
                if isinstance(widget, QCheckBox):
                    current_node.snippet_config[key] = widget.isChecked()
                elif isinstance(widget, QSpinBox):
                    current_node.snippet_config[key] = widget.value()
                elif isinstance(widget, QComboBox):
                    current_node.snippet_config[key] = widget.currentData() or widget.currentText()
                elif isinstance(widget, QLineEdit):
                    current_node.snippet_config[key] = widget.text()
                elif isinstance(widget, QTextEdit):
                    current_node.snippet_config[key] = widget.toPlainText()
            except RuntimeError:
                pass
        
        # Сохраняем код
        if getattr(self, '_snippet_code_editor', None) is not None:
            try:
                code = self._snippet_code_editor.toPlainText()
                current_node.snippet_config['_code'] = code
                current_node.user_prompt_template = code
            except RuntimeError:
                pass
        current_node = self._props._node if hasattr(self, '_props') and self._props else None
        if not current_node or not hasattr(self, '_snippet_widgets'):
            return
        
        # Собираем значения из текущих виджетов
        config = {}
        for key, widget in self._snippet_widgets.items():
            if isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QComboBox):
                config[key] = widget.currentData() or widget.currentText()
            elif isinstance(widget, QLineEdit):
                config[key] = widget.text()
            elif isinstance(widget, QTextEdit):
                config[key] = widget.toPlainText()
        
        # ═══ КРИТИЧНО: Сохраняем переменные из таблицы ═══
        if hasattr(self, '_vars_table') and self._vars_table.rowCount() > 0:
            variables = []
            for row in range(self._vars_table.rowCount()):
                name = self._vars_table.item(row, 0)
                value = self._vars_table.item(row, 1)
                type_widget = self._vars_table.cellWidget(row, 2)
                desc = self._vars_table.item(row, 3)
                
                if name and name.text().strip():
                    variables.append({
                        "name": name.text().strip(),
                        "value": value.text() if value else "",
                        "type": type_widget.currentText() if type_widget else "string",
                        "description": desc.text() if desc else ""
                    })
            config["_variables"] = variables
        
        # ═══ Сохраняем код из редактора ═══
        if getattr(self, '_snippet_code_editor', None) is not None:
            code = self._snippet_code_editor.toPlainText()
            config['_code'] = code
            current_node.user_prompt_template = code
        
        # Сохраняем в ноду
        import copy
        current_node.snippet_config = copy.deepcopy(config)
        # Также сохраняем метку типа для валидации
        current_node._snippet_type = current_node.agent_type.value
    
    def _get_current_snippet_config(self) -> dict:
        """Получить текущую конфигурацию сниппета из виджетов"""
        if not hasattr(self, '_snippet_widgets'):
            return {}
        
        import copy
        config = {}
        for key, widget in self._snippet_widgets.items():
            if isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QComboBox):
                config[key] = widget.currentData() or widget.currentText()
            elif isinstance(widget, QLineEdit):
                config[key] = widget.text()
            elif isinstance(widget, QTextEdit):
                config[key] = widget.toPlainText()
        
        # Сохраняем переменные из таблицы
        if hasattr(self, '_vars_table') and self._vars_table.rowCount() > 0:
            variables = []
            for row in range(self._vars_table.rowCount()):
                name = self._vars_table.item(row, 0)
                value = self._vars_table.item(row, 1)
                type_widget = self._vars_table.cellWidget(row, 2)
                desc = self._vars_table.item(row, 3)
                
                if name and name.text().strip():
                    variables.append({
                        "name": name.text().strip(),
                        "value": value.text() if value else "",
                        "type": type_widget.currentText() if type_widget else "string",
                        "description": desc.text() if desc else ""
                    })
            config["_variables"] = variables
        
        # Сохраняем код из редактора
        if getattr(self, '_snippet_code_editor', None) is not None:
            try:
                config['_code'] = self._snippet_code_editor.toPlainText()
            except RuntimeError:
                pass  # Виджет удалён
        
        # ═══ КРИТИЧНО: Возвращаем ГЛУБОКУЮ КОПИЮ ═══
        return copy.deepcopy(config)
    
    def _apply_snippet_config_to_node(self, node: AgentNode, config: dict):
        """Применить конфиг к ноде (для undo/redo)."""
        if node is None:
            return
        import copy
        # ═══ КРИТИЧНО: Глубокая копия чтобы избежать shared state ═══
        node.snippet_config = copy.deepcopy(config)
        # Обновляем UI если это текущая нода
        if self._props._node is node:
            self._load_snippet_config_to_widgets(node)
        # Автовысота для Switch: каждая строка cases = один выход (+28px)
        if getattr(node, 'agent_type', None) and node.agent_type == AgentType.SWITCH:
            cases_raw = config.get('cases', '')
            case_lines = [ln.strip() for ln in cases_raw.splitlines() if ln.strip()]
            n_cases = max(len(case_lines), 1)
            # Базовая высота 120px + 32px на каждый выход (+ default)
            new_height = 120 + (n_cases + 1) * 32
            if node.height != new_height:
                node.height = new_height
                item = self._scene.get_node_item(node.id) if hasattr(self, '_scene') else None
                if item:
                    item.setRect(0, 0, node.width, node.height)
                    item.update()
                    if hasattr(self._scene, 'update_edges'):
                        self._scene.update_edges()
    
    def _create_snippet_widgets_for_type(self, agent_type: AgentType):
        """Создать виджеты настроек для конкретного типа сниппета."""
        # Очищаем старое отслеживание
        self._snippet_tracker.clear_tracking()
        self._snippet_tracker.set_restoring(True)  # Временно отключаем создание команд при создании виджетов
        
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(10, 10, 10, 10)
        self._snippet_field_labels: dict = {}   # key → QLabel (или QCheckBox)
        
        # Справочник: тип -> (заголовок группы, список полей)
        SNIPPET_SCHEMA = {
            AgentType.CODE_SNIPPET: {
                'title': tr("📜 Code Snippet — выполнение кода"),
                'help': tr("Выполняет Python/Shell/Node код. Переменные: {var_name}"),
                'fields': [
                    ('language', 'combo', tr('Язык:'), [
                        ('Python', 'python'), ('Shell/Bash', 'shell'), ('Node.js', 'node')
                    ], 'python'),
                    ('code_source', 'combo', tr('Источник:'), [
                        (tr('Код в поле User Prompt'), 'inline'), 
                        (tr('Файл скрипта'), 'file')
                    ], 'inline'),
                    ('_code_editor', 'code_editor', tr('📝 Код для выполнения:'), '', tr('Введите код здесь. Переменные: {var_name}')),
                    ('script_path', 'file_browse', tr('Путь к файлу:'), '', tr('Python Files (*.py);;Shell Scripts (*.sh);;JavaScript (*.js);;All Files (*)')),
                    ('working_dir', 'dir_browse', tr('Рабочая папка:'), '', tr('Папка выполнения (пусто = папка проекта)')),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 3600, 60), None),
                    ('save_output', 'check', tr('Сохранить stdout в переменную'), True, None),
                    ('output_var', 'line', tr('Имя переменной:'), 'snippet_result', tr('Куда сохранить stdout')),
                    ('no_return', 'check', tr('Не возвращать значение'), False, tr('Если отключено — последняя строка stdout = результат')),
                    ('save_stderr', 'check', tr('Сохранить stderr в переменную'), False, None),
                    ('stderr_var', 'line', tr('Переменная для stderr:'), 'snippet_error', tr('Куда сохранить stderr')),
                    ('inject_vars', 'check', tr('Инжектировать переменные из таблицы в контекст'), True, tr('Переменные будут доступны как {имя}')),
                    ('env_vars', 'text', tr('Переменные окружения:'), '', tr('KEY=VALUE по строкам')),
                ]
            },
            AgentType.IF_CONDITION: {
                'title': tr("snippet_if_title"),  # "❓ IF Condition — условный переход"
                'help': tr("snippet_if_help"),    # "Проверяет условие..."
                'fields': [
                    ('condition_mode', 'combo', tr('snippet_if_mode') + ':', [
                        (tr('Визуальный конструктор'), 'visual'),
                        (tr('Python выражение (свободный)'), 'expression'),
                    ], 'visual'),
                    ('left_operand', 'line', tr('Левый операнд:'), '', tr('Переменная или значение. Пример: {counter} или 5')),
                    ('operator', 'combo', tr('Оператор:'), [
                        (tr('== (равно)'), 'eq'),
                        (tr('!= (не равно)'), 'neq'),
                        (tr('> (больше)'), 'gt'),
                        (tr('< (меньше)'), 'lt'),
                        (tr('>= (больше или равно)'), 'gte'),
                        (tr('<= (меньше или равно)'), 'lte'),
                        (tr('contains (содержит)'), 'contains'),
                        (tr('not contains (не содержит)'), 'not_contains'),
                        (tr('startswith (начинается)'), 'startswith'),
                        (tr('endswith (заканчивается)'), 'endswith'),
                        (tr('is empty (пустой)'), 'is_empty'),
                        (tr('is not empty (не пустой)'), 'is_not_empty'),
                        (tr('matches regex'), 'regex'),
                    ], 'eq'),
                    ('right_operand', 'line', tr('Правый операнд:'), '', tr('Значение для сравнения. Пример: {max_count} или 10')),
                    ('compare_as', 'combo', tr('Сравнивать как:'), [
                        (tr('Автоопределение'), 'auto'),
                        (tr('Строки'), 'string'),
                        (tr('Числа'), 'number'),
                        (tr('Булево (True/False)'), 'boolean'),
                    ], 'auto'),
                    ('case_sensitive', 'check', tr('Учитывать регистр'), True, None),
                    ('chain_logic', 'combo', tr('Объединение условий:'), [
                        (tr('Нет (одно условие)'), 'none'),
                        (tr('&& (И) — все истинны'), 'and'),
                        (tr('|| (ИЛИ) — хотя бы одно'), 'or'),
                    ], 'none'),
                    ('extra_conditions', 'text', tr('Доп. условия (по строкам):'), '', tr('Формат: {var} == значение (по строке на каждое)')),
                    ('negate', 'check', tr('Инвертировать результат (NOT)'), False, None),
                    ('_code_editor', 'code_editor', tr('📝 Python выражение (свободный режим):'), '', tr('Пример: ctx.get("count", 0) > 5 and ctx.get("status") == "ok"')),
                    ('log_result', 'check', tr('Логировать результат сравнения'), True, None),
                ]
            },
            AgentType.LOOP: {
                'title': tr("🔁 LOOP — цикл с итерациями"),
                'help': tr("Повторяет выполнение дочерних узлов. Поддерживает: счётчик, while, перебор списка/файла"),
                'fields': [
                    ('loop_type', 'combo', tr('Тип цикла:'), [
                        (tr('Счётчик (N итераций)'), 'count'),
                        (tr('While (пока условие)'), 'while'),
                        (tr('Перебор списка (переменная)'), 'foreach_list'),
                        (tr('Перебор строк файла'), 'foreach_file'),
                        (tr('Перебор инлайн-списка'), 'foreach_inline'),
                    ], 'count'),
                    ('max_iterations', 'spin', tr('Максимум итераций:'), (1, 100000, 10), tr('Ограничение для любого типа цикла')),
                    ('data_var', 'line', tr('Переменная-источник:'), '', tr('Для foreach_list: имя списка/переменной')),
                    ('file_path', 'file_browse', tr('Файл с данными:'), '', tr('Text Files (*.txt);;CSV (*.csv);;All Files (*)')),
                    ('inline_list', 'text', tr('Инлайн-список:'), '', tr('Элементы по строкам (для foreach_inline)')),
                    ('separator', 'line', tr('Разделитель:'), '\\n', tr('Для разбиения строки в список')),
                    ('shuffle_items', 'check', tr('Перемешать элементы'), False, None),
                    ('counter_var', 'line', tr('Переменная счётчика:'), '_loop_iteration', tr('Номер итерации (1-based)')),
                    ('iter_var', 'line', tr('Переменная значения:'), '_loop_value', tr('Текущий элемент (для foreach)')),
                    ('exit_condition', 'line', tr('Условие выхода (Python):'), '', tr('Пример: ctx.get("done") == True  или  iteration > 5')),
                    ('sleep_between', 'spin', tr('Пауза между итерациями (сек):'), (0, 3600, 0), None),
                    ('break_on_error', 'check', tr('Прервать при ошибке дочернего узла'), True, None),
                ]
            },
            AgentType.VARIABLE_SET: {
                'title': tr("📝 Variable Set — установка переменных"),
                'help': tr("Установка переменных в контекст. Используйте поля ниже ИЛИ таблицу переменных. Переменные: {var_name}"),
                'fields': [
                    ('operation', 'combo', tr('Операция:'), [
                        (tr('Установить (Set)'), 'set'),
                        (tr('Увеличить (Increment)'), 'inc'),
                        (tr('Уменьшить (Decrement)'), 'dec'),
                        (tr('Добавить к списку (Append)'), 'append'),
                        (tr('Удалить (Delete)'), 'delete')
                    ], 'set'),
                    ('var_name', 'line', tr('Имя переменной:'), '', tr('Имя переменной для установки/изменения')),
                    ('var_value', 'line', tr('Значение:'), '', tr('Значение или {другая_переменная}')),
                    ('step_value', 'spin', tr('Шаг (для inc/dec):'), (1, 10000, 1), tr('На сколько увеличить/уменьшить')),
                    ('global_scope', 'check', tr('Глобальная область видимости'), True, None),
                    ('auto_type', 'check', tr('Автоопределение типа (число/bool/строка)'), True, None),
                    ('create_if_missing', 'check', tr('Создать переменную если не существует'), True, None),
                    ('multi_set', 'text', tr('Множественная установка:'), '', tr('По строкам: имя = значение\ncount = 0\nstatus = active')),
                ]
            },
            AgentType.HTTP_REQUEST: {
                'title': tr("🌐 HTTP Request — веб-запросы"),
                'help': tr("Отправка HTTP-запросов. Переменные: {name}"),
                'fields': [
                    ('url', 'line', tr('🌐 URL:'), '', tr('Полный URL с http(s)://. Переменные: {name}')),
                    ('method', 'combo', tr('Метод:'), [
                        ('GET', 'GET'), ('POST', 'POST'), ('PUT', 'PUT'), 
                        ('DELETE', 'DELETE'), ('PATCH', 'PATCH'), ('HEAD', 'HEAD'), ('OPTIONS', 'OPTIONS')
                    ], 'GET'),
                    ('referer', 'line', tr('Referer:'), '', tr('URL реферера (откуда пришли)')),
                    ('encoding', 'combo', tr('Кодировка:'), [
                        ('utf-8', 'utf-8'), ('windows-1251', 'windows-1251'), 
                        ('ascii', 'ascii'), ('iso-8859-1', 'iso-8859-1'),
                    ], 'utf-8'),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 300, 30), None),
                    ('load_content', 'combo', tr('Загружать:'), [
                        (tr('Только содержимое'), 'content_only'),
                        (tr('Только заголовки'), 'headers_only'),
                        (tr('Заголовки и содержимое'), 'headers_and_content'),
                        (tr('Как файл'), 'as_file'),
                        (tr('Как файл + заголовки'), 'as_file_and_headers'),
                    ], 'content_only'),
                    ('save_response', 'check', tr('📦 Положить в переменную'), True, None),
                    ('response_var', 'line', tr('Переменная ответа:'), 'http_response', None),
                    ('save_status', 'check', tr('Сохранить HTTP-статус'), True, None),
                    ('status_var', 'line', tr('Переменная статуса:'), 'http_status', None),
                    ('save_headers_var', 'line', tr('Переменная для заголовков:'), '', tr('Оставьте пустым если не нужно')),
                    ('save_to_file', 'line', tr('Сохранить в файл:'), '', tr('Путь для режима "Как файл"')),
                    ('content_type', 'combo', tr('Content-Type:'), [
                        (tr('(не задавать)'), ''),
                        ('application/json', 'application/json'),
                        ('application/x-www-form-urlencoded', 'application/x-www-form-urlencoded'),
                        ('multipart/form-data', 'multipart/form-data'),
                        ('text/plain', 'text/plain'),
                        ('text/xml', 'text/xml'),
                    ], ''),
                    ('headers', 'text', tr('Заголовки (по строкам):'), '', tr('Формат: Header-Name: value')),
                    ('body', 'text', tr('Тело запроса:'), '', tr('Для POST/PUT/PATCH')),
                    ('follow_redirects', 'check', tr('✅ Редирект'), True, None),
                    ('max_redirects', 'spin', tr('Макс. редиректов:'), (0, 20, 5), None),
                    ('use_original_url', 'check', tr('Использовать оригинальный URL'), False, None),
                    ('use_cookies', 'check', tr('🍪 Использовать CookieContainer'), True, None),
                    ('verify_ssl', 'check', tr('Проверять SSL-сертификат'), True, None),
                ]
            },
            AgentType.DELAY: {
                'title': tr("⏳ Delay — пауза выполнения"),
                'help': tr("Останавливает workflow на заданное время"),
                'fields': [
                    ('seconds', 'spin', tr('Секунды:'), (0, 86400, 5), None),
                    ('randomize', 'check', tr('Случайная задержка ±50%'), False, None),
                    ('random_range', 'spin', tr('Диапазон случайности %:'), (10, 100, 50), tr('Только с галочкой выше')),
                ]
            },
            AgentType.LOG_MESSAGE: {
                'title': tr("📋 Log Message — запись в лог"),
                'help': tr("Записывает сообщение в лог и/или файл. Переменные: {name}"),
                'fields': [
                    ('message', 'text', tr('📝 Сообщение:'), '', tr('Текст для записи в лог. Переменные: {var_name}')),
                    ('level', 'combo', tr('Уровень:'), [
                        ('DEBUG', 'DEBUG'), ('INFO', 'INFO'), 
                        ('WARNING', 'WARNING'), ('ERROR', 'ERROR')
                    ], 'INFO'),
                    ('write_to_console', 'check', tr('Выводить в консоль'), True, None),
                    ('write_to_file', 'check', tr('Записывать в файл'), False, None),
                    ('log_file', 'file_browse', tr('Имя файла:'), 'execution.log', tr('Log Files (*.log);;Text Files (*.txt);;All Files (*)')),
                    ('include_timestamp', 'check', tr('Добавлять timestamp'), True, None),
                    ('include_node_name', 'check', tr('Добавлять имя ноды'), True, None),
                    ('add_newline', 'check', tr('Дополнительный перенос строки'), False, None),
                ]
            },
            AgentType.SWITCH: {
                'title': tr("🔀 Switch — множественный выбор"),
                'help': tr("Сравнивает значение переменной с условиями. Поддерживает ==, !=, >, <, >=, <=, contains, regex. По Default если ничего не совпало."),
                'fields': [
                    ('switch_variable', 'line', tr('Переменная:'), '', tr('Имя переменной из контекста (без фигурных скобок)')),
                    ('compare_mode', 'combo', tr('Режим сравнения:'), [
                        (tr('Равно (==)'), 'eq'),
                        (tr('Не равно (!=)'), 'neq'),
                        (tr('Содержит (contains)'), 'contains'),
                        (tr('Начинается с (startswith)'), 'startswith'),
                        (tr('Regex'), 'regex'),
                        (tr('Числовое сравнение'), 'numeric'),
                    ], 'eq'),
                    ('case_sensitive', 'check', tr('Учитывать регистр'), False, None),
                    ('cases', 'text', tr('Условия (по строкам):'), tr('значение1\nзначение2\nзначение3'), tr('Каждая строка = одно условие. Рёбра привязываются по порядку: 1-е ребро → 1-я строка и т.д.')),
                    ('default_action', 'combo', tr('Default (нет совпадения):'), [
                        (tr('Идти по последнему ребру'), 'last_edge'),
                        (tr('Выход по ON_FAILURE'), 'failure'),
                        (tr('Остановить workflow'), 'stop'),
                    ], 'last_edge'),
                    ('log_comparison', 'check', tr('Логировать сравнения'), True, None),
                ]
            },
            AgentType.GOOD_END: {
                'title': tr("✅ Good End — успешное завершение"),
                'help': tr("Выполняется при успешном завершении ветки. Действия привязанные после Good End выполнятся перед финальным завершением."),
                'fields': [
                    ('log_success', 'check', tr('Записать в лог об успешном завершении'), True, None),
                    ('save_report', 'check', tr('Сохранить отчёт в файл'), False, None),
                    ('report_file', 'line', tr('Имя файла отчёта:'), 'good_end_report.txt', tr('Только если галочка выше')),
                    ('include_context', 'check', tr('Включить контекст в отчёт'), True, None),
                    ('include_timing', 'check', tr('Включить время выполнения'), True, None),
                    ('custom_message', 'line', tr('Сообщение при успехе:'), '', tr('Поддерживаются переменные {name}')),
                    ('return_to_start', 'check', tr('Вернуться к началу (перезапуск)'), False, tr('Для цикличных workflow')),
                ]
            },
            AgentType.BAD_END: {
                'title': tr("🛑 Bad End — завершение с ошибкой"),
                'help': tr("Выполняется при ошибке в любом узле, если узел не имеет ON_FAILURE ребра. Используйте для восстановления данных, логирования ошибок."),
                'fields': [
                    ('log_error', 'check', tr('Записать ошибку в лог'), True, None),
                    ('save_error_log', 'check', tr('Сохранить лог ошибок в файл'), True, None),
                    ('error_log_file', 'line', tr('Файл лога ошибок:'), 'error_log.txt', None),
                    ('include_last_error', 'check', tr('Включить текст последней ошибки'), True, None),
                    ('include_failed_node', 'check', tr('Включить имя ошибочного узла'), True, None),
                    ('include_context_dump', 'check', tr('Дамп всего контекста'), False, tr('Полный дамп переменных для отладки')),
                    ('include_timestamp', 'check', tr('Добавлять timestamp'), True, None),
                    ('restore_data', 'check', tr('Восстановить данные в списки'), False, tr('Вернуть данные обратно при ошибке')),
                    ('restore_var', 'line', tr('Переменные для восстановления:'), '', tr('Через запятую: var1, var2')),
                    ('on_bad_end', 'combo', tr('После Bad End:'), [
                        (tr('Остановить workflow'), 'stop'),
                        (tr('Перезапустить с начала'), 'restart'),
                        (tr('Продолжить со следующего'), 'continue'),
                    ], 'stop'),
                    ('max_restarts', 'spin', tr('Макс. перезапусков:'), (0, 100, 3), tr('Только для режима "Перезапустить"')),
                ]
            },
            AgentType.NOTIFICATION: {
                'title': tr("🔔 Notification — оповещение"),
                'help': tr("Сообщение из User Prompt. Отображается в логе и/или всплывающим окном. Переменные: {name}"),
                'fields': [
                    ('notif_level', 'combo', tr('Уровень сообщения:'), [
                        (tr('ℹ️ Info'), 'info'),
                        (tr('⚠️ Warning'), 'warning'),
                        (tr('❌ Error'), 'error'),
                        (tr('✅ Success'), 'success'),
                    ], 'info'),
                    ('notif_color', 'combo', tr('Цвет сообщения:'), [
                        (tr('По умолчанию'), 'default'),
                        (tr('🔴 Красный'), '#F7768E'),
                        (tr('🟢 Зелёный'), '#9ECE6A'),
                        (tr('🟡 Жёлтый'), '#E0AF68'),
                        (tr('🔵 Синий'), '#7AA2F7'),
                        (tr('🟣 Фиолетовый'), '#BB9AF7'),
                    ], 'default'),
                    ('show_popup', 'check', tr('Показывать всплывающее окно'), False, None),
                    ('popup_duration', 'spin', tr('Автозакрытие через (сек):'), (0, 60, 5), tr('0 = не закрывать')),
                    ('write_to_log', 'check', tr('Записывать в лог'), True, None),
                    ('write_to_file', 'check', tr('Записывать в файл'), False, None),
                    ('log_file', 'line', tr('Имя файла:'), 'notifications.log', tr('Только если галочка выше')),
                    ('include_timestamp', 'check', tr('Добавлять timestamp'), True, None),
                    ('save_to_var', 'check', tr('Сохранить текст в переменную'), False, None),
                    ('output_var', 'line', tr('Имя переменной:'), 'last_notification', None),
                ]
            },
            AgentType.JS_SNIPPET: {
                'title': tr("🟨 JavaScript — выполнение JS кода"),
                'help': tr("Выполняет JavaScript код. Режим: локально или в контексте данных. Переменные: {var_name}"),
                'fields': [
                    ('js_mode', 'combo', tr('Режим выполнения:'), [
                        (tr('Локально (Node.js)'), 'local'),
                        (tr('Eval в Python (js2py)'), 'eval'),
                    ], 'local'),
                    ('_code_editor', 'code_editor', tr('📝 JavaScript код:'), '', tr('Введите JS код. Переменные: {var_name}')),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 600, 30), None),
                    ('save_output', 'check', tr('Сохранить результат в переменную'), True, None),
                    ('output_var', 'line', tr('Имя переменной:'), 'js_result', None),
                    ('no_return', 'check', tr('Не возвращать значение'), False, None),
                    ('inject_vars', 'check', tr('Инжектировать переменные из таблицы в контекст'), True, None),
                ]
            },
            AgentType.PROGRAM_LAUNCH: {
                'title': tr("⚙️ Запуск программы — внешние утилиты и скрипты"),
                'help': tr("Запуск .exe, .bat, Python-скриптов, ffmpeg, ImageMagick и т.д. Переменные: {var_name}"),
                'fields': [
                    ('executable', 'file_browse', tr('Исполняемый файл:'), '', tr('Executables (*.exe *.bat *.cmd *.sh *.py);;All Files (*)')),
                    ('arguments', 'line', tr('Параметры запуска:'), '', tr('Аргументы командной строки. Переменные: {var_name}')),
                    ('working_dir', 'dir_browse', tr('Рабочая папка:'), '', tr('Папка выполнения (пусто = папка проекта)')),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 3600, 60), None),
                    ('no_wait', 'check', tr('Не ждать завершения работы'), False, tr('Экшен не будет ждать пока программа закончит')),
                    ('hide_window', 'check', tr('Не показывать окно процесса'), True, None),
                    ('save_exit_code', 'check', tr('Записать EXIT CODE'), True, None),
                    ('exit_code_var', 'line', tr('Переменная для EXIT CODE:'), 'exit_code', None),
                    ('save_stdout', 'check', tr('Записать STD OUT в переменную'), True, None),
                    ('stdout_var', 'line', tr('Переменная для STD OUT:'), 'program_stdout', None),
                    ('save_stderr', 'check', tr('Записать STD ERR в переменную'), True, None),
                    ('stderr_var', 'line', tr('Переменная для STD ERR:'), 'program_stderr', None),
                    ('env_vars', 'text', tr('Переменные окружения:'), '', tr('KEY=VALUE по строкам')),
                ]
            },
            AgentType.LIST_OPERATION: {
                'title': tr("📃 Операции со списком"),
                'help': tr("Работа со списками: добавление, получение, удаление, сортировка, перемешивание, дедупликация. Данные хранятся в контексте."),
                'fields': [
                    ('operation', 'combo', tr('Операция:'), [
                        # ── Контекстные списки ──────────────────────────────
                        (tr('Добавить строку'), 'add_line'),
                        (tr('Добавить текст (многострочный)'), 'add_text'),
                        (tr('Получить строку'), 'get_line'),
                        (tr('Получить количество строк'), 'count'),
                        (tr('Удалить строки'), 'remove'),
                        (tr('Удалить дубли'), 'deduplicate'),
                        (tr('Перемешать'), 'shuffle'),
                        (tr('Сортировать'), 'sort'),
                        (tr('Объединить элементы'), 'join'),
                        (tr('Загрузить из файла'), 'load_file'),
                        (tr('Сохранить в файл'), 'save_file'),
                        (tr('Очистить'), 'clear'),
                        # ── Проектные списки (из панели Списки/Таблицы) ─────
                        (tr('── Проектные списки ──'), '__sep_proj_list__'),
                        (tr('📃 Взять строку из проектного списка → переменная'), 'proj_list_get'),
                        (tr('📃 Добавить строку в проектный список'), 'proj_list_add'),
                        (tr('📃 Удалить строку из проектного списка'), 'proj_list_remove'),
                        (tr('📃 Загрузить весь проектный список в переменную'), 'proj_list_load'),
                        (tr('📃 Сохранить переменную в проектный список'), 'proj_list_save'),
                        (tr('📃 Получить кол-во строк проектного списка'), 'proj_list_count'),
                        (tr('📃 Очистить проектный список'), 'proj_list_clear'),
                    ], 'add_line'),
                    ('project_list_name', 'line', tr('📃 Имя проектного списка:'), '',
                     tr('Имя из панели "Списки/Таблицы". Поддерживает {переменную}')),
                    ('list_var', 'line', tr('Имя списка (переменная):'), 'my_list', tr('Имя переменной-списка в контексте')),
                    ('value',    'line', tr('Значение / текст:'), '', tr('Для добавления, поиска, фильтрации. Переменные: {var_name}')),
                    ('file_path_or_var', 'line', tr('Путь к файлу или {переменная}:'), '', tr('Для upload_file')),
                    ('after_upload_action', 'combo',
                     tr('Действие после загрузки:'),
                     [('enter', tr('Нажать Enter')),
                      ('click', tr('Клик (левый)')),
                      ('dblclick', tr('Двойной клик')),
                      ('right_click', tr('Правый клик')),
                      ('none', tr('Ничего'))],
                     tr('Что делать после выбора файла')),
                    ('position', 'combo', tr('Позиция вставки:'), [
                        (tr('В конец'), 'end'),
                        (tr('В начало'), 'start'),
                        (tr('По номеру'), 'index'),
                    ], 'end'),
                    ('index', 'spin', tr('Номер позиции:'), (0, 99999, 0), tr('Нумерация с 0')),
                    ('get_mode', 'combo', tr('Критерий получения/удаления:'), [
                        (tr('Первую'), 'first'),
                        (tr('Последнюю'), 'last'),
                        (tr('По номеру'), 'by_index'),
                        (tr('Случайную'), 'random'),
                        (tr('Содержит текст'), 'contains'),
                        (tr('Не содержит текст'), 'not_contains'),
                        (tr('Regex'), 'regex'),
                        (tr('Все'), 'all'),
                    ], 'first'),
                    ('delete_after_get', 'check', tr('Удалить строку после получения'), False, None),
                    ('sort_numeric', 'check', tr('Числовая сортировка'), False, tr('Сортировать как числа, а не как строки')),
                    ('sort_descending', 'check', tr('По убыванию'), False, None),
                    ('join_separator', 'line', tr('Разделитель (для объединения):'), '\\n', None),
                    ('file_path', 'file_browse', tr('Путь к файлу:'), '', tr('Text Files (*.txt *.csv *.tsv *.log);;All Files (*)')),
                    ('auto_load_from_file', 'check', tr('Загружать из файла при каждом запуске'), False,
                     tr('Каждый раз перед выполнением этого сниппета загружать список из файла заново')),
                    ('file_append', 'check', tr('Дописывать в файл (не перезаписывать)'), True, None),
                    ('result_var', 'line', tr('Переменная для результата:'), 'list_result', tr('Куда сохранить полученное значение')),
                    # ── Поля для операций с проектными списками ─────────────
                    ('proj_get_mode', 'combo', tr('Критерий получения (проект):'), [
                        (tr('Первую строку'), 'first'),
                        (tr('Последнюю строку'), 'last'),
                        (tr('Случайную строку'), 'random'),
                        (tr('По номеру'), 'by_index'),
                        (tr('Содержит текст'), 'contains'),
                        (tr('Regex'), 'regex'),
                    ], 'first'),
                    ('proj_delete_after_get', 'check', tr('Удалить строку после получения'), False,
                     tr('Эмулирует очередь: взял — удалил')),
                    ('proj_add_position', 'combo', tr('Позиция добавления:'), [
                        (tr('В конец'), 'end'),
                        (tr('В начало'), 'start'),
                    ], 'end'),
                    ('proj_value', 'line', tr('Значение (для добавления/удаления):'), '',
                     tr('Переменные: {var_name}')),
                ]
            },
            AgentType.TABLE_OPERATION: {
                'title': tr("📊 Операции с таблицей"),
                'help': tr("Работа с таблицами (CSV/TSV): чтение, запись ячеек, строк, столбцов, сортировка, дедупликация. Данные в контексте."),
                'fields': [
                    ('operation', 'combo', tr('Операция:'), [
                        # ── Контекстные таблицы ─────────────────────────────
                        (tr('Загрузить из файла'), 'load'),
                        (tr('Сохранить в файл'), 'save'),
                        (tr('Прочитать ячейку'), 'read_cell'),
                        (tr('Записать ячейку'), 'write_cell'),
                        (tr('Добавить строку'), 'add_row'),
                        (tr('Получить строку'), 'get_row'),
                        (tr('Удалить строки'), 'delete_rows'),
                        (tr('Взять столбец в список'), 'get_column'),
                        (tr('Добавить список в столбец'), 'set_column'),
                        (tr('Удалить столбец'), 'delete_column'),
                        (tr('Получить кол-во строк'), 'row_count'),
                        (tr('Получить кол-во столбцов'), 'col_count'),
                        (tr('Удалить дубли'), 'deduplicate'),
                        (tr('Сортировать'), 'sort'),
                        # ── Проектные таблицы (из панели Списки/Таблицы) ────
                        (tr('── Проектные таблицы ──'), '__sep_proj_table__'),
                        (tr('📊 Взять строку из проектной таблицы → переменная'), 'proj_table_get_row'),
                        (tr('📊 Прочитать ячейку из проектной таблицы'), 'proj_table_read_cell'),
                        (tr('📊 Записать ячейку в проектную таблицу'), 'proj_table_write_cell'),
                        (tr('📊 Добавить строку в проектную таблицу'), 'proj_table_add_row'),
                        (tr('📊 Удалить строку из проектной таблицы'), 'proj_table_delete_row'),
                        (tr('📊 Загрузить проектную таблицу в переменную'), 'proj_table_load'),
                        (tr('📊 Взять столбец из проектной таблицы в список'), 'proj_table_get_column'),
                        (tr('📊 Получить кол-во строк проектной таблицы'), 'proj_table_row_count'),
                        (tr('📊 Очистить проектную таблицу'), 'proj_table_clear'),
                    ], 'load'),
                    ('project_table_name', 'line', tr('📊 Имя проектной таблицы:'), '',
                     tr('Имя из панели "Списки/Таблицы". Поддерживает {переменную}')),
                    ('table_var', 'line', tr('Имя таблицы (переменная):'), 'my_table', tr('Имя переменной-таблицы в контексте')),
                    ('file_path', 'file_browse', tr('Путь к файлу:'), '', tr('CSV/TSV Files (*.csv *.tsv *.txt);;All Files (*)')),
                    ('auto_load_from_file', 'check', tr('Загружать из файла при каждом запуске'), False,
                     tr('Каждый раз перед выполнением этого сниппета загружать таблицу из файла заново')),
                    ('delimiter', 'combo', tr('Разделитель:'), [
                        (tr('Авто'), 'auto'),
                        (tr('Запятая (,)'), ','),
                        (tr('Точка с запятой (;)'), ';'),
                        (tr('Табуляция (Tab)'), '\\t'),
                    ], 'auto'),
                    ('row_index', 'line', tr('Номер строки:'), '0', tr('Нумерация с 0. Переменные: {var_name}')),
                    ('col_index', 'line', tr('Столбец:'), '0', tr('Номер (с 0) или буква (A, B, C...). Переменные: {var_name}')),
                    ('cell_value', 'line', tr('Значение:'), '', tr('Для записи. Переменные: {var_name}')),
                    ('row_values', 'line', tr('Значения строки:'), '', tr('Через разделитель: val1;val2;val3')),
                    ('get_mode', 'combo', tr('Критерий строк:'), [
                        (tr('Все'), 'all'),
                        (tr('Первую'), 'first'),
                        (tr('По номеру'), 'by_index'),
                        (tr('Случайную'), 'random'),
                        (tr('Содержит текст'), 'contains'),
                        (tr('Regex'), 'regex'),
                    ], 'first'),
                    ('filter_text', 'line', tr('Текст фильтра:'), '', tr('Для поиска/фильтрации')),
                    ('delete_after_get', 'check', tr('Удалить строку после получения'), False, None),
                    ('sort_column', 'line', tr('Столбец сортировки:'), '0', None),
                    ('sort_numeric', 'check', tr('Числовая сортировка'), False, None),
                    ('sort_descending', 'check', tr('По убыванию'), False, None),
                    ('dedup_column', 'line', tr('Столбец дедупликации:'), '0', None),
                    ('target_list', 'line', tr('Список назначения:'), '', tr('Для взять столбец / получить строку')),
                    ('result_var', 'line', tr('Переменная для результата:'), 'table_result', None),
                    # ── Поля для операций с проектными таблицами ────────────
                    ('proj_row_get_mode', 'combo', tr('Критерий строки (проект):'), [
                        (tr('Первую'), 'first'),
                        (tr('Последнюю'), 'last'),
                        (tr('По номеру'), 'by_index'),
                        (tr('Случайную'), 'random'),
                        (tr('Содержит текст (в столбце)'), 'contains'),
                        (tr('Regex (в столбце)'), 'regex'),
                    ], 'first'),
                    ('proj_row_index', 'line', tr('Номер строки (для by_index):'), '0',
                     tr('Нумерация с 0. Поддерживает {переменную}')),
                    ('proj_col_index', 'line', tr('Столбец (номер или имя):'), '0',
                     tr('0, 1, 2... или имя колонки. Поддерживает {переменную}')),
                    ('proj_filter_text', 'line', tr('Текст фильтра:'), '',
                     tr('Для contains/regex. Поддерживает {переменную}')),
                    ('proj_cell_value', 'line', tr('Значение ячейки (для записи):'), '',
                     tr('Поддерживает {переменную}')),
                    ('proj_row_values', 'line', tr('Значения строки (через ;):'), '',
                     tr('val1;val2;val3 — для добавления строки. Поддерживает {переменную}')),
                    ('proj_delete_after_get', 'check', tr('Удалить строку после получения'), False,
                     tr('Эмулирует очередь: взял — удалил')),
                    ('proj_result_format', 'combo', tr('Формат результата:'), [
                        (tr('JSON-строка (dict)'), 'json'),
                        (tr('Список значений'), 'list'),
                        (tr('Первое значение'), 'first_value'),
                    ], 'json'),
                ]
            },
            AgentType.FILE_OPERATION: {
                'title': tr("📄 Файлы — чтение, запись, копирование"),
                'help': tr("Работа с файлами. Переменные: {var_name}"),
                'fields': [
                    ('file_action', 'combo', tr('Действие:'), [
                        (tr('Взять текст (прочитать)'), 'read'),
                        (tr('Записать текст'), 'write'),
                        (tr('Копировать'), 'copy'),
                        (tr('Переместить'), 'move'),
                        (tr('Удалить'), 'delete'),
                        (tr('Проверить существование'), 'exists'),
                    ], 'read'),
                    ('file_path', 'file_browse', tr('Путь к файлу:'), '', tr('All Files (*)')),
                    ('new_path', 'line', tr('Новый путь:'), '', tr('Для копирования/перемещения')),
                    ('content', 'text', tr('Текст для записи:'), '', tr('Переменные: {var_name}')),
                    ('append_mode', 'check', tr('Дописать в файл (не перезаписывать)'), True, None),
                    ('add_newline', 'check', tr('Записать перенос строки в конец'), True, None),
                    ('delete_after_read', 'check', tr('Удалить файл после чтения'), False, None),
                    ('encoding', 'combo', tr('Кодировка:'), [
                        (tr('UTF-8'), 'utf-8'), (tr('CP1251'), 'cp1251'),
                        (tr('Latin-1'), 'latin-1'), (tr('Auto'), 'auto'),
                    ], 'utf-8'),
                    ('result_var', 'line', tr('Переменная для результата:'), 'file_content', None),
                ]
            },
            AgentType.DIR_OPERATION: {
                'title': tr("📁 Директории — создание, удаление, списки файлов"),
                'help': tr("Работа с папками. Переменные: {var_name}"),
                'fields': [
                    ('dir_action', 'combo', tr('Действие:'), [
                        (tr('Создать'), 'create'),
                        (tr('Удалить'), 'delete'),
                        (tr('Копировать'), 'copy'),
                        (tr('Переместить'), 'move'),
                        (tr('Проверить существование'), 'exists'),
                        (tr('Получить список файлов'), 'list_files'),
                        (tr('Получить список директорий'), 'list_dirs'),
                        (tr('Путь к файлу (по номеру/случайный)'), 'get_file'),
                    ], 'list_files'),
                    ('dir_path', 'dir_browse', tr('Путь к директории:'), '', None),
                    ('new_path', 'line', tr('Новый путь:'), '', tr('Для копирования/перемещения')),
                    ('recursive', 'check', tr('Искать в поддиректориях'), False, None),
                    ('mask', 'line', tr('Фильтр по маске:'), '', tr('Пример: *.png|*.jpg')),
                    ('file_select', 'combo', tr('Выбор файла:'), [
                        (tr('По номеру'), 'by_index'),
                        (tr('Случайный'), 'random'),
                    ], 'random'),
                    ('file_index', 'spin', tr('Номер файла:'), (0, 99999, 0), tr('Нумерация с 0')),
                    ('result_var', 'line', tr('Переменная:'), 'dir_result', None),
                    ('result_list', 'line', tr('Список для результатов:'), 'file_list', tr('Для list_files/list_dirs')),
                ]
            },
            AgentType.TEXT_PROCESSING: {
                'title': tr("✂️ Обработка текста — regex, замена, split, spintax"),
                'help': tr("Входной текст — User Prompt или поле ниже. Переменные: {var_name}"),
                'fields': [
                    ('text_action', 'combo', tr('Действие:'), [
                        (tr('Regex (поиск)'), 'regex'),
                        (tr('Замена (replace)'), 'replace'),
                        (tr('Split (разделить)'), 'split'),
                        (tr('Spintax'), 'spintax'),
                        (tr('ToLower'), 'to_lower'),
                        (tr('ToUpper'), 'to_upper'),
                        (tr('Trim'), 'trim'),
                        (tr('UrlEncode'), 'url_encode'),
                        (tr('UrlDecode'), 'url_decode'),
                        (tr('Подстрока'), 'substring'),
                        (tr('Транслитерация'), 'translit'),
                        (tr('В переменную'), 'to_var'),
                        (tr('В список'), 'to_list'),
                    ], 'regex'),
                    ('input_text', 'text', tr('Входной текст:'), '', tr('Или используйте User Prompt. Переменные: {var_name}')),
                    ('pattern', 'line', tr('Regex / Что искать:'), '', tr('Регулярное выражение или текст для поиска')),
                    ('replacement', 'line', tr('На что заменить:'), '', tr('Для замены')),
                    ('separator', 'line', tr('Разделитель:'), ',', tr('Для split')),
                    ('take_mode', 'combo', tr('Что брать (regex):'), [
                        (tr('Первое'), 'first'), (tr('Все'), 'all'),
                        (tr('Случайное'), 'random'), (tr('По номеру'), 'by_index'),
                    ], 'first'),
                    ('match_index', 'spin', tr('Номер совпадения:'), (0, 999, 0), None),
                    ('error_on_empty', 'check', tr('Ошибка при пустом результате'), False, None),
                    ('substr_from', 'spin', tr('Подстрока от:'), (0, 99999, 0), None),
                    ('substr_to', 'spin', tr('Подстрока до:'), (0, 99999, 0), tr('0 = до конца')),
                    ('result_var', 'line', tr('Переменная:'), 'text_result', None),
                    ('result_list', 'line', tr('Список:'), '', tr('Для split/regex all')),
                ]
            },
            AgentType.JSON_XML: {
                'title': tr("🔣 JSON / XML — парсинг и запросы"),
                'help': tr("Парсинг, запросы, изменение JSON/XML. Переменные: {var_name}"),
                'fields': [
                    ('data_type', 'combo', tr('Тип данных:'), [
                        (tr('JSON'), 'json'), (tr('XML'), 'xml'),
                    ], 'json'),
                    ('jx_action', 'combo', tr('Действие:'), [
                        (tr('Парсинг'), 'parse'),
                        (tr('JsonPath / XPath запрос'), 'query'),
                        (tr('Получить значение по ключу'), 'get_value'),
                        (tr('Установить значение'), 'set_value'),
                        (tr('Добавить в список (по свойству)'), 'to_list'),
                        (tr('Добавить в таблицу'), 'to_table'),
                    ], 'parse'),
                    ('input_source', 'combo', tr('Источник данных:'), [
                        (tr('Текст (ввести ниже)'), 'text'),
                        (tr('Из переменной'), 'variable'),
                        (tr('Из файла'), 'file'),
                    ], 'text'),
                    ('inline_data', 'text', tr('📝 Данные (JSON/XML):'), '', tr('Вставьте JSON или XML. Переменные: {var_name}')),
                    ('input_var', 'line', tr('Переменная-источник:'), '', tr('Имя переменной с данными. Пример: {http_response}')),
                    ('input_file', 'file_browse', tr('Файл с данными:'), '', tr('JSON (*.json);;XML (*.xml);;All Files (*)')),
                    ('query_expr', 'line', tr('JsonPath / XPath:'), '', tr('JSON: $.store.book[*].title | XML: //CD/TITLE')),
                    ('key_path', 'line', tr('Ключ / путь:'), '', tr('Пример: data.items[0].name')),
                    ('set_value', 'line', tr('Устанавливаемое значение:'), '', tr('Для set_value. Переменные: {var_name}')),
                    ('property_name', 'line', tr('Свойство массива:'), '', tr('Для to_list: имя поля в каждом элементе')),
                    ('result_var', 'line', tr('Переменная результата:'), 'jx_result', None),
                    ('result_list', 'line', tr('Список результатов:'), '', tr('Для query/to_list — список совпадений')),
                    ('result_table', 'line', tr('Таблица:'), '', tr('Для to_table')),
                ]
            },
            AgentType.VARIABLE_PROC: {
                'title': tr("🔧 Обработка переменных — set, inc, dec, copy, cast, concat"),
                'help': tr("Работа с переменными проекта и контекста. Переменные: {var_name}"),
                'fields': [
                    ('var_action', 'combo', tr('Действие:'), [
                        (tr('Установить значение'), 'set'),
                        (tr('Увеличить счётчик'), 'increment'),
                        (tr('Уменьшить счётчик'), 'decrement'),
                        (tr('Очистить переменную'), 'clear'),
                        (tr('Очистить все переменные'), 'clear_all'),
                        (tr('Копировать в другую'), 'copy'),
                        (tr('Конкатенация (склеить)'), 'concat'),
                        (tr('Длина (length)'), 'length'),
                        (tr('Приведение типа (cast)'), 'type_cast'),
                    ], 'set'),
                    ('var_name', 'line', tr('Имя переменной:'), '', tr('Имя в контексте (без фигурных скобок)')),
                    ('var_value', 'text', tr('Значение:'), '', tr('Для set. Переменные: {var_name}. Для concat: через запятую var1,var2,text')),
                    ('step_value', 'spin', tr('Шаг (для inc/dec):'), (1, 100000, 1), None),
                    ('target_var', 'line', tr('Целевая переменная:'), '', tr('Для copy/length: куда записать результат')),
                    ('concat_separator', 'line', tr('Разделитель (concat):'), '', tr('Символ между частями. Пустой = без разделителя')),
                    ('cast_type', 'combo', tr('Тип (для cast):'), [
                        (tr('Строка (string)'), 'string'),
                        (tr('Целое число (int)'), 'int'),
                        (tr('Дробное (float)'), 'float'),
                        (tr('Булево (bool)'), 'bool'),
                    ], 'string'),
                    ('clear_except', 'line', tr('Не очищать:'), '', tr('Для clear_all: через запятую')),
                    ('save_to_project', 'check', tr('Синхронизировать с переменными проекта'), True, tr('Обновить значение в таблице переменных проекта')),
                ]
            },
            AgentType.RANDOM_GEN: {
                'title': tr("🎲 Random — генерация случайных данных"),
                'help': tr("Генерация чисел, строк, логинов. Результат в переменной."),
                'fields': [
                    ('random_type', 'combo', tr('Тип:'), [
                        (tr('Число'), 'number'),
                        (tr('Строка'), 'text'),
                        (tr('Логин / никнейм'), 'login'),
                    ], 'number'),
                    ('num_from', 'spin', tr('Число от:'), (0, 999999999, 0), None),
                    ('num_to', 'spin', tr('Число до (не включительно):'), (1, 999999999, 100), None),
                    ('str_len_min', 'spin', tr('Длина строки от:'), (1, 100, 5), None),
                    ('str_len_max', 'spin', tr('Длина строки до:'), (1, 100, 12), None),
                    ('use_upper', 'check', tr('Заглавные (A-Z)'), True, None),
                    ('use_lower', 'check', tr('Строчные (a-z)'), True, None),
                    ('use_digits', 'check', tr('Цифры (0-9)'), True, None),
                    ('custom_chars', 'line', tr('Свои символы:'), '', tr('Если заполнено — используются только эти')),
                    ('require_all', 'check', tr('Обязательно все типы символов'), False, None),
                    ('login_formula', 'line', tr('Формула логина:'), '[Eng|3][RndNum|1|99]', tr('Слоги + цифры')),
                    ('result_var', 'line', tr('Переменная:'), 'random_result', None),
                ],
            },
            AgentType.BROWSER_PROFILE_OP: {
                'title': tr("🪪 Browser Profile — операции с профилем"),
                'help': tr(
                    "Сохранение, загрузка, переназначение полей и обновление профиля браузера. "
                    "Профиль хранит: личность (имя, e-mail, дата рождения), браузерный отпечаток, "
                    "куки, прокси, User-Agent, разрешение, шрифты, временную зону, геолокацию и переменные."
                ),
                'fields': [
                    # ── Операция ─────────────────────────────────────────────
                    ('profile_op', 'combo', tr('Операция:'), [
                        (tr('💾 Сохранить профиль (файл .csprofile)'),       'save_file'),
                        (tr('📂 Загрузить профиль (файл .csprofile)'),       'load_file'),
                        (tr('📁 Сохранить профиль-папку'),                   'save_folder'),
                        (tr('📂 Запустить инстанс с профиль-папкой'),        'launch_folder'),
                        (tr('✏️  Переназначить поля профиля'),               'reassign'),
                        (tr('🔄 Обновить профиль (новая версия браузера)'),  'update'),
                        (tr('👁 Показать текущий профиль'),                  'show'),
                        (tr('🔀 Сгенерировать новый профиль'),               'generate'),
                    ], 'save_file'),
                    ('instance_id', 'line', tr('ID инстанса:'), '',
                     tr('Пусто = первый активный. Или {browser_instance_id}')),
                    # ── Путь к файлу / папке ──────────────────────────────────
                    ('_sep_path', 'label', '── 📂 Путь ─────────────────────────────────────', '', ''),
                    ('profile_path', 'line', tr('Путь к файлу / папке:'), '',
                     tr('Пример: {project_dir}\\profiles\\{login}.csprofile\n'
                        'Или для папки: {project_dir}\\ProfileDirs\\{login}\\')),
                    ('create_if_missing', 'check', tr('Создать папку/файл если не существует'), True,
                     tr('При загрузке: если файл не найден — создать новый профиль')),
                    ('error_on_incompatible', 'check', tr('Ошибка при загрузке несовместимого профиля'), False,
                     tr('Профиль другого движка браузера вызовет ошибку вместо предупреждения')),
                    # ── Переменные ────────────────────────────────────────────
                    ('_sep_vars', 'label', '── 📦 Переменные ────────────────────────────────', '', ''),
                    ('save_variables', 'check', tr('Сохранять переменные вместе с профилем'), False,
                     tr('⚠️ При загрузке такого профиля переменные будут перезаписаны')),
                    ('variables_mode', 'combo', tr('Какие переменные:'), [
                        (tr('Все переменные'),          'all'),
                        (tr('Только выбранные'),        'selected'),
                    ], 'all'),
                    ('variables_list', 'line', tr('Переменные (через запятую):'), '',
                     tr('login, password, last_activity — только если режим «Выбранные»')),
                    ('create_missing_vars', 'check', tr('Создать отсутствующие переменные при загрузке'), True,
                     tr('Переменные из профиля, которых нет в проекте, будут созданы автоматически')),
                    # ── Прокси ───────────────────────────────────────────────
                    ('_sep_proxy', 'label', '── 🔌 Прокси ────────────────────────────────────', '', ''),
                    ('save_proxy', 'check', tr('Сохранять прокси вместе с профилем'), False, ''),
                    ('proxy_string', 'line', tr('Переназначить прокси:'), '',
                     tr('login:pass@host:port  или  socks5://host:port  или  {proxy_var}')),
                    # ── Переназначение полей ──────────────────────────────────
                    ('_sep_reassign', 'label', '── ✏️ Переназначить поля профиля ──────────────', '', ''),
                    ('reassign_ua', 'line', tr('User-Agent:'), '',
                     tr('Пусто = не менять. Поддерживает {переменные}')),
                    ('reassign_name', 'line', tr('Имя:'), '',
                     tr('{-Profile.Name-}  → первое имя профиля')),
                    ('reassign_surname', 'line', tr('Фамилия:'), '', ''),
                    ('reassign_email', 'line', tr('E-mail:'), '',
                     tr('Поддерживает {переменные}. Пример: {login}@gmail.com')),
                    ('reassign_login', 'line', tr('Логин:'), '', ''),
                    ('reassign_password', 'line', tr('Пароль:'), '', ''),
                    ('reassign_phone', 'line', tr('Телефон:'), '', ''),
                    ('reassign_birthday', 'line', tr('Дата рождения (YYYY-MM-DD):'), '', ''),
                    ('reassign_gender', 'combo', tr('Пол:'), [
                        (tr('Не менять'), ''),
                        (tr('Мужской'),   'male'),
                        (tr('Женский'),   'female'),
                    ], ''),
                    ('reassign_viewport', 'line', tr('Разрешение экрана (WxH):'), '',
                     tr('Пример: 1920x1080. Пусто = не менять')),
                    ('reassign_timezone', 'line', tr('Временна́я зона:'), '',
                     tr('Пример: Europe/Moscow. Пусто = не менять')),
                    ('reassign_geo', 'line', tr('Геолокация (lat,lon):'), '',
                     tr('Пример: 55.7558,37.6176. Пусто = не менять')),
                    ('reassign_language', 'line', tr('Язык браузера:'), '',
                     tr('Пример: ru-RU,ru;q=0.9. Пусто = не менять')),
                    # ── Обновление профиля ────────────────────────────────────
                    ('_sep_update', 'label', '── 🔄 Обновление профиля ────────────────────────', '', ''),
                    ('update_max_profiles', 'spin', tr('Макс. профилей для поиска:'), (1, 4000, 400),
                     tr('ZennoPoster загружает до 4000, ProjectMaker — до 400')),
                    ('update_same_browser', 'check', tr('Только тот же движок браузера'), True, ''),
                    ('update_same_os', 'check', tr('Только та же ОС'), True, ''),
                    ('update_same_language', 'check', tr('Только тот же язык'), True, ''),
                    # ── Результат ─────────────────────────────────────────────
                    ('_sep_result', 'label', '── 📤 Результат ─────────────────────────────────', '', ''),
                    ('result_var', 'line', tr('Результат →:'), '',
                     tr('{переменная} — куда сохранить результат (путь, статус, имя профиля)')),
                    ('profile_name_var', 'line', tr('Имя профиля →:'), '',
                     tr('{переменная} — получить {-Profile.Name-} после загрузки')),
                    ('on_error', 'combo', tr('При ошибке:'), [
                        (tr('⛔ Остановить'),         'stop'),
                        (tr('🔁 Продолжить'),         'continue'),
                        (tr('↪️ Перейти к BAD END'),  'bad_end'),
                    ], 'stop'),
                ],
            },
            AgentType.BROWSER_LAUNCH: {
                'title': tr("🌐 Browser Launch — запуск браузера"),
                'help': tr("Запускает браузер с выбранным профилем и прокси. ID инстанса сохраняется в переменную. Убедитесь что установлено: pip install selenium webdriver-manager"),
                'fields': [
                    ('profile_folder', 'dir_browse', tr('Папка профиля:'), '', tr('Путь к папке профиля Chromium (пусто = временный профиль)')),
                    ('create_if_missing', 'check', tr('Создать папку если не существует'), True, None),
                    ('headless', 'check', tr('Headless режим (без окна)'), False, tr('Запуск без видимого окна браузера')),
                    ('window_width', 'spin', tr('Ширина окна:'), (800, 3840, 1280), tr('Ширина окна браузера')),
                    ('window_height', 'spin', tr('Высота окна:'), (600, 2160, 900), tr('Высота окна браузера')),
                    ('proxy_enabled', 'check', tr('Использовать прокси'), False, None),
                    ('proxy_protocol', 'combo', tr('Протокол:'), [
                        ('HTTP', 'http'), ('SOCKS4', 'socks4'), ('SOCKS5', 'socks5')
                    ], 'http'),
                    ('proxy_string', 'line', tr('Прокси:'), '', tr('login:pass@host:port  или  host:port')),
                    ('user_agent', 'line', tr('User-Agent:'), '', tr('Пусто = дефолтный')),
                    ('instance_id_var', 'line', tr('ID инстанса →:'), '{browser_instance_id}', tr('Переменная для сохранения ID')),
                    ('auto_embed', 'check', tr('Автовстраивание в панель'), False, tr('Встроить окно браузера в панель (только Windows)')),
                ],
            },
            AgentType.BROWSER_ACTION: {
                'title': tr("🖱 Browser Action — действие браузера"),
                'help': tr("Выполняет действие в открытом браузере. Используйте {переменные} в полях. Для координат: X и Y от левого верхнего угла окна браузера."),
                'fields': [
                    ('instance_id', 'line', tr('ID инстанса:'), '', tr('Пусто = первый доступный. Или {browser_instance_id}')),
                    ('action', 'combo', tr('Действие:'), [
                        (tr('Перейти по URL'), 'navigate'),
                        (tr('Клик по элементу'), 'click'),
                        (tr('Клик по координатам'), 'click_xy'),
                        (tr('Клик по тексту на странице'), 'click_text'),
                        (tr('Двойной клик по элементу'), 'double_click'),
                        (tr('Двойной клик по координатам'), 'double_click_xy'),
                        (tr('Правый клик по элементу'), 'right_click'),
                        (tr('Правый клик по координатам'), 'right_click_xy'),
                        (tr('Наведение на элемент'), 'hover'),
                        (tr('Наведение по координатам'), 'hover_xy'),
                        (tr('Ввести текст'), 'type_text'),
                        (tr('Очистить поле'), 'clear_field'),
                        (tr('Выбрать опцию'), 'select_option'),
                        (tr('Получить текст'), 'get_text'),
                        (tr('Получить атрибут'), 'get_attr'),
                        (tr('Получить URL'), 'get_url'),
                        (tr('Получить заголовок'), 'get_title'),
                        (tr('Получить HTML'), 'get_html'),
                        (tr('Ждать элемент'), 'wait_element'),
                        (tr('Ждать URL'), 'wait_url'),
                        (tr('Пауза (сек)'), 'wait_seconds'),
                        (tr('Выполнить JS'), 'execute_js'),
                        (tr('Скролл к элементу'), 'scroll_to'),
                        (tr('📎 Загрузить файл на сервер'), 'upload_file'),
                        (tr('Скролл страницы'), 'scroll_page'),
                        (tr('Получить куки'), 'cookie_get'),
                        (tr('Установить куку'), 'cookie_set'),
                        (tr('Очистить куки'), 'cookie_clear'),
                        (tr('Скриншот'), 'screenshot'),
                        (tr('Новая вкладка'), 'tab_new'),
                        (tr('Активировать вкладку'), 'tab_activate'),
                        (tr('Закрыть вкладку'), 'tab_close'),
                        (tr('Назад'), 'navigate_back'),
                        (tr('Вперёд'), 'navigate_forward'),
                        (tr('Перезагрузить'), 'reload'),
                        (tr('Максимизировать'), 'maximize'),
                        (tr('Закрыть браузер'), 'close_browser'),
                    ], 'navigate'),
                    ('selector_type', 'combo', tr('Тип селектора:'), [
                        ('CSS', 'css'), ('XPath', 'xpath'),
                        ('ID', 'id'), ('Name', 'name'), ('Tag', 'tag'),
                    ], 'css'),
                    # === ПОЛЯ ДЛЯ ЭЛЕМЕНТОВ (селектор) ===
                    ('target', 'line', tr('Селектор / URL / JS:'), '', tr('CSS-селектор, XPath, URL или JS-код')),
                    # === ПОЛЯ ДЛЯ КООРДИНАТ ===
                    ('coord_x', 'spin', tr('Координата X:'), (0, 9999, 500), tr('Пиксели от левого края (пример: 500)')),
                    ('coord_y', 'spin', tr('Координата Y:'), (0, 9999, 300), tr('Пиксели от верхнего края (пример: 300)')),
                    # === ПОЛЕ ДЛЯ ПОИСКА ПО ТЕКСТУ ===
                    ('search_text', 'line', tr('Текст для поиска:'), '', tr('Точный или частичный текст элемента')),
                    # === ОБЩИЕ ПОЛЯ ===
                    ('value', 'line', tr('Значение:'), '', tr('Текст для ввода, атрибут, параметр...')),
                    ('variable_out', 'line', tr('Результат →:'), '', tr('{имя_переменной} для сохранения результата')),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 600, 30), None),
                    ('wait_after', 'spin', tr('Пауза после (сек):'), (0, 60, 0), None),
                ],
            },
            AgentType.BROWSER_CLOSE: {
                'title': tr("🔴 Browser Close — закрыть браузер"),
                'help': tr("Закрывает браузерный инстанс. Оставьте поле пустым чтобы закрыть все."),
                'fields': [
                    ('instance_id', 'line', tr('ID инстанса:'), '', tr('Пусто = закрыть все. Или {browser_instance_id}')),
                ],
            },
            AgentType.BROWSER_AGENT: {
                'title': tr("🌐🧠 Browser Agent — AI-управление браузером"),
                'help': tr(
                    "AI-агент анализирует DOM страницы и выполняет действия в браузере. "
                    "Получает задачу от Planner-ноды, составляет и исполняет план кликов/ввода."
                ),
                'fields': [
                    ('browser_instance_var', 'line', tr('Переменная ID инстанса:'), '{browser_instance_id}',
                     tr('Переменная с ID браузерного инстанса (из Browser Launch)')),
                    ('dom_max_elements', 'spin', tr('Макс. элементов DOM:'), (10, 500, 150),
                     tr('Максимум элементов для анализа. Больше = точнее, но медленнее')),
                    ('ai_timeout_sec', 'spin', tr('Таймаут AI (сек):'), (10, 600, 120),
                     tr('Максимальное время ожидания ответа от AI')),
                    ('max_actions', 'spin', tr('Макс. действий за шаг:'), (1, 50, 10),
                     tr('Максимум действий в одном запросе к AI')),
                    ('screenshot_verify', 'check', tr('Пиксельная верификация после действий'), False,
                     tr('Сравнивать скриншоты до/после для проверки результата')),
                    ('screenshot_diff_threshold', 'spin', tr('Порог diff (%):'), (1, 100, 5),
                     tr('Минимальный % изменений пикселей для считывания «действие сработало»')),
                    ('scroll_before_scan', 'check', tr('Скроллить перед сканированием DOM'), False,
                     tr('Прокрутить страницу вниз перед сбором элементов (для lazy-load контента)')),
                    ('include_shadow_dom', 'check', tr('Сканировать Shadow DOM'), True,
                     tr('Включать элементы внутри Shadow DOM (нужно для современных SPA)')),
                    ('action_wait_sec', 'spin', tr('Пауза между действиями (сек):'), (0, 10, 1),
                     tr('Задержка после каждого действия для загрузки страницы')),
                    ('variable_out', 'line', tr('Результат (переменная) →:'), '',
                     tr('{имя_переменной} для сохранения последнего извлечённого значения')),
                ],
            },
            AgentType.PROJECT_START: {
                'title': tr("▶️ СТАРТ — точка входа в проект"),
                'help': tr(
                    "Начальная точка выполнения проекта. Выберите режим запуска и настройте "
                    "браузер, AI-модель, переменные, ограничения, логирование и уведомления."
                ),
                'fields': [
                    # ════════════════════════════════════════════════════════
                    # РЕЖИМ ВЫПОЛНЕНИЯ
                    # ════════════════════════════════════════════════════════
                    ('_sep_run', 'label', '── 🚀 Режим выполнения ──────────────────────', '', ''),
                    ('run_mode', 'combo', tr('Режим:'), [
                        (tr('▶️  Обычный старт (без AI)'),          'plain'),
                        (tr('🤖  С AI-моделью'),                    'ai'),
                        (tr('⚡  Скрипт (Python/JS без модели)'),   'script'),
                        (tr('🔁  Гибридный (AI + скрипт)'),         'hybrid'),
                    ], 'plain'),
                    # AI-поля (видны только при run_mode = ai / hybrid)
                    ('model_id',          'line',  tr('Модель:'),             '',
                     tr('Пусто = из глобальных настроек. Пример: gpt-4o, claude-3-5-sonnet')),
                    ('ai_temperature',    'spin',  tr('Temperature:'),        (0, 20, 7),
                     tr('0–20 → 0.0–2.0; 7 = 0.7 — баланс креативность/точность')),
                    ('ai_max_tokens',     'spin',  tr('Max tokens:'),         (1, 32000, 4096), ''),
                    ('ai_system_prompt',  'text',  tr('Системный промпт:'),   '',
                     tr('Контекст для AI перед стартом проекта. Поддерживает {переменные}')),
                    # Скрипт-поля (видны только при run_mode = script / hybrid)
                    ('startup_script',    'code_editor', tr('Стартовый скрипт:'), '',
                     tr('Python-код, выполняемый перед первым узлом. '
                        'Доступны: context, variables, log')),
                    # ════════════════════════════════════════════════════════
                    # БРАУЗЕР
                    # ════════════════════════════════════════════════════════
                    ('_sep_browser', 'label', '── 🌐 Браузер ──────────────────────────────', '', ''),
                    ('browser_auto_launch', 'check', tr('Автозапуск браузера при старте'), True,
                     tr('Запустить браузерный инстанс перед выполнением первого узла')),
                    ('browser_engine', 'combo', tr('Движок браузера:'), [
                        (tr('Chrome / Chromium'),  'chrome'),
                        (tr('Firefox'),            'firefox'),
                        (tr('Edge'),               'edge'),
                    ], 'chrome'),
                    ('browser_headless',    'check', tr('Без GUI (headless)'), False,
                     tr('Запуск без видимого окна — быстрее, не требует экрана')),
                    ('browser_profile',     'dir_browse', tr('Профиль:'), '',
                     tr('Пусто = временный профиль. Папка с профилем браузера')),
                    ('browser_start_url',   'line',  tr('Стартовый URL:'), '',
                     tr('Открыть при запуске. Поддерживает {переменные}')),
                    ('browser_viewport',    'line',  tr('Размер окна (WxH):'), '1280x800',
                     tr('Ширина × Высота пикселей. Пример: 1920x1080')),
                    # ── Отображение в браузере ────────────────────────────
                    ('_sep_display',        'label', '── 🖼 Что загружать в браузере ─────────', '', ''),
                    ('browser_show_images', 'check', tr('Загружать изображения'),         True,  ''),
                    ('browser_show_js',     'check', tr('Выполнять JavaScript'),          True,  ''),
                    ('browser_show_css',    'check', tr('Загружать CSS / стили'),         True,  ''),
                    ('browser_show_fonts',  'check', tr('Загружать шрифты'),              True,  ''),
                    ('browser_block_media', 'check', tr('Блокировать видео и аудио'),     False, ''),
                    ('browser_block_ads',   'check', tr('Блокировать рекламу (adblock)'), False,
                     tr('Базовая блокировка по EasyList-правилам')),
                    ('browser_block_tracking','check',tr('Блокировать трекеры'),          False, ''),
                    # ── Идентификация ─────────────────────────────────────
                    ('_sep_identity', 'label', '── 🪪 Идентификация ─────────────────────────', '', ''),
                    ('browser_user_agent',  'line',  tr('User-Agent:'), '',
                     tr('Пусто = стандартный. Поддерживает {переменные}')),
                    ('browser_language',    'line',  tr('Язык браузера:'), 'ru-RU,ru;q=0.9',
                     tr('Accept-Language заголовок. Пример: en-US,en;q=0.9')),
                    ('browser_timezone',    'line',  tr('Временная зона:'), '',
                     tr('Пусто = системная. Пример: Europe/Moscow, America/New_York')),
                    ('browser_geolocation', 'line',  tr('Геолокация (lat,lon):'), '',
                     tr('Пусто = не эмулировать. Пример: 55.7558,37.6176')),
                    ('browser_random_ua',   'check', tr('Случайный User-Agent при каждом старте'), False, ''),
                    # ── Сеть ─────────────────────────────────────────────
                    ('_sep_net', 'label', '── 🔌 Сеть и прокси ─────────────────────────', '', ''),
                    ('browser_proxy',       'line',  tr('Прокси:'), '',
                     tr('Форматы: host:port  или  user:pass@host:port  или  socks5://host:port')),
                    ('browser_proxy_bypass','line',  tr('Bypass прокси:'), 'localhost,127.0.0.1',
                     tr('Хосты через запятую, для которых прокси не используется')),
                    ('browser_ignore_ssl',  'check', tr('Игнорировать SSL-ошибки'), False, ''),
                    ('browser_offline',     'check', tr('Режим Offline (нет сети)'), False, ''),
                    ('browser_throttle',    'combo', tr('Эмуляция скорости сети:'), [
                        (tr('Без ограничений'),    'none'),
                        (tr('Fast 3G'),            'fast3g'),
                        (tr('Slow 3G'),            'slow3g'),
                        (tr('GPRS'),               'gprs'),
                    ], 'none'),
                    # ── WebRTC / медиа ────────────────────────────────────
                    ('_sep_webrtc', 'label', '── 📷 WebRTC / Медиа-устройства ────────────', '', ''),
                    ('webrtc_fake_devices', 'check', tr('Эмулировать WebRTC-устройства'), False,
                     tr('Добавляет: --use-fake-device-for-media-stream --use-fake-ui-for-media-stream')),
                    ('webrtc_video_file',   'file_browse', tr('Видео-файл (.y4m):'), '',
                     tr('--use-file-for-fake-video-capture="путь"')),
                    ('webrtc_audio_file',   'file_browse', tr('Аудио-файл (.wav):'), '',
                     tr('--use-file-for-fake-audio-capture="путь". Добавьте %noloop для однократного воспроизведения')),
                    ('webrtc_audio_noloop', 'check', tr('Аудио без повтора (%noloop)'), False, ''),
                    ('webrtc_audioinput_name',  'line', tr('Имя AudioInput-устройства:'),  '', ''),
                    ('webrtc_audiooutput_name', 'line', tr('Имя AudioOutput-устройства:'), '', ''),
                    ('webrtc_videoinput_name',  'line', tr('Имя VideoInput-устройства:'),  '', ''),
                    # ── Доп. аргументы ────────────────────────────────────
                    ('_sep_args', 'label', '── ⚙️ Дополнительные аргументы ──────────────', '', ''),
                    ('browser_extra_args',  'text', tr('Аргументы запуска браузера:'), '',
                     tr('По одному на строку. Пример:\n--disable-web-security\n--no-sandbox\n--disable-blink-features=AutomationControlled')),
                    # ════════════════════════════════════════════════════════
                    # ВЫПОЛНЕНИЕ И ОГРАНИЧЕНИЯ
                    # ════════════════════════════════════════════════════════
                    ('_sep_exec', 'label', '── 🔢 Выполнение и ограничения ─────────────', '', ''),
                    ('max_iterations',   'spin',  tr('Макс. итераций:'),        (1, 100000, 1000),
                     tr('Принудительная остановка после N шагов')),
                    ('timeout_total',    'spin',  tr('Таймаут проекта (сек):'), (0, 86400, 0),
                     tr('0 = без ограничений')),
                    ('thread_count',     'spin',  tr('Потоков:'),               (1, 500, 1),
                     tr('Количество параллельных потоков выполнения')),
                    ('startup_delay',    'spin',  tr('Задержка старта (мс):'),  (0, 60000, 0),
                     tr('Пауза перед первым узлом')),
                    ('on_error', 'combo', tr('При ошибке:'), [
                        (tr('⛔ Остановить'),          'stop'),
                        (tr('🔁 Продолжить'),          'continue'),
                        (tr('🔄 Перезапустить узел'),  'restart_node'),
                        (tr('♻️ Перезапустить проект'),'restart_project'),
                    ], 'stop'),
                    ('retry_on_error',   'spin',  tr('Повторов при ошибке:'), (0, 50, 0), ''),
                    ('retry_delay_ms',   'spin',  tr('Задержка между повторами (мс):'), (0, 60000, 1000), ''),
                    ('retry_backoff',    'check', tr('Экспоненциальная задержка повторов'), False,
                     tr('Каждый следующий повтор ждёт в 2× дольше')),
                    # ════════════════════════════════════════════════════════
                    # ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
                    # ════════════════════════════════════════════════════════
                    ('_sep_env', 'label', '── 📦 Переменные окружения ──────────────────', '', ''),
                    ('env_vars', 'text', tr('KEY=VALUE (одна на строку):'), '',
                     tr('Устанавливаются в os.environ перед стартом.\nПоддерживает {переменные} в значениях')),
                    # ════════════════════════════════════════════════════════
                    # ДАННЫЕ И ВВОД
                    # ════════════════════════════════════════════════════════
                    ('_sep_data', 'label', '── 📄 Данные / входной файл ─────────────────', '', ''),
                    ('data_file',        'file_browse', tr('Файл данных (аккаунты/список):'), '',
                     tr('Загружается в переменную {data_lines} как список строк')),
                    ('data_encoding',    'combo', tr('Кодировка файла:'), [
                        ('UTF-8', 'utf-8'), ('UTF-8-BOM', 'utf-8-sig'),
                        ('CP1251', 'cp1251'), ('Latin-1', 'latin-1'),
                    ], 'utf-8'),
                    ('data_shuffle',     'check', tr('Перемешать данные перед стартом'), False, ''),
                    ('result_file',      'file_browse', tr('Файл результатов:'), '',
                     tr('Путь для сохранения результатов. Поддерживает {переменные}')),
                    ('result_mode',      'combo', tr('Режим записи результатов:'), [
                        (tr('Дописывать'),     'append'),
                        (tr('Перезаписывать'), 'overwrite'),
                    ], 'append'),
                    # ════════════════════════════════════════════════════════
                    # КАПЧА
                    # ════════════════════════════════════════════════════════
                    ('_sep_captcha', 'label', '── 🔐 Капча-сервис ──────────────────────────', '', ''),
                    ('captcha_service', 'combo', tr('Сервис:'), [
                        (tr('Нет'),          'none'),
                        (tr('2captcha'),     '2captcha'),
                        (tr('AntiCaptcha'),  'anticaptcha'),
                        (tr('CapMonster'),   'capmonster'),
                        (tr('RuCaptcha'),    'rucaptcha'),
                        (tr('CapSolver'),    'capsolver'),
                    ], 'none'),
                    ('captcha_api_key', 'line', tr('API ключ:'), '', ''),
                    # ════════════════════════════════════════════════════════
                    # ЛОГИРОВАНИЕ
                    # ════════════════════════════════════════════════════════
                    ('_sep_log', 'label', '── 📋 Логирование ───────────────────────────', '', ''),
                    ('log_level', 'combo', tr('Уровень лога:'), [
                        (tr('📋 DEBUG — всё подробно'), 'debug'),
                        (tr('ℹ️  INFO — основные события'), 'info'),
                        (tr('⚠️  WARNING — предупреждения'), 'warning'),
                        (tr('❌ ERROR — только ошибки'), 'error'),
                    ], 'info'),
                    ('log_timestamps',   'check', tr('Временны́е метки в логе'),   True,  ''),
                    ('log_node_names',   'check', tr('Имя узла в каждой строке'), True,  ''),
                    ('log_to_file',      'check', tr('Писать лог в файл'),         False, ''),
                    ('log_file_path',    'line',  tr('Путь к файлу лога:'), '{project_dir}/run.log', ''),
                    ('log_max_size_mb',  'spin',  tr('Макс. размер лога (МБ):'),   (0, 10000, 50),
                     tr('0 = без ограничений. При превышении — ротация')),
                    # ════════════════════════════════════════════════════════
                    # УВЕДОМЛЕНИЯ
                    # ════════════════════════════════════════════════════════
                    ('_sep_notify', 'label', '── 🔔 Уведомления ───────────────────────────', '', ''),
                    ('show_progress',     'check', tr('Показывать прогресс-бар'),       True,  ''),
                    ('notify_on_finish',  'check', tr('Уведомление по завершении'),      False, ''),
                    ('notify_on_error',   'check', tr('Уведомление при ошибке'),         True,  ''),
                    ('notify_on_start',   'check', tr('Уведомление при старте'),         False, ''),
                    ('notify_telegram',   'check', tr('Отправлять уведомления в Telegram'), False, ''),
                    ('telegram_bot_token','line',  tr('Telegram Bot Token:'), '', ''),
                    ('telegram_chat_id',  'line',  tr('Telegram Chat ID:'),   '', ''),
                    ('notify_sound',      'check', tr('Звуковой сигнал по завершении'), False, ''),
                    # ════════════════════════════════════════════════════════
                    # БЕЗОПАСНОСТЬ / АНТИДЕТЕКТ
                    # ════════════════════════════════════════════════════════
                    ('_sep_antidetect', 'label', '── 🥷 Антидетект ────────────────────────', '', ''),
                    ('antidetect_enabled',    'check', tr('Включить антидетект'), False,
                     tr('Маскирует следы автоматизации (navigator.webdriver, plugins и т.д.)')),
                    ('antidetect_canvas',     'check', tr('Рандомизировать Canvas fingerprint'), False, ''),
                    ('antidetect_webgl',      'check', tr('Рандомизировать WebGL fingerprint'),  False, ''),
                    ('antidetect_audio',      'check', tr('Рандомизировать Audio fingerprint'),  False, ''),
                    ('antidetect_fonts',      'check', tr('Рандомизировать список шрифтов'),     False, ''),
                    ('antidetect_screen',     'check', tr('Случайное разрешение экрана'),        False, ''),
                    ('browser_disable_automation_flags', 'check',
                     tr('Отключить флаги автоматизации Chrome'), False,
                     tr('--disable-blink-features=AutomationControlled')),
                ],
            },
            AgentType.BROWSER_CLICK_IMAGE: {
                'title': tr("🖼 Browser Click Image — клик по картинке"),
                'help': tr(
                    "Ищет изображение-шаблон на странице браузера и выполняет действие по нему. "
                    "Нажмите 📷 чтобы сделать скриншот браузера и выделить нужную область."
                ),
                'fields': [
                    ('instance_id', 'line', tr('ID инстанса:'), '',
                     tr('Пусто = первый активный. Или {browser_instance_id}')),
                    ('action_type', 'combo', tr('Действие:'), [
                        (tr('🖱 Левый клик'),            'click'),
                        (tr('🖱🖱 Двойной клик'),         'double_click'),
                        (tr('🖱➡ Правый клик'),           'right_click'),
                        (tr('🖱➡ Навести (hover)'),       'hover'),
                        (tr('✅ Только проверить наличие'), 'check_exists'),
                        (tr('⏳ Ждать появления'),         'wait_appear'),
                        (tr('❌ Ждать исчезновения'),      'wait_disappear'),
                        (tr('📸 Сделать скриншот области'), 'screenshot_region'),
                    ], 'click'),
                    ('threshold', 'spin', tr('Точность совпадения %:'), (50, 100, 80),
                     tr('50 = нечёткое, 80 = хорошо, 95 = точное совпадение')),
                    ('search_region', 'combo', tr('Область поиска:'), [
                        (tr('Вся страница'),           'full'),
                        (tr('Верхняя половина'),       'top_half'),
                        (tr('Нижняя половина'),        'bottom_half'),
                        (tr('Левая половина'),         'left_half'),
                        (tr('Правая половина'),        'right_half'),
                        (tr('Центральная область'),    'center'),
                    ], 'full'),
                    ('click_offset_x', 'spin', tr('Смещение X от центра (px):'), (-500, 500, 0), ''),
                    ('click_offset_y', 'spin', tr('Смещение Y от центра (px):'), (-500, 500, 0), ''),
                    ('wait_timeout', 'spin', tr('Ожидать (сек):'), (0, 300, 10),
                     tr('0 = без ожидания. Используется для wait_appear/wait_disappear/check_exists')),
                    ('retry_interval', 'spin', tr('Интервал повторов (мс):'), (100, 5000, 500), ''),
                    ('if_not_found', 'combo', tr('Если не найдено:'), [
                        (tr('⛔ Ошибка'),             'error'),
                        (tr('🔁 Продолжить'),         'continue'),
                        (tr('↪️ Перейти к BAD END'), 'bad_end'),
                    ], 'error'),
                    ('variable_out', 'line', tr('Результат (x,y) →:'), '',
                     tr('Переменная для координат найденного шаблона')),
                    ('found_var', 'line', tr('Найдено (true/false) →:'), '',
                     tr('Переменная-флаг: "true" если найдено, "false" если нет')),
                    ('screenshot_var', 'line', tr('Скриншот области →:'), '',
                     tr('Переменная base64 PNG — только для действия «Скриншот области»')),
                    ('check_browser_active', 'check', tr('Проверить что браузер активен'), True,
                     tr('Перед действием убедиться что браузер запущен и отвечает')),
                    ('template_image', '_image_selector', tr('Шаблон картинки:'), '',
                     tr('Нажмите 📷 для скриншота браузера → выделите нужную область')),
                ],
            },
            AgentType.PROJECT_INFO: {
                'title': tr("🔎 Project Info — информация о проекте"),
                'help': tr(
                    "Получает системную информацию проекта: ID открытых браузеров, "
                    "имена списков, таблиц, переменных. Записывает данные в указанные переменные."
                ),
                'fields': [
                    ('info_type', 'combo', tr('Что получить:'), [
                        (tr('🌐 ID открытых браузеров'),      'browser_ids'),
                        (tr('📃 Имена списков проекта'),      'list_names'),
                        (tr('📊 Имена таблиц проекта'),       'table_names'),
                        (tr('📝 Имена переменных проекта'),   'var_names'),
                        (tr('🔧 Имена скиллов проекта'),      'skill_names'),
                        (tr('📋 Все узлы графа (сниппеты)'), 'node_names'),
                        (tr('🗂 Всё сразу (JSON)'),           'all'),
                    ], 'browser_ids'),
                    ('result_var', 'line', tr('Результат →:'), '{project_info}',
                     tr('Переменная для результата. Для browser_ids → "id1,id2"; для all → JSON')),
                    ('result_list_var', 'line', tr('Список результатов →:'), '',
                     tr('Переменная-список (Python list). Удобно для цикла Loop')),
                    ('active_browser_var', 'line', tr('ID активного браузера →:'), '',
                     tr('Переменная для ID первого/единственного активного браузера')),
                    ('browser_count_var', 'line', tr('Кол-во браузеров →:'), '',
                     tr('Переменная для числа открытых браузеров')),
                    ('include_inactive', 'check', tr('Включать неактивные инстансы'), False, ''),
                    ('format', 'combo', tr('Формат вывода:'), [
                        (tr('Через запятую'),    'csv'),
                        (tr('Построчно'),        'lines'),
                        (tr('JSON-массив'),      'json'),
                    ], 'csv'),
                ],
            },
            AgentType.PROGRAM_OPEN: {
                'title': tr("🖥 PROGRAM OPEN — открыть программу"),
                'help': tr("Запускает внешнюю программу, управляет окном. Аналог Browser Launch для программ."),
                'fields': [
                    ('executable', 'file_browse', tr('🖥 Путь к программе:'), '',
                     tr('Executable Files (*.exe);;All Files (*)')),
                    ('arguments', 'line', tr('Аргументы:'), '',
                     tr('Аргументы командной строки. {переменные}')),
                    ('working_dir', 'dir_browse', tr('Рабочая папка:'), '',
                     tr('Рабочая директория программы')),
                    ('wait_ready', 'spin', tr('Ожидание готовности (сек):'), (0, 120, 3),
                     tr('Подождать N секунд пока окно появится')),
                    ('window_title', 'line', tr('Заголовок окна (поиск):'), '',
                     tr('Часть заголовка для поиска окна. Пусто = автопоиск')),
                    ('hide_to_tray', 'check', tr('Свернуть в трей'), False,
                     tr('Минимизировать окно после запуска')),
                    ('topmost', 'check', tr('Поверх всех окон'), False, None),
                    ('resize_window', 'line', tr('Размер окна (WxH):'), '',
                     tr('Пример: 1024x768. Пусто = не менять')),
                    ('instance_var', 'line', tr('Переменная PID:'), '{program_pid}',
                     tr('Сохранить PID процесса в переменную')),
                    ('hwnd_var', 'line', tr('Переменная HWND:'), '{program_hwnd}',
                     tr('Сохранить handle окна в переменную')),
                    ('on_error', 'combo', tr('При ошибке:'), [
                        (tr('Остановить'), 'stop'),
                        (tr('Продолжить'), 'continue'),
                    ], 'stop'),
                ]
            },
            AgentType.PROGRAM_ACTION: {
                'title': tr("🎯 PROGRAM ACTION — действие в программе"),
                'help': tr("Клик, ввод текста, скролл, хоткеи в окне программы."),
                'fields': [
                    ('instance_var', 'line', tr('Переменная PID / HWND:'), '{program_pid}',
                     tr('PID или HWND программы из PROGRAM_OPEN')),
                    ('action', 'combo', tr('Действие:'), [
                        (tr('🖱 Клик (левый)'), 'click'),
                        (tr('🖱🖱 Двойной клик'), 'double_click'),
                        (tr('🖱 Правый клик'), 'right_click'),
                        (tr('⌨️ Ввод текста'), 'type_text'),
                        (tr('⌨️ Нажатие клавиш'), 'hotkey'),
                        (tr('🖱 Скролл'), 'scroll'),
                        (tr('🖱 Перетаскивание (drag)'), 'drag'),
                        (tr('📋 Фокус на окно'), 'focus'),
                        (tr('➖ Минимизировать'), 'minimize'),
                        (tr('➕ Развернуть'), 'maximize'),
                        (tr('❌ Закрыть'), 'close'),
                    ], 'click'),
                    ('coord_x', 'spin', tr('X координата:'), (0, 10000, 0),
                     tr('Координата X внутри окна программы')),
                    ('coord_y', 'spin', tr('Y координата:'), (0, 10000, 0),
                     tr('Координата Y внутри окна программы')),
                    ('value', 'line', tr('Текст / клавиши:'), '',
                     tr('Текст для ввода или комбинация (ctrl+c). {переменные}')),
                    ('drag_to_x', 'spin', tr('Перетащить в X:'), (0, 10000, 0), None),
                    ('drag_to_y', 'spin', tr('Перетащить в Y:'), (0, 10000, 0), None),
                    ('timeout', 'spin', tr('Таймаут (сек):'), (1, 300, 10), None),
                    ('wait_after', 'spin', tr('Пауза после (мс):'), (0, 10000, 200),
                     tr('Ожидание после действия')),
                    ('variable_out', 'line', tr('Переменная результата:'), '',
                     tr('Сохранить результат (текст/статус). {переменная}')),
                    ('on_error', 'combo', tr('При ошибке:'), [
                        (tr('Остановить'), 'stop'),
                        (tr('Продолжить'), 'continue'),
                    ], 'stop'),
                ]
            },
            AgentType.PROGRAM_CLICK_IMAGE: {
                'title': tr("🖼 PROGRAM CLICK IMAGE — клик по картинке"),
                'help': tr(
                    "Ищет изображение-шаблон на скриншоте окна программы и выполняет действие. "
                    "Нажмите 📷 чтобы сделать скриншот программы и выделить нужную область."
                ),
                'fields': [
                    ('instance_var', 'line', tr('Переменная PID / HWND:'), '{program_pid}',
                     tr('PID или HWND программы из PROGRAM_OPEN')),
                    ('action_type', 'combo', tr('Действие:'), [
                        (tr('🖱 Клик (левый)'), 'click'),
                        (tr('🖱🖱 Двойной клик'), 'double_click'),
                        (tr('🖱 Правый клик'), 'right_click'),
                        (tr('🖱 Навести курсор'), 'hover'),
                    ], 'click'),
                    ('threshold', 'spin', tr('Точность совпадения %:'), (50, 100, 80),
                     tr('50 = нечёткое, 80 = хорошо, 95 = точное')),
                    ('search_region', 'line', tr('Область поиска (x,y,w,h):'), '',
                     tr('Пусто = всё окно. Формат: 100,200,500,300')),
                    ('click_offset_x', 'spin', tr('Смещение X от центра:'), (-500, 500, 0), None),
                    ('click_offset_y', 'spin', tr('Смещение Y от центра:'), (-500, 500, 0), None),
                    ('wait_timeout', 'spin', tr('Таймаут ожидания (сек):'), (0, 120, 10),
                     tr('0 = без ожидания')),
                    ('retry_interval', 'spin', tr('Интервал повтора (мс):'), (100, 10000, 500), None),
                    ('if_not_found', 'combo', tr('Если не найдено:'), [
                        (tr('Ошибка'), 'error'),
                        (tr('Пропустить'), 'skip'),
                        (tr('Ждать бесконечно'), 'wait'),
                    ], 'error'),
                    ('variable_out', 'line', tr('Координаты (x,y) в переменную:'), '',
                     tr('Сохранить x,y найденной точки. {переменная}')),
                    ('found_var', 'line', tr('Найдено (true/false) →:'), '',
                     tr('true/false — найден ли шаблон. {переменная}')),
                    ('template_image', '_prog_image_selector', tr('Шаблон картинки:'), '',
                     tr('Нажмите 📷 для скриншота программы → выделите нужную область')),
                ]
            },
            AgentType.PROGRAM_AGENT: {
                'title': tr("🖥🧠 PROGRAM AGENT — AI-управление программой"),
                'help': tr(
                    "AI-агент делает скриншот окна программы, анализирует его и выполняет "
                    "действия (клики, ввод текста). Работает аналогично Browser Agent, "
                    "но для любых настольных приложений."
                ),
                'fields': [
                    ('instance_var', 'line', tr('Переменная PID / HWND:'), '{program_pid}',
                     tr('PID или HWND из сниппета Program Open')),
                    ('task', 'text', tr('Задача для AI:'), '',
                     tr('Опишите что должен сделать AI в программе. {переменные}')),
                    ('max_actions', 'spin', tr('Макс. действий за шаг:'), (1, 50, 10),
                     tr('Максимум действий в одном цикле AI')),
                    ('ai_timeout_sec', 'spin', tr('Таймаут AI (сек):'), (10, 600, 120),
                     tr('Максимальное время ожидания ответа от AI')),
                    ('screenshot_verify', 'check', tr('Верификация скриншотами'), False,
                     tr('Сравнивать скриншоты до/после каждого действия')),
                    ('action_wait_ms', 'spin', tr('Пауза между действиями (мс):'), (0, 5000, 500),
                     tr('Задержка после каждого действия')),
                    ('variable_out', 'line', tr('Результат (переменная) →:'), '',
                     tr('{переменная} для сохранения итога работы AI')),
                    ('on_error', 'combo', tr('При ошибке:'), [
                        (tr('Остановить'), 'stop'),
                        (tr('Продолжить'), 'continue'),
                    ], 'stop'),
                ],
            },
            AgentType.PROGRAM_SCREENSHOT: {
                'title': tr("📸 PROGRAM SCREENSHOT — скриншот окна программы"),
                'help': tr("Делает скриншот окна или области окна программы."),
                'fields': [
                    ('instance_var', 'line', tr('Переменная PID / HWND:'), '{program_pid}', None),
                    ('screenshot_region', 'combo', tr('Область:'), [
                        (tr('Всё окно'), 'full'),
                        (tr('Клиентская часть'), 'client'),
                        (tr('Указанная область'), 'region'),
                    ], 'full'),
                    ('region_rect', 'line', tr('Область (x,y,w,h):'), '',
                     tr('Для режима «Указанная область»')),
                    ('save_mode', 'combo', tr('Сохранить как:'), [
                        (tr('В переменную (base64)'), 'variable'),
                        (tr('В файл'), 'file'),
                        (tr('И в файл, и в переменную'), 'both'),
                    ], 'variable'),
                    ('variable_out', 'line', tr('Переменная:'), '{screenshot}',
                     tr('Переменная для base64 или пути к файлу')),
                    ('save_path', 'line', tr('Путь к файлу:'), '',
                     tr('Путь для сохранения. {переменные}, {timestamp}')),
                    ('image_format', 'combo', tr('Формат:'), [
                        ('PNG', 'png'), ('JPEG', 'jpg'), ('BMP', 'bmp'),
                    ], 'png'),
                ]
            },
            AgentType.BROWSER_SCREENSHOT: {
                'title': tr("📸 Browser Screenshot — скриншот страницы"),
                'help': tr(
                    "Делает скриншот текущей страницы браузера. "
                    "Сохраняет в переменную (base64), файл или оба варианта."
                ),
                'fields': [
                    ('instance_id', 'line', tr('ID инстанса:'), '',
                     tr('Пусто = первый активный. Или {browser_instance_id}')),
                    ('screenshot_region', 'combo', tr('Область:'), [
                        (tr('Вся страница (fullpage)'), 'fullpage'),
                        (tr('Только видимая область'), 'viewport'),
                        (tr('Элемент (по селектору)'), 'element'),
                    ], 'viewport'),
                    ('element_selector', 'line', tr('Селектор элемента:'), '',
                     tr('CSS или XPath — только для режима «Элемент»')),
                    ('save_mode', 'combo', tr('Сохранить:'), [
                        (tr('📋 Только в переменную (base64)'), 'var_only'),
                        (tr('💾 Только в файл'),                'file_only'),
                        (tr('📋+💾 Переменную и файл'),          'both'),
                    ], 'var_only'),
                    ('variable_out', 'line', tr('Переменная (base64) →:'), '{screenshot_b64}',
                     tr('Имя переменной для base64-строки PNG')),
                    ('save_path', 'dir_browse', tr('Папка сохранения:'), '',
                     tr('Папка для файла (пусто = рабочая папка проекта)')),
                    ('file_name', 'line', tr('Имя файла:'), 'screenshot_{timestamp}.png',
                     tr('Поддерживает {timestamp}, {переменные}. Расширение .png добавится автоматически')),
                    ('image_format', 'combo', tr('Формат файла:'), [
                        ('PNG', 'png'), ('JPEG', 'jpg'), ('WebP', 'webp'),
                    ], 'png'),
                    ('jpeg_quality', 'spin', tr('Качество JPEG (1-100):'), (1, 100, 85), ''),
                    ('open_after_save', 'check', tr('Открыть файл после сохранения'), False, ''),
                    ('wait_before', 'spin', tr('Пауза перед скриншотом (мс):'), (0, 10000, 0), ''),
                ],
            },
        }
        
        schema = SNIPPET_SCHEMA.get(agent_type, {
            'title': f"⚙️ {agent_type.value}",
            'help': tr("Настройки сниппета"),
            'fields': []
        })
        
        self._snippet_group.setTitle(schema['title'])
        
        # Help label
        if schema.get('help'):
            help_lbl = QLabel(schema['help'])
            help_lbl.setWordWrap(True)
            help_lbl.setStyleSheet("color: #7AA2F7; font-size: 11px; padding: 4px;")
            form.addRow(help_lbl)
        
        # Создаём поля по схеме
        for field_spec in schema['fields']:
            key, ftype, label, *rest = field_spec
            default = rest[0] if rest else None
            tooltip = rest[1] if len(rest) > 1 else None
            
            if ftype == 'combo':
                widget = QComboBox()
                for opt_label, opt_data in default:
                    widget.addItem(opt_label, opt_data)
                widget.currentIndexChanged.connect(self._on_snippet_widget_changed)
                if key == 'action' and agent_type in (AgentType.BROWSER_ACTION, AgentType.PROGRAM_ACTION):
                    widget.currentIndexChanged.connect(
                        lambda _, _at=agent_type: self._update_snippet_field_visibility(_at)
                    )
                # Primary combo → пересчёт видимости полей
                if key in ('operation', 'file_action', 'dir_action', 'text_action',
                           'jx_action', 'var_action', 'random_type', 'data_type',
                           'js_mode', 'notif_level', 'run_mode', 'captcha_service',
                           'browser_throttle', 'profile_op', 'variables_mode',
                           'action_type', 'screenshot_region', 'save_mode',
                           'image_format', 'info_type', 'search_region',
                           'action', 'loop_type', 'method', 'get_mode',
                           'proj_row_get_mode', 'load_content'):
                    widget.currentIndexChanged.connect(
                        lambda _, _at=agent_type: self._update_snippet_field_visibility(_at)
                    )
            

            elif ftype == 'combo':
                widget = QComboBox()
                for opt_label, opt_data in default:
                    widget.addItem(opt_label, opt_data)
                widget.currentIndexChanged.connect(self._on_snippet_widget_changed)
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    widget,
                    lambda w=widget: w.currentData(),
                    lambda v, w=widget: (
                        w.setCurrentIndex(w.findData(v)) if v is not None else w.setCurrentIndex(0)
                    ),
                    f"Изменение {label}"
                )
                if key == 'code_source':
                    widget.currentIndexChanged.connect(self._update_code_source_visibility)
                if key == 'condition_mode':
                    widget.currentIndexChanged.connect(self._update_if_condition_visibility)
                # Primary combo → пересчёт видимости полей
                if key in ('operation', 'file_action', 'dir_action', 'text_action',
                           'jx_action', 'var_action', 'random_type', 'data_type',
                           'js_mode', 'notif_level'):
                    widget.currentIndexChanged.connect(
                        lambda _, _at=agent_type: self._update_snippet_field_visibility(_at)
                    )
            
            elif ftype == 'spin':
                min_v, max_v, val = default
                widget = QSpinBox()
                widget.setRange(min_v, max_v)
                widget.setValue(val)
                widget.valueChanged.connect(self._on_snippet_widget_changed)
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    widget,
                    lambda w=widget: w.value(),
                    lambda v, w=widget: w.setValue(v),
                    f"Изменение {label}"
                )
                
            elif ftype == 'check':
                widget = QCheckBox(label)
                widget.setChecked(bool(default))
                widget.stateChanged.connect(self._on_snippet_widget_changed)
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    widget,
                    lambda w=widget: w.isChecked(),
                    lambda v, w=widget: w.setChecked(v),
                    f"Изменение {label}"
                )
                form.addRow(widget)
                self._snippet_widgets[key] = widget
                self._snippet_field_labels[key] = widget
                widget.installEventFilter(self)
                if tooltip:
                    widget.setToolTip(tooltip)
                continue
                
            elif ftype == 'line':
                widget = QLineEdit(str(default) if default else '')
                widget.textChanged.connect(self._on_snippet_widget_changed)
                self._install_var_context_menu(widget)
                if tooltip:
                    widget.setToolTip(tooltip)
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    widget,
                    lambda w=widget: w.text(),
                    lambda v, w=widget: w.setText(v),
                    f"Изменение {label}"
                )
                # ── Кнопка выбора проектного списка / таблицы ──────────────
                if key in ('project_list_name', 'project_table_name'):
                    _pick_container = QWidget()
                    _pick_row = QHBoxLayout(_pick_container)
                    _pick_row.setContentsMargins(0, 0, 0, 0)
                    _pick_row.setSpacing(4)
                    _pick_row.addWidget(widget)
                    _pick_icon = "📃" if key == 'project_list_name' else "📊"
                    _pick_btn = QPushButton(_pick_icon)
                    _pick_btn.setFixedWidth(28)
                    _pick_btn.setToolTip("Выбрать из списков проекта" if key == 'project_list_name'
                                         else "Выбрать из таблиц проекта")
                    _pick_btn.setStyleSheet(
                        "QPushButton { background: #1a2a3a; border: 1px solid #7AA2F7; "
                        "border-radius: 3px; } QPushButton:hover { background: #7AA2F7; color: #000; }"
                    )
                    def _make_picker(_field=widget, _k=key, _self=self):
                        def _pick():
                            vp = _self
                            while vp and not hasattr(vp, '_vars_panel'):
                                try:
                                    vp = vp.parent()
                                except Exception:
                                    vp = None
                            panel = getattr(vp, '_vars_panel', None)
                            if not panel:
                                from PyQt6.QtWidgets import QMessageBox
                                QMessageBox.information(None, "Ошибка", "Панель переменных не найдена.")
                                return
                            if _k == 'project_list_name':
                                names = [l['name'] for l in getattr(panel, '_project_lists', [])]
                                title, prompt = "Выбор списка", "Выберите проектный список:"
                            else:
                                names = [t['name'] for t in getattr(panel, '_project_tables', [])]
                                title, prompt = "Выбор таблицы", "Выберите проектную таблицу:"
                            if not names:
                                from PyQt6.QtWidgets import QMessageBox
                                QMessageBox.information(
                                    None, title,
                                    "В проекте нет элементов. Добавьте их на вкладке 'Списки / Таблицы'."
                                )
                                return
                            from PyQt6.QtWidgets import QInputDialog
                            name, ok = QInputDialog.getItem(_self, title, prompt, names, 0, False)
                            if ok and name:
                                # Временно снимаем флаг загрузки чтобы flush сработал
                                _was_loading = getattr(_self, '_snippet_loading', False)
                                _self._snippet_loading = False
                                _field.setText(name)
                                if hasattr(_self, '_flush_snippet_config_to_node'):
                                    _self._flush_snippet_config_to_node()
                                _self._snippet_loading = _was_loading
                                if hasattr(_self, '_mark_modified_from_props'):
                                    _self._mark_modified_from_props()
                        return _pick
                    _pick_btn.clicked.connect(_make_picker())
                    _pick_row.addWidget(_pick_btn)
                    _lbl = QLabel(label)
                    form.addRow(_lbl, _pick_container)
                    self._snippet_widgets[key] = widget
                    self._snippet_field_labels[key] = _lbl
                    continue
                
            elif ftype == 'text':
                widget = QTextEdit()
                widget.setPlainText(str(default) if default else '')
                widget.setMaximumHeight(80)
                widget.textChanged.connect(self._on_snippet_widget_changed)
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    widget,
                    lambda w=widget: w.toPlainText(),
                    lambda v, w=widget: w.setPlainText(v),
                    f"Изменение {label}"
                )
                # Автовысота Switch: при изменении количества строк cases
                if key == 'cases' and agent_type == AgentType.SWITCH:
                    def _make_switch_height_updater(_w=widget):
                        def _upd():
                            node = getattr(self, '_node', None)
                            if node is None or node.agent_type != AgentType.SWITCH:
                                return
                            lines = [l.strip() for l in _w.toPlainText().splitlines() if l.strip()]
                            new_h = 120 + (max(len(lines), 1) + 1) * 32
                            if int(node.height) != new_h:
                                node.height = new_h
                                scene = getattr(self, '_scene', None)
                                if scene:
                                    item = scene.get_node_item(node.id)
                                    if item:
                                        item.setRect(0, 0, node.width, node.height)
                                        item.update()
                                        if hasattr(scene, 'update_edges'):
                                            scene.update_edges()
                        return _upd
                    widget.textChanged.connect(_make_switch_height_updater())
            
            elif ftype == 'code_editor':
                # Полноценный редактор кода с подсветкой-стилем
                code_group = QWidget()
                code_vlayout = QVBoxLayout(code_group)
                code_vlayout.setContentsMargins(0, 0, 0, 0)
                code_vlayout.setSpacing(2)
                
                code_label = QLabel(label)
                code_label.setStyleSheet("color: #7AA2F7; font-size: 11px; font-weight: bold;")
                code_vlayout.addWidget(code_label)
                
                code_edit = QPlainTextEdit()
                code_edit.setPlaceholderText(tooltip or "Введите код...")
                code_edit.setMinimumHeight(180)
                code_edit.setMaximumHeight(400)
                code_edit.setStyleSheet(f"""
                    QPlainTextEdit {{
                        background: {get_color('bg0')};
                        color: #C0CAF5;
                        border: 1px solid {get_color('bd')};
                        border-radius: 4px;
                        font-family: 'Consolas', 'Courier New', 'JetBrains Mono', monospace;
                        font-size: 12px;
                        padding: 8px;
                    }}
                """)
                code_edit.setTabStopDistance(32)
                code_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                code_edit.textChanged.connect(self._on_code_editor_changed)
                self._install_var_context_menu(code_edit)
                self._install_var_context_menu(code_edit)
                code_vlayout.addWidget(code_edit)
                
                form.addRow(code_group)
                self._snippet_widgets[key] = code_edit
                self._snippet_code_editor = code_edit  # Отдельная ссылка для быстрого доступа
                # Подключаем трекер для undo/redo
                self._snippet_tracker.track_widget(
                    code_edit,
                    lambda w=code_edit: w.toPlainText(),
                    lambda v, w=code_edit: w.setPlainText(v),
                    f"Изменение кода"
                )
                if tooltip:
                    code_edit.setToolTip(tooltip)
                continue
                
            elif ftype == 'label':
                widget = QLabel(str(default) if default else '')
                widget.setStyleSheet("color: #565f89; font-size: 10px;")
                widget.setWordWrap(True)
                form.addRow(widget)
                continue  # Не добавляем в _snippet_widgets
            
            elif ftype == 'file_browse':
                # Поле с кнопкой выбора файла
                container = QWidget()
                row_layout = QHBoxLayout(container)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(4)
                line_edit = QLineEdit(str(default) if default else '')
                line_edit.setPlaceholderText("Путь к файлу... ({project_dir} = рабочая папка)")
                self._install_var_context_menu(line_edit)
                line_edit.textChanged.connect(self._on_snippet_widget_changed)
                browse_btn = QPushButton("📂")
                browse_btn.setFixedWidth(32)
                browse_btn.setToolTip(tr("Выбрать файл"))
                file_filter = tooltip or "All Files (*)"  # tooltip используется как фильтр
                # Замыкание для корректного захвата line_edit и filter
                def _make_file_handler(le, ff):
                    def handler():
                        start_dir = self._project_root or ""
                        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл скрипта", start_dir, ff)
                        if path:
                            # Делаем путь относительным от project_root если возможно
                            if self._project_root and path.startswith(self._project_root):
                                path = os.path.relpath(path, self._project_root)
                            le.setText(path)
                    return handler
                browse_btn.clicked.connect(_make_file_handler(line_edit, file_filter))
                row_layout.addWidget(line_edit)
                row_layout.addWidget(browse_btn)
                _lbl = QLabel(label)
                form.addRow(_lbl, container)
                self._snippet_widgets[key] = line_edit
                self._snippet_field_labels[key] = _lbl
                continue
            
            elif ftype == 'dir_browse':
                # Поле с кнопкой выбора папки
                container = QWidget()
                row_layout = QHBoxLayout(container)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(4)
                line_edit = QLineEdit(str(default) if default else '')
                line_edit.setPlaceholderText("Путь к папке... ({project_dir} = рабочая папка)")
                self._install_var_context_menu(line_edit)
                line_edit.textChanged.connect(self._on_snippet_widget_changed)
                browse_btn = QPushButton("📂")
                browse_btn.setFixedWidth(32)
                browse_btn.setToolTip(tr("Выбрать папку"))
                def _make_dir_handler(le):
                    def handler():
                        start_dir = le.text() or self._project_root or ""
                        path = QFileDialog.getExistingDirectory(self, "Выбрать папку", start_dir)
                        if path:
                            if self._project_root and path.startswith(self._project_root):
                                path = os.path.relpath(path, self._project_root)
                            le.setText(path)
                    return handler
                browse_btn.clicked.connect(_make_dir_handler(line_edit))
                row_layout.addWidget(line_edit)
                row_layout.addWidget(browse_btn)
                _lbl = QLabel(label)
                form.addRow(_lbl, container)
                self._snippet_widgets[key] = line_edit
                self._snippet_field_labels[key] = _lbl
                if tooltip:
                    line_edit.setToolTip(tooltip)
                continue
            
            elif ftype == '_image_selector':
                # ─── Виджет выбора шаблона картинки для Browser Click Image ───
                container = QWidget()
                col_layout = QVBoxLayout(container)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(4)

                # Превью выбранного шаблона
                preview_lbl = QLabel()
                preview_lbl.setFixedSize(220, 110)
                preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview_lbl.setStyleSheet(
                    "border: 1px dashed #7AA2F7; border-radius: 4px; "
                    "background: #0d0f18; color: #565f89; font-size: 11px;"
                )
                preview_lbl.setText("Нет шаблона")
                preview_lbl.setToolTip("Выбранный шаблон изображения")

                # Скрытое поле для хранения base64
                hidden_b64 = QLineEdit()
                hidden_b64.setVisible(False)
                hidden_b64.textChanged.connect(self._on_snippet_widget_changed)

                def _refresh_preview(b64: str, lbl=preview_lbl):
                    if not b64:
                        lbl.setText("Нет шаблона")
                        lbl.setPixmap(QPixmap())
                        return
                    try:
                        data = base64.b64decode(b64)
                        pm = QPixmap()
                        pm.loadFromData(data)
                        if not pm.isNull():
                            lbl.setPixmap(pm.scaled(
                                220, 110,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            ))
                        else:
                            lbl.setText("❌ Не удалось загрузить")
                    except Exception:
                        lbl.setText("❌ Ошибка base64")

                hidden_b64.textChanged.connect(_refresh_preview)

                # Кнопки
                btn_row = QHBoxLayout()
                btn_row.setSpacing(4)

                btn_screenshot = QPushButton(tr("📷 Скриншот браузера"))
                btn_screenshot.setToolTip(
                    "Сделать скриншот текущего браузера и выделить область для клика"
                )
                btn_screenshot.setStyleSheet(
                    "QPushButton { background: #1a2a3a; color: #7AA2F7; "
                    "border: 1px solid #7AA2F7; border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
                    "QPushButton:hover { background: #7AA2F7; color: #000; }"
                )

                btn_load_file = QPushButton(tr("📂 Из файла"))
                btn_load_file.setToolTip(tr("Загрузить шаблон из PNG/JPG файла"))
                btn_load_file.setStyleSheet(
                    "QPushButton { background: #1a1a2a; color: #9d7cd8; "
                    "border: 1px solid #9d7cd8; border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
                    "QPushButton:hover { background: #9d7cd8; color: #000; }"
                )

                btn_clear = QPushButton("🗑")
                btn_clear.setFixedWidth(28)
                btn_clear.setToolTip("Очистить шаблон")

                def _open_screenshot_editor(b64_field=hidden_b64):
                    """Делаем скриншот браузера и открываем редактор выделения области."""
                    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRubberBand
                    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
                    from PyQt6.QtCore import QRect, QSize, QPoint
                    import base64, io

                    # ═══ ИСПРАВЛЕНИЕ: корректный скриншот через Selenium ═══
                    raw_b64 = None
                    try:
                        from constructor.browser_module import BrowserManager
                        mgr = self._browser_manager if hasattr(self, '_browser_manager') else BrowserManager.get()
                        
                        # Собираем инстансы: project browser manager + глобальный
                        all_inst = {}
                        _tab = self._current_project_tab() if hasattr(self, '_current_project_tab') else None
                        _pbm = getattr(_tab, 'browser_manager', None) if _tab else None
                        if _pbm:
                            all_inst.update(_pbm.all_instances())
                        if mgr:
                            all_inst.update(mgr.all_instances())
                        
                        # Ищем по instance_id из конфига сниппета
                        inst = None
                        _cfg_iid = ''
                        if hasattr(self, '_snippet_widgets'):
                            _iid_w = self._snippet_widgets.get('instance_id')
                            if _iid_w and hasattr(_iid_w, 'text'):
                                _cfg_iid = _iid_w.text().strip().strip('{}')
                        if _cfg_iid and _cfg_iid in all_inst:
                            inst = all_inst[_cfg_iid]
                        if not inst:
                            inst = next((i for i in all_inst.values() if i.is_running), None)
                        
                        if inst:
                            raw_b64 = inst.get_screenshot_base64()
                    except Exception:
                        import traceback; traceback.print_exc()

                    if not raw_b64:
                        QMessageBox.warning(self, "Ошибка",
                            "Не удалось сделать скриншот.\n"
                            "Убедитесь что браузер запущен (BROWSER_LAUNCH).")
                        return

                    # Открываем диалог выделения области
                    dlg = _ImageRegionSelector(raw_b64, self)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        region_b64 = dlg.get_region_b64()
                        if region_b64:
                            b64_field.setText(region_b64)

                def _load_from_file(b64_field=hidden_b64):
                    path, _ = QFileDialog.getOpenFileName(
                        self, "Выбрать шаблон", "",
                        "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
                    )
                    if path:
                        try:
                            with open(path, 'rb') as f:
                                data = f.read()
                            b64_field.setText(base64.b64encode(data).decode())
                        except Exception as e:
                            QMessageBox.warning(self, "Ошибка", str(e))

                def _clear_template(b64_field=hidden_b64):
                    b64_field.clear()

                btn_screenshot.clicked.connect(lambda checked=False: _open_screenshot_editor())
                btn_load_file.clicked.connect(lambda checked=False: _load_from_file())
                btn_clear.clicked.connect(lambda checked=False: _clear_template())

                btn_row.addWidget(btn_screenshot)
                btn_row.addWidget(btn_load_file)
                btn_row.addWidget(btn_clear)

                col_layout.addWidget(preview_lbl)
                col_layout.addLayout(btn_row)
                col_layout.addWidget(hidden_b64)

                _lbl = QLabel(label)
                form.addRow(_lbl, container)
                self._snippet_widgets[key] = hidden_b64
                self._snippet_field_labels[key] = _lbl
                if tooltip:
                    container.setToolTip(tooltip)
                continue

            elif ftype == '_prog_image_selector':
                # ─── Виджет выбора шаблона для PROGRAM_CLICK_IMAGE ───
                container = QWidget()
                col_layout = QVBoxLayout(container)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(4)

                preview_lbl = QLabel()
                preview_lbl.setFixedSize(220, 110)
                preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview_lbl.setStyleSheet(
                    "border: 1px dashed #FF9E64; border-radius: 4px; "
                    "background: #0d0f18; color: #565f89; font-size: 11px;"
                )
                preview_lbl.setText("Нет шаблона")

                hidden_b64 = QLineEdit()
                hidden_b64.setVisible(False)
                hidden_b64.textChanged.connect(self._on_snippet_widget_changed)

                def _refresh_prog_preview(b64: str, lbl=preview_lbl):
                    if not b64:
                        lbl.setText("Нет шаблона")
                        lbl.setPixmap(QPixmap())
                        return
                    try:
                        data = base64.b64decode(b64)
                        pm = QPixmap()
                        pm.loadFromData(data)
                        if not pm.isNull():
                            lbl.setPixmap(pm.scaled(
                                220, 110,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            ))
                        else:
                            lbl.setText("❌ Не удалось загрузить")
                    except Exception:
                        lbl.setText("❌ Ошибка base64")

                hidden_b64.textChanged.connect(_refresh_prog_preview)

                btn_row_prog = QHBoxLayout()
                btn_row_prog.setSpacing(4)

                btn_prog_screenshot = QPushButton(tr("📷 Скриншот программы"))
                btn_prog_screenshot.setToolTip(
                    "Сделать скриншот окна программы и выделить область для клика"
                )
                btn_prog_screenshot.setStyleSheet(
                    "QPushButton { background: #2a1a0a; color: #FF9E64; "
                    "border: 1px solid #FF9E64; border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
                    "QPushButton:hover { background: #FF9E64; color: #000; }"
                )

                btn_prog_load_file = QPushButton(tr("📂 Из файла"))
                btn_prog_load_file.setToolTip(tr("Загрузить шаблон из PNG/JPG файла"))
                btn_prog_load_file.setStyleSheet(
                    "QPushButton { background: #1a1a2a; color: #9d7cd8; "
                    "border: 1px solid #9d7cd8; border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
                    "QPushButton:hover { background: #9d7cd8; color: #000; }"
                )

                btn_prog_clear = QPushButton("🗑")
                btn_prog_clear.setFixedWidth(28)
                btn_prog_clear.setToolTip("Очистить шаблон")

                def _open_prog_screenshot_editor(b64_field=hidden_b64):
                    """Делаем скриншот окна программы через HWND и открываем редактор выделения."""
                    raw_b64 = None
                    try:
                        # Получаем HWND из instance_var в сниппете
                        hwnd = 0
                        inst_w = self._snippet_widgets.get('instance_var')
                        inst_var_name = ''
                        if inst_w and hasattr(inst_w, 'text'):
                            inst_var_name = inst_w.text().strip().strip('{}')

                        # Ищем в контексте runtime (живого или завершённого)
                        rt = getattr(self, '_runtime_thread', None) or getattr(self, '_runtime', None)
                        ctx = getattr(rt, '_context', {}) if rt else {}
                        # Если runtime уже завершён — берём из сохранённых программ
                        if not ctx.get('_open_programs'):
                            _tab = self._current_project_tab() if hasattr(self, '_current_project_tab') else None
                            _saved = getattr(_tab, '_last_open_programs', None) or getattr(self, '_last_open_programs', {})
                            if _saved:
                                ctx = {'_open_programs': _saved}

                        if inst_var_name and inst_var_name in ctx:
                            pid_or_hwnd = ctx[inst_var_name]
                            open_progs = ctx.get('_open_programs', {})
                            pid_str = str(pid_or_hwnd)
                            if pid_str in open_progs:
                                hwnd = open_progs[pid_str].get('hwnd', 0)
                            else:
                                try:
                                    hwnd = int(pid_or_hwnd)
                                except Exception:
                                    pass

                        if not hwnd:
                            hwnd = ctx.get('_program_hwnd', 0)
                        if not hwnd:
                            # Берём первый из открытых программ
                            for entry in ctx.get('_open_programs', {}).values():
                                hwnd = entry.get('hwnd', 0)
                                if hwnd:
                                    break

                        if not hwnd:
                            QMessageBox.warning(self, "Ошибка",
                                "Не удалось найти окно программы.\n"
                                "Убедитесь что программа запущена (PROGRAM_OPEN)\n"
                                "и в поле 'Переменная PID/HWND' указано правильное имя.")
                            return

                        # Снимок через PrintWindow (работает за пределами экрана)
                        import ctypes, io as _io
                        import win32gui, win32ui
                        left, top, right, bot = win32gui.GetWindowRect(hwnd)
                        w, h = right - left, bot - top
                        if w <= 0 or h <= 0:
                            raise RuntimeError(f"Размер окна 0 (HWND={hwnd})")
                        hwnd_dc = win32gui.GetWindowDC(hwnd)
                        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                        save_dc = mfc_dc.CreateCompatibleDC()
                        bmp = win32ui.CreateBitmap()
                        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
                        save_dc.SelectObject(bmp)
                        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
                        from PIL import Image
                        bmpinfo = bmp.GetInfo()
                        bmpstr = bmp.GetBitmapBits(True)
                        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                                               bmpstr, 'raw', 'BGRX', 0, 1)
                        buf = _io.BytesIO()
                        img.save(buf, format='PNG')
                        win32gui.DeleteObject(bmp.GetHandle())
                        save_dc.DeleteDC(); mfc_dc.DeleteDC()
                        win32gui.ReleaseDC(hwnd, hwnd_dc)
                        import base64 as _b64
                        raw_b64 = _b64.b64encode(buf.getvalue()).decode()

                    except ImportError:
                        QMessageBox.warning(self, "Ошибка",
                            "Требуется pywin32 и Pillow:\npip install pywin32 Pillow")
                        return
                    except Exception as ex:
                        QMessageBox.warning(self, "Ошибка скриншота", str(ex))
                        return

                    dlg = _ImageRegionSelector(raw_b64, self)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        region_b64 = dlg.get_region_b64()
                        if region_b64:
                            b64_field.setText(region_b64)

                def _prog_load_from_file(b64_field=hidden_b64):
                    path, _ = QFileDialog.getOpenFileName(
                        self, "Выбрать шаблон", "",
                        "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
                    )
                    if path:
                        try:
                            with open(path, 'rb') as f:
                                data = f.read()
                            b64_field.setText(base64.b64encode(data).decode())
                        except Exception as e:
                            QMessageBox.warning(self, "Ошибка", str(e))

                btn_prog_screenshot.clicked.connect(lambda checked=False: _open_prog_screenshot_editor())
                btn_prog_load_file.clicked.connect(lambda checked=False: _prog_load_from_file())
                btn_prog_clear.clicked.connect(lambda checked=False: hidden_b64.clear())

                btn_row_prog.addWidget(btn_prog_screenshot)
                btn_row_prog.addWidget(btn_prog_load_file)
                btn_row_prog.addWidget(btn_prog_clear)

                col_layout.addWidget(preview_lbl)
                col_layout.addLayout(btn_row_prog)
                col_layout.addWidget(hidden_b64)

                _lbl = QLabel(label)
                form.addRow(_lbl, container)
                self._snippet_widgets[key] = hidden_b64
                self._snippet_field_labels[key] = _lbl
                if tooltip:
                    container.setToolTip(tooltip)
                continue

            else:
                continue
            
            if tooltip:
                widget.setToolTip(tooltip)
            
            # Контекстное меню вставки переменных для текстовых полей AI
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
                self._install_var_context_menu(widget)
            
            widget.installEventFilter(self)  # <-- ДОБАВИТЬ
            
            _lbl = QLabel(label)
            form.addRow(_lbl, widget)
            self._snippet_widgets[key] = widget
            self._snippet_field_labels[key] = _lbl
        
        self._snippet_layout.addLayout(form)
        # Первичный прогон видимости полей
        self._update_snippet_field_visibility(agent_type)
        # ═══ БЛОК ПЕРЕМЕННЫХ ═══
        self._snippet_layout.addSpacing(20)
        var_group = QGroupBox(tr("📝 Переменные (Variables)"))
        var_layout = QVBoxLayout(var_group)
        
        # Таблица переменных: Имя | Значение | Тип | Описание
        self._vars_table = QTableWidget()
        self._vars_table.setColumnCount(4)
        self._vars_table.setHorizontalHeaderLabels([tr("Имя переменной"), tr("Значение"), tr("Тип"), tr("Описание")])
        self._vars_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._vars_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._vars_table.setColumnWidth(0, 120)
        self._vars_table.setColumnWidth(2, 80)
        self._vars_table.setMaximumHeight(200)
        self._vars_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._vars_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vars_table.customContextMenuRequested.connect(self._vars_table_context_menu)
        self._vars_table.setStyleSheet(f"""
            QTableWidget {{ background: {get_color('bg0')}; color: {get_color('tx0')}; gridline-color: {get_color('bd')}; }}
            QHeaderView::section {{ background: {get_color('bg3')}; color: {get_color('tx1')}; border: 1px solid {get_color('bd')}; padding: 4px; }}
        """)
        var_layout.addWidget(self._vars_table)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        btn_add_var = QPushButton(tr("➕ Добавить"))
        btn_add_var.clicked.connect(self._add_variable_row)
        btn_del_var = QPushButton(tr("🗑 Удалить"))
        btn_del_var.clicked.connect(self._remove_variable_row)
        btn_copy_ref = QPushButton(tr("📋 Копировать {имя}"))
        btn_copy_ref.setToolTip("Скопировать ссылку на переменную вида {имя} в буфер обмена")
        btn_copy_ref.clicked.connect(self._copy_var_reference)
        btn_move_up = QPushButton(tr("▲"))
        btn_move_up.setFixedWidth(28)
        btn_move_up.setToolTip("Переместить строку вверх")
        btn_move_up.clicked.connect(self._move_var_row_up)
        btn_move_down = QPushButton(tr("▼"))
        btn_move_down.setFixedWidth(28)
        btn_move_down.setToolTip("Переместить строку вниз")
        btn_move_down.clicked.connect(self._move_var_row_down)
        btn_layout.addWidget(btn_add_var)
        btn_layout.addWidget(btn_del_var)
        btn_layout.addWidget(btn_copy_ref)
        btn_layout.addWidget(btn_move_up)
        btn_layout.addWidget(btn_move_down)
        btn_layout.addStretch()
        var_layout.addLayout(btn_layout)
        
        # Вторая строка: импорт/экспорт таблицы + прикрепление файла
        io_layout = QHBoxLayout()
        btn_import_csv = QPushButton(tr("📥 Импорт CSV/TSV"))
        btn_import_csv.setToolTip("Загрузить переменные из CSV/TSV файла (столбцы: имя, значение, тип, описание)")
        btn_import_csv.clicked.connect(self._import_vars_from_csv)
        btn_export_csv = QPushButton(tr("📤 Экспорт CSV"))
        btn_export_csv.setToolTip("Сохранить переменные в CSV файл")
        btn_export_csv.clicked.connect(self._export_vars_to_csv)
        io_layout.addWidget(btn_import_csv)
        io_layout.addWidget(btn_export_csv)
        io_layout.addStretch()
        var_layout.addLayout(io_layout)
        
        # Прикрепление файла-таблицы для инжекции
        attach_layout = QHBoxLayout()
        attach_lbl = QLabel(tr("📎 Файл таблицы:"))
        attach_lbl.setStyleSheet("color: #565f89; font-size: 10px;")
        self._fld_attached_table = QLineEdit()
        self._fld_attached_table.setPlaceholderText("Путь к CSV/TSV (переменные загрузятся при запуске)...")
        self._fld_attached_table.textChanged.connect(self._on_snippet_widget_changed)
        btn_attach_table = QPushButton("📂")
        btn_attach_table.setFixedWidth(32)
        btn_attach_table.setToolTip("Выбрать CSV/TSV файл с переменными")
        btn_attach_table.clicked.connect(self._browse_attached_table)
        btn_preview_table = QPushButton("👁")
        btn_preview_table.setFixedWidth(32)
        btn_preview_table.setToolTip("Предпросмотр: загрузить переменные из прикреплённого файла в таблицу")
        btn_preview_table.clicked.connect(self._preview_attached_table)
        attach_layout.addWidget(attach_lbl)
        attach_layout.addWidget(self._fld_attached_table)
        attach_layout.addWidget(btn_attach_table)
        attach_layout.addWidget(btn_preview_table)
        var_layout.addLayout(attach_layout)
        self._snippet_widgets["attached_table_path"] = self._fld_attached_table
        
        # Быстрая вставка из контекста
        ctx_layout = QHBoxLayout()
        ctx_label = QLabel(tr("Из контекста:"))
        ctx_label.setStyleSheet("color: #565f89; font-size: 10px;")
        self._cmb_ctx_vars = QComboBox()
        self._cmb_ctx_vars.setPlaceholderText("— выбрать переменную контекста —")
        self._cmb_ctx_vars.setMinimumWidth(180)
        # Наполняем из текущего контекста runtime (если есть)
        self._refresh_context_vars_combo()
        btn_insert_ctx = QPushButton("⬇ Вставить в таблицу")
        btn_insert_ctx.setToolTip("Добавить выбранную переменную контекста как строку в таблицу")
        btn_insert_ctx.clicked.connect(self._insert_context_var_to_table)
        ctx_layout.addWidget(ctx_label)
        ctx_layout.addWidget(self._cmb_ctx_vars)
        ctx_layout.addWidget(btn_insert_ctx)
        ctx_layout.addStretch()
        var_layout.addLayout(ctx_layout)
        
        # Справка
        help_lbl = QLabel(tr("Используйте {имя_переменной} в полях выше для подстановки значений"))
        help_lbl.setStyleSheet("color: #565f89; font-size: 10px;")
        var_layout.addWidget(help_lbl)
        
        self._snippet_layout.addWidget(var_group)
        self._snippet_widgets["_variables_table"] = self._vars_table
        
        self._snippet_layout.addStretch()
        self._snippet_layout.addStretch()
        
        # Включаем отслеживание обратно
        self._snippet_tracker.set_restoring(False)
    
    def _update_code_source_visibility(self):
        """Переключить видимость: редактор кода vs путь к файлу."""
        source_widget = self._snippet_widgets.get('code_source')
        if not source_widget:
            return
        is_inline = (source_widget.currentData() == 'inline')
        
        # Редактор кода — виден только в режиме inline
        if hasattr(self, '_snippet_code_editor'):
            parent_w = self._snippet_code_editor.parent()
            if parent_w:
                parent_w.setVisible(is_inline)
            else:
                self._snippet_code_editor.setVisible(is_inline)
        
        # Путь к файлу — виден только в режиме file
        path_widget = self._snippet_widgets.get('script_path')
        if path_widget:
            parent_w = path_widget.parent()
            if parent_w and parent_w != self:
                parent_w.setVisible(not is_inline)
            else:
                path_widget.setVisible(not is_inline)
    
    def _update_snippet_field_visibility(self, agent_type: AgentType = None):
        if agent_type is None:
            node = getattr(self._props, '_node', None) if hasattr(self, '_props') and self._props else None
            if node:
                agent_type = node.agent_type
            else:
                return
        """Скрыть/показать поля сниппета в зависимости от текущего значения primary combo."""
        if not hasattr(self, '_snippet_widgets') or not hasattr(self, '_snippet_field_labels'):
            return

        def _show(key, visible: bool):
            w = self._snippet_widgets.get(key)
            lbl = self._snippet_field_labels.get(key)
            if w:
                w.setVisible(visible)
            if lbl and lbl is not w:
                lbl.setVisible(visible)

        def _get_val(key):
            w = self._snippet_widgets.get(key)
            if isinstance(w, QComboBox):
                return w.currentData() or w.currentText()
            return None

        # ── RANDOM_GEN ──────────────────────────────────────────
        if agent_type == AgentType.RANDOM_GEN:
            rtype = _get_val('random_type') or 'number'
            _show('num_from',      rtype == 'number')
            _show('num_to',        rtype == 'number')
            _show('str_len_min',   rtype == 'text')
            _show('str_len_max',   rtype == 'text')
            _show('use_upper',     rtype == 'text')
            _show('use_lower',     rtype == 'text')
            _show('use_digits',    rtype == 'text')
            _show('custom_chars',  rtype == 'text')
            _show('require_all',   rtype == 'text')
            _show('login_formula', rtype == 'login')

        # ── FILE_OPERATION ───────────────────────────────────────
        elif agent_type == AgentType.FILE_OPERATION:
            act = _get_val('file_action') or 'read'
            _show('content',          act == 'write')
            _show('append_mode',      act == 'write')
            _show('add_newline',      act == 'write')
            _show('new_path',         act in ('copy', 'move'))
            _show('delete_after_read',act == 'read')
            _show('encoding',         act in ('read', 'write'))
            _show('result_var',       act in ('read', 'exists'))

        # ── DIR_OPERATION ────────────────────────────────────────
        elif agent_type == AgentType.DIR_OPERATION:
            act = _get_val('dir_action') or 'list_files'
            _show('new_path',    act in ('copy', 'move'))
            _show('recursive',   act in ('list_files', 'list_dirs', 'get_file'))
            _show('mask',        act in ('list_files', 'list_dirs', 'get_file'))
            _show('file_select', act == 'get_file')
            _show('file_index',  act == 'get_file')
            _show('result_var',  act in ('exists', 'get_file'))
            _show('result_list', act in ('list_files', 'list_dirs'))

        # ── TEXT_PROCESSING ──────────────────────────────────────
        elif agent_type == AgentType.TEXT_PROCESSING:
            act = _get_val('text_action') or 'regex'
            needs_pattern   = act in ('regex', 'replace')
            needs_replace   = act == 'replace'
            needs_separator = act == 'split'
            needs_take_mode = act == 'regex'
            needs_match_idx = act == 'regex'
            needs_substr    = act == 'substring'
            _show('pattern',       needs_pattern)
            _show('replacement',   needs_replace)
            _show('separator',     needs_separator)
            _show('take_mode',     needs_take_mode)
            _show('match_index',   needs_match_idx)
            _show('substr_from',   needs_substr)
            _show('substr_to',     needs_substr)
            _show('error_on_empty',act in ('regex', 'split'))
            _show('result_list',   act in ('regex', 'split') and True)

        # ── VARIABLE_PROC ────────────────────────────────────────
        elif agent_type == AgentType.VARIABLE_PROC:
            act = _get_val('var_action') or 'set'
            _show('var_value',       act in ('set', 'concat'))
            _show('step_value',      act in ('increment', 'decrement'))
            _show('target_var',      act in ('copy', 'length'))
            _show('concat_separator',act == 'concat')
            _show('cast_type',       act == 'type_cast')
            _show('clear_except',    act == 'clear_all')
            _show('save_to_project', act not in ('clear_all',))

        # ── LIST_OPERATION ───────────────────────────────────────
        elif agent_type == AgentType.LIST_OPERATION:
            act = _get_val('operation') or 'add_line'
            is_proj = act.startswith('proj_list_')
            is_ctx  = not is_proj
            
            # ── Контекстные поля: скрыть если proj_ ──
            _show('list_var',        is_ctx)
            _show('value',           is_ctx and act in ('add_line', 'add_text', 'get_line', 'remove'))
            _show('position',        is_ctx and act in ('add_line', 'add_text'))
            _show('index',           is_ctx and act in ('add_line', 'add_text'))
            _show('get_mode',        is_ctx and act in ('get_line', 'remove'))
            _show('delete_after_get',is_ctx and act == 'get_line')
            _show('sort_numeric',    is_ctx and act == 'sort')
            _show('sort_descending', is_ctx and act == 'sort')
            _show('join_separator',  is_ctx and act == 'join')
            _show('file_path',       is_ctx and act in ('load_file', 'save_file'))
            _show('file_append',     is_ctx and act == 'save_file')
            _show('result_var',      (is_ctx and act in ('get_line', 'count', 'join'))
                                     or (is_proj and act in ('proj_list_get', 'proj_list_count', 'proj_list_load')))
            _show('file_path_or_var', False)  # Не для list_operation
            _show('after_upload_action', False)
            
            # ── Проектные поля: показать если proj_ ──
            _show('project_list_name',    is_proj)
            _show('proj_get_mode',        is_proj and act in ('proj_list_get', 'proj_list_remove'))
            _show('proj_delete_after_get',is_proj and act == 'proj_list_get')
            _show('proj_add_position',    is_proj and act == 'proj_list_add')
            _show('proj_value',           is_proj and act in ('proj_list_add', 'proj_list_remove', 'proj_list_save'))
            
            # ── Автозагрузка ──
            _show('auto_load_from_file',  is_ctx and act not in ('load_file', 'save_file', 'clear'))

        # ── TABLE_OPERATION ──────────────────────────────────────
        elif agent_type == AgentType.TABLE_OPERATION:
            act = _get_val('operation') or 'load'
            is_proj = act.startswith('proj_table_')
            is_ctx  = not is_proj
            
            # ── Контекстные поля ──
            _show('table_var',       is_ctx)
            _show('file_path',       is_ctx and act in ('load', 'save'))
            _show('delimiter',       is_ctx and act in ('load', 'save', 'add_row'))
            _show('row_index',       is_ctx and act in ('read_cell', 'write_cell', 'get_row', 'delete_rows'))
            _show('col_index',       is_ctx and act in ('read_cell', 'write_cell', 'get_column', 'set_column', 'delete_column'))
            _show('cell_value',      is_ctx and act == 'write_cell')
            _show('row_values',      is_ctx and act == 'add_row')
            _show('get_mode',        is_ctx and act in ('get_row', 'delete_rows'))
            _show('filter_text',     is_ctx and act in ('get_row', 'delete_rows'))
            _show('delete_after_get',is_ctx and act == 'get_row')
            _show('sort_column',     is_ctx and act == 'sort')
            _show('sort_numeric',    is_ctx and act == 'sort')
            _show('sort_descending', is_ctx and act == 'sort')
            _show('dedup_column',    is_ctx and act == 'deduplicate')
            _show('target_list',     is_ctx and act in ('get_column', 'get_row', 'set_column'))
            _show('result_var',      (is_ctx and act in ('read_cell', 'row_count', 'col_count', 'get_row'))
                                     or (is_proj and act in ('proj_table_get_row', 'proj_table_read_cell',
                                                              'proj_table_row_count', 'proj_table_load',
                                                              'proj_table_get_column')))
            
            # ── Проектные поля ──
            _show('project_table_name',    is_proj)
            _show('proj_row_get_mode',     is_proj and act in ('proj_table_get_row', 'proj_table_delete_row'))
            _show('proj_row_index',        is_proj and act in ('proj_table_get_row', 'proj_table_read_cell',
                                                                'proj_table_write_cell', 'proj_table_delete_row'))
            _show('proj_col_index',        is_proj and act in ('proj_table_read_cell', 'proj_table_write_cell',
                                                                'proj_table_get_column'))
            _show('proj_filter_text',      is_proj and act in ('proj_table_get_row', 'proj_table_delete_row'))
            _show('proj_cell_value',       is_proj and act == 'proj_table_write_cell')
            _show('proj_row_values',       is_proj and act == 'proj_table_add_row')
            _show('proj_delete_after_get', is_proj and act == 'proj_table_get_row')
            _show('proj_result_format',    is_proj and act in ('proj_table_get_row', 'proj_table_load'))
            
            # ── Автозагрузка ──
            _show('auto_load_from_file',  is_ctx and act not in ('load', 'save'))

        # ── JSON_XML ─────────────────────────────────────────────
        elif agent_type == AgentType.JSON_XML:
            src = _get_val('input_source') or 'text'
            act = _get_val('jx_action') or 'parse'
            _show('inline_data',   src == 'text')
            _show('input_var',     src == 'variable')
            _show('input_file',    src == 'file')
            _show('query_expr',    act == 'query')
            _show('key_path',      act in ('get_value', 'set_value'))
            _show('set_value',     act == 'set_value')
            _show('property_name', act == 'to_list')
            _show('result_list',   act in ('query', 'to_list'))
            _show('result_table',  act == 'to_table')

        # ── LOOP ─────────────────────────────────────────────────
        elif agent_type == AgentType.LOOP:
            ltype = _get_val('loop_type') or 'foreach_list'
            _show('data_var',      ltype == 'foreach_list')
            _show('file_path',     ltype == 'foreach_file')
            _show('inline_list',   ltype == 'foreach_inline')
            _show('separator',     ltype in ('foreach_list', 'foreach_inline'))
            _show('shuffle_items', ltype in ('foreach_list', 'foreach_file', 'foreach_inline'))
            _show('iter_var',      ltype in ('foreach_list', 'foreach_file', 'foreach_inline'))
            _show('exit_condition',ltype in ('while', 'count'))
        
        # ── BROWSER_ACTION ──────────────────────────────────────
        elif agent_type == AgentType.BROWSER_ACTION:
            act = _get_val('action') or 'navigate'
            
            # === КАТЕГОРИИ ДЕЙСТВИЙ ===
            # Действия, требующие селектор (target как CSS/XPath)
            needs_selector = act in ('click', 'double_click', 'right_click', 
                                      'type_text', 'clear_field', 'select_option', 'get_text', 'get_attr',
                                      'get_html', 'wait_element', 'scroll_to', 'scroll_page', 'upload_file')
            # Действия по координатам (x,y) — НОВЫЕ ПОЛЯ coord_x, coord_y
            needs_coordinates = act in ('click_xy', 'double_click_xy', 'right_click_xy', 'hover_xy')
            # Действия по тексту на странице — НОВОЕ ПОЛЕ search_text
            needs_search_text = act in ('click_text',)
            # Действия, требующие value (ввод текста, выбор опции, установка куки и т.д.)
            needs_value = act in ('type_text', 'select_option', 'cookie_set', 'file_upload')
            # Действия, требующие variable_out (получение данных)
            needs_output = act in ('get_text', 'get_attr', 'get_url', 'get_title', 'get_html',
                                    'cookie_get', 'execute_js', 'screenshot')
            # Действия без target вообще
            no_target = act in ('get_url', 'get_title', 'close_browser', 'maximize', 
                                 'navigate_back', 'navigate_forward', 'reload', 'wait_seconds')
            # Действия с URL как target
            url_target = act in ('navigate', 'wait_url')
            # JS target
            js_target = act in ('execute_js',)
            
            # === УПРАВЛЕНИЕ ВИДИМОСТЬЮ ПОЛЕЙ ===
            # Поле selector_type — только для действий с селекторами
            _show('selector_type', needs_selector)
            # Поле target — для: селекторы, URL, JS (НЕ для координат и поиска по тексту)
            _show('target', needs_selector or url_target or js_target or act in ('tab_activate', 'tab_close', 'screenshot'))
            # Поля координат — только для xy-действий
            _show('coord_x', needs_coordinates)
            _show('coord_y', needs_coordinates)
            # Поле поиска по тексту — только для text-действий
            _show('search_text', needs_search_text)
            # Поле value — для ввода данных
            _show('value', needs_value)
            # Поле variable_out — для получения результатов
            _show('variable_out', needs_output)
            
            # === ОБНОВЛЕНИЕ PLACEHOLDER ДЛЯ target ===
            target_widget = self._snippet_widgets.get('target')
            if target_widget:
                if url_target:
                    target_widget.setPlaceholderText("https://example.com")
                elif js_target:
                    target_widget.setPlaceholderText("return document.title;")
                elif needs_selector:
                    target_widget.setPlaceholderText("#id или .class или //xpath")
                elif act in ('tab_activate', 'tab_close'):
                    target_widget.setPlaceholderText("Имя вкладки или номер (0, 1, 2...)")
                elif act == 'screenshot':
                    target_widget.setPlaceholderText("Путь к файлу (пусто = screenshot.png)")
                else:
                    target_widget.setPlaceholderText("URL или селектор")
        
        # ── PROJECT_START ────────────────────────────────────────
        elif agent_type == AgentType.PROJECT_START:
            mode = _get_val('run_mode') or 'plain'
            is_ai     = mode in ('ai', 'hybrid')
            is_script = mode in ('script', 'hybrid')
            webrtc    = bool(self._snippet_widgets.get('webrtc_fake_devices') and
                             getattr(self._snippet_widgets.get('webrtc_fake_devices'), 'isChecked', lambda: False)())
            captcha   = (_get_val('captcha_service') or 'none') != 'none'
            log_file  = bool(self._snippet_widgets.get('log_to_file') and
                             getattr(self._snippet_widgets.get('log_to_file'), 'isChecked', lambda: False)())
            telegram  = bool(self._snippet_widgets.get('notify_telegram') and
                             getattr(self._snippet_widgets.get('notify_telegram'), 'isChecked', lambda: False)())
            proxy_on  = bool((self._snippet_widgets.get('browser_proxy') and
                              getattr(self._snippet_widgets.get('browser_proxy'), 'text', lambda: '')()))

            # Режим AI
            _show('model_id',           is_ai)
            _show('ai_temperature',     is_ai)
            _show('ai_max_tokens',      is_ai)
            _show('ai_system_prompt',   is_ai)
            # Режим скрипт
            _show('startup_script',     is_script)
            # Браузер — показываем все поля браузера только если он включён
            browser_on = bool(self._snippet_widgets.get('browser_auto_launch') and
                              getattr(self._snippet_widgets.get('browser_auto_launch'), 'isChecked', lambda: True)())
            for key in ('browser_engine', 'browser_headless', 'browser_profile',
                        'browser_start_url', 'browser_viewport',
                        'browser_show_images', 'browser_show_js', 'browser_show_css',
                        'browser_show_fonts', 'browser_block_media', 'browser_block_ads',
                        'browser_block_tracking', '_sep_display',
                        'browser_user_agent', 'browser_language', 'browser_timezone',
                        'browser_geolocation', 'browser_random_ua', '_sep_identity',
                        'browser_proxy', 'browser_proxy_bypass', 'browser_ignore_ssl',
                        'browser_offline', 'browser_throttle', '_sep_net',
                        'webrtc_fake_devices', '_sep_webrtc',
                        'browser_extra_args', '_sep_args',
                        'antidetect_enabled', '_sep_antidetect'):
                _show(key, browser_on)
            # WebRTC sub-fields — только если webrtc включён и браузер включён
            for key in ('webrtc_video_file', 'webrtc_audio_file', 'webrtc_audio_noloop',
                        'webrtc_audioinput_name', 'webrtc_audiooutput_name',
                        'webrtc_videoinput_name'):
                _show(key, browser_on and webrtc)
            # Прокси подробности
            _show('browser_proxy_bypass', browser_on)
            # Антидетект sub-fields
            antidetect = bool(self._snippet_widgets.get('antidetect_enabled') and
                              getattr(self._snippet_widgets.get('antidetect_enabled'), 'isChecked', lambda: False)())
            for key in ('antidetect_canvas', 'antidetect_webgl', 'antidetect_audio',
                        'antidetect_fonts', 'antidetect_screen',
                        'browser_disable_automation_flags'):
                _show(key, browser_on and antidetect)
            # Капча sub-fields
            _show('captcha_api_key', captcha)
            # Лог в файл
            _show('log_file_path',   log_file)
            _show('log_max_size_mb', log_file)
            # Telegram
            _show('telegram_bot_token', telegram)
            _show('telegram_chat_id',   telegram)
            # Подключаем сигналы чекбоксов для мгновенного перестроения
            for cb_key in ('browser_auto_launch', 'webrtc_fake_devices',
                           'log_to_file', 'notify_telegram', 'antidetect_enabled'):
                cb = self._snippet_widgets.get(cb_key)
                if cb and hasattr(cb, 'toggled'):
                    try:
                        cb.toggled.disconnect()
                    except Exception:
                        pass
                    cb.toggled.connect(lambda _, _at=AgentType.PROJECT_START:
                                       self._update_snippet_field_visibility(_at))
        # ── PROGRAM_ACTION ────────────────────────────────────────
        elif agent_type == AgentType.PROGRAM_ACTION:
            act = _get_val('action') or 'click'
            needs_coords = act in ('click', 'double_click', 'right_click', 'scroll', 'drag', 'hover')
            needs_text = act in ('type_text', 'hotkey')
            needs_drag = act == 'drag'
            _show('coord_x',     needs_coords)
            _show('coord_y',     needs_coords)
            _show('value',       needs_text)
            _show('drag_to_x',   needs_drag)
            _show('drag_to_y',   needs_drag)

        # ── PROGRAM_CLICK_IMAGE ───────────────────────────────────
        elif agent_type == AgentType.PROGRAM_CLICK_IMAGE:
            pass  # Все поля видимы всегда

        # ── PROGRAM_SCREENSHOT ────────────────────────────────────
        elif agent_type == AgentType.PROGRAM_SCREENSHOT:
            mode = _get_val('screenshot_region') or 'full'
            _show('region_rect', mode == 'region')
            save = _get_val('save_mode') or 'variable'
            _show('save_path',   save in ('file', 'both'))
            _show('variable_out', save in ('variable', 'both'))
            
        # ── HTTP_REQUEST ─────────────────────────────────────────
        elif agent_type == AgentType.HTTP_REQUEST:
            method = _get_val('method') or 'GET'
            load_c = _get_val('load_content') or ''
            _show('body',             method in ('POST', 'PUT', 'PATCH'))
            _show('content_type',     method in ('POST', 'PUT', 'PATCH'))
            _show('save_to_file',     load_c in ('as_file', 'as_file_and_headers'))
            _show('save_headers_var', load_c in ('headers_only', 'headers_and_content', 'as_file_and_headers'))
        
        # ── BROWSER_PROFILE_OP ───────────────────────────────────
        elif agent_type == AgentType.BROWSER_PROFILE_OP:
            op = _get_val('profile_op') or 'save_file'

            is_file_op      = op in ('save_file', 'load_file')
            is_folder_op    = op in ('save_folder', 'launch_folder')
            is_any_save     = op in ('save_file', 'save_folder')
            is_any_load     = op in ('load_file', 'launch_folder')
            is_reassign     = op == 'reassign'
            is_update       = op == 'update'
            is_generate     = op == 'generate'
            is_show         = op == 'show'
            needs_path      = op in ('save_file', 'load_file', 'save_folder', 'launch_folder')
            needs_instance  = op != 'generate'

            # Путь
            _show('_sep_path',             needs_path)
            _show('profile_path',          needs_path)
            _show('create_if_missing',     is_any_load or is_any_save)
            _show('error_on_incompatible', is_any_load)

            # Переменные
            vars_visible = is_any_save or is_any_load
            _show('_sep_vars',            vars_visible)
            _show('save_variables',       is_any_save)
            _show('create_missing_vars',  is_any_load)
            vars_mode = _get_val('variables_mode') or 'all'
            _show('variables_mode',       is_any_save)
            _show('variables_list',       is_any_save and vars_mode == 'selected')

            # Прокси
            _show('_sep_proxy',           is_any_save or is_reassign)
            _show('save_proxy',           is_any_save)
            _show('proxy_string',         is_reassign)

            # Переназначение
            _show('_sep_reassign',        is_reassign)
            for k in ('reassign_ua', 'reassign_name', 'reassign_surname',
                      'reassign_email', 'reassign_login', 'reassign_password',
                      'reassign_phone', 'reassign_birthday', 'reassign_gender',
                      'reassign_viewport', 'reassign_timezone', 'reassign_geo',
                      'reassign_language'):
                _show(k, is_reassign)

            # Обновление
            _show('_sep_update',          is_update)
            for k in ('update_max_profiles', 'update_same_browser',
                      'update_same_os', 'update_same_language'):
                _show(k, is_update)

            # Результат
            _show('_sep_result',          True)
            _show('result_var',           not is_show)
            _show('profile_name_var',     is_any_load or is_update or is_generate)

            # ID инстанса
            _show('instance_id',          needs_instance)

            # Подключаем пересчёт при смене variables_mode
            cmb_vars = self._snippet_widgets.get('variables_mode')
            if cmb_vars and hasattr(cmb_vars, 'currentIndexChanged'):
                try:
                    cmb_vars.currentIndexChanged.disconnect()
                except Exception:
                    pass
                cmb_vars.currentIndexChanged.connect(
                    lambda _, _at=AgentType.BROWSER_PROFILE_OP:
                        self._update_snippet_field_visibility(_at)
                )
        
        # ── BROWSER_CLICK_IMAGE ──────────────────────────────────
        elif agent_type == AgentType.BROWSER_CLICK_IMAGE:
            act = _get_val('action_type') or 'click'
            is_wait   = act in ('wait_appear', 'wait_disappear')
            is_check  = act == 'check_exists'
            is_screen = act == 'screenshot_region'
            is_hover  = act == 'hover'
            has_result = act not in ('hover',)
            _show('wait_timeout',    is_wait or is_check)
            _show('retry_interval',  is_wait or is_check)
            _show('click_offset_x',  act in ('click', 'double_click', 'right_click', 'hover'))
            _show('click_offset_y',  act in ('click', 'double_click', 'right_click', 'hover'))
            _show('variable_out',    not is_check and not is_screen)
            _show('found_var',       is_check or is_wait)
            _show('screenshot_var',  is_screen)
            _show('if_not_found',    not is_screen)
            for k in ('action_type',):
                cb = self._snippet_widgets.get(k)
                if cb and hasattr(cb, 'currentIndexChanged'):
                    try:
                        cb.currentIndexChanged.disconnect()
                    except Exception:
                        pass
                    cb.currentIndexChanged.connect(
                        lambda _, _at=AgentType.BROWSER_CLICK_IMAGE:
                            self._update_snippet_field_visibility(_at)
                    )

        # ── PROJECT_INFO ─────────────────────────────────────────
        elif agent_type == AgentType.PROJECT_INFO:
            info = _get_val('info_type') or 'browser_ids'
            is_browser = info in ('browser_ids', 'all')
            _show('active_browser_var', is_browser)
            _show('browser_count_var',  is_browser)
            _show('result_list_var',    info != 'all')
            _show('format',             info != 'all')
            cb = self._snippet_widgets.get('info_type')
            if cb and hasattr(cb, 'currentIndexChanged'):
                try:
                    cb.currentIndexChanged.disconnect()
                except Exception:
                    pass
                cb.currentIndexChanged.connect(
                    lambda _, _at=AgentType.PROJECT_INFO:
                        self._update_snippet_field_visibility(_at)
                )
        
        # ── BROWSER_SCREENSHOT ───────────────────────────────────
        elif agent_type == AgentType.BROWSER_SCREENSHOT:
            region  = _get_val('screenshot_region') or 'viewport'
            mode    = _get_val('save_mode') or 'var_only'
            is_jpeg = _get_val('image_format') == 'jpg'
            _show('element_selector', region == 'element')
            _show('variable_out',     mode in ('var_only', 'both'))
            _show('save_path',        mode in ('file_only', 'both'))
            _show('file_name',        mode in ('file_only', 'both'))
            _show('image_format',     mode in ('file_only', 'both'))
            _show('jpeg_quality',     mode in ('file_only', 'both') and is_jpeg)
            _show('open_after_save',  mode in ('file_only', 'both'))
            for cb_key in ('screenshot_region', 'save_mode', 'image_format'):
                cb = self._snippet_widgets.get(cb_key)
                if cb and hasattr(cb, 'currentIndexChanged'):
                    try:
                        cb.currentIndexChanged.disconnect()
                    except Exception:
                        pass
                    cb.currentIndexChanged.connect(
                        lambda _, _at=AgentType.BROWSER_SCREENSHOT:
                            self._update_snippet_field_visibility(_at)
                    )
        
        # ── LOG_MESSAGE ──────────────────────────────────────────
        elif agent_type == AgentType.LOG_MESSAGE:
            _show('log_file', bool(_get_val('write_to_file')))
            
        # ── BROWSER_CLOSE ─────────────────────────────────────────
        elif agent_type == AgentType.BROWSER_CLOSE:
            from constructor.browser_module import execute_browser_close_snippet
            context = execute_browser_close_snippet(
                cfg=snippet_cfg,
                context=context,
                manager=self._browser_manager,
                logger=self._log,
                project_browser_manager=project_browser_manager,
            )

        # ── BROWSER_SCREENSHOT ────────────────────────────────────
        elif agent_type == AgentType.BROWSER_SCREENSHOT:
            from constructor.browser_module import execute_browser_screenshot_snippet
            context = execute_browser_screenshot_snippet(
                cfg=snippet_cfg,
                context=context,
                manager=self._browser_manager,
                logger=self._log,
                project_browser_manager=project_browser_manager,
            )
            
        # ── BROWSER_PROFILE_OP ────────────────────────────────────
        elif agent_type == AgentType.BROWSER_PROFILE_OP:
            self._execute_profile_op_snippet(snippet_cfg, context)
    
    def _execute_profile_op_snippet(self, cfg: dict, context: dict):
        """Исполнение сниппета операций с профилем браузера."""
        import os, json, shutil
        from pathlib import Path

        op           = cfg.get('profile_op', 'save_file')
        instance_id  = cfg.get('instance_id', '').strip()
        profile_path = self._resolve_vars(cfg.get('profile_path', ''), context)
        result_var   = cfg.get('result_var', '').strip().strip('{}')
        name_var     = cfg.get('profile_name_var', '').strip().strip('{}')

        def _log(msg): self._log_msg(msg)

        def _get_inst():
            mgr = self._browser_manager
            if not mgr:
                return None
            if instance_id:
                return mgr.get_instance(instance_id)
            insts = mgr.get_all_instances()
            return insts[0] if insts else None

        def _resolve_path(raw: str) -> str:
            """Подставляет {project_dir} и прочие переменные."""
            raw = raw.replace('{project_dir}', self._project_root or '.')
            return raw

        profile_path = _resolve_path(profile_path)

        # ── Сохранить профиль-файл ──────────────────────────────────
        if op == 'save_file':
            inst = _get_inst()
            if not inst:
                _log("❌ Профиль: нет активного инстанса браузера")
                return
            try:
                save_vars  = cfg.get('save_variables', False)
                save_proxy = cfg.get('save_proxy', False)
                var_mode   = cfg.get('variables_mode', 'all')
                var_list   = [v.strip() for v in cfg.get('variables_list', '').split(',') if v.strip()]

                # Собираем данные профиля из инстанса
                profile_data = {
                    'user_agent':  getattr(inst, 'user_agent', ''),
                    'cookies':     inst.get_cookies() if hasattr(inst, 'get_cookies') else [],
                    'proxy':       getattr(inst, '_proxy_string', '') if save_proxy else '',
                    'name':        getattr(inst, 'profile_name', ''),
                    'variables':   {},
                }
                if save_vars:
                    tab = self._current_project_tab()
                    if tab and hasattr(tab, '_variables'):
                        all_vars = tab._variables
                        if var_mode == 'selected' and var_list:
                            profile_data['variables'] = {k: v for k, v in all_vars.items() if k in var_list}
                        else:
                            profile_data['variables'] = dict(all_vars)

                # Создаём директорию если нужно
                p = Path(profile_path)
                if cfg.get('create_if_missing', True):
                    p.parent.mkdir(parents=True, exist_ok=True)

                with open(profile_path, 'w', encoding='utf-8') as f:
                    json.dump(profile_data, f, ensure_ascii=False, indent=2)

                _log(f"💾 Профиль сохранён: {profile_path}")
                if result_var:
                    context[result_var] = profile_path

            except Exception as e:
                _log(f"❌ Ошибка сохранения профиля: {e}")

        # ── Загрузить профиль-файл ──────────────────────────────────
        elif op == 'load_file':
            inst = _get_inst()
            if not inst:
                _log("❌ Профиль: нет активного инстанса браузера")
                return
            try:
                p = Path(profile_path)
                if not p.exists():
                    if cfg.get('create_if_missing', True):
                        _log(f"⚠️ Файл профиля не найден, будет создан новый: {profile_path}")
                        return
                    else:
                        _log(f"❌ Файл профиля не найден: {profile_path}")
                        return

                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_data = json.load(f)

                # Устанавливаем куки
                cookies = profile_data.get('cookies', [])
                if cookies and hasattr(inst, 'set_cookies'):
                    inst.set_cookies(cookies)

                # Применяем переменные
                if profile_data.get('variables') and cfg.get('create_missing_vars', True):
                    tab = self._current_project_tab()
                    if tab and hasattr(tab, '_variables'):
                        for k, v in profile_data['variables'].items():
                            tab._variables[k] = v
                            context[k] = v

                profile_name = profile_data.get('name', Path(profile_path).stem)
                _log(f"📂 Профиль загружен: {profile_name} ({profile_path})")

                if result_var:
                    context[result_var] = profile_path
                if name_var:
                    context[name_var] = profile_name

            except Exception as e:
                _log(f"❌ Ошибка загрузки профиля: {e}")

        # ── Сохранить профиль-папку ─────────────────────────────────
        elif op == 'save_folder':
            inst = _get_inst()
            if not inst:
                _log("❌ Профиль-папка: нет активного инстанса")
                return
            try:
                p = Path(profile_path)
                p.mkdir(parents=True, exist_ok=True)

                save_vars  = cfg.get('save_variables', False)
                save_proxy = cfg.get('save_proxy', False)

                # Сохраняем метаданные
                meta = {
                    'user_agent': getattr(inst, 'user_agent', ''),
                    'name':       getattr(inst, 'profile_name', ''),
                    'proxy':      getattr(inst, '_proxy_string', '') if save_proxy else '',
                }
                with open(p / 'meta.json', 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)

                # Сохраняем переменные
                if save_vars:
                    tab = self._current_project_tab()
                    if tab and hasattr(tab, '_variables'):
                        var_mode = cfg.get('variables_mode', 'all')
                        var_list = [v.strip() for v in cfg.get('variables_list', '').split(',') if v.strip()]
                        vars_data = tab._variables
                        if var_mode == 'selected' and var_list:
                            vars_data = {k: v for k, v in vars_data.items() if k in var_list}
                        with open(p / 'variables.json', 'w', encoding='utf-8') as f:
                            json.dump(dict(vars_data), f, ensure_ascii=False, indent=2)

                _log(f"📁 Профиль-папка сохранена: {profile_path}")
                if result_var:
                    context[result_var] = profile_path

            except Exception as e:
                _log(f"❌ Ошибка сохранения профиль-папки: {e}")

        # ── Запустить инстанс с профиль-папкой ─────────────────────
        elif op == 'launch_folder':
            try:
                p = Path(profile_path)
                create_ok = cfg.get('create_if_missing', True)
                if not p.exists():
                    if create_ok:
                        p.mkdir(parents=True, exist_ok=True)
                        _log(f"📁 Создана новая профиль-папка: {profile_path}")
                    else:
                        _log(f"❌ Профиль-папка не найдена: {profile_path}")
                        return

                # Загружаем переменные из папки
                vars_file = p / 'variables.json'
                if vars_file.exists() and cfg.get('create_missing_vars', True):
                    with open(vars_file, 'r', encoding='utf-8') as f:
                        saved_vars = json.load(f)
                    tab = self._current_project_tab()
                    if tab and hasattr(tab, '_variables'):
                        tab._variables.update(saved_vars)
                        context.update(saved_vars)

                _log(f"📂 Инстанс привязан к профиль-папке: {profile_path}")
                if result_var:
                    context[result_var] = profile_path

            except Exception as e:
                _log(f"❌ Ошибка запуска с профиль-папкой: {e}")

        # ── Переназначить поля профиля ──────────────────────────────
        elif op == 'reassign':
            inst = _get_inst()
            fields_map = {
                'user_agent':    'reassign_ua',
                'first_name':    'reassign_name',
                'last_name':     'reassign_surname',
                'email':         'reassign_email',
                'login':         'reassign_login',
                'password':      'reassign_password',
                'phone':         'reassign_phone',
                'birthday':      'reassign_birthday',
                'viewport':      'reassign_viewport',
                'timezone':      'reassign_timezone',
                'geolocation':   'reassign_geo',
                'language':      'reassign_language',
            }
            applied = []
            for field, cfg_key in fields_map.items():
                val = self._resolve_vars(cfg.get(cfg_key, ''), context)
                if val and inst and hasattr(inst, field):
                    setattr(inst, field, val)
                    applied.append(f"{field}={val[:30]}")

            proxy = self._resolve_vars(cfg.get('proxy_string', ''), context)
            if proxy and inst:
                inst._proxy_string = proxy
                applied.append(f"proxy={proxy[:30]}")

            gender = cfg.get('reassign_gender', '')
            if gender and inst and hasattr(inst, 'gender'):
                inst.gender = gender
                applied.append(f"gender={gender}")

            _log(f"✏️ Поля профиля переназначены: {', '.join(applied) if applied else 'нет изменений'}")

        # ── Обновить профиль ────────────────────────────────────────
        elif op == 'update':
            inst = _get_inst()
            _log("🔄 Обновление профиля (поиск новой версии браузера)...")
            # Реальная реализация требует API генерации профилей
            # Здесь эмулируем обновление User-Agent
            if inst and hasattr(inst, 'user_agent'):
                old_ua = getattr(inst, 'user_agent', '')
                _log(f"🔄 Профиль обновлён (старый UA: {old_ua[:60]}...)")
                if result_var:
                    context[result_var] = 'updated'

        # ── Сгенерировать новый профиль ─────────────────────────────
        elif op == 'generate':
            _log("🔀 Генерация нового профиля...")
            import random, string
            new_name = ''.join(random.choices(string.ascii_lowercase, k=8))
            context['_profile_name'] = new_name
            if result_var:
                context[result_var] = new_name
            if name_var:
                context[name_var] = new_name
            _log(f"✅ Новый профиль сгенерирован: {new_name}")

        # ── Показать текущий профиль ────────────────────────────────
        elif op == 'show':
            inst = _get_inst()
            if inst:
                info = {
                    'Имя':        getattr(inst, 'profile_name', '—'),
                    'User-Agent': getattr(inst, 'user_agent', '—')[:80],
                    'Прокси':     getattr(inst, '_proxy_string', '—'),
                    'Язык':       getattr(inst, 'language', '—'),
                    'Таймзона':   getattr(inst, 'timezone', '—'),
                    'Разрешение': getattr(inst, 'viewport', '—'),
                }
                lines = [f"  {k}: {v}" for k, v in info.items()]
                _log("👁 Текущий профиль:\n" + "\n".join(lines))
            else:
                _log("❌ Нет активного инстанса для отображения профиля")

    def _resolve_vars(self, text: str, context: dict) -> str:
        """Подставить {переменные} из context в строку."""
        if not text:
            return text
        for k, v in context.items():
            text = text.replace(f'{{{k}}}', str(v))
        text = text.replace('{project_dir}', self._project_root or '.')
        return text
    
    def _install_var_context_menu(self, widget):
        """Установить контекстное меню с вставкой переменных на любое текстовое поле."""
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget: self._show_var_insert_menu(w, pos)
        )

    def _show_var_insert_menu(self, widget, pos):
        """Показать контекстное меню со списком переменных проекта для вставки."""
        menu = QMenu(self)
        
        # Стандартные действия текстового поля
        if isinstance(widget, (QLineEdit,)):
            std_menu = widget.createStandardContextMenu()
            for action in std_menu.actions():
                menu.addAction(action)
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            std_menu = widget.createStandardContextMenu()
            for action in std_menu.actions():
                menu.addAction(action)
        
        menu.addSeparator()
        
        # ═══ Подменю: Вставить переменную проекта ═══
        var_menu = menu.addMenu(tr("📥 Вставить переменную {var}"))
        
        # 1. Переменные из таблицы Variables текущего сниппета
        if hasattr(self, '_vars_table') and self._vars_table.rowCount() > 0:
            local_menu = var_menu.addMenu(tr("📝 Из таблицы Variables"))
            for row in range(self._vars_table.rowCount()):
                item = self._vars_table.item(row, 0)
                if item and item.text().strip():
                    vname = item.text().strip()
                    act = local_menu.addAction(f"{{{{ {vname} }}}}")
                    act.triggered.connect(
                        lambda checked, w=widget, v=vname: self._insert_var_into_widget(w, f"{{{v}}}")
                    )
        
        # 2. Переменные из контекста runtime
        runtime = getattr(self, '_runtime', None)
        ctx = {}
        if runtime and hasattr(runtime, '_context'):
            ctx = runtime._context
        
        if ctx:
            ctx_menu = var_menu.addMenu(tr("🔄 Из контекста (runtime)"))
            for key in sorted(ctx.keys()):
                if not key.startswith('_'):
                    val_preview = str(ctx[key])[:40]
                    act = ctx_menu.addAction(f"{{{key}}}  →  {val_preview}")
                    act.triggered.connect(
                        lambda checked, w=widget, v=key: self._insert_var_into_widget(w, f"{{{v}}}")
                    )
        
        # 3. Системные переменные
        sys_menu = var_menu.addMenu(tr("⚙️ Системные"))
        for svar in ["_last_output", "_last_node", "_last_error", "_last_failed_node",
                      "_loop_iteration", "_loop_max", "_condition_result",
                      "_switch_value", "_snippet_stdout"]:
            act = sys_menu.addAction(f"{{{svar}}}")
            act.triggered.connect(
                lambda checked, w=widget, v=svar: self._insert_var_into_widget(w, f"{{{v}}}")
            )
        
        # 4. Быстрый ввод
        var_menu.addSeparator()
        act_custom = var_menu.addMenu(tr("✏️ Ввести имя вручную..."))
        act_custom.triggered.connect(lambda: self._insert_custom_var(widget))
        
        menu.exec(widget.mapToGlobal(pos))

    def _insert_var_into_widget(self, widget, text):
        """Вставить текст в виджет в позицию курсора."""
        if isinstance(widget, QLineEdit):
            pos = widget.cursorPosition()
            current = widget.text()
            widget.setText(current[:pos] + text + current[pos:])
            widget.setCursorPosition(pos + len(text))
        elif isinstance(widget, QTextEdit):
            cursor = widget.textCursor()
            cursor.insertText(text)
        elif isinstance(widget, QPlainTextEdit):
            cursor = widget.textCursor()
            cursor.insertText(text)

    def _insert_custom_var(self, widget):
        """Диалог ввода произвольного имени переменной."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Вставить переменную", "Имя переменной:")
        if ok and name.strip():
            self._insert_var_into_widget(widget, f"{{{name.strip()}}}")
    
    def _update_if_condition_visibility(self):
        """Переключить видимость полей IF: визуальный конструктор vs Python выражение."""
        mode_widget = self._snippet_widgets.get('condition_mode')
        if not mode_widget:
            return
        is_visual = (mode_widget.currentData() == 'visual')
        
        # Визуальные поля
        for key in ['left_operand', 'operator', 'right_operand', 'compare_as',
                     'case_sensitive', 'chain_logic', 'extra_conditions']:
            w = self._snippet_widgets.get(key)
            if w:
                parent = w.parent()
                if parent and parent != self:
                    parent.setVisible(is_visual)
                else:
                    w.setVisible(is_visual)
        
        # Редактор кода — только в свободном режиме
        if getattr(self, '_snippet_code_editor', None) is not None:
            parent_w = self._snippet_code_editor.parent()
            if parent_w:
                parent_w.setVisible(not is_visual)
            else:
                self._snippet_code_editor.setVisible(not is_visual)

    def _show_var_insert_menu(self, widget, pos):
        """ПКМ меню: стандартные действия + вставка переменных проекта."""
        menu = QMenu(self)
        
        # Стандартные действия
        if isinstance(widget, QLineEdit):
            std = widget.createStandardContextMenu()
            for a in std.actions(): menu.addAction(a)
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            std = widget.createStandardContextMenu()
            for a in std.actions(): menu.addAction(a)
        
        menu.addSeparator()
        
        # ═══ 1. ПЕРЕМЕННЫЕ ПРОЕКТА (из таба Переменные) ═══
        proj_menu = menu.addMenu(tr("📋 Переменные проекта"))
        proj_vars_found = False
        # Из таблицы переменных проекта
        if hasattr(self, '_var_table'):
            for row in range(self._var_table.rowCount()):
                name_item = self._var_table.item(row, 0)
                val_item = self._var_table.item(row, 1)
                if name_item and name_item.text().strip():
                    vname = name_item.text().strip()
                    vval = val_item.text()[:30] if val_item else ""
                    act = proj_menu.addAction(f"{{{vname}}}  =  {vval}")
                    act.triggered.connect(
                        lambda _, w=widget, v=vname: self._insert_var_text(w, f"{{{v}}}")
                    )
                    proj_vars_found = True
        # Также из workflow.project_variables (даже если таблица не загружена)
        if hasattr(self, '_workflow') and self._workflow and hasattr(self._workflow, 'project_variables'):
            for vname, info in self._workflow.project_variables.items():
                # Не дублируем уже добавленные
                existing = False
                if hasattr(self, '_var_table'):
                    for row in range(self._var_table.rowCount()):
                        it = self._var_table.item(row, 0)
                        if it and it.text().strip() == vname:
                            existing = True; break
                if not existing:
                    vval = str(info.get('value', info.get('default', '')))[:30]
                    act = proj_menu.addAction(f"{{{vname}}}  =  {vval}")
                    act.triggered.connect(
                        lambda _, w=widget, v=vname: self._insert_var_text(w, f"{{{v}}}")
                    )
                    proj_vars_found = True
        if not proj_vars_found:
            proj_menu.addAction("(нет переменных)").setEnabled(False)
        
        # ═══ 1б. ПУТИ ПРОЕКТА ═══
        path_menu = menu.addMenu(tr("📂 Пути проекта"))
        proj_root = getattr(self, '_project_root', '') or ''
        if proj_root:
            act_root = path_menu.addAction(f"{{project_dir}} = {proj_root[:50]}")
            act_root.triggered.connect(
                lambda _, w=widget: self._insert_var_text(w, "{project_dir}")
            )
            act_root_raw = path_menu.addAction(f"Вставить путь: {proj_root[:50]}")
            act_root_raw.triggered.connect(
                lambda _, w=widget, p=proj_root: self._insert_var_text(w, p)
            )
        file_path = getattr(self, '_file_path', '') or ''
        if file_path:
            wf_dir = os.path.dirname(file_path)
            act_wf = path_menu.addAction(f"{{workflow_dir}} = {wf_dir[:50]}")
            act_wf.triggered.connect(
                lambda _, w=widget: self._insert_var_text(w, "{workflow_dir}")
            )
        if not proj_root and not file_path:
            path_menu.addAction("(не задана рабочая папка)").setEnabled(False)
        
        # ═══ 2. ПЕРЕМЕННЫЕ ТЕКУЩЕГО СНИППЕТА ═══
        if hasattr(self, '_vars_table') and self._vars_table.rowCount() > 0:
            snip_menu = menu.addMenu(tr("📝 Переменные сниппета"))
            for row in range(self._vars_table.rowCount()):
                item = self._vars_table.item(row, 0)
                if item and item.text().strip():
                    vname = item.text().strip()
                    act = snip_menu.addAction(f"{{{vname}}}")
                    act.triggered.connect(
                        lambda _, w=widget, v=vname: self._insert_var_text(w, f"{{{v}}}")
                    )
        
        # ═══ 3. КОНТЕКСТ RUNTIME ═══
        runtime = getattr(self, '_runtime', None)
        ctx = runtime._context if runtime and hasattr(runtime, '_context') else {}
        if ctx:
            ctx_menu = menu.addMenu(tr("🔄 Контекст runtime"))
            for key in sorted(k for k in ctx if not k.startswith('_')):
                preview = str(ctx[key])[:35]
                act = ctx_menu.addAction(f"{{{key}}} = {preview}")
                act.triggered.connect(
                    lambda _, w=widget, v=key: self._insert_var_text(w, f"{{{v}}}")
                )
        
        # ═══ 4. СИСТЕМНЫЕ ═══
        sys_menu = menu.addMenu(tr("⚙️ Системные переменные"))
        for sv in ["_last_output", "_last_node", "_last_error", "_last_failed_node",
                    "_loop_iteration", "_loop_max", "_condition_result",
                    "_switch_value", "_snippet_stdout"]:
            act = sys_menu.addAction(f"{{{sv}}}")
            act.triggered.connect(
                lambda _, w=widget, v=sv: self._insert_var_text(w, f"{{{v}}}")
            )
        
        menu.addSeparator()
        act_custom = menu.addAction(tr("✏️ Ввести имя переменной..."))
        act_custom.triggered.connect(lambda: self._insert_custom_var_dialog(widget))
        
        # ═══ 5. СПИСКИ ПРОЕКТА ═══
        menu.addSeparator()
        if hasattr(self, '_workflow') and self._workflow:
            pv = getattr(self._workflow, 'project_variables', {}) or {}
            list_names = [k for k, v in pv.items() if isinstance(v, list)
                          and (not v or not isinstance(v[0], (list, dict)))]
            if list_names:
                list_menu = menu.addMenu(tr("📃 Списки проекта"))
                for lname in list_names:
                    act = list_menu.addAction(f"{{{{ {lname} }}}}")
                    act.triggered.connect(
                        lambda _, w=widget, v=lname: self._insert_var_text(w, f"{{{v}}}")
                    )

        # ═══ 6. ТАБЛИЦЫ ПРОЕКТА ═══
        if hasattr(self, '_workflow') and self._workflow:
            pv = getattr(self._workflow, 'project_variables', {}) or {}
            tbl_names = [k for k, v in pv.items() if isinstance(v, list)
                         and v and isinstance(v[0], (list, dict))]
            if tbl_names:
                tbl_menu = menu.addMenu(tr("📊 Таблицы проекта"))
                for tname in tbl_names:
                    act = tbl_menu.addAction(f"{{{{ {tname} }}}}")
                    act.triggered.connect(
                        lambda _, w=widget, v=tname: self._insert_var_text(w, f"{{{v}}}")
                    )

        # ═══ 7. ID БРАУЗЕРОВ ═══
        try:
            from constructor.browser_module import BrowserManager
            mgr = BrowserManager.get()
            if mgr and hasattr(mgr, 'all_instances'):
                inst_ids = list(mgr.all_instances().keys())
                if inst_ids:
                    br_menu = menu.addMenu(tr("🌐 ID браузеров"))
                    act_first = br_menu.addAction("{browser_instance_id}  (первый/текущий)")
                    act_first.triggered.connect(
                        lambda _, w=widget: self._insert_var_text(w, "{browser_instance_id}")
                    )
                    for iid in inst_ids:
                        act = br_menu.addAction(iid)
                        act.triggered.connect(
                            lambda _, w=widget, v=iid: self._insert_var_text(w, v)
                        )
        except Exception:
            pass

        # ═══ 8. ИСТОЧНИКИ ДАННЫХ (файлы) ═══
        menu.addSeparator()
        data_menu = menu.addMenu(tr("📂 Источники данных"))
        
        act_from_txt = data_menu.addAction(tr("📄 Загрузить из TXT-списка..."))
        act_from_txt.triggered.connect(lambda: self._load_data_from_file(widget, 'txt'))
        
        act_from_csv = data_menu.addAction(tr("📊 Загрузить из CSV/TSV..."))
        act_from_csv.triggered.connect(lambda: self._load_data_from_file(widget, 'csv'))
        
        act_from_json = data_menu.addAction(tr("🔣 Загрузить из JSON..."))
        act_from_json.triggered.connect(lambda: self._load_data_from_file(widget, 'json'))
        
        act_from_clip = data_menu.addAction(tr("📋 Вставить список из буфера"))
        act_from_clip.triggered.connect(lambda: self._paste_list_from_clipboard(widget))
        
        data_menu.addSeparator()
        act_file_ref = data_menu.addAction(tr("🔗 Вставить путь к файлу..."))
        act_file_ref.triggered.connect(lambda: self._insert_file_path_reference(widget))
        
        act_dir_ref = data_menu.addAction(tr("📁 Вставить путь к папке..."))
        act_dir_ref.triggered.connect(lambda: self._insert_dir_path_reference(widget))
        
        menu.exec(widget.mapToGlobal(pos))

    def _insert_var_text(self, widget, text):
        """Вставить текст переменной в виджет в позицию курсора."""
        if isinstance(widget, QLineEdit):
            p = widget.cursorPosition()
            c = widget.text()
            widget.setText(c[:p] + text + c[p:])
            widget.setCursorPosition(p + len(text))
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.textCursor().insertText(text)

    def _insert_custom_var_dialog(self, widget):
        """Диалог ввода произвольного имени переменной."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Вставить переменную", "Имя переменной:")
        if ok and name.strip():
            self._insert_var_text(widget, f"{{{name.strip()}}}")
    
    def _load_data_from_file(self, widget, file_type: str):
        """Загрузить данные из файла и вставить в виджет."""
        filters = {
            'txt': "Text Files (*.txt);;All Files (*)",
            'csv': "CSV/TSV (*.csv *.tsv *.tab);;All Files (*)",
            'json': "JSON (*.json);;All Files (*)",
        }
        start_dir = getattr(self, '_project_root', '') or ''
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить данные", start_dir, filters.get(file_type, "All Files (*)"))
        if not path:
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = f.read()
            
            if file_type == 'txt':
                # Построчный список
                lines = [line.strip() for line in raw.splitlines() if line.strip()]
                content = '\n'.join(lines)
                self._log_msg(f"📄 Загружено {len(lines)} строк из {os.path.basename(path)}")
            elif file_type == 'csv':
                import csv
                import io
                # Определяем разделитель
                dialect = csv.Sniffer().sniff(raw[:2000]) if raw else None
                reader = csv.reader(io.StringIO(raw), dialect or 'excel')
                rows = list(reader)
                # Формируем: каждая строка через |, строки через \n
                content = '\n'.join(['|'.join(row) for row in rows])
                self._log_msg(f"📊 Загружено {len(rows)} строк из CSV {os.path.basename(path)}")
            elif file_type == 'json':
                content = raw
                self._log_msg(f"🔣 Загружен JSON из {os.path.basename(path)} ({len(raw)} символов)")
            else:
                content = raw
            
            # Вставляем в виджет
            if isinstance(widget, QLineEdit):
                # Для однострочных полей — только первую строку или путь
                first_line = content.split('\n')[0] if '\n' in content else content
                widget.setText(first_line)
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                widget.setPlainText(content)
            
        except Exception as e:
            QMessageBox.warning(self, "Ошибка загрузки", f"Не удалось прочитать файл:\n{e}")
    
    def _paste_list_from_clipboard(self, widget):
        """Вставить содержимое буфера обмена как список (по строкам)."""
        text = QApplication.clipboard().text()
        if not text:
            self._log_msg("⚠ Буфер обмена пуст")
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        content = '\n'.join(lines)
        if isinstance(widget, QLineEdit):
            widget.setText(lines[0] if lines else '')
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.setPlainText(content)
        self._log_msg(f"📋 Вставлено {len(lines)} строк из буфера обмена")
    
    def _insert_file_path_reference(self, widget):
        """Вставить путь к файлу через диалог."""
        start_dir = getattr(self, '_project_root', '') or ''
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", start_dir, "All Files (*)")
        if path:
            # Делаем относительным от project_root если возможно
            proj = getattr(self, '_project_root', '')
            if proj and path.startswith(proj):
                path = os.path.relpath(path, proj)
            self._insert_var_text(widget, path)
    
    def _insert_dir_path_reference(self, widget):
        """Вставить путь к папке через диалог."""
        start_dir = getattr(self, '_project_root', '') or ''
        path = QFileDialog.getExistingDirectory(self, "Выбрать папку", start_dir)
        if path:
            proj = getattr(self, '_project_root', '')
            if proj and path.startswith(proj):
                path = os.path.relpath(path, proj)
            self._insert_var_text(widget, path)
    
    def _on_code_editor_changed(self):
        """Синхронизировать код из редактора в node.snippet_config['_code']."""
        # ═══ КРИТИЧНО: НЕ трогать ноду пока идёт загрузка конфига ═══
        if getattr(self, '_snippet_loading', False):
            return
        current_node = getattr(self._props, '_node', None)
        if current_node and hasattr(self, '_snippet_code_editor'):
            code = self._snippet_code_editor.toPlainText()
            # КРИТИЧНО: сохраняем сразу в оба места
            if not hasattr(current_node, 'snippet_config') or current_node.snippet_config is None:
                current_node.snippet_config = {}
            current_node.snippet_config['_code'] = code
            current_node.user_prompt_template = code
        # Сохраняем остальные виджеты тоже
        self._flush_snippet_config_to_node()

    def _on_snippet_widget_changed(self, *args):
        """Сохраняет изменения и создает undo entry."""
        if getattr(self, '_snippet_loading', False):
            return

        # ═══ КРИТИЧНО: Сначала flush в ноду, потом создаём undo ═══
        self._flush_snippet_config_to_node()

        # Создаем undo entry при каждом изменении (не только при первом)
        old_config = getattr(self, '_snippet_config_before_edit', {})
        new_config = self._get_current_snippet_config()

        if old_config != new_config:
            mw = self._main_window if hasattr(self, '_main_window') else None
            if mw and hasattr(mw, '_history'):
                node = self._props._node if hasattr(self, '_props') and self._props else None
                if node:
                    # Захватываем значения в замыкание явно
                    _old = dict(old_config)
                    _new = dict(new_config)
                    _node = node
                    mw._history.push(
                        lambda n=_new, nd=_node: self._apply_snippet_config_to_node(nd, n),
                        lambda o=_old, nd=_node: self._apply_snippet_config_to_node(nd, o),
                        f"Изменение {node.name}"
                    )
            # Обновляем baseline для следующего изменения
            self._snippet_config_before_edit = new_config
            self._snippet_undo_pending = False

        self._flush_snippet_config_to_node()
    
    def _flush_snippet_config_to_node(self):
        """Принудительно сохранить все виджеты сниппета в node.snippet_config.
        Каждый тип сниппета хранит свои поля ОТДЕЛЬНО — нет пересечений между типами."""
        if getattr(self, '_snippet_loading', False):
            return
        
        current_node = self._props._node if (hasattr(self, '_props') and self._props) else None
        if not current_node:
            return
        
        import copy
        # Получаем тип текущего сниппета
        current_type = current_node.agent_type.value if hasattr(current_node.agent_type, 'value') else str(current_node.agent_type)
        
        # Восстанавливаем конфиги ДРУГИХ типов из кэша перед очисткой
        cached_all = getattr(current_node, '_snippet_config_by_type', {})
        
        # Начинаем с чистого словаря для ТЕКУЩЕГО типа
        current_node.snippet_config = {}
        
        if not hasattr(self, '_snippet_widgets'):
            return
        
        # Собираем значения из виджетов
        for key, widget in self._snippet_widgets.items():
            if key.startswith('_'):
                continue
                
            try:
                if isinstance(widget, QCheckBox):
                    current_node.snippet_config[key] = widget.isChecked()
                elif isinstance(widget, QSpinBox):
                    current_node.snippet_config[key] = widget.value()
                elif isinstance(widget, QComboBox):
                    current_node.snippet_config[key] = widget.currentData() or widget.currentText()
                elif isinstance(widget, QLineEdit):
                    current_node.snippet_config[key] = widget.text()
                elif isinstance(widget, QTextEdit):
                    current_node.snippet_config[key] = widget.toPlainText()
                elif isinstance(widget, QPlainTextEdit):
                    current_node.snippet_config[key] = widget.toPlainText()
            except RuntimeError:
                pass  # Виджет удален
        
        # ═══ КРИТИЧНО: Сохраняем переменные из таблицы ═══
        if hasattr(self, '_vars_table') and self._vars_table.rowCount() > 0:
            variables = []
            for row in range(self._vars_table.rowCount()):
                name = self._vars_table.item(row, 0)
                value = self._vars_table.item(row, 1)
                type_widget = self._vars_table.cellWidget(row, 2)
                desc = self._vars_table.item(row, 3)
                
                if name and name.text().strip():
                    variables.append({
                        "name": name.text().strip(),
                        "value": value.text() if value else "",
                        "type": type_widget.currentText() if type_widget else "string",
                        "description": desc.text() if desc else ""
                    })
            current_node.snippet_config["_variables"] = variables
        
        # ═══ Сохраняем код из редактора ═══
        if getattr(self, '_snippet_code_editor', None) is not None:
            try:
                code = self._snippet_code_editor.toPlainText()
                current_node.snippet_config['_code'] = code
                current_node.user_prompt_template = code
            except RuntimeError:
                pass
        
        # ═══ Сохраняем путь к прикрепленной таблице ═══
        if hasattr(self, '_fld_attached_table'):
            current_node.snippet_config["attached_table_path"] = self._fld_attached_table.text()
            
        # ═══ Сохраняем специфичные поля браузера ═══
        if hasattr(self, '_snippet_widgets'):
            # Координаты
            coord_x_widget = self._snippet_widgets.get('coord_x')
            coord_y_widget = self._snippet_widgets.get('coord_y')
            search_text_widget = self._snippet_widgets.get('search_text')
            
            if coord_x_widget:
                try:
                    current_node.snippet_config['coord_x'] = coord_x_widget.value()
                except:
                    pass
            if coord_y_widget:
                try:
                    current_node.snippet_config['coord_y'] = coord_y_widget.value()
                except:
                    pass
            if search_text_widget:
                try:
                    current_node.snippet_config['search_text'] = search_text_widget.text()
                except:
                    pass
                    
        # Автовысота для Switch
        node = getattr(self, '_node', None)
        if node and getattr(node, 'agent_type', None) == AgentType.SWITCH:
            cases_raw = node.snippet_config.get('cases', '')
            if isinstance(cases_raw, list):
                n_cases = max(len(cases_raw), 1)
            else:
                lines = [l.strip() for l in str(cases_raw).splitlines() if l.strip()]
                n_cases = max(len(lines), 1)
            new_h = 120 + (n_cases + 1) * 32
            if int(node.height) != new_h:
                node.height = new_h
                item = self._scene.get_node_item(node.id) if hasattr(self, '_scene') and self._scene else None
                if item:
                    item.setRect(0, 0, node.width, node.height)
                    item.update()
                    if hasattr(self._scene, 'update_edges'):
                        self._scene.update_edges()
        
        # Тег типа: рантайм будет знать какой тип сохранён
        current_node.snippet_config['_snippet_type'] = current_node.agent_type.value
        
        # Сохраняем конфиг текущего типа в кэш по типу
        if not hasattr(current_node, '_snippet_config_by_type'):
            current_node._snippet_config_by_type = {}
        current_node._snippet_config_by_type[current_type] = copy.deepcopy(current_node.snippet_config)

    def _load_snippet_config_to_widgets(self, node):
        """Загрузить конфиг сниппета из ноды в виджеты.
        Берёт конфиг именно для типа текущего сниппета из кэша по типу."""
        if not node or not hasattr(node, 'snippet_config'):
            return
        
        self._snippet_loading = True
        
        import copy
        current_type = node.agent_type.value if hasattr(node.agent_type, 'value') else str(node.agent_type)
        
        # Если есть кэш по типу — берём именно его (гарантия отсутствия пересечений)
        cached_by_type = getattr(node, '_snippet_config_by_type', {})
        if current_type in cached_by_type:
            config = copy.deepcopy(cached_by_type[current_type])
        else:
            # Первый раз: берём текущий конфиг только если тип совпадает
            raw = getattr(node, 'snippet_config', {}) or {}
            saved_type = raw.get('_snippet_type', current_type)
            if saved_type == current_type:
                config = copy.deepcopy(raw)
            else:
                config = {}  # Чужой конфиг — сбрасываем
        
        # Загружаем в виджеты из копии config, не из node.snippet_config напрямую
        if hasattr(self, '_snippet_widgets'):
            for key, widget in self._snippet_widgets.items():
                if key.startswith('_'):
                    continue
                
                if key not in config:
                    # Ключа нет в конфиге — НЕ трогаем виджет, оставляем schema-default
                    # (виджет уже создан с правильным default из SNIPPET_SCHEMA)
                    continue
                    
                value = config[key]
                
                try:
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(bool(value))
                    elif isinstance(widget, QSpinBox):
                        widget.setValue(int(value) if value else 0)
                    elif isinstance(widget, QComboBox):
                        idx = widget.findData(value)
                        if idx < 0:
                            idx = widget.findText(str(value))
                        if idx >= 0:
                            widget.setCurrentIndex(idx)
                    elif isinstance(widget, QLineEdit):
                        widget.setText(str(value))
                    elif isinstance(widget, QTextEdit):
                        widget.setPlainText(str(value))
                    elif isinstance(widget, QPlainTextEdit):
                        widget.setPlainText(str(value))
                except RuntimeError:
                    pass
        
        # ═══ Загружаем переменные в таблицу ═══
        if hasattr(self, '_vars_table'):
            self._vars_table.blockSignals(True)
            self._vars_table.setRowCount(0)
            
            variables = config.get("_variables", [])
            for var in variables:
                row = self._vars_table.rowCount()
                self._vars_table.insertRow(row)
                
                self._vars_table.setItem(row, 0, QTableWidgetItem(var.get('name', '')))
                self._vars_table.setItem(row, 1, QTableWidgetItem(var.get('value', '')))
                
                type_combo = QComboBox()
                type_combo.addItems(["string", "int", "float", "bool", "json", "list"])
                idx = type_combo.findText(var.get('type', 'string'))
                type_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self._vars_table.setCellWidget(row, 2, type_combo)
                
                self._vars_table.setItem(row, 3, QTableWidgetItem(var.get('description', '')))
            
            self._vars_table.blockSignals(False)
        
        # ═══ Загружаем код в редактор ═══
        if getattr(self, '_snippet_code_editor', None) is not None:
            try:
                code = config.get('_code', node.user_prompt_template or '')
                self._snippet_code_editor.setPlainText(code)
            except RuntimeError:
                pass
        
        # ═══ Загружаем специфичные поля браузера ═══
        if hasattr(self, '_snippet_widgets'):
            coord_x_widget = self._snippet_widgets.get('coord_x')
            coord_y_widget = self._snippet_widgets.get('coord_y')
            search_text_widget = self._snippet_widgets.get('search_text')
            
            if coord_x_widget and 'coord_x' in config:
                try:
                    coord_x_widget.setValue(int(config['coord_x']))
                except:
                    pass
            if coord_y_widget and 'coord_y' in config:
                try:
                    coord_y_widget.setValue(int(config['coord_y']))
                except:
                    pass
            if search_text_widget and 'search_text' in config:
                try:
                    search_text_widget.setText(str(config['search_text']))
                except:
                    pass
        
        # ═══ Загружаем путь к прикрепленной таблице ═══
        if hasattr(self, '_fld_attached_table'):
            self._fld_attached_table.setText(config.get("attached_table_path", ""))
        
        # Обновляем видимость полей
        if hasattr(self, '_update_code_source_visibility'):
            self._update_code_source_visibility()
        if hasattr(self, '_update_if_condition_visibility'):
            self._update_if_condition_visibility()
        
        # Обновляем трекер
        if hasattr(self, '_snippet_tracker'):
            self._snippet_tracker.set_restoring(False)
        
        # ═══ КРИТИЧНО: сбрасываем флаг блокировки ═══
        self._snippet_loading = False
    def _on_snippet_config_change(self, *_):
        """Сохранить snippet_config в текущую ноду."""
        node = self._props._node if hasattr(self, '_props') and self._props else None
        if not node:
            return
        if not hasattr(self, '_snippet_widgets'):
            return
        
        config = {}
        for key, widget in self._snippet_widgets.items():
            if isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QComboBox):
                config[key] = widget.currentData() or widget.currentText()
            elif isinstance(widget, QLineEdit):
                config[key] = widget.text()
            elif isinstance(widget, QTextEdit):
                config[key] = widget.toPlainText()
        
        node.snippet_config = config
    
    def _load_snippet_config(self, node: AgentNode):
        """Загрузить snippet_config из ноды в виджеты."""
        if not hasattr(self, '_snippet_widgets'):
            return
        config = getattr(node, 'snippet_config', {}) or {}
        
        for key, widget in self._snippet_widgets.items():
            if key not in config:
                continue
            val = config[key]
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(val))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(val))
            elif isinstance(widget, QComboBox):
                idx = widget.findData(val)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(val))
            elif isinstance(widget, QTextEdit):
                widget.setPlainText(str(val))
            widget.blockSignals(False)
    
    def _build_skills_tab(self):
        """Вкладка управления скиллами (заглушка - основная логика в палитре слева)"""
        w = QWidget()
        layout = QVBoxLayout(w)
        info = QLabel("Управление скиллами доступно в левой панели 'СКИЛЛЫ'")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        layout.addStretch()
        return w
    
    def set_available_models(self, models: list):
        """Получить список моделей из главного окна"""
        self._available_models = models
        self._props.set_available_models(models)
        
    def load_project_skills(self, project_root: str):
        """Загрузить скиллы из проекта"""
        self._project_root = project_root
        loaded = self._skill_registry.load_from_folder(project_root)
        self._refresh_skill_list()
        self._log_msg(f"📂 Проектные скиллы: {len(loaded)}")
        
    def enable_project_mode(self, enabled: bool = True):
        """Режим полной автоматизации проекта"""
        self._project_mode = enabled
        if enabled:
            self.setWindowTitle("🚀 AI Project Constructor — Автоматический режим")
            # Автосохранение workflow при изменениях
            self._workflow.auto_save = True
            
    async def run_full_project_generation(self, goal: str):
        """Полный цикл: анализ → генерация → тестирование → патчинг"""
        self._log_msg(f"🎯 Цель проекта: {goal}")
        
        # 1. Анализ цели и создание структуры агентов
        planner = self._create_planner_agent()
        plan = await self._execute_with_model(planner, goal)
        
        # 2. Автосоздание workflow из плана
        self._workflow = self._parse_plan_to_workflow(plan)
        self._scene.set_workflow(self._workflow)
        
        # 3. Выполнение с автопатчингом
        self._runtime = WorkflowRuntimeEngine(
            self._workflow,
            self._model_manager,
            self._skill_registry,
            self._log_msg
        )
        
        result = await self._runtime.execute_workflow()
        
        # 4. Финальная валидация
        if self._validate_project(result):
            self._log_msg("✅ Проект успешно создан!")
            self._save_workflow()
        else:
            self._log_msg("⚠️ Требуется доработка")
            
    def _create_planner_agent(self) -> AgentNode:
        """Создать агента-планировщика для разбора задачи"""
        return AgentNode(
            name="🎯 Project Planner",
            agent_type=AgentType.PLANNER,
            model_id=self._get_best_reasoning_model(),
            system_prompt="""You are an expert project architect. 
Analyze the user's goal and create a detailed execution plan.
Break down into: modules, files, agents needed, skills required.
Output as structured JSON with workflow definition.""",
            available_tools=["file_write", "code_execute"],
            auto_improve=True,
            max_iterations=5
        )
        
    def _get_best_reasoning_model(self) -> str:
        """Выбрать лучшую доступную модель для сложных задач"""
        for model in self._available_models:
            if any(x in model.id.lower() for x in ["gpt-4", "claude-3-opus", "o1"]):
                return model.id
        return self._available_models[0].id if self._available_models else "default"
    
    def closeEvent(self, event):
        """Обработка закрытия окна — проверяем ВСЕ вкладки на несохранённые изменения."""
        from PyQt6.QtWidgets import QMessageBox
        import os as _os

        # Собираем все несохранённые вкладки
        unsaved = []
        for i in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(i)
            if not isinstance(tab, ProjectTab):
                continue
            
            # Проверяем флаг изменений таба И глобальный флаг только для активного
            is_active = (self._current_project_tab() is tab)
            tab_modified = tab._modified
            
            # Для активного таба также проверяем глобальный флаг (на случай если изменения были недавно)
            if is_active:
                tab_modified = tab_modified or self._is_modified
                # Синхронизируем: если глобальный флаг установлен, установим и в таб
                if self._is_modified:
                    tab._modified = True
            
            # Проверяем есть ли реальные изменения (не пустой новый проект)
            has_content = tab.workflow and (
                len(tab.workflow.nodes) > 0 or len(tab.workflow.edges) > 0
            )
            
            # Новый пустой проект не считается "несохранённым" если не было изменений
            is_really_modified = tab_modified and has_content
            
            # Дополнительная проверка: если проект никогда не сохранялся и пустой - не предлагать
            has_never_been_saved = not getattr(tab, 'project_path', '')
            if has_never_been_saved and not has_content and not tab_modified:
                is_really_modified = False
            
            if is_really_modified:
                tab_name = self._project_tabs.tabText(i) or f"Проект {i+1}"
                path = getattr(tab, 'project_path', '') or ''
                unsaved.append((i, tab, tab_name, path))

        if not unsaved:
            event.accept()
            return

        # Формируем список несохранённых проектов
        names_list = "\n".join(
            f"  • {name}" + (f"  ({_os.path.basename(path)})" if path else "  (новый)")
            for _, _, name, path in unsaved
        )

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr("Несохранённые изменения"))
        msg_box.setText(tr(f"Следующие проекты содержат несохранённые изменения:\n\n{names_list}"))
        msg_box.setInformativeText(tr("Сохранить все перед закрытием?"))
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.SaveAll |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.SaveAll)
        msg_box.button(QMessageBox.StandardButton.SaveAll).setText(tr("💾 Сохранить все"))
        msg_box.button(QMessageBox.StandardButton.Discard).setText(tr("🗑️ Закрыть без сохранения"))
        msg_box.button(QMessageBox.StandardButton.Cancel).setText(tr("❌ Отмена"))

        reply = msg_box.exec()

        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return

        if reply == QMessageBox.StandardButton.SaveAll:
            for i, tab, name, path in unsaved:
                # Переключаемся на каждый таб и сохраняем
                self._project_tabs.setCurrentIndex(i)
                QApplication.processEvents()
                self._save_workflow()
                # Если сохранение было отменено (нет пути и по-прежнему изменён)
                still_modified = tab._modified or (
                    self._current_project_tab() is tab and self._is_modified
                )
                if still_modified and not getattr(tab, 'project_path', ''):
                    event.ignore()
                    return

        # ═══ Сохраняем состояние менеджера проектов ═══
        if hasattr(self, '_project_exec_manager') and self._project_exec_manager:
            self._project_exec_manager.save_state()
        
        # FIX: Принудительно обновляем layout после закрытия всех браузеров
        try:
            for _i in range(self._project_tabs.count()):
                _t = self._project_tabs.widget(_i)
                if hasattr(_t, '_fix_tray_layout'):
                    _t._fix_tray_layout()
        except Exception:
            pass
        
        event.accept()
    
    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.theme_manager import apply_dark_titlebar
            apply_dark_titlebar(self)
        except Exception:
            pass

    def _build_models_tab(self):
        w = QWidget()
        layout = QFormLayout(w)
        
        # Основная модель
        self._cmb_main_model = QComboBox()
        self._cmb_main_model.addItem(tr("По умолчанию"), "")
        layout.addRow(tr("Основная модель:"), self._cmb_main_model)
        
        # Reasoning модель
        self._cmb_reasoning = QComboBox()
        self._cmb_reasoning.addItem(tr("Использовать основную"), "")
        layout.addRow(tr("Модель для рассуждений:"), self._cmb_reasoning)
        
        # Vision модель
        self._cmb_vision = QComboBox()
        self._cmb_vision.addItem(tr("Не использовать"), "")
        layout.addRow(tr("Vision модель:"), self._cmb_vision)
        
        # Fast модель
        self._cmb_fast = QComboBox()
        self._cmb_fast.addItem(tr("Использовать основную"), "")
        layout.addRow(tr("Быстрая модель:"), self._cmb_fast)
        
        # Анализ скиллов
        self._cmb_skill_model = QComboBox()
        self._cmb_skill_model.addItem(tr("Не анализировать"), "")
        layout.addRow(tr("Модель для подбора скиллов:"), self._cmb_skill_model)
        
        # Заполним при установке model_manager
        return w
    
    def set_available_models(self, models: list):
        """Вызывается извне для заполнения комбобоксов моделями"""
        self._available_models = models
        combo_boxes = [self._cmb_main_model, self._cmb_reasoning, 
                       self._cmb_vision, self._cmb_fast, self._cmb_skill_model]

        if hasattr(self, '_fld_model') and isinstance(self._fld_model, QComboBox):
            combo_boxes.extend([self._fld_model, self._fld_vision])

        for combo in combo_boxes:
            combo.blockSignals(True)  # Блокируем сигналы, чтобы clear() не стирал настройки
            current = combo.currentData()
            combo.clear()

            if combo in [getattr(self, '_fld_model', None), getattr(self, '_fld_vision', None)]:
                combo.addItem(tr("models_default_global"), "default_global")
            else:
                combo.addItem(tr("models_not_selected"), "not_selected")

            for model in models:
                combo.addItem(f"{model.display_name}", model.id)

            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)  # Разблокируем сигналы

        # Заполняем модели для верификации
        if hasattr(self, '_cmb_verify_model'):
            self._cmb_verify_model.blockSignals(True)
            self._cmb_verify_model.clear()
            self._cmb_verify_model.addItem(tr("models_default"), "default")
            for model in models:
                self._cmb_verify_model.addItem(f"{model.display_name}", model.id)
            self._cmb_verify_model.blockSignals(False)

        self._load_globals_from_workflow()


    def _sync_globals_to_workflow(self, *_):
        """Сохраняем ВСЕ глобальные настройки в workflow metadata"""
        if not self._workflow: return

        if not hasattr(self._workflow, 'metadata'):
            self._workflow.metadata = {}

        models_config = {
            "main": self._cmb_main_model.currentData(),
            "reasoning": self._cmb_reasoning.currentData(),
            "vision": self._cmb_vision.currentData(),
            "fast": self._cmb_fast.currentData(),
            "skill": self._cmb_skill_model.currentData(),
        }
        self._workflow.metadata['global_models'] = models_config

        # ── Тулзы — per-node, НЕ записываем в global_tools,
        # чтобы не затирать настройки отдельных агентов ──
        pass
        if hasattr(self, '_cmb_exec_mode'):
            self._workflow.metadata['global_execution'] = {
                'orchestration_mode': self._cmb_exec_mode.currentData() or 'sequential',
                'timeout':            self._spn_timeout.value(),
                'breakpoint_enabled': self._chk_breakpoint.isChecked(),
                'human_in_loop':      self._chk_human_loop.isChecked(),
                'backup_before_run':  self._chk_backup_before_run.isChecked()
                    if hasattr(self, '_chk_backup_before_run') else False,
            }
        # Сохраняем рабочую папку в metadata
        self._workflow.metadata['project_root'] = self._project_root
        # Сохраняем пути загруженных папок скиллов
        if not hasattr(self, '_loaded_skill_folders'):
            self._loaded_skill_folders = []
        self._workflow.metadata['loaded_skill_folders'] = self._loaded_skill_folders.copy()
        print(f"[SAVE PROJECT_ROOT] '{self._project_root}'")
        if hasattr(self, '_chk_auto_test'):
            self._workflow.metadata['global_auto'] = {
                'auto_test':     self._chk_auto_test.isChecked(),
                'auto_patch':    self._chk_auto_patch.isChecked(),
                'auto_improve':  self._chk_auto_improve.isChecked(),
                'max_iterations': self._spn_max_iter.value(),
                'self_modify':   self._chk_self_modify.isChecked(),
            }

        # ── Per-node настройки из СЦЕНЫ (для выбранных нод) ──
        node_settings = {}
        for item in self._scene._node_items.values():
            node = item.node  # оригинальный объект, НЕ копия
            # КРИТИЧНО: принудительно получаем snippet_config, создаём если нет
            snip_cfg = getattr(node, 'snippet_config', None)
            if snip_cfg is None:
                snip_cfg = {}
            if '_code' not in snip_cfg and getattr(node, 'user_prompt_template', ''):
                snip_cfg['_code'] = node.user_prompt_template
            
            node_settings[node.name] = {
                'available_tools':    getattr(node, 'available_tools', []),
                'tool_configs':       getattr(node, 'tool_configs', {}),
                'orchestration_mode': getattr(node, 'orchestration_mode', 'sequential'),
                'breakpoint_enabled': getattr(node, 'breakpoint_enabled', False),
                'human_in_loop':      getattr(node, 'human_in_loop', False),
                'auto_test':          getattr(node, 'auto_test', False),
                'auto_patch':         getattr(node, 'auto_patch', False),
                'auto_improve':       getattr(node, 'auto_improve', False),
                'max_iterations':     getattr(node, 'max_iterations', 1),
                'self_modify':        getattr(node, 'self_modify', False),
                'backup_before_node': getattr(node, 'backup_before_node', False),
                'snippet_config':     snip_cfg,
                'user_prompt_template': getattr(node, 'user_prompt_template', ''),
                'description':        getattr(node, 'description', ''),
                'comment':            getattr(node, 'comment', ''),
            }
        self._workflow.metadata['node_settings'] = node_settings

        if self._settings:
            setattr(self._settings, 'agent_constructor_models', models_config)


    def _load_globals_from_workflow(self):
        """Загружаем ВСЕ глобальные настройки из workflow metadata."""
        meta = getattr(self._workflow, 'metadata', {})
        
        # ── ПЕРВЫМ ДЕЛОМ восстанавливаем project_root ──
        # НО: если project_root уже установлен (например при открытии проекта),
        # то НЕ перезаписываем его из metadata — используем уже установленное значение
        saved_root = meta.get('project_root', '')
        
        # project_root всегда берём из metadata, т.к. он хранится в ProjectTab
        print(f"[LOAD GLOBALS] восстанавливаем project_root из metadata: '{saved_root}'")
        print(f"[LOAD PROJECT_ROOT] meta keys={list(meta.keys())}, saved_root='{saved_root}'")
        if saved_root:
            self._project_root = saved_root
            self._fld_working_dir.blockSignals(True)
            self._fld_working_dir.setText(saved_root)
            self._fld_working_dir.blockSignals(False)
            # Сохраняем в текущий ProjectTab чтобы не потерять при смене вкладок
            _tab = self._current_project_tab()
            if _tab is not None:
                _tab._project_root = saved_root
            if os.path.exists(saved_root):
                self._log_msg(f"📂 Рабочая папка: {saved_root}")
            else:
                self._log_msg(f"📂 Рабочая папка (⚠ не существует): {saved_root}")
        
        models_data = meta.get('global_models')

        if not models_data and self._settings and hasattr(self._settings, 'agent_constructor_models'):
            models_data = getattr(self._settings, 'agent_constructor_models')

        if models_data:
            for combo, key in [
                (self._cmb_main_model, "main"),
                (self._cmb_reasoning, "reasoning"),
                (self._cmb_vision, "vision"),
                (self._cmb_fast, "fast"),
                (self._cmb_skill_model, "skill")
            ]:
                idx = combo.findData(models_data.get(key, ""))
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        
        # ── Восстанавливаем загруженные папки скиллов ──
        saved_skill_folders = meta.get('loaded_skill_folders', [])
        # Восстанавливаем в self чтобы при следующем сохранении не потерять
        self._loaded_skill_folders = saved_skill_folders.copy()
        if saved_skill_folders:
            if not hasattr(self, '_loaded_skill_folders'):
                self._loaded_skill_folders = []
            for folder in saved_skill_folders:
                if folder and os.path.exists(folder) and folder not in self._loaded_skill_folders:
                    loaded = self._skill_registry.load_from_folder(folder)
                    self._loaded_skill_folders.append(folder)
                    self._log_msg(f"📂 Восстановлены скиллы из {folder}: {len(loaded)} шт.")
            self._refresh_skill_list()
        
        # ── Загружаем Тулзы ──
        tools_data = meta.get('global_tools', {})
        if tools_data and hasattr(self, '_tool_checkboxes'):
            for t_id, chk in self._tool_checkboxes.items():
                chk.blockSignals(True)
                chk.setChecked(tools_data.get(t_id, False))
                chk.blockSignals(False)
            print(f"[LOAD TOOLS] {tools_data}")

        # ── Загружаем Выполнение ──
        exec_data = meta.get('global_execution', {})
        if exec_data and hasattr(self, '_cmb_exec_mode'):
            self._cmb_exec_mode.blockSignals(True)
            idx = self._cmb_exec_mode.findData(exec_data.get('orchestration_mode', 'sequential'))
            self._cmb_exec_mode.setCurrentIndex(idx if idx >= 0 else 0)
            self._cmb_exec_mode.blockSignals(False)
            self._spn_timeout.blockSignals(True)
            self._spn_timeout.setValue(exec_data.get('timeout', 60))
            self._spn_timeout.blockSignals(False)
            self._chk_breakpoint.blockSignals(True)
            self._chk_breakpoint.setChecked(exec_data.get('breakpoint_enabled', False))
            self._chk_breakpoint.blockSignals(False)
            self._chk_human_loop.blockSignals(True)
            self._chk_human_loop.setChecked(exec_data.get('human_in_loop', False))
            self._chk_human_loop.blockSignals(False)
            if hasattr(self, '_chk_backup_before_run'):
                self._chk_backup_before_run.blockSignals(True)
                self._chk_backup_before_run.setChecked(exec_data.get('backup_before_run', False))
                self._chk_backup_before_run.blockSignals(False)
            print(f"[LOAD EXEC] {exec_data}")

        # ── Загружаем Авто ──
        auto_data = meta.get('global_auto', {})
        if auto_data and hasattr(self, '_chk_auto_test'):
            self._chk_auto_test.blockSignals(True)
            self._chk_auto_test.setChecked(auto_data.get('auto_test', False))
            self._chk_auto_test.blockSignals(False)
            self._chk_auto_patch.blockSignals(True)
            self._chk_auto_patch.setChecked(auto_data.get('auto_patch', False))
            self._chk_auto_patch.blockSignals(False)
            self._chk_auto_improve.blockSignals(True)
            self._chk_auto_improve.setChecked(auto_data.get('auto_improve', False))
            self._chk_auto_improve.blockSignals(False)
            self._spn_max_iter.blockSignals(True)
            self._spn_max_iter.setValue(auto_data.get('max_iterations', 1))
            self._spn_max_iter.blockSignals(False)
            self._chk_self_modify.blockSignals(True)
            self._chk_self_modify.setChecked(auto_data.get('self_modify', False))
            self._chk_self_modify.blockSignals(False)
            print(f"[LOAD AUTO] {auto_data}")
            
    def _build_tools_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)
        
        # ВСЕ возможные тулзы с настройками
        ALL_TOOLS_CONFIG = {
            "file_read": {
                "icon": "📖",
                "name": tr("Чтение файлов"),
                "desc": tr("Чтение с ограничениями"),
                "params": {
                    "max_file_size_kb": (tr("Макс. размер файла (KB)"), 1024, 1, 10000),
                    "allowed_extensions": (tr("Разрешенные расширения"), ".py,.txt,.md,.json,.yaml,.js,.ts,.html,.css"),
                    "encoding": (tr("Кодировка"), "utf-8")
                }
            },
            "file_write": {
                "icon": "✏️",
                "name": tr("Запись файлов"),
                "desc": tr("Создание и модификация"),
                "params": {
                    "backup_before_write": (tr("Создавать бэкап"), True),
                    "max_file_size_kb": (tr("Макс. размер для записи (KB)"), 2048, 1, 5000),
                    "auto_format": (tr("Автоформатирование"), True)
                }
            },
            "shell_exec": {
                "icon": "💻",
                "name": tr("Терминал"),
                "desc": tr("Выполнение shell команд"),
                "params": {
                    "timeout_seconds": (tr("Таймаут (сек)"), 30, 1, 300),
                    "allowed_commands": (tr("Разрешенные команды"), "python,git,pip,pytest,ls,cd,cat,echo"),
                    "work_dir_restricted": (tr("Ограничить рабочей папкой"), True),
                    "max_output_lines": (tr("Макс. строк вывода"), 100, 10, 1000)
                }
            },
            "browser_navigate": {
                "icon": "🌐",
                "name": tr("Браузер"),
                "desc": tr("Навигация и скриншоты"),
                "params": {
                    "headless": (tr("Headless режим"), True),
                    "viewport_width": (tr("Ширина viewport"), 1920, 800, 3840),
                    "viewport_height": (tr("Высота viewport"), 1080, 600, 2160),
                    "timeout_seconds": (tr("Таймаут загрузки"), 10, 1, 60)
                }
            },
            "browser_click": {
                "icon": "🖱️",
                "name": tr("Клик в браузере"),
                "desc": tr("Клики по элементам UI"),
                "params": {
                    "timeout_seconds": (tr("Таймаут (сек)"), 5, 1, 30),
                    "wait_after_click": (tr("Ждать после клика (сек)"), 1, 0, 10)
                }
            },
            "browser_screenshot": {
                "icon": "📸",
                "name": tr("Скриншот"),
                "desc": tr("Скриншоты страницы или элемента"),
                "params": {
                    "full_page": (tr("Полная страница"), True),
                    "format": (tr("Формат"), "png")
                }
            },
            "code_execute": {
                "icon": "⚙️",
                "name": tr("Выполнение кода"),
                "desc": tr("Python execution"),
                "params": {
                    "timeout_seconds": (tr("Таймаут (сек)"), 60, 1, 600),
                    "memory_limit_mb": (tr("Лимит памяти (MB)"), 512, 64, 2048),
                    "allowed_modules": (tr("Разрешенные модули"), "os,sys,json,re,math,random,datetime,pathlib,typing,collections,itertools"),
                    "sandbox": (tr("Песочница (ограниченный импорт)"), True)
                }
            },
            "patch_apply": {
                "icon": "🔧",
                "name": tr("Патчинг"),
                "desc": tr("SEARCH/REPLACE патчи"),
                "params": {
                    "validate_before_apply": (tr("Валидировать перед применением"), True),
                    "create_backup": (tr("Создавать бэкап"), True),
                    "auto_fix_indentation": (tr("Автоисправление отступов"), True)
                }
            },
            "image_generate": {
                "icon": "🎨",
                "name": tr("Генерация изображений"),
                "desc": tr("Создание изображений через AI"),
                "params": {
                    "width": (tr("Ширина"), 1024, 256, 2048),
                    "height": (tr("Высота"), 1024, 256, 2048),
                    "format": (tr("Формат"), "png")
                }
            },
        }
        
        # Сохраняем конфиг для использования в других методах
        self._all_tools_config = ALL_TOOLS_CONFIG
        
        # Создаем чекбоксы для выбора тулзов (per-node!)
        self._tool_checkboxes = {}
        
        for tool_id, cfg in ALL_TOOLS_CONFIG.items():
            group = QGroupBox(f"{cfg['icon']} {cfg['name']} ({tool_id})")
            group.setCheckable(True)
            group.setChecked(False)
            # Делаем галочку хорошо видимой: зелёная при включении, серая при выключении
            group.setStyleSheet("""
                QGroupBox::indicator { width: 16px; height: 16px; }
                QGroupBox::indicator:unchecked {
                    border: 2px solid #565f89; border-radius: 3px; background: #131722;
                }
                QGroupBox::indicator:checked {
                    border: 2px solid #9ECE6A; border-radius: 3px; background: #9ECE6A;
                    image: url(none);
                }
                QGroupBox:checked { border: 1px solid #9ECE6A; color: #9ECE6A; }
                QGroupBox:unchecked { border: 1px solid #2E3148; color: #565f89; }
            """)
            group.toggled.connect(lambda checked, tid=tool_id: self._on_tool_toggled(tid, checked))
            
            form = QFormLayout()
            form.setSpacing(5)
            
            for param_id, (label, default, *rest) in cfg['params'].items():
                if isinstance(default, bool):
                    widget = QCheckBox()
                    widget.setChecked(default)
                    widget.stateChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                        self._update_tool_param(tid, pid, bool(v)))
                elif isinstance(default, int):
                    widget = QSpinBox()
                    widget.setRange(rest[0], rest[1])
                    widget.setValue(default)
                    widget.setSuffix(" " + label.split("(")[-1].replace(")", ""))
                    widget.valueChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                        self._update_tool_param(tid, pid, v))
                else:
                    widget = QLineEdit(str(default))
                    widget.textChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                        self._update_tool_param(tid, pid, v))
                
                form.addRow(label, widget)
                # Сохраняем ссылку на виджет для восстановления значений
                if not hasattr(self, '_tool_widgets'):
                    self._tool_widgets = {}
                self._tool_widgets[f"{tool_id}.{param_id}"] = widget
            
            group.setLayout(form)
            layout.addWidget(group)
            self._tool_checkboxes[tool_id] = group  # Сохраняем ссылку на группу-чекбокс
            
        layout.addStretch()
        return w
        
        for tool_id, icon, desc, params in tools_config:
            # Группа для каждого tool
            group = QGroupBox(f"{icon} {tool_id}")
            group.setCheckable(True)
            group.setChecked(False)
            group.toggled.connect(lambda checked, tid=tool_id: self._on_tool_toggled(tid, checked))
            self._tool_configs[tool_id] = {"enabled": False, "params": {}}
            
            form = QFormLayout()
            form.setSpacing(5)
            
            for param_id, (label, default, *rest) in params.items():
                if isinstance(default, bool):
                    widget = QCheckBox()
                    widget.setChecked(default)
                elif isinstance(default, int):
                    widget = QSpinBox()
                    widget.setRange(rest[0], rest[1])
                    widget.setValue(default)
                    widget.setSuffix(" " + label.split("(")[-1].replace(")", ""))
                else:
                    widget = QLineEdit(str(default))
                
                widget.stateChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                    self._update_tool_param(tid, pid, bool(v))) if isinstance(default, bool) else \
                widget.valueChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                    self._update_tool_param(tid, pid, v)) if isinstance(default, int) else \
                widget.textChanged.connect(lambda v, tid=tool_id, pid=param_id: 
                    self._update_tool_param(tid, pid, v))
                
                form.addRow(label, widget)
                self._tool_configs[tool_id]["params"][param_id] = default
            
            group.setLayout(form)
            layout.addWidget(group)
            
        layout.addStretch()
        return w

    def _on_tool_toggled(self, tool_id: str, checked: bool):
        # Обновляем только локальный _tool_configs — per-node сохранение
        # происходит через _on_change в NodePropertiesPanel
        if not hasattr(self, '_tool_configs'):
            self._tool_configs = {}
        if tool_id in self._tool_configs:
            self._tool_configs[tool_id]["enabled"] = checked

    def _update_tool_param(self, tool_id: str, param: str, value):
        if tool_id in self._tool_configs:
            self._tool_configs[tool_id]["params"][param] = value
    
    def _build_execution_tab(self):
        w = QWidget()
        layout = QFormLayout(w)
        
        self._cmb_exec_mode = QComboBox()
        self._cmb_exec_mode.addItem(tr("Последовательно"), "sequential")
        self._cmb_exec_mode.addItem(tr("Параллельно"), "parallel")
        self._cmb_exec_mode.addItem(tr("Условно"), "conditional")
        self._cmb_exec_mode.addItem(tr("LLM Маршрутизатор"), "llm_router")
        layout.addRow("Режим:", self._cmb_exec_mode)
        
        self._spn_timeout = QSpinBox()
        self._spn_timeout.setRange(10, 7200)
        self._spn_timeout.setSuffix(" сек")
        layout.addRow("Таймаут:", self._spn_timeout)
        
        self._chk_breakpoint = QCheckBox(tr("Останавливаться перед выполнением"))
        layout.addRow(self._chk_breakpoint)
        
        self._chk_human_loop = QCheckBox(tr("Ждать подтверждения пользователя"))
        layout.addRow(self._chk_human_loop)

        self._chk_backup_before_node = QCheckBox(tr("Бэкап папки перед ЭТИМ сниппетом"))
        self._chk_backup_before_node.setToolTip(
            "Создаёт копию рабочей папки перед выполнением именно этого агента")
        layout.addRow(self._chk_backup_before_node)

        layout.addWidget(QLabel(""))  # разделитель
        
        self._chk_backup_before_run = QCheckBox(tr("Бэкап папки проекта перед КАЖДЫМ агентом (глобально)"))
        self._chk_backup_before_run.setToolTip(
            "Перед выполнением каждого агента создаёт копию рабочей папки в папке .backups/")
        layout.addRow(self._chk_backup_before_run)

        return w
    
    def _build_automation_tab(self):
        w = QWidget()
        layout = QFormLayout(w)
        
        self._chk_auto_test = QCheckBox(tr("Автотестирование результата"))
        layout.addRow(self._chk_auto_test)
        
        self._chk_auto_patch = QCheckBox(tr("Автопатчинг при ошибках"))
        layout.addRow(self._chk_auto_patch)
        
        self._chk_auto_improve = QCheckBox(tr("Самоулучшение промптов"))
        layout.addRow(self._chk_auto_improve)
        
        self._spn_max_iter = QSpinBox()
        self._spn_max_iter.setRange(1, 10)
        layout.addRow("Макс. итераций:", self._spn_max_iter)
        
        self._chk_self_modify = QCheckBox(tr("Разрешить самомодификацию"))
        layout.addRow(self._chk_self_modify)
        
        return w
    
    def _build_lists_tables_inline_panel(self) -> QWidget:
        """Компактная раскрывающаяся панель списков/таблиц над debug-баром."""
        panel = QFrame()
        panel.setObjectName("ltInlinePanel")
        panel.setStyleSheet(f"""
            QFrame#ltInlinePanel {{
                background: {get_color('bg1')};
                border-top: 1px solid {get_color('bd')};
            }}
        """)
        self._lt_inline_panel = panel
        self._lt_inline_expanded = False

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Заголовок-тоггл ──────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(26)
        header.setStyleSheet(f"border-bottom: 1px solid {get_color('bd2')};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(6, 0, 6, 0)
        h_lay.setSpacing(6)

        self._btn_lt_toggle = QPushButton("📋 Списки / Таблицы  ▼")
        self._btn_lt_toggle.setFlat(True)
        self._btn_lt_toggle.setStyleSheet(f"""
            QPushButton {{ color: {get_color('tx1')}; font-size: 11px;
                           background: transparent; text-align: left; border: none; }}
            QPushButton:hover {{ color: {get_color('ac')}; }}
        """)
        self._btn_lt_toggle.clicked.connect(self._toggle_lt_inline_panel)
        h_lay.addWidget(self._btn_lt_toggle)
        h_lay.addStretch()
        
        # ПКМ по заголовку — контекстное меню
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_lt_header_context_menu)

        btn_ql = QPushButton(tr("➕ Список"))
        btn_ql.setFixedHeight(20)
        btn_ql.setStyleSheet(f"""
            QPushButton {{ font-size: 10px; padding: 0 8px; background: transparent;
                          color: {get_color('ok')}; border: 1px solid {get_color('ok')}; border-radius: 3px; }}
            QPushButton:hover {{ background: {get_color('ok')}; color: #000; }}
        """)
        btn_ql.clicked.connect(self._inline_add_list)

        btn_qt = QPushButton(tr("➕ Таблица"))
        btn_qt.setFixedHeight(20)
        btn_qt.setStyleSheet(f"""
            QPushButton {{ font-size: 10px; padding: 0 8px; background: {get_color('bg2')};
                          color: {get_color('ac')}; border: 1px solid {get_color('ac')}; border-radius: 3px; }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
        """)
        btn_qt.clicked.connect(self._inline_add_table)

        btn_qdb = QPushButton(tr("➕ База данных"))
        btn_qdb.setFixedHeight(20)
        btn_qdb.setStyleSheet(f"""
            QPushButton {{ font-size: 10px; padding: 0 8px; background: {get_color('bg2')};
                          color: #BB9AF7; border: 1px solid #BB9AF7; border-radius: 3px; }}
            QPushButton:hover {{ background: #BB9AF7; color: #000; }}
        """)
        btn_qdb.clicked.connect(self._inline_add_database)

        btn_qinput = QPushButton(tr("➕ Настройки"))
        btn_qinput.setFixedHeight(20)
        btn_qinput.setStyleSheet(f"""
            QPushButton {{ font-size: 10px; padding: 0 8px; background: {get_color('bg2')};
                          color: {get_color('warn')}; border: 1px solid {get_color('warn')}; border-radius: 3px; }}
            QPushButton:hover {{ background: {get_color('warn')}; color: #000; }}
        """)
        btn_qinput.clicked.connect(self._inline_add_input_settings)

        h_lay.addWidget(btn_ql)
        h_lay.addWidget(btn_qt)
        h_lay.addWidget(btn_qdb)
        h_lay.addWidget(btn_qinput)
        outer.addWidget(header)

        # ── Раскрывающийся контент ────────────────────────────────
        self._lt_content_widget = QWidget()
        self._lt_content_widget.setAutoFillBackground(False)
        self._lt_content_widget.setVisible(False)
        self._lt_content_widget.setMinimumHeight(70)
        self._lt_content_widget.setMaximumHeight(350)

        c_lay = QHBoxLayout(self._lt_content_widget)
        c_lay.setContentsMargins(6, 4, 6, 4)
        c_lay.setSpacing(8)

        # Прокручиваемая зона списков
        from PyQt6.QtWidgets import QScrollArea
        sa_lists = QScrollArea()
        sa_lists.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_lists.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_lists.setWidgetResizable(True)
        sa_lists.setMinimumHeight(58)
        sa_lists.setMaximumHeight(320)
        sa_lists.setStyleSheet(f"QScrollArea {{ border: 1px solid {get_color('ok')}; border-radius: 4px; }}")

        lists_inner = QWidget()
        self._lt_lists_area = QHBoxLayout(lists_inner)
        self._lt_lists_area.setContentsMargins(4, 2, 4, 2)
        self._lt_lists_area.setSpacing(4)
        sa_lists.setWidget(lists_inner)
        sa_lists.viewport().setAutoFillBackground(False)
        lists_inner.setAutoFillBackground(False)
        sa_lists.viewport().setStyleSheet("background: transparent;")
        # ПКМ по пустому месту в зоне списков
        lists_inner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lists_inner.customContextMenuRequested.connect(
            lambda pos: self._show_lt_empty_context_menu('list', pos)
        )

        # Прокручиваемая зона таблиц
        sa_tables = QScrollArea()
        sa_tables.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_tables.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_tables.setWidgetResizable(True)
        sa_tables.setMinimumHeight(58)
        sa_tables.setMaximumHeight(320)
        sa_tables.setStyleSheet(f"QScrollArea {{ border: 1px solid {get_color('ac')}; border-radius: 4px; }}")

        tables_inner = QWidget()
        self._lt_tables_area = QHBoxLayout(tables_inner)
        self._lt_tables_area.setContentsMargins(4, 2, 4, 2)
        self._lt_tables_area.setSpacing(4)
        sa_tables.setWidget(tables_inner)
        sa_tables.viewport().setAutoFillBackground(False)
        tables_inner.setAutoFillBackground(False)
        sa_tables.viewport().setStyleSheet("background: transparent;")
        # ПКМ по пустому месту в зоне таблиц
        tables_inner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tables_inner.customContextMenuRequested.connect(
            lambda pos: self._show_lt_empty_context_menu('table', pos)
        )

        lbl_l = QLabel("📃")
        lbl_l.setStyleSheet("color: #9ECE6A; font-size: 14px;")
        lbl_t = QLabel("📊")
        lbl_t.setStyleSheet("color: #7AA2F7; font-size: 14px;")

        c_lay.addWidget(lbl_l)
        c_lay.addWidget(sa_lists, 1)
        c_lay.addWidget(lbl_t)
        c_lay.addWidget(sa_tables, 1)

        # ── Зона настроек и БД ──
        lbl_s = QLabel("⚙️")
        lbl_s.setStyleSheet("color: #e0af68; font-size: 14px;")
        from PyQt6.QtWidgets import QScrollArea as _QSA
        sa_settings = _QSA()
        sa_settings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_settings.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa_settings.setWidgetResizable(True)
        sa_settings.setMinimumHeight(58)
        sa_settings.setMaximumHeight(320)
        sa_settings.setStyleSheet("QScrollArea { border: 1px solid #e0af68; border-radius: 4px; }")
        settings_inner = QWidget()
        self._lt_settings_area = QHBoxLayout(settings_inner)
        self._lt_settings_area.setContentsMargins(4, 2, 4, 2)
        self._lt_settings_area.setSpacing(4)
        sa_settings.setWidget(settings_inner)
        sa_settings.viewport().setAutoFillBackground(False)
        settings_inner.setAutoFillBackground(False)
        sa_settings.viewport().setStyleSheet("background: transparent;")
        c_lay.addWidget(lbl_s)
        c_lay.addWidget(sa_settings, 1)

        outer.addWidget(self._lt_content_widget)

        return panel

    def _toggle_lt_inline_panel(self):
        self._lt_inline_expanded = not self._lt_inline_expanded
        self._lt_content_widget.setVisible(self._lt_inline_expanded)
        self._btn_lt_toggle.setText(
            "📋 Списки / Таблицы  ▲" if self._lt_inline_expanded
            else "📋 Списки / Таблицы  ▼"
        )
        if self._lt_inline_expanded:
            self._refresh_lt_inline_chips()
    
    def _show_lt_header_context_menu(self, pos):
        """Контекстное меню при ПКМ по заголовку панели списков/таблиц."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        
        # Добавление
        act_add_list = menu.addAction(f"📃  {tr('Добавить список')}")
        act_add_list.triggered.connect(self._inline_add_list)
        
        act_add_table = menu.addAction(f"📊  {tr('Добавить таблицу')}")
        act_add_table.triggered.connect(self._inline_add_table)

        act_add_db = menu.addAction(f"🗄  {tr('Добавить базу данных')}")
        act_add_db.triggered.connect(self._inline_add_database)

        act_add_input = menu.addAction(f"⚙️  {tr('Входные настройки / BotUI')}")
        act_add_input.triggered.connect(self._inline_add_input_settings)
        
        menu.addSeparator()
        
        # Переключение видимости
        if self._lt_inline_expanded:
            act_toggle = menu.addAction(f"▲  {tr('Свернуть панель')}")
        else:
            act_toggle = menu.addAction(f"▼  {tr('Развернуть панель')}")
        act_toggle.triggered.connect(self._toggle_lt_inline_panel)
        
        menu.addSeparator()
        
        # Импорт/экспорт всех
        act_import_all = menu.addAction(f"📥  {tr('Импортировать из файла...')}")
        act_import_all.triggered.connect(self._import_lists_tables_from_file)
        
        act_export_all = menu.addAction(f"📤  {tr('Экспортировать в файл...')}")
        act_export_all.triggered.connect(self._export_lists_tables_to_file)
        
        menu.addSeparator()
        
        # Очистка
        act_clear_lists = menu.addAction(f"🗑️  {tr('Очистить все списки')}")
        act_clear_lists.triggered.connect(self._clear_all_lists)
        
        act_clear_tables = menu.addAction(f"🗑️  {tr('Очистить все таблицы')}")
        act_clear_tables.triggered.connect(self._clear_all_tables)
        
        menu.exec(self._lt_inline_panel.mapToGlobal(pos))
    
    def _import_lists_tables_from_file(self):
        """Импорт списков и таблиц из JSON/CSV файла."""
        from PyQt6.QtWidgets import QFileDialog
        start_dir = self._project_root or ""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Импорт списков и таблиц"), start_dir,
            "JSON (*.json);;CSV (*.csv);;All Files (*)"
        )
        if not path or not hasattr(self, '_vars_panel'):
            return
        
        try:
            if path.endswith('.json'):
                import json
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if 'lists' in data:
                    self._vars_panel._project_lists.extend(data['lists'])
                if 'tables' in data:
                    self._vars_panel._project_tables.extend(data['tables'])
            else:
                # CSV — импортируем как список
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                list_name = path.split('/')[-1].split('\\')[-1].replace('.csv', '')
                self._vars_panel._project_lists.append({
                    'id': str(uuid.uuid4())[:8],
                    'name': list_name,
                    'items': ['|'.join(row) for row in rows],
                    'load_mode': 'static',
                    'file_path': ''
                })
            
            self._vars_panel._save_lists_tables_to_workflow()
            self._vars_panel._refresh_lists_widget()
            self._vars_panel._refresh_tables_widget()
            if self._lt_inline_expanded:
                self._refresh_lt_inline_chips()
            self._log_msg(f"📥 Импортировано из {path}")
        except Exception as e:
            QMessageBox.warning(self, tr("Ошибка импорта"), str(e))

    def _export_lists_tables_to_file(self):
        """Экспорт всех списков и таблиц в JSON файл."""
        from PyQt6.QtWidgets import QFileDialog
        start_dir = self._project_root or ""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Экспорт списков и таблиц"), 
            os.path.join(start_dir, "lists_tables.json"),
            "JSON (*.json)"
        )
        if not path or not hasattr(self, '_vars_panel'):
            return
        
        try:
            import json
            data = {
                'lists': self._vars_panel._project_lists,
                'tables': self._vars_panel._project_tables
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log_msg(f"📤 Экспортировано в {path}")
        except Exception as e:
            QMessageBox.warning(self, tr("Ошибка экспорта"), str(e))

    def _clear_all_lists(self):
        """Очистить все списки проекта."""
        from PyQt6.QtWidgets import QMessageBox
        if not getattr(self._vars_panel, '_project_lists', []):
            return
        reply = QMessageBox.question(
            self, tr("Очистка списков"),
            tr("Удалить все списки ({count} шт.)?").format(count=len(self._vars_panel._project_lists)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vars_panel._project_lists.clear()
            self._vars_panel._save_lists_tables_to_workflow()
            self._vars_panel._refresh_lists_widget()
            if self._lt_inline_expanded:
                self._refresh_lt_inline_chips()
            self._log_msg("🗑️ Все списки удалены")

    def _clear_all_tables(self):
        """Очистить все таблицы проекта."""
        from PyQt6.QtWidgets import QMessageBox
        if not getattr(self._vars_panel, '_project_tables', []):
            return
        reply = QMessageBox.question(
            self, tr("Очистка таблиц"),
            tr("Удалить все таблицы ({count} шт.)?").format(count=len(self._vars_panel._project_tables)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vars_panel._project_tables.clear()
            self._vars_panel._save_lists_tables_to_workflow()
            self._vars_panel._refresh_tables_widget()
            if self._lt_inline_expanded:
                self._refresh_lt_inline_chips()
            self._log_msg("🗑️ Все таблицы удалены")
    
    def _show_lt_empty_context_menu(self, zone_type: str, pos):
        """Контекстное меню при ПКМ по пустому месту в зоне списков или таблиц."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        
        if zone_type == 'list':
            act_add = menu.addAction(f"➕  {tr('Добавить список')}")
            act_add.triggered.connect(self._inline_add_list)
            
            if getattr(self._vars_panel, '_project_lists', []):
                menu.addSeparator()
                act_import = menu.addAction(f"📥  {tr('Импорт из файла...')}")
                act_import.triggered.connect(self._import_lists_tables_from_file)
                
                act_clear = menu.addAction(f"🗑️  {tr('Очистить все списки')}")
                act_clear.triggered.connect(self._clear_all_lists)
        else:
            act_add = menu.addAction(f"➕  {tr('Добавить таблицу')}")
            act_add.triggered.connect(self._inline_add_table)
            
            if getattr(self._vars_panel, '_project_tables', []):
                menu.addSeparator()
                act_import = menu.addAction(f"📥  {tr('Импорт из файла...')}")
                act_import.triggered.connect(self._import_lists_tables_from_file)
                
                act_clear = menu.addAction(f"🗑️  {tr('Очистить все таблицы')}")
                act_clear.triggered.connect(self._clear_all_tables)
        
        menu.exec(QCursor.pos())
    
    def _refresh_lt_inline_chips(self):
        """Перестроить чипы списков/таблиц в inline-панели."""
        if not hasattr(self, '_lt_lists_area') or not hasattr(self, '_vars_panel'):
            return

        def _clear(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        _clear(self._lt_lists_area)
        _clear(self._lt_tables_area)

        mode_icon = {'static': '📝', 'on_start': '🔄', 'always': '♻️'}

        # ── Списки ────────────────────────────────────────────────
        for lst in getattr(self._vars_panel, '_project_lists', []):
            cnt = len(lst.get('items', []))
            icon = mode_icon.get(lst.get('load_mode', 'static'), '📝')
            chip = QPushButton(f"{icon} {lst['name']}  [{cnt}]")
            chip.setFixedHeight(30)
            chip.setToolTip(
                f"Список: {lst['name']}\n"
                f"Строк: {cnt} | Режим: {lst.get('load_mode','static')}\n"
                f"Файл: {lst.get('file_path','—') or '—'}\n\n"
                "Клик — открыть редактор"
            )
            chip.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: #9ECE6A; border: 1px solid #9ECE6A;
                              border-radius: 12px; padding: 0 12px; font-size: 11px; }}
                QPushButton:hover {{ background: #9ECE6A; color: #000; }}
            """)
            chip.clicked.connect(lambda _, l=lst: self._inline_edit_list(l))
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(
                lambda pos, l=lst, btn=chip: self._show_list_context_menu(l, btn, pos)
            )
            self._lt_lists_area.addWidget(chip)

        if not getattr(self._vars_panel, '_project_lists', []):
            lbl = QLabel(tr("(нет списков — нажмите ➕ Список)"))
            lbl.setStyleSheet("color: #565f89; font-size: 10px; padding: 4px;")
            self._lt_lists_area.addWidget(lbl)
        self._lt_lists_area.addStretch()

        # ── Таблицы ────────────────────────────────────────────────
        for tbl in getattr(self._vars_panel, '_project_tables', []):
            rows = len(tbl.get('rows', []))
            cols = len(tbl.get('columns', []))
            icon = mode_icon.get(tbl.get('load_mode', 'static'), '📝')
            chip = QPushButton(f"{icon} {tbl['name']}  [{rows}×{cols}]")
            chip.setFixedHeight(30)
            chip.setToolTip(
                f"Таблица: {tbl['name']}\n"
                f"Строк: {rows} | Колонок: {cols} | Режим: {tbl.get('load_mode','static')}\n"
                f"Файл: {tbl.get('file_path','—') or '—'}\n\n"
                "Клик — открыть редактор"
            )
            chip.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: #7AA2F7; border: 1px solid #7AA2F7;
                              border-radius: 12px; padding: 0 12px; font-size: 11px; }}
                QPushButton:hover {{ background: #7AA2F7; color: #000; }}
            """)
            chip.clicked.connect(lambda _, t=tbl: self._inline_edit_table(t))
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(
                lambda pos, t=tbl, btn=chip: self._show_table_context_menu(t, btn, pos)
            )
            self._lt_tables_area.addWidget(chip)

        if not getattr(self._vars_panel, '_project_tables', []):
            lbl = QLabel(tr("(нет таблиц — нажмите ➕ Таблица)"))
            lbl.setStyleSheet("color: #565f89; font-size: 10px; padding: 4px;")
            self._lt_tables_area.addWidget(lbl)
        self._lt_tables_area.addStretch()

        # ── Настройки / БД ──
        if hasattr(self, '_lt_settings_area'):
            _clear(self._lt_settings_area)
            for inp in getattr(self._vars_panel, '_project_input_settings', []):
                chip = QPushButton(f"⚙️ {inp.get('name', '?')}")
                chip.setFixedHeight(30)
                chip.setStyleSheet(
                    "QPushButton { background: transparent; color: #e0af68; border: 1px solid #e0af68;"
                    " border-radius: 12px; padding: 0 12px; font-size: 11px; }"
                    "QPushButton:hover { background: #e0af68; color: #000; }")
                chip.clicked.connect(lambda checked=False, s=inp: self._inline_edit_settings(s))
                chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                chip.customContextMenuRequested.connect(
                    lambda pos, s=inp, btn=chip: self._show_settings_context_menu(s, btn, pos))
                self._lt_settings_area.addWidget(chip)
            for db in getattr(self._vars_panel, '_project_databases', []):
                chip = QPushButton(f"🗄 {db.get('name', '?')}")
                chip.setFixedHeight(30)
                chip.setStyleSheet(
                    "QPushButton { background: transparent; color: #bb9af7; border: 1px solid #bb9af7;"
                    " border-radius: 12px; padding: 0 12px; font-size: 11px; }"
                    "QPushButton:hover { background: #bb9af7; color: #000; }")
                chip.clicked.connect(lambda checked=False, d=db: self._inline_edit_database(d))
                chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                chip.customContextMenuRequested.connect(
                    lambda pos, d=db, btn=chip: self._show_db_context_menu(d, btn, pos))
                self._lt_settings_area.addWidget(chip)
            if (not getattr(self._vars_panel, '_project_input_settings', [])
                    and not getattr(self._vars_panel, '_project_databases', [])):
                lbl = QLabel(tr("(нет настроек / БД)"))
                lbl.setStyleSheet("color: #565f89; font-size: 10px; padding: 4px;")
                self._lt_settings_area.addWidget(lbl)
            self._lt_settings_area.addStretch()

    def _inline_add_list(self):
        if hasattr(self, '_vars_panel'):
            self._vars_panel._add_project_list()
            if self._lt_inline_expanded:
                self._refresh_lt_inline_chips()

    def _inline_add_table(self):
        if hasattr(self, '_vars_panel'):
            self._vars_panel._add_project_table()
            if self._lt_inline_expanded:
                self._refresh_lt_inline_chips()
    
    def _inline_add_database(self):
        """Добавить подключение к базе данных в проект."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                      QLineEdit, QComboBox, QSpinBox,
                                      QPushButton, QHBoxLayout, QLabel,
                                      QCheckBox, QDialogButtonBox)
        dlg = QDialog(self)
        _apply_dialog_theme(dlg)
        dlg.setWindowTitle("🗄 Подключение к базе данных")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        form = QFormLayout()

        cmb_type = QComboBox()
        for label, val in [("SQLite (локально)", "sqlite"), ("PostgreSQL", "postgresql"),
                            ("MySQL / MariaDB", "mysql"), ("MongoDB", "mongodb"),
                            ("Redis", "redis"), ("MS SQL Server", "mssql")]:
            cmb_type.addItem(label, val)
        form.addRow("Тип СУБД:", cmb_type)

        fld_name  = QLineEdit(); fld_name.setPlaceholderText("Имя подключения (для ссылок)")
        fld_host  = QLineEdit(); fld_host.setText("localhost")
        fld_port  = QSpinBox();  fld_port.setRange(1, 65535); fld_port.setValue(5432)
        fld_db    = QLineEdit(); fld_db.setPlaceholderText("Название базы / путь к файлу SQLite")
        fld_user  = QLineEdit(); fld_user.setPlaceholderText("Пользователь")
        fld_pass  = QLineEdit(); fld_pass.setEchoMode(QLineEdit.EchoMode.Password)
        fld_pass.setPlaceholderText("Пароль")
        chk_pool  = QCheckBox("Connection pool"); chk_pool.setChecked(True)
        spn_pool  = QSpinBox(); spn_pool.setRange(1, 100); spn_pool.setValue(5)

        form.addRow("Имя:", fld_name)
        form.addRow("Хост:", fld_host)
        form.addRow("Порт:", fld_port)
        form.addRow("База / файл:", fld_db)
        form.addRow("Пользователь:", fld_user)
        form.addRow("Пароль:", fld_pass)
        form.addRow("Пул соединений:", chk_pool)
        form.addRow("Размер пула:", spn_pool)
        lay.addLayout(form)

        def _update_port(_):
            ports = {"sqlite": 0, "postgresql": 5432, "mysql": 3306,
                     "mongodb": 27017, "redis": 6379, "mssql": 1433}
            v = cmb_type.currentData()
            fld_port.setEnabled(v != "sqlite")
            fld_host.setEnabled(v != "sqlite")
            fld_port.setValue(ports.get(v, 5432))
        cmb_type.currentIndexChanged.connect(_update_port)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = fld_name.text().strip() or f"db_{cmb_type.currentData()}"
            db_config = {
                "name": name, "type": cmb_type.currentData(),
                "host": fld_host.text(), "port": fld_port.value(),
                "database": fld_db.text(), "user": fld_user.text(),
                "password": fld_pass.text(),
                "pool": chk_pool.isChecked(), "pool_size": spn_pool.value()
            }
            if not hasattr(self._vars_panel, '_project_databases'):
                self._vars_panel._project_databases = []
            # Обновляем если уже есть, иначе добавляем
            existing = next((i for i, d in enumerate(self._vars_panel._project_databases)
                             if d.get('name') == name), -1)
            if existing >= 0:
                self._vars_panel._project_databases[existing] = db_config
            else:
                self._vars_panel._project_databases.append(db_config)
            if hasattr(self._vars_panel, '_save_lists_tables_to_workflow'):
                self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _inline_add_input_settings(self):
        """Диалог входных настроек проекта и BotUI."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QWidget,
                                      QFormLayout, QLineEdit, QComboBox, QCheckBox,
                                      QSpinBox, QTextEdit, QPushButton,
                                      QDialogButtonBox, QHBoxLayout, QLabel,
                                      QTableWidget, QTableWidgetItem, QHeaderView)
        dlg = QDialog(self)
        _apply_dialog_theme(dlg)
        dlg.setWindowTitle("⚙️ Входные настройки / BotUI")
        dlg.setMinimumSize(560, 480)
        lay = QVBoxLayout(dlg)

        tabs = QTabWidget()

        # ── Вкладка: Входные настройки ──────────────────────────────
        tab_input = QWidget()
        f_input = QFormLayout(tab_input)

        fld_captcha_service = QComboBox()
        for lbl, val in [("Нет", "none"), ("2captcha", "2captcha"),
                          ("AntiCaptcha", "anticaptcha"), ("CapMonster", "capmonster"),
                          ("RuCaptcha", "rucaptcha")]:
            fld_captcha_service.addItem(lbl, val)
        fld_captcha_key = QLineEdit(); fld_captcha_key.setPlaceholderText("API ключ капча-сервиса")
        fld_threads = QSpinBox(); fld_threads.setRange(1, 500); fld_threads.setValue(1)
        fld_retry = QSpinBox(); fld_retry.setRange(0, 50); fld_retry.setValue(3)
        fld_delay_min = QSpinBox(); fld_delay_min.setRange(0, 60000); fld_delay_min.setValue(500)
        fld_delay_max = QSpinBox(); fld_delay_max.setRange(0, 60000); fld_delay_max.setValue(2000)
        chk_random_ua = QCheckBox("Случайный User-Agent"); chk_random_ua.setChecked(False)
        chk_cookies   = QCheckBox("Сохранять cookies между запусками")
        fld_data_file = QLineEdit(); fld_data_file.setPlaceholderText("Путь к файлу данных / списку аккаунтов")
        fld_result_file = QLineEdit(); fld_result_file.setPlaceholderText("Файл сохранения результатов")
        cmb_result_mode = QComboBox()
        for lbl, val in [("Дописывать", "append"), ("Перезаписывать", "overwrite"), ("Новый файл", "new")]:
            cmb_result_mode.addItem(lbl, val)

        f_input.addRow("Капча-сервис:", fld_captcha_service)
        f_input.addRow("API ключ:", fld_captcha_key)
        f_input.addRow("Потоки:", fld_threads)
        f_input.addRow("Повторов при ошибке:", fld_retry)
        f_input.addRow("Задержка мин. (мс):", fld_delay_min)
        f_input.addRow("Задержка макс. (мс):", fld_delay_max)
        f_input.addRow("", chk_random_ua)
        f_input.addRow("", chk_cookies)
        f_input.addRow("Файл данных:", fld_data_file)
        f_input.addRow("Файл результатов:", fld_result_file)
        f_input.addRow("Режим записи:", cmb_result_mode)
        tabs.addTab(tab_input, "⚙️ Настройки")

        # ── Вкладка: BotUI — параметры интерфейса бота ──────────────
        tab_botui = QWidget()
        v_botui = QVBoxLayout(tab_botui)

        lbl_botui = QLabel(
            "BotUI — параметры, отображаемые пользователю перед запуском проекта.\n"
            "Добавьте поля, которые пользователь должен заполнить."
        )
        lbl_botui.setWordWrap(True)
        lbl_botui.setStyleSheet("color: #7AA2F7; font-size: 11px; padding: 4px;")
        v_botui.addWidget(lbl_botui)

        tbl_botui = QTableWidget(0, 4)
        tbl_botui.setHorizontalHeaderLabels(["Имя поля", "Заголовок", "Тип", "Значение по умолч."])
        tbl_botui.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl_botui.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        v_botui.addWidget(tbl_botui)

        btn_row = QHBoxLayout()
        btn_add_field = QPushButton("➕ Добавить поле")
        btn_del_field = QPushButton("🗑 Удалить")

        def _add_botui_field():
            r = tbl_botui.rowCount()
            tbl_botui.insertRow(r)
            tbl_botui.setItem(r, 0, QTableWidgetItem(f"param_{r+1}"))
            tbl_botui.setItem(r, 1, QTableWidgetItem(f"Параметр {r+1}"))
            cmb = QComboBox()
            for t in ["Текст", "Пароль", "Число", "Флаг", "Файл", "Папка", "Комбо"]:
                cmb.addItem(t)
            tbl_botui.setCellWidget(r, 2, cmb)
            tbl_botui.setItem(r, 3, QTableWidgetItem(""))

        def _del_botui_field():
            rows = sorted({idx.row() for idx in tbl_botui.selectedIndexes()}, reverse=True)
            for r in rows:
                tbl_botui.removeRow(r)

        btn_add_field.clicked.connect(_add_botui_field)
        btn_del_field.clicked.connect(_del_botui_field)
        btn_row.addWidget(btn_add_field)
        btn_row.addWidget(btn_del_field)
        btn_row.addStretch()
        v_botui.addLayout(btn_row)
        tabs.addTab(tab_botui, "🤖 BotUI")

        lay.addWidget(tabs)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Собираем поля BotUI
            bot_fields = []
            for r in range(tbl_botui.rowCount()):
                bot_fields.append({
                    "name":    (tbl_botui.item(r, 0) or QTableWidgetItem("")).text(),
                    "label":   (tbl_botui.item(r, 1) or QTableWidgetItem("")).text(),
                    "type":    tbl_botui.cellWidget(r, 2).currentText() if tbl_botui.cellWidget(r, 2) else "Текст",
                    "default": (tbl_botui.item(r, 3) or QTableWidgetItem("")).text(),
                })
            # Сохраняем настройки в проект
            settings_entry = {
                "name": "⚙️ Настройки проекта",
                "captcha_service":  fld_captcha_service.currentData(),
                "captcha_key":      fld_captcha_key.text(),
                "threads":          fld_threads.value(),
                "retry":            fld_retry.value(),
                "delay_min":        fld_delay_min.value(),
                "delay_max":        fld_delay_max.value(),
                "random_ua":        chk_random_ua.isChecked(),
                "save_cookies":     chk_cookies.isChecked(),
                "data_file":        fld_data_file.text(),
                "result_file":      fld_result_file.text(),
                "result_mode":      cmb_result_mode.currentData(),
                "botui_fields":     bot_fields,
            }
            if not hasattr(self._vars_panel, '_project_input_settings'):
                self._vars_panel._project_input_settings = []
            if self._vars_panel._project_input_settings:
                self._vars_panel._project_input_settings[0] = settings_entry
            else:
                self._vars_panel._project_input_settings.append(settings_entry)
            if hasattr(self._vars_panel, '_save_lists_tables_to_workflow'):
                self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()
    
    def _inline_edit_list(self, lst: dict):
        if not hasattr(self, '_vars_panel'):
            return
        try:
            from constructor.panels import ProjectListEditDialog
        except ImportError:
            from panels import ProjectListEditDialog
        dlg = ProjectListEditDialog(lst, self)
        if dlg.exec():
            new_data = dlg.get_data()
            for i, l in enumerate(self._vars_panel._project_lists):
                if l.get('id') == lst.get('id'):
                    self._vars_panel._project_lists[i] = new_data
                    break
            self._vars_panel._refresh_lists_widget()
            self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _inline_edit_table(self, tbl: dict):
        if not hasattr(self, '_vars_panel'):
            return
        try:
            from constructor.panels import ProjectTableEditDialog
        except ImportError:
            from panels import ProjectTableEditDialog
        dlg = ProjectTableEditDialog(tbl, self)
        if dlg.exec():
            new_data = dlg.get_data()
            for i, t in enumerate(self._vars_panel._project_tables):
                if t.get('id') == tbl.get('id'):
                    self._vars_panel._project_tables[i] = new_data
                    break
            self._vars_panel._refresh_tables_widget()
            self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()
    
    def _show_list_context_menu(self, lst: dict, btn: QPushButton, pos):
        """Контекстное меню для чипа списка."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
            QMenu::item:last-child {{ color: #F7768E; }}
        """)
        
        act_edit = menu.addAction(f"✏️  {tr('Редактировать')}")
        act_edit.triggered.connect(lambda: self._inline_edit_list(lst))
        
        act_rename = menu.addAction(f"🏷️  {tr('Переименовать')}")
        act_rename.triggered.connect(lambda: self._inline_rename_list(lst))
        
        menu.addSeparator()
        
        act_del = menu.addAction(f"🗑️  {tr('Удалить')}")
        act_del.triggered.connect(lambda: self._inline_delete_list(lst))
        
        menu.exec(btn.mapToGlobal(pos))

    def _show_table_context_menu(self, tbl: dict, btn: QPushButton, pos):
        """Контекстное меню для чипа таблицы."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
            QMenu::item:last-child {{ color: #F7768E; }}
        """)
        
        act_edit = menu.addAction(f"✏️  {tr('Редактировать')}")
        act_edit.triggered.connect(lambda: self._inline_edit_table(tbl))
        
        act_rename = menu.addAction(f"🏷️  {tr('Переименовать')}")
        act_rename.triggered.connect(lambda: self._inline_rename_table(tbl))
        
        menu.addSeparator()
        
        act_del = menu.addAction(f"🗑️  {tr('Удалить')}")
        act_del.triggered.connect(lambda: self._inline_delete_table(tbl))
        
        menu.exec(btn.mapToGlobal(pos))

    def _inline_rename_list(self, lst: dict):
        """Быстрое переименование списка через диалог."""
        from PyQt6.QtWidgets import QInputDialog
        old_name = lst.get('name', '')
        new_name, ok = QInputDialog.getText(
            self, tr("Переименовать список"), 
            tr("Новое имя:"), 
            text=old_name
        )
        if ok and new_name.strip() and new_name.strip() != old_name:
            lst['name'] = new_name.strip()
            self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _inline_rename_table(self, tbl: dict):
        """Быстрое переименование таблицы через диалог."""
        from PyQt6.QtWidgets import QInputDialog
        old_name = tbl.get('name', '')
        new_name, ok = QInputDialog.getText(
            self, tr("Переименовать таблицу"), 
            tr("Новое имя:"), 
            text=old_name
        )
        if ok and new_name.strip() and new_name.strip() != old_name:
            tbl['name'] = new_name.strip()
            self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _inline_delete_list(self, lst: dict):
        """Удаление списка из контекстного меню."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, tr("Удаление списка"),
            tr("Удалить список «{name}»?").format(name=lst.get('name', '')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vars_panel._project_lists.remove(lst)
            self._vars_panel._save_lists_tables_to_workflow()
            self._vars_panel._refresh_lists_widget()
            self._refresh_lt_inline_chips()

    def _inline_delete_table(self, tbl: dict):
        """Удаление таблицы из контекстного меню."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, tr("Удаление таблицы"),
            tr("Удалить таблицу «{name}»?").format(name=tbl.get('name', '')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vars_panel._project_tables.remove(tbl)
            self._vars_panel._save_lists_tables_to_workflow()
            self._vars_panel._refresh_tables_widget()
            self._refresh_lt_inline_chips()
    
    def _inline_edit_settings(self, inp: dict):
        """Открыть диалог настроек проекта для редактирования."""
        self._inline_add_input_settings()

    def _inline_edit_database(self, db: dict):
        """Открыть диалог БД для редактирования существующей."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                      QLineEdit, QComboBox, QSpinBox,
                                      QCheckBox, QDialogButtonBox)
        dlg = QDialog(self)
        _apply_dialog_theme(dlg)
        dlg.setWindowTitle(f"🗄 Редактировать: {db.get('name','БД')}")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        form = QFormLayout()

        cmb_type = QComboBox()
        for label, val in [("SQLite (локально)", "sqlite"), ("PostgreSQL", "postgresql"),
                            ("MySQL / MariaDB", "mysql"), ("MongoDB", "mongodb"),
                            ("Redis", "redis"), ("MS SQL Server", "mssql")]:
            cmb_type.addItem(label, val)
        # Восстанавливаем текущие значения
        idx = cmb_type.findData(db.get('type', 'sqlite'))
        if idx >= 0: cmb_type.setCurrentIndex(idx)

        fld_name = QLineEdit(db.get('name', ''))
        fld_host = QLineEdit(db.get('host', 'localhost'))
        fld_port = QSpinBox(); fld_port.setRange(1, 65535); fld_port.setValue(db.get('port', 5432))
        fld_db   = QLineEdit(db.get('database', ''))
        fld_user = QLineEdit(db.get('user', ''))
        fld_pass = QLineEdit(db.get('password', ''))
        fld_pass.setEchoMode(QLineEdit.EchoMode.Password)
        chk_pool = QCheckBox("Connection pool"); chk_pool.setChecked(db.get('pool', True))
        spn_pool = QSpinBox(); spn_pool.setRange(1, 100); spn_pool.setValue(db.get('pool_size', 5))

        form.addRow("Тип СУБД:", cmb_type)
        form.addRow("Имя:", fld_name)
        form.addRow("Хост:", fld_host)
        form.addRow("Порт:", fld_port)
        form.addRow("База / файл:", fld_db)
        form.addRow("Пользователь:", fld_user)
        form.addRow("Пароль:", fld_pass)
        form.addRow("Пул соединений:", chk_pool)
        form.addRow("Размер пула:", spn_pool)
        lay.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            db.update({
                "name": fld_name.text().strip() or db.get('name', 'db'),
                "type": cmb_type.currentData(),
                "host": fld_host.text(), "port": fld_port.value(),
                "database": fld_db.text(), "user": fld_user.text(),
                "password": fld_pass.text(),
                "pool": chk_pool.isChecked(), "pool_size": spn_pool.value()
            })
            if hasattr(self._vars_panel, '_save_lists_tables_to_workflow'):
                self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _show_settings_context_menu(self, inp: dict, btn, pos):
        """Контекстное меню для чипа настроек."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        menu.addAction(tr("✏️  Редактировать")).triggered.connect(
            lambda: self._inline_edit_settings(inp))
        menu.addSeparator()
        act_del = menu.addAction(tr("🗑️  Удалить"))
        act_del.triggered.connect(lambda: self._inline_delete_settings(inp))
        menu.exec(btn.mapToGlobal(pos))

    def _show_db_context_menu(self, db: dict, btn, pos):
        """Контекстное меню для чипа БД."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        menu.addAction(tr("✏️  Редактировать")).triggered.connect(
            lambda: self._inline_edit_database(db))
        menu.addSeparator()
        menu.addAction(tr("🗑️  Удалить")).triggered.connect(
            lambda: self._inline_delete_database(db))
        menu.exec(btn.mapToGlobal(pos))

    def _inline_delete_settings(self, inp: dict):
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Удаление настроек", "Удалить настройки проекта?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            lst = getattr(self._vars_panel, '_project_input_settings', [])
            if inp in lst:
                lst.remove(inp)
            if hasattr(self._vars_panel, '_save_lists_tables_to_workflow'):
                self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()

    def _inline_delete_database(self, db: dict):
        from PyQt6.QtWidgets import QMessageBox
        name = db.get('name', 'БД')
        if QMessageBox.question(self, "Удаление БД",
                f"Удалить подключение «{name}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            lst = getattr(self._vars_panel, '_project_databases', [])
            if db in lst:
                lst.remove(db)
            if hasattr(self._vars_panel, '_save_lists_tables_to_workflow'):
                self._vars_panel._save_lists_tables_to_workflow()
            self._refresh_lt_inline_chips()
    
    def _build_debug_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("debugPanel")
        panel.setMaximumHeight(40)
        panel.setStyleSheet(
            f"QFrame#debugPanel {{ background: {get_color('bg1')}; "
            f"border-top: 1px solid {get_color('bd2')}; }}"
        )
        self._debug_panel = panel

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 4, 8, 4)

        # ═══ КНОПКА "ЗАПУСТИТЬ ВСЕ ПРОЕКТЫ" — выделяющаяся ═══
        self._btn_run_all = QPushButton(tr("⚡⚡ Все проекты"))
        self._btn_run_all.setToolTip(
            tr("Запустить отладку сразу на всех открытых вкладках.\n"
               "ЛКМ — с начала каждого проекта\n"
               "ПКМ — подменю: с начала / от текущего узла")
        )
        self._btn_run_all.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {get_color('bg2')}, stop:1 {get_color('bg1')});
                color: {get_color('ok')};
                border: 2px solid {get_color('ok')};
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
                padding: 0 12px;
                min-width: 130px;
            }}
            QPushButton:hover {{
                background: {get_color('ok')};
                color: #000;
            }}
            QPushButton:pressed {{ background: #6a9e3a; }}
        """)
        self._btn_run_all.clicked.connect(self._debug_run_all_from_start)
        self._btn_run_all.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._btn_run_all.customContextMenuRequested.connect(self._show_run_all_menu)

        self._btn_stop_all_tabs = QPushButton(tr("⛔ Стоп все"))
        self._btn_stop_all_tabs.setToolTip(tr("Остановить выполнение на всех открытых вкладках"))
        self._btn_stop_all_tabs.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {get_color('bg2')}, stop:1 {get_color('bg1')});
                color: {get_color('err')};
                border: 2px solid {get_color('err')};
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
                padding: 0 12px;
                min-width: 100px;
            }}
            QPushButton:hover {{ background: {get_color('err')}; color: #000; }}
            QPushButton:pressed {{ background: #b74a5e; }}
        """)
        self._btn_stop_all_tabs.clicked.connect(self._stop_all_project_tabs)

        self._btn_dbg_start = QPushButton(tr("▶ Старт"))
        self._btn_dbg_start.setToolTip(tr("F5 — Запуск с начала"))
        self._btn_dbg_start.clicked.connect(self._debug_start)

        self._btn_dbg_from_sel = QPushButton(tr("▶| От выбранного"))
        self._btn_dbg_from_sel.setToolTip(tr("F6 — Запуск от выбранного сниппета до конца"))
        self._btn_dbg_from_sel.clicked.connect(self._debug_run_from_selected)

        self._btn_dbg_sel_only = QPushButton(tr("☑ Только выбранные"))
        self._btn_dbg_sel_only.setToolTip(tr("F7 — Выполнить только выделенные сниппеты"))
        self._btn_dbg_sel_only.clicked.connect(self._debug_run_selected_only)

        self._btn_dbg_step_start = QPushButton(tr("⏭ По шагам"))
        self._btn_dbg_step_start.setToolTip(tr("F8 — Запуск в пошаговом режиме (пауза перед каждым)"))
        self._btn_dbg_step_start.clicked.connect(self._debug_start_stepping)

        self._btn_dbg_step = QPushButton(tr("⏭ Шаг (F10)"))
        self._btn_dbg_step.setEnabled(False)
        self._btn_dbg_step.clicked.connect(self._debug_step)

        self._btn_dbg_cont = QPushButton(tr("⏩ Продолжить"))
        self._btn_dbg_cont.setEnabled(False)
        self._btn_dbg_cont.clicked.connect(self._debug_continue)

        self._btn_dbg_stop = QPushButton(tr("⏹ Стоп"))
        self._btn_dbg_stop.setEnabled(False)
        self._btn_dbg_stop.clicked.connect(self._debug_stop)
        
        # ── Кнопка записи действий браузера ──────────────────────────
        self._btn_record = QPushButton(tr("⏺ Запись"))
        self._btn_record.setCheckable(True)
        self._btn_record.setToolTip(
            "Начать запись действий в браузере.\n"
            "Клики, ввод текста, навигация — автоматически создают сниппеты в проекте."
        )
        self._btn_record.setStyleSheet(f"""
            QPushButton {{
                background: {get_color('bg1')}; color: {get_color('err')};
                border: 1px solid {get_color('err')}; border-radius: 4px;
                padding: 4px 12px; font-weight: bold;
            }}
            QPushButton:checked {{
                background: {get_color('err')}; color: #000;
                border: 1px solid {get_color('err')};
            }}
            QPushButton:hover {{ background: {get_color('bg2')}; }}
        """)
        self._btn_record.toggled.connect(self._toggle_browser_recording)
        self._recording_active = False

        self._lbl_dbg_status = QLabel(tr("Готов"))
        self._lbl_dbg_status.setStyleSheet("color: #7AA2F7;")

        # ═══ Галочка: без анимации (отложенная отрисовка) ═══
        self._chk_deferred_render = QCheckBox(tr("Без анимации"))
        self._chk_deferred_render.setToolTip(
            tr("Отключить анимацию выполнения (подсветку нод, centerOn).\n"
               "Ускоряет выполнение, не дёргает канвас.\n"
               "Результат виден в логе и диалоге агентов.")
        )
        self._chk_deferred_render.setStyleSheet(f"QCheckBox {{ color: {get_color('tx1')}; font-size: 11px; }}")
        self._chk_deferred_render.toggled.connect(self._on_deferred_toggled)

        self._chk_close_browser_toolbar = QCheckBox(tr("🌐 Закрывать браузер"))
        self._chk_close_browser_toolbar.setChecked(True)
        self._chk_close_browser_toolbar.setToolTip(
            tr("Закрывать все браузеры проекта автоматически по завершении workflow.\n"
               "Выключите, если нужно оставить браузер открытым после выполнения.")
        )
        self._chk_close_browser_toolbar.setStyleSheet(f"QCheckBox {{ color: {get_color('tx1')}; font-size: 11px; }}")
        self._chk_close_browser_toolbar.stateChanged.connect(self._on_close_browser_changed)
 
        layout.addWidget(self._btn_run_all)
        layout.addWidget(self._btn_stop_all_tabs)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {get_color('bd2')};")
        layout.addWidget(sep)

        layout.addWidget(QLabel(tr("Отладка:")))
        layout.addWidget(self._btn_dbg_start)
        layout.addWidget(self._btn_dbg_from_sel)
        layout.addWidget(self._btn_dbg_sel_only)
        layout.addWidget(self._btn_dbg_step_start)
        layout.addWidget(self._btn_dbg_step)
        layout.addWidget(self._btn_dbg_cont)
        layout.addWidget(self._btn_dbg_stop)
        layout.addWidget(self._chk_deferred_render)
        layout.addWidget(self._chk_close_browser_toolbar)
        layout.addStretch()
        layout.addWidget(self._lbl_dbg_status)
 
        return panel
    
    def _on_deferred_toggled(self, checked: bool):
        """Переключение режима без анимации."""
        tab = self._current_project_tab()
        if tab:
            tab._deferred_rendering = checked
        mode = tr("ВЫКЛ") if checked else tr("ВКЛ")
        self._log_msg(f"{tr('🎬 Анимация выполнения:')} {mode}")

    def _on_close_browser_changed(self, state: int):
        """Синхронизировать настройку закрытия браузера в workflow текущего проекта."""
        tab = self._current_project_tab()
        if tab and tab.workflow:
            tab.workflow.close_browser_on_finish = bool(state)

    def _debug_start(self):
        """Запуск с начала."""
        self._run_workflow()

    def _debug_run_from_selected(self):
        """Запуск от выбранного сниппета до конца."""
        selected = [i for i in self._scene.selectedItems() if isinstance(i, AgentNodeItem)]
        if not selected:
            QMessageBox.information(self, tr("Нет выбора"), tr("Выберите агента, от которого начать выполнение."))
            return
        start_node_id = selected[0].node.id
        self._log_msg(f"{tr('▶| Запуск от:')} {selected[0].node.name}")
        self._run_workflow(start_from_node_id=start_node_id)

    def _debug_run_selected_only(self):
        """Выполнить только выделенные сниппеты (создаем временный workflow)."""
        selected = [i for i in self._scene.selectedItems() if isinstance(i, AgentNodeItem)]
        if not selected:
            QMessageBox.information(self, tr("Нет выбора"), tr("Выделите агентов для выполнения."))
            return
        
        # Сохраняем оригинал
        original_nodes = self._workflow.nodes[:]
        original_edges = self._workflow.edges[:]
        
        try:
            node_ids = {i.node.id for i in selected}
            names = [i.node.name for i in selected]
            
            # Фильтруем workflow
            self._workflow.nodes = [n for n in original_nodes if n.id in node_ids]
            self._workflow.edges = [e for e in original_edges 
                                   if e.source_id in node_ids and e.target_id in node_ids]
            self._scene.set_workflow(self._workflow)
            
            self._log_msg(f"{tr('☑ Только выбранные:')} {', '.join(names)}")
            self._run_workflow()  # Запускаем без параметров, т.к. уже отфильтровали
            
        finally:
            # Восстанавливаем
            self._workflow.nodes = original_nodes
            self._workflow.edges = original_edges
            self._scene.set_workflow(self._workflow)
            self._log_msg(tr("↩️ Восстановлен полный workflow"))

    def _debug_start_stepping(self):
        """Запуск в пошаговом режиме — пауза перед каждым сниппетом."""
        self._log_msg(tr("⏭ Пошаговый режим"))
        self._run_workflow(step_mode=True)

    def _debug_step(self):
        """Выполнить один шаг и снова встать на паузу."""
        if self._runtime_thread and self._runtime_thread.isRunning():
            self._runtime_thread._is_paused = True  # встанет на паузу после выполнения
            self._runtime_thread.resume()

    def _debug_continue(self):
        """Продолжить выполнение до конца (или до следующего breakpoint)."""
        self._continue_runtime()

    def _debug_stop(self):
        """Stop the runtime engine."""
        self._stop_runtime()
        self._btn_dbg_start.setEnabled(True)
        self._btn_dbg_step.setEnabled(False)
        self._btn_dbg_cont.setEnabled(False)
        self._btn_dbg_stop.setEnabled(False)
        self._lbl_dbg_status.setText("Остановлено")
        self._lbl_dbg_status.setStyleSheet("color: #F7768E;")
        self._clear_highlight()
    
    def _debug_run_all_from_start(self):
        """Запустить отладку на всех открытых вкладках — с начала каждого проекта."""
        self._run_all_project_tabs(from_current=False)

    def _show_run_all_menu(self, pos):
        """Подменю для кнопки 'Все проекты'."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {get_color('bg2')}; color: {get_color('tx0')};
                     border: 1px solid {get_color('bd2')}; }}
            QMenu::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        act_start = menu.addAction(tr("⚡ С начала всех проектов"))
        act_start.triggered.connect(lambda: self._run_all_project_tabs(from_current=False))

        act_current = menu.addAction(tr("▶| С текущей позиции каждого проекта"))
        act_current.setToolTip(
            "Каждый проект запустится от того узла, на котором он остановился"
        )
        act_current.triggered.connect(lambda: self._run_all_project_tabs(from_current=True))

        menu.addSeparator()
        act_stop_all = menu.addAction(tr("⏹ Остановить все проекты"))
        act_stop_all.triggered.connect(self._stop_all_project_tabs)

        menu.exec(self._btn_run_all.mapToGlobal(pos))

    def _run_all_project_tabs(self, from_current: bool = False):
        """Запустить workflow на всех вкладках-проектах."""
        count = self._project_tabs.count()
        if count == 0:
            return

        started = 0
        for idx in range(count):
            tab = self._project_tabs.widget(idx)
            if not hasattr(tab, 'workflow') or tab.workflow is None:
                continue
            if tab._runtime_thread and tab._runtime_thread.isRunning():
                self._log_msg(f"{tr('⚠ Проект')} {idx+1} {tr('уже выполняется, пропускаем')}")
                continue

            # Переключаемся на таб для корректного запуска runtime
            prev_idx = self._project_tabs.currentIndex()
            self._project_tabs.setCurrentIndex(idx)

            # Определяем стартовый узел
            start_node_id = None
            if from_current and tab._runtime_thread:
                start_node_id = getattr(tab._runtime_thread, '_current_node_id', None)

            self._run_workflow(start_from_node_id=start_node_id)
            started += 1

            # Возвращаемся на исходный таб
            self._project_tabs.setCurrentIndex(prev_idx)

        mode = tr("от текущей позиции") if from_current else tr("с начала")
        self._log_msg(f"{tr('⚡ Запущено')} {started} {tr('проектов')} ({mode})")
        self._sync_debug_panel_to_tab(self._current_project_tab())

    def _stop_all_project_tabs(self):
        """Остановить выполнение на всех вкладках."""
        for idx in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(idx)
            if hasattr(tab, '_runtime_thread') and tab._runtime_thread and tab._runtime_thread.isRunning():
                tab._runtime_thread.stop()
        self._log_msg(tr("⏹ Все проекты остановлены"))
        self._sync_debug_panel_to_tab(self._current_project_tab())
    
    def _highlight_node(self, node_id: str, state: str):
        # ═══ Пропускаем анимацию если включён deferred rendering ═══
        tab = self._current_project_tab()
        if tab and getattr(tab, '_deferred_rendering', False):
            return
        
        # ═══ ИСПРАВЛЕНИЕ: проверяем что нода принадлежит АКТИВНОЙ сцене ═══
        # Если runtime другого проекта шлёт сигнал — игнорируем
        item = self._scene.get_node_item(node_id)
        if not item:
            return
        if item.scene() is not self._scene:
            return
        
        self._clear_highlight()
        item.setSelected(True)
        item.node._status = state
        item.update()
        self._view.centerOn(item)
    
    def _clear_highlight(self):
        tab = self._current_project_tab()
        deferred = tab and getattr(tab, '_deferred_rendering', False)
        for item in self._scene.items():
            if isinstance(item, AgentNodeItem):
                item.setSelected(False)
                if item.node._status == "running":
                    item.node._status = "idle"
                    if not deferred:
                        item.update()
    
    def _build_palette(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("leftPanel")
        self._left_panel = panel  # Сохраняем ссылку для обновления темы
        panel.setMinimumWidth(200)
        panel.setMaximumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        palette_tabs = QTabWidget()
        self._palette_tabs = palette_tabs
        palette_tabs.setTabPosition(QTabWidget.TabPosition.North)
        # Стили будут применены через _apply_palette_styles()
        
        # Сохраняем ссылки на списки для обновления стилей
        self._palette_widgets = []

        # ── Таб 1: AI Агенты ──
        ai_widget = QWidget()
        ai_layout = QVBoxLayout(ai_widget)
        ai_layout.setContentsMargins(2, 2, 2, 2)
        ai_layout.setSpacing(2)

        lbl = QLabel(tr("🤖 AI АГЕНТЫ"))
        lbl.setObjectName("sectionLabel")
        lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #7AA2F7; padding: 4px;")
        ai_layout.addWidget(lbl)

        self._agent_list = QListWidget()
        self._agent_list.setObjectName("_agent_list")
        self._palette_widgets.append(self._agent_list)
        for at in sorted(AI_AGENT_TYPES, key=lambda x: x.value):
            icon = _AGENT_ICONS.get(at, "🤖")
            # Локализуем только текстовое название агента, исключая иконку из ключа перевода
            translated_name = tr(at.value.replace('_', ' ').title())
            item = QListWidgetItem(f"{icon}  {translated_name}")
            item.setData(Qt.ItemDataRole.UserRole, at)
            self._agent_list.addItem(item)
            
        self._agent_list.itemDoubleClicked.connect(
            lambda item: self._add_agent(item.data(Qt.ItemDataRole.UserRole))
        )
        ai_layout.addWidget(self._agent_list)
        
        # Локализуем название вкладки в интерфейсе
        palette_tabs.addTab(ai_widget, tr("🤖 Агенты"))

        # ── Таб 2: Сниппеты автоматизации (как в ZennoPoster) ──
        snippet_widget = QWidget()
        snippet_layout = QVBoxLayout(snippet_widget)
        snippet_layout.setContentsMargins(2, 2, 2, 2)
        snippet_layout.setSpacing(2)

        lbl2 = QLabel(tr("⚙️ АВТОМАТИЗАЦИЯ"))
        lbl2.setObjectName("sectionLabel")
        lbl2.setStyleSheet("font-weight: bold; font-size: 11px; color: #9ECE6A; padding: 4px;")
        snippet_layout.addWidget(lbl2)

        self._snippet_list = QListWidget()
        self._snippet_list.setObjectName("_snippet_list")
        self._palette_widgets.append(self._snippet_list)
        for at in [AgentType.CODE_SNIPPET, AgentType.IF_CONDITION, AgentType.SWITCH,
                    AgentType.LOOP, AgentType.VARIABLE_SET, AgentType.HTTP_REQUEST,
                    AgentType.DELAY, AgentType.LOG_MESSAGE, AgentType.NOTIFICATION,
                    AgentType.GOOD_END, AgentType.BAD_END, AgentType.JS_SNIPPET,
                    AgentType.PROGRAM_LAUNCH, AgentType.LIST_OPERATION,
                    AgentType.TABLE_OPERATION, AgentType.FILE_OPERATION,
                    AgentType.DIR_OPERATION, AgentType.TEXT_PROCESSING,
                    AgentType.JSON_XML, AgentType.VARIABLE_PROC, AgentType.RANDOM_GEN,
                    AgentType.PROJECT_INFO]:
            icon = _SNIPPET_ICONS.get(at, "📜")
            label = {
                AgentType.CODE_SNIPPET: tr("Code Snippet"),
                AgentType.IF_CONDITION: tr("If Condition"),
                AgentType.SWITCH: tr("Switch"),
                AgentType.LOOP: tr("Loop"),
                AgentType.VARIABLE_SET: tr("Variable Set"),
                AgentType.HTTP_REQUEST: tr("Http Request"),
                AgentType.DELAY: tr("Delay"),
                AgentType.LOG_MESSAGE: tr("Log Message"),
                AgentType.NOTIFICATION: tr("Notification"),
                AgentType.GOOD_END: tr("Good End"),
                AgentType.BAD_END: tr("Bad End"),
                AgentType.JS_SNIPPET: tr("JavaScript"),
                AgentType.PROGRAM_LAUNCH: tr("Запуск программы"),
                AgentType.LIST_OPERATION: tr("Операции со списком"),
                AgentType.TABLE_OPERATION: tr("Операции с таблицей"),
                AgentType.FILE_OPERATION: tr("Файлы"),
                AgentType.DIR_OPERATION: tr("Директории"),
                AgentType.TEXT_PROCESSING: tr("Обработка текста"),
                AgentType.JSON_XML: tr("JSON / XML"),
                AgentType.VARIABLE_PROC: tr("Обработка переменных"),
                AgentType.RANDOM_GEN:  tr("Random (генерация)"),
                AgentType.PROJECT_INFO: tr("🔎 Инфо о проекте"),
            }.get(at, tr(at.value.replace('_', ' ').title()))
            item = QListWidgetItem(f"{icon}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, at)
            self._snippet_list.addItem(item)
        self._snippet_list.itemDoubleClicked.connect(
            lambda item: self._add_agent(item.data(Qt.ItemDataRole.UserRole)))
        snippet_layout.addWidget(self._snippet_list)

        # Кнопка создания заметки
        btn_note = QPushButton(tr("📌 Добавить заметку на канвас"))
        btn_note.setStyleSheet("padding: 6px; font-size: 11px; color: #E0AF68; border: 1px dashed #E0AF68; border-radius: 4px; margin-top: 4px;")
        btn_note.clicked.connect(lambda: self._add_agent(AgentType.NOTE))
        snippet_layout.addWidget(btn_note)

        palette_tabs.addTab(snippet_widget, "⚙️ Сниппеты")

        # ── Таб 3: Скиллы ──
        skill_widget = QWidget()
        skill_layout = QVBoxLayout(skill_widget)
        skill_layout.setContentsMargins(2, 2, 2, 2)

        skill_header = QHBoxLayout()
        skill_header.addWidget(QLabel(tr("🔧 СКИЛЛЫ")))
        btn_add_skill = QPushButton("+")
        btn_add_skill.setFixedWidth(30)
        btn_add_skill.setToolTip(tr("Создать новый скилл"))
        btn_add_skill.clicked.connect(self._add_custom_skill)
        skill_header.addWidget(btn_add_skill)
        skill_layout.addLayout(skill_header)

        self._skill_list = QListWidget()
        self._skill_list.setObjectName("_skill_list")
        self._palette_widgets.append(self._skill_list)
        self._refresh_skill_list()
        self._skill_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._skill_list.customContextMenuRequested.connect(self._show_skill_context_menu)
        self._skill_list.itemDoubleClicked.connect(self._on_skill_double_click)
        skill_layout.addWidget(self._skill_list)
        palette_tabs.addTab(skill_widget, "🔧 Скиллы")

        layout.addWidget(palette_tabs)
        
        # Применяем начальные стили
        self._apply_palette_styles()
        
        layout.addWidget(self._build_browser_palette_section())
        layout.addWidget(self._build_program_palette_section())
        
        return panel
    
    def _build_browser_palette_section(self) -> QWidget:
        """Секция палитры: Браузер."""
        from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton
        from services.agent_models import AgentType

        grp = QGroupBox(tr("🌐 Браузер"))
        self._browser_palette_grp = grp   # ← сохраняем ссылку
        grp.setStyleSheet(f"""
            QGroupBox {{
                color: {get_color('tx0')}; border: 1px solid #43AEFF;
                border-radius: 6px; margin-top: 6px; font-weight: bold;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: #43AEFF; }}
        """)
        lay = QVBoxLayout(grp)
        lay.setSpacing(3)

        items = [
            (AgentType.BROWSER_LAUNCH,      tr("🌐 Запустить браузер")),
            (AgentType.BROWSER_ACTION,      tr("🖱 Действие браузера")),
            (AgentType.BROWSER_CLICK_IMAGE, tr("🖼 Клик по картинке")),
            (AgentType.BROWSER_SCREENSHOT,  tr("📸 Скриншот страницы")),
            (AgentType.BROWSER_CLOSE,       tr("🔴 Закрыть браузер")),
            (AgentType.BROWSER_PROFILE_OP,  tr("🪪 Операции с профилем")),
            (AgentType.PROJECT_INFO,         tr("🔎 Информация о проекте")),
        ]

        self._browser_palette_btns = []   # ← добавляем список для обновления темы
        for atype, label in items:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {get_color('bg2')}; color: {get_color('tx0')};
                    border: 1px solid #43AEFF; border-radius: 4px;
                    padding: 5px; text-align: left;
                }}
                QPushButton:hover {{ background: #43AEFF; color: #000; }}
            """)
            btn.clicked.connect(lambda checked, t=atype: self._add_agent(t))
            lay.addWidget(btn)
            self._browser_palette_btns.append(btn)   # ← сохраняем ссылку

        # Кнопка быстрого запуска
        btn_launch = QPushButton(tr("🚀 Запустить прямо сейчас..."))
        btn_launch.setStyleSheet(f"""
            QPushButton {{
                background: #1a3a5c; color: #43AEFF;
                border: 1px solid #43AEFF; border-radius: 4px;
                padding: 5px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #43AEFF; color: #000; }}
        """)
        btn_launch.clicked.connect(self._quick_launch_browser)
        lay.addWidget(btn_launch)
        self._browser_launch_quick_btn = btn_launch   # ← сохраняем ссылку

        return grp
    
    def _build_program_palette_section(self) -> QWidget:
        """Секция палитры: Автоматизация программ."""
        from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton
        from services.agent_models import AgentType

        grp = QGroupBox(tr("🖥 Программы"))
        self._program_palette_grp = grp   # ← сохраняем ссылку для обновления темы
        grp.setStyleSheet(f"""
            QGroupBox {{
                color: {get_color('tx0')}; border: 1px solid #FF9E64;
                border-radius: 6px; margin-top: 6px; font-weight: bold;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: #FF9E64; }}
        """)
        lay = QVBoxLayout(grp)
        lay.setSpacing(3)

        items = [
            (AgentType.PROGRAM_OPEN,         tr("🖥 Открыть программу")),
            (AgentType.PROGRAM_ACTION,       tr("🎯 Действие в программе")),
            (AgentType.PROGRAM_CLICK_IMAGE,  tr("🖼 Клик по картинке")),
            (AgentType.PROGRAM_SCREENSHOT,   tr("📸 Скриншот программы")),
            (AgentType.PROGRAM_AGENT,        tr("🖥🧠 Program Agent (AI)")),
        ]
        self._program_palette_btns = []
        for atype, label in items:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {get_color('bg2')}; color: {get_color('tx0')};
                    border: 1px solid #FF9E64; border-radius: 4px;
                    padding: 5px; text-align: left;
                }}
                QPushButton:hover {{ background: #FF9E64; color: #000; }}
            """)
            btn.clicked.connect(lambda checked, t=atype: self._add_agent(t))
            lay.addWidget(btn)
            self._program_palette_btns.append(btn)

        return grp

    def _apply_palette_styles(self):
        """Применить текущие цвета темы к палитре"""
        if not hasattr(self, '_palette_tabs'):
            return
            
        # Стили табов
        self._palette_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {get_color('bd2')}; background: {get_color('bg1')}; }}
            QTabBar::tab {{ padding: 4px 8px; font-size: 10px; background: {get_color('bg2')}; color: {get_color('tx1')}; }}
            QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('ac')}; }}
            QTabBar::tab:hover {{ background: {get_color('bg3')}; }}
        """)
        
        # Стили списков
        list_style = f"""
            QListWidget {{ 
                background: {get_color('bg1')}; 
                color: {get_color('tx0')}; 
                border: none; 
            }}
            QListWidget::item {{ 
                padding: 4px 8px; 
                border-bottom: 1px solid {get_color('bg3')};
            }}
            QListWidget::item:selected {{ 
                background: {get_color('bg3')}; 
                color: {get_color('ac')}; 
            }}
            QListWidget::item:hover {{ 
                background: {get_color('bg2')}; 
            }}
        """
        
        for widget in getattr(self, '_palette_widgets', []):
            if widget:
                widget.setStyleSheet(list_style)
        
        # Стили панели
        if hasattr(self, '_left_panel'):
            self._left_panel.setStyleSheet(f"background: {get_color('bg1')};")

        # ── Браузерная секция (GroupBox + кнопки) ─────────────────
        if hasattr(self, '_browser_palette_grp') and self._browser_palette_grp:
            self._browser_palette_grp.setStyleSheet(f"""
                QGroupBox {{
                    color: {get_color('tx0')}; border: 1px solid #43AEFF;
                    border-radius: 6px; margin-top: 6px; font-weight: bold;
                }}
                QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: #43AEFF; }}
            """)
        if hasattr(self, '_browser_palette_btns'):
            _btn_style = f"""
                QPushButton {{
                    background: {get_color('bg2')}; color: {get_color('tx0')};
                    border: 1px solid #43AEFF; border-radius: 4px;
                    padding: 5px; text-align: left;
                }}
                QPushButton:hover {{ background: #43AEFF; color: #000; }}
            """
            for _btn in self._browser_palette_btns:
                if _btn:
                    _btn.setStyleSheet(_btn_style)
        if hasattr(self, '_browser_launch_quick_btn') and self._browser_launch_quick_btn:
            self._browser_launch_quick_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {get_color('bg3')}; color: #43AEFF;
                    border: 1px solid #43AEFF; border-radius: 4px;
                    padding: 5px; font-weight: bold;
                }}
                QPushButton:hover {{ background: #43AEFF; color: #000; }}
            """)
        
        # ── Секция программ (GroupBox + кнопки) ─────────────────
        if hasattr(self, '_program_palette_grp') and self._program_palette_grp:
            self._program_palette_grp.setStyleSheet(f"""
                QGroupBox {{
                    color: {get_color('tx0')}; border: 1px solid #FF9E64;
                    border-radius: 6px; margin-top: 6px; font-weight: bold;
                }}
                QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: #FF9E64; }}
            """)
        if hasattr(self, '_program_palette_btns'):
            _prog_btn_style = f"""
                QPushButton {{
                    background: {get_color('bg2')}; color: {get_color('tx0')};
                    border: 1px solid #FF9E64; border-radius: 4px;
                    padding: 5px; text-align: left;
                }}
                QPushButton:hover {{ background: #FF9E64; color: #000; }}
            """
            for _btn in self._program_palette_btns:
                if _btn:
                    _btn.setStyleSheet(_prog_btn_style)
    
    def _refresh_skill_list(self):
        self._skill_list.clear()
        for skill in self._skill_registry.all_skills():
            # Используем tr() для имени и описания
            translated_name = tr(skill.name)
            item = QListWidgetItem(f"{skill.icon} {translated_name}")
            # Сохраняем оригинал для tooltip
            translated_desc = tr(skill.description)
            translated_cat = tr(skill.category.value)
            item.setToolTip(f"{translated_desc}\n{tr('Категория')}: {translated_cat}")
            item.setData(Qt.ItemDataRole.UserRole, skill.id)
            self._skill_list.addItem(item)
            # Сохраняем оригинальные данные для повторного перевода
            item.setData(Qt.ItemDataRole.UserRole + 1, skill.name)  # оригинальное имя
            item.setData(Qt.ItemDataRole.UserRole + 2, skill.description)
            item.setData(Qt.ItemDataRole.UserRole + 3, skill.category.value)
            item.setToolTip(f"{tr(skill.description)}\n{tr('Категория')}: {tr(skill.category.value)}")
            item.setData(Qt.ItemDataRole.UserRole, skill.id)
            self._skill_list.addItem(item)

    def _show_skill_context_menu(self, position):
        """Контекстное меню для скилла"""
        item = self._skill_list.itemAt(position)
        if not item:
            return
        
        skill_id = item.data(Qt.ItemDataRole.UserRole)
        skill = self._skill_registry.get(skill_id)
        if not skill:
            return
        
        menu = QMenu(self)
        selected = [i for i in self._scene.selectedItems() if isinstance(i, AgentNodeItem)]
        
        if selected:
            act_add = menu.addAction(tr("skill_add_to").format(name=selected[0].node.name))
            act_add.triggered.connect(lambda: self._add_skill_to_node(selected[0].node, skill_id))
            menu.addSeparator()
        
        act_create = menu.addAction(tr("skill_create_agent"))
        act_create.triggered.connect(lambda: self._create_agent_with_skill(skill))
        
        if skill.id not in [s.id for s in BUILTIN_SKILLS]:
            menu.addSeparator()
            act_edit = menu.addAction(tr("✏️ Редактировать скилл"))
            act_edit.triggered.connect(lambda: self._edit_skill(skill))
            act_del = menu.addAction(tr("🗑️ Удалить скилл"))
            act_del.triggered.connect(lambda: self._delete_skill(skill_id))
        
        menu.exec(self._skill_list.mapToGlobal(position))
    
    def _edit_skill(self, skill: Skill):
        from PyQt6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        
        dlg = QDialog(self)
        _apply_dialog_theme(dlg)
        dlg.setWindowTitle(tr("skill_edit_title").format(name=skill.name))
        dlg.setMinimumWidth(400)
        
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        
        name = QLineEdit(skill.name)
        icon = QLineEdit(skill.icon)
        category = QComboBox()
        for cat in SkillCategory:
            category.addItem(cat.value, cat)
            if cat == skill.category:
                category.setCurrentIndex(category.count() - 1)
        
        desc = QTextEdit()
        desc.setPlainText(skill.description)
        desc.setMaximumHeight(80)
        
        prompt = QTextEdit()
        prompt.setPlainText(skill.system_prompt)
        
        form.addRow(tr("skill_name_lbl"), name)
        form.addRow(tr("skill_icon_lbl"), icon)
        form.addRow(tr("skill_category_lbl"), category)
        form.addRow(tr("skill_desc_lbl"), desc)
        form.addRow(tr("skill_prompt_lbl"), prompt)
        layout.addLayout(form)
        
        # Кнопки:
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            skill.name = name.text()
            skill.icon = icon.text()
            skill.category = category.currentData()
            skill.description = desc.toPlainText()
            skill.system_prompt = prompt.toPlainText()
            self._skill_registry.update(skill)
            self._refresh_skill_list()
            self._log_msg(f"✏️ Обновлен скилл: {skill.name}")
    
    def _on_skill_double_click(self, item):
        """Двойной клик - создать агента"""
        skill_id = item.data(Qt.ItemDataRole.UserRole)
        skill = self._skill_registry.get(skill_id)
        if skill:
            # ═══ Проверяем что есть активный таб ═══
            tab = self._current_project_tab()
            if tab is None:
                return
            self._create_agent_with_skill(skill)

    def _add_skill_to_node(self, node: AgentNode, skill_id: str):
        """Добавить скилл к выбранному агенту"""
        if skill_id not in node.skill_ids:
            node.skill_ids.append(skill_id)
            item = self._scene.get_node_item(node.id)
            if item:
                item.update()
            self._props.set_node(node)
            self._log_msg(f"🔧 Скилл добавлен к {node.name}")

    def _create_agent_with_skill(self, skill: Skill):
        """Создать агента с предустановленным скиллом"""
        # ═══ КРИТИЧЕСКИ: используем текущую активную сцену ═══
        tab = self._current_project_tab()
        if tab is None:
            return
        scene = tab.scene
        view = tab.view
        
        view_center = view.mapToScene(view.viewport().rect().center())
        # ...
        # ═══ Используем scene текущего таба ═══
        scene.add_node(node)
        
        tab._history.push(
            lambda: scene.add_node(node),
            lambda: scene.remove_node(node.id),
            f"Агент со скиллом {skill.name}"
        )
        self._log_msg(f"🤖 Создан агент: {skill.name}")
        self._history.push(
            lambda: self._scene.add_node(node),
            lambda: self._scene.remove_node(node.id),
            f"Агент со скиллом {skill.name}"
        )
        self._log_msg(f"🤖 Создан агент: {skill.name}")

    def _add_custom_skill(self):
        """Диалог создания кастомного скилла"""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QTextEdit, QComboBox, QDialogButtonBox
        from services.skill_registry import Skill, SkillCategory
        
        dlg = QDialog(self)
        _apply_dialog_theme(dlg)
        dlg.setWindowTitle(tr("skill_new_title"))
        dlg.setMinimumWidth(400)
        
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        
        name = QLineEdit()
        icon = QLineEdit("🔧")
        category = QComboBox()
        for cat in SkillCategory:
            category.addItem(cat.value, cat)
        desc = QTextEdit()
        desc.setMaximumHeight(80)
        prompt = QTextEdit()
        prompt.setPlaceholderText("Системный промпт...")
        
        form.addRow(tr("skill_name_lbl"), name)
        form.addRow(tr("skill_icon_lbl"), icon)
        form.addRow(tr("skill_category_lbl"), category)
        form.addRow(tr("skill_desc_lbl"), desc)
        form.addRow(tr("skill_prompt_lbl"), prompt)
        layout.addLayout(form)
        
        # Кнопки:
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_ok"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_skill = Skill(
                name=name.text(),
                icon=icon.text(),
                category=category.currentData(),
                description=desc.toPlainText(),
                system_prompt=prompt.toPlainText(),
                tags=["custom"]
            )
            self._skill_registry.add(new_skill)
            self._refresh_skill_list()
            self._log_msg(f"✨ Создан скилл: {new_skill.name}")
    def _delete_skill(self, skill_id: str):
        """Удалить кастомный скилл"""
        from PyQt6.QtWidgets import QMessageBox
        skill = self._skill_registry.get(skill_id)
        if skill and QMessageBox.question(self, "Удаление", f"Удалить '{skill.name}'?") == QMessageBox.StandardButton.Yes:
            self._skill_registry.remove(skill_id)
            self._refresh_skill_list()
            self._log_msg(f"🗑️ Скилл удален: {skill.name}")
    
    def _sync_ui_to_tab(self, tab: ProjectTab):
        """Синхронизировать UI элементы под конкретный таб."""
        # Обновляем workflow
        self._workflow = tab.workflow
        
        # Обновляем сцену и вид
        self._scene = tab.scene
        self._view = tab.view
        
        # Обновляем путь
        self._file_path = getattr(tab, 'project_path', '')
        
        # Обновляем рабочую папку
        if hasattr(tab, '_project_root'):
            self._fld_working_dir.blockSignals(True)
            self._fld_working_dir.setText(tab._project_root)
            self._fld_working_dir.blockSignals(False)
        
        # Обновляем заголовок окна
        self._update_window_title()
        
        # Обновляем статус
        self._update_status()
    
    def _wrap_history_push(self, original_push):
        """Обёртка для HistoryManager.push чтобы отслеживать изменения."""
        def wrapped(execute_fn, undo_fn, description: str = ""):
            result = original_push(execute_fn, undo_fn, description)
            self._is_modified = True
            self._update_window_title()
            
            # ═══ CRITICAL: Устанавливаем флаг и в активном табе ═══
            tab = self._current_project_tab()
            if tab:
                tab._modified = True
                
            return result
        return wrapped
    
    def _update_window_title(self):
        """Обновить заголовок окна с индикатором изменений."""
        title = tr("🤖 Конструктор AI-агентов — AI Code Sherlock")
        if self._is_modified:
            title = "● " + title
        if self._file_path:
            title += f" — {Path(self._file_path).name}"
        self.setWindowTitle(title)
    
    def _mark_saved(self):
        """Отметить что проект сохранён."""
        self._is_modified = False
        self._update_window_title()
        
        # ═══ CRITICAL: Сбрасываем флаг и в активном табе ═══
        tab = self._current_project_tab()
        if tab:
            tab._modified = False
        
        # Удаляем автосохранение для ВСЕХ вкладок при явном сохранении
        for i in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(i)
            if isinstance(tab, ProjectTab):
                apath = getattr(tab, '_autosave_path', None)
                if apath and os.path.exists(apath):
                    try:
                        os.remove(apath)
                    except Exception:
                        pass
                tab._autosave_path = None

    # ═══════════════════════════════════════════════════════
    #  АВТОСОХРАНЕНИЕ И ВОССТАНОВЛЕНИЕ ПОСЛЕ КРАША
    # ═══════════════════════════════════════════════════════

    def _get_autosave_dir(self) -> str:
        """Папка для автосохранений."""
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        d = os.path.join(base, 'AI Code Sherlock', 'autosave')
        os.makedirs(d, exist_ok=True)
        return d

    def _init_autosave(self):
        """Запустить таймер автосохранения и зарегистрировать обработчики краша."""
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start(60_000)  # каждую минуту

        # Безопасный выход — удаляем автосохранения
        atexit.register(self._cleanup_autosave_on_clean_exit)
        atexit.register(self._cleanup_all_browsers_and_processes)

        # Перехватываем SIGTERM (kill) и SIGINT (Ctrl+C)
        try:
            _signal_module.signal(_signal_module.SIGTERM, self._handle_crash_signal)
            _signal_module.signal(_signal_module.SIGINT,  self._handle_crash_signal)
        except (OSError, ValueError):
            pass  # В некоторых потоках нельзя ставить сигналы

        # Обработчик необработанных исключений
        import sys as _sys
        _orig_excepthook = _sys.excepthook
        def _crash_hook(etype, evalue, etb):
            self._do_autosave(is_crash=True)
            _orig_excepthook(etype, evalue, etb)
        _sys.excepthook = _crash_hook

    def _do_autosave(self, is_crash: bool = False):
        """Автосохранить все изменённые вкладки."""
        autosave_dir = self._get_autosave_dir()
        for i in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(i)
            if not isinstance(tab, ProjectTab) or not tab.workflow:
                continue
            is_active = (self._current_project_tab() is tab)
            tab_modified = tab._modified or (is_active and self._is_modified)
            has_content = tab.workflow and (
                len(tab.workflow.nodes) > 0 or len(tab.workflow.edges) > 0
            )
            if not (tab_modified and has_content):
                continue
            try:
                # Имя файла автосохранения
                orig_path = getattr(tab, 'project_path', '') or ''
                if orig_path:
                    import pathlib
                    stem = pathlib.Path(orig_path).stem
                else:
                    stem = tab.workflow.name or f"tab_{i}"
                safe_stem = "".join(c for c in stem if c.isalnum() or c in '-_')[:40]
                apath = os.path.join(autosave_dir, f"{safe_stem}_autosave.workflow.json")

                # Сохраняем workflow в автосохранение
                tab.workflow.save(apath)

                # Записываем метаданные восстановления рядом
                meta = {
                    'original_path': orig_path,
                    'tab_name': self._project_tabs.tabText(i),
                    'autosave_path': apath,
                    'is_crash': is_crash,
                    'timestamp': __import__('datetime').datetime.now().isoformat(),
                }
                meta_path = apath.replace('.workflow.json', '.recovery.json')
                with open(meta_path, 'w', encoding='utf-8') as f:
                    _json_autosave.dump(meta, f, ensure_ascii=False, indent=2)

                tab._autosave_path = apath
            except Exception as e:
                print(f"[autosave] error: {e}")

    def _cleanup_autosave_on_clean_exit(self):
        """При чистом выходе удаляем файлы автосохранения."""
        for i in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(i)
            if not isinstance(tab, ProjectTab):
                continue
            apath = getattr(tab, '_autosave_path', None)
            if apath:
                for p in [apath, apath.replace('.workflow.json', '.recovery.json')]:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
    
    def _cleanup_all_browsers_and_processes(self):
        """Аварийная очистка при любом завершении программы."""
        try:
            for i in range(self._project_tabs.count()):
                tab = self._project_tabs.widget(i)
                if hasattr(tab, 'close_all_browsers'):
                    try:
                        tab.close_all_browsers()
                    except Exception:
                        pass
        except Exception:
            pass
    
    def _handle_crash_signal(self, signum, frame):
        """Обработчик SIGTERM/SIGINT — сохраняемся перед завершением."""
        self._do_autosave(is_crash=True)

    def _check_and_offer_recovery(self):
        """При старте проверить наличие автосохранений и предложить восстановление."""
        autosave_dir = self._get_autosave_dir()
        if not os.path.isdir(autosave_dir):
            return
        recovery_files = [
            f for f in os.listdir(autosave_dir)
            if f.endswith('.recovery.json')
        ]
        if not recovery_files:
            return

        recoveries = []
        for rf in recovery_files:
            try:
                with open(os.path.join(autosave_dir, rf), encoding='utf-8') as f:
                    meta = _json_autosave.load(f)
                apath = meta.get('autosave_path', '')
                if os.path.exists(apath):
                    recoveries.append(meta)
            except Exception:
                pass

        if not recoveries:
            return

        lines = "\n".join(
            f"  • {r.get('tab_name', '?')}  "
            f"({r.get('timestamp', '')[:19].replace('T', ' ')})"
            + ("  [краш]" if r.get('is_crash') else "")
            for r in recoveries
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("🔄 Восстановление проектов")
        msg.setText(
            f"Найдено {len(recoveries)} несохранённых проект(ов):\n\n{lines}"
        )
        msg.setInformativeText("Восстановить проекты из автосохранения?")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        msg.button(QMessageBox.StandardButton.Yes).setText("🔄 Восстановить")
        msg.button(QMessageBox.StandardButton.No).setText("🗑️ Удалить и пропустить")
        reply = msg.exec()

        if reply == QMessageBox.StandardButton.Yes:
            for meta in recoveries:
                apath = meta.get('autosave_path', '')
                orig = meta.get('original_path', '')
                tab_name = meta.get('tab_name', 'Восстановлено')
                try:
                    new_tab = self._add_project_tab(tab_name)
                    self._load_workflow_into_tab(new_tab, apath)
                    # Восстанавливаем оригинальный путь (чтобы Сохранить работало сразу)
                    if orig:
                        new_tab.project_path = orig
                        self._file_path = orig
                    new_tab._modified = True  # помечаем как несохранённый
                    self._is_modified = True
                except Exception as e:
                    print(f"[recovery] error: {e}")

        # Удаляем файлы автосохранения в любом случае
        for meta in recoveries:
            for p in [
                meta.get('autosave_path', ''),
                meta.get('autosave_path', '').replace('.workflow.json', '.recovery.json'),
            ]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    
    def _connect_signals(self):
        self._scene.node_selected.connect(self._on_node_selected)
        self._props.node_changed.connect(self._on_node_changed)
        # Отслеживаем изменения через панель свойств
        self._props.node_changed.connect(self._mark_modified_from_props)
    
    def _mark_modified_from_props(self):
        """Вызывается при любом изменении в правой панели свойств."""
        if not self._is_modified:
            self._is_modified = True
            self._update_window_title()
        
        # ═══ CRITICAL: Устанавливаем флаг и в активном табе ═══
        tab = self._current_project_tab()
        if tab and not tab._modified:
            tab._modified = True

        if hasattr(self, '_scene') and self._scene:
            selected = self._scene.selectedItems()
            if selected:
                item = selected[0]
                
                # 1. Принудительно сохраняем данные из UI в объект ноды
                if hasattr(self, '_props') and hasattr(self._props, '_apply_properties'):
                    self._props.blockSignals(True)
                    self._props._apply_properties()
                    self._props.blockSignals(False)
                
                # 2. Обновляем визуальный размер на сцене
                if hasattr(item, 'update_dynamic_size'):
                    item.update_dynamic_size()
                
                if hasattr(item, 'update_text'):
                    item.update_text()
                item.update()

    # ── Actions ──

    def _add_agent(self, agent_type: AgentType):
        # ═══ КРИТИЧЕСКИ: используем текущую активную сцену, а не self._scene ═══
        tab = self._current_project_tab()
        if tab is None:
            return
        scene = tab.scene
        view = tab.view
        
        view_center = view.mapToScene(view.viewport().rect().center())
        
        # ... создание node (без изменений) ...
        if agent_type == AgentType.NOTE:
            node = AgentNode(
                name="📌 Заметка",
                agent_type=agent_type,
                x=view_center.x() - 100,
                y=view_center.y() - 60,
                width=220,
                height=140,
                color="#E0AF68",
                note_color="#E0AF68",
            )
        else:
            node = AgentNode(
                name=f"{_AGENT_ICONS.get(agent_type, '🤖')} {agent_type.value.replace('_', ' ').title()}",
                agent_type=agent_type,
                x=view_center.x() - 100,
                y=view_center.y() - 60,
                color=_AGENT_COLORS.get(agent_type, "#565f89"),
            )
        _init_extended_attrs(node)
        
        # ═══ Используем scene текущего таба, а не self._scene ═══
        scene.add_node(node)
        
        # ═══ История тоже из текущего таба ═══
        tab._history.push(
            lambda: scene.add_node(node),
            lambda: scene.remove_node(node.id),
            f"Добавление {node.name}"
        )
        self._log_msg(f"{tr('Добавлен агент:')} {node.name}")
        self._update_status()
        
        
    def _connect_selected(self):
        selected = [i for i in self._scene.selectedItems() if isinstance(i, AgentNodeItem)]
        if len(selected) != 2:
            QMessageBox.information(self, tr("Связь"), tr("Выбери ровно 2 агента для соединения."))
            return
        src, tgt = selected[0], selected[1]
        edge = AgentEdge(source_id=src.node.id, target_id=tgt.node.id)
        self._scene.add_edge(edge)
        self._log_msg(f"{tr('Связь:')} {src.node.name} → {tgt.node.name}")

    def _undo(self):
        """Undo последнего действия"""
        desc = self._history.undo()
        if desc:
            self._log_msg(f"↩️ Undo: {desc}")
            self._mark_modified_from_props()
        else:
            self._log_msg(tr("↩️ Нечего отменять"))
    
    def _redo(self):
        """Redo отменённого действия"""
        desc = self._history.redo()
        if desc:
            self._log_msg(f"↪️ Redo: {desc}")
            self._mark_modified_from_props()
        else:
            self._log_msg(tr("↪️ Нечего повторять"))

    def _delete_selected(self):
        # Собираем данные для undo
        nodes_data = []
        edges_data = []
        
        for item in self._scene.selectedItems():
            if isinstance(item, AgentNodeItem):
                nodes_data.append((item.node.id, item.node.to_dict()))
                # Сохраняем связи этого узла
                for edge in self._workflow.edges[:]:
                    if edge.source_id == item.node.id or edge.target_id == item.node.id:
                        edges_data.append((edge.id, edge.to_dict()))
            elif isinstance(item, EdgeItem):
                edges_data.append((item.edge.id, item.edge.to_dict()))
        
        if not nodes_data and not edges_data:
            return
        
        # Выполняем удаление через remove_selected (безопасно, без attach_node в цикле)
        self._scene.remove_selected()

        # Функции для undo/redo
        def undo():
            for node_id, data in nodes_data:
                node = AgentNode.from_dict(data)
                self._workflow.add_node(node)
                self._scene._add_node_item(node)
            # Восстанавливаем attached_children у родителей
            for node_id, data in nodes_data:
                parent_id = data.get('attached_to')
                if parent_id:
                    parent_item = self._scene.get_node_item(parent_id)
                    if parent_item and node_id not in parent_item.node.attached_children:
                        parent_item.node.attached_children.append(node_id)
            # Обновляем шапки блоков
            for item in self._scene._node_items.values():
                if hasattr(item, '_update_block_header'):
                    item._update_block_header()
            for edge_id, data in edges_data:
                edge = AgentEdge.from_dict(data)
                try:
                    self._workflow.add_edge(edge)
                    self._scene._add_edge_item(edge)
                except Exception:
                    pass

        def redo():
            for node_id, _ in nodes_data:
                if self._scene.get_node_item(node_id):
                    self._scene.remove_node(node_id)
        
        self._history.push(redo, undo, f"Удаление {len(nodes_data)} агентов")
        self._update_status()
        self._log_msg(f"{tr('🗑️ Удалено:')} {len(nodes_data)} {tr('агентов')}, {len(edges_data)} {tr('связей')}")

    def _on_node_selected(self, node: AgentNode | None):
        # Сохраняем старую ноду и переключаемся — один вызов set_node
        if self._props._node and self._props._node != node:
            self._props._sync_current_node_to_data()  # сохраняем старую без перестройки
        self._props.set_node(node)
        self._switch_panels_for_node(node)

    def _switch_panels_for_node(self, node: AgentNode | None):
        """Переключить правую панель и левые табы под выбранный тип ноды."""
        if not node:
            return

        cat = get_node_category(node.agent_type)

        # ═══ Правая панель: показать/скрыть табы ═══
        tabs = self._props._tabs
        # Запоминаем текущий таб
        # Показываем все табы для AI, только Базовые для сниппетов, отдельный виджет для заметок
        if cat == 'note':
            # Для заметок — показать только таб "Базовые" (там будет виджет заметки)
            for i in range(tabs.count()):
                tabs.setTabVisible(i, i == 0)  # только первый таб
        elif cat == 'snippet':
            # Для сниппетов — показать только Базовые (там snippet_group)
            for i in range(tabs.count()):
                tabs.setTabVisible(i, i == 0)
        else:
            # AI агент — показать все табы
            for i in range(tabs.count()):
                tabs.setTabVisible(i, True)

        # ═══ Левая панель: переключить таб палитры ═══
        if hasattr(self, '_palette_tabs'):
            if cat == 'ai':
                self._palette_tabs.setCurrentIndex(0)
            elif cat == 'snippet':
                self._palette_tabs.setCurrentIndex(1)
            # note — не переключаем, остаётся как есть

    def _on_node_changed(self):
        self._scene.update()

    # ── File ops ──
    
    def _reset_global_tabs(self):
        """Сброс вкладок Тулзы/Выполнение/Авто к дефолтам при смене проекта."""
        if hasattr(self, '_tool_checkboxes'):
            for chk in self._tool_checkboxes.values():
                chk.blockSignals(True)
                chk.setChecked(False)
                chk.blockSignals(False)
        if hasattr(self, '_cmb_exec_mode'):
            self._cmb_exec_mode.blockSignals(True)
            self._cmb_exec_mode.setCurrentIndex(0)
            self._cmb_exec_mode.blockSignals(False)
        if hasattr(self, '_spn_timeout'):
            self._spn_timeout.blockSignals(True)
            self._spn_timeout.setValue(60)
            self._spn_timeout.blockSignals(False)
        if hasattr(self, '_chk_breakpoint'):
            self._chk_breakpoint.blockSignals(True)
            self._chk_breakpoint.setChecked(False)
            self._chk_breakpoint.blockSignals(False)
        if hasattr(self, '_chk_human_loop'):
            self._chk_human_loop.blockSignals(True)
            self._chk_human_loop.setChecked(False)
            self._chk_human_loop.blockSignals(False)
        if hasattr(self, '_chk_auto_test'):
            self._chk_auto_test.blockSignals(True)
            self._chk_auto_test.setChecked(False)
            self._chk_auto_test.blockSignals(False)
        if hasattr(self, '_chk_auto_patch'):
            self._chk_auto_patch.blockSignals(True)
            self._chk_auto_patch.setChecked(False)
            self._chk_auto_patch.blockSignals(False)
        if hasattr(self, '_chk_auto_improve'):
            self._chk_auto_improve.blockSignals(True)
            self._chk_auto_improve.setChecked(False)
            self._chk_auto_improve.blockSignals(False)
        if hasattr(self, '_spn_max_iter'):
            self._spn_max_iter.blockSignals(True)
            self._spn_max_iter.setValue(1)
            self._spn_max_iter.blockSignals(False)
        if hasattr(self, '_chk_self_modify'):
            self._chk_self_modify.blockSignals(True)
            self._chk_self_modify.setChecked(False)
            self._chk_self_modify.blockSignals(False)
    
    def _new_workflow(self):
        # ═══ КРИТИЧЕСКИ: работаем с текущим табом, а не глобальными ссылками ═══
        tab = self._current_project_tab()
        if tab is None:
            return
        
        self._workflow = AgentWorkflow()
        tab.workflow = self._workflow  # Сохраняем в таб
        tab.scene.set_workflow(self._workflow)  # Привязываем к сцене таба
        self._file_path = ""
        self._is_modified = False  # Новый пустой проект — не "изменён"
        self._update_window_title()
        self._props.set_node(None)
        self._reset_global_tabs()
        self._load_globals_from_workflow()
        if hasattr(self, '_vars_panel'):
            self._vars_panel.set_workflow(self._workflow)
            self._vars_panel.reset_variables_to_defaults()
        # Сохраняем состояние обратно в текущий ProjectTab
        _tab = self._current_project_tab()
        if _tab is not None:
            _tab.workflow = self._workflow
            _tab.project_path = ""
            _tab._modified = False  # ← Один раз здесь
        self._log_msg(tr("Новый проект создан"))
        self._update_status()
        # ── Авто-добавляем START-ноду в пустой проект ──
        _start = AgentNode(
            name=tr("СТАРТ"),
            agent_type=AgentType.PROJECT_START,
            x=60, y=60,
            width=100, height=100,
        )
        tab2 = self._current_project_tab()
        if tab2 and tab2.scene:
            tab2.scene.add_node(_start)
            self._workflow.entry_node_id = _start.id
            QTimer.singleShot(80, self._navigate_to_start)

    def _open_workflow(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Открыть workflow"), "",
            "Workflow (*.workflow.json);;All (*)"
        )
        if not paths:
            return
        # Если выбрано несколько — каждый в новую вкладку
        if len(paths) > 1:
            for p in paths:
                new_tab = self._add_project_tab("…")
                self._load_workflow_into_tab(new_tab, p)
            return
        # Один файл — грузим в текущий таб (прежнее поведение)
        tab = self._current_project_tab()
        if tab is None:
            return
        path = paths[0]
        self._load_workflow_into_tab(tab, path)

    def _load_workflow_into_tab(self, tab, path: str):
        """Загружает workflow из файла в указанный таб."""
        try:
            self._workflow = AgentWorkflow.load(path)
            tab.workflow = self._workflow
            tab.scene.set_workflow(self._workflow)

            # 2. Инициализируем extended-атрибуты на объектах СЦЕНЫ
            for item in tab.scene._node_items.values():
                _init_extended_attrs(item.node)

            # 3. Применяем per-node настройки на объекты СЦЕНЫ (после set_workflow!)
            # Восстанавливаем _loaded_skill_folders из metadata сразу после загрузки
            meta = getattr(self._workflow, 'metadata', {}) or {}
            saved_folders = meta.get('loaded_skill_folders', [])
            if saved_folders:
                self._loaded_skill_folders = saved_folders.copy()

            self._file_path = path
            self._props.set_node(None)

                        # 4. Восстанавливаем рабочую папку из metadata ДО загрузки globals
            meta = getattr(self._workflow, 'metadata', {})
            saved_root = meta.get('project_root', '')
            print(f"[OPEN WF] project_root='{saved_root}', meta keys={list(meta.keys())}")
            if saved_root:
                # Сохраняем ТОЛЬКО в ProjectTab, НЕ в self._project_root
                _tab2 = self._current_project_tab()
                if _tab2 is not None:
                    _tab2._project_root = saved_root
                self._fld_working_dir.blockSignals(True)
                self._fld_working_dir.setText(saved_root)
                self._fld_working_dir.blockSignals(False)
                if os.path.exists(saved_root):
                    self._log_msg(f"📂 Восстановлена рабочая папка: {saved_root}")
                else:
                    self._log_msg(f"📂 Рабочая папка (⚠ не существует): {saved_root}")
            
            if hasattr(self, '_vars_panel'):
                self._vars_panel._workflow = self._workflow
                self._vars_panel._reload_variables()
                self._vars_panel._reload_notes()
                self._vars_panel._load_lists_tables_from_workflow()

            # Сохраняем состояние обратно в текущий ProjectTab
            _tab = self._current_project_tab()
            if _tab is not None:
                _tab.workflow = self._workflow
                _tab.project_path = path
                _tab._modified = False
                _tab.skill_registry = self._skill_registry
                # Обновляем имя вкладки на имя файла
                import os as _os
                tab_name = _os.path.basename(path).replace('.workflow.json', '')
                tab_idx = self._project_tabs.indexOf(_tab)
                if tab_idx >= 0:
                    self._project_tabs.setTabText(tab_idx, tab_name)

            # Автопереход к первому узлу после короткой задержки (чтобы UI успел отрисоваться)
            QTimer.singleShot(100, self._navigate_to_start)

            self._is_modified = False  # Только открыли — не "изменён"
            self._update_window_title()
            self._log_msg(f"{tr('Открыт:')} {path}")
            self._update_status()
            
            # ═══ CRITICAL: Явно сбрасываем флаг таба после загрузки ═══
            tab._modified = False
            if _tab is not None:
                _tab._modified = False
        except Exception as e:
            QMessageBox.critical(self, tr("Ошибка"), str(e))

    def _apply_node_settings_from_file(self, path: str):
        """Прямое чтение per-node настроек из JSON-файла.
        КРИТИЧНО: применяем на объекты СЦЕНЫ (оригиналы),
        а НЕ на workflow.nodes (Pydantic копии!)."""
        import json as _json
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)

            file_meta = data.get('metadata') or {}

            # ── Пропихиваем global_tools/execution/auto в workflow.metadata ──
            if not hasattr(self._workflow, 'metadata'):
                self._workflow.metadata = {}
            for key in ('global_tools', 'global_execution', 'global_auto', 'global_models', 'project_root', 'loaded_skill_folders'):
                if key in file_meta:
                    self._workflow.metadata[key] = file_meta[key]
            # ── Загружаем переменные и заметки из файла ──
            if 'project_variables' in data:
                loaded_vars = data['project_variables']
                # ═══ Сброс value → default при загрузке проекта ═══
                for var_name, var_info in loaded_vars.items():
                    if isinstance(var_info, dict):
                        default_val = var_info.get('default', '')
                        if default_val:
                            # Если default задан — сбрасываем value к нему
                            var_info['value'] = default_val
                self._workflow.project_variables = loaded_vars
            if 'project_notes' in data:
                self._workflow.project_notes = data['project_notes']
                
            ns = file_meta.get('node_settings_by_name', {})
            if not ns:
                print(f"[LOAD] node_settings_by_name не найден в {path}")
                return

            # ── Применяем на объекты СЦЕНЫ — это те же объекты что покажет _populate ──
            applied = 0
            for item in self._scene._node_items.values():
                node = item.node  # оригинальный объект
                cfg = ns.get(str(node.id)) or ns.get(node.name)
                if cfg:
                    node.available_tools    = cfg.get('available_tools', [])
                    node.tool_configs       = cfg.get('tool_configs', {})
                    node.orchestration_mode = cfg.get('orchestration_mode', 'sequential')
                    node.breakpoint_enabled = cfg.get('breakpoint_enabled', False)
                    node.human_in_loop      = cfg.get('human_in_loop', False)
                    node.auto_test          = cfg.get('auto_test', False)
                    node.auto_patch         = cfg.get('auto_patch', False)
                    node.auto_improve       = cfg.get('auto_improve', False)
                    node.max_iterations     = cfg.get('max_iterations', 1)
                    node.self_modify        = cfg.get('self_modify', False)
                    node.backup_before_node = cfg.get('backup_before_node', False)
                    node.comment            = cfg.get('comment', '')  # <-- ДОБАВЛЕНО
                    # КРИТИЧНО: восстанавливаем snippet_config полностью
                    raw_snippet_cfg = cfg.get('snippet_config', {})
                    if isinstance(raw_snippet_cfg, dict):
                        node.snippet_config = raw_snippet_cfg.copy()
                    else:
                        node.snippet_config = {}
                    # Синхронизируем _code и user_prompt_template
                    if '_code' in node.snippet_config and node.snippet_config['_code']:
                        node.user_prompt_template = node.snippet_config['_code']
                    elif cfg.get('user_prompt_template', ''):
                        node.user_prompt_template = cfg.get('user_prompt_template', '')
                        node.snippet_config['_code'] = node.user_prompt_template
                    print(f"[APPLY SETTINGS] {node.name}: snippet_config={list(node.snippet_config.keys())}")
                    node.description        = cfg.get('description', '')
                    node.description        = cfg.get('description', '')
                    applied += 1

            print(f"[LOAD OK] Применено {applied}/{len(ns)} нод (через сцену): "
                f"{[v.get('name', k) for k, v in ns.items() if isinstance(v, dict)]}")
        except Exception as e:
            print(f"[LOAD FAIL] _apply_node_settings_from_file: {e}")
            import traceback; traceback.print_exc()

    def _save_all_snippets_configs(self):
        """Сохранить snippet_config для ВСЕХ нод-сниппетов перед сохранением файла."""
        saved_count = 0
        for item in self._scene._node_items.values():
            node = item.node
            if node.agent_type in SNIPPET_TYPES:
                # Инициализируем snippet_config если нужно
                if not hasattr(node, 'snippet_config') or node.snippet_config is None:
                    node.snippet_config = {}
                
                # Если это текущая выбранная нода — принудительно сохраняем из UI
                if self._props._node == node and hasattr(self, '_snippet_widgets'):
                    self._snippet_loading = False
                    self._flush_snippet_config_to_node()
                    # Дополнительно сохраняем код из редактора
                    if hasattr(self, '_snippet_code_editor') and self._snippet_code_editor:
                        code = self._snippet_code_editor.toPlainText()
                        node.snippet_config['_code'] = code
                        node.user_prompt_template = code
                        print(f"[SAVE ALL] Текущая нода {node.name}: код длины {len(code)}")
                
                # Гарантируем что _code синхронизирован с user_prompt_template
                if '_code' in node.snippet_config and node.snippet_config['_code']:
                    node.user_prompt_template = node.snippet_config['_code']
                elif node.user_prompt_template:
                    node.snippet_config['_code'] = node.user_prompt_template
                
                saved_count += 1
                print(f"[SAVE ALL] {node.name}: snippet_config={list(node.snippet_config.keys())}")
        
        print(f"[SAVE ALL] Всего сохранено сниппетов: {saved_count}")

    def _save_workflow(self):
        if not self._file_path:
            self._save_as_workflow()
            return
        try:
            # ═══ КРИТИЧНО: Сохранить snippet_config ВСЕХ нод-сниппетов ═══
            self._save_all_snippets_configs()
            
            # Синхронизировать текущую ноду из UI — ТОЛЬКО если нода выбрана
            if self._props._node is not None:
                self._props._sync_current_node()
            # ═══ Проверяем что ВСЕ ноды имеют snippet_config ═══
            for item in self._scene._node_items.values():
                node = item.node
                if not hasattr(node, 'snippet_config'):
                    node.snippet_config = {}
            self._sync_globals_to_workflow()
            for node in self._workflow.nodes:
                _init_extended_attrs(node)
            self._workflow.save(self._file_path)

            # ── ПРЯМАЯ ИНЪЕКЦИЯ: дописываем per-node настройки в JSON ──
            self._inject_node_settings_to_file(self._file_path)

            self._mark_saved()  # Отмечаем как сохранённое
            self._log_msg(f"{tr('Сохранён:')} {self._file_path}")
        except Exception as e:
            QMessageBox.critical(self, tr("Ошибка сохранения"), str(e))

    def _inject_node_settings_to_file(self, path: str):
        """Прямая запись per-node настроек в JSON-файл.
        КРИТИЧНО: читаем из scene._node_items (оригиналы), 
        а НЕ из workflow.nodes (Pydantic возвращает копии!)."""
        import json as _json
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)

            ns = {}
            # ── Читаем из СЦЕНЫ — это те же объекты что редактирует _on_change ──
            for item in self._scene._node_items.values():
                node = item.node  # оригинальный объект, НЕ копия
                # КРИТИЧНО: принудительно получаем snippet_config, создаём если нет
                snip_cfg = getattr(node, 'snippet_config', None)
                if snip_cfg is None:
                    snip_cfg = {}
                # Если есть user_prompt_template но нет _code — синхронизируем
                if '_code' not in snip_cfg and getattr(node, 'user_prompt_template', ''):
                    snip_cfg['_code'] = node.user_prompt_template
                
                ns[str(node.id)] = {
                    'name':               node.name,
                    'available_tools':    getattr(node, 'available_tools', []),
                    'tool_configs':       getattr(node, 'tool_configs', {}),
                    'orchestration_mode': getattr(node, 'orchestration_mode', 'sequential'),
                    'breakpoint_enabled': getattr(node, 'breakpoint_enabled', False),
                    'human_in_loop':      getattr(node, 'human_in_loop', False),
                    'auto_test':          getattr(node, 'auto_test', False),
                    'auto_patch':         getattr(node, 'auto_patch', False),
                    'auto_improve':       getattr(node, 'auto_improve', False),
                    'max_iterations':     getattr(node, 'max_iterations', 1),
                    'self_modify':        getattr(node, 'self_modify', False),
                    'backup_before_node': getattr(node, 'backup_before_node', False),
                    'snippet_config':     snip_cfg,
                    'user_prompt_template': getattr(node, 'user_prompt_template', ''),
                    'description':        getattr(node, 'description', ''),
                    'comment':            getattr(node, 'comment', ''),
                }

            if 'metadata' not in data or not isinstance(data.get('metadata'), dict):
                data['metadata'] = {}
            data['metadata']['node_settings_by_name'] = ns

            # ── Также пишем глобальные настройки вкладок ──
            if hasattr(self._workflow, 'metadata'):
                for key in ('global_tools', 'global_execution', 'global_auto', 'global_models', 'project_root', 'loaded_skill_folders'):
                    if key in self._workflow.metadata:
                        data['metadata'][key] = self._workflow.metadata[key]
            
            # ── Сохраняем переменные и заметки ──
            if hasattr(self._workflow, 'project_variables'):
                data['project_variables'] = self._workflow.project_variables
            if hasattr(self._workflow, 'project_notes'):
                data['project_notes'] = self._workflow.project_notes
            
            with open(path, 'w', encoding='utf-8') as f:
                _json.dump(data, f, indent=4, ensure_ascii=False)

            print(f"[SAVE OK] node_settings_by_name: {list(ns.keys())}, "
                  f"tools пример: {list(ns.values())[0] if ns else 'пусто'}")
        except Exception as e:
            print(f"[SAVE FAIL] _inject_node_settings_to_file: {e}")
            import traceback; traceback.print_exc()

    def _save_as_workflow(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Сохранить workflow"), "",
            "Workflow (*.workflow.json)")
        if not path:
            return
        if not path.endswith(".workflow.json"):
            path += ".workflow.json"
        self._file_path = path
        # Сохраняем путь обратно в текущий ProjectTab
        _tab = self._current_project_tab()
        if _tab is not None:
            _tab.project_path = path
            _tab._modified = False
            # Обновляем имя вкладки
            import os as _os
            tab_name = _os.path.basename(path).replace('.workflow.json', '')
            tab_idx = self._project_tabs.indexOf(_tab)
            if tab_idx >= 0:
                self._project_tabs.setTabText(tab_idx, tab_name)
        self._save_workflow()
        # _save_workflow уже вызывает _mark_saved()

    def _run_workflow(self, start_from_node_id: str = "", only_node_ids: list[str] = None, step_mode: bool = False):
        """Launch the workflow runtime engine."""
        if not self._model_manager or not self._model_manager.active_provider:
            QMessageBox.warning(self, tr("Нет модели"),
                tr("Настройте AI модель в главном окне перед запуском."))
            return
 
        # ═══ Проверяем runtime ТЕКУЩЕЙ вкладки, а не глобальный ═══
        _active_tab = self._current_project_tab()
        if not _active_tab:
            return
        if _active_tab._runtime_thread and _active_tab._runtime_thread.isRunning():
            QMessageBox.information(self, tr("Запуск"), 
                tr(f"Проект «{self._workflow.name}» уже выполняется в этой вкладке."))
            return

        # Collect scene nodes (originals, not Pydantic copies)
        scene_nodes = {}
        for item in self._scene._node_items.values():
            scene_nodes[item.node.id] = item.node

        if not scene_nodes:
            QMessageBox.warning(self, tr("Пусто"), tr("Добавьте хотя бы одного агента."))
            return
        
        # ── Регистрация в менеджере проектов ──────────────
        _active_tab = self._current_project_tab()
        if _active_tab and self._project_exec_manager:
            # Убедимся что проект зарегистрирован
            registered = False
            for p in self._project_exec_manager.get_all_projects():
                if p.tab_reference is _active_tab:
                    registered = True
                    break
            if not registered:
                entry = ProjectEntry(
                    name=self._workflow.name,
                    file_path=getattr(_active_tab, 'project_path', ''),
                    workflow=self._workflow,
                    tab_reference=_active_tab,
                    window_reference=self,
                )
                self._project_exec_manager.add_project(entry)
        
        # Read global settings from UI - СИНХРОНИЗИРУЕМ ПЕРЕД ЧТЕНИЕМ!
        self._sync_globals_to_workflow()  # <-- КЛЮЧЕВОЕ: сохраняем в workflow.metadata
        
        # Теперь читаем из metadata (там актуальные значения)
        meta = getattr(self._workflow, 'metadata', {})
        
        global_tools = meta.get('global_tools', {})
        if not global_tools and hasattr(self, '_tool_checkboxes'):
            global_tools = {t_id: chk.isChecked() for t_id, chk in self._tool_checkboxes.items()}

        global_execution = meta.get('global_execution', {})
        if not global_execution and hasattr(self, '_cmb_exec_mode'):
            global_execution = {
                'orchestration_mode': self._cmb_exec_mode.currentData() or 'sequential',
                'timeout': self._spn_timeout.value(),
                'breakpoint_enabled': self._chk_breakpoint.isChecked(),
                'human_in_loop': self._chk_human_loop.isChecked(),
                'backup_before_run': self._chk_backup_before_run.isChecked()
                    if hasattr(self, '_chk_backup_before_run') else False,
            }

        # Бэкап рабочей папки перед запуском (если галочка стоит)
        if global_execution.get('backup_before_run') and self._project_root:
            self._do_project_backup(self._project_root, label="pre_run")

        global_auto = meta.get('global_auto', {})
        if not global_auto and hasattr(self, '_chk_auto_test'):
            global_auto = {
                'auto_test': self._chk_auto_test.isChecked(),
                'auto_patch': self._chk_auto_patch.isChecked(),
                'auto_improve': self._chk_auto_improve.isChecked(),
                'max_iterations': self._spn_max_iter.value(),
                'self_modify': self._chk_self_modify.isChecked(),
            }
        
        # Логируем что применяем
        self._log_msg(f"[RUN] Execution: {global_execution}")
        self._log_msg(f"[RUN] Auto: {global_auto}")
        
        # === СОХРАНЕНИЕ ПЕРЕМЕННЫХ ПРОЕКТА ДЛЯ RUNTIME ===
        # Подготовка переменных проекта для runtime
        project_vars = {}
        if hasattr(self, '_vars_panel') and self._vars_panel:
            # Получаем переменные из панели в правильном формате
            raw_vars = self._vars_panel.get_variables() if hasattr(self._vars_panel, 'get_variables') else {}
            # Преобразуем в формат {name: {'value': ..., 'type': ...}}
            for name, data in raw_vars.items():
                if isinstance(data, dict):
                    project_vars[name] = {
                        'value': data.get('value', data.get('default', '')),
                        'type': data.get('type', 'string'),
                        'default': data.get('default', '')
                    }
                else:
                    project_vars[name] = {'value': str(data), 'type': 'string'}
            if project_vars:
                self._log_msg(f"[DEBUG] Подготовлены project_vars: {list(project_vars.keys())}")
        else:
            self._log_msg(f"[DEBUG] _vars_panel недоступен")
        
        if project_vars:
            self._log_msg(f"📋 Переменные проекта: {list(project_vars.keys())}")
        
        # ═══ КРИТИЧНО: передаём проектные списки/таблицы из metadata ═══
        _meta = getattr(self._workflow, 'metadata', {}) or {}
        _panel_lists = getattr(getattr(self, '_vars_panel', None), '_project_lists', None)
        _src_lists = _panel_lists if _panel_lists else _meta.get('project_lists', [])
        if _src_lists:
            project_vars['_project_lists'] = _src_lists
            self._log_msg(f"📃 Передано списков: {len(_src_lists)}")

        _panel_tables = getattr(getattr(self, '_vars_panel', None), '_project_tables', None)
        _src_tables = _panel_tables if _panel_tables else _meta.get('project_tables', [])
        if _src_tables:
            project_vars['_project_tables'] = _src_tables
            self._log_msg(f"📊 Передано таблиц: {len(_src_tables)}")
        
        # Create and configure runtime
        rt = WorkflowRuntime(self)
        rt._was_step_mode = step_mode   # ← сохраняем флаг для _on_runtime_finished
        # Подготавливаем детальные настройки tools
        tool_configs = getattr(self, '_tool_configs', {}) if hasattr(self, '_tool_configs') else {}
        
        _active_tab = self._current_project_tab()
        rt.configure(
            workflow=self._workflow,
            scene_nodes=scene_nodes,
            model_manager=self._model_manager,
            skill_registry=self._skill_registry,
            project_root=self._project_root if hasattr(self, '_project_root') else "",
            global_tools=global_tools,
            global_execution=global_execution,
            global_auto=global_auto,
            tool_configs=tool_configs,
            start_from_node_id=start_from_node_id,
            only_node_ids=only_node_ids,
            step_mode=step_mode,
            project_variables=project_vars,
            project_browser_manager=_active_tab.browser_manager if _active_tab else None,
            browser_tray_callback=_active_tab.send_browser_to_tray if _active_tab else None,
        )

        # Connect signals
        rt.signals.log.connect(self._log_msg)
        rt.signals.workflow_started.connect(self._on_runtime_started)
        rt.signals.workflow_finished.connect(self._on_runtime_finished)
        rt.signals.node_started.connect(self._on_runtime_node_started)
        rt.signals.node_finished.connect(self._on_runtime_node_finished)
        rt.signals.node_streaming.connect(self._on_agent_stream)  # Потоковый вывод
        rt.signals.breakpoint_hit.connect(self._on_runtime_breakpoint)
        rt.signals.waiting_input.connect(self._on_runtime_waiting_input)
        rt.signals.error.connect(self._on_runtime_error)
        rt.signals.progress.connect(self._on_runtime_progress)
        rt.signals.variable_updated.connect(self._update_project_variable)
        rt.signals.list_table_updated.connect(self._on_runtime_list_table_updated)

        # Очистка диалога перед запуском — ТОЛЬКО если это текущий активный таб
        if self._current_project_tab() is _active_tab:
            self._agent_chat.clear()
            self._agent_chat.append(f"<b style='color: #7AA2F7;'>🚀 Запуск workflow: {self._workflow.name}</b>")
            self._bottom_tabs.setCurrentIndex(1)  # Переключиться на диалог

        self._runtime_thread = rt  # ← КРИТИЧЕСКИ: без этого кнопки отладки не работают!

        # ── Запуск QThread напрямую из главного потока ────────────────
        # WorkflowRuntime — это QThread, он УЖЕ работает в своём потоке.
        # Оборачивать в threading.Thread НЕЛЬЗЯ — QThread.start() из фонового
        # потока крашит Qt (QThread принадлежит главному потоку).
        # Лимит параллельных проектов проверяем, но не блокируем.
        try:
            pm = ProjectThreadManager.get()
            active = pm.active_count()
            limit = GlobalSettings.get("max_parallel_projects")
            if active >= limit:
                self._log_msg(
                    f"⚠️ Достигнут лимит параллельных проектов ({limit}). "
                    f"Запуск всё равно разрешён (QThread)."
                )
            # Регистрируем в менеджере для учёта (без threading.Thread обёртки)
            project_id = getattr(_active_tab, 'project_id', str(uuid.uuid4())[:8])
            pm._active[project_id] = None  # Маркер что проект запущен
            # При завершении — удаляем маркер
            def _on_rt_done(success, summary, pid=project_id):
                pm._active.pop(pid, None)
                self._log_msg(f"✅ Проект {pid} завершён (QThread)")
            rt.signals.workflow_finished.connect(_on_rt_done)
        except Exception:
            pass
        rt.start()
    
    def _on_agent_stream(self, node_id: str, chunk: str):
        """Отображение потокового вывода от агента"""
        node_name = "Unknown"
        if node_id in self._scene._node_items:
            node_name = self._scene._node_items[node_id].node.name
        
        # HTML-escape для безопасности
        import html
        safe_chunk = html.escape(chunk)
        
        # Добавляем в чат с цветовой маркировкой
        if not hasattr(self, '_current_stream_node') or self._current_stream_node != node_id:
            self._current_stream_node = node_id
            self._agent_chat.append(f"<br><b style='color: #9ECE6A;'>[{node_name}]:</b> ")
        
        self._agent_chat.insertPlainText(chunk)
        
        # Автоскролл
        scrollbar = self._agent_chat.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_runtime_node_started(self, node_id: str, name: str):
        # ═══ ИСПРАВЛЕНИЕ: обновляем UI только если сигнал от ТЕКУЩЕГО таба ═══
        tab = self._current_project_tab()
        sender_rt = self.sender()  # runtime который послал сигнал
        if tab and (tab._runtime_thread is None or tab._runtime_thread.signals is not sender_rt):
            return  # Сигнал от чужого таба — игнорируем
        
        self._highlight_node(node_id, "running")
        self._lbl_dbg_status.setText(f"▶ {name}")
        self._current_stream_node = None
        self._agent_chat.append(f"<br><i style='color: #565f89;'>--- Запуск {name} ---</i>")
    
    # ── Runtime signal handlers ─────────────────────────

    def _on_runtime_started(self):
        # ═══ ИСПРАВЛЕНИЕ: обновляем UI только если сигнал от ТЕКУЩЕГО таба ═══
        sender_rt = self.sender()
        tab = self._current_project_tab()
        if tab and hasattr(tab, '_runtime_thread') and tab._runtime_thread is not None and tab._runtime_thread.signals is not sender_rt:
            return  # Сигнал от другого таба — не трогаем UI текущего

        self._btn_dbg_start.setEnabled(False)
        self._btn_dbg_from_sel.setEnabled(False)
        self._btn_dbg_sel_only.setEnabled(False)
        self._btn_dbg_step_start.setEnabled(False)
        self._btn_dbg_stop.setEnabled(True)
        self._btn_dbg_cont.setEnabled(False)
        self._btn_dbg_step.setEnabled(False)
        self._lbl_dbg_status.setText("▶ Выполняется")
        self._lbl_dbg_status.setStyleSheet("color: #9ECE6A;")

        # Очищаем кэш выполненных команд при каждом новом запуске
        self._executed_cmds = set()
        
        # ═══ Блокируем взаимодействие со сценой во время выполнения ═══
        self._is_executing = True
        if hasattr(self, '_view') and self._view:
            self._view.setEnabled(False)  # Запрещаем drag, клик, редактирование
        if hasattr(self, '_props') and self._props:
            self._props.setEnabled(False)  # Запрещаем редактирование свойств
        if hasattr(self, '_snippet_group') and self._snippet_group:
            self._snippet_group.setEnabled(False)

    def _on_runtime_finished(self, success: bool, summary: str):
        # ═══ ИСПРАВЛЕНИЕ: определяем таб по sender (runtime), а не по текущему табу ═══
        sender_rt = self.sender()
        finished_tab = None
        for i in range(self._project_tabs.count()):
            t = self._project_tabs.widget(i)
            if hasattr(t, '_runtime_thread') and t._runtime_thread is not None and t._runtime_thread.signals is sender_rt:
                finished_tab = t
                break
        
        # Кнопки обновляем ТОЛЬКО если завершившийся таб — текущий
        current_tab = self._current_project_tab()
        if finished_tab is current_tab or finished_tab is None:
            self._btn_dbg_start.setEnabled(True)
            self._btn_dbg_from_sel.setEnabled(True)
            self._btn_dbg_sel_only.setEnabled(True)
            self._btn_dbg_step_start.setEnabled(True)
            self._btn_dbg_step.setEnabled(False)
            self._btn_dbg_stop.setEnabled(False)
            self._btn_dbg_cont.setEnabled(False)
        
        # ═══ Если был deferred mode — показать итоговое состояние нод ═══
        tab = finished_tab or current_tab
        if tab and getattr(tab, '_deferred_rendering', False):
            # Обновляем все ноды чтобы показать итоговый статус
            _target_scene = tab.scene if hasattr(tab, 'scene') else self._scene
            for item_widget in _target_scene.items():
                if isinstance(item_widget, AgentNodeItem):
                    item_widget.update()
        
        # ═══ Разблокируем взаимодействие со сценой ═══
        self._is_executing = False
        if hasattr(self, '_view') and self._view:
            self._view.setEnabled(True)
        if hasattr(self, '_props') and self._props:
            self._props.setEnabled(True)
        if hasattr(self, '_snippet_group') and self._snippet_group:
            self._snippet_group.setEnabled(True)
        
        self._clear_highlight()
        icon = "✅" if success else "❌"
        self._lbl_dbg_status.setText(f"{icon} {summary[:60]}")
        self._lbl_dbg_status.setStyleSheet(f"color: {'#9ECE6A' if success else '#F7768E'};")
        
        # ═══ СИНХРОНИЗАЦИЯ: контекст runtime → переменные проекта + UI ═══
        rt = sender_rt  # Используем runtime завершившегося таба, а не текущего!
        if rt and hasattr(rt, '_context') and hasattr(self, '_vars_panel'):
            ctx = rt._context
            panel = self._vars_panel
            if panel._workflow and hasattr(panel._workflow, 'project_variables'):
                updated = 0
                for var_name, var_info in panel._workflow.project_variables.items():
                    if var_name in ctx:
                        new_val = str(ctx[var_name])
                        old_val = var_info.get('value', '')
                        if new_val != old_val:
                            var_info['value'] = new_val
                            updated += 1
                    
                    # Обработка Random Gen - конвертация в нужный тип
                    if var_name in ctx:
                        raw_val = ctx[var_name]
                        # Конвертация типов как в оригинальной логике
                        var_type = var_info.get('type', 'string')
                        try:
                            if var_type == 'int':
                                new_val = int(raw_val) if raw_val else 0
                            elif var_type == 'float':
                                new_val = float(raw_val) if raw_val else 0.0
                            elif var_type == 'bool':
                                new_val = raw_val.lower() in ('true', '1', 'yes') if isinstance(raw_val, str) else bool(raw_val)
                            else:
                                new_val = str(raw_val)
                            var_info['value'] = str(new_val)
                        except:
                            var_info['value'] = str(raw_val)
                        updated += 1
                
                if updated > 0:
                    # ═══ ПРАВИЛЬНЫЙ ФИКС: обновляем UI без перезагрузки таблицы ═══
                    panel._var_table.blockSignals(True)
                    try:
                        for row in range(panel._var_table.rowCount()):
                            name_item = panel._var_table.item(row, 0)
                            if not name_item:
                                continue
                            var_name = name_item.text().strip()
                            if var_name in panel._workflow.project_variables:
                                new_val = str(panel._workflow.project_variables[var_name].get('value', ''))
                                value_item = panel._var_table.item(row, 1)
                                if value_item:
                                    value_item.setText(new_val)
                    finally:
                        panel._var_table.blockSignals(False)
                    
                    panel._var_table.viewport().update()
                    self._log_msg(f"🔄 Синхронизировано {updated} переменных из runtime в проект")
                    # Также обновляем сцену чтобы ноды увидели новые значения
                    self._scene.update()
                    self._log_msg(f"🔄 Синхронизировано {updated} переменных из runtime в проект")
                    
                    # ═══ ФИКС: если обновление не сработало - перезагружаем всю таблицу ═══
                    # Проверяем что значение действительно обновилось
                    actual_value = panel._workflow.project_variables.get(var_name, {}).get('value', 'NOT_FOUND')
                    self._log_msg(f"[DEBUG CHECK] В модели: {var_name} = {actual_value}")
        
        # ═══ Автозакрытие браузеров — только НЕ в пошаговом режиме ═══
        _was_step = getattr(sender_rt, '_was_step_mode', False)
        if not _was_step:
            try:
                _fin_tab = finished_tab or self._current_project_tab()
                _should_close = getattr(
                    getattr(_fin_tab, 'workflow', None),
                    'close_browser_on_finish', True
                )
                if _fin_tab and hasattr(_fin_tab, 'close_all_browsers') and _should_close:
                    _fin_tab.close_all_browsers()
                    self._log_msg("🔴 Все браузеры проекта закрыты по завершении workflow")
                elif not _should_close:
                    self._log_msg("🌐 Браузеры оставлены открытыми (настройка проекта)")
            except Exception as _e:
                self._log_msg(f"⚠ Ошибка закрытия браузеров: {_e}")
        # ═══ Синхронизируем списки/таблицы из metadata обратно в панель ═══
        try:
            if finished_tab is current_tab:
                if hasattr(self, '_vars_panel') and self._vars_panel and self._vars_panel._workflow:
                    self._vars_panel._load_lists_tables_from_workflow()
        except Exception:
            pass
        # ═══ Сохраняем _open_programs перед обнулением runtime ═══
        try:
            _rt_fin = finished_tab._runtime_thread if finished_tab else self._runtime_thread
            if _rt_fin and hasattr(_rt_fin, '_context'):
                _progs = _rt_fin._context.get('_open_programs', {})
                if _progs:
                    if finished_tab:
                        finished_tab._last_open_programs = _progs
                    else:
                        self._last_open_programs = _progs
        except Exception:
            pass
        # ═══ Обнуляем runtime для ЗАВЕРШИВШЕГОСЯ таба (не текущего!) ═══
        if finished_tab:
            finished_tab._runtime_thread = None
        else:
            self._runtime_thread = None
        # Обновляем debug-панель
        tab = self._current_project_tab()
        if tab:
            self._sync_debug_panel_to_tab(tab)

    def _on_runtime_node_finished(self, node_id: str, name: str, success: bool, preview: str):
        # ═══ ИСПРАВЛЕНИЕ: обновляем UI только если сигнал от ТЕКУЩЕГО таба ═══
        tab = self._current_project_tab()
        sender_rt = self.sender()
        if tab and (tab._runtime_thread is None or tab._runtime_thread.signals is not sender_rt):
            return
        # ═══ Обновляем статус ноды (но НЕ визуал если deferred) ═══
        tab = self._current_project_tab()
        deferred = tab and getattr(tab, '_deferred_rendering', False)
        item = self._scene.get_node_item(node_id)
        if item:
            item.node._status = "success" if success else "error"
            if not deferred:
                item.update()

        # --- НАЧАЛО: ПРИНУДИТЕЛЬНЫЙ ПАРСИНГ И СОЗДАНИЕ ФАЙЛОВ ИЗ ТЕКСТА ---
        if success and hasattr(self, '_project_root') and self._project_root:
            import re, json, os, hashlib
            
            if not hasattr(self, '_executed_cmds'):
                self._executed_cmds = set()

            # Читаем текст агента (весь лог чата, чтобы избежать обрезки preview)
            chat_text = self._agent_chat.toPlainText()
            
            # 1. Ищем команды в формате Markdown: ```json ... ```
            json_blocks = re.findall(r'```json\s*(.*?)\s*```', chat_text, re.DOTALL)
            
            for block in json_blocks:
                try:
                    parsed_data = json.loads(block)
                    # Логика обработки распарсенного JSON
                    if isinstance(parsed_data, dict):
                        pass # Здесь должен быть восстановлен утерянный код сохранения файлов
                except json.JSONDecodeError as e:
                    self._log_msg(f"❌ Ошибка парсинга JSON: {e}")

    def _on_runtime_breakpoint(self, node_id: str, name: str):
        sender_rt = self.sender()
        tab = self._current_project_tab()
        if tab and hasattr(tab, '_runtime_thread') and tab._runtime_thread is not None and tab._runtime_thread.signals is not sender_rt:
            return
        self._highlight_node(node_id, "running")
        self._btn_dbg_cont.setEnabled(True)
        self._btn_dbg_step.setEnabled(True)
        self._btn_dbg_stop.setEnabled(True)
        self._lbl_dbg_status.setText(f"⏸ Пауза: {name}")
        self._lbl_dbg_status.setStyleSheet("color: #E0AF68;")
    
    def _on_runtime_waiting_input(self, node_id: str, prompt: str):
        """Пауза для подтверждения пользователем (human in loop)."""
        sender_rt = self.sender()
        tab = self._current_project_tab()
        if tab and hasattr(tab, '_runtime_thread') and tab._runtime_thread is not None and tab._runtime_thread.signals is not sender_rt:
            return
        self._highlight_node(node_id, "running")
        self._btn_dbg_cont.setEnabled(True)
        self._btn_dbg_step.setEnabled(True)
        self._btn_dbg_stop.setEnabled(True)
        self._lbl_dbg_status.setText(f"👤 Ожидание: {prompt[:40]}")
        self._lbl_dbg_status.setStyleSheet("color: #E0AF68;")
        
        # Показываем в чате
        self._agent_chat.append(
            f"<br><b style='color: #E0AF68;'>👤 {prompt}</b>"
            f"<br><i style='color: #565f89;'>Нажмите «Продолжить» или «Шаг» для запуска</i>"
        )
    
    def _on_runtime_error(self, node_id: str, error: str):
        # ═══ ИСПРАВЛЕНИЕ: обновляем UI только если сигнал от ТЕКУЩЕГО таба ═══
        sender_rt = self.sender()
        tab = self._current_project_tab()
        if tab and hasattr(tab, '_runtime_thread') and tab._runtime_thread is not None and tab._runtime_thread.signals is not sender_rt:
            return
        if node_id:
            item = self._scene.get_node_item(node_id)
            if item:
                item.node._status = "error"
                item.update()

    def _on_runtime_progress(self, current: int, total: int):
        # ═══ ИСПРАВЛЕНИЕ: обновляем UI только если сигнал от ТЕКУЩЕГО таба ═══
        sender_rt = self.sender()
        tab = self._current_project_tab()
        if tab and hasattr(tab, '_runtime_thread') and tab._runtime_thread is not None and tab._runtime_thread.signals is not sender_rt:
            return
        self._lbl_dbg_status.setText(f"▶ Шаг {current}/{total}")
    
    def _toggle_browser_recording(self, active: bool):
        """Включить/выключить запись действий браузера в сниппеты."""
        self._recording_active = active
        if active:
            self._btn_record.setText("⏹ Стоп запись")
            self._statusBar().showMessage("⏺ Идёт запись действий браузера...") \
                if hasattr(self, '_statusBar') else None
            self._browser_recorder = BrowserActionRecorder(
                on_action=self._on_recorded_browser_action,
                parent=self
            )
            self._browser_recorder.start()
        else:
            self._btn_record.setText("⏺ Запись")
            if hasattr(self, '_browser_recorder'):
                self._browser_recorder.stop()
                self._browser_recorder = None

    def _on_recorded_browser_action(self, action_type: str, data: dict):
        """Вызывается при каждом записанном действии браузера — создаёт сниппет."""
        from services.agent_models import AgentNode, AgentType
        import uuid

        # Маппинг типа действия → тип сниппета
        type_map = {
            "click":       AgentType.BROWSER_ACTION,
            "input":       AgentType.BROWSER_ACTION,
            "navigate":    AgentType.BROWSER_ACTION,
            "screenshot":  AgentType.BROWSER_SCREENSHOT,
            "scroll":      AgentType.BROWSER_ACTION,
            "key":         AgentType.BROWSER_ACTION,
        }
        agent_type = type_map.get(action_type, AgentType.BROWSER_ACTION)

        node = AgentNode(
            id=str(uuid.uuid4()),
            name=f"[Rec] {action_type.capitalize()}",
            agent_type=agent_type,
            description=f"Записано: {action_type}",
        )

        # Заполняем snippet_config из данных записи
        cfg = {}
        if action_type == "click":
            cfg["action"] = "click"
            cfg["target"] = data.get("selector", data.get("xpath", ""))
        elif action_type == "input":
            cfg["action"] = "set_value"
            cfg["target"] = data.get("selector", "")
            cfg["value"]  = data.get("value", "")
        elif action_type == "navigate":
            cfg["action"] = "navigate"
            cfg["target"] = data.get("url", "")
        elif action_type == "scroll":
            cfg["action"] = "scroll"
            cfg["target"] = data.get("selector", "")
        elif action_type == "key":
            cfg["action"] = "keyboard"
            cfg["target"] = data.get("key", "")
        node.snippet_config = cfg

        # Добавить узел в граф после последнего выделенного/записанного
        if self._workflow:
            self._workflow.add_node(node)
            # Соединить с предыдущим записанным узлом
            if hasattr(self, '_last_recorded_node_id') and self._last_recorded_node_id:
                from services.agent_models import AgentEdge
                edge = AgentEdge(
                    id=str(uuid.uuid4()),
                    source_id=self._last_recorded_node_id,
                    target_id=node.id
                )
                self._workflow.add_edge(edge)
            self._last_recorded_node_id = node.id
            self._scene.refresh_from_workflow()


    def _stop_runtime(self):
        if self._runtime_thread and self._runtime_thread.isRunning():
            self._runtime_thread.stop()
            self._btn_dbg_stop.setEnabled(False)  # ← ДОБАВИТЬ: блокируем повторные нажатия
            self._btn_dbg_cont.setEnabled(False)
            self._log_msg("⏹ Остановка запрошена...")
            # Не ждём завершения — поток сам обновит UI через сигналы

    def _continue_runtime(self):
        if self._runtime_thread and self._runtime_thread.isRunning():
            self._runtime_thread.resume()
            self._lbl_dbg_status.setText("▶ Продолжение...")
            self._btn_dbg_cont.setEnabled(False)
            self._btn_dbg_step.setEnabled(False)

    # ── Helpers ──

    def _log_msg(self, msg: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"[{ts}] {msg}")

    def _update_status(self):
        n = len(self._workflow.nodes)
        e = len(self._workflow.edges)
        name = self._workflow.name
        self._statusbar.showMessage(
            f"{name} — {n} агентов, {e} связей" +
            (f" — {Path(self._file_path).name}" if self._file_path else ""))

    def _vline(self) -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1); f.setStyleSheet("background:#1E2030;margin:3px 4px;")
        return f

    # ── Zoom & Navigation ──────────────────────────

    def _zoom(self, factor: float):
        """Масштабирование канваса."""
        self._view.scale(factor, factor)
        self._update_zoom_label()

    def _zoom_fit(self):
        """Вместить все элементы в видимую область."""
        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isNull():
            return
        margin = 60
        items_rect.adjust(-margin, -margin, margin, margin)
        self._view.fitInView(items_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._update_zoom_label()

    def _zoom_reset(self):
        """Сброс масштаба к 100%."""
        self._view.resetTransform()
        self._update_zoom_label()

    def _on_zoom_slider(self, value):
        """Обработка ползунка масштаба."""
        current = self._view.transform().m11()
        target = value / 100.0
        if abs(current) > 0.01:
            factor = target / current
            self._view.scale(factor, factor)
        self._lbl_zoom.setText(f"{value}%")

    def _update_zoom_label(self):
        """Обновить лейбл и слайдер масштаба."""
        scale = self._view.transform().m11()
        pct = int(scale * 100)
        if hasattr(self, '_lbl_zoom'):
            self._lbl_zoom.setText(f"{pct}%")
        if hasattr(self, '_zoom_slider'):
            self._zoom_slider.blockSignals(True)
            self._zoom_slider.setValue(pct)
            self._zoom_slider.blockSignals(False)

    def _navigate_to_start(self):
        """Перейти к начальному узлу."""
        entry = self._workflow.get_entry_node() if self._workflow else None
        if entry:
            item = self._scene.get_node_item(entry.id)
            if item:
                if item.scene() is self._scene:
                    self._view.centerOn(item)
                item.setSelected(True)

    def _navigate_to_end(self):
        """Перейти к последнему узлу (без исходящих связей)."""
        if not self._workflow or not self._workflow.nodes:
            return
        # Находим узлы без исходящих связей
        sources = {e.source_id for e in self._workflow.edges}
        end_nodes = [n for n in self._workflow.nodes if n.id not in sources]
        target = end_nodes[-1] if end_nodes else self._workflow.nodes[-1]
        item = self._scene.get_node_item(target.id)
        if item:
            if item.scene() is self._scene:
                self._view.centerOn(item)
            item.setSelected(True)

    def _refresh_styles(self):
        # Принудительно обновляем все ноды при смене темы
        for item in self._scene.items():
            if isinstance(item, AgentNodeItem):
                item._setup_visuals()
                item.update()
        self._scene.update()

        # Обновляем стили панелей
        if hasattr(self, '_debug_panel'):
            self._debug_panel.setStyleSheet(
                f"QFrame#debugPanel {{ background: {get_color('bg1')}; "
                f"border-top: 1px solid {get_color('bd2')}; }}"
            )

        # Обновляем панель переменных
        if hasattr(self, '_vars_panel'):
            self._vars_panel._on_theme_changed()
            self._vars_panel.setStyleSheet(f"background: {get_color('bg1')}; border: none;")

        # ── Диалог агентов ────────────────────────────────────────
        if hasattr(self, '_agent_chat'):
            self._agent_chat.setStyleSheet(f"""
                QTextEdit {{
                    background: {get_color('bg0')};
                    color: {get_color('tx0')};
                    border: 1px solid {get_color('bd')};
                    border-radius: 4px;
                    font-family: 'JetBrains Mono', Consolas, monospace;
                    font-size: 11px;
                }}
            """)

        # ── Лог и нижние табы ────────────────────────────────────
        if hasattr(self, '_bottom_tabs'):
            self._bottom_tabs.setStyleSheet(
                f"QTabWidget::pane {{ background: {get_color('bg1')}; border: 1px solid {get_color('bd2')}; }}"
                f"QTabBar::tab {{ background: {get_color('bg2')}; color: {get_color('tx1')}; padding: 4px 10px; }}"
                f"QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('tx0')}; }}"
            )
        if hasattr(self, '_log'):
            self._log.setStyleSheet(
                f"QPlainTextEdit {{ background: {get_color('bg0')}; color: {get_color('tx1')}; border: none; }}"
            )

        # ── Правая панель свойств ────────────────────────────────
        if hasattr(self, '_props'):
            self._props.setStyleSheet(
                f"background: {get_color('bg1')}; color: {get_color('tx0')};"
            )

        # ── Обновляем левую панель (палитру) ─────────────────────
        if hasattr(self, '_apply_palette_styles'):
            self._apply_palette_styles()

        # ── Обновляем трей браузеров во всех вкладках ─────────────
        if hasattr(self, '_project_tabs'):
            for _i in range(self._project_tabs.count()):
                _tab = self._project_tabs.widget(_i)
                if hasattr(_tab, 'tray_panel') and _tab.tray_panel:
                    _tab.tray_panel.apply_theme()

        # ── Обновляем панель браузеров (нижний таб) ───────────────
        if hasattr(self, '_browser_panel') and self._browser_panel:
            self._browser_panel.set_manager(tab._base_browser_manager)
        if hasattr(self, '_program_panel') and self._program_panel:
            self._program_panel.apply_theme()
            self._program_panel._refresh()

        # ── Обновляем панель Списки/Таблицы ──────────────────────
        if hasattr(self, '_lt_inline_panel') and self._lt_inline_panel:
            self._lt_inline_panel.setStyleSheet(f"""
                QFrame#ltInlinePanel {{
                    background: {get_color('bg1')};
                    border-top: 1px solid {get_color('bd')};
                }}
            """)
        # ── Обновляем кнопки debug-панели ─────────────────────────
        if hasattr(self, '_btn_run_all'):
            self._btn_run_all.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {get_color('bg2')}, stop:1 {get_color('bg1')});
                    color: {get_color('ok')}; border: 2px solid {get_color('ok')};
                    border-radius: 5px; font-weight: bold; font-size: 12px;
                    padding: 0 12px; min-width: 130px;
                }}
                QPushButton:hover {{ background: {get_color('ok')}; color: #000; }}
                QPushButton:pressed {{ background: #6a9e3a; }}
            """)
        if hasattr(self, '_btn_stop_all_tabs'):
            self._btn_stop_all_tabs.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {get_color('bg2')}, stop:1 {get_color('bg1')});
                    color: {get_color('err')}; border: 2px solid {get_color('err')};
                    border-radius: 5px; font-weight: bold; font-size: 12px;
                    padding: 0 12px; min-width: 100px;
                }}
                QPushButton:hover {{ background: {get_color('err')}; color: #000; }}
            """)
        if hasattr(self, '_chk_deferred_render'):
            self._chk_deferred_render.setStyleSheet(
                f"QCheckBox {{ color: {get_color('tx1')}; font-size: 11px; }}")
        if hasattr(self, '_chk_close_browser_toolbar'):
            self._chk_close_browser_toolbar.setStyleSheet(
                f"QCheckBox {{ color: {get_color('tx1')}; font-size: 11px; }}")

    def _on_language_changed(self, lang: str = "") -> None:
        """Полный ретраслят ВСЕГО окна конструктора."""
        try:
            _retranslate_widget(self)
            self.setWindowTitle(tr("🤖 Конструктор AI-агентов — AI Code Sherlock"))
            
            if hasattr(self, '_bottom_tabs'):
                _retranslate_widget(self._bottom_tabs)
                # Переустанавливаем тексты табов
                self._bottom_tabs.setTabText(0, tr("📋 Системный лог"))
                self._bottom_tabs.setTabText(1, tr("💬 Диалог агентов"))
                self._bottom_tabs.setTabText(2, tr("🌐 Браузеры"))
                
            if hasattr(self, '_props'):
                _retranslate_widget(self._props)
                
            if hasattr(self, '_vars_panel'):
                _retranslate_widget(self._vars_panel)
                
            if hasattr(self, '_project_tabs'):
                _retranslate_widget(self._project_tabs)

            # Переводим QAction в тулбаре
            from PyQt6.QtGui import QAction
            for action in self.findChildren(QAction):
                if action.text():
                    action.setText(tr(action.text()))

            # Перестраиваем панель свойств если есть выбранная нода
            if hasattr(self, '_props') and self._props and self._props._node:
                current_node = self._props._node
                self._props.set_node(None)
                self._props.set_node(current_node)
            
            # Перестраиваем snippet панель
            if hasattr(self, '_rebuild_snippet_panel'):
                self._rebuild_snippet_panel()
                
            # Обновляем палитру
            if hasattr(self, '_apply_palette_styles'):
                self._apply_palette_styles()
            
            # Переводим список скиллов (левое меню)
            if hasattr(self, '_skill_list'):
                for i in range(self._skill_list.count()):
                    item = self._skill_list.item(i)
                    skill_id = item.data(Qt.ItemDataRole.UserRole)
                    skill = self._skill_registry.get(skill_id)
                    if skill:
                        # Переводим имя и tooltip
                        item.setText(f"{skill.icon} {tr(skill.name)}")
                        translated_desc = tr(skill.description)
                        translated_cat = tr(skill.category.value if hasattr(skill.category, 'value') else str(skill.category))
                        item.setToolTip(f"{translated_desc}\n{tr('Категория')}: {translated_cat}")

            # Переводим заголовки таблицы переменных сниппета
            if hasattr(self, '_vars_table'):
                self._vars_table.setHorizontalHeaderLabels([
                    tr("var_col_name"),      # "Имя переменной"
                    tr("var_col_value"),     # "Значение"
                    tr("var_col_type"),      # "Тип"
                    tr("var_col_desc")       # "Описание"
                ])
            
            # Переводим динамические label'ы сниппетов если они есть
            if hasattr(self, '_snippet_field_labels') and self._props._node:
                node_type = self._props._node.agent_type
                # Получаем схему для текущего типа
                from constructor.constants import SNIPPET_SCHEMA  # или где у вас схема
                schema = SNIPPET_SCHEMA.get(node_type, {})
                
                for key, lbl in self._snippet_field_labels.items():
                    # Находим оригинальный ключ в схеме
                    for field in schema.get('fields', []):
                        if field[0] == key:
                            # field[2] — это label (третий элемент)
                            original_label = field[2]
                            # Убираем двоеточие если есть
                            label_key = original_label.replace(':', '')
                            lbl.setText(tr(label_key))
                            break
            
            self._log_msg(tr("🌍 Язык обновлён"))
        except Exception as e:
            print(f"[i18n] retranslate error: {e}")

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        
        # Обработка Ctrl+Z / Ctrl+Y для undo/redo
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self._undo()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Y:
                self._redo()
                event.accept()
                return
        elif event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Z:
                self._redo()
                event.accept()
                return
        
        # Ctrl+Z - Undo
        if event.key() == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            desc = self._history.undo()
            self._log_msg(f"↩️ Отменено: {desc}" if desc else "Нечего отменять")
            event.accept()
            return
        
        # Ctrl+Shift+Z или Ctrl+Y - Redo
        if (event.key() == Qt.Key.Key_Z and modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)) or \
           (event.key() == Qt.Key.Key_Y and modifiers == Qt.KeyboardModifier.ControlModifier):
            desc = self._history.redo()
            self._log_msg(f"↪️ Повторено: {desc}" if desc else "Нечего повторять")
            event.accept()
            return
        
        # Ctrl+C - Copy
        if event.key() == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier:
            self._copy_selected()
            event.accept()
            return
        
        # Ctrl+V - Paste
        if event.key() == Qt.Key.Key_V and modifiers == Qt.KeyboardModifier.ControlModifier:
            self._paste_clipboard()
            event.accept()
            return
        
        # Ctrl+X - Cut (копируем с блоковой структурой, затем удаляем всю цепочку)
        if event.key() == Qt.Key.Key_X and modifiers == Qt.KeyboardModifier.ControlModifier:
            self._copy_selected()   # уже собирает всю цепочку в буфер
            # Удаляем все ноды из скопированного блока (они теперь все в буфере)
            import json
            raw = QApplication.clipboard().text()
            try:
                clip = json.loads(raw)
                nodes_data = clip['nodes'] if isinstance(clip, dict) else clip
                ids_to_delete = [nd['id'] for nd in nodes_data]
                for nid in ids_to_delete:
                    item = self._scene.get_node_item(nid)
                    if item:
                        self._scene.remove_node(nid)
                self._log_msg(f"✂️ Вырезано {len(ids_to_delete)} нодов")
            except Exception:
                self._delete_selected()
            event.accept()
            return
        
        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
        elif event.key() == Qt.Key.Key_S and modifiers == Qt.KeyboardModifier.ControlModifier:
            self._save_workflow()
            
        elif event.key() == Qt.Key.Key_F5:
            if self._btn_dbg_start.isEnabled():
                self._debug_start()
            event.accept()
            return

        elif event.key() == Qt.Key.Key_F6:
            self._debug_run_from_selected()
            event.accept()
            return

        elif event.key() == Qt.Key.Key_F7:
            self._debug_run_selected_only()
            event.accept()
            return

        elif event.key() == Qt.Key.Key_F8:
            self._debug_start_stepping()
            event.accept()
            return

        elif event.key() == Qt.Key.Key_F10:
            if self._btn_dbg_step.isEnabled():
                self._debug_step()
            event.accept()
            return    
        else:
            super().keyPressEvent(event)
    
    def _copy_selected(self):
        """Копирование выбранных агентов вместе с блоковой структурой и рёбрами"""
        selected_items = [item for item in self._scene.selectedItems() if isinstance(item, AgentNodeItem)]
        if not selected_items:
            return

        # Расширяем выделение: если выбран верхний нод — добавляем всех его детей
        all_ids = {item.node.id for item in selected_items}
        extra = []
        for item in list(selected_items):
            def _collect_chain(node_id):
                ni = self._scene.get_node_item(node_id)
                if not ni:
                    return
                for child_id in getattr(ni.node, 'attached_children', []):
                    if child_id not in all_ids:
                        all_ids.add(child_id)
                        child_item = self._scene.get_node_item(child_id)
                        if child_item:
                            extra.append(child_item)
                    _collect_chain(child_id)
            _collect_chain(item.node.id)
        selected_items = selected_items + extra

        import json
        nodes_data = []
        for item in selected_items:
            d = item.node.to_dict()
            d['_copy_attached_to'] = getattr(item.node, 'attached_to', None)
            d['_copy_attached_children'] = getattr(item.node, 'attached_children', [])
            nodes_data.append(d)

        # ═══ НОВОЕ: сохраняем рёбра между скопированными нодами ═══
        edges_data = []
        for edge in self._workflow.edges:
            if edge.source_id in all_ids and edge.target_id in all_ids:
                edges_data.append(edge.to_dict())

        clipboard = {'nodes': nodes_data, 'edges': edges_data, '_is_block_copy': True}
        QApplication.clipboard().setText(json.dumps(clipboard))
        self._log_msg(f"📋 Скопировано: {len(nodes_data)} нодов, {len(edges_data)} связей")

    def _paste_at(self, pos: QPointF):
        """Вставить в указанную позицию, восстанавливая блоковую структуру"""
        text = QApplication.clipboard().text()
        if not text:
            return

        try:
            import json
            raw = json.loads(text)

            # Поддерживаем оба формата: новый (dict с nodes) и старый (list)
            if isinstance(raw, dict) and raw.get('_is_block_copy'):
                nodes_data = raw['nodes']
            elif isinstance(raw, list):
                nodes_data = raw
            else:
                return

            if not nodes_data:
                return

            # Смещение относительно первой ноды
            first_x = nodes_data[0].get('x', 0)
            first_y = nodes_data[0].get('y', 0)
            offset_x = pos.x() - first_x - 100
            offset_y = pos.y() - first_y - 60

            # Маппинг old_id → new_id для восстановления связей
            id_map = {}
            pasted = []
            for nd in nodes_data:
                old_id = nd.get('id', '')
                new_id = str(uuid.uuid4())[:8]
                id_map[old_id] = new_id
                nd['id'] = new_id
                nd['x'] = nd.get('x', 0) + offset_x
                nd['y'] = nd.get('y', 0) + offset_y
                # Временно сбрасываем attachment (восстановим ниже)
                nd['attached_to'] = None
                nd['attached_children'] = []
                node = AgentNode.from_dict(nd)
                _init_extended_attrs(node)
                self._scene.add_node(node)
                pasted.append((node, nd))

            # Восстанавливаем блоковую структуру через attach_node
            for node, nd in pasted:
                old_parent = nd.get('_copy_attached_to')
                if old_parent and old_parent in id_map:
                    new_parent_id = id_map[old_parent]
                    self._scene.attach_node(node.id, new_parent_id)

            # ═══ НОВОЕ: восстанавливаем рёбра (стрелки) между вставленными нодами ═══
            from services.agent_models import AgentEdge, EdgeCondition
            pasted_edges = []
            edges_source = raw.get('edges', []) if isinstance(raw, dict) else []
            for ed in edges_source:
                old_src = ed.get('source_id', '')
                old_tgt = ed.get('target_id', '')
                if old_src in id_map and old_tgt in id_map:
                    new_edge = AgentEdge(
                        source_id=id_map[old_src],
                        target_id=id_map[old_tgt],
                        condition=EdgeCondition(ed.get('condition', 'always')),
                        label=ed.get('label', ''),
                    )
                    ok, _ = self._workflow.add_edge(new_edge)
                    if ok:
                        # ═══ ИСПРАВЛЕНИЕ: создаём визуальный элемент стрелки в сцене ═══
                        self._scene._add_edge_item(new_edge)
                        pasted_edges.append(new_edge)
            if pasted_edges:
                self._scene.update_edges()

            pasted_nodes = [n for n, _ in pasted]
            if pasted_nodes:
                def _undo_paste():
                    for e in pasted_edges:
                        self._workflow.remove_edge(e.id)
                    for n in pasted_nodes:
                        self._scene.remove_node(n.id)
                    self._scene.update_edges()
                def _redo_paste():
                    pass  # ноды уже вставлены; история только для отмены

                self._history.push(
                    _redo_paste,
                    _undo_paste,
                    f"Вставка {len(pasted_nodes)} нодов + {len(pasted_edges)} связей"
                )
                self._log_msg(f"📥 Вставлено {len(pasted_nodes)} нодов в ({int(pos.x())}, {int(pos.y())})")
        except Exception as e:
            self._log_msg(f"❌ Ошибка вставки: {e}")

    def _paste_clipboard(self):
        """Legacy paste at center"""
        view_center = self._view.mapToScene(self._view.viewport().rect().center())
        self._paste_at(view_center)

    def _create_agent_at(self, agent_type: AgentType, pos: QPointF):
        """Create agent at specific position"""
        # ═══ КРИТИЧЕСКИ: используем текущую активную сцену ═══
        tab = self._current_project_tab()
        if tab is None:
            return
        scene = tab.scene
        
        if agent_type == AgentType.NOTE:
            node = AgentNode(
                name="📌 Заметка",
                agent_type=agent_type,
                x=pos.x() - 110,
                y=pos.y() - 70,
                width=220,
                height=140,
                color="#E0AF68",
                note_color="#E0AF68",
            )
        else:
            node = AgentNode(
                name=f"{_AGENT_ICONS.get(agent_type, '🤖')} {agent_type.value.replace('_', ' ').title()}",
                agent_type=agent_type,
                x=pos.x() - 100,
                y=pos.y() - 60,
                color=_AGENT_COLORS.get(agent_type, "#565f89"),
            )
        _init_extended_attrs(node)
    
        # ═══ Используем scene текущего таба ═══
        scene.add_node(node)
        
        tab._history.push(
            lambda: scene.add_node(node),
            lambda: scene.remove_node(node.id),
            f"Создание {node.name}"
        )
        self._log_msg(f"🤖 Создан агент в ({int(pos.x())}, {int(pos.y())}): {node.name}")
        self._update_status()
        self._history.push(
            lambda: self._scene.add_node(node),
            lambda: self._scene.remove_node(node.id),
            f"Создание {node.name}"
        )
        self._log_msg(f"🤖 Создан агент в ({int(pos.x())}, {int(pos.y())}): {node.name}")
        self._update_status()

    def _load_skills_from_folder(self):
        """Load skills from user-selected folder"""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку со скиллами")
        if not folder:
            return
        
        loaded = self._skill_registry.load_from_folder(folder)
        self._refresh_skill_list()
        
        # Запоминаем папку для последующего сохранения в проект
        if not hasattr(self, '_loaded_skill_folders'):
            self._loaded_skill_folders = []
        if folder not in self._loaded_skill_folders:
            self._loaded_skill_folders.append(folder)
        
        self._log_msg(f"📂 Загружено {len(loaded)} скиллов из {folder}")
        QMessageBox.information(self, "Готово", f"Загружено {len(loaded)} скиллов\nВсего: {len(self._skill_registry.all_skills())}")
        # Сразу сохраняем в metadata чтобы не потерять при закрытии без явного Save
        if self._workflow:
            if not hasattr(self._workflow, 'metadata'):
                self._workflow.metadata = {}
            self._workflow.metadata['loaded_skill_folders'] = self._loaded_skill_folders.copy()
            
    def _save_project_root(self):
        """Сохранить рабочую папку в workflow metadata (без полного Save As)."""
        tab = self._current_project_tab()
        root = tab._project_root if tab else ""
        if not root:
            QMessageBox.warning(self, "Нет папки", "Сначала выберите рабочую папку.")
            return
        if not hasattr(self._workflow, 'metadata'):
            self._workflow.metadata = {}
        self._workflow.metadata['project_root'] = root
        self._workflow.project_root = root
        # Если workflow уже сохранен - обновляем файл
        if self._file_path:
            self._save_workflow()
            self._log_msg(f"💾 Рабочая папка сохранена в проект: {self._project_root}")
        else:
            self._log_msg(f"💾 Рабочая папка запомнена: {self._project_root} (сохраните workflow для записи на диск)")
    
    def _on_working_dir_changed(self, text: str):
        """Обработчик изменения рабочей папки в поле ввода."""
        # Сохраняем в текущий ProjectTab
        tab = self._current_project_tab()
        if tab:
            tab._project_root = text
        # Обновляем корень профилей браузера
        if text and os.path.exists(text):
            self._browser_profiles.set_root(text)

    def _browse_working_dir(self):
        """Открыть диалог выбора рабочей папки."""
        path = QFileDialog.getExistingDirectory(self, "Выбрать рабочую папку", self._project_root or "")
        if path:
            self._fld_working_dir.setText(path)
    
    def _quick_launch_browser(self):
        """Быстрый запуск браузера через диалог."""
        from PyQt6.QtWidgets import QDialog
        dlg = BrowserLaunchDialog(self._browser_profiles, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            profile, proxy = dlg.get_result()
            self._browser_profiles.add_or_update(profile)
            # Авто-встраивание теперь делает сама панель BrowserInstancePanel
            inst = self._browser_manager.launch(profile, proxy)
            if inst:
                self._log_msg(f"🌐 Браузер запущен: {inst.instance_id}")
                
                # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
                # Полный перевод сразу после создания UI
                QTimer.singleShot(0, lambda: _retranslate_widget(self))
                QTimer.singleShot(50, self._on_language_changed)   # гарантируем перевод всего
                # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

                # Автосохранение + проверка восстановления
                self._init_autosave()
                QTimer.singleShot(1500, self._check_and_offer_recovery)

                if hasattr(self, '_browser_panel'):
                    self._browser_panel._refresh()
            else:
                QMessageBox.warning(self, "Ошибка",
                    "❌ Не удалось запустить браузер.\n"
                    "Установите: pip install selenium webdriver-manager")

    def _set_project_browser_root(self, root: str = None):
        """Обновить корень проекта для браузерных профилей."""
        if root is None:
            tab = self._current_project_tab()
            root = tab._project_root if tab else ""
        if hasattr(self, '_browser_profiles'):
            self._browser_profiles.set_root(root)
    
    def _open_working_dir(self):
        import os
        import subprocess
        tab = self._current_project_tab()
        root = tab._project_root if tab else ""
        path = self._fld_working_dir.text() or root
        if path and os.path.exists(path):
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', path])
            else:  # macOS/Linux
                subprocess.run(['xdg-open', path])

    def _on_working_dir_changed(self, path: str):
        # Сохраняем ТОЛЬКО в текущий ProjectTab
        _tab = self._current_project_tab()
        if _tab is not None:
            _tab._project_root = path
        if hasattr(self, '_tool_executor') and self._tool_executor:
            self._tool_executor.set_root(path)
        if self._workflow:
            self._workflow.project_root = path
        # Браузерные профили привязаны к папке проекта
        if hasattr(self, '_browser_profiles'):
            self._browser_profiles.set_root(path)

    def _create_dated_subfolder(self):
        from datetime import datetime
        tab = self._current_project_tab()
        base = tab._project_root if tab else ""
        if not base:
            base = QFileDialog.getExistingDirectory(self, "Выберите базовую папку для проекта")
        if not base:
            base = QFileDialog.getExistingDirectory(self, "Выберите базовую папку для проекта")
            if not base:
                return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_dir = os.path.join(base, f"run_{ts}")
        try:
            os.makedirs(new_dir, exist_ok=True)
            self._project_root = new_dir
            self._fld_working_dir.setText(new_dir)
            self._log_msg(f"📁 Создана папка запуска: {new_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать папку: {e}")

    def _do_project_backup(self, root: str = None, label: str = "backup"):
        import shutil
        from datetime import datetime
        if root is None:
            tab = self._current_project_tab()
            root = tab._project_root if tab else ""
        if not root or not os.path.exists(root):
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(root, ".backups", f"{label}_{ts}")
        try:
            os.makedirs(backup_dir, exist_ok=True)
            for item in os.listdir(root):
                if item == ".backups":
                    continue
                src = os.path.join(root, item)
                dst = os.path.join(backup_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            self._log_msg(f"💾 Бэкап создан: {backup_dir}")
        except Exception as e:
            self._log_msg(f"⚠ Бэкап не удался: {e}")
            
    # ─── Управление вкладками проектов ──────────────────────────────────────
    
    def _open_dashboard(self):
        """Открыть/показать окно менеджера проектов."""
        if self._project_dashboard is None:
            self._project_dashboard = ProjectDashboard(
                manager=self._project_exec_manager,
                constructor_window=self,
                parent=None  # Отдельное окно
            )
            self._project_dashboard.open_project_requested.connect(
                self._on_dashboard_open_project
            )
            # Передаём сервисы
            if self._model_manager:
                self._project_exec_manager.set_services(
                    self._model_manager, self._skill_registry
                )
        
        # Автоматически добавляем все открытые проекты (только непустые)
        for i in range(self._project_tabs.count()):
            tab = self._project_tabs.widget(i)
            if not isinstance(tab, ProjectTab) or not tab.workflow:
                continue
            # Пропускаем пустые вкладки без файла и без нод
            _has_file = bool(getattr(tab, 'project_path', '') or '')
            _has_nodes = bool(tab.workflow.nodes or tab.workflow.edges)
            if not _has_file and not _has_nodes:
                continue
            # Имя: сначала из пути файла, затем из workflow.name, затем из вкладки
            _path = getattr(tab, 'project_path', '') or ''
            if _path:
                import os as _os
                _tab_name = _os.path.basename(_path).replace('.workflow.json', '')
            else:
                _tab_name = (tab.workflow.name or '').strip()
            if not _tab_name or _tab_name in ('...', '…'):
                _tab_name = self._project_tabs.tabText(i).strip()
            if not _tab_name or _tab_name in ('...', '…'):
                _tab_name = f"Проект {i + 1}"
            self._project_dashboard.register_from_tab(tab, _tab_name)
        
        self._project_dashboard.show()
        self._project_dashboard.raise_()
        self._project_dashboard.activateWindow()
 
    def _on_dashboard_open_project(self, project_id: str):
        """Открыть проект в редакторе по запросу из dashboard."""
        entry = self._project_exec_manager.get_project(project_id)
        if entry and entry.tab_reference:
            # Переключиться на вкладку
            for i in range(self._project_tabs.count()):
                if self._project_tabs.widget(i) is entry.tab_reference:
                    self._project_tabs.setCurrentIndex(i)
                    break
    
    def _add_project_tab(self, name: str = "Проект") -> "ProjectTab":
        tab = ProjectTab(parent=self)
        # Прокидываем ссылку на главное окно в сцену
        tab.scene._main_window = self
        # Гарантируем что workflow создан
        if tab.workflow is None:
            tab.workflow = AgentWorkflow()
            tab.scene.set_workflow(tab.workflow)
            _start = AgentNode(
                name=tr("СТАРТ"),
                agent_type=AgentType.PROJECT_START,
                x=60, y=60,
                width=100, height=100,
            )
            tab.scene.add_node(_start)
            tab.workflow.entry_node_id = _start.id
        # ═══ CRITICAL: Явно сбрасываем флаг изменений для нового проекта ═══
        tab._modified = False
        idx = self._project_tabs.addTab(tab, name)
        self._project_tabs.setCurrentIndex(idx)
        self._on_tab_switched(idx)
        
        # ── Регистрация в менеджере — отложена ──
        # НЕ регистрируем здесь: таб ещё пустой (нет file_path, нет нод).
        # Регистрация произойдёт автоматически:
        #   - при открытии Dashboard (register_from_tab)
        #   - при запуске workflow (_run_workflow)
        # Здесь только привязываем если запись УЖЕ существует в менеджере (после load_state)
        if hasattr(self, '_project_exec_manager') and self._project_exec_manager:
            _tab_path = getattr(tab, 'project_path', '') or ''
            if _tab_path:
                for _p in self._project_exec_manager.get_all_projects():
                    if _p.file_path and _p.file_path == _tab_path:
                        _p.tab_reference = tab
                        _p.window_reference = self
                        _p.workflow = tab.workflow
                        if name and name not in ("Проект", tr("Новый проект"), "...", "…"):
                            _p.name = name
                        self._project_exec_manager.signals.project_updated.emit(_p.project_id)
                        break
        
        return tab

    def _current_project_tab(self) -> Optional[ProjectTab]:
        """Получить текущий активный ProjectTab."""
        if not hasattr(self, '_project_tabs'):
            return None
        idx = self._project_tabs.currentIndex()
        if idx < 0:
            return None
        widget = self._project_tabs.widget(idx)
        return widget if isinstance(widget, ProjectTab) else None

    def _on_tab_switched(self, idx: int):
        """Переключились на другой проект — переключаем активные ресурсы."""
        # ═══ CRITICAL FIX: Save current _is_modified to OLD tab BEFORE any switching ═══
        if hasattr(self, '_scene'):
            old_tab = self._current_project_tab()
            if old_tab is not None and isinstance(old_tab, ProjectTab):
                # Save the modification state of the tab we're leaving
                old_tab._modified = self._is_modified
                old_tab._project_root = getattr(self, '_project_root', '')
        
        tab = self._project_tabs.widget(idx)
        if not isinstance(tab, ProjectTab):
            return

        tab = self._project_tabs.widget(idx)
        if not isinstance(tab, ProjectTab):
            return
        # Гарантируем что _main_window всегда установлен
        tab.scene._main_window = self

        # ── Отключаем сигнал node_selected от СТАРОЙ сцены ──────────────
        if hasattr(self, '_scene') and self._scene is not tab.scene:
            try:
                self._scene.node_selected.disconnect(self._on_node_selected)
            except Exception:
                pass

        # Переключаем ссылки для совместимости со старым кодом
        self._scene = tab.scene
        self._view = tab.view
        self._history = tab._history

        # ── Подключаем node_selected НОВОЙ сцены ────────────────────────
        try:
            tab.scene.node_selected.disconnect(self._on_node_selected)
        except Exception:
            pass
        tab.scene.node_selected.connect(self._on_node_selected)

        # Обновляем миникарту под новую сцену/вид
        if hasattr(self, "_minimap") and self._minimap:
            self._minimap._main_view = tab.view
            self._minimap.setScene(tab.scene)
        # Передаём browser_manager текущего проекта в рантайм
        # НЕ трогаем runtime если проект уже запущен — у каждого запуска свой runtime
        if hasattr(self, "_runtime") and self._runtime:
            if not self._runtime.isRunning():
                self._runtime.project_browser_manager = tab.browser_manager

        # ── Переключаем workflow и переменные ──────────────────────────
        # ═══ КРИТИЧЕСКИ: синхронизируем workflow в ОБЕ стороны ═══
        if tab.workflow is None:
            # Новый таб без workflow — создаём и привязываем
            tab.workflow = AgentWorkflow()
            tab.scene.set_workflow(tab.workflow)
        self._workflow = tab.workflow
        # Принудительно привязываем workflow к сцене (на случай рассинхрона)
        tab.scene.set_workflow(self._workflow)
        if hasattr(self, '_vars_panel') and self._vars_panel and tab.workflow is not None:
            self._vars_panel._workflow = tab.workflow
            self._vars_panel._reload_variables()
            self._vars_panel._reload_notes()
            self._vars_panel._load_lists_tables_from_workflow()
            # ═══ Обновляем inline-панель Списки/Таблицы/Настройки для нового проекта ═══
            if getattr(self, '_lt_inline_expanded', False):
                self._refresh_lt_inline_chips()
            elif hasattr(self, '_lt_inline_panel'):
                # Обновляем даже если свёрнута — чтобы данные были актуальны при раскрытии
                self._refresh_lt_inline_chips()

        # ── Синхронизируем чекбокс закрытия браузера ───────────────────
        if hasattr(self, '_chk_close_browser_toolbar') and tab.workflow is not None:
            self._chk_close_browser_toolbar.blockSignals(True)
            self._chk_close_browser_toolbar.setChecked(
                getattr(tab.workflow, 'close_browser_on_finish', True)
            )
            self._chk_close_browser_toolbar.blockSignals(False)

        # ── Переключаем file_path и project_root ───────────────────────
        self._file_path = tab.project_path
        
        # ВАЖНО: восстанавливаем project_root ДО загрузки globals
        # project_root хранится ТОЛЬКО в tab._project_root, не в self!
        root_path = tab._project_root if tab._project_root else ""
        
        if hasattr(self, '_fld_working_dir'):
            self._fld_working_dir.blockSignals(True)
            self._fld_working_dir.setText(root_path)
            self._fld_working_dir.blockSignals(False)
        
        # ── Загружаем глобальные настройки проекта ─────────────────────
        # ВАЖНО: project_root уже установлен, _load_globals_from_workflow это увидит
        self._load_globals_from_workflow()

        # ── Переключаем skill_registry ─────────────────────────────────
        self._skill_registry = tab.skill_registry

        # ── Переключаем browser_panel на менеджер этого проекта ────────
        if hasattr(self, '_browser_panel') and self._browser_panel:
            self._browser_panel.set_manager(tab._base_browser_manager)
        self._browser_manager = tab._base_browser_manager

        # ── Сбрасываем панель свойств чтобы не показывала узел чужого проекта
        if hasattr(self, '_props') and self._props:
            self._props.set_node(None)
 
        # ═══ Обновляем debug-панель под runtime текущей вкладки ═══
        self._sync_debug_panel_to_tab(tab)
 
        # ═══ Восстанавливаем флаг изменений нового таба ═══
        # ВАЖНО: используем ИЛИ чтобы учесть оба источника изменений
        self._is_modified = tab._modified
        self._update_window_title()
    
    def _sync_debug_panel_to_tab(self, tab):
        """Обновить кнопки debug-панели под состояние runtime текущей вкладки."""
        if not hasattr(self, '_btn_dbg_start'):
            return
        
        rt = tab._runtime_thread if tab else None
        is_running = rt is not None and rt.isRunning()
        is_paused = rt is not None and getattr(rt, '_is_paused', False)
        
        # Кнопки запуска: доступны только если НЕ работает в этой вкладке
        self._btn_dbg_start.setEnabled(not is_running)
        self._btn_dbg_from_sel.setEnabled(not is_running)
        self._btn_dbg_sel_only.setEnabled(not is_running)
        self._btn_dbg_step_start.setEnabled(not is_running)
        
        # Кнопки управления: доступны только если работает
        self._btn_dbg_stop.setEnabled(is_running)
        self._btn_dbg_cont.setEnabled(is_paused)
        self._btn_dbg_step.setEnabled(is_paused)
        
        # Статус
        if is_running and is_paused:
            self._lbl_dbg_status.setText("⏸ Пауза")
            self._lbl_dbg_status.setStyleSheet("color: #E0AF68;")
        elif is_running:
            self._lbl_dbg_status.setText("▶ Выполняется")
            self._lbl_dbg_status.setStyleSheet("color: #9ECE6A;")
        else:
            self._lbl_dbg_status.setText("Готов")
            self._lbl_dbg_status.setStyleSheet("color: #7AA2F7;")
        
        # ═══ Галочка «Без анимации» синхронизируется с вкладкой ═══
        if hasattr(self, '_chk_deferred_render') and tab:
            self._chk_deferred_render.blockSignals(True)
            self._chk_deferred_render.setChecked(
                getattr(tab, '_deferred_rendering', False)
            )
            self._chk_deferred_render.blockSignals(False)
    
    def _close_project_tab(self, idx: int):
        tab = self._project_tabs.widget(idx)
        if isinstance(tab, ProjectTab):
            # ═══ Остановить debug-runtime вкладки если запущен ═══
            if tab._runtime_thread and tab._runtime_thread.isRunning():
                r = QMessageBox.question(
                    self, tr("Отладка работает"),
                    tr(f"В этой вкладке идёт выполнение проекта.\nОстановить и закрыть?"),
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.Cancel,
                )
                if r == QMessageBox.StandardButton.Cancel:
                    return
                tab._runtime_thread.stop()
                tab._runtime_thread.wait(3000)
 
            # Проверяем запущен ли проект в менеджере
            if hasattr(self, '_project_exec_manager') and self._project_exec_manager:
                for p in self._project_exec_manager.get_all_projects():
                    if p.tab_reference is tab and p.status == ProjectStatus.RUNNING:
                        r = QMessageBox.question(
                            self, "Проект выполняется!",
                            f"Проект '{p.name}' сейчас выполняется.\n"
                            "Остановить и закрыть?",
                            QMessageBox.StandardButton.Yes |
                            QMessageBox.StandardButton.Cancel,
                        )
                        if r == QMessageBox.StandardButton.Cancel:
                            return
                        self._project_exec_manager.stop_project(p.project_id)
                        break
 
            # Синхронизируем флаг: если это текущий таб — берём self._is_modified
            is_active_tab = (self._current_project_tab() is tab)
            tab_is_modified = tab._modified or (is_active_tab and self._is_modified)
            has_content = tab.workflow and (
                len(tab.workflow.nodes) > 0 or len(tab.workflow.edges) > 0
            )
            if tab_is_modified and has_content:
                tab_name = self._project_tabs.tabText(idx) or "Проект"
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(tr("Несохранённые изменения"))
                msg_box.setText(tr(f"Проект «{tab_name}» содержит несохранённые изменения."))
                msg_box.setInformativeText(tr("Сохранить перед закрытием?"))
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Save |
                    QMessageBox.StandardButton.Discard |
                    QMessageBox.StandardButton.Cancel
                )
                msg_box.setDefaultButton(QMessageBox.StandardButton.Save)
                msg_box.button(QMessageBox.StandardButton.Save).setText(tr("💾 Сохранить"))
                msg_box.button(QMessageBox.StandardButton.Discard).setText(tr("🗑️ Не сохранять"))
                msg_box.button(QMessageBox.StandardButton.Cancel).setText(tr("❌ Отмена"))
                r = msg_box.exec()
                if r == QMessageBox.StandardButton.Cancel:
                    return
                if r == QMessageBox.StandardButton.Save:
                    # Переключаемся на таб чтобы _save_workflow работал корректно
                    self._project_tabs.setCurrentIndex(idx)
                    self._save_workflow()
            
            # Удаляем из менеджера проектов
            if hasattr(self, '_project_exec_manager') and self._project_exec_manager:
                for p in self._project_exec_manager.get_all_projects():
                    if p.tab_reference is tab:
                        self._project_exec_manager.remove_project(p.project_id)
                        break
            
            tab.close_all_browsers()
        self._project_tabs.removeTab(idx)
        if self._project_tabs.count() == 0:
            self._add_project_tab()


class BrowserActionRecorder(QObject):
    """
    Перехватчик действий браузера для режима записи.
    Подключается к BrowserInstance и слушает события JS.
    """
    action_recorded = pyqtSignal(str, dict)

    def __init__(self, on_action=None, parent=None):
        super().__init__(parent)
        self._on_action = on_action
        self._active = False
        self._instances = []

    def start(self):
        """Подключиться ко всем активным инстансам браузера и начать запись."""
        self._active = True
        try:
            from constructor.browser_module import BrowserManager
            mgr = BrowserManager.get()
            if mgr:
                for inst in mgr.get_all_instances():
                    self._inject_recorder_script(inst)
                    self._instances.append(inst)
        except Exception as e:
            print(f"BrowserRecorder start error: {e}")

    def stop(self):
        self._active = False
        for inst in self._instances:
            try:
                self._remove_recorder_script(inst)
            except Exception:
                pass
        self._instances.clear()

    def _inject_recorder_script(self, inst):
        """Инжектируем JS-скрипт записи в браузер."""
        js = """
(function() {
    if (window.__sherlock_recorder_active) return;
    window.__sherlock_recorder_active = true;

    function sendAction(type, data) {
        var msg = JSON.stringify({__sherlock_rec: true, type: type, data: data});
        window.__sherlock_last_action = msg;
    }

    function getSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.name) return '[name="' + el.name + '"]';
        var path = [];
        while (el && el.nodeType === Node.ELEMENT_NODE) {
            var idx = Array.from(el.parentNode.children).indexOf(el) + 1;
            path.unshift(el.tagName.toLowerCase() + ':nth-child(' + idx + ')');
            el = el.parentNode;
        }
        return path.join(' > ');
    }

    document.addEventListener('click', function(e) {
        sendAction('click', {
            selector: getSelector(e.target),
            x: e.clientX, y: e.clientY,
            text: e.target.innerText ? e.target.innerText.slice(0, 50) : ''
        });
    }, true);

    document.addEventListener('change', function(e) {
        if (e.target.value !== undefined) {
            sendAction('input', {
                selector: getSelector(e.target),
                value: e.target.type === 'password' ? '***' : e.target.value
            });
        }
    }, true);

    document.addEventListener('keydown', function(e) {
        if (['Enter','Tab','Escape','F5'].includes(e.key)) {
            sendAction('key', {key: e.key, selector: getSelector(e.target)});
        }
    }, true);

    window.addEventListener('popstate', function() {
        sendAction('navigate', {url: location.href});
    });
})();
        """
        try:
            inst.page().runJavaScript(js)
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(lambda: self._poll_actions(inst))
            self._poll_timer.start(300)
        except Exception as e:
            print(f"Inject recorder script error: {e}")

    def _poll_actions(self, inst):
        """Читаем последнее записанное действие из браузера."""
        if not self._active:
            return
        try:
            def _handle_result(result):
                if result and isinstance(result, str):
                    import json
                    try:
                        data = json.loads(result)
                        if data.get('__sherlock_rec'):
                            inst.page().runJavaScript("window.__sherlock_last_action = null;")
                            if self._on_action:
                                self._on_action(data['type'], data.get('data', {}))
                    except Exception:
                        pass
            inst.page().runJavaScript(
                "window.__sherlock_last_action || null;",
                _handle_result
            )
        except Exception:
            pass

    def _remove_recorder_script(self, inst):
        try:
            inst.page().runJavaScript(
                "window.__sherlock_recorder_active = false; "
                "window.__sherlock_last_action = null;"
            )
            if hasattr(self, '_poll_timer'):
                self._poll_timer.stop()
        except Exception:
            pass


class _ImageRegionSelector(QDialog):
    """Диалог выбора прямоугольной области на скриншоте браузера."""

    def __init__(self, screenshot_b64: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🖼 Выделите область для клика")
        self.setModal(True)
        self.resize(900, 650)
        self._region_b64 = ""

        import base64
        from PyQt6.QtGui import QPixmap
        data = base64.b64decode(screenshot_b64)
        self._full_pm = QPixmap()
        self._full_pm.loadFromData(data)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        help_lbl = QLabel(
            "Зажмите ЛКМ и выделите область — именно этот фрагмент будет шаблоном для клика по картинке."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #7AA2F7; font-size: 11px;")
        layout.addWidget(help_lbl)

        # Canvas с изображением
        self._canvas = _RegionCanvas(self._full_pm)
        from PyQt6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidget(self._canvas)
        sa.setWidgetResizable(False)
        layout.addWidget(sa, 1)

        # Инфо о выделении
        self._info_lbl = QLabel("Область не выбрана")
        self._info_lbl.setStyleSheet("color: #9ECE6A; font-size: 11px;")
        layout.addWidget(self._info_lbl)
        self._canvas.region_selected.connect(self._on_region)

        # Кнопки
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("✅ Использовать выделение")
        btn_ok.setEnabled(False)
        btn_ok.setStyleSheet(
            "QPushButton { background: #1a3a1a; color: #9ECE6A; border: 1px solid #9ECE6A; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:enabled:hover { background: #9ECE6A; color: #000; }"
            "QPushButton:disabled { color: #565f89; border-color: #565f89; }"
        )
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setStyleSheet(
            "QPushButton { background: #1a1a2a; color: #f7768e; border: 1px solid #f7768e; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #f7768e; color: #000; }"
        )
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self._btn_ok = btn_ok
        btn_ok.clicked.connect(self._accept_region)
        btn_cancel.clicked.connect(self.reject)

    def _on_region(self, rect):
        if rect.isValid() and rect.width() > 4 and rect.height() > 4:
            self._info_lbl.setText(
                f"Выделено: x={rect.x()}, y={rect.y()}, "
                f"w={rect.width()}, h={rect.height()}"
            )
            self._btn_ok.setEnabled(True)
        else:
            self._info_lbl.setText("Область не выбрана")
            self._btn_ok.setEnabled(False)

    def _accept_region(self):
        rect = self._canvas.get_selection_rect()
        if rect and rect.isValid() and rect.width() > 4 and rect.height() > 4:
            import base64
            from PyQt6.QtCore import QByteArray, QBuffer, QIODeviceBase
            cropped = self._full_pm.copy(rect)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODeviceBase.OpenModeFlag.WriteOnly)
            cropped.save(buf, "PNG")
            buf.close()
            self._region_b64 = base64.b64encode(bytes(ba)).decode()
            self.accept()

    def get_region_b64(self) -> str:
        return self._region_b64


class _RegionCanvas(QWidget):
    """Canvas с поддержкой выделения прямоугольной области мышью."""
    from PyQt6.QtCore import pyqtSignal
    region_selected = pyqtSignal(object)

    def __init__(self, pixmap: 'QPixmap', parent=None):
        super().__init__(parent)
        self._pm = pixmap
        self._start = None
        self._end = None
        self._selecting = False
        self.setFixedSize(pixmap.width(), pixmap.height())
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)
        if self._start and self._end:
            rect = self._get_normalized_rect()
            # Затемнение всего кроме выделения
            overlay_color = QColor(0, 0, 0, 100)
            p.fillRect(self.rect(), overlay_color)
            # Чистим выделенную область
            p.drawPixmap(rect, self._pm, rect)
            # Рамка выделения
            p.setPen(QPen(QColor('#7AA2F7'), 2, Qt.PenStyle.SolidLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            # Угловые маркеры
            p.setBrush(QColor('#7AA2F7'))
            for corner in [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]:
                p.drawEllipse(corner, 4, 4)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.pos()
            self._end = e.pos()
            self._selecting = True

    def mouseMoveEvent(self, e):
        if self._selecting:
            self._end = e.pos()
            self.update()
            self.region_selected.emit(self._get_normalized_rect())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._end = e.pos()
            self._selecting = False
            self.update()
            self.region_selected.emit(self._get_normalized_rect())

    def _get_normalized_rect(self):
        from PyQt6.QtCore import QRect
        if not self._start or not self._end:
            return QRect()
        x1, y1 = min(self._start.x(), self._end.x()), min(self._start.y(), self._end.y())
        x2, y2 = max(self._start.x(), self._end.x()), max(self._start.y(), self._end.y())
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def get_selection_rect(self):
        return self._get_normalized_rect()


# ══════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА (опционально)
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = AgentConstructorWindow()
    window.show()
    sys.exit(app.exec())