"""Система Undo/Redo и истории изменений."""
from typing import Optional

class Command:
    """Базовый класс для команд undo/redo"""
    def __init__(self, description: str = ""):
        self.description = description
    
    def execute(self):
        raise NotImplementedError
    
    def undo(self):
        raise NotImplementedError

class WidgetChangeCommand(Command):
    """Команда изменения виджета сниппета"""
    def __init__(self, widget, old_value, new_value, setter_func, description: str = ""):
        super().__init__(description)
        self.widget = widget
        self.old_value = old_value
        self.new_value = new_value
        self.setter_func = setter_func
        self._is_updating = False
    
    def execute(self):
        if not self._is_updating:
            self._is_updating = True
            self.setter_func(self.new_value)
            self._is_updating = False
    
    def undo(self):
        if not self._is_updating:
            self._is_updating = True
            self.setter_func(self.old_value)
            self._is_updating = False

class HistoryManager:
    """Управление историей действий для Undo/Redo"""
    def __init__(self, max_history=50):
        self.undo_stack = []
        self.redo_stack = []
        self.max_history = max_history
        self._is_undoing = False  # Флаг для предотвращения рекурсии
    
    def push(self, execute_fn, undo_fn, description: str = ""):
        """Добавить действие в историю (legacy tuple format)"""
        if self._is_undoing:
            return
        self.undo_stack.append((execute_fn, undo_fn, description))
        self.redo_stack.clear()
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
    
    def push_command(self, command: Command):
        """Добавить Command объект в историю"""
        if self._is_undoing:
            return
        self.undo_stack.append(command)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
    
    def undo(self):
        if not self.undo_stack or self._is_undoing:
            return None
        self._is_undoing = True
        try:
            item = self.undo_stack.pop()
            if isinstance(item, Command):
                item.undo()
                desc = item.description
                self.redo_stack.append(item)
            else:
                # Legacy tuple format
                _, undo_action, desc = item
                undo_action()
                self.redo_stack.append(item)
            return desc
        except Exception as e:
            print(f"Undo error: {e}")
            import traceback; traceback.print_exc()
            return None
        finally:
            self._is_undoing = False
    
    def redo(self):
        if not self.redo_stack or self._is_undoing:
            return None
        self._is_undoing = True
        try:
            item = self.redo_stack.pop()
            if isinstance(item, Command):
                item.execute()
                desc = item.description
                self.undo_stack.append(item)
            else:
                # Legacy tuple format
                execute_action, undo_action, desc = item
                execute_action()
                self.undo_stack.append(item)
            return desc
        except Exception as e:
            print(f"Redo error: {e}")
            import traceback; traceback.print_exc()
            return None
        finally:
            self._is_undoing = False
    
    def clear(self):
        """Очистить всю историю"""
        self.undo_stack.clear()
        self.redo_stack.clear()