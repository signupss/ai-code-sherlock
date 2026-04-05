"""
Project Execution Manager — многопоточное управление проектами в стиле ZennoPoster.

Архитектура:
  - ProjectEntry: данные одного проекта (настройки, состояние, статистика)
  - ProjectExecutor: изолированный QThread для одного запуска проекта
  - ProjectExecutionManager: синглтон-диспетчер всех проектов
  - ProjectScheduler: планировщик расписания запусков

Каждый проект выполняется в полностью изолированном потоке.
Основной UI НИКОГДА не блокируется выполнением.
"""
from __future__ import annotations

import copy
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer, QMutex, QWaitCondition, QWaitCondition


# ══════════════════════════════════════════════════════════
#  ENUMS
# ══════════════════════════════════════════════════════════

class ProjectStatus(str, Enum):
    STOPPED     = "stopped"        # Остановлен
    QUEUED      = "queued"         # В очереди (ждёт слот)
    RUNNING     = "running"        # Выполняется
    PAUSED      = "paused"         # На паузе
    COMPLETED   = "completed"      # Все попытки выполнены
    SCHEDULED   = "scheduled"      # Ждёт по расписанию
    ERROR       = "error"          # Ошибка


class ThreadMode(str, Enum):
    SEQUENTIAL      = "sequential"      # Потоки по очереди
    PARALLEL        = "parallel"        # Потоки одновременно
    SEMAPHORE_WAIT  = "semaphore_wait"  # Ждут триггерный сниппет


class StopCondition(str, Enum):
    NONE             = "none"                # Нет условия остановки
    ON_FIRST_ERROR   = "on_first_error"      # При первой ошибке
    ON_N_ERRORS      = "on_n_errors"         # После N ошибок подряд
    ON_SUCCESS_COUNT = "on_success_count"     # После N успехов
    ON_TIME_LIMIT    = "on_time_limit"        # По таймауту


# ══════════════════════════════════════════════════════════
#  PROJECT ENTRY — данные одного проекта
# ══════════════════════════════════════════════════════════

