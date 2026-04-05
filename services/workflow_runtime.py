"""
Workflow Runtime Engine — executes AI agent graphs from the Constructor.

Architecture:
  - Runs in QThread to keep UI responsive
  - Communicates via pyqtSignals (node_started, node_finished, log, error, etc.)
  - Executes agents by calling AI models via ModelManager
  - Passes context between nodes through shared execution_context dict
  - Supports: sequential, parallel, conditional, LLM-router orchestration
  - Supports: breakpoints, auto-test, auto-patch, auto-improve, retries
  - Tool execution: file_read, file_write, shell_exec, code_execute, patch_apply
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import traceback
import time
from datetime import datetime
from pathlib import Path
import tempfile
from typing import Optional, Any

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QMutex, QWaitCondition

# ── Imports from project ──────────────────────────────────────

try:
    from core.models import ChatMessage, MessageRole
except ImportError:
    # Fallback
    from dataclasses import dataclass, field
    from enum import Enum
    class MessageRole(Enum):
        SYSTEM = "system"
        USER = "user"
        ASSISTANT = "assistant"
    @dataclass
    class ChatMessage:
        role: MessageRole
        content: str

try:
    from services.agent_models import AgentNode, AgentEdge, AgentWorkflow, AgentType, EdgeCondition
except ImportError:
    class EdgeCondition:
        ALWAYS = "always"
        ON_SUCCESS = "on_success"
        ON_FAILURE = "on_failure"


# ══════════════════════════════════════════════════════════
#  NODE EXECUTION RESULT
# ══════════════════════════════════════════════════════════

class NodeResult:
    """Result of executing a single node."""
    __slots__ = ('node_id', 'node_name', 'status', 'output', 'error',
                 'duration_ms', 'attempt', 'timestamp')

    def __init__(self, node_id: str, node_name: str):
        self.node_id = node_id
        self.node_name = node_name
        self.status: str = "pending"       # pending | running | success | error | skipped
        self.output: str = ""              # AI response text
        self.error: str = ""               # error message if failed
        self.duration_ms: int = 0
        self.attempt: int = 1
        self.timestamp: str = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ══════════════════════════════════════════════════════════
#  TOOL EXECUTOR
# ══════════════════════════════════════════════════════════

class ToolExecutor:
    """Executes tools available to agents (file ops, shell, code, etc.)."""

    def __init__(self, project_root: str = "", logger=None):
        self._root = project_root or os.getcwd()
        self._log = logger or print

    def set_root(self, root: str):
        self._root = root

    def set_configs(self, configs: dict):
        """Применить детальные настройки для tools"""
        self._configs = configs
    
    @staticmethod
    def _sanitize_path(path: str) -> str:
        """Превращает любой путь в безопасный относительный.
        
        '/path/to/project/my_project/src/main.py' → 'src/main.py'
        'C:\\Users\\user\\project\\main.py'        → 'main.py'
        'project_directory/scripts/test.py'        → 'scripts/test.py'
        """
        if not path:
            return path
        # Нормализуем слеши
        path = path.replace('\\', '/')
        # Убираем абсолютный путь: /path/to/... или C:/Users/...
        if path.startswith('/') or (len(path) > 2 and path[1] == ':'):
            parts = path.split('/')
            # Ищем первую часть которая похожа на файл проекта (содержит расширение)
            # или является известной директорией проекта
            project_dirs = {'src', 'lib', 'scripts', 'data', 'tests', 'test', 'db',
                           'database', 'config', 'configs', 'docs', 'static', 'templates',
                           'utils', 'code', 'app', 'api', 'models', 'views', 'routes',
                           'services', 'helpers', 'logs', 'assets', 'public', 'dist', 'build'}
            best_start = len(parts)  # по умолчанию — последний элемент
            for i, part in enumerate(parts):
                if part.lower() in project_dirs or '.' in part:
                    best_start = i
                    break
                # Если часть содержит "_project" или "project" или "__init__" — берём следующую
                if 'project' in part.lower() or part == 'my_project':
                    best_start = i + 1
                    continue
            path = '/'.join(parts[best_start:]) if best_start < len(parts) else parts[-1]
        # Убираем лидирующие ./
        while path.startswith('./'):
            path = path[2:]
        # Убираем общий корень проекта (одиночная папка-обёртка)
        parts = path.split('/')
        if len(parts) > 1 and '.' not in parts[0]:
            # Если первая часть — обёртка без расширения, и НЕ является src/lib/data/etc
            known_keep = {'src', 'lib', 'scripts', 'data', 'tests', 'test', 'db',
                         'database', 'config', 'configs', 'docs', 'static', 'templates',
                         'utils', 'code', 'app', 'api', 'models', 'views', 'routes',
                         'services', 'helpers', 'logs', 'assets', 'public', 'dist', 'build'}
            if parts[0].lower() not in known_keep:
                path = '/'.join(parts[1:])
        return path or 'unnamed_file'
    
    async def execute_tool(self, tool_id: str, params: dict) -> dict:
        """Execute a tool and return result dict."""
        handlers = {
            "file_read":      self._tool_file_read,
            "file_write":     self._tool_file_write,
            "shell_exec":     self._tool_shell_exec,
            "code_execute":   self._tool_code_execute,
            "patch_apply":    self._tool_patch_apply,
            "browser_navigate": self._tool_stub,
            "browser_click":    self._tool_stub,
            "browser_screenshot": self._tool_stub,
            "image_generate":   self._tool_stub,
        }
        handler = handlers.get(tool_id, self._tool_stub)
        
        # === ПРИМЕНЕНИЕ КОНФИГУРАЦИИ ===
        config = self._configs.get(tool_id, {})
        
        # Проверка ограничений перед выполнением
        if tool_id == "file_write":
            if config.get("params", {}).get("backup_before_write"):
                # Создаем бэкап перед записью если файл существует
                full_path = os.path.join(self._root, params.get("path", ""))
                if os.path.exists(full_path):
                    backup_path = full_path + ".backup"
                    try:
                        import shutil
                        shutil.copy2(full_path, backup_path)
                        self._log(f"  💾 Бэкап создан: {backup_path}")
                    except Exception as e:
                        self._log(f"  ⚠ Не удалось создать бэкап: {e}")
        
        if tool_id == "shell_exec":
            if config.get("params", {}).get("work_dir_restricted"):
                # Принудительно ограничиваем рабочей директорией
                params["command"] = f"cd {self._root} && " + params.get("command", "")
        
        try:
            return await handler(params)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_file_read(self, params: dict) -> dict:
        path = params.get("path", "")
        path = self._sanitize_path(path)
        full = os.path.join(self._root, path)
        if not os.path.isfile(full):
            return {"success": False, "error": f"File not found: {full}"}
        content = Path(full).read_text(encoding="utf-8", errors="replace")
        self._log(f"📖 Прочитан: {path} ({len(content)} символов)")
        return {"success": True, "content": content, "path": full}

    async def _tool_file_write(self, params: dict) -> dict:
        path = params.get("path", "")
        content = params.get("content", "")
        # ПРИНУДИТЕЛЬНО делаем путь относительным — НИКОГДА не пишем по абсолютному
        path = self._sanitize_path(path)
        full = os.path.join(self._root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        Path(full).write_text(content, encoding="utf-8")
        self._log(f"✏️ Записан: {path} ({len(content)} символов)")
        return {"success": True, "path": full, "bytes_written": len(content)}

    async def _tool_shell_exec(self, params: dict) -> dict:
        cmd = params.get("command", "")
        timeout = params.get("timeout", 30)
        # Используем cwd из params если есть, иначе self._root если существует
        _cwd = params.get("cwd") or self._root
        if _cwd and not os.path.exists(_cwd):
            _cwd = None  # не падать если папка не существует
        self._log(f"💻 Shell: {cmd[:80]}")
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=_cwd
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-2000:],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Timeout ({timeout}s)"}

    async def _tool_code_execute(self, params: dict) -> dict:
        code = params.get("code", "")
        self._log(f"⚙️ Выполняю Python ({len(code)} символов)")
        tmp_path = os.path.join(self._root, "__runtime_tmp__.py")
        try:
            Path(tmp_path).write_text(code, encoding="utf-8")
            result = await self._tool_shell_exec({
                "command": f'python "{tmp_path}"', "timeout": 60
            })
            return result
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def _tool_patch_apply(self, params: dict) -> dict:
        """Apply SEARCH/REPLACE patch to a file."""
        path = params.get("path", "")
        search = params.get("search", "")
        replace = params.get("replace", "")
        full = os.path.join(self._root, path) if not os.path.isabs(path) else path
        if not os.path.isfile(full):
            return {"success": False, "error": f"File not found: {full}"}
        content = Path(full).read_text(encoding="utf-8")
        if search not in content:
            return {"success": False, "error": "Search string not found"}
        new_content = content.replace(search, replace, 1)
        Path(full).write_text(new_content, encoding="utf-8")
        self._log(f"🔧 Патч применён: {path}")
        return {"success": True, "path": full}

    async def _tool_stub(self, params: dict) -> dict:
        return {"success": False, "error": "Tool not yet implemented"}


# ══════════════════════════════════════════════════════════
#  RUNTIME SIGNALS
# ══════════════════════════════════════════════════════════

class RuntimeSignals(QObject):
    """Signals emitted by the runtime engine for UI updates."""
    # Workflow lifecycle
    workflow_started  = pyqtSignal()                    # workflow execution began
    workflow_finished = pyqtSignal(bool, str)            # (success, summary)

    # Node lifecycle
    node_started      = pyqtSignal(str, str)             # (node_id, node_name)
    node_finished     = pyqtSignal(str, str, bool, str)   # (node_id, node_name, success, output_preview)
    node_streaming    = pyqtSignal(str, str)              # (node_id, chunk)

    # Execution control
    breakpoint_hit    = pyqtSignal(str, str)              # (node_id, node_name) — pause for user
    waiting_input     = pyqtSignal(str, str)              # (node_id, prompt) — human in loop

    # Logging
    log               = pyqtSignal(str)                   # log message for the panel
    progress          = pyqtSignal(int, int)              # (current_step, total_steps)
    error             = pyqtSignal(str, str)              # (node_id, error_message)
    variable_updated  = pyqtSignal(str, str)              # (var_name, value)
    list_table_updated = pyqtSignal(str, str, int)         # (kind='list'|'table', name, count)


# ══════════════════════════════════════════════════════════
#  WORKFLOW RUNTIME ENGINE
# ══════════════════════════════════════════════════════════

class WorkflowRuntime(QThread):
    """
    Professional workflow execution engine.
    Runs in a QThread, communicates via RuntimeSignals.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = RuntimeSignals()
        self._isolated_mode = parent is None  # True если запущен из ProjectExecutor

        # External services (set before start)
        self._model_manager = None
        self._skill_registry = None
        self._tool_executor = ToolExecutor()

        # Workflow data (set before start)
        self._scene_nodes: dict[str, Any] = {}   # node_id -> AgentNode (from scene)
        self._workflow: AgentWorkflow | None = None

        # Global settings from UI tabs
        self._global_tools: dict[str, bool] = {}
        self._global_execution: dict = {}
        self._global_auto: dict = {}
        self._global_models: dict = {}

        # Execution state
        self._results: dict[str, NodeResult] = {}
        self._context: dict[str, Any] = {}         # shared context passed between nodes
        self.execution_context = self._context     # для Browser Agent
        self.execution_path: list[str] = []        # ← ДОБАВИТЬ: путь выполнения узлов
        self._is_running = False
        self._is_paused = False
        self._stop_requested = False
        
        # Breakpoint / step support
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
        self._human_response: str = ""
    
    def _build_task_context(self, current_node: AgentNode) -> str:
        """Собирает контекст из предыдущих узлов для передачи текущему"""
        context_parts = []
        
        # 1. Глобальная цель (если есть)
        if "global_goal" in self._context:
            context_parts.append(f"🎯 ГЛОБАЛЬНАЯ ЦЕЛЬ: {self._context['global_goal']}")
        
        # 2. ПОЛНЫЙ вывод предыдущего агента (не truncated!) для Code Writer
        if current_node.agent_type.value == "code_writer" and len(self._results) > 0:
            # Найти вывод Planner или предыдущего агента
            for node_id, res in self._results.items():
                if res.status == "success" and res.output:
                    # Для Code Writer даем ПОЛНЫЙ контекст планирования
                    full_output = res.output
                    context_parts.append(f"📋 ПОЛНЫЙ ПЛАН ОТ {res.node_name} (следуй строго):\n{full_output}\n\n⚠️ ВАЖНО: Создай ВСЕ файлы из структуры выше, не только один!")
                    break
        
        # 2b. Контекст для Script Runner: реальные файлы + ошибки
        if current_node.agent_type.value == "script_runner":
            # Сканируем РЕАЛЬНЫЕ файлы на диске
            disk_files = []
            try:
                root = self._tool_executor._root
                for dir_path, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for f in files:
                        rel = os.path.relpath(os.path.join(dir_path, f), root)
                        disk_files.append(rel)
            except Exception:
                pass
            
            if disk_files:
                context_parts.append(f"📁 ФАЙЛЫ НА ДИСКЕ ({len(disk_files)}):\n" + "\n".join(f"  - {f}" for f in disk_files[:30]))
            else:
                context_parts.append("⚠️ НА ДИСКЕ НЕТ ФАЙЛОВ! Code Writer не создал ничего.")
            
            # Передаем ошибки предыдущего теста
            if "_script_error" in self._context:
                context_parts.append(
                    f"⚠️ ПРЕДЫДУЩАЯ ОШИБКА ТЕСТА:\n{self._context['_script_error']}"
                )
            
            # Передаем вывод предыдущего агента
            for node_id, res in self._results.items():
                if res.status == "success" and res.output:
                    context_parts.append(
                        f"📋 ВЫВОД ОТ {res.node_name}:\n{res.output[:3000]}"
                    )
        # 2c. Контекст для Patcher: ошибки + исходный код файлов
        if current_node.agent_type.value == "patcher":
            if "_script_error" in self._context:
                context_parts.append(
                    f"🚨 ОШИБКА ВЫПОЛНЕНИЯ СКРИПТА:\n{self._context['_script_error']}"
                )
            # Даём содержимое файлов с ошибками
            error_files = self._context.get("_error_file_contents", {})
            if error_files:
                for fname, content in error_files.items():
                    context_parts.append(
                        f"📄 ФАЙЛ {fname}:\n```\n{content[:3000]}\n```"
                    )
            else:
                # Если нет конкретных файлов — даём все .py файлы
                disk_files = self._scan_disk_files()
                py_files = [f for f in disk_files if f.endswith('.py')]
                for pf in py_files[:8]:
                    try:
                        full = os.path.join(self._tool_executor._root, pf)
                        content = Path(full).read_text(encoding='utf-8', errors='replace')
                        context_parts.append(f"📄 {pf}:\n```\n{content[:2000]}\n```")
                    except Exception:
                        pass
            
            # Список всех файлов проекта
            disk_files = self._scan_disk_files()
            context_parts.append(f"📁 ФАЙЛЫ НА ДИСКЕ: {', '.join(disk_files[:30])}")
            # Найти вывод Planner или предыдущего агента
            for node_id, res in self._results.items():
                if res.status == "success" and res.output:
                    # Для Code Writer даем ПОЛНЫЙ контекст планирования
                    full_output = res.output
                    context_parts.append(f"📋 ПОЛНЫЙ ПЛАН ОТ {res.node_name} (следуй строго):\n{full_output}\n\n⚠️ ВАЖНО: Создай ВСЕ файлы из структуры выше, не только один!")
                    break
        
        # 3. История выполнения (последние 3 шага) - кратко
        history = []
        for node_id, res in list(self._results.items())[-3:]:
            if res.status == "success":
                preview = res.output[:200].replace("\n", " ")
                history.append(f"- {res.node_name}: {preview}...")
        if history:
            context_parts.append("📜 ИСТОРИЯ ВЫПОЛНЕНИЯ:\n" + "\n".join(history))
        
        # 4. Ошибки предыдущих попыток (для отладки)
        errors = [r.error for r in self._results.values() if r.error]
        if errors and current_node.agent_type.value in ["code_writer", "debugger"]:
            context_parts.append("❌ ПРЕДЫДУЩИЕ ОШИБКИ:\n" + "\n".join(f"- {e}" for e in errors[-2:]))
        
        # 5. Файлы созданные ранее
        if "created_files" in self._context:
            files = self._context["created_files"]
            context_parts.append(f"📁 УЖЕ СОЗДАННЫЕ ФАЙЛЫ: {', '.join(files)}")
        
        return "\n\n".join(context_parts)
    
    # ── Configuration (call before start()) ──────────────────

    def configure(self, *,
                  workflow: AgentWorkflow,
                  scene_nodes: dict[str, Any],
                  model_manager,
                  skill_registry=None,
                  project_root: str = "",
                  global_tools: dict = None,
                  global_execution: dict = None,
                  global_auto: dict = None,
                  global_models: dict = None,
                  tool_configs: dict = None,
                  initial_context: dict = None,
                  start_from_node_id: str = "",
                  only_node_ids: list[str] = None,
                  step_mode: bool = False,
                  project_variables: dict = None,
                  update_callback=None,
                  project_browser_manager=None,
                  browser_tray_callback=None):
        """Configure the runtime before calling start()."""
        self.project_browser_manager = project_browser_manager
        self._browser_tray_callback = browser_tray_callback
        self._workflow = workflow
        self._scene_nodes = scene_nodes
        self._model_manager = model_manager
        self._skill_registry = skill_registry
        self._project_root = project_root or ""
        self._tool_executor.set_root(project_root or os.getcwd())
        
        # === НАСТРОЙКА TOOL EXECUTOR ===
        self._tool_configs = tool_configs or {}
        self._tool_executor.set_configs(self._tool_configs)
        
        self._global_tools = global_tools or {}
        self._global_execution = global_execution or {}
        self._global_auto = global_auto or {}
        self._global_models = global_models or {}
        self._context = initial_context or {}
        self._context["_project_browser_manager"] = project_browser_manager
        self._project_browser_manager = project_browser_manager  # ← ДОБАВИТЬ ЭТУ СТРОКУ
        
        # Сохраняем browser_instance_id из предыдущих запусков если есть
        if project_variables and "browser_instance_id" in project_variables:
            self._context["browser_instance_id"] = project_variables["browser_instance_id"]
        # Инъекция переменных проекта в контекст выполнения
        self._project_variables = project_variables  # Сохраняем всегда, даже если None
        
        if project_variables:
            for var_name, var_data in project_variables.items():
                # Очищаем имя переменной от скобок если они есть
                clean_name = var_name.strip('{}').strip()
                if isinstance(var_data, dict):
                    self._context[clean_name] = var_data.get('value', var_data.get('default', ''))
                else:
                    self._context[clean_name] = str(var_data)
                # Также сохраняем под оригинальным именем для совместимости
                if clean_name != var_name:
                    self._context[var_name] = self._context[clean_name]
        
        # Callback для обновления UI
        self._update_callback = update_callback
        # Пути проекта — доступны как {project_dir} и {workflow_dir}
        if self._project_root:
            self._context["project_dir"] = self._project_root
        if hasattr(self, '_workflow_path') and self._workflow_path:
            self._context["workflow_dir"] = os.path.dirname(self._workflow_path)
        self._results = {}
        self._stop_requested = False
        self._is_paused = step_mode  # Если step_mode — сразу пауза перед первым узлом
        
        # Режимы запуска
        self._start_from_node_id = start_from_node_id
        self._only_node_ids = set(only_node_ids) if only_node_ids else None

    # ── Control (thread-safe) ─────────────────────────────────

    def stop(self):
        self._stop_requested = True
        self.resume()  # unblock if paused

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False
        self._pause_condition.wakeAll()

    def provide_human_input(self, text: str):
        """Called from UI when user responds to a human-in-loop prompt."""
        self._human_response = text
        self.resume()

    def _init_project_lists_tables(self):
        """Загрузить проектные списки и таблицы в контекст выполнения."""
        # ═══ ОЧИСТКА СТАРЫХ ДАННЫХ ПЕРЕД ЗАГРУЗКОЙ ═══
        # Удаляем старые списки и таблицы из контекста
        for key in list(self._context.keys()):
            if key.startswith('_project_') or key in ['_project_lists', '_project_tables']:
                del self._context[key]
        
        # Списки/таблицы передаются через project_variables
        pv = self._project_variables or {}
        meta = getattr(self._workflow, 'metadata', {}) or {}
        
        raw_lists = pv.get('_project_lists', meta.get('project_lists', []))
        raw_tables = pv.get('_project_tables', meta.get('project_tables', []))
        
        # ── Списки ──
        proj_lists = {}
        for lst in (raw_lists or []):
            if not isinstance(lst, dict):
                continue
            name = lst.get('name', '')
            if not name:
                continue
            
            load_mode = lst.get('load_mode', 'static')
            
            # ═══ ИСПРАВЛЕНИЕ: static = берем из items, on_start/always = из файла ═══
            if load_mode == 'static':
                # Используем items из конфигурации (могут быть изменены в UI)
                items = list(lst.get('items', []))
            else:
                # on_start или always — загружаем из файла
                items = []
                fp = lst.get('file_path', '')
                if fp:
                    resolved_fp = fp
                    if not os.path.isabs(resolved_fp):
                        resolved_fp = os.path.join(self._tool_executor._root, resolved_fp)
                    if os.path.isfile(resolved_fp):
                        try:
                            enc = lst.get('encoding', 'utf-8') or 'utf-8'
                            with open(resolved_fp, 'r', encoding=enc, errors='replace') as f:
                                items = [line.rstrip('\n\r') for line in f.readlines() if line.strip()]
                            self._log(f"📃 Проектный список '{name}': {len(items)} строк из {os.path.basename(fp)}")
                        except Exception as e:
                            self._log(f"⚠ Ошибка загрузки списка '{name}': {e}")
                            items = []
                    else:
                        self._log(f"⚠ Файл списка не найден: {resolved_fp}")
            
            proj_lists[name] = items
        
        self._context['_project_lists'] = proj_lists
        # Зеркалируем в прямые ключи
        for _name, _items in proj_lists.items():
            if _items:
                self._context[_name] = list(_items)
        
        # ── Таблицы ── (аналогично)
        proj_tables = {}
        for tbl in (raw_tables or []):
            if not isinstance(tbl, dict):
                continue
            name = tbl.get('name', '')
            if not name:
                continue
            
            load_mode = tbl.get('load_mode', 'static')
            
            if load_mode == 'static':
                rows = list(tbl.get('rows', []))
            else:
                rows = []
                fp = tbl.get('file_path', '')
                if fp:
                    resolved_fp = fp
                    if not os.path.isabs(resolved_fp):
                        resolved_fp = os.path.join(self._tool_executor._root, resolved_fp)
                    if os.path.isfile(resolved_fp):
                        try:
                            import csv
                            enc = tbl.get('encoding', 'utf-8') or 'utf-8'
                            with open(resolved_fp, 'r', encoding=enc, errors='replace') as f:
                                reader = csv.reader(f)
                                rows = [row for row in reader]
                            if tbl.get('has_header') and rows:
                                rows = rows[1:]
                            self._log(f"📊 Проектная таблица '{name}': {len(rows)} строк из {os.path.basename(fp)}")
                        except Exception as e:
                            self._log(f"⚠ Ошибка загрузки таблицы '{name}': {e}")
                            rows = []
            
            proj_tables[name] = rows
        
        self._context['_project_tables'] = proj_tables
        for _name, _rows in proj_tables.items():
            if _rows:
                self._context[_name] = list(_rows)
        
        if proj_lists:
            self._log(f"📃 Инициализировано списков: {len(proj_lists)}")
        if proj_tables:
            self._log(f"📊 Инициализировано таблиц: {len(proj_tables)}")

    # ── Main execution loop (runs in QThread) ─────────────────

    def run(self):
        """QThread entry point."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execute())
        except Exception as e:
            self.signals.error.emit("", f"Fatal: {e}\n{traceback.format_exc()}")
            self.signals.workflow_finished.emit(False, f"Фатальная ошибка: {e}")
        finally:
            loop.close()

    async def _execute(self):
        """Main async execution logic."""
        if not self._workflow:
            self.signals.workflow_finished.emit(False, "Workflow не задан")
            return
        if not self._model_manager or not self._model_manager.active_provider:
            self.signals.workflow_finished.emit(False, "Нет активной AI модели. Настройте модель в главном окне.")
            return

        self._is_running = True
        self.signals.workflow_started.emit()
        self._log("🚀 Запуск workflow...")

        # Find entry node
        if self._start_from_node_id and self._start_from_node_id in self._scene_nodes:
            entry = self._scene_nodes[self._start_from_node_id]
            self._log(f"▶ Запуск от выбранного: {entry.name}")
        else:
            entry = self._find_entry_node()
        if not entry:
            self.signals.workflow_finished.emit(False, "Не найдена точка входа (нода без входящих связей)")
            return

        total_nodes = len(self._scene_nodes)
        completed = 0
        current_node = entry
        # Если max_total_steps == 0 — цикл бесконечный (только стоп пользователя)
        _workflow_max = self._workflow.max_total_steps if self._workflow else 100
        max_steps = float('inf') if _workflow_max == 0 else _workflow_max

        start_time = time.time()

        # ═══ Инъекция переменных в контекст (без сброса к дефолтным) ═══
        if self._project_variables:
            for var_name, var_data in list(self._project_variables.items()):
                if var_name.startswith('_'):
                    continue
                if isinstance(var_data, dict):
                    self._context[var_name] = var_data.get('value', var_data.get('default', ''))
                else:
                    self._context[var_name] = str(var_data) if var_data else ''

        # ═══ Инициализация проектных списков и таблиц ═══
        self._init_project_lists_tables()

        try:
            _visit_count = {}  # Счётчик посещений каждого узла (защита от бесконечного цикла)
            # Если max_total_steps == 0 — бесконечный цикл, лимит снят полностью
            # Если max_total_steps > 0 — это общий лимит шагов, НЕ лимит на узел
            
            while current_node and completed < max_steps:
                if self._stop_requested:
                    self._log("⏹ Остановлено пользователем")
                    break
                
                # Защита от бесконечного цикла ОТКЛЮЧЕНА для обычных шагов
                # Контроль только через max_steps (общий лимит) и _stop_requested (кнопка стоп)
                # Если max_total_steps == 0, цикл бесконечный — только по кнопке Стоп
                
                # Добавляем узел в путь выполнения
                self.execution_path.append(current_node.id)
                
                # Skip NOTE nodes — они только визуальные, не выполняются
                if getattr(current_node, 'agent_type', None) and hasattr(current_node.agent_type, 'value') and current_node.agent_type.value == 'note':
                    self._log(f"  📌 Пропуск заметки: {current_node.name}")
                    current_node = self._find_next_node(current_node, NodeResult(current_node.id, current_node.name))
                    continue
                
                # Skip nodes not in selection (if only_node_ids mode)
                if self._only_node_ids and current_node.id not in self._only_node_ids:
                    self._log(f"  ⏭ Пропуск: {current_node.name} (не в выборке)")
                    current_node = self._find_next_node(current_node, NodeResult(current_node.id, current_node.name))
                    continue
                    
                # Check pause / breakpoint — ТОЛЬКО per-node настройка
                # Глобальная настройка больше НЕ влияет (она в UI для удобства массового включения)
                node_bp = getattr(current_node, 'breakpoint_enabled', False)
                self._log(f"  [DEBUG] breakpoint: node={node_bp}")
                if node_bp or self._is_paused:
                    self._is_paused = True
                    self._log(f"⏸ Точка останова: {current_node.name}")
                    self.signals.breakpoint_hit.emit(current_node.id, current_node.name)
                    self._wait_for_resume()
                    if self._stop_requested:
                        break

                # Human in loop check — ТОЛЬКО per-node
                node_hil = getattr(current_node, 'human_in_loop', False)
                self._log(f"  [DEBUG] human_in_loop: node={node_hil}")
                if node_hil:
                    self._is_paused = True
                    self._log(f"👤 Ожидание пользователя: {current_node.name}")
                    self.signals.waiting_input.emit(current_node.id, f"Подтвердите выполнение: {current_node.name}")
                    self._wait_for_resume()
                    if self._stop_requested:
                        break

                # Per-node backup перед выполнением
                node_backup = getattr(current_node, 'backup_before_node', False)
                if node_backup and self._project_root:
                    self._log(f"  💾 Бэкап перед {current_node.name}...")
                    self._do_backup(current_node.name)

                # Execute node
                self.signals.progress.emit(completed + 1, total_nodes)
                result = await self._execute_node(current_node)
                self._results[current_node.id] = result

                completed += 1

                if result.status == "success":
                    # Store output in context for next node
                    self._context[current_node.name] = result.output
                    self._context["_last_output"] = result.output
                    self._context["_last_node"] = current_node.name

                    # Find next node (для IF/Loop/Switch _find_next_node сам решает куда идти)
                    current_node = self._find_next_node(current_node, result)
                else:
                    # Error — look for ON_FAILURE edge before stopping
                    self._log(f"❌ {current_node.name}: {result.error}")
                    self._context["_last_error"] = result.error
                    self._context["_last_failed_node"] = current_node.name
                    failure_node = self._find_failure_node(current_node)
                    if failure_node:
                        self._log(f"🔧 Маршрут к агенту исправления: {failure_node.name}")
                        current_node = failure_node
                    else:
                        current_node = None  # stop

            elapsed = int(time.time() - start_time)
            success_count = sum(1 for r in self._results.values() if r.status == "success")
            fail_count = sum(1 for r in self._results.values() if r.status == "error")
            
            # ═══ Автоматический вызов Good End / Bad End ═══
            # Ищем ноды Good End / Bad End которые ещё не были выполнены
            good_end_reached = self._context.get("_good_end_reached", False)
            bad_end_reached = self._context.get("_bad_end_reached", False)
            was_stopped = self._stop_requested
            
            if not was_stopped and not good_end_reached and not bad_end_reached:
                # Определяем тип завершения
                workflow_success = (fail_count == 0 and success_count > 0)
                
                # Ищем подходящий End-узел среди всех нод
                for node_id, node_obj in self._scene_nodes.items():
                    if node_id in self._results:
                        continue  # Уже выполнен — пропускаем
                    
                    node_type = getattr(node_obj, 'agent_type', None)
                    if node_type == AgentType.GOOD_END and workflow_success:
                        self._log(f"  ✅ Авто-вызов Good End: {node_obj.name}")
                        try:
                            end_result = await self._execute_node(node_obj)
                            self._results[node_id] = end_result
                        except Exception as e:
                            self._log(f"  ⚠ Ошибка Good End: {e}")
                        break
                    elif node_type == AgentType.BAD_END and not workflow_success:
                        self._log(f"  🛑 Авто-вызов Bad End: {node_obj.name}")
                        try:
                            end_result = await self._execute_node(node_obj)
                            self._results[node_id] = end_result
                        except Exception as e:
                            self._log(f"  ⚠ Ошибка Bad End: {e}")
                        break

            summary = (f"Завершено за {elapsed}с: "
                       f"{success_count} успешно, {fail_count} ошибок, "
                       f"{completed} шагов")
            self._log(f"🏁 {summary}")
            
            # === ЗАКРЫТИЕ БРАУЗЕРА ПО ЗАВЕРШЕНИИ ===
            self._close_browser_if_needed()
            
            self.signals.workflow_finished.emit(fail_count == 0, summary)

        except Exception as e:
            self._log(f"💥 Фатальная ошибка: {e}")
            # Закрываем браузер и при ошибке, если флаг стоит
            self._close_browser_if_needed()
            self.signals.workflow_finished.emit(False, str(e))

        self._is_running = False

    # ── Node execution ────────────────────────────────────────

    async def _execute_node(self, node: AgentNode) -> NodeResult:
        """Execute a single agent node with retries and auto-improve."""
        result = NodeResult(node.id, node.name)
        result.status = "running"
        self.signals.node_started.emit(node.id, node.name)
        self._log(f"▶ {node.name} ({node.agent_type.value})")
        
        # === КОНТЕКСТ ЗАДАЧИ ===
        # Формируем контекст из предыдущих выполнений
        task_context = self._build_task_context(node)
        
        # Логируем входной контекст
        self._log(f"  📥 Контекст: {len(task_context)} символов")

        # Get settings (per-node overrides global)
        max_iter = getattr(node, 'max_iterations', 1)
        if max_iter <= 0:
            max_iter = self._global_auto.get('max_iterations', 1) or 1
        auto_test = getattr(node, 'auto_test', False) or self._global_auto.get('auto_test', False)
        auto_patch = getattr(node, 'auto_patch', False) or self._global_auto.get('auto_patch', False)
        auto_improve = getattr(node, 'auto_improve', False) or self._global_auto.get('auto_improve', False)

        timeout = getattr(node, 'timeout_seconds', 0) or self._global_execution.get('timeout', 120)

        start = time.time()

        for attempt in range(1, max_iter + 1):
            if self._stop_requested:
                result.status = "error"
                result.error = "Остановлено"
                break

            result.attempt = attempt
            if attempt > 1:
                self._log(f"  🔄 Попытка {attempt}/{max_iter}")

            try:
                # Build prompt
                messages = self._build_messages(node)

                # === Специальные режимы по типу агента ===
                if node.agent_type == AgentType.CODE_WRITER:
                    full_response = await self._iterative_code_write(node, timeout)
                elif node.agent_type == AgentType.SCRIPT_RUNNER:
                    full_response = await self._iterative_script_run(node, timeout)
                elif node.agent_type == AgentType.PATCHER:
                    full_response = await self._iterative_patch(node, timeout)
                elif node.agent_type == AgentType.CODE_SNIPPET:
                    full_response = await self._exec_code_snippet(node)
                elif node.agent_type == AgentType.IF_CONDITION:
                    full_response = await self._exec_if_condition(node)
                elif node.agent_type == AgentType.LOOP:
                    full_response = await self._exec_loop(node, timeout)
                elif node.agent_type == AgentType.VARIABLE_SET:
                    full_response = await self._exec_variable_set(node)
                elif node.agent_type == AgentType.HTTP_REQUEST:
                    full_response = await self._exec_http_request(node)
                elif node.agent_type == AgentType.DELAY:
                    full_response = await self._exec_delay(node)
                elif node.agent_type == AgentType.LOG_MESSAGE:
                    full_response = await self._exec_log_message(node)
                elif node.agent_type == AgentType.SWITCH:
                    full_response = await self._exec_switch(node)
                elif node.agent_type == AgentType.GOOD_END:
                    full_response = await self._exec_good_end(node)
                elif node.agent_type == AgentType.BAD_END:
                    full_response = await self._exec_bad_end(node)
                elif node.agent_type == AgentType.NOTIFICATION:
                    full_response = await self._exec_notification(node)
                elif node.agent_type == AgentType.JS_SNIPPET:
                    full_response = await self._exec_js_snippet(node)
                elif node.agent_type == AgentType.PROGRAM_LAUNCH:
                    full_response = await self._exec_program_launch(node)
                elif node.agent_type == AgentType.LIST_OPERATION:
                    full_response = await self._exec_list_operation(node)
                elif node.agent_type == AgentType.TABLE_OPERATION:
                    full_response = await self._exec_table_operation(node)
                elif node.agent_type == AgentType.FILE_OPERATION:
                    full_response = await self._exec_file_operation(node)
                elif node.agent_type == AgentType.DIR_OPERATION:
                    full_response = await self._exec_dir_operation(node)
                elif node.agent_type == AgentType.TEXT_PROCESSING:
                    full_response = await self._exec_text_processing(node)
                elif node.agent_type == AgentType.JSON_XML:
                    full_response = await self._exec_json_xml(node)
                elif node.agent_type == AgentType.VARIABLE_PROC:
                    full_response = await self._exec_variable_proc(node)
                elif node.agent_type == AgentType.RANDOM_GEN:
                    full_response = await self._exec_random_gen(node)
                elif node.agent_type == AgentType.BROWSER_LAUNCH:
                    full_response = await self._exec_browser_launch(node)
                    # Синхронизируем browser_instance_id в project_variables
                    if "browser_instance_id" in self._context and self._project_variables is not None:
                        self._project_variables["browser_instance_id"] = self._context["browser_instance_id"]
                        self._log(f"[DEBUG] Синхронизирован browser_instance_id в project_variables")
                elif node.agent_type == AgentType.BROWSER_ACTION:
                    full_response = await self._exec_browser_action(node)
                elif node.agent_type == AgentType.BROWSER_AGENT:
                    # Проверяем режим предобработки планера
                    if getattr(node, 'planner_preprocess', False):
                        full_response = await self._exec_browser_agent_preprocessed(node, timeout)
                    else:
                        full_response = await self._exec_browser_agent_single(node, timeout)
                elif node.agent_type == AgentType.BROWSER_CLOSE:
                    full_response = await self._exec_browser_close(node)
                elif node.agent_type == AgentType.BROWSER_CLICK_IMAGE:
                    from constructor.browser_module import (
                        BrowserManager, execute_browser_click_image_snippet,
                    )
                    pbm  = getattr(self, 'project_browser_manager', None)
                    mgr  = (pbm._manager if pbm and hasattr(pbm, '_manager')
                            else None) or BrowserManager.get()
                    self._context = execute_browser_click_image_snippet(
                        cfg=self._node_cfg(node),
                        context=self._context,
                        manager=mgr,
                        logger=self._log,
                        project_browser_manager=pbm,
                    )
                    full_response = "ok"
                elif node.agent_type == AgentType.BROWSER_PROFILE_OP:
                    full_response = await self._exec_browser_profile_op(node)
                elif node.agent_type == AgentType.BROWSER_SCREENSHOT:
                    full_response = await self._exec_browser_screenshot(node)
                elif node.agent_type == AgentType.PROJECT_INFO:
                    full_response = await self._exec_project_info(node)
                elif node.agent_type == AgentType.BROWSER_PARSE:
                    full_response = await self._exec_browser_parse(node)
                elif node.agent_type == AgentType.PROGRAM_INSPECTOR:
                    full_response = await self._exec_program_inspector(node)
                elif node.agent_type == AgentType.PROJECT_START:
                    full_response = await self._exec_project_start(node)
                elif node.agent_type == AgentType.PROGRAM_OPEN:
                    full_response = await self._exec_program_open(node)
                elif node.agent_type == AgentType.PROGRAM_ACTION:
                    full_response = await self._exec_program_action(node)
                elif node.agent_type == AgentType.PROGRAM_CLICK_IMAGE:
                    full_response = await self._exec_program_click_image(node)
                elif node.agent_type == AgentType.PROGRAM_SCREENSHOT:
                    full_response = await self._exec_program_screenshot(node)
                elif node.agent_type == AgentType.PROGRAM_AGENT:
                    full_response = await self._exec_program_agent(node)
                elif node.agent_type == AgentType.PROJECT_IN_PROJECT:
                    full_response = await self._exec_project_in_project(node)
                else:
                    # AI-powered agents (Code Reviewer, Tester, Verifier, etc.)
                    full_response = await self._call_model(node, messages, timeout)

                result.output = full_response
                result.status = "success"
                result.duration_ms = int((time.time() - start) * 1000)

                self.signals.node_finished.emit(node.id, node.name, True, full_response[:200])
                self._log(f"  ✅ {node.name} — {len(full_response)} символов ({result.duration_ms}мс)")

                # Auto-test
                if auto_test and not self._auto_test(node, full_response):
                    self._log(f"  ⚠ Авто-тест не пройден")
                    if attempt < max_iter:
                        if auto_improve:
                            self._log(f"  🧠 Улучшаю промпт...")
                            node.user_prompt_template += (
                                f"\n\n[PREVIOUS ATTEMPT FAILED AUTO-TEST]\n"
                                f"Previous output was rejected. Try a different approach."
                            )
                        continue  # retry
                    result.status = "error"
                    result.error = "Auto-test failed after all attempts"
                    break

                # === ПРОВЕРКА: Code Writer создал файлы (итеративный режим) ===
                if node.agent_type == AgentType.CODE_WRITER:
                    disk_files = self._scan_disk_files()
                    self._context["created_files"] = disk_files
                    self._log(f"  📁 Файлов на диске после Code Writer: {len(disk_files)}")
                    if len(disk_files) == 0 and attempt < max_iter:
                        self._log(f"  ⚠ 0 файлов! Повтор итеративного создания...")
                        result.status = "error"
                        result.error = "0 files created"
                        continue
                
                # Execute tools and capture failures
                failed_tools = await self._execute_node_tools(node, full_response)

                # === SCRIPT RUNNER: ИТЕРАТИВНЫЙ ЦИКЛ ТЕСТ → ФИКС → ТЕСТ ===
                if node.agent_type == AgentType.SCRIPT_RUNNER and failed_tools:
                    shell_failures = [f for f in failed_tools
                                      if f["tool"] in ("shell_exec", "code_execute")]
                    if shell_failures:
                        err = shell_failures[0]
                        error_log = (
                            f"Скрипт упал (код {err['returncode']}):\n"
                            f"STDERR: {err['error'][:2000]}\n"
                            f"STDOUT: {err['stdout'][:2000]}"
                        )
                        
                        # Читаем настройки итеративного тестирования
                        sr_max_fix_loops = getattr(node, 'max_iterations', 1)
                        sr_auto_fix = getattr(node, 'auto_patch', False)
                        
                        if sr_auto_fix and attempt < sr_max_fix_loops:
                            self._log(f"  💥 Тест не пройден (попытка {attempt}/{sr_max_fix_loops})")
                            self._log(f"  🔄 Запрос исправления от модели...")
                            
                            # Собираем список файлов проекта для контекста
                            project_files_list = ""
                            try:
                                list_result = await self._tool_executor.execute_tool("shell_exec", {
                                    "command": "find . -type f -name '*.py' -o -name '*.js' -o -name '*.json' | head -30",
                                    "timeout": 10,
                                })
                                if list_result.get("success"):
                                    project_files_list = list_result.get("stdout", "")
                            except Exception:
                                pass
                            
                            # Дополняем промпт для следующей попытки
                            fix_instruction = (
                                f"\n\n=== ОШИБКА ТЕСТИРОВАНИЯ (попытка {attempt}) ===\n"
                                f"{error_log}\n"
                                f"\n=== ФАЙЛЫ ПРОЕКТА ===\n{project_files_list}\n"
                                f"\n=== ЗАДАЧА ===\n"
                                f"Исправь ошибку. Используй file_write для перезаписи сломанных файлов "
                                f"и shell_exec/code_execute для повторного теста.\n"
                                f"=== КОНЕЦ ==="
                            )
                            node.user_prompt_template = (node.user_prompt_template or "") + fix_instruction
                            
                            # Сохраняем ошибку в контекст
                            self._context["_script_error"] = error_log
                            self._context["_script_stdout"] = err.get("stdout", "")
                            self._context["_last_test_attempt"] = attempt
                            
                            continue  # → повторная итерация основного цикла
                        else:
                            # Все попытки исчерпаны или auto_patch отключен
                            result.status = "error"
                            result.error = error_log
                            self._context["_script_error"] = error_log
                            self._context["_script_stdout"] = err.get("stdout", "")
                            self._log(f"  💥 Скрипт завершился с ошибкой — передаю агенту исправления")

                # === СОХРАНЕНИЕ В КОНТЕКСТ ===
                # Сохраняем в глобальный контекст для следующих узлов
                self._context[f"output_{node.name}"] = full_response
                self._context["_last_output"] = full_response
                
                # Если это Code Writer, отслеживаем какие файлы он должен был создать
                if node.agent_type.value == "code_writer":
                    import re
                    # Ищем упоминания файлов в плане
                    planned_files = re.findall(r'[\w\-\/]+\.(py|js|ts|json|yaml|yml|md|txt)', full_response)
                    if planned_files:
                        self._context["_planned_files"] = planned_files
                        self._log(f"  📋 Code Writer должен создать: {', '.join(planned_files[:10])}")
                
                # Если узел создал файлы, сохраняем список
                if any(ext in full_response.lower() for ext in ['.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml']):
                    # Парсинг созданных файлов из вывода
                    import re
                    files = re.findall(r'[\w\-\/]+\.(py|js|txt|md|json|yaml|yml)', full_response)
                    if files:
                        existing = self._context.get("created_files", [])
                        self._context["created_files"] = list(set(existing + files))
                        self._log(f"  📁 Обнаружены файлы: {', '.join(files)}")
                
                break  # success, stop retrying

            except asyncio.TimeoutError:
                result.error = f"Таймаут ({timeout}с)"
                result.status = "error"
                self._log(f"  ⏱ Таймаут: {node.name}")
                if attempt < max_iter:
                    continue
            except Exception as e:
                # ═══ LOOP_CONTINUE — это не ошибка, а сигнал продолжения цикла ═══
                if str(e) == "LOOP_CONTINUE":
                    result.status = "success"
                    result.output = f"🔁 Итерация {self._context.get('_loop_iteration', '?')}"
                    result.duration_ms = int((time.time() - start) * 1000)
                    self.signals.node_finished.emit(node.id, node.name, True, result.output[:200])
                    break
                result.error = str(e)
                result.status = "error"
                self._log(f"  ❌ Ошибка: {e}")
                if auto_improve and attempt < max_iter:
                    # ═══ НЕ модифицировать user_prompt_template для сниппетов! ═══
                    _snippet_types = {
                        AgentType.CODE_SNIPPET, AgentType.IF_CONDITION, AgentType.LOOP,
                        AgentType.VARIABLE_SET, AgentType.HTTP_REQUEST, AgentType.DELAY,
                        AgentType.LOG_MESSAGE, AgentType.SWITCH, AgentType.GOOD_END,
                        AgentType.PROJECT_IN_PROJECT,
                        AgentType.BAD_END, AgentType.NOTIFICATION, AgentType.JS_SNIPPET,
                        AgentType.PROGRAM_LAUNCH, AgentType.LIST_OPERATION, AgentType.TABLE_OPERATION,
                        AgentType.FILE_OPERATION, AgentType.DIR_OPERATION, AgentType.TEXT_PROCESSING,
                        AgentType.JSON_XML, AgentType.VARIABLE_PROC, AgentType.RANDOM_GEN,
                        AgentType.BROWSER_LAUNCH, AgentType.BROWSER_ACTION, AgentType.BROWSER_CLOSE,
                        AgentType.BROWSER_CLICK_IMAGE, AgentType.BROWSER_SCREENSHOT,
                        AgentType.BROWSER_PROFILE_OP, AgentType.PROJECT_INFO,
                        AgentType.BROWSER_PARSE, AgentType.PROGRAM_INSPECTOR,
                        AgentType.PROGRAM_OPEN, AgentType.PROGRAM_ACTION,
                        AgentType.PROGRAM_CLICK_IMAGE, AgentType.PROGRAM_SCREENSHOT,
                    }
                    if node.agent_type not in _snippet_types:
                        node.user_prompt_template += f"\n\n[ERROR IN ATTEMPT {attempt}]: {e}\nFix the issue."
                    continue
                break

        if result.status == "error":
            self.signals.node_finished.emit(node.id, node.name, False, result.error[:200])
            self.signals.error.emit(node.id, result.error)

        return result
    
    async def _exec_planner_preprocessor(self, node: AgentNode, timeout: int) -> str:
        """
        Предобработка вывода Planner'а и выполнение Browser Agent для каждого пункта.
        """
        import re
        
        # Получаем вывод от Planner (ищем в результатах предыдущих узлов)
        planner_output = ""
        planner_node_id = getattr(node, "planner_source_node_id", "")
        
        # Ищем по ID или по типу PLANNER
        if planner_node_id and planner_node_id in self._results:
            planner_output = self._results[planner_node_id].output
        else:
            # Автопоиск последнего PLANNER
            for nid in reversed(self.execution_path):
                if nid in self._results:
                    node_obj = self._scene_nodes.get(nid)
                    if node_obj and getattr(node_obj, 'agent_type', None) == AgentType.PLANNER:
                        planner_output = self._results[nid].output
                        break
        
        if not planner_output:
            return "⚠️ Не найден вывод Planner'а"
        
        self._log(f"  📋 Получен план: {len(planner_output)} символов")
        
        # === ПАРСИНГ ПУНКТОВ ПЛАНА ===
        # Поддерживаемые форматы:
        # 1. "1. Пункт", "2. Пункт" 
        # 2. "- Пункт", "* Пункт"
        # 3. "### Пункт", "**Пункт**"
        # 4. [ ] или [x] чекбоксы
        
        tasks = []
        
        # Пробуем нумерованный список
        numbered = re.findall(r'^\s*\d+[\.\)]\s+(.+?)(?=\n\s*\d+[\.\)]|\Z)', planner_output, re.MULTILINE | re.DOTALL)
        if numbered:
            tasks = [t.strip() for t in numbered if len(t.strip()) > 10]
        
        # Пробуем маркированный список
        if not tasks:
            bullet = re.findall(r'^\s*[-*•]\s+(.+?)(?=\n\s*[-*•]|\Z)', planner_output, re.MULTILINE | re.DOTALL)
            if bullet:
                tasks = [t.strip() for t in bullet if len(t.strip()) > 10]
        
        # Пробуем заголовки
        if not tasks:
            headers = re.findall(r'#{1,3}\s+(.+?)(?=\n#{1,3}|\Z)', planner_output, re.MULTILINE | re.DOTALL)
            if headers:
                tasks = [t.strip() for t in headers if len(t.strip()) > 10]
        
        # Фоллбэк: разбиваем по пустым строкам на блоки
        if not tasks:
            blocks = [b.strip() for b in re.split(r'\n\s*\n', planner_output) if len(b.strip()) > 20]
            tasks = blocks
        
        if not tasks:
            # Если ничего не распарсилось — берём весь текст как одну задачу
            tasks = [planner_output[:2000]]
        
        self._log(f"  📋 Распознано задач: {len(tasks)}")
        for i, t in enumerate(tasks[:5], 1):
            preview = t.replace('\n', ' ')[:80]
            self._log(f"    {i}. {preview}...")
        
        # === ВЫПОЛНЕНИЕ BROWSER AGENT ДЛЯ КАЖДОЙ ЗАДАЧИ ===
        all_results = []
        total_actions = 0
        
        for i, task in enumerate(tasks, 1):
            if self._stop_requested:
                break
                
            self._log(f"\n  🔷 [{i}/{len(tasks)}] Выполнение: {task[:60]}...")
            self.signals.node_streaming.emit(node.id, f"\n{'='*50}\n🔷 Задача {i}/{len(tasks)}: {task[:100]}\n{'='*50}\n")
            
            # Сохраняем текущую задачу в контекст
            self._context["_current_planner_task"] = task
            self._context["_current_task_index"] = i
            self._context["_total_tasks"] = len(tasks)
            
            # Вызываем Browser Agent для этой задачи
            try:
                # Получаем инстанс браузера
                browser_id = (
                    self.execution_context.get("browser_instance_id") or
                    getattr(self, '_project_variables', {}).get("browser_instance_id") or
                    self._context.get("browser_instance_id")
                )
                
                # Fallback на первый доступный
                if not browser_id and self.project_browser_manager:
                    browser_id = self.project_browser_manager.first_instance_id()
                
                if not browser_id:
                    self._log(f"  ⚠️ Нет активного браузера для задачи {i}")
                    continue
                
                # Формируем специальный промпт для Browser Agent
                task_prompt = f"""ВЫПОЛНИ ЗАДАЧУ:
    {task}

    КОНТЕКСТ ПОЛНОГО ПЛАНА:
    {planner_output[:500]}

    Это задача {i} из {len(tasks)}. Выполни только эту конкретную задачу."""
                
                # Создаём временный узел для Browser Agent
                from services.agent_models import AgentNode, AgentType
                
                temp_node = AgentNode(
                    id=f"{node.id}_task_{i}",
                    name=f"Browser Agent Task {i}",
                    agent_type=AgentType.BROWSER_AGENT,
                    system_prompt=getattr(node, 'browser_system_prompt', '') or 
                        "Ты — браузерный агент. Получаешь конкретную задачу и выполняешь её в браузере. "
                        "Отвечай JSON-списком действий.",
                    user_prompt_template=task_prompt,
                    browser_instance_var="{browser_instance_id}",
                    dom_max_tokens=getattr(node, 'dom_max_tokens', 2000),
                    screenshot_verify=getattr(node, 'screenshot_verify', False),
                )
                
                # Вызываем Browser Agent
                result = await self._exec_browser_agent(temp_node, timeout)
                
                all_results.append({
                    "task_index": i,
                    "task": task[:200],
                    "result": result,
                    "success": not result.startswith("❌") if result else True
                })
                
                # Считаем действия
                total_actions += self.execution_context.get('browser_agent_actions_count', 0)
                
                # Пауза между задачами если нужна
                if i < len(tasks) and getattr(node, 'delay_between_tasks', 0) > 0:
                    await asyncio.sleep(node.delay_between_tasks)
                    
            except Exception as e:
                self._log(f"  ❌ Ошибка в задаче {i}: {e}")
                all_results.append({
                    "task_index": i,
                    "task": task[:200],
                    "result": f"❌ {e}",
                    "success": False
                })
        
        # Формируем итоговый отчёт
        successful = sum(1 for r in all_results if r['success'])
        report = f"""📋 Предобработка плана завершена

    Всего задач: {len(tasks)}
    Успешно: {successful}
    Ошибок: {len(tasks) - successful}
    Всего действий в браузере: {total_actions}

    Детали:
    """
        for r in all_results:
            icon = "✅" if r['success'] else "❌"
            report += f"\n{icon} [{r['task_index']}] {r['task'][:60]}..."
        
        # Сохраняем результаты
        self._context["_planner_tasks_results"] = all_results
        self._context["_planner_tasks_total"] = len(tasks)
        self._context["_planner_tasks_successful"] = successful
        
        return report
    
    # ── Prompt building ───────────────────────────────────────

    def _build_messages(self, node: AgentNode) -> list[ChatMessage]:
        """Build chat messages for the AI model call."""
        messages = []
        
        # System prompt с контекстом задачи
        task_context = self._build_task_context(node)
        system = node.system_prompt or self._default_system_prompt(node)
        
        # Добавляем контекст в system prompt если это не первый узел
        if task_context and len(self._results) > 0:
            system += f"\n\n=== КОНТЕКСТ ТЕКУЩЕЙ ЗАДАЧИ ===\n{task_context}\n=== КОНЕЦ КОНТЕКСТА ==="

        # Add skills context
        if hasattr(node, 'skill_ids') and node.skill_ids and self._skill_registry:
            skills_text = []
            for sid in node.skill_ids:
                skill = self._skill_registry.get(sid)
                if skill:
                    skills_text.append(f"- {skill.name}: {skill.description}")
            if skills_text:
                system += f"\n\nAvailable skills:\n" + "\n".join(skills_text)

        # Add available tools info
        tools = getattr(node, 'available_tools', [])
        if not tools:
            tools = [t for t, enabled in self._global_tools.items() if enabled]
        if tools:
            system += f"\n\nAvailable tools: {', '.join(tools)}"
            system += ("\n\nTo use a tool, output JSON in this format:\n"
                       '```tool\n{"tool": "tool_name", "params": {...}}\n```')

        messages.append(ChatMessage(role=MessageRole.SYSTEM, content=system))

        # Add context from previous nodes - include ALL previous outputs for project generation
        if self._context:
            ctx_parts = []
            for key, val in self._context.items():
                if not key.startswith("_") and isinstance(val, str):
                    # Include full context for project files, truncated for others
                    max_len = 8000 if 'structure' in key.lower() or 'plan' in key.lower() else 2000
                    ctx_parts.append(f"[Output from {key}]:\n{val[:max_len]}")
            if ctx_parts:
                messages.append(ChatMessage(
                    role=MessageRole.USER,
                    content="""Context from previous agents (CRITICAL: follow the complete file structure from Planner):

""" + "\n\n".join(ctx_parts[-3:]) + """

INSTRUCTION: You MUST create ALL files listed in the project structure above. Do not stop after creating just one file. Create every single file mentioned in the structure."""
                ))

        # User prompt
        user = node.user_prompt_template or f"Execute the task: {node.name}\n{node.description}"
        messages.append(ChatMessage(role=MessageRole.USER, content=user))

        return messages

    def _default_system_prompt(self, node: AgentNode) -> str:
        """Generate a default system prompt based on agent type."""
        type_prompts = {
            AgentType.CODE_WRITER: (
                "You are an expert code writer. You MUST output complete working code for EVERY file.\n\n"
                "FORMAT — for each file output EXACTLY this:\n\n"
                "**filename.py**\n"
                "```python\n"
                "# full working code here\n"
                "```\n\n"
                "RULES:\n"
                "- Output COMPLETE code for EVERY file from the plan\n"
                "- NEVER say 'here are the files' without actual code\n"
                "- NEVER use placeholders like 'implement here' or 'pass'\n"
                "- EVERY function must have a real implementation\n"
                "- Create ALL files: main scripts, configs, requirements.txt, README.md\n"
                "- If tools are available, use file_write for each file:\n"
                "```tool\n"
                '{"tool": "file_write", "params": {"path": "filename.py", "content": "..."}}\n'
                "```"
            ),
            AgentType.CODE_REVIEWER: (
                "You are an expert code reviewer.\n"
                "Read ALL project files and find:\n"
                "1. Bugs and logic errors\n"
                "2. Security vulnerabilities\n"
                "3. Missing imports, undefined variables\n"
                "4. Inconsistent function signatures between files\n"
                "5. Dead code, unused imports\n\n"
                "For each issue output:\n"
                "FILE: filename.py\n"
                "LINE: approximate line number\n"
                "SEVERITY: critical/warning/info\n"
                "ISSUE: description\n"
                "FIX: suggested fix\n"
            ),
            AgentType.TESTER: (
                "You are a testing specialist. Create test files and run them.\n"
                "1. Read all project .py files\n"
                "2. Create test_*.py files using unittest or pytest\n"
                "3. Use file_write to save test files\n"
                "4. Use shell_exec to run: python -m pytest tests/ -v\n"
                "5. Report results: PASS/FAIL with details\n\n"
                "IMPORTANT: Tests must be RUNNABLE, not stubs."
            ),
            AgentType.PLANNER: "You are a project planner. Break down tasks, create action plans, and define architecture.",
            AgentType.IMAGE_GEN: "You are an image generation specialist. Create prompts and manage image assets.",
            AgentType.IMAGE_ANALYST: "You are an image analyst. Describe, analyze, and extract information from images.",
            AgentType.FILE_MANAGER: "You are a file manager. Organize, create, read, and modify project files.",
            AgentType.SCRIPT_RUNNER: (
                "You are a script execution and testing specialist.\n\n"
                "WORKFLOW:\n"
                "1. First, analyze the project files in the working directory using:\n"
                "```tool\n"
                '{"tool": "shell_exec", "params": {"command": "find . -type f -name *.py | head -20"}}\n'
                "```\n"
                "2. Determine which script is the main entry point or test script.\n"
                "3. Run the script:\n"
                "```tool\n"
                '{"tool": "code_execute", "params": {"code": "..."}}\n'
                "```\n"
                "   OR:\n"
                "```tool\n"
                '{"tool": "shell_exec", "params": {"command": "python main.py"}}\n'
                "```\n"
                "4. If the script fails, output the FULL error log and list ALL project files.\n"
                "5. Suggest specific fixes needed.\n\n"
                "IMPORTANT: Always show the complete stdout/stderr output."
            ),
            AgentType.VERIFIER: (
                "You are a verification specialist.\n"
                "1. Read the original plan/requirements from context\n"
                "2. Read all created files\n"
                "3. Check: does the code match the requirements?\n"
                "4. Check: do all imports resolve?\n"
                "5. Check: is main entry point functional?\n\n"
                "Output:\n"
                "✅ PASS: requirement met\n"
                "❌ FAIL: requirement not met — what's missing\n"
                "Score: X/Y requirements met"
            ),
            AgentType.ORCHESTRATOR: "You are a workflow orchestrator. Coordinate between agents and manage execution flow.",
            AgentType.PATCHER: (
                "You are a code fixer and patcher. You receive error logs from failed script executions "
                "and must fix the broken code.\n\n"
                "RULES:\n"
                "1. Read the error log carefully — find the ROOT CAUSE\n"
                "2. Read the source files that caused the error\n"
                "3. Fix ONLY the broken parts — do NOT rewrite entire files\n"
                "4. Use file_write to save fixed files:\n"
                "```tool\n"
                '{"tool": "file_write", "params": {"path": "filename.py", "content": "...fixed code..."}}\n'
                "```\n"
                "5. After fixing, verify by listing what you changed\n\n"
                "Output format for EACH fix:\n"
                "**FIXING: filename.py**\n"
                "Problem: <what was wrong>\n"
                "Solution: <what you changed>\n"
                "```tool\n"
                '{"tool": "file_write", "params": {"path": "filename.py", "content": "..."}}\n'
                "```"
            ),
        }
        return type_prompts.get(node.agent_type,
                                f"You are an AI assistant performing the role: {node.agent_type.value}")

    # ── Model calling ─────────────────────────────────────────

    async def _call_model(self, node: AgentNode, messages: list[ChatMessage],
                      timeout: int, model_id: str = None) -> str:  # ← добавить model_id
        """Call the AI model and return the full response."""
        provider = self._model_manager.active_provider
        if not provider:
            raise RuntimeError("No active AI provider")
        
        # ═══ ИСПРАВЛЕНИЕ: выбор модели по model_id если указан ═══
        if model_id and hasattr(self._model_manager, 'get_provider_by_id'):
            provider = self._model_manager.get_provider_by_id(model_id) or provider

        chunks = []

        async def _stream():
            async for chunk in provider.stream(messages):
                chunks.append(chunk)
                self.signals.node_streaming.emit(node.id, chunk)

        # ── Семафор модели: sequential / parallel из GlobalSettings ────────
        _model_id = getattr(node, 'model_id', '') or 'default'
        _sem = None
        try:
            from constructor.agent_constructor import ProjectThreadManager
            _sem = ProjectThreadManager.get().get_model_semaphore(_model_id)
        except Exception:
            _sem = None

        if _sem is not None:
            _sem.acquire()
            try:
                await asyncio.wait_for(_stream(), timeout=timeout)
            finally:
                _sem.release()
        else:
            await asyncio.wait_for(_stream(), timeout=timeout)

        return "".join(chunks)

    # ── Tool execution from AI response ───────────────────────

    async def _execute_node_tools(self, node: AgentNode, response: str) -> list[dict]:
        """Parse and execute any tool calls from the AI response.
        Returns list of failed tool results for error propagation."""
        import re
        tool_pattern = re.compile(r'```tool\s*\n(.*?)\n```', re.DOTALL)
        matches = tool_pattern.findall(response)

        available = set(getattr(node, 'available_tools', []))
        if not available:
            available = {t for t, enabled in self._global_tools.items() if enabled}

        failed_tools: list[dict] = []

        for match in matches:
            try:
                call = json.loads(match.strip())
                tool_id = call.get("tool", "")
                params = call.get("params", {})

                if tool_id not in available:
                    self._log(f"  ⚠ Тулза {tool_id} не разрешена для {node.name}")
                    continue

                self._log(f"  🔧 Вызов: {tool_id}")
                tool_result = await self._tool_executor.execute_tool(tool_id, params)

                if tool_result.get("success"):
                    self._log(f"  ✓ {tool_id} выполнен")
                    # Store stdout in context for fixer agents
                    if "stdout" in tool_result:
                        self._context["_last_tool_stdout"] = tool_result["stdout"]
                else:
                    error_msg = (tool_result.get("stderr") or
                                 tool_result.get("error") or "неизвестная ошибка")
                    self._log(f"  ✗ {tool_id}: {error_msg}")
                    failed_tools.append({
                        "tool": tool_id,
                        "params": params,
                        "error": error_msg,
                        "stdout": tool_result.get("stdout", ""),
                        "returncode": tool_result.get("returncode", -1),
                    })
            except json.JSONDecodeError:
                self._log(f"  ⚠ Невалидный JSON для tool call")
            except Exception as e:
                self._log(f"  ⚠ Ошибка tool: {e}")

        return failed_tools
    
    # ── Iterative Code Writer ─────────────────────────────────

    async def _iterative_code_write(self, node: AgentNode, timeout: int) -> str:
        """Итеративное создание файлов: один файл = один вызов модели.
        
        Шаг 1: Просим модель составить список файлов
        Шаг 2: Для каждого файла — отдельный вызов с контекстом уже созданных
        """
        import re
        
        system = node.system_prompt or self._default_system_prompt(node)
        task_context = self._build_task_context(node)
        
        # ═══ ШАГ 1: Получить список файлов из плана ═══
        self._log(f"  📋 Шаг 1: Запрашиваю список файлов...")
        
        plan_messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=(
                "You are a project architect. Analyze the plan and output ONLY "
                "a numbered list of files to create. Format:\n"
                "1. path/filename.ext - brief description\n"
                "2. path/filename2.ext - brief description\n"
                "Output NOTHING else. No explanations, no code."
            )),
            ChatMessage(role=MessageRole.USER, content=(
                f"Plan:\n{task_context}\n\n"
                "List ALL files needed for this project (including __init__.py, "
                "requirements.txt, README.md, main entry point, etc.):"
            )),
        ]
        
        file_list_response = await self._call_model(node, plan_messages, timeout)
        self.signals.node_streaming.emit(node.id, f"\n📋 Список файлов:\n{file_list_response}\n")
        
        # Парсим файлы из ответа
        files_to_create = []
        seen = set()
        for line in file_list_response.split('\n'):
            m = re.search(
                r'([\w\-\.\/\\]+\.(?:py|js|ts|json|yaml|yml|md|txt|html|css|toml|cfg|ini|sh|bat|sql))',
                line
            )
            if m:
                fname = m.group(1).strip()
                # Нормализуем путь через общий sanitizer
                fname_clean = ToolExecutor._sanitize_path(fname)
                if fname_clean not in seen:
                    seen.add(fname_clean)
                    # Извлекаем описание
                    desc = line.split('-', 1)[1].strip() if '-' in line else ""
                    files_to_create.append((fname_clean, desc))
        
        if not files_to_create:
            # Фоллбэк: извлекаем файлы из контекста плана
            for m in re.finditer(
                r'([\w\-\.\/]+\.(?:py|js|ts|json|yaml|yml|md|txt|html|css))',
                task_context
            ):
                fname = m.group(1)
                if fname not in seen:
                    seen.add(fname)
                    files_to_create.append((fname, ""))
        
        if not files_to_create:
            self._log(f"  ⚠ Не удалось определить список файлов, фоллбэк на обычный вызов")
            messages = self._build_messages(node)
            return await self._call_model(node, messages, timeout)
        
        self._log(f"  📋 К созданию: {len(files_to_create)} файлов")
        for i, (f, d) in enumerate(files_to_create):
            self._log(f"    {i+1}. {f}" + (f" — {d}" if d else ""))
        
        # ═══ ШАГ 2: Создаём файлы по одному ═══
        all_outputs = []
        created_files_info = []  # [{'name': ..., 'lines': ..., 'summary': ...}]
        
        for i, (filename, description) in enumerate(files_to_create):
            if self._stop_requested:
                break
            
            # Пропускаем файлы которые уже существуют на диске
            full_path = os.path.join(self._tool_executor._root, filename)
            if os.path.exists(full_path):
                # Читаем существующий файл для контекста
                try:
                    content = Path(full_path).read_text(encoding='utf-8', errors='replace')
                    lines = len(content.split('\n'))
                    summary_lines = [l for l in content.split('\n')
                                     if l.strip().startswith(('def ', 'class ', 'import ', 'from '))]
                    created_files_info.append({
                        'name': filename,
                        'lines': lines,
                        'summary': '; '.join(summary_lines[:5])[:200],
                        'content': content,
                    })
                    self._log(f"  ⏭ [{i+1}/{len(files_to_create)}] Пропуск (уже есть): {filename} ({lines} строк)")
                except Exception:
                    self._log(f"  ⏭ [{i+1}/{len(files_to_create)}] Пропуск (уже есть): {filename}")
                continue
            
            self._log(f"  📝 [{i+1}/{len(files_to_create)}] Создаю: {filename}")
            self.signals.node_streaming.emit(
                node.id, f"\n\n{'='*50}\n📝 [{i+1}/{len(files_to_create)}] {filename}\n{'='*50}\n"
            )
            
            # Формируем контекст уже созданных файлов
            created_context = ""
            if created_files_info:
                created_context = "\n\nУже созданные файлы проекта:\n"
                for cf in created_files_info:
                    created_context += f"  ✅ {cf['name']} ({cf['lines']} строк)"
                    if cf.get('summary'):
                        created_context += f" — {cf['summary']}"
                    created_context += "\n"
                
                # Для последних 2 файлов — даём полный код для контекста импортов
                recent = created_files_info[-2:]
                for cf in recent:
                    if cf.get('content') and cf['name'].endswith('.py'):
                        created_context += f"\n--- {cf['name']} (полный код для контекста) ---\n"
                        created_context += cf['content'][:3000]
                        created_context += "\n--- конец ---\n"
            
            file_messages = [
                ChatMessage(role=MessageRole.SYSTEM, content=(
                    "You are an expert code writer. Create EXACTLY ONE file.\n"
                    "Output ONLY the file content in a code block. No explanations before or after.\n"
                    "The code must be COMPLETE and WORKING — no placeholders, no 'pass', no TODOs.\n"
                    "Every function must have a real implementation."
                )),
                ChatMessage(role=MessageRole.USER, content=(
                    f"PROJECT PLAN:\n{task_context[:2000]}\n"
                    f"{created_context}\n\n"
                    f"NOW CREATE THIS FILE: {filename}\n"
                    f"{'Description: ' + description if description else ''}\n\n"
                    f"Output format:\n"
                    f"**{filename}**\n"
                    f"```\n"
                    f"<complete working code>\n"
                    f"```"
                )),
            ]
            
            try:
                file_response = await self._call_model(node, file_messages, timeout)
                all_outputs.append(f"**{filename}**\n{file_response}")
                
                # Записываем файл НАПРЯМУЮ через file_write (без auto_extract чтобы не было рекурсии)
                full_path = os.path.join(self._tool_executor._root, filename)
                
                # Берём первый code-блок из ответа
                code_match = re.search(r'```\w*\n(.*?)\n```', file_response, re.DOTALL)
                if code_match:
                    code_content = code_match.group(1)
                    # Убираем артефакты типа **filename.py** в начале кода
                    if code_content.strip().startswith('**'):
                        code_content = '\n'.join(code_content.split('\n')[1:])
                    await self._tool_executor.execute_tool("file_write", {
                        "path": filename,
                        "content": code_content,
                    })
                elif file_response.strip():
                    # Если нет code-блока — пишем весь ответ как есть (для .txt, .md, .sql)
                    # Убираем markdown обёртки
                    clean = file_response.strip()
                    if clean.startswith('**') and '\n' in clean:
                        clean = '\n'.join(clean.split('\n')[1:])
                    await self._tool_executor.execute_tool("file_write", {
                        "path": filename,
                        "content": clean,
                    })
                
                # Проверяем что файл создан
                if os.path.exists(full_path):
                    content = Path(full_path).read_text(encoding='utf-8', errors='replace')
                    lines = len(content.split('\n'))
                    # Краткое саммари для контекста
                    summary_lines = [l for l in content.split('\n') 
                                     if l.strip().startswith(('def ', 'class ', 'import ', 'from '))]
                    summary = '; '.join(summary_lines[:5])
                    
                    created_files_info.append({
                        'name': filename,
                        'lines': lines,
                        'summary': summary[:200],
                        'content': content,
                    })
                    self._log(f"  ✅ {filename} — {lines} строк")
                else:
                    self._log(f"  ⚠ {filename} НЕ создан на диске!")
                    
            except asyncio.TimeoutError:
                self._log(f"  ⏱ Таймаут при создании {filename}")
            except Exception as e:
                self._log(f"  ❌ Ошибка при создании {filename}: {e}")
        
        # ═══ ШАГ 3: Итоговая проверка ═══
        disk_files = self._scan_disk_files()
        self._context["created_files"] = disk_files
        self._log(f"  📁 Итого на диске: {len(disk_files)} файлов: {', '.join(disk_files[:15])}")
        
        # Комбинируем все ответы
        combined = "\n\n".join(all_outputs)
        return combined if combined else "No files created"
    
    # ── Iterative Script Runner ───────────────────────────────

    async def _iterative_script_run(self, node: AgentNode, timeout: int) -> str:
        """Script Runner: спрашивает AI что запустить → запускает → возвращает результат."""
        import re
        
        task_context = self._build_task_context(node)
        disk_files = self._scan_disk_files()
        py_files = [f for f in disk_files if f.endswith('.py')]
        
        # ═══ ШАГ 1: Спросить AI какой скрипт запустить ═══
        self._log(f"  🔍 Шаг 1: Определяю точку входа...")
        
        # Умная логика определения точки входа
        main_candidates = ['main.py', 'app.py', 'run.py', 'start.py', 'cli.py', 'scraper.py', 'server.py']
        entry_file = None
        
        # Фильтруем: убираем __init__.py, тесты, файлы внутри подпапок (приоритет — корень)
        root_py = []      # файлы в корне проекта
        nested_py = []    # файлы в подпапках
        for pf in py_files:
            basename = os.path.basename(pf)
            if basename == '__init__.py':
                continue
            if 'test' in basename.lower() or 'test' in pf.lower().split(os.sep)[0] if os.sep in pf else False:
                continue
            if os.sep in pf or '/' in pf:
                nested_py.append(pf)
            else:
                root_py.append(pf)
        
        self._log(f"  📂 Корневые .py: {root_py}")
        self._log(f"  📂 Вложенные .py: {nested_py[:10]}")
        
        # 1. Ищем main.py / app.py / etc. В КОРНЕ
        for candidate in main_candidates:
            if candidate in root_py:
                entry_file = candidate
                break
        
        # 2. Ищем КОРНЕВОЙ файл с if __name__ == "__main__"
        if not entry_file:
            for pf in root_py:
                try:
                    full = os.path.join(self._tool_executor._root, pf)
                    content = Path(full).read_text(encoding='utf-8', errors='replace')
                    if '__name__' in content and '__main__' in content:
                        entry_file = pf
                        break
                except Exception:
                    pass
        
        # 3. Первый корневой .py файл
        if not entry_file and root_py:
            entry_file = root_py[0]
        
        # 4. Ищем main.py / app.py во вложенных
        if not entry_file:
            for candidate in main_candidates:
                for pf in nested_py:
                    if os.path.basename(pf) == candidate:
                        entry_file = pf
                        break
                if entry_file:
                    break
        
        # 5. Ищем вложенный файл с __main__
        if not entry_file:
            for pf in nested_py:
                try:
                    full = os.path.join(self._tool_executor._root, pf)
                    content = Path(full).read_text(encoding='utf-8', errors='replace')
                    if '__name__' in content and '__main__' in content:
                        entry_file = pf
                        break
                except Exception:
                    pass
        
        # 6. Последний фоллбэк
        if not entry_file:
            entry_file = (root_py + nested_py + ['main.py'])[0]
        
        run_cmd = f"python {entry_file}"
        
        # Читаем файл и определяем нужны ли аргументы
        try:
            entry_content = Path(os.path.join(self._tool_executor._root, entry_file)).read_text(encoding='utf-8', errors='replace')
            if 'argparse' in entry_content or 'sys.argv' in entry_content:
                # Скрипт использует аргументы — добавляем тестовые
                if '--query' in entry_content or "'-q'" in entry_content or '"-q"' in entry_content:
                    run_cmd = f'python {entry_file} -q "test query"'
                elif '--help' in entry_content:
                    run_cmd = f'python {entry_file} --help'
                elif 'required=True' in entry_content:
                    # Есть обязательные аргументы — запускаем с --help чтобы увидеть какие
                    run_cmd = f'python {entry_file} --help'
        except Exception:
            pass
        
        self._log(f"  🔍 Точка входа: {entry_file}")
        
        # ═══ ШАГ 2: Реально запустить скрипт ═══
        exec_result = await self._tool_executor.execute_tool("shell_exec", {
            "command": run_cmd,
            "timeout": min(timeout, 60),
        })
        
        stdout = exec_result.get("stdout", "")
        stderr = exec_result.get("stderr", "")
        returncode = exec_result.get("returncode", -1)
        success = exec_result.get("success", False)
        
        self.signals.node_streaming.emit(node.id, f"\n📤 Exit code: {returncode}\n")
        if stdout:
            self.signals.node_streaming.emit(node.id, f"STDOUT:\n{stdout[:2000]}\n")
        if stderr:
            self.signals.node_streaming.emit(node.id, f"STDERR:\n{stderr[:2000]}\n")
        
        # ═══ ШАГ 3: Формируем результат ═══
        output_parts = [
            f"🚀 Команда: {run_cmd}",
            f"📤 Exit code: {returncode}",
        ]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout[:3000]}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr[:3000]}")
        
        full_output = "\n\n".join(output_parts)
        
        if success:
            self._log(f"  ✅ Скрипт выполнен успешно (код {returncode})")
            self._context["_script_success"] = True
            self._context["_script_stdout"] = stdout
            return full_output
        else:
            self._log(f"  ❌ Скрипт упал (код {returncode})")
            
            # Читаем содержимое проблемных файлов для контекста патчера
            error_files = set()
            for line in (stderr + stdout):
                # Ищем имена файлов в traceback
                m = re.search(r'File "([^"]+)"', line if isinstance(line, str) else "")
                if m:
                    error_files.add(m.group(1))
            
            file_contents = {}
            for ef in list(error_files)[:5]:
                try:
                    p = os.path.join(self._tool_executor._root, ef) if not os.path.isabs(ef) else ef
                    if os.path.exists(p):
                        content = Path(p).read_text(encoding='utf-8', errors='replace')
                        rel = os.path.relpath(p, self._tool_executor._root)
                        file_contents[rel] = content
                except Exception:
                    pass
            
            # Сохраняем ошибку в контекст для Patcher
            error_context = {
                "command": run_cmd,
                "returncode": returncode,
                "stdout": stdout[:3000],
                "stderr": stderr[:3000],
                "files_on_disk": disk_files,
                "error_file_contents": file_contents,
            }
            self._context["_script_error"] = (
                f"КОМАНДА: {run_cmd}\n"
                f"КОД ВЫХОДА: {returncode}\n"
                f"STDERR:\n{stderr[:3000]}\n"
                f"STDOUT:\n{stdout[:3000]}"
            )
            self._context["_script_error_context"] = error_context
            self._context["_script_success"] = False
            
            # Добавляем содержимое файлов с ошибками
            if file_contents:
                fc_text = "\n\n".join(
                    f"=== {name} ===\n{content[:2000]}"
                    for name, content in file_contents.items()
                )
                full_output += f"\n\n📄 ФАЙЛЫ С ОШИБКАМИ:\n{fc_text}"
                self._context["_error_file_contents"] = file_contents
            
            # Устанавливаем статус ошибки — пойдёт по ON_FAILURE ребру к Patcher
            raise RuntimeError(full_output)
    
    # ── Iterative Patcher ─────────────────────────────────────

    async def _iterative_patch(self, node: AgentNode, timeout: int) -> str:
        """Patcher: читает ошибку, читает файлы, фиксит по одному."""
        import re
        
        error_text = self._context.get("_script_error", "Unknown error")
        error_files = self._context.get("_error_file_contents", {})
        disk_files = self._scan_disk_files()
        py_files = [f for f in disk_files if f.endswith('.py')]
        
        self._log(f"  🩹 Patcher: анализ ошибки...")
        self.signals.node_streaming.emit(node.id, f"\n🩹 Ошибка для исправления:\n{error_text[:500]}\n")
        
        # ═══ ШАГ 1: Спросить AI какие файлы нужно исправить ═══
        # Читаем ВСЕ .py файлы проекта
        all_file_contents = {}
        for pf in py_files[:15]:
            try:
                full = os.path.join(self._tool_executor._root, pf)
                content = Path(full).read_text(encoding='utf-8', errors='replace')
                all_file_contents[pf] = content
            except Exception:
                pass
        
        files_text = "\n\n".join(
            f"=== {name} ===\n{content}"
            for name, content in all_file_contents.items()
        )
        
        analyze_messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=(
                "You are a code debugger. Analyze the error and source files.\n"
                "Output ONLY a numbered list of files that need fixing and what to fix.\n"
                "Format:\n"
                "1. filename.py - what to fix\n"
                "2. filename2.py - what to fix\n"
                "Output NOTHING else."
            )),
            ChatMessage(role=MessageRole.USER, content=(
                f"ERROR LOG:\n{error_text[:2000]}\n\n"
                f"SOURCE FILES:\n{files_text[:6000]}\n\n"
                f"Which files need fixing?"
            )),
        ]
        
        analysis = await self._call_model(node, analyze_messages, timeout)
        self._log(f"  📋 Анализ: {analysis[:200]}")
        self.signals.node_streaming.emit(node.id, f"\n📋 Файлы для исправления:\n{analysis}\n")
        
        # Парсим список файлов
        files_to_fix = []
        for line in analysis.split('\n'):
            m = re.search(r'([\w\-\.\/]+\.py)', line)
            if m:
                fname = m.group(1)
                desc = line.split('-', 1)[1].strip() if '-' in line else ""
                if fname in all_file_contents:
                    files_to_fix.append((fname, desc))
        
        if not files_to_fix:
            # Фоллбэк: фиксим все файлы упомянутые в ошибке
            for fname in all_file_contents:
                if fname in error_text:
                    files_to_fix.append((fname, "mentioned in error"))
        
        if not files_to_fix:
            self._log(f"  ⚠ Не определено что фиксить, пробую все .py файлы")
            files_to_fix = [(f, "") for f in list(all_file_contents.keys())[:5]]
        
        # ═══ ШАГ 2: Фиксим файлы по одному ═══
        all_outputs = []
        fixed_count = 0
        
        for i, (filename, fix_desc) in enumerate(files_to_fix):
            if self._stop_requested:
                break
            
            original_content = all_file_contents.get(filename, "")
            if not original_content:
                continue
            
            self._log(f"  🔧 [{i+1}/{len(files_to_fix)}] Исправляю: {filename}")
            self.signals.node_streaming.emit(
                node.id, f"\n{'='*50}\n🔧 [{i+1}/{len(files_to_fix)}] {filename}\n{'='*50}\n"
            )
            
            fix_messages = [
                ChatMessage(role=MessageRole.SYSTEM, content=(
                    "You are a precise code patcher. Fix ONLY the broken parts.\n\n"
                    "Output format — for EACH change output a SEARCH/REPLACE block:\n"
                    "<<<SEARCH\n"
                    "exact original lines to find\n"
                    ">>>\n"
                    "<<<REPLACE\n"
                    "fixed lines\n"
                    ">>>\n\n"
                    "RULES:\n"
                    "- SEARCH block must match the original file EXACTLY (including whitespace)\n"
                    "- Make MINIMAL changes — fix only what's broken\n"
                    "- You can output multiple SEARCH/REPLACE blocks for multiple fixes\n"
                    "- If a NEW file is needed, output:\n"
                    "<<<NEW_FILE: path/filename.py\n"
                    "complete file content\n"
                    ">>>\n"
                    "- Do NOT output the entire file — only the changed parts"
                )),
                ChatMessage(role=MessageRole.USER, content=(
                    f"ERROR:\n{error_text[:1500]}\n\n"
                    f"FILE TO FIX: {filename}\n"
                    f"Problem: {fix_desc}\n\n"
                    f"ORIGINAL CODE:\n```\n{original_content}\n```\n\n"
                    f"Output SEARCH/REPLACE patches:"
                )),
            ]
            
            try:
                fix_response = await self._call_model(node, fix_messages, timeout)
                applied = 0
                
                # Парсим SEARCH/REPLACE блоки
                sr_pattern = re.compile(
                    r'<<<SEARCH\n(.*?)\n>>>\s*\n<<<REPLACE\n(.*?)\n>>>',
                    re.DOTALL
                )
                
                current_content = original_content
                for sr_match in sr_pattern.finditer(fix_response):
                    search_text = sr_match.group(1)
                    replace_text = sr_match.group(2)
                    
                    if search_text in current_content:
                        current_content = current_content.replace(search_text, replace_text, 1)
                        applied += 1
                        self._log(f"    ✓ Патч применён ({len(search_text.split(chr(10)))} строк)")
                    else:
                        # Пробуем с подрезанными пробелами
                        search_stripped = '\n'.join(l.rstrip() for l in search_text.split('\n'))
                        content_stripped = '\n'.join(l.rstrip() for l in current_content.split('\n'))
                        if search_stripped in content_stripped:
                            # Находим позицию в оригинале и заменяем
                            idx = content_stripped.find(search_stripped)
                            # Считаем строки до этой позиции
                            line_start = content_stripped[:idx].count('\n')
                            line_end = line_start + search_stripped.count('\n')
                            lines = current_content.split('\n')
                            lines[line_start:line_end+1] = replace_text.split('\n')
                            current_content = '\n'.join(lines)
                            applied += 1
                            self._log(f"    ✓ Патч применён (fuzzy, строки {line_start}-{line_end})")
                        else:
                            self._log(f"    ⚠ SEARCH блок не найден в файле")
                
                # Парсим NEW_FILE блоки
                nf_pattern = re.compile(r'<<<NEW_FILE:\s*([\w\-\.\/]+)\n(.*?)\n>>>', re.DOTALL)
                for nf_match in nf_pattern.finditer(fix_response):
                    new_fname = ToolExecutor._sanitize_path(nf_match.group(1))
                    new_content = nf_match.group(2)
                    await self._tool_executor.execute_tool("file_write", {
                        "path": new_fname,
                        "content": new_content,
                    })
                    applied += 1
                    self._log(f"    ✓ Создан новый файл: {new_fname}")
                
                # Фоллбэк: если не нашли SEARCH/REPLACE — ищем code-блок (полная замена)
                if applied == 0:
                    code_match = re.search(r'```\w*\n(.*?)\n```', fix_response, re.DOTALL)
                    if code_match:
                        current_content = code_match.group(1)
                        if current_content.strip().startswith('**'):
                            current_content = '\n'.join(current_content.split('\n')[1:])
                        applied = 1
                        self._log(f"    ⚠ Фоллбэк: полная замена файла")
                
                if applied > 0 and current_content != original_content:
                    await self._tool_executor.execute_tool("file_write", {
                        "path": filename,
                        "content": current_content,
                    })
                    fixed_count += 1
                    self._log(f"  ✅ {filename}: {applied} патч(ей) применено")
                    all_outputs.append(f"**PATCHED: {filename}** ({applied} changes)\n{fix_response}")
                elif applied == 0:
                    self._log(f"  ⚠ {filename}: SEARCH/REPLACE не совпал — полная перезапись...")
                    # Фоллбэк: просим AI переписать файл целиком
                    rewrite_messages = [
                        ChatMessage(role=MessageRole.SYSTEM, content=(
                            "You are a code fixer. Output ONLY the complete fixed file.\n"
                            "No explanations, no markdown headers — ONLY the code.\n"
                            "```python\n<complete fixed code>\n```"
                        )),
                        ChatMessage(role=MessageRole.USER, content=(
                            f"ERROR:\n{error_text[:1000]}\n\n"
                            f"FILE: {filename}\n"
                            f"CURRENT CONTENT:\n```\n{original_content}\n```\n\n"
                            f"Fix the error and output the COMPLETE fixed file."
                        )),
                    ]
                    try:
                        rewrite_resp = await self._call_model(node, rewrite_messages, timeout)
                        code_match = re.search(r'```\w*\n(.*?)\n```', rewrite_resp, re.DOTALL)
                        if code_match:
                            rewritten = code_match.group(1)
                            if rewritten.strip().startswith('**'):
                                rewritten = '\n'.join(rewritten.split('\n')[1:])
                            await self._tool_executor.execute_tool("file_write", {
                                "path": filename,
                                "content": rewritten,
                            })
                            fixed_count += 1
                            self._log(f"  ✅ {filename}: полная перезапись (фоллбэк)")
                            all_outputs.append(f"**REWRITTEN: {filename}**\n{rewrite_resp}")
                        else:
                            self._log(f"  ❌ {filename}: фоллбэк тоже не дал код")
                    except Exception as e2:
                        self._log(f"  ❌ {filename}: ошибка фоллбэка: {e2}")
                    
            except asyncio.TimeoutError:
                self._log(f"  ⏱ Таймаут при фиксе {filename}")
            except Exception as e:
                self._log(f"  ❌ Ошибка при фиксе {filename}: {e}")
        
        self._log(f"  🩹 Исправлено: {fixed_count}/{len(files_to_fix)} файлов")
        combined = "\n\n".join(all_outputs)
        return combined if combined else "No fixes applied"
    
    async def _auto_extract_files_from_response(self, node: AgentNode, response: str):
        """Извлечь файлы из markdown code-блоков и записать на диск.
        
        Ищет паттерны вида:
          # filename.py   (или ## filename.py, или **filename.py**)
```python
          content
```
        А также прямые file_write tool-блоки которые не были выполнены.
        """
        import re
        
        # Паттерн 1: блоки с именем файла в заголовке/комментарии перед кодом
        # Ловит форматы:
        #   **File 1: main.py**        ← LLM часто пишет так
        #   # main.py                  ← markdown заголовок
        #   **main.py**                ← жирный текст
        #   ## src/main.py             ← с путём
        file_pattern = re.compile(
            r'(?:^|\n)\s*'                                # начало строки
            r'(?:#+\s*|\*\*)?'                            # optional # или **
            r'(?:File\s*\d+[\s:：\-]*)?'                  # optional "File 1: " или "File 1 - "
            r'([\w\-\.\/\\]+\.(?:py|js|ts|json|yaml|yml|md|txt|html|css|toml|cfg|ini|sh|bat|sql))'  # filename
            r'(?:\*\*)?\s*\n'                             # optional ** и newline
            r'```\w*\n'                                   # ``` с optional language
            r'(.*?)'                                      # content
            r'\n```',                                     # closing ```
            re.DOTALL
        )
        
        created = []
        seen_files = set()
        
        for match in file_pattern.finditer(response):
            filename = match.group(1).strip()
            content = match.group(2)
            
            # Нормализуем путь через общий sanitizer
            filename = ToolExecutor._sanitize_path(filename)
            
            # Пропускаем дубликаты — берём ПОСЛЕДНЮЮ версию (перезаписываем)
            seen_files.add(filename)
            
            # Записываем файл
            try:
                result = await self._tool_executor.execute_tool("file_write", {
                    "path": filename,
                    "content": content,
                })
                if result.get("success"):
                    created.append(filename)
                    self._log(f"  📝 Авто-создан файл: {filename}")
                else:
                    self._log(f"  ⚠ Не удалось создать {filename}: {result.get('error')}")
            except Exception as e:
                self._log(f"  ⚠ Ошибка при создании {filename}: {e}")
        
        # Паттерн 2: Если ничего не нашли — ищем имена файлов в тексте рядом с блоками кода
        if not created:
            # Разбиваем по ``` блокам
            blocks = re.split(r'```\w*\n', response)
            for i in range(0, len(blocks) - 1):
                text_before = blocks[i]
                code_after = blocks[i + 1].split('\n```')[0] if '\n```' in blocks[i + 1] else ''
                if not code_after.strip():
                    continue
                
                # Ищем имя файла в последних 3 строках перед блоком кода
                last_lines = text_before.strip().split('\n')[-3:]
                fname = None
                for line in reversed(last_lines):
                    m = re.search(
                        r'([\w\-\.\/\\]+\.(?:py|js|ts|json|yaml|yml|md|txt|html|css|sql|toml|sh|bat))',
                        line
                    )
                    if m:
                        fname = m.group(1).strip()
                        break
                
                if fname:
                    fname = ToolExecutor._sanitize_path(fname)
                    seen_files.add(fname)
                    try:
                        result = await self._tool_executor.execute_tool("file_write", {
                            "path": fname,
                            "content": code_after,
                        })
                        if result.get("success"):
                            created.append(fname)
                            self._log(f"  📝 Авто-создан (паттерн 2): {fname}")
                    except Exception as e:
                        self._log(f"  ⚠ Ошибка при создании {fname}: {e}")
        
        if created:
            existing = self._context.get("created_files", [])
            self._context["created_files"] = list(set(existing + created))
            self._log(f"  📁 Авто-создано файлов: {len(created)} — {', '.join(created)}")
    
    # ── Auto-test ─────────────────────────────────────────────

    def _auto_test(self, node: AgentNode, output: str) -> bool:
        """Basic auto-test: check output is non-empty and not an error."""
        if not output or len(output.strip()) < 10:
            return False
        error_indicators = ["error", "failed", "exception", "traceback"]
        lower = output.lower()
        error_count = sum(1 for e in error_indicators if e in lower)
        return error_count < 3  # Allow some mentions but not too many

    # ── Graph navigation ──────────────────────────────────────

    def _find_entry_node(self) -> AgentNode | None:
        """Find the entry node (no incoming edges)."""
        if not self._workflow:
            return None
        incoming = set()
        for edge in self._workflow.edges:
            incoming.add(edge.target_id)

        for node_id, node in self._scene_nodes.items():
            if node_id not in incoming:
                return node
        # Fallback: first node
        if self._scene_nodes:
            return next(iter(self._scene_nodes.values()))
        return None

    def _find_next_node(self, current: AgentNode, result: NodeResult) -> AgentNode | None:
        """Determine the next node based on orchestration mode."""
        if not self._workflow:
            return None
        
        # IF_CONDITION: True → ON_SUCCESS, False → ON_FAILURE
        if current.agent_type == AgentType.IF_CONDITION:
            condition_true = self._context.get("_condition_result", False)
            edges = self._workflow.get_outgoing_edges(current.id)
            for edge in edges:
                if condition_true and edge.condition in (EdgeCondition.ON_SUCCESS, EdgeCondition.ALWAYS):
                    return self._scene_nodes.get(edge.target_id)
                if not condition_true and edge.condition == EdgeCondition.ON_FAILURE:
                    return self._scene_nodes.get(edge.target_id)
            # Фоллбэк: первое ALWAYS ребро
            for edge in edges:
                if edge.condition == EdgeCondition.ALWAYS:
                    return self._scene_nodes.get(edge.target_id)
            return None
        
        # SWITCH: маршрутизация по индексу совпавшего условия
        if current.agent_type == AgentType.SWITCH:
            matched_index = self._context.get("_switch_matched_index", -1)
            edges = self._workflow.get_outgoing_edges(current.id)
            edges_sorted = sorted(edges, key=lambda e: getattr(e, 'priority', 0), reverse=True)
            # Фильтруем только не-failure рёбра для нумерации
            success_edges = [e for e in edges_sorted if getattr(e, 'condition', EdgeCondition.ALWAYS) != EdgeCondition.ON_FAILURE]
            
            if matched_index >= 0 and matched_index < len(success_edges):
                return self._scene_nodes.get(success_edges[matched_index].target_id)
            
            # Default: последнее ребро или failure
            default_action = (getattr(current, 'snippet_config', {}) or {}).get('default_action', 'last_edge')
            if default_action == 'last_edge' and success_edges:
                return self._scene_nodes.get(success_edges[-1].target_id)
            elif default_action == 'failure':
                for e in edges_sorted:
                    if getattr(e, 'condition', EdgeCondition.ALWAYS) == EdgeCondition.ON_FAILURE:
                        return self._scene_nodes.get(e.target_id)
            return None
        
        # LOOP: маршрутизация по стрелкам
        # Completed (условие достигнуто) → зелёная стрелка (ON_SUCCESS / ALWAYS)
        # Not completed (ещё итерации) → красная стрелка (ON_FAILURE) → тело цикла → обратно в Loop
        if current.agent_type == AgentType.LOOP:
            loop_completed = self._context.get("_loop_completed", False)
            edges = self._workflow.get_outgoing_edges(current.id)
            if loop_completed:
                # Цикл завершён → зелёная стрелка (ON_SUCCESS / ALWAYS)
                for edge in edges:
                    if edge.condition in (EdgeCondition.ON_SUCCESS, EdgeCondition.ALWAYS):
                        target = self._scene_nodes.get(edge.target_id)
                        if target and target.id != current.id:
                            return target
                return None
            else:
                # Цикл продолжается → красная стрелка (ON_FAILURE) → тело цикла
                for edge in edges:
                    if edge.condition == EdgeCondition.ON_FAILURE:
                        return self._scene_nodes.get(edge.target_id)
                # Фоллбэк: если красной стрелки нет, идём по первой
                for edge in edges:
                    target = self._scene_nodes.get(edge.target_id)
                    if target and target.id != current.id:
                        return target
                return None

        mode = getattr(current, 'orchestration_mode', 'sequential')
        if not mode or mode == 'sequential' or mode == 'static':
            edges = self._workflow.get_outgoing_edges(current.id)
            edges_sorted = sorted(edges, key=lambda e: getattr(e, 'priority', 0), reverse=True)
            for edge in edges_sorted:
                cond = getattr(edge, 'condition', EdgeCondition.ALWAYS)
                # Skip ON_FAILURE edges here — they are handled by _find_failure_node
                if cond == EdgeCondition.ON_FAILURE:
                    continue
                if cond == EdgeCondition.ALWAYS:
                    return self._scene_nodes.get(edge.target_id)
                if cond == EdgeCondition.ON_SUCCESS and result.status == "success":
                    return self._scene_nodes.get(edge.target_id)
            # Fallback: first non-failure edge
            for edge in edges_sorted:
                if getattr(edge, 'condition', EdgeCondition.ALWAYS) != EdgeCondition.ON_FAILURE:
                    return self._scene_nodes.get(edge.target_id)
            return None

        elif mode == 'conditional':
            # Check edge conditions
            edges = self._workflow.get_outgoing_edges(current.id)
            for edge in edges:
                cond = getattr(edge, 'condition', None)
                if cond:
                    try:
                        if eval(str(cond), {"result": result.output, "context": self._context}):
                            return self._scene_nodes.get(edge.target_id)
                    except Exception:
                        pass
            # Fallback to first edge
            if edges:
                return self._scene_nodes.get(edges[0].target_id)
            return None

        elif mode == 'parallel':
            # TODO: execute all outgoing nodes in parallel
            # For now, sequential fallback
            edges = self._workflow.get_outgoing_edges(current.id)
            if edges:
                return self._scene_nodes.get(edges[0].target_id)
            return None

        # Default: sequential
        edges = self._workflow.get_outgoing_edges(current.id)
        if edges:
            return self._scene_nodes.get(edges[0].target_id)
        return None
    
    def _find_failure_node(self, current: AgentNode) -> AgentNode | None:
        """Find the node connected via ON_FAILURE edge."""
        if not self._workflow:
            return None
        edges = self._workflow.get_outgoing_edges(current.id)
        edges_sorted = sorted(edges, key=lambda e: getattr(e, 'priority', 0), reverse=True)
        for edge in edges_sorted:
            cond = getattr(edge, 'condition', EdgeCondition.ALWAYS)
            if cond == EdgeCondition.ON_FAILURE:
                return self._scene_nodes.get(edge.target_id)
        return None
    
    def _subst_vars(self, text: str) -> str:
        """Подставить ВСЕ переменные контекста в текст. Работает с любым типом значений."""
        if not isinstance(text, str):
            return text
        for key, val in self._context.items():
            if not key.startswith('_'):
                text = text.replace(f'{{{key}}}', str(val))
        return text
    
    # ══════════════════════════════════════════════════════
    #  STANDARD SNIPPETS (no AI, direct execution)
    # ══════════════════════════════════════════════════════

    async def _exec_code_snippet(self, node: AgentNode) -> str:
        """📜 Code Snippet: выполняет Python/Shell/Node код.
        
        Поддерживает:
        - Инжекцию переменных из таблицы Variables в контекст
        - Подстановку {var_name} в код
        - Типизацию переменных (string/int/float/bool/json/list)
        - Сохранение stdout и stderr в переменные
        - Рабочую папку, env vars, таймаут
        - Флаг "не возвращать значение"
        """
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        # ═══ 1. ИНЖЕКЦИЯ ПЕРЕМЕННЫХ ИЗ ТАБЛИЦЫ В КОНТЕКСТ ═══
        inject_vars = cfg.get('inject_vars', True)
        table_vars = cfg.get('_variables', [])
        
        # Если указан прикреплённый файл таблицы — дозагружаем из него
        attached_table = cfg.get('attached_table_path', '')
        if inject_vars and attached_table:
            try:
                import csv as _csv
                if os.path.isabs(attached_table):
                    table_path = attached_table
                else:
                    table_path = os.path.join(self._tool_executor._root, attached_table)
                
                if os.path.isfile(table_path):
                    with open(table_path, 'r', encoding='utf-8', errors='replace') as f:
                        sample = f.read(4096)
                        f.seek(0)
                        if '\t' in sample:
                            delim = '\t'
                        elif ';' in sample:
                            delim = ';'
                        else:
                            delim = ','
                        reader = _csv.reader(f, delimiter=delim)
                        rows = list(reader)
                    
                    if rows:
                        header_lower = [h.strip().lower() for h in rows[0]]
                        known = {'name', 'имя', 'variable', 'переменная', 'var', 'имя переменной'}
                        data_rows = rows[1:] if (known & set(header_lower)) else rows
                        file_vars = []
                        for r in data_rows:
                            if r and r[0].strip():
                                file_vars.append({
                                    'name': r[0].strip(),
                                    'value': r[1].strip() if len(r) > 1 else '',
                                    'type': r[2].strip().lower() if len(r) > 2 else 'string',
                                    'description': r[3].strip() if len(r) > 3 else ''
                                })
                        # Файловые переменные дополняют табличные (табличные приоритетнее)
                        existing_names = {v.get('name') for v in table_vars}
                        for fv in file_vars:
                            if fv['name'] not in existing_names:
                                table_vars.append(fv)
                        self._log(f"  📎 Загружено {len(file_vars)} переменных из {os.path.basename(table_path)}")
                else:
                    self._log(f"  ⚠ Прикреплённый файл таблицы не найден: {table_path}")
            except Exception as e:
                self._log(f"  ⚠ Ошибка загрузки прикреплённой таблицы: {e}")
        
        if inject_vars and table_vars:
            for var_def in table_vars:
                vname = var_def.get('name', '').strip()
                vvalue = var_def.get('value', '')
                vtype = var_def.get('type', 'string')
                if not vname:
                    continue
                # Подстановка переменных контекста в значение
                for ck, cv in self._context.items():
                    if not ck.startswith('_'):
                        vvalue = vvalue.replace(f'{{{ck}}}', str(cv))
                # Типизация значения
                try:
                    if vtype == 'int':
                        typed_val = str(int(vvalue)) if vvalue else '0'
                    elif vtype == 'float':
                        typed_val = str(float(vvalue)) if vvalue else '0.0'
                    elif vtype == 'bool':
                        typed_val = str(vvalue.lower() in ('true', '1', 'yes', 'да'))
                    elif vtype == 'json':
                        import json as _json
                        _json.loads(vvalue)  # Валидация
                        typed_val = vvalue
                    elif vtype == 'list':
                        typed_val = vvalue
                    else:
                        typed_val = vvalue
                except (ValueError, TypeError):
                    typed_val = vvalue
                    self._log(f"  ⚠ Переменная '{vname}': не удалось конвертировать в {vtype}, используется как string")
                
                self._context[vname] = typed_val
                self._log(f"  📥 Переменная: {vname} = {str(typed_val)[:80]}{'...' if len(str(typed_val)) > 80 else ''} ({vtype})")
        
        # ═══ 2. ОПРЕДЕЛЯЕМ ИСТОЧНИК КОДА ═══
        code_source = cfg.get('code_source', 'inline')
        
        if code_source == 'file':
            script_path = cfg.get('script_path', '')
            if not script_path:
                return "⚠ Не указан путь к файлу скрипта (заполните 'Путь к файлу' в настройках)"
            
            # Подстановка переменных в путь
            for key, val in self._context.items():
                if not key.startswith('_'):
                    script_path = script_path.replace(f'{{{key}}}', str(val))
            
            script_path = ToolExecutor._sanitize_path(script_path)
            full_path = os.path.join(self._tool_executor._root, script_path)
            
            if not os.path.isfile(full_path):
                return f"⚠ Файл не найден: {full_path}"
            
            try:
                code = Path(full_path).read_text(encoding='utf-8', errors='replace')
                self._log(f"  📖 Загружен скрипт: {script_path} ({len(code)} символов)")
            except Exception as e:
                return f"⚠ Ошибка чтения файла {script_path}: {e}"
        else:
            code = node.user_prompt_template or ""
            if not code.strip():
                return "⚠ Нет кода для выполнения (заполните User Prompt или выберите 'Файл скрипта')"
        
        language = cfg.get('language', 'python')
        snip_timeout = cfg.get('timeout', 60)
        save_output = cfg.get('save_output', False)
        output_var = cfg.get('output_var', 'snippet_result')
        no_return = cfg.get('no_return', False)
        save_stderr = cfg.get('save_stderr', False)
        stderr_var = cfg.get('stderr_var', 'snippet_error')
        working_dir = cfg.get('working_dir', '')
        env_vars_raw = cfg.get('env_vars', '')
        
        self._log(f"  📜 Выполняю {language} код ({len(code)} симв)...")
        
        # ═══ 3. ПОДСТАНОВКА ПЕРЕМЕННЫХ КОНТЕКСТА В КОД ═══
        for key, val in self._context.items():
            if not key.startswith('_'):
                code = code.replace(f'{{{key}}}', str(val))
        
        # ═══ 4. ПАРСИНГ ENV VARS ═══
        env_dict = {}
        if env_vars_raw.strip():
            for line in env_vars_raw.strip().splitlines():
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    # Подстановка переменных в env тоже
                    for ck, cv in self._context.items():
                        if not ck.startswith('_'):
                            v = v.replace(f'{{{ck}}}', str(cv))
                    env_dict[k.strip()] = v.strip()
        
        # ═══ 5. ВЫПОЛНЕНИЕ ═══
        exec_params = {"timeout": snip_timeout}
        if working_dir:
            for ck, cv in self._context.items():
                if not ck.startswith('_'):
                    working_dir = working_dir.replace(f'{{{ck}}}', str(cv))
            exec_params["cwd"] = working_dir
        if env_dict:
            exec_params["env"] = env_dict
        
        if language == "shell":
            result = await self._tool_executor.execute_tool("shell_exec", {
                "command": code,
                **exec_params,
            })
        elif language == "node":
            # Записываем код во временный файл для корректного запуска
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                result = await self._tool_executor.execute_tool("shell_exec", {
                    "command": f'node "{tmp_path}"',
                    **exec_params,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        elif language in ("cpp", "csharp", "java", "go", "ruby", "php", "powershell", "batch"):
            import tempfile, sys as _sys
            _ext_map = {
                "cpp": ".cpp", "csharp": ".cs", "java": ".java",
                "go": ".go", "ruby": ".rb", "php": ".php",
                "powershell": ".ps1", "batch": ".bat"
            }
            _run_map = {
                "cpp": None,        # требует компиляции — shell
                "csharp": None,     # dotnet-script или roslyn
                "java": None,       # javac+java
                "go": "go run",
                "ruby": "ruby",
                "php": "php",
                "powershell": "powershell -ExecutionPolicy Bypass -File",
                "batch": "",
            }
            _suffix = _ext_map[language]
            with tempfile.NamedTemporaryFile(mode='w', suffix=_suffix, delete=False, encoding='utf-8') as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                runner = _run_map.get(language, "")
                if language == "batch":
                    shell_cmd = f'"{tmp_path}"'
                elif runner:
                    shell_cmd = f'{runner} "{tmp_path}"'
                else:
                    # Fallback: shell пытается запустить напрямую
                    shell_cmd = f'"{tmp_path}"'
                result = await self._tool_executor.execute_tool("shell_exec", {
                    "command": shell_cmd,
                    **exec_params,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            result = await self._tool_executor.execute_tool("code_execute", {
                "code": code,
                **exec_params,
            })
        
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        success = result.get("success", False)
        
        # ═══ 6. СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ═══
        output = f"📜 Code Snippet: exit={result.get('returncode', '?')}\n"
        
        if stdout:
            output += f"STDOUT:\n{stdout[:3000]}\n"
            self._context["_snippet_stdout"] = stdout
            if save_output and not no_return:
                self._context[output_var] = stdout.strip()
                self._log(f"  📝 Сохранено в переменную: {output_var} = {stdout.strip()[:100]}")
        
        if stderr:
            output += f"STDERR:\n{stderr[:2000]}\n"
            self._context["_snippet_stderr"] = stderr
            if save_stderr:
                self._context[stderr_var] = stderr.strip()
                self._log(f"  📝 stderr → {stderr_var}")
        
        # Обновляем переменные таблицы в контексте после выполнения
        # (если скрипт мог их изменить через stdout-протокол SET:name=value)
        if stdout:
            for line in stdout.splitlines():
                if line.startswith("SET:") and "=" in line[4:]:
                    set_key, _, set_val = line[4:].partition("=")
                    self._context[set_key.strip()] = set_val.strip()
                    self._log(f"  📝 SET из stdout: {set_key.strip()} = {set_val.strip()[:60]}")
        
        if not success:
            raise RuntimeError(output)
        
        self._log(f"  ✅ Code Snippet выполнен")
        return output

    async def _exec_if_condition(self, node: AgentNode) -> str:
        """❓ IF Condition: визуальный конструктор условий + свободный Python режим."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        condition_mode = cfg.get('condition_mode', 'visual')
        negate = cfg.get('negate', False)
        log_result = cfg.get('log_result', True)
        
        if condition_mode == 'expression':
            # === СВОБОДНЫЙ РЕЖИМ: Python выражение ===
            expr = node.user_prompt_template or "False"
            # Подстановка переменных (все типы → str)
            for key, val in self._context.items():
                if not key.startswith('_'):
                    expr = expr.replace(f'{{{key}}}', str(val))
            
            if log_result:
                self._log(f"  ❓ Python выражение: {expr[:200]}")
            
            try:
                result = eval(expr, {"__builtins__": {}}, {
                    "ctx": self._context, "context": self._context,
                    "len": len, "int": int, "str": str, "bool": bool,
                    "float": float, "list": list, "dict": dict,
                    "True": True, "False": False, "None": None,
                })
                is_true = bool(result)
            except Exception as e:
                self._log(f"  ⚠ Ошибка вычисления: {e}")
                is_true = False
        else:
            # === ВИЗУАЛЬНЫЙ РЕЖИМ: конструктор условий ===
            left_raw = cfg.get('left_operand', '')
            operator = cfg.get('operator', 'eq')
            right_raw = cfg.get('right_operand', '')
            compare_as = cfg.get('compare_as', 'auto')
            case_sensitive = cfg.get('case_sensitive', True)
            chain_logic = cfg.get('chain_logic', 'none')
            extra_raw = cfg.get('extra_conditions', '')
            
            # Подстановка переменных контекста (все типы → str)
            def subst(s):
                if not isinstance(s, str):
                    return s
                for k, v in self._context.items():
                    if not k.startswith('_'):
                        s = s.replace(f'{{{k}}}', str(v))
                return s
            
            left = subst(left_raw)
            right = subst(right_raw)
            
            def compare_pair(l, r, op, cmp_as, cs):
                """Сравнить два значения по оператору."""
                # Типизация
                if cmp_as == 'number':
                    try:
                        l_val, r_val = float(l), float(r)
                    except (ValueError, TypeError):
                        l_val, r_val = l, r
                elif cmp_as == 'boolean':
                    l_val = l.lower() in ('true', '1', 'yes', 'да') if isinstance(l, str) else bool(l)
                    r_val = r.lower() in ('true', '1', 'yes', 'да') if isinstance(r, str) else bool(r)
                elif cmp_as == 'auto':
                    # Пробуем как числа
                    try:
                        l_val, r_val = float(l), float(r)
                    except (ValueError, TypeError):
                        l_val, r_val = l, r
                else:
                    l_val, r_val = str(l), str(r)
                
                # Регистр
                if not cs and isinstance(l_val, str) and isinstance(r_val, str):
                    l_val = l_val.lower()
                    r_val = r_val.lower()
                
                if op == 'eq': return l_val == r_val
                elif op == 'neq': return l_val != r_val
                elif op == 'gt': return l_val > r_val
                elif op == 'lt': return l_val < r_val
                elif op == 'gte': return l_val >= r_val
                elif op == 'lte': return l_val <= r_val
                elif op == 'contains': return str(r_val) in str(l_val)
                elif op == 'not_contains': return str(r_val) not in str(l_val)
                elif op == 'startswith': return str(l_val).startswith(str(r_val))
                elif op == 'endswith': return str(l_val).endswith(str(r_val))
                elif op == 'is_empty': return not str(l).strip()
                elif op == 'is_not_empty': return bool(str(l).strip())
                elif op == 'regex':
                    import re
                    flags = 0 if cs else re.IGNORECASE
                    return bool(re.search(str(r), str(l), flags))
                return False
            
            # Основное условие
            main_result = compare_pair(left, right, operator, compare_as, case_sensitive)
            
            op_symbols = {
                'eq': '==', 'neq': '!=', 'gt': '>', 'lt': '<', 'gte': '>=', 'lte': '<=',
                'contains': 'contains', 'not_contains': 'not contains',
                'startswith': 'startswith', 'endswith': 'endswith',
                'is_empty': 'is empty', 'is_not_empty': 'is not empty', 'regex': '~='
            }
            if log_result:
                self._log(f"  ❓ Условие: '{left}' {op_symbols.get(operator, operator)} '{right}' → {'✅ True' if main_result else '❌ False'}")
            
            # Доп. условия (цепочка)
            all_results = [main_result]
            if chain_logic != 'none' and extra_raw.strip():
                for line in extra_raw.strip().splitlines():
                    line = subst(line.strip())
                    if not line:
                        continue
                    # Парсим: left op right
                    parsed = False
                    for op_str, op_key in [('!=', 'neq'), ('>=', 'gte'), ('<=', 'lte'),
                                            ('==', 'eq'), ('>', 'gt'), ('<', 'lt'),
                                            (' contains ', 'contains'), (' startswith ', 'startswith'),
                                            (' endswith ', 'endswith'), (' regex ', 'regex')]:
                        if op_str in line:
                            parts = line.split(op_str, 1)
                            if len(parts) == 2:
                                el, er = parts[0].strip(), parts[1].strip()
                                # Убираем кавычки
                                for q in ['"', "'"]:
                                    el = el.strip(q)
                                    er = er.strip(q)
                                r = compare_pair(el, er, op_key, compare_as, case_sensitive)
                                all_results.append(r)
                                if log_result:
                                    self._log(f"  ❓ Доп: '{el}' {op_str.strip()} '{er}' → {'✅' if r else '❌'}")
                                parsed = True
                                break
                    if not parsed and line:
                        # Пробуем как Python expression
                        try:
                            r = bool(eval(line, {"__builtins__": {}}, {
                                "ctx": self._context, "context": self._context,
                                "True": True, "False": False, "None": None,
                                "len": len, "int": int, "str": str, "float": float,
                            }))
                            all_results.append(r)
                            if log_result:
                                self._log(f"  ❓ Доп (eval): '{line[:60]}' → {'✅' if r else '❌'}")
                        except Exception as e:
                            self._log(f"  ⚠ Ошибка в доп. условии '{line[:60]}': {e}")
                            all_results.append(False)
            
            # Объединение
            if chain_logic == 'and':
                is_true = all(all_results)
            elif chain_logic == 'or':
                is_true = any(all_results)
            else:
                is_true = main_result
        
        # Инверсия
        if negate:
            is_true = not is_true
            if log_result:
                self._log(f"  🔄 Инвертировано → {'✅ True' if is_true else '❌ False'}")
        
        if log_result:
            self._log(f"  ❓ Итоговый результат: {'✅ True → зелёная ветка' if is_true else '❌ False → красная ветка'}")
        
        self._context["_condition_result"] = is_true
        
        if not is_true:
            # НЕ бросаем RuntimeError — это не ошибка, а ветвление
            # _find_next_node маршрутизирует по ON_FAILURE (красная стрелка)
            return f"❌ Условие ЛОЖНО"
        
        return f"✅ Условие ИСТИННО"

    async def _exec_loop(self, node: AgentNode, timeout: int) -> str:
        """🔁 Loop: ОДИН шаг цикла. Каждый вызов = одна итерация.
        Возврат в цикл осуществляется через граф (красная стрелка → тело → обратно в Loop).
        Завершение цикла — выход по зелёной стрелке (ON_SUCCESS/ALWAYS)."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        loop_type = cfg.get('loop_type', 'count')
        max_loops = cfg.get('max_iterations', 3)
        exit_condition = cfg.get('exit_condition', '') or ''
        counter_var = cfg.get('counter_var', '_loop_iteration')
        iter_var = cfg.get('iter_var', '_loop_value')
        sleep_between = cfg.get('sleep_between', 0)
        data_var = cfg.get('data_var', '')
        file_path = cfg.get('file_path', '')
        inline_list = cfg.get('inline_list', '')
        separator = cfg.get('separator', '\n')
        shuffle_items = cfg.get('shuffle_items', False)
        
        # Подстановка переменных
        for k, v in self._context.items():
            if not k.startswith('_') and isinstance(v, str):
                exit_condition = exit_condition.replace(f'{{{k}}}', v)
                data_var = data_var.replace(f'{{{k}}}', v)
                file_path = file_path.replace(f'{{{k}}}', v)
        
        # ═══ Инициализация при ПЕРВОМ входе в цикл ═══
        loop_state_key = f"_loop_state_{node.id}"
        if loop_state_key not in self._context:
            # Первый вход — инициализируем
            items = None
            
            if loop_type == 'foreach_list':
                src = self._context.get(data_var.strip('{}').strip(), [])
                if isinstance(src, list):
                    items = list(src)
                elif isinstance(src, str):
                    items = [x.strip() for x in src.split(separator) if x.strip()]
                else:
                    items = [str(src)]
            elif loop_type == 'foreach_file':
                fpath = file_path
                if not os.path.isabs(fpath):
                    fpath = os.path.join(self._tool_executor._root, fpath)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        items = [line.strip() for line in f if line.strip()]
                    self._log(f"  📂 Загружено {len(items)} строк из {file_path}")
                except Exception as e:
                    self._log(f"  ⚠ Ошибка чтения файла: {e}")
                    items = []
            elif loop_type == 'foreach_inline':
                items = [x.strip() for x in inline_list.split(separator) if x.strip()]
            elif loop_type == 'while':
                items = None
                if not exit_condition:
                    exit_condition = 'False'
            
            if items is not None and shuffle_items:
                import random
                random.shuffle(items)
            
            total = len(items) if items is not None else max_loops
            if items is not None and max_loops > 0:
                total = min(total, max_loops)
            
            self._context[loop_state_key] = {
                'items': items,
                'total': total,
                'current_index': 0,
                'exit_condition': exit_condition,
                'exit_condition_raw': cfg.get('exit_condition', '') or '',
            }
            self._context["_loop_iteration"] = 0
            self._context["_loop_max"] = total
            self._context["_loop_total"] = total
            self._context["_loop_completed"] = False
            self._context["_loop_broke_error"] = False
            self._log(f"  🔁 Цикл ({loop_type}): до {total} итераций")
        
        # ═══ Получаем состояние цикла ═══
        state = self._context[loop_state_key]
        items = state['items']
        total = state['total']
        i = state['current_index']
        exit_cond = state['exit_condition']
        
        # ═══ Проверяем — цикл завершён? ═══
        if i >= total:
            # Все итерации пройдены — цикл завершён
            self._context["_loop_completed"] = True
            del self._context[loop_state_key]  # Очищаем состояние
            self._log(f"  ✅ Цикл завершён: {i} итераций выполнено")
            return f"🔁 Цикл завершён ({i} итераций)"
        
        # Проверяем условие выхода — динамическая подстановка актуальных переменных
        exit_cond_raw = state.get('exit_condition_raw', state['exit_condition'])
        if exit_cond_raw:
            try:
                # Подставляем текущие значения из контекста (меняются в теле цикла)
                exit_cond = exit_cond_raw
                for k, v in self._context.items():
                    if not k.startswith('_'):
                        exit_cond = exit_cond.replace(f'{{{k}}}', str(v))
                # Также подставляем из project_variables (видимые переменные проекта)
                pv = getattr(self, '_project_variables', None)
                if pv and isinstance(pv, dict):
                    for k, v in pv.items():
                        pval = v.get('value', v) if isinstance(v, dict) else str(v)
                        exit_cond = exit_cond.replace(f'{{{k}}}', str(pval))
                should_exit = eval(exit_cond, {"__builtins__": {}}, {
                    "ctx": self._context,
                    "context": self._context,
                    "i": i,
                    "iteration": i + 1,
                    "value": items[i] if items and i < len(items) else None,
                    "True": True, "False": False, "None": None,
                    "len": len, "int": int, "str": str, "bool": bool, "float": float,
                })
                if should_exit:
                    self._context["_loop_completed"] = True
                    del self._context[loop_state_key]
                    self._log(f"  🔁 Выход из цикла по условию на итерации {i+1}")
                    return f"🔁 Выход по условию (итерация {i+1})"
            except Exception as e:
                self._log(f"  ⚠ Ошибка в условии выхода: {e}")
        
        # ═══ Выполняем ОДНУ итерацию (устанавливаем переменные) ═══
        self._context[counter_var] = i + 1
        self._context["_loop_iteration"] = i + 1
        self._context["_loop_index"] = i
        
        if items is not None and i < len(items):
            self._context[iter_var] = items[i]
            self._context["_loop_value"] = items[i]
        
        self._log(f"  🔁 Итерация {i+1}/{total}" + (f" | {iter_var}={items[i][:50]}" if items and i < len(items) else ""))
        
        # Увеличиваем счётчик для следующего входа
        state['current_index'] = i + 1
        
        # Пауза между итерациями
        if sleep_between > 0 and i > 0:
            await asyncio.sleep(sleep_between)
        
        # Цикл НЕ завершён — нужна следующая итерация
        # _find_next_node направит по красной стрелке (ON_FAILURE) для продолжения
        self._context["_loop_completed"] = False
        raise RuntimeError("LOOP_CONTINUE")

    async def _exec_variable_set(self, node: AgentNode) -> str:
        cfg = getattr(node, 'snippet_config', {}) or {}
        operation = cfg.get('operation', 'set')
        var_name = cfg.get('var_name', cfg.get('name', '')).strip()
        
        # Извлечение значения — приоритет: var_value → value → user_prompt_template
        var_value = cfg.get('var_value')
        if var_value is None:
            var_value = cfg.get('value')
        if var_value is None:
            # Основное текстовое поле сниппета (только если оба выше не заданы вообще)
            var_value = getattr(node, 'user_prompt_template', '')
        if var_value is None:
            var_value = ''
            
        # Убираем фигурные скобки из имени переменной, если они есть
        var_name = var_name.strip('{}')
        
        # Выполняем подстановку других переменных (например, {var_2}) в значение
        if hasattr(self, '_context') and isinstance(var_value, str) and '{' in var_value:
            for k, v in self._context.items():
                if not k.startswith('_'):
                    var_value = var_value.replace(f'{{{k}}}', str(v))
                    
        step = cfg.get('step_value', 1)
        auto_type = cfg.get('auto_type', True)
        create_if_missing = cfg.get('create_if_missing', True)
        multi_set = cfg.get('multi_set', '')
        
        def subst(s):
            if not isinstance(s, str):
                return s
            for k, v in self._context.items():
                if not k.startswith('_'):
                    s = s.replace(f'{{{k}}}', str(v))
            return s
        
        def auto_convert(val):
            if not auto_type or not isinstance(val, str):
                return val
            v = val.strip()
            if v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
                try: return int(v)
                except ValueError: pass
            elif '.' in v and v.replace('.', '').replace('-', '').isdigit():
                try: return float(v)
                except ValueError: pass
            elif v.lower() in ('true', 'false'):
                return v.lower() == 'true'
            return val
        
        set_count = 0
        
        # ═══ 1. Одиночная операция (из полей var_name / var_value) ═══
        if var_name:
            # Убираем фигурные скобки если пользователь написал {var_1} вместо var_1
            var_name = var_name.strip().strip('{}').strip()
            # НЕ делаем subst на имени — это ИМЯ переменной, не значение
            var_value = subst(var_value)
            
            if operation == 'set':
                val = auto_convert(var_value)
                if create_if_missing or var_name in self._context:
                    self._context[var_name] = val
                    self._log(f"  📝 {var_name} = {val} ({type(val).__name__})")
                    set_count += 1
                    
                    # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                    if self._project_variables is not None:
                        if var_name in self._project_variables:
                            if isinstance(self._project_variables[var_name], dict):
                                self._project_variables[var_name]['value'] = str(val)
                            else:
                                self._project_variables[var_name] = str(val)
                        else:
                            # Создаём новую переменную в проекте
                            self._project_variables[var_name] = {
                                'value': str(val),
                                'default': '',
                                'type': 'string'
                            }
                            
                        # Гарантируем добавление в глобальный список (как в List Operation)
                        if hasattr(self, '_project_vars') and isinstance(self._project_vars, list):
                            if var_name not in self._project_vars:
                                self._project_vars.append(var_name)
                                
                        self._log(f"  📝 Синхронизировано с проектом: {var_name} = {str(val)[:60]}")
                        
                        # Безопасно обновляем UI
                        if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                            self.signals.variable_updated.emit(var_name, str(val))
                    
                else:
                    self._log(f"  ⚠ Переменная '{var_name}' не существует")
            elif operation == 'inc':
                cur = self._context.get(var_name, 0)
                try:
                    cur = int(cur) if not isinstance(cur, (int, float)) else cur
                except (ValueError, TypeError):
                    cur = 0
                new_val = cur + step
                self._context[var_name] = new_val
                self._sync_var_to_project(var_name, str(new_val))
                self._log(f"  📝 {var_name}: {cur} + {step} = {new_val}")
                set_count += 1
            elif operation == 'dec':
                cur = self._context.get(var_name, 0)
                try:
                    cur = int(cur) if not isinstance(cur, (int, float)) else cur
                except (ValueError, TypeError):
                    cur = 0
                new_val = cur - step
                self._context[var_name] = new_val
                self._sync_var_to_project(var_name, str(new_val))
                self._log(f"  📝 {var_name}: {cur} - {step} = {new_val}")
                set_count += 1
            elif operation == 'append':
                lst = self._context.get(var_name, [])
                if isinstance(lst, str):
                    lst = [lst] if lst else []
                if not isinstance(lst, list):
                    lst = [lst]
                lst.append(auto_convert(var_value))
                self._context[var_name] = lst
                self._sync_var_to_project(var_name, str(lst))
                self._log(f"  📝 {var_name} += {var_value} (размер: {len(lst)})")
                set_count += 1
            elif operation == 'delete':
                if var_name in self._context:
                    del self._context[var_name]
                    # Обнуляем в project_variables (не удаляем — переменная остаётся в UI)
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        if var_name in self._project_variables:
                            if isinstance(self._project_variables[var_name], dict):
                                self._project_variables[var_name]['value'] = ''
                            else:
                                self._project_variables[var_name] = ''
                            if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                                self.signals.variable_updated.emit(var_name, '')
                    self._log(f"  📝 Удалено: {var_name}")
                    set_count += 1
        
        # ═══ 2. Множественная установка (из текстового поля multi_set) ═══
        multi_text = subst(multi_set) or subst(node.user_prompt_template or "")
        if multi_text.strip():
            for line in multi_text.split('\n'):
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = subst(value.strip().strip('"').strip("'"))
                
                if not create_if_missing and key not in self._context:
                    self._log(f"  ⚠ '{key}' не существует, пропуск")
                    continue
                
                self._context[key] = auto_convert(value)
                self._sync_var_to_project(key, str(self._context[key]))
                self._log(f"  📝 {key} = {self._context[key]} ({type(self._context[key]).__name__})")
                set_count += 1
        
        # ═══ 3. Из таблицы переменных (Variables) ═══
        table_vars = cfg.get('_variables', [])
        if table_vars:
            for var_def in table_vars:
                vname = var_def.get('name', '').strip()
                vvalue = subst(var_def.get('value', ''))
                if not vname:
                    continue
                
                if operation == 'set' or not var_name:
                    self._context[vname] = auto_convert(vvalue)
                    self._sync_var_to_project(vname, str(self._context[vname]))
                    self._log(f"  📝 (таблица) {vname} = {self._context[vname]}")
                    set_count += 1
                elif operation == 'inc':
                    cur = self._context.get(vname, 0)
                    try: cur = int(cur)
                    except: cur = 0
                    new_v = cur + (int(vvalue) if vvalue else step)
                    self._context[vname] = new_v
                    self._sync_var_to_project(vname, str(new_v))
                    set_count += 1
                elif operation == 'dec':
                    cur = self._context.get(vname, 0)
                    try: cur = int(cur)
                    except: cur = 0
                    new_v = cur - (int(vvalue) if vvalue else step)
                    self._context[vname] = new_v
                    self._sync_var_to_project(vname, str(new_v))
                    set_count += 1
        
        # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
        if set_count > 0 and self._project_variables is not None:
            # Определяем какие переменные были изменены
            changed_vars = []
            if var_name:
                changed_vars.append(var_name)
            # Из multi_set
            multi_text = subst(multi_set) or subst(node.user_prompt_template or "")
            if multi_text.strip():
                for line in multi_text.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, _, _ = line.partition('=')
                    key = key.strip()
                    if key:
                        changed_vars.append(key)
            # Из таблицы переменных
            if table_vars:
                for var_def in table_vars:
                    vname = var_def.get('name', '').strip()
                    if vname:
                        changed_vars.append(vname)
            
            # Синхронизируем все изменённые переменные
            for vname in changed_vars:
                if vname in self._context:
                    vval = self._context[vname]
                    if isinstance(self._project_variables, dict):
                        if vname in self._project_variables:
                            if isinstance(self._project_variables[vname], dict):
                                self._project_variables[vname]['value'] = str(vval)
                            else:
                                self._project_variables[vname] = str(vval)
                        else:
                            # Создаём новую переменную
                            self._project_variables[vname] = {
                                'value': str(vval),
                                'default': '',
                                'type': 'string'
                            }
                            
                        # Гарантируем добавление в глобальный список (как в List Operation)
                        if hasattr(self, '_project_vars') and isinstance(self._project_vars, list):
                            if vname not in self._project_vars:
                                self._project_vars.append(vname)
                                
                        self._log(f"  📝 Синхронизировано с проектом: {vname} = {str(vval)[:60]}")
                        
                        # Безопасно обновляем UI
                        if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                            self.signals.variable_updated.emit(vname, str(vval))
        
        return f"📝 Установлено {set_count} переменных"

    async def _exec_http_request(self, node: AgentNode) -> str:
        """🌐 HTTP Request: отправляет запрос (стиль ZennoPoster)."""
        import aiohttp
        
        cfg = getattr(node, 'snippet_config', {}) or {}
        url = cfg.get('url', '') or node.user_prompt_template or ""
        method = cfg.get('method', 'GET')
        referer = cfg.get('referer', '')
        encoding = cfg.get('encoding', 'utf-8')
        req_timeout = cfg.get('timeout', 30)
        load_content = cfg.get('load_content', 'content_only')
        
        # Доп. настройки
        follow_redirects = cfg.get('follow_redirects', True)
        max_redirects = cfg.get('max_redirects', 5)
        use_original_url = cfg.get('use_original_url', False)
        headers_profile = cfg.get('headers_profile', 'current')
        use_cookies = cfg.get('use_cookies', True)
        verify_ssl = cfg.get('verify_ssl', True)
        
        # Тело и заголовки
        headers_text = cfg.get('headers', '')
        body_text = cfg.get('body', cfg.get('body_template', ''))
        content_type = cfg.get('content_type', '')
        
        # Сохранение
        save_response = cfg.get('save_response', True)
        response_var = cfg.get('response_var', 'http_response')
        save_status = cfg.get('save_status', True)
        status_var = cfg.get('status_var', 'http_status')
        save_headers_var = cfg.get('save_headers_var', '')
        save_to_file = cfg.get('save_to_file', '')
        
        # Подставляем переменные
        for key, val in self._context.items():
            if not key.startswith('_'):
                url = url.replace(f'{{{key}}}', str(val))
                referer = referer.replace(f'{{{key}}}', str(val))
                body_text = body_text.replace(f'{{{key}}}', str(val)) if body_text else ''
                headers_text = headers_text.replace(f'{{{key}}}', str(val)) if headers_text else ''
        
        if not url:
            return "⚠ URL не указан"
        
        self._log(f"  🌐 {method} {url[:80]}")
        
        try:
            # Парсим заголовки
            headers = {}
            for line in headers_text.split('\n'):
                if ':' in line:
                    k, _, v = line.partition(':')
                    headers[k.strip()] = v.strip()
            
            if referer:
                headers['Referer'] = referer
            if content_type and content_type not in headers.values():
                headers['Content-Type'] = content_type
            
            timeout_obj = aiohttp.ClientTimeout(total=req_timeout)
            connector = aiohttp.TCPConnector(ssl=verify_ssl)
            
            kwargs = {}
            if headers:
                kwargs['headers'] = headers
            if body_text and method in ("POST", "PUT", "PATCH"):
                kwargs['data'] = body_text
            if not follow_redirects:
                kwargs['allow_redirects'] = False
            elif max_redirects:
                kwargs['max_redirects'] = max_redirects
            
            async with aiohttp.ClientSession(timeout=timeout_obj, connector=connector) as session:
                async with session.request(method, url, **kwargs) as resp:
                    status = resp.status
                    resp_headers = dict(resp.headers)
                    final_url = str(resp.url)
                    
                    # Загрузка контента в зависимости от режима
                    if load_content in ('content_only', 'headers_and_content'):
                        try:
                            body = await resp.text(encoding=encoding)
                        except Exception:
                            body = await resp.text()
                    elif load_content == 'as_file':
                        raw_bytes = await resp.read()
                        if save_to_file:
                            fpath = save_to_file
                            if not os.path.isabs(fpath):
                                fpath = os.path.join(self._tool_executor._root, fpath)
                            os.makedirs(os.path.dirname(fpath) or '.', exist_ok=True)
                            with open(fpath, 'wb') as f:
                                f.write(raw_bytes)
                            body = f"Сохранено {len(raw_bytes)} байт → {save_to_file}"
                            self._log(f"  💾 Файл сохранён: {fpath}")
                        else:
                            body = f"[binary: {len(raw_bytes)} bytes]"
                    elif load_content == 'headers_only':
                        body = ''
                    else:
                        body = await resp.text()
                    
                    # Сохраняем результаты
                    self._context["_http_status"] = str(status)
                    self._context["_http_url"] = url
                    self._context["_http_final_url"] = final_url
                    
                    if save_status:
                        self._context[status_var] = str(status)
                        self._sync_var_to_project(status_var, str(status))
                    
                    if save_response and load_content != 'headers_only':
                        self._context[response_var] = body[:10000]
                        self._sync_var_to_project(response_var, body[:10000])
                    
                    if load_content in ('headers_only', 'headers_and_content', 'as_file_and_headers'):
                        hdr_text = '\n'.join(f'{k}: {v}' for k, v in resp_headers.items())
                        self._context["_http_headers"] = hdr_text
                        if save_headers_var:
                            self._context[save_headers_var] = hdr_text
                    
                    output = f"🌐 {method} {url}\n📤 Status: {status}\nBody ({len(body)} chars):\n{body[:2000]}"
                    self._log(f"  ✅ HTTP {status} ({len(body)} chars)")
                    
                    if status >= 400:
                        raise RuntimeError(output)
                    return output
                    
        except aiohttp.ClientError as e:
            error_msg = f"🌐 HTTP Error: {e}"
            self._context["_http_error"] = str(e)
            raise RuntimeError(error_msg)

    async def _exec_delay(self, node: AgentNode) -> str:
        """⏳ Delay: ждёт N секунд с поддержкой рандомизации и прерыванием."""
        import random
        
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        seconds = cfg.get('seconds', 5)
        try:
            seconds = float(seconds)
        except (ValueError, TypeError):
            seconds = 5.0
        randomize_raw = cfg.get('randomize', False)
        # Защита от строковых значений из JSON ("false", "0", "" → False)
        if isinstance(randomize_raw, str):
            randomize = randomize_raw.lower() in ('true', '1', 'yes')
        else:
            randomize = bool(randomize_raw)
        random_range = cfg.get('random_range', 50) / 100.0
        
        if randomize:
            variation = seconds * random_range
            seconds = seconds + random.uniform(-variation, variation)
            seconds = max(0.1, seconds)  # минимум 0.1 сек
        
        self._log(f"  ⏳ Пауза {seconds:.1f} сек...")
        
        # Исправлено: используем правильный флаг остановки
        elapsed = 0
        interval = 0.5
        while elapsed < seconds:
            if self._stop_requested:  # ← ИСПРАВЛЕНО: _stopped → _stop_requested
                self._log(f"  ⏹ Delay прерван на {elapsed:.1f}s из {seconds}s")
                return f"⏹ Пауза прервана на {elapsed:.1f}s из {seconds}s"
            await asyncio.sleep(min(interval, seconds - elapsed))
            elapsed += interval
        
        self._log(f"  ⏳ Готово")
        return f"⏳ Пауза {seconds:.1f} сек завершена"

    async def _exec_log_message(self, node: AgentNode) -> str:
        """📋 Log Message: выводит сообщение в лог с расширенными настройками."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        # Приоритет: 1) snippet_config.message, 2) user_prompt_template, 3) fallback
        msg = cfg.get('message', '') or node.user_prompt_template or "Empty log message"
        level = cfg.get('level', 'INFO')
        write_console = cfg.get('write_to_console', True)
        write_file = cfg.get('write_to_file', False)
        log_file = cfg.get('log_file', 'execution.log')
        include_timestamp = cfg.get('include_timestamp', True)
        include_node_name = cfg.get('include_node_name', True)
        add_newline = cfg.get('add_newline', False)
        
        # Подставляем переменные
        for key, val in self._context.items():
            if not key.startswith('_'):
                msg = msg.replace(f'{{{key}}}', str(val))
        
        # Формируем префикс
        prefix_parts = []
        if include_timestamp:
            from datetime import datetime
            prefix_parts.append(datetime.now().strftime("%H:%M:%S"))
        if include_node_name:
            prefix_parts.append(f"[{node.name}]")
        
        prefix = " ".join(prefix_parts)
        if prefix:
            prefix += " "
        
        full_msg = f"{prefix}{msg}"
        if add_newline:
            full_msg += "\n"
        
        # Вывод в консоль/лог UI
        if write_console:
            level_icons = {"DEBUG": "🔍", "INFO": "ℹ", "WARNING": "⚠", "ERROR": "❌"}
            icon = level_icons.get(level, "📋")
            self._log(f"  {icon} [{level}] {full_msg}")
            self.signals.node_streaming.emit(node.id, f"\n{icon} [{level}] {full_msg}\n")
        
        # Запись в файл — ВСЕГДА по абсолютному пути
        if write_file and log_file:
            try:
                from datetime import datetime
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_line = f"[{ts}] [{level}] [{node.name}] {msg}\n"
                
                # Определяем полный путь
                if os.path.isabs(log_file):
                    log_path = log_file
                else:
                    root = getattr(self._tool_executor, '_root', '') or os.getcwd()
                    log_path = os.path.join(root, log_file)
                
                # Создаём папку если нужно
                log_dir = os.path.dirname(log_path)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(log_line)
                    f.flush()
                
                self._log(f"  📝 Записано в файл: {log_path}")
                    
            except Exception as e:
                self._log(f"  ⚠ Не удалось записать в {log_file}: {e}")
                import traceback
                self._log(f"  ⚠ {traceback.format_exc()}")
        
        return f"{level}: {full_msg}"
    
    async def _exec_switch(self, node: AgentNode) -> str:
        """🔀 Switch: множественный выбор по значению переменной."""
        import re
        
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        switch_var = cfg.get('switch_variable', '')
        compare_mode = cfg.get('compare_mode', 'eq')
        case_sensitive = cfg.get('case_sensitive', False)
        cases_raw = cfg.get('cases', '') or node.user_prompt_template or ''
        default_action = cfg.get('default_action', 'last_edge')
        log_comparison = cfg.get('log_comparison', True)
        
        # ═══ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: очищаем имя переменной ═══
        clean_var_name = switch_var.strip('{}').strip()
        
        # Получаем значение по очищенному имени
        actual_value = str(self._context.get(clean_var_name, ''))
        
        if log_comparison:
            self._log(f"  🔀 Switch: переменная '{clean_var_name}' = '{actual_value[:100]}'")
            self._log(f"  🔀 Режим: {compare_mode}, case_sensitive={case_sensitive}")
        
        # Парсим условия — разделяем по строкам
        cases = [line.strip() for line in cases_raw.replace('\r\n', '\n').split('\n') if line.strip()]
        
        if not cases:
            self._log(f"  ⚠ Switch: нет условий для сравнения")
            return "⚠ Switch: пустой список условий"
        
        # Подставляем переменные в каждое условие (для динамических кейсов)
        for i, case in enumerate(cases):
            for key, val in self._context.items():
                if not key.startswith('_'):
                    cases[i] = cases[i].replace(f'{{{key}}}', str(val))
        
        if log_comparison:
            self._log(f"  🔀 Кейсы для сравнения: {cases}")
        
        # Сравнение
        matched_index = -1
        
        for i, case_val in enumerate(cases):
            match = False
            
            if compare_mode == 'eq':
                if case_sensitive:
                    match = (actual_value == case_val)
                else:
                    match = (actual_value.lower() == case_val.lower())
                    
            elif compare_mode == 'neq':
                if case_sensitive:
                    match = (actual_value != case_val)
                else:
                    match = (actual_value.lower() != case_val.lower())
                    
            elif compare_mode == 'contains':
                if case_sensitive:
                    match = (case_val in actual_value)
                else:
                    match = (case_val.lower() in actual_value.lower())
                    
            elif compare_mode == 'not_contains':
                if case_sensitive:
                    match = (case_val not in actual_value)
                else:
                    match = (case_val.lower() not in actual_value.lower())
                    
            elif compare_mode == 'startswith':
                if case_sensitive:
                    match = actual_value.startswith(case_val)
                else:
                    match = actual_value.lower().startswith(case_val.lower())
                    
            elif compare_mode == 'endswith':
                if case_sensitive:
                    match = actual_value.endswith(case_val)
                else:
                    match = actual_value.lower().endswith(case_val.lower())
                    
            elif compare_mode == 'regex':
                try:
                    flags = 0 if case_sensitive else re.IGNORECASE
                    match = bool(re.search(case_val, actual_value, flags))
                except re.error as e:
                    self._log(f"  ⚠ Regex ошибка в условии {i+1}: {e}")
                    match = False
                    
            elif compare_mode == 'numeric':
                try:
                    match = (float(actual_value) == float(case_val))
                except ValueError:
                    match = False
            
            if log_comparison:
                status = "✅ MATCH" if match else "❌ no match"
                self._log(f"  🔀 [{i+1}] '{actual_value[:30]}' == '{case_val[:30]}' → {status}")
            
            if match:
                matched_index = i
                break
        
        # Маршрутизация
        self._context["_switch_matched_index"] = matched_index
        self._context["_switch_cases_count"] = len(cases)
        self._context["_switch_value"] = actual_value
        
        if matched_index >= 0:
            self._log(f"  ✅ Switch: совпадение #{matched_index + 1}: '{cases[matched_index]}'")
            return f"🔀 Switch: совпадение #{matched_index + 1} ('{cases[matched_index]}')"
        else:
            self._log(f"  🔀 Switch: нет совпадений → Default ({default_action})")
            if default_action == 'failure':
                raise RuntimeError(f"Switch: нет совпадения для '{actual_value}'")
            elif default_action == 'stop':
                raise RuntimeError(f"STOP: Switch: нет совпадения для '{actual_value}'")
            return f"🔀 Switch: Default (нет совпадения для '{actual_value}')"
            
    async def _exec_good_end(self, node: AgentNode) -> str:
        """✅ Good End: успешное завершение ветки."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        log_success = cfg.get('log_success', True)
        save_report = cfg.get('save_report', False)
        report_file = cfg.get('report_file', 'good_end_report.txt')
        include_context = cfg.get('include_context', True)
        include_timing = cfg.get('include_timing', True)
        custom_message = cfg.get('custom_message', '')
        return_to_start = cfg.get('return_to_start', False)
        
        # Подстановка переменных в сообщение
        for key, val in self._context.items():
            if not key.startswith('_'):
                custom_message = custom_message.replace(f'{{{key}}}', str(val))
                report_file = report_file.replace(f'{{{key}}}', str(val))
        
        import time as _time
        output_parts = ["✅ Good End — успешное завершение"]
        
        if custom_message:
            output_parts.append(f"Сообщение: {custom_message}")
        
        if include_timing:
            elapsed = self._context.get('_elapsed_time', 'N/A')
            output_parts.append(f"Время выполнения: {elapsed}")
        
        success_count = sum(1 for r in self._results.values() if r.status == "success")
        fail_count = sum(1 for r in self._results.values() if r.status == "error")
        output_parts.append(f"Узлов выполнено: {success_count} ✅ / {fail_count} ❌")
        
        if log_success:
            for part in output_parts:
                self._log(f"  ✅ {part}")
        
        # Сохранение отчёта
        if save_report:
            try:
                report_path = os.path.join(self._tool_executor._root, report_file)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                report_lines = [f"=== GOOD END: {timestamp} ==="]
                report_lines.extend(output_parts)
                
                if include_context:
                    report_lines.append("\n--- Контекст ---")
                    for k, v in self._context.items():
                        if not k.startswith('_'):
                            report_lines.append(f"  {k} = {str(v)[:200]}")
                
                with open(report_path, 'a', encoding='utf-8') as f:
                    f.write('\n'.join(report_lines) + '\n\n')
                self._log(f"  📄 Отчёт сохранён: {report_file}")
            except Exception as e:
                self._log(f"  ⚠ Ошибка сохранения отчёта: {e}")
        
        self._context["_good_end_reached"] = True
        
        if return_to_start:
            self._context["_restart_requested"] = True
            self._log(f"  🔄 Запрошен перезапуск workflow")
        
        return '\n'.join(output_parts)

    async def _exec_bad_end(self, node: AgentNode) -> str:
        """🛑 Bad End: завершение с ошибкой — логирование и восстановление."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        log_error = cfg.get('log_error', True)
        save_error_log = cfg.get('save_error_log', True)
        error_log_file = cfg.get('error_log_file', 'error_log.txt')
        include_last_error = cfg.get('include_last_error', True)
        include_failed_node = cfg.get('include_failed_node', True)
        include_context_dump = cfg.get('include_context_dump', False)
        include_timestamp = cfg.get('include_timestamp', True)
        restore_data = cfg.get('restore_data', False)
        restore_var = cfg.get('restore_var', '')
        on_bad_end = cfg.get('on_bad_end', 'stop')
        max_restarts = cfg.get('max_restarts', 3)
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_error = self._context.get('_last_error', 'Неизвестная ошибка')
        failed_node = self._context.get('_last_failed_node', 'Неизвестный узел')
        
        output_parts = [f"🛑 Bad End — ошибка в workflow"]
        
        if include_timestamp:
            output_parts.append(f"Время: {timestamp}")
        if include_failed_node:
            output_parts.append(f"Ошибочный узел: {failed_node}")
        if include_last_error:
            output_parts.append(f"Ошибка: {str(last_error)[:500]}")
        
        if log_error:
            for part in output_parts:
                self._log(f"  🛑 {part}")
        
        # Сохранение лога ошибок
        if save_error_log:
            try:
                # Подстановка переменных
                for key, val in self._context.items():
                    if not key.startswith('_'):
                        error_log_file = error_log_file.replace(f'{{{key}}}', str(val))
                
                log_path = os.path.join(self._tool_executor._root, error_log_file)
                
                log_lines = [f"=== BAD END: {timestamp} ==="]
                log_lines.extend(output_parts)
                
                if include_context_dump:
                    log_lines.append("\n--- Дамп контекста ---")
                    for k, v in self._context.items():
                        log_lines.append(f"  {k} = {str(v)[:300]}")
                
                # Результаты всех узлов
                log_lines.append("\n--- Результаты узлов ---")
                for node_id, result in self._results.items():
                    status_icon = "✅" if result.status == "success" else "❌"
                    log_lines.append(f"  {status_icon} {result.node_name}: {result.status}")
                    if result.error:
                        log_lines.append(f"      Ошибка: {str(result.error)[:200]}")
                
                os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else '.', exist_ok=True)
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write('\n'.join(log_lines) + '\n\n')
                self._log(f"  📄 Лог ошибок: {error_log_file}")
            except Exception as e:
                self._log(f"  ⚠ Ошибка сохранения лога: {e}")
        
        # Восстановление данных
        if restore_data and restore_var:
            var_names = [v.strip() for v in restore_var.split(',') if v.strip()]
            for vn in var_names:
                backup_key = f"_backup_{vn}"
                if backup_key in self._context:
                    self._context[vn] = self._context[backup_key]
                    self._log(f"  ♻️ Восстановлено: {vn}")
                else:
                    self._log(f"  ⚠ Нет бэкапа для: {vn}")
        
        self._context["_bad_end_reached"] = True
        
        # Логика after-action
        restart_count = self._context.get('_restart_count', 0)
        if on_bad_end == 'restart' and restart_count < max_restarts:
            self._context["_restart_requested"] = True
            self._context["_restart_count"] = restart_count + 1
            self._log(f"  🔄 Перезапуск #{restart_count + 1}/{max_restarts}")
        elif on_bad_end == 'continue':
            self._log(f"  ▶ Продолжение выполнения...")
            # Не бросаем исключение — workflow пойдёт дальше
            return '\n'.join(output_parts)
        
        return '\n'.join(output_parts)

    async def _exec_notification(self, node: AgentNode) -> str:
        """🔔 Notification: оповещение пользователя."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        message = node.user_prompt_template or ''
        notif_level = cfg.get('notif_level', 'info')
        notif_color = cfg.get('notif_color', 'default')
        show_popup = cfg.get('show_popup', False)
        popup_duration = cfg.get('popup_duration', 5)
        write_to_log = cfg.get('write_to_log', True)
        write_to_file = cfg.get('write_to_file', False)
        log_file = cfg.get('log_file', 'notifications.log')
        include_timestamp = cfg.get('include_timestamp', True)
        save_to_var = cfg.get('save_to_var', False)
        output_var = cfg.get('output_var', 'last_notification')
        
        # Подстановка переменных
        for key, val in self._context.items():
            if not key.startswith('_'):
                message = message.replace(f'{{{key}}}', str(val))
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        level_icons = {'info': 'ℹ️', 'warning': '⚠️', 'error': '❌', 'success': '✅'}
        icon = level_icons.get(notif_level, 'ℹ️')
        
        formatted = f"{icon} [{notif_level.upper()}] {message}"
        if include_timestamp:
            formatted = f"[{timestamp}] {formatted}"
        
        if write_to_log:
            self._log(f"  🔔 {formatted}")
        
        # Всплывающее окно через сигнал
        if show_popup:
            try:
                self.signals.log.emit(f"🔔 POPUP: {formatted}")
            except Exception:
                pass
        
        # Запись в файл
        if write_to_file:
            try:
                for key, val in self._context.items():
                    if not key.startswith('_'):
                        log_file = log_file.replace(f'{{{key}}}', str(val))
                
                fpath = os.path.join(self._tool_executor._root, log_file)
                os.makedirs(os.path.dirname(fpath) if os.path.dirname(fpath) else '.', exist_ok=True)
                with open(fpath, 'a', encoding='utf-8') as f:
                    f.write(formatted + '\n')
            except Exception as e:
                self._log(f"  ⚠ Ошибка записи notification в файл: {e}")
        
        # Сохранение в переменную
        if save_to_var:
            self._context[output_var] = message
        
        return formatted
    
    async def _exec_js_snippet(self, node: AgentNode) -> str:
        """🟨 JavaScript Snippet: выполняет JS код."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        code = node.user_prompt_template or ''
        if not code.strip():
            return "⚠ Нет JS кода для выполнения"
        
        js_mode = cfg.get('js_mode', 'local')
        snip_timeout = cfg.get('timeout', 30)
        save_output = cfg.get('save_output', False)
        output_var = cfg.get('output_var', 'js_result')
        no_return = cfg.get('no_return', False)
        inject_vars = cfg.get('inject_vars', True)
        table_vars = cfg.get('_variables', [])
        
        # Инжекция переменных
        if inject_vars and table_vars:
            for var_def in table_vars:
                vname = var_def.get('name', '').strip()
                vvalue = var_def.get('value', '')
                if vname:
                    self._context[vname] = vvalue
        
        # Подстановка переменных в код
        for key, val in self._context.items():
            if not key.startswith('_'):
                code = code.replace(f'{{{key}}}', str(val))
        
        self._log(f"  🟨 Выполняю JavaScript ({js_mode}, {len(code)} симв)...")
        
        if js_mode == 'local':
            # Через Node.js
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                result = await self._tool_executor.execute_tool("shell_exec", {
                    "command": f'node "{tmp_path}"',
                    "timeout": snip_timeout,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            # Через Python eval — оборачиваем в subprocess с js2py
            wrapper = f"""
import sys
try:
    import js2py
    result = js2py.eval_js('''{code.replace("'", "\\'")}''')
    print(result)
except ImportError:
    # Фоллбэк на node
    import subprocess
    p = subprocess.run(['node', '-e', '''{code.replace("'", "\\'")}'''], capture_output=True, text=True, timeout={snip_timeout})
    print(p.stdout)
    if p.stderr:
        print(p.stderr, file=sys.stderr)
"""
            result = await self._tool_executor.execute_tool("code_execute", {"code": wrapper})
        
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        success = result.get("success", False)
        
        output = f"🟨 JavaScript: exit={result.get('returncode', '?')}\n"
        if stdout:
            output += f"STDOUT:\n{stdout[:3000]}\n"
            self._context["_js_stdout"] = stdout
            if save_output and not no_return:
                self._context[output_var] = stdout.strip()
                self._log(f"  📝 → {output_var}")
        if stderr:
            output += f"STDERR:\n{stderr[:2000]}\n"
        
        if not success:
            raise RuntimeError(output)
        
        self._log(f"  ✅ JavaScript выполнен")
        return output

    async def _exec_program_launch(self, node: AgentNode) -> str:
        """⚙️ Program Launch: запуск внешней программы."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        executable = cfg.get('executable', '')
        arguments = cfg.get('arguments', '')
        working_dir = cfg.get('working_dir', '')
        timeout = cfg.get('timeout', 60)
        no_wait = cfg.get('no_wait', False)
        hide_window = cfg.get('hide_window', True)
        save_exit_code = cfg.get('save_exit_code', True)
        exit_code_var = cfg.get('exit_code_var', 'exit_code')
        save_stdout = cfg.get('save_stdout', True)
        stdout_var = cfg.get('stdout_var', 'program_stdout')
        save_stderr = cfg.get('save_stderr', True)
        stderr_var = cfg.get('stderr_var', 'program_stderr')
        env_vars_raw = cfg.get('env_vars', '')
        
        if not executable:
            return "⚠ Не указан исполняемый файл"
        
        # Подстановка переменных
        for key, val in self._context.items():
            if not key.startswith('_'):
                executable = executable.replace(f'{{{key}}}', str(val))
                arguments = arguments.replace(f'{{{key}}}', str(val))
                working_dir = working_dir.replace(f'{{{key}}}', str(val))
        
        import sys as _sys
        _ext = os.path.splitext(executable)[1].lower()
        if _ext == '.py':
            _py = _sys.executable.replace('\\', '/')
            cmd = f'"{_py}" "{executable}" {arguments}' if arguments else f'"{_py}" "{executable}"'
        elif _ext in ('.sh',):
            cmd = f'bash "{executable}" {arguments}' if arguments else f'bash "{executable}"'
        else:
            cmd = f'"{executable}" {arguments}' if arguments else f'"{executable}"'
        
        self._log(f"  ⚙️ Запуск: {cmd[:200]}")
        
        # Env vars
        env_dict = {}
        if env_vars_raw.strip():
            for line in env_vars_raw.strip().splitlines():
                if '=' in line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    for ck, cv in self._context.items():
                        if not ck.startswith('_'):
                            v = v.replace(f'{{{ck}}}', str(cv))
                    env_dict[k.strip()] = v.strip()
        
        if no_wait:
            # Запуск без ожидания — для GUI-приложений и фоновых процессов
            try:
                import subprocess as _sp
                popen_kwargs = {'shell': True, 'stdin': _sp.DEVNULL}
                if working_dir:
                    popen_kwargs['cwd'] = working_dir
                if env_dict:
                    merged_env = os.environ.copy()
                    merged_env.update(env_dict)
                    popen_kwargs['env'] = merged_env
                if hide_window:
                    try:
                        popen_kwargs['creationflags'] = _sp.CREATE_NO_WINDOW
                    except AttributeError:
                        pass  # Linux/macOS — не нужно
                _sp.Popen(cmd, **popen_kwargs)
                if save_exit_code:
                    self._context[exit_code_var] = '0'
                    self._sync_var_to_project(exit_code_var, '0')
                self._log(f"  ✅ Программа запущена (no_wait): {cmd[:100]}")
                return f"⚙️ Запущено (no_wait): {cmd[:100]}"
            except Exception as e:
                self._log(f"  ⚠ Ошибка запуска: {e}")
                raise RuntimeError(f"Ошибка запуска программы: {e}")

        # ── Запуск с ожиданием: Popen + async-polling (поддержка Stop + hide_window + timeout) ──
        import subprocess as _sp
        import time as _time

        popen_kwargs = {
            'shell': True,
            'stdout': _sp.PIPE,
            'stderr': _sp.PIPE,
            'stdin':  _sp.DEVNULL,
        }
        _cwd = working_dir if working_dir and os.path.exists(working_dir) else None
        if not _cwd and _ext == '.py':
            # Для Python-скриптов без явной рабочей папки — используем папку самого скрипта
            _script_dir = os.path.dirname(os.path.abspath(executable.strip('"')))
            if _script_dir and os.path.exists(_script_dir):
                _cwd = _script_dir
        if not _cwd:
            _root = getattr(self._tool_executor, '_root', '')
            if _root and os.path.exists(_root):
                _cwd = _root
        if _cwd:
            popen_kwargs['cwd'] = _cwd
        if env_dict:
            _env = os.environ.copy()
            _env.update(env_dict)
            popen_kwargs['env'] = _env
        if hide_window:
            try:
                popen_kwargs['creationflags'] = _sp.CREATE_NO_WINDOW
            except AttributeError:
                pass  # Linux/macOS

        try:
            proc = _sp.Popen(cmd, **popen_kwargs)
        except Exception as e:
            self._log(f"  ⚠ Не удалось запустить процесс: {e}")
            raise RuntimeError(f"Ошибка запуска программы: {e}")

        _deadline = _time.time() + timeout
        returncode = -1
        out_b = b''
        err_b = b''
        try:
            while True:
                # ── Проверка кнопки Stop ──
                if getattr(self, '_stop_requested', False):
                    proc.kill()
                    try: proc.wait(timeout=2)
                    except Exception: pass
                    self._log("  🛑 Программа остановлена по сигналу Stop")
                    returncode = -9
                    break
                ret = proc.poll()
                if ret is not None:
                    returncode = ret
                    break
                # ── Проверка таймаута ──
                if _time.time() >= _deadline:
                    proc.kill()
                    try: proc.wait(timeout=2)
                    except Exception: pass
                    self._log(f"  ⏱ Таймаут {timeout}с — программа остановлена")
                    returncode = -2
                    break
                await asyncio.sleep(0.25)
        finally:
            try:
                out_b, err_b = proc.communicate(timeout=3)
            except Exception:
                try: out_b, err_b = proc.stdout.read(), proc.stderr.read()
                except Exception: pass

        stdout = out_b.decode('utf-8', errors='replace')[-4000:] if out_b else ''
        stderr = err_b.decode('utf-8', errors='replace')[-2000:] if err_b else ''

        output = f"⚙️ Program: exit={returncode}\n"

        if save_exit_code:
            self._context[exit_code_var] = str(returncode)
            self._sync_var_to_project(exit_code_var, str(returncode))
        if stdout:
            output += f"STDOUT:\n{stdout[:3000]}\n"
            if save_stdout:
                self._context[stdout_var] = stdout.strip()
                self._sync_var_to_project(stdout_var, stdout.strip())
        if stderr:
            output += f"STDERR:\n{stderr[:2000]}\n"
            if save_stderr:
                self._context[stderr_var] = stderr.strip()
                self._sync_var_to_project(stderr_var, stderr.strip())

        if returncode == -9:
            self._log("  🛑 Программа остановлена вручную")
        elif returncode == -2:
            self._log(f"  ⏱ Программа остановлена по таймауту ({timeout}с)")
        elif returncode != 0:
            self._log(f"  ⚠ Программа завершилась с кодом {returncode}")
            # Показываем stderr прямо в лог чтобы пользователь видел причину краша
            if stderr:
                for _line in stderr.strip().splitlines()[-15:]:  # последние 15 строк
                    self._log(f"    ❗ {_line}")

        self._log(f"  ✅ Программа завершена (exit={returncode})")
        return output

    async def _exec_list_operation(self, node: AgentNode) -> str:
        """📃 List Operation: операции со списками в контексте."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        operation = cfg.get('operation', 'add_line')
        list_var = cfg.get('list_var', 'my_list')
        value = cfg.get('value', '') or node.user_prompt_template or ''
        position = cfg.get('position', 'end')
        index = cfg.get('index', 0)
        get_mode = cfg.get('get_mode', 'first')
        delete_after = cfg.get('delete_after_get', False)
        sort_numeric = cfg.get('sort_numeric', False)
        sort_desc = cfg.get('sort_descending', False)
        join_sep = cfg.get('join_separator', '\\n').replace('\\n', '\n').replace('\\t', '\t')
        file_path = cfg.get('file_path', '')
        file_append = cfg.get('file_append', True)
        result_var = cfg.get('result_var', 'list_result')
        
        # Подстановка переменных
        for key, val in self._context.items():
            if not key.startswith('_'):
                value = value.replace(f'{{{key}}}', str(val))
                file_path = file_path.replace(f'{{{key}}}', str(val))
        
        # ═══ Автозагрузка из файла если включена ═══
        if cfg.get('auto_load_from_file', False) and cfg.get('file_path', ''):
            auto_fp = cfg['file_path']
            for key, val in self._context.items():
                if not key.startswith('_'):
                    auto_fp = auto_fp.replace(f'{{{key}}}', str(val))
            fpath = os.path.join(self._tool_executor._root, auto_fp) if not os.path.isabs(auto_fp) else auto_fp
            if os.path.isfile(fpath):
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    auto_lst = [line.rstrip('\n\r') for line in f.readlines()]
                self._context[list_var] = auto_lst
                self._log(f"  📃 Автозагрузка: {len(auto_lst)} строк из {os.path.basename(fpath)}")
        
        # Получаем или создаём список
        lst = self._context.get(list_var, [])
        if isinstance(lst, str):
            lst = lst.split('\n') if lst else []
        if not isinstance(lst, list):
            lst = [str(lst)]
        
        self._log(f"  📃 Список '{list_var}': {operation} (текущий размер: {len(lst)})")
        
        if operation == 'add_line':
            if position == 'start':
                lst.insert(0, value)
            elif position == 'index':
                lst.insert(min(index, len(lst)), value)
            else:
                lst.append(value)
            result = f"Добавлено: '{value[:60]}'. Размер: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'add_text':
            lines = value.split('\n')
            lst.extend([l for l in lines if l.strip()])
            result = f"Добавлено {len(lines)} строк. Размер: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'get_line':
            if not lst:
                self._context[result_var] = ''
                raise RuntimeError("Список пуст")
            
            import random as _rnd
            if get_mode == 'first':
                idx = 0
            elif get_mode == 'last':
                idx = len(lst) - 1
            elif get_mode == 'random':
                idx = _rnd.randint(0, len(lst) - 1)
            elif get_mode == 'by_index':
                idx = min(index, len(lst) - 1)
            elif get_mode == 'contains':
                idx = next((i for i, s in enumerate(lst) if value in s), -1)
                if idx < 0:
                    self._context[result_var] = ''
                    return f"📃 Не найдено: '{value[:40]}'"
            elif get_mode == 'regex':
                import re
                idx = next((i for i, s in enumerate(lst) if re.search(value, s)), -1)
                if idx < 0:
                    self._context[result_var] = ''
                    return f"📃 Regex не найден: '{value[:40]}'"
            else:
                idx = 0
            
            got = lst[idx]
            if delete_after:
                lst.pop(idx)
                self._context[list_var] = lst
                self._sync_list_to_metadata(list_var, lst)
            self._context[result_var] = got
            self._sync_var_to_project(result_var, got)
            result = f"Получено [{idx}]: '{got[:80]}'" + (" (удалено)" if delete_after else "")
        
        elif operation == 'count':
            cnt = len(lst)
            self._context[result_var] = str(cnt)
            self._sync_var_to_project(result_var, str(cnt))
            result = f"Количество строк: {cnt}"
        
        elif operation == 'remove':
            before = len(lst)
            if get_mode == 'all':
                lst.clear()
            elif get_mode == 'first':
                if lst: lst.pop(0)
            elif get_mode == 'last':
                if lst: lst.pop()
            elif get_mode == 'by_index':
                if 0 <= index < len(lst): lst.pop(index)
            elif get_mode == 'contains':
                lst = [s for s in lst if value not in s]
            elif get_mode == 'not_contains':
                lst = [s for s in lst if value in s]
            elif get_mode == 'regex':
                import re
                lst = [s for s in lst if not re.search(value, s)]
            result = f"Удалено {before - len(lst)} строк. Осталось: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'deduplicate':
            before = len(lst)
            seen = set()
            deduped = []
            for item in lst:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            lst = deduped
            result = f"Удалено дублей: {before - len(lst)}. Осталось: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'shuffle':
            import random as _rnd
            _rnd.shuffle(lst)
            result = f"Перемешано. Размер: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'sort':
            if sort_numeric:
                try:
                    lst.sort(key=lambda x: float(x), reverse=sort_desc)
                except ValueError:
                    lst.sort(reverse=sort_desc)
            else:
                lst.sort(reverse=sort_desc)
            result = f"Отсортировано {'↓' if sort_desc else '↑'}. Размер: {len(lst)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
            self._context[list_var] = lst
        
        elif operation == 'join':
            joined = join_sep.join(lst)
            self._context[result_var] = joined
            self._sync_var_to_project(result_var, joined)
            result = f"Объединено {len(lst)} элементов ({len(joined)} символов)"
        
        elif operation == 'load_file':
            if not file_path:
                return "⚠ Не указан файл"
            fpath = os.path.join(self._tool_executor._root, file_path) if not os.path.isabs(file_path) else file_path
            if not os.path.isfile(fpath):
                return f"⚠ Файл не найден: {fpath}"
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                lst = [line.rstrip('\n\r') for line in f.readlines()]
            cnt_str = str(len(lst))
            self._context[result_var] = cnt_str
            self._sync_var_to_project(result_var, cnt_str)
            result = f"Загружено {len(lst)} строк из {os.path.basename(file_path)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_list_to_metadata(list_var, lst)
        
        elif operation == 'save_file':
            if not file_path:
                return "⚠ Не указан файл"
            fpath = os.path.join(self._tool_executor._root, file_path) if not os.path.isabs(file_path) else file_path
            os.makedirs(os.path.dirname(fpath) if os.path.dirname(fpath) else '.', exist_ok=True)
            mode = 'a' if file_append else 'w'
            with open(fpath, mode, encoding='utf-8') as f:
                f.write('\n'.join(lst) + '\n')
            result = f"Сохранено {len(lst)} строк в {os.path.basename(file_path)}"
        
        elif operation == 'clear':
            lst = []
            result = "Список очищен"
        
        # ═══ ПРОЕКТНЫЕ СПИСКИ ═══
        elif operation.startswith('proj_list_'):
            proj_name = cfg.get('project_list_name', '')
            for k, v in self._context.items():
                if not k.startswith('_'):
                    proj_name = proj_name.replace(f'{{{k}}}', str(v))
            
            if not proj_name:
                return "⚠ Не указано имя проектного списка"
            
            # Получаем проектный список из контекста _project_lists
            proj_lists = self._context.get('_project_lists', {})
            proj_data = proj_lists.get(proj_name, [])
            if isinstance(proj_data, str):
                proj_data = proj_data.split('\n') if proj_data else []
            
            # ═══ Режим always: перечитываем из файла при каждом обращении ═══
            _pv = self._project_variables or {}
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            if isinstance(_meta, str):
                try:
                    import json as _json
                    _meta = _json.loads(_meta) if _meta.strip() else {}
                except Exception:
                    _meta = {}
            raw_lists = _pv.get('_project_lists', _meta.get('project_lists', []))
            _raw_tables = _pv.get('_project_tables', _meta.get('project_tables', []))
            for _lcfg in (raw_lists or []):
                if isinstance(_lcfg, dict) and _lcfg.get('name') == proj_name:
                    if _lcfg.get('load_mode') == 'always' and _lcfg.get('file_path'):
                        _fp = _lcfg['file_path']
                        if not os.path.isabs(_fp):
                            _fp = os.path.join(self._tool_executor._root, _fp)
                        if os.path.isfile(_fp):
                            _enc = _lcfg.get('encoding', 'utf-8') or 'utf-8'
                            with open(_fp, 'r', encoding=_enc, errors='replace') as f:
                                proj_data = [line.rstrip('\n\r') for line in f.readlines() if line.strip()]
                            proj_lists[proj_name] = proj_data
                            self._log(f"  📃 Перечитан '{proj_name}': {len(proj_data)} строк (always)")
                    break
            
            if operation == 'proj_list_get':
                if not proj_data:
                    self._context[result_var] = ''
                    raise RuntimeError(f"Проектный список '{proj_name}' пуст")
                mode = cfg.get('proj_get_mode', 'first')
                import random as _rnd
                if mode == 'first': idx = 0
                elif mode == 'last': idx = len(proj_data) - 1
                elif mode == 'random': idx = _rnd.randint(0, len(proj_data) - 1)
                elif mode == 'by_index': idx = min(index, len(proj_data) - 1)
                elif mode == 'contains':
                    search = cfg.get('proj_value', '') or value
                    idx = next((i for i, s in enumerate(proj_data) if search in s), -1)
                    if idx < 0:
                        self._context[result_var] = ''
                        return f"📃 Не найдено в '{proj_name}': '{search[:40]}'"
                elif mode == 'regex':
                    import re
                    search = cfg.get('proj_value', '') or value
                    idx = next((i for i, s in enumerate(proj_data) if re.search(search, s)), -1)
                    if idx < 0:
                        self._context[result_var] = ''
                        return f"📃 Regex не найден в '{proj_name}'"
                else: idx = 0
                got = proj_data[idx]
                if cfg.get('proj_delete_after_get', False):
                    proj_data.pop(idx)
                    proj_lists[proj_name] = proj_data
                    self._context['_project_lists'] = proj_lists
                self._context[result_var] = got
                self._sync_var_to_project(result_var, got)
                result = f"Из '{proj_name}'[{idx}]: '{got[:80]}'"
            
            elif operation == 'proj_list_add':
                val = cfg.get('proj_value', '') or value
                pos = cfg.get('proj_add_position', 'end')
                if pos == 'start':
                    proj_data.insert(0, val)
                else:
                    proj_data.append(val)
                result = f"Добавлено в '{proj_name}': '{val[:60]}'. Размер: {len(proj_data)}"
            
            elif operation == 'proj_list_remove':
                val = cfg.get('proj_value', '') or value
                before = len(proj_data)
                proj_data = [s for s in proj_data if val not in s]
                result = f"Удалено из '{proj_name}': {before - len(proj_data)} строк"
            
            elif operation == 'proj_list_load':
                loaded = '\n'.join(proj_data)
                self._context[result_var] = loaded
                self._sync_var_to_project(result_var, loaded)
                result = f"Загружен '{proj_name}' ({len(proj_data)} строк) → {result_var}"
            
            elif operation == 'proj_list_save':
                val = cfg.get('proj_value', '') or value
                proj_data = val.split('\n') if val else []
                result = f"Сохранено {len(proj_data)} строк в '{proj_name}'"
            
            elif operation == 'proj_list_count':
                cnt = str(len(proj_data))
                self._context[result_var] = cnt
                self._sync_var_to_project(result_var, cnt)
                result = f"'{proj_name}': {len(proj_data)} строк"
            
            elif operation == 'proj_list_clear':
                proj_data = []
                result = f"'{proj_name}' очищен"
            
            else:
                result = f"Неизвестная proj_list операция: {operation}"
            
            proj_lists[proj_name] = proj_data
            self._context['_project_lists'] = proj_lists
            self._log(f"  📃 {result}")
            return f"📃 {result}"
        
        else:
            result = f"Неизвестная операция: {operation}"
        
        self._context[list_var] = lst
        # ── Персистим изменения в metadata workflow чтобы следующий запуск видел данные ──
        try:
            if hasattr(self._workflow, 'metadata') and isinstance(self._workflow.metadata, dict):
                for _plst in self._workflow.metadata.get('project_lists', []):
                    if isinstance(_plst, dict) and _plst.get('name') == list_var:
                        _plst['items'] = list(lst)
                        break
        except Exception:
            pass
        self._log(f"  📃 {result}")
        return f"📃 {result}"

    async def _exec_table_operation(self, node: AgentNode) -> str:
        """📊 Table Operation: операции с таблицами в контексте."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        operation = cfg.get('operation', 'load')
        # Получаем имя таблицы из snippet_config с правильным fallback
        table_var = cfg.get('table_var', '')
        if not table_var:
            table_var = 'my_table'
        # Очищаем от фигурных скобок если пользователь так написал
        table_var = table_var.strip('{}').strip()
        if not table_var:
            table_var = 'my_table'
        file_path = cfg.get('file_path', '')
        delimiter_cfg = cfg.get('delimiter', 'auto')
        row_idx_str = cfg.get('row_index', '0')
        col_idx_str = cfg.get('col_index', '0')
        cell_value = cfg.get('cell_value', '')
        row_values = cfg.get('row_values', '')
        get_mode = cfg.get('get_mode', 'first')
        # ═══ АВТО: если row_index указан и != 0, а get_mode по умолчанию — ставим by_index ═══
        _raw_row_idx = cfg.get('row_index', '0')
        if get_mode == 'first' and str(_raw_row_idx).strip() not in ('', '0'):
            get_mode = 'by_index'
        filter_text = cfg.get('filter_text', '')
        delete_after = cfg.get('delete_after_get', False)
        sort_col_str = cfg.get('sort_column', '0')
        sort_numeric = cfg.get('sort_numeric', False)
        sort_desc = cfg.get('sort_descending', False)
        dedup_col_str = cfg.get('dedup_column', '0')
        target_list = cfg.get('target_list', '')
        result_var = cfg.get('result_var', 'table_result')
        
        # Очищаем имя переменной от фигурных скобок
        result_var = result_var.strip('{}').strip() if result_var else 'table_result'
        target_list = target_list.strip('{}').strip() if target_list else ''
        
        # Подстановка переменных
        for key, val in self._context.items():
            if not key.startswith('_'):
                file_path = file_path.replace(f'{{{key}}}', str(val))
                cell_value = cell_value.replace(f'{{{key}}}', str(val))
                row_values = row_values.replace(f'{{{key}}}', str(val))
                filter_text = filter_text.replace(f'{{{key}}}', str(val))
                row_idx_str = row_idx_str.replace(f'{{{key}}}', str(val))
                col_idx_str = col_idx_str.replace(f'{{{key}}}', str(val))
        
        # Парсинг индексов
        def parse_col(s, columns=None):
            """Парсинг индекса столбца: число, буква (A,B,C...) или имя колонки."""
            s = s.strip()
            if s.isdigit():
                return int(s)
            if len(s) == 1 and s.isalpha():
                return ord(s.upper()) - ord('A')
            # Поиск по имени колонки (из метаданных проектной таблицы)
            if columns:
                for i, col_name in enumerate(columns):
                    if col_name.strip().lower() == s.lower():
                        return i
            return 0
        
        row_idx = int(row_idx_str) if row_idx_str.strip().isdigit() else 0
        col_idx = parse_col(col_idx_str)
        sort_col = parse_col(sort_col_str)
        dedup_col = parse_col(dedup_col_str)
        
        def detect_delimiter(sample):
            if '\t' in sample: return '\t'
            if ';' in sample: return ';'
            return ','
        
        # ═══ Автозагрузка из файла если включена ═══
        if cfg.get('auto_load_from_file', False) and cfg.get('file_path', ''):
            auto_fp = cfg['file_path']
            for key, val in self._context.items():
                if not key.startswith('_'):
                    auto_fp = auto_fp.replace(f'{{{key}}}', str(val))
            fpath = os.path.join(self._tool_executor._root, auto_fp) if not os.path.isabs(auto_fp) else auto_fp
            if os.path.isfile(fpath):
                import csv
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    sample = f.read(4096)
                    f.seek(0)
                    delim = detect_delimiter(sample) if delimiter_cfg == 'auto' else delimiter_cfg.replace('\\t', '\t')
                    reader = csv.reader(f, delimiter=delim)
                    auto_table = [row for row in reader]
                self._context[table_var] = auto_table
                self._log(f"  📊 Автозагрузка: {len(auto_table)} строк из {os.path.basename(fpath)}")
        
        # Получаем таблицу из контекста (список списков)
        table = self._context.get(table_var, [])
        if not isinstance(table, list):
            table = []
        
        self._log(f"  📊 Таблица '{table_var}': {operation} ({len(table)} строк)")
        
        if operation == 'load':
            if not file_path:
                return "⚠ Не указан файл"
            import csv
            fpath = os.path.join(self._tool_executor._root, file_path) if not os.path.isabs(file_path) else file_path
            if not os.path.isfile(fpath):
                return f"⚠ Файл не найден: {fpath}"
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                sample = f.read(4096)
                f.seek(0)
                delim = detect_delimiter(sample) if delimiter_cfg == 'auto' else delimiter_cfg.replace('\\t', '\t')
                reader = csv.reader(f, delimiter=delim)
                table = [row for row in reader]
            self._context[table_var] = table
            cnt_str = str(len(table))
            self._context[result_var] = cnt_str
            self._sync_var_to_project(result_var, cnt_str)
            self._sync_table_to_metadata(table_var, table)
            result = f"Загружено {len(table)} строк, {max(len(r) for r in table) if table else 0} столбцов"
            self._log(f"  📊 Сохранено в '{result_var}': {cnt_str}")
        
        elif operation == 'save':
            if not file_path:
                return "⚠ Не указан файл"
            import csv
            fpath = os.path.join(self._tool_executor._root, file_path) if not os.path.isabs(file_path) else file_path
            os.makedirs(os.path.dirname(fpath) if os.path.dirname(fpath) else '.', exist_ok=True)
            delim = ',' if delimiter_cfg == 'auto' else delimiter_cfg.replace('\\t', '\t')
            with open(fpath, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter=delim)
                for row in table:
                    writer.writerow(row)
            cnt_str = str(len(table))
            self._context[result_var] = fpath  # <-- ДОБАВИТЬ (сохраняем путь к файлу)
            result = f"Сохранено {len(table)} строк в {os.path.basename(file_path)}"
            self._log(f"  📊 Сохранено в '{result_var}': {fpath}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, fpath)  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
        
        elif operation == 'read_cell':
            if row_idx < len(table) and col_idx < len(table[row_idx]):
                val = table[row_idx][col_idx]
            else:
                val = ''
            self._context[result_var] = val
            result = f"Ячейка [{row_idx},{col_idx}] = '{val[:80]}'"
            self._log(f"  📊 Сохранено в '{result_var}': {str(val)[:80]}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, val)  # <-- ДОБАВИТЬ
            self._log(f"  📊 Сохранено в '{result_var}': {str(val)[:80]}")
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, val)
        
        elif operation == 'write_cell':
            while len(table) <= row_idx:
                table.append([])
            while len(table[row_idx]) <= col_idx:
                table[row_idx].append('')
            table[row_idx][col_idx] = cell_value
            self._context[result_var] = cell_value  # <-- ДОБАВИТЬ
            result = f"Записано [{row_idx},{col_idx}] = '{cell_value[:60]}'"
            self._log(f"  📊 Сохранено в '{result_var}': {str(cell_value)[:80]}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, cell_value)  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
        
        elif operation == 'add_row':
            delim = ';' if delimiter_cfg == 'auto' else delimiter_cfg.replace('\\t', '\t')
            new_row = row_values.split(delim) if row_values else []
            table.append(new_row)
            row_str = ';'.join(new_row)  # <-- ДОБАВИТЬ
            self._context[result_var] = row_str  # <-- ДОБАВИТЬ
            result = f"Добавлена строка ({len(new_row)} столбцов). Всего строк: {len(table)}"
            self._log(f"  📊 Сохранено в '{result_var}': {row_str[:80]}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, row_str)  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
            
        elif operation == 'get_row':
            if not table:
                self._context[result_var] = ''
                raise RuntimeError("Таблица пуста")
            import random as _rnd
            if get_mode == 'first': idx = 0
            elif get_mode == 'by_index': idx = min(row_idx, len(table)-1)
            elif get_mode == 'random': idx = _rnd.randint(0, len(table)-1)
            elif get_mode == 'contains':
                idx = next((i for i, r in enumerate(table) if any(filter_text in c for c in r)), -1)
                if idx < 0:
                    self._context[result_var] = ''
                    return "📊 Строка не найдена"
            else: idx = 0
            
            row = table[idx]
            if delete_after:
                table.pop(idx)
            # === ИСПРАВЛЕНИЕ: сохраняем в result_var правильно ===
            row_str = ';'.join(row)
            self._context[result_var] = row_str
            self._context[f"_{table_var}_last_row"] = row  # для совместимости
            if target_list:
                self._context[target_list] = row
            result = f"Строка [{idx}]: {row_str[:100]}" + (" (удалена)" if delete_after else "")
            self._log(f"  📊 Сохранено в '{result_var}': {row_str[:80]}")
            
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, row_str)
        
        elif operation == 'delete_rows':
            before = len(table)
            if get_mode == 'all': table.clear()
            elif get_mode == 'first' and table: table.pop(0)
            elif get_mode == 'by_index' and row_idx < len(table): table.pop(row_idx)
            elif get_mode == 'contains':
                table = [r for r in table if not any(filter_text in c for c in r)]
            elif get_mode == 'regex':
                import re
                table = [r for r in table if not any(re.search(filter_text, c) for c in r)]
            result = f"Удалено {before - len(table)} строк. Осталось: {len(table)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
            
        elif operation == 'get_column':
            col_data = [row[col_idx] if col_idx < len(row) else '' for row in table]
            if target_list:
                self._context[target_list] = col_data
            col_str = '\n'.join(col_data)  # <-- ДОБАВИТЬ
            self._context[result_var] = col_str
            result = f"Столбец [{col_idx}]: {len(col_data)} значений"
            self._log(f"  📊 Сохранено в '{result_var}': {col_str[:80]}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, col_str)  # <-- ДОБАВИТЬ
        
        elif operation == 'set_column':
            src_list = self._context.get(target_list, [])
            if isinstance(src_list, str):
                src_list = src_list.split('\n')
            for i, val in enumerate(src_list):
                while len(table) <= i:
                    table.append([])
                while len(table[i]) <= col_idx:
                    table[i].append('')
                table[i][col_idx] = val
            result = f"Столбец [{col_idx}] заполнен ({len(src_list)} значений)"
        
        elif operation == 'delete_column':
            for row in table:
                if col_idx < len(row):
                    row.pop(col_idx)
            result = f"Столбец [{col_idx}] удалён"
        
        elif operation == 'row_count':
            cnt = str(len(table))
            self._context[result_var] = cnt
            result = f"Строк: {len(table)}"
            self._log(f"  📊 Сохранено в '{result_var}': {cnt}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, cnt)  # <-- ДОБАВИТЬ
        
        elif operation == 'col_count':
            cnt = max(len(r) for r in table) if table else 0
            cnt_str = str(cnt)
            self._context[result_var] = cnt_str
            result = f"Столбцов: {cnt}"
            self._log(f"  📊 Сохранено в '{result_var}': {cnt_str}")  # <-- ДОБАВИТЬ
            # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
            self._sync_var_to_project(result_var, cnt_str)  # <-- ДОБАВИТЬ
        
        elif operation == 'deduplicate':
            before = len(table)
            seen = set()
            deduped = []
            for row in table:
                key = row[dedup_col] if dedup_col < len(row) else ''
                if key not in seen:
                    seen.add(key)
                    deduped.append(row)
            table = deduped
            result = f"Дубли (по столбцу {dedup_col}): удалено {before - len(table)}, осталось {len(table)}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
            
        elif operation == 'sort':
            def sort_key(row):
                v = row[sort_col] if sort_col < len(row) else ''
                if sort_numeric:
                    try: return float(v)
                    except ValueError: return 0
                return v
            table.sort(key=sort_key, reverse=sort_desc)
            result = f"Сортировка по столбцу {sort_col} {'↓' if sort_desc else '↑'}"
            # === СИНХРОНИЗАЦИЯ В METADATA ДЛЯ UI ===
            self._sync_table_to_metadata(table_var, table)
        
        # ═══ ПРОЕКТНЫЕ ТАБЛИЦЫ ═══
        elif operation.startswith('proj_table_'):
            proj_name = cfg.get('project_table_name', '')
            for k, v in self._context.items():
                if not k.startswith('_'):
                    proj_name = proj_name.replace(f'{{{k}}}', str(v))
            
            if not proj_name:
                return "⚠ Не указано имя проектной таблицы"
            
            proj_tables = self._context.get('_project_tables', {})
            proj_data = proj_tables.get(proj_name, [])  # Список списков
            
            # ═══ Режим always: перечитываем из файла при каждом обращении ═══
            _pv = self._project_variables or {}
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            if isinstance(_meta, str):
                try:
                    import json as _json
                    _meta = _json.loads(_meta) if _meta.strip() else {}
                except Exception:
                    _meta = {}
            _raw_lists = _pv.get('_project_lists', _meta.get('project_lists', []))
            _raw_tables = _pv.get('_project_tables', _meta.get('project_tables', []))
            for _tcfg in (_raw_tables or []):
                if isinstance(_tcfg, dict) and _tcfg.get('name') == proj_name:
                    if _tcfg.get('load_mode') == 'always' and _tcfg.get('file_path'):
                        _fp = _tcfg['file_path']
                        if not os.path.isabs(_fp):
                            _fp = os.path.join(self._tool_executor._root, _fp)
                        if os.path.isfile(_fp):
                            import csv
                            _enc = _tcfg.get('encoding', 'utf-8') or 'utf-8'
                            with open(_fp, 'r', encoding=_enc, errors='replace') as f:
                                reader = csv.reader(f)
                                proj_data = [row for row in reader]
                            if _tcfg.get('has_header') and proj_data:
                                proj_data = proj_data[1:]
                            proj_tables[proj_name] = proj_data
                            self._log(f"  📊 Перечитана '{proj_name}': {len(proj_data)} строк (always)")
                    break
            
            p_row_idx = cfg.get('proj_row_index', '0')
            p_col_idx = cfg.get('proj_col_index', '0')
            for k, v in self._context.items():
                if not k.startswith('_'):
                    p_row_idx = p_row_idx.replace(f'{{{k}}}', str(v))
                    p_col_idx = p_col_idx.replace(f'{{{k}}}', str(v))
            p_row = int(p_row_idx) if p_row_idx.strip().isdigit() else 0
            # Получаем имена колонок из метаданных таблицы для поиска по имени
            _tbl_columns = None
            _pv = self._project_variables or {}
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            _raw_tables = _pv.get('_project_tables', _meta.get('project_tables', []))
            for _tcfg in (_raw_tables or []):
                if isinstance(_tcfg, dict) and _tcfg.get('name') == proj_name:
                    _tbl_columns = _tcfg.get('columns', [])
                    break
            p_col = parse_col(p_col_idx, columns=_tbl_columns)
            
            if operation == 'proj_table_get_row':
                if not proj_data:
                    self._context[result_var] = ''
                    raise RuntimeError(f"Проектная таблица '{proj_name}' пуста")
                mode = cfg.get('proj_row_get_mode', 'first')
                import random as _rnd
                if mode == 'first': idx = 0
                elif mode == 'last': idx = len(proj_data) - 1
                elif mode == 'by_index': idx = min(p_row, len(proj_data) - 1)
                elif mode == 'random': idx = _rnd.randint(0, len(proj_data) - 1)
                elif mode == 'contains':
                    search = cfg.get('proj_filter_text', '')
                    for k, v in self._context.items():
                        if not k.startswith('_'):
                            search = search.replace(f'{{{k}}}', str(v))
                    idx = next((i for i, r in enumerate(proj_data) if any(search in c for c in r)), -1)
                    if idx < 0:
                        self._context[result_var] = ''
                        return f"📊 Строка не найдена в '{proj_name}'"
                else: idx = 0
                row = proj_data[idx]
                if cfg.get('proj_delete_after_get', False):
                    proj_data.pop(idx)
                # === ИСПРАВЛЕНИЕ: правильное сохранение в result_var ===
                fmt = cfg.get('proj_result_format', 'json')
                if fmt == 'json':
                    import json as _json
                    result_value = _json.dumps(row, ensure_ascii=False)
                elif fmt == 'list':
                    result_value = ';'.join(row)
                else:  # first_cell
                    result_value = row[0] if row else ''
                
                self._context[result_var] = result_value
                self._context[f"_{proj_name}_last_row"] = row
                result = f"Строка [{idx}] из '{proj_name}' → '{result_var}' = {result_value[:80]}"
                self._log(f"  📊 {result}")
                
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, result_value)
            
            elif operation == 'proj_table_read_cell':
                val = ''
                if p_row < len(proj_data) and p_col < len(proj_data[p_row]):
                    val = proj_data[p_row][p_col]
                self._context[result_var] = val
                result = f"'{proj_name}'[{p_row},{p_col}] = '{val[:80]}'"
            
            elif operation == 'proj_table_write_cell':
                while len(proj_data) <= p_row:
                    proj_data.append([])
                while len(proj_data[p_row]) <= p_col:
                    proj_data[p_row].append('')
                val = cfg.get('proj_cell_value', '')
                for k, v in self._context.items():
                    if not k.startswith('_'):
                        val = val.replace(f'{{{k}}}', str(v))
                proj_data[p_row][p_col] = val
                self._context[result_var] = val  # <-- ДОБАВИТЬ
                result = f"'{proj_name}'[{p_row},{p_col}] = '{val[:60]}'"
                self._log(f"  📊 Сохранено в '{result_var}': {str(val)[:80]}")  # <-- ДОБАВИТЬ
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, val)  # <-- ДОБАВИТЬ
            
            elif operation == 'proj_table_add_row':
                row_vals = cfg.get('proj_row_values', '')
                for k, v in self._context.items():
                    if not k.startswith('_'):
                        row_vals = row_vals.replace(f'{{{k}}}', str(v))
                new_row = row_vals.split(';') if row_vals else []
                proj_data.append(new_row)
                row_str = ';'.join(new_row)  # <-- ДОБАВИТЬ
                self._context[result_var] = row_str  # <-- ДОБАВИТЬ
                result = f"Добавлена строка в '{proj_name}' ({len(new_row)} столбцов)"
                self._log(f"  📊 Сохранено в '{result_var}': {row_str[:80]}")  # <-- ДОБАВИТЬ
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, row_str)  # <-- ДОБАВИТЬ
            
            elif operation == 'proj_table_delete_row':
                mode = cfg.get('proj_row_get_mode', 'first')
                before = len(proj_data)
                if mode == 'first' and proj_data: proj_data.pop(0)
                elif mode == 'last' and proj_data: proj_data.pop()
                elif mode == 'by_index' and p_row < len(proj_data): proj_data.pop(p_row)
                elif mode == 'contains':
                    ft = cfg.get('proj_filter_text', '')
                    proj_data = [r for r in proj_data if not any(ft in c for c in r)]
                result = f"Удалено {before - len(proj_data)} строк из '{proj_name}'"
            
            elif operation == 'proj_table_load':
                import json as _json
                json_str = _json.dumps(proj_data, ensure_ascii=False)
                self._context[result_var] = json_str
                result = f"'{proj_name}' ({len(proj_data)} строк) → {result_var}"
                self._log(f"  📊 Сохранено в '{result_var}': {json_str[:80]}")
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, json_str)
            
            elif operation == 'proj_table_get_column':
                col_data = [row[p_col] if p_col < len(row) else '' for row in proj_data]
                col_str = '\n'.join(col_data)
                self._context[result_var] = col_str
                result = f"Столбец [{p_col}] из '{proj_name}': {len(col_data)} значений"
                self._log(f"  📊 Сохранено в '{result_var}': {col_str[:80]}")
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, col_str)
            
            elif operation == 'proj_table_row_count':
                cnt = str(len(proj_data))
                self._context[result_var] = cnt
                result = f"'{proj_name}': {len(proj_data)} строк"
                self._log(f"  📊 Сохранено в '{result_var}': {cnt}")
                # === СИНХРОНИЗАЦИЯ С ПРОЕКТНЫМИ ПЕРЕМЕННЫМИ ===
                self._sync_var_to_project(result_var, cnt)
            
            elif operation == 'proj_table_load_from_file':
                # Загрузка проектной таблицы из файла (аналогично proj_list_load_from_file)
                _pv = self._project_variables or {}
                _meta = getattr(self._workflow, 'metadata', {}) or {}
                _raw_tables = _pv.get('_project_tables', _meta.get('project_tables', []))
                
                # Находим конфиг таблицы
                tbl_config = None
                for _tcfg in (_raw_tables or []):
                    if isinstance(_tcfg, dict) and _tcfg.get('name') == proj_name:
                        tbl_config = _tcfg
                        break
                
                if not tbl_config:
                    return f"⚠ Проектная таблица '{proj_name}' не найдена в конфигурации"
                
                fp = tbl_config.get('file_path', '')
                if not fp:
                    return f"⚠ У таблицы '{proj_name}' не указан file_path"
                
                # Разрешаем путь
                if not os.path.isabs(fp):
                    fp = os.path.join(self._tool_executor._root, fp)
                
                if not os.path.isfile(fp):
                    return f"⚠ Файл таблицы не найден: {fp}"
                
                # Загружаем
                try:
                    import csv
                    enc = tbl_config.get('encoding', 'utf-8') or 'utf-8'
                    with open(fp, 'r', encoding=enc, errors='replace') as f:
                        reader = csv.reader(f)
                        loaded_rows = [row for row in reader]
                    
                    # Убираем заголовок если нужно
                    if tbl_config.get('has_header') and loaded_rows:
                        loaded_rows = loaded_rows[1:]
                    
                    proj_data = loaded_rows
                    result = f"Загружено {len(proj_data)} строк из файла для '{proj_name}'"
                except Exception as e:
                    return f"⚠ Ошибка загрузки файла: {e}"
            
            elif operation == 'proj_table_clear':
                proj_data = []
                result = f"'{proj_name}' очищена"
            
            else:
                result = f"Неизвестная proj_table операция: {operation}"
            
            proj_tables[proj_name] = proj_data
            self._context['_project_tables'] = proj_tables
            # ═══ ЗЕРКАЛИРУЕМ В ПРЯМОЙ КЛЮЧ КОНТЕКСТА (как у списков) ═══
            if proj_data:
                self._context[proj_name] = list(proj_data)
            # ── Персистим изменения в metadata workflow ──
            try:
                if hasattr(self._workflow, 'metadata') and self._workflow.metadata is not None:
                    _meta = self._workflow.metadata
                    if isinstance(_meta, str):
                        try:
                            import json as _json
                            _meta = _json.loads(_meta) if _meta.strip() else {}
                        except Exception:
                            _meta = {}
                    # Работаем с _meta как со словарём
                    for _ptbl in _meta.get('project_tables', []):
                        # ... изменения ...
                        if isinstance(_ptbl, dict) and _ptbl.get('name') == proj_name:
                            _ptbl['rows'] = list(proj_data)
                            break
                    # Сохраняем обратно как строку если нужно
                    if isinstance(self._workflow.metadata, str):
                        self._workflow.metadata = _json.dumps(_meta, ensure_ascii=False)
            except Exception:
                pass
            self._log(f"  📊 {result}")
            return f"📊 {result}"
        
        else:
            result = f"Неизвестная операция: {operation}"
        
        # ═══ ВСЕГДА СИНХРОНИЗИРУЕМ ТАБЛИЦУ В КОНТЕКСТ И METADATA ═══
        self._context[table_var] = table
        
        # Синхронизация в metadata для UI (ВСЕГДА, не только для _project_table_*)
        if table_var and self._workflow:
            self._sync_table_to_metadata(table_var, table)
        
        # Также в _project_tables для совместимости
        proj_tables = self._context.get('_project_tables', {})
        if table_var:
            proj_tables[table_var] = table
        self._context['_project_tables'] = proj_tables
        
        self._log(f"  📊 {result}")
        return f"📊 {result}"
    
    async def _exec_file_operation(self, node: AgentNode) -> str:
        """📄 File Operation."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        action = cfg.get('file_action', 'read')
        file_path = cfg.get('file_path', '')
        new_path = cfg.get('new_path', '')
        content = cfg.get('content', '') or node.user_prompt_template or ''
        append = cfg.get('append_mode', True)
        newline = cfg.get('add_newline', True)
        delete_after = cfg.get('delete_after_read', False)
        encoding = cfg.get('encoding', 'utf-8')
        result_var = cfg.get('result_var', 'file_content')
        
        def subst(s):
            for k, v in self._context.items():
                if not k.startswith('_'):
                    s = s.replace(f'{{{k}}}', str(v))
            return s
        file_path = subst(file_path)
        new_path = subst(new_path)
        content = subst(content)
        
        fp = os.path.join(self._tool_executor._root, file_path) if file_path and not os.path.isabs(file_path) else file_path
        
        if action == 'read':
            if not os.path.isfile(fp): raise RuntimeError(f"Файл не найден: {fp}")
            enc = encoding if encoding != 'auto' else 'utf-8'
            text = Path(fp).read_text(encoding=enc, errors='replace')
            self._context[result_var] = text
            self._sync_var_to_project(result_var, text)
            if delete_after: os.unlink(fp)
            return f"📄 Прочитано {len(text)} символов из {os.path.basename(fp)}"
        elif action == 'write':
            os.makedirs(os.path.dirname(fp) or '.', exist_ok=True)
            mode = 'a' if append else 'w'
            with open(fp, mode, encoding='utf-8') as f:
                f.write(content + ('\n' if newline else ''))
            return f"📄 Записано в {os.path.basename(fp)}"
        elif action == 'copy':
            import shutil
            np = os.path.join(self._tool_executor._root, new_path) if not os.path.isabs(new_path) else new_path
            os.makedirs(os.path.dirname(np) or '.', exist_ok=True)
            shutil.copy2(fp, np)
            return f"📄 Скопировано → {np}"
        elif action == 'move':
            import shutil
            np = os.path.join(self._tool_executor._root, new_path) if not os.path.isabs(new_path) else new_path
            os.makedirs(os.path.dirname(np) or '.', exist_ok=True)
            shutil.move(fp, np)
            return f"📄 Перемещено → {np}"
        elif action == 'delete':
            if os.path.isfile(fp): os.unlink(fp)
            return f"📄 Удалено: {fp}"
        elif action == 'exists':
            exists = os.path.isfile(fp)
            self._context[result_var] = str(exists)
            self._sync_var_to_project(result_var, str(exists))
            if not exists: raise RuntimeError(f"Файл не существует: {fp}")
            return f"📄 Файл {'существует' if exists else 'НЕ существует'}: {fp}"
        return "⚠ Неизвестное действие"

    async def _exec_dir_operation(self, node: AgentNode) -> str:
        """📁 Directory Operation."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        action = cfg.get('dir_action', 'list_files')
        dir_path = cfg.get('dir_path', '')
        new_path = cfg.get('new_path', '')
        recursive = cfg.get('recursive', False)
        mask = cfg.get('mask', '')
        file_select = cfg.get('file_select', 'random')
        file_index = cfg.get('file_index', 0)
        result_var = cfg.get('result_var', 'dir_result')
        result_list = cfg.get('result_list', 'file_list')
        
        def subst(s):
            for k, v in self._context.items():
                if not k.startswith('_'): s = s.replace(f'{{{k}}}', str(v))
            return s
        dir_path = subst(dir_path)
        dp = os.path.join(self._tool_executor._root, dir_path) if dir_path and not os.path.isabs(dir_path) else dir_path
        
        import glob, fnmatch, random as _rnd
        if action == 'create':
            os.makedirs(dp, exist_ok=True)
            return f"📁 Создана: {dp}"
        elif action == 'delete':
            import shutil
            if os.path.isdir(dp): shutil.rmtree(dp)
            return f"📁 Удалена: {dp}"
        elif action == 'exists':
            exists = os.path.isdir(dp)
            self._context[result_var] = str(exists)
            if not exists: raise RuntimeError(f"Директория не существует: {dp}")
            return f"📁 {'Существует' if exists else 'НЕ существует'}: {dp}"
        elif action in ('list_files', 'list_dirs', 'get_file'):
            masks = [m.strip() for m in mask.split('|')] if mask else ['*']
            files = []
            for m in masks:
                if recursive:
                    for root, dirs, fnames in os.walk(dp):
                        for fn in fnames if action != 'list_dirs' else dirs:
                            if fnmatch.fnmatch(fn, m):
                                files.append(os.path.join(root, fn))
                else:
                    pattern = os.path.join(dp, m)
                    found = glob.glob(pattern)
                    if action == 'list_dirs':
                        files.extend([f for f in found if os.path.isdir(f)])
                    else:
                        files.extend([f for f in found if os.path.isfile(f)])
            files = sorted(set(files))
            
            if action == 'get_file':
                if not files: raise RuntimeError(f"Нет файлов в {dp}")
                idx = _rnd.randint(0, len(files)-1) if file_select == 'random' else min(file_index, len(files)-1)
                self._context[result_var] = files[idx]
                return f"📁 Файл: {files[idx]}"
            else:
                self._context[result_list] = files
                self._context[result_var] = str(len(files))
                self._sync_var_to_project(result_var, str(len(files)))
                if result_list:
                    self._sync_list_to_metadata(result_list, files)
                return f"📁 Найдено: {len(files)} элементов"
        elif action in ('copy', 'move'):
            import shutil
            np = os.path.join(self._tool_executor._root, subst(new_path)) if not os.path.isabs(new_path) else subst(new_path)
            if action == 'copy': shutil.copytree(dp, np, dirs_exist_ok=True)
            else: shutil.move(dp, np)
            return f"📁 {'Скопировано' if action == 'copy' else 'Перемещено'} → {np}"
        return "⚠ Неизвестное действие"

    async def _exec_text_processing(self, node: AgentNode) -> str:
        """✂️ Text Processing."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        action = cfg.get('text_action', 'regex')
        input_text = cfg.get('input_text', '') or node.user_prompt_template or ''
        pattern = cfg.get('pattern', '')
        replacement = cfg.get('replacement', '')
        separator = cfg.get('separator', ',')
        take_mode = cfg.get('take_mode', 'first')
        match_index = cfg.get('match_index', 0)
        error_on_empty = cfg.get('error_on_empty', False)
        substr_from = cfg.get('substr_from', 0)
        substr_to = cfg.get('substr_to', 0)
        result_var = cfg.get('result_var', 'text_result')
        result_list = cfg.get('result_list', '')
        
        def subst(s):
            for k, v in self._context.items():
                if not k.startswith('_'): s = s.replace(f'{{{k}}}', str(v))
            return s
        input_text = subst(input_text); pattern = subst(pattern); replacement = subst(replacement)
        
        import re, random as _rnd
        if action == 'regex':
            matches = re.findall(pattern, input_text)
            if not matches and error_on_empty: raise RuntimeError(f"Regex не нашёл: {pattern[:60]}")
            if take_mode == 'first': val = matches[0] if matches else ''
            elif take_mode == 'all':
                if result_list:
                    self._context[result_list] = matches
                    self._sync_list_to_metadata(result_list, [str(m) for m in matches])
                val = '\n'.join(str(m) for m in matches)
            elif take_mode == 'random': val = _rnd.choice(matches) if matches else ''
            elif take_mode == 'by_index': val = matches[min(match_index, len(matches)-1)] if matches else ''
            else: val = matches[0] if matches else ''
            if isinstance(val, tuple): val = val[0]
            self._context[result_var] = str(val)
            self._sync_var_to_project(result_var, str(val))
            return f"✂️ Regex: {len(matches)} совпадений → {str(val)[:80]}"
        elif action == 'replace':
            result = input_text.replace(pattern, replacement)
            self._context[result_var] = result
            self._sync_var_to_project(result_var, result)
            return f"✂️ Замена: {len(result)} символов"
        elif action == 'split':
            parts = input_text.split(separator)
            if result_list:
                self._context[result_list] = parts
                self._sync_list_to_metadata(result_list, parts)
            self._context[result_var] = str(len(parts))
            self._sync_var_to_project(result_var, str(len(parts)))
            return f"✂️ Split: {len(parts)} частей"
        elif action == 'spintax':
            def spin(text):
                while '{' in text and '|' in text:
                    text = re.sub(r'\{([^{}]+)\}', lambda m: _rnd.choice(m.group(1).split('|')), text)
                return text
            self._context[result_var] = spin(input_text)
            self._sync_var_to_project(result_var, self._context[result_var])
            return f"✂️ Spintax: {self._context[result_var][:80]}"
        elif action == 'to_lower':
            self._context[result_var] = input_text.lower()
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'to_upper':
            self._context[result_var] = input_text.upper()
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'trim':
            self._context[result_var] = input_text.strip()
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'url_encode':
            from urllib.parse import quote
            self._context[result_var] = quote(input_text)
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'url_decode':
            from urllib.parse import unquote
            self._context[result_var] = unquote(input_text)
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'substring':
            end = substr_to if substr_to > 0 else len(input_text)
            self._context[result_var] = input_text[substr_from:end]
            self._sync_var_to_project(result_var, self._context[result_var])
        elif action == 'translit':
            tr = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y',
                  'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
                  'х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
            result = ''.join(tr.get(c, tr.get(c.lower(), c).upper() if c.isupper() else tr.get(c, c)) for c in input_text)
            self._context[result_var] = result
            self._sync_var_to_project(result_var, result)
        elif action == 'to_var':
            self._context[result_var] = input_text
            self._sync_var_to_project(result_var, input_text)
        elif action == 'to_list':
            sep = separator.replace('\\n', '\n').replace('\\t', '\t')
            parts = input_text.split(sep)
            if result_list:
                self._context[result_list] = parts
                self._sync_list_to_metadata(result_list, parts)
            self._context[result_var] = str(len(parts))
            self._sync_var_to_project(result_var, str(len(parts)))
        return f"✂️ {action}: → {str(self._context.get(result_var, ''))[:80]}"

    async def _exec_json_xml(self, node: AgentNode) -> str:
        """🔣 JSON/XML."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        data_type = cfg.get('data_type', 'json')
        action = cfg.get('jx_action', 'parse')
        input_source = cfg.get('input_source', 'text')
        input_var = cfg.get('input_var', '')
        input_file = cfg.get('input_file', '')
        query_expr = cfg.get('query_expr', '')
        key_path = cfg.get('key_path', '')
        set_value = cfg.get('set_value', '')
        prop_name = cfg.get('property_name', '')
        result_var = cfg.get('result_var', 'jx_result')
        result_list = cfg.get('result_list', '')
        
        # Получаем входные данные в зависимости от источника
        if input_source == 'variable':
            clean_var = input_var.strip('{}').strip()
            raw = str(self._context.get(clean_var, ''))
        elif input_source == 'file':
            fpath = input_file
            if not os.path.isabs(fpath):
                fpath = os.path.join(self._tool_executor._root, fpath)
            try:
                raw = Path(fpath).read_text(encoding='utf-8')
                self._log(f"  📂 Загружено из файла: {input_file} ({len(raw)} символов)")
            except Exception as e:
                return f"⚠ Ошибка чтения файла {input_file}: {e}"
        else:
            # text — из user_prompt_template или inline_data
            raw = cfg.get('inline_data', '') or node.user_prompt_template or ''
        
        # Подстановка переменных
        for k, v in self._context.items():
            if not k.startswith('_'):
                raw = raw.replace(f'{{{k}}}', str(v))
                query_expr = query_expr.replace(f'{{{k}}}', str(v))
                key_path = key_path.replace(f'{{{k}}}', str(v))
                set_value = set_value.replace(f'{{{k}}}', str(v))
        
        if not raw.strip() and action == 'parse':
            return "⚠ Нет входных данных для парсинга"
        
        if data_type == 'json':
            import json as _json
            if action == 'parse':
                data = _json.loads(raw)
                self._context['_parsed_json'] = data
                parsed_str = _json.dumps(data, ensure_ascii=False, indent=2)[:1000]
                self._context[result_var] = parsed_str
                self._sync_var_to_project(result_var, parsed_str)
                return f"🔣 JSON parsed ({len(raw)} chars)"
            elif action == 'get_value':
                data = self._context.get('_parsed_json') or _json.loads(raw)
                keys = key_path.replace('[', '.').replace(']', '').split('.')
                val = data
                for k in keys:
                    if k.isdigit(): val = val[int(k)]
                    else: val = val[k]
                result_str = str(val) if not isinstance(val, str) else val
                self._context[result_var] = result_str
                self._sync_var_to_project(result_var, result_str)
                return f"🔣 JSON get: {key_path} = {result_str[:80]}"
            elif action == 'set_value':
                data = self._context.get('_parsed_json') or _json.loads(raw)
                keys = key_path.replace('[', '.').replace(']', '').split('.')
                obj = data
                for k in keys[:-1]:
                    if k.isdigit(): obj = obj[int(k)]
                    else: obj = obj[k]
                last_key = keys[-1]
                if last_key.isdigit():
                    obj[int(last_key)] = set_value
                else:
                    obj[last_key] = set_value
                self._context['_parsed_json'] = data
                result_str = _json.dumps(data, ensure_ascii=False, indent=2)[:1000]
                self._context[result_var] = result_str
                self._sync_var_to_project(result_var, result_str)
                return f"🔣 JSON set: {key_path} = {set_value[:40]}"
            elif action == 'query':
                data = self._context.get('_parsed_json') or _json.loads(raw)
                try:
                    import jsonpath_ng.ext as jp
                    expr = jp.parse(query_expr)
                    matches = [m.value for m in expr.find(data)]
                except ImportError:
                    keys = query_expr.lstrip('$.').split('.')
                    val = data
                    for k in keys:
                        if k.endswith('[*]'):
                            val = [item for item in val[k[:-3]]]
                        elif k.isdigit(): val = val[int(k)]
                        else: val = val[k]
                    matches = val if isinstance(val, list) else [val]
                str_matches = [str(m) for m in matches]
                if result_list:
                    self._context[result_list] = str_matches
                    self._sync_list_to_metadata(result_list, str_matches)
                first = str_matches[0] if str_matches else ''
                self._context[result_var] = first
                self._sync_var_to_project(result_var, first)
                return f"🔣 JsonPath: {len(matches)} результатов"
            elif action == 'to_list':
                data = self._context.get('_parsed_json') or _json.loads(raw)
                keys = key_path.split('.') if key_path else []
                arr = data
                for k in keys:
                    arr = arr[k]
                vals = [str(item.get(prop_name, item) if isinstance(item, dict) else item) for item in arr]
                if result_list:
                    self._context[result_list] = vals
                    self._sync_list_to_metadata(result_list, vals)
                count_str = str(len(vals))
                self._context[result_var] = count_str
                self._sync_var_to_project(result_var, count_str)
                return f"🔣 JSON to_list: {len(vals)} элементов"
        else:
            import xml.etree.ElementTree as ET
            if action == 'parse':
                root = ET.fromstring(raw)
                self._context['_parsed_xml_str'] = raw
                parse_result = f"XML root: {root.tag}, children: {len(root)}"
                self._context[result_var] = parse_result
                self._sync_var_to_project(result_var, parse_result)
                return f"🔣 XML parsed: {root.tag}"
            elif action == 'query':
                root = ET.fromstring(self._context.get('_parsed_xml_str', raw))
                results = root.findall(query_expr)
                vals = [el.text or '' for el in results]
                if result_list:
                    self._context[result_list] = vals
                    self._sync_list_to_metadata(result_list, vals)
                first = vals[0] if vals else ''
                self._context[result_var] = first
                self._sync_var_to_project(result_var, first)
                return f"🔣 XPath: {len(vals)} результатов"
        return f"🔣 {action} done"

    async def _exec_variable_proc(self, node: AgentNode) -> str:
        """🔧 Variable Processing."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        action = cfg.get('var_action', 'set')
        var_name = cfg.get('var_name', '')
        var_value = cfg.get('var_value', '')
        step = cfg.get('step_value', 1)
        target_var = cfg.get('target_var', '')
        clear_except = cfg.get('clear_except', '')
        save_to_project = cfg.get('save_to_project', True)
        
        # Очищаем имя от фигурных скобок ПЕРЕД подстановкой — это ИМЯ, не значение
        var_name = var_name.strip('{}').strip() if var_name else var_name
        target_var = target_var.strip('{}').strip() if target_var else target_var
        
        # Подставляем переменные только в VALUE, НЕ в имя
        for k, v in self._context.items():
            if not k.startswith('_'):
                var_value = var_value.replace(f'{{{k}}}', str(v))
        
        result_msg = "⚠ Неизвестное действие"
        changed_vars = []  # Список (имя, значение) для синхронизации
        
        if action == 'set':
            self._context[var_name] = var_value
            changed_vars.append((var_name, var_value))
            result_msg = f"🔧 {var_name} = {var_value[:80]}"
        elif action == 'increment':
            try:
                cur = int(self._context.get(var_name, 0))
            except (ValueError, TypeError):
                cur = 0
            new_val = cur + step
            self._context[var_name] = str(new_val)
            changed_vars.append((var_name, str(new_val)))
            result_msg = f"🔧 {var_name}: {cur} → {new_val}"
        elif action == 'decrement':
            try:
                cur = int(self._context.get(var_name, 0))
            except (ValueError, TypeError):
                cur = 0
            new_val = cur - step
            self._context[var_name] = str(new_val)
            changed_vars.append((var_name, str(new_val)))
            result_msg = f"🔧 {var_name}: {cur} → {new_val}"
        elif action == 'clear':
            self._context.pop(var_name, None)
            # Обнуляем в project_variables, не удаляем — переменная остаётся видима в UI
            if self._project_variables is not None and isinstance(self._project_variables, dict):
                if var_name in self._project_variables:
                    if isinstance(self._project_variables[var_name], dict):
                        self._project_variables[var_name]['value'] = ''
                    else:
                        self._project_variables[var_name] = ''
                    if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                        self.signals.variable_updated.emit(var_name, '')
            result_msg = f"🔧 Очищено: {var_name}"
        elif action == 'clear_all':
            except_list = {e.strip() for e in clear_except.split(',') if e.strip()}
            keys = [k for k in self._context if not k.startswith('_') and k not in except_list]
            for k in keys: self._context.pop(k)
            result_msg = f"🔧 Очищено {len(keys)} переменных"
        elif action == 'copy':
            val = self._context.get(var_name, '')
            self._context[target_var] = val
            changed_vars.append((target_var, str(val)))
            result_msg = f"🔧 {var_name} → {target_var}"
        elif action == 'concat':
            separator = cfg.get('concat_separator', '')
            parts = [str(self._context.get(p.strip().strip('{}'), p.strip())) for p in var_value.split(',')]
            val = separator.join(parts)
            self._context[var_name] = val
            changed_vars.append((var_name, val))
            result_msg = f"🔧 concat → {var_name} = {val[:80]}"
        elif action == 'length':
            src = self._context.get(var_name, '')
            if isinstance(src, list):
                val = str(len(src))
            else:
                val = str(len(str(src)))
            self._context[target_var or var_name + '_len'] = val
            changed_vars.append((target_var or var_name + '_len', val))
            result_msg = f"🔧 len({var_name}) = {val}"
        elif action == 'type_cast':
            cast_type = cfg.get('cast_type', 'string')
            raw = self._context.get(var_name, '')
            try:
                if cast_type == 'int': val = str(int(float(str(raw))))
                elif cast_type == 'float': val = str(float(str(raw)))
                elif cast_type == 'bool': val = str(str(raw).lower() in ('true', '1', 'yes'))
                else: val = str(raw)
            except (ValueError, TypeError):
                val = str(raw)
            self._context[var_name] = val
            changed_vars.append((var_name, val))
            result_msg = f"🔧 {var_name} → {cast_type} = {val}"
        
        self._log(f"  {result_msg}")
        
        # === СИНХРОНИЗАЦИЯ С ПЕРЕМЕННЫМИ ПРОЕКТА ===
        if save_to_project and changed_vars:
            project_vars = getattr(self, '_project_variables', None)
            for vname, vval in changed_vars:
                if project_vars is not None and isinstance(project_vars, dict):
                    if vname in project_vars:
                        if isinstance(project_vars[vname], dict):
                            project_vars[vname]['value'] = str(vval)
                        else:
                            project_vars[vname] = str(vval)
                        self._log(f"  📝 Обновлена переменная проекта: {vname} = {str(vval)[:60]}")
                    else:
                        project_vars[vname] = {
                            'value': str(vval),
                            'default': '',
                            'type': 'string'
                        }
                        self._log(f"  📝 Создана переменная проекта: {vname} = {str(vval)[:60]}")
                    if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                        self.signals.variable_updated.emit(vname, str(vval))
        
        return result_msg

    async def _exec_random_gen(self, node: AgentNode) -> str:
        """🎲 Random Generation."""
        import random as _rnd, string
        cfg = getattr(node, 'snippet_config', {}) or {}
        rtype = cfg.get('random_type', 'number')
        result_var = cfg.get('result_var', 'random_result')
        
        if rtype == 'number':
            n_from = cfg.get('num_from', 0)
            n_to = cfg.get('num_to', 100)
            val = str(_rnd.randint(n_from, max(n_from, n_to - 1)))
        elif rtype == 'text':
            min_len = cfg.get('str_len_min', 5)
            max_len = cfg.get('str_len_max', 12)
            use_upper = cfg.get('use_upper', True)
            use_lower = cfg.get('use_lower', True)
            use_digits = cfg.get('use_digits', True)
            custom = cfg.get('custom_chars', '')
            require_all = cfg.get('require_all', False)
            
            if custom:
                chars = custom
            else:
                chars = ''
                if use_upper: chars += string.ascii_uppercase
                if use_lower: chars += string.ascii_lowercase
                if use_digits: chars += string.digits
                if not chars: chars = string.ascii_letters
            
            length = _rnd.randint(min_len, max(min_len, max_len - 1))
            if require_all and not custom:
                parts = []
                if use_upper: parts.append(_rnd.choice(string.ascii_uppercase))
                if use_lower: parts.append(_rnd.choice(string.ascii_lowercase))
                if use_digits: parts.append(_rnd.choice(string.digits))
                rest = length - len(parts)
                parts.extend(_rnd.choices(chars, k=max(0, rest)))
                _rnd.shuffle(parts)
                val = ''.join(parts)
            else:
                val = ''.join(_rnd.choices(chars, k=length))
        elif rtype == 'login':
            formula = cfg.get('login_formula', '[Eng|3]')
            # Простая реализация слоговой генерации
            vowels = 'aeiou'
            consonants = 'bcdfghjklmnpqrstvwxyz'
            def gen_syllable():
                return _rnd.choice(consonants) + _rnd.choice(vowels) + _rnd.choice(consonants + '')
            
            import re
            def expand(f):
                def repl_eng(m):
                    n = int(m.group(1))
                    return ''.join(gen_syllable() for _ in range(n))
                def repl_num(m):
                    a, b = int(m.group(1)), int(m.group(2))
                    return str(_rnd.randint(a, b))
                def repl_text(m):
                    n = int(m.group(1))
                    mode = m.group(2)
                    chars = ''
                    if 'U' in mode: chars += string.ascii_uppercase
                    if 'L' in mode or 'l' in mode: chars += string.ascii_lowercase
                    if 'D' in mode or 'd' in mode: chars += string.digits
                    if not chars: chars = string.ascii_letters + string.digits
                    return ''.join(_rnd.choices(chars, k=n))
                def repl_sym(m):
                    n_str = m.group(1); syms = m.group(2)
                    # n_str can be a nested expression, simplify
                    try: n = int(n_str)
                    except: n = _rnd.randint(0, 3)
                    return ''.join(_rnd.choices(syms, k=n)) if n > 0 else ''
                
                f = re.sub(r'\[Eng\|(\d+)\]', repl_eng, f)
                f = re.sub(r'\[Lat\|(\d+)\]', repl_eng, f)
                f = re.sub(r'\[Jap\|(\d+)\]', lambda m: ''.join(gen_syllable() for _ in range(int(m.group(1)))), f)
                f = re.sub(r'\[RndNum\|(\d+)\|(\d+)\]', repl_num, f)
                f = re.sub(r'\[RndText\|(\d+)\|([ULDuld]+)\]', repl_text, f)
                f = re.sub(r'\[RndSym\|([^|]+)\|([^\]]+)\]', repl_sym, f)
                return f
            val = expand(formula)
        else:
            val = str(_rnd.randint(0, 99))
        
        # Очищаем имя переменной от фигурных скобок {var} → var ПЕРЕД записью в контекст
        clean_var_name = result_var.strip('{}').strip() if result_var else result_var
        self._context[clean_var_name] = val
        self._log(f"  🎲 Random ({rtype}): {val}")
        
        # === СОХРАНЕНИЕ В ПЕРЕМЕННЫЕ ПРОЕКТА ===
        
        # Проверяем разные варианты структуры project_variables
        project_vars = getattr(self, '_project_variables', None)
        self._log(f"  [DEBUG] result_var={result_var}, clean_var={clean_var_name}, project_vars exists={project_vars is not None}")
        
        if project_vars is not None and isinstance(project_vars, dict):
            if clean_var_name in project_vars:
                if isinstance(project_vars[clean_var_name], dict):
                    project_vars[clean_var_name]['value'] = str(val)
                else:
                    project_vars[clean_var_name] = str(val)
                self._log(f"  📝 Обновлена переменная проекта: {clean_var_name} = {val}")
            else:
                project_vars[clean_var_name] = {
                    'value': str(val),
                    'default': '',
                    'type': 'string'
                }
                self._log(f"  📝 Создана переменная проекта: {clean_var_name} = {val}")
            if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
                self.signals.variable_updated.emit(clean_var_name, str(val))
        
        return f"🎲 {rtype}: {val}"
    
    
    def _node_cfg(self, node) -> dict:
        """Вернуть snippet_config только если тип совпадает с текущим agent_type."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        stored_type = cfg.get('_snippet_type')
        if stored_type and stored_type != node.agent_type.value:
            return {}
        return cfg

    async def _exec_browser_launch(self, node) -> str:
        """Запуск браузерного инстанса."""
        try:
            from constructor.browser_module import (
                BrowserManager, BrowserProfileManager,
                execute_browser_launch_snippet,
            )
            # ═══ В многопоточном режиме берём менеджер проекта, а не глобальный синглтон ═══
            pbm = getattr(self, 'project_browser_manager', None)
            manager = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()
            pm = BrowserProfileManager(self._project_root or "")

            self._log(f"🌐 BROWSER_LAUNCH: запуск...")

            # ═══ Lock для многопоточного запуска браузера ═══
            # Предотвращает гонку за --user-data-dir и одновременный запуск
            _lock = getattr(self, '_browser_launch_lock', None)
            if _lock:
                self._log("🔒 Ожидание блокировки запуска браузера...")
                _lock.acquire()
                self._log("🔓 Блокировка получена, запускаем браузер...")
            
            try:
                self._context = execute_browser_launch_snippet(
                    cfg=self._node_cfg(node),
                    context=self._context,
                    profile_manager=pm,
                    manager=manager,
                    logger=self._log,
                    embed_target=None,
                    project_browser_manager=pbm,
                )
            finally:
                if _lock:
                    _lock.release()
                    self._log("🔓 Блокировка запуска браузера снята")

            iid = self._context.get("browser_instance_id", "")
            _cfg_br = self._node_cfg(node)
            _window_mode = _cfg_br.get('window_mode', 'embed_panel')
            _do_tray = _window_mode == 'embed_panel'
            if iid and _do_tray:
                # ═══ ИСПРАВЛЕНИЕ: ищем инстанс сначала в project_browser_manager, потом в глобальном ═══
                inst = None
                if pbm:
                    inst = pbm.get_instance(iid)
                if not inst:
                    inst = manager.get_instance(iid)
                if inst:
                    _iid_copy = iid
                    _inst_copy = inst
                    _tray_cb = getattr(self, '_browser_tray_callback', None)
                    
                    def _hide_and_tray(_inst=_inst_copy, _iid=_iid_copy, _cb=_tray_cb):
                        import time
                        time.sleep(2)
                        _inst.minimize_window()
                        if _cb:
                            profile_name = getattr(_inst.profile, 'name', f"Browser {_iid}")
                            try:
                                _cb(_iid, profile_name)
                            except Exception as e:
                                self._log(f"⚠️ Ошибка tray callback: {e}")
                            self._log(f"📥 Браузер {_iid} встроен в панель браузеров")
                        else:
                            self._log(f"⚠️ _browser_tray_callback не найден")
                    
                    import threading
                    threading.Thread(target=_hide_and_tray, daemon=True).start()
            elif iid and _window_mode == 'desktop':
                inst = manager.get_instance(iid)
                if inst:
                    self._log(f"🖥 Браузер {iid} запущен в режиме рабочего стола")

            return "✅ Браузер запущен"
        except Exception as e:
            import traceback
            self._log(f"❌ Ошибка запуска браузера: {e}\n{traceback.format_exc()[:500]}")
            return f"❌ Ошибка запуска браузера: {e}"


    async def _exec_browser_action(self, node) -> str:
        """Выполнение действия браузера."""
        try:
            from constructor.browser_module import (
                BrowserManager, execute_browser_action_snippet,
            )
            # ═══ Используем менеджер проекта, а не глобальный синглтон ═══
            pbm = getattr(self, 'project_browser_manager', None)
            manager = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()
            
            self._context = execute_browser_action_snippet(
                cfg=getattr(node, 'snippet_config', {}) or {},
                context=self._context,
                manager=manager,
                logger=self._log,
                project_browser_manager=pbm,
            )
            cfg = getattr(node, 'snippet_config', {}) or {}
            return f"✅ Действие выполнено: {cfg.get('action', '?')}"
        except Exception as e:
            return f"❌ Ошибка действия браузера: {e}"

    async def _exec_browser_close(self, node) -> str:
        """Закрытие браузерного инстанса."""
        try:
            from constructor.browser_module import BrowserManager
            pbm = getattr(self, 'project_browser_manager', None)
            manager = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()
            cfg = getattr(node, 'snippet_config', {}) or {}

            # Ищем iid точно как execute_browser_action_snippet
            iid = cfg.get('instance_id')
            if not iid:
                iid = self._context.get('browser_instance_id')
            if not iid and pbm:
                iid = pbm.first_instance_id()
            if not iid:
                iid = next(iter(manager.all_instances()), None)

            # Получаем инстанс точно как Browser Action
            inst = None
            if iid:
                if pbm:
                    inst = pbm.get_instance(iid)
                if not inst:
                    inst = manager.get_instance(iid)

            if inst:
                # Закрываем через тот BrowserManager, где инстанс реально зарегистрирован.
                # pbm._manager — это реальный BrowserManager проекта (может отличаться от синглтона).
                owning_manager = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or manager
                owning_manager.close_instance(iid)
                if pbm and hasattr(pbm, '_owned_ids'):
                    pbm._owned_ids.discard(iid)
                return f"🔴 Закрыт инстанс: {iid}"
            else:
                # Закрываем всё через pbm._manager, а не глобальный синглтон
                if pbm and hasattr(pbm, '_manager'):
                    pbm._manager.close_all()
                    if hasattr(pbm, '_owned_ids'):
                        pbm._owned_ids.clear()
                else:
                    manager.close_all()
                return "🔴 Все браузеры закрыты"
        except Exception as e:
            return f"❌ Ошибка закрытия браузера: {e}"
    
    async def _exec_browser_screenshot(self, node) -> str:
        """📸 Browser Screenshot."""
        import base64, os
        from datetime import datetime
        from PyQt6.QtCore import QByteArray, QBuffer, QIODeviceBase

        cfg = getattr(node, 'snippet_config', {}) or {}

        def _get_inst():
            from constructor.browser_module import BrowserManager
            pbm = getattr(self, 'project_browser_manager', None)
            mgr = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()
            iid = cfg.get('instance_id') or self._context.get('browser_instance_id')
            if not iid and pbm and hasattr(pbm, 'first_instance_id'):
                iid = pbm.first_instance_id()
            if iid:
                return (pbm.get_instance(iid) if pbm else None) or mgr.get_instance(iid)
            insts = list((mgr.all_instances() or {}).values())
            return insts[0] if insts else None

        wait_before = cfg.get('wait_before', 0)
        if wait_before > 0:
            import asyncio
            await asyncio.sleep(wait_before / 1000.0)

        inst = _get_inst()
        if not inst:
            return "❌ Screenshot: нет активного инстанса браузера"

        try:
            # ═══ ИСПРАВЛЕНИЕ: используем get_screenshot_base64 (Selenium) ═══
            raw_b64 = None
            if hasattr(inst, 'get_screenshot_base64'):
                raw_b64 = inst.get_screenshot_base64()
            elif hasattr(inst, '_driver') and inst._driver:
                raw_b64 = inst._driver.get_screenshot_as_base64()

            if not raw_b64:
                return "❌ Screenshot: не удалось получить изображение"

            mode       = cfg.get('save_mode', 'var_only')
            var_out    = cfg.get('variable_out', 'screenshot_b64').strip().strip('{}')
            save_dir   = cfg.get('save_path', '').strip()
            file_name  = cfg.get('file_name', 'screenshot_{timestamp}.png')
            img_format = cfg.get('image_format', 'png').lower()
            quality    = cfg.get('jpeg_quality', 85)

            # Подстановка {timestamp} и переменных
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = file_name.replace('{timestamp}', ts)
            for k, v in self._context.items():
                file_name = file_name.replace(f'{{{k}}}', str(v))
            if not file_name.lower().endswith(f'.{img_format}'):
                file_name = f"{file_name}.{img_format}"

            # Сохранить в переменную
            if mode in ('var_only', 'both') and var_out:
                self._context[var_out] = raw_b64
                self._sync_var_to_project(var_out, raw_b64)

            # Сохранить в файл
            if mode in ('file_only', 'both'):
                root = save_dir or self._project_root or '.'
                for k, v in self._context.items():
                    root = root.replace(f'{{{k}}}', str(v))
                os.makedirs(root, exist_ok=True)
                out_path = os.path.join(root, file_name)

                img_data = base64.b64decode(raw_b64)

                if img_format == 'png':
                    with open(out_path, 'wb') as f:
                        f.write(img_data)
                elif img_format in ('jpg', 'jpeg', 'webp'):
                    # ═══ ИСПРАВЛЕНИЕ: конвертация через Pillow вместо QPixmap ═══
                    # QPixmap нельзя использовать из QThread — вызывает зависание UI
                    try:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(img_data))
                        if img_format in ('jpg', 'jpeg'):
                            img = img.convert('RGB')  # JPEG не поддерживает alpha
                            img.save(out_path, 'JPEG', quality=quality)
                        elif img_format == 'webp':
                            img.save(out_path, 'WEBP', quality=quality)
                    except ImportError:
                        # Pillow не установлен — сохраняем как PNG
                        fallback_path = out_path.rsplit('.', 1)[0] + '.png'
                        with open(fallback_path, 'wb') as f:
                            f.write(img_data)
                        out_path = fallback_path
                        self._log(f"  ⚠ Pillow не установлен, сохранено как PNG")
                else:
                    with open(out_path, 'wb') as f:
                        f.write(img_data)

                if cfg.get('open_after_save', False):
                    import subprocess, sys
                    if sys.platform == 'win32':
                        os.startfile(out_path)
                    else:
                        subprocess.run(['xdg-open', out_path])

                self._log(f"📸 Скриншот сохранён: {out_path}")
                return f"📸 Скриншот: {os.path.basename(out_path)}"

            return f"📸 Скриншот в переменную {var_out}: {len(raw_b64)} символов"
        except Exception as e:
            import traceback
            return f"❌ Screenshot ошибка: {e}\n{traceback.format_exc()[:300]}"
    
    async def _exec_project_in_project(self, node) -> str:
        """Выполнить вложенный проект как подпроект с передачей переменных."""
        import copy
        from services.agent_models import AgentWorkflow

        cfg = getattr(node, 'snippet_config', {}) or {}

        # ── 1. Разрешаем путь к проекту (поддержка {переменных}) ──────────────
        raw_path = cfg.get('project_path', '').strip()
        if not raw_path:
            raise RuntimeError("PROJECT_IN_PROJECT: не задан путь к вложенному проекту")

        resolved_path = self._resolve_variables(raw_path)
        project_file = Path(resolved_path)

        # Если файл не найден — пробуем рядом с текущим проектом
        if not project_file.exists() and self._project_root:
            project_file = Path(self._project_root) / resolved_path

        if not project_file.exists():
            raise FileNotFoundError(f"PROJECT_IN_PROJECT: файл не найден: {project_file}")

        self._log(f"📦 Загружаю вложенный проект: {project_file}")

        # ── 2. Загружаем sub-workflow ──────────────────────────────────────────
        try:
            sub_workflow = AgentWorkflow.load(str(project_file))
        except Exception as e:
            raise RuntimeError(f"PROJECT_IN_PROJECT: ошибка загрузки проекта: {e}")

        # ── 3. Формируем сопоставление переменных (outer → inner) ─────────────
        match_same = cfg.get('match_same_names', True)
        no_return_on_fail = cfg.get('no_return_on_fail', False)

        # Парсим ручное сопоставление из текстового поля:
        # Формат: "outer_var = inner_var" (по одному на строку, # — комментарий)
        manual_map: dict[str, str] = {}   # {inner_name: outer_name}
        var_map_text = cfg.get('var_map', '')
        for line in var_map_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                outer, inner = line.split('=', 1)
                outer = outer.strip()
                inner = inner.strip()
                if outer and inner:
                    manual_map[inner] = outer  # inner_var ← outer_var

        # ── 4. Снимаем текущие переменные внешнего проекта ────────────────────
        outer_vars: dict = {}
        if self._project_variables is not None:
            outer_vars = dict(self._project_variables)
        # Также смотрим в execution context
        outer_vars.update({k: v for k, v in self._context.items()
                           if not k.startswith('_')})

        # ── 5. Заполняем переменные sub-workflow ──────────────────────────────
        sub_vars: dict = dict(sub_workflow.project_variables)

        for inner_name in list(sub_vars.keys()):
            # Ручное сопоставление (высший приоритет)
            if inner_name in manual_map:
                outer_name = manual_map[inner_name]
                if outer_name in outer_vars:
                    val = outer_vars[outer_name]
                    if isinstance(sub_vars[inner_name], dict):
                        sub_vars[inner_name]['value'] = val
                    else:
                        sub_vars[inner_name] = val
            elif match_same and inner_name in outer_vars:
                # Автосопоставление по одинаковым именам
                val = outer_vars[inner_name]
                if isinstance(sub_vars[inner_name], dict):
                    sub_vars[inner_name]['value'] = val
                else:
                    sub_vars[inner_name] = val

        sub_workflow.project_variables = sub_vars

        # ── 6. Запускаем sub-workflow ──────────────────────────────────────────
        # Используем тот же класс WorkflowRuntime, но без Qt-сигналов UI
        sub_context: dict = {}
        sub_success = True
        sub_error = ""

        try:
            # Строим плоский context из sub_vars для sub-runtime
            flat_sub_vars: dict = {}
            for k, v in sub_vars.items():
                flat_sub_vars[k] = v['value'] if isinstance(v, dict) and 'value' in v else v

            sub_runtime = WorkflowRuntime(
                workflow=sub_workflow,
                model_manager=self._model_manager,
                logger=lambda msg: self._log(f"  [SUB] {msg}"),
                project_root=str(project_file.parent),
            )
            # Передаём контекст как начальные project_variables
            sub_runtime._project_variables = flat_sub_vars
            sub_runtime._context = copy.deepcopy(flat_sub_vars)

            # Запускаем синхронно в текущем event loop
            await sub_runtime._run_workflow_async()

            # Забираем итоговый контекст
            sub_context = sub_runtime._context or {}
            if sub_runtime._project_variables:
                sub_context.update(sub_runtime._project_variables)

        except Exception as e:
            sub_success = False
            sub_error = str(e)
            self._log(f"  ❌ Вложенный проект завершился с ошибкой: {e}")
            if no_return_on_fail:
                raise RuntimeError(f"PROJECT_IN_PROJECT failed: {e}")

        # ── 7. Возвращаем переменные из sub-workflow в outer ──────────────────
        if sub_success or not no_return_on_fail:
            # Обратное сопоставление: inner → outer
            outer_inner_map: dict[str, str] = {v: k for k, v in manual_map.items()}
            # manual_map: {inner: outer} → outer_inner_map: {inner: outer} (для обратного копирования)

            for inner_name, inner_val in sub_context.items():
                if inner_name.startswith('_'):
                    continue

                outer_name = None

                # Ручное сопоставление: ищем inner_name в manual_map
                if inner_name in manual_map:
                    outer_name = manual_map[inner_name]
                elif match_same and inner_name in outer_vars:
                    outer_name = inner_name

                if outer_name and self._project_variables is not None:
                    self._project_variables[outer_name] = inner_val
                    self._context[outer_name] = inner_val
                    self._log(f"  ↩ {inner_name} → {outer_name} = {str(inner_val)[:60]}")

        status = "✅ успешно" if sub_success else f"❌ ошибка: {sub_error}"
        self._log(f"📦 Вложенный проект завершён: {status}")
        return f"project_in_project: {status}"
    
    async def _exec_project_info(self, node) -> str:
        """🔎 Project Info — системная информация о проекте."""
        import json
        cfg = getattr(node, 'snippet_config', {}) or {}
        info_type      = cfg.get('info_type', 'browser_ids')
        result_var     = cfg.get('result_var', 'project_info').strip().strip('{}')
        result_list_var = cfg.get('result_list_var', '').strip().strip('{}')
        active_var     = cfg.get('active_browser_var', '').strip().strip('{}')
        count_var      = cfg.get('browser_count_var', '').strip().strip('{}')
        fmt            = cfg.get('format', 'csv')
        inc_inactive   = cfg.get('include_inactive', False)

        def _set(key, val):
            if key:
                self._context[key] = val
                self._sync_var_to_project(key, str(val) if not isinstance(val, str) else val)

        def _fmt(lst):
            if fmt == 'csv':
                return ','.join(str(x) for x in lst)
            elif fmt == 'lines':
                return '\n'.join(str(x) for x in lst)
            else:
                return json.dumps(lst, ensure_ascii=False)

        result_items = []

        # ── Браузеры ──────────────────────────────────────────────
        if info_type in ('browser_ids', 'all'):
            from constructor.browser_module import BrowserManager
            pbm = getattr(self, 'project_browser_manager', None)
            mgr = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()
            try:
                all_inst = mgr.all_instances() if hasattr(mgr, 'all_instances') else {}
                ids = list(all_inst.keys())
            except Exception:
                ids = []
            result_items = ids
            _set(count_var, str(len(ids)))
            if ids:
                _set(active_var, ids[0])
            if info_type == 'browser_ids':
                _set(result_var, _fmt(ids))
                if result_list_var:
                    self._context[result_list_var] = ids
                    # ═══ ИСПРАВЛЕНИЕ: синхронизируем список с переменными проекта ═══
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(ids)
                        self.signals.variable_updated.emit(result_list_var, str(...))
                    self._log(f"  📝 Список сохранён: {result_list_var} ({len(ids)} элементов)")
                self._log(f"🔎 Браузеры: {ids}")
                return f"🔎 Браузеров открыто: {len(ids)} → {_fmt(ids)[:80]}"

        # ── Списки ────────────────────────────────────────────────
        if info_type in ('list_names', 'all'):
            pv = self._project_variables or {}
            names = [k for k, v in pv.items() if isinstance(v, list)]
            result_items = names
            if info_type == 'list_names':
                _set(result_var, _fmt(names))
                if result_list_var:
                    self._context[result_list_var] = names
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(names)
                        self.signals.variable_updated.emit(result_list_var, str(...))
                return f"🔎 Списков: {len(names)} → {_fmt(names)[:80]}"

        # ── Таблицы ───────────────────────────────────────────────
        if info_type in ('table_names', 'all'):
            pv = self._project_variables or {}
            names = [k for k, v in pv.items()
                     if isinstance(v, list) and v and isinstance(v[0], (list, dict))]
            result_items = names
            if info_type == 'table_names':
                _set(result_var, _fmt(names))
                if result_list_var:
                    self._context[result_list_var] = names
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(names)
                        self.signals.variable_updated.emit(result_list_var, str(...))
                return f"🔎 Таблиц: {len(names)} → {_fmt(names)[:80]}"

        # ── Переменные ────────────────────────────────────────────
        if info_type in ('var_names', 'all'):
            pv = self._project_variables or {}
            names = [k for k in pv.keys() if not k.startswith('_')]
            result_items = names
            if info_type == 'var_names':
                _set(result_var, _fmt(names))
                if result_list_var:
                    self._context[result_list_var] = names
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(names)
                        self.signals.variable_updated.emit(result_list_var, str(...))
                return f"🔎 Переменных: {len(names)} → {_fmt(names)[:80]}"

        # ── Скиллы ────────────────────────────────────────────────
        if info_type == 'skill_names':
            try:
                from services.skill_registry import SkillRegistry
                reg = SkillRegistry()
                names = [s.name for s in reg.all_skills()]
            except Exception:
                names = []
            _set(result_var, _fmt(names))
            if result_list_var:
                    self._context[result_list_var] = names
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(names)
                        self.signals.variable_updated.emit(result_list_var, str(...))
            return f"🔎 Скиллов: {len(names)}"

        # ── Узлы графа ────────────────────────────────────────────
        if info_type == 'node_names':
            try:
                from services.agent_models import AgentWorkflow
                wf = getattr(self, '_workflow', None)
                names = [n.name for n in wf.nodes] if wf else []
            except Exception:
                names = []
            _set(result_var, _fmt(names))
            if result_list_var:
                    self._context[result_list_var] = names
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = list(names)
                        self.signals.variable_updated.emit(result_list_var, str(...))
            return f"🔎 Узлов: {len(names)}"
        
        # ── Открытые программы ────────────────────────────────────────────
        if info_type == 'open_programs':
            # Сначала берём из реестра PROGRAM_OPEN (контекст + metadata)
            _registered = {}
            for _pid_str, _e in self._context.get('_open_programs', {}).items():
                _registered[_pid_str] = {
                    'hwnd': int(_e.get('hwnd', 0) or 0),
                    'pid':  int(_pid_str),
                    'title': str(_e.get('name', '') or _e.get('exe', '')),
                    'exe':  str(_e.get('exe', '')),
                }
            _meta = getattr(self._workflow, 'metadata', None) or {}
            for _pid_str, _e in _meta.get('_open_programs_meta', {}).items():
                if _pid_str not in _registered:
                    _registered[_pid_str] = {
                        'hwnd': int(_e.get('hwnd', 0) or 0),
                        'pid':  int(_pid_str),
                        'title': str(_e.get('name', '') or _e.get('exe', '')),
                        'exe':  str(_e.get('exe', '')),
                    }
            if _registered:
                programs = list(_registered.values())
                out = json.dumps(programs, ensure_ascii=False)
                _set(result_var, out)
                if result_list_var:
                    titles = [p['title'] for p in programs]
                    self._context[result_list_var] = titles
                    if self._project_variables is not None and isinstance(self._project_variables, dict):
                        self._project_variables[result_list_var] = titles
                        self.signals.variable_updated.emit(result_list_var, str(titles))
                self._log(f"🖥 Открытых программ (PROGRAM_OPEN): {len(programs)}")
                return f"🖥 Программ: {len(programs)}"
            # Fallback: если PROGRAM_OPEN не запускался — перечисляем системные окна
            try:
                import psutil, ctypes
                from ctypes import wintypes
                programs = []
                EnumWindows = ctypes.windll.user32.EnumWindows
                GetWindowText = ctypes.windll.user32.GetWindowTextW
                IsWindowVisible = ctypes.windll.user32.IsWindowVisible
                GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
                buf = ctypes.create_unicode_buffer(512)
                pids_seen = set()
                def _enum_cb(hwnd, _):
                    if IsWindowVisible(hwnd):
                        GetWindowText(hwnd, buf, 512)
                        title = buf.value.strip()
                        if title:
                            pid = wintypes.DWORD()
                            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            pid_val = pid.value
                            if pid_val not in pids_seen:
                                pids_seen.add(pid_val)
                                try:
                                    proc = psutil.Process(pid_val)
                                    exe = proc.exe()
                                except Exception:
                                    exe = ''
                                programs.append({
                                    'hwnd': int(hwnd), 'pid': int(pid_val),
                                    'title': str(title), 'exe': str(exe)
                                })
                    return True
                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)
                EnumWindows(WNDENUMPROC(_enum_cb), 0)
            except Exception as e:
                programs = []
                self._log(f"⚠ open_programs: {e}")
            out = json.dumps(programs, ensure_ascii=False)
            _set(result_var, out)
            if result_list_var:
                titles = [p['title'] for p in programs]
                self._context[result_list_var] = titles
                if self._project_variables is not None and isinstance(self._project_variables, dict):
                    self._project_variables[result_list_var] = titles
                    self.signals.variable_updated.emit(result_list_var, str(...))
            self._log(f"🖥 Открытых программ: {len(programs)}")
            return f"🖥 Программ: {len(programs)}"

        # ── Настройки проекта ─────────────────────────────────────
        if info_type == 'project_settings':
            try:
                wf = getattr(self, '_workflow', None)
                settings = {}
                if wf:
                    settings = {
                        'name':           getattr(wf, 'name', ''),
                        'description':    getattr(wf, 'description', ''),
                        'max_total_steps': getattr(wf, 'max_total_steps', 0),
                        'entry_node_id':  getattr(wf, 'entry_node_id', ''),
                        'node_count':     len(getattr(wf, 'nodes', [])),
                        'edge_count':     len(getattr(wf, 'edges', [])),
                        'metadata':       getattr(wf, 'metadata', {}),
                    }
            except Exception as e:
                settings = {}
                self._log(f"⚠ project_settings: {e}")
            out = json.dumps(settings, ensure_ascii=False)
            _set(result_var, out)
            self._log(f"⚙️ Настройки проекта получены")
            return f"⚙️ Настройки проекта сохранены в {result_var}"

        # ── БД проекта ────────────────────────────────────────────
        if info_type == 'project_db':
            try:
                pv = self._project_variables or {}
                tables = {
                    k: v for k, v in pv.items()
                    if isinstance(v, list) and v and isinstance(v[0], (list, dict))
                }
            except Exception as e:
                tables = {}
                self._log(f"⚠ project_db: {e}")
            out = json.dumps(tables, ensure_ascii=False)
            _set(result_var, out)
            self._log(f"🗄 Таблиц (БД) в проекте: {len(tables)}")
            return f"🗄 БД проекта: {len(tables)} таблиц → {result_var}"
        
        # ── Всё сразу ─────────────────────────────────────────────
        if info_type == 'all':
            pv = self._project_variables or {}
            summary = {
                'browser_ids':  result_items,
                'list_names':   [k for k, v in pv.items() if isinstance(v, list)],
                'var_names':    [k for k in pv.keys() if not k.startswith('_')],
            }
            out = json.dumps(summary, ensure_ascii=False)
            _set(result_var, out)
            return f"🔎 Информация о проекте сохранена"

        return f"🔎 Неизвестный тип: {info_type}"
        
    async def _exec_browser_parse(self, node) -> str:
        """🕸️ Browser Parse — парсинг текста из браузера."""
        import asyncio, json as _json
        cfg = getattr(node, 'snippet_config', {}) or {}
        pick_mode       = cfg.get('pick_mode', 'interactive')
        css_sel         = cfg.get('css_selector', '').strip()
        xpath_sel       = cfg.get('xpath_selector', '').strip()
        picked_selector = cfg.get('picked_selector', '').strip()   # из пикера
        ai_prompt       = cfg.get('ai_prompt', '').strip()
        parse_type      = cfg.get('parse_type', 'first')
        save_to         = cfg.get('save_to', 'variable')
        result_var      = cfg.get('result_var', 'parsed_text').strip().strip('{}')
        result_list     = cfg.get('result_list', '').strip().strip('{}')
        result_table    = cfg.get('result_table', '').strip().strip('{}')
        wait_ms         = int(cfg.get('wait_load', 1500) or 0)
        fallback_ai     = bool(cfg.get('fallback_ai', True))
        on_error        = cfg.get('on_error', 'empty')
        browser_var_key = cfg.get('browser_instance_var', 'browser_instance_id').strip().strip('{}')

        # ── Найти инстанс браузера (как в Screenshot) ────────────────
        from constructor.browser_module import BrowserManager
        pbm = getattr(self, 'project_browser_manager', None)
        mgr = (pbm._manager if pbm and hasattr(pbm, '_manager') else None) or BrowserManager.get()

        iid = self._context.get(browser_var_key, '')
        if not iid:
            iid = self._context.get('browser_instance_id', '')
        if not iid and pbm and hasattr(pbm, 'first_instance_id'):
            iid = pbm.first_instance_id()
        inst = (pbm.get_instance(iid) if pbm and iid else None) or (mgr.get_instance(iid) if iid else None)
        if inst is None:
            all_inst = mgr.all_instances() if hasattr(mgr, 'all_instances') else {}
            inst = next((i for i in all_inst.values() if getattr(i, 'is_running', False)), None) \
                   or next(iter(all_inst.values()), None)
        if inst is None:
            raise RuntimeError("Браузер не найден. Запустите Browser Launch перед парсингом.")

        # ── Получить Selenium driver ──────────────────────────────────
        drv = getattr(inst, '_driver', None)
        if drv is None:
            raise RuntimeError("Selenium driver недоступен. Playwright не поддерживается этим сниппетом.")

        def _save(value):
            if save_to == 'variable' and result_var:
                v = value if isinstance(value, str) else _json.dumps(value, ensure_ascii=False)
                self._context[result_var] = v
                self._sync_var_to_project(result_var, v)
            elif save_to == 'list' and result_list:
                lst = value if isinstance(value, list) else [value]
                self._context[result_list] = lst
                if self._project_variables is not None:
                    self._project_variables[result_list] = lst
                    self.signals.variable_updated.emit(result_list, str(...))
            elif save_to == 'table' and result_table:
                tbl = value if isinstance(value, list) else [[value]]
                if self._project_variables is not None:
                    self._project_variables[result_table] = tbl
                    self.signals.variable_updated.emit(result_table, str(...))

        def _by_selector(sel, all_matches=False):
            """Selenium CSS-поиск с возвратом текста."""
            from selenium.webdriver.common.by import By
            try:
                if all_matches:
                    els = drv.find_elements(By.CSS_SELECTOR, sel)
                    return [e.text or e.get_attribute('textContent') or '' for e in els if e]
                else:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    return [el.text or el.get_attribute('textContent') or ''] if el else []
            except Exception as ex:
                self._log(f"⚠ CSS-selector '{sel}': {ex}")
                return []

        def _by_xpath(sel, all_matches=False):
            from selenium.webdriver.common.by import By
            try:
                if all_matches:
                    els = drv.find_elements(By.XPATH, sel)
                    return [e.text or '' for e in els if e]
                else:
                    el = drv.find_element(By.XPATH, sel)
                    return [el.text or ''] if el else []
            except Exception as ex:
                self._log(f"⚠ XPath '{sel}': {ex}")
                return []

        try:
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000.0)

            results = []
            found = False

            # interactive — использует CSS-селектор из пикера
            if pick_mode == 'interactive':
                if picked_selector:
                    self._log(f"🖱 Интерактивный: CSS-селектор из пикера: {picked_selector}")
                    results = _by_selector(picked_selector, parse_type == 'all_matches')
                    found = bool(results)
                else:
                    self._log("⚠ Интерактивный режим: селектор не выбран. Откройте свойства сниппета и нажмите '🖱 Открыть пикер'.")
                    _save('')
                    return "⚠ Пикер: элемент не выбран. Используйте кнопку в настройках сниппета."

            elif pick_mode == 'css' and css_sel:
                results = _by_selector(css_sel, parse_type == 'all_matches')
                found = bool(results)

            elif pick_mode == 'xpath' and xpath_sel:
                results = _by_xpath(xpath_sel, parse_type == 'all_matches')
                found = bool(results)

            elif pick_mode == 'page_text':
                try:
                    results = [drv.execute_script(
                        "return document.body ? document.body.innerText : document.documentElement.innerText;"
                    ) or '']
                    found = True
                except Exception as ex:
                    results = [drv.page_source or '']
                    found = True

            elif pick_mode == 'tables':
                try:
                    raw = drv.execute_script("""
return Array.from(document.querySelectorAll('table')).map(function(t){
  return Array.from(t.querySelectorAll('tr')).map(function(r){
    return Array.from(r.querySelectorAll('td,th')).map(function(c){
      return (c.innerText||'').trim();
    });
  });
});""")
                    results = raw or []
                    found = bool(results)
                except Exception as ex:
                    self._log(f"⚠ tables: {ex}")

            elif pick_mode == 'ai_universal':
                found = False  # handled below

            # ── Фолбэк через AI ───────────────────────────────────────
            if not found and fallback_ai and ai_prompt:
                self._log("🤖 Фолбэк: AI-парсер...")
                try:
                    page_text = drv.execute_script(
                        "return document.body ? document.body.innerText : '';"
                    ) or drv.page_source or ''
                except Exception:
                    page_text = drv.page_source or ''
                ai_full = (
                    f"Страница:\n{page_text[:8000]}\n\n"
                    f"Задача: {ai_prompt}\n\nВерни только результат без пояснений."
                )
                if self._model_manager:
                    mid = getattr(self, '_default_model_id', None) or ''
                    provider = self._model_manager.get_provider(mid) if mid else None
                    if provider:
                        ai_result = await provider.complete(ai_full)
                        results = [ai_result.strip()]
                        found = True
                        self._log("🤖 AI-парсер: результат получен")

            if pick_mode == 'ai_universal' and not found:
                try:
                    page_text = drv.execute_script(
                        "return document.body ? document.body.innerText : '';"
                    ) or ''
                except Exception:
                    page_text = drv.page_source or ''
                ai_full = (
                    f"Страница:\n{page_text[:8000]}\n\n"
                    f"Задача: {ai_prompt or 'Извлеки основные данные'}\n\nВерни только результат."
                )
                if self._model_manager:
                    mid = getattr(self, '_default_model_id', None) or ''
                    provider = self._model_manager.get_provider(mid) if mid else None
                    if provider:
                        ai_result = await provider.complete(ai_full)
                        results = [ai_result.strip()]
                        found = True

            out = results[0] if (parse_type == 'first' and results) else results
            _save(out)
            cnt = len(results) if isinstance(results, list) else 1
            self._log(f"🕸️ Парсинг завершён: {str(out)[:120]}")
            return f"🕸️ Текст получен ({cnt} элементов)"

        except Exception as e:
            self._log(f"❌ Browser Parse ошибка: {e}")
            if on_error == 'stop':
                raise
            elif on_error == 'empty':
                _save('')
            return f"❌ Browser Parse: {e}"

    async def _exec_program_inspector(self, node) -> str:
        """🔬 Program Inspector — Win32 + UIAutomation + OCR фолбэк."""
        import json as _json, asyncio, ctypes
        from ctypes import wintypes
        cfg = getattr(node, 'snippet_config', {}) or {}
        program_source  = cfg.get('program_source', 'hwnd_var')
        hwnd_var        = cfg.get('hwnd_var', 'program_hwnd').strip().strip('{}')
        win_title       = cfg.get('window_title_filter', '').strip()
        pid_var_name    = cfg.get('pid_var', 'program_pid').strip().strip('{}')
        inspect_mode    = cfg.get('inspect_mode', 'full_dump')
        class_filter    = cfg.get('class_filter', '').strip()
        include_coords  = bool(cfg.get('include_coords', True))
        include_state   = bool(cfg.get('include_state', True))
        include_text    = bool(cfg.get('include_text', True))
        depth_limit     = int(cfg.get('depth_limit', 5) or 5)
        use_ai          = bool(cfg.get('use_ai_interpret', False))
        ai_task         = cfg.get('ai_task', '').strip()
        save_to         = cfg.get('save_to', 'table')
        result_var      = cfg.get('result_var', 'program_dump').strip().strip('{}')
        result_table    = cfg.get('result_table', 'program_elements').strip().strip('{}')
        result_list     = cfg.get('result_list', '').strip().strip('{}')
        on_error        = cfg.get('on_error', 'stop')

        user32 = ctypes.windll.user32

        # ══ 1. Найти HWND ════════════════════════════════════════════
        hwnd = 0
        if program_source == 'hwnd_var':
            hwnd = int(self._context.get(hwnd_var, 0) or 0)
            if not hwnd and self._project_variables:
                pv_raw = self._project_variables.get(hwnd_var)
                if isinstance(pv_raw, dict):
                    hwnd = int(pv_raw.get('value', 0) or 0)
                elif pv_raw:
                    try: hwnd = int(pv_raw)
                    except (ValueError, TypeError): pass
            if not hwnd:
                hwnd = int(self._context.get('_program_hwnd', 0) or 0)
            if not hwnd and self._workflow:
                _meta = getattr(self._workflow, 'metadata', {}) or {}
                hwnd = int(_meta.get('_last_program_hwnd', 0) or 0)
                if not hwnd:
                    for _entry in _meta.get('_open_programs_meta', {}).values():
                        hwnd = int(_entry.get('hwnd', 0) or 0)
                        if hwnd:
                            self._log(f"  🔍 HWND из _open_programs_meta: {hwnd}")
                            break
        elif program_source == 'window_title':
            buf = ctypes.create_unicode_buffer(512)
            def _find_cb(h, _):
                nonlocal hwnd
                if user32.IsWindowVisible(h):
                    user32.GetWindowTextW(h, buf, 512)
                    if win_title.lower() in buf.value.lower():
                        hwnd = h
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(WNDENUMPROC(_find_cb), 0)
        elif program_source == 'pid_var':
            pid = int(self._context.get(pid_var_name, 0) or 0)
            def _pid_cb(h, _):
                nonlocal hwnd
                d = wintypes.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(d))
                if d.value == pid:
                    hwnd = h
                return True
            WNDENUMPROC2 = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(WNDENUMPROC2(_pid_cb), 0)
        elif program_source == 'active_window':
            hwnd = user32.GetForegroundWindow()

        if not hwnd:
            raise RuntimeError("Окно программы не найдено")

        self._log(f"🔬 HWND: {hwnd}")

        try:
            elements = []

            # ══ 2. Win32 API — классические элементы ══════════════════
            def _read_win32(parent_hwnd, depth=0):
                if depth > depth_limit:
                    return
                child = user32.GetWindow(parent_hwnd, 5)  # GW_CHILD
                while child:
                    cls_buf = ctypes.create_unicode_buffer(256)
                    txt_buf = ctypes.create_unicode_buffer(1024)
                    user32.GetClassNameW(child, cls_buf, 256)
                    cls = cls_buf.value
                    txt = ''
                    if include_text:
                        user32.GetWindowTextW(child, txt_buf, 1024)
                        txt = txt_buf.value.strip()
                    if class_filter and class_filter.lower() not in cls.lower():
                        child = user32.GetWindow(child, 2)
                        continue
                    skip = False
                    if inspect_mode == 'buttons_only' and 'button' not in cls.lower():
                        skip = True
                    elif inspect_mode == 'text_fields' and cls.lower() not in (
                            'edit', 'richedit', 'richedit20a', 'richedit20w'):
                        skip = True
                    elif inspect_mode == 'labels_only' and cls.lower() != 'static':
                        skip = True
                    elif inspect_mode == 'checkboxes' and 'button' not in cls.lower():
                        skip = True
                    if not skip:
                        # Пропускаем хром-элементы Electron (они не несут полезной информации)
                        _skip_classes = {
                            'chrome_renderwidgethosthwnd', 'intermediate d3d window',
                            'chrome_widgetwin_1', 'chrome_widgetwin_0',
                        }
                        if cls.lower() not in _skip_classes or txt:
                            elem = {'hwnd': child, 'class': cls, 'text': txt,
                                    'depth': depth, 'source': 'win32'}
                            if include_coords:
                                r = wintypes.RECT()
                                user32.GetWindowRect(child, ctypes.byref(r))
                                elem.update({'x': r.left, 'y': r.top,
                                             'w': r.right - r.left, 'h': r.bottom - r.top})
                            if include_state:
                                elem['visible'] = bool(user32.IsWindowVisible(child))
                                elem['enabled'] = bool(user32.IsWindowEnabled(child))
                                elem['checked'] = (
                                    bool(user32.SendMessageW(child, 0x00F0, 0, 0))
                                    if 'button' in cls.lower() else None
                                )
                            elements.append(elem)
                    _read_win32(child, depth + 1)
                    child = user32.GetWindow(child, 2)

            _read_win32(hwnd)
            self._log(f"🔬 Win32 элементов: {len(elements)}")

            # ══ 3. UIAutomation — работает для Electron/WPF/UWP ═══════
            uia_elements = []
            # Сначала пробуем pip-пакет uiautomation (стабильнее, не требует COM-регистрации)
            _uia_pkg_ok = False
            try:
                import uiautomation as _uia
                ctrl = _uia.ControlFromHandle(hwnd)
                if ctrl:
                    def _walk_uia(c, depth=0):
                        if depth > depth_limit:
                            return
                        for el in c.GetChildren():
                            name = (el.Name or '').strip()
                            entry = {
                                'class': el.ControlTypeName,
                                'text': name,
                                'depth': depth,
                                'source': 'uia_pkg',
                                'enabled': el.IsEnabled,
                            }
                            if include_coords:
                                try:
                                    r = el.BoundingRectangle
                                    entry.update({'x': r.left, 'y': r.top,
                                                  'w': r.width(), 'h': r.height()})
                                except Exception:
                                    pass
                            if entry['text'] or (include_coords and entry.get('w', 0) > 0):
                                uia_elements.append(entry)
                            _walk_uia(el, depth + 1)
                    _walk_uia(ctrl)
                    self._log(f"🔬 uiautomation пакет: {len(uia_elements)} элементов")
                    _uia_pkg_ok = True
            except ImportError:
                pass  # Нет пакета — пробуем comtypes ниже
            except Exception as uia_pkg_err:
                self._log(f"⚠ uiautomation pkg ошибка: {uia_pkg_err}")

            # Если pip-пакет не дал результата — пробуем comtypes (COM/WinRT)
            if not _uia_pkg_ok:
                try:
                    import pythoncom
                    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                except Exception:
                    pass
                try:
                    import comtypes.client
                    comtypes.client.GetModule('UIAutomationClient')
                    from comtypes.gen.UIAutomationClient import (
                        CUIAutomation, IUIAutomation, UIA_ControlTypePropertyId,
                        UIA_NamePropertyId, UIA_BoundingRectanglePropertyId,
                        UIA_IsEnabledPropertyId, TreeScope_Descendants,
                    )
                    uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
                    root_el = uia.ElementFromHandle(hwnd)
                    condition = uia.CreateTrueCondition()
                    children = root_el.FindAll(TreeScope_Descendants, condition)
                    count = children.Length
                    self._log(f"🔬 UIAutomation (comtypes): {count} элементов")
                    for i in range(min(count, 500)):
                        try:
                            el = children.GetElement(i)
                            name = el.GetCurrentPropertyValue(UIA_NamePropertyId) or ''
                            ctrl_type = el.GetCurrentPropertyValue(UIA_ControlTypePropertyId)
                            enabled  = el.GetCurrentPropertyValue(UIA_IsEnabledPropertyId)
                            rect_val = el.GetCurrentPropertyValue(UIA_BoundingRectanglePropertyId)
                            if not name and not rect_val:
                                continue
                            uia_elem = {
                                'class': f'UIA_CtrlType_{ctrl_type}',
                                'text': str(name),
                                'depth': 0,
                                'source': 'uia',
                                'enabled': bool(enabled),
                            }
                            if include_coords and rect_val:
                                try:
                                    uia_elem.update({
                                        'x': int(rect_val.left), 'y': int(rect_val.top),
                                        'w': int(rect_val.right - rect_val.left),
                                        'h': int(rect_val.bottom - rect_val.top),
                                    })
                                except Exception:
                                    pass
                            if uia_elem['text'] or (include_coords and uia_elem.get('w', 0) > 0):
                                uia_elements.append(uia_elem)
                        except Exception:
                            continue
                except ImportError:
                    self._log("⚠ comtypes не установлен — UIAutomation недоступен")
                except Exception as uia_err:
                    self._log(f"⚠ UIAutomation (comtypes) ошибка: {uia_err}")

            if uia_elements:
                elements = uia_elements + [e for e in elements if e.get('text')]
                self._log(f"🔬 Итого после UIAutomation: {len(elements)}")

            # ══ 4. OCR фолбэк — если Win32/UIA дали мало текста ═══════
            useful = [e for e in elements if e.get('text', '').strip()]
            if len(useful) < 3:
                self._log("🔬 Мало текста через Win32/UIA — запускаем OCR скриншота...")
                ocr_elements = await self._ocr_window(hwnd, include_coords)
                if ocr_elements:
                    elements = ocr_elements + elements
                    self._log(f"🔬 OCR добавил {len(ocr_elements)} текстовых блоков")

            self._log(f"🔬 Итого элементов: {len(elements)}")

            # ══ 5. AI-интерпретация ════════════════════════════════════
            if use_ai and ai_task and elements:
                dump_str = _json.dumps(elements[:200], ensure_ascii=False)
                ai_full = (
                    f"Элементы программы:\n{dump_str}\n\n"
                    f"Задача: {ai_task}\n\nОтветь только результатом."
                )
                if self._model_manager:
                    mid = getattr(self, '_default_model_id', None) or ''
                    provider = self._model_manager.get_provider(mid) if mid else None
                    if provider:
                        ai_result = await provider.complete(ai_full)
                        self._context['_ai_inspector_result'] = ai_result
                        self._log(f"🤖 AI: {ai_result[:200]}")

            # ══ 6. Сохранение ══════════════════════════════════════════
            if save_to == 'variable' and result_var:
                val = _json.dumps(elements, ensure_ascii=False)
                self._context[result_var] = val
                self._sync_var_to_project(result_var, val)
            elif save_to == 'table' and result_table:
                headers = ['class', 'text', 'source', 'depth']
                if include_coords:
                    headers += ['x', 'y', 'w', 'h']
                if include_state:
                    headers += ['enabled']
                rows = [[str(e.get(h, '')) for h in headers] for e in elements]
                tbl = [headers] + rows
                if self._project_variables is not None:
                    self._project_variables[result_table] = tbl
                    self.signals.variable_updated.emit(result_table, str(...))
            elif save_to == 'list' and result_list:
                texts = [e.get('text', '').strip() for e in elements if e.get('text', '').strip()]
                self._context[result_list] = texts
                if self._project_variables is not None:
                    self._project_variables[result_list] = texts
                    self.signals.variable_updated.emit(result_list, str(...))

            return f"🔬 Инспекция завершена: {len(elements)} элементов"

        except Exception as e:
            self._log(f"❌ Program Inspector: {e}")
            if on_error == 'stop':
                raise
            return f"❌ Program Inspector: {e}"
            
    async def _ocr_window(self, hwnd: int, include_coords: bool = True) -> list:
        """Скриншот HWND + OCR → список элементов с текстом и координатами."""
        import ctypes
        from ctypes import wintypes
        elements = []

        # ── 1. Скриншот через PrintWindow (работает для окон за экраном и Electron) ──
        try:
            import win32gui, win32ui, win32con
            import ctypes as _ct
            left, top, right, bot = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bot - top
            if w <= 0 or h <= 0:
                w, h = 800, 600
            hwnd_dc  = win32gui.GetWindowDC(hwnd)
            mfc_dc   = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc  = mfc_dc.CreateCompatibleDC()
            bmp      = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            # PW_RENDERFULLCONTENT=2 — захватывает Electron/WPF/скрытые/заэкранные окна
            printed = _ct.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
            if not printed:
                # Fallback: BitBlt (работает только для видимых окон)
                save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
            bmp_info = bmp.GetInfo()
            bmp_data = bmp.GetBitmapBits(True)
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            win32gui.DeleteObject(bmp.GetHandle())
            # Конвертируем в PIL Image
            from PIL import Image
            img = Image.frombuffer('RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']),
                                   bmp_data, 'raw', 'BGRX', 0, 1)
        except Exception as e:
            self._log(f"⚠ OCR screenshot (BitBlt) не удался: {e}. Пробуем pyautogui...")
            try:
                import pyautogui
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                r = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                region = (r.left, r.top, r.right - r.left, r.bottom - r.top)
                if region[2] <= 0 or region[3] <= 0:
                    region = (100, 100, 800, 600)
                img = pyautogui.screenshot(region=region)
            except Exception as e2:
                self._log(f"⚠ OCR screenshot (pyautogui): {e2}")
                return []

        # ── 2. OCR: pytesseract (первый приоритет) ─────────────────
        try:
            import pytesseract
            from PIL import Image as _PILImg
            ocr_data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT,
                lang='rus+eng', config='--psm 11'
            )
            n = len(ocr_data['text'])
            for i in range(n):
                txt = (ocr_data['text'][i] or '').strip()
                conf = int(ocr_data['conf'][i] or 0)
                if not txt or conf < 30:
                    continue
                elem = {'class': 'OCR_text', 'text': txt, 'source': 'ocr',
                        'depth': 0, 'enabled': True, 'ocr_conf': conf}
                if include_coords:
                    elem.update({
                        'x': ocr_data['left'][i],
                        'y': ocr_data['top'][i],
                        'w': ocr_data['width'][i],
                        'h': ocr_data['height'][i],
                    })
                elements.append(elem)
            self._log(f"🔬 pytesseract OCR: {len(elements)} слов")
            return elements
        except ImportError:
            self._log("⚠ pytesseract не установлен. pip install pytesseract")
        except Exception as te:
            self._log(f"⚠ pytesseract: {te}")

        # ── 3. easyocr фолбэк ──────────────────────────────────────
        try:
            import easyocr
            import numpy as np
            reader = easyocr.Reader(['ru', 'en'], gpu=False, verbose=False)
            arr = np.array(img)
            results = reader.readtext(arr, detail=1)
            for (bbox, txt, conf) in results:
                txt = (txt or '').strip()
                if not txt or conf < 0.3:
                    continue
                xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
                elem = {'class': 'OCR_text', 'text': txt, 'source': 'ocr_easy',
                        'depth': 0, 'enabled': True, 'ocr_conf': round(conf, 2)}
                if include_coords:
                    elem.update({
                        'x': int(min(xs)), 'y': int(min(ys)),
                        'w': int(max(xs) - min(xs)), 'h': int(max(ys) - min(ys)),
                    })
                elements.append(elem)
            self._log(f"🔬 easyocr: {len(elements)} блоков")
            return elements
        except ImportError:
            self._log("⚠ easyocr не установлен. pip install easyocr")
        except Exception as ee:
            self._log(f"⚠ easyocr: {ee}")

        # ── 4. Windows 10+ встроенный OCR (без зависимостей) ───────
        try:
            import asyncio as _aio
            import winrt.windows.media.ocr as _wocr
            import winrt.windows.graphics.imaging as _wgi
            import winrt.windows.storage.streams as _wss
            import io, base64

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            png_bytes = buf.read()

            async def _run_win_ocr():
                engine = _wocr.OcrEngine.try_create_from_user_profile_languages()
                if engine is None:
                    return []
                data = _wss.InMemoryRandomAccessStream()
                writer = _wss.DataWriter(data)
                writer.write_bytes(list(png_bytes))
                await writer.store_async()
                await writer.flush_async()
                data.seek(0)
                decoder = await _wgi.BitmapDecoder.create_async(data)
                soft_bmp = await decoder.get_soft_bitmap_async()
                result = await engine.recognize_async(soft_bmp)
                out = []
                for line in result.lines:
                    txt = line.text.strip()
                    if txt:
                        out.append({'class': 'OCR_winrt', 'text': txt,
                                    'source': 'ocr_winrt', 'depth': 0, 'enabled': True})
                return out

            loop = asyncio.get_event_loop()
            ocr_res = loop.run_until_complete(_run_win_ocr())
            if ocr_res:
                self._log(f"🔬 Windows OCR: {len(ocr_res)} строк")
                return ocr_res
        except Exception as we:
            self._log(f"⚠ Windows OCR: {we}")

        self._log("⚠ OCR: ни один движок не сработал. Установите pytesseract или easyocr.")
        return []
        
    async def _exec_project_start(self, node: AgentNode) -> str:
        """▶ PROJECT_START: точка входа — выполняет стартовую логику по настройкам."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        run_mode = cfg.get('run_mode', 'plain')
        parts = []

        # ═══ Сброс переменных к дефолтным (только здесь, через сниппет PROJECT_START) ═══
        if self._project_variables:
            for var_name, var_data in list(self._project_variables.items()):
                if var_name.startswith('_'):
                    continue
                if isinstance(var_data, dict):
                    default_val = var_data.get('default', '')
                    self._project_variables[var_name] = {
                        'value': default_val,
                        'default': default_val,
                        'type': var_data.get('type', 'string')
                    }
                    self._context[var_name] = default_val
                    self.signals.variable_updated.emit(var_name, str(default_val))
                    self._log(f"  📝 {var_name} = '{default_val}' (reset to default)")
            self._log("🔄 Переменные сброшены к дефолтным (PROJECT_START)")

        self._log(f"▶ СТАРТ: режим = {run_mode}")

        # ═══ 1. Стартовая задержка ═══
        delay_ms = cfg.get('startup_delay', 0)
        if delay_ms and int(delay_ms) > 0:
            delay_sec = int(delay_ms) / 1000.0
            self._log(f"  ⏳ Задержка старта: {delay_sec}с")
            await asyncio.sleep(delay_sec)
            parts.append(f"Задержка {delay_sec}с")

        # ═══ 2. Переменные окружения ═══
        env_text = cfg.get('env_vars', '')
        if env_text:
            for line in env_text.strip().split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    # Подстановка переменных
                    for ck, cv in self._context.items():
                        if not ck.startswith('_'):
                            v = v.replace(f'{{{ck}}}', str(cv))
                    os.environ[k.strip()] = v.strip()
                    self._context[k.strip()] = v.strip()
            parts.append(f"Переменные окружения установлены")

        # ═══ 3. Загрузка файла данных ═══
        data_file = cfg.get('data_file', '')
        if data_file:
            enc = cfg.get('data_encoding', 'utf-8') or 'utf-8'
            for ck, cv in self._context.items():
                if not ck.startswith('_'):
                    data_file = data_file.replace(f'{{{ck}}}', str(cv))
            if not os.path.isabs(data_file):
                data_file = os.path.join(self._project_root or '.', data_file)
            if os.path.isfile(data_file):
                with open(data_file, 'r', encoding=enc, errors='replace') as f:
                    lines = [l.rstrip('\n\r') for l in f.readlines() if l.strip()]
                self._context['data_lines'] = lines
                self._context['data_count'] = len(lines)
                self._log(f"  📄 Загружено {len(lines)} строк из {os.path.basename(data_file)}")
                parts.append(f"Данные: {len(lines)} строк")

        # ═══ 4. Автозапуск браузера ═══
        if cfg.get('browser_auto_launch', False):
            self._log("  🌐 Автозапуск браузера из PROJECT_START...")
            try:
                from constructor.browser_module import (
                    BrowserManager, BrowserProfileManager,
                    execute_browser_launch_snippet, BrowserProfile, BrowserProxy,
                )
                browser_cfg = {
                    'profile_folder': cfg.get('browser_profile', ''),
                    'headless': cfg.get('browser_headless', False),
                    'user_agent': cfg.get('browser_user_agent', ''),
                    'create_if_missing': True,
                }
                # Парсинг viewport
                vp = cfg.get('browser_viewport', '1280x800')
                if 'x' in str(vp):
                    try:
                        w, h = str(vp).split('x', 1)
                        browser_cfg['window_width'] = int(w)
                        browser_cfg['window_height'] = int(h)
                    except Exception:
                        pass
                # Прокси
                proxy_str = cfg.get('browser_proxy', '')
                if proxy_str:
                    browser_cfg['proxy_enabled'] = True
                    browser_cfg['proxy_string'] = proxy_str

                pbm = getattr(self, 'project_browser_manager', None)
                mgr = (pbm._manager if pbm and hasattr(pbm, '_manager')
                       else None) or BrowserManager.get()
                pm = BrowserProfileManager(self._project_root or "")
                self._context = execute_browser_launch_snippet(
                    cfg=browser_cfg,
                    context=self._context,
                    profile_manager=pm,
                    manager=mgr,
                    logger=self._log,
                    embed_target=None,
                    project_browser_manager=pbm,
                )
                parts.append("Браузер запущен")
            except Exception as e:
                self._log(f"  ⚠ Ошибка автозапуска браузера: {e}")
                parts.append(f"Браузер: ошибка ({e})")

        # ═══ 5. Стартовый скрипт ═══
        if run_mode in ('script', 'hybrid'):
            script = cfg.get('startup_script', '')
            if script:
                self._log("  ⚡ Выполняю стартовый скрипт...")
                try:
                    exec_globals = {
                        'context': self._context,
                        'variables': self._project_variables or {},
                        'log': self._log,
                        'os': os,
                    }
                    exec(script, exec_globals)
                    # Синхронизируем изменения обратно
                    if 'context' in exec_globals:
                        self._context.update(exec_globals['context'])
                    parts.append("Скрипт выполнен")
                except Exception as e:
                    self._log(f"  ❌ Ошибка скрипта: {e}")
                    parts.append(f"Скрипт: ошибка ({e})")

        # ═══ 6. AI-модель на старте ═══
        if run_mode in ('ai', 'hybrid'):
            ai_prompt = cfg.get('ai_system_prompt', '')
            model_id = cfg.get('model_id', '')
            if ai_prompt:
                self._log(f"  🤖 AI на старте (модель: {model_id or 'default'})...")
                try:
                    # Формируем временные сообщения
                    messages = [{"role": "system", "content": ai_prompt}]
                    user_msg = f"Проект запущен. Контекст: {list(self._context.keys())[:20]}"
                    messages.append({"role": "user", "content": user_msg})
                    response = await self._call_model(node, messages, timeout=60)
                    self._context['_start_ai_response'] = response
                    parts.append(f"AI: {len(response)} символов")
                except Exception as e:
                    self._log(f"  ⚠ AI на старте: {e}")
                    parts.append(f"AI: ошибка ({e})")

        summary = " | ".join(parts) if parts else "▶ Холодный старт (без действий)"
        self._log(f"  ✅ {summary}")
        return f"▶ {summary}"
    
    async def _exec_program_open(self, node: AgentNode) -> str:
        """🖥 Открыть программу, найти окно, управлять. Поддерживает множественные экземпляры."""
        import subprocess, time, ctypes
        from ctypes import wintypes
        cfg = getattr(node, 'snippet_config', {}) or {}
        exe = cfg.get('executable', '')
        args = cfg.get('arguments', '')
        wait_sec = int(cfg.get('wait_ready', 3))
        inst_var = cfg.get('instance_var', 'program_pid').strip('{}').strip()
        hwnd_var = cfg.get('hwnd_var', 'program_hwnd').strip('{}').strip()
        hide = cfg.get('hide_to_tray', False)
        resize = cfg.get('resize_window', '')
        program_name = cfg.get('program_name', '') or os.path.basename(exe)

        for k, v in self._context.items():
            if not k.startswith('_'):
                exe = exe.replace(f'{{{k}}}', str(v))
                args = args.replace(f'{{{k}}}', str(v))

        if not exe:
            return "❌ Не указан путь к программе"
        self._log(f"🖥 Запуск: {exe} {args}")

        # ── Собираем ВСЕ уже известные HWND: из контекста + из metadata ──────────
        # Это ключевой момент: context пуст при новом запуске, но metadata персистентна
        def _collect_known_hwnds() -> set:
            known = set()
            # Из текущего контекста (текущий запуск)
            for e in self._context.get('_open_programs', {}).values():
                h = int(e.get('hwnd', 0) or 0)
                if h:
                    known.add(h)
            # Из metadata (предыдущие запуски — ключевое для multi-instance!)
            _meta = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(_meta, dict):
                for e in _meta.get('_open_programs_meta', {}).values():
                    h = int(e.get('hwnd', 0) or 0)
                    if h:
                        known.add(h)
            return known

        # ── Считаем сколько занято слотов offscreen (для правильного OFFSCREEN_X) ─
        def _count_offscreen_slots() -> int:
            """Количество программ уже перемещённых за экран (у кого offscreen_x > 10000)."""
            count = 0
            for e in self._context.get('_open_programs', {}).values():
                if int(e.get('offscreen_x', 0) or 0) > 10000:
                    count += 1
            _meta = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(_meta, dict):
                for e in _meta.get('_open_programs_meta', {}).values():
                    ox = int(e.get('offscreen_x', 0) or 0)
                    if ox > 10000:
                        count += 1
            return count

        # ── Определяем индекс экземпляра (для уникального hwnd_var) ─────────────
        def _is_pid_alive(check_pid: int) -> bool:
            """Проверить жив ли процесс через WinAPI (без psutil)."""
            try:
                h = ctypes.windll.kernel32.OpenProcess(0x100000, False, check_pid)
                if not h:
                    return False
                ret = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
                ctypes.windll.kernel32.CloseHandle(h)
                return ret == 0x102  # WAIT_TIMEOUT = процесс жив
            except Exception:
                return True  # при ошибке считаем живым

        def _find_existing_same_exe() -> tuple:
            """Вернуть (pid, instance_index) живого экземпляра того же EXE, или (None, None)."""
            for pid_str, e in list(self._context.get('_open_programs', {}).items()):
                if e.get('exe', '').lower() == exe.lower():
                    try:
                        _p = int(pid_str)
                        if _is_pid_alive(_p):
                            return _p, e.get('instance_index', 1)
                    except (ValueError, TypeError):
                        pass
            _meta_ex = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(_meta_ex, dict):
                for pid_str, e in list(_meta_ex.get('_open_programs_meta', {}).items()):
                    if e.get('exe', '').lower() == exe.lower():
                        try:
                            _p = int(pid_str)
                            if _is_pid_alive(_p):
                                return _p, e.get('instance_index', 1)
                        except (ValueError, TypeError):
                            pass
            return None, None

        def _find_next_free_slot() -> int:
            """Найти первый свободный instance_index (не занятый ни одной живой программой)."""
            used = set()
            for pid_str, e in self._context.get('_open_programs', {}).items():
                try:
                    if _is_pid_alive(int(pid_str)):
                        used.add(e.get('instance_index', 1))
                except (ValueError, TypeError):
                    pass
            _meta_fs = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(_meta_fs, dict):
                for pid_str, e in _meta_fs.get('_open_programs_meta', {}).items():
                    try:
                        if _is_pid_alive(int(pid_str)):
                            used.add(e.get('instance_index', 1))
                    except (ValueError, TypeError):
                        pass
            idx = 1
            while idx in used:
                idx += 1
            return idx

        single_instance = cfg.get('single_instance', False)

        try:
            # ── Определяем слот: single_instance = перезапуск в том же; иначе — новый ──
            if single_instance:
                existing_pid, reuse_instance_index = _find_existing_same_exe()
                if existing_pid is not None:
                    self._log(f"  ♻️ Single Instance: EXE уже открыт (PID:{existing_pid}, слот {reuse_instance_index - 1}), перезапуск...")
                    try:
                        subprocess.call(['taskkill', '/F', '/PID', str(existing_pid)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                    self._context.get('_open_programs', {}).pop(str(existing_pid), None)
                    _meta_kill = getattr(self._workflow, 'metadata', None) or {}
                    if isinstance(_meta_kill, dict):
                        _meta_kill.get('_open_programs_meta', {}).pop(str(existing_pid), None)
                    time.sleep(0.5)
                    instance_index = reuse_instance_index
                else:
                    instance_index = _find_next_free_slot()
            else:
                # Single Instance выключен — всегда новый слот, не трогаем существующие
                instance_index = _find_next_free_slot()

            cmd = [exe] + (args.split() if args else [])
            wd = cfg.get('working_dir', '') or None
            proc = subprocess.Popen(cmd, cwd=wd if wd else None)
            pid = proc.pid
            self._context[inst_var] = pid
            self._context['_program_pid'] = pid
            self._log(f"  PID: {pid}, слот: {instance_index - 1}")
            if instance_index > 1:
                hwnd_var_actual = f'{hwnd_var}_{instance_index}'
                inst_var_actual = f'{inst_var}_{instance_index}'
            else:
                hwnd_var_actual = hwnd_var
                inst_var_actual = inst_var
            if instance_index > 1:
                self._log(f"  📋 Экземпляр #{instance_index} → переменные: {hwnd_var_actual}, {inst_var_actual}")

            # Регистрируем в реестре
            prog_entry = {
                'pid': pid,
                'hwnd': 0,
                'name': program_name,
                'exe': exe,
                'hidden': hide,
                'instance_index': instance_index,
                'offscreen_x': 0,
                'offscreen_y': 0,
                'win_w': 0,
                'win_h': 0,
            }
            if '_open_programs' not in self._context:
                self._context['_open_programs'] = {}
            self._context['_open_programs'][str(pid)] = prog_entry

            if wait_sec > 0:
                time.sleep(wait_sec)

            user32 = ctypes.windll.user32
            WNDENUMPROC_T = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)

            # ── Вспомогательная функция поиска окон по PID ──────────────────────
            def _find_hwnds_by_pid(target_pid: int, include_invisible: bool = False) -> list:
                found = []
                def _cb(h, _):
                    visible = bool(user32.IsWindowVisible(h))
                    if visible or include_invisible:
                        _p = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(h, ctypes.byref(_p))
                        if _p.value == target_pid:
                            found.append(h)
                    return True
                user32.EnumWindows(WNDENUMPROC_T(_cb), 0)
                return found

            # ── Прячем окна за экран как только они появляются (поллинг) ─────────
            if hide:
                try:
                    _known_pre = _collect_known_hwnds()
                    _hidden_pre = set()
                    _slot = instance_index - 1
                    # Опрашиваем до wait_sec секунд (окно может появиться в любой момент)
                    _pre_deadline = time.time() + wait_sec
                    while time.time() < _pre_deadline:
                        _pre_found = _find_hwnds_by_pid(pid)
                        _fresh_pre = [h for h in _pre_found if h not in _known_pre and h not in _hidden_pre]
                        for _h in _fresh_pre:
                            user32.ShowWindow(_h, 5)
                            time.sleep(0.05)
                            _r = wintypes.RECT()
                            user32.GetWindowRect(_h, ctypes.byref(_r))
                            _ww = max(_r.right - _r.left, 800)
                            _wh = max(_r.bottom - _r.top, 600)
                            _ox = 20000 + _slot * (_ww + 50)
                            user32.MoveWindow(_h, _ox, 20000, _ww, _wh, True)
                            _hidden_pre.add(_h)
                            self._log(f"  📦 Окно скрыто за экран ({_ox},20000) [слот {_slot}]")
                        time.sleep(0.1)
                except Exception:
                    pass

            # ── Поиск HWND с retry-циклом ────────────────────────────────────────
            hwnd = 0
            try:
                _known_hwnds = _collect_known_hwnds()
                # Retry: до 10 попыток × 0.5с = ещё 5 секунд поверх wait_sec
                for _attempt in range(10):
                    _candidates = _find_hwnds_by_pid(pid, include_invisible=False)
                    if not _candidates:
                        # Fallback: ищем также невидимые
                        _candidates = _find_hwnds_by_pid(pid, include_invisible=True)
                    if _candidates:
                        # Исключаем все уже известные HWND (context + metadata)
                        _fresh = [h for h in _candidates if h not in _known_hwnds]
                        hwnd = _fresh[0] if _fresh else _candidates[0]
                        break
                    if _attempt < 9:
                        time.sleep(0.5)
                        self._log(f"  🔄 HWND не найден, попытка {_attempt + 2}/10...")

                if not hwnd:
                    self._log("  ⚠ HWND не найден после 10 попыток")
            except Exception as _ex:
                self._log(f"  ⚠ Ошибка поиска HWND: {_ex}")
            
            # ── Фаза стабилизации: ждём пока заставки/загрузчики не исчезнут ──────
            # Нужна для программ с экраном загрузки (ZennoPoster, AIDA64 и т.п.)
            # wait_splash задаётся в настройках сниппета (по умолчанию 0 = отключено)
            wait_splash = int(cfg.get('wait_splash', 0))
            if wait_splash > 0 and hwnd:
                self._log(f"  ⏳ Стабилизация окна ({wait_splash}с)...")
                _stable_start = time.time()
                _tracked = hwnd
                while time.time() - _stable_start < wait_splash:
                    time.sleep(0.4)
                    _win_alive = bool(user32.IsWindow(_tracked))
                    _wins_now = _find_hwnds_by_pid(pid, include_invisible=False)
                    if not _win_alive:
                        # Заставка закрылась — ищем новое главное окно
                        _new_wins = [h for h in _wins_now if h not in _known_hwnds]
                        if not _new_wins:
                            # Процесс сплеша умер и породил НОВЫЙ процесс (напр. ZennoPoster)
                            # Ищем по имени exe среди всех процессов системы
                            try:
                                import psutil as _psu
                                _exe_name = os.path.basename(exe).lower()
                                for _proc in _psu.process_iter(['pid', 'name', 'exe']):
                                    try:
                                        _pexe = (_proc.info.get('exe') or '').lower()
                                        _pname = (_proc.info.get('name') or '').lower()
                                        if _exe_name in _pexe or _exe_name in _pname:
                                            _child_pid = _proc.info['pid']
                                            if _child_pid != pid:
                                                _child_wins = _find_hwnds_by_pid(_child_pid)
                                                _fresh_child = [h for h in _child_wins if h not in _known_hwnds]
                                                if _fresh_child:
                                                    _new_wins = _fresh_child
                                                    pid = _child_pid  # обновляем PID на новый процесс
                                                    self._context[inst_var] = pid
                                                    self._context['_open_programs'][str(pid)] = \
                                                        self._context['_open_programs'].pop(str(proc.pid), prog_entry)
                                                    self._log(f"  🔄 Новый процесс после сплеша: PID={pid}")
                                                    break
                                    except Exception:
                                        pass
                            except ImportError:
                                pass
                        if _new_wins:
                            _tracked = _new_wins[0]
                            _known_hwnds.add(hwnd)  # старый HWND больше не "новый"
                            self._log(f"  🔄 Заставка → главное окно: {_tracked}")
                            # Сразу прячем если нужно
                            if hide:
                                try:
                                    _slot = instance_index - 1
                                    user32.ShowWindow(_tracked, 5)
                                    _r2 = wintypes.RECT()
                                    user32.GetWindowRect(_tracked, ctypes.byref(_r2))
                                    _ww2 = max(_r2.right - _r2.left, 800)
                                    _wh2 = max(_r2.bottom - _r2.top, 600)
                                    _ox2 = 20000 + _slot * (_ww2 + 50)
                                    user32.MoveWindow(_tracked, _ox2, 20000, _ww2, _wh2, True)
                                except Exception:
                                    pass
                            break
                    else:
                        # Окно живо — смотрим нет ли нового окна (главное появилось рядом с заставкой)
                        _new_extra = [h for h in _wins_now if h not in _known_hwnds and h != _tracked]
                        if _new_extra:
                            _tracked = _new_extra[0]
                            self._log(f"  🔄 Главное окно появилось: {_tracked}")
                            if hide:
                                try:
                                    _slot = instance_index - 1
                                    user32.ShowWindow(_tracked, 5)
                                    _r2 = wintypes.RECT()
                                    user32.GetWindowRect(_tracked, ctypes.byref(_r2))
                                    _ww2 = max(_r2.right - _r2.left, 800)
                                    _wh2 = max(_r2.bottom - _r2.top, 600)
                                    _ox2 = 20000 + _slot * (_ww2 + 50)
                                    user32.MoveWindow(_tracked, _ox2, 20000, _ww2, _wh2, True)
                                except Exception:
                                    pass
                            # Ждём пока заставка не закроется
                            for _ in range(10):
                                time.sleep(0.3)
                                if not user32.IsWindow(hwnd):
                                    break
                            break
                hwnd = _tracked
            
            # ── Сохраняем HWND в контекст и переменные ──────────────────────────
            if hwnd:
                self._context['_open_programs'][str(pid)]['hwnd'] = hwnd
                # Основной hwnd_var (с индексом если >1 экземпляр)
                self._context[hwnd_var_actual] = hwnd
                self._context[f'_program_hwnd_{instance_index}'] = hwnd  # всегда — адресация по индексу
                if instance_index == 1:
                    # Базовые переменные пишем ТОЛЬКО для первого экземпляра
                    self._context[hwnd_var] = hwnd
                    self._context['_program_hwnd'] = hwnd
                self._context[inst_var_actual] = pid
                # Именованная переменная по имени программы
                if program_name:
                    _safe = program_name.replace(' ', '_').lower()
                    _named = f'program_hwnd_{_safe}'
                    _named_idx = f'program_hwnd_{_safe}_{instance_index}'
                    self._context[_named] = hwnd
                    self._context[_named_idx] = hwnd
                    if isinstance(self._project_variables, dict):
                        self._project_variables[_named] = str(hwnd)
                        self._project_variables[_named_idx] = str(hwnd)
                        self.signals.variable_updated.emit(_named, str(hwnd))
                        self.signals.variable_updated.emit(_named_idx, str(hwnd))
                self._log(f"  HWND: {hwnd} → {hwnd_var_actual}")
                # Сохраняем в workflow.metadata
                if self._workflow and isinstance(getattr(self._workflow, 'metadata', None), dict):
                    if '_open_programs_meta' not in self._workflow.metadata:
                        self._workflow.metadata['_open_programs_meta'] = {}
                    self._workflow.metadata['_open_programs_meta'][str(pid)] = {
                        'hwnd': hwnd,
                        'name': program_name,
                        'exe': exe,
                        'instance_index': instance_index,
                        'hwnd_var': hwnd_var_actual,
                        'offscreen_x': 0,
                        'offscreen_y': 0,
                    }
                    self._workflow.metadata['_last_program_hwnd'] = hwnd
                    self._workflow.metadata['_last_program_pid'] = pid
                # Сохраняем в project_variables
                if self._project_variables is not None and isinstance(self._project_variables, dict):
                    for _vn in [hwnd_var_actual, hwnd_var]:
                        if _vn in self._project_variables:
                            if isinstance(self._project_variables[_vn], dict):
                                self._project_variables[_vn]['value'] = str(hwnd)
                            else:
                                self._project_variables[_vn] = str(hwnd)
                        else:
                            self._project_variables[_vn] = str(hwnd)
                        self.signals.variable_updated.emit(_vn, str(hwnd))

            # ── Resize если задан ───────────────────────────────────────────────
            if resize and 'x' in resize and hwnd:
                try:
                    w, h = resize.split('x')
                    user32.MoveWindow(hwnd, 0, 0, int(w), int(h), True)
                except Exception:
                    pass

            # ── Перемещаем за экран (финальная позиция по точному размеру) ──────
            if hide and hwnd:
                try:
                    user32.ShowWindow(hwnd, 5)
                    time.sleep(0.1)
                    r = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    win_w = max(r.right - r.left, 1)
                    win_h = max(r.bottom - r.top, 1)
                    # Слот = количество уже спрятанных программ (без текущей)
                    _slot = instance_index - 1   # тот же детерминированный слот — без гонки
                    OFFSCREEN_X = 20000 + _slot * (win_w + 50)
                    OFFSCREEN_Y = 20000
                    user32.MoveWindow(hwnd, OFFSCREEN_X, OFFSCREEN_Y, win_w, win_h, True)
                    self._log(f"  📦 Программа перемещена за экран ({OFFSCREEN_X},{OFFSCREEN_Y}) [слот {_slot}]")
                    # Обновляем координаты в обоих реестрах
                    self._context['_open_programs'][str(pid)].update({
                        'offscreen_x': OFFSCREEN_X,
                        'offscreen_y': OFFSCREEN_Y,
                        'win_w': win_w,
                        'win_h': win_h,
                    })
                    if self._workflow and isinstance(getattr(self._workflow, 'metadata', None), dict):
                        _pm = self._workflow.metadata.get('_open_programs_meta', {})
                        if str(pid) in _pm:
                            _pm[str(pid)].update({
                                'offscreen_x': OFFSCREEN_X,
                                'offscreen_y': OFFSCREEN_Y,
                                'win_w': win_w,
                                'win_h': win_h,
                            })
                except Exception as ex:
                    self._log(f"  ⚠ Не удалось переместить за экран: {ex}")

            return (f"✅ Программа запущена (PID:{pid}, HWND:{hwnd}, "
                    f"экземпляр #{instance_index}, переменная: {hwnd_var_actual})")
        except Exception as e:
            return f"❌ Ошибка: {e}"
            
    async def _exec_program_action(self, node: AgentNode) -> str:
        """🎯 Действие в окне программы."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        action = cfg.get('action', 'click')
        x = int(cfg.get('coord_x', 0))
        y = int(cfg.get('coord_y', 0))
        text = cfg.get('value', '')
        wait_ms = int(cfg.get('wait_after', 200))
        
        # Определяем HWND: сначала по instance_var из cfg, потом глобальный
        hwnd_var = cfg.get('hwnd_var', '').strip('{}').strip()
        hwnd = 0
        # 1. hwnd_var — прямое имя HWND-переменной (приоритет, как в Program Inspector)
        if hwnd_var:
            hwnd = int(self._context.get(hwnd_var, 0) or 0)
            if not hwnd and self._project_variables:
                pv = self._project_variables.get(hwnd_var)
                hwnd = int((pv.get('value', 0) if isinstance(pv, dict) else pv) or 0)
            if hwnd:
                self._log(f"  🔍 HWND из hwnd_var '{hwnd_var}': {hwnd}")
        # 2. instance_var (PID → _open_programs → hwnd)
        if not hwnd:
            inst_var = cfg.get('instance_var', '').strip('{}').strip()
            if inst_var:
                inst_val = self._context.get(inst_var)
                if inst_val:
                    open_progs = self._context.get('_open_programs', {})
                    pid_str = str(inst_val)
                    if pid_str in open_progs:
                        hwnd = open_progs[pid_str].get('hwnd', 0)
                    else:
                        try:
                            hwnd = int(inst_val)
                        except (ValueError, TypeError):
                            pass
        # 3. Глобальный _program_hwnd (только если экземпляр один)
        if not hwnd:
            hwnd = self._context.get('_program_hwnd', 0)
        # 4. Первый из _open_programs
        if not hwnd:
            for entry in self._context.get('_open_programs', {}).values():
                hwnd = entry.get('hwnd', 0)
                if hwnd:
                    break
        # 5. metadata — сначала по hwnd_var, потом last
        if not hwnd and self._workflow:
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            if hwnd_var:
                for _entry in _meta.get('_open_programs_meta', {}).values():
                    if _entry.get('hwnd_var') == hwnd_var:
                        hwnd = int(_entry.get('hwnd', 0) or 0)
                        if hwnd:
                            self._log(f"  🔍 HWND из metadata по hwnd_var '{hwnd_var}': {hwnd}")
                            break
            if not hwnd:
                hwnd = int(_meta.get('_last_program_hwnd', 0) or 0)
            if not hwnd:
                for _entry in _meta.get('_open_programs_meta', {}).values():
                    hwnd = int(_entry.get('hwnd', 0) or 0)
                    if hwnd:
                        break
            if hwnd:
                self._log(f"  🔍 HWND из metadata workflow: {hwnd}")

        for k, v in self._context.items():
            if not k.startswith('_'):
                text = text.replace(f'{{{k}}}', str(v))

        self._log(f"🎯 Program action: {action} ({x},{y})")
        try:
            import pyautogui
            pyautogui.PAUSE = 0.05

            # Фокус окна
            if hwnd:
                try:
                    import ctypes
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    import time; time.sleep(0.3)
                except Exception:
                    pass

            if action == 'click':
                pyautogui.click(x, y)
            elif action == 'double_click':
                pyautogui.doubleClick(x, y)
            elif action == 'right_click':
                pyautogui.rightClick(x, y)
            elif action == 'type_text':
                if x or y:
                    pyautogui.click(x, y)
                import time; time.sleep(0.1)
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
            elif action == 'hotkey':
                keys = [k.strip() for k in text.split('+')]
                pyautogui.hotkey(*keys)
            elif action == 'scroll':
                clicks = int(text) if text else 3
                pyautogui.scroll(clicks, x, y)
            elif action == 'drag':
                to_x = int(cfg.get('drag_to_x', 0))
                to_y = int(cfg.get('drag_to_y', 0))
                pyautogui.moveTo(x, y)
                pyautogui.drag(to_x - x, to_y - y, duration=0.5)
            elif action == 'focus':
                pass  # Уже сфокусировали выше
            elif action == 'minimize':
                if hwnd:
                    import ctypes; ctypes.windll.user32.ShowWindow(hwnd, 6)
            elif action == 'maximize':
                if hwnd:
                    import ctypes; ctypes.windll.user32.ShowWindow(hwnd, 3)
            elif action == 'close':
                if hwnd:
                    import ctypes; ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                # Убираем из реестра открытых программ → панель Программы очистится
                _inst_var_close = cfg.get('instance_var', '').strip('{}').strip() or 'program_pid'
                _pid_close = self._context.get(_inst_var_close)
                if _pid_close:
                    _pid_str = str(_pid_close)
                    self._context.get('_open_programs', {}).pop(_pid_str, None)
                    if self._workflow:
                        _m = getattr(self._workflow, 'metadata', {}) or {}
                        _m.get('_open_programs_meta', {}).pop(_pid_str, None)
                        if _m.get('_last_program_pid') == _pid_close or str(_m.get('_last_program_pid')) == _pid_str:
                            _m.pop('_last_program_hwnd', None)
                            _m.pop('_last_program_pid', None)

            if wait_ms > 0:
                import time; time.sleep(wait_ms / 1000.0)

            return f"✅ {action} ({x},{y})"
        except ImportError:
            return "❌ pip install pyautogui pyperclip"
        except Exception as e:
            return f"❌ {e}"

    async def _exec_program_click_image(self, node: AgentNode) -> str:
        """🖼 Клик по шаблону картинки в окне программы (base64 шаблон + скриншот через HWND)."""
        import time, base64, io
        cfg = getattr(node, 'snippet_config', {}) or {}
        template_b64 = cfg.get('template_image', '')   # base64 PNG — как в Browser Click Image
        threshold    = int(cfg.get('threshold', 80)) / 100.0
        timeout_s    = int(cfg.get('wait_timeout', 10))
        retry_ms     = int(cfg.get('retry_interval', 500))
        action       = cfg.get('action_type', 'click')
        off_x        = int(cfg.get('click_offset_x', 0))
        off_y        = int(cfg.get('click_offset_y', 0))
        if_not_found = cfg.get('if_not_found', 'error')
        var_out      = cfg.get('variable_out', '').strip('{}').strip()
        found_var    = cfg.get('found_var', '').strip('{}').strip()
        # ═══ Ищем HWND: из контекста → по inst_var → по PID из проектных переменных → EnumWindows ═══
        hwnd = 0
        inst_var = cfg.get('instance_var', '').strip('{}').strip()
        # Fallback: если поле не заполнено — берём стандартный ключ program_pid
        hwnd = 0
        # 1. hwnd_var — прямое имя HWND-переменной (приоритет)
        hwnd_var = cfg.get('hwnd_var', '').strip('{}').strip()
        if hwnd_var:
            hwnd = int(self._context.get(hwnd_var, 0) or 0)
            if not hwnd and self._project_variables:
                pv = self._project_variables.get(hwnd_var)
                hwnd = int((pv.get('value', 0) if isinstance(pv, dict) else pv) or 0)
            if hwnd:
                self._log(f"  🔍 HWND из hwnd_var '{hwnd_var}': {hwnd}")
        # 2. inst_var → _open_programs → hwnd
        inst_var = cfg.get('instance_var', '').strip('{}').strip()
        if not inst_var:
            inst_var = 'program_pid'
        if not hwnd and inst_var and inst_var in self._context:
            inst_val = self._context[inst_var]
            open_progs = self._context.get('_open_programs', {})
            pid_str = str(inst_val)
            if pid_str in open_progs:
                hwnd = open_progs[pid_str].get('hwnd', 0)
            else:
                try:
                    hwnd = int(inst_val)
                except (ValueError, TypeError):
                    pass
        # 3. _program_hwnd
        if not hwnd:
            hwnd = self._context.get('_program_hwnd', 0)
        # 4. _open_programs первый
        if not hwnd:
            for entry in self._context.get('_open_programs', {}).values():
                hwnd = entry.get('hwnd', 0)
                if hwnd:
                    break
        # 5. EnumWindows по PID (fallback)
        if not hwnd and inst_var and inst_var in self._context:
            try:
                target_pid = int(self._context[inst_var])
                import ctypes
                from ctypes import wintypes
                _found = []
                def _cb(h, _):
                    if ctypes.windll.user32.IsWindowVisible(h):
                        _p = wintypes.DWORD()
                        ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(_p))
                        if _p.value == target_pid:
                            _found.append(h)
                    return True
                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)
                ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
                if _found:
                    hwnd = _found[0]
                    self._log(f"  🔍 HWND найден по PID {target_pid}: {hwnd}")
            except Exception:
                pass
        # 6. metadata — по hwnd_var, потом last
        if not hwnd and self._workflow:
            _meta = getattr(self._workflow, 'metadata', {}) or {}
            if hwnd_var:
                for _entry in _meta.get('_open_programs_meta', {}).values():
                    if _entry.get('hwnd_var') == hwnd_var:
                        hwnd = int(_entry.get('hwnd', 0) or 0)
                        if hwnd:
                            self._log(f"  🔍 HWND из metadata по hwnd_var '{hwnd_var}': {hwnd}")
                            break
            if not hwnd:
                hwnd = int(_meta.get('_last_program_hwnd', 0) or 0)
            if not hwnd:
                for _entry in _meta.get('_open_programs_meta', {}).values():
                    hwnd = int(_entry.get('hwnd', 0) or 0)
                    if hwnd:
                        break
            if hwnd:
                self._log(f"  🔍 HWND из metadata workflow: {hwnd}")

        self._log(f"  🔍 HWND для Program Click Image: {hwnd}")

        if not template_b64:
            return "❌ Шаблон не задан — откройте настройки сниппета и выберите область на скриншоте программы"

        def _take_program_screenshot() -> tuple[bytes | None, int, int]:
            """Сделать скриншот окна программы через HWND.
            
            Возвращает (png_bytes, win_left, win_top) — левый верхний угол окна
            в экранных координатах нужен для последующей конвертации шаблонных
            координат → клиентских координат.
            """
            if not hwnd:
                return None, 0, 0
            try:
                import ctypes, ctypes.wintypes as wt
                from PIL import Image
                import win32gui, win32ui

                user32 = ctypes.windll.user32
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                win_l, win_t = r.left, r.top
                w = r.right - r.left
                h = r.bottom - r.top
                if w <= 0 or h <= 0:
                    return None, win_l, win_t

                # Один вызов PrintWindow через win32ui — захватывает даже скрытые / за экраном окна
                hwnd_dc = win32gui.GetWindowDC(hwnd)
                mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bmp     = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfc_dc, w, h)
                save_dc.SelectObject(bmp)
                # PW_RENDERFULLCONTENT (2) — рендерит DirectX/OpenGL содержимое
                user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
                bmpinfo = bmp.GetInfo()
                bmpstr  = bmp.GetBitmapBits(True)
                img     = Image.frombuffer('RGB',
                                           (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                                           bmpstr, 'raw', 'BGRX', 0, 1)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                win32gui.DeleteObject(bmp.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwnd_dc)
                return buf.getvalue(), win_l, win_t
            except Exception as e:
                self._log(f"  ⚠ PrintWindow error: {e}")
                return None, 0, 0

        def _find_template(screen_bytes: bytes) -> tuple[bool, int, int]:
            """Найти template_b64 на screen_bytes через OpenCV / PIL."""
            try:
                import cv2, numpy as np
                page_arr = np.frombuffer(screen_bytes, np.uint8)
                tmpl_arr = np.frombuffer(base64.b64decode(template_b64), np.uint8)
                page_img = cv2.imdecode(page_arr, cv2.IMREAD_COLOR)
                tmpl_img = cv2.imdecode(tmpl_arr, cv2.IMREAD_COLOR)
                if page_img is None or tmpl_img is None:
                    raise ValueError("decode failed")
                res = cv2.matchTemplate(page_img, tmpl_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    h, w = tmpl_img.shape[:2]
                    return True, max_loc[0] + w // 2, max_loc[1] + h // 2
                return False, 0, 0
            except ImportError:
                pass
            try:
                from PIL import Image
                import numpy as np
                page_img = np.array(Image.open(io.BytesIO(screen_bytes)).convert("RGB"))
                tmpl_img = np.array(Image.open(io.BytesIO(base64.b64decode(template_b64))).convert("RGB"))
                ph, pw = page_img.shape[:2]
                th, tw = tmpl_img.shape[:2]
                if th > ph or tw > pw:
                    return False, 0, 0
                best_score, best_loc = 0.0, (0, 0)
                for y in range(0, ph - th, 4):
                    for x in range(0, pw - tw, 4):
                        patch = page_img[y:y+th, x:x+tw]
                        score = 1.0 - np.abs(patch.astype(int) - tmpl_img.astype(int)).mean() / 255.0
                        if score > best_score:
                            best_score, best_loc = score, (x, y)
                if best_score >= threshold:
                    return True, best_loc[0] + tw // 2, best_loc[1] + th // 2
                return False, 0, 0
            except ImportError:
                self._log("⚠️ Установите opencv-python или Pillow: pip install opencv-python Pillow pywin32")
                return False, 0, 0

        self._log(f"🖼 Ищу шаблон в окне программы (HWND:{hwnd}, порог:{threshold:.0%})")
        deadline = time.time() + max(timeout_s, 0)
        found, fx, fy = False, 0, 0
        win_left, win_top = 0, 0
        attempts = 0
        while True:
            screen_bytes, win_left, win_top = _take_program_screenshot()
            if screen_bytes:
                found, fx, fy = _find_template(screen_bytes)
            attempts += 1
            if found or timeout_s <= 0 or time.time() > deadline:
                break
            time.sleep(retry_ms / 1000.0)

        if not found:
            if found_var:
                self._context[found_var] = 'false'
            msg = f"⚠ Шаблон не найден (попыток:{attempts}, порог:{threshold:.0%})"
            if if_not_found == 'error':
                raise RuntimeError(msg)
            return msg

        # Конвертируем оконные координаты (от левого верха HWND) → клиентские координаты.
        # GetWindowDC / PrintWindow захватывает весь HWND включая заголовок и рамки.
        # PostMessage(WM_LBUTTONDOWN) ожидает координаты в CLIENT-пространстве.
        try:
            import ctypes, ctypes.wintypes as _wt
            _pt = _wt.POINT(win_left + fx, win_top + fy)  # экранные координаты шаблона
            ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(_pt))
            cx, cy = _pt.x + off_x, _pt.y + off_y
        except Exception:
            # Fallback: грубое вычитание стандартных рамок (8px border + 30px title)
            cx, cy = max(0, fx - 8 + off_x), max(0, fy - 30 + off_y)

        if found_var:
            self._context[found_var] = 'true'
        if var_out:
            self._context[var_out] = f"{cx},{cy}"

        # Клик через PostMessageW — работает для скрытых/фоновых окон
        try:
            import ctypes
            user32 = ctypes.windll.user32
            PostMessageW = user32.PostMessageW
            PostMessageW.restype = ctypes.c_bool
            PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_ulong, ctypes.c_long]
            MAKELPARAM = lambda x, y: ctypes.c_long((y << 16) | (x & 0xFFFF)).value
            lp = MAKELPARAM(cx, cy)
            WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
            WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
            WM_LBUTTONDBLCLK             = 0x0203
            if action in ('click', 'left_click'):
                PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
                time.sleep(0.05)
                PostMessageW(hwnd, WM_LBUTTONUP,   0, lp)
            elif action == 'double_click':
                PostMessageW(hwnd, WM_LBUTTONDBLCLK, 1, lp)
                time.sleep(0.05)
                PostMessageW(hwnd, WM_LBUTTONUP,     0, lp)
            elif action == 'right_click':
                PostMessageW(hwnd, WM_RBUTTONDOWN, 1, lp)
                time.sleep(0.05)
                PostMessageW(hwnd, WM_RBUTTONUP,   0, lp)
            elif action == 'hover':
                PostMessageW(hwnd, 0x0200, 0, lp)  # WM_MOUSEMOVE
            self._log(f"✅ Клик ({action}) по координатам ({cx},{cy}) в окне")
        except Exception as e:
            self._log(f"  ⚠ Ошибка клика: {e}")
            return f"❌ {e}"

        return f"✅ Найдено и кликнуто: ({cx},{cy})"
        
    async def _exec_program_screenshot(self, node: AgentNode) -> str:
        """📸 Скриншот окна программы."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        region_mode = cfg.get('screenshot_region', 'full')
        region_rect = cfg.get('region_rect', '')
        save_mode = cfg.get('save_mode', 'variable')
        var_out = cfg.get('variable_out', 'screenshot').strip('{}').strip()
        save_path = cfg.get('save_path', '')
        fmt = cfg.get('image_format', 'png')
        hwnd = self._context.get('_program_hwnd', 0)

        for k, v in self._context.items():
            if not k.startswith('_'):
                save_path = save_path.replace(f'{{{k}}}', str(v))

        self._log(f"📸 Скриншот программы ({region_mode})")
        try:
            import pyautogui

            # Фокус
            if hwnd:
                try:
                    import ctypes; ctypes.windll.user32.SetForegroundWindow(hwnd)
                    import time; time.sleep(0.3)
                except Exception:
                    pass

            if region_mode == 'region' and region_rect:
                parts = [int(x.strip()) for x in region_rect.split(',')]
                if len(parts) == 4:
                    img = pyautogui.screenshot(region=tuple(parts))
                else:
                    img = pyautogui.screenshot()
            else:
                # Снимок всего окна через HWND если доступен
                if hwnd and region_mode in ('full', 'client'):
                    try:
                        import ctypes
                        from ctypes import wintypes
                        r = wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                        img = pyautogui.screenshot(region=(r.left, r.top, r.right - r.left, r.bottom - r.top))
                    except Exception:
                        img = pyautogui.screenshot()
                else:
                    img = pyautogui.screenshot()

            result_path = ''
            if save_mode in ('file', 'both') and save_path:
                os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
                img.save(save_path, fmt.upper())
                result_path = save_path
                self._context[var_out] = save_path

            if save_mode in ('variable', 'both'):
                import io, base64
                buf = io.BytesIO()
                img.save(buf, format=fmt.upper())
                b64 = base64.b64encode(buf.getvalue()).decode('ascii')
                if save_mode == 'variable':
                    self._context[var_out] = b64
                # Для 'both' — путь уже в переменной

            return f"✅ Скриншот: {result_path or 'в переменной'}"
        except ImportError:
            return "❌ pip install pyautogui"
        except Exception as e:
            return f"❌ {e}"

    async def _exec_program_agent(self, node: AgentNode) -> str:
        """🖥🧠 AI-агент управления окном программы через скриншоты."""
        import base64 as _b64, io as _io, time as _time, asyncio as _asyncio
        cfg        = getattr(node, 'snippet_config', {}) or {}
        task       = cfg.get('task', '') or getattr(node, 'system_prompt', '') or ''
        max_acts   = int(cfg.get('max_actions', 10))
        timeout_s  = int(cfg.get('ai_timeout_sec', 120))
        wait_ms    = int(cfg.get('action_wait_ms', 500))
        var_out    = cfg.get('variable_out', '').strip('{}').strip()

        for k, v in self._context.items():
            if not k.startswith('_'):
                task = task.replace(f'{{{k}}}', str(v))

        # ── Получаем HWND ──────────────────────────────────────
        hwnd = 0
        inst_var = cfg.get('instance_var', '').strip('{}').strip() or 'program_pid'
        if inst_var in self._context:
            inst_val  = self._context[inst_var]
            open_progs = self._context.get('_open_programs', {})
            pid_str   = str(inst_val)
            if pid_str in open_progs:
                hwnd = open_progs[pid_str].get('hwnd', 0)
            else:
                try:
                    hwnd = int(inst_val)
                except (ValueError, TypeError):
                    pass
        if not hwnd:
            hwnd = self._context.get('_program_hwnd', 0)
        if not hwnd and self._workflow:
            _m = getattr(self._workflow, 'metadata', {}) or {}
            hwnd = _m.get('_last_program_hwnd', 0)

        if not hwnd:
            return "❌ HWND не найден — запустите Program Open перед Program Agent"
        if not task:
            return "❌ Задача не задана — заполните поле 'Задача для AI'"

        self._log(f"🖥🧠 Program Agent: HWND={hwnd}, задача: {task[:80]}...")

        # ── Скриншот окна ──────────────────────────────────────
        def _take_screenshot() -> str | None:
            try:
                import ctypes
                from PIL import Image
                import win32gui, win32ui
                left, top, right, bot = win32gui.GetWindowRect(hwnd)
                w, h = right - left, bot - top
                if w <= 0 or h <= 0:
                    return None
                hdc      = win32gui.GetWindowDC(hwnd)
                mfc_dc   = win32ui.CreateDCFromHandle(hdc)
                save_dc  = mfc_dc.CreateCompatibleDC()
                bmp      = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfc_dc, w, h)
                save_dc.SelectObject(bmp)
                ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
                bmi  = bmp.GetInfo()
                data = bmp.GetBitmapBits(True)
                img  = Image.frombuffer('RGB', (bmi['bmWidth'], bmi['bmHeight']),
                                        data, 'raw', 'BGRX', 0, 1)
                win32gui.DeleteObject(bmp.GetHandle())
                save_dc.DeleteDC(); mfc_dc.DeleteDC()
                win32gui.ReleaseDC(hwnd, hdc)
                buf = _io.BytesIO()
                img.save(buf, format='PNG')
                return _b64.b64encode(buf.getvalue()).decode()
            except Exception as e:
                self._log(f"  ⚠ screenshot error: {e}")
                return None

        # ── Действие в окне ────────────────────────────────────
        def _do_action(act: str, x: int, y: int, text: str = ''):
            try:
                import ctypes
                user32     = ctypes.windll.user32
                PostMsgW   = user32.PostMessageW
                PostMsgW.restype  = ctypes.c_bool
                PostMsgW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_ulong, ctypes.c_long]
                lp = ctypes.c_long(((y & 0xFFFF) << 16) | (x & 0xFFFF)).value
                if act in ('click', 'left_click'):
                    PostMsgW(hwnd, 0x0201, 1, lp); _time.sleep(0.05)
                    PostMsgW(hwnd, 0x0202, 0, lp)
                elif act == 'double_click':
                    PostMsgW(hwnd, 0x0203, 1, lp); _time.sleep(0.05)
                    PostMsgW(hwnd, 0x0202, 0, lp)
                elif act == 'right_click':
                    PostMsgW(hwnd, 0x0204, 1, lp); _time.sleep(0.05)
                    PostMsgW(hwnd, 0x0205, 0, lp)
                elif act == 'type_text' and text:
                    user32.SetForegroundWindow(hwnd)
                    _time.sleep(0.2)
                    import pyperclip, pyautogui
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                elif act == 'hotkey' and text:
                    import pyautogui
                    user32.SetForegroundWindow(hwnd)
                    _time.sleep(0.15)
                    pyautogui.hotkey(*[k.strip() for k in text.split('+')])
            except Exception as e:
                self._log(f"  ⚠ action error: {e}")

        # ── AI цикл ────────────────────────────────────────────
        model_id = (node.model_id or
                    getattr(self, '_default_model_id', None) or
                    (self._model_manager.get_default_model_id()
                     if self._model_manager else None))
        if not model_id:
            return "❌ Не выбрана AI-модель для Program Agent"

        result_text = ''
        start_t     = _time.time()
        step        = 0

        for step in range(max_acts):
            if _time.time() - start_t > timeout_s:
                self._log("⏱ Program Agent: таймаут")
                break

            shot = _take_screenshot()
            if not shot:
                return "❌ Не удалось сделать скриншот окна"

            prompt = (
                f"Задача: {task}\n"
                f"Шаг {step + 1}/{max_acts}.\n"
                "Проанализируй скриншот и верни ТОЛЬКО JSON без пояснений:\n"
                '{"action":"click|double_click|right_click|type_text|hotkey|done|fail",'
                '"x":0,"y":0,"text":"","reason":""}\n'
                'action=done — задача выполнена. action=fail — невозможно выполнить.'
            )

            try:
                import json as _json
                provider = self._model_manager.get_provider(model_id)
                response = await _asyncio.wait_for(
                    provider.complete_with_image(prompt, shot),
                    timeout=30
                )
                raw = response.strip()
                j0, j1 = raw.find('{'), raw.rfind('}') + 1
                parsed = _json.loads(raw[j0:j1]) if j0 >= 0 and j1 > j0 else {}
            except Exception as e:
                self._log(f"  ⚠ AI error: {e}")
                break

            act    = parsed.get('action', 'fail')
            ax     = int(parsed.get('x', 0))
            ay     = int(parsed.get('y', 0))
            atext  = str(parsed.get('text', ''))
            reason = str(parsed.get('reason', ''))
            self._log(f"  🖥🧠 step {step+1}: {act} ({ax},{ay}) — {reason[:60]}")

            if act == 'done':
                result_text = reason or 'Задача выполнена'
                break
            if act == 'fail':
                result_text = f"AI не смог: {reason}"
                break

            _do_action(act, ax, ay, atext)
            _time.sleep(wait_ms / 1000.0)

        if var_out and result_text:
            self._context[var_out] = result_text

        return f"✅ Program Agent: {result_text or f'выполнено {step+1} действий'}"

    async def _call_model_raw(self, node, messages, model_id=''):
        """Вызов модели с конкретным model_id (или default)."""
        if not self._model_manager or not self._model_manager.active_provider:
            return "⚠ Нет активной модели"
        provider = self._model_manager.active_provider
        full = []
        async for chunk in provider.stream(messages, temperature=0.7, max_tokens=4096):
            full.append(chunk)
        return ''.join(full)
    
    async def _exec_browser_profile_op(self, node) -> str:
        """Операции с профилем браузера: сохранение, загрузка, профиль-папка, переназначение."""
        import json
        from pathlib import Path

        cfg = getattr(node, 'snippet_config', {}) or {}
        op  = cfg.get('profile_op', 'save_file')

        # ── Получить активный инстанс ──────────────────────────────────
        def _get_inst():
            from constructor.browser_module import BrowserManager
            pbm = getattr(self, 'project_browser_manager', None)
            mgr = (pbm._manager if pbm and hasattr(pbm, '_manager')
                   else None) or BrowserManager.get()
            iid = cfg.get('instance_id') or self._context.get('browser_instance_id')
            if not iid and pbm and hasattr(pbm, 'first_instance_id'):
                iid = pbm.first_instance_id()
            if iid:
                inst = (pbm.get_instance(iid) if pbm else None) or mgr.get_instance(iid)
                if inst:
                    return inst
            instances = list(mgr.all_instances().values()) if hasattr(mgr, 'all_instances') else []
            return instances[0] if instances else None

        # ── Подстановка переменных ────────────────────────────────────
        def _rv(text: str) -> str:
            if not text:
                return text
            for k, v in self._context.items():
                text = text.replace(f'{{{k}}}', str(v))
            text = text.replace('{project_dir}', self._project_root or '.')
            return text

        profile_path = _rv(cfg.get('profile_path', ''))
        # ═══ АВТО: если путь пустой при сохранении — формируем из проекта или инстанса ═══
        if not profile_path.strip() and op in ('save_file', 'save_folder'):
            inst = _get_inst()
            _inst_folder = ''
            if inst:
                _inst_folder = getattr(getattr(inst, 'profile', None), 'profile_folder', '') or ''
            if _inst_folder:
                profile_path = _inst_folder
                self._log(f"📁 Авто-путь из инстанса: {profile_path}")
            elif self._project_root:
                import os as _os
                _ext = '.json' if op == 'save_file' else ''
                profile_path = _os.path.join(self._project_root, 'profiles', f'default_profile{_ext}')
                self._log(f"📁 Авто-путь проекта: {profile_path}")
        result_var   = cfg.get('result_var',       '').strip().strip('{}')
        name_var     = cfg.get('profile_name_var', '').strip().strip('{}')

        def _set_var(key, val):
            if key:
                self._context[key] = val
                if self._project_variables is not None:
                    self._project_variables[key] = val

        # ═══════════════════════════════════════════════════════════════
        # СОХРАНИТЬ ПРОФИЛЬ-ФАЙЛ
        # ═══════════════════════════════════════════════════════════════
        if op == 'save_file':
            inst = _get_inst()
            if not inst:
                return "❌ Профиль: нет активного инстанса браузера"
            try:
                p = Path(profile_path)
                if cfg.get('create_if_missing', True):
                    p.parent.mkdir(parents=True, exist_ok=True)

                save_vars  = cfg.get('save_variables', False)
                save_proxy = cfg.get('save_proxy', False)
                var_mode   = cfg.get('variables_mode', 'all')
                var_list   = [v.strip() for v in cfg.get('variables_list', '').split(',') if v.strip()]

                cookies = []
                if hasattr(inst, 'get_cookies'):
                    try:
                        cookies = inst.get_cookies() or []
                    except Exception:
                        pass

                profile_data = {
                    'user_agent':  getattr(inst, 'user_agent', ''),
                    'cookies':     cookies,
                    'proxy':       getattr(inst, '_proxy_string', '') if save_proxy else '',
                    'name':        getattr(inst, 'profile_name', p.stem),
                    'variables':   {},
                    'viewport':    getattr(inst, 'viewport', ''),
                    'language':    getattr(inst, 'language', ''),
                    'timezone':    getattr(inst, 'timezone', ''),
                }
                if save_vars and self._project_variables:
                    src = dict(self._project_variables)
                    if var_mode == 'selected' and var_list:
                        src = {k: v for k, v in src.items() if k in var_list}
                    profile_data['variables'] = src

                p.write_text(json.dumps(profile_data, ensure_ascii=False, indent=2), encoding='utf-8')
                self._log(f"💾 Профиль сохранён: {profile_path}")
                _set_var(result_var, profile_path)
                return f"💾 Профиль сохранён: {p.name}"
            except Exception as e:
                return f"❌ Ошибка сохранения профиля: {e}"

        # ═══════════════════════════════════════════════════════════════
        # ЗАГРУЗИТЬ ПРОФИЛЬ-ФАЙЛ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'load_file':
            inst = _get_inst()
            if not inst:
                return "❌ Профиль: нет активного инстанса браузера"
            try:
                p = Path(profile_path)
                if not p.exists():
                    if cfg.get('create_if_missing', True):
                        self._log(f"⚠️ Файл не найден, продолжаем с пустым профилем: {profile_path}")
                        return f"⚠️ Файл профиля не найден: {p.name}"
                    return f"❌ Файл профиля не найден: {profile_path}"

                profile_data = json.loads(p.read_text(encoding='utf-8'))

                # Применяем куки
                cookies = profile_data.get('cookies', [])
                if cookies and hasattr(inst, 'set_cookies'):
                    try:
                        inst.set_cookies(cookies)
                    except Exception:
                        pass

                # Применяем переменные
                pv = profile_data.get('variables', {})
                if pv and cfg.get('create_missing_vars', True) and self._project_variables is not None:
                    self._project_variables.update(pv)
                    self._context.update(pv)

                # Восстанавливаем другие параметры
                for attr in ('user_agent', 'viewport', 'language', 'timezone'):
                    val = profile_data.get(attr)
                    if val and hasattr(inst, attr):
                        setattr(inst, attr, val)

                profile_name = profile_data.get('name', p.stem)
                self._log(f"📂 Профиль загружен: {profile_name}")
                _set_var(result_var, profile_path)
                _set_var(name_var, profile_name)
                return f"📂 Профиль загружен: {profile_name}"
            except Exception as e:
                return f"❌ Ошибка загрузки профиля: {e}"

        # ═══════════════════════════════════════════════════════════════
        # СОХРАНИТЬ ПРОФИЛЬ-ПАПКУ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'save_folder':
            inst = _get_inst()
            if not inst:
                return "❌ Профиль-папка: нет активного инстанса"
            try:
                p = Path(profile_path)
                p.mkdir(parents=True, exist_ok=True)

                # Метаданные
                meta = {
                    'user_agent': getattr(inst, 'user_agent', ''),
                    'name':       getattr(inst, 'profile_name', p.name),
                    'viewport':   getattr(inst, 'viewport', ''),
                    'language':   getattr(inst, 'language', ''),
                    'timezone':   getattr(inst, 'timezone', ''),
                    'proxy':      getattr(inst, '_proxy_string', '') if cfg.get('save_proxy') else '',
                }
                (p / 'meta.json').write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8'
                )

                # Куки
                if hasattr(inst, 'get_cookies'):
                    try:
                        cookies = inst.get_cookies() or []
                        (p / 'cookies.json').write_text(
                            json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8'
                        )
                    except Exception:
                        pass

                # Переменные
                if cfg.get('save_variables') and self._project_variables:
                    var_mode = cfg.get('variables_mode', 'all')
                    var_list = [v.strip() for v in cfg.get('variables_list', '').split(',') if v.strip()]
                    src = dict(self._project_variables)
                    if var_mode == 'selected' and var_list:
                        src = {k: v for k, v in src.items() if k in var_list}
                    (p / 'variables.json').write_text(
                        json.dumps(src, ensure_ascii=False, indent=2), encoding='utf-8'
                    )

                self._log(f"📁 Профиль-папка сохранена: {profile_path}")
                _set_var(result_var, profile_path)
                _set_var(name_var, profile_name)
                self._context['_browser_profile_path'] = profile_path
                return f"📁 Профиль-папка сохранена: {p.name}"
            except Exception as e:
                return f"❌ Ошибка сохранения профиль-папки: {e}"

        # ═══════════════════════════════════════════════════════════════
        # ЗАПУСТИТЬ ИНСТАНС С ПРОФИЛЬ-ПАПКОЙ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'launch_folder':
            try:
                p = Path(profile_path)
                if not p.exists():
                    if cfg.get('create_if_missing', True):
                        p.mkdir(parents=True, exist_ok=True)
                        self._log(f"📁 Создана новая профиль-папка: {profile_path}")
                    else:
                        return f"❌ Профиль-папка не найдена: {profile_path}"

                # Загружаем переменные
                vars_file = p / 'variables.json'
                if vars_file.exists() and cfg.get('create_missing_vars', True):
                    saved = json.loads(vars_file.read_text(encoding='utf-8'))
                    if self._project_variables is not None:
                        self._project_variables.update(saved)
                    self._context.update(saved)

                # Загружаем мета
                meta_file = p / 'meta.json'
                profile_name = p.name
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding='utf-8'))
                    profile_name = meta.get('name', p.name)

                self._log(f"📂 Инстанс использует профиль-папку: {profile_path}")
                _set_var(result_var, profile_path)
                _set_var(name_var, profile_name)
                self._context['_browser_profile_path'] = profile_path
                return f"📂 Профиль-папка подключена: {profile_name}"
            except Exception as e:
                return f"❌ Ошибка подключения профиль-папки: {e}"

        # ═══════════════════════════════════════════════════════════════
        # ПЕРЕНАЗНАЧИТЬ ПОЛЯ ПРОФИЛЯ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'reassign':
            inst = _get_inst()
            if not inst:
                return "❌ Переназначение: нет активного инстанса"
            applied = []
            field_map = {
                'user_agent':  'reassign_ua',
                'first_name':  'reassign_name',
                'last_name':   'reassign_surname',
                'email':       'reassign_email',
                'login':       'reassign_login',
                'password':    'reassign_password',
                'phone':       'reassign_phone',
                'birthday':    'reassign_birthday',
                'viewport':    'reassign_viewport',
                'timezone':    'reassign_timezone',
                'language':    'reassign_language',
            }
            for attr, cfg_key in field_map.items():
                val = _rv(cfg.get(cfg_key, ''))
                if val and hasattr(inst, attr):
                    setattr(inst, attr, val)
                    applied.append(f"{attr}={val[:25]}")

            # Геолокация
            geo = _rv(cfg.get('reassign_geo', ''))
            if geo:
                parts = geo.split(',')
                if len(parts) == 2:
                    try:
                        lat, lon = float(parts[0].strip()), float(parts[1].strip())
                        if hasattr(inst, 'geolocation'):
                            inst.geolocation = (lat, lon)
                        applied.append(f"geo={lat},{lon}")
                    except ValueError:
                        pass

            # Пол
            gender = cfg.get('reassign_gender', '')
            if gender and hasattr(inst, 'gender'):
                inst.gender = gender
                applied.append(f"gender={gender}")

            # Прокси
            proxy = _rv(cfg.get('proxy_string', ''))
            if proxy:
                inst._proxy_string = proxy
                applied.append(f"proxy={proxy[:25]}")

            msg = f"✏️ Поля переназначены: {', '.join(applied)}" if applied else "✏️ Нет изменений"
            self._log(msg)
            return msg

        # ═══════════════════════════════════════════════════════════════
        # ОБНОВИТЬ ПРОФИЛЬ (новая версия браузера)
        # ═══════════════════════════════════════════════════════════════
        elif op == 'update':
            inst = _get_inst()
            self._log("🔄 Обновление профиля — поиск новой версии браузера...")
            if inst:
                old_ua = getattr(inst, 'user_agent', '')
                # Реальная реализация требует API генерации профилей
                _set_var(result_var, 'updated')
                return f"🔄 Профиль обновлён (был UA: {old_ua[:60]})"
            return "❌ Нет инстанса для обновления профиля"

        # ═══════════════════════════════════════════════════════════════
        # СГЕНЕРИРОВАТЬ НОВЫЙ ПРОФИЛЬ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'generate':
            import random, string
            new_name = ''.join(random.choices(string.ascii_lowercase, k=8))
            self._log(f"🔀 Сгенерирован новый профиль: {new_name}")
            _set_var(result_var, new_name)
            _set_var(name_var, new_name)
            self._context['_profile_name'] = new_name
            return f"🔀 Профиль сгенерирован: {new_name}"

        # ═══════════════════════════════════════════════════════════════
        # ПОКАЗАТЬ ТЕКУЩИЙ ПРОФИЛЬ
        # ═══════════════════════════════════════════════════════════════
        elif op == 'show':
            inst = _get_inst()
            if inst:
                lines = [
                    f"  Имя:        {getattr(inst, 'profile_name', '—')}",
                    f"  User-Agent: {getattr(inst, 'user_agent', '—')[:80]}",
                    f"  Прокси:     {getattr(inst, '_proxy_string', '—')}",
                    f"  Язык:       {getattr(inst, 'language', '—')}",
                    f"  Таймзона:   {getattr(inst, 'timezone', '—')}",
                    f"  Разрешение: {getattr(inst, 'viewport', '—')}",
                ]
                msg = "👁 Текущий профиль:\n" + "\n".join(lines)
                self._log(msg)
                return msg
            return "❌ Нет активного инстанса"

        return f"❓ Неизвестная операция профиля: {op}"
    
    async def _exec_browser_agent(self, node: AgentNode) -> str:
        """Новый AI-агент: понимает контекст Planner + DOM + screenshot."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        instance_id = cfg.get("instance_id") or next(iter(self._browser_manager.all_instances()), None)
        
        if not instance_id:
            return "❌ Нет открытого браузера (запустите BROWSER_LAUNCH)"
        
        inst = self._browser_manager.get_instance(instance_id)
        if not inst or not inst.is_running:
            return "❌ Браузер не запущен"
        
        # 1. Получаем умный DOM-контекст
        context = inst.get_smart_dom_context(max_tokens=12000)
        
        # 2. Добавляем контекст от Planner (последний успешный Planner)
        planner_output = ""
        for res in self._results.values():
            if res.node_name.lower().startswith("planner") and res.status == "success":
                planner_output = res.output
                break
        
        # 3. Инжектим в промпт агента
        extra_context = f"""🌐 БРАУЗЕР КОНТЕКСТ:
URL: {context.get('url', '—')}
Title: {context.get('title', '—')}
DOM (сокращённый): {context.get('dom_summary', '')[:8000]}
Видимый текст: {context.get('visible_text', '')[:1500]}
Скриншот: {'✅ получен' if context.get('screenshot_base64') else '❌ не нужен'}

📋 КОНТЕКСТ ОТ PLANNER:
{planner_output[:4000]}

Выполни действие из задачи выше."""
        
        # Добавляем в глобальный контекст
        self._context["_browser_context"] = context
        self._context["_browser_dom"] = context.get("dom_summary", "")
        
        return f"🌐 Browser Agent готов\nURL: {context.get('url')}\nDOM tokens: ~{len(context.get('dom_summary', ''))}"
    
    
    async def _exec_browser_agent_single(self, node: AgentNode, timeout: int) -> str:
        """Обычный режим BROWSER_AGENT — одна задача."""
        cfg = getattr(node, 'snippet_config', {}) or {}
        
        # Получаем ProjectBrowserManager (как в Browser Action)
        pbm = (self.execution_context.get("_project_browser_manager") or
               getattr(self, 'project_browser_manager', None) or
               getattr(self, '_project_browser_manager', None))
        
        # Используем менеджер проекта, а не глобальный синглтон
        from constructor.browser_module import BrowserManager
        pbm_agent = (self.execution_context.get("_project_browser_manager") or
               getattr(self, 'project_browser_manager', None) or
               getattr(self, '_project_browser_manager', None))
        manager = (pbm_agent._manager if pbm_agent and hasattr(pbm_agent, '_manager') else None) or BrowserManager.get()
        
        # Ищем browser_id точно как в Browser Action
        browser_id = cfg.get('instance_id')
        if not browser_id:
            browser_id = self.execution_context.get("browser_instance_id") or self._context.get("browser_instance_id")
        if not browser_id and pbm:
            browser_id = pbm.first_instance_id()
        if not browser_id:
            browser_id = next(iter(manager.all_instances()), None)
        
        self._log(f"[DEBUG] BROWSER_AGENT: ищу browser_id, найдено: {browser_id}")
        
        # Получаем инстанс точно как в Browser Action
        inst = None
        if browser_id:
            if pbm:
                inst = pbm.get_instance(browser_id)
            if not inst:
                inst = manager.get_instance(browser_id)
        
        # Проверяем активность
        has_active = inst and getattr(inst, 'is_running', False)
        active_instance = inst if has_active else None
        
        if has_active:
            self._log(f"[DEBUG] Найден активный инстанс: {browser_id}")
        
        if not has_active:
            self._log(f"⚠️ BROWSER_AGENT '{node.name}': нет активного браузера для проекта")
            raise RuntimeError("No active browser instance")
        
        # Синхронизируем ID в контексте
        self.execution_context["browser_instance_id"] = browser_id
        self._context["browser_instance_id"] = browser_id
        planner_output = ""
        planner_node_id = getattr(node, "browser_planner_node_id", "")
        if planner_node_id and planner_node_id in self._results:
            planner_result = self._results[planner_node_id]
            planner_output = getattr(planner_result, "output", "")

        # Fallback — ищем последний Planner
        if not planner_output:
            for nid in reversed(self.execution_path):
                if nid in self._results:
                    res = self._results[nid]
                    node_obj = self._scene_nodes.get(nid)
                    if node_obj and getattr(node_obj, 'agent_type', None) == AgentType.PLANNER:
                        planner_output = getattr(res, "output", "")
                        break

        if pbm is None:
            self._log(f"⚠️ BROWSER_AGENT '{node.name}': нет ProjectBrowserManager в контексте")
            raise RuntimeError("No ProjectBrowserManager")

        from constructor.browser_module import execute_browser_agent_node
        provider = self._model_manager.active_provider
        
        async def _call_model_wrapper(messages, timeout=60):
            chunks = []
            async for chunk in provider.stream(messages):
                chunks.append(chunk)
            return "".join(chunks)
        
        try:
            self.execution_context = execute_browser_agent_node(
                node=node,
                context=self.execution_context,
                project_browser_manager=pbm,
                planner_output=planner_output,
                model_provider=provider,
                logger=self._log,
                call_model_func=_call_model_wrapper,
            )
            # Загружаем глобальные переменные проекта в контекст
            self._load_global_variables_to_context()
            return f"Выполнено действий: {self.execution_context.get('browser_agent_actions_count', 0)}"
        except Exception as e:
            raise RuntimeError(f"Browser Agent error: {e}")

    async def _exec_browser_agent_preprocessed(self, node: AgentNode, timeout: int) -> str:
        """Режим предобработки: разбиваем план на задачи и выполняем по очереди."""
        import re
        import asyncio
        
        # Получаем вывод от Planner
        planner_output = ""
        planner_node_id = getattr(node, "browser_planner_node_id", "")
        
        if planner_node_id and planner_node_id in self._results:
            planner_output = self._results[planner_node_id].output
        else:
            # Автопоиск последнего PLANNER
            for nid in reversed(self.execution_path):
                if nid in self._results:
                    node_obj = self._scene_nodes.get(nid)
                    if node_obj and getattr(node_obj, 'agent_type', None) == AgentType.PLANNER:
                        planner_output = self._results[nid].output
                        break
        
        if not planner_output:
            self._log("  ⚠️ Предобработка: не найден вывод Planner'а, выполняю как обычно")
            return await self._exec_browser_agent_single(node, timeout)
        
        self._log(f"  📋 План получен: {len(planner_output)} символов")
        
        # === РАЗБИВКА НА ЗАДАЧИ ===
        separator_mode = getattr(node, 'planner_task_separator', 'auto')
        tasks = []
        
        if separator_mode == "auto":
            # Пробуем все форматы по очереди
            patterns = [
                (r'^\s*\d+[\.\)]\s+(.+?)(?=\n\s*\d+[\.\)]|\Z)', "numbered"),      # 1. 2. 3.
                (r'^\s*[-*•]\s+(.+?)(?=\n\s*[-*•]|\Z)', "bullet"),               # - * •
                (r'^#{1,3}\s+(.+?)(?=\n#{1,3}|\Z)', "header"),                    # ### Заголовок
                (r'^\s*\[[ x]\]\s+(.+?)(?=\n\s*\[[ x]\]|\Z)', "checkbox"),         # [ ] [x]
            ]
            for pattern, name in patterns:
                matches = re.findall(pattern, planner_output, re.MULTILINE | re.DOTALL)
                if len(matches) >= 2:
                    tasks = [t.strip() for t in matches if len(t.strip()) > 10]
                    self._log(f"  📋 Распознан формат '{name}': {len(tasks)} задач")
                    break
        elif separator_mode == "numbered":
            matches = re.findall(r'^\s*\d+[\.\)]\s+(.+?)(?=\n\s*\d+[\.\)]|\Z)', planner_output, re.MULTILINE | re.DOTALL)
            tasks = [t.strip() for t in matches if len(t.strip()) > 10]
        elif separator_mode == "bullet":
            matches = re.findall(r'^\s*[-*•]\s+(.+?)(?=\n\s*[-*•]|\Z)', planner_output, re.MULTILINE | re.DOTALL)
            tasks = [t.strip() for t in matches if len(t.strip()) > 10]
        elif separator_mode == "header":
            matches = re.findall(r'^#{1,3}\s+(.+?)(?=\n#{1,3}|\Z)', planner_output, re.MULTILINE | re.DOTALL)
            tasks = [t.strip() for t in matches if len(t.strip()) > 10]
        elif separator_mode == "regex":
            custom_regex = getattr(node, 'planner_task_regex', r'^\s*[-*]\s+(.+?)(?=\n\s*[-*]|\Z)')
            try:
                matches = re.findall(custom_regex, planner_output, re.MULTILINE | re.DOTALL)
                tasks = [t.strip() for t in matches if len(t.strip()) > 10]
            except re.error as e:
                self._log(f"  ⚠️ Ошибка regex: {e}")
        
        # Фоллбэк: разбиваем по пустым строкам
        if not tasks:
            blocks = [b.strip() for b in re.split(r'\n\s*\n', planner_output) if len(b.strip()) > 20]
            tasks = blocks[:10]  # Максимум 10 задач
            self._log(f"  📋 Разбито по параграфам: {len(tasks)} задач")
        
        if len(tasks) <= 1:
            self._log("  📋 Только 1 задача, выполняю как обычно")
            return await self._exec_browser_agent_single(node, timeout)
        
        self._log(f"  📋 Всего задач для выполнения: {len(tasks)}")
        
        # === ВЫПОЛНЕНИЕ ЗАДАЧ ===
        all_results = []
        total_actions = 0
        delay = getattr(node, 'delay_between_tasks', 0.5)
        stop_on_error = getattr(node, 'stop_on_task_error', False)
        
        for i, task in enumerate(tasks, 1):
            if self._stop_requested:
                self._log("  ⏹ Остановлено пользователем")
                break
            
            task_preview = task.replace('\n', ' ')[:70]
            self._log(f"\n  🔷 [{i}/{len(tasks)}] {task_preview}...")
            self.signals.node_streaming.emit(node.id, f"\n{'='*50}\n🔷 Задача {i}/{len(tasks)}\n{'='*50}\n")
            
            # Создаём временный узел с этой задачей
            from services.agent_models import AgentNode, AgentType
            temp_node = AgentNode(
                id=f"{node.id}_task_{i}",
                name=f"Browser Task {i}/{len(tasks)}",
                agent_type=AgentType.BROWSER_AGENT,
                system_prompt=node.system_prompt,
                user_prompt_template=task,
                browser_instance_var=node.browser_instance_var,
                dom_max_tokens=node.dom_max_tokens,
                screenshot_verify=node.screenshot_verify,
                screenshot_diff_threshold=node.screenshot_diff_threshold,
                browser_planner_node_id="",  # Уже получили контекст
            )
            
            try:
                result = await self._exec_browser_agent_single(temp_node, timeout)
                
                actions_count = self.execution_context.get('browser_agent_actions_count', 0)
                total_actions += actions_count
                
                all_results.append({
                    "task": i,
                    "preview": task_preview,
                    "actions": actions_count,
                    "success": True
                })
                
                self._log(f"  ✅ [{i}/{len(tasks)}] Выполнено ({actions_count} действий)")
                
            except Exception as e:
                self._log(f"  ❌ [{i}/{len(tasks)}] Ошибка: {e}")
                all_results.append({
                    "task": i,
                    "preview": task_preview,
                    "error": str(e),
                    "success": False
                })
                
                if stop_on_error:
                    self._log(f"  🛑 Остановка по ошибке (stop_on_task_error=True)")
                    break
            
            # Пауза между задачами
            if i < len(tasks) and delay > 0:
                await asyncio.sleep(delay)
        
        # Формируем отчёт
        successful = sum(1 for r in all_results if r['success'])
        report = f"""📋 Предобработка плана: {successful}/{len(all_results)} успешно
Всего действий в браузере: {total_actions}

Детали по задачам:
"""
        for r in all_results:
            icon = "✅" if r['success'] else "❌"
            info = f"({r.get('actions', 0)} действий)" if r['success'] else f"Ошибка: {r.get('error', 'unknown')[:30]}"
            report += f"\n{icon} [{r['task']}] {r['preview'][:50]}... {info}"
        
        self._context["_planner_tasks_results"] = all_results
        self._context["_planner_tasks_total"] = len(tasks)
        self._context["_planner_tasks_successful"] = successful
        self._context["_planner_total_actions"] = total_actions
        
        return report
    
    # ── Helpers ────────────────────────────────────────────────
    
    def _scan_disk_files(self) -> list[str]:
        """Сканировать файлы на диске в рабочей папке."""
        disk_files = []
        try:
            root = self._tool_executor._root
            for dir_path, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for f in files:
                    disk_files.append(os.path.relpath(os.path.join(dir_path, f), root))
        except Exception:
            pass
        return disk_files
    
    def _sync_table_to_metadata(self, table_name: str, table_data: list):
        """Синхронизировать таблицу из контекста в metadata workflow для отображения в UI."""
        if not table_name or not self._workflow:
            return
        
        try:
            # Получаем или создаем metadata
            meta = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(meta, str):
                try:
                    import json as _json
                    meta = _json.loads(meta) if meta.strip() else {}
                except Exception:
                    meta = {}
            
            # Обновляем project_tables
            project_tables = meta.get('project_tables', [])
            
            # Определяем колонки из данных (все колонки, не только первую)
            columns = []
            if table_data and len(table_data) > 0:
                # Берем максимальное количество колонок из всех строк
                max_cols = max(len(row) for row in table_data) if table_data else 0
                # Генерируем имена колонок A, B, C... или используем индексы
                columns = [f"Col {i}" for i in range(max_cols)]
                # Если есть заголовок в первой строке - используем его
                if table_data and len(table_data[0]) > 0:
                    first_row = table_data[0]
                    if all(isinstance(c, str) for c in first_row):
                        columns = [str(c) for c in first_row] + columns[len(first_row):]
            
            # Ищем существующую таблицу
            found = False
            for pt in project_tables:
                if isinstance(pt, dict) and pt.get('name') == table_name:
                    pt['rows'] = list(table_data)
                    pt['columns'] = columns  # <-- Сохраняем все колонки
                    found = True
                    break
            
            # Если не нашли — добавляем новую
            if not found:
                project_tables.append({
                    'name': table_name,
                    'rows': list(table_data),
                    'columns': columns,  # <-- Сохраняем все колонки
                    'load_mode': 'static'
                })
            
            meta['project_tables'] = project_tables
            self._workflow.metadata = meta
            
            self._log(f"  📊 Синхронизировано в metadata: '{table_name}' ({len(table_data)} строк, {len(columns)} колонок)")
            self.signals.list_table_updated.emit('table', table_name, len(table_data))
            
        except Exception as e:
            self._log(f"  ⚠ Ошибка синхронизации таблицы в metadata: {e}")
            
    def _sync_list_to_metadata(self, list_name: str, list_data: list):
        """Синхронизировать список из контекста в metadata workflow для отображения в UI."""
        if not list_name or not self._workflow:
            return
        
        try:
            meta = getattr(self._workflow, 'metadata', None) or {}
            if isinstance(meta, str):
                try:
                    import json as _json
                    meta = _json.loads(meta) if meta.strip() else {}
                except Exception:
                    meta = {}
            
            project_lists = meta.get('project_lists', [])
            
            found = False
            for pl in project_lists:
                if isinstance(pl, dict) and pl.get('name') == list_name:
                    pl['items'] = list(list_data)
                    found = True
                    break
            
            if not found:
                project_lists.append({
                    'name': list_name,
                    'items': list(list_data),
                    'load_mode': 'static'
                })
            
            meta['project_lists'] = project_lists
            self._workflow.metadata = meta
            
            self._log(f"  📃 Синхронизировано в metadata: '{list_name}' ({len(list_data)} элементов)")
            self.signals.list_table_updated.emit('list', list_name, len(list_data))
            
        except Exception as e:
            self._log(f"  ⚠ Ошибка синхронизации списка в metadata: {e}")
    
    def _sync_var_to_project(self, var_name: str, value: str):
        """Синхронизировать переменную контекста с project_variables."""
        if not var_name or self._project_variables is None:
            return
        if not isinstance(self._project_variables, dict):
            return
        
        if var_name in self._project_variables:
            if isinstance(self._project_variables[var_name], dict):
                self._project_variables[var_name]['value'] = str(value)
            else:
                self._project_variables[var_name] = str(value)
            self._log(f"  📝 Синхронизировано с проектом: {var_name} = {str(value)[:60]}")
        else:
            # Создаём с полной dict-структурой, как Variable Set
            self._project_variables[var_name] = {
                'value': str(value),
                'default': '',
                'type': 'string'
            }
            self._log(f"  📝 Создана новая переменная: {var_name} = {str(value)[:60]}")
        
        if hasattr(self, 'signals') and hasattr(self.signals, 'variable_updated'):
            self.signals.variable_updated.emit(var_name, str(value))
    
    def _do_backup(self, label: str):
        """Бэкап рабочей папки перед выполнением узла."""
        import shutil
        if not self._project_root or not os.path.exists(self._project_root):
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = label.replace(" ", "_").replace("/", "_")[:30]
        backup_dir = os.path.join(self._project_root, ".backups", f"{safe_label}_{ts}")
        try:
            os.makedirs(backup_dir, exist_ok=True)
            for item in os.listdir(self._project_root):
                if item == ".backups":
                    continue
                src = os.path.join(self._project_root, item)
                dst = os.path.join(backup_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            self._log(f"  💾 Бэкап: {backup_dir}")
        except Exception as e:
            self._log(f"  ⚠ Бэкап не удался: {e}")
    
    def _wait_for_resume(self):
        """Block until resume() is called."""
        self._mutex.lock()
        while self._is_paused and not self._stop_requested:
            self._pause_condition.wait(self._mutex)
        self._mutex.unlock()
    
    def _close_browser_if_needed(self):
        """Закрыть браузер по завершении workflow если флаг close_browser_on_finish=True."""
        try:
            if not self._workflow:
                return
            if not getattr(self._workflow, 'close_browser_on_finish', False):
                return

            iid = self._context.get('browser_instance_id', '')
            pbm = getattr(self, '_project_browser_manager', None)
            if not iid and not pbm:
                return

            self._log("🔴 Закрываю браузер по завершении workflow...")

            # Через ProjectBrowserManager (приоритет)
            if pbm and iid:
                try:
                    inst = pbm.get_instance(iid)
                    if inst and getattr(inst, 'is_running', False):
                        inst.close()
                        self._log(f"  ✅ Браузер {iid} закрыт")
                        return
                except Exception as e:
                    self._log(f"  ⚠ pbm close error: {e}")

            # Через BrowserManager (глобальный fallback)
            try:
                from constructor.browser_module import BrowserManager
                mgr = BrowserManager.get()
                if iid:
                    inst = mgr.get_instance(iid)
                    if inst and getattr(inst, 'is_running', False):
                        inst.close()
                        self._log(f"  ✅ Браузер {iid} закрыт (fallback)")
                else:
                    # Закрыть первый попавшийся работающий
                    for inst in mgr.all_instances().values():
                        if getattr(inst, 'is_running', False):
                            inst.close()
                            self._log("  ✅ Браузер закрыт (fallback, первый активный)")
                            break
            except Exception as e:
                self._log(f"  ⚠ BrowserManager close error: {e}")
        except Exception as e:
            self._log(f"  ⚠ _close_browser_if_needed error: {e}")
    
    def _log(self, msg: str):
        self.signals.log.emit(msg)

    @property
    def results(self) -> dict[str, NodeResult]:
        return self._results

    @property
    def context(self) -> dict:
        return self._context