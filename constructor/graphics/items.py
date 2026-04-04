"""Графические элементы нод и связей."""
from __future__ import annotations
import math
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QLineF, QEvent
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont, QPolygonF, QPainterPath,
    QLinearGradient, QCursor
)
from PyQt6.QtWidgets import (
    QGraphicsRectItem, QGraphicsItem, QGraphicsDropShadowEffect,
    QGraphicsPathItem, QMenu, QGraphicsLineItem, QApplication
)

from ..constants import _AGENT_COLORS, _AGENT_ICONS, SNIPPET_TYPES, NOTE_TYPES, get_node_category
from services.agent_models import AgentType, EdgeCondition, AgentEdge

# ═══ ЛОКАЛИЗАЦИЯ ═══
try:
    from ..i18n import tr
except ImportError:
    def tr(text: str) -> str:
        return text
# ═══════════════════

if TYPE_CHECKING:
    from .scene import WorkflowScene

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

def is_dark_theme():
    """Определяет, используется ли темная тема."""
    try:
        # PyQt6.5+: используем colorScheme
        from PyQt6.QtCore import Qt
        scheme = QApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        elif scheme == Qt.ColorScheme.Light:
            return False
    except (AttributeError, ImportError):
        pass
    
    # Fallback: проверяем яркость фона палитры
    palette = QApplication.palette()
    bg_color = palette.color(QApplication.palette().ColorRole.Window)
    # Если яркость фона < 128 — считаем темной темой
    return bg_color.lightness() < 128