@dataclass
class ProjectEntry:
    """Запись о проекте в менеджере выполнения."""
    # Идентификация
    project_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Новый проект"
    file_path: str = ""                # Путь к .json файлу workflow
    
    # Ссылки (не сериализуются)
    workflow: Any = field(default=None, repr=False)       # AgentWorkflow
    tab_reference: Any = field(default=None, repr=False)  # ProjectTab
    window_reference: Any = field(default=None, repr=False)  # AgentConstructorWindow
    
    # ═══ Настройки выполнения ═══
    max_threads: int = 1               # Макс потоков для этого проекта
    total_executions: int = -1         # Сколько раз выполнить (-1 = бесконечно)
    thread_mode: ThreadMode = ThreadMode.SEQUENTIAL
    
    # ═══ Триггерный сниппет (ресурсоёмкий) ═══
    bottleneck_snippet_id: str = ""    # ID сниппета-узкого горла
    bottleneck_max_concurrent: int = 1 # Сколько потоков могут одновременно выполнять его
    
    # ═══ Приоритет ═══
    priority: int = 5                  # 1-10, выше = важнее
    
    # ═══ Расписание ═══
    schedule_enabled: bool = False
    schedule_cron: str = ""            # Формат: "HH:MM" или "*/30" (каждые 30 мин)
    schedule_next_run: str = ""        # ISO datetime следующего запуска
    schedule_repeat: bool = False      # Повторять по расписанию
    
    # ═══ Условия остановки ═══
    stop_condition: StopCondition = StopCondition.NONE
    stop_value: int = 0                # Значение для условия (N ошибок, N успехов, секунды)
    
    # ═══ Прокси ═══
    proxy_mode: str = "none"           # none, from_list, from_checker
    proxy_list_path: str = ""
    
    # ═══ Метки ═══
    labels: list[str] = field(default_factory=list)
    
    # ═══ Статистика (runtime) ═══
    status: ProjectStatus = ProjectStatus.STOPPED
    current_threads: int = 0           # Сколько потоков сейчас работает
    completed_executions: int = 0      # Успешно завершённых
    failed_executions: int = 0         # Неуспешных
    consecutive_failures: int = 0      # Неуспехов подряд
    total_attempts: int = 0            # Всего попыток (успех + неуспех)
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str = ""
    last_run_at: str = ""
    
    # ═══ Настройки входных данных ═══
    input_settings: dict = field(default_factory=dict)
    # Формат: {"type": "none"|"file"|"list", "path": "...", "mode": "sequential"|"random"}
    
    @property
    def progress(self) -> float:
        """Прогресс в процентах."""
        if self.total_executions <= 0:
            return 0.0
        if self.total_executions == -1:
            return 0.0  # Бесконечное выполнение
        return min(100.0, (self.completed_executions / self.total_executions) * 100)
    
    @property
    def remaining(self) -> int:
        """Оставшиеся попытки."""
        if self.total_executions == -1:
            return -1
        return max(0, self.total_executions - self.total_attempts)
    
    def to_dict(self) -> dict:
        # Сохраняем global_variables из workflow.metadata если есть
        global_vars = []
        if self.workflow is not None:
            try:
                meta = getattr(self.workflow, 'metadata', None) or {}
                if isinstance(meta, str):
                    import json as _j
                    meta = _j.loads(meta) if meta.strip() else {}
                global_vars = meta.get('global_variables', [])
            except Exception:
                pass
        return {
            "project_id": self.project_id,
            "name": self.name,
            "file_path": self.file_path,
            "max_threads": self.max_threads,
            "total_executions": self.total_executions,
            "thread_mode": self.thread_mode.value,
            "bottleneck_snippet_id": self.bottleneck_snippet_id,
            "bottleneck_max_concurrent": self.bottleneck_max_concurrent,
            "priority": self.priority,
            "schedule_enabled": self.schedule_enabled,
            "schedule_cron": self.schedule_cron,
            "schedule_next_run": self.schedule_next_run,
            "schedule_repeat": self.schedule_repeat,
            "stop_condition": self.stop_condition.value,
            "stop_value": self.stop_value,
            "proxy_mode": self.proxy_mode,
            "proxy_list_path": self.proxy_list_path,
            "labels": self.labels,
            "completed_executions": self.completed_executions,
            "failed_executions": self.failed_executions,
            "added_at": self.added_at,
            "input_settings": self.input_settings,
            "global_variables": global_vars,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> ProjectEntry:
        entry = cls()
        for k, v in d.items():
            if k == "thread_mode":
                entry.thread_mode = ThreadMode(v)
            elif k == "stop_condition":
                entry.stop_condition = StopCondition(v)
            elif k == "status":
                entry.status = ProjectStatus(v)
            elif k == "global_variables":
                # Сохраняем для последующего восстановления в workflow.metadata
                entry.input_settings = entry.input_settings or {}
                entry.input_settings['_restored_global_variables'] = v
            elif hasattr(entry, k):
                setattr(entry, k, v)
        return entry


# ══════════════════════════════════════════════════════════
#  PROJECT EXECUTOR — изолированный поток выполнения
# ══════════════════════════════════════════════════════════

class ExecutorSignals(QObject):
    """Сигналы от одного потока выполнения."""
    started       = pyqtSignal(str, int)          # (project_id, thread_num)
    finished      = pyqtSignal(str, int, bool, str)  # (project_id, thread_num, success, summary)
    progress      = pyqtSignal(str, int, int, int)    # (project_id, thread_num, current_step, total)
    log           = pyqtSignal(str, int, str)         # (project_id, thread_num, message)
    node_started  = pyqtSignal(str, int, str, str)    # (project_id, thread_num, node_id, node_name)
    node_finished = pyqtSignal(str, int, str, bool)   # (project_id, thread_num, node_id, success)
    error         = pyqtSignal(str, int, str)          # (project_id, thread_num, error_msg)
    status_changed = pyqtSignal(str, str)              # (project_id, new_status)


class ProjectExecutor(QThread):
    """
    Изолированный поток для одного запуска проекта.
    
    Каждый экземпляр получает КОПИЮ workflow и собственный контекст,
    что обеспечивает полную изоляцию от других потоков.
    """
    
    def __init__(self, entry: ProjectEntry, thread_num: int,
                 model_manager, skill_registry,
                 global_semaphore: threading.Semaphore,
                 model_semaphores: dict,
                 bottleneck_semaphore: threading.Semaphore | None = None,
                 browser_launch_lock: threading.Lock | None = None,
                 parent=None):
        super().__init__(parent)
        self.signals = ExecutorSignals()
        
        self._entry = entry
        self._thread_num = thread_num
        self._model_manager = model_manager
        self._skill_registry = skill_registry
        self._global_semaphore = global_semaphore
        self._model_semaphores = model_semaphores
        self._bottleneck_semaphore = bottleneck_semaphore
        self._browser_launch_lock = browser_launch_lock  # Блокировка запуска браузера
        
        # Управление
        self._stop_requested = False
        self._pause_requested = False
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
    
    def stop(self):
        self._stop_requested = True
        self._pause_requested = False
        self._pause_condition.wakeAll()
    
    def pause(self):
        self._pause_requested = True
    
    def resume(self):
        self._pause_requested = False
        self._pause_condition.wakeAll()
    
    def run(self):
        """Основной цикл потока — выполняет workflow."""
        pid = self._entry.project_id
        tnum = self._thread_num
        acquired_global = False
        acquired_bn = False
        
        # Ждём глобальный слот
        self.signals.log.emit(pid, tnum, f"⏳ Поток #{tnum} ожидает глобальный слот...")
        acquired_global = self._global_semaphore.acquire(timeout=300)
        if not acquired_global:
            self.signals.error.emit(pid, tnum, "Таймаут ожидания глобального слота (300с)")
            self.signals.finished.emit(pid, tnum, False, "Таймаут очереди")
            return
        
        # Ждём bottleneck семафор (если есть) - чтобы не блокировать глобальный слот зря
        if self._bottleneck_semaphore:
            self.signals.log.emit(pid, tnum, f"⏳ Ожидание bottleneck семафора...")
            acquired_bn = self._bottleneck_semaphore.acquire(timeout=300)
            if not acquired_bn:
                self.signals.error.emit(pid, tnum, "Таймаут ожидания bottleneck (300с)")
                self.signals.finished.emit(pid, tnum, False, "Таймаут bottleneck")
                self._global_semaphore.release()
                return
        
        try:
            self.signals.started.emit(pid, tnum)
            self.signals.log.emit(pid, tnum, f"▶️ Поток #{tnum} запущен")
            
            success = self._execute_workflow()
            
            summary = "Успех" if success else "Ошибка"
            self.signals.finished.emit(pid, tnum, success, summary)
            
        except Exception as e:
            import traceback
            self.signals.error.emit(pid, tnum, str(e))
            self.signals.finished.emit(pid, tnum, False, f"Exception: {e}")
            traceback.print_exc()
        finally:
            # ═══ Закрытие браузеров по настройке проекта ═══
            try:
                workflow = getattr(self._entry, 'workflow', None)
                if workflow is None:
                    self.signals.log.emit(pid, tnum, f"⚠️ Workflow не найден при закрытии браузеров")
                    return
                    
                _should_close = getattr(workflow, 'close_browser_on_finish', True)
                bm = getattr(self, '_thread_browser_manager', None)
                
                if _should_close and bm:
                    # Закрываем ВСЕ браузеры этого потока
                    bm.close_all()
                    self.signals.log.emit(pid, tnum, f"🔴 Браузеры потока #{tnum} закрыты (close_browser_on_finish)")
                elif not _should_close:
                    self.signals.log.emit(pid, tnum, f"🌐 Браузеры потока #{tnum} оставлены открытыми")
            except Exception as e:
                self.signals.log.emit(pid, tnum, f"⚠️ Ошибка при закрытии браузеров: {e}")
            if acquired_bn:
                self._bottleneck_semaphore.release()
            if acquired_global:
                self._global_semaphore.release()
    
    def _execute_workflow(self) -> bool:
        """Выполняет workflow с защитой от зависаний."""
        pid = self._entry.project_id
        tnum = self._thread_num
        
        self.signals.log.emit(pid, tnum, "[EXEC] Старт выполнения workflow")
        
        try:
            from services.workflow_runtime import WorkflowRuntime
            from services.agent_models import AgentWorkflow
            import threading
            import queue
        except ImportError as e:
            self.signals.error.emit(pid, tnum, f"Import error: {e}")
            return False
        
        try:
            # Проверка workflow
            workflow = self._entry.workflow
            if workflow is None:
                self.signals.error.emit(pid, tnum, "Workflow не задан")
                return False
            
            self.signals.log.emit(pid, tnum, "[EXEC] Копирование workflow...")
            workflow_copy = AgentWorkflow.from_dict(workflow.to_dict())
            # ═══ Для менеджера проектов: бесконечное выполнение (0 = без лимита) ═══
            # Остановка только по условиям проекта или кнопке "Стоп"
            workflow_copy.max_total_steps = 0
            scene_nodes = {node.id: node for node in workflow_copy.nodes}
            
            # Runtime
            self.signals.log.emit(pid, tnum, "[EXEC] Создание runtime...")
            rt = WorkflowRuntime()
            
            # ═══ КРИТИЧНО: DirectConnection чтобы сигналы доставлялись мгновенно ═══
            # Без этого сигналы ставятся в очередь QThread'а ProjectExecutor,
            # но он сидит в busy-wait (msleep) и НИКОГДА не обрабатывает очередь.
            from PyQt6.QtCore import Qt as _QtConn
            _DC = _QtConn.ConnectionType.DirectConnection
            
            rt.signals.log.connect(
                lambda msg, p=pid, t=tnum: self.signals.log.emit(p, t, msg), _DC)
            rt.signals.node_started.connect(
                lambda nid, name, p=pid, t=tnum: self.signals.node_started.emit(p, t, nid, name), _DC)
            rt.signals.node_finished.connect(
                lambda nid, name, ok, prev, p=pid, t=tnum: self.signals.node_finished.emit(p, t, nid, ok), _DC)
            rt.signals.error.connect(
                lambda nid, err, p=pid, t=tnum: self.signals.error.emit(p, t, f"[{nid}] {err}"), _DC)
            rt.signals.progress.connect(
                lambda cur, tot, p=pid, t=tnum: self.signals.progress.emit(p, t, cur, tot), _DC)
            
            # Переменные
            project_vars = {}
            if hasattr(self._entry, 'input_settings') and self._entry.input_settings:
                project_vars.update(self._entry.input_settings.get('variables', {}))
                # Восстанавливаем global_variables в metadata workflow
                restored_gvars = self._entry.input_settings.get('_restored_global_variables', [])
                if restored_gvars and workflow_copy is not None:
                    try:
                        meta = getattr(workflow_copy, 'metadata', None) or {}
                        if isinstance(meta, str):
                            import json as _jmeta
                            meta = _jmeta.loads(meta) if meta.strip() else {}
                        if not meta.get('global_variables'):
                            meta['global_variables'] = restored_gvars
                        workflow_copy.metadata = meta
                    except Exception as _e:
                        self.signals.log.emit(pid, tnum, f"⚠ Восстановление global_variables: {_e}")
            
            project_root = workflow_copy.project_root or (str(Path(self._entry.file_path).parent) if self._entry.file_path else "")
            
            # ═══ Инъекция номера потока в контекст для изоляции браузеров ═══
            project_vars["_thread_num"] = str(tnum)
            project_vars["_thread_id"] = f"t{tnum}"
            
            # ═══ Создание/получение ProjectBrowserManager ═══
            browser_manager = None
            browser_tray_callback = None
            self.signals.log.emit(pid, tnum, "[EXEC] Создание браузерного менеджера...")
            try:
                from constructor.browser_module import ProjectBrowserManager, BrowserManager
                
                tab = self._entry.tab_reference
                if tab and hasattr(tab, 'browser_manager'):
                    # Используем общий BrowserManager проекта (из вкладки)
                    browser_manager = tab.browser_manager
                    self.signals.log.emit(pid, tnum,
                        f"🌐 Используем браузер проекта (tab.browser_manager, "
                        f"owned={len(browser_manager._owned_ids)})")
                    
                    # Tray callback из вкладки
                    if hasattr(tab, 'send_browser_to_tray'):
                        browser_tray_callback = tab.send_browser_to_tray
                else:
                    # Нет вкладки — используем ГЛОБАЛЬНЫЙ синглтон BrowserManager
                    # чтобы все потоки/проекты видели браузеры друг друга
                    global_bm = BrowserManager.get()
                    browser_manager = ProjectBrowserManager(
                        self._entry.project_id,
                        global_bm
                    )
                    self.signals.log.emit(pid, tnum,
                        f"🌐 ProjectBrowserManager на глобальном BrowserManager "
                        f"(project={self._entry.project_id})")
            except Exception as e:
                self.signals.log.emit(pid, tnum, f"⚠️ Браузер не создан: {e}")
                browser_manager = None
            
            self._thread_browser_manager = browser_manager
            
            # Конфигурация
            self.signals.log.emit(pid, tnum, "[EXEC] Конфигурация runtime...")
            rt.configure(
                workflow=workflow_copy,
                scene_nodes=scene_nodes,
                model_manager=self._model_manager,
                skill_registry=self._skill_registry,
                project_root=project_root,
                global_tools={},
                global_execution={},
                global_auto={},
                project_variables=project_vars,
                project_browser_manager=browser_manager,
                browser_tray_callback=browser_tray_callback,
            )
            # Передаём lock запуска браузера в runtime
            if self._browser_launch_lock:
                rt._browser_launch_lock = self._browser_launch_lock
            
            # ═══ Запуск + отслеживание результата через DirectConnection ═══
            success_holder = [False]
            summary_holder = [""]
            def on_finished(ok, summary):
                success_holder[0] = ok
                summary_holder[0] = summary
            
            rt.signals.workflow_finished.connect(on_finished, _DC)
            
            self.signals.log.emit(pid, tnum, "[EXEC] Запуск workflow...")
            rt.start()
            
            # Ожидание с таймаутом 30 минут на весь workflow
            max_ms = 30 * 60 * 1000  # 30 минут
            elapsed = 0
            check_interval = 250  # проверяем каждые 250мс
            
            while rt.isRunning():
                if self._stop_requested:
                    self.signals.log.emit(pid, tnum, "[EXEC] Получен сигнал остановки")
                    rt.stop()
                    rt.wait(5000)
                    return False
                
                if self._pause_requested:
                    rt.pause()
                    self._mutex.lock()
                    self._pause_condition.wait(self._mutex, 500)
                    self._mutex.unlock()
                    if not self._stop_requested:
                        rt.resume()
                
                self.msleep(check_interval)
                elapsed += check_interval
                
                # Прогресс каждые 5 секунд
                if elapsed % 5000 < check_interval:
                    self.signals.log.emit(pid, tnum, f"[EXEC] Выполняется... ({elapsed/1000:.0f}s)")
                
                # Глобальный таймаут
                if elapsed > max_ms:
                    self.signals.error.emit(pid, tnum, "Таймаут выполнения workflow (30 мин)")
                    rt.stop()
                    rt.wait(5000)
                    return False
            
            # ═══ FALLBACK: если DirectConnection сработал — success_holder уже обновлён.
            # Если нет — читаем результат напрямую из runtime. ═══
            if not success_holder[0] and not summary_holder[0]:
                # Сигнал мог не дойти — проверяем внутреннее состояние runtime
                results = getattr(rt, '_results', {})
                has_errors = any(r.status == "error" for r in results.values())
                has_success = any(r.status == "success" for r in results.values())
                if has_success and not has_errors:
                    success_holder[0] = True
                    self.signals.log.emit(pid, tnum, "[EXEC] Результат определён из runtime._results (fallback)")
            
            self.signals.log.emit(pid, tnum,
                f"[EXEC] Завершено: {'Успех' if success_holder[0] else 'Ошибка'}"
                f" | {summary_holder[0][:100]}")
            return success_holder[0]
            
        except Exception as e:
            import traceback
            self.signals.error.emit(pid, tnum, f"Критическая ошибка: {str(e)[:200]}")
            print(f"[ProjectExecutor] Ошибка в потоке {tnum}: {traceback.format_exc()}")
            return False
        
# ══════════════════════════════════════════════════════════
#  PROJECT EXECUTION MANAGER — центральный диспетчер
# ══════════════════════════════════════════════════════════

class ManagerSignals(QObject):
    """Сигналы от менеджера проектов для UI."""
    project_added    = pyqtSignal(str)           # project_id
    project_removed  = pyqtSignal(str)           # project_id
    project_updated  = pyqtSignal(str)           # project_id (любое изменение)
    project_started  = pyqtSignal(str)           # project_id
    project_stopped  = pyqtSignal(str)           # project_id
    project_finished = pyqtSignal(str, bool)     # (project_id, success)
    stats_updated    = pyqtSignal(int, int)       # (active_threads, max_threads)
    log              = pyqtSignal(str, str)        # (project_id, message)
    global_log       = pyqtSignal(str)             # message


class ProjectExecutionManager(QObject):
    """
    Синглтон — центральный диспетчер всех проектов.
    
    Управляет:
    - Реестром проектов (ProjectEntry)
    - Глобальным лимитом потоков
    - Семафорами моделей (из GlobalSettings)
    - Семафорами узких мест (bottleneck snippets)
    - Расписанием
    - Статистикой
    """
    _instance: Optional['ProjectExecutionManager'] = None
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = ManagerSignals()
        
        # Реестр проектов
        self._projects: dict[str, ProjectEntry] = {}
        
        # Глобальные лимиты
        self._max_global_threads = 10
        self._global_semaphore = threading.Semaphore(self._max_global_threads)
        
        # Семафоры моделей: {model_id: Semaphore}
        self._model_semaphores: dict[str, threading.Semaphore] = {}
        
        # Семафоры bottleneck сниппетов: {snippet_id: Semaphore}
        self._bottleneck_semaphores: dict[str, threading.Semaphore] = {}
        
        # Активные потоки: {project_id: [ProjectExecutor, ...]}
        self._active_executors: dict[str, list[ProjectExecutor]] = {}
        
        # Ссылки на внешние ресурсы
        self._model_manager = None
        self._skill_registry = None
        
        # Планировщик
        self._scheduler_timer = QTimer(self)
        self._scheduler_timer.timeout.connect(self._check_schedule)
        self._scheduler_timer.start(10000)  # Каждые 10 секунд
        
        # Статистика
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(1000)
        
        # Мьютекс для потокобезопасности
        self._lock = threading.Lock()
        
        # Lock'и для синхронизации запуска браузера по проектам
        self._browser_launch_locks: dict[str, threading.Lock] = {}
        
        self._load_settings()
    
    @classmethod
    def instance(cls, parent=None) -> 'ProjectExecutionManager':
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance
    
    # ── Настройки ────────────────────────────────────────────
    
    def _load_settings(self):
        """Загрузить настройки из GlobalSettings."""
        try:
            # Импортируем GlobalSettings из agent_constructor
            # (или из отдельного модуля если вынесен)
            from constructor.agent_constructor import GlobalSettings
            s = GlobalSettings.get()
            self._max_global_threads = s.get("max_global_threads", 10)
            self._global_semaphore = threading.Semaphore(self._max_global_threads)
            
            # Семафоры моделей
            model_sems = s.get("model_semaphores", {})
            model_modes = s.get("model_exec_mode", {})
            for mid, limit in model_sems.items():
                mode = model_modes.get(mid, "parallel")
                n = 1 if mode == "sequential" else max(1, limit)
                self._model_semaphores[mid] = threading.Semaphore(n)
        except Exception:
            pass
    
    def update_global_settings(self, max_threads: int = None,
                                model_semaphores: dict = None,
                                model_modes: dict = None):
        """Обновить глобальные настройки (из UI)."""
        with self._lock:
            if max_threads is not None:
                self._max_global_threads = max_threads
                self._global_semaphore = threading.Semaphore(max_threads)
            
            if model_semaphores:
                for mid, limit in model_semaphores.items():
                    mode = (model_modes or {}).get(mid, "parallel")
                    n = 1 if mode == "sequential" else max(1, limit)
                    self._model_semaphores[mid] = threading.Semaphore(n)
    
    def set_services(self, model_manager, skill_registry):
        """Установить ссылки на внешние сервисы."""
        self._model_manager = model_manager
        self._skill_registry = skill_registry
    
    # ── CRUD проектов ────────────────────────────────────────
    
    def add_project(self, entry: ProjectEntry) -> str:
        """Добавить проект в менеджер."""
        with self._lock:
            self._projects[entry.project_id] = entry
            self._active_executors[entry.project_id] = []
            
            # Создаём bottleneck семафор если задан
            if entry.bottleneck_snippet_id:
                if entry.bottleneck_snippet_id not in self._bottleneck_semaphores:
                    self._bottleneck_semaphores[entry.bottleneck_snippet_id] = \
                        threading.Semaphore(entry.bottleneck_max_concurrent)
        
        self.signals.project_added.emit(entry.project_id)
        self.signals.global_log.emit(f"➕ Проект добавлен: {entry.name}")
        return entry.project_id
    
    def remove_project(self, project_id: str):
        """Удалить проект (остановить если запущен)."""
        self.stop_project(project_id)
        with self._lock:
            self._projects.pop(project_id, None)
            self._active_executors.pop(project_id, None)
        self.signals.project_removed.emit(project_id)
    
    def get_project(self, project_id: str) -> ProjectEntry | None:
        return self._projects.get(project_id)
    
    def get_all_projects(self) -> list[ProjectEntry]:
        return list(self._projects.values())
    
    def get_projects_by_status(self, status: ProjectStatus) -> list[ProjectEntry]:
        return [p for p in self._projects.values() if p.status == status]
    
    def get_projects_by_label(self, label: str) -> list[ProjectEntry]:
        return [p for p in self._projects.values() if label in p.labels]
    
    # ── Управление выполнением ───────────────────────────────
    
    def start_project(self, project_id: str):
        """Запустить проект с учётом его настроек потоков."""
        entry = self._projects.get(project_id)
        if not entry:
            return
        
        if entry.status == ProjectStatus.RUNNING:
            self.signals.global_log.emit(f"⚠️ Проект {entry.name} уже запущен")
            return
        
        if not self._model_manager:
            self.signals.global_log.emit("❌ Модель AI не настроена")
            return
        
        # ═══ ИСПРАВЛЕНИЕ: сбрасываем счётчики при повторном запуске ═══
        entry.total_attempts = 0
        entry.completed_executions = 0
        entry.failed_executions = 0
        entry.consecutive_failures = 0
        entry.current_threads = 0
        
        # ═══ ИСПРАВЛЕНИЕ: очищаем список завершённых executor'ов ═══
        with self._lock:
            old_executors = self._active_executors.get(project_id, [])
            # Ждём завершения зависших потоков
            for ex in old_executors:
                if ex.isRunning():
                    ex.stop()
                    ex.wait(2000)
            self._active_executors[project_id] = []
        
        entry.status = ProjectStatus.RUNNING
        entry.started_at = datetime.now().isoformat()
        self.signals.project_started.emit(project_id)
        self.signals.project_updated.emit(project_id)
        
        # ═══ Общий lock для синхронизации запуска браузера между потоками проекта ═══
        self._browser_launch_locks[project_id] = threading.Lock()
        
        # Запускаем потоки согласно настройкам
        threads_to_launch = entry.max_threads
        
        for t_num in range(1, threads_to_launch + 1):
            self._launch_executor(entry, t_num)
    
    def _launch_executor(self, entry: ProjectEntry, thread_num: int):
        """Создать и запустить один executor."""
        # Проверяем: нужно ли ещё запускать?
        if entry.total_executions != -1 and entry.total_attempts >= entry.total_executions:
            self._check_project_completion(entry)
            return
        
        if entry.status != ProjectStatus.RUNNING:
            return
        
        # ═══ ЗАЩИТА ОТ ФАНТОМНЫХ ПОТОКОВ ═══
        # Проверяем, не запущен ли уже executor с таким номером
        with self._lock:
            existing = self._active_executors.get(entry.project_id, [])
            for ex in existing:
                if hasattr(ex, '_thread_num') and ex._thread_num == thread_num and ex.isRunning():
                    self.signals.log.emit(entry.project_id, 
                        f"⚠️ Поток #{thread_num} уже запущен, пропускаем дублирующий запуск")
                    return
        
        # Проверяем условия остановки
        if self._check_stop_condition(entry):
            self._finish_project(entry, True)
            return
        
        # Bottleneck семафор
        bn_sem = None
        if entry.bottleneck_snippet_id:
            bn_sem = self._bottleneck_semaphores.get(entry.bottleneck_snippet_id)
        
        executor = ProjectExecutor(
            entry=entry,
            thread_num=thread_num,
            model_manager=self._model_manager,
            skill_registry=self._skill_registry,
            global_semaphore=self._global_semaphore,
            model_semaphores=self._model_semaphores,
            bottleneck_semaphore=bn_sem,
            browser_launch_lock=self._browser_launch_locks.get(entry.project_id),
        )
        
        # Подключаем сигналы
        executor.signals.started.connect(self._on_executor_started)
        executor.signals.finished.connect(self._on_executor_finished)
        executor.signals.log.connect(self._on_executor_log)
        executor.signals.error.connect(self._on_executor_error)
        executor.signals.progress.connect(self._on_executor_progress)
        executor.signals.node_started.connect(self._on_executor_node_started)
        executor.signals.node_finished.connect(self._on_executor_node_finished)
        
        with self._lock:
            self._active_executors.setdefault(entry.project_id, []).append(executor)
            entry.current_threads += 1
        
        # ═══ ИСПРАВЛЕНИЕ: принудительно отключаем анимацию при запуске через менеджер ═══
        if entry.tab_reference and hasattr(entry.tab_reference, '_deferred_rendering'):
            entry.tab_reference._deferred_rendering = True
        
        executor.start()
        entry.total_attempts += 1
    
    def stop_project(self, project_id: str):
        """Остановить все потоки проекта."""
        entry = self._projects.get(project_id)
        if not entry:
            return
        
        with self._lock:
            executors = self._active_executors.get(project_id, [])
            for ex in executors:
                ex.stop()
        
        entry.status = ProjectStatus.STOPPED
        self.signals.project_stopped.emit(project_id)
        self.signals.project_updated.emit(project_id)
    
    def pause_project(self, project_id: str):
        """Приостановить проект."""
        entry = self._projects.get(project_id)
        if not entry or entry.status != ProjectStatus.RUNNING:
            return
        
        with self._lock:
            for ex in self._active_executors.get(project_id, []):
                ex.pause()
        
        entry.status = ProjectStatus.PAUSED
        self.signals.project_updated.emit(project_id)
    
    def resume_project(self, project_id: str):
        """Возобновить проект."""
        entry = self._projects.get(project_id)
        if not entry or entry.status != ProjectStatus.PAUSED:
            return
        
        with self._lock:
            for ex in self._active_executors.get(project_id, []):
                ex.resume()
        
        entry.status = ProjectStatus.RUNNING
        self.signals.project_updated.emit(project_id)
    
    def add_executions(self, project_id: str, count: int):
        """Добавить попытки к проекту (как кнопка +N в ZennoPoster)."""
        entry = self._projects.get(project_id)
        if not entry:
            return
        
        if count == -1:
            entry.total_executions = -1  # Бесконечно
        else:
            if entry.total_executions == -1:
                entry.total_executions = count
            else:
                entry.total_executions += count
        
        entry.consecutive_failures = 0  # Сброс счётчика неуспехов
        self.signals.project_updated.emit(project_id)
        
        # Если проект был завершён — можно перезапустить
        if entry.status == ProjectStatus.COMPLETED:
            entry.status = ProjectStatus.STOPPED
            self.signals.project_updated.emit(project_id)
    
    def set_project_threads(self, project_id: str, max_threads: int):
        """Изменить количество потоков проекта на лету."""
        entry = self._projects.get(project_id)
        if not entry:
            return
        entry.max_threads = max(1, max_threads)
        self.signals.project_updated.emit(project_id)
    
    # ── Обработчики сигналов executor'ов ─────────────────────
    
    def _on_executor_started(self, project_id: str, thread_num: int):
        self.signals.log.emit(project_id, f"▶️ Поток #{thread_num} запущен")
    
    def _on_executor_finished(self, project_id: str, thread_num: int, success: bool, summary: str):
        entry = self._projects.get(project_id)
        if not entry:
            return
        
        with self._lock:
            entry.current_threads = max(0, entry.current_threads - 1)
            entry.last_run_at = datetime.now().isoformat()
            
            if success:
                entry.completed_executions += 1
                entry.consecutive_failures = 0
            else:
                entry.failed_executions += 1
                entry.consecutive_failures += 1
            
            # Убираем executor из списка активных
            executors = self._active_executors.get(project_id, [])
            self._active_executors[project_id] = [
                ex for ex in executors if ex.isRunning()
            ]
        
        self.signals.project_updated.emit(project_id)
        
        # Проверяем нужно ли запустить ещё потоки
        if entry.status == ProjectStatus.RUNNING:
            if not self._check_stop_condition(entry):
                if entry.total_executions == -1 or entry.total_attempts < entry.total_executions:
                    # Автоматически запускаем следующую попытку в этом потоке
                    QTimer.singleShot(100, lambda p=entry, t=thread_num: self._launch_executor(p, t))
                else:
                    self._check_project_completion(entry)
            else:
                self._finish_project(entry, True)
    
    def _on_executor_log(self, project_id: str, thread_num: int, message: str):
        self.signals.log.emit(project_id, f"[T{thread_num}] {message}")
    
    def _on_executor_error(self, project_id: str, thread_num: int, error_msg: str):
        self.signals.log.emit(project_id, f"❌ [T{thread_num}] {error_msg}")
    
    def _on_executor_progress(self, project_id: str, thread_num: int, current: int, total: int):
        self.signals.project_updated.emit(project_id)
    
    def _on_executor_node_started(self, project_id: str, thread_num: int, node_id: str, node_name: str):
        pass  # Можно добавить визуализацию
    
    def _on_executor_node_finished(self, project_id: str, thread_num: int, node_id: str, success: bool):
        pass
    
    # ── Проверки ─────────────────────────────────────────────
    
    def _check_stop_condition(self, entry: ProjectEntry) -> bool:
        """Проверить условие остановки."""
        if entry.stop_condition == StopCondition.NONE:
            return False
        if entry.stop_condition == StopCondition.ON_FIRST_ERROR:
            return entry.consecutive_failures >= 1
        if entry.stop_condition == StopCondition.ON_N_ERRORS:
            # stop_value=0 означает "не задано" (иначе остановится сразу)
            return entry.stop_value > 0 and entry.consecutive_failures >= entry.stop_value
        if entry.stop_condition == StopCondition.ON_SUCCESS_COUNT:
            return entry.stop_value > 0 and entry.completed_executions >= entry.stop_value
        if entry.stop_condition == StopCondition.ON_TIME_LIMIT:
            if entry.started_at and entry.stop_value > 0:
                started = datetime.fromisoformat(entry.started_at)
                return (datetime.now() - started).total_seconds() >= entry.stop_value
        return False
    
    def _check_project_completion(self, entry: ProjectEntry):
        """Проверить завершены ли все попытки."""
        if entry.total_executions == -1:
            return  # Бесконечное выполнение
        
        if entry.total_attempts >= entry.total_executions and entry.current_threads == 0:
            self._finish_project(entry, True)
    
    def _finish_project(self, entry: ProjectEntry, normal: bool):
        """Завершить проект."""
        entry.status = ProjectStatus.COMPLETED
        self.signals.project_finished.emit(entry.project_id, normal)
        self.signals.project_updated.emit(entry.project_id)
        self.signals.global_log.emit(
            f"✅ Проект {entry.name} завершён: "
            f"{entry.completed_executions} успехов, {entry.failed_executions} ошибок"
        )
    
    # ── Расписание ───────────────────────────────────────────
    
    def _check_schedule(self):
        """Проверяет расписание каждые 10 секунд."""
        now = datetime.now()
        for entry in self._projects.values():
            if not entry.schedule_enabled:
                continue
            if entry.status == ProjectStatus.RUNNING:
                continue
            if entry.schedule_next_run:
                try:
                    next_run = datetime.fromisoformat(entry.schedule_next_run)
                    if now >= next_run:
                        self.signals.global_log.emit(
                            f"📅 Запуск по расписанию: {entry.name}"
                        )
                        self.start_project(entry.project_id)
                        
                        if entry.schedule_repeat:
                            # Рассчитываем следующий запуск
                            entry.schedule_next_run = self._calc_next_run(
                                entry.schedule_cron
                            )
                        else:
                            entry.schedule_enabled = False
                except ValueError:
                    pass
    
    @staticmethod
    def _calc_next_run(cron_expr: str) -> str:
        """Простой расчёт следующего запуска."""
        now = datetime.now()
        try:
            if ":" in cron_expr:
                # Формат HH:MM — каждый день в указанное время
                h, m = map(int, cron_expr.split(":"))
                next_run = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                return next_run.isoformat()
            elif cron_expr.startswith("*/"):
                # Формат */N — каждые N минут
                interval = int(cron_expr[2:])
                next_run = now + timedelta(minutes=interval)
                return next_run.isoformat()
        except Exception:
            pass
        return (now + timedelta(hours=1)).isoformat()
    
    # ── Статистика ───────────────────────────────────────────
    
    def _update_stats(self):
        """Обновление статистики для UI."""
        total_active = sum(
            len([ex for ex in exs if ex.isRunning()])
            for exs in self._active_executors.values()
        )
        self.signals.stats_updated.emit(total_active, self._max_global_threads)
    
    @property
    def active_thread_count(self) -> int:
        return sum(
            len([ex for ex in exs if ex.isRunning()])
            for exs in self._active_executors.values()
        )
    
    # ── Сериализация ─────────────────────────────────────────
    
    def save_state(self, path: str = ""):
        """Сохранить состояние менеджера."""
        if not path:
            path = str(Path.home() / ".sherlock" / "project_manager_state.json")
        data = {
            "projects": [p.to_dict() for p in self._projects.values()],
            "max_global_threads": self._max_global_threads,
            "model_semaphores": {k: v._value for k, v in self._model_semaphores.items()},
        }
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"⚠ Ошибка сохранения состояния менеджера: {e}")
    
    def load_state(self, path: str = ""):
        """Загрузить сохранённое состояние."""
        if not path:
            path = str(Path.home() / ".sherlock" / "project_manager_state.json")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for pd in data.get("projects", []):
                entry = ProjectEntry.from_dict(pd)
                entry.status = ProjectStatus.STOPPED  # Сброс при загрузке
                entry.current_threads = 0
                self._projects[entry.project_id] = entry
                self._active_executors[entry.project_id] = []
            self._max_global_threads = data.get("max_global_threads", 10)
            self._global_semaphore = threading.Semaphore(self._max_global_threads)
        except Exception:
            pass
