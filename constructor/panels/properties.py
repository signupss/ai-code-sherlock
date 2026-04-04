"""Панель свойств ноды."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QScrollArea, QTabWidget, QListWidget, QPushButton, QLabel,
    QGroupBox
)

from ..constants import get_node_category, AI_AGENT_TYPES, _AGENT_COLORS
from services.agent_models import AgentType, AgentNode
from services.skill_registry import SkillRegistry
from ui.i18n import tr

try:
    from ui.theme_manager import get_color
except ImportError:
    def get_color(k): return "#CDD6F4"

class NodePropertiesPanel(QScrollArea):
    """Right panel — edit selected node properties."""

    node_changed = pyqtSignal()

    def __init__(self, skill_registry: SkillRegistry, parent=None):
        super().__init__(parent)
        self._skills = skill_registry
        self._node: AgentNode | None = None
        self._main_window = parent  # ← сохраняем ДО перепривязки Qt-parent
        self.setWidgetResizable(True)
        self.setMinimumWidth(340)
        self.setMaximumWidth(600)
        self._build_ui()

    def _build_ui(self):
        """Build the properties panel UI"""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self._tabs = QTabWidget()
        parent = self._main_window
        
        if parent and hasattr(parent, '_build_basic_tab'):
            self._tabs.addTab(parent._build_basic_tab(), tr("Базовые"))
            if hasattr(parent, '_build_models_tab'):
                self._tabs.addTab(parent._build_models_tab(), tr("Модели"))
            if hasattr(parent, '_build_tools_tab'):
                self._tabs.addTab(parent._build_tools_tab(), tr("Тулзы"))
            if hasattr(parent, '_build_execution_tab'):
                self._tabs.addTab(parent._build_execution_tab(), tr("Выполнение"))
            if hasattr(parent, '_build_automation_tab'):
                self._tabs.addTab(parent._build_automation_tab(), tr("Авто"))
                
            # Прокидываем ссылки на поля в self, чтобы работал метод _populate()
            for attr in ['_fld_name', '_fld_desc', '_cmb_type', '_fld_model', '_fld_vision', 
                         '_spn_temp', '_spn_timeout', '_txt_system', '_txt_user', 
                         '_chk_verify', '_cmb_verify_mode', '_txt_verify_prompt', '_chk_verify_strict', '_cmb_verify_model',
                         '_fld_verifier', '_skills_list',
                         '_tool_checkboxes', '_tool_widgets', '_all_tools_config',
                         '_cmb_exec_mode', '_chk_breakpoint', '_chk_human_loop', '_chk_backup_before_node',
                         '_chk_auto_test', '_chk_auto_patch', '_chk_auto_improve', '_spn_max_iter', '_chk_self_modify',
                         # ↓ ДОБАВЛЕНО: копируем snippet-поля чтобы _populate мог блокировать их сигналы
                         '_snippet_fld_name', '_snippet_fld_desc', '_snippet_fld_comment', '_snippet_lbl_type']:
                if hasattr(parent, attr):
                    setattr(self, attr, getattr(parent, attr))

                    # === МЕТОД _on_change ДОЛЖЕН БЫТЬ ОПРЕДЕЛЁН ДО ПОДКЛЮЧЕНИЯ СИГНАЛОВ! ===
        
        # Сначала определяем метод _on_change как локальную функцию и привязываем к self
        def _on_change(*_):
            if getattr(self, '_is_updating', False):
                return
            if not self._node:
                return
            n = self._node
            
            # Определяем категорию
            cat = get_node_category(n.agent_type)
            
            parent = self._main_window
            
            if cat == 'note':
                # Для заметок — берём из note-полей
                if hasattr(parent, '_note_fld_title'):
                    n.name = parent._note_fld_title.text()
                    n.note_content = parent._note_txt_content.toPlainText()
                return  # Заметки не имеют остальных настроек
            elif cat == 'snippet':
                # Для сниппетов — берём имя/описание из сниппет-полей
                if hasattr(parent, '_snippet_fld_name'):
                    n.name = parent._snippet_fld_name.text()
                    n.description = parent._snippet_fld_desc.toPlainText()
                # Синхронизируем код из встроенного редактора
                if hasattr(parent, '_snippet_code_editor'):
                    n.user_prompt_template = parent._snippet_code_editor.toPlainText()
            else:
                # Для AI-агентов — стандартная логика
                n.name = self._fld_name.text()
                n.description = self._fld_desc.toPlainText()
                n.agent_type = self._cmb_type.currentData() or AgentType.CUSTOM
                n.model_id = self._fld_model.currentData() or ""
                n.vision_model_id = self._fld_vision.currentData() or ""
                n.temperature = self._spn_temp.value() / 10.0
                n.timeout_seconds = self._spn_timeout.value()
                n.system_prompt = self._txt_system.toPlainText()
                n.user_prompt_template = self._txt_user.toPlainText()
                n.auto_verify = self._chk_verify.isChecked()
                n.verifier_agent_id = self._fld_verifier.text()
                n.color = _AGENT_COLORS.get(n.agent_type, "#565f89")
                
                # Сохраняем тулзы с per-node настройками!
                if hasattr(self, '_tool_checkboxes'):
                    enabled_tools = []
                    tool_configs = {}
                    
                    for t_id, group in self._tool_checkboxes.items():
                        if group.isChecked():
                            enabled_tools.append(t_id)
                            # Собираем параметры для этого тулза
                            params = {}
                            # Берем конфиг напрямую из self
                            all_tools_config = getattr(self, '_all_tools_config', {})
                            cfg = all_tools_config.get(t_id, {})
                            for param_id in cfg.get('params', {}).keys():
                                widget_key = f"{t_id}.{param_id}"
                                if hasattr(self, '_tool_widgets') and widget_key in self._tool_widgets:
                                    widget = self._tool_widgets[widget_key]
                                    if isinstance(widget, QCheckBox):
                                        params[param_id] = widget.isChecked()
                                    elif isinstance(widget, QSpinBox):
                                        params[param_id] = widget.value()
                                    elif isinstance(widget, QLineEdit):
                                        params[param_id] = widget.text()
                            tool_configs[t_id] = {"enabled": True, "params": params}
                    
                    n.available_tools = enabled_tools
                    n.tool_configs = tool_configs  # Сохраняем per-node конфиг!
                
                # Сохраняем настройки выполнения
                if hasattr(self, '_cmb_exec_mode'): n.orchestration_mode = self._cmb_exec_mode.currentData() or "sequential"
                if hasattr(self, '_chk_breakpoint'): n.breakpoint_enabled = self._chk_breakpoint.isChecked()
                if hasattr(self, '_chk_human_loop'): n.human_in_loop = self._chk_human_loop.isChecked()
                if hasattr(self, '_chk_backup_before_node'): n.backup_before_node = self._chk_backup_before_node.isChecked()
                if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
                
                # Сохраняем настройки автоматизации
                if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
                if hasattr(self, '_chk_auto_patch'): n.auto_patch = self._chk_auto_patch.isChecked()
                if hasattr(self, '_chk_auto_improve'): n.auto_improve = self._chk_auto_improve.isChecked()
                if hasattr(self, '_spn_max_iter'): n.max_iterations = self._spn_max_iter.value()
                if hasattr(self, '_chk_self_modify'): n.self_modify = self._chk_self_modify.isChecked()
                
                self.node_changed.emit()
        
        # Привязываем метод к экземпляру
        self._on_change = _on_change
        
        # Теперь подключаем сигналы — метод уже существует!
        if hasattr(self, '_fld_name'): self._fld_name.textChanged.connect(self._on_change)
        if hasattr(self, '_fld_desc'): self._fld_desc.textChanged.connect(self._on_change)
        if hasattr(self, '_cmb_type'): self._cmb_type.currentIndexChanged.connect(self._on_change)
        if hasattr(self, '_fld_model'): self._fld_model.currentIndexChanged.connect(self._on_change)
        if hasattr(self, '_fld_vision'): self._fld_vision.currentIndexChanged.connect(self._on_change)
        if hasattr(self, '_spn_temp'): self._spn_temp.valueChanged.connect(self._on_change)
        if hasattr(self, '_spn_timeout'): self._spn_timeout.valueChanged.connect(self._on_change)
        if hasattr(self, '_txt_system'): self._txt_system.textChanged.connect(self._on_change)
        if hasattr(self, '_txt_user'): self._txt_user.textChanged.connect(self._on_change)
        if hasattr(self, '_chk_verify'): self._chk_verify.stateChanged.connect(self._on_change)
        if hasattr(self, '_fld_verifier'): self._fld_verifier.textChanged.connect(self._on_change)
        
        # Подключаем сигналы для новых вкладок (Тулзы, Выполнение, Авто)
        if hasattr(self, '_tool_checkboxes'):
            for chk in self._tool_checkboxes.values():
                chk.toggled.connect(self._on_change)
        # ДОБАВЛЕНО: Привязка сигналов внутренних параметров тулзов
        if hasattr(self, '_tool_widgets'):
            for widget in self._tool_widgets.values():
                if isinstance(widget, QCheckBox):
                    widget.stateChanged.connect(self._on_change)
                elif isinstance(widget, QSpinBox):
                    widget.valueChanged.connect(self._on_change)
                elif isinstance(widget, QLineEdit):
                    widget.textChanged.connect(self._on_change)
        if hasattr(self, '_cmb_exec_mode'): self._cmb_exec_mode.currentIndexChanged.connect(self._on_change)
        if hasattr(self, '_chk_breakpoint'): self._chk_breakpoint.stateChanged.connect(self._on_change)
        if hasattr(self, '_chk_human_loop'): self._chk_human_loop.stateChanged.connect(self._on_change)
        if hasattr(self, '_chk_backup_before_node'): self._chk_backup_before_node.stateChanged.connect(self._on_change)
        if hasattr(self, '_chk_auto_test'): self._chk_auto_test.stateChanged.connect(self._on_change)
        if hasattr(self, '_chk_auto_patch'): self._chk_auto_patch.stateChanged.connect(self._on_change)
        if hasattr(self, '_chk_auto_improve'): self._chk_auto_improve.stateChanged.connect(self._on_change)
        if hasattr(self, '_spn_max_iter'): self._spn_max_iter.valueChanged.connect(self._on_change)
        if hasattr(self, '_chk_self_modify'): self._chk_self_modify.stateChanged.connect(self._on_change)
                    
        layout.addWidget(self._tabs)
        self.setWidget(content)
    
    def _capture_node_state(self, node: AgentNode) -> dict:
        """Захват текущего состояния ноды для undo"""
        return {
            'name': node.name,
            'description': node.description,
            'agent_type': node.agent_type,
            'model_id': node.model_id,
            'vision_model_id': getattr(node, 'vision_model_id', ''),
            'temperature': node.temperature,
            'timeout_seconds': node.timeout_seconds,
            'system_prompt': node.system_prompt,
            'user_prompt_template': node.user_prompt_template,
            'skill_ids': node.skill_ids.copy(),
            'auto_verify': getattr(node, 'auto_verify', False),
            'verifier_agent_id': getattr(node, 'verifier_agent_id', ''),
        }
    
    def _restore_node_state(self, node: AgentNode, state: dict):
        """Восстановление состояния ноды из snapshot"""
        for key, val in state.items():
            setattr(node, key, val)
        self._populate()  # Обновляем UI
        self.node_changed.emit()
        if self._main_window:
            self._main_window._scene.update()
    
    def _commit_property_change(self):
        """Сохраняет изменения свойств в историю"""
        if not self._node or not hasattr(self, '_last_snapshot'):
            return
        
        current_state = self._capture_node_state(self._node)
        if current_state != self._last_snapshot:
            old_state = self._last_snapshot
            node = self._node
            
            # execute_fn = redo (применить изменение), undo_fn = отменить (вернуть старое)
            old_snap = old_state   # захват в замыкание
            new_snap = current_state
            self._main_window._history.push(
                lambda n=node, s=new_snap: self._restore_node_state(n, s),
                lambda n=node, s=old_snap: self._restore_node_state(n, s),
                f"Изменение {node.name}"
            )
            self._last_snapshot = current_state
            self._main_window._mark_modified_from_props()
    
    def _apply_properties(self):
        """Применить текущие значения из виджетов к объекту ноды."""
        n = self._node
        if not n:
            return

        # 1. Сохраняем базовые настройки
        if hasattr(self, '_chk_breakpoint'): n.breakpoint_enabled = self._chk_breakpoint.isChecked()
        if hasattr(self, '_chk_human_loop'): n.human_in_loop = self._chk_human_loop.isChecked()
        if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
        if hasattr(self, '_chk_auto_patch'): n.auto_patch = self._chk_auto_patch.isChecked()
        if hasattr(self, '_chk_auto_improve'): n.auto_improve = self._chk_auto_improve.isChecked()
        if hasattr(self, '_spn_max_iter'): n.max_iterations = self._spn_max_iter.value()
        if hasattr(self, '_chk_self_modify'): n.self_modify = self._chk_self_modify.isChecked()
        if hasattr(self, '_cmb_exec_mode'): n.orchestration_mode = self._cmb_exec_mode.currentData()

        # 2. Сохраняем специфические поля сниппетов
        if hasattr(self, '_snippet_widgets'):
            conf = getattr(n, 'snippet_config', {})
            for key, widget in self._snippet_widgets.items():
                if isinstance(widget, QLineEdit):
                    conf[key] = widget.text()
                elif isinstance(widget, QTextEdit) or isinstance(widget, QPlainTextEdit):
                    conf[key] = widget.toPlainText()
                elif isinstance(widget, QComboBox):
                    conf[key] = widget.currentData() or widget.currentText()
                elif isinstance(widget, QCheckBox):
                    conf[key] = widget.isChecked()
                elif isinstance(widget, QSpinBox):
                    conf[key] = widget.value()
                elif isinstance(widget, QTableWidget):
                    # Важно для Switch: сохраняем данные таблицы (Cases)
                    if key == 'cases':
                        rows = []
                        for i in range(widget.rowCount()):
                            rows.append(widget.item(i, 0).text() if widget.item(i, 0) else "")
                        conf[key] = rows
            n.snippet_config = conf
            
            # ═══ Обновляем размер Switch-ноды при изменении cases ═══
            if n.agent_type == AgentType.SWITCH and self._main_window:
                scene = getattr(self._main_window, '_scene', None)
                if scene and hasattr(scene, 'get_node_item'):
                    item = scene.get_node_item(n.id)
                    if item:
                        item.update_dynamic_size()
    
    def set_node(self, node: AgentNode | None):
        """Установить текущую ноду для редактирования. Сохраняет предыдущую ноду перед переключением."""
        # ═══ Защита: если node None, просто сбрасываем ═══
        if node is None:
            # ═══ КРИТИЧНО: Сначала сохраняем текущую ноду если есть ═══
            if self._node is not None:
                self._sync_current_node_to_data()
            self._node = None
            self._populate()
            return
        
        # ═══ КРИТИЧНО: сохранить конфиг СТАРОЙ ноды ДО смены на новую ═══
        old_node = self._node
        if old_node is not None and old_node != node:
            # ═══ КРИТИЧНО: Принудительный flush перед переключением ═══
            self._sync_current_node_to_data()
            
            # ═══ ЯВНОЕ СОХРАНЕНИЕ ПОЛЕЙ AI-АГЕНТА (т.к. _on_change не всегда успевает сработать) ═══
            if get_node_category(old_node.agent_type) == 'ai':
                # Используем parent (main_window) для доступа к полям, т.к. они созданы там
                parent = self._main_window  # <-- ИСПРАВЛЕНИЕ: определяем parent
                if hasattr(parent, '_fld_name') and parent._fld_name is not None:
                    old_node.name = parent._fld_name.text()
                if hasattr(parent, '_fld_desc') and parent._fld_desc is not None:
                    old_node.description = parent._fld_desc.toPlainText()
                if hasattr(self, '_txt_user') and self._txt_user is not None:
                    old_node.user_prompt_template = self._txt_user.toPlainText()
                if hasattr(self, '_txt_system') and self._txt_system is not None:
                    old_node.system_prompt = self._txt_system.toPlainText()
                if hasattr(self, '_cmb_type') and self._cmb_type is not None:
                    old_node.agent_type = self._cmb_type.currentData() or old_node.agent_type
                if hasattr(self, '_fld_model') and self._fld_model is not None:
                    old_node.model_id = self._fld_model.currentData() or ""
                if hasattr(self, '_fld_vision') and self._fld_vision is not None:
                    old_node.vision_model_id = self._fld_vision.currentData() or ""
                if hasattr(self, '_spn_temp') and self._spn_temp is not None:
                    old_node.temperature = self._spn_temp.value() / 10.0
                if hasattr(self, '_spn_timeout') and self._spn_timeout is not None:
                    old_node.timeout_seconds = self._spn_timeout.value()
                if hasattr(parent, '_fld_comment') and parent._fld_comment is not None:
                    old_node.comment = parent._fld_comment.text()
                # Verification fields
                if hasattr(self, '_chk_verify') and self._chk_verify is not None:
                    old_node.verification_enabled = self._chk_verify.isChecked()
                if hasattr(self, '_cmb_verify_mode') and self._cmb_verify_mode is not None:
                    old_node.verification_mode = self._cmb_verify_mode.currentData() or 'self_check'
                if hasattr(self, '_txt_verify_prompt') and self._txt_verify_prompt is not None:
                    old_node.verification_prompt = self._txt_verify_prompt.toPlainText()
                if hasattr(self, '_chk_verify_strict') and self._chk_verify_strict is not None:
                    old_node.verification_strict = self._chk_verify_strict.isChecked()
                if hasattr(self, '_cmb_verify_model') and self._cmb_verify_model is not None:
                    old_node.verification_model_id = self._cmb_verify_model.currentData() or ''
            
            # Принудительно сохраняем код из редактора если он есть
            parent = self._main_window  # <-- ИСПРАВЛЕНИЕ
            if parent and hasattr(parent, '_snippet_code_editor') and parent._snippet_code_editor:
                if old_node:
                    if not hasattr(old_node, 'snippet_config') or old_node.snippet_config is None:
                        old_node.snippet_config = {}
                    old_node.snippet_config['_code'] = parent._snippet_code_editor.toPlainText()
                    old_node.user_prompt_template = parent._snippet_code_editor.toPlainText()
            # Принудительный flush всех виджетов
            if parent and hasattr(parent, '_flush_snippet_config_to_node'):
                parent._flush_snippet_config_to_node()
            # Дополнительно сохраняем код из редактора если он есть
            if parent and hasattr(parent, '_snippet_code_editor') and parent._snippet_code_editor:
                code = parent._snippet_code_editor.toPlainText()
                if not hasattr(old_node, 'snippet_config'):
                    old_node.snippet_config = {}
                old_node.snippet_config['_code'] = code
                old_node.user_prompt_template = code
        
        self._node = node
        self._populate()
    
    def _sync_current_node_to_data(self):
        """Принудительная синхронизация текущих данных из UI в ноду перед переключением."""
        if self._node is None:
            return
            
        n = self._node
        cat = get_node_category(n.agent_type)
        parent = self._main_window
        
        try:
            if cat == 'snippet':
                # ═══ Синхронизируем имя и описание ═══
                if hasattr(parent, '_snippet_fld_name') and parent._snippet_fld_name is not None:
                    try:
                        n.name = parent._snippet_fld_name.text()
                    except RuntimeError:
                        pass
                if hasattr(parent, '_snippet_fld_desc') and parent._snippet_fld_desc is not None:
                    try:
                        n.description = parent._snippet_fld_desc.toPlainText()
                    except RuntimeError:
                        pass
                        
                # ═══ КРИТИЧНО: Принудительный flush snippet config ═══
                if hasattr(parent, '_flush_snippet_config_to_node'):
                    parent._flush_snippet_config_to_node()
                    
            elif cat == 'ai':
                # ═══ Базовые поля ═══
                if hasattr(self, '_fld_name') and self._fld_name is not None:
                    try:
                        n.name = self._fld_name.text()
                    except RuntimeError:
                        pass
                if hasattr(self, '_fld_desc') and self._fld_desc is not None:
                    try:
                        n.description = self._fld_desc.toPlainText()
                    except RuntimeError:
                        pass
                if hasattr(self, '_txt_system') and self._txt_system is not None:
                    try:
                        n.system_prompt = self._txt_system.toPlainText()
                    except RuntimeError:
                        pass
                if hasattr(self, '_txt_user') and self._txt_user is not None:
                    try:
                        n.user_prompt_template = self._txt_user.toPlainText()
                    except RuntimeError:
                        pass
                if hasattr(self, '_cmb_type') and self._cmb_type is not None:
                    try:
                        n.agent_type = self._cmb_type.currentData() or n.agent_type
                    except RuntimeError:
                        pass
                # ═══ Модели ═══
                if hasattr(self, '_fld_model') and self._fld_model is not None:
                    try:
                        n.model_id = self._fld_model.currentData() or ""
                    except RuntimeError:
                        pass
                if hasattr(self, '_fld_vision') and self._fld_vision is not None:
                    try:
                        n.vision_model_id = self._fld_vision.currentData() or ""
                    except RuntimeError:
                        pass
                # ═══ Температура / таймаут ═══
                if hasattr(self, '_spn_temp') and self._spn_temp is not None:
                    try:
                        n.temperature = self._spn_temp.value() / 10.0
                    except RuntimeError:
                        pass
                if hasattr(self, '_spn_timeout') and self._spn_timeout is not None:
                    try:
                        n.timeout_seconds = self._spn_timeout.value()
                    except RuntimeError:
                        pass
                # ═══ Настройки выполнения ═══
                if hasattr(self, '_cmb_exec_mode') and self._cmb_exec_mode is not None:
                    try:
                        n.orchestration_mode = self._cmb_exec_mode.currentData() or 'sequential'
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_breakpoint') and self._chk_breakpoint is not None:
                    try:
                        n.breakpoint_enabled = self._chk_breakpoint.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_human_loop') and self._chk_human_loop is not None:
                    try:
                        n.human_in_loop = self._chk_human_loop.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_auto_test') and self._chk_auto_test is not None:
                    try:
                        n.auto_test = self._chk_auto_test.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_auto_patch') and self._chk_auto_patch is not None:
                    try:
                        n.auto_patch = self._chk_auto_patch.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_auto_improve') and self._chk_auto_improve is not None:
                    try:
                        n.auto_improve = self._chk_auto_improve.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_spn_max_iter') and self._spn_max_iter is not None:
                    try:
                        n.max_iterations = self._spn_max_iter.value()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_self_modify') and self._chk_self_modify is not None:
                    try:
                        n.self_modify = self._chk_self_modify.isChecked()
                    except RuntimeError:
                        pass
                # ═══ Верификация ═══
                if hasattr(self, '_chk_verify') and self._chk_verify is not None:
                    try:
                        n.verification_enabled = self._chk_verify.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_cmb_verify_mode') and self._cmb_verify_mode is not None:
                    try:
                        n.verification_mode = self._cmb_verify_mode.currentData() or 'self_check'
                    except RuntimeError:
                        pass
                if hasattr(self, '_txt_verify_prompt') and self._txt_verify_prompt is not None:
                    try:
                        n.verification_prompt = self._txt_verify_prompt.toPlainText()
                    except RuntimeError:
                        pass
                if hasattr(self, '_chk_verify_strict') and self._chk_verify_strict is not None:
                    try:
                        n.verification_strict = self._chk_verify_strict.isChecked()
                    except RuntimeError:
                        pass
                if hasattr(self, '_cmb_verify_model') and self._cmb_verify_model is not None:
                    try:
                        n.verification_model_id = self._cmb_verify_model.currentData() or ''
                    except RuntimeError:
                        pass
                # ═══ Комментарий ═══
                if hasattr(parent, '_fld_comment') and parent._fld_comment is not None:
                    try:
                        n.comment = parent._fld_comment.text()
                    except RuntimeError:
                        pass
                        
            elif cat == 'note':
                if hasattr(parent, '_note_fld_title') and parent._note_fld_title is not None:
                    try:
                        n.name = parent._note_fld_title.text()
                    except RuntimeError:
                        pass
                        
        except Exception as e:
            print(f"[SYNC ERROR] {e}")
            import traceback
            traceback.print_exc()
    
    def _populate(self):
        self._is_updating = True
        n = self._node
        
        # ── Защита от None ──
        if n is None:
            self._is_updating = False
            return
        
        # ── Сразу скрываем все группы, покажем нужные ниже ──
        parent = self._main_window
        if parent:
            for attr in ('_ai_settings_group', '_snippet_common_group',
                     '_snippet_group', '_note_settings_group', '_start_settings_group'):
                grp = getattr(parent, attr, None)
                if grp:
                    grp.setVisible(False)

        # ── Блокируем сигналы на КАЖДОМ виджете ──
        all_widgets = [self._fld_name, self._fld_desc, self._cmb_type,
                       self._fld_model, self._fld_vision, self._spn_temp,
                       self._spn_timeout, self._txt_system, self._txt_user,
                       self._chk_verify, self._fld_verifier]
        
        # Добавляем сниппет-виджеты если есть
        if hasattr(self, '_snippet_fld_name'):
            all_widgets.extend([self._snippet_fld_name, self._snippet_fld_desc])
        if hasattr(self, '_snippet_fld_comment'):
            all_widgets.append(self._snippet_fld_comment)
        
        for w in all_widgets:
            if w:
                w.blockSignals(True)

        try:
            if not n:
                # Сброс обеих панелей
                self._fld_name.clear()
                self._fld_desc.clear()
                self._cmb_type.setCurrentIndex(0)
                
                if hasattr(self, '_snippet_fld_name'):
                    self._snippet_fld_name.clear()
                    self._snippet_fld_desc.clear()
                    self._snippet_lbl_type.clear()
                
                # Скрываем обе группы
                if hasattr(self._main_window, '_ai_settings_group'):
                    self._main_window._ai_settings_group.setVisible(False)
                if hasattr(self._main_window, '_snippet_common_group'):
                    self._main_window._snippet_common_group.setVisible(False)
                return

            # Определяем категорию
            cat = get_node_category(n.agent_type)
            is_snippet = cat == 'snippet'
            is_note = cat == 'note'
            is_ai = cat == 'ai'
            
            parent = self._main_window
            if hasattr(parent, '_ai_settings_group') and hasattr(parent, '_snippet_common_group'):
                parent._ai_settings_group.setVisible(is_ai)
                parent._snippet_common_group.setVisible(is_snippet)
                # Показать/скрыть панель заметки
                if hasattr(parent, '_note_settings_group'):
                    parent._note_settings_group.setVisible(is_note)
                
                is_start = (n.agent_type == AgentType.PROJECT_START)

                if is_start:
                    # Показываем панель старта вместо заметки
                    if hasattr(parent, '_start_settings_group'):
                        parent._start_settings_group.setVisible(True)
                    cfg = getattr(n, 'snippet_config', {}) or {}
                    if hasattr(parent, '_start_fld_heading'):
                        parent._start_fld_heading.blockSignals(True)
                        parent._start_fld_heading.setText(n.name)
                        parent._start_fld_heading.blockSignals(False)
                    if hasattr(parent, '_start_fld_desc'):
                        parent._start_fld_desc.blockSignals(True)
                        parent._start_fld_desc.setText(n.description or '')
                        parent._start_fld_desc.blockSignals(False)
                    if hasattr(parent, '_start_cmb_mode'):
                        parent._start_cmb_mode.blockSignals(True)
                        idx = parent._start_cmb_mode.findData(cfg.get('start_mode', 'simple'))
                        parent._start_cmb_mode.setCurrentIndex(idx if idx >= 0 else 0)
                        parent._start_cmb_mode.blockSignals(False)
                    if hasattr(parent, '_start_txt_prompt'):
                        parent._start_txt_prompt.blockSignals(True)
                        parent._start_txt_prompt.setPlainText(cfg.get('start_prompt', ''))
                        parent._start_txt_prompt.blockSignals(False)
                        parent._start_txt_prompt.setVisible(cfg.get('start_mode', 'simple') == 'with_model')
                    if hasattr(parent, '_start_prompt_label'):
                        parent._start_prompt_label.setVisible(cfg.get('start_mode', 'simple') == 'with_model')
                    if hasattr(parent, '_start_chk_reset_vars'):
                        parent._start_chk_reset_vars.blockSignals(True)
                        parent._start_chk_reset_vars.setChecked(cfg.get('reset_vars', True))
                        parent._start_chk_reset_vars.blockSignals(False)
                    if hasattr(parent, '_start_chk_reset_global'):
                        parent._start_chk_reset_global.blockSignals(True)
                        parent._start_chk_reset_global.setChecked(cfg.get('reset_global_vars', False))
                        parent._start_chk_reset_global.blockSignals(False)
                    if hasattr(parent, '_start_chk_clear_log'):
                        parent._start_chk_clear_log.blockSignals(True)
                        parent._start_chk_clear_log.setChecked(cfg.get('clear_log', False))
                        parent._start_chk_clear_log.blockSignals(False)
                    if hasattr(parent, '_start_chk_save_before'):
                        parent._start_chk_save_before.blockSignals(True)
                        parent._start_chk_save_before.setChecked(cfg.get('save_before', False))
                        parent._start_chk_save_before.blockSignals(False)
                    if hasattr(parent, '_btn_start_color'):
                        c = n.custom_color if getattr(n, 'custom_color', '') else '#9ECE6A'
                        parent._btn_start_color.setStyleSheet(f"background: {c}; color: #000; padding: 4px;")
                elif is_note:
                    # Заполняем поля заметки
                    if hasattr(parent, '_note_fld_title'):
                        parent._note_fld_title.setText(n.name)
                    if hasattr(parent, '_note_txt_content'):
                        parent._note_txt_content.setPlainText(getattr(n, 'note_content', ''))
                    if hasattr(parent, '_btn_note_color'):
                        nc = getattr(n, 'note_color', '#E0AF68')
                        parent._btn_note_color.setStyleSheet(f"background: {nc}; color: white; padding: 4px;")
                    if hasattr(parent, '_note_spn_width'):
                        parent._note_spn_width.blockSignals(True)
                        parent._note_spn_width.setValue(int(n.width))
                        parent._note_spn_width.blockSignals(False)
                    if hasattr(parent, '_note_spn_font_size'):
                        parent._note_spn_font_size.blockSignals(True)
                        parent._note_spn_font_size.setValue(getattr(n, 'note_font_size', 9))
                        parent._note_spn_font_size.blockSignals(False)
                elif is_snippet:
                    # Заполняем сниппет-поля
                    parent._snippet_fld_name.setText(n.name)
                    parent._snippet_fld_desc.setPlainText(n.description)
                    parent._snippet_lbl_type.setText(n.agent_type.value.replace('_', ' ').title())
                    # Комментарий для сниппета
                    if hasattr(parent, '_snippet_fld_comment'):
                        parent._snippet_fld_comment.blockSignals(True)
                        parent._snippet_fld_comment.setText(getattr(n, 'comment', ''))
                        parent._snippet_fld_comment.blockSignals(False)
                    # Загружаем код в редактор — приоритет: snippet_config._code > user_prompt_template
                    if hasattr(parent, '_snippet_code_editor') and parent._snippet_code_editor is not None:
                        parent._snippet_code_editor.blockSignals(True)
                        code = ''
                        if hasattr(n, 'snippet_config') and n.snippet_config and '_code' in n.snippet_config:
                            code = n.snippet_config['_code']
                        elif getattr(n, 'user_prompt_template', ''):
                            code = n.user_prompt_template
                        parent._snippet_code_editor.setPlainText(code)
                        parent._snippet_code_editor.blockSignals(False)    
                else:
                    # Заполняем AI-поля
                    self._fld_name.setText(n.name)
                    self._fld_desc.setPlainText(n.description)
            
            # Остальная логика populate только для AI-агентов
            if is_ai:
                idx = self._cmb_type.findData(n.agent_type)
                if idx >= 0:
                    self._cmb_type.setCurrentIndex(idx)
                idx_model = self._fld_model.findData(n.model_id or "")
                self._fld_model.setCurrentIndex(idx_model if idx_model >= 0 else 0)
                idx_vision = self._fld_vision.findData(n.vision_model_id or "")
                self._fld_vision.setCurrentIndex(idx_vision if idx_vision >= 0 else 0)
                self._spn_temp.setValue(int(n.temperature * 10))
                self._spn_timeout.setValue(n.timeout_seconds)
                self._txt_system.setPlainText(n.system_prompt)
                self._txt_user.setPlainText(n.user_prompt_template)
                
                # ═══ Верификация ═══
                if hasattr(self, '_chk_verify'):
                    self._chk_verify.blockSignals(True)
                    self._chk_verify.setChecked(getattr(n, 'verification_enabled', False))
                    self._chk_verify.blockSignals(False)
                if hasattr(self, '_cmb_verify_mode'):
                    self._cmb_verify_mode.blockSignals(True)
                    idx_vm = self._cmb_verify_mode.findData(getattr(n, 'verification_mode', 'self_check'))
                    self._cmb_verify_mode.setCurrentIndex(idx_vm if idx_vm >= 0 else 0)
                    self._cmb_verify_mode.setEnabled(getattr(n, 'verification_enabled', False))
                    self._cmb_verify_mode.blockSignals(False)
                if hasattr(self, '_txt_verify_prompt'):
                    self._txt_verify_prompt.blockSignals(True)
                    self._txt_verify_prompt.setPlainText(getattr(n, 'verification_prompt', ''))
                    self._txt_verify_prompt.setEnabled(getattr(n, 'verification_enabled', False))
                    self._txt_verify_prompt.blockSignals(False)
                if hasattr(self, '_chk_verify_strict'):
                    self._chk_verify_strict.blockSignals(True)
                    self._chk_verify_strict.setChecked(getattr(n, 'verification_strict', False))
                    self._chk_verify_strict.setEnabled(getattr(n, 'verification_enabled', False))
                    self._chk_verify_strict.blockSignals(False)
                if hasattr(self, '_cmb_verify_model'):
                    self._cmb_verify_model.blockSignals(True)
                    idx_vmod = self._cmb_verify_model.findData(getattr(n, 'verification_model_id', ''))
                    self._cmb_verify_model.setCurrentIndex(idx_vmod if idx_vmod >= 0 else 0)
                    v_mode = getattr(n, 'verification_mode', 'self_check')
                    self._cmb_verify_model.setEnabled(
                        v_mode == 'another_model' and getattr(n, 'verification_enabled', False)
                    )
                    self._cmb_verify_model.blockSignals(False)

                # ═══ Тулзы (per-node) ═══
                if hasattr(self, '_tool_checkboxes'):
                    node_tools = set(getattr(n, 'available_tools', []))
                    node_tool_configs = getattr(n, 'tool_configs', {})
                    for t_id, group in self._tool_checkboxes.items():
                        group.blockSignals(True)
                        group.setChecked(t_id in node_tools)
                        group.blockSignals(False)
                    # Восстанавливаем per-node параметры тулзов
                    if hasattr(self, '_tool_widgets'):
                        for widget_key, widget in self._tool_widgets.items():
                            t_id, param_id = widget_key.split('.', 1)
                            cfg = node_tool_configs.get(t_id, {})
                            params = cfg.get('params', {})
                            if param_id in params:
                                widget.blockSignals(True)
                                if isinstance(widget, QCheckBox):
                                    widget.setChecked(params[param_id])
                                elif isinstance(widget, QSpinBox):
                                    widget.setValue(params[param_id])
                                elif isinstance(widget, QLineEdit):
                                    widget.setText(str(params[param_id]))
                                widget.blockSignals(False)

                # ═══ Режим выполнения (per-node) ═══
                if hasattr(self, '_cmb_exec_mode'):
                    self._cmb_exec_mode.blockSignals(True)
                    idx_em = self._cmb_exec_mode.findData(getattr(n, 'orchestration_mode', 'sequential'))
                    self._cmb_exec_mode.setCurrentIndex(idx_em if idx_em >= 0 else 0)
                    self._cmb_exec_mode.blockSignals(False)
                if hasattr(self, '_chk_breakpoint'):
                    self._chk_breakpoint.blockSignals(True)
                    self._chk_breakpoint.setChecked(getattr(n, 'breakpoint_enabled', False))
                    self._chk_breakpoint.blockSignals(False)
                if hasattr(self, '_chk_human_loop'):
                    self._chk_human_loop.blockSignals(True)
                    self._chk_human_loop.setChecked(getattr(n, 'human_in_loop', False))
                    self._chk_human_loop.blockSignals(False)
                if hasattr(self, '_chk_backup_before_node'):
                    self._chk_backup_before_node.blockSignals(True)
                    self._chk_backup_before_node.setChecked(getattr(n, 'backup_before_node', False))
                    self._chk_backup_before_node.blockSignals(False)

                # ═══ Автоматизация (per-node) ═══
                if hasattr(self, '_chk_auto_test'):
                    self._chk_auto_test.blockSignals(True)
                    self._chk_auto_test.setChecked(getattr(n, 'auto_test', False))
                    self._chk_auto_test.blockSignals(False)
                if hasattr(self, '_chk_auto_patch'):
                    self._chk_auto_patch.blockSignals(True)
                    self._chk_auto_patch.setChecked(getattr(n, 'auto_patch', False))
                    self._chk_auto_patch.blockSignals(False)
                if hasattr(self, '_chk_auto_improve'):
                    self._chk_auto_improve.blockSignals(True)
                    self._chk_auto_improve.setChecked(getattr(n, 'auto_improve', False))
                    self._chk_auto_improve.blockSignals(False)
                if hasattr(self, '_spn_max_iter'):
                    self._spn_max_iter.blockSignals(True)
                    self._spn_max_iter.setValue(getattr(n, 'max_iterations', 1))
                    self._spn_max_iter.blockSignals(False)
                if hasattr(self, '_chk_self_modify'):
                    self._chk_self_modify.blockSignals(True)
                    self._chk_self_modify.setChecked(getattr(n, 'self_modify', False))
                    self._chk_self_modify.blockSignals(False)

                # Skills
                self._skills_list.clear()
                for sid in n.skill_ids:
                    skill = self._skills.get(sid)
                    if skill:
                        self._skills_list.addItem(f"{skill.icon} {skill.name}")
                
                # Кастомный цвет
                parent = self._main_window
                if hasattr(parent, '_btn_node_color'):
                    cc = getattr(n, 'custom_color', '')
                    if cc:
                        parent._btn_node_color.setStyleSheet(f"background: {cc}; color: white;")
                    else:
                        parent._btn_node_color.setStyleSheet("")
                
                # Комментарий
                if hasattr(parent, '_fld_comment'):
                    parent._fld_comment.blockSignals(True)
                    parent._fld_comment.setText(getattr(n, 'comment', ''))
                    parent._fld_comment.blockSignals(False)
                
            # Для сниппетов — перестраиваем панель и загружаем настройки
            if is_snippet and hasattr(parent, '_rebuild_snippet_panel'):
                # _rebuild_snippet_panel уже вызывает _delayed_load_snippet_config через QTimer
                parent._rebuild_snippet_panel()
                
        finally:
            for w in all_widgets:
                if w:
                    w.blockSignals(False)
            # Сохраняем snapshot для отслеживания изменений
            if n:
                self._last_snapshot = self._capture_node_state(n)

    def _on_change(self, *_):
        if getattr(self, '_is_updating', False):
            return
        if not self._node:
            return
        n = self._node
        
        # Определяем категорию
        cat = get_node_category(n.agent_type)
        
        parent = self.parent()
        
        if cat == 'note':
            if n.agent_type == AgentType.PROJECT_START:
                # PROJECT_START — своя панель
                if hasattr(parent, '_start_fld_heading'):
                    n.name = parent._start_fld_heading.text()
                    n.description = parent._start_fld_desc.text()
                    if not hasattr(n, 'snippet_config') or n.snippet_config is None:
                        n.snippet_config = {}
                    n.snippet_config['start_mode'] = parent._start_cmb_mode.currentData() or 'simple'
                    n.snippet_config['start_prompt'] = parent._start_txt_prompt.toPlainText()
                    n.snippet_config['reset_vars'] = parent._start_chk_reset_vars.isChecked()
                    n.snippet_config['reset_global_vars'] = parent._start_chk_reset_global.isChecked()
                    n.snippet_config['clear_log'] = parent._start_chk_clear_log.isChecked()
                    n.snippet_config['save_before'] = parent._start_chk_save_before.isChecked()
                return
            # Для обычных заметок — берём из note-полей
            if hasattr(parent, '_note_fld_title'):
                n.name = parent._note_fld_title.text()
                n.note_content = parent._note_txt_content.toPlainText()
            return  # Заметки не имеют остальных настроек
        elif cat == 'snippet':
            # Для сниппетов — берём имя/описание из сниппет-полей
            if hasattr(parent, '_snippet_fld_name'):
                n.name = parent._snippet_fld_name.text()
                n.description = parent._snippet_fld_desc.toPlainText()
            # Синхронизируем код из встроенного редактора в user_prompt_template
            if hasattr(parent, '_snippet_code_editor') and parent._snippet_code_editor is not None:
                try:
                    parent._snippet_code_editor.objectName()  # проверка существования
                    code = parent._snippet_code_editor.toPlainText()
                    n.user_prompt_template = code
                    # Также сохраняем в snippet_config для надежности
                    if not hasattr(n, 'snippet_config') or n.snippet_config is None:
                        n.snippet_config = {}
                    n.snippet_config['_code'] = code
                except RuntimeError:
                    pass  # виджет удален
        else:
            # Для AI-агентов — стандартная логика
            print(f"[ON_CHANGE] {n.name}: writing tools/exec/auto from UI")
            n.name = self._fld_name.text()
            n.description = self._fld_desc.toPlainText()
            n.agent_type = self._cmb_type.currentData() or AgentType.CUSTOM
            n.model_id = self._fld_model.currentData() or ""
            n.vision_model_id = self._fld_vision.currentData() or ""
            n.temperature = self._spn_temp.value() / 10.0
            n.timeout_seconds = self._spn_timeout.value()
            n.system_prompt = self._txt_system.toPlainText()
            n.user_prompt_template = self._txt_user.toPlainText()
            n.agent_type = self._cmb_type.currentData() or AgentType.CUSTOM
            n.model_id = self._fld_model.currentData() or ""
            n.vision_model_id = self._fld_vision.currentData() or ""
            n.temperature = self._spn_temp.value() / 10.0
            n.timeout_seconds = self._spn_timeout.value()
            n.system_prompt = self._txt_system.toPlainText()
            n.user_prompt_template = self._txt_user.toPlainText()
            # Новая система верификации
            n.verification_enabled = self._chk_verify.isChecked()
            n.verification_mode = self._cmb_verify_mode.currentData() or 'self_check'
            n.verification_prompt = self._txt_verify_prompt.toPlainText()
            n.verification_strict = self._chk_verify_strict.isChecked()
            n.verification_model_id = self._cmb_verify_model.currentData() or ''
            
            # Deprecated (для совместимости)
            n.auto_verify = self._chk_verify.isChecked()
            n.verifier_agent_id = self._fld_verifier.text()
            n.color = _AGENT_COLORS.get(n.agent_type, "#565f89")
            
            # Сохраняем тулзы с per-node настройками!
            if hasattr(self, '_tool_checkboxes'):
                enabled_tools = []
                tool_configs = {}
                
                for t_id, group in self._tool_checkboxes.items():
                    if group.isChecked():
                        enabled_tools.append(t_id)
                        # Собираем параметры для этого тулза
                        params = {}
                        # Берем конфиг напрямую из self
                        all_tools_config = getattr(self, '_all_tools_config', {})
                        cfg = all_tools_config.get(t_id, {})
                        for param_id in cfg.get('params', {}).keys():
                            widget_key = f"{t_id}.{param_id}"
                            if hasattr(self, '_tool_widgets') and widget_key in self._tool_widgets:
                                widget = self._tool_widgets[widget_key]
                                if isinstance(widget, QCheckBox):
                                    params[param_id] = widget.isChecked()
                                elif isinstance(widget, QSpinBox):
                                    params[param_id] = widget.value()
                                elif isinstance(widget, QLineEdit):
                                    params[param_id] = widget.text()
                        tool_configs[t_id] = {"enabled": True, "params": params}
                
                n.available_tools = enabled_tools
                n.tool_configs = tool_configs  # Сохраняем per-node конфиг!
            
            # Сохраняем настройки выполнения
            if hasattr(self, '_cmb_exec_mode'): n.orchestration_mode = self._cmb_exec_mode.currentData() or "sequential"
            if hasattr(self, '_chk_breakpoint'): n.breakpoint_enabled = self._chk_breakpoint.isChecked()
            if hasattr(self, '_chk_human_loop'): n.human_in_loop = self._chk_human_loop.isChecked()
            if hasattr(self, '_chk_backup_before_node'): n.backup_before_node = self._chk_backup_before_node.isChecked()
            if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
            
            # Сохраняем настройки автоматизации
            if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
            if hasattr(self, '_chk_auto_patch'): n.auto_patch = self._chk_auto_patch.isChecked()
            if hasattr(self, '_chk_auto_improve'): n.auto_improve = self._chk_auto_improve.isChecked()
            if hasattr(self, '_spn_max_iter'): n.max_iterations = self._spn_max_iter.value()
            if hasattr(self, '_chk_self_modify'): n.self_modify = self._chk_self_modify.isChecked()
            
            self.node_changed.emit()

    def _add_skill(self):
        menu = QMenu(self)
        for skill in self._skills.all_skills():
            act = menu.addAction(f"{skill.icon} {tr(skill.name)}")
            act.setData(skill.id)
            act.triggered.connect(lambda checked, s=skill: self._do_add_skill(s.id))
        menu.exec(self.mapToGlobal(self._skills_list.pos()))

    def _do_add_skill(self, skill_id: str):
        if self._node and skill_id not in self._node.skill_ids:
            self._node.skill_ids.append(skill_id)
            self._populate()
            self.node_changed.emit()

    def _remove_skill(self):
        row = self._skills_list.currentRow()
        if self._node and 0 <= row < len(self._node.skill_ids):
            del self._node.skill_ids[row]
            self._populate()
            self.node_changed.emit()
    
    def _sync_current_node(self):
        """Безопасная синхронизация текущей ноды перед сохранением."""
        n = self._node
        if not n:
            return
        
        # Определяем категорию
        cat = get_node_category(n.agent_type)
        
        parent = self._main_window
        
        if cat == 'note':
            # Для заметок — берём из note-полей
            if hasattr(parent, '_note_fld_title'):
                n.name = parent._note_fld_title.text()
                n.note_content = parent._note_txt_content.toPlainText()
            return  # Заметки не имеют остальных настроек
        elif cat == 'snippet':
            # Для сниппетов — берём имя/описание из сниппет-полей
            if hasattr(parent, '_snippet_fld_name'):
                n.name = parent._snippet_fld_name.text()
                n.description = parent._snippet_fld_desc.toPlainText()
            # Синхронизируем код из редактора
            if hasattr(parent, '_snippet_code_editor') and parent._snippet_code_editor is not None:
                try:
                    code = parent._snippet_code_editor.toPlainText()
                    n.user_prompt_template = code
                    if not hasattr(n, 'snippet_config') or n.snippet_config is None:
                        n.snippet_config = {}
                    n.snippet_config['_code'] = code
                except RuntimeError:
                    pass
        else:
            # Для AI-агентов — стандартная логика
            n.name = self._fld_name.text()
            n.description = self._fld_desc.toPlainText()
            n.agent_type = self._cmb_type.currentData() or AgentType.CUSTOM
            n.model_id = self._fld_model.currentData() or ""
            n.vision_model_id = self._fld_vision.currentData() or ""
            n.temperature = self._spn_temp.value() / 10.0
            n.timeout_seconds = self._spn_timeout.value()
            n.system_prompt = self._txt_system.toPlainText()
            n.user_prompt_template = self._txt_user.toPlainText()
            n.auto_verify = self._chk_verify.isChecked()
            n.verifier_agent_id = self._fld_verifier.text()
            n.color = _AGENT_COLORS.get(n.agent_type, "#565f89")
            if hasattr(self, '_tool_checkboxes'):
                enabled_tools = []
                tool_configs = {}
                for t_id, group in self._tool_checkboxes.items():
                    if group.isChecked():
                        enabled_tools.append(t_id)
                        params = {}
                        cfg = getattr(self, '_all_tools_config', {}).get(t_id, {})
                        for param_id in cfg.get('params', {}).keys():
                            widget_key = f"{t_id}.{param_id}"
                            if hasattr(self, '_tool_widgets') and widget_key in self._tool_widgets:
                                widget = self._tool_widgets[widget_key]
                                if isinstance(widget, QCheckBox):
                                    params[param_id] = widget.isChecked()
                                elif isinstance(widget, QSpinBox):
                                    params[param_id] = widget.value()
                                elif isinstance(widget, QLineEdit):
                                    params[param_id] = widget.text()
                        tool_configs[t_id] = {"enabled": True, "params": params}
                n.available_tools = enabled_tools
                n.tool_configs = tool_configs
            if hasattr(self, '_cmb_exec_mode'): n.orchestration_mode = self._cmb_exec_mode.currentData() or "sequential"
            if hasattr(self, '_chk_breakpoint'): n.breakpoint_enabled = self._chk_breakpoint.isChecked()
            if hasattr(self, '_chk_human_loop'): n.human_in_loop = self._chk_human_loop.isChecked()
            if hasattr(self, '_chk_auto_test'): n.auto_test = self._chk_auto_test.isChecked()
            if hasattr(self, '_chk_auto_patch'): n.auto_patch = self._chk_auto_patch.isChecked()
            if hasattr(self, '_chk_auto_improve'): n.auto_improve = self._chk_auto_improve.isChecked()
            if hasattr(self, '_spn_max_iter'): n.max_iterations = self._spn_max_iter.value()
            if hasattr(self, '_chk_self_modify'): n.self_modify = self._chk_self_modify.isChecked()