class AgentNodeItem(QGraphicsRectItem):
    """Visual representation of an AgentNode on the canvas."""

    PORT_RADIUS = 6

    def __init__(self, node: AgentNode, scene_ref: "WorkflowScene"):
        # Защита: проверяем что нода валидна
        if node is None or not hasattr(node, 'id'):
            raise ValueError("AgentNodeItem: node cannot be None")
        
        w, h = node.width, node.height
        super().__init__(0, 0, w, h)
        self.node = node
        
        # --- ДОБАВЛЕНО ДЛЯ СТАРЫХ ПРОЕКТОВ ---
        if not hasattr(self.node, 'attached_to'):
            self.node.attached_to = None
        if not hasattr(self.node, 'attached_children'):
            self.node.attached_children = []
        # -------------------------------------

        self._scene_ref = scene_ref  # может быть None, проверяем при использовании
        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self._creation_order = getattr(scene_ref, '_node_counter', 0)
        if scene_ref:
            scene_ref._node_counter = getattr(scene_ref, '_node_counter', 0) + 1
        self._hovered = False
        self._connecting = False
        self._temp_line = None
        self._drag_start_port = None
        self._detach_triggered = False  # Флаг: уже открепили при перетаскивании
        self._dragging_block = False
        self._drag_block_insert_target = None  # Целевой блок для вставки
        self._drag_block_insert_pos = None     # 'before' или 'after'
        self._drag_block_insert_node = None    # Конкретная нода вставки
        self._in_item_change = False  # Защита от рекурсии в itemChange
        self._drag_block_start_pos = None
        self._drag_block_mouse_start = None
        self._dragged_block_nodes = []
        self._block_wrapper_rect = None
        self._setup_visuals()

        # ═══ Создаем шапку блока если это корень цепочки ═══
        self._block_header = None
        self._update_block_header()
        
        # Сразу применяем динамический размер при создании
        self.update_dynamic_size()
    
    def _update_drag_preview(self, scene_pos: QPointF):
        """Обновить визуальный превью при перетаскивании над блоком."""
        if not self._scene_ref:
            return
        
        # Ищем ближайший блок под курсором
        target_block = None
        insert_position = None  # 'before', 'after', 'child'
        min_distance = float('inf')
        
        for item in self._scene_ref.items(scene_pos):
            if not isinstance(item, AgentNodeItem) or item == self:
                continue
                
            # Проверяем, является ли item частью блока (имеет детей или родителя)
            has_children = bool(getattr(item.node, 'attached_children', []))
            has_parent = bool(getattr(item.node, 'attached_to', None))
            
            if not has_children and not has_parent:
                continue  # Одиночная нода, не блок
            
            item_rect = item.sceneBoundingRect()
            item_center_y = item_rect.center().y()
            
            # Расстояние по Y от центра нашей ноды до центра целевой
            my_center_y = self.sceneBoundingRect().center().y()
            distance_y = abs(my_center_y - item_center_y)
            
            # Проверяем выравнивание по X (должны быть примерно в одной колонке)
            x_aligned = abs(self.sceneBoundingRect().center().x() - item_rect.center().x()) < 80
            
            if x_aligned and distance_y < min_distance:
                min_distance = distance_y
                target_block = item
                
                # Определяем позицию вставки
                if my_center_y < item_center_y - item_rect.height() / 3:
                    insert_position = 'before'  # Над нодой
                elif my_center_y > item_center_y + item_rect.height() / 3:
                    insert_position = 'after'   # Под нодой
                else:
                    insert_position = 'child'   # Как ребёнок
        
        # Применяем визуальный фидбек
        if target_block and min_distance < 100:
            # Подсвечиваем целевой блок
            self._drag_target_block = target_block
            self._drag_insert_pos = insert_position
            
            # Меняем курсор и визуально "притягиваем" к позиции
            self.setCursor(QCursor(Qt.CursorShape.DragCopyCursor))
            
            # Прозрачность для эффекта "встраивания"
            self.setOpacity(0.7)
            
            # Подсвечиваем целевой блок
            target_block._hovered = True
            target_block.update()
        else:
            if getattr(self, '_drag_target_block', None):
                self._drag_target_block._hovered = False
                self._drag_target_block.update()
            self._drag_target_block = None
            self._drag_insert_pos = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.setOpacity(1.0)
    
    def _get_block_at_pos(self, scene_pos: QPointF) -> Optional[AgentNodeItem]:
        """Найти корневой блок под позицией (только корни цепочек)."""
        if not self._scene_ref:
            return None
            
        for item in self._scene_ref.items(scene_pos):
            if not isinstance(item, AgentNodeItem) or item == self:
                continue
            
            # Проверяем, является ли item корнем блока (есть дети, нет родителя)
            has_children = bool(getattr(item.node, 'attached_children', []))
            has_parent = bool(getattr(item.node, 'attached_to', None))
            
            if has_children and not has_parent:
                return item
        
        return None
    
    def _get_chain_root(self) -> Optional[AgentNodeItem]:
        """Получить корень цепочки для этого блока."""
        if not self._scene_ref:
            return None
            
        current = self
        visited = set()
        
        while current and current.node.id not in visited:
            visited.add(current.node.id)
            parent_id = getattr(current.node, 'attached_to', None)
            
            if not parent_id:
                # Это корень
                has_children = bool(getattr(current.node, 'attached_children', []))
                if has_children:
                    return current
                return None
            
            parent = self._scene_ref.get_node_item(parent_id)
            if not parent:
                break
            current = parent
        
        return None
    
    def _is_in_block_chain(self, potential_ancestor: AgentNodeItem) -> bool:
        """Проверить, является ли potential_ancestor предком этого блока."""
        if not self._scene_ref or not potential_ancestor:
            return False
            
        current_id = self.node.id
        visited = set()
        
        while current_id and current_id not in visited:
            visited.add(current_id)
            item = self._scene_ref.get_node_item(current_id)
            if not item:
                break
            
            # Проверяем детей
            for child_id in getattr(item.node, 'attached_children', []):
                if child_id == potential_ancestor.node.id:
                    return True
                # Рекурсивно проверяем детей
                child_item = self._scene_ref.get_node_item(child_id)
                if child_item and self._is_in_block_chain_recursive(child_id, potential_ancestor.node.id, set()):
                    return True
            
            # Идём вверх по цепочке
            parent_id = getattr(item.node, 'attached_to', None)
            if not parent_id:
                break
            current_id = parent_id
        
        return False
    
    def _is_in_block_chain_recursive(self, node_id: str, target_id: str, visited: set) -> bool:
        """Рекурсивная проверка вниз по цепочке."""
        if node_id in visited:
            return False
        visited.add(node_id)
        
        item = self._scene_ref.get_node_item(node_id)
        if not item:
            return False
        
        for child_id in getattr(item.node, 'attached_children', []):
            if child_id == target_id:
                return True
            if self._is_in_block_chain_recursive(child_id, target_id, visited):
                return True
        
        return False
    
    def _get_all_chain_nodes(self, root_item: AgentNodeItem) -> list:
        """Получить все ноды в цепочке начиная с корня (все дети рекурсивно)."""
        nodes = []
        visited = set()

        def _collect(node_id):
            if not node_id or node_id in visited:
                return
            visited.add(node_id)
            item = self._scene_ref.get_node_item(node_id)
            if not item:
                return
            nodes.append(item)
            for child_id in getattr(item.node, 'attached_children', []):
                _collect(child_id)

        _collect(root_item.node.id)
        return nodes
    
    def _find_insert_position_in_block(self, block_root: AgentNodeItem, 
                                       drag_scene_pos: QPointF) -> tuple:
        """Определить позицию вставки внутри блока: ('before', node) или ('after', node)."""
        chain = self._get_all_chain_nodes(block_root)
        if not chain:
            return ('after', block_root)
        
        # Находим ближайшую ноду по Y
        min_dist = float('inf')
        closest_node = None
        position = 'after'
        
        for node in chain:
            rect = node.sceneBoundingRect()
            center_y = rect.center().y()
            dist = abs(drag_scene_pos.y() - center_y)
            
            if dist < min_dist:
                min_dist = dist
                closest_node = node
                
                # Определяем before/after
                if drag_scene_pos.y() < center_y - rect.height() / 4:
                    position = 'before'
                elif drag_scene_pos.y() > center_y + rect.height() / 4:
                    position = 'after'
                else:
                    # Внутри ноды — вставляем после
                    position = 'after'
        
        return (position, closest_node)
    
    def update_dynamic_size(self):
        """Динамическое изменение высоты для Switch."""
        if getattr(self.node, 'agent_type', None) == AgentType.SWITCH:
            # Получаем актуальный список условий
            conf = getattr(self.node, 'snippet_config', {}) or {}
            cases = conf.get('cases', [])
            
            # Если данные в JSON-строке — декодируем
            if isinstance(cases, str):
                try:
                    import json
                    cases = json.loads(cases)
                except Exception:
                    # Формат "одна строка = одно условие"
                    cases = [ln.strip() for ln in cases.split('\n') if ln.strip()]
            
            count = len(cases) if isinstance(cases, list) else 0
            
            # Расчет: база 80 + 35 пикселей на каждое условие, мин 2 слота
            min_cases = max(count, 2)
            new_h = 80 + (min_cases * 35)
            new_h = max(120, min(new_h, 800))
            
            if abs(self.node.height - new_h) > 1:
                self.prepareGeometryChange() # КРИТИЧНО для перерисовки
                self.node.height = new_h
                self.setRect(0, 0, self.node.width, self.node.height)
                
                # Обновляем порты и связи
                if hasattr(self, '_position_ports'):
                    self._position_ports()
                if self.scene() and hasattr(self.scene(), 'update_edges'):
                    self.scene().update_edges()
                self.update()
    
    def _update_block_header(self):
        """Создать или удалить шапку блока в зависимости от статуса."""
        try:
            scene = self.scene()
            if scene is None:
                self._remove_block_header()
                return
            
            if self._scene_ref is None:
                self._remove_block_header()
                return
            
            has_children = bool(getattr(self.node, 'attached_children', []))
            has_parent = bool(getattr(self.node, 'attached_to', None))
            
            needs_header = has_children and not has_parent
            
            # ═══ ИСПРАВЛЕНИЕ: Если шапка есть — обновляем её Z-ордер относительно родителя ═══
            if self._block_header and self._block_header.scene():
                # Находим корень цепочки (верхний родитель)
                root_item = self
                current = self
                while current:
                    parent_id = getattr(current.node, 'attached_to', None)
                    if parent_id:
                        parent_item = self._scene_ref.get_node_item(parent_id)
                        if parent_item:
                            root_item = parent_item
                            current = parent_item
                        else:
                            break
                    else:
                        break
                
                # Шапка корня всегда выше всех
                if root_item == self:
                    self._block_header.setZValue(self.zValue() + 1000)
                else:
                    # Для не-корневых нод шапка не нужна, но если есть — убираем
                    self._remove_block_header()
                    return
            
            if needs_header and not self._block_header:
                # ═══ ИСПРАВЛЕНИЕ: сначала создаём, потом добавляем в сцену, потом обновляем позицию ═══
                self._block_header = BlockHeaderItem(self)
                self._block_header.setPos(self.pos())
                # ═══ ИСПРАВЛЕНИЕ: Z-ордер шапки = Z-ордер ноды + 1, но с учётом порядка создания ═══
                base_z = max(15, self.zValue() + 1)
                # Гарантируем что более новые блоки выше старых
                creation_layer = getattr(self, '_creation_order', 0) * 0.001
                self._block_header.setZValue(base_z + creation_layer + 1000)  # +1000 чтобы точно быть выше всех нод
                scene.addItem(self._block_header)
                self._block_header.update_geometry()
            elif not needs_header and self._block_header:
                self._remove_block_header()
            elif self._block_header:
                self._block_header.update_geometry()
        except Exception as e:
            print(f"[_update_block_header ERROR] {e}")
    
    def _remove_block_header(self):
        """Безопасное удаление шапки."""
        if not self._block_header:
            return
        try:
            if self._block_header.scene():
                self._block_header.scene().removeItem(self._block_header)
        except RuntimeError:
            pass
        self._block_header = None
    
    def _remove_block_header(self):
        """Безопасное удаление шапки."""
        if not self._block_header:
            return
        try:
            if self._block_header.scene():
                self._block_header.scene().removeItem(self._block_header)
        except RuntimeError:
            pass
        self._block_header = None

    def update_block_header_position(self):
        """Обновить позицию шапки при движении ноды."""
        # Защита: проверяем что и нода и шапка в сцене
        if self.scene() is None:
            return
        if self._block_header and self._block_header.scene():
            self._block_header.update_geometry()
    
    def _paint_block_wrapper(self, painter: QPainter, w: float, h: float, color: QColor):
        """Рисует единую обёртку для всего блока прикреплённых нодов."""
        if not self._scene_ref:
            return
            
        # Проверяем, являемся ли мы корнем цепочки (нет родителя)
        has_parent = bool(getattr(self.node, 'attached_to', None))
        if has_parent:
            return  # Не корень — не рисуем обёртку
            
        has_children = bool(getattr(self.node, 'attached_children', []))
        if not has_children:
            return  # Нет детей — нечего оборачивать
        
        # Собираем всю цепочку рекурсивно
        def get_chain_info(node_id, visited=None):
            if visited is None:
                visited = set()
            if node_id in visited:
                return [], 0
            visited.add(node_id)
            
            item = self._scene_ref.get_node_item(node_id)
            if not item:
                return [], 0
            
            children_ids = getattr(item.node, 'attached_children', [])
            chain = [item]
            total_height = item.node.height
            
            if children_ids:
                child_id = children_ids[0]  # Цепочка — только первый ребёнок
                sub_chain, sub_height = get_chain_info(child_id, visited)
                chain.extend(sub_chain)
                total_height += 10 + sub_height  # 10px отступ между нодами
            
            return chain, total_height
        
        chain, chain_height = get_chain_info(self.node.id)
        if len(chain) < 2:
            return  # Только один нод — не рисуем обёртку
        
        chain_count = len(chain)
        
        # Параметры обёртки
        MARGIN = 8
        HEADER = 22  # Высота шапки для захвата
        SPACING = 10  # Отступ между нодами в цепочке
        
        # Вычисляем общую высоту: шапка + все ноды + отступы между ними
        total_height = HEADER + chain_height + (chain_count - 1) * SPACING + MARGIN
        
        # Ширина — по максимальной ширине нода в цепочке
        max_width = max(item.node.width for item in chain)
        
        # Прямоугольник обёртки (относительно текущего нода)
        block_rect = QRectF(
            -MARGIN,                    # left
            -HEADER - MARGIN,            # top (шапка выше нода)
            max_width + MARGIN * 2,      # width
            total_height + MARGIN        # height
        )
        
        # Сохраняем для проверки кликов
        self._block_wrapper_rect = block_rect
        
        # Рисуем фон обёртки (полупрозрачный)
        block_bg = QColor(color)
        block_bg.setAlpha(30)
        block_path = QPainterPath()
        block_path.addRoundedRect(block_rect, 10, 10)
        painter.fillPath(block_path, QBrush(block_bg))
        
        # Рисуем границу (сплошная линия)
        border_pen = QPen(color, 2.0, Qt.PenStyle.SolidLine)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(block_rect, 10, 10)
        
        # Рисуем шапку (где можно ухватиться)
        header_rect = QRectF(
            -MARGIN,
            -HEADER - MARGIN,
            max_width + MARGIN * 2,
            HEADER
        )
        header_bg = QColor(color)
        header_bg.setAlpha(100)
        header_path = QPainterPath()
        # Верхние углы скруглены, нижние — прямые
        header_path.addRoundedRect(header_rect, 10, 10)
        # Закрываем низ шапки
        header_path.addRect(QRectF(-MARGIN, -MARGIN - 4, max_width + MARGIN * 2, 6))
        painter.fillPath(header_path, QBrush(header_bg))
        
        # Разделительная линия между шапкой и первым нодом
        painter.setPen(QPen(color, 1))
        line_y = int(-MARGIN)
        painter.drawLine(
            int(-MARGIN + 2), line_y,
            int(max_width + MARGIN - 2), line_y
        )
        
        # Текст в шапке
        painter.setPen(QPen(QColor(get_color("tx0")), 1))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        
        # Иконка "ручки" для перетаскивания (⋮⋮ или ⠿)
        header_text = f"⛓ Блок · {chain_count} нодов  ⠿"
        painter.drawText(
            header_rect.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            header_text
        )
        
        # Подсказка при наведении на шапку
        if self._hovered:
            # Проверяем, что мышь в зоне шапки (по Y)
            # Это приблизительная проверка, точная будет в mousePressEvent
            painter.setPen(QPen(QColor(get_color("ac")), 1))
            painter.setFont(QFont("Segoe UI", 7))
            hint_rect = QRectF(
                -MARGIN, 
                -HEADER - MARGIN - 14,
                max_width + MARGIN * 2,
                12
            )
            painter.drawText(
                hint_rect,
                Qt.AlignmentFlag.AlignCenter,
                "Зажмите шапку чтобы переместить блок"
            )
    
    def mouseDoubleClickEvent(self, event):
        """Двойной клик — быстрое открепление первого нода из блока"""
        try:
            if event.button() != Qt.MouseButton.LeftButton:
                super().mouseDoubleClickEvent(event)
                return
            
            if self.scene() is None or self._scene_ref is None:
                super().mouseDoubleClickEvent(event)
                return
            
            has_children = bool(getattr(self.node, 'attached_children', []))
            has_parent = bool(getattr(self.node, 'attached_to', None))
            
            if not has_children or has_parent:
                super().mouseDoubleClickEvent(event)
                return
            
            first_child_id = self.node.attached_children[0] if self.node.attached_children else None
            if not first_child_id:
                super().mouseDoubleClickEvent(event)
                return
            
            # Сохраняем ссылку на сцену ДО вызова detach
            scene_ref = self._scene_ref
            
            # Открепляем первого ребёнка
            scene_ref.detach_node(first_child_id)
            
            # Обновляем отображение через таймер чтобы избежать рекурсии
            QTimer.singleShot(0, lambda: self._delayed_update_after_detach(scene_ref))
            
            event.accept()
            
        except Exception as e:
            print(f"[mouseDoubleClickEvent ERROR] {e}")
            event.accept()
    
    def _delayed_update_after_detach(self, scene_ref):
        """Отложенное обновление после открепления."""
        try:
            if hasattr(scene_ref, '_main_window'):
                mw = scene_ref._main_window
                if hasattr(mw, '_log_msg'):
                    remaining = len(getattr(self.node, 'attached_children', []))
                    mw._log_msg(f"🔓 {self.node.name} " + tr("вытянут, {0} нодов осталось").format(remaining))
            self.update()
            scene_ref.update()
            scene_ref.invalidate()
        except Exception as e:
            print(f"[_delayed_update_after_detach ERROR] {e}")
    
    def _start_edge_drag(self, event):
        self._connecting = True
        scene = self.scene()
        if scene is None:
            print("⚠️ _start_edge_drag: scene is None")
            self._connecting = False
            return
        self._temp_line = QGraphicsLineItem()
        # Красный пунктир для порта ошибки, синий для обычного
        if self._drag_start_port == 'error':
            pen = QPen(QColor(get_color("err")), 2, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(get_color("ac")), 2, Qt.PenStyle.DashLine)
        self._temp_line.setPen(pen)
        self._temp_line.setZValue(100)
        scene.addItem(self._temp_line)
        self._update_temp_line(event.scenePos())

    def _update_temp_line(self, scene_pos):
        if self._temp_line:
            scene = self.scene()
            if scene is None:
                return
            # Ищем цель под курсором для определения стороны выхода
            target_item = None
            items = scene.items(scene_pos)
            for item in items:
                if isinstance(item, AgentNodeItem) and item != self:
                    target_item = item
                    break
            
            if self._drag_start_port == 'error':
                start = self.error_port_pos()
            elif isinstance(self._drag_start_port, str) and self._drag_start_port.startswith('switch_case_'):
                try:
                    i = int(self._drag_start_port.rsplit('_', 1)[-1])
                    cases = self._get_switch_cases()
                    start = self.pos() + self._switch_case_port_local(i, max(len(cases), 1))
                except Exception:
                    target_center = target_item.pos() + QPointF(target_item.node.width / 2, target_item.node.height / 2) if target_item else None
                    start = self.output_port_pos(target_center)
            else:
                target_center = target_item.pos() + QPointF(target_item.node.width / 2, target_item.node.height / 2) if target_item else None
                start = self.output_port_pos(target_center)
            self._temp_line.setLine(QLineF(start, scene_pos))

    def mouseMoveEvent(self, event):
        if getattr(self, '_connecting', False) and getattr(self, '_temp_line', None):
            self._update_temp_line(event.scenePos())
            
            # Автоскролл для НОВЫХ стрелочек
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                from PyQt6.QtGui import QCursor
                from PyQt6.QtCore import QTimer
                
                view_pos = view.mapFromGlobal(QCursor.pos())
                view_rect = view.rect()
                
                margin = 40
                step = 2
                dx, dy = 0, 0
                
                if view_pos.x() < margin: dx = -step
                elif view_pos.x() > view_rect.width() - margin: dx = step
                if view_pos.y() < margin: dy = -step
                elif view_pos.y() > view_rect.height() - margin: dy = step
                
                if dx != 0 or dy != 0:
                    h_bar = view.horizontalScrollBar()
                    v_bar = view.verticalScrollBar()
                    QTimer.singleShot(0, lambda: h_bar.setValue(h_bar.value() + dx))
                    QTimer.singleShot(0, lambda: v_bar.setValue(v_bar.value() + dy))
            return
            
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # ═══ Сброс индикации вставки блока ═══
        if hasattr(self, '_drag_block_insert_target') and self._drag_block_insert_target:
            self._drag_block_insert_target._hovered = False
            self._drag_block_insert_target.update()
        self._drag_block_insert_target = None
        self._drag_block_insert_pos = None
        self._drag_block_insert_node = None
        # Защита: проверяем что сцена существует
        scene = self.scene()
        if scene is None:
            super().mouseReleaseEvent(event)
            return
        
        # ═══ ИСПРАВЛЕНИЕ: Сбрасываем визуальную индикацию drag-over ═══
        self.setOpacity(1.0)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        if hasattr(self, '_drag_target_block') and self._drag_target_block:
            self._drag_target_block._hovered = False
            self._drag_target_block.update()
            self._drag_target_block = None
        
        # ═══ ИСПРАВЛЕНИЕ: ПРЕДОХРАНИТЕЛЬ — проверяем не улетел ли сниппет при отпускании ═══
        if event.button() == Qt.MouseButton.LeftButton and not self._connecting:
            cursor_pos = event.scenePos()
            node_center = self.sceneBoundingRect().center()
            distance = (cursor_pos - node_center).manhattanLength()
            
            # Если сниппет далеко от курсора (более чем на 150px) — телепортнулся
            if distance > 150:
                # Возвращаем сниппет под курсор мыши
                offset = QPointF(self.node.width / 2, self.node.height / 2)
                corrected_pos = cursor_pos - offset
                
                # Snap to grid
                grid = 20
                x = round(corrected_pos.x() / grid) * grid
                y = round(corrected_pos.y() / grid) * grid
                corrected_pos = QPointF(x, y)
                
                self.setPos(corrected_pos)
                self.node.x = corrected_pos.x()
                self.node.y = corrected_pos.y()
                
                # Обновляем рёбра
                if self._scene_ref:
                    self._scene_ref.update_edges()
                    self._scene_ref.invalidate()
                    self._scene_ref.update()
                
                # Логируем для отладки
                if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                    mw = self._scene_ref._main_window
                    if hasattr(mw, '_log_msg'):
                        mw._log_msg(f"🛡️ Телепорт {self.node.name} предотвращён, возвращён под курсор")
        # ═════════════════════════════════════════════════════════════════════════════════
        
        # ═══ ИСПРАВЛЕНИЕ: Игнорируем правый клик, чтобы стрелка не сбрасывалась при открытии меню ═══
        if event.button() == Qt.MouseButton.RightButton:
            super().mouseReleaseEvent(event)
            return
        
        # ═══ ЗАВЕРШЕНИЕ ПЕРЕТАСКИВАНИЯ БЛОКА ═══
        if getattr(self, '_dragging_block', False):
            self._dragging_block = False
            
            # ═══ ИСПРАВЛЕНИЕ: если не было реального перемещения — не создаём undo ═══
            click_pos = getattr(self, '_drag_block_mouse_start', None)
            if click_pos is not None:
                delta = event.scenePos() - click_pos
                if abs(delta.x()) < 3 and abs(delta.y()) < 3:
                    # Восстанавливаем оригинальные позиции
                    for node_info in self._dragged_block_nodes:
                        item = node_info['item']
                        if item.scene() is not None:
                            item.setPos(node_info['start_pos'])
                            item.node.x = node_info['start_pos'].x()
                            item.node.y = node_info['start_pos'].y()
                    if self._scene_ref:
                        self._scene_ref.update_edges()
                    # ═══ ИСПРАВЛЕНИЕ: Восстанавливаем Z-ордер на основе порядка создания ═══
                    for i, node_info in enumerate(self._dragged_block_nodes):
                        item = node_info['item']
                        base_z = 10 + getattr(item, '_creation_order', 0) * 0.001
                        item.setZValue(base_z)
                        if hasattr(item, '_block_header') and item._block_header:
                            item._block_header.setZValue(base_z + 1000)

                    self._dragged_block_nodes = []
                    self._drag_start_mouse_pos = None
                    self._detach_triggered = False
                    event.accept()
                    return
            
            # Создаём undo для перемещения блока
            if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                mw = self._scene_ref._main_window
                if hasattr(mw, '_history'):
                    old_positions = [(n['item'], QPointF(n['start_pos'].x(), n['start_pos'].y())) 
                                    for n in self._dragged_block_nodes]
                    new_positions = [(n['item'], QPointF(n['item'].pos().x(), n['item'].pos().y())) 
                                    for n in self._dragged_block_nodes]
                    
                    scene_ref = self._scene_ref
                    
                    def make_undo_block(old_pos_list):
                        def _undo():
                            for item, pos in old_pos_list:
                                item.setPos(pos)
                                item.node.x = pos.x()
                                item.node.y = pos.y()
                            scene_ref.update_edges()
                            scene_ref.invalidate()
                            scene_ref.update()
                        return _undo
                    
                    def make_redo_block(new_pos_list):
                        def _redo():
                            for item, pos in new_pos_list:
                                item.setPos(pos)
                                item.node.x = pos.x()
                                item.node.y = pos.y()
                            scene_ref.update_edges()
                            scene_ref.invalidate()
                            scene_ref.update()
                        return _redo
                    
                    mw._history.push(
                        make_redo_block(new_positions),
                        make_undo_block(old_positions),
                        tr("Перемещение блока ({0} нодов)").format(len(self._dragged_block_nodes))
                    )
                    mw._mark_modified_from_props()
            
            self._dragged_block_nodes = []
            # Сбрасываем mouse-origin и флаг открепления чтобы избежать телепортации
            self._drag_start_mouse_pos = None
            self._detach_triggered = False
            event.accept()
            return
        
        # Сбрасываем флаг открепления
        self._detach_triggered = False
        
        # ═══ НОВОЕ: ВСТАВКА БЛОКА В БЛОК ═══
        # Проверяем, перетаскиваем ли мы целый блок и хотим вставить его в другой блок
        _is_dragging_block = (
            hasattr(self, '_drag_start_pos') and 
            self._drag_start_pos is not None and 
            self._drag_start_pos != self.pos() and
            bool(getattr(self.node, 'attached_children', [])) and 
            not getattr(self.node, 'attached_to', None)
        )
        
        if (_is_dragging_block and 
            event.button() == Qt.MouseButton.LeftButton and 
            not self._connecting and 
            self._scene_ref):
            
            target_block = getattr(self, '_drag_block_insert_target', None)
            insert_pos = getattr(self, '_drag_block_insert_pos', None)
            target_node = getattr(self, '_drag_block_insert_node', None)
            
            if target_block and insert_pos and target_node:
                try:
                    scene = self._scene_ref
                    
                    # Получаем все ноды перетаскиваемого блока (в порядке цепочки)
                    dragged_nodes = self._get_all_chain_nodes(self)
                    if not dragged_nodes:
                        raise ValueError("Empty dragged block")
                    
                    first_dragged = dragged_nodes[0]
                    last_dragged = dragged_nodes[-1]
                    
                    # Определяем точку вставки в целевом блоке
                    target_chain = self._get_all_chain_nodes(target_block)
                    
                    # Находим индекс target_node в цепочке
                    target_idx = -1
                    for i, n in enumerate(target_chain):
                        if n.node.id == target_node.node.id:
                            target_idx = i
                            break
                    
                    if target_idx < 0:
                        raise ValueError("Target node not found in chain")
                    
                    # ═══ ИСПРАВЛЕНИЕ: Правильная вставка блока с сохранением всех связей ═══
                    
                    # Сначала отвязываем ВЕСЬ dragged блок от его текущего места
                    # Находим родителя dragged блока (если есть)
                    dragged_parent_id = getattr(first_dragged.node, 'attached_to', None)
                    if dragged_parent_id:
                        dragged_parent = scene.get_node_item(dragged_parent_id)
                        if dragged_parent and first_dragged.node.id in dragged_parent.node.attached_children:
                            dragged_parent.node.attached_children.remove(first_dragged.node.id)
                        # Удаляем ребро от родителя к dragged
                        for e in list(scene._workflow.edges):
                            if e.source_id == dragged_parent_id and e.target_id == first_dragged.node.id:
                                scene._workflow.remove_edge(e.id)
                                if e.id in scene._edge_items:
                                    scene.removeItem(scene._edge_items.pop(e.id))
                        first_dragged.node.attached_to = None
                    
                    # Выполняем вставку
                    if insert_pos == 'before':
                        # Вставляем ПЕРЕД target_node
                        parent_id = getattr(target_node.node, 'attached_to', None)
                        
                        if parent_id:
                            parent_item = scene.get_node_item(parent_id)
                            # Отвязываем target_node от родителя
                            if target_node.node.id in parent_item.node.attached_children:
                                parent_item.node.attached_children.remove(target_node.node.id)
                            target_node.node.attached_to = None
                            
                            # Удаляем ребро parent → target_node
                            for e in list(scene._workflow.edges):
                                if e.source_id == parent_id and e.target_id == target_node.node.id:
                                    scene._workflow.remove_edge(e.id)
                                    if e.id in scene._edge_items:
                                        scene.removeItem(scene._edge_items.pop(e.id))
                            
                            # parent → first_dragged (начало вставляемого блока)
                            parent_item.node.attached_children.append(first_dragged.node.id)
                            first_dragged.node.attached_to = parent_id
                            # Создаём ребро
                            new_edge = AgentEdge(
                                source_id=parent_id,
                                target_id=first_dragged.node.id,
                                condition=EdgeCondition.ALWAYS,
                                label=""
                            )
                            scene._workflow.add_edge(new_edge)
                        # else: target_node был корнем — теперь first_dragged станет корнем
                        
                        # last_dragged → target_node (конец блока к target_node)
                        last_dragged.node.attached_children.append(target_node.node.id)
                        target_node.node.attached_to = last_dragged.node.id
                        # Создаём ребро
                        new_edge = AgentEdge(
                            source_id=last_dragged.node.id,
                            target_id=target_node.node.id,
                            condition=EdgeCondition.ALWAYS,
                            label=""
                        )
                        scene._workflow.add_edge(new_edge)
                        
                    else:  # insert_pos == 'after'
                        # Вставляем ПОСЛЕ target_node
                        target_children = list(getattr(target_node.node, 'attached_children', []))
                        
                        # target_node → first_dragged
                        target_node.node.attached_children.append(first_dragged.node.id)
                        first_dragged.node.attached_to = target_node.node.id
                        # Создаём ребро
                        new_edge = AgentEdge(
                            source_id=target_node.node.id,
                            target_id=first_dragged.node.id,
                            condition=EdgeCondition.ALWAYS,
                            label=""
                        )
                        scene._workflow.add_edge(new_edge)
                        
                        if target_children:
                            # last_dragged → бывшие дети target_node
                            for child_id in target_children:
                                child = scene.get_node_item(child_id)
                                if child:
                                    # Отвязываем от target_node
                                    if child_id in target_node.node.attached_children:
                                        target_node.node.attached_children.remove(child_id)
                                    child.node.attached_to = None
                                    
                                    # Удаляем старое ребро
                                    for e in list(scene._workflow.edges):
                                        if e.source_id == target_node.node.id and e.target_id == child_id:
                                            scene._workflow.remove_edge(e.id)
                                            if e.id in scene._edge_items:
                                                scene.removeItem(scene._edge_items.pop(e.id))
                                    
                                    # Привязываем к last_dragged
                                    last_dragged.node.attached_children.append(child_id)
                                    child.node.attached_to = last_dragged.node.id
                                    # Создаём новое ребро
                                    new_edge = AgentEdge(
                                        source_id=last_dragged.node.id,
                                        target_id=child_id,
                                        condition=EdgeCondition.ALWAYS,
                                        label=""
                                    )
                                    scene._workflow.add_edge(new_edge)
                    
                    # ═══ КРИТИЧНО: Пересчитываем позиции ВСЕЙ цепочки от верхнего корня ═══
                    # Находим самый верхний корень
                    top_root_id = target_block.node.id
                    while True:
                        root_item = scene.get_node_item(top_root_id)
                        if not root_item:
                            break
                        parent_id = getattr(root_item.node, 'attached_to', None)
                        if not parent_id:
                            break
                        top_root_id = parent_id
                    
                    # Пересчитываем позиции
                    AgentNodeItem._reposition_chain(scene, top_root_id)
                    
                    # Обновляем все визуальные элементы
                    scene.update_edges()
                    scene.invalidate()
                    scene.update()

                    # Принудительно обновляем шапки всех затронутых нод
                    _all_affected = set()
                    def _collect_affected(nid, _vis=None):
                        if _vis is None: _vis = set()
                        if not nid or nid in _vis: return
                        _vis.add(nid)
                        _all_affected.add(nid)
                        it = scene.get_node_item(nid)
                        if it:
                            for cid in getattr(it.node, 'attached_children', []):
                                _collect_affected(cid, _vis)
                    _collect_affected(top_root_id)
                    for _nid in _all_affected:
                        _it = scene.get_node_item(_nid)
                        if _it:
                            _it._update_block_header()
                            if _it._block_header:
                                _it._block_header.update_geometry()

                    # Логируем
                    if hasattr(scene, '_main_window') and scene._main_window:
                        scene._main_window._log_msg(
                            f"⛓ " + tr("Блок вставлен: {0} нодов в {1}").format(
                                len(dragged_nodes), target_node.node.name
                            )
                        )
                        scene._main_window._mark_modified_from_props()
                    
                    # Создаём undo
                    self._create_block_insert_undo(scene, dragged_nodes, target_node, insert_pos)
                    
                    event.accept()
                    return
                    
                except Exception as exc:
                    import traceback
                    print(f"=== BLOCK INSERT ERROR ===\n{traceback.format_exc()}")
                    if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                        self._scene_ref._main_window._log_msg(f"⚠ Ошибка вставки блока: {exc}")
        
        # ═══ ВСТАВКА МЕЖДУ БЛОКАМИ: проверяем, вставляем ли между двумя связанными ═══
        # ИСПРАВЛЕНИЕ: срабатываем ТОЛЬКО если нода была реально перемещена (не просто клик)
        _node_was_moved = (
            hasattr(self, '_drag_start_pos') and 
            self._drag_start_pos is not None and 
            self._drag_start_pos != self.pos()
        )
        if (event.button() == Qt.MouseButton.LeftButton and 
            not self._connecting and 
            not getattr(self.node, 'attached_to', None) and  # Этот блок ещё не прикреплён
            self._scene_ref and
            _node_was_moved):   # ← только если нода реально двигалась
            
            # ═══ ИСПРАВЛЕНИЕ: Улучшенное определение соседей с учётом attached-цепочек ═══
            my_rect = self.sceneBoundingRect()
            my_center_x = my_rect.center().x()
            my_center_y = my_rect.center().y()

            upper_neighbor = None
            lower_neighbor = None
            upper_distance = float('inf')
            lower_distance = float('inf')

            # Сначала ищем в радиусе по Y, потом фильтруем по X
            for item in self.scene().items():
                if not isinstance(item, AgentNodeItem) or item == self:
                    continue
                    
                if item is None or not hasattr(item, 'node') or item.node is None:
                    continue
                
                # Пропускаем ноды которые уже наши дети или родители
                if item.node.id in getattr(self.node, 'attached_children', []):
                    continue
                if getattr(self.node, 'attached_to', None) == item.node.id:
                    continue
                
                item_rect = item.sceneBoundingRect()
                item_center_x = item_rect.center().x()
                item_center_y = item_rect.center().y()
                
                # Проверяем выравнивание по X (более мягкое)
                x_aligned = abs(my_center_x - item_center_x) < 100
                
                if not x_aligned:
                    continue
                
                # Вычисляем расстояние по Y
                vertical_distance = item_center_y - my_center_y
                
                # Сверху (item выше нас)
                if vertical_distance < -20:  # Точно выше
                    distance = abs(vertical_distance)
                    if distance < upper_distance and distance < 200:  # Макс расстояние 200px
                        upper_distance = distance
                        upper_neighbor = item
                
                # Снизу (item ниже нас)
                elif vertical_distance > 20:  # Точно ниже
                    distance = vertical_distance
                    if distance < lower_distance and distance < 200:
                        lower_distance = distance
                        lower_neighbor = item

            # Если не нашли по центру, ищем по границам как fallback
            if not upper_neighbor or not lower_neighbor:
                my_top = my_rect.top()
                my_bottom = my_rect.bottom()
                
                for item in self.scene().items():
                    if not isinstance(item, AgentNodeItem) or item == self:
                        continue
                        
                    if item is None or not hasattr(item, 'node') or item.node is None:
                        continue
                    
                    # Пропускаем связанные
                    if item.node.id in getattr(self.node, 'attached_children', []):
                        continue
                    if getattr(self.node, 'attached_to', None) == item.node.id:
                        continue
                    
                    item_rect = item.sceneBoundingRect()
                    item_center_x = item_rect.center().x()
                    item_bottom = item_rect.bottom()
                    item_top = item_rect.top()
                    
                    x_aligned = abs(my_center_x - item_center_x) < 80
                    
                    # Сверху по границе
                    if x_aligned and not upper_neighbor:
                        gap = my_top - item_bottom
                        if 0 < gap < 80:
                            upper_neighbor = item
                    
                    # Снизу по границе
                    if x_aligned and not lower_neighbor:
                        gap = item_top - my_bottom
                        if 0 < gap < 80:
                            lower_neighbor = item
            
            upper_valid = upper_neighbor is not None and hasattr(upper_neighbor, 'node') and upper_neighbor.node is not None
            lower_valid = lower_neighbor is not None and hasattr(lower_neighbor, 'node') and lower_neighbor.node is not None
            
            # ═══ ИСПРАВЛЕНИЕ: Умная вставка с учётом близости к целевому блоку ═══
            if upper_valid and lower_valid:
                try:
                    scene = self._scene_ref
                    
                    # ═══ Защита от цикла: self не должен быть предком upper или lower ═══
                    def _is_ancestor(node_id, potential_ancestor_id, _visited=None):
                        """Проверяет, не является ли potential_ancestor_id предком node_id."""
                        if _visited is None:
                            _visited = set()
                        if node_id in _visited:
                            return False
                        _visited.add(node_id)
                        item = scene.get_node_item(node_id)
                        if not item:
                            return False
                        for child_id in getattr(item.node, 'attached_children', []):
                            if child_id == potential_ancestor_id:
                                return True
                            if _is_ancestor(child_id, potential_ancestor_id, _visited):
                                return True
                        return False
                    
                    if (_is_ancestor(self.node.id, upper_neighbor.node.id) or
                        _is_ancestor(self.node.id, lower_neighbor.node.id) or
                        self.node.id == upper_neighbor.node.id or
                        self.node.id == lower_neighbor.node.id):
                        # Цикл — не вставляем
                        pass
                    else:
                        # 1) Отвязываем lower от upper (если они связаны)
                        if lower_neighbor.node.attached_to == upper_neighbor.node.id:
                            if lower_neighbor.node.id in upper_neighbor.node.attached_children:
                                upper_neighbor.node.attached_children.remove(lower_neighbor.node.id)
                            lower_neighbor.node.attached_to = None
                            # Удаляем ребро upper → lower
                            for e in list(scene._workflow.edges):
                                if e.source_id == upper_neighbor.node.id and e.target_id == lower_neighbor.node.id:
                                    scene._workflow.remove_edge(e.id)
                                    if e.id in scene._edge_items:
                                        scene.removeItem(scene._edge_items.pop(e.id))
                        
                        # 2) Если self уже прикреплён где-то — отвязываем
                        if self.node.attached_to:
                            scene.detach_node(self.node.id)
                        
                        # 3) Прикрепляем self к upper через безопасный attach_node
                        scene.attach_node(self.node.id, upper_neighbor.node.id)
                        
                        # 4) Прикрепляем lower к ПОСЛЕДНЕЙ ноде вставляемого блока
                        _last_of_dragged = self._get_chain_last_node()
                        scene.attach_node(lower_neighbor.node.id, _last_of_dragged.node.id)
                        
                        # 5) ═══ КРИТИЧНО: Пересчитать позиции ВСЕЙ цепочки сверху вниз ═══
                        # Находим верхний корень цепочки
                        top_id = upper_neighbor.node.id
                        _visited_top = set()
                        while True:
                            top_item = scene.get_node_item(top_id)
                            if not top_item or top_id in _visited_top:
                                break
                            _visited_top.add(top_id)
                            parent_id = getattr(top_item.node, 'attached_to', None)
                            if not parent_id:
                                break
                            top_id = parent_id
                        
                        # Каскадное перепозиционирование всей цепочки
                        AgentNodeItem._reposition_chain(scene, top_id)
                        
                        # Обновляем рёбра и перерисовку
                        scene.update_edges()
                        
                        if hasattr(scene, '_main_window') and scene._main_window:
                            scene._main_window._log_msg(
                                f"🔗 Вставлен: {upper_neighbor.node.name} → {self.node.name} → {lower_neighbor.node.name}"
                            )
                            scene._main_window._mark_modified_from_props()
                    
                except Exception as exc:
                    import traceback
                    print(f"=== BLOCK INSERT ERROR ===\n{traceback.format_exc()}")
                    if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                        self._scene_ref._main_window._log_msg(f"⚠ Ошибка вставки: {exc}")
                
                event.accept()
                return
                
            # Если только верхний сосед — прикрепляем снизу
            # Если у верхнего уже есть ребёнок — вставляем между ними
            elif upper_valid and not lower_valid:
                try:
                    scene = self._scene_ref
                    if not hasattr(upper_neighbor.node, 'attached_children'):
                        upper_neighbor.node.attached_children = []
                    
                    # Если self уже прикреплён — отвязываем
                    if self.node.attached_to:
                        scene.detach_node(self.node.id)
                    
                    existing_child_id = (upper_neighbor.node.attached_children[0]
                                         if upper_neighbor.node.attached_children else None)
                    
                    if existing_child_id and existing_child_id != self.node.id:
                        existing_child_item = scene.get_node_item(existing_child_id)
                        # Отвязываем existing_child от upper
                        if existing_child_id in upper_neighbor.node.attached_children:
                            upper_neighbor.node.attached_children.remove(existing_child_id)
                        if existing_child_item:
                            existing_child_item.node.attached_to = None
                        # Удаляем ребро upper → existing_child
                        for e in list(scene._workflow.edges):
                            if e.source_id == upper_neighbor.node.id and e.target_id == existing_child_id:
                                scene._workflow.remove_edge(e.id)
                                if e.id in scene._edge_items:
                                    scene.removeItem(scene._edge_items.pop(e.id))
                        # self → upper, existing_child → последняя нода вставляемого блока
                        scene.attach_node(self.node.id, upper_neighbor.node.id)
                        if existing_child_item:
                            _last_of_dragged = self._get_chain_last_node()
                            scene.attach_node(existing_child_id, _last_of_dragged.node.id)
                    else:
                        scene.attach_node(self.node.id, upper_neighbor.node.id)
                    
                    # ═══ Пересчёт позиций цепочки ═══
                    AgentNodeItem._reposition_chain(scene, upper_neighbor.node.id)
                    scene.update_edges()
                except Exception as exc:
                    import traceback
                    print(f"=== UPPER-ONLY INSERT ERROR ===\n{traceback.format_exc()}")
                event.accept()
                return
            
            # Если только нижний сосед — ставим self над ним,
            # сохраняем цепочку нижнего соседа и его связь с родителем
            elif lower_valid and not upper_valid:
                try:
                    scene = self._scene_ref
                    if not hasattr(lower_neighbor.node, 'attached_to'):
                        lower_neighbor.node.attached_to = None
                    
                    # Если self уже прикреплён — отвязываем
                    if self.node.attached_to:
                        scene.detach_node(self.node.id)
                    
                    old_parent_id = lower_neighbor.node.attached_to
                    if old_parent_id:
                        old_parent_item = scene.get_node_item(old_parent_id)
                        # Отвязываем lower от его родителя
                        if old_parent_item and lower_neighbor.node.id in old_parent_item.node.attached_children:
                            old_parent_item.node.attached_children.remove(lower_neighbor.node.id)
                        for e in list(scene._workflow.edges):
                            if e.source_id == old_parent_id and e.target_id == lower_neighbor.node.id:
                                scene._workflow.remove_edge(e.id)
                                if e.id in scene._edge_items:
                                    scene.removeItem(scene._edge_items.pop(e.id))
                        lower_neighbor.node.attached_to = None
                        # self встаёт на место lower: old_parent → self
                        scene.attach_node(self.node.id, old_parent_id)
                    # lower → последняя нода вставляемого блока
                    _last_of_dragged = self._get_chain_last_node()
                    scene.attach_node(lower_neighbor.node.id, _last_of_dragged.node.id)
                    
                    # ═══ Пересчёт позиций цепочки ═══
                    _top = self.node.attached_to or self.node.id
                    AgentNodeItem._reposition_chain(scene, _top)
                    scene.update_edges()
                except Exception as exc:
                    import traceback
                    print(f"=== LOWER-ONLY INSERT ERROR ===\n{traceback.format_exc()}")
                event.accept()
                return
        
        # ═══ ПРИКРЕПЛЕНИЕ: Shift+Drop или авто при близости (резервный вариант) ═══
        if event.button() == Qt.MouseButton.LeftButton and not self._connecting and _node_was_moved:
            items = self.scene().items(event.scenePos())
            target = None
            for it in items:
                if isinstance(it, AgentNodeItem) and it != self:
                    target = it
                    break
            
            if target and self._scene_ref:
                # Ручное прикрепление через Shift (работает всегда)
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    if self.node.attached_to and self.node.attached_to != target.node.id:
                        self._scene_ref.detach_node(self.node.id)
                    if not self.node.attached_to:
                        self._scene_ref.attach_node(self.node.id, target.node.id)
                    event.accept()
                    return
                
                # ═══ АВТОПРИКРЕПЛЕНИЕ: только если self СВЕРХУ от target ═══
                # (т.е. перетаскиваем блок и "бросаем" его под другим блоком)
                else:
                    my_rect = self.sceneBoundingRect()
                    target_rect = target.sceneBoundingRect()
                    
                    # Проверяем выравнивание по центру X
                    x_aligned = abs(my_rect.center().x() - target_rect.center().x()) < 60
                    
                    # self ниже target: зазор 0-40px ИЛИ перекрытие не более чем на 30px
                    gap = my_rect.top() - target_rect.bottom()
                    y_below = -30 < gap < 40  # self под target (включая небольшое перекрытие)
                    
                    # self не должен быть ВЫШЕ target (чтобы не прикреплять в обратную сторону)
                    self_is_above = my_rect.bottom() < target_rect.top() + 10
                    
                    # ═══ Проверяем, не пытаемся ли вытащить первый нод из блока ═══
                    is_root_with_children = (
                        getattr(self.node, 'attached_children', []) and 
                        not getattr(self.node, 'attached_to', None)
                    )
                    
                    if is_root_with_children and y_below:
                        pass  # Пользователь хочет вытащить корень — не прикрепляем
                    elif x_aligned and y_below and not self_is_above:
                        # self снизу, target сверху → self прикрепляется к target
                        if self.node.attached_to:
                            self._scene_ref.detach_node(self.node.id)
                        self._scene_ref.attach_node(self.node.id, target.node.id)
                        event.accept()
                        return

        if self._connecting:
            scene = self.scene()
            items = scene.items(event.scenePos())
            target_item = None
            for item in items:
                if isinstance(item, AgentNodeItem) and item != self:
                    target_item = item
                    break

            if target_item and self._scene_ref:
                if self._drag_start_port == 'error':
                    condition = EdgeCondition.ON_FAILURE
                    label = "⚡ error"
                elif isinstance(self._drag_start_port, str) and self._drag_start_port.startswith('switch_case_'):
                    condition = EdgeCondition.ON_CONDITION
                    try:
                        i = int(self._drag_start_port.rsplit('_', 1)[-1])
                        cases = self._get_switch_cases()
                        case_val = cases[i] if i < len(cases) else f"case_{i}"
                        label = f"__sw_{i}__:{case_val[:20]}"
                    except Exception:
                        label = "__sw_0__:case_0"
                else:
                    condition = EdgeCondition.ALWAYS
                    label = ""
                # ═══ УНИКАЛЬНЫЙ ID ДЛЯ КАЖДОЙ СВЯЗИ SWITCH ═══
                # Для Switch case-портов добавляем индекс к ID чтобы разные case могли идти на одну цель
                edge_id_suffix = ""
                if isinstance(self._drag_start_port, str) and self._drag_start_port.startswith('switch_case_'):
                    edge_id_suffix = f"_{self._drag_start_port}"
                
                edge = AgentEdge(
                    source_id=self.node.id,
                    target_id=target_item.node.id,
                    condition=condition,
                    label=label,
                )
                # Переопределяем ID для уникальности (только для Switch case-портов)
                if edge_id_suffix:
                    edge.id = f"{edge.source_id}_{edge.target_id}{edge_id_suffix}"
                
                self._scene_ref.request_edge_creation(edge, self.node, target_item.node, 
                                                      source_port=self._drag_start_port)

            if self._temp_line:
                self.scene().removeItem(self._temp_line)
                self._temp_line = None
            self._connecting = False
            self._drag_start_port = None
            # Сбрасываем позицию начала драга, чтобы не создать undo для "перемещения" после создания связи
            self._drag_start_pos = None
            
            # Сбрасываем устаревший origin мыши и флаг открепления
            self._drag_start_mouse_pos = None
            self._detach_triggered = False
            
            super().mouseReleaseEvent(event)
            return
        
        # Проверяем перемещение для undo (только если это было не создание связи)
        if hasattr(self, '_drag_start_pos') and self._drag_start_pos is not None and self._drag_start_pos != self.pos():
            if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                mw = self._scene_ref._main_window
                old_pos = self._drag_start_pos
                new_pos = self.pos()
                node = self.node
                
                def _set_pos(n, x, y):
                    n.x = x
                    n.y = y
                
                # Сохраняем позиции как локальные переменные (критично для замыкания)
                old_x, old_y = old_pos.x(), old_pos.y()
                new_x, new_y = new_pos.x(), new_pos.y()
                
                # Factory functions для создания замыканий с правильным захватом значений
                def make_undo_func(item, x, y, scene):
                    def _undo():
                        item.setPos(QPointF(x, y))
                        item.node.x = x
                        item.node.y = y
                        item.update()
                        if scene:
                            scene.update_edges()
                            scene.invalidate()  # Принудительная перерисовка сцены
                            scene.update()
                    return _undo
                
                def make_redo_func(item, x, y, scene):
                    def _redo():
                        item.setPos(QPointF(x, y))
                        item.node.x = x
                        item.node.y = y
                        item.update()
                        if scene:
                            scene.update_edges()
                            scene.invalidate()
                            scene.update()
                    return _redo
                
            mw._history.push(
                make_redo_func(self, new_x, new_y, self._scene_ref),
                make_undo_func(self, old_x, old_y, self._scene_ref),
                tr("Перемещение {0}").format(node.name)
            )
            mw._mark_modified_from_props()
            # Сбрасываем после создания undo
            self._drag_start_pos = None
        
        super().mouseReleaseEvent(event)
        
    def _setup_visuals(self):
        base_color = self.node.custom_color if getattr(self.node, 'custom_color', '') else _AGENT_COLORS.get(self.node.agent_type, "#565f89")
        color = QColor(base_color)
        self.setBrush(QBrush(QColor(get_color("bg2"))))
        self.setPen(QPen(color, 2))
        self.setToolTip(f"{self.node.name}\n{self.node.description}")
    
    def mouseMoveEvent(self, event):
        # Защита: проверяем что сцена существует
        if self.scene() is None:
            super().mouseMoveEvent(event)
            return
        
        # ═══ ПЕРЕТАСКИВАНИЕ БЛОКА ЦЕЛИКОМ ═══
        # ═══ ИСПРАВЛЕНИЕ: защита от телепорта при смене режима drag ═══
        # Если нода внезапно оказалась далеко от курсора - отменяем движение
        if event.buttons() & Qt.MouseButton.LeftButton and not self._connecting:
            cursor_pos = event.scenePos()
            node_center = self.sceneBoundingRect().center()
            distance = (cursor_pos - node_center).manhattanLength()
            
            # Если расстояние больше размера ноды + запас, значит был телепорт
            max_expected_distance = max(self.node.width, self.node.height) + 100
            if distance > max_expected_distance and not getattr(self, '_dragging_block', False):
                # Возвращаем ноду к курсору плавно
                offset = QPointF(self.node.width / 2, self.node.height / 2)
                corrected_pos = cursor_pos - offset
                self.setPos(corrected_pos)
                self.node.x = corrected_pos.x()
                self.node.y = corrected_pos.y()
                self._drag_start_pos = corrected_pos
                if self._scene_ref:
                    self._scene_ref.update_edges()
                event.accept()
                return
        # ═════════════════════════════════════════════════════════════════
        if getattr(self, '_dragging_block', False) and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.scenePos() - self._drag_block_mouse_start
            
            # Перемещаем все ноды блока с сохранением их относительных позиций
            for node_info in self._dragged_block_nodes:
                item = node_info['item']
                new_pos = node_info['start_pos'] + delta
                
                # Snap to grid
                grid = 20
                x = round(new_pos.x() / grid) * grid
                y = round(new_pos.y() / grid) * grid
                snapped = QPointF(x, y)
                
                item.setPos(snapped)
                item.node.x = snapped.x()
                item.node.y = snapped.y()
            
            # Обновляем рёбра
            self._scene_ref.update_edges()
            self._scene_ref.invalidate()
            event.accept()
            return
        
        # ═══ ИСПРАВЛЕНИЕ: При наведении на другой блок поднимаем Z-ордер для визуальной обратной связи ═══
        if not getattr(self, '_connecting', False) and event.buttons() & Qt.MouseButton.LeftButton:
            items_under = self.scene().items(event.scenePos())
            for it in items_under:
                if isinstance(it, AgentNodeItem) and it != self and not self.node.attached_to:
                    # Навелись на потенциального родителя — поднимаем себя выше него
                    if it.zValue() >= self.zValue():
                        self.setZValue(it.zValue() + 0.1)
                        if self._block_header:
                            self._block_header.setZValue(it.zValue() + 1000)
                    break
        
        # ═══ ИСПРАВЛЕНИЕ: Визуальная индикация при наведении на блок для встраивания ═══
        if not getattr(self, '_connecting', False) and event.buttons() & Qt.MouseButton.LeftButton and not self.node.attached_to:
            self._update_drag_preview(event.scenePos())
            
            # ═══ НОВОЕ: Проверяем вставку блока в блок ═══
            # Определяем, перетаскиваем ли мы целый блок (мы корень с детьми)
            is_dragging_block = bool(getattr(self.node, 'attached_children', [])) and not getattr(self.node, 'attached_to', None)
            
            if is_dragging_block:
                target_block = self._get_block_at_pos(event.scenePos())
                
                # Не вставляем в самого себя или своих потомков
                if target_block and target_block.node.id != self.node.id:
                    if not self._is_in_block_chain(target_block):
                        # Определяем позицию вставки
                        pos, target_node = self._find_insert_position_in_block(target_block, event.scenePos())
                        
                        # Визуальная индикация
                        self._drag_block_insert_target = target_block
                        self._drag_block_insert_pos = pos
                        self._drag_block_insert_node = target_node
                        
                        # Подсвечиваем целевой блок и позицию вставки
                        target_block._hovered = True
                        target_block.update()
                        
                        # Меняем курсор
                        from PyQt6.QtGui import QCursor
                        self.setCursor(QCursor(Qt.CursorShape.DragCopyCursor))
                        self.setOpacity(0.6)
                    else:
                        # Цикл — отменяем
                        self._drag_block_insert_target = None
                        self.setOpacity(0.8)
        
        # ═══ АВТООТКРЕПЛЕНИЕ: только при реальном перетаскивании (движение > 10px) ═══
        if (not getattr(self, '_connecting', False) and 
            event.buttons() & Qt.MouseButton.LeftButton and 
            self.node.attached_to and self._scene_ref and
            not getattr(self, '_detach_triggered', False)):
            
            start_mouse = getattr(self, '_drag_start_mouse_pos', None)
            # Защита: авто-открепление только если этот элемент был именно кликнут
            # (start_mouse не None значит mousePressEvent именно этого элемента сработал)
            if start_mouse and self.isUnderMouse():
                delta = (event.scenePos() - start_mouse).manhattanLength()
                if delta > 20:
                    # Защита: проверяем что мы всё ещё в сцене перед отсоединением
                    if self.scene() is not None:
                        self._scene_ref.detach_node(self.node.id)
                        self._detach_triggered = True  # Чтобы не откреплять повторно
        
        # 1. Проверяем, тянем ли мы сейчас НОВУЮ стрелочку
        if hasattr(self, '_connecting') and self._connecting and hasattr(self, '_temp_line') and self._temp_line:
            self._update_temp_line(event.scenePos())
            
            # 2. Автоскролл (скорость снижена до минимума)
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                from PyQt6.QtGui import QCursor
                from PyQt6.QtCore import QTimer
                
                view_pos = view.mapFromGlobal(QCursor.pos())
                view_rect = view.rect()
                
                margin = 40
                step = 1  # ═══ МИНИМАЛЬНАЯ СКОРОСТЬ ═══
                dx, dy = 0, 0
                
                if view_pos.x() < margin: dx = -step
                elif view_pos.x() > view_rect.width() - margin: dx = step
                if view_pos.y() < margin: dy = -step
                elif view_pos.y() > view_rect.height() - margin: dy = step
                
                if dx != 0 or dy != 0:
                    h_bar = view.horizontalScrollBar()
                    v_bar = view.verticalScrollBar()
                    QTimer.singleShot(0, lambda: h_bar.setValue(h_bar.value() + dx))
                    QTimer.singleShot(0, lambda: v_bar.setValue(v_bar.value() + dy))
            return
            
        # 3. Базовый метод
        super().mouseMoveEvent(event)
    
    def paint(self, painter: QPainter, option, widget=None):
        w, h = self.rect().width(), self.rect().height()
        # Кастомный цвет имеет приоритет
        base_color = self.node.custom_color if getattr(self.node, 'custom_color', '') else _AGENT_COLORS.get(self.node.agent_type, "#565f89")
        color = QColor(base_color)
        bg = QColor(get_color("bg2"))
        bg_sel = QColor(get_color("bg3"))
        tx = QColor(get_color("tx0"))
        tx2 = QColor(get_color("tx2"))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # ═══ ИСПРАВЛЕНИЕ: Подсветка при drag-over другого сниппета ═══
        if self._hovered and any(
            hasattr(item, '_drag_target_block') and item._drag_target_block == self 
            for item in (self.scene().items() if self.scene() else [])
            if isinstance(item, AgentNodeItem)
        ):
            # Рисуем "призрачную" рамку для индикации возможного встраивания
            highlight_pen = QPen(QColor(get_color("ac")), 3, Qt.PenStyle.DashLine)
            painter.setPen(highlight_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(-2, -2, 2, 2), 12, 12)
        
        # ═══ ЗАМЕТКА — особая отрисовка ═══
        if self.node.agent_type == AgentType.NOTE:
            self._paint_note(painter, w, h, color, tx, tx2)
            return

        # ═══ СТАРТ — круглая нода ═══
        if self.node.agent_type == AgentType.PROJECT_START:
            self._paint_start(painter, w, h, color, tx, tx2)
            return

        # Лёгкая тень — ВНУТРИ boundingRect чтобы не было артефактов
        shadow_rect = QRectF(3, 4, w - 1, h - 1)
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(shadow_rect, 10, 10)
        shadow_c = QColor(0, 0, 0, 30)
        painter.fillPath(shadow_path, QBrush(shadow_c))

        # Background (стандартная нода)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 10, 10)
        painter.fillPath(path, QBrush(bg_sel if self.isSelected() else bg))

        # Top accent bar
        bar_path = QPainterPath()
        bar_path.addRoundedRect(QRectF(0, 0, w, 28), 10, 10)
        bar_path.addRect(QRectF(0, 14, w, 14))  # square off bottom of bar
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, color)
        c2 = QColor(color)
        c2.setAlpha(160)
        grad.setColorAt(1, c2)
        painter.fillPath(bar_path, QBrush(grad))

        # Border
        pen_w = 2.5 if self.isSelected() else 1.5
        pen_c = color if self.isSelected() else QColor(get_color("bd"))
        if self._hovered:
            pen_c = color
        painter.setPen(QPen(pen_c, pen_w))
        painter.drawRoundedRect(self.rect(), 10, 10)

        # Icon + title
        icon = _AGENT_ICONS.get(self.node.agent_type, "🤖")
        painter.setFont(QFont("Segoe UI Emoji", 14))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawText(QRectF(8, 2, 26, 26), Qt.AlignmentFlag.AlignCenter, icon)

        # Используем цвет текста темы для заголовка (адаптирован под светлую/темную тему)
        painter.setPen(QPen(tx, 1))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(34, 4, w - 44, 22), Qt.AlignmentFlag.AlignVCenter,
                         self.node.name[:25])

        # Agent type label — используем tx (основной текст темы) для лучшей читаемости
        painter.setPen(QPen(tx, 1))
        painter.setFont(QFont("Segoe UI", 8))
        type_label = self.node.agent_type.value.replace("_", " ").title()
        painter.drawText(QRectF(10, 32, w - 20, 16), Qt.AlignmentFlag.AlignLeft, type_label)
        
        # ═══ ОТОБРАЖЕНИЕ ПОЛЕЙ СНИППЕТА НА БЛОКЕ ═══
        if self.node.agent_type in SNIPPET_TYPES:
            cfg = getattr(self.node, 'snippet_config', {}) or {}
            # Собираем заполненные поля для отображения (исключаем служебные)
            display_fields = []
            for k, v in cfg.items():
                if v and not k.startswith('_') and k not in ['inject_vars', 'global_scope', 'create_if_missing', 'no_return']:
                    display_fields.append(f"{k}: {str(v)[:22]}")
                    if len(display_fields) >= 2:  # Максимум 2 строки чтобы не перегружать
                        break
            
            if display_fields:
                y_offset = 48
                for field_text in display_fields:
                    painter.setPen(QPen(QColor(get_color("tx2")), 1))
                    painter.setFont(QFont("Segoe UI", 8))
                    painter.drawText(QRectF(10, y_offset, w - 20, 14), 
                                   Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine, 
                                   field_text)
                    y_offset += 14

        # Skills count
        n_skills = len(self.node.skill_ids)
        if n_skills:
            painter.setPen(QPen(QColor(get_color("ok")), 1))
            painter.drawText(QRectF(10, 48, w - 20, 16), Qt.AlignmentFlag.AlignLeft,
                             f"🔧 {n_skills} скиллов")

        # Model
        if self.node.model_id:
            painter.setPen(QPen(QColor(get_color("ac")), 1))
            painter.drawText(QRectF(10, 64, w - 20, 16), Qt.AlignmentFlag.AlignLeft,
                             f"🧠 {self.node.model_id[:20]}")
        
        # ═══ ВИЗУАЛЬНАЯ ОБЁРТКА БЛОКА — теперь отдельный элемент ═══
        # Обновляем шапку если нужно
        self._update_block_header()

        # Attached children indicator (зеленая точка если есть прикрепленные)
        if getattr(self.node, 'attached_children', []):
            painter.setBrush(QBrush(QColor("#9ECE6A")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(w - 8, 8), 4, 4)
            if len(self.node.attached_children) > 0:
                painter.setPen(QPen(QColor(get_color("bg0")), 1))
                painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                painter.drawText(QRectF(w - 12, 4, 8, 8),
                               Qt.AlignmentFlag.AlignCenter,
                               str(len(self.node.attached_children)))

        # Attached to parent indicator (оранжевая точка если прикреплен к родителю)
        if getattr(self.node, 'attached_to', None):
            painter.setBrush(QBrush(QColor("#E0AF68")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(8, 8), 4, 4)
            if len(self.node.attached_children) > 0:
                painter.setPen(QPen(QColor(get_color("bg0")), 1))
                painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                painter.drawText(QRectF(w - 12, 4, 8, 8), 
                               Qt.AlignmentFlag.AlignCenter, 
                               str(len(self.node.attached_children)))
        
        # Attached to parent indicator (оранжевая точка если прикреплен к родителю)
        if getattr(self.node, 'attached_to', None):
            painter.setBrush(QBrush(QColor("#E0AF68")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(8, 8), 4, 4)
        
        # Status indicator
        status_colors = {
            "idle": get_color("tx3") if hasattr(get_color, '__call__') else "#3B4261",
            "running": get_color("warn"),
            "success": get_color("ok"),
            "failed": get_color("err"),
        }
        sc = QColor(status_colors.get(self.node._status, "#3B4261"))
        painter.setBrush(QBrush(sc))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(w - 14, 14), 5, 5)

        # Connection ports (in/out)
        port_color = QColor(color)
        port_color.setAlpha(200)
        painter.setBrush(QBrush(port_color))
        painter.setPen(QPen(QColor(get_color("bg0")), 1))
        
        # ═══ ВХОДНОЙ ПОРТ — для всех типов кроме заметок ═══
        if self.node.agent_type != AgentType.NOTE:
            # Левый верхний входной порт
            painter.drawEllipse(QPointF(0, 16), self.PORT_RADIUS, self.PORT_RADIUS)
        
        # ═══ ВЫХОДНЫЕ ПОРТЫ — только для не-заметок ═══
        if self.node.agent_type != AgentType.NOTE:
            # Правый верхний (дополнительный вход при соединении справа)
            painter.drawEllipse(QPointF(w, 16), self.PORT_RADIUS, self.PORT_RADIUS)
            
            if self.node.agent_type == AgentType.SWITCH:
                # Switch: по одному выходному порту на каждый case
                cases = self._get_switch_cases()
                n = max(len(cases), 1)
                for i in range(n):
                    cp = self._switch_case_port_local(i, n)
                    painter.drawEllipse(cp, self.PORT_RADIUS, self.PORT_RADIUS)
                    # Миникрышка с номером/значением case
                    case_text = cases[i][:10] if i < len(cases) else f"#{i}"
                    painter.setPen(QPen(QColor(get_color("tx2")), 1))
                    painter.setFont(QFont("Segoe UI", 7))
                    painter.drawText(QPointF(w - 55, cp.y() + 4), case_text)
                    painter.setBrush(QBrush(port_color))
                    painter.setPen(QPen(QColor(get_color("bg0")), 1))
            else:
                # Обычный выходной порт (правый центр)
                painter.drawEllipse(QPointF(w, h / 2), self.PORT_RADIUS, self.PORT_RADIUS)

            # Error port — ON_FAILURE (правый нижний), красный + пунктир
            err_color = QColor(get_color("err"))
            err_color.setAlpha(220)
            painter.setBrush(QBrush(err_color))
            err_pen = QPen(QColor(get_color("bg0")), 1, Qt.PenStyle.DashLine)
            painter.setPen(err_pen)
            painter.drawEllipse(self.error_port_local(), self.PORT_RADIUS, self.PORT_RADIUS)
            # Small ⚡ label
            painter.setPen(QPen(err_color, 1))
            painter.setFont(QFont("Segoe UI Emoji", 7))
            painter.drawText(QPointF(w - 18, h - 2), "⚡")
        
        # ═══ Индикация цели вставки блока ═══
        if getattr(self, '_drag_block_insert_target', None) == self:
            # Рисуем индикатор позиции вставки
            insert_pos = getattr(self._drag_block_insert_target, '_drag_block_insert_pos', None)
            target_node = getattr(self._drag_block_insert_target, '_drag_block_insert_node', None)
            
            if target_node and target_node.scene():
                # Находим позицию target_node
                target_rect = target_node.sceneBoundingRect()
                
                # Рисуем линию-индикатор
                indicator_y = target_rect.top() if insert_pos == 'before' else target_rect.bottom()
                
                pen = QPen(QColor(get_color("ac")), 3, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(
                    int(target_rect.left() - 10), int(indicator_y),
                    int(target_rect.right() + 10), int(indicator_y)
                )
                
                # Стрелка
                arrow_size = 8
                painter.setBrush(QBrush(QColor(get_color("ac"))))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon(QPolygonF([
                    QPointF(target_rect.center().x(), indicator_y - arrow_size),
                    QPointF(target_rect.center().x() - arrow_size, indicator_y - arrow_size * 2),
                    QPointF(target_rect.center().x() + arrow_size, indicator_y - arrow_size * 2),
                ]))
        
        # ═══ Отметка стартовой ноды ═══
        if self._scene_ref and hasattr(self._scene_ref, '_workflow') and self._scene_ref._workflow:
            if getattr(self._scene_ref._workflow, 'entry_node_id', '') == self.node.id:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#9ECE6A")))
                triangle = QPolygonF([
                    QPointF(4, 2),
                    QPointF(16, 9),
                    QPointF(4, 16)
                ])
                painter.drawPolygon(triangle)

        # ═══ Комментарий под нодой ═══
        comment = getattr(self.node, 'comment', '')
        if comment:
            painter.setPen(QPen(QColor("#E0AF68"), 1))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
            comment_rect = QRectF(4, h + 4, w - 8, 30)
            painter.drawText(comment_rect,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             comment[:80])
    def _paint_note(self, painter: QPainter, w, h, color, tx, tx2):
        """Рисование заметки — бумажный стиль, без портов."""
        note_bg = QColor(getattr(self.node, 'note_color', '#E0AF68'))
        note_bg.setAlpha(25)
        note_border = QColor(getattr(self.node, 'note_color', '#E0AF68'))
        note_border.setAlpha(140)

        # Фон — «бумажная» текстура (скруглённый прямоугольник с заливкой)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 6, 6)
        painter.fillPath(path, QBrush(note_bg))

        # Рамка — пунктирная линия
        pen = QPen(note_border, 2.0 if self.isSelected() else 1.5, Qt.PenStyle.DashDotLine)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect(), 6, 6)

        # «Загнутый уголок» сверху-справа
        fold = 16
        fold_path = QPainterPath()
        fold_path.moveTo(w - fold, 0)
        fold_path.lineTo(w, fold)
        fold_path.lineTo(w - fold, fold)
        fold_path.closeSubpath()
        fold_color = QColor(getattr(self.node, 'note_color', '#E0AF68'))
        fold_color.setAlpha(60)
        painter.fillPath(fold_path, QBrush(fold_color))

        # Иконка 📌
        painter.setFont(QFont("Segoe UI Emoji", 14))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawText(QRectF(6, 4, 24, 24), Qt.AlignmentFlag.AlignCenter, "📌")

        # Заголовок — адаптивный цвет
        title_color = QColor(getattr(self.node, 'note_color', '#E0AF68'))
        title_color.setAlpha(255)
        # ═══ ИСПРАВЛЕНИЕ: проверяем контраст с фоном ═══
        def is_light_color(c: QColor) -> bool:
            y = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            return y > 128
        
        # Если фон светлый — делаем заголовок тёмнее для контраста
        bg = QColor(get_color("bg2"))
        if is_light_color(bg) and is_light_color(title_color):
            # На светлом фоне светлый заголовок — делаем тёмнее
            title_color = title_color.darker(150)
        
        painter.setPen(QPen(title_color, 1))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(32, 4, w - 44, 22), Qt.AlignmentFlag.AlignVCenter,
                         self.node.name[:30])

        # Превью содержимого — используем tx из параметра (адаптивный цвет темы)
        content = getattr(self.node, 'note_content', '')
        font_size = getattr(self.node, 'note_font_size', 9)
        if content:
            painter.setPen(QPen(tx, 1))  # tx уже адаптивный из paint()
            painter.setFont(QFont("Segoe UI", font_size))
            
            # Рисуем весь текст с переносом слов в доступной области
            text_rect = QRectF(10, 32, w - 20, h - 48)
            painter.drawText(text_rect, 
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, 
                           content)

        # Метка «Note» внизу — используем tx2 из параметра
        painter.setPen(QPen(tx2, 1))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(10, h - 16, w - 20, 14), Qt.AlignmentFlag.AlignRight, "note")

    def _paint_start(self, painter: QPainter, w, h, color, tx, tx2):
        """Рисование стартового узла — круг с градиентом."""
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 2

        # Градиентный фон
        grad = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        c1 = QColor(color)
        c1.setAlpha(60)
        c2 = QColor(color)
        c2.setAlpha(25)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        painter.setBrush(QBrush(grad))

        # Граница
        pen_w = 3.0 if self.isSelected() else 2.0
        pen_c = QColor(color) if self.isSelected() else QColor(color)
        pen_c.setAlpha(255 if self.isSelected() else 200)
        painter.setPen(QPen(pen_c, pen_w))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # Внутренний круг (акцент)
        inner_grad = QLinearGradient(cx - radius * 0.6, cy - radius * 0.6,
                                      cx + radius * 0.6, cy + radius * 0.6)
        inner_c = QColor(color)
        inner_c.setAlpha(120)
        inner_grad.setColorAt(0, inner_c)
        inner_c2 = QColor(color)
        inner_c2.setAlpha(40)
        inner_grad.setColorAt(1, inner_c2)
        painter.setBrush(QBrush(inner_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius * 0.7, radius * 0.7)

        # Треугольник «Play» в центре
        tri_size = radius * 0.35
        play_path = QPainterPath()
        play_path.moveTo(cx - tri_size * 0.4, cy - tri_size)
        play_path.lineTo(cx + tri_size * 0.8, cy)
        play_path.lineTo(cx - tri_size * 0.4, cy + tri_size)
        play_path.closeSubpath()
        painter.setBrush(QBrush(tx))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(play_path, QBrush(tx))

        # Название — под кругом
        painter.setPen(QPen(tx, 1))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(QRectF(0, h - 20, w, 18),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         self.node.name[:20])

        # Режим (run_mode) — маленький текст
        cfg = getattr(self.node, 'snippet_config', {}) or {}
        mode = cfg.get('run_mode', 'plain')
        mode_labels = {'plain': '▶ Cold Start', 'ai': '🤖 AI Start',
                       'script': '⚡ Script', 'hybrid': '🔁 Hybrid'}
        mode_text = mode_labels.get(mode, mode)
        painter.setPen(QPen(QColor(color), 1))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(0, 2, w, 14),
                         Qt.AlignmentFlag.AlignHCenter, mode_text)

        # Статус-индикатор (точка)
        status_colors = {"idle": "#3B4261", "running": get_color("warn"),
                         "success": get_color("ok"), "failed": get_color("err")}
        sc = QColor(status_colors.get(self.node._status, "#3B4261"))
        painter.setBrush(QBrush(sc))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(w - 10, 10), 5, 5)

        # Порты: входной — слева по центру, выходной — справа по центру
        port_color = QColor(color)
        port_color.setAlpha(200)
        painter.setBrush(QBrush(port_color))
        painter.setPen(QPen(QColor(get_color("bg0")), 1))
        # Входной порт (левый)
        painter.drawEllipse(QPointF(0, cy), self.PORT_RADIUS, self.PORT_RADIUS)
        # Выходной порт (правый)
        painter.drawEllipse(QPointF(w, cy), self.PORT_RADIUS, self.PORT_RADIUS)
        # Error-порт (нижний правый)
        err_color = QColor(get_color("err"))
        err_color.setAlpha(220)
        painter.setBrush(QBrush(err_color))
        painter.setPen(QPen(QColor(get_color("bg0")), 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(self.error_port_local(), self.PORT_RADIUS, self.PORT_RADIUS)

        # Статус-индикатор (как у обычных нод)
        if self.isSelected():
            sel_pen = QPen(QColor(getattr(self.node, 'note_color', '#E0AF68')), 2.5)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)

        # ЗАМЕТКИ НЕ ИМЕЮТ ПОРТОВ — не рисуем кружки ввода/вывода
        
    def itemChange(self, change, value):
        if self.scene() is None:
            return super().itemChange(change, value)
        
        if self._in_item_change:
            return value
        self._in_item_change = True
        
        try:
            if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
                # Snap to grid
                grid = 20
                new_pos = value
                x = round(new_pos.x() / grid) * grid
                y = round(new_pos.y() / grid) * grid
                snapped = QPointF(x, y)
                # Update model
                self.node.x = snapped.x()
                self.node.y = snapped.y()
                
                # ═══ Движение детей только при НЕактивном перетаскивании блока ═══
                # Если перетаскиваем блок — дети двигаются вместе с родителем через _dragged_block_nodes
                if (getattr(self.node, 'attached_children', []) and self._scene_ref and
                    not getattr(self, '_dragging_block', False)):
                    
                    # Только если это не корень с обёрткой (иначе двигаем через блок)
                    has_parent = bool(getattr(self.node, 'attached_to', None))
                    # Двигаем детей ТОЛЬКО если пользователь реально тащит этот элемент мышью
                    # (drag_start_mouse_pos установлен = mousePressEvent сработал на этом элементе)
                    user_is_dragging = (
                        getattr(self, '_drag_start_mouse_pos', None) is not None and
                        not getattr(self, '_detach_triggered', False)
                    )
                    if has_parent and user_is_dragging:
                        for child_id in self.node.attached_children:
                            child_item = self._scene_ref.get_node_item(child_id)
                            if child_item:
                                # Центрирование детей относительно родителя
                                new_child_pos = QPointF(
                                    snapped.x() + (self.node.width - child_item.node.width) / 2,
                                    snapped.y() + self.node.height + 10
                                )
                                child_item.setPos(new_child_pos)
                                child_item.node.x = new_child_pos.x()
                                child_item.node.y = new_child_pos.y()
                
                # Обновляем позицию шапки
                if self._block_header:
                    self._block_header.update_geometry()
                
                # Update connected edges (throttled)
                if self._scene_ref:
                    # Немедленное обновление самой ноды
                    self.prepareGeometryChange()
                    self.update()
                    if not getattr(self._scene_ref, '_edges_update_pending', False):
                        self._scene_ref._edges_update_pending = True
                        QTimer.singleShot(0, self._deferred_update_edges)
                # Отмечаем изменение для отслеживания сохранения
                if self._scene_ref and hasattr(self._scene_ref, '_main_window'):
                    mw = self._scene_ref._main_window
                    if mw and not mw._is_modified:
                        mw._is_modified = True
                        mw._update_window_title()
                return snapped
            if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
                if self._scene_ref:
                    self._scene_ref.node_selected.emit(self.node if value else None)
            
            result = super().itemChange(change, value)
        finally:
            self._in_item_change = False
        
        return result
    
    def _deferred_update_edges(self):
        """Отложенное обновление рёбер (throttle)."""
        if self._scene_ref:
            self._scene_ref._edges_update_pending = False
            self._scene_ref.update_edges()
            self._scene_ref.update()
    
    @staticmethod
    def _reposition_chain(scene, top_parent_id: str, _visited: set = None):
        """Каскадное перепозиционирование цепочки сверху вниз (без рёбер)."""
        if _visited is None:
            _visited = set()
        if top_parent_id in _visited:
            return
        _visited.add(top_parent_id)
        
        parent_item = scene.get_node_item(top_parent_id)
        if not parent_item:
            return
        
        children = list(getattr(parent_item.node, 'attached_children', []))
        if not children:
            return
        
        y_offset = parent_item.pos().y() + parent_item.node.height + 10
        for child_id in children:
            child_item = scene.get_node_item(child_id)
            if not child_item:
                continue
            
            # Позиционируем дочернюю ноду ровно под родителем
            new_x = parent_item.pos().x() + (parent_item.node.width - child_item.node.width) / 2
            new_y = y_offset
            
            child_item.setPos(QPointF(new_x, new_y))
            child_item.node.x = new_x
            child_item.node.y = new_y
            
            y_offset += child_item.node.height + 10
            
            # Рекурсивно позиционируем детей этого ребёнка
            AgentNodeItem._reposition_chain(scene, child_id, _visited)
    
    def _find_chain_root_id(self, node_id: str) -> str:
        """Найти ID корневого элемента цепочки."""
        if not self._scene_ref:
            return node_id
            
        current_id = node_id
        visited = set()
        
        while current_id and current_id not in visited:
            visited.add(current_id)
            item = self._scene_ref.get_node_item(current_id)
            if not item:
                break
            parent_id = getattr(item.node, 'attached_to', None)
            if not parent_id:
                return current_id
            current_id = parent_id
        
        return node_id
    
    def _create_block_insert_undo(self, scene, dragged_nodes, target_node, insert_pos):
        """Создать undo для вставки блока."""
        if not hasattr(scene, '_main_window') or not scene._main_window:
            return
            
        mw = scene._main_window
        if not hasattr(mw, '_history'):
            return
        
        # Сохраняем состояние ДО вставки
        old_parents = {}
        old_children = {}
        old_positions = {}
        
        all_involved = list(dragged_nodes) + [target_node]
        if insert_pos == 'before':
            # Также включаем родителя target_node
            parent_id = getattr(target_node.node, 'attached_to', None)
            if parent_id:
                parent_item = scene.get_node_item(parent_id)
                if parent_item:
                    all_involved.append(parent_item)
        
        for node in all_involved:
            old_parents[node.node.id] = getattr(node.node, 'attached_to', None)
            old_children[node.node.id] = list(getattr(node.node, 'attached_children', []))
            old_positions[node.node.id] = QPointF(node.pos().x(), node.pos().y())
        
        dragged_ids = [n.node.id for n in dragged_nodes]
        target_id = target_node.node.id
        
        scene_ref = scene
        
        def make_undo():
            def _undo():
                try:
                    # Восстанавливаем связи
                    for node_id, parent_id in old_parents.items():
                        item = scene_ref.get_node_item(node_id)
                        if not item:
                            continue
                        
                        # Отвязываем от текущего
                        current_parent = getattr(item.node, 'attached_to', None)
                        if current_parent:
                            current_parent_item = scene_ref.get_node_item(current_parent)
                            if current_parent_item and node_id in current_parent_item.node.attached_children:
                                current_parent_item.node.attached_children.remove(node_id)
                        
                        # Восстанавливаем родителя
                        item.node.attached_to = parent_id
                        if parent_id:
                            parent_item = scene_ref.get_node_item(parent_id)
                            if parent_item and node_id not in parent_item.node.attached_children:
                                parent_item.node.attached_children.append(node_id)
                    
                    # Восстанавливаем детей
                    for node_id, children_ids in old_children.items():
                        item = scene_ref.get_node_item(node_id)
                        if not item:
                            continue
                        item.node.attached_children = list(children_ids)
                    
                    # Восстанавливаем позиции
                    for node_id, pos in old_positions.items():
                        item = scene_ref.get_node_item(node_id)
                        if item:
                            item.setPos(pos)
                            item.node.x = pos.x()
                            item.node.y = pos.y()
                    
                    # Пересчитываем позиции
                    root_id = self._find_chain_root_id(target_id)
                    AgentNodeItem._reposition_chain(scene_ref, root_id)
                    
                    scene_ref.update_edges()
                    scene_ref.invalidate()
                    scene_ref.update()
                except Exception as e:
                    print(f"[Block insert undo error] {e}")
            return _undo
        
        def make_redo():
            # Для redo просто повторяем операцию (упрощённо — просто логируем)
            def _redo():
                mw._log_msg(tr("Повтор вставки блока (вручную)"))
            return _redo
        
        mw._history.push(make_redo(), make_undo(), 
            tr("Вставка блока ({0} нодов)").format(len(dragged_nodes)))
    
    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
    
    def _get_chain_last_node(self) -> 'AgentNodeItem':
        """Получить последнюю ноду в линейной цепочке attached_children начиная с self."""
        current = self
        visited = set()
        while True:
            if current.node.id in visited:
                break
            visited.add(current.node.id)
            children = getattr(current.node, 'attached_children', [])
            if not children:
                break
            next_id = children[0]
            if not self._scene_ref:
                break
            next_item = self._scene_ref.get_node_item(next_id)
            if not next_item:
                break
            current = next_item
        return current
    
    def mousePressEvent(self, event: QMouseEvent):
        """Обработка клика по портам для создания связей."""
        # Защита: проверяем что сцена существует
        if self.scene() is None:
            super().mousePressEvent(event)
            return
        
        local_pos = event.pos()
        
        # ═══ ПРОВЕРКА КЛИКА ПО ШАПКЕ БЛОКА ═══
        # Проверяем, являемся ли мы корнем цепочки с детьми
        has_children = bool(getattr(self.node, 'attached_children', []))
        has_parent = bool(getattr(self.node, 'attached_to', None))
        
        if has_children and not has_parent and self._scene_ref:
            # Проверяем клик по шапке (в зоне _block_wrapper_rect)
            HEADER = 22
            MARGIN = 8
            
            # Шапка находится выше нода: от -HEADER-MARGIN до -MARGIN
            if local_pos.y() < -MARGIN and local_pos.y() > -HEADER - MARGIN:
                if event.button() == Qt.MouseButton.LeftButton:
                    # Начинаем перетаскивание блока
                    self._dragging_block = True
                    self._drag_block_start_pos = self.pos()
                    self._drag_block_mouse_start = event.scenePos()
                    # ═══ ИСПРАВЛЕНИЕ: Поднимаем Z-ордер перетаскиваемого блока выше всех ═══
                    max_z = 0
                    for item in self._scene_ref.items():
                        if isinstance(item, (AgentNodeItem, BlockHeaderItem)):
                            max_z = max(max_z, item.zValue())
                    # Устанавливаем базовый Z для всей цепочки
                    for node_info in self._dragged_block_nodes:
                        item = node_info['item']
                        item.setZValue(max_z + 10 + self._dragged_block_nodes.index(node_info))
                        if hasattr(item, '_block_header') and item._block_header:
                            item._block_header.setZValue(max_z + 100 + self._dragged_block_nodes.index(node_info))
                    
                    # Собираем все ноды цепочки
                    self._dragged_block_nodes = []
                    current_id = self.node.id
                    visited = set()
                    
                    while current_id and current_id not in visited:
                        visited.add(current_id)
                        item = self._scene_ref.get_node_item(current_id)
                        if not item:
                            break
                        
                        self._dragged_block_nodes.append({
                            'item': item,
                            'start_pos': QPointF(item.pos().x(), item.pos().y())
                        })
                        
                        children = getattr(item.node, 'attached_children', [])
                        current_id = children[0] if children else None
                    
                    self._log_msg(f"🎯 " + tr("Захвачен блок: {0} нодов").format(len(self._dragged_block_nodes)))
                    self._drag_block_click_pos = event.scenePos()  # запоминаем для проверки "был ли реальный drag"
                    event.accept()
                    return
        
        # ═══ ОБЫЧНАЯ ОБРАБОТКА (порты и т.д.) ═══
        if event.button() == Qt.MouseButton.LeftButton:
            # ═══ ИСПРАВЛЕНИЕ: сбрасываем флаг перетаскивания блока у других нод ═══
            # Это предотвращает "залипание" состояния drag между разными нодами
            if self._scene_ref:
                for item in self._scene_ref.items():
                    if isinstance(item, AgentNodeItem) and item != self:
                        if hasattr(item, '_dragging_block'):
                            item._dragging_block = False
                        if hasattr(item, '_dragged_block_nodes'):
                            item._dragged_block_nodes = []
                        # Сбрасываем позицию мыши чтобы не было телепорта
                        if hasattr(item, '_drag_start_mouse_pos'):
                            item._drag_start_mouse_pos = None
            # ═══════════════════════════════════════════════════════════════════
            
            # ═══ ПОРТ ОШИБКИ (красный, нижний правый) ═══
            err_port = self.error_port_local()
            dist_err = (local_pos - err_port).manhattanLength()
            if dist_err < (self.PORT_RADIUS + 6):
                self._drag_start_port = 'error'
                self._start_edge_drag(event)
                event.accept()
                return
            
            # ═══ SWITCH CASE ПОРТЫ (правая сторона, распределённые) ═══
            if self.node.agent_type == AgentType.SWITCH:
                cases = self._get_switch_cases()
                n = max(len(cases), 1)
                for i in range(n):
                    port_pos = self._switch_case_port_local(i, n)
                    dist = (local_pos - port_pos).manhattanLength()
                    if dist < (self.PORT_RADIUS + 6):
                        self._drag_start_port = f'switch_case_{i}'
                        self._start_edge_drag(event)
                        event.accept()
                        return
            
            # ═══ ОБЫЧНЫЙ ВЫХОДНОЙ ПОРТ (правый центр) ═══
            # Для всех кроме заметок
            if self.node.agent_type != AgentType.NOTE:
                out_port = QPointF(self.node.width, self.node.height / 2)
                dist_out = (local_pos - out_port).manhattanLength()
                if dist_out < (self.PORT_RADIUS + 6):
                    self._drag_start_port = 'output'
                    self._start_edge_drag(event)
                    event.accept()
                    return
        
        # Сохраняем позицию ноды для undo и позицию мыши для порога открепления
        self._drag_start_pos = self.pos()
        
        # ═══ ИСПРАВЛЕНИЕ: корректировка позиции мыши при переключении с блока ═══
        # Если предыдущее действие было с другой нодой в режиме drag блока,
        # позиция мыши может быть сильно смещена - синхронизируем
        expected_pos = self.sceneBoundingRect().center()
        actual_pos = event.scenePos()
        delta = (actual_pos - expected_pos).manhattanLength()
        
        # Если курсор далеко от центра ноды (более чем на 200px), 
        # значит был "скачок" - сбрасываем начальную позицию
        if delta > 200:
            # Принудительно устанавливаем позицию мыши в центр ноды
            # чтобы избежать телепорта
            self._drag_start_mouse_pos = expected_pos
            # Обновляем позицию курсора в событии невозможно, 
            # но можно предотвратить расчет delta в mouseMoveEvent
            self._detach_triggered = True  # Блокируем авто-открепление
        else:
            self._drag_start_mouse_pos = actual_pos
        # ═══════════════════════════════════════════════════════════════════════
        
        # Стандартное поведение — выделение/перетаскивание
        super().mousePressEvent(event)
    
    def output_port_pos(self, target_pos: QPointF = None) -> QPointF:
        """Выходной порт — зависит от стороны цели (левый или правый)."""
        # Используем node.x/node.y напрямую чтобы избежать рекурсии через self.pos()
        my_pos = QPointF(self.node.x, self.node.y)
        
        if target_pos is None:
            # По умолчанию — правый центр
            return my_pos + QPointF(self.node.width, self.node.height / 2)
        
        # Определяем с какой стороны цель
        my_center_x = my_pos.x() + self.node.width / 2
        target_center_x = target_pos.x()
        
        if target_center_x >= my_center_x:
            # Цель справа или на том же уровне — выходим справа
            return my_pos + QPointF(self.node.width, self.node.height / 2)
        else:
            # Цель слева — выходим слева
            return my_pos + QPointF(0, self.node.height / 2)

    def input_port_left_top(self) -> QPointF:
        """Левая сторона, около верхнего края — когда источник слева."""
        return QPointF(self.node.x, self.node.y) + QPointF(0, 16)

    def input_port_right_top(self) -> QPointF:
        """Правая сторона, около верхнего края — когда источник справа."""
        return QPointF(self.node.x, self.node.y) + QPointF(self.node.width, 16)

    def input_port_pos(self) -> QPointF:
        """Дефолт — верхний левый (используется только как fallback)."""
        return self.input_port_left_top()
    
    def error_port_local(self) -> QPointF:
        """Позиция порта ошибки в локальных координатах (нижний правый)."""
        w, h = self.node.width, self.node.height
        return QPointF(w - 3, h - 10)  # Сдвинут внутрь для лучшего попадания

    def error_port_pos(self) -> QPointF:
        """Позиция порта ошибки в сцене."""
        # Используем node.x/node.y напрямую чтобы избежать рекурсии через self.pos()
        return QPointF(self.node.x, self.node.y) + self.error_port_local()

    def _is_error_port_click(self, local_pos: QPointF) -> bool:
        return (local_pos - self.error_port_local()).manhattanLength() < self.PORT_RADIUS + 6

    def _get_switch_cases(self) -> list:
        """Список значений cases из snippet_config Switch-ноды."""
        cfg = getattr(self.node, 'snippet_config', {}) or {}
        raw = cfg.get('cases', '')
        if not raw:
            return []
        return [ln.strip() for ln in str(raw).split('\n') if ln.strip()]

    def _switch_case_port_local(self, i: int, n: int) -> QPointF:
        """Локальная позиция i-го выходного порта Switch (правая сторона)."""
        w, h = self.node.width, self.node.height
        margin = 35  # Отступ сверху/снизу
        if n <= 1:
            y = h / 2
        else:
            available = h - 2 * margin
            y = margin + (available * i / (n - 1))
        return QPointF(w - 3, y)  # Сдвинут внутрь для лучшего попадания

    def switch_case_port_pos(self, i: int, n: int) -> QPointF:
        """Позиция i-го case-порта Switch в координатах сцены."""
        return QPointF(self.node.x, self.node.y) + self._switch_case_port_local(i, n)


class BlockHeaderItem(QGraphicsRectItem):
    HEADER_HEIGHT = 22
    MARGIN = 8
    
    def __init__(self, parent_node_item: AgentNodeItem):
        # ═══ ИСПРАВЛЕНИЕ: используем константу напрямую, не self. ═══
        super().__init__(0, 0, 100, 22)  # HEADER_HEIGHT = 22
        self._parent_node = parent_node_item
        self._scene_ref = parent_node_item._scene_ref if parent_node_item else None
        if self._scene_ref is None:
            print("⚠️ BlockHeaderItem: _scene_ref is None")
        self.setZValue(1000)  # Временное значение, переопределится  # Выше ноды (10)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self._dragging = False
        self._drag_start_pos = None
        self._chain_items = []  # Кэш цепочки при начале драга
        
        # Визуальный стиль шапки
        self._setup_visuals()
        # ═══ ИСПРАВЛЕНИЕ: НЕ вызываем update_geometry здесь — позиция ещё неизвестна ═══
    
    def _remove_self(self):
        """Безопасное самоудаление из сцены."""
        try:
            if self.scene():
                self.scene().removeItem(self)
        except RuntimeError:
            pass
        if self._parent_node and hasattr(self._parent_node, '_block_header'):
            self._parent_node._block_header = None
    
    def _setup_visuals(self):
        self.setPen(QPen(QColor(get_color("ac")), 2))
        self.setBrush(QBrush(QColor(get_color("bg3"))))
    
    def update_geometry(self):
        """Обновить позицию и размер относительно родительской ноды."""
        try:
            if not self._parent_node:
                return
            if not hasattr(self._parent_node, 'node') or self._parent_node.node is None:
                return
            if self._parent_node.scene() is None:
                self._remove_self()
                return
            
            # Проверяем что родитель всё ещё корень
            has_children = bool(getattr(self._parent_node.node, 'attached_children', []))
            has_parent = bool(getattr(self._parent_node.node, 'attached_to', None))
            
            if not has_children or has_parent:
                self._remove_self()
                return
            
            parent_rect = self._parent_node.rect()
            parent_pos = self._parent_node.pos()
            
            # ═══ ИСПРАВЛЕНИЕ: используем ЛОКАЛЬНЫЕ переменные, не self. ═══
            margin = 8
            header_height = 22
            
            new_rect = QRectF(
                -margin,
                -header_height - margin,
                parent_rect.width() + margin * 2,  # ← скобки!
                header_height
            )
            self.setRect(new_rect)
            self.setPos(parent_pos)
            # ═══ ИСПРАВЛЕНИЕ: Синхронизируем Z-ордер с родителем ═══
            if self._parent_node:
                parent_z = self._parent_node.zValue()
                self.setZValue(parent_z + 1000)  # Шапка всегда выше родителя на 1000
        except Exception as e:
            print(f"[BlockHeaderItem.update_geometry ERROR] {e}")
    
    def paint(self, painter: QPainter, option, widget=None):
        # Фон шапки
        base_color = self._parent_node.node.custom_color if getattr(self._parent_node.node, 'custom_color', '') else _AGENT_COLORS.get(self._parent_node.node.agent_type, "#565f89")
        color = QColor(base_color)
        
        # Градиент
        grad = QLinearGradient(0, 0, self.rect().width(), 0)
        grad.setColorAt(0, color)
        c2 = QColor(color)
        c2.setAlpha(160)
        grad.setColorAt(1, c2)
        
        painter.fillRect(self.rect(), QBrush(grad))
        
        # Рамка
        pen = QPen(color, 2 if self._hovered else 1)
        painter.setPen(pen)
        painter.drawRect(self.rect())
        
        # Текст
        painter.setPen(QPen(QColor(get_color("tx0")), 1))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        
        # Собираем цепочку для подсчета
        chain_count = self._get_chain_count()
        
        header_text = f"⛓ " + tr("Блок · {0} нодов").format(chain_count) + "  ⠿"
        painter.drawText(
            self.rect().adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            header_text
        )
        
        # Подсказка при наведении
        if self._hovered:
            painter.setPen(QPen(QColor(get_color("ac")), 1))
            painter.setFont(QFont("Segoe UI", 7))
            hint_rect = self.rect().adjusted(0, -14, 0, 0)
            painter.drawText(
                hint_rect,
                Qt.AlignmentFlag.AlignCenter,
                tr("Зажмите чтобы переместить блок")
            )
    
    def _get_chain_count(self) -> int:
        """Подсчитать количество нодов в цепочке (рекурсивно)."""
        if self._scene_ref is None:
            return 1
        count = [0]
        visited = set()

        def _count(node_id):
            if not node_id or node_id in visited:
                return
            visited.add(node_id)
            item = self._scene_ref.get_node_item(node_id)
            if not item:
                return
            count[0] += 1
            for child_id in getattr(item.node, 'attached_children', []):
                _count(child_id)

        _count(self._parent_node.node.id)
        return count[0]
    
    def _get_chain_items(self) -> list:
        """Получить все элементы цепочки (рекурсивно, все ветки)."""
        items = []
        if self._parent_node is None or not hasattr(self._parent_node, 'node'):
            return items
        if self._scene_ref is None:
            return items

        visited = set()

        def _collect(node_id):
            if not node_id or node_id in visited:
                return
            visited.add(node_id)
            item = self._scene_ref.get_node_item(node_id)
            if not item or item.scene() is None:
                return
            items.append({
                'item': item,
                'start_pos': QPointF(item.pos().x(), item.pos().y())
            })
            for child_id in getattr(item.node, 'attached_children', []):
                _collect(child_id)

        _collect(self._parent_node.node.id)
        return items
    
    def hoverEnterEvent(self, event):
        self._hovered = True
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.update()
    
    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # Защита: проверяем что родительская нода всё ещё в сцене
            if self._parent_node is None or self._parent_node.scene() is None:
                event.ignore()
                return
            
            self._dragging = True
            self._drag_start_pos = event.scenePos()
            self._chain_items = self._get_chain_items()
            
            # Защита: если цепочка пуста — отменяем
            if not self._chain_items:
                self._dragging = False
                event.ignore()
                return
            
            # ═══ ИСПРАВЛЕНИЕ: синхронизируем позицию с родителем перед драгом ═══
            self.setPos(self._parent_node.pos())
            
            # ═══ ИСПРАВЛЕНИЕ: пересохраняем start_pos ПОСЛЕ синхронизации позиции ═══
            # чтобы при отпускании без движения позиции совпадали и блок не прыгал
            for node_info in self._chain_items:
                node_info['start_pos'] = QPointF(node_info['item'].pos().x(), node_info['item'].pos().y())
            
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Перетаскивание блока целиком."""
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            # Защита: проверяем что сцена существует
            if self.scene() is None or self._scene_ref is None:
                return
            
            # Защита: проверяем что родительская нода всё ещё в сцене
            if self._parent_node is None or self._parent_node.scene() is None:
                self._dragging = False
                return
            
            delta = event.scenePos() - self._drag_start_pos
            
            # Перемещаем все ноды цепочки
            for node_info in self._chain_items:
                item = node_info['item']
                # Защита: проверяем что элемент всё ещё в сцене
                if item.scene() is None:
                    continue
                new_pos = node_info['start_pos'] + delta
                
                # Snap to grid
                grid = 20
                x = round(new_pos.x() / grid) * grid
                y = round(new_pos.y() / grid) * grid
                snapped = QPointF(x, y)
                
                item.setPos(snapped)
                item.node.x = snapped.x()
                item.node.y = snapped.y()
            
            # ═══ ИСПРАВЛЕНИЕ: обновляем позицию шапки СИНХРОННО с родителем ═══
            parent_pos = self._parent_node.pos()
            self.setPos(parent_pos)
            
            self._scene_ref.update_edges()
            self._scene_ref.invalidate()
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging:
            self._dragging = False
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            
            # Защита: проверяем что сцена всё ещё существует
            if self.scene() is None or self._scene_ref is None:
                self._chain_items = []
                event.accept()
                return
            
            # ═══ ИСПРАВЛЕНИЕ: если не было реального перемещения — просто сбрасываем ═══
            if self._drag_start_pos is not None:
                delta = event.scenePos() - self._drag_start_pos
                if abs(delta.x()) < 3 and abs(delta.y()) < 3:
                    # Простой клик без движения — восстанавливаем позиции
                    for node_info in self._chain_items:
                        item = node_info['item']
                        if item.scene() is not None:
                            item.setPos(node_info['start_pos'])
                            item.node.x = node_info['start_pos'].x()
                            item.node.y = node_info['start_pos'].y()
                    if self._scene_ref:
                        self._scene_ref.update_edges()
                    self._chain_items = []
                    event.accept()
                    return
            
            # ═══ ИСПРАВЛЕНИЕ: ПРЕДОХРАНИТЕЛЬ для блока — проверяем позиции всех нодов ═══
            cursor_pos = event.scenePos()
            for node_info in self._chain_items:
                item = node_info['item']
                if item.scene() is None:
                    continue
                    
                node_center = item.sceneBoundingRect().center()
                distance = (cursor_pos - node_center).manhattanLength()
                
                # Если нода далеко от курсора — корректируем всю цепочку относительно курсора
                if distance > 200 and len(self._chain_items) > 0:
                    # Вычисляем смещение относительно первой ноды
                    first_item = self._chain_items[0]['item']
                    first_pos = first_item.pos()
                    
                    # Новая позиция первой ноды — под курсор
                    offset = QPointF(first_item.node.width / 2, 11)  # 11 = HEADER_HEIGHT/2 + MARGIN
                    new_first_pos = cursor_pos - offset
                    
                    # Snap to grid
                    grid = 20
                    x = round(new_first_pos.x() / grid) * grid
                    y = round(new_first_pos.y() / grid) * grid
                    new_first_pos = QPointF(x, y)
                    
                    # Применяем смещение ко всей цепочке
                    delta = new_first_pos - first_pos
                    for ni in self._chain_items:
                        it = ni['item']
                        if it.scene() is None:
                            continue
                        new_pos = it.pos() + delta
                        it.setPos(new_pos)
                        it.node.x = new_pos.x()
                        it.node.y = new_pos.y()
                    
                    # Обновляем рёбра
                    self._scene_ref.update_edges()
                    self._scene_ref.invalidate()
                    self._scene_ref.update()
                    
                    if hasattr(self._scene_ref, '_main_window'):
                        mw = self._scene_ref._main_window
                        if hasattr(mw, '_log_msg'):
                            mw._log_msg(f"🛡️ Телепорт блока предотвращён, возвращён под курсор")
                    break  # Корректируем только один раз для всей цепочки
            # ═════════════════════════════════════════════════════════════════════════════════
            
            # ═══ ИСПРАВЛЕНИЕ: Проверяем что родительская нода всё ещё валидна ═══
            if self._parent_node is None or self._parent_node.scene() is None:
                event.accept()
                return
            
            # ═══ ИСПРАВЛЕНИЕ: Проверяем что цепочка не пуста ═══
            if not self._chain_items:
                event.accept()
                return
            
            # Защита: проверяем что родительская нода всё ещё валидна
            if self._parent_node is None or self._parent_node.scene() is None:
                event.accept()
                return
            
            # Защита: проверяем что цепочка не пуста
            if not self._chain_items:
                event.accept()
                return

                
            # Создаем undo для перемещения блока
            if hasattr(self._scene_ref, '_main_window'):
                mw = self._scene_ref._main_window
                if hasattr(mw, '_history'):
                    old_positions = [(n['item'], QPointF(n['start_pos'].x(), n['start_pos'].y())) 
                                    for n in self._chain_items]
                    new_positions = [(n['item'], QPointF(n['item'].pos().x(), n['item'].pos().y())) 
                                    for n in self._chain_items]
                    
                    scene_ref = self._scene_ref
                    
                    def make_undo_block(old_pos_list):
                        def _undo():
                            for item, pos in old_pos_list:
                                item.setPos(pos)
                                item.node.x = pos.x()
                                item.node.y = pos.y()
                            scene_ref.update_edges()
                            scene_ref.invalidate()
                            scene_ref.update()
                        return _undo
                    
                    def make_redo_block(new_pos_list):
                        def _redo():
                            for item, pos in new_pos_list:
                                item.setPos(pos)
                                item.node.x = pos.x()
                                item.node.y = pos.y()
                            scene_ref.update_edges()
                            scene_ref.invalidate()
                            scene_ref.update()
                        return _redo
                    
                    mw._history.push(
                        make_redo_block(new_positions),
                        make_undo_block(old_positions),
                        tr("Перемещение блока ({0} нодов)").format(len(self._chain_items))
                    )
                    mw._mark_modified_from_props()
            
            # Сбрасываем устаревшее состояние у всех нодов цепочки
            for node_info in self._chain_items:
                item = node_info['item']
                item._drag_start_mouse_pos = None
                item._detach_triggered = False
                # ═══ ИСПРАВЛЕНИЕ: сбрасываем флаг drag блока ═══
                item._dragging_block = False
                # ═══════════════════════════════════════════════
            self._chain_items = []
            
            # ═══ ИСПРАВЛЕНИЕ: глобальный сброс состояния drag ═══
            # Чтобы следующий клик по другой ноде не унаследовал состояние
            if self._scene_ref:
                for item in self._scene_ref.items():
                    if isinstance(item, AgentNodeItem):
                        item._dragging_block = False
                        if hasattr(item, '_dragged_block_nodes'):
                            item._dragged_block_nodes = []
            # ════════════════════════════════════════════════════
            
            event.accept()


class EdgeItem(QGraphicsPathItem):
    """Visual arrow between two agent nodes."""

    PORT_RADIUS = 8  # Радиус захвата для перетаскивания

    def __init__(self, edge: AgentEdge, source: AgentNodeItem, target: AgentNodeItem, scene_ref: "WorkflowScene" = None):
        super().__init__()
        # Защита: проверяем аргументы
        if edge is None or source is None or target is None:
            raise ValueError("EdgeItem: edge, source and target cannot be None")
        
        self.edge = edge
        self.source = source
        self.target = target
        self._scene_ref = scene_ref
        self.setZValue(5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self._dragging_target = False
        self._temp_target_pos = None
        self._update_path()

    def _update_path(self):
        # Защита: проверяем что source и target существуют
        if self.source is None or self.target is None:
            return
        
        # ═══ ВРЕМЕННАЯ ОТРИСОВКА ПРИ ПЕРЕТАСКИВАНИИ ТАРГЕТА ═══
        if self._dragging_target and self._temp_target_pos:
            p1 = self._get_source_port_pos()
            p2 = self._temp_target_pos
            
            path = QPainterPath()
            path.moveTo(p1)
            dx = max(abs(p2.x() - p1.x()) * 0.5, 60)
            
            # Определяем направление для контрольных точек
            if p2.x() >= p1.x():
                cp1 = QPointF(p1.x() + dx, p1.y())
                cp2 = QPointF(p2.x() - dx, p2.y())
            else:
                cp1 = QPointF(p1.x() - dx, p1.y())
                cp2 = QPointF(p2.x() + dx, p2.y())
            
            path.cubicTo(cp1, cp2, p2)
            self.setPath(path)
            return

        # ── Определяем стартовый порт источника ──
        # Центр цели для определения с какой стороны выходить
        target_center = self.target.pos() + QPointF(self.target.node.width / 2, self.target.node.height / 2)
        
        if self.edge.condition == EdgeCondition.ON_FAILURE:
            p1 = self.source.error_port_pos()
        elif (self.source.node.agent_type == AgentType.SWITCH
              and self.edge.label and self.edge.label.startswith('__sw_')):
            try:
                i = int(self.edge.label.split('__sw_')[1].split('__')[0])
                cases = self.source._get_switch_cases()
                n = max(len(cases), 1)
                p1 = self.source.pos() + self.source._switch_case_port_local(i, n)
            except Exception:
                p1 = self.source.output_port_pos(target_center)
        else:
            p1 = self.source.output_port_pos(target_center)

        # Входной порт — левый или правый верхний угол в зависимости от стороны источника
        src_center_x = p1.x()
        tgt_center_x = self.target.pos().x() + self.target.node.width / 2
        if src_center_x <= tgt_center_x:
            p2 = self.target.input_port_left_top()   # источник слева → левый верхний
        else:
            p2 = self.target.input_port_right_top()  # источник справа → правый верхний

        # Безье: горизонтально от источника, горизонтально к боковому порту цели
        path = QPainterPath()
        path.moveTo(p1)
        dx = max(abs(p2.x() - p1.x()) * 0.5, 60)
        
        # ═══ ИСПРАВЛЕНИЕ: направление контрольных точек зависит от стороны ═══
        if src_center_x <= tgt_center_x:
            # Источник слева: выход вправо, вход слева
            cp1 = QPointF(p1.x() + dx, p1.y())
            cp2 = QPointF(p2.x() - dx, p2.y())
        else:
            # Источник справа: выход влево, вход справа
            cp1 = QPointF(p1.x() - dx, p1.y())
            cp2 = QPointF(p2.x() + dx, p2.y())
        
        path.cubicTo(cp1, cp2, p2)
        self.setPath(path)
    def _get_source_port_pos(self) -> QPointF:
        """Получить позицию исходного порта для временной отрисовки."""
        if self.source is None:
            return QPointF(0, 0)
        
        if self.edge.condition == EdgeCondition.ON_FAILURE:
            return self.source.error_port_pos()
        elif (self.source.node.agent_type == AgentType.SWITCH
              and self.edge.label and self.edge.label.startswith('__sw_')):
            try:
                i = int(self.edge.label.split('__sw_')[1].split('__')[0])
                cases = self.source._get_switch_cases()
                n = max(len(cases), 1)
                return self.source.pos() + self.source._switch_case_port_local(i, n)
            except Exception:
                pass
        # Дефолт — правый центр
        return self.source.pos() + QPointF(self.source.node.width, self.source.node.height / 2)
    
    def update_position(self):
        if self.source is None or self.target is None:
            return
        # Защита: не обновляем если source/target в процессе itemChange
        if getattr(self.source, '_in_item_change', False) or getattr(self.target, '_in_item_change', False):
            return
        self._update_path()

    def paint(self, painter: QPainter, option, widget=None):
        # Защита: проверяем что source и target в сцене
        if self.source is None or self.target is None:
            return
        if self.source.scene() is None or self.target.scene() is None:
            return
        
        self._update_path()
        
        # ═══ ИСПРАВЛЕНИЕ: красная толстая пунктирная линия для ошибки ═══
        pen = self.pen()
        if self.edge.condition == EdgeCondition.ON_FAILURE:
            pen.setColor(QColor(get_color("err")))  
            pen.setWidth(3)                         
            pen.setStyle(Qt.PenStyle.DashLine)      
        else:
            # ═══ ИСПРАВЛЕНИЕ: Адаптивный цвет стрелок в зависимости от темы ═══
            # На светлой теме — тёмный цвет, на тёмной — светлый
            if is_dark_theme():
                edge_color = QColor(get_color("tx0"))  # Светлый для тёмной темы
            else:
                edge_color = QColor(get_color("tx0"))  # Тёмный для светлой темы
            pen.setColor(edge_color)
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.SolidLine)
        self.setPen(pen)
        # ════════════════════════════════════════════════════════════════
        
        super().paint(painter, option, widget)

        # Рисуем интерактивную точку на конце стрелки (таргет)
        path = self.path()
        if not path.isEmpty():
            end = path.pointAtPercent(1.0)
            
            # Круг для захвата в конце стрелки
            if self._hovered or self._dragging_target:
                painter.setBrush(QBrush(QColor("#E0AF68")))  # Оранжевый при наведении
                painter.setPen(QPen(QColor("#E0AF68"), 2))
            else:
                # Адаптивный цвет точки
                if is_dark_theme():
                    dot_color = QColor(get_color("tx1"))  # Светлый для тёмной темы
                else:
                    dot_color = QColor(get_color("tx1"))  # Тёмный для светлой темы
                painter.setBrush(QBrush(dot_color))
                painter.setPen(QPen(QColor(get_color("bg0")), 1))
            
            # Рисуем круг в конце стрелки (таргет-порт)
            painter.drawEllipse(end, self.PORT_RADIUS, self.PORT_RADIUS)
            
            # Подсказка при наведении
            if self._hovered and not self._dragging_target:
                painter.setPen(QPen(QColor("#E0AF68"), 1))
                painter.setFont(QFont("Segoe UI", 8))
                painter.drawText(end + QPointF(10, -10), "↺ " + tr("перетащить"))

        # Draw arrowhead at target
        path = self.path()
        if path.isEmpty():
            return
        end = path.pointAtPercent(1.0)
        pre = path.pointAtPercent(0.96)
        angle = math.atan2(end.y() - pre.y(), end.x() - pre.x())
        arrow_size = 10
        p1 = QPointF(
            end.x() - arrow_size * math.cos(angle - math.pi / 6),
            end.y() - arrow_size * math.sin(angle - math.pi / 6),
        )
        p2 = QPointF(
            end.x() - arrow_size * math.cos(angle + math.pi / 6),
            end.y() - arrow_size * math.sin(angle + math.pi / 6),
        )
        painter.setBrush(QBrush(self.pen().color()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([end, p1, p2]))

        # Draw label if present (пропускаем для ошибок, так как ниже рисуется кастомный бейдж)
        if self.edge.label and self.edge.condition != EdgeCondition.ON_FAILURE:
            mid = path.pointAtPercent(0.5)
            painter.setPen(QPen(QColor(get_color("tx1")), 1))
            painter.setFont(QFont("Segoe UI", 8))
            # Switch-рёбра — показывать только значение case без служебного префикса
            display_label = self.edge.label
            if display_label.startswith('__sw_') and '__:' in display_label:
                display_label = display_label.split('__:', 1)[1]
            painter.drawText(mid + QPointF(5, -5), display_label)

        # ON_FAILURE: draw second arrowhead at midpoint + "⚡ error" badge
        if self.edge.condition == EdgeCondition.ON_FAILURE:
            mid = path.pointAtPercent(0.5)
            mid_pre = path.pointAtPercent(0.46)
            err_angle = math.atan2(mid.y() - mid_pre.y(), mid.x() - mid_pre.x())
            err_size = 8
            ep1 = QPointF(
                mid.x() - err_size * math.cos(err_angle - math.pi / 6),
                mid.y() - err_size * math.sin(err_angle - math.pi / 6),
            )
            ep2 = QPointF(
                mid.x() - err_size * math.cos(err_angle + math.pi / 6),
                mid.y() - err_size * math.sin(err_angle + math.pi / 6),
            )
            err_color = self.pen().color()
            painter.setBrush(QBrush(err_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([mid, ep1, ep2]))
            
            # Badge background — смещаем чтобы не перекрывать стрелку
            badge_rect = QRectF(mid.x() + 15, mid.y() - 8, 58, 16)
            painter.setBrush(QBrush(QColor(40, 20, 20, 200)))
            painter.setPen(QPen(err_color, 1))
            painter.drawRoundedRect(badge_rect, 3, 3)
            
            # Badge text — ОДИН раз
            painter.setPen(QPen(err_color, 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "⚡ error")
    
    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        """Начало перетаскивания конца стрелки (таргета)."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Проверяем, кликнули ли по концу стрелки (таргет-порт)
            path = self.path()
            if not path.isEmpty():
                end = path.pointAtPercent(1.0)
                local_pos = event.pos()
                dist = (local_pos - end).manhattanLength()
                
                if dist < (self.PORT_RADIUS + 6):
                    # Начинаем перетаскивание таргета
                    self._dragging_target = True
                    self._temp_target_pos = end
                    event.accept()
                    return
        
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Перетаскивание конца стрелки к новому таргету."""
        if self._dragging_target:
            # Защита: проверяем что сцена существует
            scene = self.scene()
            if scene is None:
                return
            
            self._temp_target_pos = event.scenePos()
            self.update()  # Перерисовать с временной позицией
            
            # ═══ ДОБАВЛЕНО: Автоскролл для существующих стрелочек (скорость 1) ═══
            if scene.views():
                view = self.scene().views()[0]
                from PyQt6.QtGui import QCursor
                from PyQt6.QtCore import QTimer
                
                view_pos = view.mapFromGlobal(QCursor.pos())
                view_rect = view.rect()
                
                margin = 40
                step = 1
                dx, dy = 0, 0
                
                if view_pos.x() < margin: dx = -step
                elif view_pos.x() > view_rect.width() - margin: dx = step
                if view_pos.y() < margin: dy = -step
                elif view_pos.y() > view_rect.height() - margin: dy = step
                
                if dx != 0 or dy != 0:
                    h_bar = view.horizontalScrollBar()
                    v_bar = view.verticalScrollBar()
                    QTimer.singleShot(0, lambda: h_bar.setValue(h_bar.value() + dx))
                    QTimer.singleShot(0, lambda: v_bar.setValue(v_bar.value() + dy))
            # ═════════════════════════════════════════════════════════════════════
            
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Отпускание — присоединение к новому сниппету или отмена."""
        if self._dragging_target:
            self._dragging_target = False
            
            # Ищем сниппет под курсором
            scene = self.scene()
            if scene is None:
                # Отмена — возвращаем к исходному таргету
                self._update_path()
                self.update()
                event.accept()
                return
            
            items = scene.items(event.scenePos())
            new_target = None
            
            for item in items:
                if isinstance(item, AgentNodeItem) and item != self.source:
                    new_target = item
                    break
            
            if new_target and new_target != self.target and self._scene_ref:
                # Меняем таргет
                old_target = self.target
                old_target_id = self.edge.target_id
                
                # Обновляем edge
                self.edge.target_id = new_target.node.id
                self.target = new_target
                
                # Пересоздаем визуал
                self._update_path()
                self.update()
                
                # Создаем undo
                mw = self._scene_ref._main_window if hasattr(self._scene_ref, '_main_window') else None
                if mw and hasattr(mw, '_history'):
                    edge = self.edge
                    scene_ref = self._scene_ref
                    
                    def _undo():
                        edge.target_id = old_target_id
                        # Найти старый item и обновить
                        for item in scene_ref._node_items.values():
                            if item.node.id == old_target_id:
                                self.target = item
                                break
                        self._update_path()
                        self.update()
                        scene_ref.update_edges()
                    
                    def _redo():
                        edge.target_id = new_target.node.id
                        self.target = new_target
                        self._update_path()
                        self.update()
                        scene_ref.update_edges()
                    
                    mw._history.push(_redo, _undo, 
                        tr("Переподключение {0} → {1}").format(self.source.node.name, new_target.node.name))
                
                if mw:
                    mw._log_msg(f"↺ " + tr("Переподключено: {0} → {1}").format(self.source.node.name, new_target.node.name))
                    mw._mark_modified_from_props()
            else:
                # Отмена — возвращаем к исходному таргету
                self._update_path()
                self.update()
            
            event.accept()
            return
        
        super().mouseReleaseEvent(event)