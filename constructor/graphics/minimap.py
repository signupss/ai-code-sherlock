"""Миникарта проекта."""
from PyQt6.QtCore import Qt, QRectF, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene

from .items import AgentNodeItem

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

class MiniMapWidget(QGraphicsView):
    """Миникарта проекта с кнопками навигации."""

    def __init__(self, scene: QGraphicsScene, main_view: QGraphicsView, parent=None):
        super().__init__(scene, parent)
        self._main_view = main_view
        self._main_window = parent  # Сохраняем ссылку на родителя
        self.setFixedHeight(160)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setInteractive(False)
        self.setStyleSheet(f"""
            MiniMapWidget {{ border: 1px solid {get_color('bd')}; background: {get_color('bg0')}; }}
        """)
        self._dragging = False  # Флаг перетаскивания
        self._pan_dragging = False      # Флаг панорамирования миникарты
        self._pan_drag_start = None     # Начальная позиция мыши в пикселях
        self._group_drag_start = {}  # Стартовые позиции для группового undo
        
        # Таймер для обновления границ миникарты (реже, только при расширении)
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._expand_if_needed)
        self._update_timer.start(500)
        
        # Таймер для плавного следования за видом (чаще, только отрисовка)
        self._follow_timer = QTimer(self)
        self._follow_timer.timeout.connect(self.viewport().update)
        self._follow_timer.start(50)
        
        # Сохраняем полный bounding rect проекта
        self._project_rect = QRectF()
    
    def mousePressEvent(self, event):
        """Начало перетаскивания — запоминаем выбранные ноды."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._group_drag_start = {}
            # Сохраняем начальные позиции ВСЕХ выбранных нод на сцене
            for item in self.scene().selectedItems():
                if isinstance(item, AgentNodeItem):
                    self._group_drag_start[item.node.id] = item.pos()
        # Начало перетаскивания миникарты колесиком мыши (панорамирование вида миникарты)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._pan_dragging = True
            self._pan_drag_start = event.pos()  # Только позиция мыши в пикселях
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)
    
    def _expand_if_needed(self):
        """Обновить миникарту под реальные границы проекта (расширение и сужение)."""
        items_rect = self.scene().itemsBoundingRect()
        if items_rect.isNull():
            return
        
        margin = 100
        new_rect = QRectF(items_rect)
        new_rect.adjust(-margin, -margin, margin, margin)
        
        if new_rect != self._project_rect:
            self._project_rect = new_rect
            self.fitInView(self._project_rect, Qt.AspectRatioMode.KeepAspectRatio)
    
    def resizeEvent(self, event):
        """При изменении размера окна перецентровываем вид на проект."""
        super().resizeEvent(event)
        if hasattr(self, '_project_rect') and self._project_rect and not self._project_rect.isNull():
            self.fitInView(self._project_rect, Qt.AspectRatioMode.KeepAspectRatio)
    
    def _fit_all(self):
        """Подогнать вид миникарты под все элементы проекта."""
        items_rect = self.scene().itemsBoundingRect()
        if items_rect.isNull():
            return
        
        # Добавляем больше отступов для удобства навигации
        margin = 100
        items_rect.adjust(-margin, -margin, margin, margin)
        
        # Сохраняем текущий масштаб если пользователь его менял
        current_transform = self.transform()
        current_scale = current_transform.m11()
        
        # Применяем fitInView с сохранением пропорций
        self.fitInView(items_rect, Qt.AspectRatioMode.KeepAspectRatio)
        
        # Если масштаб слишком маленький, ограничиваем минимум
        new_scale = self.transform().m11()
        if new_scale < 0.05:
            self.resetTransform()
            self.scale(0.05, 0.05)
            # Центрируем на область элементов
            self.centerOn(items_rect.center())
    
    def update_visible_rect(self):
        """Обновить вид миникарты чтобы следовать за основным видом."""
        if not self._main_view:
            return
        
        # Получаем видимую область основного вида в координатах сцены
        viewport_rect = self._main_view.viewport().rect()
        visible_scene_rect = self._main_view.mapToScene(viewport_rect).boundingRect()
        
        # Если видимая область выходит за пределы текущего вида миникарты,
        # пересчитываем fitInView чтобы включить новую область
        current_scene_rect = self.sceneRect()
        
        # Расширяем rect миникарты если нужно
        needs_update = False
        new_rect = QRectF(current_scene_rect)
        
        if visible_scene_rect.left() < current_scene_rect.left():
            new_rect.setLeft(visible_scene_rect.left() - 50)
            needs_update = True
        if visible_scene_rect.right() > current_scene_rect.right():
            new_rect.setRight(visible_scene_rect.right() + 50)
            needs_update = True
        if visible_scene_rect.top() < current_scene_rect.top():
            new_rect.setTop(visible_scene_rect.top() - 50)
            needs_update = True
        if visible_scene_rect.bottom() > current_scene_rect.bottom():
            new_rect.setBottom(visible_scene_rect.bottom() + 50)
            needs_update = True
        
        if needs_update:
            # Добавляем отступы
            new_rect.adjust(-100, -100, 100, 100)
            self.fitInView(new_rect, Qt.AspectRatioMode.KeepAspectRatio)
        
        # Обновляем отображение рамки
        self.viewport().update()
    
    def wheelEvent(self, event):
        """Зум миникарты колесиком мыши."""
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        
        # Получаем позицию курсора в координатах сцены до зума
        scene_pos_before = self.mapToScene(event.position().toPoint())
        
        # Применяем зум
        self.scale(factor, factor)
        
        # Центрируем на позицию курсора чтобы зум был к точке под мышью
        scene_pos_after = self.mapToScene(event.position().toPoint())
        delta = scene_pos_after - scene_pos_before
        self.translate(delta.x(), delta.y())
        
        event.accept()
    
    def drawForeground(self, painter: QPainter, rect: QRectF):
        """Рисуем рамку текущей видимой области основного вида."""
        super().drawForeground(painter, rect)
        
        # Получаем видимую область основного вида
        viewport_rect = self._main_view.viewport().rect()
        scene_polygon = self._main_view.mapToScene(viewport_rect)
        
        if scene_polygon.isEmpty():
            return
        
        # Преобразуем полигон в прямоугольник
        visible_rect = scene_polygon.boundingRect()
        
        # Рисуем рамку с тенью для лучшей видимости
        # Тень
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 40)))
        shadow_rect = visible_rect.translated(2, 2)
        painter.drawRect(shadow_rect)
        
        # Основная рамка
        painter.setPen(QPen(QColor("#7AA2F7"), 2))
        painter.setBrush(QBrush(QColor(122, 162, 247, 30)))
        painter.drawRect(visible_rect)
        
        # Уголки для наглядности
        corner_size = min(20.0, min(visible_rect.width(), visible_rect.height()) / 4)
        painter.setPen(QPen(QColor("#7AA2F7"), 3))
        
        # Левый верхний
        painter.drawLine(
            int(visible_rect.left()), int(visible_rect.top() + corner_size),
            int(visible_rect.left()), int(visible_rect.top())
        )
        painter.drawLine(
            int(visible_rect.left()), int(visible_rect.top()),
            int(visible_rect.left() + corner_size), int(visible_rect.top())
        )
        
        # Правый верхний
        painter.drawLine(
            int(visible_rect.right() - corner_size), int(visible_rect.top()),
            int(visible_rect.right()), int(visible_rect.top())
        )
        painter.drawLine(
            int(visible_rect.right()), int(visible_rect.top()),
            int(visible_rect.right()), int(visible_rect.top() + corner_size)
        )
        
        # Левый нижний
        painter.drawLine(
            int(visible_rect.left()), int(visible_rect.bottom() - corner_size),
            int(visible_rect.left()), int(visible_rect.bottom())
        )
        painter.drawLine(
            int(visible_rect.left()), int(visible_rect.bottom()),
            int(visible_rect.left() + corner_size), int(visible_rect.bottom())
        )
        
        # Правый нижний
        painter.drawLine(
            int(visible_rect.right() - corner_size), int(visible_rect.bottom()),
            int(visible_rect.right()), int(visible_rect.bottom())
        )
        painter.drawLine(
            int(visible_rect.right()), int(visible_rect.bottom()),
            int(visible_rect.right()), int(visible_rect.bottom() - corner_size)
        )
    
    def mouseMoveEvent(self, event):
        """Перетаскивание по миникарте — плавная навигация основного вида."""
        if getattr(self, '_dragging', False) and event.buttons() & Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            self._main_view.centerOn(scene_pos)
            self.viewport().update()
            event.accept()
            return
        # Панорамирование миникарты колесиком мыши (перемещаем саму миникарту)
        if getattr(self, '_pan_dragging', False) and event.buttons() & Qt.MouseButton.MiddleButton:
            # Получаем текущий центр вида в координатах сцены
            viewport_rect = self.viewport().rect()
            current_center = self.mapToScene(viewport_rect.center())
            # Вычисляем смещение мыши в пикселях виджета
            delta_pixels = event.pos() - self._pan_drag_start
            # Преобразуем пиксели в координаты сцены с учетом текущего масштаба
            scale = self.transform().m11()
            if scale > 0:
                delta_scene = QPointF(delta_pixels.x() / scale, delta_pixels.y() / scale)
            else:
                delta_scene = QPointF(delta_pixels.x(), delta_pixels.y())
            # Перемещаем центр вида в противоположную сторону (для естественного движения)
            new_center = current_center - delta_scene
            self.centerOn(new_center)
            # Обновляем начальную позицию мыши
            self._pan_drag_start = event.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        
        # Отпускание колесика мыши — завершаем панорамирование миникарты
        if event.button() == Qt.MouseButton.MiddleButton and getattr(self, '_pan_dragging', False):
            self._pan_dragging = False
            self.unsetCursor()
            event.accept()
            return
        
        # Групповое undo для перемещения нескольких нод
        if not hasattr(self, '_group_drag_start') or not self._group_drag_start:
            self._group_drag_start = {}
            super().mouseReleaseEvent(event)
            return
        
        # Получаем выбранные ноды со СЦЕНЫ (не с миникарты!)
        selected_nodes = [item for item in self.scene().selectedItems() if isinstance(item, AgentNodeItem)]
        
        if len(selected_nodes) <= 1:
            # Для одной ноды undo уже создаёт AgentNodeItem.mouseReleaseEvent
            self._group_drag_start = {}
            return
        
        # Проверяем что хоть что-то сдвинулось
        moved = {}
        for item in selected_nodes:
            old_pos = self._group_drag_start.get(item.node.id)
            if old_pos is not None and old_pos != item.pos():
                moved[item.node.id] = (old_pos, item.pos())
        
        if not moved:
            self._group_drag_start = {}
            return
        
        # Сбрасываем _drag_start_pos у каждого item чтобы они НЕ создавали свои undo-записи
        for item in selected_nodes:
            item._drag_start_pos = None
        
        mw = self._main_window
        if mw and hasattr(mw, '_history'):
            scene = self.scene()
            # Снимок для замыкания
            _moved = dict(moved)
            _items_by_id = {item.node.id: item for item in selected_nodes}
            
            def _undo_group():
                for nid, (old_p, new_p) in _moved.items():
                    it = _items_by_id.get(nid)
                    if it:
                        it.setPos(old_p)
                        it.node.x = old_p.x()
                        it.node.y = old_p.y()
                scene.update_edges()
                scene.update()
            
            def _redo_group():
                for nid, (old_p, new_p) in _moved.items():
                    it = _items_by_id.get(nid)
                    if it:
                        it.setPos(new_p)
                        it.node.x = new_p.x()
                        it.node.y = new_p.y()
                scene.update_edges()
                scene.update()
            
            mw._history.push(_redo_group, _undo_group, f"Перемещение {len(moved)} нод")
        
        self._group_drag_start = {}
        super().mouseReleaseEvent(event)
