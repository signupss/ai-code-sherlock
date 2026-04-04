"""Вид (View) с поддержкой зума и навигации."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QCursor, QMouseEvent
from PyQt6.QtWidgets import QGraphicsView, QApplication, QGraphicsRectItem

from .items import AgentNodeItem

class WorkflowView(QGraphicsView):
    """Кастомный View с поддержкой Shift+Scroll (горизонтально), 
    Ctrl+Scroll (зум без вертикальной прокрутки) и панорамирования."""
    
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self._item_drag_active = False  # Флаг: перетаскивание элемента внутри канваса
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.timeout.connect(self._do_auto_scroll)
        # НЕ запускаем постоянно — стартуем только при drag
        
    def _do_auto_scroll(self):
        try:
            # Автоскролл ТОЛЬКО когда перетаскиваем элемент внутри канваса
            if not getattr(self, '_item_drag_active', False):
                self._last_scroll_dx = 0
                self._last_scroll_dy = 0
                return
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._item_drag_active = False
                self._last_scroll_dx = 0
                self._last_scroll_dy = 0
                return
            scene = self.scene()
            if scene is None:
                return
            if not scene.selectedItems():
                self._last_scroll_dx = 0
                self._last_scroll_dy = 0
                return
            vp = self.viewport()
            if vp is None:
                return
            vp_w = vp.width()
            vp_h = vp.height()
            cursor_pos = vp.mapFromGlobal(QCursor.pos())
            cx = cursor_pos.x()
            cy = cursor_pos.y()
            margin = 50
            speed = 14
            dx = dy = 0
            # Курсор внутри или рядом с viewport
            if -200 < cx < vp_w + 200 and -200 < cy < vp_h + 200:
                if cx < margin:
                    dx = -max(1, int((margin - cx) * speed / margin))
                elif cx > vp_w - margin:
                    dx = max(1, int((cx - (vp_w - margin)) * speed / margin))
                if cy < margin:
                    dy = -max(1, int((margin - cy) * speed / margin))
                elif cy > vp_h - margin:
                    dy = max(1, int((cy - (vp_h - margin)) * speed / margin))
                if dx or dy:
                    self._last_scroll_dx = dx
                    self._last_scroll_dy = dy
                else:
                    self._last_scroll_dx = 0
                    self._last_scroll_dy = 0
            else:
                dx = getattr(self, '_last_scroll_dx', 0)
                dy = getattr(self, '_last_scroll_dy', 0)
            if dx:
                hbar = self.horizontalScrollBar()
                hbar.setValue(hbar.value() + dx)
            if dy:
                vbar = self.verticalScrollBar()
                vbar.setValue(vbar.value() + dy)
        except Exception:
            pass

    def wheelEvent(self, event):
        """Shift+колесико = горизонтально, Ctrl+колесико = зум, иначе = вертикально."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Только зум, без прокрутки
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            # Обновляем лейбл зума в родительском окне
            if hasattr(self.parent(), '_update_zoom_label'):
                self.parent()._update_zoom_label()
            event.accept()
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Горизонтальная прокрутка (Shift + колесико)
            delta = event.angleDelta().y()
            hbar = self.horizontalScrollBar()
            hbar.setValue(hbar.value() - delta)
            event.accept()
        else:
            # Вертикальная прокрутка (по умолчанию)
            delta = event.angleDelta().y()
            vbar = self.verticalScrollBar()
            vbar.setValue(vbar.value() - delta)
            event.accept()
    
    def mousePressEvent(self, event):
        """Зажатие средней кнопки мыши для панорамирования."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake_event = QMouseEvent(
                event.type(), event.position(), event.globalPosition(),
                Qt.MouseButton.LeftButton,
                event.buttons() | Qt.MouseButton.LeftButton,
                event.modifiers()
            )
            super().mousePressEvent(fake_event)
        elif event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item and isinstance(item, (AgentNodeItem, QGraphicsRectItem)):
                self._item_drag_active = True
                if not self._auto_scroll_timer.isActive():
                    self._auto_scroll_timer.start(30)  # 30мс вместо 16
            else:
                self._item_drag_active = False
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Отпускание кнопки - сброс режимов."""
        if event.button() == Qt.MouseButton.MiddleButton:
            fake_event = QMouseEvent(
                event.type(), 
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton, 
                event.buttons() & ~Qt.MouseButton.LeftButton,
                event.modifiers()
            )
            super().mouseReleaseEvent(fake_event)
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self._item_drag_active = False
            self._auto_scroll_timer.stop()
            super().mouseReleaseEvent(event)
    
    def keyPressEvent(self, event):
        # Перехватываем горячие клавиши и отправляем родителю (главному окну)
        modifiers = event.modifiers()
        key = event.key()
        
        # Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y для undo/redo — всегда передаём родителю
        if (key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier) or \
           (key == Qt.Key.Key_Z and modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)) or \
           (key == Qt.Key.Key_Y and modifiers == Qt.KeyboardModifier.ControlModifier):
            # Передаем родителю (AgentConstructorWindow) для глобального undo/redo
            if self.parent():
                self.parent().keyPressEvent(event)
            return
        
        if (key == Qt.Key.Key_X and modifiers == Qt.KeyboardModifier.ControlModifier) or \
           (key == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier) or \
           (key == Qt.Key.Key_V and modifiers == Qt.KeyboardModifier.ControlModifier) or \
           (key == Qt.Key.Key_Delete):
            # Передаем родителю (AgentConstructorWindow)
            if self.parent():
                self.parent().keyPressEvent(event)
            return
        super().keyPressEvent(event)
