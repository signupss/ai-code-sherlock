"""Сцена workflow с логикой нод и связей."""
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QIcon
from PyQt6.QtWidgets import QGraphicsScene, QMenu, QGraphicsRectItem

from .items import AgentNodeItem, EdgeItem, BlockHeaderItem
from ..constants import get_node_category, AI_AGENT_TYPES, _AGENT_COLORS, _AGENT_ICONS, SNIPPET_TYPES
from services.agent_models import AgentNode, AgentEdge, AgentWorkflow, EdgeCondition, AgentType

try:
    from ui.i18n import tr
except ImportError:
    def tr(s): return s

try:
    from ui.theme_manager import get_color
except ImportError:
    def get_color(k): 
        return {
            "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722", "bg3": "#1A1D2E",
            "bd": "#2E3148", "bd2": "#1E2030",
            "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
            "ac": "#7AA2F7", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
        }.get(k, "#CDD6F4")

class WorkflowScene(QGraphicsScene):
    """The canvas holding all nodes and edges."""

    node_selected = pyqtSignal(object)  # AgentNode or None

    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        # Бесконечная сцена (практически)
        self.setSceneRect(-100000, -100000, 200000, 200000)
        # ═══ ОПТИМИЗАЦИЯ: NoIndex быстрее при частом перемещении элементов ═══
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self._node_items: dict[str, AgentNodeItem] = {}
        self._edge_items: dict[str, EdgeItem] = {}
        self._workflow: AgentWorkflow | None = None
        self._node_counter = 0  # ═══ Добавлено: счётчик порядка создания нод ═══
        self._draw_grid = True
        self._main_window = main_window  # Ссылка на AgentConstructorWindow

    def set_workflow(self, wf: AgentWorkflow):
        self.clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._workflow = wf

        for node in wf.nodes:
            self._add_node_item(node)
        for edge in wf.edges:
            self._add_edge_item(edge)
        
        # Принудительно обновляем позиции рёбер после загрузки
        self.update_edges()
        self.invalidate()
        self.update()
    
    def attach_node(self, child_id: str, parent_id: str):
        """Прикрепить дочернюю ноду к родительской (ZennoPoster-стиль)"""
        # Защита: проверяем что сцена валидна
        if self._workflow is None:
            return
        
        child = self.get_node_item(child_id)
        parent = self.get_node_item(parent_id)
        
        if not child or not parent or child_id == parent_id:
            return
        
        # Проверяем, не пытаемся ли прикрепить к тому, кто уже наш ребёнок (цикл)
        if child_id in getattr(parent.node, 'attached_children', []):
            return
            
        # Проверка на циклическую зависимость
        current_id = parent_id
        visited = set()
        while current_id:
            if current_id == child_id:
                return  # Обнаружен цикл - не прикрепляем
            if current_id in visited:
                break
            visited.add(current_id)
            node = self.get_node_item(current_id)
            if not node:
                break
            current_id = getattr(node.node, 'attached_to', None)
        
        # === ОБРАБОТКА СУЩЕСТВУЮЩИХ СВЯЗЕЙ ===
        # Если у child уже есть дети - сохраняем их, они останутся привязанными к child
        # Если у parent уже есть связь куда-то - проверяем не конфликтует ли
        
        # Открепляем от старого родителя если был
        old_parent_id = child.node.attached_to
        if old_parent_id and old_parent_id != parent_id:
            old_parent = self.get_node_item(old_parent_id)
            if old_parent and child_id in old_parent.node.attached_children:
                old_parent.node.attached_children.remove(child_id)
                # Удаляем старую связь от old_parent к child
                for e in list(self._workflow.edges):
                    if e.source_id == old_parent_id and e.target_id == child_id:
                        self._workflow.remove_edge(e.id)
                        if e.id in self._edge_items:
                            self.removeItem(self._edge_items[e.id])
                            del self._edge_items[e.id]
            child.node.attached_to = None
        
        # Если child уже был прикреплен к этому parent - выходим
        if child.node.attached_to == parent_id:
            return
        
        # Устанавливаем новую связь
        child.node.attached_to = parent_id
        if child_id not in parent.node.attached_children:
            parent.node.attached_children.append(child_id)
        
        # Позиционируем РОВНО по центру под родителем
        new_pos = QPointF(
            parent.pos().x() + (parent.node.width - child.node.width) / 2,
            parent.pos().y() + parent.node.height + 10
        )
        child.setPos(new_pos)
        child.node.x = new_pos.x()
        child.node.y = new_pos.y()
        
        # === АВТОМАТИЧЕСКОЕ СОЗДАНИЕ СВЯЗИ ===
        # Удаляем только существующую связь ОТ parent К child (не наоборот)
        for e in list(self._workflow.edges):
            if e.source_id == parent_id and e.target_id == child_id:
                self._workflow.remove_edge(e.id)
                if e.id in self._edge_items:
                    self.removeItem(self._edge_items[e.id])
                    del self._edge_items[e.id]
        
        # Создаем связь: parent (верхний) -> child (нижний)
        from services.agent_models import AgentEdge, EdgeCondition
        edge = AgentEdge(
            source_id=parent_id,
            target_id=child_id,
            condition=EdgeCondition.ALWAYS,
            label=""  # Пустой label = автоматическая связь
        )
        self._workflow.edges.append(edge)
        self._add_edge_item(edge)
        
        # === ПЕРЕСТРОЙКА: только для цепочки от parent вниз ===
        # Не трогаем другие связи, только пересчитываем позиции детей
        self._rebuild_attachment_chain(parent_id)
        
        # Обновляем шапки
        for item in self._node_items.values():
            item._update_block_header()

        # В detach_node(), после self.update():
        # Обновляем шапки
        for item in self._node_items.values():
            item._update_block_header()
        
        # Принудительная перерисовка
        self.update_edges()
        self.invalidate()
        self.update()
        
        if hasattr(self, '_main_window'):
            self._main_window._log_msg(f"{tr('🔗 Авто-связь:')} {parent.node.name} → {child.node.name}")
            self._main_window._mark_modified_from_props()
        
    def detach_node(self, node_id: str):
        """Открепить ноду от родителя и перестроить связи в цепочке"""
        try:
            node = self.get_node_item(node_id)
            if not node or not node.node.attached_to:
                return
            
            if node.scene() is None:
                return
            
            parent_id = node.node.attached_to
            parent = self.get_node_item(parent_id)
            
            # ═══ ИСПРАВЛЕНИЕ: Сохраняем детей открепляемой ноды ═══
            children_ids = list(getattr(node.node, 'attached_children', []))
            
            # ═══ ИСПРАВЛЕНИЕ: Запоминаем старого "внука" (первого ребёнка) ═══
            first_child_id = children_ids[0] if children_ids else None
        
            # ═══ Собираем ВСЕ пользовательские рёбра от ВСЕХ нод блока к внешним нодам ═══
            # Чтобы не потерять их при перестройке цепочки
            block_node_ids = set(children_ids) | {parent_id, node_id}
            # Добавляем всех членов блока рекурсивно (потомки детей)
            def _collect_block_members(nid, members):
                members.add(nid)
                ni = self.get_node_item(nid)
                if ni:
                    for cid in list(getattr(ni.node, 'attached_children', [])):
                        if cid not in members:
                            _collect_block_members(cid, members)
            full_block_ids = set()
            if parent:
                _collect_block_members(parent_id, full_block_ids)
            full_block_ids.add(node_id)
            
            # Пользовательские рёбра: от/к нодам блока, но target/source — ВНЕШНЯЯ нода
            user_edges_snapshot = []
            for e in list(self._workflow.edges):
                src_in_block = e.source_id in full_block_ids
                tgt_in_block = e.target_id in full_block_ids
                # Ребро наружу или внутрь от/к внешней ноды
                if src_in_block and not tgt_in_block:
                    user_edges_snapshot.append((e.source_id, e.target_id, e.condition, e.label))
                elif tgt_in_block and not src_in_block:
                    user_edges_snapshot.append((e.source_id, e.target_id, e.condition, e.label))
            
            # Удаляем связь между родителем и этой нодой
            edges_to_remove = []
            for e in list(self._workflow.edges):
                if (e.source_id == parent_id and e.target_id == node_id) or \
                   (e.source_id == node_id and e.target_id == parent_id):
                    edges_to_remove.append(e)
            
            for e in edges_to_remove:
                self._workflow.remove_edge(e.id)
                if e.id in self._edge_items:
                    self.removeItem(self._edge_items[e.id])
                    del self._edge_items[e.id]
            
            # ═══ Удаляем ТОЛЬКО блочные связи от этой ноды к её детям ═══
            for child_id in children_ids:
                for e in list(self._workflow.edges):
                    if e.source_id == node_id and e.target_id == child_id and \
                       e.condition == EdgeCondition.ALWAYS and not e.label:
                        self._workflow.remove_edge(e.id)
                        if e.id in self._edge_items:
                            self.removeItem(self._edge_items[e.id])
                            del self._edge_items[e.id]
            
            # ═══ ИСПРАВЛЕНИЕ: Обновляем attached_children у родителя ═══
            if parent and node_id in parent.node.attached_children:
                parent.node.attached_children.remove(node_id)
            
            # ═══ ИСПРАВЛЕНИЕ: Переподключаем детей напрямую к родителю ═══
            # Сначала отвязываем от текущей ноды
            for child_id in children_ids:
                child = self.get_node_item(child_id)
                if child:
                    child.node.attached_to = None
            
            # Затем подключаем к родителю в правильном порядке
            if parent and first_child_id:
                # Первый ребёнок становится прямым потомком родителя
                parent.node.attached_children.insert(0, first_child_id)
                first_child = self.get_node_item(first_child_id)
                if first_child:
                    first_child.node.attached_to = parent_id
                
                # Остальные дети цепочкой от первого
                prev_child_id = first_child_id
                for child_id in children_ids[1:]:
                    prev_child = self.get_node_item(prev_child_id)
                    if prev_child:
                        prev_child.node.attached_children.append(child_id)
                        child = self.get_node_item(child_id)
                        if child:
                            child.node.attached_to = prev_child_id
                    prev_child_id = child_id
            
            # Отсоединённая нода теряет все связи
            node.node.attached_to = None
            node.node.attached_children = []

            # ═══ ИСПРАВЛЕНИЕ: Перестраиваем цепочку от родителя ═══
            if parent_id:
                self._rebuild_attachment_chain(parent_id)

            # ═══ КРИТИЧНО: Перемещаем шапку блока на новый корень если нужно ═══
            # Если у родителя остались дети — он остаётся корнем, шапка уже на месте
            # Если у родителя НЕТ детей — ищем новый корень в цепочке (бывших детей откреплённой ноды)
            if parent and not parent.node.attached_children:
                # Родитель потерял всех детей — убираем его шапку
                if hasattr(parent, '_block_header') and parent._block_header:
                    try:
                        if parent._block_header.scene():
                            self.removeItem(parent._block_header)
                    except RuntimeError:
                        pass
                    parent._block_header = None
            
            # Если у откреплённой ноды были дети — она становится новым корнем своей подцепочки
            # Но мы их очистили выше, так что проверяем children_ids которые перешли к родителю
            # Если родитель получил детей — он остаётся корнем, ничего делать не надо
            # Если дети ушли к родителю, но родитель теперь без детей ( edge case ) — 
            # ищем первого ребёнка в цепочке и делаем его корнем
            
            # Дополнительно: если первый ребёнок из children_ids теперь без родителя 
            # (не должен случиться при нормальной логике, но на всякий случай)
            if children_ids:
                first_child_id = children_ids[0]
                first_child = self.get_node_item(first_child_id)
                if first_child and not first_child.node.attached_to:
                    # Этот ребёнок стал корнем — создаём ему шапку
                    first_child._update_block_header()
            
            # ═══ КРИТИЧНО: Обновляем шапки — сначала удаляем у тех кто перестал быть корнем ═══
            # 1. У откреплённой ноды шапку убираем всегда
            if hasattr(node, '_block_header') and node._block_header:
                try:
                    if node._block_header.scene():
                        self.removeItem(node._block_header)
                except RuntimeError:
                    pass
                node._block_header = None
            
            # 2. У родителя обновляем (уберётся если нет детей, останется если есть)
            if parent:
                if hasattr(parent, '_update_block_header'):
                    parent._update_block_header()
            
            # 3. Если дети перешли к родителю — проверяем что у них нет шапок
            for child_id in children_ids:
                child = self.get_node_item(child_id)
                if child and hasattr(child, '_block_header') and child._block_header:
                    try:
                        if child._block_header.scene():
                            self.removeItem(child._block_header)
                    except RuntimeError:
                        pass
                    child._block_header = None
            
            # 4. Общее обновление всех шапок на всякий случай
            for item in self._node_items.values():
                if hasattr(item, '_update_block_header'):
                    item._update_block_header()
            
            self.update_edges()
            
            # ═══ Восстановление пользовательских рёбер к внешним нодам ═══
            # Собираем текущие рёбра блока для сравнения
            current_block_ids = set()
            if parent:
                def _collect_members(nid, out):
                    out.add(nid)
                    ni = self.get_node_item(nid)
                    if ni:
                        for cid in list(getattr(ni.node, 'attached_children', [])):
                            if cid not in out:
                                _collect_members(cid, out)
                _collect_members(parent_id, current_block_ids)
            
            # Проверяем, что пользовательские рёбра от нод блока к внешним нодам не потерялись
            existing_edges = {(e.source_id, e.target_id) for e in self._workflow.edges}
            for src_id, tgt_id, cond, lbl in user_edges_snapshot:
                if (src_id, tgt_id) not in existing_edges:
                    # Ребро потеряно — восстанавливаем
                    if self.get_node_item(src_id) and self.get_node_item(tgt_id):
                        from services.agent_models import AgentEdge
                        restored = AgentEdge(source_id=src_id, target_id=tgt_id,
                                             condition=cond, label=lbl)
                        self._workflow.edges.append(restored)
                        self._add_edge_item(restored)
            
            self.invalidate()
            self.update()

            if hasattr(self, '_main_window'):
                self._main_window._log_msg(f"📤 {node.node.name} {tr('откреплён, связи перестроены')}")
                self._main_window._mark_modified_from_props()
        except Exception as e:
            print(f"[detach_node CRITICAL ERROR] {e}")
            import traceback
            traceback.print_exc()
            
    def remove_node(self, node_id: str):
        """Удалить ноду и все связанные рёбра из сцены и workflow."""
        item = self._node_items.get(node_id)
        if not item:
            return
        
        node = item.node
        
        # ═══ ИСПРАВЛЕНИЕ: Сохраняем информацию о прикреплении ПЕРЕД удалением ═══
        old_parent_id = getattr(node, 'attached_to', None)
        old_children_ids = list(getattr(node, 'attached_children', []))

        # ═══ ИСПРАВЛЕНИЕ: Убираем себя из attached_children родителя ═══
        if old_parent_id:
            parent_item = self._node_items.get(old_parent_id)
            if parent_item and node_id in parent_item.node.attached_children:
                parent_item.node.attached_children.remove(node_id)

        # ═══ ИСПРАВЛЕНИЕ: Удаляем шапку блока если есть ═══
        if hasattr(item, '_block_header') and item._block_header:
            try:
                if item._block_header.scene():
                    self.removeItem(item._block_header)
            except RuntimeError:
                pass
            item._block_header = None
        
        # Удаляем связанные рёбра
        for eid in list(self._edge_items.keys()):
            ei = self._edge_items[eid]
            if ei.source is item or ei.target is item:
                if self._workflow:
                    self._workflow.remove_edge(eid)
                self.removeItem(ei)
                del self._edge_items[eid]
        
        # ═══ Очистка тяжёлых данных из snippet_config (base64 картинки и т.п.) ═══
        cfg = getattr(node, 'snippet_config', None)
        if cfg and isinstance(cfg, dict):
            for heavy_key in ('template_image', 'screenshot_b64', 'image_data'):
                if heavy_key in cfg:
                    cfg[heavy_key] = ''
        
        # Удаляем ноду
        if self._workflow:
            self._workflow.remove_node(node_id)
        self.removeItem(item)
        del self._node_items[node_id]
        
        # ═══ ИСПРАВЛЕНИЕ: Переподключаем цепочку — родитель к первому ребёнку ═══
        if old_parent_id and old_children_ids:
            parent_item = self._node_items.get(old_parent_id)
            first_child_id = old_children_ids[0]
            first_child_item = self._node_items.get(first_child_id)
            
            if parent_item and first_child_item:
                self.attach_node(first_child_id, old_parent_id)
                
                if hasattr(self, '_main_window'):
                    self._main_window._log_msg(
                        f"{tr('🔗 Авто-переподключение:')} {parent_item.node.name} → {first_child_item.node.name}"
                    )
        
        # Обновляем шапку родителя (если у него не осталось детей — убирает header)
        if old_parent_id:
            parent_item = self._node_items.get(old_parent_id)
            if parent_item and hasattr(parent_item, '_update_block_header'):
                parent_item._update_block_header()

        # Принудительная перерисовка — убирает артефакты
        self.update()
        self.invalidate()
        for _v in self.views():
            _v.viewport().update()
    
    def _delete_nodes_list(self, nodes: list):
        """Удалить список нод (для удаления всего блока)."""
        # ═══ ИСПРАВЛЕНИЕ: Сначала удаляем все шапки блоков ═══
        for node in nodes:
            item = self._node_items.get(node.id)
            if item and hasattr(item, '_block_header') and item._block_header:
                try:
                    if item._block_header.scene():
                        self.removeItem(item._block_header)
                except RuntimeError:
                    pass
                item._block_header = None
        
        # Сначала открепляем все ноды друг от друга чтобы избежать конфликтов
        for node in nodes:
            if hasattr(node, 'attached_to'):
                node.attached_to = None
            if hasattr(node, 'attached_children'):
                node.attached_children = []
        
        # Теперь удаляем каждую ноду
        for node in nodes:
            self.remove_node(node.id)
        
        if hasattr(self, '_main_window') and self._main_window:
            self._main_window._log_msg(f"{tr('🗑 Удалён блок из')} {len(nodes)} {tr('нод')}")
            self._main_window._mark_modified_from_props()
    
    def _add_node_item(self, node: AgentNode) -> AgentNodeItem | None:
        # Защита: проверяем что нода валидна
        if node is None or not hasattr(node, 'id'):
            print("⚠️ _add_node_item: invalid node")
            return None
        
        item = AgentNodeItem(node, self)
        # ═══ ИСПРАВЛЕНИЕ: Устанавливаем Z-ордер до добавления в сцену ═══
        item.setZValue(10 + self._node_counter * 0.001)
        self.addItem(item)
        self._node_items[node.id] = item
        self._node_counter += 1
        return item

    def _add_edge_item(self, edge: AgentEdge) -> EdgeItem | None:
        # Защита: проверяем что edge валиден
        if edge is None or not hasattr(edge, 'source_id') or not hasattr(edge, 'target_id'):
            print("⚠️ _add_edge_item: invalid edge")
            return None
        
        src = self._node_items.get(edge.source_id)
        tgt = self._node_items.get(edge.target_id)
        if not src or not tgt:
            print(f"⚠️ _add_edge_item: missing src={edge.source_id} or tgt={edge.target_id}")
            return None
        
        # Защита: проверяем что src и tgt всё ещё в сцене
        if src.scene() is None or tgt.scene() is None:
            print("⚠️ _add_edge_item: src or tgt not in scene")
            return None
        
        item = EdgeItem(edge, src, tgt, self)  # Передаем scene_ref
        self.addItem(item)
        self._edge_items[edge.id] = item
        return item

    def add_node(self, node: AgentNode) -> AgentNodeItem | None:
        if self._workflow is None:
            print("⚠️ add_node: no workflow")
            return None
        self._workflow.add_node(node)
        return self._add_node_item(node)

    def add_edge(self, edge: AgentEdge) -> EdgeItem | None:
        """Для внутреннего использования (загрузка файлов) - без валидации"""
        if self._workflow is None:
            print("⚠️ add_edge: no workflow")
            return None
        self._workflow.add_edge(edge)
        # ── Если ребро из PROJECT_START — цель становится стартовой нодой ──
        src_node = self._workflow.get_node(edge.source_id)
        from services.agent_models import AgentType as _AT
        if src_node and getattr(src_node, 'agent_type', None) == _AT.PROJECT_START:
            self._workflow.entry_node_id = edge.target_id
        return self._add_edge_item(edge)
    
    def request_edge_creation(self, edge: AgentEdge, source_node=None, target_node=None,
                          source_port: str = None) -> bool:
        """Создание связи с валидацией логики через UI.
        source_port: 'output', 'error', 'switch_case_0', 'switch_case_1', etc.
        Ручные связи (output/error/switch) НЕ перестраивают автоматические цепочки."""
        if not self._workflow:
            return False
        
        # ═══ ПРОВЕРКА: не конфликтует ли с автоматической цепочкой прикрепления ═══
        # Если source или target в автоматической цепочке — запрещаем ручное соединение
        source_item = self._node_items.get(edge.source_id)
        target_item = self._node_items.get(edge.target_id)
        
        if source_item and target_item:
            source_attached_to = getattr(source_item.node, 'attached_to', None)
            source_children = getattr(source_item.node, 'attached_children', [])
            target_attached_to = getattr(target_item.node, 'attached_to', None)
            target_children = getattr(target_item.node, 'attached_children', [])
            
            # Проверяем, не пытаемся ли соединить ноды из одной цепочки прикрепления
            # в неправильном порядке (ручная связь должна игнорировать авто-логику)
            in_same_chain = (
                source_attached_to == edge.target_id or  # source прикреплен к target
                target_attached_to == edge.source_id or  # target прикреплен к source
                edge.target_id in source_children or      # target ребенок source
                edge.source_id in target_children         # source ребенок target
            )
            
            if in_same_chain and source_port == 'output':
                # Это попытка ручного соединения внутри цепочки прикрепления
                # Разрешаем, но НЕ перестраиваем автоматические связи
                pass  # Продолжаем создание связи
        
        # ═══ УДАЛЕНИЕ СУЩЕСТВУЮЩИХ СВЯЗЕЙ ОТ ЭТОГО ЖЕ ПОРТА ═══
        if source_port:  # Для всех портов включая output — заменяем старую связь новой
            edges_to_remove = []
            for existing_edge in list(self._workflow.edges):
                if existing_edge.source_id != edge.source_id:
                    continue
                
                existing_port = 'output'
                if existing_edge.condition == EdgeCondition.ON_FAILURE:
                    existing_port = 'error'
                elif existing_edge.label and existing_edge.label.startswith('__sw_'):
                    try:
                        i = int(existing_edge.label.split('__sw_')[1].split('__')[0])
                        existing_port = f'switch_case_{i}'
                    except:
                        pass
                
                if existing_port == source_port:
                    edges_to_remove.append(existing_edge)
            
            for old_edge in edges_to_remove:
                self._workflow.remove_edge(old_edge.id)
                if old_edge.id in self._edge_items:
                    old_item = self._edge_items.pop(old_edge.id)
                    self.removeItem(old_item)
        
        # ═══ ДЛЯ ОБЫЧНОГО OUTPUT: не удаляем автоматические связи цепочки ═══
        # Автоматические связи имеют condition=ALWAYS и пустой label
        # Они управляются только attach_node/detach_node
        
        success, error = self._workflow.add_edge(edge)
        if not success:
            if hasattr(self.parent(), '_log_msg'):
                self.parent()._log_msg(f"⚠️ {error}")
            return False
        
        # Создаем визуал
        item = self._add_edge_item(edge)
        if item and hasattr(self.parent(), '_history'):
            desc = f"{tr('Связь')} {source_node.name if source_node else ''} → {target_node.name if target_node else ''}"
            self.parent()._history.push(
                lambda: (self._workflow.add_edge(edge), self._add_edge_item(edge)),
                lambda: (self._workflow.remove_edge(edge.id), 
                        self._edge_items.pop(edge.id, None) and self.removeItem(item)),
                desc
            )
            self.parent()._log_msg(f"🔗 {desc}")
            mw = self.parent()
            if mw and not mw._is_modified:
                mw._is_modified = True
                mw._update_window_title()
        return True

    def remove_selected(self):
        # Собираем список нод для удаления заранее (selectedItems меняется в процессе)
        nodes_to_remove = []
        edges_to_remove = []
        for item in self.selectedItems():
            if isinstance(item, AgentNodeItem):
                nodes_to_remove.append(item)
            elif isinstance(item, EdgeItem):
                edges_to_remove.append(item)

        # ids удаляемых нод — чтобы не переподключать к ним же
        removing_ids = {item.node.id for item in nodes_to_remove}

        for item in nodes_to_remove:
            node_id = item.node.id
            old_parent_id = getattr(item.node, 'attached_to', None)
            old_children_ids = list(getattr(item.node, 'attached_children', []))

            # Убираем шапку блока если есть
            if hasattr(item, '_block_header') and item._block_header:
                try:
                    if item._block_header.scene():
                        self.removeItem(item._block_header)
                except RuntimeError:
                    pass
                item._block_header = None

            # Убираем себя из attached_children родителя
            if old_parent_id and old_parent_id not in removing_ids:
                parent_item = self._node_items.get(old_parent_id)
                if parent_item and node_id in parent_item.node.attached_children:
                    parent_item.node.attached_children.remove(node_id)

                # Переподключаем детей (которые не удаляются) к родителю
                surviving_children = [c for c in old_children_ids if c not in removing_ids]
                if surviving_children:
                    first_child_id = surviving_children[0]
                    first_child_item = self._node_items.get(first_child_id)
                    parent_item2 = self._node_items.get(old_parent_id)
                    if parent_item2 and first_child_item:
                        first_child_item.node.attached_to = old_parent_id
                        if first_child_id not in parent_item2.node.attached_children:
                            parent_item2.node.attached_children.insert(0, first_child_id)

            if self._workflow:
                self._workflow.remove_node(node_id)
            self._node_items.pop(node_id, None)
            # Удаляем связанные рёбра
            for eid in list(self._edge_items):
                ei = self._edge_items[eid]
                if ei.source is item or ei.target is item:
                    self.removeItem(ei)
                    del self._edge_items[eid]
            self.removeItem(item)

        for item in edges_to_remove:
            if self._workflow:
                self._workflow.remove_edge(item.edge.id)
            self._edge_items.pop(item.edge.id, None)
            self.removeItem(item)

        # Перестраиваем цепочки для всех затронутых родителей
        affected_parents = set()
        for item in nodes_to_remove:
            p = getattr(item.node, 'attached_to', None)
            if p and p not in removing_ids:
                affected_parents.add(p)
        for parent_id in affected_parents:
            if self._node_items.get(parent_id):
                self._rebuild_attachment_chain(parent_id)

        # Обновляем шапки оставшихся нод
        for remaining in list(self._node_items.values()):
            if hasattr(remaining, '_update_block_header'):
                remaining._update_block_header()

        # Принудительная перерисовка — убирает артефакты от удалённых элементов
        self.update()
        self.invalidate()
        for _v in self.views():
            _v.viewport().update()

    def update_edges(self):
        for ei in self._edge_items.values():
            ei.update_position()

    def get_node_item(self, node_id: str) -> AgentNodeItem | None:
        return self._node_items.get(node_id)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if not self._draw_grid:
            return

        bg = QColor(get_color("bg1"))
        grid_color = QColor(get_color("bd2"))
        painter.fillRect(rect, bg)

        grid = 20
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)

        pen = QPen(grid_color, 0.5)
        painter.setPen(pen)
        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += grid
        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += grid
    
    def attach_node(self, child_id: str, parent_id: str):
        """Прикрепить дочернюю ноду к родительской (с автоматической стрелкой)"""
        child = self.get_node_item(child_id)
        parent = self.get_node_item(parent_id)

        if not child or not parent or child_id == parent_id:
            return
        
        # ═══ ИСПРАВЛЕНИЕ: Проверяем что child не является предком parent (цикл) ═══
        current_id = parent_id
        visited = set()
        while current_id:
            if current_id == child_id:
                return  # Обнаружен цикл — не прикрепляем
            if current_id in visited:
                break
            visited.add(current_id)
            node = self.get_node_item(current_id)
            if not node:
                break
            current_id = getattr(node.node, 'attached_to', None)
        
        # ═══ ИСПРАВЛЕНИЕ: Если у parent уже есть дети — проверяем дубликаты ═══
        existing_children = getattr(parent.node, 'attached_children', [])
        if child_id in existing_children:
            # Уже прикреплен — просто перестраиваем позицию
            pass

        # Защита от циклов
        current_id = parent_id
        visited = set()
        while current_id:
            if current_id == child_id:
                return
            if current_id in visited:
                break
            visited.add(current_id)
            ni = self.get_node_item(current_id)
            if not ni:
                break
            current_id = getattr(ni.node, 'attached_to', None)

        # Аккуратно отвязываем от старого родителя (без полного detach,
        # чтобы не потерять детей child)
        old_parent_id = child.node.attached_to
        if old_parent_id and old_parent_id != parent_id:
            old_parent = self.get_node_item(old_parent_id)
            if old_parent and child_id in old_parent.node.attached_children:
                old_parent.node.attached_children.remove(child_id)
            for e in list(self._workflow.edges):
                if e.source_id == old_parent_id and e.target_id == child_id:
                    self._workflow.remove_edge(e.id)
                    if e.id in self._edge_items:
                        self.removeItem(self._edge_items.pop(e.id))
            child.node.attached_to = None

        if child.node.attached_to == parent_id:
            return  # уже прикреплён

        # Устанавливаем связь
        child.node.attached_to = parent_id
        if child_id not in parent.node.attached_children:
            parent.node.attached_children.append(child_id)

        # Позиционируем по центру под родителем
        new_pos = QPointF(
            parent.pos().x() + (parent.node.width - child.node.width) / 2,
            parent.pos().y() + parent.node.height + 10
        )
        child.setPos(new_pos)
        child.node.x = new_pos.x()
        child.node.y = new_pos.y()

        # === СОЗДАЁМ СТРЕЛКУ parent → child ===
        # Сначала удаляем дублирующую если есть
        for e in list(self._workflow.edges):
            if e.source_id == parent_id and e.target_id == child_id:
                self._workflow.remove_edge(e.id)
                if e.id in self._edge_items:
                    self.removeItem(self._edge_items.pop(e.id))

        from services.agent_models import AgentEdge, EdgeCondition
        edge = AgentEdge(
            source_id=parent_id,
            target_id=child_id,
            condition=EdgeCondition.ALWAYS,
            label=""
        )
        self._workflow.edges.append(edge)
        self._add_edge_item(edge)

        # ═══ ИСПРАВЛЕНИЕ: Поднимаем Z-ордер переносимого сниппета и его цепочки выше родителя ═══
        def _raise_z_order_recursive(node_item, base_z):
            """Рекурсивно поднимаем Z-ордер ноды и всех её детей"""
            if not node_item:
                return
            # Нода на уровне base_z
            node_item.setZValue(base_z)
            # Её шапка (если есть) выше
            if hasattr(node_item, '_block_header') and node_item._block_header:
                node_item._block_header.setZValue(base_z + 1000)
            # Дети на том же уровне + небольшой отступ для порядка
            for i, cid in enumerate(getattr(node_item.node, 'attached_children', [])):
                child_item = self.get_node_item(cid)
                if child_item:
                    _raise_z_order_recursive(child_item, base_z + (i + 1) * 0.01)

        # Получаем текущий Z родителя и поднимаем переносимого ребёнка выше
        parent_z = parent.zValue()
        _raise_z_order_recursive(child, parent_z + 0.1)

        # Полная перестройка всей цепочки от вершины
        self._rebuild_attachment_chain(parent_id)

        self.update_edges()
        self.invalidate()
        self.update()

        if hasattr(self, '_main_window'):
            self._main_window._log_msg(
                f"🔗 Авто-связь: {parent.node.name} → {child.node.name}")
            self._main_window._mark_modified_from_props()
    
    def _rebuild_attachment_chain(self, top_parent_id: str, visited: set = None):
        """Полная перестройка стрелок во всей цепочке от top_parent вниз."""
        from services.agent_models import AgentEdge, EdgeCondition
        
        if visited is None:
            visited = set()
        if top_parent_id in visited:
            return
        visited.add(top_parent_id)

        parent_item = self.get_node_item(top_parent_id)
        if not parent_item:
            return

        # ═══ ИСПРАВЛЕНИЕ: Получаем актуальный список детей ═══
        children = list(getattr(parent_item.node, 'attached_children', []))

        # ═══ Чистим ТОЛЬКО авто-рёбра от этого parent к его attached детям ═══
        # НЕ трогаем рёбра к внешним нодам (пользовательские стрелки)
        children_set = set(children)
        edges_to_remove = []
        for e in list(self._workflow.edges):
            if e.source_id == top_parent_id and e.target_id in children_set:
                # Удаляем ТОЛЬКО авто-рёбра блока (ALWAYS + пустой label)
                if e.condition == EdgeCondition.ALWAYS and not e.label:
                    edges_to_remove.append(e.id)
            # ВАЖНО: НЕ удаляем рёбра от parent к нодам ВНЕ блока!
        
        for eid in edges_to_remove:
            self._workflow.remove_edge(eid)
            if eid in self._edge_items:
                self.removeItem(self._edge_items.pop(eid))

        if not children:
            return

        # ═══ ИСПРАВЛЕНИЕ: Создаём ребро только к ПЕРВОМУ ребёнку ═══
        first_child_id = children[0]
        
        # Проверяем что ребёнок существует и валиден
        first_child_item = self.get_node_item(first_child_id)
        if not first_child_item:
            # Первый ребёнок недоступен — пробуем следующего
            for child_id in children[1:]:
                child_item = self.get_node_item(child_id)
                if child_item:
                    first_child_id = child_id
                    first_child_item = child_item
                    # Обновляем список детей у parent
                    parent_item.node.attached_children = [child_id] + [
                        c for c in children if c != child_id
                    ]
                    break
            else:
                return  # Нет валидных детей

        # Создаём единственное правильное ребро parent → first_child
        edge = AgentEdge(
            source_id=top_parent_id,
            target_id=first_child_id,
            condition=EdgeCondition.ALWAYS,
            label=""
        )
        self._workflow.edges.append(edge)
        self._add_edge_item(edge)

        # ═══ ИСПРАВЛЕНИЕ: Позиционируем первого ребёнка ровно под родителем ═══
        parent_pos = parent_item.pos()
        new_pos = QPointF(
            parent_pos.x() + (parent_item.node.width - first_child_item.node.width) / 2,
            parent_pos.y() + parent_item.node.height + 10
        )
        first_child_item.setPos(new_pos)
        first_child_item.node.x = new_pos.x()
        first_child_item.node.y = new_pos.y()
        
        # ═══ ИСПРАВЛЕНИЕ: Перестраиваем все связи блока чтобы убрать дубли и починить порядок ═══
        # Собираем все ноды цепочки
        chain_node_ids = {top_parent_id}
        current = top_parent_id
        while True:
            item = self.get_node_item(current)
            if not item:
                break
            children = getattr(item.node, 'attached_children', [])
            if not children:
                break
            chain_node_ids.add(children[0])
            current = children[0]
        
        # Удаляем дублирующиеся рёбра внутри цепочки (оставляем только attached)
        edges_to_remove = []
        for e in self._workflow.edges:
            if e.source_id in chain_node_ids and e.target_id in chain_node_ids:
                # Это ребро внутри цепочки
                src_item = self.get_node_item(e.source_id)
                tgt_item = self.get_node_item(e.target_id)
                if src_item and tgt_item:
                    # Проверяем, является ли это attached-связью
                    is_attached = (
                        tgt_item.node.attached_to == src_item.node.id or
                        (e.condition == EdgeCondition.ALWAYS and not e.label)
                    )
                    if not is_attached:
                        # Это "висячее" ребро внутри цепочки - удаляем
                        edges_to_remove.append(e.id)
        
        for eid in edges_to_remove:
            self._workflow.remove_edge(eid)
            if eid in self._edge_items:
                self.removeItem(self._edge_items.pop(eid))
        
        # ═══ ИСПРАВЛЕНИЕ: Синхронизируем Z-ордер ПЕРЕД рекурсией ═══
        parent_z = parent_item.zValue()
        if first_child_item:  # first_child_item точно определён здесь
            first_child_item.setZValue(parent_z)
            if hasattr(first_child_item, '_block_header') and first_child_item._block_header:
                first_child_item._block_header.setZValue(parent_z + 1000)
        
        # Рекурсивно перестраиваем для child (после установки Z-ордера)
        self._rebuild_attachment_chain(first_child_id, visited)
        
    def _set_node_color(self, node, color):
        """Установить цвет ноды"""
        node.custom_color = color
        item = self.get_node_item(node.id)
        if item:
            item._setup_visuals()
            item.update()
        if hasattr(self, '_main_window'):
            self._main_window._mark_modified_from_props()

    def _edit_node_comment(self, node):
        """Редактировать комментарий"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        text, ok = QInputDialog.getText(
            self._main_window, tr("Комментарий"),
            tr("Текст:"),
            QLineEdit.EchoMode.Normal,
            getattr(node, 'comment', '')
        )
        if ok:
            node.comment = text
            item = self.get_node_item(node.id)
            if item:
                item.update()
            if hasattr(self, '_main_window'):
                self._main_window._mark_modified_from_props()
    
    def _set_node_color(self, node, color):
        """Установить кастомный цвет ноды"""
        node.custom_color = color
        item = self.get_node_item(node.id)
        if item:
            item._setup_visuals()
            item.update()
        if hasattr(self, '_main_window'):
            self._main_window._mark_modified_from_props()

    def _edit_node_comment(self, node):
        """Редактировать комментарий ноды"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        text, ok = QInputDialog.getText(
            self._main_window, tr("Комментарий"),
            tr("Текст комментария:"),
            QLineEdit.EchoMode.Normal,
            getattr(node, 'comment', '')
        )
        if ok:
            node.comment = text
            item = self.get_node_item(node.id)
            if item:
                item.update()
            if hasattr(self, '_main_window'):
                self._main_window._mark_modified_from_props()
    
    def _create_node_and_connect_if_needed(self, agent_type, pos):
        """Вспомогательный метод для создания ноды и авто-подключения стрелки."""
        if not self._main_window:
            return
            
        # ═══ ИСПРАВЛЕНИЕ: Ищем ноду, которая СЕЙЧАС тянет стрелку (среди AgentNodeItem) ═══
        source_node_item = None
        for item in self.items():
            if hasattr(item, '_connecting') and item._connecting:
                source_node_item = item
                break
                
        source_node_id = None
        drag_port = None
        
        if source_node_item:
            source_node_id = source_node_item.node.id
            drag_port = getattr(source_node_item, '_drag_start_port', None)
            
            # Отменяем текущее визуальное вытягивание стрелки в самом элементе
            source_node_item._connecting = False
            temp_line = getattr(source_node_item, '_temp_line', None)
            if temp_line:
                self.removeItem(temp_line)
                source_node_item._temp_line = None
            source_node_item._connection_source = None
            
        # 1. Создаем саму ноду через главное окно
        self._main_window._create_agent_at(agent_type, pos)
        
        # 2. Если мы тянули стрелку — соединяем!
        if source_node_id:
            if self._workflow and self._workflow.nodes:
                new_node = self._workflow.nodes[-1]
                
                # Настраиваем условие и label (как для SWITCH и Error)
                condition = EdgeCondition.ALWAYS
                label = ""
                edge_id_suffix = ""
                
                if drag_port == 'error':
                    condition = EdgeCondition.ON_FAILURE
                    label = "⚡ error"
                elif isinstance(drag_port, str) and drag_port.startswith('switch_case_'):
                    condition = EdgeCondition.ON_CONDITION
                    try:
                        i = int(drag_port.rsplit('_', 1)[-1])
                        cases = source_node_item._get_switch_cases()
                        case_val = cases[i] if i < len(cases) else f"case_{i}"
                        label = f"__sw_{i}__:{case_val[:20]}"
                        edge_id_suffix = f"_{drag_port}"
                    except Exception:
                        label = "__sw_0__:case_0"
                        
                edge = AgentEdge(
                    source_id=source_node_id, 
                    target_id=new_node.id,
                    condition=condition,
                    label=label
                )
                if edge_id_suffix:
                    edge.id = f"{edge.source_id}_{edge.target_id}{edge_id_suffix}"
                    
                # Добавляем связь правильно
                if hasattr(self, 'request_edge_creation'):
                    self.request_edge_creation(edge, source_node_item.node, new_node, source_port=drag_port)
                else:
                    self.add_edge(edge)
                
                self.update()
                self._main_window._log_msg(f"{tr('🔗 Авто-связь с')} {new_node.name}")
    
    def _set_entry_node(self, node_id: str):
        """Установить ноду как стартовую."""
        self._workflow.entry_node_id = node_id
        self.invalidate()
        self.update()
        if hasattr(self, '_main_window') and self._main_window:
            self._main_window._mark_modified_from_props()
            if hasattr(self._main_window, '_log_msg'):
                node = self._workflow.get_node(node_id)
                name = node.name if node else node_id
                self._main_window._log_msg(f"▶ Стартовое действие: {name}")
    
    def _set_entry_node(self, node_id: str):
        """Установить ноду как стартовое действие."""
        if self._workflow:
            self._workflow.entry_node_id = node_id
            self.invalidate()
            self.update()
            if self._main_window:
                self._main_window._mark_modified_from_props()
                if hasattr(self._main_window, '_log_msg'):
                    node = self._workflow.get_node(node_id)
                    name = node.name if node else node_id
                    self._main_window._log_msg(f"▶ Стартовое действие: {name}")
    
    def contextMenuEvent(self, event):
        """Right-click menu on canvas"""
        menu = QMenu()
        
        # ── Подменю AI-агентов (без сниппетов и заметок) ──
        create_menu = menu.addMenu(tr("🤖 Создать агент"))
        for at in [
            AgentType.CODE_WRITER, AgentType.CODE_REVIEWER, AgentType.TESTER,
            AgentType.PLANNER, AgentType.IMAGE_GEN, AgentType.IMAGE_ANALYST,
            AgentType.FILE_MANAGER, AgentType.SCRIPT_RUNNER, AgentType.VERIFIER,
            AgentType.ORCHESTRATOR, AgentType.PATCHER, AgentType.CUSTOM,
        ]:
            icon = _AGENT_ICONS.get(at, "🤖")
            translated_name = tr(at.value.replace('_', ' ').title())
            act = create_menu.addAction(f"{icon} {translated_name}")
            act.triggered.connect(lambda checked, t=at, pos=event.scenePos(): 
                self._create_node_and_connect_if_needed(t, pos))

        # ── Подменю сниппетов (логика / автоматизация) ──
        snippet_menu = menu.addMenu(tr("📜 Создать сниппет"))
        for at in [
            AgentType.CODE_SNIPPET, AgentType.IF_CONDITION, AgentType.SWITCH,
            AgentType.LOOP, AgentType.VARIABLE_SET, AgentType.HTTP_REQUEST,
            AgentType.DELAY, AgentType.LOG_MESSAGE, AgentType.NOTIFICATION,
            AgentType.GOOD_END, AgentType.BAD_END, AgentType.JS_SNIPPET,
            AgentType.PROGRAM_LAUNCH, AgentType.LIST_OPERATION,
            AgentType.TABLE_OPERATION, AgentType.FILE_OPERATION,
            AgentType.DIR_OPERATION, AgentType.TEXT_PROCESSING,
            AgentType.JSON_XML, AgentType.VARIABLE_PROC, AgentType.RANDOM_GEN,
        ]:
            icon = _AGENT_ICONS.get(at, "📜")
            translated_name = tr(at.value.replace('_', ' ').title())
            act = snippet_menu.addAction(f"{icon} {translated_name}")
            act.triggered.connect(lambda checked, t=at, pos=event.scenePos(): 
                self._create_node_and_connect_if_needed(t, pos))
        
        # ── Подменю браузер ──
        browser_menu = menu.addMenu(tr("🌐 Браузер"))
        _browser_items = [
            (AgentType.BROWSER_LAUNCH,      tr("🌐 Запустить браузер")),
            (AgentType.BROWSER_ACTION,      tr("🖱 Действие браузера")),
            (AgentType.BROWSER_CLICK_IMAGE, tr("🖼 Клик по картинке")),
            (AgentType.BROWSER_SCREENSHOT,  tr("📸 Скриншот страницы")),
            (AgentType.BROWSER_CLOSE,       tr("🔴 Закрыть браузер")),
            (AgentType.BROWSER_AGENT,       tr("🌐🧠 Browser Agent (AI)")),
            (AgentType.BROWSER_PROFILE_OP,  tr("🪪 Операции с профилем")),
        ]
        for at, label in _browser_items:
            act = browser_menu.addAction(label)
            act.triggered.connect(lambda checked, t=at, pos=event.scenePos():
                self._create_node_and_connect_if_needed(t, pos))

        # ── Подменю программы ──
        program_menu = menu.addMenu(tr("🖥 Программы"))
        _program_items = [
            (AgentType.PROGRAM_OPEN,        tr("🖥 Открыть программу")),
            (AgentType.PROGRAM_ACTION,      tr("🎯 Действие в программе")),
            (AgentType.PROGRAM_CLICK_IMAGE, tr("🖼 Клик по картинке")),
            (AgentType.PROGRAM_SCREENSHOT,  tr("📸 Скриншот программы")),
            (AgentType.PROGRAM_AGENT,       tr("🖥🧠 Program Agent (AI)")),
        ]
        for at, label in _program_items:
            act = program_menu.addAction(label)
            act.triggered.connect(lambda checked, t=at, pos=event.scenePos():
                self._create_node_and_connect_if_needed(t, pos))

        menu.addSeparator()

        # Создать заметку
        act_note = menu.addAction(tr("📌 Создать заметку"))
        act_note.triggered.connect(lambda checked, pos=event.scenePos(): 
            self._create_node_and_connect_if_needed(AgentType.NOTE, pos))

        menu.addSeparator()
        
        # Paste at position
        act_paste = menu.addAction(tr("📥 Вставить сюда"))
        act_paste.setShortcut("Ctrl+V")
        act_paste.triggered.connect(lambda: self._main_window._paste_at(event.scenePos()) if self._main_window else None)
        
        menu.addSeparator()
        
        # Skills management
        act_skill = menu.addAction(tr("🔧 Создать новый скилл"))
        act_skill.triggered.connect(lambda: self._main_window._add_custom_skill() if self._main_window else None)
        
        act_load = menu.addAction(tr("📂 Загрузить скиллы из папки..."))
        act_load.triggered.connect(lambda: self._main_window._load_skills_from_folder() if self._main_window else None)
        
        # If clicked on item - additional options
        views = self.views()
        if views:
            transform = views[0].transform()
            item = self.itemAt(event.scenePos(), transform)

            # ── Клик по РЕБРУ ───────────────────────────────
            if isinstance(item, EdgeItem):
                menu.addSeparator()
                cond_menu = menu.addMenu(tr("🔀 Тип перехода"))
                cond_map = {
                    tr("➡️  Всегда"):            EdgeCondition.ALWAYS,
                    tr("✅  Только при успехе"): EdgeCondition.ON_SUCCESS,
                    tr("⚡  Только при ошибке"): EdgeCondition.ON_FAILURE,
                    tr("❓  По условию"):         EdgeCondition.ON_CONDITION,
                }
                for label, cond in cond_map.items():
                    act = cond_menu.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(item.edge.condition == cond)
                    def _set_cond(checked, ei=item, c=cond):
                        ei.edge.condition = c
                        ei.edge.label = {
                            EdgeCondition.ON_FAILURE: "⚡ error",
                            EdgeCondition.ON_SUCCESS: "✅ ok",
                            EdgeCondition.ON_CONDITION: "❓ cond",
                        }.get(c, "")
                        ei.update_position()
                        ei.update()
                        if self._workflow:
                            # Сохраняем изменение в модели
                            for e in self._workflow.edges:
                                if e.id == ei.edge.id:
                                    e.condition = c
                                    e.label = ei.edge.label
                                    break
                        if self._main_window:
                            self._main_window._log_msg(
                                f"🔀 Ребро → {c.value}")
                    act.triggered.connect(_set_cond)

                menu.addSeparator()
                act_del_e = menu.addAction(tr("🗑 Удалить связь"))
                act_del_e.triggered.connect(lambda: (
                    self._workflow.remove_edge(item.edge.id) if self._workflow else None,
                    self._edge_items.pop(item.edge.id, None),
                    self.removeItem(item),
                ))
        
        # ═══ Цвет блока ═══
        color_menu = menu.addMenu(tr("🎨 Цвет"))
        colors = [
            ("", tr("По умолчанию")),
            ("#F7768E", tr("Красный")),
            ("#9ECE6A", tr("Зеленый")),
            ("#E0AF68", tr("Желтый")),
            ("#7AA2F7", tr("Синий")),
            ("#BB9AF7", tr("Фиолетовый")),
            ("#FF9E64", tr("Оранжевый")),
            ("#2AC3DE", tr("Бирюзовый")),
        ]
        for color_val, color_name in colors:
                    act = color_menu.addAction(color_name)
                    if color_val:
                        pix = QPixmap(16, 16)
                        pix.fill(QColor(color_val))
                        act.setIcon(QIcon(pix))
                    # Захватываем node в момент создания, не ссылку на item
                    # ═══ ИСПРАВЛЕНИЕ: BlockHeaderItem имеет _parent_node, не node ═══
                    # Определяем node_ref безопасно для любого типа item
                    if isinstance(item, BlockHeaderItem):
                        node_ref = item._parent_node.node if item._parent_node else None
                    elif hasattr(item, 'node'):
                        node_ref = item.node
                    else:
                        node_ref = None

                    if node_ref:
                        act.triggered.connect(
                            lambda checked, n=node_ref, c=color_val: self._set_node_color(n, c)
                        )
                    else:
                        act.setEnabled(False)
        
        # ═══ Комментарий ═══
        if hasattr(item, 'node') or isinstance(item, BlockHeaderItem):
            act_comment = menu.addAction(tr("💬 Комментарий"))
            # Используем уже вычисленный ранее actual_node (он у вас есть в коде ниже)
            act_comment.triggered.connect(lambda: self._edit_node_comment(actual_node))
        
        # ═══ Прикрепление ═══
        # ═══ ИСПРАВЛЕНИЕ: Получаем node с проверкой типа ═══
        actual_node = None
        if isinstance(item, AgentNodeItem):
            actual_node = item.node
        elif isinstance(item, BlockHeaderItem):
            actual_node = item._parent_node.node if item._parent_node else None
        
        # ═══ УДАЛЕНИЕ БЛОКА: если клик по шапке — добавляем опцию удаления всего блока ═══
        if isinstance(item, BlockHeaderItem) and actual_node:
            menu.addSeparator()
            act_del_block = menu.addAction(tr("🗑 Удалить весь блок"))
            # Собираем все ноды блока для удаления
            block_nodes = []
            current_id = actual_node.id
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                node_item = self.get_node_item(current_id)
                if not node_item:
                    break
                block_nodes.append(node_item.node)
                children = getattr(node_item.node, 'attached_children', [])
                current_id = children[0] if children else None
            
            act_del_block.triggered.connect(
                lambda checked, nodes=block_nodes: self._delete_nodes_list(nodes)
            )
            
        if actual_node is None:
            menu.exec(event.screenPos())
            return
            
        attach_menu = menu.addMenu(tr("📎 Прикрепить"))
        if actual_node.attached_to:
            act_detach = attach_menu.addAction(tr("📤 Открепить"))
            act_detach.triggered.connect(lambda: self.detach_node(actual_node.id))
        else:
            for other_id, other_item in self._node_items.items():
                if other_item != item and other_id not in getattr(actual_node, 'attached_children', []):
                    act = attach_menu.addAction(f"→ {other_item.node.name[:20]}")
                    act.triggered.connect(
                        lambda checked, child=actual_node.id, parent=other_id: 
                        self.attach_node(child, parent)
                    )
        
        menu.addSeparator()
        
        # ═══ Стартовое действие ═══
        if actual_node and self._workflow:
            is_entry = (self._workflow.entry_node_id == actual_node.id)
            act_entry = menu.addAction(tr("✅ Стартовое действие") if is_entry else tr("▶ Установить как стартовое"))
            _node_id_for_entry = actual_node.id
            act_entry.triggered.connect(lambda checked, nid=_node_id_for_entry: self._set_entry_node(nid))
        
        # Если клик по агенту - добавляем пункты управления
        views = self.views()
        if views:
            transform = views[0].transform()
            item = self.itemAt(event.scenePos(), transform)
            if isinstance(item, AgentNodeItem) and self._main_window:
                menu.addSeparator()
                
                # ═══ УДАЛЕНИЕ — один для ВСЕХ типов нод (AI + сниппеты + заметки) ═══
                act_del = menu.addAction(tr("🗑 Удалить"))
                act_del.triggered.connect(lambda: self._main_window._delete_selected())
                
                # AI-агенты: меню скиллов
                if item.node.agent_type in AI_AGENT_TYPES:
                    # Подменю добавления скилла
                    add_skill_menu = menu.addMenu(tr("➕ Добавить скилл"))
                    for skill in self._main_window._skill_registry.all_skills():
                        act = add_skill_menu.addAction(f"{skill.icon} {skill.name}")
                        act.triggered.connect(
                            lambda checked, n=item.node, s=skill: 
                            self._main_window._add_skill_to_node_direct(n, s.id)
                        )
                    
                    # Показать текущие скиллы агента
                    if item.node.skill_ids:
                        current_menu = menu.addMenu(tr("🔧 Текущие скиллы"))
                        for sid in item.node.skill_ids:
                            skill = self._main_window._skill_registry.get(sid)
                            if skill:
                                act = current_menu.addAction(f"{skill.icon} {skill.name}")
                                act.triggered.connect(
                                    lambda checked, s=skill: 
                                    self._main_window._edit_skill(s)
                                )
                
                # Сниппеты: настройки вместо скиллов
                elif item.node.agent_type in SNIPPET_TYPES:
                    act_settings = menu.addMenu(tr("⚙️ Настройки сниппета"))
                    # Подменю для быстрого доступа к типу сниппета
                    type_act = act_settings.addAction(f"{tr('Тип:')} {item.node.agent_type.value}")
                    type_act.setEnabled(False)
                    act_settings.addSeparator()
                    act_edit = act_settings.addAction(tr("✏️ Редактировать в панели"))
                    act_edit.triggered.connect(lambda: item.setSelected(True))
        
        menu.exec(event.screenPos())
